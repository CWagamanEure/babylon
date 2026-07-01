# Audit 20 — Engineering: RAM/OOM & polars correctness  (agent: 20_engineering_ram_polars)

## Summary
I audited the data pipeline's OOM-safety and polars correctness: the tuple-key regression
(#13), missing `engine="streaming"` (#12), `split_his_fills` split correctness (#3 of task),
float-residual exact-zero reset (#15), and provider/reconstruction determinism (#5 of task).
Ran one RAM-bounded single-wallet probe and sampled ~20 wallet files one at a time
(streaming, `POLARS_MAX_THREADS=2`, never the monthlies). **No CRITICAL or HIGH found — this
is essentially a clean bill.** The known false-"no-edge" tuple-key bug is correctly guarded
in every call site. Residual items are one MED OOM that is by-design/offline, one LOW
resume-after-crash gap, and one NIT (missing tie-break column) that I empirically proved has
no numerical impact.

## What I checked and how
- `vm_stat` before each probe (free+inactive ~3 GB, safe). Probes loaded ONE ~32 KB
  per-wallet file at a time, released each, printed only scalars. Monthlies never touched.
- Grepped `partition_by|as_dict|group_by|read_parquet|scan_parquet|.collect(` across `src/`
  and `scripts/`; read every position-reconstruction and gate-feeding path.

## Findings

### F1 — `convergence_his.reshape_month` materializes a full month in RAM (the box-crasher)  [MED]
- **Where:** `scripts/convergence_his.py:48` (`reshape_month`): `pl.concat([tk, mk]).collect(engine="streaming")` then `:51` `partition_by("wallet", as_dict=True)`.
- **Blast radius:** reporting/offline-estimate (OOM only). Not the gate.
- **Failure scenario:** `engine="streaming"` bounds the *scan*, but the `.collect()` result is
  the entire month's universe+priceable fills as one in-memory frame, and `partition_by`
  then requires that whole frame resident. For a month of ~1500-wallet universe fills this is
  hundreds of MB to ~1 GB — exactly the "full-month reshape swaps on 8 GB" path the task
  names, and the most likely contributor to the prior OOM crash if this script is run
  alongside others.
- **Why it's real (not theoretical):** `partition_by` is not a streaming sink; peak RSS =
  full-month materialization regardless of the streaming label on `collect`.
- **Mitigating:** This is the *deliberately expensive offline diagnostic*; it is explicitly
  superseded by the safe path (`split_his_fills.py` → `edge_sweep.py`, which reads tiny
  per-wallet files). It should not be run during the audit waves. So severity is MED, not HIGH.
- **Confidence:** high (static; arithmetic on documented universe size). Did not run it (banned).
- **Fix sketch:** in `reshape_month`, `sink_parquet` per-wallet like `split_his_fills` Phase 1/2
  rather than collect-then-`partition_by`; or just always use the pre-split `edge_sweep` path
  and retire the monthly reshape.

### F2 — `split_his_fills` Phase-2 resume can silently DROP a partial batch after a crash  [LOW]
- **Where:** `scripts/split_his_fills.py:84` — `if (out / f"{batch[0]}.parquet").exists(): skipped += …; continue`.
- **Blast radius:** offline-estimate (only if a crash occurred mid-write); not the gate.
- **Failure scenario:** Phase 2 writes a whole batch's wallets in one `for k, wdf in parts.items()`
  loop (`:89–91`). If the process dies after `batch[0].parquet` is written but before later
  wallets in the same batch, a resume sees `batch[0]` exists and skips the *entire* batch →
  the un-written wallets in that batch are permanently missing from `data/follow/fills_his/`,
  silently shrinking the universe for every downstream sweep. No checksum/all-present guard.
- **Why it's real:** resume key is a single sentinel file, not "all wallets in batch present."
- **Confidence:** medium — depends on a crash happening mid-batch; no evidence it did.
- **Fix sketch:** write to a temp name and `os.replace`, or gate resume on a per-batch
  `_done` marker written only after the full `parts` loop completes.

### F3 — `_positions_for` sorts by `time` only; same-ms order ≠ true fill (tid) sequence  [NIT — proven no impact]
- **Where:** `skill.py:124` (`_positions_for`), `skill.py:143`, `followable.py:63,103`,
  `edge_sweep.py:43` — all `df.sort("time")` / `group_by("coin")` with no tie-break column.
- **Blast radius:** would be gate + selection (position reconstruction feeds the gated
  `followable_returns`) — *if* it bit. It does not (see proof).
- **Hypothesis:** within one millisecond a coin can have opposite-side fills; the
  signed-contract state machine in `reconstruct` (`skill.py:91–119`) is order-sensitive
  (which fill opens vs closes, `taker_open`, weighted `entry_px`). `sort("time")` provides
  *some* tie order, and I confirmed it does NOT equal the true `tid`-ordered sequence.
- **Why it is NOT a finding (probe):** sampled 20 wallet files one at a time — opposite-side
  same-ms groups are common (11,855 across 20 wallets; one wallet 11,534). On the worst
  wallet's busiest coin (VVV, 488,897 rows): (a) `sort("time")` is **reproducible** run-to-run
  (deterministic, not racy), and (b) reconstruction is **identical** under time-only,
  `["time","tid"]` ascending, and `["time","tid"]` descending — all give 124 positions,
  19 taker, median raw 15.34 bp. The intra-ms ordering nets out (entry/exit share the same
  ms so `hold_ms` is unaffected, and the weighted-average basis is invariant here). So the
  determinism/ordering hypothesis (#5) and the non-determinism worry are both **DEFUSED**.
- **Confidence:** high (empirical, worst-case wallet).
- **Fix sketch (hardening only):** `sort(["time", "tid"])` everywhere to make the order match
  the true sequence explicitly and remove any future fragility — no behavior change today.

## Checked and CLEAN (no finding)

- **#13 tuple-key regression — fully guarded.** Every `partition_by(..., as_dict=True)`
  unwraps the polars-1.x `(value,)` tuple key: `split_his_fills.py:90`
  (`w = k[0] if isinstance(k, tuple) else k`) and `convergence_his.py:50` (same idiom, with
  comment). Every `group_by("coin")` uses tuple-unpacking `for (coin,), g in …`
  (`skill.py:143`, `followable.py:63,103`, `edge_sweep.py:43`, `copy_backtest.py:50`). No dict
  is indexed by a bare string against a tuple-keyed map. The known clean-false-"no-edge" path
  cannot recur here. Verified live: single-wallet provider returns 2330 rows, correct 9-col
  schema, tid-unique.
- **#12 streaming — clean on the cheap/gated path.** `split_his_fills.py:87` uses
  `collect(engine="streaming")`; `:73` is a `pl.len()` count (scalar, not a materialization).
  `rank_wallets`/`rank_followable`/`oos`/`copy_backtest` all read **one per-wallet file at a
  time** in a `for f in sorted(glob(...))` loop — bounded RSS. `ParquetFillsProvider`
  (`fills_source.py:111`) eager-reads a single ~32 KB wallet file (fine; could be
  `scan_parquet` for predicate pushdown but irrelevant at this size). The only full-frame
  materialization is F1 above.
- **#15 float-residual staling — correct.** `reconstruct` (`skill.py:108–119`) resets
  `pos = 0.0` exactly on close, anchors `tol` to a **causal running** `maxabs`
  (`:93–94`, updated before each step, not a full-sequence max), and seeds `valid` from
  `startpos[0]` so a mid-window-opened (pre-window) position is reconstructed but **not
  emitted** (`:87,109`). Matches the documented streaming-`CoinStepper` parity requirement.
- **split semantics (#3).** Output schema (after `drop("wallet").sort("time")`) matches
  `fills_source._SCHEMA`; taker rows keep `side`+`crossed=True`, maker rows flip side +
  `crossed=False` (`split_his_fills.py:42–48`) — consistent with README's
  "maker fills the opposite sign." Per-wallet `tid` confirmed unique (dup=0) on the probed
  wallet; concat across month tmp-files preserves all months. Cross-month duplicate `tid`
  (if his monthly exports overlapped at boundaries) is the one thing I could NOT rule out
  without loading a monthly (banned) — low likelihood given the cumulative-notional export
  design; flag for the author to confirm his monthlies are boundary-disjoint.

## Could not rule out (bounded by the no-monthly rule)
- Exact row-count parity of the split vs the monthly source (README documents methodology but
  no row counts; verifying parity requires reading a monthly). Mitigated by per-wallet schema
  + tid-uniqueness spot-check.
- Cross-month `tid` duplication (see split semantics above).

## Headline
Near-clean: #13 tuple-key and #15 float-residual fully guarded; determinism hypothesis
empirically defused. Residual: 1 MED (offline full-month OOM in `convergence_his`), 1 LOW
(split resume-after-crash drop), 1 NIT (sort tie-break) — none touch the GO/NO-GO gate.
