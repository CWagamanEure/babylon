# Audit 04 — Market-neutralization & beta  (agent: 04_neutralization_beta)

## Summary
I traced `beta=1.245`, `build_basket`, `_basket_ret_bps`, and every call site of the
neutralizer through `skill.py`, `followable.py`, `selection.py`, `main.py`, `measure.py`,
and the three offline scripts. **Headline result: no path by which the neutralizer can
produce a false GO.** The GO/NO-GO gate is the DIRECTIONAL top−pool-mean series
(`measure.py:5`, explicit), live selection is built with `basket=None`
(`main.py:109`), and the deployed book is directional (no basket hedge, v3.1). So every
beta defect below is **bounded to the offline neutralized diagnostic / reporting** — it
cannot fabricate edge at the gate. The most material issue is that `beta=1.245` has **no
derivation anywhere in the repo** (no estimator, no comment, no notebook) — it is an
unverifiable magic constant, plausibly an in-sample OLS fit, but I cannot confirm its
out-of-sample-ness from this codebase. The index-look-ahead hypothesis is **refuted**:
`_basket_ret_bps` is causal and telescopes to the in-window basket return.

## Findings

### F1 — `beta=1.245` provenance is undocumented and unverifiable in-repo  [MED]
- **Where:** `scripts/edge_sweep.py:100`, `scripts/convergence_his.py:74`,
  `scripts/convergence_test.py:110`, `src/babylon/follow/main.py:60` (all hardcode 1.245);
  `git log -S 1.245` → first appears in `73b1f0c` with no estimator.
- **Blast radius:** offline-estimate / reporting-only. (NOT the gate — see Summary.)
- **Failure scenario:** A precise 3-sig-fig value almost certainly came from an OLS
  regression of per-RT returns on basket returns. If that fit was run on the **same
  Feb–Jun data** used to print the neutralized convergence number
  (`convergence_his.py:128` "His ref: median +10.7 … neutralized"), the neutralizer is
  fit in-sample: the residual `dir·(coin_ret − 1.245·basket_ret)` is then the minimized
  residual on its own training set, so the neutralized edge is over-fit and not a
  forward-honest number. There is **no code in this repo** that estimates beta, and no
  comment stating which window/repo produced 1.245, so an auditor cannot tell whether it
  is frozen-OOS or in-sample. It is also a **single static beta** — never re-estimated
  per transition — so even if it were OOS once, it is stale for later transitions.
- **Why it's real (not theoretical):** the constant is the literal CLI default and the
  locked `ExperimentConfig` value; nothing in the tree derives or validates it. The
  neutralized column of `edge_sweep.py` and the `--neutralize` runs of the convergence
  scripts inherit it directly (`skill.py:156`, `followable.py:80/121`,
  `edge_sweep.py:65`).
- **Confidence:** medium. The *insulation* of the gate is high-confidence; the
  *in-sample-ness* is low-confidence-positive — I cannot prove it because the estimator
  lives outside the repo.
- **Mitigant (why only MED):** the convergence/survivorship diagnosis does **not** depend
  on beta — `--neutralize` is off by default in both convergence scripts
  (`convergence_his.py:75`, `convergence_test.py:111` → `basket=None` → directional), and
  the directional convergence alone establishes "+159 was survivorship." Beta only colors
  the optional neutralized secondary number.
- **Fix sketch:** either (a) check in the beta estimator + the window it was fit on, and
  re-estimate per transition on the TRAIN window only (forward-frozen); or (b) drop the
  neutralized diagnostic entirely and report directional + controls, since the gate
  already does.

### F2 — Single global beta applied to every coin (misspecification)  [MED]
- **Where:** `skill.py:156`, `followable.py:80` & `:121`, `edge_sweep.py:65` — one scalar
  `beta` multiplies `_basket_ret_bps` for every RT regardless of coin.
- **Blast radius:** offline-estimate / reporting-only.
- **Failure scenario:** a thin alt whose true loading on the equal-weight basket is ~2.5
  gets only 1.245× subtracted → its residual **retains positive beta** (looks like alpha
  in an up-alt regime); a near-major whose true loading is ~0.4 gets 1.245× subtracted →
  the residual is **over-hedged** (negative synthetic beta injected). Because selection
  then ranks on this residual (in any neutralized sweep), it preferentially elevates
  high-true-beta wallets in an up regime — i.e. the neutralizer leaks exactly the beta it
  claims to remove. The docs already concede neutralized alpha is "thin/fragile"
  (`LIVE_FOLLOW.md:199`); a per-coin-beta mis-spec is a concrete mechanism for that
  fragility being partly an artifact.
- **Why it's real:** there is no per-coin or per-cluster beta anywhere (`grep` confirms a
  single scalar). The basket is one equal-weight index; coins differ widely in loading.
- **Confidence:** high that it's a misspecification; medium on magnitude (needs the
  neutralized-vs-directional sweep numbers to size — see F3-adjacent hypothesis 5, which I
  could not run under the RAM rules).
- **Fix sketch:** estimate per-coin (or per-liquidity-bucket) beta on the train window, or
  abandon neutralization for the gate (already done) and label the neutralized series
  "single-beta approximation, diagnostic only."

### F3 — `build_basket` is equal-weight over ALL priceable coins, not a "liquid" subset  [LOW-MED]
- **Where:** `skill.py:166` (`build_basket`) called with the **full** coin set in every
  caller: `edge_sweep.py:111` `build_basket(dir, sorted(coins))`,
  `convergence_his.py:84` `sorted(priceable)`, `convergence_test.py:117` `sorted(coins)`.
  There are 191 candle files (`data/follow/candles/`), and no liquidity screen runs before
  `build_basket`.
- **Blast radius:** offline-estimate / reporting-only.
- **Failure scenario (two parts):**
  1. **Mislabel + noise:** the docstrings call it the "liquid-alt basket" / "liquid coins"
     (`skill.py:6,167`; `followable.py` header), but the basket is *every coin with a
     candle file*, equal-weighted. Thin alts with noisy hourly closes get the same weight
     as deep names, so the neutralizer subtracts a noisier, lower-quality market proxy than
     advertised — adding variance (and any systematic small-alt drift) to the residual.
  2. **Membership = "has a candle file" → survivorship flavor:** inclusion is decided by
     whether `candles_dir/{coin}.parquet` exists. If candles were fetched only for coins
     extant at analysis time, coins that delisted earlier in Feb–Jun are absent from the
     basket for the whole span, biasing the index toward survivors. (The listing-event
     handling at `skill.py:184-192` correctly NaNs a coin *before* its first candle, so the
     *late-listing* direction is handled; the *delisting / never-fetched* direction is
     not — a delisted coin that still has a truncated candle file gets `_ffill`'d flat →
     0-returns post-delist, a smaller dilution bias.)
- **Why it's real:** call sites pass the full set; no ranking/threshold exists. I did not
  enumerate which coins delisted (would need the monthly fills, which are RAM-banned), so
  part 2 is confidence-low.
- **Confidence:** high on the mislabel/equal-weight-all fact; low on the delisting
  magnitude.
- **Fix sketch:** apply an explicit causal liquidity screen (train-window notional) to
  basket membership, or rename to "equal-weight all-priceable-alt index" and note the
  candle-file-existence selection in the caveat.

### F4 — `config.beta=1.245` is pre-registered/locked but inert in the live system  [LOW / transparency]
- **Where:** `main.py:60` locks `beta=1.245` into `ExperimentConfig`; `experiment.py:47`
  comments "diagnostic neutralization ratio (gate is directional)"; but `main.py:109`
  builds `SelectionAdapter(... )` with **no `basket=` argument** → `basket=None`
  (`selection.py:29,35`) → `followable_returns(basket=None …)` skips the beta term
  entirely (`followable.py:120`). So `beta` flows into the run_id/manifest hash and the
  pre-registration but has **zero effect** on selection, the gate, or the book.
- **Blast radius:** reporting-only (good for safety: confirms no live neutralization
  leak). The risk is interpretive: an auditor reading `locked_config` would believe
  selection is neutralized at 1.245 when it is not.
- **Failure scenario:** none operationally — this is the *reason* beta can't fabricate a GO.
  Flagged so the pre-registration isn't read as committing to a neutralized selection it
  never performs.
- **Confidence:** high.
- **Fix sketch:** either wire the basket into `SelectionAdapter` if neutralized selection
  was intended, or drop `beta` from the locked config (or comment it "unused; directional
  selection") so the registry reflects reality.

### F5 — `skill.wallet_skill` neutralizes a wallet-fill return against an unlagged, hour-stale basket point  [LOW]
- **Where:** `skill.py:154-156` — `neut = p.raw_bps` (wallet's own `entry_px/exit_px`,
  sub-second) minus `beta·_basket_ret_bps(basket, p.entry_t, p.exit_t)` (basket read at the
  **last fully-closed hourly candle before entry_t**, up to ~2h stale, and with **no lag**).
- **Blast radius:** offline-estimate / reporting-only, and only for the non-followable
  `skill.py` path (the headline uses `followable.py`, which aligns coin and basket at the
  same `t+lag` causal candle — that path is clean, `followable.py:74-81`).
- **Failure scenario:** the coin leg and the basket leg are sampled at **different clocks**
  (exact fill time vs last-closed-hour), so the subtraction mixes a precise return with a
  coarse, lagged market move → a timing-mismatch residual that is neither the wallet's true
  beta-adjusted return nor a follower's. Sign-neutral in expectation but adds residual
  variance and a small bias around volatile hour-boundaries.
- **Why it's real:** the two legs literally use different time arguments on the same line.
- **Confidence:** high that the mismatch exists; low that it moves any headline (this path
  isn't the reported one).
- **Fix sketch:** if `wallet_skill` is still reported, price its coin leg at the same
  candle as the basket (or drop it in favor of `followable_skill`).

## Cleared (checked, no defect)

- **Index look-ahead — REFUTED.** `_basket_ret_bps` (`skill.py:196-203`) reads
  `index[i1]/index[i0]` where both `i0,i1` are the **last fully-closed hourly point** at
  `t0-3.6e6` / `t1-3.6e6` (same `-_CANDLE_MS` rule as `_close_at`). Because `index` is a
  `cumprod`, that ratio **telescopes to the product of basket returns strictly inside
  [entry, exit]** — it does NOT see the rest of the month. The "same-month index peeks at
  future" hypothesis does not hold; the neutralizer is causal and uses only the in-window
  basket return. Coin and basket legs are read at the *same* `t+lag` candle in
  `followable.py` and `edge_sweep.py:62-65`, so they're consistently aligned.
- **Listing-event handling is correct** (`skill.py:184-192`): a not-yet-listed coin is
  NaN'd (excluded from the equal-weight average) until its first candle, so it can't
  dilute the basket with phantom flat returns — the documented under-neutralization-across-
  listings guard is genuinely present.
- **Direction-signed hedge accounting is correct:** the basket term is
  `dir·beta·basket_ret`, so a short RT (dir=−1) is hedged by adding back beta·basket — the
  right sign (`skill.py:156`, `followable.py:80/121`).
- **No live neutralization mismatch (hypothesis 6):** selection (`basket=None`), the gate
  (`measure.py:5` directional), and the deployed book (v3.1 no-hedge) are all directional
  and mutually consistent. The deployed edge is measured the way it is selected.

## What I could not rule out (RAM-bounded, static only)
- The actual in-sample-ness of 1.245 (needs the external estimator / the fit window).
- The numerical size of the neutralized-vs-directional divergence and the lag at which
  neutralized flips sign (hypothesis 5) — requires running `edge_sweep.py`, which builds a
  191-coin basket and loads per-wallet fills; not run under the resource rules. The
  divergence is a **diagnostic** divergence only (gate is directional), so even a large
  flip does not move GO/NO-GO.
- Whether any coin in Feb–Jun delisted and is silently absent from the candle set (F3
  part 2) — would need the banned monthly fills to enumerate.
