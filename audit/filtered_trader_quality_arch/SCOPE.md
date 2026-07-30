# Filtered trader-quality architecture — audit scope

Audit target: `research/studies/copy_cohort/FILTERED_TRADER_QUALITY_ARCH.md`.

This is a design-only audit. No implementation or result exists. Follow `audit/AUDIT_PROTOCOL.md`: read
only, do not load parquet, do not edit files, and tie every finding to a line. Check the architecture against
the existing `majors_native.py`, `gated_backtest.py`, `informed.py`, the copy-cohort findings ledger, and
`docs/BABYLON_PITFALLS.md` as relevant.

The proposed method converts daily $100k-notional-normalized majors PnL to within-day normal-score ranks,
filters a latent wallet state, selects a monthly rolling top 30, and grades the cohort on the existing
majors 8h copy book. The primary comparison is KF-REL versus a same-input t-stat top 30. Historical folds
are burned; forward data alone may confirm.

Audit questions:

1. Is every input and parameter available strictly before its roster cutoff, including daily ranks,
   eligible pools, episode-derived reliability, and pooled state-space parameters?
2. Does the observation/filter model identify the intended relative-quality state, or do missingness,
   activity, risk, rank normalization, or the $100k transformation create a mechanical winner?
3. Is the primary paired book estimand mathematically coherent when arms trade on different days and deploy
   different capital? Are the bootstrap, MDE, planted control, and sign tests adequate?
4. Is the comparison fair to the existing majors-native top-30 and is consensus kept as a non-confounding
   secondary pure-subset gate?
5. Are there underspecified details that would create hidden researcher degrees of freedom during build?

Report only; propose minimal fix sketches but make no edits.
