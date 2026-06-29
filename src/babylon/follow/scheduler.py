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


def _sortino(r: np.ndarray) -> float:
    """Sortino ratio = mean / downside-deviation — the empirically best OOS-predictive
    selection statistic on our data: it keeps UPSIDE-tail magnitude (real signal for a
    Kelly book) but penalizes DOWNSIDE dispersion (the blowup risk a follower inherits).
    Beats median (tail-blind, worst OOS) and Sharpe (penalizes the good upside tail too).
    Sign(Sortino)=sign(mean), so a selected wallet always gets positive Kelly weight."""
    mu = float(r.mean())
    dn = r[r < 0]
    dd = float(np.sqrt(np.mean(dn * dn))) if dn.size else 0.0
    return mu / dd if dd > 0 else mu * 1e6   # no losing round-trip → rank by mean, far up


def select_roster(
    returns_by_wallet: dict[str, np.ndarray], cutoff_tids: dict[str, int], *,
    top_quintile_frac: float = 0.2, min_positions: int = 6, max_wallet_frac: float = 0.05,
    max_roster_size: int | None = None,
) -> tuple[list[str], dict[str, float], dict[str, int]]:
    """Rank by SORTINO of the followable return (mean/downside-deviation — the best
    OOS-predictive statistic on our data; see _sortino), take the top `top_quintile_frac`
    (capped at `max_roster_size`), weight by frozen fractional-Kelly. The cap keeps the roster small
    enough to POLL in real time under the HL rate limit — a huge roster can't be swept fast
    enough to detect position changes before the front-loaded edge decays. Returns
    (roster, weights, train_cutoff_tids)."""
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
    ) -> None:
        config.validate()
        self._candidates = list(candidates)
        self._returns_fn = returns_fn
        self._cutoff_fn = cutoff_fn
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
        for w in self._candidates:
            returns[w] = self._returns_fn(w, t0_ms)
            cutoffs[w] = self._cutoff_fn(w, t0_ms)
        roster, weights, cut = select_roster(
            returns, cutoffs, top_quintile_frac=self._tqf,
            min_positions=self._config.min_positions, max_wallet_frac=self._config.max_wallet_frac,
            max_roster_size=self._max_roster)
        if not roster:
            raise ValueError(f"roll @ T0={t0_ms} selected an empty roster — no eligible wallets")
        manifest = RunManifest.build(
            t0_ms=t0_ms, edge_weights=weights, train_cutoff_tids=cut,
            config=self._config, analysis_script_hash=self._analysis_hash)
        run_id = self._registry.register(manifest)
        log.info("roll.committed", t0_ms=t0_ms, run_id=run_id, n_roster=len(roster))
        return roster, weights, run_id
