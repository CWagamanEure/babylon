# Alt-timing v2 (MAKER-ONLY tilt) — PRE-REGISTRATION (frozen 2026-07-11, BEFORE any forward data)

Pre-registered **secondary** signal for the alt-complex-timing paper follower, added as a prospective A/B
alongside the deployed v1 (combined breadth tilt). Origin: FINDINGS Result 9b (9-agent audit swarm). **PAPER
ONLY — no signing/capital.** Freeze these rules now; do not revise retroactively. Parent prereg (all rules
inherited unless overridden here): `docs/ALT_TIMING_PAPER_PREREG.md`.

## Why v2 exists (the in-sample evidence — honestly labelled)
The v1 tilt pools each cohort wallet's MAKER (passive, crossed=false) and TAKER (aggressor, crossed=true) fills
into one directional vote. Result 9b found the taker fills are ~noise (per-fold z ≈ −0.24) and DILUTE a real
maker sub-signal — the same "aggregator buries a sub-signal" failure that Result 8 already demonstrated on this
line (net-notional vs breadth). Restricting the vote to **maker fills only**:
- lifts the **honest full 7-month walk-forward** OOS IC from +0.0043 → **+0.0195 (4.5×)**, z_vs_random +2.5–2.9,
  5/7 folds positive (vs 3/7), and it **recovers the previously-negative regime months** (202602 z −0.86→+3.20;
  202605 +0.47→+2.54). Unlike v1's "+2.0", this lift is on the FULL window, not a favorable 4-of-7 subwindow.
- ⚠️ **NOT yet significant / NOT confirmed:** day-block 95% CI **[−0.0094, +0.0458] still crosses zero**; it is
  the **argmax of 6** aggregators tried (Bonferroni×6 → adj-p ≈ 0.02–0.07, borderline); Fisher (iid) MDE 0.035 >
  observed 0.0195. It is a **lead requiring PROSPECTIVE confirmation**, not an established edge. That is precisely
  why it is pre-registered here and logged forward — never retroactively swapped in.

## The v2 signal (frozen)
- **Cohort / basket / horizon / smoothing / target / cost / neutralization:** IDENTICAL to v1 (same frozen
  `data/derived/alt_timing/cohort.json` recency-gated top-1500, same 7-name basket, H=1h primary, same 8h smooth,
  same BTC/ETH-neutral alt-index target). The ONLY change from v1 is the fill filter.
- **Signal:** `maker_tilt = (#net-long − #net-short)/(#active)` over the alt universe, counting **only each
  wallet's crossed=false (passive/maker) fills** for the hour. Implemented in
  `src/babylon/follow/alt_timing_main.py::compute_tilt(..., maker_only=True)`; logged every hour as
  `maker_tilt` + `maker_n_active` in `alt_timing_log.jsonl`, ALONGSIDE the unchanged v1 `tilt`/`n_active`.
  Position (offline) = sign(8h-smoothed maker_tilt).

## Verdict rule (frozen; A/B vs v1)
- **PRIMARY metric:** annualized net Sharpe of the sign(smoothed maker_tilt) book at top-tier taker fee (2.4bp),
  day-block 95% CI, over the forward window only. **SECONDARY:** forward IC of live maker_tilt vs the BTC/ETH-
  neutral basket return (z vs random-cohort); net Sharpe at maker(0)/base(4.5) fee; per-month sign.
- **MIN WINDOW before ANY v2 verdict:** same as v1 — 6 forward months or 120 active trading days, whichever later.
- **v2 PROMOTED to primary** ONLY if, on the forward window, it beats v1 on PRIMARY net Sharpe AND its own CI-low
  > 0 AND positive in ≥⌈70%⌉ of forward months. Until then v1 remains the deployed signal; v2 is record-only.
- **v2 KILLED** if PRIMARY point estimate ≤ 0 over a ≥6-month forward window. In between = CONTINUE accumulating.

## Guards (frozen — the anti-over-carry rules, learned from v1's mistake)
- **All-fold reporting is mandatory.** Any v2 (and v1) verdict cites the FULL per-fold breakdown of every
  forward month, never a pooled headline that can silently re-dilute a regime split, and never a hand-picked
  favorable subwindow (the exact error that produced v1's overstated "+2.0"; see Result 9b).
- No re-tuning of horizon/smooth/cohort-size/basket on forward data. The maker/taker split is the ONLY new lever
  registered; further aggregator ideas require their own dated pre-registration before scoring.
- v2 is evaluated on the SAME forward hours as v1 (shared cohort export as_of), so the A/B is apples-to-apples.
- The in-sample +0.0195 / 4.5× numbers are NOT evidence for deployment; they only justify collecting the record.

## Excluded / not claimed
- Any capital deployment (paper only). Any retroactive swap of the live signal. Any v2 verdict before the min
  window. Any claim that v2 "works" from the in-sample lift — its CI crosses zero and it is an argmax; only the
  forward record adjudicates.
