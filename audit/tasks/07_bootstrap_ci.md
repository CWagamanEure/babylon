# Audit 07 — Bootstrap / confidence intervals  [DYNAMIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/07_bootstrap.md`.
> DYNAMIC: max 2 dynamic agents at once. Single-wallet files / streaming only. Never the monthlies.

## Scope
The CI is what separates "real edge" from "lucky draw". A wrong bootstrap (resampling the wrong
unit, ignoring correlation) produces a too-narrow CI that fakes significance.

## Read
- `scripts/edge_sweep.py` — `_boot_ci` (wallet-cluster bootstrap).
- `scripts/convergence_test.py` — its CI construction.
- Known #8: resample WALLETS not RTs (RTs within a wallet are correlated).

## Adversarial hypotheses to test
1. **Cluster unit correctness.** `_boot_ci` resamples `arrays` (per-wallet) — confirm each array
   is one wallet's RTs and the resample is over wallets, with all RTs of a picked wallet kept
   together. If it ever flattens to per-RT resampling, the CI is too narrow.
2. **Selection inside or outside the bootstrap?** The CI is computed on the *already-selected*
   top-N arrays (`sel_arrays_pooled`). That ignores selection uncertainty (which wallets made the
   top-N is itself random). A correct CI re-runs selection inside each bootstrap draw. Quantify how
   much wider the CI gets if selection is bootstrapped. **This is the likely real finding.**
3. **Cost subtracted per draw correctly.** `means[b] = pooled.mean() - cost` — cost is a constant,
   fine, but confirm it's the right cost and not double-subtracted elsewhere.
4. **n_boot=1000 adequacy & seeding.** Fixed seed 12345 → reproducible, good. Is 1000 enough for a
   5th/95th percentile? Check CI stability across two seeds (cheap probe).
5. **Does the CI cross zero at the deployed operating point?** Re-run the sweep at the LIVE config
   (top_n=50 or live min_positions, the live lag, neutralized) and report whether `net` CI excludes
   zero. If it includes zero, the deployable edge is not established.

## Allowed probe (RAM-bounded)
You MAY run `scripts/edge_sweep.py` — but it reads `data/follow/fills_his/` (per-wallet, safe) via
`ParquetFillsProvider`, NOT the monthlies. Run with a SMALL universe slice first to confirm it
behaves, then the real config. Cap it:
```bash
POLARS_MAX_THREADS=2 timeout 300 .venv/bin/python scripts/edge_sweep.py \
  --boot 200 --top-n 50 --lags 60000 --stat sortino 2>&1 | tail -30
```
Check `vm_stat` before running. If memory is tight, reason statically about `_boot_ci` instead.

## RAM
DYNAMIC but the per-wallet provider is cheap. The danger is only if you point it at a monthly file
— don't. Never raise `--boot` so high it runs for minutes; keep it bounded.
