# Majors Markout Study — Architecture (v3, post-re-audit)

**Status:** v3 — revised after TWO audit rounds (4 agents each: pricing, position, statistics, pitfall-regression). Round 1 fixed the measurement core; round 2 confirmed the core sound *on real data* and hardened the winsorization details and the §4.7 peak-selection wrapper (block bootstrap, common-entry-set argmax, held-out debiased peak, unit-aware ALT threshold, bar-net clustering). Tags: `[stats-Fx]`/`[pricing-Fx]`/`[position-Fx]` = round-1 findings; `[re-audit ...]` = round-2. Ready to build.
**Date:** 2026-07-04

---

## 0. Goal (what this build is, and is not)

**Is:** For the liquid markets we can copy at size — **BTC, ETH, SOL, HYPE, SPX** — compute, for every taker who trades a coin enough to be measurable, a **markout term structure**: the signed post-entry return at many exit horizons. From it, a **per-(trader, coin, horizon) statistics table**, and a per-(trader, coin) **optimal-exit roll-up**.

**The deliverable that answers the goal** ("find copy-tradeable-on-entry traders with a profitable exit window, to optimize exits") is the roll-up in **§4.7**: for each trader×coin, the exit horizon that maximizes the **deployable, cost-netted, volume-weighted** edge — *not* the equal-weight curve — carried with a **stability guard** so it is not a noise-max over the horizon grid. `[stats-F4, pitfall-F1: an uncontrolled in-sample argmax over 12 horizons on the size-blind curve re-imports the winner's-curse + #8 no-CI + #18 size-blind. The peak MUST be defined on the deployable curve with a bootstrap CI.]`

**Is NOT (phase 2, explicitly out of scope):** informedness/significance testing (flip-null, entity resolution); L2 depth & market-impact; the maker side; reconstruction of the trader's *actual* exits (markout marks a counterfactual fixed-horizon exit). This build is **descriptive and in-sample** — it characterizes historical records; it makes **no out-of-sample selection claim** (see §7).

---

## 1. Scope: coins

**Primary universe — scored per-wallet individually:** `BTC, ETH, SOL, HYPE, SPX`.
**Secondary — field aggregate ONLY (never a per-wallet stats row):** `ALT`. `[pitfall-F4/position-F6: per-(wallet,coin) position logic cannot coherently pool a wallet's distinct alt coins into one Sharpe/DD; so ALT is a field-level contrast column only.]` **Definition of an ALT coin:** `coin ∈ bars file ∧ ≥ 500 bars in-window ∧ coin ∉ {5 majors}`. Pooled across all such coins into `(ALT, horizon)` field cells.

Rationale unchanged: majors are the only markets deep enough to copy at size (capacity trap); their prices are continuous; alts delist/gap and flatter results.

---

## 2. Data sources (canonical — never mix)

| What | File | Schema | Notes |
|---|---|---|---|
| Fills (signed) | `scratch_conv/mlscreen/cand2_{YYYYMM}.parquet` × 11 | `wallet, ts, tid, coin, px, sz, crossed, zhash` | **Canonical.** `sz` pre-signed; `crossed`=taker; `zhash`=self/wash flag (moves position, not scored — §4.2). Verified: all 5 majors present, symbol-consistent, 12.07M rows/mo. |
| Prices | `scratch_conv/mlscreen/bars_{YYYYMM}.parquet` × 11 | `coin, bar, close` | 5-min bar close; gaps when a bar had no trades = the delist/halt signal. |

**PITFALL GUARD (#17, freshest wound):** read ONLY `cand2_*`. `other_repo_notes/fills_*` and droplet `parquet_cold/` are different/incomplete extractions (different coin convention, majors missing). **No stitching.** Verified clean by the audit.

---

## 3. Reuse map (stand on proven code)

Import from `scratch_conv/mlscreen2.py`: `_load_bars()`, `_next_bar_close_vec(lookup, ts)` (**verified leak-free**: `searchsorted(times, (ts//BAR_MS)*BAR_MS, side="right")` prices the first bar starting *strictly after* the fill's bar; NaN when that bar is >30 min away or ≤0 — post-fill AND delist-safe), and constants `T0, ALL_MONTHS, OUT, BAR_MS`. Model the per-wallet-prefix sharded loop on `coin_term_structure.py` (opening detection + burn-in). **The size/dollar/clustering/stats layer below is new code** and is where the audit found every defect — build it with the fixes here. `[position: reference engine only ever made equal-weight bps; dollar layer is unproven.]`

---

## 4. Measurement pipeline (per wallet, per coin)

Sharded by wallet-prefix `0x0..0xf` (16 shards), `scan_parquet(11 files).filter(prefix).collect(streaming)` — **RAM-verified** ~1 GB peak/shard, safe on 8 GB. Per `(wallet, coin)` group, fills sorted `(ts, tid)` with `maintain_order=True`.

### 4.1 Burn-in
`cum = cumsum(sz)`; first index where `|cum| < flat_units(coin)` = return-to-flat; discard through it (`[ff+1:]`); **recompute `cum` on the surviving slice**. Never-flat `(wallet,coin)` dropped (unknowable opening inventory; #11). **Flatness is tested in UNITS, not dollars** `[re-audit NEW-4: a dollar floor is directionally wrong — it only ever raises above $1 and never catches a huge-unit position in a sub-$0.001 alt].` `flat_units(coin) = 1e-3 · median(|sz|)` over that coin's fills (a position smaller than 0.1% of a typical fill = dust/float-residue). This is price-agnostic, so it works for $68k BTC and $0.0001 alts alike; the field ALT baseline uses the same per-coin rule *before* pooling. Accept that a wallet genuinely flat at t0 loses its first episode — indistinguishable from carried inventory; matches `pnl_engine.py`'s `warmed` flag; documented, not "fixed." `[position-F4]`

### 4.2 Opening-fill detection (per-fill, BEFORE clustering)
```
pb   = shift(cum, 1, fill=0)
comp = where(sign(pb)==sign(cum) | pb==0,  |cum|-|pb|,  |cum|)   # position INCREASE; =|q| for open/add, =|cum| for flip residual
open = (comp > 1e-12) & crossed & ~zhash
dir  = sign(cum)   # at the opening fill
```
`comp` is the exact position increment in all cases (open/add/partial-reduce/flip/close) — **verified by trace.** Reductions/closes are not entries (documented scope limitation, §7). `zhash` fills move `cum` but are never scored `[position-F5: confirmed consistent with pnl_engine; zhash = real position-moving fill we don't score]`.

### 4.3 Entry clustering — FINAL: masked per-fill detection + (bar,dir) cluster (code-audit BLOCKER-1)
**Bar-net (the round-2 proposal) was SUPERSEDED**: it operates on `cum` (all fills) and cannot exclude **maker** (`~crossed`, 29% of fills) or **wash** (`zhash`, 29%) fills per-fill, which §0/§4.2 require. So the FINAL rule is the reference-faithful structure (`coin_term_structure.py`):
```
cum = cumsum(sz) over ALL fills                      # TRUE position -> burn-in + per-fill comp
comp = per-fill position increment (§4.2)            # |q| open/add, |cum| flip residual
open_fill = (comp > flat_units) & crossed & ~zhash   # TAKER, non-wash, position-increasing
entries = cluster open_fill by (bar, sign(cum)), summing comp   # same-bar taker sweep = one decision
```
Maker/wash fills move `cum` (so burn-in and subsequent `comp` stay correct) but are never SCORED. Accepted, disclosed trade-off vs bar-net: intrabar churn sums per-leg (`+10,−3,+5` taker → 15, not net 12) and a within-bar flip books BOTH legs (long-10 + short-4) — both rare, surfaced via the §7 within-bar-flip fraction. All same-bar entries share one post-fill price (§4.4), so clustering is exact for pricing; the VWAP fill price is diagnostic only. Validated by 7 known-answer probe fixtures (incl. maker-excluded, wash-excluded).

### 4.4 Per-entry markout at each horizon `h`
```
entry_px   = _next_bar_close_vec(lk, t_e)          # post-fill
exit_px(h) = _next_bar_close_vec(lk, t_e + h_ms)   # post-fill at horizon
ret(e,h)   = d_e · (exit_px(h)/entry_px - 1)        # signed
notl_e     = q_e · entry_px                          # q_e = clustered comp (NOT raw |sz|)  [position-F1]
mk_bps(e,h)= w( ret(e,h) ) · 1e4                     # winsorized — see below
mk_usd(e,h)= w( ret(e,h) ) · notl_e                  # SAME winsorized ret as bps  [pricing-F1]
```
**Notional uses `q_e` (clustered position increment), never raw `|sz|`** — a flip's raw size includes the closing leg and would overstate notional ~N× `[position-F1]`. Notional is at the copier's post-fill `entry_px`, not the wallet's fill VWAP (correct for copy framing; documented) `[position-F8]`.

**Winsorization (replaces the ±2000 bps clip) — DECIDED (Q6), revised:** winsorize the **direction-neutral magnitude** `|ret(e,h)|` at the **empirical p99 per REAL coin × horizon**, then re-apply the sign; use the *identical* winsorized value for both `mk_bps` and `mk_usd`. `[pricing-F1: flat ±2000bp clip is horizon-asymmetric (12.7% HYPE / 23.1% SPX of 168h cells clipped) and biased the deliverable peak. Re-audit: winsorizing the SIGNED return at p1/p99 re-introduces a skew bias (pooled signed dist is right-skewed, p99 +4346 vs p1 −2323 on HYPE) that pulls the mean down ~2-5bp; magnitude-winsor is skew-neutral. And ALT must be winsorized per REAL coin BEFORE pooling — pooled ALT p99 spans 33× across coins and would be set by memecoins.]` Winsorization is applied ONLY to the *edge* estimators (`mk_bps`, `mk_usd`, and thus `avg_edge_bps`/`vw_edge_bps`); **risk denominators (§4.5 std, downside-dev, field-dd) are computed on UN-winsorized returns** `[re-audit: winsorizing the downside tail understates downside deviation → inflates Sharpe/Sortino for the fat-left-tail wallets, the dangerous ones].` Report raw AND winsorized peak, and the winsorized-fraction, per (coin,horizon). Note winsor is entry-count-based, not notional-weighted, so it does not by itself tame the notional-weighted peak's tails — the §4.7 block-bootstrap stability flag is the single-large-entry guard.

NaN entry/exit → cell **dropped** (never zero-filled). Coverage handled in §6.

**Horizon ladder (extended down for exit-timing):** `[5m,15m,30m,1h,2h,4h,8h,12h,24h,48h,72h,168h]`. Every horizon is an integer multiple of BAR_MS, so entry and exit are always ≥1 distinct bar apart — no same-bar degeneracy (**verified**). Sub-1h cells carry one-bar (~5 min) noise — flagged.

### 4.5 Per-(wallet, coin, horizon) statistics
Over the valid, winsorized entry set `E` at horizon `h`. **Primary = deployable/size-aware; equal-weight = diagnostic secondary** `[stats-F8, #18]`.

| Stat | Definition | Notes |
|---|---|---|
| `n` | \|E\| | raw entry count |
| `n_above_floor` | entries with `notl_e ≥ MIN_NOTL` | dust guard `[position-F3]` |
| `n_eff` | overlap-deflated effective N; **block length `L(h)` = median #entries within any trailing window of length `h`** (the overlap scale); `n_eff ≈ n/L` | concrete, implementable `[re-audit: "Newey-West/block" was unspecified]` |
| `volume` | Σ `notl_e` | turnover |
| **`vw_edge_bps`** (PRIMARY) | Σ`mk_usd` / Σ`notl` · 1e4 | volume-weighted; = deployable edge quality; overlap-robust; **carries a block-bootstrap CI (below)** |
| **`exec_quality`** (PRIMARY) | `cum_pnl_gross`/`volume` | = `vw_edge_bps`/1e4 |
| `avg_edge_bps` (secondary) | mean `mk_bps` | equal-weight, size-blind — **diagnostic only** |
| `hit_rate` | mean(`ret>0`) on un-winsorized ret | point estimate; **no iid CI** (overlap-autocorrelated) `[stats-F10]` |
| `sharpe` | mean(`mk_bps`)/**std(un-winsorized ret·1e4)**, ddof=1 | per-entry, **NOT annualized**; NaN if `n<MIN` or std=0; uncertainty via block-bootstrap CI + `n_eff`, NOT an analytic SE `[re-audit: the Lo (1+½S²)/n_eff formula is not autocorrelation-consistent; a moving-block bootstrap over the entry sequence is]` |
| `sortino` | mean(`mk_bps`)/**downside-dev(un-winsorized ret)** | floor `dd=max(ε, k·field_dd(coin,h))`, k≈0.15; **NaN unless ≥5 losing entries**; DIAGNOSTIC (a binding field-floor collapses it toward a mean-rank) `[stats-F5, #7, re-audit]` |
| `cum_pnl_gross` | Σ `mk_usd` | **gross, overlapping, un-netted — NOT capital-constrained realized PnL** (only consumed as the `exec_quality` ratio) `[stats-F2]` |

**Uncertainty via moving-block bootstrap (unifies with §4.7):** every PRIMARY cell (`vw_edge_bps`, `net_exec_bps`) carries a CI from a **moving-block bootstrap over the (time-ordered) entry sequence**, block length `L(h)` as above. This is the one honest uncertainty estimator under overlap; the analytic SE and a bare `n_eff` are reported as descriptive only. `[re-audit MAJOR: iid resampling of overlapping entries gives a too-tight CI.]`

**DROPPED: `max_dd` on the fixed-horizon curve.** `[stats-F1 BLOCKER: fixed-horizon markouts overlap in calendar time, so the entry-ordered cumsum is not an equity curve; its "drawdown" scales with entry cadence, not risk — fictitious.]` A path/risk stat, if wanted, is computed only on a **non-overlapping entry subset** (entries spaced ≥ h apart) → genuine one-at-a-time PnL → `max_dd_nonoverlap` on the thinned sample, clearly labeled. Not in the headline table.

### 4.6 Cost model / deployable net
`cost_bps(coin) = 2·taker_fee + 2·half_spread(coin) + 2·slippage_buffer` — round-trip (cross on copy-entry AND copy-exit; **2× confirmed correct**, horizon-independent). Slippage is **per-crossing → 2×** `[stats-F6]`. `half_spread` a measured per-coin constant (§8). **Net is computed on the volume-weighted edge:** `net_exec_bps = vw_edge_bps − cost_bps` (PRIMARY). `avg_edge_bps − cost` kept only as a labeled diagnostic. `[stats-F3 MAJOR: netting the size-blind metric is the exact #18 trap.]` `net_exec_bps` is an **upper bound on net edge** — the constant top-of-book cost ignores market impact at copy size (lower-bounds true cost) `[stats-F6]`; labeled as such. **Note (re-audit):** `cost_bps` is horizon-independent, so `argmax_h net_exec_bps = argmax_h vw_edge_bps` — netting does NOT relocate the peak; it only gates candidacy via `net_exec_bps>0`.

### 4.7 Per-(wallet, coin) optimal-exit roll-up — the goal deliverable `[pitfall-F2]`, hardened (re-audit)
`markout_study/out/optimal_exit.parquet`, one row per (wallet, coin). The peak selection is the project's classic failure surface, so it is built to defeat BOTH a size-blind peak and a winner's-curse peak:

1. **Common entry set.** All per-horizon curves for a wallet are computed on the **entry set valid at EVERY horizon** (the §6 common set), so `argmax_h` compares horizons on the *same* entries — not the censoring-mismatched sets a naive argmax would use. `[re-audit NEW-3 / stats-MAJOR-2: long horizons censor/drop more entries, so a naive argmax can pick a horizon because its subset landed in a good regime.]`
2. **Deployable curve.** `h_star = argmax_h vw_edge_bps(h)` on that common set (identical to the net-curve argmax since cost is flat, §4.6). Never the equal-weight curve. `[pitfall-F1]`
3. **Out-of-sample peak value (debias the winner's curse).** Split the wallet's entries into two time halves: choose `h_star` on the **first half**, evaluate `peak_net_bps` on the **held-out second half**. `[re-audit stats-MAJOR-2: a bootstrap that re-runs the argmax inherits the max's optimism; only a held-out evaluation debiases the peak value.]` (If either half is below `MIN_ENTRIES`, `h_star` is reported but `peak_net_bps`/candidacy are NaN — insufficient evidence.)
4. **Stability gate.** `peak_stable` iff the held-out **moving-block-bootstrap lower CI bound of `net_exec_bps(h_star)` > 0** (not the point estimate) AND that peak beats the coin-field baseline at `h_star`. `[re-audit stats-MAJOR-1/3: use a block (not iid) bootstrap; require the LOWER bound > cost; test vs the field/a distant horizon, NOT the autocorrelated neighbor — adjacent horizons are mechanically near-identical under overlap so a neighbor check is vacuous.]`

Columns: `h_star`, `peak_net_bps` (held-out), `peak_net_lo` (block-boot lower CI), `n`, `n_eff`, `coverage`, `volume`, `peak_stable`, `beats_field`. Only `peak_stable` rows are candidate copy-tradeable-with-exit traders; all others reported, not endorsed. **§7's header disclaimer still applies — even a `peak_stable` row is an in-sample candidate, not an out-of-sample pick (the held-out half is within the same 11-month window).**

---

## 5. Minimal filter (mechanical only)
Per `(wallet, coin)`: keep if `n_above_floor ≥ MIN_ENTRIES` (=30). `MIN_NOTL` dust floor (=$100) applied per entry. **No performance-based filtering** ("filters fix mechanics; statistics fix luck"). Population = the cand2 eligible cohort ∩ (≥30 non-dust entries in the coin); documented.

---

## 6. Outputs & reproducibility
- `out/markout_stats.parquet` — per (wallet,coin,horizon): §4.5 stats + `net_exec_bps` + `coverage`. Long format. **Not sorted by any performance metric** (sort = wallet,coin,horizon); sorting-by-performance IS selection `[stats-F4]`.
- `out/optimal_exit.parquet` — §4.7 roll-up (the decision artifact).
- `out/field_by_coin_horizon.parquet` — field mean/median markout per coin×horizon (the baseline every trader is read against; ALT lives only here).
- `out/coverage_report.parquet` — per (coin,horizon): valid-cell fraction, **dropped-entry count + their short-horizon markout distribution** for BOTH the NaN-price drops AND the §5 dust-floor drops `[pricing-F2, re-audit NEW-2: dust drops preferentially remove flip residuals, a distinct subpopulation — audit them too]`, **and the scorable entry-time window** (long horizons right-censor entries in the last ~h of data → over-represent early-window entries) `[pricing-F2, pitfall-F3]`. The **common entry set valid at every horizon** is a real artifact (verified ~97.9% retained for majors) and FEEDS §4.7, not just a sensitivity check `[pricing-F2]`.
- **Known-answer probe:** before trusting any aggregate, validate the full burn-in/opening/clustering/markout path on ONE hand-checked wallet (fixture in `audit/`) `[pitfall-F5, #13 META-GUARD]`.
- **Determinism:** sort keys before every final float reduction (else polars hash-order gives ULP drift) `[pitfall-F6]`. Fixed input set; RNG only in the §4.7 bootstrap (seeded). Every number traces to `cand2_*`+`bars_*`.

---

## 7. Limitations (carry into the report)
- **Descriptive, in-sample — NOT a selection.** Header sentence, mandatory `[stats-F7, pitfall-F1]`: *"No row here is a wallet pick. In this project, in-sample Sharpe/edge has failed to persist out-of-sample and has inverted (E2 −1.17; June −90 bp/entry). Any pick requires the phase-2 walk-forward on non-overlapping windows."* Enforced structurally: table unsorted by performance; every performance cell carries N/N_eff/SE.
- **SPX is fully continuous here** (24/7, ~complete 5-min bars, one >30-min gap in 11 months) — **no equity-calendar gapping** `[pricing-F3 corrects the v1 rationale]`. SPX's real risk is that it is the *most volatile* major at long horizons (handled by §4.4 winsorization). SPX uses the **full horizon ladder** (Q4).
- **Overlapping fixed-horizon markouts:** `cum_pnl_gross` and Sharpe are affected by overlap (handled via relabeling, `n_eff`, and the non-overlap DD variant).
- **Single entry lag:** entry priced at one fixed lag (~2.5 min avg to next bar). Edge decays with lag (prior work: 60s +71 → 15m +37 bps); this build does not stress copy-latency sensitivity — "copy-tradeable-on-entry" is only weakly evidenced by single-lag markout `[pitfall-F7, phase-2]`.
- **Co-trading wallets** (e.g. the known 8-wallet group) double-count in field aggregates; entity dedup is phase-2 — flag in the field baseline `[Q7]`.
- **Within-bar flips** are booked as a single copyable bar-net entry (§4.3), so a wallet that flips inside a 5-min bar has its pre-flip leg treated as un-copyable churn — report the per-wallet within-bar-flip fraction so flip-heavy HFT wallets are visible `[re-audit NEW-5]`.
- Reductions/closes not scored; maker side unexamined; theoretical markout ≠ realized copy PnL (modeled not booked cost).

---

## 8. Cost calibration (small, deferred, non-blocking)
Model cost now with documented constants. Later: pull **BBO (best bid/offer), not full depth**, for the 5 majors over a short window to measure `half_spread(coin)` and replace the assumed constant; spot-check exits. Full L2 depth → phase-2 capacity/impact. Source: HL S3 archive (documented).

---

## 9. Pitfall checklist (code must satisfy each)
1. Post-fill pricing via `_next_bar_close_vec` — verified leak-free. ✔
2. Delist/halt/gap → NaN → cell dropped, never stale-carried. ✔
3. Burn-in; never-flat dropped. ✔ §4.1
4. Entry = **bar-net position delta, split at zero-cross** (not summed per-fill comp); one entry per (wallet,coin,bar). ✔ §4.3
5. Winsorize **magnitude `|ret|` at p99 per REAL coin×h** (re-apply sign), SAME value for bps and $; **risk denominators on UN-winsorized ret**. ✔ §4.4
6. Sortino scale-relative floor + ≥5 losers (diagnostic); uncertainty via **moving-block bootstrap**, not analytic SE. ✔ §4.5
7. Primary metrics volume-weighted; net on vw_edge; equal-weight diagnostic-only; cost horizon-independent (doesn't move peak). ✔ §4.5/4.6
8. `max_dd` dropped from fixed-horizon table; non-overlap variant only. ✔ §4.5
9. `cum_pnl_gross` relabeled (overlapping, un-netted). ✔ §4.5
10. Peak on **common-entry-set** deployable curve; `peak_net_bps` **held-out (train-half chooses h_star, test-half evaluates)**; `peak_stable` = block-boot **lower CI > 0** AND beats field. ✔ §4.7
11. Burn-in flatness in **units** (`1e-3·median|sz|`), not dollars. ✔ §4.1
12. Coverage: fraction + dropped-entry distribution (NaN + dust drops) + temporal-censoring window + common-set (feeds §4.7). ✔ §6
13. ALT = field-aggregate only; "standard perp" defined; winsor per real coin before pooling. ✔ §1/§4.4
14. Mechanical filter + dust floor only; no performance selection. ✔ §5
15. Descriptive scope enforced structurally (unsorted, block-boot CI on every primary cell). ✔ §6/§7
16. Canonical `cand2_*` only. ✔ §2
17. RAM-safe prefix sharding + streaming. ✔ §4
18. Known-answer single-wallet probe before trusting aggregates. ✔ §6
19. Determinism: sort before reductions; seeded bootstrap. ✔ §6

## 10. Resolved decisions
- **Q1 clustering:** one entry per (wallet,coin,bar) = **bar-net position delta split at zero-cross** (supersedes sum-of-comps, which double-counted intrabar churn). ✔
- **Q2 Sharpe:** per-entry, not annualized, + `se_sharpe` + `n_eff`; table never sorted by it. ✔
- **Q3 MIN_ENTRIES:** 30 on `n_above_floor`; MIN_NOTL=$100 dust floor; Sortino needs ≥5 losers. ✔
- **Q4 SPX:** full ladder (SPX is continuous; risk is volatility → winsorized). ✔
- **Q5 max_dd:** dropped from headline; non-overlap-subset variant only. ✔
- **Q6 clip:** replaced by **magnitude** p99 winsorization per REAL coin×h (sign re-applied), identical for bps and $; risk denominators un-winsorized. ✔
- **Q7 entities:** co-trading caveat on field aggregates; dedup is phase-2. ✔
