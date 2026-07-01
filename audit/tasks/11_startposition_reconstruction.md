# Audit 11 — startPosition seeding & position reconstruction  [DYNAMIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/11_startpos.md`.
> DYNAMIC: max 2 dynamic agents at once. Single-wallet files / streaming only. Never the monthlies.

## Scope
The his export has NO true startPosition (seeded 0). A position open before a wallet's first
in-window fill is mis-seeded → its first "round-trip" is fictitious or sign-flipped. This is a
residual bias on every number derived from it. Verify the hold-out actually fires.

## Read
- `src/babylon/follow/skill.py` — `reconstruct`, `_positions_for`, how `startPosition` is used.
- `src/babylon/follow/capture/stepper.py` — `unmarkable` flag for cold-start-seeded positions.
- `src/babylon/follow/fills_source.py` — `ParquetFillsProvider`, what `startPosition` it supplies.
- Known #11; commit history "dangling-held-out".

## Adversarial hypotheses to test
1. **Leading position held out?** A wallet whose first in-window fill is a *sell* of a pre-window
   long: does `_positions_for` treat that as opening a short (wrong sign) or correctly mark the
   position `unmarkable`/held-out? Trace the seed logic. **This is the core check.**
2. **`unmarkable` flag actually excludes from scoring.** The stepper sets `unmarkable` for
   cold-start positions — confirm the scorer/sweep DROPS those RTs, not just flags them.
3. **his export vs live divergence.** Live has a real `startPosition` (REST truth-up); the his
   export seeds 0. So the offline-validated edge carries a bias the live one won't, OR vice versa.
   Which direction does seed-0 bias the his edge? Argue it.
4. **Float residual (known #15).** Position close must reset to EXACT 0; a float residual leaves a
   dust position that never closes → a dangling RT. Confirm the causal running-max tolerance.

## Allowed probe (RAM-bounded, single wallet)
Pick ONE wallet, reconstruct its positions, and look for an opening fill that is a partial close
(sign mismatch at t0). Use the per-wallet file only:
```bash
POLARS_MAX_THREADS=2 timeout 120 .venv/bin/python - <<'PY'
import polars as pl
from babylon.follow.skill import _positions_for
w="0x000007b83bf80adcc02897528403c640991a6544"  # or any from data/follow/fills_his/
df=pl.scan_parquet(f"data/follow/fills_his/{w}.parquet").collect(engine="streaming").sort("time")
print(df.head(5).select(["coin","side","sz","px","time"]))
# inspect first position per coin for seed/sign sanity
PY
```
Check `vm_stat` first. One wallet at a time; do not loop over many.

## RAM
DYNAMIC, but single small file → trivial. The risk is only the monthlies — don't touch them.
