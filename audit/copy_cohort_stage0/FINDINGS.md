# AUDIT FINDINGS — copy_cohort Stage-0 code (build-stage swarm, 2026-07-12)

Four agents (correctness, stats-rigor, data-integrity, determinism-repro) against the NEW code:
`research/lib/stats.py` additions (`sign_flip_pvalue` cluster variant, `t_ppf`,
`twoway_cluster_ci`, `eb_shrink`), `research/studies/copy_cohort/mu_fold.py`,
`research/studies/copy_cohort/stage0_dependence.py`, and the materialized
`data/derived/copy_cohort/stage0_y.parquet`.

**Disposition: all findings accepted and fixed in place before the Stage-0 run; the y panel was
rebuilt deterministic.** Severities: 0 CRITICAL, 2 HIGH, 5 MED, rest LOW/NIT.

## Verified-exact clean bills (the load-bearing machinery)

- Flip-calibration vectorized algebra ≡ brute-force CR0 on flipped data (0/200 mismatches, 1e-17).
- eb_shrink MoM τ̂² unbiased (probe 4.06 vs true 4.0); composite-key/scatter index algebra correct.
- Two-way CGM CI coverage 0.958 at nominal 95% on study dims; CR1 and intersection-cell variants
  move coverage < 0.5 pp — spec-faithful and conservative-direction only.
- Data path: y recomputed exactly from an independently rebuilt μ (0/22); straddle-week censor
  exact to the minute (6,961); cross-month episodes included with zero differential drop;
  finalize-month trap avoided; iso-week keys identical both sides; join populations collision-free.
- Seeding discipline fully clean (all paths explicitly seeded, no module-level RNG).

## Fixed (by finding)

- **[HIGH det] build COPY had no ORDER BY under `preserve_insertion_order=false`** → total-order
  `ORDER BY wallet, coin, open_ts, opener_block, opener_event_index` + `PRAGMA threads=1` for the
  build (deterministic μ AVG); opener keys added to the panel (also fixes the traceability NIT).
- **[HIGH det] `load()` row order unspecified → ε float-sum drift could reach the frozen decision**
  → same total ORDER BY on the load SELECT.
- **[MED cor+stats] wallet-coin-day (open_ts) not nested in wallet-week (entry_bar_ts) — crash in
  the rung diagnostic (14 straddling clusters found in 1/32 of one coin)** → all clustering keys
  re-anchored on open_ts; entry-tick week retained only for the μ join; rung skips-and-counts
  non-nested wallets; supporting diagnostics wrapped so they can never destroy the decisional report.
- **[MED stats] eb_shrink estimand drift (mean-of-cluster-means vs registered episode-equal-weight
  mean)** → frozen to episode-equal-weight with CR1·CR0 cluster-sandwich noise; ARCH §4 updated.
- **[MED stats] MIN_EP_CAL=10 unregistered; superset population could bias adoption finer** →
  registered in ARCH §2; adoption now requires calibration on BOTH the ≥10 and the ≥30 (F1-level)
  populations.
- **[MED det] no provenance** → `_STAGE0_META.json` sidecar (code_commit, markout/mu schema
  versions, counts); `run` asserts schema-version match and echoes provenance into the report.
- **[LOW×6, NIT×8]** t critical at G−1 in both flip tests; `t_ppf` raises below df=4 and docstring
  corrected (df=1 underestimates 9.7 vs 12.7); identical seed across candidate levels (paired
  comparison); `flip_chunk` frozen into config; descriptives lexsort tiebreak (same-ms opens);
  errstate + var≤0-counts-as-reject documented; eb_shrink NaN refusal; μ-join drop count logged;
  coverage sim n_sim→4000 + heavy-tailed cluster-size variant; se_over_wallets ddof=1; docstring
  population claim corrected; μ `≤`-vs-`<` one-tick asymmetry documented in ARCH §1; join-key
  uniqueness caveat documented in ARCH §1.

## Accepted-as-is (recorded, no change)

- CGM third term uses V_iid rather than the intersection-cell variance — matches the frozen S1 spec;
  probed direction is conservative (SE overstated ≤ 1.2%).
- Pool mean excludes single-cluster units; measured-zero v_w → B≈1 corner — documented in docstring.
- ICC singleton-group exclusion (standard ANOVA practice, non-decisional).
