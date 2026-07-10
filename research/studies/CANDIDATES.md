# Strategy candidates — the menu (2026-07-07)

Ranked, de-duplicated output of a 5-agent research swarm (liquidation, TWAP/mechanical, funding, order-flow,
web deep-research). This is the hypothesis backlog `research/studies/<name>/` draws from. Weighted toward
**forced flow** (liquidations, TWAP) per the standing steer: forced flow is *price-insensitive and
mechanically labelled in our tape*, so overshoot→reversion is the cleanest edge story.

**Data-sufficiency legend:** FULL (testable now on majors + asset_ctx) · PARTIAL (testable with a caveat) ·
NO (needs data we don't have — a scope-expansion trigger).

**Cross-cutting guards (bake into every study — from the swarm + this repo's scars):**
- **Never price entries off `liq_mark_px` or a liquidation fill's `px`** — that's the counterparty's forced
  fill; using it as our price is the stale-price artifact that killed edge3. Entry AND exit come from
  **post-event as-of `asset_ctx`** (`oracle_px`/`mark_px`, `ctx.ts ≤ t`). `liq_mark_px` is a *signal*
  (dislocation depth), never a tradable price.
- **Per-minute price is the floor** → horizons are minutes-to-hours; the sub-60s snapback (which HLP likely
  already harvests) is invisible. We measure the *slower executable residual*.
- **Only 4 majors** → cross-sectional breadth is structurally underpowered; the power lever is the
  **4-coin sign test** + pooling across time, and **block/moving-block bootstrap** nulls (overlapping
  forward windows inflate naive t-stats).
- **Gross vs net**: cost from `research.lib.cost` calibrated on `impact_bid/ask_px`; a net verdict needs it.
- **Over-null gate**: every null reports point estimate + CI + positive-control MDE + 4-coin sign test.
- **`is_zhash` is a SUPERSET** (~18% of fills — TWAP *and* liquidations/ADL/system); strip `is_liq_origin`
  and segment before calling it "TWAP." There is **no `twapId`** — TWAPs are *reconstructed*, not read.

---

## Tier 1 — forced flow, FULL-testable, on-brief (start here)

### A. Liquidation reaction  ⭐ recommended first study
Forced deleveraging = full-size market orders (partial-liq: 20% tranche + 30s cooldown → multi-minute
staggered flow, matches our price resolution). Direction (fade vs follow) is a genuine open question our
tape is built to answer. HLP backstop takes sub-2/3-MM positions at mark (its vault address is public → its
majors fills are in our tape).
- **A1 LiqFade** — post-liquidation short-horizon reversal. Signed liq notional per coin-minute → markout at
  +1/2/5/10/15m against the flow. *The atom.* **FULL.**
- **A2 CascadeFade** — detect same-direction liq clusters (≥N events / W-min, notional > rolling quantile),
  fade at cluster end, time-based exit. External walk-forward evidence: works SOL/ETH (PF~2.5–2.9), **fails
  BTC** → built-in falsification. Highest standalone upside. **PARTIAL** (volume proxy).
- **A3 MarkGap dose-response** — bucket events by `|liq_mark_px − oracle_px|`; reversion should rise
  monotonically with dislocation. A *conditioner* that turns a flat average into a dose-response. **FULL.**
- **A4 LiqImbalance** — net signed liq flow (shorts-liq'd buys − longs-liq'd sells) as a contrarian
  directional signal, 5–60m. Distinct estimand (direction, not just fade). **FULL.**
- **A5 RegimeSplit** — condition A1 on funding/premium sign, OI change, hour-of-day, impact-spread width
  (reversal concentrates when the crowded/over-funded side is flushed in thin hours). **FULL** (multiplicity
  hazard → prosecute-the-positive pass).
- **A6 BackstopEdge** — is it already arbed? Compare book-liq vs backstop-liq forward markout; tally the HLP
  "prize" from `closed_pnl` on liq-origin wallets. The deployability gate. **PARTIAL** (no labelled vault).

### B. Mechanical / TWAP flow
- **B1 zhash net-flow imbalance** — rolling signed `is_zhash` notional imbalance (strip liqs) → forward
  return at 5/15/30/60m. Dodges TWAP segmentation entirely; highest power, no look-ahead. **FULL.**
- **B2 Ride-the-TWAP** — reconstruct a live TWAP (≥K same-wallet/coin/side zhash fills at ~30s cadence),
  ride the drift to estimated completion. **PARTIAL** (no `twapId` → episode-merge risk).
- **B3 Fade-completion** — enter opposite at detected completion. **PARTIAL** — *completion detector is a
  look-ahead hazard*; must declare completion causally ("no slice for N×30s"), reversion starts after.
- **B4 Informed-vs-mechanical discriminator** — classify a live TWAP as transient (fade) vs informed
  (continuation) from pre-completion features. Rescues B3. **PARTIAL** (leakage surface + wallet-history
  feature = the known tight-null trap).

### C. Order flow / microstructure
- **C1 OI-build direction** — signed *opening* flow (`start_position`+`dir`) × price sign → 4-quadrant
  forward return; **self-validating against true `open_interest`**. Best power/horizon profile (lives at
  hours, where the price floor + cost aren't fatal). **FULL.**
- **C2 Whale-print event study** — top-p99 taker prints (aggregate same `oid`/`cloid`/block) → continuation;
  exploits our exact-per-fill granularity. **FULL.**
- **C3 Taker OFI continuation** — signed taker-flow imbalance → next-interval return. Documented as
  *momentum, tiny (~0.4bp@30s), fast-decaying* → the honest test of whether ANY flow residual survives our
  minute floor + cost. **FULL** (flow); **PARTIAL** (horizon).
- **C4 Builder-routed toxicity** — rank builders by their taker flow's forward markout (fade toxic / follow
  informed). Publicly under-explored, fully on our tape, complements the wallet lane. **FULL** (multiplicity
  → FDR + OOS).

### D. Funding / carry / basis
- **D1 Premium→funding lag** ⭐ — HL charges funding = clamped TWAP of `premium`; so current premium predicts
  next-hour funding *by construction*. Near-guaranteed signal, lowest DOF, and a **data-integrity check** on
  funding/timestamp alignment. **FULL.** (Edge likely competed to ~0 net, but ideal validation warm-up.)
- **D2 Fade extreme funding** — funding z-score extreme → reversion + carry aligned. **FULL.**
- **D3 Carry-farm persistent funding** — receive the "farmable middle" band; run *with* D2 to find the
  reversion/carry break-even. **FULL.**
- **D4 OI-gate on D2** — take D2 only when OI is *building* (fresh crowd) not capitulating. Cheap ablation. **FULL.**
- **D5 Cross-sectional funding carry** — long/short the 4 majors on funding rank. **PARTIAL** — N=4 is
  structurally underpowered; recast as pooled pairwise (anti-ratchet) or declare data-limited. HYPE dominates.

---

## Tier 2 — structural, PARTIAL (strong follow-ons)
- **HLP backstop-inventory fade** — reconstruct HLP's majors inventory from its public vault fills; extreme
  skew → reversion. **PARTIAL** (majors-only view of a 100+-coin book; dissent says HLP is defended, not
  exploitable). ~41% of HLP lifetime PnL came from 2 days (Oct-10-25, Jan-31-26).
- **Copy-trade / vault crowding fade** — fade the crowded/"rekt" cohort; redemption unwind = 20% tranches.
  **PARTIAL** (vault membership/deposits off-tape). Note the repo's prior sealed FAIL on generic
  wallet-selection alpha — frame as fade/selection, not follow.
- **Premium/mark dislocation → liq-trigger anticipation** — **PARTIAL/LOW**; median-of-three mark defeats the
  naive basis trade on majors; per-minute too coarse for the 150s-EMA mechanics. Use as a feature for A.

---

## NOT testable on our data (record so we don't re-open — these are scope-expansion triggers)
- **Cross-venue lead-lag (Binance leads HL, HL lags ~−800ms; arXiv 2506.08718, Hayashi–Yoshida — directional
  not exact per the @ltrd_ coarse-grid critique)** — a real, documented edge, but **NO** on our data: needs
  CEX tick data + sub-second oracle. Our `oracle_px` IS a Binance-weighted CEX median but stored per-minute →
  minute-scale only. *The single highest-value data acquisition.*
- **Listings / delistings / new-perp (hyperp funding-fade, 1h-TWAP delist convergence) & airdrop-unwind** —
  **NO**: all live in alts/spot; majors-only tape, no in-window major listing/delisting.
- **MEV / on-chain ordering** — HyperCore perp MEV deliberately suppressed; real MEV is on HyperEVM AMMs →
  needs EVM mempool/DEX data. **NO.**

---

## Recommended sequencing
1. **Study 1 = Liquidation reaction (A).** Most on-brief, uses our most unique fields (full liq struct),
   cleanest forced=uninformed→overshoot→revert mechanics, strong over-null structure (thin per-coin →
   4-coin sign test + pooling), built-in falsification (BTC), and a dose-response conditioner (A3). Build
   A1 (atom) → A3/A5 (conditioners) → A2 (cascade, SOL/ETH/HYPE first) → A6 (already-arbed gate).
   **Building it creates the reusable `flow-subset → signed forward-markout + full gauntlet` harness** that
   B/C/D re-parameterize.
2. **D1** in parallel as a cheap funding/timestamp-alignment validation.
3. Then **B1** (mechanical-flow imbalance) and **C1** (OI-build) reuse the harness.
4. **C4** (builder toxicity) as an orthogonal track with its own multiplicity budget.

*Corrections folded in from the web pass: lead-lag "700–800ms" is coarse-grid/directional, not precise;
vault leader profit share is documented at 10%, not 20%.*
