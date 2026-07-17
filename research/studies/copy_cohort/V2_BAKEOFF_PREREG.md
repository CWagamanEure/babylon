# V2 SELECTOR BAKEOFF — PREREGISTRATION (candidate-ranking only)

**Registered:** 2026-07-16, BEFORE any forward number of any new method was computed.
**Status of the evaluation months: BURNED.** Folds 202511–202606 have been reused across the
alt-universe validation (ALT_UNIVERSE_PREREG.md), the z-band probe (TSPLIT_HYPOTHESIS.md /
zband_semifresh.py), and multiple prior looks. Therefore this bakeoff is
**CANDIDATE-RANKING ONLY**: its output ranks selector candidates for the live paper trader.
It can NEVER be read as out-of-sample confirmation of any method, including the winner.
The only confirmation instrument that remains is genuinely forward (paper-trader) data.

## Question
Among six frozen formation-side selectors of alt-universe wallets, which produce the best
forward-month alt 8h markout on these (reused) folds — to pick 1–2 arms for the paper trader?

## Data & folds
- Folds T ∈ {202511, 202512, 202601, 202602, 202603, 202604, 202605, 202606}.
- Formation per fold = the 3 calendar months < T (identical to alt_select.py).
- Formation inputs: (i) the frozen per-fold informedness pool
  `data/derived/copy_cohort/informedness/fold=T/pool.parquet` (wallet, nd, mu_capday,
  sd_capday, metric_capday, t_stat, z, p_informed — CAP=$100k capped daily pnl, nd≥15, sd>0);
  (ii) lake `alt_universe_wallet_coin_day` (day re-aggregations); (iii) lake
  `alt_universe_open_entries` (formation entry notional). Lake access via
  `research/studies/copy_cohort/lake.py`.
- **Fresh-comparability exclusion:** the 133 frozen wallets
  (`frozen_alt_universe.json.distinct_wallets`) are removed from every fold's pool BEFORE
  ranking, for every method. (Note this differs from alt_fresh_validate's select-then-exclude;
  method (a) is therefore the exclude-then-select variant of arm T, expected close to but not
  identical to the known arm-T FRESH result.)
- Eligibility for all methods: presence in pool.parquet (nd≥15, sd>0 already enforced).

## The six methods (all frozen; each selects top-30 wallets per fold)
(a) **t_v1** — top-30 by `t_stat` desc. Baseline; its (select-then-exclude) fresh result is
    already known: robust +24.5 bp, CI [−3.0, +51.2], P(>0)=0.96 (alt_fresh_validation_report,
    arm T, H1_fresh). Result known ⇒ burned by construction.
(b) **zband** — keep `z ≤ 6.84`, then top-30 by `t_stat` desc. This is the zband_semifresh
    band cell WITHOUT the arm-T/P exclusion (only the frozen-133 exclusion), for
    comparability with the other five methods. The 6.84 threshold came from these months'
    forward returns (TSPLIT_HYPOTHESIS.md) ⇒ doubly burned.
(c) **winsor_t** — t-stat recomputed on per-wallet p5/p95-winsorized daily capped pnl.
    Day series rebuilt from lake wallet_coin_day exactly as alt_select._pool_panel
    (SUM(pnl)−SUM(fee) per wallet-day across ALL coins, × LEAST(1, 100k/notional)).
    Winsorization: per wallet, clip its own day series to [p5, p95] (np.percentile, linear
    interpolation); t_w = mean_w / (sd_w/√nd), sd ddof=1; require sd_w > 0.
    **Cost-bounding prefilter (registered):** day series computed only for the per-fold
    top-500 wallets by `t_stat` (post frozen-133 exclusion); top-30 by t_w within them.
    Approximation is acknowledged: a wallet outside the t top-500 cannot be selected.
(d) **sign_stat** — binomial z of fraction-positive formation days:
    n_pos = #days with capped day-pnl > 0 (zeros count as non-positive);
    z_sign = (n_pos − nd/2)/√(nd/4). Top-30 by z_sign desc, ties broken by `t_stat` desc.
(e) **t_noliq** — as (a) but wallets with ANY formation liquidation fill excluded
    (SUM(n_liq) > 0 over formation wallet_coin_day ⇒ out). Top-30 by `t_stat`.
(f) **t_notional** — as (a) but restricted to wallets with formation median flat-open entry
    notional ≥ $250 (median of CAST(notl AS DOUBLE) over formation open_entries).
    **Cost-bounding prefilter (registered):** medians computed for the per-fold top-500 by
    `t_stat`; if fewer than 30 of those pass the $250 gate, extend the prefilter to top-2000
    and recompute. Top-30 by `t_stat` among passers.

## Forward evaluation (identical to alt_fresh_validate.py; its functions imported)
- Forward book per fold: selected wallets' TEST-month flat taker opens (lake open_entries),
  ALT coins only (exclude BTC/ETH/SOL/HYPE), 8h gross dir-signed markout on the local
  asset_ctx mid lattice (backward ASOF, ≤90s staleness both ends)
  = `alt_fresh_validate._forward_entries`.
- **Registered headline spec (robust):** winsor at p95 |mk| within the entry set, keep
  wallet-folds with ≥3 evaluable entries, wallet-fold-equal mean of means
  (`_robust_mask` + `_wallet_equal`). Raw point reported alongside, never headline.
- Uncertainty: wallet-cluster bootstrap, 4000 reps (`_cluster_boot`), seed = 20260716 with
  per-method rng `default_rng(SEED + 1000 + method_index)` (method order as listed a→f).
- Also reported per method: per-fold means of robust wallet-fold means, per-fold wallet
  counts, leave-one-wallet-out extremes, and the **≥$250 forward-notional stratum** (robust
  point + its own boot, rng `SEED + 2000 + method_index`), n entries / wallets.
- **One-sided p per method** (H1: robust wallet-equal mean > 0):
  p = (#{boot draws ≤ 0} + 1) / (n_valid + 1).
- **Multiplicity:** Benjamini–Hochberg across the 6 methods on the one-sided p's; report
  BH-adjusted p (step-up, monotonicity enforced). NOTE: BH here controls only the within-
  bakeoff comparison — it cannot repair the months' reuse.

## Decision rule (for paper-trader arm selection, registered)
Rank methods by robust point estimate; recommend 1–2 arms preferring (in order):
1. robust point ≥ baseline t_v1's robust point − 5 bp AND P(>0) ≥ 0.90;
2. mechanistic diversity vs t_v1 (a non-t ranking family beats a t-variant at equal showing);
3. per-fold breadth (positive mean in ≥5 of 8 folds) over a concentrated blowup.
If no method clears (1), recommend t_v1 alone (status quo) — the bakeoff then simply failed
to find a better candidate; it does NOT demote t_v1 (its evidence is unchanged).

## Honesty stamps
- Every number produced here inherits the reuse taint of 202511–202606. Adjectives allowed:
  "candidate-ranking", "burned-fold". Adjectives banned: "confirmed", "validated", "OOS".
- No method may be dropped or added after this registration; no parameter may be tuned after
  seeing forward numbers. Any deviation must be logged in the Results section below.

## Artifacts
- Code: `research/studies/copy_cohort/v2_bakeoff.py` (imports alt_fresh_validate evaluation).
- Report: `data/derived/copy_cohort/v2_bakeoff_report.json`.
- Results table appended below after the run.

---

# RESULTS (run 2026-07-16, exit clean, no deviations from the registration)

⚠️ **REUSE STAMP: every number below is on BURNED folds (202511–202606). This table RANKS
paper-trader candidates. It confirms nothing. BH-adjusted p's control only the within-bakeoff
comparison and cannot repair the months' reuse.**

Robust spec = winsor p95 |mk|, wallet-folds ≥3, wallet-fold-equal; wallet-cluster boot (4000).

| method     | robust bp | 95% CI          | P(>0) | p 1-sided | BH-adj p | n entries | n wallets | folds + | ≥$250 stratum bp (CI, P>0) |
|------------|----------:|-----------------|------:|----------:|---------:|----------:|----------:|--------:|-----------------------------|
| t_v1       | **+27.6** | [+0.7, +53.1]   | 0.98  | 0.023     | 0.070    | 11,884    | 64        | 7/8     | +49.5 ([+9.7,+84.5], 0.99)  |
| t_noliq    | **+27.4** | [+2.6, +51.1]   | 0.98  | 0.016     | 0.070    | 12,265    | 67        | 8/8     | +38.8 ([+9.7,+65.4], 1.00)  |
| zband      | +15.6     | [−10.9, +40.1]  | 0.88  | 0.123     | 0.188    | 9,557     | 80        | 4/8     | +15.6 ([−26.1,+51.1], 0.77) |
| t_notional | +13.0     | [−9.1, +34.2]   | 0.87  | 0.125     | 0.188    | 8,717     | 83        | 5/8     | +18.9 ([−6.4,+42.2], 0.93)  |
| winsor_t   | +5.9      | [−19.8, +28.8]  | 0.68  | 0.319     | 0.319    | 14,320    | 66        | 4/8     | +36.0 ([+3.5,+68.1], 0.98)  |
| sign_stat  | +5.1      | [−13.7, +22.4]  | 0.71  | 0.292     | 0.319    | 17,569    | 71        | 4/8     | +25.3 ([−11.0,+58.4], 0.91) |

("folds +" = folds with positive robust per-fold mean. Raw points, per-fold means, LOO
extremes, selection lists and overlaps in the JSON report.)

## Honest read
- **No method beats the t-stat family.** The two leaders, t_v1 and t_noliq, share 27–30 of
  30 wallets per fold — t_noliq is t_v1 minus formation-liquidated wallets, i.e. a near-
  duplicate, not an independent confirmation. Its edge over t_v1: tighter CI ([+2.6,+51.1]
  vs [+0.7,+53.1]) and 8/8 positive folds vs 7/8 (it dodges t_v1's −33 bp 202511 fold).
- **Every genuinely different ranking family did worse.** zband (+15.6), t_notional (+13.0),
  winsor_t (+5.9), sign_stat (+5.1) all have CIs spanning 0 — on burned folds this is a
  ranking datum, not evidence they are dead; but none earns a paper-trader slot over t.
  Notably the burned-in z≤6.84 band, which looked strong in the semifresh probe framing,
  does NOT beat plain t once the T/P-exclusion is dropped and both compete on equal terms.
- **Nothing is BH-significant at 0.05** (min BH-adj p = 0.070) even before the reuse taint —
  consistent with the standing AMBER "underpowered positive, not deployable" status of the
  line. The ≥$250 forward-notional stratum is stronger than the full book for both leaders
  (t_v1 +49.5, t_noliq +38.8, both CIs excluding 0 — same burned-fold caveat).
- **Per registered decision rule:** t_noliq clears gate (1) (within 5 bp of t_v1, P>0 ≥ 0.90);
  no non-t family clears; t_noliq wins tiebreak (3) on breadth (8/8).

## Recommendation for the paper trader (candidate-ranking output, not a validation)
1. **t_v1** (status quo baseline) — keep as the primary arm; every alternative was ranked
   against it and none beat it.
2. **t_noliq** — the one variant matching t_v1's point with a tighter CI and 8/8 fold
   breadth; run it as the second arm. Because the cohorts overlap ~90%, treat the paper-
   trader comparison as a *marginal* test of the no-liquidation filter, not an independent
   strategy; genuinely forward data is the only instrument that can separate them.
   Weight entries toward the ≥$250 stratum if the book design allows.
