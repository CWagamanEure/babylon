# Harvest + Gate adversarial audit — agent tasks

Scope: everything built in the event-harvest arc (the validated markout strategy's live
execution + gate). You are an ADVERSARY: your job is to find the bug, not to bless the code.

## GROUND RULES (all agents)
- **RAM-SAFE.** Do NOT load monthly parquets or the whole 2431-wallet pool. Do NOT run the full
  edge-investigation scripts. You may run TARGETED `pytest tests/test_<x>.py` and read source.
  If you must exercise data, use ≤3 tiny synthetic frames. A prior 20-agent run OOM'd the box.
- **Environment:** run pytest via `.venv/bin/python -m pytest`. Working dir `/Users/corywagamaneure/bablyon`.
- **Blast-radius lens:** rank findings by whether they can fabricate a GO / mis-measure the edge
  (CRITICAL) vs merely lose power or crash (lower). The GATE (A5/A6) is the highest stakes.
- **Report format:** severity-ranked list. For each: `file:line`, one-sentence defect, and a
  CONCRETE failure scenario (inputs → wrong output). Distinguish CONFIRMED (you traced/ran it) from
  PLAUSIBLE. End with a one-line verdict: is this component sound? Keep it tight — findings, not prose.
- Do NOT edit code. Audit only.

## A1 — HarvestLedger state machine (`src/babylon/follow/harvest.py`)
Adversarial focus: can a tranche be harvested twice, lost, or mis-priced? Check: expiry is from
ENTRY FILL time not open/target; dedup by event_id; due_entries cap allocation (arrival-time
rationing, scale-to-fit, cancel-below-min — any double-count of gross/coin room?); the exact-zero
close vs float residue; on_exit_fill bps sign (long vs short); to_state/from_state roundtrip
(does a resumed OPEN tranche keep its expiry + entry_px so it still harvests?). Run test_harvest.py.

## A2 — HarvestRunner executor integration (`src/babylon/follow/harvest_runner.py`)
Adversarial focus: does the executor net stay == Σ active tranches? Exits are NORMAL (not
reduce-only) orders sized to −tranche contracts — verify offsetting cross-wallet tranches close
correctly and can't over/under-sell. Check: contracts map (leak on failed exit? restored on
resume?); cash booking sign; stale-book defer vs drop (entry stays PENDING, exit retried); the
async poll/tick loop + on_realized hook; checkpoint to_state/from_state. Run test_harvest_runner.py.

## A3 — Watcher open detection (`src/babylon/follow/watcher.py` `_detect_opens`, `on_opens`)
Adversarial focus: is live detection bit-identical to the study's `open_events`? Check the
per-poll seeding via each fill's startPosition (does a batch that STARTS mid-position spuriously
emit or miss an open?); dedup across overlapping polls (event_id = wallet:coin:entry_t — collision
or miss?); open-then-close within one poll; a MISSED prior fill (does startPosition re-anchor?);
ordering/tie-break. The mirror runner must be unaffected (sink=None). Run test_harvest_runner.py.

## A4 — Tail-aware sizing (`scheduler.tail_aware_notionals`, `_downside_dev`; `live._harvest_notionals`)
Adversarial focus: does sizing accidentally RE-RANK on edge (it must be a pure risk tilt)? Check
the ratio_cap/floor (blowup on ~0 downside?); non-positive-edge → 0; the harvest_base_frac
calibration (earlier degeneracy: base ≫ coin cap clamped all to cap — is it actually fixed?);
does the dd persistence claim (train→test ρ≈0.38, edge-orthogonal) in `scratch_conv/dd_persist.py`
hold up, or is the script biased (eligibility, look-ahead, pooling)? Run test_scheduler.py.

## A5 — Gate TOP arm + decide wiring (`src/babylon/follow/gate_feed.py`: neutralize_top, run_gate)
**HIGH STAKES.** Adversarial focus: can this fabricate a GO? Check neutralize_top sign (dir·β·basket
subtraction, long vs short); equity_curve / maxdd; contrib_by_wallet concentration; the element-wise
TOP−CONTROL pairing + truncation; results_hash binds to the read-once chain; is measure()'s
conditional block-bootstrap actually valid for the FORWARD test (or does it understate uncertainty)?
Run test_gate_feed.py.

## A6 — Gate CONTROL arm + cost symmetry (`gate_feed.field_control`, `run_gate_decision`)
**HIGHEST STAKES.** Adversarial focus: is the field CONTROL a valid null, or is it biased LOW (→
fake GO)? Check cost symmetry: TOP is realized-NET (cost in fills), CONTROL = field gross − cost_floor
— is that apples-to-apples, or does it advantage TOP? Eligibility (≥min_opens) match to selection;
the constant-broadcast pairing vs the study's selected_mean−field_mean; subsample bias (max_wallets
= deterministic prefix — biased?); does the field include the roster (should it)? window correctness.

## A7 — Live/CLI wiring (`src/babylon/follow/live.py`, `main.py` cmd_gate, `experiment.py` fields)
Adversarial focus: does harvest mode wire end-to-end and survive a roll/restart? Check the build
branch (markout→HarvestRunner, basket built + refreshed, sink set); reroll recomputes notionals +
KEEPS prior OPEN tranches (harvest them, don't drop); on_realized→journal wired only in harvest mode;
selection-aware candidate default; cmd_gate window=(t0,now)+run_id=latest; new config fields validated.
Run test_main.py.

## A8 — Strategy/measurement fidelity (cross-cutting; read, don't just test)
Adversarial focus: does the BUILT live system actually measure the VALIDATED quantity? Is
live ≡ validated by construction, or does the pipeline silently diverge? Check: the 6h/15min/trimmed-
mean/opens≥5/broad-pool operating point is faithfully wired; the harvest realizes the fixed-horizon
markout (not the null round-trip); neutralization basket ≡ the study's; any place the forward test
would measure something OTHER than "+30bp net over field". Name the biggest threat to the test's validity.
