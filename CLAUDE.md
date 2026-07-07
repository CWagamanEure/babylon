# Babylon — working instructions

## ⛔ THE OVER-NULLING GATE (highest priority — this overrides my default conservatism)

I have a demonstrated, recurring bias: I call findings **null / "no effect" / "dead" / "doesn't work"**
when the evidence only supports **"inconclusive / underpowered / positive-but-not-yet-significant."**
This has repeatedly buried real signals. It happens because every rigor tool I reach for (permutation
nulls, FDR, kill-gauntlets, code audits) is aimed at catching FALSE POSITIVES, and "not significant" is
the safe-sounding conclusion — so I drift there. **A p > 0.05 is NOT evidence of absence.**

### Hard gate: a null verdict must EARN the word. Default to "INCONCLUSIVE," never "no effect", unless ALL four exist:
1. **Point estimate + CI (not a p-value).** If the CI still admits an effect size we'd care about
   (e.g. CI = [−5, +45] when we care about +20), it is **inconclusive**, not null. Print the CI.
2. **Positive-control MDE ≤ the effect size we care about.** The pipeline must be *shown* able to recover
   an injected edge of the relevant size. If MDE ≫ the realistic edge, the test is **blind by construction**
   → inconclusive, full stop. (This is why "baseline persistence" is inconclusive, not negative.)
   ⚠️ **BUT "inconclusive" is not a permanent shield — the anti-ratchet rule.** If a design is structurally
   underpowered (MDE ≫ care-about is baked into the estimand, e.g. a 30-entry cohort against ±316 bp of beta),
   the obligation is to **build a powered design** (variance-reduce via neutralization, pool for N, pick the
   horizon by SNR) — NOT to re-run the blind instrument and relabel each failure "inconclusive." A test that
   *cannot fail* provides no evidence in EITHER direction. Once a genuine, powered attempt has been designed
   and it still returns a null with **MDE ≤ care-about**, that EARNS a **method-scoped negative** ("no edge
   *from this selector/method*") — which is a real, publishable conclusion, not perpetual limbo. If after honest
   effort no powered design is constructible from the data at hand, say *that* ("the available data cannot
   resolve this") and stop — do not keep looping the underpowered test.
3. **Cross-independent-unit combination run.** Individual cells are underpowered; N/N units leaning the
   same way (coins, folds, wallets) is a sign/aggregate test that can be significant where no single cell
   is. Run it BEFORE declaring null. Staring at one weak cell and never combining is the classic over-null.
4. **Construction-conservatism check.** Confirm the null band / test was not accidentally built *against*
   the finding (e.g. a null band aggregated at the wrong level and 3.5× too wide manufactures a false null).

If any of the four is missing → the verdict is **"inconclusive / underpowered,"** and I must surface the
positive point estimate and its direction, not bury it.

### Standing "steelman the positive" pass (as mandatory as the code audit)
Before finalizing ANY null/negative conclusion, run a dedicated adversarial pass whose ONLY job is to argue
the finding is REAL — and it must be a **separate agent** from the one that did the analysis (the analyzing
pass is the one prone to nulling). Report what it found. This pass has flipped conclusions before; it is not
optional.

### Symmetry (so this doesn't become over-claiming) — the OVER-CARRY hazard is equal to the over-null hazard
Positives still face the full false-positive gauntlet (permutation null, FDR, kill-gauntlet, replication).
The goal is **both** error directions gated equally — not trading one bias for the other. When I do call
something a live positive, it is honestly labeled with its significance status (e.g. "underpowered positive,
post-hoc horizon, not deployable") — suggestive ≠ established ≠ deployable.
⚠️ **The mirror failure — OVER-CARRY — actually happened (2026-07-04) and this rule now guards it explicitly.**
A residual that is (a) post-hoc-selected (the argmax of a horizon/K/metric search), (b) only present in the
uncontrolled descriptive layer while the *error-controlled* layer says nothing survives, and (c) at chance on
the cut that would matter for deployment, must be **DEMOTED to "unresolved residual, direction unknown," not
carried as a "live positive."** The "steelman the positive" pass (above) has a mandatory counterpart with
**equal standing: a "prosecute the positive / null the residual" pass** — a separate agent whose only job is
the benign-noise explanation (multiple-comparisons tally across the WHOLE arc, non-independence of units,
small-K selection variance, argmax-of-N-horizons). Run BOTH before finalizing.
**A tight null on the load-bearing quantity outweighs a downstream lean:** if the mechanism that MUST exist
(e.g. wallet-rank persistence, or per-wallet OOS predictiveness) is measured with a *tight CI around zero or
negative*, that is genuine evidence of ABSENCE and dominates a size-blind tail-cohort lean built on the same
data. Do not let the over-null gate suppress reporting a real, powered negative.

### The user's lever
For anything I call null, the user can ask: **"point estimate, CI, MDE, and cross-unit sign test?"** If I
can't produce all four, I have not earned the null. Treat that question as always-pending.

---

## Research conventions (see also memory: babylon-pitfalls, babylon-conventions)
- Report only out-of-sample, multiplicity-controlled numbers as results; never an in-sample figure.
- **Record findings before moving on.** At the END of each stage, before starting the next, update the
  findings ledger (`markout_study/docs/FINDINGS_LEDGER.md`, or the study's equivalent): question, method,
  calibrated result, caveats, artifacts. It is the accumulating, report-ready backbone — the user assembles
  the final report from it. Also register dead-ends (so we don't re-run them) and live underpowered positives
  (so they aren't lost). This is a required step, not optional.
- Standard flow for a new analysis: **architecture doc → agent-swarm audit → build → code audit →
  run → framing/steelman audit → update the findings ledger**. The last two steps are not optional (see gate above).
- **Reusable audit subagents** live in `.claude/agents/audit-*.md` (correctness, stats-rigor,
  firewall-leakage, data-integrity, determinism-repro, docs-consistency); they all follow the shared
  `audit/AUDIT_PROTOCOL.md` (resource safety, verify-before-report, blast-radius severity, no edits).
  Invoke by `subagent_type` for a swarm audit; add a run-specific scope note like `audit/00_GROUND_RULES.md`.
- Decimal/async/Parquet/logging conventions and known statistical pitfalls live in the memory files.

## Repo layout & the data pipeline (see docs/DATA_ARCHITECTURE.md for the full plan)

Two lanes, one firewall (never cross them): `src/babylon/` is the **deployable engine** (production code
only); `research/` is the **analysis workbench** (never imported into the engine, never shipped).

```
data/                        # gitignored (anchored /data/); large; all regenerable from S3 + code
  raw/fills/month=YYYYMM/day=YYYYMMDD/hourHH.parquet   # THE authoritative tape (majors node_fills)
  raw/fills/manifest.parquet + _manifest/*.json        # ingest checkpoint (leaf glob skips these)
  raw/bars/coin=…/           # 5-min close lattice (bars.py — still to build)
  follow/ , l2Book/          # existing live copy-trade + L2 data — leave as-is
research/data/               # the versioned research data layer
  ingest.py                  # S3 node_fills_by_block → data/raw/fills (THE only writer of the tape)
  schema.py                  # full fill contract (all node_fills fields) + DuckDB views; source of truth
  validate.py                # replay a month's counts vs the RESTORE_PLAN oracle (zhash/liq/transitions)
  db.py                      # connect() → DuckDB views over the parquet lake (query layer, no ETL)
markout_study/gate_a/        # frozen Gate-A v1.0 pipeline (consumes the tape; firewalled)
markout_study/discovery/     # frozen specs + audits — RESTORE_PLAN_v1.md is the ingest spec
```

**The fills tape (`data/raw/fills/`).** Restored from `s3://hl-mainnet-node-data/node_fills_by_block`
(requester-pays, us-east-1) per `markout_study/discovery/RESTORE_PLAN_v1.md`. It is the ONLY source
with per-wallet `startPosition` + block identity that Gate-A needs (the old cand2/cohort/his projections
dropped it — do NOT substitute them). Every node_fills field is captured (full liquidation struct incl markPx, both block timestamps);
monetary/size fields are stored as **exact strings** (px, sz, start_position, closed_pnl, fee,
builder_fee, liq_mark_px), cast to Decimal on demand — float is never authoritative.
`raw/` is immutable + archive-sourced; everything under `derived/` is a pure function of it + a code commit.

**Running / resuming ingest** (local; `.venv/bin/python`):
```
python -m research.data.ingest hour 20250801 12      # one object (stage-1 gate)
python -m research.data.ingest month 202508          # one month (~744 objects)
python -m research.data.ingest range 202508 202606   # full 2025-08 … 2026-06 window
python -m research.data.ingest manifest              # consolidate shards → manifest.parquet + report
```
Idempotent + crash-safe: an object is skipped iff its part exists AND a done-shard records the current
`SCHEMA_VERSION`+`code_commit`; parts land via atomic rename (no half-part reads as complete). **Just
re-run the same command after any crash** — it resumes from the manifest. Bump `SCHEMA_VERSION` in
`schema.py` to force re-ingest on a contract change. Validate a fresh full-month run against the recorded
oracle in RESTORE_PLAN §"MONTH GATE RESULT — 2025-08" (87.9M fills, zhash 18.2%, the transition counts).

⚠️ `hl_hist/*.csv.lz4` is per-coin **asset-context metadata** (funding/OI/px), NOT the fills tape.
