# PRE-REGISTERED confirmatory protocol — wallet entry-timing edge (frozen 2026-07-09)

⚠️ ASTERISK (pre-registered honestly): the Aug–Jun tape, INCLUDING the OOS window, has been examined in prior
exploratory analyses this week. This run is therefore **protocol-clean but data-contaminated** — survivors are
PROVISIONAL until re-confirmed on true forward data (July 2026+, untouched). The protocol below is frozen
verbatim for that forward re-run.

## Frozen parameters (no knob may change after results are seen)
- Estimand: `timing_alpha = raw_markout − dir_sign·μ_h(coin, period)` on oracle_px; **episode-weighted**
  (plain mean over episodes) aggregation. μ computed per-period with `t+h ≤ period_end`.
- Horizons: {1h, 2h, 4h, 8h}. **HYPE-8h cell excluded** (known stale-oracle pathology, pre-registered).
- Split: discovery = [2025-08-01, 2026-02-01), OOS = [2026-02-01, 2026-06-29).
- Cost hurdle: **5 bp round-trip** (2.5 bp/side). Care-about: 8 bp.
- Bootstrap: day-block, B = 10,000, seed 20260709. Distinct-day floor: ≥ 10 (else not-testable, not failed).
- FDR: **BH**, q = 0.10 (discovery and OOS Tier B).

## Stage 1 — DISCOVERY (earlier period only)
Eligibility (activity/copyability — costless gates):
  E1 ≥200 fills; E2 ≥8 active ISO weeks; E3 ≥$1M notional; E4 twap-flag share <30%; E5 liq share <10%;
  E6 taker share ≥50% (copyable entries); E7 ≥10 distinct entry-days;
  E8 horizon–hold consistency: frozen horizon ≤ 4 × median hold duration.
Performance selection (performance-based ⇒ discovery-only, per protocol):
  S1 best_horizon = argmax over eligible horizons of discovery est; require est > 8 bp;
  S2 realized net PnL > 0 in discovery (must monetize own entries);
  S3 drop-best-day: discovery mean at best horizon stays > 0 excluding best day;
  S4 one horizon-adjusted p per wallet: day-block bootstrap p at best horizon × 4 (Bonferroni over the
     horizon search), BH-FDR q=0.10 → CANDIDATES.
Freeze per candidate: (wallet, coin, horizon, weighting=episode, cost=5bp). Written to
`data/derived/confirmatory/candidates.parquet` before any OOS number is computed.

## Stage 2 — OOS CONFIRMATION (later period, frozen horizon only, no argmax)
- OOS testability (activity-only): ≥10 distinct entry-days, ≥5 episodes in OOS. Untestable ≠ failed; reported.
- **Tier A (PRIMARY) — basket test:** equal-weight per trader; per-day basket alpha = mean over candidates
  active that day (handles cross-trader same-day correlation); day-block bootstrap over OOS days;
  H0: basket edge ≤ 0, one p-value. Report point estimate, 95% CI, MDE, and estimate vs 5 bp cost.
- **Tier B (secondary) — per-trader:** day-block bootstrap H0: edge ≤ 0 at the frozen horizon; BH-FDR q=0.10;
  then economic filter: OOS point estimate > 5 bp (an estimate check, NOT a significance test).
- **Attribution (secondary) — style-matched null for the basket:** B=1,000 draws replacing each candidate's OOS
  entries with random price-grid minutes matched to the wallet's own hour-of-day distribution (direction kept);
  p_style = fraction of null basket means ≥ observed. Distinguishes timing skill from structural footprint.

## AMENDMENTS (each dated, motivated, and made before any forward data exists)
- **A1 (2026-07-09) — S2 (realized net PnL > 0) REMOVED from discovery.** Motivation: user's external-repo
  evidence that it over-filters + measured cut of 75% of the eligible pool (11,562 → 2,878); it gates on the
  wrong quantity (realized PnL bundles exits/fees/funding while the estimand and copy design use only entries),
  and its target failure mode (markout-positive but non-monetizable) is covered by the style-matched attribution
  test and the OOS cost hurdle. Discovery-period net PnL is retained as a REPORTED column on candidates (for
  portfolio construction), not a gate. Middle option (gross-before-fees > 0, pool 4,902) documented but not used.
- **A1+A2 were ALSO applied retrospectively to the Aug–Jun tape on 2026-07-09** (results:
  `WALLET_CANDIDATES_2026-07-09.md`, asterisked as previously-examined data; code defaults now implement them,
  `Q_DISC=0.20`). The frozen-params line "q=0.10 (discovery)" describes the ORIGINAL protocol only.
- **A2 (2026-07-09, for the forward run) — discovery FDR may be loosened to q=0.20** (or S4 dropped, S1–S3 only)
  to grow the confirmed-basket size; discovery false positives are cheap because OOS gates them.

## Verdict rules (frozen)
- Basket CONFIRMED iff Tier A CI-low > 0 AND point estimate > 5 bp. Basket earned-null iff MDE ≤ 8 bp and
  CI-high < 8 bp. Else INCONCLUSIVE.
- A wallet is CONFIRMED iff it survives Tier B FDR AND its OOS estimate > 5 bp.
- p_style ≥ 0.05 with Tier A confirmed ⇒ label "structural residual, not timing skill" (still reportable).
- All results carry the contamination asterisk until the forward re-run.
