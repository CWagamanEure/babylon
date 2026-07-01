# Audit 12 — Capture stepper (live≡batch parity)  (agent: 12_capture_stepper_parity)

## Summary
I read `capture/stepper.py` in full, the batch `skill.reconstruct` it claims bit-for-bit
parity with, the `test_capture_stepper.py` fuzz, and the live driver (`capture/ingest.py`,
`capture/markout.py`). The stepper's internal logic (flip → 2 events, size-weighted add,
exact-zero close with causal running-max tol, `unmarkable`/`valid` propagation) is correct
and matches `reconstruct` line-for-line; the 6-test file passes (6 passed, 1.62s). The
substantive finding is NOT in the stepper itself: the "bit-for-bit live≡batch" proof only
covers `reconstruct ≡ reconstruct_via_stepper` **given an identical input array**, and that
assumption is silently violated for **same-ms fills**, because live releases in `(time, tid)`
order while batch sorts by `time` only. Blast radius is selection-power (capture feeds
selection, not the gate), so top severity is MED.

## Findings

### F1 — Same-ms fill order differs live (time,tid) vs batch (time-only) → parity proof's input-order assumption is unenforced  [MED]
- **Where:** `src/babylon/follow/capture/ingest.py:66` (heap keyed `(f.time, f.tid, f)`) vs
  `src/babylon/follow/skill.py:124` and `:143` and `src/babylon/follow/fills_source.py:53`
  (all `.sort("time")`, no tid tiebreak). The proof itself: `tests/test_capture_stepper.py:30-31`
  feeds the *same* array to both reconstructors.
- **Blast radius:** selection-power (live capture score for a wallet diverges from its
  batch-validated score; capture does not feed the GO/NO-GO gate per ground-rules §2).
- **Failure scenario:** the round-trip machine is order-dependent across a close/flip boundary
  even for *same-side* fills. Take a short position of −5 and two same-ms BUY fills, +3 @ p1
  (tid 10) and +4 @ p2 (tid 11). Live releases tid-order (+3 then +4): close leg gets
  `exit_px=(3·p1+2·p2)/5`, the flip leg opens with `entry_px=p2`. If batch's `time`-only sort
  emits them in the other order (+4 then +3), the same fills give `exit_px=(4·p2+1·p1)/5` and
  flip `entry_px=p1` — a different round-trip pair. polars `.sort("time")` defaults to
  `maintain_order=False`, so ties are not guaranteed to come out in tid order even if the
  parquet were stored that way; nothing on the batch side ever sorts by `tid`. A wallet that
  flips via an aggressive book-sweep produces exactly this pattern (multiple same-ms same-side
  fills crossing zero), so it is common, not contrived. The per-event bps delta is intra-sweep
  small, but it is a *systematic* live-vs-batch divergence that the "bit-for-bit proven" claim
  (stepper.py:9-10, docstring; skill.py:74-77) denies.
- **Why it's real (not theoretical):** the fuzz cannot catch it by construction — both paths
  receive one shared `np.sort`-ed array (test line 30-31), so any ordering-source mismatch is
  invisible. The mismatch only manifests when the *two different code paths* build their input
  order from different keys, which is precisely the live (heap `(time,tid)`) vs batch
  (`sort("time")`) situation, never exercised by the test.
- **Confidence:** high that the ordering keys differ and that the machine is boundary-order
  dependent; medium on real-world frequency/magnitude (would need a same-ms-fill census on a
  few `data/follow/fills_his/<wallet>.parquet`, loaded one at a time, to quantify — I did not
  run it to stay within the RAM cap).
- **Fix sketch:** make batch deterministic on the same key the live heap uses — `.sort(["time",
  "tid"])` everywhere fills are ordered for reconstruction (`fills_source.py:53`, `skill.py:124`,
  `skill.py:143`, and `copy_backtest.py:50`), and assert the his export carries `tid` (schema at
  `fills_source.py:25` does). Then the parity proof's hidden assumption becomes true.

### F2 — Fuzz barely generates same-ms fills and never tests ordering-source parity  [LOW]
- **Where:** `tests/test_capture_stepper.py:10` (`np.sort(rng.integers(1_000, 1_000_000, n))`,
  n≤40).
- **Blast radius:** reporting/test-confidence (the proof is weaker than advertised).
- **Failure scenario:** with ≤40 draws over a ~1e6 range, expected same-ms collisions per seed
  ≈ 40²/2/1e6 ≈ 8e-4 → only a couple of duplicate-time cases across all 3000 seeds, and even
  those feed both paths an identical order. So the one regime where live and batch can diverge
  (dense same-ms boundary-crossing fills) is essentially never reconstructed and the
  ordering-source divergence (F1) is structurally untestable in this harness. The fuzz *does*
  combine flips+adds+seeded-startpos via the random walk (so hypothesis 6's "never combined"
  worry does not apply), but it does so only on strictly-increasing timestamps.
- **Confidence:** high.
- **Fix sketch:** add a clustered-timestamp generator (draw from a small set of ms values so
  many fills share a ms) AND a case that builds the batch input by `sort("time")` while the
  stepper is fed `(time, tid)` order, asserting equality — i.e. test the actual live-vs-batch
  ordering contract, not two views of one pre-sorted array.

### F3 — Lateness buffer drops fills batch keeps (live-only RT loss)  [LOW / by-design]
- **Where:** `src/babylon/follow/capture/ingest.py:62-65` (drop if `f.time <
  last_released`), `:68` (release at `watermark − lateness`, `lateness_ms=2000`).
- **Blast radius:** selection-power.
- **Failure scenario:** a fill arriving >2 s after a later fill of the same (wallet,coin) was
  already released is dropped live (`dropped_late`), but batch `sort("time")` includes it →
  for wallets with bursty/late `userFills` replays the live RT set is a subset of batch's, so
  the live score is computed on fewer RTs. Acknowledged in the ingest docstring; inherent to a
  bounded-lateness streaming buffer (you cannot reorder unboundedly live). Noted for
  completeness, not a defect to fix.
- **Confidence:** high. **Fix:** none required; keep `dropped_late` observable so the
  live-vs-batch RT-count gap is monitorable.

## Cleared (checked, no parity defect)
- **Flip (hyp 1):** stepper.py:119-127 ≡ skill.py:114-119. Leftover sizing, new-leg
  `entry_px = leftover·px/leftover = px`, direction `1 if d>0 else -1`, and the same-ms
  `Close(rid=k)+Open(rid=k+1)` pair (rid distinct, entry_t collides) all correct;
  `test_flip_rids_distinct...` confirms.
- **Add / size-weighted basis (hyp 2):** stepper.py:101-104 accumulates `en += |d|·px`,
  `es += |d|`; `Close.entry_px = en/es` is the true size-weighted average, not first/last;
  matches skill.py:99-101. `test_scale_in_emits_add_same_rid` confirms same rid.
- **Exact-zero close + causal running-max tol (hyp 4, known #15):** both reset `pos = 0.0`
  (stepper.py:117, skill.py:113) and both anchor `tol` to a **running** `maxabs =
  max(maxabs, abs(pos+d))` computed identically before the branch (stepper.py:90 ≡ skill.py:93).
  The mixed-scale/unrounded/seeded fuzz (test lines 14-19, 29) specifically targets this and
  passes for 3000 seeds.
- **`unmarkable` / `valid` propagation (hyp 5):** seeded `startpos≠0` → `valid=False`, `rid=−1`
  (stepper.py:70-71 ≡ skill.py:86-87). Batch never emits it (`if valid and …`, skill.py:109);
  the stepper emits `Close(valid=False)` but `reconstruct_via_stepper` drops it (line 145) AND
  the **live** path drops it too (`markout.on_close` returns early on `not ev.valid`,
  markout.py:97-98). So no phantom scored RT on either side. `test_seeded_*` confirm.
- **OOO at the stepper (hyp 3, in-window):** the stepper has no buffer (by design); the
  bounded-lateness heap in ingest.py reorders correctly within `lateness_ms`. The residual
  parity risk is the same-ms tie-break of F1 and the >window drop of F3, both upstream of the
  stepper.

## Probe run
`POLARS_MAX_THREADS=2 .venv/bin/pytest tests/test_capture_stepper.py -x -q -p no:cacheprovider`
→ `6 passed in 1.62s`. (`timeout` is absent on this host; the suite is synthetic and finished
in <2 s. `vm_stat` showed ~3.1 GB free+inactive before running — within budget.) I did not load
any monthly or per-wallet fills file.
