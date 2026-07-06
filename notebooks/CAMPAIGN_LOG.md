# Informed-Wallet Campaign — Complete Methods Log

Every approach tried, the exact steps taken, the assumptions made, and what happened.
Period: 2026-06-22 → 2026-07-03. Data: full Hyperliquid fills tape, Aug 2025 – Jun 2026.
Companion documents: `audit/edge3/PREREG_WALLET_SCREEN.md` (the pre-registration with all
amendments), `audit/edge3/PIPELINE_AUDIT*.md` (7 audit rounds), `notebooks/informed_wallets_report.ipynb`.

---

## Phase 0 — The inherited edge, and its death (context)

**What existed before:** a deployed live experiment harvesting a claimed +24–31bp/entry edge
from copying wallet entries on alt-perps at a 6h horizon.

**Steps taken:** an adversarial audit swarm re-derived the edge from scratch; a decisive
re-measurement re-priced every entry with post-fill pricing (entry = close of the first 5m bar
strictly AFTER the fill, never the bar containing it).

**Assumption that failed:** that pricing an entry within its own hourly candle was harmless.
It wasn't — the fill's own print (and the pre-fill portion of the candle) leaked the leader's
information into the "market" price. The entire edge was this artifact.

**Result:** edge dead; live premise falsified; the post-fill pricing rule became law for
everything after. **Lesson institutionalized:** any benchmark that can see price action from
at-or-before the decision moment manufactures skill.

---

## Phase 1 — Data acquisition

**Steps:**
1. Backfilled `s3://hl-mainnet-node-data/node_fills_by_block/hourly` (requester-pays), 11
   months (Aug 2025 – Jun 2026), ~50M+ fills/month, both counterparties per fill.
2. Hardened driver: double download pass, gzip integrity test + corrupt purge, completeness
   count vs expected hours logged BEFORE conversion, raw deleted only after parquet row-count
   sanity + bars/stats derived.
3. Converted to monthly parquets (duckdb), derived per-month: 5-minute bars per coin (last
   trade price per bar, trade-id tiebreaker for determinism) and per-wallet activity stats.
4. Storage crises (233GB disk at 100%, twice) handled by offloading verified parquets to the
   droplet (`/root/parquet_cold/`, byte-size verified before local delete) and pulling back
   one month at a time during extraction.
5. Checked archive depth for more history: **none exists** — the archive begins 2025-07-27.
   Forward accrual (July 2026+, incremental daily pull) is the only source of virgin data.

**Assumptions:** the tape is complete per its own hour-file inventory (verified); bars built
from candidate fills are adequate prices (later challenged — see self-pricing, R7-7);
delisted coins simply stop having bars (later flagged as scoring survivorship, R7-8).

---

## Phase 2 — The screen and its pre-registration

**Design (user's spec, from a prior attempt in another repo):** activity band 150–20,000
taker orders, ≥25 active days, 0.5–15 orders/day, ≥$500 mean order size; reconstruct
positions; rank by markout PnL; test out-of-sample.

**Steps:**
1. Wrote `scratch_conv/mlscreen2.py` — the registered pipeline: pick (activity band on train
   months) → extract (candidate fills, both sides, sign conventions) → markout (9 horizons:
   1,2,4,8,12,24,48,72,168h) → daily (full position + funding + follower simulation) →
   look-markout / analyze (the two registered looks) → walkforward.
2. Sealed test window: Apr–Jun 2026, read exactly ONCE by the registered look. Enforced in
   code: completeness gates (`_require_complete`), provenance manifests (`_require_fresh`),
   ordering guards (walkforward refuses to run before the look's manifest exists).
3. Entry events defined as position-INCREASING taker fills (opening component only for
   reversals); zhash fills (TWAP slices, liquidations) excluded from scored entries but kept
   in position reconstruction (amendment v1.6).
4. Every markout: post-fill next-bar pricing, ≤30min gap or skip.
5. Decision rules declared BEFORE looking: markout cell (roster > 97.5th placebo percentile),
   follower cell (bootstrap CI, placebo p95, sign-robustness), walk-forward (≥4/5 folds and
   pooled z > 1.64).

**Assumptions:** 24h is a sensible primary horizon (chosen a priori); per-wallet equal-weight
mean bps is the right roster statistic (later understood to be implicitly fill-weighted across
orders); dollar-PnL ranking finds skill (falsified at the very end — it finds book size).

---

## Phase 3 — Filters: tried, kept, killed

Method for ALL filter tests after the maker episode: **decile-matched population
certification** — match excluded vs kept wallets on rank-window PnL deciles, compare
next-month outcomes. (The user's methodological contribution; adopted as law.)

| filter | steps | assumption | result |
|---|---|---|---|
| Activity band | applied at pick | mechanics: evidence quantity | KEPT (470k → ~23k) |
| Maker-exit cap ≤30% (follower side) | daily reconstruction flag | copyability: resting exits can't be mirrored | KEPT |
| Median hold ≥1h | episode durations, flat-to-flat | copy latency physics | KEPT (cut 6% of field, 1 roster seat) |
| zhash exclusion from entries | carried zhash col through extract | TWAP slices/liquidations aren't decisions | KEPT (v1.6) |
| Maker-share exclusion (≤25%, ≤10%, ≤5%) | roster audition, then population certification, then whole-cohort test | "makers are uncopyable/uninformed" | **KILLED — INVERTED**: maker-heavy wallets transfer BETTER (monotone bands, +10.6bp cohort at ≥80%); became H4 |
| Effective-bets floors (episode HHI, coin-day HHI) | episode reconstruction, HHI over PnL contributions | concentration = luck | **KILLED**: crash-shorter had 156 "episodes" = 1 thesis; N_eff measures estimate concentration, not repeated informedness |
| Win-breadth floors (≥3 winning coins, ≥2 winning months) | monthly/coin PnL cells | breadth = evidence | weak/mixed; retained only inside signal B |
| Fills ceiling ≤50k | fills-per-order analysis | huge fill counts = execution desks | **KILLED**: they were whales sweeping books (fpo = size signature); fixed properly by decision-counting |
| Coin-count / activity-uniformity bot detectors | proposed only | bots are bad | **WITHDRAWN**: transfer is the judge, not species; bots that work are ideal copy targets |

**The principle that emerged:** filters fix *mechanics* (latency, observability, evidence
counting); statistics fix *luck*. Every filter that tried to remove bad luck ex-ante failed
population certification.

---

## Phase 4 — Rankings and signals: the tournament roster

All exploratory tests: rank on trailing window, score next month, 50-wallet roster,
per-wallet mean bps, vs 1000 random-roster placebos (later + activity-matched null).

| signal | construction | assumption | outcome |
|---|---|---|---|
| A — raw markout $PnL | sum of per-entry markout dollars, trailing window | dollars = skill | pooled z ≈ +0.4; **FAILED registered test**; ~0.0 on virgin early months. Dollars measure book size × luck |
| B — win floors | A + ≥2 winning months | consistency floor helps | +0.17 — no help |
| C — win-breadth rank | count of winning coins/months | breadth = skill | −0.18 — dead (counts ignore magnitude) |
| D — maker-cap | A + maker ≤25% | see filter table | refuted with the filter |
| E — shrinkage | posterior mean: field + w·(wallet − field), w from signal/noise variance decomposition | luck shrinks toward mean | +0.33 ≈ baseline; right theory, crude prior |
| E2 — lower confidence bound | mean − 1.645·σ/√n (fixed σ=200, fill counts) | precision-first ranking | **−1.17, inverted**: fixed-σ + fill-counted n = a broken t; selected steady-small-edge wallets crushed in trends |
| F — ex-majors selection | rank by trailing NON-major (BTC/ETH/SOL/HYPE excluded) markout $PnL | alt records are idiosyncratic → legible; majors PnL is shared regime → selection-blind | **10/10 folds positive** (3 exploratory + 5 registered + 2 virgin), pooled ~+1.0 after 3 artifact corrections (its own +1.81 was half boundary-leak + winsor + missing null). Cross-venue asymmetry: alt skill predicts majors performance (+1.10), reverse predicts nothing. SURVIVING CANDIDATE |
| G — full-position $PnL | rank by trailing daily reconstructed PnL (all coins, funding-aware) | exits matter; full positions = true edge | raw-$ version didn't replicate on virgin months |
| G2 — full-position Sharpe | mean/std of daily PnL | risk-adjusted better | dead on markout basis |
| G3 — full-position return-on-flow | PnL / scored turnover | size-free efficiency | 7/9 folds positive (~+1.2–2.3 by basis), roster overlap with F = 0/50 — independent population (tiny alt specialists). SECOND CANDIDATE, with a declared denominator-artifact caveat |
| Crowd-relative (excess mean, hit-rate vs crowd) | leave-one-out (coin, day, side) cells | de-noise by peer comparison | previews failed (+0.48/+0.23) AND had a self-crowding bug (leave-one-ENTRY-out) — unreliable in both directions; proper spec (H6) deferred |
| Drift-neutralized (DGTW) | subtract coin-month drift per entry | remove coin trend | didn't rescue majors (+0.17); mildly helped ex-majors (+1.22) |
| Majors-timing T1/T2/T3 | benchmark vs coin's own DAILY counterfactual; T2 = two-sided min(long, short) | own-coin benchmark + two-sidedness = regime-proof | **+3.86, 9/9 folds — then KILLED**: the daily counterfactual averaged windows starting BEFORE the entry → post-move contrarians mechanically positive on both sides. Kill test (raw markout scoring): +0.64. Pitfall #16 |
| H — "the badge" v1 | per-wallet t on month-demeaned, ±500-winsorized, coin-day-clustered markouts; BH-FDR | positions ≈ independent; clip = robustness; pooled demeaning suffices | **631 "certified" wallets, transfer +2.74 8/8 — then DEMOLISHED by round-7 audit** (below) |
| H — badge v2 | raw outcomes, per-coin demeaning, week-block FLIP-NULL (dependence-preserving), empirical FDR, declared stops | every choice leans AGAINST the hypothesis | **zero nameable individuals** (empFDR floor 0.26); but t>4: 57 vs 15 expected, negative side at null → ≈40 real informed wallets exist; basket transfer raw ~+1.0σ; stops don't rescue tails. FINAL FORM |

---

## Phase 5 — The existence question (the user's reframing)

1. **Monthly median-sign test:** per month, each wallet above/below the field median; binomial
   on months-above; BH-FDR. Result: 84 perfect records vs 84.5 expected — *exactly* chance.
   **Flaw (user caught it):** caps every wallet at 11 bits of evidence; cannot see the
   10k-trade modest-edge trader. Conclusion narrowed to "no strong month-scale consistency."
2. **Trade-level t (badge v1):** the user's "effective positions" and "evidence ∝ trade count"
   demands. Found 631 — then round 7 found the three artifact stacks.
3. **Badge v2 (flip-null):** the null is each wallet's OWN record with directions randomized
   per week-block — carries the full dependence structure, so no independence assumption at
   all. THE definitive instrument. Result above.

---

## Phase 6 — The registered verdict (sealed Apr–Jun 2026, read once)

- Markout cell: roster +24.1bp/entry @24h vs placebo median −17.9 → 84.5th pct (bar 97.5). FAIL.
- Follower cell: copier Sharpe −0.03; bootstrap 5th pct −3.70; placebo pct 81.7%; reverses
  ex-best-month. FAIL. The leaders' OWN test-quarter PnL was negative.
- Walk-forward: 3/5 folds, pooled z +0.37; June −90bp/entry. FAIL.
- Declared tournament: no signal cleared 1.64; F alone positive in all 5 folds.

**The paradox this created — and its resolution:** how could ~40 real informed wallets exist
while dollar-ranked rosters fail? Because dollar PnL ranks by book size × luck, not
signal-to-noise. The registered screen tested the user's boss's original construction —
honestly, and it is dead. The surviving objects were found with different indices.

---

## Phase 7 — Audits (the actual engine of the campaign)

Seven adversarial rounds, ~120 confirmed findings total. The recurring killers:
1. **D1 month-boundary leaks** — exits crossing into the score month leak its prices into
   ranking. Found in the registered pipeline (fixed), then AGAIN in venue_split (F's +1.81 →
   +1.01), then AGAIN in badge_transfer (survived unchanged, the only one).
2. **Backward-visible benchmarks** — majors-timing counterfactual (killed the +3.86).
3. **Winsorization asymmetries** — the ±500 clip manufacturing transfer (badge v1 kill test:
   +2.74 → +0.42 raw).
4. **Dependence-blind inference** — iid assumptions on correlated positions (631 → 0).
5. **Placebo confounds** — activity persistence (fixed via second null), size (fixed via
   bps/equal-weight), self-crowding (killed the crowd previews).
6. **Deploy bugs found live** — crash-looping manifest assert, a 14-day time-bomb reroll that
   would have silently swapped sizing to the falsified signal's Kelly weights.

**Mandatory instruments now (pitfalls #16–17):** measurable-at-entry benchmarks only;
raw-outcome kill test before believing any transfer; dependence-preserving nulls (flip-null)
for any per-wallet significance claim.

---

## Final state (2026-07-03)

- **Dead, with receipts:** generic wallet-selection (rank by PnL, copy top-N) — registered
  FAIL + virgin-month zero. Every performance-based filter. Individual-wallet certification
  at 11 months of data.
- **Alive, modest, artifact-hardened:** the alt-identifiability thesis via two disjoint
  cohorts — F (ex-majors dollar leaders, 10/10 folds) and the badge-v2 t>4 basket (57 wallets,
  ~74% expected real, raw cohort transfer ~+1σ); G3 as a caveated third.
- **Proven as fact:** ≈40 genuinely informed traders exist among 22k eligible (t>4 excess
  with negative side at null, flip-null-proof); the field is anti-informed (−14bp/entry);
  majors skill is unidentifiable from position data at daily granularity (4 independent
  instruments agree); copyability ≠ identifiability.
- **Infrastructure:** audited registered pipeline; `--selection fixed` paper-harvest mode
  (crash-loop + reroll fixes tested; droplet service STOPPED pending basket decision);
  July 2026 incremental collection live (`scratch_conv/pull_july.sh`).
- **Next adjudication:** July data through the frozen pipeline — the basket, F, and the
  H4 state-transition + H6 crowd-certification specs, all declared before the data existed.
