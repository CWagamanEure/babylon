# Tier-2 markout — the edge/informedness measurement (architecture)

> ## v2 RESOLVED (post 3-agent estimand audit, 2026-07-08). These OVERRIDE the body where they conflict.
>
> **R1 — HEADLINE ESTIMATOR = wallet-day-weighted MEAN + weekly-block cluster-robust CI (OVERRIDES spec P15).**
> Median-of-means is a *biased* estimator of the mean under skew (proved: right-skew ⇒ ≈−7 bp bias buries a
> real +8 bp edge; left-skew ⇒ ≈+7 bp inflates noise — bias ≈ skew·σ, ~edge-invariant, exceeds the care-about
> band, flips sign both ways). So the point estimate that makes the call is the **wallet-day-weighted mean**;
> its CI is a **weekly-block cluster bootstrap** (resample whole weeks). `stable_edge`/`trim20` (MoM) are kept
> ONLY as **concordance diagnostics**, never the decision quantity. Positive-control MUST inject a *realistically
> skewed* edge and prove recovery of the headline estimator specifically.
> **R2 — ALL μ COMPUTED IN THE PER-CUTOFF AGGREGATION LAYER under one `t+h ≤ C` filter; NO μ-subtracted column
> is ever stored in the backfill.** The backfill stores only cutoff-independent primitives per episode:
> `raw_markout_h`, and for μ: per-(coin,week,h) `fwd_ret_sum/sumsq/n` built from the price panel. `timing_alpha`
> (both variants) is derived at aggregation time. Fixes the store-once-vs-≤C contradiction AND the straddle-week
> leak (the week containing C uses only minutes with `t+h ≤ C`). Invariant test: straddle-week μ at C == μ
> recomputed on data truncated at C.
> **R3 — REPORT TWO market-adjustments as a PAIR, not one headline.** `timing_alpha_weekly` (subtract per-week
> μ) = intra-week timing FLOOR — it *defines away* regime/week-selection skill, so it is a lower bound, NOT the
> verdict. `timing_alpha_global` (subtract global-≤C μ) = timing + selection. A wallet is a live positive if
> EITHER clears at MDE ≤ care-about; a NULL requires BOTH tight-around-zero (over-null guard).
> **R4 — MARKOUT IS A 1:1 AUGMENTATION of the episode lake, not a joined table.** `(wallet,coin,open_ts)` has
> 19,007 dup keys and even `(opener_block,opener_event_index)` has 1,167 (inherited position whose first fill
> FLIPs → two episodes share the opener fill). So the backfill emits one markout row PER episode row (carrying
> the full identity incl `dir`, `opener_block`, `opener_event_index`), never self-joining episodes. The only
> join is episode→price (ASOF).
> **R5 — EXCLUDE `inherited_basis=true` (58,327 eps, 0.17%)** from the entry-timing cohort — their `open_ts` is
> a synthetic mid-life fill, not an economic entry. Also exclude/flag `entry_bar_ts ≥ close_ts` (sub-cadence
> scalps) and store `entry_lag_s = entry_bar_ts − open_ts`. Label the metric **"initial-entry timing markout"**
> (≠ VWAP/realized edge for scale-in wallets).
> **R6 — ASOF NEEDS A STALENESS BOUND (the *other* artifact direction).** Majors have ~1,000 interior missing
> minutes; an endpoint landing in a gap silently uses a stale price (edge3 family). Require the ASOF match within
> **≤ 90 s** of the target; else NULL that (episode,horizon) and right-censor it. Store `p0_staleness_s`,
> `ph_staleness_s`. This guards Ph AND P0.
> **R7 — POWER/DECISION gate (over-null discipline).** MDE is derived from the SE of the **headline estimator**
> (weighted-mean cluster bootstrap), with α, β, two-sided z, ddof PINNED. `n_active_weeks < 6` ⇒ INCONCLUSIVE.
> Replace the 4-way conjunctive "convincing" AND with a **scored concordance** (how many of {mean>0, most weeks
> positive, ex-best-week>0, bootstrap-LB≥0} agree) reported *beside* point-estimate+CI+MDE. "No edge" is earned
> ONLY when `mde ≤ care-about AND CI-upper < care-about`; everything else with `mde > care-about` is INCONCLUSIVE.
> **R8 — MULTIPLICITY controlled across the WHOLE arc.** Family = all (wallet,coin,horizon) cells at a given
> (cutoff,window). Permutation-null = **label-permutation of the wallet's own entry minutes** (preserves its
> calendar footprint), `perm_p = (1+#{perm≥obs})/(B+1)`, one-sided (skill>0), B stored. Then **BH-FDR across the
> whole family**, store `q_value` + test count. Pin ONE primary horizon (or a pre-registered composite) as THE
> headline; `peak_horizon` is descriptive-only — never report an argmax-horizon edge without a max-stat p.
> **R9 — FIREWALL = MECHANISM, not labels (over-carry).** Do NOT materialize a ready-to-consume ranked list;
> store only raw components + force ranking through an explicitly-named EXPLORATORY function that stamps every
> row `EXPLORATORY_NOT_A_VERDICT`. Register the shadow-ranking via a SEPARATE catalog/path NOT in `db.py`'s
> default `connect()`. Hash the **selection rule** (horizon+aggregation+threshold) into `frozen_config.sha256`,
> not just the estimand knobs. Test: the frozen Gate-A catalog cannot resolve `addr_coin_shadow_ranking`.
> **R10 — TWO distinct named right-censor invariants** + an aggregation-layer test that a panel at cutoff C
> contains ZERO markout endpoints with `t_h > C` (independent of data availability): (a) `t_h ≤ last_ctx_tick`
> (data availability), (b) `t_h ≤ C` (leakage). ASOF will silently return a valid price for `t_h > C` unless (b)
> is explicitly applied per cutoff.
> **R11 — CLEAN (confirmed by audit, keep as-is):** post-fill `entry_bar_ts` (strictly `>` open) + oracle_px +
> per-minute ASOF + per-horizon right-censor precludes the edge3 stale-candle artifact on the FORWARD leg; short
> sign convention and μ-subtraction sign are correct; μ-from-same-oracle-series is not harmful circularity;
> import firewall holds (gate_a has zero price logic); both steelman + prosecute passes are mandated (§10).

# Tier-2 markout — the edge/informedness measurement (architecture, pre-audit 2026-07-08)

Implements `WALLET_FEATURES_SPEC.md §4c` + P12/P15 over the episode lake and the price panel
(`data/raw/asset_ctx`, per-minute, majors pristine). **This is the load-bearing "is there edge" measurement
and the single most artifact-prone thing in the project** — the prior "+24–31 bp edge" was ENTIRELY a
stale-hourly-candle pricing artifact ([[babylon-edge3-audit]]). Every design choice below is aimed at not
repeating that. EXPLORATORY lane, firewalled from Gate-A; this is a SHADOW Gate-A (over-carry surface, §7/P10).

## 0. The hard lessons this design is built around (read first)
1. **Post-fill pricing, never the fill price.** Markout is measured from an INDEPENDENT price at a timestamp
   STRICTLY AFTER the entry fill (`entry_bar_ts` = first ctx tick strictly after `open_ts`, P12). Using the
   fill's own px, or a candle that straddles the fill, manufactures a spurious edge (self-impact / look-ahead).
2. **Independent price = `oracle_px`** (per-minute, 0 nulls for majors), never derived from wallet prints.
   `mid_px` kept as a cross-check only (majors have 0 mid==0 sentinels; the sentinel plagues alts, not us).
3. **As-of join to per-minute ticks, never an hourly candle.** The stale-candle join is the exact bug that
   created the phantom edge.
4. **Raw directional markout ≈ beta.** A long-in-an-uptrend wallet shows big positive markout with zero skill.
   The skill quantity is **timing_alpha = raw_markout − static-beta baseline** (§4). Report BOTH; the raw is
   the FOIL, the market-adjusted is the finding (§4c "raw markout alone is a beta sort").
5. **A null verdict must earn it** (CLAUDE.md over-null gate): every horizon carries point estimate + CI +
   MDE + n_weeks; `n_active_weeks < 6` ⇒ INCONCLUSIVE, never "no edge". Every positive faces the placebo/
   permutation null + FDR (over-carry gate). Both directions gated equally.

## 1. Price panel (§4c pins)
- Source `data/raw/asset_ctx/month=*/day=*/ctx.parquet`, per coin per minute. Majors: 478,480 ticks each,
  2025-08-01 00:00 → 2026-06-29 23:59, 0 oracle_px nulls, 60s cadence.
- **Price P(coin, t) = `oracle_px`** via **ASOF JOIN**: `latest ctx.ts ≤ t`. NOT a floored equi-join.
- `last_ctx_tick(coin)` = max ts; any horizon endpoint past it is right-censored (§5).

## 2. entry_bar_ts + per-horizon endpoints (P12)
- `entry_bar_ts` = **first ctx tick STRICTLY after `open_ts`** (frozen `>`, not `≥` — post-fill). Backfilled
  into the episode lake's reserved `entry_bar_ts` column (no re-walk — it was reserved for exactly this).
- Entry price `P0 = P(coin, entry_bar_ts)` (ASOF, = the tick itself). For horizon h, endpoint `t_h =
  entry_bar_ts + h`, `Ph = P(coin, t_h)` (ASOF ≤ t_h).
- Horizons `h ∈ {5m,15m,30m,1h,2h,4h,8h,16h,24h,48h}`; PRIMARY study `{1,2,4,8}h` (matches Gate-A frozen set).

## 3. Raw markout estimand (per episode, per horizon)
```
dir_sign = +1 (long) / −1 (short)
raw_markout_{e,h} = dir_sign_e · (P_{e,h} − P0_e) / P0_e · 1e4      # basis points, signed by direction
```
Measured ONCE per episode at its entry (NOT per fill — the lifecycle episode's entry). Stored per-episode in a
new `episodes_markout` table keyed to the episode (wallet,coin,open_ts) — a pure function of the episode lake +
price panel + code commit (backfill, re-runnable). `entry_return` context fields (15m/1h pre-entry move) stored
for momentum/contrarian conditioning.

## 4. Market-adjustment — the timing-vs-static-beta quantity (filter 11, the crux)
The static-beta counterfactual = **a same-direction position entering at a RANDOM minute**. Its expected
markout at horizon h is `dir_sign · μ_h(coin)`, where `μ_h(coin, ≤C)` = the coin's **unconditional mean forward
oracle return over horizon h**, estimated over minutes with `t + h ≤ C` (cutoff-relative → leakage-safe, no
future). Then:
```
timing_alpha_{e,h} = raw_markout_{e,h} − dir_sign_e · μ_h(coin, ≤C)
```
- Interpretation: raw markout minus "what you'd earn just being exposed in this direction on average." A
  long-in-an-uptrend wallet has `raw ≫ 0` but `timing_alpha ≈ 0`. Entry skill ⇒ `timing_alpha > 0`.
- `μ_h` estimated per (coin, horizon) and ALSO per calendar-week (`μ_h(coin, week)`) to remove regime drift —
  the per-week version is the stricter baseline (subtracts the drift the wallet actually lived through). Store
  both `timing_alpha` (vs global-≤C μ) and `timing_alpha_weekly` (vs same-week μ); the weekly one is the
  headline skill metric, the global one the foil.
- ⚠ This is a per-coin baseline (§4c "per coin has most signal" — matches the user's finding). Beta-scaling
  (regress wallet markout on coin return) is a v2 refinement; the μ-subtraction is the v1 skill estimand.

## 5. Leakage / right-censoring (P12, P13)
- Episode contributes horizon h to panel `(cutoff C, window W)` iff: it is a realized member (`close_ts ≤ C`,
  §Table-2 §2) **AND** `entry_bar_ts + h ≤ C` **AND** `t_h ≤ last_ctx_tick(coin)`. Per-horizon `n_episodes`
  therefore DIFFER — store each horizon's n. (An episode can be a realized member but not yet have its 48h
  markout resolved by cutoff C → excluded from h=48h only.)
- `μ_h(coin, ≤C)` uses only minutes with endpoint ≤ C. Nothing post-C enters any panel-C number.
- Open-at-cutoff episodes never contribute markout (they aren't members).

## 6. StableEdge — the robust primary estimator (P15)
Markout is heavy-tailed; the ordinary mean is dominated by one trade/day/week. Per (wallet,coin,cutoff,window,h)
on the **`timing_alpha_weekly`** series:
```
stable_edge_h = median_week( mean_{wallet-coin-DAY}( timing_alpha_weekly ) )         # median-of-means
stable_edge_trim20_h = 20%-trimmed-mean_week( daily means )                          # retains magnitude
```
Store the persistence+concentration+floor quartet (the COMBINATION is the tell, per P15):
`positive_week_fraction`, `markout_without_best_week`, `worst_leave_one_week_out_mean`,
`weekly_bootstrap_lower_bound` (block bootstrap over weeks → 5–10th pctile floor). Convincing iff ALL of:
stable_edge>0, most weeks positive, ex-best-week>0, weekly-bootstrap-LB near/above 0.
- ⛔ **POWER GATE:** store `n_active_weeks` beside every stable field; `n_active_weeks < 6` ⇒ **INCONCLUSIVE,
  never "no edge."** Also store `mde_bp` (the MDE from the weekly bootstrap SE) so a null is only a null when
  `mde ≤ care-about (≈8bp)`.
- Weightings stored separately: `__episode`, **`__wallet_day` (PRIMARY — de-correlates overlapping windows)**,
  `__notional`. Ordinary `mean_bp` kept ONLY as the FOIL (mean ≫ stable_edge ⇒ a lucky block, not an edge).

## 7. Anti-artifact battery (mandatory — this is where the last edge died)
Run and STORE these as first-class columns, not ad-hoc checks:
- **Placebo / permutation null:** shuffle entry times within (coin, week) N times → the random-entry markout
  distribution; `timing_alpha` must clear its permutation p-value. Store `perm_p_value` per horizon.
- **Post-fill sensitivity:** recompute markout at `entry_bar_ts` vs `entry_bar_ts + 1 tick` vs `+ 5 min`; a real
  edge is stable, an artifact collapses. Store `markout_shift1_delta`.
- **Both halves (filter 3):** `stable_edge_first_half` / `_second_half` — require both > care-about.
- **Concentration (filters 9/10):** `markout_without_best_week`, `markout_without_best_day` (day-grain,
  patches the Table-2 gap), `top_day_markout_share`.
- **Curve shape (filter 7, AUC):** `markout_curve_auc_1h_8h`, `slope`, `monotonicity`, `sign_consistency`,
  `peak_horizon`, `8h_minus_1h`, `decay_8h_over_4h` — a genuine information signal decays monotonically; a
  reversal/impact signature is a tell.
- **Decompositions:** buy vs sell, maker vs taker (the single most discriminating informed tell — from the
  episode's `n_taker_fills`/`crossed_open`), size-conditioned (within-wallet notional quantiles).
- **Positive control (MDE proof):** inject a synthetic +Xbp timing edge into a random cohort, confirm the
  pipeline recovers it at the relevant size — proves the test is not blind by construction (CLAUDE.md gate).

## 8. Output — Table 2b `addr_coin_markout` (SHADOW namespace, P10)
Separate namespace from Table 2 (`addr_coin_features`). One row per (address, coin, as_of_cutoff, window,
horizon), naming `metric__aggregation__horizon__window`. Physical `leakage_controls_applied=false` column; any
z/EB/percentile ranking cols prefixed `shadow__` and kept in `addr_coin_shadow_ranking` (NOT joinable into an
"informed list" — reading wallets off this is exploratory, NOT the frozen verdict). Provenance metadata + a
committed `frozen_config.sha256` of {seed, horizons, μ-baseline rule, care-about} recorded BEFORE any real
markout is materialized/viewed (P10 over-carry: post-hoc config edits after seeing rankings = firewall breach).

## 9. Compute plan (8 GB — same constraints as Table 2)
- **Backfill (once):** per coin, ASOF JOIN each episode's `entry_bar_ts` + 10 endpoints to the coin's per-minute
  oracle series → `data/derived/episodes_markout/coin=*/…parquet` (per-episode, per-horizon raw_markout +
  timing_alpha). Per-coin chunk (4×), sorted-merge ASOF is streaming-cheap. ~33.8M episodes × 11 lookups.
- **μ_h(coin, week) baseline:** one pass over the price panel per coin → per-(coin,horizon,week) mean forward
  return. Tiny table, join into the backfill.
- **Aggregate → Table 2b:** per (coin, cutoff, window, horizon) filter members with resolved horizon (§5),
  `GROUP BY wallet`, compute StableEdge + quartet + anti-artifact columns. Per-coin chunk; holistic weekly
  median-of-means needs per-(wallet,week) daily means first (two-level agg) — bucketed if needed. Sequential
  cells, `memory_limit=5GB`, spill to `.tmp`, exact quantiles, deterministic tie-breaks (as Table 2).
- Right-censoring makes late-cutoff/long-horizon cells smaller — cheaper.

## 10. Build order
1. Swarm-audit THIS doc — attack the estimand (§3/§4), the anti-artifact battery (§7), leakage/right-censor
   (§5), and the power/MDE gate (§6). Estimand correctness is the whole game.
2. Backfill `entry_bar_ts` + `episodes_markout` (raw + timing_alpha) on one coin; validate against hand-computed
   markout on a few episodes + the post-fill sensitivity check.
3. μ_h weekly baseline; the placebo permutation null; positive-control MDE proof.
4. Full backfill → Table 2b aggregation (StableEdge + quartet + battery).
5. Re-run the user's 11-filter screen with the REAL markout filters (3,7,8,11) on the hygiene cohort.
6. Steelman-the-positive AND prosecute-the-positive passes (separate agents, CLAUDE.md) → findings ledger.
