# Adversarial Quant Audit — SUMMARY (20/20 complete)

Ranked by **blast radius**: false-GO (fabricates an edge) > offline-estimate inflation > selection-power
(biases toward INCONCLUSIVE) > hygiene. Each item links its `findings/NN_*.md`.

**Status: all 20 agents complete.** The whole audit never touched host RAM unsafely — no crash, no
monthly parquet loaded; Audit 07's probe even self-aborted twice at ~1.6 GB RSS and recovered rather
than risk the 8 GB box (the scaffold's RAM discipline working as intended).

**One open question remains UNRESOLVED:** whether the net edge CI excludes zero at the live operating
point (Audit 07 couldn't complete the bootstrap cheaply enough on this box). To settle it, run the
edge sweep on the droplet or a bigger box — see Audit 07 below.

## The three cross-cutting headlines (read these first)

**H1 — The GO/NO-GO gate is not yet fed realized fills (the bridge is unwired).**
18-F3, 19, 10 independently found the realized-PnL → gate pipeline is unwritten. Right now that
means *nothing can emit a GO* (safe by vacuity) — but it also means the gate's central protection
("it reads realized paper fills, not the selection score") is currently **unverified in practice**.
When wired, it must be fed the spread-walked paper fills (19 confirms those are realistic), NOT a
spread-free candle markout. This is the single most important structural gap.

**H2 — The live deployed candidate pool is the FROZEN survivorship set, not the validated rolling
universe.** 01 (HIGH): the runner defaults to the ~1404 `long_hold_wallets.csv` — the same frozen,
performance-filtered set behind the discredited +159 bp number — while the leak-free rolling
`past_univ[k]` is only used offline. 05 corroborates (live eligibility differs from offline). The CSV
has no in-repo builder, so its past-only construction is unverifiable. **Escalates to false-GO** if
`measure→decide` is ever run over the in-sample window with the default candidates.

**H3 — Once wired, the gate has two false-GO holes.** 18-F1 (HIGH): the read-once guard ignores
INCONCLUSIVE verdicts → optional-stopping (peek, stay open, re-test) can walk into a false GO.
18-F2 (HIGH): the decision log certifies a Results object it doesn't bind/verify. Plus 18-F4 (MED):
uncorrected multi-arm/multi-roll comparison.

## Tier 1 — false-GO class (fix before any GO is trusted)
- **01** [HIGH] live pool = frozen survivor CSV, not rolling universe → `findings/01_universe.md`
- **18-F1** [HIGH] read-once ignores INCONCLUSIVE → optional-stopping into GO → `findings/18_gate.md`
- **18-F2** [HIGH] decision log doesn't bind/verify the Results it certifies → `findings/18_gate.md`
- **18-F3 / 19** [HIGH] realized-PnL→gate bridge unwired; gate could be fed candle markout → `findings/18_gate.md`, `findings/19_execution.md`

## Tier 2 — offline-estimate inflation (the headline edge is overstated)
- **07** [HIGH] selection runs OUTSIDE the bootstrap → the CI is computed on already-selected top-N arrays, ignoring selection uncertainty → reported CI is too narrow (overstates significance). Correct CI re-runs selection inside each draw. Zero-crossing at the live operating point left UNRESOLVED (probe killed at ~1.6 GB on the 8 GB box — re-run on the droplet) → `findings/07_bootstrap.md`
- **10** [HIGH] flat 8 bp cost < the system's own 9 bp fee-only RT (live models 21–40 bp) → "tradeable" claim inflated → `findings/10_cost.md`
- **03** [HIGH] 60 s lag changes only ~1.7% of legs at hourly candle res → sweep's lag-robustness is a quantization artifact; lag is a scalar not the measured ~50–120 s live distribution → `findings/03_lag.md`
- **19** [HIGH] pinned 60 s lag never applied in the live entry path → `findings/19_execution.md`

## Tier 3 — selection-power (capture is shadow + selection-only; biases toward INCONCLUSIVE)
- **16** [HIGH] re-derivability fix didn't land (run_id has no returns content-hash; MTM reads ephemeral book) → `findings/16_scorer.md`
- **14** [2×HIGH] `last_tid` cursor never built (replay storm double-counts last fill/coin); `rid` non-durable → post-restart round-trips silently dropped by store PK → `findings/14_ingest.md`
- **13** [HIGH] in-process `late_markout` survives — `process_due` marks at latest-only book, no due-vs-now guard → `findings/13_markout.md`
- **09** [HIGH] MTM-at-cutoff incompletely applied; capture eligibility still closed-RT gated; staleness censors the quiet open losers it targets → `findings/09_disposition.md`
- **06** [HIGH] Sortino EPS-floor fix incomplete — self-relative floor still lets small-n/low-dispersion wallets explode the rank → `findings/06_sortino.md`
- **05** [2×MED] live `≥20 raw-fill` gate absent from offline validation; capture still has closed-RT gate (known #6 not propagated to `capture/store.py`) → `findings/05_selection.md`

## Tier 3b — capture parity / durability (Wave B probes; selection-power)
- **15** [2×HIGH] store implements ONLY the `roundtrips` table — spec'd `open_state`/`wallets`/`meta` don't exist → restart loses all in-flight state (disposition fix silently reverts to closed-only); non-durable `rid` + PK + `INSERT OR IGNORE` drops post-restart round-trips. A passing test enshrines the bug. Confirms 14 from the store side → `findings/15_store.md`
- **11** [2×MED] leading-position hold-out is DEAD CODE in both paths: his export seeds `startPosition=0` uniformly (sign-flips a real −890 ZEC short into a phantom long); live scorer builds every CoinStepper at startpos=0 so the cold-start `valid=False` guard can never fire → `findings/11_startpos.md`
- **12** [MED] stepper internals bit-for-bit match `reconstruct` (6/6 pass), but live≡batch has an untested ordering gap: live releases same-ms fills in `(time,tid)` order, batch sorts by `time` only → boundary-crossing same-ms fills can reconstruct differently → `findings/12_stepper.md`

## Tier 4 — hygiene (MED/LOW)
- **20** [MED+LOW+NIT] tuple-key (#13) and float-residual (#15) fully guarded, determinism defused; residual offline full-month OOM in `convergence_his.reshape_month` (the reshape that swaps your box), split resume-after-crash drop, missing sort tie-break → `findings/20_engineering.md`
- **04** [MED×5] beta=1.245 no in-repo derivation (possible in-sample fit); single global beta; basket is equal-weight-all-coins not "liquid" → `findings/04_beta.md`
- **08** [MED×3] eligibility ranks on superset coin set; live trades coins selection couldn't price; basket major-inconsistency → `findings/08_coverage.md`
- **02** [LOW] seam filters key on `exit_t` but pricing reads `exit_t+lag` → ≤15 min post-seam sliver leaks into ranking skill → `findings/02_lookahead.md`
- **17** [LOW] no per-coin volume-share monitor (reflexivity); material only ~1–5% of near-touch depth at live notional → `findings/17_reflexivity.md`

## Clean bills (verified, no defect)
- Gate registry hash-chain, config binding, min-n recompute, selection/gate **code** separation (18).
- Pricing is strictly causal; candle `time` = open time (02). Index look-ahead **refuted** (04).
- Paper retail fill crosses spread, walks depth, fee+impact folded, validator wallet-price arm hard-blocked, no look-ahead (19).
- Aggressing-side, crossed-book, heap order, restart-drop logic clean (13). The ~3.5 GB/day dedup OOM is genuinely fixed (14).
- Tuple-key regression (#13) and float-residual exact-zero (#15) fully guarded; provider determinism holds (20).
- Stepper internals bit-for-bit match `reconstruct`, 6/6 tests pass (12).

## Recurring patterns the team should internalize
1. **Live ≠ validated.** Deployed pool (01), eligibility (05), cost (10), and lag (03, 19) all differ
   from what the offline edge was measured on. The validated number is not the deployed number.
2. **Known fixes not propagated to the capture path.** Closed-RT eligibility (05, 09), EPS floor (06),
   `last_tid` cursor (14), re-derivability hash (16) — each was fixed in one place, missed in another.
3. **The gate is structurally sound but operationally inert** — its protections are real, but it isn't
   yet fed, and two holes (optional-stopping, unbound Results) open once it is.

## What to fix before trusting the edge (ordered)
1. Wire realized paper fills → gate; assert the source is the spread-walked fill, never a candle mark (H1).
2. Point the live runner at the rolling `past_univ[k]`, or commit a verifiable builder for the 1404 CSV (H2/01).
3. Close the read-once INCONCLUSIVE hole + bind the Results object in the decision log (18-F1/F2).
4. Re-net the offline edge at a realistic per-coin cost (≥ fee-only 9 bp + spread) before quoting "tradeable" (10).
5. Then re-run the lag sweep at sub-candle resolution to confirm the edge isn't a quantization artifact (03).

_Capture-subsystem items (06,09,13,14,16) are all selection-power because CaptureScorer is shadow/
selection-only; fix opportunistically, not as gate blockers._
