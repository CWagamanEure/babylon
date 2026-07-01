# Audit 08 — Coverage / priceability bias  (agent: 08_coverage_priceability)

## Summary
I examined whether the ~73%-priceable drop, and the coin-set used for ranking vs pricing vs
live trading, can corrupt the edge estimate or the GO/NO-GO gate. **The core coverage question
(#9) holds up for the gated/directional path**: the offline edge is measured on exactly the
non-major, priceable alt set that the live system actually trades, and selected-vs-field are
always compared on a matched priceable coin set, so the unpriceable tail is excluded
symmetrically — it cannot fabricate a false GO. The defects I did find are all **selection-power
/ offline-estimate** in blast radius, not gate-false-GO: (F1) the wallet-eligibility gate ranks
on a *superset* coin set (offline notional includes `@`/`#`/spot; live raw-activity is
coin-unfiltered) that the priceable measurement set does not match; (F2) the live runner takes
unvalidated exposure in any universe coin whose candles failed to fetch; (F3) the two offline
neutralization baskets disagree on whether majors are included. Top severity: MED.

## Findings

### F1 — Wallet-eligibility gate ranks on a SUPERSET coin set vs the priceable measurement set  [MED]
- **Where:**
  - Live: `src/babylon/follow/selection.py:65-72` (`activity_fn`) — counts `df.height` with **no
    coin filter**; `src/babylon/follow/fills_source.py:90-94` (`RestFillsProvider.__call__`) returns
    *all* of a wallet's fills (spot, majors, `@`-index, everything) with no universe filter. The
    deployed gate is `activity_by_wallet[w] >= min_positions` (scheduler.py:71-72, min_positions=20
    from `locked_config`, main.py:61).
  - Offline: `other_repo_notes/README.txt:4-8` — `past_univ`/`universe_k.json` ranks wallets by
    `sum(notional)` over coins excluding only majors and `':'` — i.e. **including** `@N` spot-index
    and `#` builder notional that is never priceable (alt_universe.txt excludes `:`,`/`,`@`,`#`).
- **Blast radius:** selection-power (population/representativeness), NOT gate-false-GO.
- **Failure scenario:** A wallet whose fills are dominated by `@N` spot-index or majors volume
  has high raw activity / high cumulative notional → it clears the eligibility gate, even though
  its activity in the *traded* (priceable alt) universe is thin. With only `len(r) >= 2` priceable
  returns required to compute a Sortino (scheduler.py:72), such a wallet can be ranked and selected
  on a 2-round-trip Sortino — pure noise. The eligibility gate therefore does not guarantee the
  selected wallet is active in the universe we mirror; it widens the pool with wallets whose skill
  we can barely estimate.
- **Why it's real (not theoretical):** `returns_fn` (selection.py:56-63) restricts to
  `universe ∩ lookups`, but `activity_fn` (the gate) does not — they are computed from the same
  unfiltered `df`. The offline validation that produced the +15–20 bp claim used a *different*
  eligibility rule (`len(tr) >= 2` priceable RTs in edge_sweep.py:144-145; `tr_stat>=2` priceable in
  convergence_his.py:108) with no raw-activity gate, so the live operating point's eligibility was
  not the one the headline number was measured under. Commit fe44463's own note argues the
  raw-activity min "has no material effect" because ranking is still by priceable-coin Sortino — that
  bounds the damage to pool-width/noise, but it does not make the gate coin-consistent.
- **Confidence:** high (the code paths are explicit). Materiality is medium — bounded because the
  *final ranking* is still on priceable-coin Sortino with a ≥2-priceable-RT floor.
- **Fix sketch:** Make `activity_fn` count fills restricted to `universe` (the traded coin set), so
  eligibility measures activity in coins we can actually price and mirror; or raise the priceable-RT
  floor above 2 so thin wallets can't be selected on noise.

### F2 — Live runner takes unvalidated exposure in coins selection could not price  [MED]
- **Where:** `src/babylon/follow/runner.py:173` (`for coin in self._universe`) trades every universe
  coin; `src/babylon/follow/candles_source.py:37-44` (`fetch_lookups`) silently **drops** any coin
  that errors or returns no candles; `src/babylon/follow/selection.py:60-63` then skips that coin in
  scoring (`c not in lookups`, via followable_returns followable.py:105).
- **Blast radius:** unvalidated-exposure / selection-power, capped by `max_coin_frac` (0.08).
- **Failure scenario:** During a roll, HL returns no candles for coin X (transient error, rate-limit,
  or a freshly listed coin). `fetch_lookups` drops X from `lookups`, so X contributes nothing to any
  wallet's selection skill — but X stays in `self._universe`, the L2 feed is subscribed (runner.py:
  368-369), and `consensus_sign(X)` is computed from the wallet's *live position* regardless of
  candles. The follower therefore mirrors X live with up to `max_coin_frac` of budget, on a coin whose
  followable edge was never measured in the train window.
- **Why it's real:** the runner's trade loop is gated on the live L2 book + consensus, never on
  whether selection priced the coin; `universe` and `lookups` are independently sourced and can diverge.
  In the offline backtest they cannot diverge (`coins = set(lookups)`, edge_sweep.py:110), so this is a
  live-only gap that the offline validation cannot surface.
- **Confidence:** medium — requires a candle-fetch miss for a coin a roster wallet actually holds;
  frequency depends on HL reliability, which I could not measure statically.
- **Fix sketch:** intersect the runner's traded universe with the coins that actually priced this roll
  (`self._universe & set(lookups)`), or skip entries in coins absent from the current `lookups`.

### F3 — Offline neutralization baskets disagree on majors (estimator inconsistency)  [LOW]
- **Where:** `scripts/edge_sweep.py:110-111` builds `build_basket(candles_dir, sorted(set(lookups)))`
  — `set(lookups)` includes the BTC/ETH/SOL/HYPE candle files, so majors enter the "alt" basket; vs
  `scripts/convergence_his.py:83-84` builds `build_basket(sorted(priceable))` where
  `priceable = set(lookups) & his_coins` and `his_coins` is non-major (README.txt:13), so majors are
  excluded.
- **Blast radius:** offline-estimate (diagnostic only — the gated/live measure is DIRECTIONAL,
  `basket=None`: SelectionAdapter is built without a basket in main.py:109, and measure.py gates
  top−pool-mean directional).
- **Failure scenario:** the two offline neutralized numbers are not comparable — edge_sweep's
  "neutralized" edge subtracts a market index contaminated with the four majors, while the
  README headline (+10.7 bp, from convergence/clean_persistence) uses a non-major basket. A reader
  comparing the two would mis-attribute the difference to method rather than basket composition.
- **Why it's real:** `build_basket` (skill.py:166-193) neutralizes against whatever coin list it is
  handed; the two scripts hand it different lists. (Including majors as a market factor is defensible
  for de-marketing; the defect is the *inconsistency*, not necessarily either choice.)
- **Confidence:** high that the inconsistency exists; low that it changes any GO/NO-GO conclusion
  (the gate never uses the basket).
- **Fix sketch:** pin one basket definition (non-major alt index, or explicit market index) and use it
  in both scripts; document which.

## Clean bill — what holds up (and what I checked)

- **#9 coverage is correctly controlled for the gate.** Live trades exactly the 187 non-major candle
  coins: `comm` of `data/follow/candles/*.parquet` stems vs `data/follow/alt_universe.txt` shows the
  only difference is {BTC, ETH, SOL, HYPE}, and **every** alt_universe coin has a candle file. The
  unpriceable tail (`@`/`#`/`:`/spot) is excluded from live trading *and* from offline measurement, so
  the offline edge population equals the live exposure population. Selected and field are computed over
  the same priceable set in both estimators (followable.py:64-65/105; edge_sweep.py:148-150;
  convergence_his.py:110-114), so the comparison is matched — the coverage drop is common-mode and
  cancels in selected−field and in the gate's paired top−pool-mean (measure.py:94). A coverage bias
  cannot manufacture a positive top−control.
- **No within-coin temporal candle gap.** Bounded probe (ADA, AVNT, 0G, DOGE) shows all candle files
  share an identical grid, n=3529, 2026-02-01 → 2026-06-28 — fully spanning the his Feb→Jun window.
  `_close_at`'s `i<0` / `i>=size` None-skip (followable.py:46-50) therefore only drops the first/last
  ~1h of coverage, symmetrically across wallets; not a material non-random slice.
- **min_hold_ms is a consistent, validated operating point.** The 1h hold filter is applied identically
  in skill.py:152, followable.py:72 & :111, and edge_sweep.py:48, and live threads `config.min_hold_ms`
  (locked 3_600_000, main.py:61) through SelectionAdapter.returns_fn (selection.py:62). Dropping
  sub-hour holds (scalpers) is the deliberate thesis (follower lag collapses HFT edge; followable.py
  docstring:6-9), not an ad-hoc filter — and it is applied to selected and field alike.
- **Majors do not leak into the directional/gated path.** His fills are pre-filtered non-major
  (README.txt:13); convergence_his re-filters to `priceable` (non-major) before reshaping
  (convergence_his.py:40); alt_universe excludes majors; the runner trades alt_universe only. The only
  major contamination is the diagnostic basket (F3).

## Could not rule out
- The realized top/control arrays fed to `measure()`/`decide()` are computed outside my scope files
  (measure.py consumes them as inputs). I reasoned structurally that the paired differencing makes
  coverage common-mode, but I did not trace the realized-return harness end to end. A reviewer of the
  measurement-harness task should confirm top and control are paired on the same priceable RTs.
- F2's real-world frequency (candle-fetch misses on held coins) needs a live/log probe; static review
  only shows the gap exists.
