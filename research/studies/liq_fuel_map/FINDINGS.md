# Findings ledger — liq_fuel_map (estimate the hidden liquidation-fuel state)

**Premise.** The price layer is arbed (see `../basis/FINDINGS.md`). Our edge is a *state* only we can see:
`start_position` on every fill lets us rebuild every wallet's running position on majors → estimate where
forced-liquidation flow will trigger (the "fuel map"). Others can't draw this; it's not published. The
non-arbed majors dynamics (cascades, overshoot-revert) are functions of this state.

## Feasibility validation (2026-07-07, SOL, 2025-08)

| # | Question | Method | Result | Verdict |
| --- | --- | --- | --- | --- |
| 1 | Can we reconstruct positions exactly? | `signed_sz = +sz if side='B' else −sz`; roll `start_position` per wallet; check `end_pos(fill_n) == start_position(fill_{n+1})` | **100.0% chain** (592,653 pairs, 2025-08-01) once ordered by **`(ts, event_index)`**; whole-month median abs error = 0. Wrong key `(ts, tid)` gave only 53% — **event_index is the intra-block execution order, not tid.** | **CONFIRMED** — running positions rebuildable to the unit. |
| 2 | Is the "fuel" real and clustered? | aggregate `is_liq_origin` fills | SOL Aug'25: **42,027 liqs, $451M** notional, **0.6% of volume**; med liq $1,563 / p99 $131k (retail-heavy, fat tail); **top 3 days = 43%** of monthly liq notional. | **CONFIRMED** — fuel is material and discharges in bursts (cascade premise holds). |

## Reconstruction contract (pin for the engine)
- Signed size from `side` (`B`=+, `A`=−); order strictly by **`(ts, event_index)`** within `(wallet, coin)`.
- `start_position_d` is the exact pre-fill position; `end_pos = start_position_d + signed_sz` = the next
  fill's `start_position_d` (verified). `notional_usd` = |sz|·px.
- Ground truth for calibration = `is_liq_origin` fills (`liq_user == wallet`); `liq_mark_px_d` = mark at the
  liquidation (a SIGNAL of trigger price — **never** a tradable entry price, per the edge3 scar).

## Not yet done → the engine (next build, architecture-doc-first)
1. **Entry VWAP per position episode** (reset on flat/flip) → each open position's cost basis.
2. **Liq-price BAND** per position from HL's tiered maintenance-margin schedule (leverage & margin-mode are
   unobserved → a band, not a point; cross-margin accounts liquidate off their whole book and we see
   majors-only → partial observation. Name both caveats.)
3. **Fuel curve** `L(price, t)` = notional triggering per price level, above/below spot, over time.
4. **Calibration** — does the estimated fuel map predict *where/when* `is_liq_origin` liqs actually fired?
   (self-validating in the same tape.)
5. **Conditional trade** — does proximity-to / depletion-of a cluster predict move acceleration then
   overshoot-revert; does fuel asymmetry predict directional drift — OOS, net of (stressed) cost.

## Upper-bound gate (2026-07-07) — the audit's decisive pre-build test → NEGATIVE, engine not built

Realized top-decile liquidation cascades (all 4 majors, 11 months, 62,878 cascade-minutes; `upper_bound.py`).
**Perfect cascade timing** (entry at `oracle(t)` of the cascade minute) → a hard upper bound on the whole
program. Signal `d = sign(forced-buy − forced-sell)`; revert `= −d·fwd_ret` (>0 ⇒ fade/overshoot-revert
works); pre-drift `= d·trailing_ret` (>0 ⇒ magnet, price drawn in). Cost = contemporaneous impact spread + 2×
taker (~10–13 bp). `liq_mark_px` never used.

| coin | n_top | pre-drift 5m | revert 1m | revert 5m | revert 15m | cost |
|---|---|---|---|---|---|---|
| BTC | 2078 | **+34.6** | −18.6 | −16.6 | −14.7 | 9.7 |
| ETH | 1438 | **+53.7** | −30.4 | −27.4 | −27.1 | 10.5 |
| SOL | 1458 | **+61.9** | −32.5 | −29.4 | −26.5 | 11.5 |
| HYPE| 1292 | **+64.9** | −35.1 | −26.3 | −11.8 | 13.2 |

**Verdict — EARNED POWERED NEGATIVE on the fade / overshoot-revert thesis (the study's Stage-2 S2 leg, the
~12%-prior leg).** All four over-null conditions met: (1) point estimate = **−15 to −35 bp**, wrong sign for a
fade, CI nowhere near the positive care-about; (2) n≈1300–2100 top-decile cascades/coin → MDE a few bp ≪ the
effect; (3) **4/4 coins agree** (unanimous continuation at every horizon 1/5/15m); (4) this is the UPPER
bound (perfect timing, generous entry) — the negative survives the construction most favorable to an edge.
Cascades **continue, they do not revert**, at 1–30 min on majors.

**Revealed structure = magnet + momentum, not reversion — but the momentum is SUB-MINUTE.** Price drifts
**+35 to +65 bp INTO** the cascade in the prior 5 min (magnet, hindsight-conditioned) and continues through
the cascade minute. Follow-momentum tested directly (entry-lag split): the entire continuation is the
**single cascade minute** (`leg_t→t+1` = **+18 to +35 bp**); once you can realistically observe-and-enter at
`t+1`, there is **nothing left** — `follow_{t+1→t+5}` and `{t+1→t+15}` are **negative** (−2 to −23 bp),
**net −14 to −37 bp** after cost. The only positive point estimate is a **1-minute scalp** (enter at the
cascade-minute *close*, exit `t+1`: +8 to +22 bp net) — but it (a) lives entirely inside one minute →
needs intra-minute detection + minute-boundary execution, and (b) our per-minute `impact` spread proxy
**understates** the true cost of a market order into a cascade (audit feasibility/economic F-notes), so that
net is optimistic. That is the **sub-minute HLP/fast-arb domain** — visible to us, not reachable or
cost-measurable at per-minute resolution. Same wall as `../basis/` (edge lives faster than our data). Fade,
realistic-follow, and anticipation all resolve unfavorably; the 1-min burst is the fast-money game.

**Decision: DO NOT build the M1–M4 fuel-map engine.** Its Stage-2 was fade (S2, now wrong-sign) + directional
pressure (S1, whose realized sign = follow = the crowded/front-run trade). Both legs resolve unfavorably at
per-minute resolution. Consistent with the basis study: majors are efficient/crowded at the resolution we can
trade; the forced-flow reaction lives sub-minute (HLP harvest) or is already priced by the public on-chain map.

## PIVOT (2026-07-08) — the reversion is a GENERIC HYPE-vs-BTC overshoot, NOT liquidation-driven

Chasing the one non-arbed venue (HYPE is HL-native → no external anchor → real, unarbed cascade moves,
~100–150 bp), we built a transient-vs-permanent classifier for HYPE cascade dislocations and then ran the
decisive **placebo/confound control**: is the reversion *caused* by liquidations, or generic?

**Discriminator that works (OOS-robust in relative terms).** Split big HYPE cascades by whether **BTC moved
the same way** in the prior 15 min:
- **market-aligned** (BTC also down) → HYPE overshot the systematic move → **reverts** (+11.5 bp @2h in-samp;
  train +17.7 / test −6.7 — absolute level non-stationary but the *ranking* holds).
- **idiosyncratic** (BTC flat) → HYPE-specific info → **permanent** (−9.6); **HYPE-alone vs BTC** → −27.7.
- The transient/permanent *separation* (~+19–26 bp market-aligned − idiosyncratic) **holds OOS in both
  train and test**; the *absolute* recovery is trend-exposed (test window was a HYPE downtrend) → the
  tradeable form must be **beta-hedged** (HYPE-vs-BTC), not outright-long-the-dip.

**Confound control → the liquidation framing DISSOLVES.** Hold the overshoot size (HYPE − BTC, 15 min) fixed
and vary liquidation notional. Among **market-aligned HYPE overshoots with ZERO liquidations** (n=28,041):
mean bounce **+12.6 bp @2h, stable ~+10–15 bp across every overshoot-size bucket** (n=3k–9k/bucket). Big
cascades coincide with bigger overshoots (−109 vs −61 bp) and revert a bit more (+22 vs +13) but that is
mostly the bigger move; **at fixed overshoot size the liq-heavy marginal effect is noisy/small-N and one
bucket goes negative (+18.8/+36.7/−12.2/+38.6 vs a rock-steady +9.5/+15.0/+12.6/+14.9 no-liq baseline).**

**Verdict.** The robust, large-sample, tradeable effect is a **generic single-name-overshoots-index
mean-reversion: HYPE falls hard vs BTC → snaps back**, present with *zero* liquidations. Needs only two
prices (HYPE, BTC) — **no position reconstruction, no fuel map, no liq levels.** Liquidations are a *symptom*
(marker of the largest overshoots), not the cause; their marginal contribution is **inconclusive** (small-N,
mixed sign — not a powered null, not a usable positive). **The liq_fuel_map machinery is NOT the source of
this edge.** Study redirects to: HYPE↔BTC overshoot-reversion, **beta-hedged**, validated **OOS net of cost**
(pooled numbers above are gross + trend-exposed). Liq notional retained only as a candidate secondary feature.

## RESOLUTION (2026-07-08) — beta-hedged OOS backtest + mandatory steelman → EARNED NEGATIVE (tradeable), with a framing correction

Built the honest test: overshoot = `h15 − β·b15` (β=1.36 OLS train), fade extremes (train p2/p98 ≈ ±100bp),
beta-hedged fwd = `hf − β·bf`, non-overlapping trades, train<202604 / test≥202604, net of cost
(13bp taker unhedged / 23bp hedged). **Every OOS net cell negative** (30/60/120m: −21/−23/−28 bp);
hedged OOS *gross* ≈0; the lone in-sample positive (60m train Sharpe 2.4) dies OOS (test 0.1).

**Mandatory "steelman the positive" pass (separate general-purpose agent) — verdict:**
- **CORRECTION to my framing: it is NOT "mostly beta."** Regressing the *market-neutral* fwd return on the
  overshoot gives a negative, highly significant, train→test-stable slope at every horizon (t ≈ −10 to −16);
  controlling for BTC's *forward* return makes it **stronger** (−0.05 vs −0.02). So there IS a real,
  replicable, **HYPE-specific idiosyncratic mean-reversion**. I under-credited it — logged against the
  over-null bias. **The killer is size, not existence: ~2–5 bp reverted at the ±100bp extremes.**
- **Tradeable negative HOLDS (all four gate conditions met).** Gross ceiling ~3–13 bp everywhere; realistic
  cost ~10–13 bp (HYPE impact spread is only ~2bp, so cost is fees + the BTC hedge leg). Under the only
  honestly-tradeable execution — **maker-entry / taker-exit** (can't guarantee a passive fill at a fixed exit
  horizon) — best OOS cell = **+1.7 bp, 95% CI [−6.6, +10.0], MDE ≈ 12 bp, point estimate at zero**, most
  cells significantly negative. Only maker/maker (double-passive, unmodeled adverse selection) flips positive,
  and that corner **fails the first OOS slice** (202604 = −4.6) and is a 6×3×26×3 multiple-comparisons argmax.
  Conditioning (26 configs), hedge-ratio (under-hedging *hurts* OOS), horizon, and mid-vs-oracle basis (mid
  reverts ~1.5bp more, still sub-cost) — none yield a robust OOS net-positive.

**VERDICT: earned method-scoped NEGATIVE — no deployable edge from per-minute HYPE overshoot-reversion,
taker or realistic maker.** The reversion is *real and HYPE-specific* (t≈−13, OOS-stable) but structurally
**sub-cost** — same wall as `../basis/` and the cascade legs: the edge lives faster/smaller than per-minute
execution can harvest (the HLP/rebate domain).
**One door left, honestly labeled INCONCLUSIVE (not a live positive):** genuine maker-*rebate* liquidity
provision at 5–10 min shows gross +3 to +12 bp — but resolving it needs **sub-minute fill + adverse-selection
modeling on L2/BBO data this per-minute tape cannot provide.** Registered as a candidate; not promising enough
to deploy or to keep looping the per-minute test. Liquidations confirmed a red herring for this effect.

## Compute note
Full-month per-wallet window reconstruction is heavy and **timed out (2 min) against the running episode
build** (PID 3987, ~64% CPU). One-day scope runs in seconds. The engine must be **day-chunked with
position carryover** (or run after the build frees RAM), not a single month-wide window.
