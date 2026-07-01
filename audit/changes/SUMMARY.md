# Change-Audit SUMMARY — fixed-horizon selection signal (piece 1+2)

5 static auditors on the ~100-line diff (skill.open_events, followable.markout_returns, selci_fh
refactor, tests). Findings + resolution:

## Confirmed correct (clean)
- **A1** `open_events` is bit-for-bit identical to the validated `reconstruct` state machine
  (flips, adds, exact-zero close, causal tol, is_leading). The load-bearing component is sound.
- **A3** the `selci_fh` delegation is lossless (tuple order, imports, call sites); proven
  byte-identical to the validated run on 296 (k,wallet) cells.

## HIGH issues found AND FIXED in this pass
- **A2 [HIGH]** `markout_returns` had a mandatory `universe` gate the validated `selci_fh` lacked →
  with live config it would drop majors and rank on a different array than validated.
  **FIX:** `universe` is now optional, default `None` = price all candle coins = exactly the
  validated behavior. Restricting is opt-in. Pinned by `test_default_universe_does_not_drop_majors`.
- **A4 [HIGH]** tests gave false confidence — no live≡validated parity test, deployed config untested.
  **FIX:** added `test_live_equals_validated_neutralized_multicoin_lagged` (markout_returns ≡ an
  inline replica of selci_fh's pricing on a multi-coin/neutralized/lag≠0/flip/never-closer fixture),
  plus never-closer, directional-vs-neutralized, and major-coin tests. 31 tests pass.

## Wiring checklist for pieces 3–5 (A5 — NOT bugs in landed code, requirements for the wire-in)
- `markout_returns` is not a drop-in for the current `returns_fn` contract — adapt in SelectionAdapter.
- **No horizon config field** exists → add `markout_horizon_ms` to ExperimentConfig.
- **Locked config lag is 60 s, but the validated rule needs ~15 min (900_000 ms)** → must change/override.
- Defaults to flip for the markout path: pass the **basket (neutralized)**, swap `_sortino` →
  **trimmed-mean** in select_roster.
- Pass `universe=set(lookups)` is NOT needed (default None already matches validated); but DO point the
  runner at the rolling past-notional universe for the candidate POOL (Audit 01), separate concern.
- Eligibility: min_positions now counts ENTRIES (opens), not round-trips — re-tune the threshold.

## Status
Piece 1+2 are correct, parity-proven, and the two HIGH findings are resolved. Safe to build pieces 3–5
on top, using the checklist above. The selection change remains power-only (cannot fake a GO).
