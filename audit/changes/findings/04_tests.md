# A4 — Do the new tests catch bugs, or give false confidence?

Scope: `tests/test_markout_returns.py` (9 tests) vs `skill.open_events` and `followable.markout_returns`.
Static review only. Cross-referenced against `scripts/selci_fh.py` (`cmd_extract`, `_open_events`) and
`skill.reconstruct`.

## Verdict
The assertions are **arithmetically correct** — every numeric expectation re-derived from `_close_at`'s
actual logic checks out (details below). But the suite gives **false confidence on the one thing the
diff exists to guarantee**: live (`markout_returns`) ≡ validated (`selci_fh`). It never exercises the
DEPLOYED configuration (neutralized basket, beta=1.245, lag≠0), never cross-checks against `selci_fh`,
and never tests the multi-event / multi-coin / mid-position-seed paths where a real divergence would hide.

Top severity: **HIGH** (missing parity test for the load-bearing invariant). Count: 1 HIGH, 1 MED-weak-test,
~12 coverage gaps.

---

## Assertion correctness — all re-derived, all CORRECT
`_close_at(t)`: `i = searchsorted(times, t - 3_600_000, "right") - 1`.

- **test_markout_fixed_horizon_value (+1000bp):** ein=_close_at(2H): searchsorted([-H,0,H,2H,3H], H, right)=3, i=2 → closes[2]=100. eout=_close_at(3H): searchsorted(...,2H,right)=4, i=3 → closes[3]=110. raw=(110/100−1)·1e4=**1000**. Correct. The in-line comment `times[i]<=H`/`<=2H` is also right.
- **test_markout_seam_guard:** end=2H+0+H=3H. Guard is `end >= before_ms → exclude`. before=3H−1 → 3H≥3H−1 → excluded (size 0). before=3H+1 → 3H≥3H+1 false → included (size 1); event is priceable (ein=closes[1]=110, eout=closes[2]=121). Correct.
- **test_markout_drop_leading:** single fill → leading open; kept (size 1), dropped via drop_leading (size 0). Priceable. Correct — but see MED weakness below.
- **test_markout_skips_unpriceable_coin:** coin "Y" in universe but not in lookups → `continue`. size 0. Correct.
- **open_events state machine** (single/add/flip/open-after-close/zero-hash): all five re-derived against the `pos==0 / same-side / opposite-sign / flip-leftover` branches and `seen_close` flag — direction, is_leading, notional (|d|·px and leftover·px) all correct.

No wrong-assertion bug like the earlier `_close_at` regression. Good.

---

## HIGH — No live≡validated parity test (the most important missing test)
GROUND_RULES calls live≡validated "the load-bearing invariant." There is **no test** anywhere
(`grep` confirms only `test_markout_returns.py` and `test_capture_stepper.py` touch these) that pins
`markout_returns` output to `selci_fh.cmd_extract`'s `tr`/`te` arrays on identical fills. The 9 tests
validate `markout_returns` *in isolation* — they cannot catch a divergence from the study, which is
exactly the failure class the diff is supposed to foreclose. Concrete divergence risks left uncovered:

1. **Neutralization mismatch.** `selci_fh.cmd_extract` ALWAYS subtracts `_basket_ret_bps` (neutralized,
   the validated operating point). `markout_returns` only neutralizes when `basket is not None`, and
   **every test passes basket=None**. A live caller that forgets the basket trades the raw (beta-loaded)
   signal — a different, unvalidated rule — and no test would fail.
2. **beta default mismatch.** `selci_fh` default `beta=1.245`; `markout_returns` default `beta=1.0`.
   Untested; a caller relying on the default silently diverges.
3. **lag≠0.** Validated point is 15-min (900 s) lag. All tests use `lag_ms=0`, so `entry+lag` and
   `end=entry+lag+horizon` pricing under nonzero lag is never exercised.
4. **Seam-guard equivalence.** `selci_fh` train bucket is `end < t0`; `markout_returns` is
   `end >= before_ms → exclude` (i.e. keep `end < before_ms`). These are equal ONLY with
   `before_ms = t0` — nothing pins that equivalence, and the exact-boundary case `end == before_ms`
   (both must exclude) is never tested.

**Add:** a test that builds a small multi-coin, multi-event fill set, runs `selci_fh._open_events` +
its extract pricing AND `markout_returns(before_ms=t0, basket=basket, beta=1.245, lag_ms=900_000)`,
and asserts the two `tr` arrays are elementwise equal. This is the single highest-value missing test.

---

## MED — drop_leading test is weak (passes even if it dropped EVERYTHING)
`test_markout_drop_leading` uses ONE event, which is leading. drop_leading=True → size 0.
A buggy `drop_leading` that dropped *all* events (ignoring `is_leading`) would also pass.
The test proves "drop_leading is not a no-op" but not "drop_leading is selective."
**Add:** a fill set with one leading open AND one non-leading open (e.g. open→full-close→re-open, or a
flip), assert `drop_leading=True` keeps exactly the non-leading one. Mirror it for `selci_fh`'s
`te_lead` filtering to confirm both selectivity paths agree.

---

## Coverage gaps — concrete missing cases that can hide a real bug
Each is an actionable test to add:

1. **reconstruct ↔ open_events parity (fuzz).** Docstring (skill.py:150) claims open_events is
   "bit-for-bit identical to reconstruct." Zero tests cross-check them. `followable_returns` uses
   `reconstruct`; `markout_returns` uses `open_events`. A state-machine drift between them is a real
   divergence with no guard. Add a randomized fill fuzz asserting open_events' emitted (entry_t,
   direction) match reconstruct's Position entries (for the closed ones).
2. **Mid-position window seed (startPosition ≠ 0).** Every test seeds startPosition=0.0. The entire
   `is_leading`/`drop_leading` machinery (Audit 11) exists for windows that open MID-position, where
   the leading open is pre-window/unobserved. The "never emit the pre-window open, flag the first
   in-window open" behavior is completely untested. Add cases: startPos>0 then add (no emit), startPos>0
   then full close then re-open (is_leading=False), startPos>0 then flip.
3. **Neutralized pricing path.** No test passes a `basket`; `_basket_ret_bps` interaction inside
   `markout_returns` (the deployed path) has zero coverage. Add a basket and hand-verify one neutralized bp.
4. **Multi-coin dataframe.** All tests use a single coin. The `group_by("coin")` loop, per-coin lookup
   selection, and ordering across coins are untested — a coin-keying bug would pass.
5. **Multiple events returned in one array.** No test runs `markout_returns` on input that emits ≥2
   priced events; array length/order/per-event direction across a flip is never checked end-to-end.
6. **add-then-flip combination.** Tests cover add alone and flip alone, but not open→add-same-side→flip
   (does the flip close the full added size and price the leftover correctly?).
7. **Empty dataframe.** `markout_returns` / `open_events` on 0 rows → empty array. Untested.
8. **Out-of-order input.** Both helpers sort by time; no test feeds shuffled rows to confirm the sort
   (and the startPosition[0] seed taken AFTER sort) actually happens.
9. **The never-closer contrast (the whole point of the study).** No test contrasts `markout_returns`
   vs `followable_returns` on a single open that never closes — showing markout keeps it while the
   round-trip path drops it. This is the stated reason markout exists; assert it directly.
10. **taker_only / conviction_only filters inside markout_returns.** open_events' conviction flag is
    tested at the dataclass level, but `markout_returns`' filtering on `e.taker_open`/`e.conviction`
    is not. Add a maker open (crossed=False) and a zero-hash open and assert both are excluded by default
    (and that this matches `selci_fh`'s `if topen and conv`).
11. **Priceable coin, unpriceable time.** `test_markout_skips_unpriceable_coin` only covers
    coin-not-in-lookups. The `ein is None` path when the coin IS present but `entry+lag` predates the
    first candle (i<0), and the `px<=0` guard in `_close_at`, are untested.
12. **Relative-tolerance flat detection at scale.** All sizes are 1–3. The `_REL_TOL · max|pos|`
    meme-coin-scale logic the docstring brags about (billion-supply residuals) is never exercised; a
    tolerance regression on large notionals would pass.

## What I could NOT rule out
Whether `selci_fh`'s refactored `_open_events` is truly byte-identical to the validated pre-refactor
run — there is no golden-output regression fixture, and (correctly) I did not run anything. The parity
test in HIGH would close most of this; a checked-in golden array from the validated run would close the rest.
