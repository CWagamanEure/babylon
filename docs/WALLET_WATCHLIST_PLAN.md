# WALLET WATCHLIST PLAN — monthly best-bet compilation + self-scoring (frozen 2026-07-10)

Stance: prediction and decision. The list IS what the droplet paper-follower copies — one process, one
scoreboard. Selector mining stays CLOSED: membership comes verbatim from the frozen rolling selector
(`rolling_wf live` → `live_basket.parquet`); this plan only annotates, tiers, sets expectations, and scores.
Implementation: `research/data/watchlist.py`. Reports: `docs/WALLET_WATCHLIST_YYYY-MM.md`.

## Evidence basis (the 360-slot forward dataset, synthesis 2026-07-10)
Built from every basket slot ever selected (3 selectors × all windows) joined to its NEXT-MONTH realized
markout. What it established — and the plan's weights follow it exactly:
- **Activity/recency is the strongest predictor in the repo**: recency ≤4d ⇒ 0.99 next-month trade hazard;
  days30 ≥15 ⇒ 0.91; days30 ↔ next-month volume r≈+0.5. ⇒ **first-class tiering term.**
- **1h horizon cohort: +11.2 ±5.3 bp forward** (6/8 months, cross-coin) — the only cohort clearing the
  realistic 10.5bp cost line. ⇒ **tilt.**
- **Discovery magnitude: weak, NON-monotonic** (60–100bp discovery bin goes NEGATIVE forward). ⇒ capped
  tie-break only (cap 60bp), never selection.
- **Recurrence bonus is DEAD**: clean prior-windows-only measurement = repeats −15.9 vs first-timers +6.4
  (the earlier +43bp was look-ahead). ⇒ **no points; informational label only.**
- **Cross-selector consensus: no slot-level effect** (2-source slots −7.5, n=6). ⇒ label only.
- Steadiness/consistency metrics, within-basket score rank, selector identity as slot quality: all ≈0.
- **Residual next-month markout among active slots is unpredicted** (all |r| ≤0.12 < MDE 0.17) — which is
  WHY activity, horizon, and cost lines are the whole ranking; nothing else measured helps.
- **Two evidence-backed names**: `0xd7dc4b…14cb5` HYPE (positive every substantive month for 11 months +
  independent protocol confirmation + own PnL) ⇒ ★ tier. `0x42bbf95f…bccc0` BTC (6/6 positive forward
  slot-months — post-hoc-selected record) ⇒ "elevated, watch with caveat".

## Tiering (implemented)
- Membership: the frozen top-20, never edited.
- **★** = independently-confirmed name(s). **A** = days30 ≥15 AND recency ≤4d (near-certain exposure).
  **B** = the rest. Within tier: S = 3·(days30≥15) + 2·(recency≤4) + 2·(horizon=1h) + min(disc_gross,60)/60.
- Labels (no points): HYPE-discount (halve trust), persistence-consensus rank, elevated-watch.
- **Steady bench**: persistence-score top-20 not on the copy list — highest survival cohort (7% attrition),
  edge below cost. Pipeline and corroboration, not PnL.

## Expectations printed in every report (measured forward numbers, not discovery)
Average active slot ≈ +4 bp gross/day (below both cost lines at flat weighting); 1h cohort ≈ +11 bp (clears
10.5bp for ~half its slots); day-weighted portfolio cleared the 5bp line 4/5 historical months (placebo
0/500). Tier A activity odds 0.91–0.99; list-wide ~0.8. Standing rule: discovery bp ≠ forecast.

## Watch protocol (monthly, automatic — no discretionary edits)
Two feeds: (1) droplet `realized.jsonl` (A1 un-fold formula — the pre-registered verdict series, untouched);
(2) tape-anchored per-wallet re-measure at the frozen horizon (`watchlist.py::_tape_month_score`).
Scorecard rows appended per wallet per month; statuses RE-SELECTED / ROTATED-OUT / ATTRITED / PROMOTED.
Running hypotheses reported each month: H1 Tier A > Tier B (tests the tiering), H2 the pre-registered
recurrence-weighted exploratory series, H3 steady-bench vs copy-list attrition. Weight revisions allowed
only from ≥4 months of H1 evidence, logged in the findings ledger; frozen selectors and prereg untouched.

## Monthly refresh (1st of month)
ingest month → episodes/markout/mu pipeline → `rolling_wf live` → archive basket copy to
`data/derived/rolling_wf/history/` → `python -m research.data.watchlist` (scores last month, compiles the
report) → `./scripts/deploy_basket.sh` → one refresh line in FORWARD_PAPER_PREREG.md + ledger.

Footnote (the one): the generating process is a favorable-direction, not-yet-established positive; the live
paper scoreboard settles it.
