# XSEC CROSS-SECTIONAL BOOK — FORWARD PAPER PRE-REGISTRATION (frozen 2026-07-10)

**Purpose.** Forward paper-test the ONE quantity no offline analysis of the historical tape can measure: the
**passive-fill rate / adverse selection** of the V-trail cross-sectional alt-selection book. Everything else is
settled offline (see [[babylon-xsec-statarb]] Results 10 + concentrated book): the signal is real, leak-free,
Bonferroni-surviving (IC +0.023, z≈8, 39/45 coins), and the concentrated maker book is a **powered positive**
(pooled decile reb4, pessimistic 50%-adverse-selection: +3.60 bp/hr, day-block CI [+2.54,+4.56], 7/7 folds,
month-block sign p=0.016). The remaining unknown is fill. This prereg freezes the config + metrics + verdict
rules BEFORE any forward data so the forward test is honest.

## FROZEN CONFIG (do not change; changes start a NEW config epoch, old data excluded from that leg's verdict)
- **Signal = V-trail relative reallocation flow, skill-weighted, per alt, per hour.** For each cohort wallet w
  and alt a in the closed hour: `flow_{w,a}` = signed notional reallocation; `q_{w,a} = sign(flow) − mean_over_
  w's-trailing-24h-traded-set(sign(flow))` (size-blind, breadth). Aggregate `S_a = Σ_w W_w · q_{w,a}` where
  `W_w` = frozen train-only shrunk skill weight (`W = max(0,θ)`, θ = g·n/(n+λ)). Rank `S_a` across the active
  alts that hour → the cross-section.
- **Book = DECILE long-short, EQUAL-weight, FULL 45-name PIT universe.** Long top-10% of `S_a`, short bottom-10%,
  no-trade hold band to top/bottom-15% (hysteresis). Do NOT liquidity-stack (a decile of a liquid subset = 1-2
  names = netting trap). Universe frozen at formation (`data/derived/xsec_book/cohort.json`, universe_sha).
- **Rebalance = every 4 hours (reb=4)** — the net-per-hour-optimal harvest horizon from the concentrated book.
- **Cohort + weights FROZEN** as of the export `as_of_hour_ms`; any hour after that is genuine OOS. Monthly
  refresh allowed = re-export (new epoch tag), never retroactive.
- **Neutralization** (offline, for the TARGET only): forward return per alt = BTC/ETH(+LOO-alt-index)-residual
  return over the 4h hold, per the frozen `build_resid` betas. The book is dollar-neutral within alts.

## TWO LEGS (bracket the fill unknown)
- **TAKER leg = PRIMARY forward verdict (certain fill, no fill model needed).** At each 4h rebalance: cross the
  spread to enter/exit the decile changes; cost per name = top-tier taker fee (2.4 bp/side) + the LOGGED live
  impact half-spread at decision time (also report a small-clip cap of ~1 bp/side). Turnover-aware: charge only
  name entries/exits, not the whole book. This is a faithful paper test — nothing is assumed about fills.
- **MAKER leg = SECONDARY (fill measured, not assumed).** Log the intended passive quote (touch bid for longs /
  ask for shorts) at each rebalance + the forward bid/ask/mid path. Offline, estimate fill via "did the market
  trade through the resting price within the hold" (a documented PROXY, not a live fill) → realized fill rate +
  adverse markout. Earn the half-spread on filled orders; unfilled → carry to taker fallback. Report net-per-hr
  vs measured fill rate. This leg REPLACES the offline adverse-selection ASSUMPTION with a forward MEASUREMENT.

## WHAT IS LOGGED (hourly JSONL; PnL computed OFFLINE, never in the follower)
Per closed hour: `hour_ms`, per-alt `S_a` (skill-weighted signal), the active-alt set, and for all 45 alts the
live `bid/ask/mid/impact_bid/impact_ask` at decision time; `cohort_sha`, `universe_sha`, `n_wallets_polled`,
`config_epoch`. NO positions/PnL in the log — the book + both legs' PnL are reconstructed offline from the frozen
rules so the follower cannot bias the result.

## METRICS (all OUT-OF-SAMPLE, forward only)
- **Primary (taker leg):** net bp per HOUR after top-tier-taker cost, turnover-aware. Day-block bootstrap CI +
  **month-block (or ≥3-week-block) sign test** as the cross-independent-unit gate once ≥3 blocks exist.
- **Secondary (maker leg):** measured passive-fill rate; net bp/hr earning the spread on fills + taker fallback
  on misses; adverse markout on fills. Reported with the same block CI.
- **Diagnostics:** realized gross bp/crossing (vs the +8bp/crossing offline decile), turnover, per-alt hit rate,
  book breadth. Compare live gross to the offline expectation as a signal-decay check.

## VERDICT RULES (frozen)
- **Minimum window before ANY verdict: 3 calendar months OR 60 active trading days**, whichever later. No peeking
  verdicts before then (the offline result already establishes existence; forward is purely the fill/decay test).
- **Taker leg GO** = net-per-hr day-block CI-low > 0 AND month-block sign test p < 0.10 over the window AND live
  gross ≥ ~60% of the offline +8bp/crossing (decay check). **Taker NO-GO** = CI-high < 0 (earned forward negative).
  Between = inconclusive, extend window.
- **Maker leg GO** = measured fill rate high enough that net-per-hr CI-low > 0 under the MEASURED (not assumed)
  adverse markout. This is the upside case (+4-6 bp/hr offline central).
- **Capital: NONE.** Paper only. A GO here authorizes at most a follow-up small-size REAL-order fill study
  (the only way to truly measure maker fills), never direct capital deployment off paper.

## PRE-REGISTERED, PHASE-AVERAGED config matrix (added 2026-07-10; magnitudes CORRECTED by the denoise-swarm)
The follower logs the RAW hourly `S_a` unchanged; the offline evaluator (`xsec_book_eval.run`) books a matrix of configs,
each **PHASE-AVERAGED** over all rebalance offsets (deployment can't pick the phase — the denoise-swarm proved the earlier
reb4-phase0 numbers were a ~9× favorable-phase artifact). Frozen α=0.90 level-EMA `m_t=0.90·S_t+0.10·m_{t−1}` is a near-free
denoise TILT (do NOT re-tune α forward = new epoch). Configs & HONEST phase-averaged offline priors:
- **base reb4 (RAW vs DENOISE):** the original book. Maker phase-avg ≈ **+3.2/hr** (NOT the +4.35 phase-0 figure — that was
  inflated). Denoise adds a small ~+0.15/hr (p≈0.10, direction-established, magnitude underpowered) — carry it as a free tilt.
- **⭐ reb2 maker (RAW vs DENOISE) — the swarm's biggest, phase-ROBUST lever:** maker phase-avg **+5.4/hr, 7/7 folds** (maker net
  is monotone-decreasing in reb; reb2 is the maker-optimal horizon). ⚠️ MAKER-ONLY (reb2 taker is negative) and it leans HARDER
  on the passive-fill rate (2× rebalances → more earned-spread) — the forward maker leg is exactly the test of that dependence.
- **taker-hyst reb4 q0.30 — the wider-hold-band TAKER candidate:** regime-gated offline (mid-dispersion 7/7 p=0.016); pooled here
  as the deployable-shape certain-fill floor. Underpowered-positive, forward-only verdict.
- **⭐ CONSENSUS arms (base reb4 + reb2 maker) — the adaptive-filter-swarm win (2026-07-10):** rank the cross-section by
  `S_a · cons_a` where `cons_a = |Σ_w W_w·sign(q_{w,a})| / Σ_w W_w` ∈ [0,1] = the cohort's DIRECTIONAL CONSENSUS on that alt
  (the follower now logs `cons_a` additively). Directional consensus is a real R-driver ORTHOGONAL to breadth: offline, contested
  cells have forward-IC ≈ 0, unanimous cells ≈ +0.050; the consensus-weighted book BEAT fixed α=0.90 on maker_a30 by +0.46bp OOS
  (3/4 folds) and PASSED a matched-DoF random-precision null (P=0.016) — the only R input to do both. ⚠️ SUGGESTIVE not deployable-
  significant offline (maker paired-CI crossed 0 on 7 folds; HURTS the taker leg). Forward A/B is the powered confirmation. Config
  note: adding the logged `cons_a` field is ADDITIVE (S_a and the base book are unchanged) → it does NOT reset the base epoch;
  the consensus ARMS begin their own evaluation window at the first hour the field is present.
This forward A/B is the OOS confirmation the swarms demanded. Report every config × both legs at each checkpoint. Corrected
expectation: the DEPLOYABLE improvement is the **horizon (reb2 maker)** and the **regime-gated taker hysteresis**; the denoise is
a small free tilt, NOT the +27%/+0.7 headline (that was phase-0-selected + tail-amplified — over-carry, corrected).

## EXCLUSIONS / EPOCHS
- Config epoch 1 begins at first live hour after deploy; record the exact start ms. Any change to signal, book,
  universe, cohort, reb, or cost model = a NEW epoch; prior epoch's data excluded from the changed leg's verdict.
  (The RAW/DENOISED A/B is applied offline to the SAME logged raw signal → both share one epoch, not a new one.)
- Warm-up hours (before the 24h trailing buffer + skill state are seeded) EXCLUDED.
- Discovery-magnitude / in-sample weighting EXCLUDED (winner's-curse; the skill weights are TRAIN-only frozen).

## OVER-CARRY / OVER-NULL GUARDS (standing)
- The offline maker central (+4.3 bp/hr) assumes ~100% passive fills; ~half is earned-spread. The forward maker
  leg exists precisely to MEASURE that. Do NOT report the offline maker number as a forward result.
- The taker floor (+1.4 bp/hr small-clip) has a CI that includes 0 offline — the forward taker leg is the powered
  test of whether it's real. Do NOT pre-conclude either way.
- Report live gross-decay honestly: if live gross ≪ offline +8bp/crossing, the signal decayed forward — that is
  the real risk for any historical edge and the forward test's job to catch.

Deploy: `src/babylon/follow/xsec_book_main.py` (hourly poller) + `data/derived/xsec_book/cohort.json` (frozen
cohort+weights+universe) + offline evaluator `research/studies/wallet_flow/xsec_book_eval.py`. Runs on the droplet
alongside the basket follower (shares HL weight budget). See [[babylon-basket-deployment]] for the box/service pattern.
