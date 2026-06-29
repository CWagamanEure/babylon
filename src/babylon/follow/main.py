"""Live entrypoint glue for the forward copy-trade paper experiment.

Instantiates the real adapters (InfoClient, WebSocketFeed, RestFillsProvider), loads the
candidate pool / universe / candle lookups, LOCKS the ExperimentConfig at T0 = deploy, and
runs LiveFollowSystem. T0's train window is the trailing `train_days`.

Candidate pool defaults to the BROAD study pool (not the 281 in-sample winners): re-ranking
within pre-selected winners is survivorship-tainted, and the gated top−pool-mean control
only discriminates against a broad pool. Override with --top-quintile-only or --candidates.

Adapters are injectable so the orchestration is testable without the network; `--dry-run`
prefetches + does the initial roll (registers the manifest, selects a roster) WITHOUT
starting the loop — the pre-arm smoke check.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import polars as pl

import babylon.follow.measure as _measure_mod
from babylon.config import Network
from babylon.exchange.constants import endpoints_for
from babylon.exchange.rest import InfoClient
from babylon.exchange.websocket import WebSocketFeed
from babylon.follow.candles_source import fetch_lookups
from babylon.follow.experiment import ExperimentConfig, Registry
from babylon.follow.fills_source import ParquetFillsProvider, RestFillsProvider
from babylon.follow.followable import load_price_lookups
from babylon.follow.live import LiveFollowSystem, wall_ms
from babylon.follow.selection import SelectionAdapter
from babylon.logging import get_logger

log = get_logger("follow.main")
_DAY_MS = 86_400_000
_DEFAULT = object()   # sentinel: "refresh_lookups not specified" vs explicit None


def universe_hash(universe: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(universe)).encode()).hexdigest()[:16]


def analysis_hash() -> str:
    """Pre-committed analysis identity = the measurement harness source hash."""
    return hashlib.sha256(Path(_measure_mod.__file__).read_bytes()).hexdigest()[:16]


def locked_config(universe: list[str], *, execution: str = "retail") -> ExperimentConfig:
    """The FROZEN forward-experiment config (the approved numbers). Bound to the universe
    via universe_hash so a universe change changes every run_id."""
    return ExperimentConfig(
        execution=execution, universe_hash=universe_hash(universe),  # type: ignore[arg-type]
        eligible_pool="broad_study_pool", train_days=30, follow_days=14, roll_cadence_days=14,
        min_hold_ms=3_600_000, min_positions=6, beta=1.245, gross_target=1.0,
        max_coin_frac=0.08, max_wallet_frac=0.05, also_run_uncapped=True, lag_bucket_ms=60_000,
        fee_bps=4.5, impact_bps=6.0, max_depth_frac=0.25, target_notional_usd=1_000.0,
        primary_control="pool_mean", secondary_controls=("random", "sign_shuffle"),
        min_n_nominal=1500, min_effective_n=120, horizon_cap_days=300, mar_bps=8.0,
        maxdd_bound=-0.25, max_single_contrib_frac=0.20, cost_floor_bps=15.0)


def load_candidates(path: Path, *, top_quintile_only: bool = False) -> list[str]:
    df = pl.read_csv(path)
    if top_quintile_only and "top_quintile" in df.columns:
        df = df.filter(pl.col("top_quintile"))
    col = "w" if "w" in df.columns else df.columns[0]
    return [str(w) for w in df[col].to_list()]


def load_universe(path: Path) -> list[str]:
    return [s for ln in path.read_text().splitlines()
            if (s := ln.strip()) and not s.startswith("#")]   # skip blanks + # comments


async def run_live(
    *, candidates: list[str], universe: list[str], registry_path: Path, checkpoint_path: Path,
    candles_dir: Path | None = None, network: Network = Network.MAINNET,
    budget_usd: float = 1000.0, execution: str = "retail", dry_run: bool = False,
    config: ExperimentConfig | None = None, t0_ms: int | None = None,
    max_roster_size: int | None = None,
    lookups: dict[str, tuple[Any, Any]] | None = None, info: object = None, feed: object = None,
    provider: object = None,
    prefetch: Callable[[list[str], int, int], Awaitable[None]] | None = None,
    refresh_lookups: object = _DEFAULT, **run_kw: object,
) -> LiveFollowSystem:
    """Orchestrate: lock config → ready roll-time data (fresh candles + fills) → build
    (initial roll registers the manifest) → run. Adapters injectable for tests; real ones
    built by default. A restart resumes the committed roster (no re-roll, no data fetch)."""
    ep = endpoints_for(network)
    config = config or locked_config(universe, execution=execution)
    config.validate()
    info = info or InfoClient(ep.rest)
    feed = feed or WebSocketFeed(ep.ws)
    provider = provider or RestFillsProvider(info)  # type: ignore[arg-type]
    if prefetch is None and isinstance(provider, RestFillsProvider):
        prefetch = provider.prefetch
    # candle lookups: static (tests / candles_dir) or fetched fresh per roll (live default)
    if refresh_lookups is _DEFAULT:
        refresh_lookups = None if lookups is not None else \
            (lambda u, s, e: fetch_lookups(info, u, s, e))  # type: ignore[arg-type]
    if lookups is None and refresh_lookups is None and candles_dir is not None:
        lookups = load_price_lookups(candles_dir)
    adapter = SelectionAdapter(provider, universe=set(universe), lookups=lookups or {}, config=config)  # type: ignore[arg-type]
    train_ms = config.train_days * _DAY_MS

    async def prepare(t0: int) -> None:
        if refresh_lookups is not None:
            log.info("live.refresh_candles", n=len(universe), t0=t0)
            adapter.set_lookups(await refresh_lookups(universe, t0 - train_ms, t0))  # type: ignore[operator]
        if prefetch is not None:
            log.info("live.prefetch", n_candidates=len(candidates), t0=t0)
            await prefetch(candidates, t0 - train_ms, t0)
        adapter.reset()

    async with info:  # type: ignore[attr-defined]
        t0 = t0_ms if t0_ms is not None else wall_ms()
        resuming = Registry(registry_path).latest() is not None
        if not resuming:                                  # a restart resumes the committed roster
            await prepare(t0)
        system = LiveFollowSystem.build(
            config=config, candidates=candidates, universe=universe, source=info, feed=feed,  # type: ignore[arg-type]
            returns_fn=adapter.returns_fn, cutoff_fn=adapter.cutoff_fn, t0_ms=t0,
            budget_usd=budget_usd, registry_path=registry_path, checkpoint_path=checkpoint_path,
            analysis_script_hash=analysis_hash(), prepare=prepare, max_roster_size=max_roster_size)
        log.info("live.built", run_id=system.run_id, roster=len(system.runner._weights),  # noqa: SLF001
                 dry_run=dry_run)
        if dry_run:
            return system
        await system.run(**run_kw)  # type: ignore[arg-type]
        return system


def main() -> None:
    ap = argparse.ArgumentParser(description="Forward copy-trade paper experiment")
    ap.add_argument("--candidates", type=Path, default=Path("data/follow/long_hold_wallets.csv"))
    ap.add_argument("--top-quintile-only", action="store_true",
                    help="rank only the 281 in-sample winners (survivorship-tainted; NOT default)")
    ap.add_argument("--universe", type=Path, default=Path("data/follow/alt_universe.txt"))
    ap.add_argument("--candles", type=Path, default=Path("data/follow/candles"))
    ap.add_argument("--fills-dir", type=Path, default=None,
                    help="rank from LOCAL fills parquets + local candles (instant roll, no "
                         "REST prefetch). Live positions + books are still real-time.")
    ap.add_argument("--state-dir", type=Path, default=Path("data/follow/live"))
    ap.add_argument("--max-roster", type=int, default=50,
                    help="cap the roster to the top-N by Kelly weight so it can be polled in "
                         "real time under the rate limit (0 = no cap)")
    ap.add_argument("--budget", type=float, default=1000.0)
    ap.add_argument("--testnet", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="prepare + initial roll only (pre-arm smoke), do not trade")
    a = ap.parse_args()
    a.state_dir.mkdir(parents=True, exist_ok=True)
    candidates = load_candidates(a.candidates, top_quintile_only=a.top_quintile_only)
    universe = load_universe(a.universe)
    # local-selection mode: parquet fills + static local candles ⇒ no REST prefetch/refetch
    local: dict[str, Any] = dict(provider=ParquetFillsProvider(a.fills_dir), refresh_lookups=None) \
        if a.fills_dir else {}
    log.info("live.start", n_candidates=len(candidates), n_universe=len(universe),
             dry_run=a.dry_run, testnet=a.testnet, local_fills=bool(a.fills_dir))
    asyncio.run(run_live(
        candidates=candidates, universe=universe, candles_dir=a.candles,
        network=Network.TESTNET if a.testnet else Network.MAINNET,
        registry_path=a.state_dir / "registry.jsonl",
        checkpoint_path=a.state_dir / "checkpoint.json", budget_usd=a.budget,
        max_roster_size=a.max_roster or None, dry_run=a.dry_run, **local))


if __name__ == "__main__":
    main()
