# Audit 15 — Capture store / SQLite / retention / restart  [DYNAMIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/15_store.md`.
> DYNAMIC: max 2 dynamic agents at once. You may run ONLY `tests/test_capture_store.py`.

## Scope
The SQLite store is the durable state: roundtrips, open_state, wallets, meta. Restart recovery and
retention pruning must not lose, duplicate, or corrupt round-trips, and must keep the box under its
disk/RAM budget.

## Read
- `src/babylon/follow/capture/store.py`, `tests/test_capture_store.py`.
- `docs/LIVE_CAPTURE.md`: schema, "Restart recovery", "Retention & resilience", WAL + batched commits.
- Commit d080167 (RoundtripStore SQLite, retention).

## Adversarial hypotheses to test
1. **Restart recovery completeness.** Rebuild PositionTracker from `open_state`; re-derive pending
   markouts. Adversarial: an `open_state` row whose `t_entry+lag` passed during downtime — spec says
   DROP it (no `late_markout`). Does the code drop, or mark at current mid (fabricated)? Cross-check
   with audit 13.
2. **Retention prune correctness.** `DELETE WHERE exit_t < now − retention`. Does the prune ever
   delete an OPEN position's state (open_state has no exit_t), or a round-trip still needed for the
   current scoring cutoff? An over-aggressive prune shrinks the scoring window → fewer RTs → noisier
   rank. Check the boundary.
3. **Idempotent insert.** Round-trip insert keyed on what? A replayed fill (audit 14) that re-derives
   the same RT must not double-insert. Is there a UNIQUE constraint / upsert?
4. **WAL + crash atomicity.** Batched transactional insert — on crash mid-batch, are partial RTs
   committed? Could a committed RT reference an open_state row already deleted (dangling)?
5. **Disk/RAM budget.** Spec: round-trips ~10 MB/month (keep ~1yr), fills 3–7 days, NO per-second
   mid log. Confirm nothing accidentally persists the mid log or unbounded fills → disk blowup on the
   droplet.

## Allowed probe
Run only this one test file:
```bash
POLARS_MAX_THREADS=2 timeout 180 .venv/bin/pytest tests/test_capture_store.py -x -q -p no:cacheprovider 2>&1 | tail -20
```
SQLite tests use tiny temp DBs — light. Check `vm_stat` first. Do NOT run the full suite.

## RAM
DYNAMIC but tiny temp SQLite → trivial.
