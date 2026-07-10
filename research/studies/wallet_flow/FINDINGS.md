# Findings ledger — wallet_flow (informed-wallet cohort as the xsec_statarb differentiator)

Design: `flow.py` docstring (ARCHITECTURE §10, AUDIT_RESPONSE A8). Firewalled research lane; reads only
`research.data.db` (asset_ctx, fills). Majors only (BTC/ETH/SOL/HYPE — the fills tape is majors-only).

QUESTION: does signed flow from a strictly point-in-time **informed-wallet cohort** predict factor-neutral
forward returns on majors, BEYOND aggregate order-flow imbalance (OFI)?

## Setup (what was tested)
- **Feature (the only one):** wallet **alignment** = mean over the wallet's TRAIN buckets of
  `sign(flow) × fwd_resid`. Rank all active (≥50 lifetime trades, non-vault) wallets; freeze **top 20%**.
  No size / PnL / holding-time / maker-taker / win-rate features tested — just this one persistence proxy.
- **Target:** factor-neutral forward residual return (LOO equal-weight major index, rolling causal beta), 1h & 2h.
- **Split:** train month<202603 / held-out test month≥202603, disjoint. Cohort wallet-id list FROZEN on train (A8).
- **Inference:** partial IC (cohort flow residualized on OFI), block bootstrap over time-blocks; per-coin sign.

## RESULT 1 — cohort adds predictive value beyond OFI, OOS (2026-07-09, `flow.py`)
- 231,349 active wallets. Sanity A ok (all-wallet signed flow ≈ 0; both counterparties recorded).
- **1h: COHORT PARTIAL IC | OFI = +0.0299, 95%CI [+0.0102, +0.0479]** (excludes 0); reg cohort coef +0.022, t=+2.3.
  Per-coin: BTC +0.0225, ETH +0.0205, SOL +0.0038, **HYPE +0.0407 (highest)**.
- 2h: partial IC +0.0181, CI [−0.0015, +0.0387] (touches 0); coef t=+2.4. Per-coin HYPE +0.003 (collapses), ETH leads.
- **Positive control anomaly:** aggregate OFI naive IC came out NEGATIVE (−0.011, insig). Defensible as
  post-bucket impact reversion (aggressor impact reverts; informed net flow predicts the *opposite*), but it
  means the OFI control did NOT cleanly certify the pipeline → the placebo below carries that burden instead.

## RESULT 2 — PLACEBO (prosecute-the-positive pass, 2026-07-09, `placebo.py`) — SELECTION IS REAL at 1h
60 random same-size cohorts drawn from the SAME eligibility pool (isolates the alignment feature from
"any big active-wallet basket"):

| H | informed partial IC | random mean | random sd | 95% band | z | one-sided p | verdict |
|---|---|---|---|---|---|---|---|
| **1h** | **+0.0299** | +0.0053 | 0.0113 | [−0.012, +0.030] | **+2.17** | **0.033** | **SELECTION MATTERS** |
| 2h | +0.0181 | +0.0024 | 0.0125 | [−0.022, +0.022] | +1.26 | 0.067 | ambiguous |

- Random cohorts have a **small positive mean IC (+0.005)** — so *some* of the naive cohort signal is generic
  "big-basket flow ≈ diffuse OFI." But the **alignment selection adds ~+0.025 IC beyond that**, at the 97th
  percentile of the random distribution (p=0.033). The feature is NOT OFI-in-disguise and NOT just "big wallets."
- 2h is only elevated (p=0.067), consistent with the weaker 2h partial IC.

## RESULT 3 — WALK-FORWARD (2026-07-09, `walkforward.py`) — 1h ROBUST across folds, 2h is noise
Expanding-train / single-forward-month folds; each fold re-freezes the informed cohort on train-only and
re-runs 40 random cohorts on that one month. Test months 202602…202606.

**h=1 (deliverable):**
| test month | n | informed IC | random mean±sd | gap | p(rand≥inf) |
|---|---|---|---|---|---|
| 202602 | 2689 | +0.0217 | +0.0086±0.0243 | +0.013 | 0.275 |
| 202603 | 2977 | +0.0327 | +0.0065±0.0204 | +0.026 | 0.075 |
| 202604 | 2880 | +0.0334 | −0.0048±0.0160 | +0.038 | **0.000** |
| 202605 | 2904 | +0.0095 | −0.0033±0.0232 | +0.013 | 0.350 |
| 202606 | 2780 | +0.0313 | −0.0084±0.0182 | +0.040 | **0.000** |

- **Informed IC positive in 5/5 folds (sign-test p=0.031); mean +0.0257. Beats random in 5/5 (p=0.031); mean
  gap +0.0260.** Direction-consistent every forward month → NOT one lucky quarter. The "one-window" risk retires.
- **BUT** per-month only 2/5 individually clear the placebo (202604, 202606 at p=0.000; 202603 marginal); in
  single months the effect often sits INSIDE the random band (n~2900 too small per month). Consistency carries
  it, not per-month significance. And folds share a largely-overlapping expanding wallet pool → the 5 draws are
  time-disjoint but NOT fully independent, so p=0.031 slightly overstates independence.

**h=2:** informed positive 2/5 (p=0.81), beats random 2/5 (p=0.81), mean gap +0.007 — NOISE, one lucky month
(202604 +0.044) carries the mean. Confirms the signal is a **1h-specific** phenomenon.

## RESULT 4 — TRADEABILITY BOOK (2026-07-09, `book.py`) — taker-dead, but MAKER ceiling is STRONG
Factor-neutral majors book from the signal: hourly cross-sectional rank weights over the 4 majors (dollar-
neutral), t+1 entry, 1h hold, realized leg PnL = fwd_resid (beta-neutral). Cost re-measured from asset_ctx
impact px — **majors are cheap:** half-spread BTC 0.07 / ETH 0.23 / SOL 0.28 / HYPE 0.97 bp; per-crossing
taker cost ≈ half-spread + 4.5 bp fee ≈ **4.9 bp** (vs the ~9 bp alt spread behind the xsec 36 bp wall).

| book (full 4-name) | gross bp/hr | cost bp/hr | net bp/hr | net SR [95%CI] |
|---|---|---|---|---|
| **informed cohort** | **+1.51** | 5.78 | −4.27 | −13.2 [−16.5, −9.5] |
| random cohort | +0.51 | 6.08 | −5.58 | −18.6 |
| OFI (order flow) | +0.45 | 6.07 | −5.62 | −18.8 |

- **Signal is real in a portfolio:** informed gross +1.51 = ~3× random (+0.51) and OFI (+0.45) — the IC edge
  carries all the way into book gross, not an artifact. Concentration lever (top/bottom-name-only) did NOT help
  (net −5.02, worse turnover) → no cheap taker rescue.
- **TAKER = earned negative, near-deterministic:** net −4.27 bp/hr, SR −13 (CI firmly negative). Break-even
  needs per-crossing cost ≤ **1.27 bp**; taker fee ALONE is 4.5 bp → cannot clear. Same wall, cleanly earned.
- **⭐ MAKER ceiling is the real news — and unlike xsec, it's STRONG:** zero-cost gross **Sharpe = +4.69
  [+1.22, +8.11]** (CI excludes 0), turnover 1.19/hr, break-even 1.27 bp **> maker cost (~0 fee + 0.39 bp
  half-spread ≈ 0.4 bp)**. So at maker fees the book clears break-even with headroom, and the ceiling (~4.7) is
  high enough to absorb substantial adverse selection — vs the xsec reversal whose zero-cost ceiling was only
  ~1.4 / negative OOS. The load-bearing unknown is **adverse selection / fill probability** (a maker gets filled
  adversely on the informative moves; gross +1.51 assumes mid fills). Unmodeled — needs L2/BBO or a forward paper
  test. NB [[babylon-oos-persistence]] Stage H found this style of cohort DIP-BUYS (favorable maker fill), which
  makes the maker path more plausible but does not resolve it.

## RESULT 5 — STEELMAN SWARM (2026-07-09, 6 agents, `audit/wallet_book/STEELMAN_SCOPE.md`) — no buried taker edge; verdict framing corrected ~2×
User pushed: "we're disregarding a real taker edge." 6 adversarial agents (cost, code, turnover, concentration,
horizon, estimand) each prosecuted a way the null could be false. 5/6 HARDENED it; the 6th corrected our wording.
- **Cost model is honest** — turnover not double-counted, legs consistent, spread mildly conservative;
  taker stays negative at EVERY HL fee tier (net −1.78 even at top-tier 2.4 bp, full book). Fee×turnover is the wall.
- **No code bug** — t/t+1 pairing is optimal (±1 shift destroys gross by 10×), sign correct (corr +0.91),
  NaN-divides benign, z-weights don't beat ranks. +1.51 gross is faithful; 4-name breadth is what caps it.
- **Turnover can't rescue it** — gross is a LAG-0-ONLY impulse (hour-0 +1.51 t=2.7; hours 1-12 all noise).
  Holding longer spreads a FIXED ~1.5 bp over more hours; best net crawls to ~0 (SR ≤ +0.6) only by collecting
  ~no gross. Causal conviction-gate / EMA / hysteresis / fewer-names all fail. **Turnover ≈1/hr is FORCED by the
  1h alpha decay, not a construction choice.**
- **Concentration/directional** — no variant clears the 4.5 bp floor (best HYPE+ETH net −1.98, CI touches 0).
  Raw UNHEDGED directional cuts turnover ~25% (helps the maker path) — BUT the event-study shows the multi-hour
  raw hump (+13 bp h2-h3) is pure MARKET BETA (residual ~0), not alpha. HYPE @1h +10.7 is small-n selection noise.
- **⚠️ CONSTRUCTION-CONSERVATISM CORRECTION (estimand agent, real):** our headline break-even (1.27 bp/crossing)
  was computed on the maximally-turnover-heavy IC-book — the over-null-gate point-4 hazard. The FAIR turnover-
  optimized book (no-trade band τ=0.25): gross +1.95, turnover 0.84, **gross/crossing 2.33 bp** (not 1.27), net
  @4.5 = −2.11 [−3.16,−1.06]. **At the top-tier 2.4 bp fee this book's net CI = [−1.40, +0.69] — straddles zero
  → INCONCLUSIVE, not "dead," at that tier** (MDE > deficit). Still: point estimate negative, rides an in-sample
  argmax τ + single 4-name window → borderline, NOT a live taker edge.
- **The decisive frame:** MAKER strictly dominates taker at every fee tier (same gross/turnover, lower cost);
  even taker's best (top-tier, band-optimized, HYPE-tilted) case is dominated. HYPE is a real per-coin concentration
  (g/crossing +3.60) that SOL (−0.72 drag) masks. So taker is moot regardless → the SOLE load-bearing question
  stays maker fill-probability / adverse selection.

## RESULT 6 — SUB-HOURLY (2026-07-09, `subhourly.py`) — the edge is SLOW, not fast; no burst/taker escape
Re-measured at 1-min & 5-min buckets, reusing the frozen hourly cohort (leak-free). A3-clean (forward = post-bucket).
- **Intra-hour IC decay is MONOTONICALLY INCREASING** (cohort flow → forward residual), i.e. the edge is
  weakest at short horizons and builds over the hour: 1-min-bucket naive IC = 1m +0.0025, 5m +0.0075, 15m
  +0.0114, 30m +0.0147, **60m +0.0170**; 5-min-bucket similar (5m +0.004 → 60m +0.012). This is the OPPOSITE
  of a fast informed-flow impulse — the signal predicts a **slow ~1h drift**, not a few-minute pop.
- **Burst event study (top-decile |cohort flow| bucket, signed forward move) — no fast move to capture.** Signed
  RESIDUAL forward return grows slowly and stays tiny: ALL-majors 5m +0.45 → 60m +1.55 bp; HYPE 5m +1.34 → 60m
  +2.96 bp. Every horizon's signed move (1–4 bp) is FAR below the ~9.8–10.9 bp taker round-trip → netRAW −6 to
  −10 bp at every horizon, 1–60 min. HYPE strongest but still ~3–4 bp << 10.9 bp cost. (n large but events highly
  non-independent — read the SHAPE and the order-of-magnitude, not the point CIs.)
- **Consequence:** checking within the hour CLOSES the fast-burst taker escape hatch (contra the markout Stage-H
  fast-burst analogy — THIS cohort is slow, not fast). It confirms ~1h is the right horizon and reinforces
  maker-only. Small silver lining for the maker path: a slow ~1h build means you have TIME to work passive limit
  orders (less urgency → potentially less adverse selection) rather than needing to cross immediately.

## RESULT 7 — ALT-BREADTH TEST (2026-07-09, `alt_flow.py`/`alt_placebo.py`/`alt_confirm.py`/`alt_sweep.py`/`alt_wf_sharp.py`) — the majors signal does NOT cleanly transfer to the alt cross-section; a thin top-tail is a live underpowered positive
> ⚠️ **SUPERSEDED IN PART BY RESULT 8 (2026-07-10).** The "earned negative on EXISTENCE" below was reached with a
> **mis-specified aggregator**: the cohort is SELECTED on sign-agreement but was DEPLOYED as a whale-dominated
> dollar-SUM (`Σ flow_signed`). A coherent consensus-BREADTH aggregator on the same cohort recovers a real, broad,
> sector-robust, CI-excludes-0 signal at the pre-registered Q=0.20 (Result 8). The DEPLOYMENT negative (sub-cost by
> ~10×) still stands; the EXISTENCE negative does not. Read Result 8 first.
Ran the exact informed-cohort pipeline on a **point-in-time ~45-name liquid-alt cross-section** (`alt_universe.py`,
$2M trailing-ADV floor, formed 2026-03-01), sourced from the Reservoir `alt_flow` tape (per wallet×coin×5-min signed
notional; 334/334 days; cohort flow = Σ flow_signed over BOTH crossed, OFI = FILTER crossed). Factor-neutral residual
on BTC+ETH-orth+LOO-alt-index (causal rolling beta), H=1h, POST-bucket; H-embargo at the TRAIN/TEST seam; drop the
partial price day 2026-05-30; TRAIN month<202603 / TEST ≥202603 (129,510 coin-hour cells; pool 66,144 wallets).
Built to `ALT_BREADTH_AUDIT_RESPONSE.md` (breadth buys POWER, not gross/crossing — N cancels).
- **Load-bearing placebo at the majors-inherited COHORT_Q=0.20: FAIL.** Partial IC|OFI +0.0058, day-block 95%CI
  [−0.0006,+0.0123]; vs random same-size cohorts the informed sits INSIDE the null band [−0.0034,+0.0091],
  random mean +0.0028±0.0033, **z=+0.91, p=0.19**. (Naive cohort IC +0.0074 [+0.0009,+0.0139] "clears zero" but
  the random-cohort mean also clears — CI-vs-zero is NOT the selection test; the placebo is.)
- **Positive control (instrument is NOT blind):** in-sample the same pipeline separates hugely — informed IC
  +0.0572 vs random +0.0013±0.0033, **z=+16.85**. So the OOS placebo FAIL is genuine OOS DECAY, not blindness.
- **Cohort-sharpness sweep (anti-ratchet powered attempt — COHORT_Q=0.20 was the wrong knob for a 45-name panel;
  a random 20% cohort shares ~2,646 wallets with informed BY CONSTRUCTION, diluting the gap):** as the cohort
  sharpens the placebo revives — top-5% z=+1.38 p=0.072; **top-2% z=+1.83 p=0.035; top-1% z=+1.88 p=0.020** (both
  clear). BUT informed IC barely moves (+0.0058→+0.0082); most of the z-gain is the MECHANICAL collapse of the
  random baseline (+0.0027→+0.0005) as overlap drops. Reproduced independently by the steelman agent (z 1.67/1.91).
  ⚠ top-2%/1% is an **argmax over 5 Q-values** (Bonferroni×5 → p≈0.10) — suggestive, not clean.
- **Walk-forward at the sharp knob (the diluted-knob confound cleared):** at Q=0.20 it was 3/4 with one strongly
  NEGATIVE fold (202605 z=−1.30), sign-test p=0.31. At **Q=2%: 4/4 folds informed>random** (per-fold z
  {0.35,0.86,1.07,0.55}), sign p=0.062; at **Q=1%: 4/4, mean z=+1.18** (202605 flips to +1.86). 4/4 is the sign-test
  floor (p=0.0625) — consistent in SIGN but every fold individually weak (max z 1.9).
- **Conviction-WEIGHTED book (the cleanest estimator — all 66,144 wallets, rank weight, no arbitrary cliff, no
  Q-argmax): DEAD NULL, IC −0.0004, z=−0.14, p=0.59.** A real monotone concentration of skill in aligned wallets
  should make this positive; it doesn't → the top-1% "pass" is plausibly small-K selection variance in a 661-wallet
  tail, not smooth concentrated skill. (Gate: a tight null on the load-bearing quantity outweighs a downstream lean.)
- **Magnitude:** even the best-case informed IC (~0.008) is far below the pre-registered alt taker hurdle
  (5.5–7.6 bp/crossing vs projected gross/crossing 1.8–2.5 bp) → sub-cost even if real; not taker-deployable.

### RESULT 7 VERDICT (gated; steelman + prosecutor both run) — DEPLOYMENT: EARNED NEGATIVE; residual: unresolved sub-cost lean
- **Breadth does NOT rescue the informed-cohort signal into tradeability — taker OR maker. EARNED (powered)
  NEGATIVE** on deployability, exactly as `ALT_BREADTH_AUDIT_RESPONSE.md` pre-registered. Passes all four over-null
  pillars: (1) primary partial IC|OFI +0.0058, 95%CI [−0.0006,+0.0123] → the CI's *entire* range maps to
  0.35–0.75 bp gross/crossing (spec anchor ≈61 bp × IC), ~7–15× below the 5.5–7.6 bp taker hurdle AND the ~4.8 bp
  maker break-even; (2) the pipeline is POWERED (in-sample z=+16.85), so the ~0.09 IC deployment would need is
  excluded by the CI by a mile — MDE ≪ care-about; (3) cross-unit combined = null (conviction-weighted book over
  all wallets z=−0.14; nested walk-forward sign p=0.062 fails its bar); (4) placebo built symmetric, not against.
- **The residual thin-tail positive is DEMOTED to "unresolved sub-cost residual, direction positive" — NOT carried
  as a live positive** (over-carry gate). It is: a post-hoc argmax over 5 cohort sizes (Bonferroni×5 → p≈0.10);
  ~48% manufactured by mechanical random-baseline collapse (hold baseline fixed → top-1% z=1.34, p≈0.09, FAIL);
  non-monotone in sharpness; contradicted by the clean no-cliff conviction-weighted NULL; and its 4/4 walk-forward
  uses nested expanding train windows (~90% shared cohort membership → not 4 independent trials). Nothing survives
  honest multiplicity correction.
- **Known limitation (does not change the deployment verdict):** the binding F4 sector/PC factors + sector-matched
  placebo were NOT built (only BTC+ETH+single LOO alt index), so the ~0.008 tail micro-lean is not certified free of
  residual sector-momentum leak. Immaterial to deployability (sector control reduces cohort IC; it cannot lift a
  0.008 IC ~10× to clear cost) — but it means "is there ANY real residual micro-signal in the tail" stays formally
  un-adjudicated. Only worth building if a **zero-cost (maker) use** is ever in view; not for the taker book.
- **Label:** *the majors informed-cohort signal does NOT extend to a taker- or maker-DEPLOYABLE edge on the liquid-alt
  cross-section (earned powered negative, sub-cost by ~10×). Breadth — the one structural lever the steelman swarm
  left open — is now TESTED and exhausted for deployment. A tiny positive-direction tail residual persists but is
  multiplicity-insignificant, half-mechanical, and structurally sub-cost → shelved, not carried.* The only genuinely
  promising unresolved thread remains the MAJORS maker path (Result 4, zero-cost SR +4.69), not alts.

## RESULT 8 — META-AUDIT SWARM (2026-07-10, 6 agents `audit/alt_breadth_meta/SCOPE.md` + `alt_breadth_confirm.py`) — the Result-7 EXISTENCE-negative was an AGGREGATOR ARTIFACT; a real broad alt signal exists (still sub-cost)
User: "we are for sure missing something… where are we over-generalizing / averaging away the result?" → 6-agent
creative swarm, each hunting a distinct signal-loss mechanism. It found the pooled net-notional hourly rank-IC is a
badly mis-specified estimator, and the strongest thread (agent C) reverses the existence-negative.
- **⭐ THE FINDING (agent C, then reproduced + hardened by me in `alt_breadth_confirm.py`): the aggregator is
  incoherent with the selection.** Cohort is SELECTED on sign-agreement (`alignment=mean(sign(flow)·fwd_resid)`,
  one-wallet-one-vote) but was DEPLOYED as `cohort_flow=Σ flow_signed` — **whale-dominated** (median top-wallet share
  of cohort |flow| = 0.62 on cells with ≥5 wallets; Herfindahl 0.47 vs 0.14 equal-weight) and **net-cancelling**.
  Swap to consensus-**breadth** `(#long−#short)/#active` on the SAME cohort:

  | gate | net-notional (Result 7) | **consensus-breadth** |
  |---|---|---|
  | (1) placebo @ **pre-registered Q=0.20** | +0.0058, z=+0.90, FAIL | **+0.0112, z=+3.81, p=0.002 ✓** |
  | (2) per-coin consistency (pillar-3) | ~23/45 ≈ chance | **30/45 beat random, sign-test p=0.018 ✓** |
  | (3) sector×hour-demean (never-built F4 control) | z=+0.72 | **z=+2.17, p=0.016 ✓ (survives)** |
  | (4) day-block 95% CI on breadth IC | — | **[+0.0052, +0.0177], excludes 0 ✓** |

  Breadth ~2× the IC, clears at the PRE-REGISTERED knob (no argmax), is BROAD across coins (not the 2-3-coin
  artifact the prosecutor found in the net agg), survives sector-neutralization (some herding: z 3.81→2.17, but a
  real residual remains), and CI excludes 0. It also **explains away the prosecutor's "clean null"**: the
  conviction-weighted book that was z=−0.14 weighted by rank×**notional** — it doubled down on the whale-domination
  bug, so its null was PREDICTED by this mechanism, not evidence of absence. The over-null gate did its job: a real
  broad signal was buried by a construction choice.
- **Secondary live threads (agents B, D — untested by placebo, lower priority):** (B) the LOO-alt-index
  neutralization deletes ~40% of the IC (partial IC full +0.0058 → BTC/ETH-only +0.0083) and the market-kept IC
  **grows with horizon to +0.0106 @24h** → the cohort may be timing the whole alt COMPLEX (a cheaper basket
  estimand the per-name residual defines away) — worth a placebo-hardened be-cumulative-24h + index-beta test.
  (D) the hourly bucket blends a DEAD early-hour flow (IC ≈ 0) with a LIVE late-hour flow (IC +0.006; last-5-min ≈
  full hour) → a 15-min re-grain might sharpen (but Result 6 "edge is slow" cuts against). Agent F's
  conviction-threshold cut (+2.7 bp top-decile) is real but microcap/large-move concentrated (negative median).
- **Agents E + F HARDENED parts of the negative:** E ran the missing per-coin (pillar-3) combination on the NET
  aggregator → chance at every knob (the sharp-Q "revival" was argmax-of-coins, confirming the demotion). F killed
  the magnitude/volatility idea (−0.0293).
- **RESULT 8 VERDICT (gated):** **EXISTENCE = POSITIVE (over-null correction).** A real, broad, sector-robust,
  placebo-hardened, CI-excludes-0 informed-cohort signal DOES exist on the ~45-name alt cross-section — Result 7's
  "earned negative on existence" was an artifact of a whale-dominated dollar-sum aggregator incoherent with the
  sign-based selection; the user's "we're averaging it away" was correct. **DEPLOYMENT = still NEGATIVE / sub-cost:**
  breadth IC ~0.0112 → gross/crossing ≈ 0.7 bp (≈61 bp × IC), still ~8–10× below the 5.5–7.6 bp alt taker hurdle
  AND below the ~4.8 bp maker break-even → NOT taker-deployable; maker needs the adverse-selection resolution and
  even then the edge is thin. **Label:** *real broad sub-cost alt signal; existence-YES / deployment-NO. The honest
  home is a maker/basket framing (like majors), OR agent-B's alt-complex-timing re-frame if it survives placebo.*
- **Next (ranked):** (1) B's market-timing test — does cohort breadth predict the forward alt-INDEX return? placebo
  + index-beta discriminator (cheapest-to-trade estimand, genuinely un-prosecuted); (2) build the F4 sector/PC
  factors properly + re-confirm breadth; (3) the maker path (shared with majors Result 4). Do NOT chase per-name
  Variant-B (E showed argmax-of-coins) or the taker book (sub-cost).

## VERDICT (gated) — real, placebo-hardened, WALK-FORWARD-ROBUST OOS feature at 1h; taker earned-negative (standard fee) / inconclusive (top-tier) but DOMINATED; MAKER-unresolved-but-promising
- **NOT null** (over-null gate): informed-wallet net flow carries incremental, point-in-time, factor-neutral,
  OFI-controlled predictive information at 1h that a random same-size cohort does not (partial IC +0.030, CI
  excludes 0, beats placebo p=0.033). First result on the whole stat-arb line to survive its own prosecution.
  Now walk-forward-robust (5/5 folds positive, 5/5 beat random, sign-test p=0.031 each) → not a lucky window.
- **TAKER book = earned negative at STANDARD fee, INCONCLUSIVE at top-tier, DOMINATED regardless** (Results 4-5):
  net −4.27 bp/hr @4.5 bp (band-optimized −2.11 [−3.16,−1.06]); turnover-optimized break-even ~2 bp/crossing (the
  1.27 bp figure was the worst-case IC-book — corrected). At top-tier 2.4 bp fee the net CI straddles zero
  (inconclusive, not dead), but it's a negative point estimate on an in-sample band + single window, and MAKER
  strictly dominates it at every fee → not worth pursuing the taker book regardless. Turnover ≈1/hr is forced by
  the 1h alpha decay (gross is a lag-0 impulse), so cost can't be amortized by holding — only more names help.
- **Remaining over-carry caveats:** (a) 1h-ONLY (2h noise); (b) per-month only 2/5 folds clear placebo
  individually (consistency carries it), folds share an overlapping wallet pool so 5/5 isn't 5 independent draws;
  (c) single 4-name book window for the PnL; (d) single self-referential feature, not a robust panel;
  (e) the MAKER ceiling (+4.69 gross SR) assumes mid fills — adverse selection is unmodeled and could erode it.
- **Label:** *real informed-flow signal at 1h (placebo-hardened, walk-forward-robust); TAKER-untradeable
  (earned negative); MAKER path genuinely promising & unresolved — zero-cost SR +4.69 [1.22, 8.11], break-even
  1.27 bp > maker cost ~0.4 bp (strong headroom, unlike xsec's ~1.4 ceiling). Resolve maker viability next.*

## Open / next (untested)
1. ~~Walk-forward robustness~~ **DONE (Result 3): 1h robust 5/5, 2h noise.**
2. ~~Tradeability book~~ **DONE (Result 4): taker-dead; MAKER ceiling STRONG (gross SR +4.69, break-even 1.27 bp
   > maker cost). This is the new focus.**
3. **⭐ Resolve the maker path (the load-bearing unknown)** — model fill probability + adverse selection. Two
   routes: (a) forward paper test posting passive quotes on the live signal (needs the signal wired live +
   clearinghouseState/order flow); (b) L2/BBO majors data to backtest maker fills. This now has a ceiling worth
   the investment (unlike the xsec reversal). Stage-H dip-buy precedent ([[babylon-oos-persistence]]) is encouraging.
4. ~~Alt extension~~ **DONE (Result 7): EARNED NEGATIVE for deployment.** Built the Reservoir `alt_flow` tape
   (334/334 days) + the full ~45-name alt cross-section pipeline. Breadth does NOT rescue tradeability (taker or
   maker): primary partial IC|OFI +0.0058 [−0.0006,+0.0123] → 0.35–0.75 bp gross/crossing, ~10× sub-cost; powered
   (in-sample z=16.85). Thin-tail residual demoted (argmax, half-mechanical, conviction-null). Breadth lever
   exhausted. (Optional, only for a maker use: build the F4 sector/PC neutralization + Variant B per-coin cohorts to
   adjudicate the un-certified tail micro-lean — low priority.)
5. **Richer wallet features** — size/PnL/holding-time/maker-share, only if the above justify the build.
