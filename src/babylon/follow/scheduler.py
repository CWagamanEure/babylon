"""Rolling re-rank scheduler for the forward experiment (docs/LIVE_FOLLOW.md §v4.4).

At each pre-committed roll T0 it ranks the candidate wallets by their TRAIN-window
followable skill, takes the top quintile, computes frozen per-wallet fractional-Kelly
weights, captures each wallet's train-cutoff tid (the rolling-seam guard so a round-trip
straddling T0 can't leak into training), and registers the sub-period's immutable
RunManifest. The roll SCHEDULE is pre-committed and cron-auto — no human re-fit; the
registry refuses to overwrite a committed T0.

The per-wallet return computation is INJECTED (followable.py's job): the scheduler owns
selection + weighting + registration, which keeps it pure and testable.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from babylon.follow.experiment import ExperimentConfig, Registry, RunManifest
from babylon.follow.weights import kelly_weights
from babylon.logging import get_logger

log = get_logger("follow.scheduler")

# (wallet, t0_ms) -> per-round-trip net returns fully closed BEFORE t0 (the seam guard)
ReturnsFn = Callable[[str, int], np.ndarray]
# (wallet, t0_ms) -> the wallet's last train-window fill tid (0 if none)
CutoffFn = Callable[[str, int], int]
# (wallet, t0_ms) -> raw FILL count in the train window (the disposition-free eligibility gate)
ActivityFn = Callable[[str, int], int]
# (candidates, t0_ms) -> (returns, cutoffs, activity) for the WHOLE pool at once — the RAM-bounded
# chunked-subprocess path (roll_worker.chunked_batch_returns). When set, replaces the per-wallet
# in-process loop so a 2431-wallet roll never climbs past one chunk (fits a 1GB box).
BatchReturnsFn = Callable[[list[str], int],
                          tuple[dict[str, np.ndarray], dict[str, int], dict[str, int]]]


def _sortino(r: np.ndarray) -> float:
    """Sortino ratio = mean / downside-deviation — the empirically best OOS-predictive
    selection statistic on our data: it keeps UPSIDE-tail magnitude (real signal for a
    Kelly book) but penalizes DOWNSIDE dispersion (the blowup risk a follower inherits).
    Beats median (tail-blind, worst OOS) and Sharpe (penalizes the good upside tail too).
    Sign(Sortino)=sign(mean), so a selected wallet always gets positive Kelly weight.

    The downside deviation is taken over ALL n (min(r,0), the standard form) and FLOORED at a
    fraction of the overall dispersion — so a wallet with (near-)zero downside in its sample
    can't explode the ratio and auto-rank top (the EPS / one-tiny-loser artifact an audit
    flagged). With the floor, a no-loser wallet scores ~4×Sharpe, not +∞."""
    if r.size == 0:
        return 0.0
    mu = float(r.mean())
    neg = np.minimum(r, 0.0)
    dd = float(np.sqrt(np.mean(neg * neg)))           # downside deviation over N (standard)
    floor = 0.25 * float(r.std()) + 1e-9              # regularize: no (near-)zero-downside blowup
    return mu / max(dd, floor)


def _trimmed_mean(r: np.ndarray, trim: float = 0.1) -> float:
    """Trimmed mean (drop the trim% tails each side) — the empirically best OOS-predictive
    selection statistic for the fixed-horizon markout signal (audit/EDGE_INVESTIGATION.md): it
    beats Sortino, which penalized downside dispersion that did NOT predict OOS. Robust to the
    fat tails; with <5 obs falls back to the plain mean (nothing to trim)."""
    if r.size == 0:
        return 0.0
    if r.size < 5:
        return float(r.mean())
    lo, hi = np.percentile(r, [trim * 100.0, (1.0 - trim) * 100.0])
    m = r[(r >= lo) & (r <= hi)]
    return float(m.mean()) if m.size else float(r.mean())


_RANK_FNS = {"sortino": _sortino, "trimmed_mean": _trimmed_mean}


def _downside_dev(r: np.ndarray, floor_frac: float = 0.25) -> float:
    """Downside deviation (Sortino denominator) = sqrt(mean(min(r,0)^2)), FLOORED at a fraction
    of overall dispersion so a (near-)zero-downside sample can't blow up the bet (the same EPS
    guard `_sortino` uses). This is the OOS-PERSISTENT risk lever (train→test Spearman ≈ +0.38,
    orthogonal to edge — see [[babylon-edge-investigation]]); it's used for SIZING, not ranking."""
    neg = np.minimum(r, 0.0)
    dd = float(np.sqrt(np.mean(neg * neg))) if r.size else 0.0
    return max(dd, floor_frac * float(r.std()) + 1e-9)


def tail_aware_notionals(
    returns_by_wallet: dict[str, np.ndarray], *, base_notional: float, kelly_frac: float = 1.0,
    ratio_cap: float = 3.0, max_notional: float | None = None,
) -> dict[str, float]:
    """Per-event tranche notional for each (selected) wallet, sized by tail-aware fractional
    Kelly: `base · kelly_frac · clamp(trimmed_mean / downside_dev, 0, ratio_cap)`.

    Size = fractional Kelly = trimmed_mean / downside-deviation. The numerator is the SAME
    trimmed-mean edge stat used for selection, so size is EDGE-PROPORTIONAL by design — a bigger
    edge bets more. This is NOT a pure risk tilt / re-scaling that leaves the edge ranking alone;
    edge enters the size directly. The downside-deviation denominator is the OOS-persistent risk
    lever (bet LESS on a wallet whose same edge carries a fatter LEFT tail). `kelly_frac` (<1) is
    the fractional-Kelly drawdown scalar; `ratio_cap` bounds the mu/σ multiplier and `max_notional`
    caps the per-event size, so a thin-sample low-downside wallet can't dominate the book. Wallets
    with a non-positive trimmed mean get 0 (they shouldn't be in the roster). The ledger's
    gross/per-coin caps bound the BOOK; this sizes a single event."""
    out: dict[str, float] = {}
    for w, r in returns_by_wallet.items():
        a = np.asarray(r, dtype=np.float64)
        mu = _trimmed_mean(a)
        if mu <= 0.0 or a.size == 0:
            out[w] = 0.0
            continue
        ratio = min(mu / _downside_dev(a), ratio_cap)
        n = base_notional * kelly_frac * ratio
        out[w] = min(n, max_notional) if max_notional is not None else n
    return out


def select_roster(
    returns_by_wallet: dict[str, np.ndarray], cutoff_tids: dict[str, int], *,
    top_quintile_frac: float = 0.2, min_positions: int = 6, max_wallet_frac: float = 0.05,
    max_roster_size: int | None = None, activity_by_wallet: dict[str, int] | None = None,
    rank_stat: str = "sortino",
) -> tuple[list[str], dict[str, float], dict[str, int]]:
    """Rank by SORTINO of the followable return (mean/downside-deviation; see _sortino), take
    the top `top_quintile_frac` (capped at `max_roster_size`), weight by frozen fractional-Kelly.

    ELIGIBILITY: when `activity_by_wallet` is given, gate on RAW activity (fill count) ≥
    min_positions — NOT closed-round-trip count. A disposition-corrected re-test showed the
    closed-count gate re-introduces disposition correlation (it selects high-turnover wallets
    and shrinks the pool); raw-activity gating keeps a broad, unbiased pool and the min then
    has no material effect. A hard floor of ≥2 returns is still required to compute a Sortino.
    Falls back to closed-count (the old behaviour) when activity isn't supplied (tests).

    The roster cap keeps it small enough to POLL in real time under the HL rate limit."""
    if activity_by_wallet is not None:
        eligible = {w: np.asarray(r, dtype=np.float64) for w, r in returns_by_wallet.items()
                    if len(r) >= 2 and activity_by_wallet.get(w, 0) >= min_positions}
    else:
        eligible = {w: np.asarray(r, dtype=np.float64)
                    for w, r in returns_by_wallet.items() if len(r) >= min_positions}
    if not eligible:
        return [], {}, {}
    rank_fn = _RANK_FNS[rank_stat]
    ranked = sorted(eligible, key=lambda w: -rank_fn(eligible[w]))
    q = max(1, int(len(ranked) * top_quintile_frac))
    if max_roster_size is not None:
        q = min(q, max_roster_size)
    top = ranked[:q]
    weights = kelly_weights({w: eligible[w] for w in top}, max_frac=max_wallet_frac)
    cutoffs = {w: int(cutoff_tids.get(w, 0)) for w in weights}
    return list(weights), weights, cutoffs


class RollScheduler:
    def __init__(
        self, candidates: list[str], returns_fn: ReturnsFn, cutoff_fn: CutoffFn,
        config: ExperimentConfig, registry: Registry, *, analysis_script_hash: str,
        top_quintile_frac: float = 0.2, max_roster_size: int | None = None,
        activity_fn: ActivityFn | None = None, batch_returns_fn: BatchReturnsFn | None = None,
    ) -> None:
        config.validate()
        self._candidates = list(candidates)
        self._returns_fn = returns_fn
        self._cutoff_fn = cutoff_fn
        self._activity_fn = activity_fn      # (wallet, t0) -> raw fill count in train window
        self._batch_fn = batch_returns_fn    # chunked-subprocess whole-pool path (RAM-bounded)
        self._config = config
        self._registry = registry
        self._analysis_hash = analysis_script_hash
        self._tqf = top_quintile_frac
        self._max_roster = max_roster_size

    def roll(self, t0_ms: int) -> tuple[list[str], dict[str, float], str]:
        """Select + freeze the roster for the sub-period starting at t0_ms, register its
        immutable manifest, and return (roster, weights, run_id) for the runner to adopt.
        Idempotent for an identical re-selection; a different selection at the same T0 is
        refused by the registry (immutable pre-registration)."""
        # The raw-activity gate is the round-trip disposition-bias fix. The markout signal scores
        # OPENS (disposition-free), so it gates purely on the OPEN count (len(returns) ≥
        # min_positions = the validated min_train) via select_roster's no-activity branch — no raw
        # gate, which keeps live ≡ the validated study.
        use_activity = self._activity_fn is not None and self._config.selection_signal != "markout"
        if self._batch_fn is not None:
            # RAM-bounded: whole pool via chunked subprocesses (each frees its memory on exit) —
            # bit-identical roster, but peak RSS stays at one chunk (fits a 1GB box).
            returns, cutoffs, batch_activity = self._batch_fn(self._candidates, t0_ms)
            activity: dict[str, int] | None = batch_activity if use_activity else None
        else:
            # in-process: process each wallet's returns + cutoff consecutively so the adapter's
            # single-entry cache holds ONE wallet's fills at a time (used for REST mode + tests).
            returns = {}
            cutoffs = {}
            activity = {} if use_activity else None
            for w in self._candidates:
                returns[w] = self._returns_fn(w, t0_ms)
                cutoffs[w] = self._cutoff_fn(w, t0_ms)
                if use_activity and activity is not None:
                    activity[w] = self._activity_fn(w, t0_ms)  # type: ignore[misc]
        roster, weights, cut = select_roster(
            returns, cutoffs, top_quintile_frac=self._tqf,
            min_positions=self._config.min_positions, max_wallet_frac=self._config.max_wallet_frac,
            max_roster_size=self._max_roster, activity_by_wallet=activity,
            rank_stat=self._config.selection_rank)
        if not roster:
            raise ValueError(f"roll @ T0={t0_ms} selected an empty roster — no eligible wallets")
        manifest = RunManifest.build(
            t0_ms=t0_ms, edge_weights=weights, train_cutoff_tids=cut,
            config=self._config, analysis_script_hash=self._analysis_hash)
        run_id = self._registry.register(manifest)
        log.info("roll.committed", t0_ms=t0_ms, run_id=run_id, n_roster=len(roster))
        return roster, weights, run_id
