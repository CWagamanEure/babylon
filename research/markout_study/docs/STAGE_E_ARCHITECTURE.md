# Stage E — The pre-registered confirmatory test (feature → held-out copyable edge)

**Status: PRE-REGISTRATION (frozen before any result is seen). Audited BEFORE build/run.**

This is the single decisive experiment the whole study points at. Everything before it is either a registered
negative (performance-ranking selection — dead) or an inconclusive/underpowered prior (a small 24h directional
lean; the in-sample "edge gate" was non-discriminating and is retracted). Stage E is the ONE properly-powered,
out-of-sample attempt mandated by the anti-ratchet rule (CLAUDE.md): given a genuinely inconclusive prior, build
one powered design and take the verdict — CONFIRM / KILL / INCONCLUSIVE — rather than loop blind instruments.

## The one question
Does selecting wallets by a **pre-registered behavioral trait** (measured on past data) produce a portfolio whose
**future, market-neutralized, cost-aware trades make money** — beyond an activity+notional-matched random baseline?

This is NON-CIRCULAR by construction: the selector is a *behavior* (how they trade), NOT their past 24h edge
(the inflated quantity that made every prior "positive" a winner's curse).

## Frozen choices (no post-hoc changes; no menus; no scans)

**Selector (primary, ONE):** `highvol_entry_propensity` = fraction of a wallet's TRAIN-window entries that land in a
high-vol regime (coin's trailing-24h rolling vol above that coin's *train-window* median — NO full-sample look-ahead,
fixing the Stage-1 caveat). This is the single trait that survived Stage-1 cross-checks (vw+ew, matched control).
**Secondary (declared, reported but not primary):** `add_frac` (position-adding propensity). Reported for context;
the CONFIRM/KILL verdict rides on the primary only.

**Portfolio (pooled, NOT top-K):** all train-qualifying wallets in the **top quartile** of `highvol_entry_propensity`
per coin. Pooling many wallets (hundreds) is the only route to the N needed for power. Train-qualifying = ≥30 train
entries in that coin.

**Split (wallet- AND time-disjoint):**
- TRAIN = months 1–6 (measure the selector only).
- EMBARGO = month 7 (discard entirely — ≥ max-horizon + regime-autocorrelation buffer; defeats crowding/regime leak).
- TEST = months 8–11 (measure edge only).
- Universe **frozen at train time** (no survivorship look-ahead). Wallets inactive in TEST are **excluded**, never
  scored as 0 (excluding shrinks N honestly; zero-filling would fabricate a null).

**Estimand (the number that decides it):** pooled, entry-level, **coin×day-neutralized** 24h vw-markout of the
portfolio's TEST entries, minus the activity+notional-matched random baseline.
- *Neutralization:* subtract each entry's **same-coin, same-UTC-day** dir-signed benchmark (the coin's own avg-entry
  → +24h return that day). Removes the shared daily beta (the σ=316bp→~100–150bp cut that makes the test powered).
  Estimand becomes *intraday entry-timing skill* — the copy-relevant, beta-free quantity. Raw (un-neutralized)
  vw-markout is reported ALONGSIDE for the deployability/CONFIRM hurdle.
- *Horizon:* 24h, fixed (the prior's horizon). NO horizon scan.

**Statistic + uncertainty:** pooled mean neutralized vw-markout (bps); 95% CI via **two-way cluster bootstrap**,
clusters = (wallet) ⊗ (coin-week) — charges honestly for both wallet-repeat and crowding (many wallets, same
coin-week bet = not independent). Baseline = distribution of the same statistic over matched-random portfolios.

**Positive control (MANDATORY — makes a null interpretable):** inject a known +20 bp per-entry edge into a random
portfolio's TEST markouts and confirm the pipeline recovers it (CI excludes 0). Report the achieved **MDE**. Without
MDE ≤ care-about, a null is "inconclusive," not "KILL" (the anti-ratchet condition).

## Pre-registered decision rule (frozen)
- **CONFIRM** iff neutralized CI lower bound > 0 AND the matched-baseline is cleared (one-sided) AND the *raw*
  (deployable, un-neutralized) point estimate ≥ a ~5–10 bp net-of-cost hurdle. (Funding not yet netted → CONFIRM is
  provisional-pending-funding; a CONFIRM triggers the funding + BBO pulls, not immediate deployment.)
- **KILL** iff neutralized CI contains 0 AND achieved MDE ≤ 15 bp (an *adequately powered* null — earns the word).
- **INCONCLUSIVE** iff neutralized CI contains 0 AND MDE > 15 bp → the design is still underpowered; escalate to
  more data (forward months 12–16), do NOT re-slice or re-pick the feature.

## What this test does NOT do (guarding the known failure modes)
- No horizon scan (24h fixed), no feature menu (one primary), no K-sweep (one quartile threshold), no re-selection
  on realized edge (behavioral selector only). Any of these would re-introduce the winner's curse we just proved.
- Does not claim deployability on a CONFIRM alone — funding + real BBO spreads are a separate gate.

## ⛔ POST-AUDIT REVISION — FROZEN v2 (2026-07-04, supersedes the frozen choices above where they conflict)
Three pre-registration audits (power / leak / built-to-fail) ran BEFORE build. Consolidated frozen spec:

**Coin set:** BTC, ETH, SOL, HYPE pooled (primary). **SPX EXCLUDED from the primary verdict** (only ~24
train-qual top-quartile wallets → degenerate, per Stage 1); reported separately, non-binding.

**Train-only recompute (leak fix, MANDATORY):** pool membership (≥30 TRAIN entries), the selector, and any winsor
cap are computed from `b_ts < TRAIN_HI` ONLY — never from the full-sample `markout_stats.parquet` / `winsor_caps`
/ `cohort_forensics` outputs (all full-sample). Build asserts no TEST-window row touches selector/threshold/cap.
Drop TEST entries whose 24h exit is unpriceable (final ~24h of June); baseline drops symmetrically.

**Neutralization (the load-bearing power fix):** PRIMARY = **coin-MONTH** neutralized 24h markout:
`neut_i = dir_i·fwd24(coin,bar_i) − dir_i·[mean over ALL 5-min bars b in that coin-MONTH of fwd24(coin,b)]`.
The benchmark is **PRICE-ONLY** (coin's own forward returns; NO wallet/portfolio entries in it → non-circular,
proven zero first-order bias under no-skill). Coin-MONTH grain (NOT coin-day) removes the coin's drift/beta while
PRESERVING the day-level regime-timing the selector targets (coin-day neutralization deletes exactly the signal
under test and removes <1% variance — audit-rejected). Report RAW (deployable) alongside; coin-DAY-neutralized is
a SECONDARY "intraday-only" diagnostic. Winsorize at a TRAIN-derived p99 (pinned); un-winsorized reported as robustness.

**Selector:** PRIMARY = `highvol_entry_propensity` on TRAIN entries, threshold = coin's TRAIN-window trailing-vol
median (train-only). SECONDARY (declared, reported, non-verdict): idiosyncratic (cross-coin-residualized) high-vol
propensity; `add_frac`.

**Primary statistic (anti-dilution):** the two-way-clustered **rank-slope** of entry-level `neut` on the wallet's
continuous (per-coin-standardized) `highvol_propensity` rank — edge-increases-with-trait, uses all wallets, no
threshold. SECONDARY (deployable) = top-quartile portfolio mean (raw & neut) vs an activity+notional-matched,
**TEST-ACTIVE-conditioned** random baseline (matched on TRAIN n-quintile×vol-quintile). vw primary; ew robustness.

**Uncertainty:** two-way cluster bootstrap, clusters = wallet ⊗ coin-week, **R=5000**, seed frozen, one-sided 2.5%
(report the 95% CI lower bound). Baseline portfolios drawn same-size, run through the SAME two-way bootstrap.

**Two required nulls:** (1) POSITIVE CONTROL — inject a **coin-week-CLUSTERED** +edge (not a per-entry constant) on
a random coin-week subset, confirm recovery under the two-way bootstrap → reports achieved MDE. (2) PLACEBO —
permute selector labels (activity+notional matched), confirm the primary statistic's CI includes 0.

**Decision rule (frozen v2):**
- **CONFIRM** iff primary (coin-month-neut) rank-slope CI lower bound > 0 AND the top-quartile deployable RAW point
  estimate clears the per-coin `COST_BPS` net hurdle (BTC/ETH 8, SOL 10, HYPE 14 bp). (Provisional-pending-funding.)
- **KILL** iff primary CI contains 0 AND achieved MDE ≤ **10 bp** (tightened from 15 → the care-about hurdle, so a
  null actually excludes a deployable edge; 15 was too loose → false-KILL risk).
- **INCONCLUSIVE** iff CI contains 0 AND MDE > 10 bp → escalate to forward months 12–16 EXACTLY ONCE; if still
  MDE > hurdle, register the anti-ratchet terminus "available data cannot resolve this" and stop.

**Survivorship (record with verdict):** ~41–58% of train-qual wallets are TEST-active; exclusion biases toward
CONFIRM. Baseline is test-active-conditioned so it first-order differences out; report cohort-vs-baseline attrition;
if they differ, flag the verdict survivorship-caveated (a CONFIRM read optimistically, a KILL read as conservative).

## Artifacts
`src/stage_e.py` → `out/stage_e_verdict.parquet` (rank-slope + quartile portfolio vs matched baseline, per coin +
pooled, raw & coin-month-neut & coin-day-neut, CI, MDE, placebo, verdict). Ledger Stage E updated with the frozen
verdict on completion (whatever it is — CONFIRM/KILL/INCONCLUSIVE).
