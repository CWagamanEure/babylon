# Audit 07 — Bootstrap / confidence intervals  (agent: 07_bootstrap_ci)

## Summary
I audited the wallet-cluster bootstrap CI in `scripts/edge_sweep.py` (`_boot_ci`) and the
CI-free `convergence_test.py`. The cluster mechanics are essentially correct (it resamples
per-wallet test arrays and keeps each wallet's RTs together — NOT per-RT), and the cost is
subtracted once, not double-counted. The real defect is structural and matches the task's
prime hypothesis: **selection happens entirely OUTSIDE the bootstrap**, so the CI conditions on
the already-chosen top-N and ignores selection uncertainty — it is too narrow and overstates
significance (F1, HIGH). A second, independent bug: **the CI is built on a different estimator
than the headline point estimate** (per-RT pooled mean vs per-transition mean-of-means), so the
reported `net` is not the center of `[lo,hi]` (F2, MED). All findings are **offline-estimate**
blast radius — `edge_sweep.py` is the offline edge claim, not the hash-chained GO/NO-GO gate, so
none are CRITICAL. The one quantitative question I could not settle — *does the net CI exclude
zero at the live operating point, and how much does selection-aware resampling widen it* — is left
UNRESOLVED: the probe ballooned to ~1.6 GB RSS twice on this 8 GB box and I killed it for safety
(see Resource note). The exact bounded probe to finish it is given.

## Findings

### F1 — Selection runs OUTSIDE the bootstrap; the CI ignores selection uncertainty and is too narrow  [HIGH]
- **Where:** `scripts/edge_sweep.py:138-160` (selection at 142-154, CI at 160) and `_boot_ci` 76-88.
- **Blast radius:** offline-estimate (this is the "is the net edge real / does the CI exclude zero"
  claim). NOT the gate, so HIGH not CRITICAL.
- **Failure scenario:** Per (lag,mode), wallets are ranked by *train* Sortino and the top-N is
  taken at line 149, then `sel_arrays_pooled.extend(ter[w] for w in top)` (154) freezes that
  selected set. `_boot_ci` (160) then resamples ONLY among those already-selected wallets'
  **test** arrays. It never lets a near-the-cutoff wallet drop out or a non-selected wallet enter.
  Train skill for top-50-of-1500 is a noisy estimate and the marginal selected wallet sits just
  above the cutoff, so the *identity* of the top-N is itself a random variable with real variance.
  A correct CI re-runs the whole pipeline inside each draw: resample the eligible universe →
  recompute train skill → re-rank → take top-N → measure their test mean. The frozen bootstrap
  omits this between-selection variance component entirely, so its lower tail is biased upward and
  the interval is too narrow. Consequence: a net edge that is only marginally positive can be
  reported with a CI that excludes zero when a selection-aware CI would straddle it. In the
  limiting case where train skill carried no real signal, the selection-aware CI would widen toward
  the (much wider, near-zero-centered) FIELD distribution; the truth is between, but always wider
  than what `_boot_ci` reports.
- **Why it's real (not theoretical):** the selection code (142-154) and `_boot_ci` (76-88) are
  textually separate; `_boot_ci`'s only input is the post-selection `sel_arrays_pooled`. There is
  no resampling of the eligible set or re-ranking anywhere. The point estimate itself is honest
  out-of-sample (rank on train, measure on test), so this is purely a CI-width / significance
  defect, not a point-estimate inflation — but it is exactly the quantity ("does the CI exclude
  zero") used to call the edge deployable.
- **Confidence:** high that the bug exists (pure code reading). medium on magnitude — I could not
  complete the quantitative comparison (Resource note). Direction is unambiguous: selection-aware
  width ≥ frozen width, strictly greater whenever near-cutoff swaps occur (always, here).
- **Fix sketch:** move selection inside the bootstrap. Per draw `b`, for each transition resample
  the eligible wallets with replacement (carrying both train-skill and test arrays together),
  re-rank by train skill, take top-N, pool their test arrays across transitions, take
  `mean - cost`; then percentile the `n_boot` means. I wrote this as a standalone probe
  (`sel_boot.py`, see Resource note) that prints frozen vs selection-aware width side by side for
  two seeds; run it on a trimmed universe to quantify.

### F2 — CI is built on a different estimator than the reported point estimate (per-RT pooled vs per-transition mean-of-means)  [MED]
- **Where:** `scripts/edge_sweep.py:151-160`. Headline `sm = float(np.nanmean(sel_means))` (157)
  where `sel_means` has one entry per transition (152). CI center is `pooled.mean()` over ALL
  selected RTs across all transitions (`_boot_ci` line 87, fed by `sel_arrays_pooled` accumulated
  at 154).
- **Blast radius:** offline-estimate / reporting.
- **Failure scenario:** `sm`/`net` weight each transition equally (mean of per-transition pooled
  means). The bootstrap pools every selected RT across all 4 transitions and means them — equal
  weight per RT. When transitions carry unequal RT counts (they will: activity grows over the span,
  and selected-wallet RT counts differ per window), these two estimators disagree. The printed
  `net = sm - cost` is therefore NOT the center of the printed `[lo,hi]`; the interval can be
  off-center relative to, or even fail to contain, the headline number. A reader interpreting
  `net [lo,hi]` as "point estimate ± sampling error" is misled.
- **Why it's real:** `sel_means` is per-transition (line 152), `sel_arrays_pooled` is per-RT pooled
  (line 154); they are computed in the same loop from the same `top` but aggregated differently,
  and the two aggregations are only equal when every transition has the same selected-RT count.
- **Confidence:** high (code reading only).
- **Fix sketch:** pick one weighting and use it for both the point and the bootstrap. Simplest:
  compute the headline `net` as `np.concatenate(sel_arrays_pooled).mean() - cost` so the point
  estimate is the per-RT pooled mean that the bootstrap is actually a CI for. (Or, conversely, make
  the bootstrap resample per-transition means with equal weight to match `sm`.)

### F3 — Cross-transition appearances of the same wallet are treated as independent clusters  [LOW-MED]
- **Where:** `scripts/edge_sweep.py:154` (`sel_arrays_pooled.extend(...)` inside the `for k` loop)
  and `_boot_ci:84-87`.
- **Blast radius:** offline-estimate.
- **Failure scenario:** `sel_arrays_pooled` accumulates `ter[w]` across all transitions, so a
  wallet selected in transitions k=1 AND k=2 contributes two separate arrays that the bootstrap
  resamples as two independent cluster units. Known issue #8 says the cluster unit is the WALLET
  (its RTs are correlated through persistent skill/style). The same wallet's returns are still
  correlated across adjacent windows, so clustering by (wallet, transition) rather than by wallet
  undercounts that correlation → CI slightly too narrow. This is second-order relative to F1 (the
  windows are time-disjoint, so cross-window correlation is weaker than within-window), but it is a
  genuine deviation from the stated wallet-cluster principle.
- **Confidence:** high on the behavior, medium on materiality (depends on how many wallets recur
  across the 4 transitions — likely a sizable fraction, since the universe is the same top-1500
  rolling pool).
- **Fix sketch:** key the cluster by wallet, not by (wallet, transition): concatenate a wallet's
  test arrays across transitions into one cluster array before bootstrapping, OR adopt a block
  bootstrap that resamples wallets and carries all of that wallet's per-transition arrays together.
  (If F1 is fixed by re-selecting inside the bootstrap, do the wallet resample at the wallet level
  so this is fixed simultaneously.)

### F4 — Notes that don't move the headline but weaken the CI's usefulness  [LOW / NIT]
- **No CI on edge-over-field.** `scripts/edge_sweep.py:161-163` prints `edge_v_field` as a bare
  point with no interval, while only `net` gets `[lo,hi]`. Edge-over-field is the cost-invariant
  skill measure (robust to a mis-estimated 8 bp cost) and arguably the more trustworthy quantity;
  it deserves a CI too. LOW.
- **Shared RNG across all 10 (lag×mode) configs.** `rng = np.random.default_rng(12345)` is created
  once (line 107) and consumed sequentially by every `_boot_ci` call. Valid, but each config's CI
  depends on how many draws earlier configs consumed, so changing `--lags`/mode order silently
  shifts every subsequent CI. Reproducible only for an identical invocation. NIT — prefer a fresh
  `default_rng` seeded per (lag,mode) for independent, order-stable CIs.
- **`--boot 200` (the task's suggested smoke value) is light for 5th/95th percentiles.** The
  default `--boot 1000` is conventionally adequate for a 90% interval; 200 has visible Monte-Carlo
  noise in the tails. Fine for a smoke, not for a reported CI. NIT.
- **`convergence_test.py` reports NO confidence interval at all** (only point edge/sel/rho per
  transition and a pooled mean over transitions, lines 144-157). That is by design (it's a
  cross-repo point-replication, not the significance test), but if any GO discussion cites its
  pooled edge as evidence, it carries no uncertainty quantification. LOW — flag only so the pooled
  numbers aren't read as significant.

## UNRESOLVED (could not settle within resource limits)

- **Does the net CI exclude zero at the LIVE operating point (top_n=50, lag=60 s, neutralized,
  sortino), and how much wider is the selection-aware CI?** This is the crux of F1 and of task
  hypothesis #5. I could not produce numbers: the run block-buffered its output and then ballooned
  to ~1.6 GB RSS, and I killed it for memory safety (twice — once at full universe, once at a
  300-wallet/transition trim). To finish on a safe slice, run my probe (writes both CIs + two seeds
  + the F2 weighting gap) against a trimmed universe so RSS stays bounded:
  ```bash
  # build a small universe first (e.g. 200 wallets/transition), then:
  PYTHONUNBUFFERED=1 POLARS_MAX_THREADS=2 .venv/bin/python <scratch>/sel_boot.py
  ```
  Expected qualitative result: `SELAWARE width > FROZEN width`; if `net` is only +5–10 bp the
  selection-aware lower bound may cross zero where the frozen one does not. Note: top-50-of-200 is a
  *milder* selection than the live top-50-of-1500, so the trimmed widening is a **lower bound** on
  the real effect.

## What I checked and could rule OUT
- **Per-RT vs per-wallet resampling (Known #8):** NOT violated in the core mechanism — `_boot_ci`
  resamples per-wallet arrays (`idx = arange(len(arrays))`, line 84) and concatenates each picked
  array whole (86-87), so each wallet's RTs move together. The only cluster defect is the
  cross-transition one (F3).
- **Cost double-subtraction:** ruled out. Cost is the constant `args.cost_bps` (8 bp), subtracted
  once in `_boot_ci` (line 87) and once for the headline `net` (line 159); not applied anywhere in
  `price()`/`extract_positions`/`_positions_for`. ✓
- **Look-ahead / seam / startPosition:** out of this task's scope (other agents); not re-checked.

## Resource note (for the coordinator)
`scripts/edge_sweep.py` at the sanctioned config (full 1500-wallet/transition universe) ran >9 min
and spiked to ~1.6 GB RSS on this 8 GB box before I killed it; output is block-buffered to a
redirected file so nothing prints until process exit, and the `timeout 300` in the task would kill
it before any result appears. Even a 300-wallet/transition trim hit ~1.6 GB (the footprint is
polars/arrow accumulation across many per-wallet reads plus `Position`-object extraction, not the
candles — candles are only 17 MB). Recommendation for future dynamic runs of this script:
`PYTHONUNBUFFERED=1`, a trimmed universe, and a hard RSS guard. I did NOT load any monthly file.
