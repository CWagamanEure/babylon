# T-only vs T∩P formation-feature split — HYPOTHESIS-GENERATION

**⚠️ HYPOTHESIS-GENERATION ONLY.** The groups (T-only forward robust +49bp vs T∩P +2.7bp)
were defined *using forward returns*; every feature below was screened against those
labels, ~24 features tested with no multiplicity control. Any candidate rule REQUIRES
registered confirmation on new (post-202606) data before it is evidence of anything.

Unit = arm-T membership (fold, wallet), folds 202511–202606: 130 T-only, 110 T∩P (130 P-only shown as contrast — the −33bp group).
Formation features = 3 formation months strictly before the fold (leakage-safe by
construction); sources: lake wallet_coin_day, open_entries, cohort-json selector stats.
Table: `data/derived/copy_cohort/tsplit_features.parquet`; build/analyze scripts alongside this file.

| feature | T-only med | T∩P med | P-only med | MW p | rank-biserial |
|---|---:|---:|---:|---:|---:|
| selector z | 6.22 | 7.46 | -7.94 | 3.8e-38 | -0.97 |
| p_informed | 1 | 1 | 1 | 2.3e-26 | -0.80 |
| selector t-stat | 7.85 | 9.15 | -11.6 | 1e-22 | -0.74 |
| selector nd (active days) | 49.0 | 86.5 | 71.0 | 6e-19 | -0.67 |
| formation active days (wcd) | 49.0 | 86.5 | 71.0 | 6e-19 | -0.67 |
| n entries (3mo) | 146.0 | 308.0 | 258.0 | 0.00012 | -0.32 |
| n fills (3mo) | 2,230 | 6,186 | 1,224 | 0.00018 | -0.28 |
| pnl total ($) | 3,867 | 20,178 | -1.95 | 0.00025 | -0.27 |
| total notional ($) | 938,457 | 4,056,145 | 359,290 | 0.0048 | -0.21 |
| taker share | 0.46 | 0.423 | 1 | 0.03 | +0.16 |
| fills / active day | 43.9 | 75.9 | 15.6 | 0.04 | -0.15 |
| coin breadth | 4 | 15.0 | 2 | 0.067 | -0.14 |
| notional / active day ($) | 21,279 | 55,762 | 4,917 | 0.075 | -0.13 |
| n open-from-flat | 104.5 | 207.0 | 189.0 | 0.11 | -0.12 |
| entries / active day | 4.44 | 4.9 | 3.58 | 0.22 | -0.10 |
| majors (BTC/ETH/SOL) notional share | 0.0628 | 0.0188 | 0.986 | 0.33 | +0.07 |
| scale_med_notl ($) | 332.3 | 358.9 | 231.8 | 0.61 | +0.04 |
| median entry notional ($) | 332.3 | 358.9 | 231.8 | 0.61 | +0.04 |
| fee total ($) | 128.8 | 502.5 | 13.5 | 0.62 | -0.12 |
| dust entry share (<$100) | 0.221 | 0.226 | 0.272 | 0.63 | -0.04 |
| open-from-flat / day | 2.43 | 2.77 | 2.33 | 0.66 | +0.03 |
| capday metric | 36.8 | 26.7 | -1.67 | 0.82 | +0.02 |
| n liquidation fills | 0 | 0 | 0 | 0.89 | +0.00 |
| p90 entry notional ($) | 570.7 | 661.5 | 662.2 | 0.99 | +0.00 |

## Single-threshold separation (top features)

- selector z: T-only <= 6.84 → balanced accuracy 0.93
- p_informed: T-only <= 1 → balanced accuracy 0.83
- selector t-stat: T-only <= 8.19 → balanced accuracy 0.80
- selector nd (active days): T-only <= 66.0 → balanced accuracy 0.78
- formation active days (wcd): T-only <= 66.0 → balanced accuracy 0.78
- n entries (3mo): T-only <= 154.0 → balanced accuracy 0.66
- n fills (3mo): T-only <= 4,868 → balanced accuracy 0.62
- pnl total ($): T-only <= 27,864 → balanced accuracy 0.62

## Reading (hypothesis, not finding)

**The split is essentially ONE-dimensional in selector z (informedness strength).**
Rule `sel_z <= 6.84` alone: captures 117/130 T-only, excludes 105/110 T∩P (balanced
accuracy 0.93; of the 122 memberships with z ≤ 6.84, 117 = 96% are T-only). t-stat, nd
(activity history length), n_fills, realized pnl are all correlates of the same axis:
T∩P = the *extreme-signal, long-history, big-realized-PnL* end of T — exactly the wallets
that also clear the realized-PnL top-30 (arm P). Within the z-overlap band (z 6.85–7.01,
n = 6 vs 11) nothing else separates significantly (all p > 0.28), though the band is too
small to rule secondary features in or out.

**It is NOT the botlike-end story.** Entries/day (p = 0.22), dust share (p = 0.63),
taker share (p = 0.03 but T-only slightly MORE taker), median/p90 entry notional (p ≥ 0.6)
barely separate. T∩P wallets are bigger and busier, not dustier.

**Candidate interpretation:** within the T top-30, the very-strongest / already-hugely-
profitable wallets (z ≳ 7, ~90 active days, ~$20k formation PnL) contribute the +2.7bp
dead weight — consistent with winner's-curse / already-monetized / crowded signal — while
the moderate-z, shorter-history members (z ≈ 5.5–6.8, ~49 active days, ~$4k PnL) carry
the +49bp. Note the mechanical component: T is ranked by informedness, P by realized PnL,
so T∩P being the high-z end is partly by construction; the *forward-return* difference
between the two ends is the substantive (and unconfirmed) claim.

### Top-3 candidate features (effect sizes, T-only vs T∩P)
1. **selector z** — med 6.22 vs 7.46, rank-biserial −0.97, MW p ≈ 4e-38 (near-total separation)
2. **formation active days (nd)** — med 49 vs 86.5, rb −0.67, p ≈ 6e-19
3. **formation realized pnl** — med $3.9k vs $20.2k, rb −0.27, p ≈ 2.5e-4

### Single best candidate rule
`(in T top-30) AND sel_z <= 6.84` → 122 memberships: 117 T-only (the +49bp group),
5 T∩P. Equivalent softer form: "informed but not extreme: 4 ≲ z ≲ 6.8, nd ≤ 66".
**Requires registered confirmation on post-202606 folds before any use.**

---

## 2026-07-16 — SEMI-FRESH ROBUSTNESS PROBE (new wallets, same months — NOT registered confirmation)

Script `zband_semifresh.py`, report `data/derived/copy_cohort/zband_semifresh_report.json`.
Per fold 202511–202606: pool wallets with z ≤ 6.84, top-30 by t, then EXCLUDE that fold's
arm-T/arm-P top-30 and the frozen 133 → wallets the hypothesis never saw. Forward ALT 8h
markout per `alt_fresh_validate` robust spec (winsor p95, wf ≥ 3, wallet-equal, 4000-rep
wallet-cluster boot, seed 20260716). **Caveat: z-threshold was derived from these months'
forward returns; only the wallets are new (same-regime).**

| cell | n ent | n wal | folds | robust pt | boot 95% CI | P(>0) | raw pt |
|---|---:|---:|---:|---:|---|---:|---:|
| band (z≤6.84, spec) | 3,562 | 52 | 8 | **−0.5 bp** | [−29.8, +28.1] | 0.48 | +7.0 |
| band_post (top-30 after excl.) | 8,364 | 97 | 8 | −6.3 bp | [−24.8, +11.5] | 0.24 | −3.2 |
| complement (z>6.84) | 0 | — | — | — | — | — | — |

- Complement is **empty by construction**: every z > 6.84 wallet in every fold's pool is in
  that fold's arm-T/arm-P top-30 (checked directly; the only 4 semi-fresh z>6.84 wallets,
  fold 202606, had zero priced forward alt entries). The moderate-vs-extreme *contrast*
  is untestable on unseen wallets — z>6.84 membership ≡ original-arm membership.
- Band per-fold means (bp): −51, +120, −3, −20, +29, +79, −23, −35 (3/8 positive; wallets/fold
  1–20). LOO range [−7.1, +8.4] — no single wallet drives it. Strata: ≥$250 −7.5 bp
  (CI[−53, +38]), ≥$1k −17.7 bp (CI[−172, +107]).
- **Read:** the +49 bp T-only effect does NOT transfer: both cells' CI upper bounds (+28.1,
  +11.5) exclude +49, so this is a powered negative *for the hypothesized effect size* on
  semi-fresh wallets. Point estimates ~0/negative. Still inconclusive for a small (≤ +25 bp)
  residual edge. Confound: semi-fresh band wallets are by construction the *weaker-t tail*
  of the z≤6.84 ranking (the strong ones were arm-T members and thus excluded), so this
  refutes "z≤6.84 as a standalone selector generalizes," not strictly the within-arm-T split.
  Net: consistent with the z-band story being overfit to / specific to the original 130.
