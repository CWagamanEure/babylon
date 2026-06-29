"""Pre-registration harness for the forward copy-trade paper experiment.

Encodes docs/LIVE_FOLLOW.md §v4.3/4.4: ONE immutable numeric config + an immutable
run_id + a pre-committed numeric decision rule + an append-only registry. The point is
that this forward run cannot be re-litigated the way the backtest investigation was —
every knob is fixed before T0, the team runs blind to PnL until min-n, and the verdict
is read ONCE against fixed thresholds. A re-ranked roster cannot silently resume because
the run_id hashes the roster + per-wallet train-cutoff tid + config.

The gate is on the DIRECTIONAL (deployed) per-round-trip top−control return — NOT the
portfolio Sharpe (underpowered on a months horizon) and NOT the neutralized series
(the fragile variant). See §v4.2.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Execution = Literal["retail", "validator"]
Decision = Literal["GO", "NO_GO", "INCONCLUSIVE"]


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Every knob resolved to a number BEFORE T0. `retail` execution is the binding
    primary; `validator` is a labeled optimistic upside bound, never the headline."""

    # selection / strategy
    execution: Execution
    universe_hash: str           # sha256 of the sorted alt universe (locks the coin set)
    eligible_pool: str           # control-pool definition, e.g. "longhold_taker_conviction"
    train_days: int
    follow_days: int
    roll_cadence_days: int
    min_hold_ms: int             # SELECTION skill only — never filters the live copy
    min_positions: int
    beta: float                  # diagnostic neutralization ratio (gate is directional)
    # sizing / risk
    gross_target: float
    max_coin_frac: float
    max_wallet_frac: float
    also_run_uncapped: bool      # report the capped vs uncapped "concentration premium"
    # execution / measurement
    lag_bucket_ms: int           # the SINGLE headline lag
    fee_bps: float               # 4.5 taker, folded into the fill price
    impact_bps: float            # entry-impact slippage (retail), folded into the fill price
    max_depth_frac: float        # depth cap (capacity realism)
    target_notional_usd: float
    # controls / power / decision rule
    primary_control: str         # "pool_mean"
    secondary_controls: tuple[str, ...]   # ("random", "sign_shuffle")
    min_n_nominal: int           # nominal round-trips per arm before any verdict
    min_effective_n: int         # block-bootstrap effective-n floor
    horizon_cap_days: int        # hard calendar cap
    mar_bps: float               # minimum acceptable net return (above cost floor) for GO
    maxdd_bound: float           # e.g. -0.25 (negative)
    max_single_contrib_frac: float  # no single wallet/coin may supply > this of the spread

    def validate(self) -> None:
        assert self.execution in ("retail", "validator")
        assert 0 < self.train_days and 0 < self.follow_days and 0 < self.roll_cadence_days
        assert self.min_positions >= 1 and self.min_hold_ms >= 0
        assert 0 < self.gross_target <= 5
        assert 0 < self.max_coin_frac <= 1 and 0 < self.max_wallet_frac <= 1
        assert self.lag_bucket_ms >= 0 and self.fee_bps >= 0 and self.impact_bps >= 0
        assert 0 < self.max_depth_frac <= 1 and self.target_notional_usd > 0
        assert self.primary_control == "pool_mean", "primary control must be the pool-mean null"
        assert self.min_n_nominal >= 1 and self.min_effective_n >= 1
        assert self.horizon_cap_days > 0
        assert self.maxdd_bound < 0 and 0 < self.max_single_contrib_frac <= 1
        assert self.mar_bps > 0

    def canonical(self) -> str:
        d = asdict(self)
        d["secondary_controls"] = list(self.secondary_controls)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def hash(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Frozen at each sub-period's T0. The run_id is the experiment's identity; a
    re-ranked roster or any config change produces a different run_id, so a contaminated
    resume cannot masquerade as the pre-registered run."""

    t0_ms: int
    roster: tuple[str, ...]              # sorted wallet addresses (the frozen follow set)
    edge_weights: dict[str, float]       # wallet -> consensus weight (capped, renormalized)
    train_cutoff_tids: dict[str, int]    # wallet -> last train-window tid (rolling-seam guard)
    config_hash: str
    analysis_script_hash: str

    def canonical(self) -> str:
        return json.dumps(
            {
                "t0_ms": self.t0_ms,
                "roster": list(self.roster),
                "edge_weights": {k: self.edge_weights[k] for k in sorted(self.edge_weights)},
                "train_cutoff_tids": {
                    k: self.train_cutoff_tids[k] for k in sorted(self.train_cutoff_tids)},
                "config_hash": self.config_hash,
                "analysis_script_hash": self.analysis_script_hash,
            },
            sort_keys=True, separators=(",", ":"),
        )

    def run_id(self) -> str:
        return "run_" + hashlib.sha256(self.canonical().encode()).hexdigest()[:24]


class Registry:
    """Append-only on-disk registry. register() commits a manifest; verify_resume()
    refuses to start if the live manifest differs from the committed one for that T0 —
    blocking a silent re-rank. Pre-commit the whole roll SCHEDULE; only the cron-auto roll
    may add a new sub-period manifest, never a human re-fit."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _read(self) -> list[dict[str, object]]:
        if not self._path.exists():
            return []
        return [json.loads(line) for line in self._path.read_text().splitlines() if line.strip()]

    def committed(self, t0_ms: int) -> dict[str, object] | None:
        for rec in self._read():
            if rec["t0_ms"] == t0_ms:
                return rec
        return None

    def register(self, manifest: RunManifest) -> str:
        rid = manifest.run_id()
        existing = self.committed(manifest.t0_ms)
        if existing is not None:
            if existing["run_id"] != rid:
                raise ValueError(
                    f"T0={manifest.t0_ms} already committed as {existing['run_id']}; "
                    f"refusing to overwrite with {rid} (a re-rank/config change). "
                    "Pre-registration is immutable.")
            return rid  # idempotent re-register of the identical manifest
        rec = {"run_id": rid, "t0_ms": manifest.t0_ms, "config_hash": manifest.config_hash,
               "analysis_script_hash": manifest.analysis_script_hash,
               "manifest": manifest.canonical()}
        with self._path.open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return rid

    def verify_resume(self, manifest: RunManifest) -> None:
        """Raise unless this manifest is exactly the one committed for its T0 (blocks a
        silent re-rank resuming as the pre-registered run)."""
        existing = self.committed(manifest.t0_ms)
        if existing is None:
            raise ValueError(f"no committed run for T0={manifest.t0_ms}; cannot resume an "
                             "un-pre-registered run")
        if existing["run_id"] != manifest.run_id():
            raise ValueError("live manifest != committed manifest for this T0 — a re-rank or "
                             "config drift. Refusing to resume (clean-OOS contract).")


@dataclass(frozen=True, slots=True)
class Results:
    """The measured inputs to the decision rule (computed by the pre-committed analysis
    script from realized fill prices only)."""

    reached_min_n: bool          # nominal AND effective-n floors met
    n_effective: int
    top_minus_control_ci_low: float    # bps, block-bootstrap 95%
    top_minus_control_ci_high: float
    top_vs_poolmean_significant: bool  # top significantly beats the pool-mean null
    maxdd: float                 # negative
    depth_capped_survives: bool  # edge survives at target notional under the depth cap
    max_single_contrib_frac: float


@dataclass(frozen=True, slots=True)
class Verdict:
    decision: Decision
    reasons: tuple[str, ...]


def decide(cfg: ExperimentConfig, r: Results) -> Verdict:
    """The pre-committed numeric rule (§v4.3). Read ONCE, after min-n, against these
    fixed thresholds. INCONCLUSIVE defaults to NO capital."""
    if not r.reached_min_n:
        return Verdict("INCONCLUSIVE", ("min-n not reached — no verdict may be read (no peeking)",))

    reasons: list[str] = []
    # hard NO-GO conditions
    if r.top_minus_control_ci_high <= 0:
        reasons.append("top−control CI entirely ≤ 0: no edge")
    if not r.top_vs_poolmean_significant:
        reasons.append("top ≈ pool-mean: ranking adds nothing (just follow everyone)")
    if not r.depth_capped_survives:
        reasons.append("edge does not survive the depth cap at target notional")
    if r.maxdd < cfg.maxdd_bound:
        reasons.append(f"maxDD {r.maxdd:.1%} breaches bound {cfg.maxdd_bound:.1%}")
    if r.max_single_contrib_frac > cfg.max_single_contrib_frac:
        reasons.append(f"single wallet/coin supplies {r.max_single_contrib_frac:.0%} of the "
                       f"spread (> {cfg.max_single_contrib_frac:.0%} cap)")
    if reasons:
        return Verdict("NO_GO", tuple(reasons))

    # GO requires the CI lower bound to clear the MAR above the cost floor
    if r.top_minus_control_ci_low >= cfg.mar_bps:
        return Verdict("GO", (
            f"top−control CI lower bound +{r.top_minus_control_ci_low:.1f}bp ≥ MAR "
            f"+{cfg.mar_bps:.1f}bp; beats pool-mean; survives depth cap; DD within bound",))
    # CI straddles the MAR at the horizon → underpowered, not a pass
    return Verdict("INCONCLUSIVE", (
        f"CI lower bound +{r.top_minus_control_ci_low:.1f}bp < MAR +{cfg.mar_bps:.1f}bp "
        "(straddles): underpowered, NOT a pass → no capital",))
