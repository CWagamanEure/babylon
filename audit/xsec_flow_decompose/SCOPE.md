# AUDIT SCOPE — xsec_flow_decompose (unpool + relax pass, 2026-07-10)

Shared `audit/AUDIT_PROTOCOL.md` ALWAYS holds (resource safety — a build MAY be running; do NOT reload
`data/**` parquet or rebuild panels; verify-before-report; blast-radius severity; NO edits; report format).
You are one of several independent adversarial auditors. Read: `research/studies/wallet_flow/xsec_flow_decompose.py`,
its output `data/derived/xsec_flow_decompose/results.json`, the run log
`/private/tmp/claude-501/-Users-corywagamaneure-bablyon/e7986c68-b22e-4ff8-a672-1a1b4b625c30/scratchpad/decomp_run.log`,
and for construction context `xsec_flow_step0.py` (S0.run_horizon/residualize/fwd_sum/xsec_rank) +
`xsec_flow_adjudicate.py` (ADJ.build_q_fixed / _hour_spreads / _spread_ci / gap_lag / sign_test).

## What was built & the CLAIM being prosecuted
A DECOMPOSE pass on the SAME leak-free OOS cells as the adjudication, run for TWO predictors (V-sim same-hour
demean; V-trail trailing-24h demean, window-bug-fixed), each = one L2-neutralized (⊥crowd,⊥mom) h_train=4 signal:
D1 horizon sweep h∈{1..24} quintile long-short bp/crossing + day-block CI; D2 extremity (quintile/decile/ventile)
+ conviction-weighting; D3 per-coin IC + sign-test-across-coins + ADV tertile; D4 causal-trailing-dispersion regime
split; gap-lag (info vs impact); D5 cost ladder.

**HEADLINE (this just FLIPPED a near-earned-negative to "strongest lead"):** V-TRAIL cross-sectional long-short
spread **+3.6→+6.8 bp/crossing across h=2–12, day-block CI excludes 0 at EVERY horizon in that band**, steepens to
**+9–10bp at the ventile**, **39/45 coins IC>0 (sign p<0.001)**, concentrated in **mid-dispersion** regime
(+9.9bp) and **liquid** names, gap-lag retains **76%/50% through 1h/2h gaps → verdict INFORMATION**, holds on clean
folds (≥202603). **Clears the 3.6bp maker round-trip at h≥4 (net +1.1→+3.2bp); taker-dead; h=24 dead.**

## ⚠️ This flipped a negative to a positive by UNPOOLING + RELAXING THRESHOLDS. That is EXACTLY when over-CARRY
## strikes. Attack the benign explanations, each with `file:line` + a concrete paper scenario:

1. **FORKING PATHS / MULTIPLE COMPARISONS (TOP concern).** The winning cell (predictor=V-trail, h=8–12, ventile,
   mid-dispersion) is an argmax over 2 predictors × 8 horizons × 4 extremities × 3 regimes × {all,clean}. Each CI is
   marginal (per-cell, not multiplicity-adjusted). How many independent looks? Under the full garden of forking
   paths, does ANY cell survive an FDR / Bonferroni correction? Is the "CI excludes 0 across a contiguous h=2–12
   band" genuine robustness or just autocorrelated horizons (overlapping fwd windows → the horizons are NOT
   independent looks)? Estimate the honest family-wise error.
2. **TRAILING-WINDOW AUTOCORRELATION — why is V-trail 2× V-sim?** V-trail demeans a wallet's flow over its
   trailing-24h traded set → a MECHANICALLY more autocorrelated/persistent signal than the same-hour V-sim. The
   gap-lag says INFORMATION (50% survives a 2h gap) — but a 2h gap cannot kill a 24h-window-induced slow-persistence
   / momentum component. Is V-trail's excess over V-sim genuine selection, or trailing-window staleness/momentum the
   L2 ⊥mom neutralization + 2h gap don't fully remove? What single control kills it (e.g. gap g=4/6/8; orthogonalize
   V-trail signal on trailing INDEX momentum; compare V-trail vs V-sim gap-retention head to head)?
3. **COST / MAKER-FILL REALISM.** "Clears 3.6bp maker RT" assumes passive fills at/near mid with NO adverse
   selection — the load-bearing unmodeled assumption on this whole line. The spread is a top-vs-bottom-quintile
   forward RESIDUAL return; is that even earnable by a resting maker order, or does the signal predict exactly the
   names that run away from a passive quote (adverse selection)? Is the per-crossing cost applied correctly given
   turnover (rebalance every h hours, overlapping windows in the estimate)? Is net-per-hour (not net-per-crossing)
   the right deploy metric, and does it still clear?
4. **QUINTILE-SPREAD ESTIMATOR + CI CORRECTNESS.** `_hour_spreads`/`_hour_spreads_ext`: per-hour top-vs-bottom
   frac, mean of fwd_sum VALUES ×1e4. Is the day-block bootstrap (`_spread_ci`) valid when the per-hour spreads use
   OVERLAPPING h-hour forward windows (adjacent hours share returns → autocorrelated → CI too tight)? Does the
   ventile (n//20 per side) have enough names per hour (45 alts → ~2/side) to be anything but noise? Is `best_h` by
   net-per-hour a defensible selector or a variance-maximiser?
5. **LEAKAGE at the V-trail fold seam + regime/ADV PIT.** Is q_trail strictly causal at the test seam (trailing
   window uses only ≤t rows; the "window-bug fix" `searchsorted(...,side='right')` = last sibling of hour r, verify
   it does not reach r+1)? Is the ADV tertile strictly pre-formation (30d before UNIV_FORMATION)? Is the regime var
   (trailing xsec dispersion of LAG_ac) strictly ≤t? Any test-month info in the L2 residualization (per-hour lstsq
   pools the test month cross-section — is that a leak or benign within-hour centering)?
6. **PER-COIN sign test independence.** 39/45 coins IC>0 p<0.001 treats coins as independent — but alts co-move
   (shared alt-beta) and the signal is one cohort's flow → coins are NOT independent. Does the breadth survive a
   coin-block / sector bootstrap, or is 39/45 really ~1 correlated bet?

## Two mandatory opposed passes (over-null / over-carry, per CLAUDE.md)
- **PROSECUTOR (over-carry, PRIMARY here):** the whole benign story — forking paths + trailing autocorrelation +
  adverse-selection-eats-maker + non-independent coins. Argue the flip is an artifact. What ONE pre-registered
  single-config walk-forward would most cleanly confirm-or-kill it?
- **STEELMAN (over-null, equal standing):** is it even BIGGER/realer — ventile+mid-dispersion+conviction stack, is
  V-trail genuinely the better predictor, what is the cleanest deployable operating point, is the maker path real?

Report per protocol, most-severe first, file:line + scenario + confidence. A clean bill is valid. WIN CONDITION
for this line = COST (maker-clearing net-per-hour after realistic fill), not IC. Statistical GREEN ≠ deployable.
