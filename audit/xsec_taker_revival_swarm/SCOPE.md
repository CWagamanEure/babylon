# TAKER-REVIVAL SWARM (2026-07-11): can the TAKER leg be made alive? Where is signal hidden in an average? + focused quant-finance research

GOAL: the taker leg (certain fill, KNOWN cost, NO fill-model risk) has been declared dead repeatedly. If it can be made net-positive
OOS, it MOOTS the entire maker-fill gate the whole line is stuck on — the highest-value outcome available. This swarm's job: (1) hunt for
where the taker signal is being AVERAGED AWAY, (2) STEELMAN the taker (adversarially argue it's alive, find the config), (3) bring focused
QUANT-FINANCE research (cost-aware portfolio construction, alpha-decay/horizon theory, execution microstructure) to bear on the cost bind.

## WHY THE TAKER DIES (the exact bind — don't re-derive, ATTACK it)
Taker net = gross_per_crossing − (fee×turnover + spread×turnover). The measured facts:
- **Cost:** impact half-spread median **3.25 bp/side** → taker round-trip ≈ **9-10 bp**; fees: top-tier **2.4 bp/side**, base **4.5 bp/side**.
- **Turnover:** the signal turns over **~1.3×/rebalance even WITH the 10/15 hold-band** (fast alpha half-life ~0.5-1.3h → names cycle out of
  the decile faster than hysteresis holds them). Fee×turnover ALONE eats ~84% of gross at the concentrated extreme.
- **Gross:** decile long-short ≈ +8 bp/crossing (reb4), ≈ +2 bp/hr. Verdicts: Result-8 alt-breadth ~10× sub-cost; `xsec_taker_book.py`
  PRIMARY (decile/reb4/top-tier 2.4) = net **−1.73 bp/hr, CI[−4.33,+0.77], 1/4 folds** (base fee 4.5 → −3.12 excl 0); concentration audit =
  even a **ZERO-spread** taker nets only +0.37/hr at 3/7 folds (fee-throttled); Tier-2 fill-sim f=0 (pure taker) column ALL negative.
⇒ To revive the taker you must, OOS + faithfully-costed: **(a) cut TURNOVER hard without killing gross, and/or (b) find a much bigger
gross/crossing from a genuinely-more-informative subset (NOT mechanical concentration — that's tail-magnitude, info-ratio FALLS), and/or
(c) a slower/cheaper ESTIMAND, and/or (d) lower cost (top-tier fee / tight-spread names / spread-timing).**

## DEAD / DON'T RE-PROPOSE (already hardened)
Mechanical concentration (info-ratio falls, netting trap); EMA/Kalman smoothing (signal is FAST — cuts gross faster than turnover);
conviction/notional/vol-weighting the decile (no lift + whale bug); within-sector RV neutralization (probed NEGATIVE); per-token
reliability (doesn't persist); PCA factor-representative (signal is idiosyncratic); the fade-vs-chase gate (~88% collider artifact);
reviving the alt-complex TIMING basket naively (Result 9 died = BTC/ETH rotation-beta contamination — any directional estimand MUST be
alt-clean). The reversal signal is real but taker-untradeable. Long-horizon h=24 cross-section is DEAD (IC ~0).

## THE GENUINELY-UNTESTED TAKER LEVERS (where to focus — extend these)
1. **⭐ COST-AWARE PARTIAL REBALANCING / AIM PORTFOLIO (Gârleanu-Pedersen 2013 "Dynamic Trading with Predictable Returns & Transaction
   Costs"). NEVER TESTED — we've only ever done FULL decile rebalancing.** The optimal policy with predictable alpha + quadratic/linear
   costs is to trade a FRACTION γ toward the target each period: `x_t = (1−γ)·x_{t−1} + γ·aim_t`, where aim tilts toward the current signal
   and γ trades off alpha-tracking vs turnover. Low γ can cut turnover 5-10× at modest alpha slippage — the single most promising taker
   lever from the literature. Build a continuous position vector from the signal, sweep γ, cost turnover-aware, find if any γ makes taker
   net-positive OOS. Cache-testable.
2. **SLOW-SIGNAL SUBSET averaged into the fast churn.** The pooled signal has a fast HL, but a SUBSET (position-BUILDING/accumulation
   trades via startPosition; repeat-conviction wallets; large persistent bets) may carry a slower, stickier, lower-turnover signal that
   survives taker cost. Decompose the signal into persistent vs transient; does the persistent part have taker-viable turnover×gross?
3. **HORIZON × cost frontier done properly.** Is there a hold (reb) that maximizes taker NET (amortize fixed cost over a longer hold) IF a
   slow component exists — or is faster always net-worse for the taker? (Distinct from the maker's reb2 optimum.)
4. **EXECUTION / cost realism.** Is the impact-spread cost model too pessimistic vs achievable execution (participation-rate scheduling,
   spread-timing = trade only when the spread is tight / toxicity low)? Trade only the cheapest-spread liquid names? Top-tier fee tier?
5. **CHEAPER ESTIMAND.** A directional/basket expression is structurally cheaper (one crossing vs 45 per unit exposure) — but must be
   ALT-CLEAN (Result 9 trap). Is there a taker-tradeable directional signal that isn't rotation-beta?

## FOCUSED QUANT-FINANCE RESEARCH (bring the actual literature — cite the framework, then test it here)
Assign research agents to a SPECIFIC area and make it concrete on our data: (i) **cost-aware dynamic portfolio construction** (Gârleanu-
Pedersen aim portfolio; Almgren-Chriss; the "no-trade region" / buffering literature — Leland); (ii) **alpha decay & optimal holding
period** (Grinold-Kahn transfer coefficient; the cost-adjusted IR / breadth "fundamental law"; matching hold to signal half-life to
maximize net-of-cost IR); (iii) **microstructure & execution** (adverse-selection/order-flow toxicity VPIN, spread dynamics, optimal
execution scheduling, maker-taker fee/rebate structure) — is there an execution regime where our taker cost is materially lower?

## THE DATA
Cache `data/derived/xsec_kalman/panel_cache.npz`: `R,Cc` (cell hour-idx 0..7991 + coin 0..44), `s_inf` (V-trail signal ⊥[crowd,mom]),
`hours(7992)`, `panel_month(7992)` (7 folds 202512..202606), `disp(7992)`, `resid_alt(7992,45)` (per-HOUR BTC/ETH-resid return = book PnL,
forward via `S0.fwd_sum` → t+1 entry), `hs_arr(45)` STATIC impact half-spread bp/side, `hs_default`, `n_alt=45`. Per-wallet size/
startPosition + raw pre-residual S need the pipeline (`kalman_swarm_perwallet.py` load ~130s). asset_ctx (DuckDB) = spread/OI/funding/mark
for execution/spread-timing. Book+cost machinery to REUSE: `research/studies/wallet_flow/ideation_tier1_eval.py` (`book()`, turnover-aware
taker cost, phase-avg, per-fold sign, day-block CI — reproduces the frozen baseline EXACTLY) and `xsec_concentrated_book.py` (SCENARIOS).

## GUARDRAILS (CLAUDE.md — over-null AND over-carry, both live here)
- The taker has been over-carried before (a one-fold +0.088 cell, a variance-tightening `*`). ANY "taker is alive" claim MUST survive:
  PHASE-AVERAGE, t+1 entry, TURNOVER-AWARE faithful cost (fee×turnover, not one-flat-fee/crossing — that 3× undercount already faked a
  rescue once), per-fold (month) sign test across all 7 folds, day-block CI, and multiplicity (report the size of the config search). A
  taker positive that only appears in one fold / one cell / under a flat-cost model does NOT count.
- Equally, do NOT over-NULL: report point estimate + CI + break-even fee, not a bare "negative." If a lever cuts turnover enough that the
  taker CI crosses into positive at top-tier fee, that is a real lead even if not yet significant — surface it with its CI.
- DuckDB: `SET memory_limit='1400MB'; SET threads=1`. Verify before claiming. No repo edits — probes in scratchpad. Two envs:
  `.venv/bin/python` (numpy+duckdb) / `/opt/miniconda3/bin/python` (pandas/matplotlib).

## DELIVERABLE (each agent)
Ranked, concrete, testable ideas from your lens with SCOPE tags (hypothesis / construction / test+cost / leakage+overfit / does-it-make-
TAKER-net-positive-OOS / priority), a real cache PROBE of your top idea WITH turnover-aware net + per-fold sign, and a "if I could test ONE
thing" pick. Be honest if the taker stays dead from your angle — an earned negative is a real result. The prize = a faithfully-costed,
cross-fold-robust taker-net-positive config; failing that, the tightest CI + lowest break-even fee you can construct.
