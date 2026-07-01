# Audit 20 — Engineering: RAM/OOM & polars correctness  [DYNAMIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/20_engineering.md`.
> DYNAMIC: max 2 dynamic agents at once. Single-wallet files / streaming only. Never the monthlies.

## Scope
The data pipeline's engineering bugs silently corrupt the stats (a tuple-key regression produced a
clean false "no edge"), and its memory behavior is literally why this audit is split into waves.
Audit both the OOM-safety and the polars correctness of the pipeline.

## Read
- `src/babylon/follow/fills_source.py` (`ParquetFillsProvider`), `scripts/split_his_fills.py`,
  `scripts/edge_sweep.py`, `scripts/convergence_his.py`.
- Known #12 (non-streaming `.collect()` OOM), #13 (`partition_by(as_dict=True)` tuple-key), #15
  (float residual). Infra note: 8 GB Mac swaps on full-month reshapes; pre-split then sweep cheap.

## Adversarial hypotheses to test
1. **Tuple-key regression (known #13).** polars 1.x `partition_by(as_dict=True)` keys by `('0x…',)`
   not the bare string → a lookup `d[wallet]` silently misses → `elig=0` "no edge". Grep the codebase
   for `partition_by`, `group_by`, `as_dict`, and any dict keyed on a group key. Confirm every such
   access matches the actual key shape. **META-GUARD: validate on a known-answer single-wallet probe.**
2. **Streaming everywhere (known #12).** Find every `read_parquet`/`.collect()` without
   `engine="streaming"`. Any eager collect on a path that could see a monthly-sized frame is an OOM
   waiting to happen (and is what crashed the box). List them with file:line.
3. **split_his_fills correctness.** The per-wallet split is the foundation of the cheap path. Does it
   drop or duplicate any wallet's fills vs the monthly source? Does it preserve `tid`, `side`,
   `startPosition` semantics? A lossy split silently changes every downstream number. (Verify by
   *counting*, not by loading the monthly — e.g. trust the documented row counts, or spot-check one
   wallet's split file against its expected shape.)
4. **Float residual staling (known #15).** Position close must reset to EXACT 0 with causal
   running-max tolerance. Grep the steppers/reconstruct for the zero-reset and confirm it's exact.
5. **Provider determinism.** `ParquetFillsProvider(w, lo, hi)` — does it return fills in a stable
   sorted order every call? Non-deterministic ordering → non-deterministic positions → non-re-derivable.

## Allowed probe (RAM-bounded, single wallet)
Known-answer single-wallet sanity (the meta-guard from pitfall #13):
```bash
POLARS_MAX_THREADS=2 timeout 120 .venv/bin/python - <<'PY'
import polars as pl
from babylon.follow.fills_source import ParquetFillsProvider
p=ParquetFillsProvider(__import__("pathlib").Path("data/follow/fills_his"))
w="0x000007b83bf80adcc02897528403c640991a6544"
df=p(w, 0, 9_999_999_999_999)
print("rows",df.height,"cols",df.columns)
print(df.head(3))
PY
```
Check `vm_stat` first. ONE wallet. Do not load the monthlies to "compare" — use documented counts.

## RAM
DYNAMIC — this task IS partly about the RAM safety. Model the discipline: streaming, one small file,
bounded output.
