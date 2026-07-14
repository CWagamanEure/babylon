# IDEATION SWARM — SYNTHESIS (7 agents, 2026-07-11)

Generative swarm: "where are we averaging away signal, and what recovers it." 7 lenses (filters/R-Q,
target/book, cross-sectional, aggregation, time/event, steelman, size). Each returned a ranked idea list;
several ran a quick cache probe. Below = deduped, cross-ranked. **These are IDEAS with a pulse, NOT validated
edges** — every probed number is pre-gauntlet (needs phase-averaged book + OOS + placebo + multiplicity before
it earns a verdict, per CLAUDE.md). Convergence = # of independent agents that landed on it.

## CROSS-CUTTING CATCHES (apply to everything below)
- **t+1 entry is mandatory when probing the book from cache.** target/book agent: t+0 entry manufactures a fake
  rank-IC −0.094 (contemporaneous impact-reversion) that flips to +0.021 at t+1. Any cache book must enter t+1.
- **Most of these are MAKER-side signal-quality lifts that SIDESTEP, not solve, the passive-fill gate.** The few
  that attack the gate directly are flagged ⚔️. The load-bearing unknown (offline-unmeasurable fill rate) stands.
- **Residualization caveat:** `s_inf` in the cache is already ⊥[crowd, lag/mom]. Any "fade/reversal" split must be
  re-checked on the PRE-residual signal to rule out a residualization artifact.

---

## TIER 1 — cache-cheap + already probed positive (do first, ~hours each)

### 1. Covariance-aware / min-variance book on the SAME signal ⭐ CONVERGENCE ×2 (target/book #1-2, cross-sec #1-2)
- Averaging-away: equal-weight decile discards the entire alt covariance ("rotate A↔B" = one paired bet booked as two).
- Both agents PROBED the diagonal-only version (inverse-vol): reb4 IR **4.13→4.56**, folds **6/7→7/7**; reb2 IR 4.17→4.34.
- Construction: char-portfolio `w ∝ Σ⁻¹·rank(S)`, Σ = Ledoit-Wolf shrunk train-window resid_alt cov, dollar/beta-neutral.
- Cost: cache-only, ~1hr. Overfit LOW (Σ from train, few DoF). Maker: HELPS (netting → lower turnover); add a liquidity
  floor so it doesn't tilt into thin names. **The cleanest convergent quick-win.**

### 2. Conviction-CONCENTRATION book + point-in-time cost ⭐⚔️ (steelman #1) — the TAKER-RESCUE candidate
- Averaging-away: equal-weight decile + hold-band averages extreme high-conviction cells with marginal ones → understates
  per-crossing gross 3–20×; "taker-dead" was concluded on the maximally-diluted book.
- PROBED (OOS 202603-06): per-crossing gross +0.92(top30%)→+7.08(decile)→+19.46(top5%), **static half-spread stays flat 3.7bp**
  (not just picking wide names). Taker net/crossing flips −5.3→+1.0(decile)→+13.4(top5%). Survives over-carry: decile median
  **+6.2**, **79% hours positive**, trim-top-5%-hours still +5.9.
- ⚔️ If it holds it's a TAKER expression that MOOTS the maker-fill gate — highest-value flip on the line.
- THE hinge (test this): replace static `hs_arr` with **point-in-time asset_ctx spread** of the just-reverted names (they're
  extreme *because* they just moved = widest instantaneous spread). Cap at decile/liquid-15 (netting trap). Require the positive
  MEDIAN to survive PIT cost, not just the mean. Cache + asset_ctx, cheap.

### 3. Fade-vs-chase gate → book ⚔️ CONVERGENCE ×2 (filters #1, steelman #3)
- Averaging-away: the book pools contrarian cells (informed flow FADES the recent move) with momentum-chasing cells; the signal
  is almost entirely contrarian.
- PROBED (filters): K=8h IC all +0.028, **chase +0.005 vs fade +0.049** (~10×), fade>chase **7/7 OOS months (p≈0.016)**.
- steelman #3 frames the mechanism: reversal×informed-flow are complementary conditioners — fade only where informed flow is
  absent/opposed; don't fade where informed flow is behind the move (that's where a passive maker gets run over).
- ⚔️ Contrarian = resting orders against crowd aggression = plausibly HIGHER passive-fill rate + favorable adverse selection.
- Cost: cache. GUARD: re-verify on pre-residual signal (s_inf already ⊥mom). Take fade + fade×consensus through the phase-avg book.

---

## TIER 2 — one cheap pipeline pass (~130s re-agg), high-EV, stacks on the PROVEN consensus mechanism

### 4. Conviction axis at the VOTE level, de-whaled ⭐ CONVERGENCE ×2 (size #1+#3, steelman size-note)
- Averaging-away: one-wallet-one-vote treats a wallet sizing 5× its norm identically to one poking at 0.3×; intensity averaged flat.
- size agent VERIFIED the de-whaling property on cache: `corr(sizing-up flag, wallet abs-size pct) = +0.031 ≈ 0` — small wallets
  size up as often as whales, so a conviction-BREADTH aggregator is structurally immune to the whale bug that killed dollar-sum.
- Two forms: (a) `conv_a = Σ W·1[z_w≥τ]/ΣW` where `z_w=|flow|/own-trailing-median`, rank by `S_a·conv_a` (mirrors the proven
  `S_a·cons_a` recipe); (b) net/gross LEAN vote `lean_w=net/gross ∈[−1,1]` replacing sign (bounded → no whale term). Pre-register τ=2.
- Cost: LOW — add a `Σ|flow|` column to the cohort re-agg. Run the exact placebo (60 random cohorts) + day-block CI + per-coin sign
  battery that certified consensus. Maker (gross/IC). Success = beats fixed breadth AND clears placebo.

### 5. Effective-independent breadth — residual-herd de-duplication (aggregation #1)
- Averaging-away: breadth & consensus assume independent votes; sub-accounts/copy-bots = one bet counted many times.
- PROBED: raw N_eff = **19 of 1200** wallets — but most of that collapse is LEGITIMATE shared consensus (the live lever, keep it).
  After projecting out the top-k consensus PCs, **11–17% of wallets still have a >0.7 co-voting twin** = the real residual herd.
- Construction: project out top-k consensus PCs FIRST, cluster the residual, replace raw count with `N_eff` in breadth/consensus.
  Pure denoise, NO added turnover → helps maker + taker. Rider: compute N_eff of the deployable top-150 (is the live poll a herd?).

### 6. Within-hour recency-weighted vote (time #1)
- Averaging-away: hourly poll weights a :05 fill = a :55 fill, but level half-life = **0.47h** (probed) → the :05 fill is ~85%
  decayed by the next open. Flat within-bar averaging blends stale + fresh.
- Construction: weight each fill's contribution by `exp(−(bar_close−fill_ts)/τ)`, τ≈0.5h frozen from measured HL (no search).
- Cost: pipeline (intra-hour timestamps already in node_fills). **Pure signal-quality lift at IDENTICAL turnover** → the only
  "harvest faster" that does NOT lean harder on the fill gate. Bank this as the new baseline before testing costlier faster-reb.

### 7. Smart-money-vs-crowd polarization (aggregation #4) — genuinely orthogonal to consensus
- Averaging-away: consensus discards *contested* cells (fwd-IC≈0), but a cell where the TOP-skill tier is long while the low-skill
  crowd is short reads as "contested" yet is high-conviction smart money. Consensus averages the tiers together.
- Construction: split cohort into skill tiers by W; signal = top-tier lean conditioned on top-vs-bottom disagreement (smart-dumb spread).
- Cost: pipeline. The cleanest NEW axis orthogonal to the live consensus lever. Guard: top tier is thin → small-K.

---

## TIER 3 — structural / new-data bets (higher ceiling, higher cost/risk)

### 8. Position-BUILDING vs churn, from startPosition ⭐ CONVERGENCE ×2 (steelman #6, size #4-5)
- Averaging-away: a wallet OPENING/ADDING (new conviction, new money) carries more forward info than one FLIPPING/TRIMMING
  (inventory churn); pooling them dilutes the informative subset. Still one-wallet-one-vote → whale-immune.
- Construction: classify each fill via start_position + signed size as OPEN-from-flat / ADD / TRIM / FLIP; vote from ADDS+OPENS
  only (or the pure flat→open "fresh conviction" subset). Majors: start_position is in the tape (cheap). Alts: Reservoir re-agg or
  causal cumsum proxy. Novel + orthogonal to everything tested; position reconstruction is already solved. Possible turnover cut
  (builders are stickier → adverse-selection help). MED cost.

### 9. Early-mover / lead-lag sub-cohort ⚔️ CONVERGENCE ×3 (aggregation #2, time #5, steelman #7)
- Averaging-away: aggregation is order-blind — sums leaders + followers at one timestamp. The edge is a slow ~1h build (Result 6);
  identifying WHO leads it → enter at the start, capture more before the crowd is paid.
- ⚔️ The one idea that could crack the TAKER gate (earlier entry on a slow build may clear cost the averaged signal can't).
- Construction: TRAIN lead-score per wallet (flow leads cohort shift / forward resid); leader-tier vote = fast signal, crowd = confirm.
- Cost: pipeline + sub-hourly grain. Guard: per-wallet lead-score noisy → pool to a TIER not individuals; freeze on train.
- Note: pulls opposite to #6 (recency = closer-to-trade = fresher; lead-lag = earlier = more informed) — running both disambiguates.

### 10. Pairwise rotation transition matrix (cross-sectional #2) — highest structural ceiling
- Averaging-away: a wallet moving INTO A and OUT OF B is ONE relative-value decision scored as two independent votes.
- Construction: per-wallet A→B rotation events → skill-weighted transition matrix T[A,B]; signal(A)=net rotation-in − rotation-out.
- Cost: pipeline (per-wallet transitions + raw fills). The purest attack on the cross-sectional lens; the cache literally can't
  represent it. Overfit MED (pair space large → shrink/threshold on breadth). Speculative but the biggest genuinely-new structure.

### 11. Liquidation-cascade event clock ⚔️ (time #3)
- Averaging-away: clock-time averages liq-adjacent fills (informed cohort = passive absorber of forced flow) into quiet-tape fills.
- ⚔️ STRUCTURALLY FAVORS the maker gate: after a cascade the cohort is the passive side (limits absorbing forced sells) = naturally
  high fill probability + FAVORABLE adverse selection (paid to provide liquidity). Best conceptual fit to the load-bearing unknown.
- Construction: flag formation bars with a liq cascade (liq notional > k×trailing median, from the raw-tape liq struct / asset_ctx OI
  drop, strictly pre-t); interact S_a with liq intensity. Consistent with the known "this cohort dip-buys." HIGH cost (new join), HIGH EV.

---

## TIER 4 — cheap riders / conditioning (bolt-on, lower stand-alone EV)
- **Vol-adaptive harvest horizon** (target/book #3, time #4, steelman #5; CONV ×3): reb=f(realized vol), reb1 high-vol/reb4 calm.
  Cache-feasible (`disp`). ⚠️ per-NAME decay does NOT persist (known) → gate on hs_arr early/late persistence; only the vol-REGIME
  (market-level, persistent) half is expected to survive. Extends the biggest known lever with one monotone knob.
- **Sub-hourly frequency sweep** (time #2): rebuild panel at 30/15/5-min; reb1>reb2>reb4 hasn't bottomed (0.47h HL). ⚠️ leans HARDER
  on the fill rate + thins breadth → pair with a live-follower high-cadence arm.
- **Funding/OI-extreme conditioning** (filters, time #6): interact S_a with |funding|/OI-extreme. asset_ctx, cheap. Predetermined → low leak.
- **Per-liquidity-tier ranking** (target/book #4): rank within STRUCTURAL liquidity tiers (not realized per-token IC = dead), book per
  tier, risk-combine. The liquid tier is directly more taker-tradeable — a deployable sub-book that sidesteps the maker gate.
- **Cross-coin lead-lag** (cross-sec #3): augment score with covariance-neighbor lagged signal `S_a + λ·Σ C_ab·S_b(t−1)`. Cache, fast.
- **Decile-spread-IC objective** (target/book #7): tune W + decile depth on tail-spread accuracy (what the book trades), not full-panel rank-IC.
- **Sector-specialist timing weights** (aggregation #3): per-(wallet,sector) timing score — powered extension of the live Result-9 timing basket.

---

## KILLS & CAUTIONS from this swarm (record so we don't re-run)
- **Within-sector RV neutralization: PROBED NEGATIVE** (cross-sec). Global signal carries real sector-DIRECTIONAL content;
  neutralizing it lost return (IR 4.13→3.20) without enough variance reduction. The earlier "within-sector lift" was a degenerate-
  clustering artifact. DEAD.
- **"Promote alt-complex timing basket" (steelman #2): CAUTION.** The alt-timing follower was already STOPPED — clean alt-only OOS
  IC +0.0045 (t≈0.3), the apparent edge was BTC/ETH rotation-beta contamination. Don't naively re-tread; any revival must be alt-clean.
- **Fully-stacked book (steelman #4):** run LAST, only under a true 3-way split (cohort/config/test) — stacking multiplies in-sample
  choices; it's the biggest over-carry risk on the list.
- Distribution-shape pooling (aggregation #7), spectral community gating (cross-sec #4): flagged by their own agents as likely
  redundant with breadth/consensus or adjacent to dead per-token reliability — lowest priority.
