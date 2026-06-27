"""Babylon command-line interface.

Data-foundation commands for now:

    babylon mids                     # snapshot of all mid prices (connectivity check)
    babylon book BTC                 # top of the order book for one coin
    babylon stream --coin BTC        # live trade prints to the console
    babylon record --coin BTC -c ETH # capture trades + book to Parquet
    babylon backfill --coin BTC --start 20260601  # historical L2 from S3
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable, Coroutine
from decimal import Decimal
from typing import Any

import aiohttp
import numpy as np
import typer
from rich.console import Console
from rich.table import Table

from babylon.config import get_settings
from babylon.data.archive import HyperliquidArchive, daterange
from babylon.data.models import Trade, TradeSide
from babylon.data.recorder import Recorder
from babylon.data.store import ParquetStore
from babylon.engine.clock import RealClock
from babylon.engine.context import MarketView
from babylon.engine.engine import Engine
from babylon.exchange.constants import endpoints_for
from babylon.exchange.rest import InfoClient
from babylon.exchange.websocket import Subscription, WebSocketFeed
from babylon.execution.paper import PaperExecutor
from babylon.logging import configure_logging, get_logger
from babylon.portfolio.ledger import Ledger
from babylon.portfolio.reconcile import Reconciler
from babylon.risk.manager import RiskManager
from babylon.risk.net import NetRiskManager
from babylon.sizing.sizer import Sizer
from babylon.strategy.examples.ma_crossover import MACrossover

app = typer.Typer(help="Babylon — quantitative trading on Hyperliquid", no_args_is_help=True)
console = Console()
log = get_logger("cli")

# Above this many coin-hours, backfill demands explicit --yes (requester-pays cost).
_BACKFILL_CONFIRM_THRESHOLD = 48
_APPROX_MB_PER_COIN_HOUR = 1.4
_FLUSH_INTERVAL_S = 10.0


def _bootstrap() -> None:
    s = get_settings()
    configure_logging(level=s.log_level, console=s.log_console)
    if s.is_mainnet and s.can_trade:
        log.warning("ARMED ON MAINNET — orders will use real funds", network="mainnet")


def _run_async(factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Run a one-shot async command, turning network errors into clean exits."""
    try:
        asyncio.run(factory())
    except (aiohttp.ClientError, TimeoutError, OSError) as exc:
        console.print(f"[red]Network/API error:[/red] {exc}")
        raise typer.Exit(1) from exc


@app.command()
def mids(top: int = typer.Option(20, help="Show only the N highest-priced coins")) -> None:
    """Fetch a snapshot of all mid prices — quickest connectivity check."""
    _bootstrap()
    s = get_settings()
    ep = endpoints_for(s.network)

    async def run() -> None:
        async with InfoClient(ep.rest) as info:
            all_mids = await info.all_mids()
        rows = sorted(all_mids.mids.items(), key=lambda kv: kv[1], reverse=True)[:top]
        table = Table(title=f"All mids ({s.network.value})")
        table.add_column("coin")
        table.add_column("mid", justify="right")
        for coin, px in rows:
            table.add_row(coin, f"{px}")
        console.print(table)

    _run_async(run)


@app.command()
def book(coin: str) -> None:
    """Print the current top of the order book for one coin."""
    _bootstrap()
    s = get_settings()
    ep = endpoints_for(s.network)

    async def run() -> None:
        async with InfoClient(ep.rest) as info:
            b = await info.l2_book(coin)
        console.print(
            f"[bold]{b.coin}[/bold]  bid [green]{b.best_bid}[/green]  "
            f"ask [red]{b.best_ask}[/red]  mid {b.mid}"
        )

    _run_async(run)


@app.command()
def stream(coin: list[str] = typer.Option(..., "--coin", "-c", help="Coin(s) to stream")) -> None:
    """Stream live trade prints to the console."""
    _bootstrap()
    s = get_settings()
    ep = endpoints_for(s.network)
    feed = WebSocketFeed(url=ep.ws)

    async def on_trades(data: list[dict[str, Any]]) -> None:
        for raw in data:
            t = Trade.from_ws(raw)
            color = "green" if t.side is TradeSide.BUY else "red"
            console.print(f"[{color}]{t.coin:>6} {t.side.name} {t.sz} @ {t.px}[/{color}]")

    for c in coin:
        feed.subscribe(Subscription(type="trades", coin=c))
    feed.on("trades", on_trades)
    _run_feed(feed)


@app.command()
def record(
    coin: list[str] = typer.Option(..., "--coin", "-c", help="Coin(s) to record"),
    bbo: bool = typer.Option(False, help="Also capture BBO ticks"),
) -> None:
    """Capture trades + order book to Parquet under BABYLON_DATA_DIR."""
    _bootstrap()
    s = get_settings()
    ep = endpoints_for(s.network)
    feed = WebSocketFeed(url=ep.ws)
    store = ParquetStore(s.data_dir)
    recorder = Recorder(feed, store)
    for c in coin:
        recorder.record_coin(c, book=True, bbo=bbo)
    log.info("record.start", coins=coin, data_dir=str(s.data_dir), network=s.network.value)
    _run_feed(feed, store=store)


@app.command()
def backfill(
    coin: list[str] = typer.Option(..., "--coin", "-c", help="Coin(s) to backfill"),
    start: str = typer.Option(..., help="Start date YYYYMMDD (inclusive)"),
    end: str = typer.Option("", help="End date YYYYMMDD (inclusive); defaults to start"),
    hour: list[int] = typer.Option([], "--hour", help="Specific hour(s) 0-23; default all 24"),
    levels: int = typer.Option(20, help="Max book levels to persist per side"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost confirmation"),
) -> None:
    """Backfill historical L2 snapshots from Hyperliquid's S3 archive to Parquet.

    The archive is requester-pays: this downloads from AWS and you pay egress.
    """
    _bootstrap()
    s = get_settings()
    end = end or start
    try:
        days = list(daterange(start, end))  # validates format + ordering
    except ValueError as exc:
        console.print(f"[red]Invalid date range:[/red] {exc}")
        raise typer.Exit(1) from exc
    if any(h < 0 or h > 23 for h in hour):
        console.print("[red]--hour values must be 0-23[/red]")
        raise typer.Exit(1)
    hours = list(range(24)) if not hour else sorted(set(hour))

    coin_hours = len(days) * len(hours) * len(coin)
    if coin_hours > _BACKFILL_CONFIRM_THRESHOLD and not yes:
        est_mb = coin_hours * _APPROX_MB_PER_COIN_HOUR
        console.print(
            f"[yellow]This will fetch ~{coin_hours} coin-hours (~{est_mb:.0f} MB) from a "
            f"requester-pays bucket — you pay egress.[/yellow]\n"
            f"Re-run with [bold]--yes[/bold] to proceed."
        )
        raise typer.Exit(1)

    store = ParquetStore(s.data_dir)
    archive = HyperliquidArchive()
    log.info("backfill.start", coins=coin, start=start, end=end, coin_hours=coin_hours)
    try:
        stats = archive.backfill_l2(store, coin, start, end, hours=hours, max_levels=levels)
    except Exception as exc:  # noqa: BLE001 — surface a clean message, flush what we have
        store.flush()
        console.print(f"[red]Backfill failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(
        f"[bold green]Backfill complete[/bold green]: {stats.snapshots} snapshots "
        f"across {stats.files} coin-hours ({stats.empty_hours} empty, "
        f"{stats.bad_lines} bad lines) → {s.data_dir}"
    )


@app.command()
def paper(
    coin: list[str] = typer.Option(..., "--coin", "-c", help="Coin(s) to trade"),
    equity: float = typer.Option(100_000.0, help="Starting paper equity (USDC)"),
    fast: int = typer.Option(10, help="Fast MA window"),
    slow: int = typer.Option(30, help="Slow MA window"),
    interval: float = typer.Option(2.0, help="Evaluation cadence (seconds)"),
    seed: int = typer.Option(0, help="RNG seed (reproducible sizing)"),
) -> None:
    """Run the MA-crossover toy strategy in PAPER mode on the live feed.

    No signing, no real orders — the full engine pipeline (sizing → risk → net
    risk → reconcile → paper fills → ledger) on real prices.
    """
    _bootstrap()
    s = get_settings()
    ep = endpoints_for(s.network)
    rng = np.random.default_rng(seed)
    feed = WebSocketFeed(url=ep.ws)
    strategies = [MACrossover(c, fast=fast, slow=slow) for c in coin]
    budgets = {st.name: 1.0 / len(strategies) for st in strategies}
    engine = Engine(
        feed=feed,
        market=MarketView(),
        strategies=strategies,
        sizer=Sizer(rng),
        risk=RiskManager(),
        net_risk=NetRiskManager(),
        reconciler=Reconciler(),
        executor=PaperExecutor(),
        ledger=Ledger(Decimal(str(equity))),
        clock=RealClock(),
        budgets=budgets,
        rng=rng,
        interval_s=interval,
    )
    log.info("paper.start", coins=coin, equity=equity, network=s.network.value)
    _run_engine(engine)


def _run_engine(engine: Engine) -> None:
    async def run() -> None:
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(engine.run())
        presses = {"n": 0}

        def on_signal() -> None:
            presses["n"] += 1
            if presses["n"] == 1:
                log.info("shutdown.graceful")
                engine.stop()
            else:
                task.cancel()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, on_signal)
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())


def _run_feed(feed: WebSocketFeed, store: ParquetStore | None = None) -> None:
    """Drive a feed to completion with graceful (1st Ctrl+C) and forced (2nd)
    shutdown, plus a periodic off-loop flush when a store is attached."""

    async def periodic_flush() -> None:
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL_S)
            await asyncio.to_thread(store.flush)  # type: ignore[union-attr]

    async def run() -> None:
        loop = asyncio.get_running_loop()
        feed_task = asyncio.create_task(feed.run())
        presses = {"n": 0}

        def on_signal() -> None:
            presses["n"] += 1
            if presses["n"] == 1:
                log.info("shutdown.graceful")
                feed.stop()
            else:
                log.warning("shutdown.forced")
                feed_task.cancel()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, on_signal)

        flusher = asyncio.create_task(periodic_flush()) if store is not None else None
        try:
            await feed_task
        except asyncio.CancelledError:
            pass
        finally:
            if flusher is not None:
                flusher.cancel()
            if store is not None:
                await asyncio.to_thread(store.flush)

    asyncio.run(run())


if __name__ == "__main__":
    app()
