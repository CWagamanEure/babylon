"""Gate feed — turns the committed roster + candidate field into the gate's pre-committed
decision, computed on the VALIDATED estimator (audit/EDGE_INVESTIGATION.md, `selci_fh.cmd_ci`).

The gate tests SELECTION SKILL = edge-over-field: mean(roster forward candle-markouts) −
mean(field forward candle-markouts). BOTH arms are priced the SAME way — candle close at
entry+lag → entry+lag+horizon, per OPEN, disposition-free (`markout_returns`) — so cost cancels
in the difference (the study never subtracted a cost floor from the edge-over-field; it only
cancels). The CI is a CLUSTER bootstrap that resamples whole WALLETS with replacement in each
arm (reproducing `_boot_eof` forward; selection is frozen at T0, so there's no re-selection),
which carries BOTH arms' sampling error — unlike a constant-broadcast field baseline.

    TOP     = the committed roster's forward candle-markouts (per wallet).
    CONTROL = the TRAIN-ELIGIBLE field's forward candle-markouts (per wallet) over the SAME
              window — the "follow everyone" null. Roster ⊂ field, exactly as the study.

The REALIZED harvest fills (RealizedJournal) are NO LONGER the gate's edge measurement — you
can't realize the field, so realized-vs-candle can never be symmetric and silently rigs the
comparison. They are kept as a SEPARATE execution-quality diagnostic (`execution_slippage`:
how much real spread/slippage/fillability ate vs the candle markout) and as the honest source
of the realized-PnL drawdown bound.

[Gate rework, 2026-06-30: replaced realized-fill TOP vs candle-mid−flat-cost CONTROL — two
incompatible rulers that could fabricate a GO (empty-field→zeros→GO, one-sided cost, constant
control stripping field variance). This module now measures the thing that was validated.]
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path

import numpy as np

from babylon.follow.experiment import ExperimentConfig, Registry, Results, Verdict, decide
from babylon.follow.followable import markout_returns
from babylon.follow.harvest import RealizedRoundTrip
from babylon.follow.measure import (
    block_bootstrap_ci,
    effective_n,
    max_drawdown,
    single_contrib_frac,
)
from babylon.follow.skill import _basket_ret_bps
from babylon.logging import get_logger

log = get_logger("follow.gate_feed")

Lookups = dict[str, tuple[np.ndarray, np.ndarray]]
Basket = tuple[np.ndarray, np.ndarray] | None
FillsProvider = Callable[[str, int, int], object]  # (wallet, start_ms, end_ms) -> df | None
_DAY_MS = 86_400_000


class RealizedJournal:
    """Append-only durable log of realized harvests — wired as the HarvestRunner's `on_realized`
    hook. In the reworked gate this is the EXECUTION-QUALITY source (slippage diagnostic + the
    realized-PnL drawdown bound), NOT the edge measurement (which is candle-symmetric)."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def append(self, realized: Sequence[RealizedRoundTrip]) -> None:
        if not realized:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            for r in realized:
                f.write(json.dumps(asdict(r)) + "\n")

    def load(self) -> list[RealizedRoundTrip]:
        """Read the durable harvest log, DEDUPED by tranche id (first write wins). `append` is
        at-least-once: a crash between the journal write and the next checkpoint re-exits the
        (checkpoint-still-OPEN) tranche on resume and writes a SECOND, distorted-horizon line for
        the same id. Deduping on read keeps the original 6h harvest and drops the resume artifact,
        so the profitability CI + maxDD bound aren't double-counted."""
        if not self._path.exists():
            return []
        out: list[RealizedRoundTrip] = []
        seen: set[str] = set()
        for ln in self._path.read_text().splitlines():
            if not ln.strip():
                continue
            rt = RealizedRoundTrip(**json.loads(ln))
            if rt.id in seen:
                continue
            seen.add(rt.id)
            out.append(rt)
        return out


# ── candle-markout arms (the SYMMETRIC estimator: same ruler on TOP and CONTROL) ──────────────
def _forward_markouts(
    wallet: str, fills_provider: FillsProvider, window: tuple[int, int], *,
    lookups: Lookups, basket: Basket, config: ExperimentConfig,
) -> np.ndarray:
    """One wallet's per-open fixed-horizon candle markouts over `window`, seam-guarded so only
    opens whose FULL markout window (entry+lag+horizon) finished before `window[1]` count."""
    df = fills_provider(wallet, window[0], window[1])
    if df is None or getattr(df, "height", 0) == 0:
        return np.empty(0, dtype=np.float64)
    return markout_returns(
        df, lookups=lookups, lag_ms=config.lag_bucket_ms, horizon_ms=config.markout_horizon_ms,
        basket=basket, beta=config.beta, before_ms=window[1])


def roster_markouts(
    roster: Sequence[str], fills_provider: FillsProvider, *, window: tuple[int, int],
    lookups: Lookups, basket: Basket, config: ExperimentConfig,
) -> dict[str, np.ndarray]:
    """TOP arm: each committed roster wallet's forward candle-markouts (drops wallets with no
    priceable open in the window)."""
    out: dict[str, np.ndarray] = {}
    for w in roster:
        r = _forward_markouts(w, fills_provider, window, lookups=lookups, basket=basket,
                              config=config)
        if r.size:
            out[w] = r
    return out


def eligible_field_markouts(
    candidates: Sequence[str], fills_provider: FillsProvider, *,
    train_window: tuple[int, int], forward_window: tuple[int, int],
    lookups: Lookups, basket: Basket, config: ExperimentConfig, max_wallets: int | None = None,
) -> dict[str, np.ndarray]:
    """CONTROL arm: the "follow everyone" null = every candidate that was TRAIN-ELIGIBLE at
    selection (≥ `min_positions` markout opens in the TRAIN window — the SAME eligibility the
    roster was selected under, NOT forward activity), scored on its forward candle-markouts over
    the SAME `forward_window` as TOP. Roster ⊂ field by construction, exactly as the study's field.

    Fetches per-wallet — SHOULD run OFF the live box (a whole-pool fetch hits the ~4GB polars
    plateau → would OOM a 1GB droplet). `max_wallets` = deterministic prefix subsample."""
    pool = list(candidates)[:max_wallets] if max_wallets is not None else list(candidates)
    out: dict[str, np.ndarray] = {}
    for w in pool:
        tr = fills_provider(w, train_window[0], train_window[1])
        if tr is None or getattr(tr, "height", 0) == 0:
            continue
        n_train = markout_returns(
            tr, lookups=lookups, lag_ms=config.lag_bucket_ms,
            horizon_ms=config.markout_horizon_ms, basket=basket, beta=config.beta,
            before_ms=train_window[1]).size
        if n_train < config.min_positions:
            continue                                    # train-ineligible → not in the field
        r = _forward_markouts(w, fills_provider, forward_window, lookups=lookups, basket=basket,
                              config=config)
        if r.size:
            out[w] = r
    return out


def _pool(mk: dict[str, np.ndarray]) -> np.ndarray:
    arrs = [a for a in mk.values() if a.size]
    return np.concatenate(arrs) if arrs else np.empty(0, dtype=np.float64)


def cluster_boot_eof(
    roster_mk: dict[str, np.ndarray], field_mk: dict[str, np.ndarray], *,
    n_boot: int, seed: int, alpha: float = 0.05,
) -> tuple[float, float, float]:
    """(point eof, ci_low, ci_high). eof = pooled roster mean − pooled field mean. The CI
    resamples whole WALLETS with replacement in each arm (cluster bootstrap = `_boot_eof`
    forward): whole per-wallet arrays are kept, so within-wallet autocorrelation and
    cross-wallet clustering are both preserved, and the field's own sampling error is in the CI."""
    r_arrs = [a for a in roster_mk.values() if a.size]
    f_arrs = [a for a in field_mk.values() if a.size]
    point = float(_pool(roster_mk).mean()) - float(_pool(field_mk).mean())
    rng = np.random.default_rng(seed)
    nr, nf = len(r_arrs), len(f_arrs)
    dist = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        ri = rng.integers(0, nr, nr)
        fi = rng.integers(0, nf, nf)
        rm = np.concatenate([r_arrs[i] for i in ri]).mean()
        fm = np.concatenate([f_arrs[i] for i in fi]).mean()
        dist[b] = rm - fm
    lo, hi = np.quantile(dist, [alpha / 2, 1 - alpha / 2])
    return point, float(lo), float(hi)


# ── realized-fill execution diagnostic (NOT the edge measurement) ─────────────────────────────
def neutralize_top(
    realized: Sequence[RealizedRoundTrip], basket: Basket, beta: float = 1.0,
) -> np.ndarray:
    """Neutralized REALIZED-fill returns (raw_bps − dir·β·basket over [entry, exit]). Used for the
    realized-PnL drawdown bound and the execution-slippage diagnostic — NOT the gate's TOP arm."""
    out = np.empty(len(realized), dtype=np.float64)
    for i, r in enumerate(realized):
        neut = r.raw_bps
        if basket is not None:
            neut -= r.direction * beta * _basket_ret_bps(basket, r.entry_ms, r.exit_ms)
        out[i] = neut
    return out


def equity_curve(top_bps: np.ndarray, start: float = 1.0) -> np.ndarray:
    """Compounding equity from per-harvest returns (for the realized maxDD bound), in realized
    order — drawdowns reflect the actual harvest sequence."""
    g = 1.0 + np.asarray(top_bps, dtype=np.float64) / 1e4
    return start * np.concatenate([[1.0], np.cumprod(g)])


def execution_slippage(
    realized: Sequence[RealizedRoundTrip], roster_mk: dict[str, np.ndarray], basket: Basket,
    beta: float = 1.0,
) -> dict[str, float]:
    """Execution-quality diagnostic (reported, NOT gated): mean realized-fill markout vs mean
    candle markout for the roster. `realized − candle` is what real spread/slippage/fillability
    cost us relative to the idealized candle measure the gate is decided on."""
    rtop = neutralize_top(realized, basket, beta=beta)
    candle = _pool(roster_mk)
    r_mean = float(rtop.mean()) if rtop.size else 0.0
    c_mean = float(candle.mean()) if candle.size else 0.0
    return {"realized_mean_bps": r_mean, "candle_mean_bps": c_mean,
            "slippage_bps": r_mean - c_mean, "n_realized": int(rtop.size),
            "n_candle": int(candle.size)}


def results_hash(r: Results) -> str:
    """Stable hash binding the measured Results to the read-once decision log."""
    return hashlib.sha256(json.dumps(asdict(r), sort_keys=True).encode()).hexdigest()[:16]


# ── assemble Results + run the read-once decision ─────────────────────────────────────────────
_MIN_ARM_WALLETS = 3   # cluster bootstrap can't estimate an arm's sampling error from 1-2 wallets


def assemble_results(
    roster_mk: dict[str, np.ndarray], field_mk: dict[str, np.ndarray], *,
    realized_net: np.ndarray, depth_capped_survives: bool, config: ExperimentConfig,
) -> Results:
    """Build the pre-committed Results from the two candle-markout arms (selection skill) plus the
    realized-net-PnL CI (profitability). Raises if EITHER candle arm is empty — an empty field can
    NEVER become a zero null that any positive TOP beats into a GO.

    `realized_net` = the neutralized realized per-harvest returns (bps), time-ordered — real fast
    execution net of real cost. Its circular block-bootstrap CI is the profitability leg (GO needs
    ci_low>0); <2 harvests → (0,0) = not yet proven (INCONCLUSIVE), never a spurious pass."""
    r_pool, f_pool = _pool(roster_mk), _pool(field_mk)
    if r_pool.size == 0 or f_pool.size == 0:
        raise ValueError(
            "empty TOP or CONTROL arm — cannot form the edge-over-field null (INCONCLUSIVE); "
            "refusing to score a positive TOP against an absent field")
    _point, lo, hi = cluster_boot_eof(
        roster_mk, field_mk, n_boot=config.gate_n_boot, seed=config.gate_boot_seed)
    # Min-wallet floor: a 1-2 wallet arm makes the cluster bootstrap resample a constant (nf==1 →
    # always index [0]) → ZERO field/roster sampling variance → a spuriously tight, passable eof
    # CI on ~no data. Below the floor the selection leg is underpowered, not proven — clamp the
    # lower bound to <=0 so it can never clear a positive MAR (INCONCLUSIVE, never a fabricated GO).
    n_roster_w = sum(1 for a in roster_mk.values() if a.size)
    n_field_w = sum(1 for a in field_mk.values() if a.size)
    if n_roster_w < _MIN_ARM_WALLETS or n_field_w < _MIN_ARM_WALLETS:
        log.warning("gate.eof_underpowered", roster_wallets=n_roster_w, field_wallets=n_field_w,
                    min=_MIN_ARM_WALLETS)
        lo = min(lo, 0.0)
    rn = np.asarray(realized_net, dtype=np.float64)
    # Min-harvest floor: the realized block-bootstrap needs n >> block or its CI degenerates
    # (see block_bootstrap_ci). Require >= 3*block harvests before the profitability leg can pass;
    # below it, profitability is unproven → (0,0), never a spurious ci_low>0 from 2 lucky fills.
    min_harvests = max(20, 3 * config.gate_block)
    if rn.size >= min_harvests:
        rlo, rhi = block_bootstrap_ci(rn, block=config.gate_block, n_boot=config.gate_n_boot,
                                      seed=config.gate_boot_seed)
    else:
        rlo, rhi = 0.0, 0.0                      # too few harvests → profitability unproven
    eq = equity_curve(rn) if rn.size else np.array([1.0])
    field_mean = float(f_pool.mean())
    n = int(r_pool.size)
    # per-wallet share of the eof spread (Σ = eof): concentration gate
    contrib = {w: (a.size / n) * (float(a.mean()) - field_mean)
               for w, a in roster_mk.items() if a.size}
    r = Results(
        n_effective=effective_n(r_pool),
        n_nominal=n,
        top_minus_control_ci_low=lo,
        top_minus_control_ci_high=hi,
        top_vs_poolmean_significant=lo > 0.0,
        maxdd=max_drawdown(eq),
        depth_capped_survives=depth_capped_survives,
        max_single_contrib_frac=single_contrib_frac(contrib),
        realized_net_ci_low=rlo,
        realized_net_ci_high=rhi,
    )
    r.validate()
    return r


def run_gate_decision(
    *, config: ExperimentConfig, registry_path: Path, decision_log: Path,
    candidates: Sequence[str], field_fills_provider: FillsProvider,
    lookups: Lookups, basket: Basket, now_ms: int, depth_capped_survives: bool,
    journal: RealizedJournal | None = None, max_field_wallets: int | None = None,
) -> tuple[Verdict, Results]:
    """The DRIVER ("score it now"). Loads the LATEST committed run, prices the roster (TOP) and
    the train-eligible field (CONTROL) as forward candle-markouts over the SAME [T0, now] window,
    and runs the read-once gate ONCE. The realized journal (if any) supplies the maxDD bound.
    Raises on nothing-committed or an empty arm (never a silent GO)."""
    registry = Registry(registry_path)
    prior = registry.latest()
    if prior is None:
        raise ValueError("no committed run in the registry — cannot decide")
    t0 = prior.t0_ms
    forward_window = (t0, int(now_ms))
    if forward_window[1] <= forward_window[0]:
        raise ValueError("gate window end must be after T0")
    train_window = (t0 - config.train_days * _DAY_MS, t0)
    field_mk = eligible_field_markouts(
        candidates, field_fills_provider, train_window=train_window,
        forward_window=forward_window, lookups=lookups, basket=basket, config=config,
        max_wallets=max_field_wallets)
    roster_mk = roster_markouts(
        prior.roster, field_fills_provider, window=forward_window, lookups=lookups,
        basket=basket, config=config)
    realized = sorted(journal.load(), key=lambda r: r.exit_ms) if journal is not None else []
    rtop = neutralize_top(realized, basket, beta=config.beta) if realized else np.empty(0)
    r = assemble_results(roster_mk, field_mk, realized_net=rtop,
                         depth_capped_survives=depth_capped_survives, config=config)
    v = decide(config, r, registry=registry, run_id=prior.run_id(), decision_log=decision_log,
               results_hash=results_hash(r))
    return v, r
