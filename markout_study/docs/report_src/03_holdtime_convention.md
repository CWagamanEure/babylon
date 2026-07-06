# 03 — Hold time & the trade-exit convention

## (1) Is a REAL round-trip hold-time distribution available without scanning the tape?

**Yes — a precomputed per-wallet summary already exists on disk, built once (2026-07-05) and
now reusable at zero cost.**

- **Source file:** `out/hold_size_dist.parquet` (1.85 MB, 29,334 wallets, 15 columns). Built by
  `src/hold_size_dist.py`, a *single* streaming pass over `../scratch_conv/mlscreen/cand2_*.parquet`
  (BTC/ETH/SOL/HYPE), already run to completion (log: `out/hold_size_dist.log`,
  `[done] exit=0`). **Do not re-run it for this report** — reading the parquet is a light,
  in-RAM op; re-running would re-scan the tape.
- **What it measures:** a real average-cost position ledger per (wallet, coin) reconstructed from
  signed fills (`src/hold_size_dist.py::ledger`), tracking entry-taker-share of the *open*
  inventory so only **taker-opened** round-trips count as "copyable" (maker-opened legs excluded).
  Dust floor: closed notional ≥ $100. Whole window (train+test), majors only.
- **Per-wallet fields:** `n_close_all`, `taker_share`, `n_tk_close` (taker-opened closes),
  `med_hold_h` / `p25_hold_h` / `p75_hold_h` (hold-time quantiles, **per-trade, not averaged**),
  `n_copyable` (taker-opened closes with hold in [1h, 24h)), and six hold-band counts
  (`nb_lt15m, nb_15m_1h, nb_1_4h, nb_4_24h, nb_24_72h, nb_gt72h`).
- **Rendered already:** `notebooks/hold_feasibility.ipynb` → `out/figs_hold/hold_feasibility.png`
  (4-panel: copyable-sample-vs-hold scatter, within-wallet hold dispersion, `n_copyable`
  histogram, pooled hold-band bar chart). This can be dropped into the report directly or
  regenerated cheaply from the parquet (no tape access needed).

**Pooled population facts (29,334 wallets with ≥200 majors fills, whole window):**

| hold band | taker-opened round-trips | share |
|---|---:|---:|
| <15m | 4,630,918 | 18.3% |
| 15m–1h | 3,878,364 | 15.3% |
| 1–4h | 4,363,745 | 17.2% |
| 4–24h | 6,170,512 | 24.4% |
| 24–72h | 2,957,847 | 11.7% |
| >72h | 3,339,856 | 13.2% |
| **total** | **25,341,242** | 100% |

Per-wallet hold-time quantiles (median of each wallet's own median/P25/P75, across 29,334 wallets):
`med_hold_h` P25/median/P75 = 0.62h / 1.95h / 7.12h. **Caution (already flagged in the
notebook, Panel B):** many wallets have an hold-time IQR as wide as their median — i.e. a
single "this wallet is a 4h trader" label is often wrong; hold is heterogeneous *within* a
wallet, which is why the artifact buckets per-trade rather than reporting one avg-hold number.

**Sample-size feasibility (n_copyable = taker-opened round-trips with hold in [1h,24h)):**

| threshold | all wallets | + taker_share≥0.7 | + taker_share≥0.9 |
|---|---:|---:|---:|
| n_copyable ≥ 50 | 21,305 | 18,869 | 14,956 |
| n_copyable ≥ 100 | 14,225 | 12,544 | 9,860 |
| n_copyable ≥ 200 | 8,167 | 7,149 | 5,482 |

**Prior findings referencing real (not markout-inferred) hold time** — from the tape
round-trip reconstruction (Stage G, `src/tape_roundtrip.py`, `src/how_they_trade.py`),
on the specific top-decile TRAIN-neut-persistent cohort (178 wallets, NOT the general
population above): **~49-minute median hold**, 68–76% taker-opened. Source:
`docs/FINDINGS_LEDGER.md` (Stage G section, lines ~245, ~631) and memory
`babylon-oos-persistence.md`. This is a *much shorter* hold than the population median above —
expected, since that cohort was specifically the high-turnover scalper subgroup identified by
the persistence hunt, not a representative sample of all wallets.

**Bottom line for (1):** yes, a real hold-time distribution exists and is directly plottable —
both at the population level (`out/hold_size_dist.parquet`, all 29,334 majors-active wallets)
and for the one previously-studied cohort (49-min holds, Stage G). No further tape scan is
needed to include a real-hold-time figure in the report.

---

## (2) The report's chosen convention: horizon-exit markout AS the per-trade PnL

**This is the convention the codebase already uses throughout the markout term-structure
build** (`docs/ARCHITECTURE.md` §4.4–4.5), not a new choice for the report — documenting it
here for the writeup.

### What "exited at the horizon" means
For every entry `e` (a taker-opened fill) at time `t_e`, direction `d_e`, and a fixed horizon
`h` (from the ladder `[5m,15m,30m,1h,2h,4h,8h,12h,24h,48h,72h,168h]`):

```
exit_px(e,h) = post-fill bar close at t_e + h       (next-bar-close convention, no same-bar look-ahead)
markout(e,h) = d_e · (exit_px(e,h) / entry_px(e) − 1)     [signed return, bps]
```

**`markout(e,h)` is treated as if the trader closed the ENTIRE position at exactly `t_e + h`** —
a *counterfactual, fixed-horizon* exit, not the trader's actual (unknown/heterogeneous) close
time. This is explicit in the architecture doc: markout "marks a counterfactual fixed-horizon
exit," and reconstructing the trader's actual exit is out of scope for this build (§1,
"Is NOT... reconstruction of the trader's *actual* exits"). Each entry generates **one PnL
observation per horizon** — the same entry appears in the "1h" series, the "4h" series, etc.,
each with a different `markout` value; these are *different, non-nested* per-trade PnL series,
not a single trade followed over time.

### Sharpe — exact formula, per horizon, per (wallet, coin)
```
sharpe(w,c,h) = mean( mk_bps(e,h) )  /  std( mk_bps_UNWINSORIZED(e,h) ),  ddof=1
```
over the valid, count-winsorized entry set `E` at that horizon. Concretely (`src/markout_stats.py`,
`sharpe = mean_w_bps / std_raw_bps` where `std_raw_bps` uses **un-winsorized** returns):
- **Numerator** uses the magnitude-winsorized (p99 per coin×horizon) markout mean — the same
  edge estimator as `avg_edge_bps`.
- **Denominator** deliberately uses the **UN-winsorized** std — winsorizing the downside tail
  would understate risk and inflate Sharpe for exactly the fat-left-tail wallets that matter
  most (`docs/ARCHITECTURE.md` §4.5 re-audit note).
- **This is a per-trade (per-entry) ratio, left un-annualized.** No `×√N` or `×√(periods/year)`
  scaling is applied — the doc states explicitly: `sharpe` is "per-entry, **NOT annualized**."
  (Annualizing would be misleading anyway since horizons overlap in calendar time — see MDD
  below — so a trade count/year isn't a clean scalar.)
- `NaN` if `n < MIN_ENTRIES` or `std == 0`.
- **Uncertainty:** NOT an analytic SE (the entry sequence is autocorrelated under overlap) —
  use a **moving-block bootstrap** over the time-ordered entry sequence, block length `L(h)`
  = median #entries within any trailing window of length `h`. Also report `n_eff ≈ n / L(h)`
  (overlap-deflated effective N) alongside any headline Sharpe.
- A `sortino` variant exists too (mean / downside-deviation, with a `k≈0.15 × field_dd` floor,
  NaN unless ≥5 losing entries) — kept as a diagnostic, not primary, because the floor can
  mechanically collapse it toward a mean-rank for low-loss-count wallets.

### MDD (max drawdown) — **NOT computed on the raw horizon-exit series; this is a deliberate, audited exclusion**
This is the one place the naive "treat markout-at-h as per-trade PnL, then take cumsum and
drawdown" recipe is **wrong by construction**, and the architecture doc calls it out as a
blocker finding:

> **DROPPED: `max_dd` on the fixed-horizon curve.** Fixed-horizon markouts overlap in calendar
> time (e.g. every `4h`-horizon entry made less than 4h after the previous one shares realized
> price path with it), so the entry-ordered cumsum is **not an equity curve** — its "drawdown"
> scales with entry *cadence* (how often the wallet trades), not with risk. **Fictitious.**

**If a report figure needs an MDD-like path stat, the audited approach is:**
```
1. Thin the entry set to a NON-OVERLAPPING subset: keep entries spaced ≥ h apart in time
   (drop entries whose position is still "open" under the h-horizon convention).
2. cum = cumsum(markout_bps over the thinned, time-ordered subset)
3. max_dd_nonoverlap = min( cum − running_max(cum) )        # most negative drawdown, bps
```
(pattern already used elsewhere in this codebase for a different cumulative series, e.g.
`src/cohort_M3_trigger.py:182` — `cum = np.cumsum(s); (cum - np.maximum.accumulate(cum)).min()`
— the same recipe, just requires the non-overlap thinning first for the markout case.)
This `max_dd_nonoverlap` is explicitly **not part of the headline stats table** — report it only
labeled as a non-overlap-thinned diagnostic, on a reduced sample, if at all.

### Summary table (what to print, what NOT to print)

| Quantity | Formula | Status |
|---|---|---|
| Per-trade PnL | `markout(e,h)` at chosen horizon | headline, primary |
| `vw_edge_bps` (PRIMARY edge) | `Σ mk_usd / Σ notl · 1e4` | volume-weighted, deployable |
| `net_exec_bps` | `vw_edge_bps − cost_bps(coin)` | PRIMARY net (upper bound; TOB cost only) |
| Sharpe | `mean(mk_bps) / std(mk_bps_unwinsorized)`, ddof=1, per-entry | report **un-annualized**; pair with block-bootstrap CI + `n_eff` |
| Sortino | `mean / downside-dev`, floor via field_dd | diagnostic only |
| Hit rate | `mean(ret>0)` | point estimate only, no iid CI (autocorrelated) |
| **MDD / max drawdown** | cumsum − running max, on RAW overlapping horizon series | **do not compute — architecturally invalid (fictitious, scales with cadence not risk)** |
| MDD (if needed) | same recipe, but on a **non-overlapping** (≥h-spaced) entry subset | valid but off headline table, reduced N, label clearly |

---

## (3) Taker-fraction / trade-frequency facts (cheaply available, no tape scan needed)

From the same `out/hold_size_dist.parquet` (population: 29,334 wallets, ≥200 majors fills,
whole window):

- **Taker share** (fraction of fill notional that crossed the spread), per wallet:
  mean **0.879**, median **0.969**, P25 **0.828**. Most active wallets in this universe are
  overwhelmingly taker — consistent with the "pay the spread" fingerprint already documented
  for the narrower Stage G cohort (68–76% taker there).
- **Trade frequency proxy**: `n_close_all` (total closed round-trips per wallet, whole window)
  — mean **1,735**, median **305**, P75 **732**, max **764,735** (one extreme high-frequency
  wallet). `n_tk_close` (taker-opened closes only) — median **244**.
- These are **descriptive population facts only** — no claim of edge or persistence attached;
  they characterize *how the universe trades*, feeding the hold-time feasibility question, not
  a profitability claim.

---

## FACTS (with source)

1. Real per-wallet hold-time distribution IS available without a tape scan — `out/hold_size_dist.parquet`
   (29,334 wallets), already built by `src/hold_size_dist.py` (log confirms completed run,
   exit=0). Reading it is a light parquet read (1.85MB), not a tape scan.
2. Pooled taker-opened round-trip counts by hold band (population, whole window):
   <15m 4.63M, 15m–1h 3.88M, 1–4h 4.36M, 4–24h 6.17M, 24–72h 2.96M, >72h 3.34M (25.3M total).
3. Per-wallet median hold time (of each wallet's own per-trade median): P25/median/P75 =
   0.62h / 1.95h / 7.12h across 29,334 wallets — but hold is heterogeneous *within* a wallet
   (IQR often ≈ median), so a single "typical hold" label per wallet is frequently misleading.
4. Sample-size feasibility for a mid-frequency (1–24h hold) copy-style test: 14,225 wallets
   have ≥100 taker-opened round-trips in that band; 12,544 of those also have taker_share≥0.7.
5. The previously-studied, narrower Stage G cohort (178 top-decile TRAIN-neut-persistent
   wallets) has **~49-min median hold**, 68–76% taker — a distinct, much higher-turnover
   population than the general universe above (docs/FINDINGS_LEDGER.md Stage G; memory
   babylon-oos-persistence.md). Do not conflate the two hold-time numbers.
6. Population taker share: mean 0.879, median 0.969 (`out/hold_size_dist.parquet`).
7. The report's markout convention treats each entry's `h`-horizon markout AS the trade's
   entire PnL (fixed counterfactual exit, not the trader's real close) — `docs/ARCHITECTURE.md`
   §4.4, explicit design choice, "Is NOT... reconstruction of the trader's actual exits."
8. Sharpe = mean(winsorized mk_bps) / std(UN-winsorized mk_bps), ddof=1, **per-trade, left
   un-annualized** — `docs/ARCHITECTURE.md` §4.5, `src/markout_stats.py` line ~110.
9. MDD/max-drawdown on the raw overlapping horizon-exit series is **architecturally invalid**
   and was explicitly DROPPED from the stats table (`docs/ARCHITECTURE.md` §4.5, "DROPPED: max_dd
   on the fixed-horizon curve... fictitious"). A valid variant exists only on a non-overlapping
   (≥h-spaced) entry subset, off the headline table.

## FIGURES-TO-MAKE

- **Reuse as-is:** `out/figs_hold/hold_feasibility.png` (4-panel: sample-size-vs-hold scatter
  with copyable box, within-wallet hold dispersion, `n_copyable` histogram, hold-band bar
  chart) — already rendered, drop straight into the report for the "is hold-time available"
  section.
- **New, cheap (reads `out/hold_size_dist.parquet` only, no tape):** a single population
  hold-time histogram (log-x, per-trade `med_hold_h` or pooled band bar chart restyled for the
  report's visual system) sized for the report rather than the notebook's exploratory 4-panel.
- **New, cheap:** side-by-side annotation on the hold-band bar chart marking where the Stage G
  49-min cohort would sit (far left of `lt15m`/`15m_1h`) vs. the population median (~2h) — makes
  the "narrow high-turnover cohort ≠ general population" point visually.
- **Conceptual diagram (no data, illustrative only):** one entry → multiple horizon-exit markouts
  (5m through 168h) as parallel counterfactual PnL realizations, to make the "not a real
  round-trip, not a followed trade" convention visually explicit for readers — this is the
  single most important framing figure for this section since the convention is easy to
  misread as "actual trade duration."
- **Optional, if MDD is requested by the team:** a `max_dd_nonoverlap` bar chart per top
  candidate wallet, clearly subtitled "non-overlapping entries only, reduced N, off headline
  table" so it can't be mistaken for a real equity curve.

## GAPS

- `out/hold_size_dist.parquet` covers only wallets with **≥200 majors fills** and only
  **BTC/ETH/SOL/HYPE** (not SPX, which the markout study otherwise includes as a 5th major) —
  so it is not a perfect population match to the markout entries universe; a small mismatch
  in wallet coverage should be footnoted if the two are shown side by side.
- A non-overlap `max_dd_nonoverlap` was NOT computed for any candidate wallet in
  `out/optimal_exit.parquet` for this report — it would be a small, bounded computation (not a
  full tape rescan) but should be scoped/estimated before promising it, since it requires
  re-deriving a non-overlapping entry subset per wallet.
- No annualized Sharpe exists anywhere in the codebase (deliberately, per architecture doc) —
  if the team/readers expect an annualized number for comparability to conventional funds, that
  is a framing gap to flag explicitly in the writeup, not silently compute.
- The "49-min median hold" figure is for ONE specific 178-wallet cohort from an earlier stage
  of the study (Stage G), not the markout study's general wallet universe; report readers
  should not generalize it as "the" hold time without the population figure above alongside it.
