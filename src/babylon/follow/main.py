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
from babylon.follow.skill import basket_from_series
from babylon.logging import get_logger

log = get_logger("follow.main")
_DAY_MS = 86_400_000
_DEFAULT = object()   # sentinel: "refresh_lookups not specified" vs explicit None


def universe_hash(universe: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(universe)).encode()).hexdigest()[:16]


def analysis_hash() -> str:
    """Pre-committed analysis identity = the measurement harness source hash."""
    return hashlib.sha256(Path(_measure_mod.__file__).read_bytes()).hexdigest()[:16]


def locked_config(
    universe: list[str], *, execution: str = "retail", selection: str = "roundtrip",
) -> ExperimentConfig:
    """The FROZEN forward-experiment config (the approved numbers). Bound to the universe
    via universe_hash so a universe change changes every run_id.

    `selection="markout"` swaps in the VALIDATED fixed-horizon operating point
    (audit/EDGE_INVESTIGATION.md): per-entry 6 h markout, 15 min follower lag, neutralized,
    ranked by trimmed-mean. `selection="roundtrip"` (default) keeps the original directional
    round-trip Sortino rule. Both are pre-registered configs — pick one at deploy, not mid-run."""
    if selection not in ("roundtrip", "markout"):
        raise ValueError(f"selection must be 'roundtrip' or 'markout', got {selection!r}")
    markout = selection == "markout"
    return ExperimentConfig(
        execution=execution, universe_hash=universe_hash(universe),  # type: ignore[arg-type]
        eligible_pool="broad_study_pool", train_days=30, follow_days=14, roll_cadence_days=14,
        min_hold_ms=3_600_000,
        # markout: eligibility = ≥5 train OPENS (the validated `min_train`, the regime the 4/4-fold
        # OOS walk-forward blessed) — disposition-free, so NO raw-activity gate. round-trip: ≥20 raw
        # fills (the disposition-bias fix). The markout path gates on opens via select_roster.
        min_positions=5 if markout else 20, beta=1.245, gross_target=1.0,
        max_coin_frac=0.08, max_wallet_frac=0.05, also_run_uncapped=True,
        # markout: 15 min follower lag (vs 60 s); round-trip: 60 s
        lag_bucket_ms=900_000 if markout else 60_000,
        selection_signal="markout" if markout else "roundtrip",
        markout_horizon_ms=21_600_000 if markout else 0,           # 6 h fixed horizon
        selection_rank="trimmed_mean" if markout else "sortino",
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
    selection: str = "roundtrip",
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
    config = config or locked_config(universe, execution=execution, selection=selection)
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
    # markout path neutralizes against the equal-weight universe basket (matches the validated
    # study). Built from the candle lookups so it tracks the per-roll refresh (no parquet re-read).
    neutralize = config.selection_signal == "markout"
    basket = basket_from_series({c: lookups[c] for c in universe if c in lookups}) \
        if neutralize and lookups else None
    adapter = SelectionAdapter(provider, universe=set(universe), lookups=lookups or {},  # type: ignore[arg-type]
                               config=config, basket=basket)
    train_ms = config.train_days * _DAY_MS

    async def prepare(t0: int) -> None:
        if refresh_lookups is not None:
            log.info("live.refresh_candles", n=len(universe), t0=t0)
            fresh = await refresh_lookups(universe, t0 - train_ms, t0)  # type: ignore[operator]
            adapter.set_lookups(fresh)
            if neutralize:
                adapter.set_basket(
                    basket_from_series({c: fresh[c] for c in universe if c in fresh}))
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
            returns_fn=adapter.returns_fn, cutoff_fn=adapter.cutoff_fn,
            activity_fn=adapter.activity_fn, t0_ms=t0,
            budget_usd=budget_usd, registry_path=registry_path, checkpoint_path=checkpoint_path,
            analysis_script_hash=analysis_hash(), prepare=prepare, max_roster_size=max_roster_size)
        log.info("live.built", run_id=system.run_id, roster=system.runner.n_roster,
                 dry_run=dry_run)
        if dry_run:
            return system
        await system.run(**run_kw)  # type: ignore[arg-type]
        return system


def cmd_gate(a: argparse.Namespace) -> None:
    """Score the committed run once (the read-once gate verdict) on the candle-symmetric
    edge-over-field: roster vs train-eligible field, both priced as forward candle-markouts over
    [T0, now]. Uses LOCAL fills for BOTH arms (the whole-pool fetch is heavy — run off the live
    box). The realized journal only supplies the maxDD bound, not the edge measurement."""
    from babylon.follow.experiment import Registry
    from babylon.follow.gate_feed import RealizedJournal, run_gate_decision
    from babylon.follow.live import wall_ms

    if a.fills_dir is None:
        raise SystemExit("--gate needs --fills-dir (the field CONTROL fetch is heavy; run off-box)")
    universe = load_universe(a.universe)
    config = locked_config(universe, selection="markout")
    cand_path = a.candidates or Path("data/follow/markout_candidates.csv")
    candidates = load_candidates(cand_path)
    lookups = load_price_lookups(a.candles)
    basket = basket_from_series({c: lookups[c] for c in universe if c in lookups})
    reg_path = a.state_dir / "registry.jsonl"
    prior = Registry(reg_path).latest()
    if prior is None:
        raise SystemExit("no committed run in the registry — nothing to score")
    now_ms = a.now_ms if a.now_ms is not None else wall_ms()
    v, r = run_gate_decision(
        config=config, registry_path=reg_path, decision_log=a.state_dir / "decisions.jsonl",
        journal=RealizedJournal(a.state_dir / "realized.jsonl"), candidates=candidates,
        field_fills_provider=ParquetFillsProvider(a.fills_dir), lookups=lookups, basket=basket,
        now_ms=now_ms, depth_capped_survives=a.gate_depth_survives,
        max_field_wallets=a.max_field)
    log.info("gate.verdict", decision=v.decision, reasons=list(v.reasons),
             n_nominal=r.n_nominal, n_effective=r.n_effective,
             ci=(round(r.top_minus_control_ci_low, 2), round(r.top_minus_control_ci_high, 2)),
             maxdd=round(r.maxdd, 4), single_contrib=round(r.max_single_contrib_frac, 3))
    print(f"\nGATE VERDICT: {v.decision}")
    for reason in v.reasons:
        print(f"  - {reason}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Forward copy-trade paper experiment")
    ap.add_argument("--candidates", type=Path, default=None,
                    help="candidate pool CSV. Default is selection-aware: markout → the VALIDATED "
                         "2431-wallet study universe (data/follow/markout_candidates.csv); "
                         "roundtrip → data/follow/long_hold_wallets.csv.")
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
    ap.add_argument("--selection", choices=("roundtrip", "markout"), default="roundtrip",
                    help="roundtrip = original directional Sortino rule; markout = the validated "
                         "fixed-horizon operating point (6h markout, 15min lag, neutralized, "
                         "trimmed-mean). See audit/EDGE_INVESTIGATION.md.")
    ap.add_argument("--gate", action="store_true",
                    help="DRIVER: score accumulated harvests ONCE (read-once verdict). Loads the "
                         "journal (TOP) + computes the field CONTROL, then runs measure/decide. "
                         "Needs --fills-dir (the field fetch is heavy — run OFF the live box).")
    ap.add_argument("--gate-depth-survives", action="store_true",
                    help="assert the edge survives the depth cap at target notional (operator "
                         "attestation; paper harvests are tiny so depth rarely binds).")
    ap.add_argument("--max-field", type=int, default=None,
                    help="subsample the field CONTROL to N wallets (bounds RAM off-box).")
    ap.add_argument("--now-ms", type=int, default=None,
                    help="gate window end (default: wall clock); set for a reproducible run")
    a = ap.parse_args()
    a.state_dir.mkdir(parents=True, exist_ok=True)
    if a.gate:
        cmd_gate(a)
        return
    # selection-aware default pool. markout's validated pool is the BROAD 2431-wallet study
    # universe (fills_his) — NOT the long-hold survivor list (Audit 01): pre-selecting on past
    # long-hold skill is survivorship-tainted and isn't what the +24-31bp edge was measured on.
    cand_path = a.candidates or (Path("data/follow/markout_candidates.csv")
                                 if a.selection == "markout" else
                                 Path("data/follow/long_hold_wallets.csv"))
    candidates = load_candidates(cand_path, top_quintile_only=a.top_quintile_only)
    universe = load_universe(a.universe)
    # local-selection mode: parquet fills + static local candles ⇒ no REST prefetch/refetch
    local: dict[str, Any] = dict(provider=ParquetFillsProvider(a.fills_dir), refresh_lookups=None) \
        if a.fills_dir else {}
    log.info("live.start", n_candidates=len(candidates), n_universe=len(universe),
             dry_run=a.dry_run, testnet=a.testnet, local_fills=bool(a.fills_dir),
             selection=a.selection, candidates_pool=str(cand_path))
    asyncio.run(run_live(
        candidates=candidates, universe=universe, candles_dir=a.candles,
        network=Network.TESTNET if a.testnet else Network.MAINNET,
        registry_path=a.state_dir / "registry.jsonl",
        checkpoint_path=a.state_dir / "checkpoint.json", budget_usd=a.budget,
        max_roster_size=a.max_roster or None, dry_run=a.dry_run, selection=a.selection, **local))


if __name__ == "__main__":
    main()
