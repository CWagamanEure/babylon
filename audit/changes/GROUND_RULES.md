# Change-Audit — adversarial review of the new selection signal (piece 1+2)

You are one of a small swarm auditing a SPECIFIC, SMALL diff before it gets wired into the live
copy-trade selection path. The change adds the fixed-horizon markout selection signal that an
offline study (`audit/EDGE_INVESTIGATION.md`) validated as having a real OOS edge.

## RESOURCE SAFETY (8 GB Mac — a prior swarm OOM-crashed it)
- You are a STATIC auditor: **read code and reason**. Do NOT run Python, pytest, or any data load.
- NEVER read `other_repo_notes/fills_*.parquet` (0.5–1 GB each) or `scratch_conv/selci_*.jsonl` (large).
- The whole diff is tiny (~100 lines). Read it, reason, write findings. No execution needed.

## The diff under review
- `audit/changes/the_diff.patch` — the full diff (skill.py + followable.py).
- New: `src/babylon/follow/skill.py` → `OpenEvent` dataclass + `open_events()` function.
- New: `src/babylon/follow/followable.py` → `markout_returns()` function.
- New test: `tests/test_markout_returns.py` (9 tests).
- Refactor: `scripts/selci_fh.py` `_open_events` now DELEGATES to `skill.open_events` (claimed
  byte-identical to the validated run — verify the claim is sound by reasoning, not by running).

## What "correct" means here — the load-bearing invariant
The whole value proposition is **live ≡ validated**: `markout_returns` (which live selection will
call) must produce EXACTLY the per-entry returns that `selci_fh.py` produced in the study that
validated the edge. If they diverge, the live system trades a DIFFERENT, unvalidated rule. Your job
is to find any way they diverge, any correctness bug in the new functions, or any gap that makes the
"byte-identical / parity" claim false.

## Context to read
- `src/babylon/follow/skill.py` — esp. `reconstruct` (the validated batch state machine that
  `open_events` must match) and the new `open_events`.
- `src/babylon/follow/followable.py` — `_close_at` (look-ahead semantics), `followable_returns`
  (the sibling round-trip fn), the new `markout_returns`.
- `scripts/selci_fh.py` — `cmd_extract` (how the study built the validated arrays) + the refactored
  `_open_events`.
- `audit/EDGE_INVESTIGATION.md` — the operating point that was validated (6h horizon, 15-min lag,
  neutralized, seam guard, trimmed-mean ranking).

## Reporting — write to `audit/changes/findings/NN_<slug>.md`
Per finding: severity [CRITICAL/HIGH/MED/LOW/NIT], where (file:line), the concrete failure scenario
(specific inputs → wrong output), why it's real (the code path), confidence, and a fix sketch.
Blast radius matters: a divergence between markout_returns and the validated selci_fh is the worst
class (the live system would trade an unvalidated rule). A clean bill is a valid result — say what
you checked and what you couldn't rule out. Don't fix anything; propose fixes only.

Final message back: just the findings path + a one-line headline (top severity + count).
