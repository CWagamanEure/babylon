"""Pre-registration harness for the forward copy-trade paper experiment.

Encodes docs/LIVE_FOLLOW.md §v4.3/4.4: ONE immutable numeric config + an immutable
run_id + a pre-committed numeric decision rule + an append-only, hash-chained registry
and decision log. The point is that this forward run cannot be re-litigated the way the
backtest investigation was — every knob is fixed before T0, the team runs blind to PnL
until min-n, and the verdict is read ONCE against fixed thresholds, with both the config
binding and the read-once property ENFORCED (not honor-system).

The gate is on the DIRECTIONAL (deployed) per-round-trip top−control return — NOT the
portfolio Sharpe (underpowered on a months horizon) and NOT the neutralized series
(the fragile variant). See §v4.2.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Execution = Literal["retail", "validator"]
Decision = Literal["GO", "NO_GO", "INCONCLUSIVE"]
_GENESIS = "0" * 64


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Every knob resolved to a number BEFORE T0. `retail` execution is the binding
    primary; `validator` is a labeled optimistic upside bound, never the headline."""

    execution: Execution
    universe_hash: str
    eligible_pool: str
    train_days: int
    follow_days: int
    roll_cadence_days: int
    min_hold_ms: int             # SELECTION skill only — never filters the live copy
    min_positions: int
    beta: float                  # diagnostic neutralization ratio (gate is directional)
    gross_target: float
    max_coin_frac: float
    max_wallet_frac: float
    also_run_uncapped: bool
    lag_bucket_ms: int           # the SINGLE headline lag
    fee_bps: float
    impact_bps: float
    max_depth_frac: float
    target_notional_usd: float
    primary_control: str         # "pool_mean"
    secondary_controls: tuple[str, ...]
    min_n_nominal: int
    min_effective_n: int
    horizon_cap_days: int
    mar_bps: float               # minimum acceptable net return (above cost floor) for GO
    maxdd_bound: float           # negative
    max_single_contrib_frac: float
    cost_floor_bps: float        # the realistic round-trip cost; MAR must clear it
    # --- selection signal (default = the original round-trip path; "markout" = the validated
    #     fixed-horizon edge, see audit/EDGE_INVESTIGATION.md). SELECTION-only: cannot fake a GO.
    selection_signal: str = "roundtrip"   # "roundtrip" | "markout"
    markout_horizon_ms: int = 0           # fixed-horizon window (markout only); 6h = 21_600_000
    selection_rank: str = "sortino"       # "sortino" | "trimmed_mean"
    # EXECUTOR entry delay after detecting a wallet's open — DECOUPLED from `lag_bucket_ms`
    # (which is the conservative SELECTION + GATE measurement lag). Default 0 = enter as soon as
    # detected; the real entry lag then emerges from the rate-limited poll sweep (~1.05s/wallet →
    # ~30-60s across the roster ≈ the study's 60s column). We execute as fast as viable but still
    # SELECT/JUDGE at the conservative 15-min mark; realized fills reveal if fast entry pays.
    entry_lag_ms: int = 0
    # harvest execution (markout only): fractional-Kelly scalar for tail-aware per-event sizing
    # (bet ∝ trimmed_mean / downside_dev · this). <1 controls drawdown; the validated lever.
    harvest_kelly_frac: float = 0.5
    # per-event base notional as a FRACTION of the book (decoupled from target_notional_usd, a
    # per-position legacy number). Small so the tail-aware ratio lands BELOW the per-coin cap →
    # the risk differentiation actually shows instead of all events clamping to the cap.
    harvest_base_frac: float = 0.01
    # loosens ONLY the ledger's per-coin + gross caps (NOT tranche sizing, which stays pegged to
    # max_coin_frac·budget) for a paper MEASUREMENT run: at a $1000 book the gross cap saturates
    # during active periods and CANCELS later opens by arrival time, so the harvested set becomes a
    # biased subsample of conviction opens. bps are scale-free (the gate reads bps, not $), so
    # raising the caps lets ~every open through — unbiased coverage — without distorting the CI.
    harvest_cap_mult: float = 1.0
    # a PENDING harvest that can't enter within this long past its target (chronically stale book)
    # is cancelled — a late entry harvests a contaminated window + it leaks memory/cap room.
    # 0 = disabled. markout uses 30 min (2× the 15-min selection mark).
    harvest_max_entry_lag_ms: int = 0
    # gate CI knobs — PRE-REGISTERED (hashed into the run) so they can't be tuned post-hoc to
    # collapse the interval into a fake GO. `gate_boot_seed`/`gate_n_boot` drive the edge-over-field
    # cluster bootstrap; `gate_block` is the circular block length for the realized-net-PnL
    # bootstrap (harvests are serially correlated → i.i.d. resampling would understate its CI).
    gate_boot_seed: int = 0
    gate_n_boot: int = 2000
    gate_block: int = 10

    def validate(self) -> None:
        assert self.execution in ("retail", "validator")
        assert 0 < self.train_days and 0 < self.follow_days and 0 < self.roll_cadence_days
        assert self.min_positions >= 1 and self.min_hold_ms >= 0
        assert 0 < self.gross_target <= 5
        assert 0 < self.max_coin_frac <= 1 and 0 < self.max_wallet_frac <= 1
        assert self.lag_bucket_ms >= 0 and self.fee_bps >= 0 and self.impact_bps >= 0
        assert self.entry_lag_ms >= 0, "executor entry delay cannot be negative"
        assert 0 < self.max_depth_frac <= 1 and self.target_notional_usd > 0
        assert self.primary_control == "pool_mean", "primary control must be the pool-mean null"
        assert self.min_n_nominal >= 1 and self.min_effective_n >= 1
        assert self.min_effective_n <= self.min_n_nominal, "effective-n floor cannot exceed nominal"
        assert self.horizon_cap_days > 0
        assert self.maxdd_bound < 0
        assert 0 < self.max_single_contrib_frac < 1, "concentration gate must be < 100%"
        assert len(self.secondary_controls) >= 1, "need ≥1 falsification control"
        assert math.isfinite(self.beta)
        # economic floor: a GO must clear realistic cost by a real margin
        assert self.cost_floor_bps >= 0 and self.mar_bps >= 1.0, "MAR must be a real ≥1bp margin"
        assert self.selection_signal in ("roundtrip", "markout")
        assert self.selection_rank in ("sortino", "trimmed_mean")
        if self.selection_signal == "markout":
            assert self.markout_horizon_ms > 0, "markout signal needs a positive horizon_ms"
        assert 0 < self.harvest_kelly_frac <= 1, "fractional-Kelly scalar must be in (0, 1]"
        assert 0 < self.harvest_base_frac <= 1, "harvest base fraction must be in (0, 1]"
        assert self.harvest_cap_mult >= 1.0, "cap multiplier only loosens (>=1); never tightens"
        assert self.harvest_max_entry_lag_ms >= 0, "entry-lag deadline cannot be negative"
        assert self.gate_n_boot >= 200, "gate bootstrap needs ≥200 resamples for a stable CI"
        assert self.gate_block >= 1, "gate block length must be ≥1"

    def canonical(self) -> str:
        d = asdict(self)
        d["secondary_controls"] = sorted(self.secondary_controls)
        return json.dumps(d, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def hash(self) -> str:
        return _sha(self.canonical())


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Frozen at each sub-period's T0. The run_id is the experiment's identity; a
    re-ranked roster or any config change produces a different run_id. Built FROM a
    validated config (config_hash recomputed internally, not trusted as input)."""

    t0_ms: int
    roster: tuple[str, ...]
    edge_weights: dict[str, float]
    train_cutoff_tids: dict[str, int]
    config_hash: str
    analysis_script_hash: str

    def validate(self) -> None:
        assert self.roster, "empty roster"
        assert set(self.roster) == set(self.edge_weights) == set(self.train_cutoff_tids), \
            "roster / weights / tids must cover the same wallets"
        for w in self.edge_weights.values():
            assert math.isfinite(w) and w >= 0, "weights must be finite, non-negative"

    @classmethod
    def build(cls, *, t0_ms: int, edge_weights: dict[str, float],
              train_cutoff_tids: dict[str, int], config: ExperimentConfig,
              analysis_script_hash: str) -> RunManifest:
        config.validate()
        m = cls(t0_ms=t0_ms, roster=tuple(sorted(edge_weights)), edge_weights=dict(edge_weights),
                train_cutoff_tids=dict(train_cutoff_tids), config_hash=config.hash(),
                analysis_script_hash=analysis_script_hash)
        m.validate()
        return m

    def canonical(self) -> str:
        return json.dumps(
            {
                "t0_ms": self.t0_ms,
                "roster": sorted(self.roster),
                "edge_weights": {k: self.edge_weights[k] for k in sorted(self.edge_weights)},
                "train_cutoff_tids": {
                    k: self.train_cutoff_tids[k] for k in sorted(self.train_cutoff_tids)},
                "config_hash": self.config_hash,
                "analysis_script_hash": self.analysis_script_hash,
            },
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        )

    def run_id(self) -> str:
        return "run_" + _sha(self.canonical())[:24]


def _append_chained(path: Path, payload: dict[str, object]) -> str:
    """Append a hash-chained record under an exclusive lock. Returns the record hash."""
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
            prev = json.loads(lines[-1])["rec_hash"] if lines else _GENESIS
            body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
            rec_hash = _sha(prev + body)
            f.write(json.dumps({"prev": prev, "rec_hash": rec_hash, "body": body},
                               sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
            return rec_hash
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _read_chained(path: Path) -> list[dict[str, object]]:
    """Read + verify the hash chain; raise if tampered. Returns the parsed bodies."""
    if not path.exists():
        return []
    out: list[dict[str, object]] = []
    prev = _GENESIS
    for ln in path.read_text().splitlines():
        if not ln.strip():
            continue
        rec = json.loads(ln)
        if rec["prev"] != prev or _sha(prev + rec["body"]) != rec["rec_hash"]:
            raise ValueError(f"registry chain broken at {rec.get('rec_hash')}: tampered")
        out.append(json.loads(rec["body"]))
        prev = rec["rec_hash"]
    return out


class Registry:
    """Append-only, hash-chained registry. register() commits a manifest under a lock;
    every read re-derives the run_id from the stored manifest and verifies the chain, so
    a hand-edited manifest or a silent re-rank is detected. One manifest per T0."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _committed(self, t0_ms: int) -> RunManifest | None:
        hits = []
        for body in _read_chained(self._path):
            man = body["manifest"]
            assert isinstance(man, dict)
            m = RunManifest(
                t0_ms=man["t0_ms"], roster=tuple(man["roster"]),
                edge_weights=man["edge_weights"], train_cutoff_tids=man["train_cutoff_tids"],
                config_hash=man["config_hash"], analysis_script_hash=man["analysis_script_hash"])
            if m.run_id() != body["run_id"]:
                raise ValueError(
                    f"stored run_id {body['run_id']} != re-derived {m.run_id()}: tampered")
            if m.t0_ms == t0_ms:
                hits.append(m)
        if len(hits) > 1:
            raise ValueError(f"multiple committed manifests for T0={t0_ms}: corrupt registry")
        return hits[0] if hits else None

    def committed(self, t0_ms: int) -> RunManifest | None:
        return self._committed(t0_ms)

    def latest(self) -> RunManifest | None:
        """The most recent committed sub-period manifest (max T0) — what a restart resumes,
        re-deriving + chain-verifying every record on the way (tamper-evident)."""
        best: RunManifest | None = None
        for body in _read_chained(self._path):
            man = body["manifest"]
            assert isinstance(man, dict)
            m = RunManifest(
                t0_ms=man["t0_ms"], roster=tuple(man["roster"]),
                edge_weights=man["edge_weights"], train_cutoff_tids=man["train_cutoff_tids"],
                config_hash=man["config_hash"], analysis_script_hash=man["analysis_script_hash"])
            if m.run_id() != body["run_id"]:
                raise ValueError(f"stored run_id {body['run_id']} != re-derived: tampered")
            if best is None or m.t0_ms > best.t0_ms:
                best = m
        return best

    def register(self, manifest: RunManifest) -> str:
        manifest.validate()
        rid = manifest.run_id()
        existing = self._committed(manifest.t0_ms)
        if existing is not None:
            if existing.run_id() != rid:
                raise ValueError(
                    f"T0={manifest.t0_ms} already committed as {existing.run_id()}; "
                    f"refusing {rid} (a re-rank/config change). Pre-registration is immutable.")
            return rid
        _append_chained(self._path, {
            "run_id": rid,
            "manifest": json.loads(manifest.canonical()),
        })
        return rid

    def verify_resume(self, manifest: RunManifest) -> None:
        existing = self._committed(manifest.t0_ms)
        if existing is None:
            raise ValueError(f"no committed run for T0={manifest.t0_ms}; cannot resume")
        if existing.run_id() != manifest.run_id():
            raise ValueError("live manifest != committed manifest for this T0 — a re-rank or "
                             "config drift. Refusing to resume (clean-OOS contract).")


@dataclass(frozen=True, slots=True)
class Results:
    """Measured inputs to the decision rule, computed by the pre-committed analysis script
    from realized fill prices only. n's are reported but the gate RECOMPUTES min-n."""

    n_effective: int
    n_nominal: int
    top_minus_control_ci_low: float    # bps, block-bootstrap 95%
    top_minus_control_ci_high: float
    top_vs_poolmean_significant: bool
    maxdd: float
    depth_capped_survives: bool
    max_single_contrib_frac: float
    # realized net-of-cost profitability (markout gate only): block-bootstrap CI of the realized
    # neutralized per-harvest return. Because we EXECUTE faster than we MEASURE (entry_lag_ms≈0 vs
    # the 15-min selection/gate lag), profitability is judged on REALIZED fills — real fast
    # execution + real cost — not the candle mark. GO requires ci_low>0 (we actually make money,
    # not just beat a losing field). 0.0/0.0 default = roundtrip path or no realized harvests yet.
    realized_net_ci_low: float = 0.0
    realized_net_ci_high: float = 0.0

    def validate(self) -> None:
        assert self.top_minus_control_ci_low <= self.top_minus_control_ci_high, "inverted CI"
        assert self.realized_net_ci_low <= self.realized_net_ci_high, "inverted realized-net CI"
        assert self.n_effective >= 0 and self.n_nominal >= 0
        for x in (self.top_minus_control_ci_low, self.top_minus_control_ci_high, self.maxdd,
                  self.realized_net_ci_low, self.realized_net_ci_high):
            assert math.isfinite(x)


@dataclass(frozen=True, slots=True)
class Verdict:
    decision: Decision
    reasons: tuple[str, ...]


def decide(
    cfg: ExperimentConfig, r: Results, *, registry: Registry, run_id: str,
    decision_log: Path, results_hash: str,
) -> Verdict:
    """The pre-committed numeric rule (§v4.3), ENFORCED: the config is verified against the
    committed run, min-n is RECOMPUTED (not trusted), and the read is logged READ-ONCE in a
    hash-chained decision log — a second post-min-n read for the same run is refused, so the
    verdict cannot be peeked/optional-stopped or have its thresholds lowered post-hoc."""
    r.validate()
    # 1. bind cfg to the committed run (no post-hoc threshold tweaking)
    committed = next((m for m in (registry.committed(t) for t in _t0s(registry))
                      if m and m.run_id() == run_id), None)
    if committed is None:
        raise ValueError(f"run_id {run_id} not in the registry — cannot decide an "
                         "un-pre-registered run")
    if cfg.hash() != committed.config_hash:
        raise ValueError("cfg does not match the committed config_hash — refusing "
                         "(post-hoc threshold change)")
    # 2. recompute the min-n gate from the measured n's (don't trust a self-reported bool)
    if r.n_nominal < cfg.min_n_nominal or r.n_effective < cfg.min_effective_n:
        _log_read(decision_log, run_id, results_hash, "INCONCLUSIVE")
        return Verdict("INCONCLUSIVE", (
            f"min-n not reached (nominal {r.n_nominal}/{cfg.min_n_nominal}, "
            f"effective {r.n_effective}/{cfg.min_effective_n}) — no verdict (no peeking)",))
    # 3. read-once: refuse a second post-min-n read for this run
    for body in _read_chained(decision_log):
        if body["run_id"] == run_id and body["verdict"] != "INCONCLUSIVE":
            raise ValueError(f"run {run_id} already has a final verdict {body['verdict']} "
                             "logged — read-once: refusing a second read")
    v = _rule(cfg, r)
    _log_read(decision_log, run_id, results_hash, v.decision)
    return v


def _rule(cfg: ExperimentConfig, r: Results) -> Verdict:
    reasons: list[str] = []
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
    markout = cfg.selection_signal == "markout"
    if markout and r.realized_net_ci_high < 0:
        reasons.append("realized net-of-cost PnL CI entirely < 0: unprofitable after real "
                       "execution cost (beats a losing field but still loses money)")
    if reasons:
        return Verdict("NO_GO", tuple(reasons))
    selection_pass = r.top_minus_control_ci_low >= cfg.mar_bps
    profit_pass = (not markout) or r.realized_net_ci_low > 0.0
    if selection_pass and profit_pass:
        note = ("; realized net-of-cost CI lower bound "
                f"+{r.realized_net_ci_low:.1f}bp > 0" if markout else "")
        return Verdict("GO", (
            f"top−control CI lower bound +{r.top_minus_control_ci_low:.1f}bp ≥ MAR "
            f"+{cfg.mar_bps:.1f}bp; beats pool-mean; survives depth cap; DD within bound" + note,))
    if selection_pass and not profit_pass:
        return Verdict("INCONCLUSIVE", (
            f"selection edge clears MAR (+{r.top_minus_control_ci_low:.1f}bp) but realized "
            f"net-of-cost CI [{r.realized_net_ci_low:.1f}, {r.realized_net_ci_high:.1f}]bp does "
            "not exclude 0: profitability not yet proven → no capital",))
    return Verdict("INCONCLUSIVE", (
        f"CI lower bound +{r.top_minus_control_ci_low:.1f}bp < MAR +{cfg.mar_bps:.1f}bp "
        "(straddles): underpowered, NOT a pass → no capital",))


def _t0s(registry: Registry) -> list[int]:
    out = []
    for b in _read_chained(registry._path):  # noqa: SLF001
        man = b["manifest"]
        assert isinstance(man, dict)
        out.append(int(man["t0_ms"]))
    return out


def _log_read(path: Path, run_id: str, results_hash: str, verdict: str) -> None:
    _append_chained(path, {"run_id": run_id, "results_hash": results_hash, "verdict": verdict})
