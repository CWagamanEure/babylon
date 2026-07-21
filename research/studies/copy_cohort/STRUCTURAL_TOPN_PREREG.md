# STRUCTURAL TOP-N COPY BOOK — frozen forward specification (v1.0, 2026-07-21)

**Status: FROZEN.** Burned-fold work on this line concludes with this document. The knives
(`structural_knives_report.json`) were the final descriptive looks; from here, only forward data
(paper trader / new months) may be read against the predictions below. Any spec change requires a
new version stamp and restarts the forward clock.

## Lineage (all burned-fold, hypothesis-grade)

Metric-sweep atlas (2026-07-21): PnL-level features anti-predictive at pool scale; structural
features monotone (maxDD 8/8 folds, trades/day 8/8, turnover 7/8, clip size 7/8). Dragger anatomy
(2026-07-21): cohort shorts anti-predictive (field-adj −55.6, CI excl 0); long-only overlay
registered. Knives: all four features load-bearing (LOFO degrades every variant); N=30 optimal
(N50 acceptable, 8/8 fold-positive at lower point); eligibility gates help (+6bp we vs ungated);
long-only stacks (+41.5 we vs +26.6 both-sides); ex-202512 sensitivity does not flip anything.

## Frozen specification

**Universe & data.** Majors = {BTC, ETH, SOL, HYPE}, local node_fills tape + asset_ctx marks.
Monthly roll: at the first instant of month T, formation = the 3 calendar months strictly before T
(ts-based boundaries; data through T−1 only).

**Eligibility gates (formation):** n_active_days ≥ 15 (day_notional > 0 days, Net-Child-Vaults
excluded); capday metric > 0 (incerto `capday_stats` definition: net-of-fee day PnL × min(1,
100k/day_notional), ÷ active days); fills per active day < 1,000.

**Score (frozen, unweighted):** mean of within-month percentile ranks over eligible wallets of:
1. − max drawdown of cumulative daily net PnL (smaller DD → higher rank)
2. + fills per active day
3. + turnover (Σ notional / active day)
4. + median flat-open entry notional (oid-grouped entries, first-fill flat/taker/unflagged rule)

**Cohort:** top-N by score, N = 30 (PRIMARY), wallet-asc tie-break. N = 50 tracked as SECONDARY.

**Book (per the ledger's accumulated entry/exit rules):**
- Copy only **`Open Long`** flat-open taker entries (long-only overlay — PRIMARY; both-sides
  tracked as SECONDARY to isolate the overlay), entry notional ≥ $250, unflagged, oid-grouped.
- Equal-$ clips (never notional-proportional); single-wallet cap 10% of month's entries (excess
  entries of that wallet skipped chronologically).
- Exit at fixed **8h**; net cost 2.6bp RT (5.5bp stress line reported).

## A-priori predictions (registered before any forward data)

P1. PRIMARY (long-only N30): forward net > 0; expected ≈ +15–30bp/trade (burned point +29.0,
    haircut for selection-on-selection).
P2. Overlay: long-only ≥ both-sides on wallet-equal markout (burned gap ≈ +15bp).
P3. Structural ≥ capday-PnL selection: PRIMARY outperforms the capday top-30 book on the same
    months (burned gap large; any forward gap > 0 satisfies).
P4. Surface: ≥ 80 followable entries/month at N=30 (burned ≈ 96/mo¹; below 50/mo = surface regime
    change, flag).
¹ 770 long-only entries / 8 months.

## Evaluation protocol

- Forward paper accumulation ≥ 6 months before any verdict; wallet-cluster + day-block CIs (wider
  quoted); care-about +5bp net; MDE reported each read.
- Verdict vocabulary per the over-null/over-carry gates; failures of P1–P4 reported as-is.
- Standing arms for comparison: majors-native K30 @8h, capday top-30, vault-deposit ranking.

## Known risks (stated at freeze)

Selection-on-selection (score assembled from an atlas on the same folds — the primary honesty
caveat; forward data is the only cure). Fold 202512 negative in most variants (regime sensitivity).
Structural features may proxy market-maker-adjacent profiles whose edge decays; the bot gate
(<1000 fills/day) is the only guard. HYPE listing-era drift made HYPE-shorts the worst cell; the
long-only rule removes the worst expression but HYPE regime change remains a risk.
