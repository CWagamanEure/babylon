# Audit 18 — GO/NO-GO gate & pre-registration integrity  (agent: 18_gate_preregistration)

## Summary
I audited the gate (`experiment.decide`/`_rule`, `measure.measure`, `stats/gate.py`,
`stats/metrics.py`, `stats/decay.py`) plus the selection→manifest path
(`scheduler.py`, `selection.py`, `followable.py`) and the live glue (`main.py`,
`runner.py`). The hash-chained registry and config-binding are solid and the
*selection score does not leak into the gate in code*. BUT the read-once enforcement
has a real hole that enables **optional stopping into a false GO** (F1), the decision
log does not actually bind the numeric Results it certifies (F2), and the whole
realized-PnL→gate pipeline is **unwired** so the load-bearing "gate reads realized
PAPER fills" claim is presently vacuous (F3). Top severity: HIGH (an operator-driven
false-GO path that the design explicitly claims to prevent).

## Findings

### F1 — Read-once guard ignores INCONCLUSIVE verdicts → optional-stopping into a false GO  [HIGH]
- **Where:** `src/babylon/follow/experiment.py:299-311` (`decide`), guard at `:305-308`; rule at `:333` (`_rule` straddle→INCONCLUSIVE); `:300` (min-n→INCONCLUSIVE).
- **Blast radius:** gate-false-GO (the CRITICAL class; rated HIGH because it requires repeated operator invocation rather than a single call).
- **Failure scenario:** The read-once guard refuses a second read only when a prior
  logged verdict is `!= "INCONCLUSIVE"`:
  ```python
  if body["run_id"] == run_id and body["verdict"] != "INCONCLUSIVE":
      raise ValueError(... "read-once: refusing a second read")
  ```
  Both the min-n branch (`:300`) and the straddle branch (`_rule` returning
  `INCONCLUSIVE` at `:333`) log `"INCONCLUSIVE"`. So once `min_n` is reached, if the
  bootstrap CI lower bound straddles MAR (`mar_bps`=8), the verdict is INCONCLUSIVE and
  **does not lock the run**. The operator can call `decide()` again weeks later as more
  round-trips accumulate; the block-bootstrap CI lower bound (`measure`, seed=0,
  deterministic on a *growing* sample) wanders, and the first time it crosses +8bp the
  call returns and logs **GO** (and only then locks). That is textbook optional
  stopping / peeking, which inflates the false-positive rate precisely in the marginal
  regime (edge near MAR) where it does the most damage. `horizon_cap_days` exists in the
  config but is **only validated (`:78`), never enforced in `decide()`**, so there is no
  time bound on the peeking either, and there is no alpha-spending / group-sequential
  accounting.
- **Why it's real (not theoretical):** `decide()`'s own docstring (`:284-287`) claims
  "a second post-min-n read for the same run is refused, so the verdict cannot be
  peeked/optional-stopped"; `docs/LIVE_FOLLOW.md` §v4.3 mandates "no peeking … one
  pre-declared extension max." The code enforces neither for the INCONCLUSIVE→GO path:
  no read counter, no extension cap, no horizon enforcement. The min-n and straddle
  INCONCLUSIVEs are indistinguishable to the guard, and nothing dedupes repeated
  INCONCLUSIVE reads (each appends a fresh record with a free-form `results_hash`).
- **Confidence:** high (logic is fully determined by the four cited lines).
- **Fix sketch:** Lock the run on the FIRST post-min-n read regardless of verdict —
  i.e. once `r.n_nominal >= cfg.min_n_nominal and r.n_effective >= cfg.min_effective_n`,
  log a terminal verdict and refuse any further read for that `run_id` (drop the
  `!= "INCONCLUSIVE"` exception for post-min-n reads; keep peeking allowed only for the
  pre-min-n "not reached" log). If a single pre-declared extension is intended, encode
  it as an explicit, counted, alpha-adjusted second look rather than unlimited re-reads.

### F2 — `results_hash` is caller-supplied and unverified; Results never committed to the chain → GO not re-derivable, doctored inputs undetectable  [HIGH]
- **Where:** `src/babylon/follow/experiment.py:280-282` (`decide` signature), `:300`/`:310` (`_log_read` calls), `:347-348` (`_log_read`); `Results` dataclass `:253-271` has no `canonical()`/`hash()` (only `ExperimentConfig`/`RunManifest` do).
- **Blast radius:** gate integrity / re-derivability — removes the guard that would catch a fabricated or false GO.
- **Failure scenario:** `decide()` takes `results_hash` as an opaque string and only
  writes it into the decision log; it is **never** checked against `r` (there is no
  `assert results_hash == sha(canonicalize(r))`, and `Results` has no canonicalizer).
  The Results themselves are **not stored** in the log (only `run_id`, `results_hash`,
  `verdict`). Consequences: (a) the GO cannot be re-derived from the committed artifacts
  — the numeric inputs that produced it are absent; (b) an operator can feed manipulated
  Results (e.g. an inflated `top_minus_control_ci_low`) while logging any "clean-looking"
  `results_hash`, or simply a hash that doesn't match the Results, and nothing detects
  the mismatch. The hash-chain protects the *sequence* of records but not the *binding*
  between the certified verdict and the numbers behind it.
- **Why it's real:** The chain verification (`_read_chained`, `:165-179`) only checks
  `prev`/`rec_hash` continuity of the stored bodies; it has no view of `Results`. Tests
  pass arbitrary `results_hash="rh"/"r1"/"r2"` (`tests/test_experiment.py:106-129`),
  confirming it is decorative.
- **Confidence:** high.
- **Fix sketch:** Give `Results` a `canonical()`/`hash()` (mirroring `RunManifest`),
  store the full canonical Results in the decision-log body, and in `decide()` assert
  `results_hash == r.hash()` before logging — so the verdict is bound to, and
  re-derivable from, the exact committed numbers.

### F3 — Realized-PnL→gate pipeline is UNWIRED; the "gate reads realized PAPER fills" boundary is vacuous, not verified  [MED]
- **Where:** `measure.measure`/`experiment.decide` are invoked only in `tests/` (grep: no caller in `src/`); `runner.py` journals equity/targets (`:339-341`) but never computes per-round-trip `top`/`control` arrays nor calls the gate; the selection-score fn `followable.followable_returns` is referenced **only** by `selection.SelectionAdapter.returns_fn` (`:56-63`).
- **Blast radius:** gate-false-GO risk **deferred to unbuilt code** (informational, but it is the audit's load-bearing claim).
- **Failure scenario / status:** The prior audit's load-bearing claim is "the gate reads
  realized PAPER fills, not the selection score." In code the selection score
  (`followable_returns` on the wallet's OWN historical train fills, priced at lag, used
  for Sortino-ranking + Kelly weights in `scheduler.select_roster`) is **never** passed
  to `measure()`. So there is no selection-leak path — but there is also no
  realized-paper-fill path: `measure()` accepts arbitrary `top`/`control` arrays, and
  nothing in `src/` produces them from the journal. The forward measurement→`Results`
  step is a future MANUAL action. Therefore the boundary holds *vacuously* (nothing
  feeds the gate), and the real risk is that whoever wires it later could mistakenly feed
  `followable_returns` (the selection quantity) instead of journaled paper round-trips —
  which would be a true selection-into-gate leak and a false GO. This cannot be ruled in
  or out by reading today's code because the code does not exist.
- **Why it's real:** confirmed by absence — no `src/` reference to `measure(`/`decide(`
  outside their definitions, and `runner.py` has no round-trip/control/gate symbols.
- **Confidence:** high (on the unwired status); the eventual-leak risk is medium and
  unresolvable until the wiring is written.
- **Fix sketch:** When wiring forward PnL to the gate, build `top`/`control` strictly
  from journaled PAPER fills (our own fill prices at/after T0), add a test asserting the
  gate inputs are NOT derived from `followable_returns`/selection, and have `decide()`
  certify the journal segment hash so the provenance is auditable (ties to F2).

### F4 — No multiple-comparison control across roll sub-periods / execution arms; per-period run_id vs an un-meetable per-period min-n  [MED]
- **Where:** `scheduler.roll` (`:106-132`) registers a NEW manifest/`run_id` every roll (new roster ⇒ new `RunManifest.canonical` ⇒ new `run_id`); `decide()` binds to ONE `run_id` (`:290-297`); config carries no family-wise-correction field (`ExperimentConfig`, `:34-65`); `also_run_uncapped=True` and `execution ∈ {retail, validator}` define extra arms.
- **Blast radius:** gate-false-GO if the gate is read per-period or per-arm and the best is taken (uncorrected max-over-arms).
- **Failure scenario:** `min_n_nominal=1500` round-trips is implausible within a single
  14-day follow window on a ~50-wallet roster, so a verdict must be read on round-trips
  **aggregated across many sub-periods/rosters** — yet every roll commits a *different*
  `run_id`, and the protocol never defines which `run_id` the aggregate verdict binds to,
  nor corrects for testing the gate across transitions. Likewise retail-vs-validator and
  capped-vs-uncapped are separate committable configs (distinct `config_hash`→`run_id`);
  reading each and reporting the GO is an uncorrected max over arms. The doc names retail
  "primary," but `decide()` will GO on whatever `cfg` is committed and bound — no code
  enforces single-arm or applies a Bonferroni/sequential correction.
- **Why it's real:** `run_id` sensitivity to roster is proven by
  `tests/test_experiment.py:59-64`; nothing in `decide`/`_rule` references a comparison
  count or a horizon. This is a pre-registration design gap that becomes exploitable once
  the (F3) wiring exists.
- **Confidence:** medium (the per-period registration is concrete; the harm depends on
  the unbuilt aggregation/reading procedure).
- **Fix sketch:** Pre-register exactly ONE primary arm and ONE aggregation rule mapping
  the multi-roster forward sample to a single decision `run_id` (e.g. a parent
  experiment_id), and if multiple arms are read, pre-declare an alpha split.

## What I checked and could NOT fault (clean)
- **Hash-chain / tamper-evidence:** `_append_chained`/`_read_chained` (`:144-179`) verify
  `prev`/`rec_hash` continuity and re-derive every `run_id` from the stored manifest
  (`Registry._committed` `:199-201`, `latest` `:222-223`); a hand-edited body or silent
  re-rank is caught (test `:73-89`). Append is under `fcntl.LOCK_EX` + `fsync`.
- **Config binding / no post-hoc threshold tweak:** `decide` recomputes `cfg.hash()` and
  refuses a mismatch vs the committed `config_hash` (`:295-297`); `Registry.register`
  refuses a second, different manifest at the same T0 (`:231-237`). MAR/maxdd/concentration
  thresholds are frozen in the hashed config.
- **min-n recompute:** `decide` recomputes the floor from the measured `n_nominal`/
  `n_effective` and ignores any self-reported bool (`:299-303`); a great CI below min-n is
  forced INCONCLUSIVE (test `:117-121`). (The *peeking* hole is F1, not this.)
- **Selection→gate code separation:** `followable_returns` (selection) and `measure`
  (gate) share no call path; the Sortino EPS-floor (`scheduler._sortino` `:50`) and seam
  guard (`followable.followable_returns` `before_ms` `:113-114`, `_close_at` no-look-ahead
  `:40-50`) are on the SELECTION side only — an offline seam/disposition bug there biases
  *power*, not the gate, given F3.
- **Determinism:** `block_bootstrap_ci`/`effective_n`/`max_drawdown` (`measure.py`) and
  `gate.log_growth_gate` are seed-fixed and pure; given fixed inputs the verdict is
  reproducible. (Re-derivability still fails at the artifact level — F2.)
- **`stats/gate.py`, `stats/decay.py`:** not on the forward decision path (`gate.py`/
  `decay.py` are unreferenced by `decide`); the active gate is `experiment._rule`. Noted
  for completeness; no defect that reaches the forward GO.
