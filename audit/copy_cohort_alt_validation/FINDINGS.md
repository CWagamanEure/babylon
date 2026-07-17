# Alt external validation — adversarial passes (2026-07-16)

Run: `capday_alt_validate.py` on `alt_episodes/` (2,495 evaluable in-test → 717 cohort-member entries:
258 LARGE / 459 SMALL, 25 LARGE wallets, 8 folds, 174 coins). Raw output:
`data/derived/copy_cohort/capday_alt_validation_report.json`. Two separate agents, per CLAUDE.md
(steelman-the-positive + prosecute-the-positive), both re-deriving from the parquet with independent code.

## Headline (as printed by the validator — DO NOT QUOTE, see prosecution)
H1 large wallet-equal +196.9bp, boot CI [+22.7,+347.4] P=0.99; H2 Δ +125.7bp CI [−113.3,+363.1]
P(Δ>0)=0.80, 6/8 folds; LOO-wallet min +9.6, LOO-coin min +12.0.

## PROSECUTION (verdict: MATERIALLY WEAKENED — not killed)
- **KILLED: the raw magnitudes and P=0.99.** Excluding wallet-folds with <3 entries: H1 +196.9 → +66.9
  (P=0.883). Wallet-fold sign test 17/26 p=0.084; wallet-collapsed sign 17/25 p=0.054; t=+1.56 (p≈0.13).
  Percentile bootstrap over 26 right-skewed clusters is anti-conservative — honest H1 significance
  p≈0.05–0.13. Raw H2 is carried by ONE entry: drop the +3074bp POPCAT fill → Δ +9.6 P=0.47; drop top-3
  → −14.3. Raw Δ+125.7 is dead.
- **SURVIVES the knife (the prosecutor's own harshest spec):** winsor-p95 + wf≥3 → H1 +108.8 CI
  [+38.8,+174.9] t=+2.29; **H2 +87.4 boot CI [+11.0,+165.3] P=0.987**. Median shift LARGE +42.5 vs
  SMALL −12.8, permutation p=0.004 (median), 0.009 (mean). Tail inflates magnitude, not sign.
- **Mark quality clean:** all lags ≤60s (p50 21s), zero stale px8 fallbacks, zero dupes, 18/717
  overlapping windows; extremes are real 8h alt moves (Nov-2025 alt crash), not lattice artifacts.
- **Dust critique BACKFIRES:** notional Q4 ($495–75k) +187 mean/+93 median; entries ≥$1k: 12/15
  wallet-folds positive, p=0.018. The most copyable entries are the best.
- **Not regime-only:** ex-202511 H2 +92.6 P=0.965. Not clustering-unit: only 1/25 LARGE wallets spans
  folds.
- **Label correction:** "external validation" = same wallets / NEW asset-class returns — one notch
  weaker than a fresh-wallet replication (no multiplicity penalty applies; single registered directional
  hypothesis).
- **Economics:** gross ~+70–110bp core vs realistic alt taker RT 20–100bp → marginal for a taker copier
  as-is (H2 doesn't require absolute profitability per prereg).

## STEELMAN (verdict: MODERATE-REAL)
- Every robust estimator keeps LARGE positive & SMALL ≤0: winsor H1 +125.5 CI [+26.3,+211.3]; drop the
  POPCAT WALLET entirely → +81.8 CI [+3.4,+165.7] P=0.979; trimmed +97–106; entry MW p=0.0044; entry
  sign 151/258 p=0.0037; win rate 58.5% vs 47.1%.
- Breadth: 17/25 LARGE wallets positive (68%) vs 13/33 SMALL (39%); 6/8 folds (the 2 negatives have
  n_large=2 each).
- **Internal control:** SMALL stratum through the identical pipeline/months/coins = −29.5bp (−19.1 on
  LARGE's coins) — kills "alts drifted up" and every pipeline-bias story in one stroke.
- Prereg independence VERIFIED by code-path audit (selection/classification never read an alt return).
- Fourth same-sign scale lead (majors paired Δ, WF β, Q4 quartile, alts) — first three share the tape,
  so corroboration not independence; the alt return series is genuinely disjoint.
- Dose-response: ≥$250 +130 (63% win), ≥$1k +295 (78% win), ≥$5k 9/9 positive — post-hoc, ex-ante
  variable, points toward deployability.

## ADJUDICATED VERDICT (both gates applied)
**DIRECTIONAL REPLICATION, ROBUST-POSITIVE, UNDERPOWERED-AT-RAW-SPEC — the scale signal survives; the
printed magnitudes do not.** Quotable numbers: LARGE−SMALL ≈ **+85–100bp gross** (winsorized, wf≥3, CI
[+11,+165]), median shift +42 vs −13 (perm p=0.004), H1 core ≈ +70–110bp (honest wallet-level
significance p≈0.05–0.13). The prereg's raw-spec H2 clause "not driven by 1 wallet" FAILS (POPCAT), so
this is NOT a clean "externally validated" stamp; the robust-spec versions (not pre-registered) all
clear. Economically marginal for a taker copier at alt costs; strongest exactly where notionals are
copyable.
