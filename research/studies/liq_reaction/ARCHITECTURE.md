# liq_reaction — ARCHITECTURE

Design for the liquidation-reaction study. Read with `PREREGISTRATION.md` (which freezes the A1 primary
estimand + gauntlet). Nothing here is run until this doc is approved and audited (standard flow:
architecture doc → agent-swarm audit → build → code audit → run → framing/steelman → ledger).

## 0. Hypothesis
Forced liquidations close positions with market orders at zero price-sensitivity → a temporary price
**overshoot** that reverts once the forced flow stops (**fade**). The competing hypothesis is that
liquidations mark genuine repricing → **continuation (follow)**. The sign of the forward markout decides
which regime dominates, and whether it is conditional (A3/A5). Mechanically-labelled forced flow is the
cleanest possible test of "forced ≠ informed."

## 1. Data & identification (reason from `research/data/schema.py` — no new ingest)
- **Universe / window:** majors {BTC, ETH, SOL, HYPE}, 2025-08-01 … 2026-06-29 (asset_ctx coverage; fills
  run to 06-30 but right-censor to the last ctx minute).
- **Liquidation fills:** the liquidated wallet's own fills, `is_liq_origin` = `liq_user IS NOT NULL AND
  lower(liq_user)=lower(wallet)`. This is the **forced side** (the position being closed) — the price-taker.
  Counterparty fills are NOT counted (avoids double-counting the forced flow).
- **Forced direction** (the pressure sign): a long being liquidated is force-**sold** (down pressure), a
  short is force-**bought** (up pressure). `forced_dir = −sign(start_position)` (long pos>0 → −1 sell),
  **corroborated** by `side` (`A`=sell should dominate long-liqs) and `dir`. Rows where `start_position`
  sign and `side` disagree are quarantined + counted (DQ diagnostic), not silently kept.
- **Signed forced notional** per fill = `forced_dir · |sz| · px` (exact via `*_d` casts; `notional_usd` for
  the aggregate). Aggregate to **coin × minute** → `L_{c,t}` = net signed liq notional in minute t.
- **`liq_method` split:** partition events by method (book market-order liq vs backstop/HLP-vault) — the
  actual string values are **discovered in EDA** (§6), then frozen. Feeds A6.
- ⚠ **`liq_mark_px` is signal-only, NEVER a price.** It is the counterparty's forced fill price; using it as
  our entry/exit is the edge3 stale-price artifact. All returns use `asset_ctx` (§2).

## 2. The shared markout harness (the reusable core — biggest engineering deliverable)
A single, tested function `flow_markout(events, horizons, price='oracle_px')` that every forced-flow study
reuses. Given a table of **decision events** `(coin, t_decision, signal_sign, weight, covariates…)`:
1. **Entry price** = as-of `asset_ctx` price with `ctx.ts ≥ t_decision` **strictly after** the last fill
   used in the signal (leakage-safe; a fill never sets its own entry). Default `oracle_px`.
2. **Forward markout** at each horizon h: `m_h = signal_sign · (P(entry_ts + h)/P_entry − 1) · 1e4` bp,
   using as-of `oracle_px` at `entry_ts + h`. `signal_sign = +1` encodes the FADE direction (fade markout
   > 0 ⇒ reversion; report follow as the negation).
3. **Right-censor** any event whose `entry_ts + h` exceeds the last ctx minute for that coin.
4. Return per-event markouts + covariates → fed to the gauntlet (§3).
Implemented in `research/lib/` **iff** a second study will reuse it (it will — TWAP/OI/builder), else in the
study. AS-OF joins via DuckDB `ASOF JOIN` over `research.data.db.connect()`. **No parquet-lake bulk load**
into Python — aggregate in SQL, pull only the (small) event table + a per-coin minute price panel.

## 3. Statistical gauntlet (applied to every sub-study; frozen for A1 in PREREGISTRATION)
- **Unit of analysis:** the liquidation **event** (coin-minute with `|L| > 0`, or a cascade for A2). Events
  are autocorrelated (cascades) → inference must cluster.
- **Point estimate + CI:** mean (and StableEdge-style median-of-means over weekly blocks) fade markout;
  CI via **`research.lib.stats.moving_block_bootstrap_ci`** over time per coin (blocks absorb cascade
  autocorrelation) and **`cluster_bootstrap_ci`** clustering by (coin, day).
- **Null models (two):** (a) **sign permutation** — randomize `forced_dir` per event (`sign_flip_pvalue`);
  (b) **matched-baseline** — random non-liq coin-minutes matched on trailing |return| and volume, to prove
  we're not just buying volatility. Observed must beat both.
- **Cross-coin sign test** (`stats.sign_test`): do 4/4 majors lean the same way? The primary power lever
  given only 4 units — significant where no single coin is.
- **Positive control + MDE:** `power.inject_positive_control` injects a known reversion of the care-about
  size into post-event returns; confirm recovery. `power.power_check` reports MDE vs care-about. **If MDE ≫
  care-about → INCONCLUSIVE, and the obligation is to variance-reduce/pool, not relabel** (anti-ratchet).
- **Multiplicity:** horizons/coins/methods are a grid → `stats.bh_fdr` across the reported set; **one
  primary horizon is pre-registered** (PREREG) so the headline isn't an argmax-over-horizons (over-carry).
- **Walk-forward:** any fitted parameter (event threshold, cascade params) is fit on train months and
  evaluated on later months via `cv.walkforward_splits`. The A1 base markout has **no** fitted parameter →
  its OOS check is month-by-month stability + the whole-window estimate with honest CI.
- **Cost / net:** `research.lib.cost` with `half_spread_bp` calibrated from `impact_bid/ask_px` at event
  times; report **gross AND net** (`net = gross − round_trip`). A liq-fade is entry+exit = one round trip.
- **Care-about effect size:** net fade markout that clears round-trip cost (~taker fee + crossed spread,
  order ~a handful of bp) by a deployable margin. Pinned numerically in PREREG.

## 4. Sub-studies
- **A1 — LiqFade (PRIMARY, preregistered).** Continuous `L_{c,t}` → forward fade-markout term structure.
  Also the event form (|L| over a causal rolling quantile). Establishes: does forced flow revert at all,
  which horizon, gross and net, 4/4 sign. No fitted parameters in the primary estimand.
- **A3 — MarkGap dose-response.** Bucket events by `|liq_mark_px − oracle_px|` (cross-checked vs `premium`);
  reversion should rise monotonically with dislocation depth. A conditioner (turns a flat average into a
  dose-response) + a monotonicity/rank test. `liq_mark_px` used as *signal magnitude* only.
- **A5 — RegimeSplit.** Interact A1 with funding sign/level, premium, ΔOI, hour-of-day, impact-spread width.
  Hypothesis: fade concentrates when the crowded/over-funded side is flushed in thin hours. Heavy
  multiplicity → mandatory **prosecute-the-positive** pass (a separate agent argues it's a multiple-
  comparisons artifact) before any regime is carried.
- **A2 — CascadeFade.** Cascade = ≥N same-direction liq events within a rolling W-min window AND cumulative
  `|L|` > per-coin rolling quantile. Fade at cluster end, time-based exit (reversion *duration* is more
  stable than magnitude). Portfolio backtest via `research.lib.backtest`. Run **SOL/ETH/HYPE first; BTC is
  the pre-registered falsification** (external evidence says BTC cascade-fade is weak — if our BTC result
  is strong, suspect a bug/overfit).
- **A6 — BackstopEdge (deployability gate).** Split events by `liq_method`; compare book-liq vs
  backstop-liq forward markout. Tally the HLP "prize" descriptively from `closed_pnl` on liq-origin wallets
  (upper bound on transferred edge). Answers "is it already arbed" — if HLP captures the reversion sub-
  minute, our per-minute residual is ~0 by construction, which is itself a finding.

## 5. Sequencing & deliverables
1. **EDA (descriptive, not a test):** liq base rates per coin/month, `liq_method` value counts,
   forced_dir↔side agreement, event-size distribution, cascade frequency. Freezes the discovered constants.
2. **Build the markout harness** (§2) + tests (leakage, as-of correctness, right-censor).
3. **A1** under the frozen gauntlet → FINDINGS ledger entry (point est + CI + MDE + sign + net).
4. **A3, A5** conditioners; **A2** cascade backtest; **A6** arbed-gate.
5. **Framing/steelman + prosecute-the-positive** passes (separate agents) before any verdict.
Each stage writes to `FINDINGS.md` before the next starts.

## 6. What EDA must settle before A1 is frozen (discovered constants, then pinned in PREREG)
- The exact `liq_method` string values and their meaning (book vs backstop).
- Liq-event base rate per coin (drives MDE / whether per-coin cells are viable or pooling is mandatory).
- The forced_dir rule validated (`start_position` sign vs `side` vs `dir` agreement rate; quarantine rule).
- The causal rolling-quantile lookback for the event definition.

## 7. Risks & known traps (guard each)
- **Stale-price / look-ahead** — entry strictly after the last signal fill; never `liq_mark_px`. (edge3.)
- **Continuation swamping reversal** — informed liqs → follow; split by size/regime (A3/A5), report the
  term structure, don't average opposites into a false null.
- **Autocorrelation-inflated N** — cascades are dependent; moving-block/cluster bootstrap, not naive t.
- **Thin per-coin samples on 4 majors** — pooling + 4-coin sign test; a per-coin null is INCONCLUSIVE
  unless MDE ≤ care-about.
- **Cost eating a small residual** — net is decisive; `impact` spread is a proxy, so report the cost
  sensitivity band, not a single netted point.
- **Multiplicity / over-carry** — one pre-registered primary horizon; FDR on the rest; prosecute-the-
  positive pass on A5.
- **HLP already-arbed** — A6 bounds how much residual is even left at our resolution.
- **Firewall** — exploratory lane only; never feeds `gate_a/`; nothing imported into `src/babylon/`.
