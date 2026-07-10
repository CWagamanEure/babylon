# Architecture — Cross-Sectional Residual Stat-Arb on Hyperliquid Perps

**Status:** design v1.0, audited. **`AUDIT_RESPONSE.md` (4-agent swarm) is BINDING — read it with this doc;
on any conflict it wins.** Next step: build Stage 1 with the AUDIT_RESPONSE blockers (A1–A12) baked in.
**Lane:** `research/` analysis workbench — FIREWALLED. Never imported into `src/babylon/`, never feeds
`markout_study/gate_a/`. Read-only over the data lake (`asset_ctx`, `fills`).

---

## 1. Objective & hypothesis

**Hypothesis.** After removing broad market exposure (BTC, ETH) and shared sector comovement, a coin's
*idiosyncratic* residual return partially **mean-reverts** at horizons of hours-to-a-day. A market-neutral
book that fades the cross-sectional extremes — long the unusually-weak, short the unusually-strong — earns a
positive risk-adjusted return **net of realistic cost and funding**, *provided* the dislocation is mechanical
(liquidity/liquidation/flow) rather than informational.

**Why this regime, when the 2-asset minute-scale version was sub-cost** (see `../liq_fuel_map/FINDINGS.md`):
the residual reversion is *real but small per name* (~2–5 bp on majors at 30–120 min, t≈−13, OOS-stable).
Three levers change the economics here: (a) **horizon amortizes the ~fixed round-trip cost** over a bigger
move; (b) **breadth** diversifies idiosyncratic risk so Sharpe scales; (c) **alts dislocate harder** (bigger
gross residuals — offset by bigger cost; that tension is the test). Sector-neutralization does not *create*
edge; it **cleans** the signal (stops us fading a coin that is merely riding a sector repricing — an
informational move that will not revert).

**Estimand (primary).** OOS net Sharpe (after endogenous cost + funding + slippage) of the factor-neutral
cross-sectional reversal portfolio at the pre-registered horizon. **Secondary:** residual-reversal IC by
horizon; incremental IC from the wallet-flow conditioner (majors, Stage 6).

**Success bar (pre-registered).** Net-of-everything OOS Sharpe materially > 0 with (i) both long and short
legs contributing, (ii) positive net IC at the primary horizon, (iii) robustness across vol/trend regimes,
(iv) non-trivial capacity under the %-of-volume cap. A *powered negative* (tight CI on Sharpe near/below 0
with MDE ≤ the Sharpe we'd deploy on) is a real, publishable result — not a failure to be re-looped.

---

## 2. Data sources

- **`asset_ctx`** (per-minute, **230 coins**, 2025-08 … 2026-06): `oracle_px`, `mark_px`, `mid_px`,
  `funding`, `open_interest`, `premium`, `day_ntl_vlm`, `impact_bid_px`, `impact_ask_px`. Supplies returns,
  the factor model, the composite-signal inputs, AND the endogenous cost proxy. **177 coins** have both
  >200k minutes of coverage and a populated impact spread (median full impact spread ≈ **15 bp**).
- **`fills`** (per-wallet, **MAJORS ONLY — BTC/ETH/SOL/HYPE**): powers the Stage-6 wallet-flow conditioner
  *on majors only*. Extending the wallet veto to the alt cross-section requires a node_fills backfill for
  alts — an explicit downstream decision gated on Stage 6 results, NOT assumed here.

Price basis: use **`mid_px`** for tradable returns/execution and the impact spread for cost;
`oracle_px`/`mark_px`/`premium` feed signal terms (perp-premium dislocation). Reconcile mid vs oracle
carefully (book-overshoot vs composite).

---

## 3. Universe construction — point-in-time, no survivorship

At each rebalance `t`, membership is recomputed from **trailing** data only:
- Liquidity floor: rolling median `day_ntl_vlm` above a threshold AND rolling median impact spread below a
  cap → keep ~**50–70** names.
- **Causal:** a coin is eligible at `t` iff it had sufficient trailing history/liquidity *as of `t`*. Coins
  list and delist across the 11 months — membership is time-varying. **No look-ahead** (never select on
  full-sample liquidity), **no survivorship** (a coin that dies mid-sample contributes returns up to its
  last valid bar, then exits; no forward-fill of dead prices, no silent drop of losers).
- Always exclude BTC/ETH from the tradable set (they are factors, not positions).

---

## 4. Factor model → residuals

For each coin, rolling (causal) exposure estimate over a trailing window (e.g., 30–60d, EWMA-weighted):
```
r_i,t = β_BTC·r_BTC,t + β_ETH·r_ETH,t + Σ_k β_(sector k)·F_k,t + ε_i,t
```
- Betas from trailing data only; apply shrinkage (betas are noisy and the residual is sensitive to beta
  error). Consider ridge / Bayesian shrinkage toward a prior beta.
- **Sector factors `F_k` are statistical, not hand-labeled** (per decision): PCA (or hierarchical
  clustering) on the **residual-after-BTC/ETH** return correlation matrix over a rolling window → top-K
  principal components / cluster-mean residual returns as the sector factors. **Leave-one-out**: coin `i`'s
  sector factor excludes `i` (else a big coin is mechanically correlated with its own sector). Recompute
  monthly; require persistence before changing structure (consensus across windows). Hand-labels
  (CoinGecko/DefiLlama) retained only as an *interpretability cross-check*, never as the definition.
- `ε_i,t` = the coin-specific move after removing market + sector = the object we fade.

---

## 5. Signal

- Base: cross-sectional standardized residual over lookback `L`: `z_i = rank/winsorized(ε_i over [t−L,t])`.
  **Rank/winsorized, not raw Pearson** — prior studies were repeatedly misled by outlier-driven Pearson vs
  robust-decile disagreement. `S_i = −z_i` (fade).
- Composite (Stage 5, additive, each term OOS-justified before inclusion):
  `S_i = −z(residual) − z(short-term order-flow imbalance) − z(perp-premium dislocation) − z(funding vs
  predicted) + reversal-quality filters (peer non-confirmation, flow-shock concentration)`.
- **Reversal-quality = the transient-vs-permanent classifier**, generalized from `../liq_fuel_map/` (where
  BTC-alignment separated overshoot from repricing at ~+20 bp OOS). Do NOT fade when: peers confirmed the
  move, OI is persistently expanding, funding/basis signal structural repositioning, or (majors, Stage 6)
  informed wallets are on the move.

---

## 6. Horizon ladder — sweep all, adjudicate honestly

Build the full **lookback `L` × holding `H`** grid (e.g., L ∈ {4h, 12h, 1d, 3d} × H ∈ {4h, 12h, 1d}).
- **Discipline (resolves "try all"):** report the *entire* surface; **select the primary cell on TRAIN /
  by the a-priori cost-vs-power criterion, then CONFIRM on the held-out TEST** — never pick the test-set
  argmax. Also run a *joint* read (does the whole surface lean the right way) to distinguish a real,
  horizon-robust effect from a single lucky cell.
- **A-priori primary ≈ 12–24h hold** (power/cost sweet spot below). Headline result reported on that cell;
  the surface is supporting evidence.

**Power caveat (drives horizon choice).** 11 months bounds independent periods: ~1,300 at 4–6h, ~330–670 at
12–24h, only ~65–110 at 3–5d (OOS ≈ ⅓ of each). Multi-day fully amortizes cost but the Sharpe CI is too wide
to trust → would fail the MDE gate. Hence primary in the **hours-to-a-day** band, not multi-day.

---

## 7. Portfolio construction (the real driver)

Long **top**-quantile `S`, short **bottom**-quantile `S` (recall `S=−z`, so top-`S` = the unusually-*weak*
coins we fade long; bottom-`S` = the unusually-*strong* we fade short — worked ex.: a coin that ran up
idiosyncratically has large +z ⇒ large −S ⇒ bottom quantile ⇒ **short**). [AUDIT A2]. Weights solved s.t.:
- Net dollar exposure = 0; **BTC-beta = 0, ETH-beta = 0, each sector-factor exposure ≈ 0**.
- Inverse-(predicted-vol) × liquidity scaling; **max weight per coin**; **max fraction of coin's ADV**
  (capacity + cost realism); portfolio **vol target**; **turnover penalty**.
- MVP approximates the optimizer with a neutralized ranking (residualize the raw weight vector against the
  factor-exposure matrix) before introducing a full constrained optimizer.
- **Explicitly audit the "secret exposures"**: a naive book silently becomes long-high-beta-alts /
  short-low-beta-majors / short-momentum / long-illiquidity / long-funding-carry. Report realized factor,
  momentum, size, illiquidity, and funding exposures — neutrality must be *verified*, not assumed.

---

## 8. Cost & funding — endogenous, first-class

- **Cost** per coin per rebalance from the impact spread (half-spread × 2 taker + fees). The impact spread
  is quoted at HL's impact notional — for size beyond that, cost is higher; the ADV cap keeps us near it.
  Model HL's **actual fee tier** (volume-dependent), not a flat constant.
- **Funding** accrued over the hold (HL funding hourly, on mark). For a neutral book funding partly nets but
  net funding exposure is tracked and charged; longer holds accrue more.
- **Turnover** is the cost multiplier → rebalance only on *material* rank change; report turnover-adjusted
  edge. First reported metric is **gross edge vs 2–3× spread**, before any Sharpe.

---

## 9. The gate test (cheapest, decisive, FIRST)

BTC/ETH-only residual reversal (no sectors, no composite, no wallet), primary horizon, quantile long/short,
beta-neutral, inverse-vol, endogenous cost, OOS. This is the **floor** — sectors + composite + wallet
*refine* it. If the floor is strongly net-negative, that is a cheap, powered read; if marginal-or-positive,
build out Stages 5–6. Report point estimate + CI + MDE + cross-horizon sign consistency (the four-part gate).

---

## 10. Wallet leg (Stage 6, parallel, MAJORS ONLY)

The differentiator — but data-gated and with a **discouraging prior** (copy-trade + OOS-persistence studies
found generic wallet-selection alpha unsupported OOS; see memory). Test the hypothesis *cheaply on majors
before* funding any alt backfill:
> Does signed flow from a pre-ranked *informed-wallet cohort* predict **factor-neutral forward returns**
> (5–30m, 30m–2h) **beyond aggregate signed market flow**, on SOL/HYPE?
- Target **delayed** post-trade returns (drop the first bar) to avoid mechanical price-impact contamination.
- Cohort-level flow first (informed / short-horizon / momentum / liquidation-TWAP / noise); regularized
  individual-wallet and hierarchical (global+sector+coin, shrunk) models only if the cohort test clears.
- Controls: total signed flow/imbalance, spread/depth, vol, recent market return, BTC/ETH/sector returns,
  OI/funding change, liquidations, coin+time fixed effects, wallet trade size as fraction of bucket volume.
  The wallet coefficient must show **incremental** value beyond aggregate imbalance.
- **Decision gate:** incremental IC OOS → justify alt fills backfill to extend the veto cross-sectionally.
  Null → the strategy stands (or falls) on the conventional legs alone.

---

## 11. Evaluation battery

Net return after fees/slippage/funding; IC by horizon; **long and short legs separately**; turnover-adjusted
edge; performance by vol and trend regime; PnL concentration by coin/day/event (no single-name or single-week
dependence); **beta drift during crashes** (correlations → 1, neutrality breaks — test explicitly); signal
decay after entry. Inference on **non-overlapping** periods (or Newey-West / block bootstrap) — overlapping
holds inflate t-stats.

---

## 12. Risks & controls

| Risk | Control |
|---|---|
| Winner's curse / huge DOF (L×H × sector × cohort × thresholds) | Pre-register primary; hold out last 3mo before looking; report full surface; train-selects/test-confirms |
| Survivorship / look-ahead in universe | Point-in-time membership from trailing liquidity; delisted coins exit cleanly |
| Beta/factor instability | Rolling + shrunk betas; verify realized neutrality; report factor exposures |
| Cost under-modeled (alt spreads, size) | Endogenous impact spread + ADV cap + real fee tier; gross-vs-2–3×-spread as first metric |
| Overlapping-return t-stat inflation | Non-overlapping periods / block bootstrap |
| Crash beta-drift | Explicit stressed-regime split; measure neutrality breakdown |
| Wallet-alpha prior is negative | Cheap majors test before any backfill; incremental-over-aggregate bar |
| Outlier-driven signal (Pearson trap) | Rank/winsorized cross-sectional scores |

---

## 13. Build stages (milestones)

1. Point-in-time universe + data/return/cost layer.
2. Rolling BTC/ETH factor model → residuals.
3. Signal decay / IC surface across L×H → pre-register primary.
4. **Gate test** (§9) → decision point.
5. Statistical sector factors + full neutralized portfolio + composite signal.
6. Wallet leg (majors, §10) → backfill decision.
7. Full backtest + evaluation battery (§11).

## 14. Open questions for the swarm audit
- Impact-spread → true cost mapping at our position sizes (is 15 bp optimistic/pessimistic?).
- PCA vs hierarchical-cluster sector factors — which is more stable OOS on this universe?
- Rebalance-trigger rule (material rank change) tuning without leaking the OOS.
- Is 11 months enough for the primary horizon's Sharpe MDE? (pre-compute the MDE before trusting a null).
