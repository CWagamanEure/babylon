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


def select_roster(
    returns_by_wallet: dict[str, np.ndarray], cutoff_tids: dict[str, int], *,
    top_quintile_frac: float = 0.2, min_positions: int = 6, max_wallet_frac: float = 0.05,
    max_roster_size: int | None = None, activity_by_wallet: dict[str, int] | None = None,
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
    ranked = sorted(eligible, key=lambda w: -_sortino(eligible[w]))
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
        activity_fn: ActivityFn | None = None,
    ) -> None:
        config.validate()
        self._candidates = list(candidates)
        self._returns_fn = returns_fn
        self._cutoff_fn = cutoff_fn
        self._activity_fn = activity_fn      # (wallet, t0) -> raw fill count in train window
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
        # process each wallet's returns + cutoff consecutively so a single-entry adapter
        # cache holds ONE wallet's fills at a time (the whole pool at once OOMs a small box)
        returns: dict[str, np.ndarray] = {}
        cutoffs: dict[str, int] = {}
        activity: dict[str, int] | None = {} if self._activity_fn is not None else None
        for w in self._candidates:
            returns[w] = self._returns_fn(w, t0_ms)
            cutoffs[w] = self._cutoff_fn(w, t0_ms)
            if self._activity_fn is not None and activity is not None:
                activity[w] = self._activity_fn(w, t0_ms)
        roster, weights, cut = select_roster(
            returns, cutoffs, top_quintile_frac=self._tqf,
            min_positions=self._config.min_positions, max_wallet_frac=self._config.max_wallet_frac,
            max_roster_size=self._max_roster, activity_by_wallet=activity)
        if not roster:
            raise ValueError(f"roll @ T0={t0_ms} selected an empty roster — no eligible wallets")
        manifest = RunManifest.build(
            t0_ms=t0_ms, edge_weights=weights, train_cutoff_tids=cut,
            config=self._config, analysis_script_hash=self._analysis_hash)
        run_id = self._registry.register(manifest)
        log.info("roll.committed", t0_ms=t0_ms, run_id=run_id, n_roster=len(roster))
        return roster, weights, run_id
