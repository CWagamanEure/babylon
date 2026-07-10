"""Paper follower for the ROLLING WALK-FORWARD basket (the L=6 monthly re-discovery process,
research/data/rolling_wf.py). Loads data/derived/rolling_wf/live_basket.parquet — (wallet, coin,
horizon) triples — and paper-copies each basket wallet's position OPENS in ITS basket coin:

  open detected (WalletWatcher, ~21s sweep over 20 wallets)
    → tranche enters at detection + entry_lag (default 2 min — the copy-delay decay curve showed
      1–2 min costs ~nothing; audits 2026-07-09)
    → holds the row's FROZEN horizon (per-tranche; 1h/2h/4h/8h)
    → exits on ITS OWN CLOCK, blind to the wallet's exit (mirroring trader exits KILLS the edge —
      the hold≥horizon subset measured +5.5bp p=.49; the early-exit subset carried it all).

Estimand parity with the backtest (research/data/rolling_wf.py):
  - NO event-level taker/TWAP filter (those were WALLET-level discovery eligibility);
  - leading opens are KEPT (epoch 2; skip_leading=False — per-poll batching flags true
    flat-opens as leading; inherited positions never emit opens live, see build());
  - flat notional per tranche (the backtest is equal-weight per wallet-day).

Refresh: monthly, run `python -m research.data.rolling_wf live` on the updated tape, redeploy the
new basket file, restart this service (open tranches keep their clocks via the checkpoint).
PAPER ONLY — PaperExecutor, no signing code exists. Verdict authority: the prosecution audit
labeled the backtest 'suggestive, regime-concentrated, n=5 months' — this run IS the adjudicating
forward test, not a capital deployment.

    python -m babylon.follow.basket_main --dry-run          # load + manifest + smoke, no loop
    python -m babylon.follow.basket_main                    # run
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

from babylon.config import Network
from babylon.exchange.constants import endpoints_for
from babylon.exchange.rest import InfoClient
from babylon.exchange.websocket import WebSocketFeed
from babylon.execution.paper import PaperExecutor
from babylon.follow.gate_feed import RealizedJournal
from babylon.follow.harvest import HarvestLedger
from babylon.follow.harvest_runner import HarvestRunner
from babylon.follow.live import mono_ms, wall_ms
from babylon.follow.runner import attach_l2_feed
from babylon.follow.watcher import WalletWatcher
from babylon.logging import get_logger

log = get_logger("follow.basket")

HORIZON_MS = {"1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000}


def load_basket(path: Path) -> tuple[dict[tuple[str, str], int], list[str], list[str], str]:
    """live_basket.parquet -> ({(wallet, coin): horizon_ms}, roster wallets, universe coins,
    sha256 of the file — the frozen-roster identity recorded in the manifest)."""
    rows = pq.read_table(path).to_pylist()
    basket: dict[tuple[str, str], int] = {}
    for r in rows:
        h = str(r["horizon"])
        if h not in HORIZON_MS:
            raise SystemExit(f"unknown horizon {h!r} in basket row {r}")
        basket[(str(r["wallet"]), str(r["coin"]))] = HORIZON_MS[h]
    roster = sorted({w for (w, _c) in basket})
    universe = sorted({c for (_w, c) in basket})
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return basket, roster, universe, digest


def build(
    a: argparse.Namespace, info: InfoClient, feed: WebSocketFeed,
) -> tuple[HarvestRunner, RealizedJournal, Path]:
    basket, roster, universe, digest = load_basket(a.basket)
    log.info("basket.loaded", n_pairs=len(basket), n_wallets=len(roster),
             coins=universe, sha=digest)
    watcher = WalletWatcher(info, roster)
    executor = PaperExecutor(taker_fee_bps=a.fee_bps, mode="retail",
                             impact_bps=a.impact_bps, max_depth_frac=0.25)
    ledger = HarvestLedger(
        entry_lag_ms=a.entry_lag_s * 1000, horizon_ms=max(HORIZON_MS.values()),  # fallback only
        # measurement-mode caps: generous so a busy day doesn't bias WHICH opens harvest
        max_coin_notional=a.tranche_usd * 40, max_gross_notional=a.tranche_usd * 100,
        min_tranche_notional=1.0, max_entry_lag_ms=30 * 60_000)
    runner = HarvestRunner(
        ledger, {w: a.tranche_usd for w in roster}, executor, universe=set(universe),
        watcher=watcher, roster=roster, budget_usd=a.budget,
        # estimand parity: NO event-level taker/TWAP filter. skip_leading MUST be False live:
        # per-poll batching makes nearly every true flat->open the first fill of its batch
        # (is_leading=True), so skipping leading opens drops almost ALL entries (verified live
        # 2026-07-09: 539 basket-coin fills, 0 registered). The inherited_basis exclusion is
        # AUTOMATIC live — a position opened before observation never emits an open event
        # (startPosition-anchored state machine only emits on an observed zero-cross or a
        # batch that starts provably flat).
        taker_only=False, conviction_only=False, basket=basket, skip_leading=False)
    watcher.set_opens_sink(runner.ingest_opens)
    watcher.seed_cursors(wall_ms())          # forward only — never replay history as fresh opens
    a.state_dir.mkdir(parents=True, exist_ok=True)
    ckpt = a.state_dir / "checkpoint.json"
    if ckpt.exists():
        runner.from_state(json.loads(ckpt.read_text()))   # restores watcher cursors + open clocks
        # REFRESH SEAM (audit F2): from_state wholesale-replaces the watcher's cursor/pos maps with
        # the OLD checkpoint's keys — wallets NEW to this basket would KeyError on every poll and
        # never register an open. update_roster seeds new wallets (cursor=now), keeps continuing
        # ones, purges dropped ones.
        watcher.update_roster(roster, since_ms=wall_ms())
        log.info("basket.resumed", checkpoint=str(ckpt))
    # manifest: the frozen roster identity + config, written BEFORE any trade (pre-reg hygiene)
    manifest = {
        "basket_sha": digest, "basket_file": str(a.basket), "n_pairs": len(basket),
        "pairs": [{"wallet": w, "coin": c, "horizon_ms": h} for (w, c), h in sorted(basket.items())],
        "entry_lag_s": a.entry_lag_s, "tranche_usd": a.tranche_usd,
        "fee_bps": a.fee_bps, "impact_bps": a.impact_bps, "started_wall_ms": wall_ms(),
    }
    mpath = a.state_dir / "basket_manifest.jsonl"
    with mpath.open("a") as f:
        f.write(json.dumps(manifest) + "\n")
    journal = RealizedJournal(a.state_dir / "realized.jsonl")
    return runner, journal, ckpt


async def run(a: argparse.Namespace) -> None:
    ep = endpoints_for(Network.MAINNET)
    info = InfoClient(ep.rest)
    feed = WebSocketFeed(ep.ws)
    async with info:                       # the REST session lives for the whole run (as main.py)
        runner, journal, ckpt = build(a, info, feed)
        if a.dry_run:
            log.info("basket.dry_run_ok", roster=runner.n_roster)
            return
        stop = asyncio.Event()

        async def _drive() -> None:
            try:
                await runner.run(wall_ms, mono_ms, tick_s=2.0, checkpoint_path=ckpt,
                                 checkpoint_every=30, on_realized=journal.append, stop=stop)
            finally:
                feed.stop()
                stop.set()

        # subscribe books for the basket universe PLUS any coins carried by restored open
        # tranches / positions (audit F3 — else a refresh that drops a coin starves its exits)
        attach_l2_feed(runner, feed, runner.feed_universe())
        await asyncio.gather(feed.run(), _drive())


def main() -> None:
    ap = argparse.ArgumentParser(description="Paper follower for the rolling-WF basket")
    ap.add_argument("--basket", type=Path,
                    default=Path("data/derived/rolling_wf/live_basket.parquet"))
    ap.add_argument("--state-dir", type=Path, default=Path("data/follow/basket_live"))
    ap.add_argument("--budget", type=float, default=1000.0)
    ap.add_argument("--tranche-usd", type=float, default=50.0,
                    help="flat notional per tranche (backtest = equal-weight per wallet-day)")
    ap.add_argument("--entry-lag-s", type=int, default=120,
                    help="copy delay after detection (decay curve: 1-2min ~free)")
    ap.add_argument("--fee-bps", type=float, default=4.5,
                    help="taker fee folded into paper fills (base tier 4.5bp/side)")
    ap.add_argument("--impact-bps", type=float, default=1.0)
    ap.add_argument("--dry-run", action="store_true", help="load + manifest + smoke, no loop")
    a = ap.parse_args()
    asyncio.run(run(a))


if __name__ == "__main__":
    main()
