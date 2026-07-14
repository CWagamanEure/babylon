# 05 — Neutralized (drift-stripped) markout term structure per coin × horizon

**Scope note:** this doc is a light, RAM-safe aggregation of an *already-built* artifact
(`out/cohort_K_entries.parquet`, 812,616 rows, 59.5 MB). No bar-pricing, no tape scan was run to
produce it — everything below is `pl.read_parquet` + groupby/quantile on that one file
(`POLARS_MAX_THREADS=2`). It is the skill-isolating counterpart to the raw-curve report (04): same
entries, same horizons, but with each coin's own drift subtracted so what's left is (approximately)
*idiosyncratic* markout, not "the coin went up/down that month."

---

## FACTS

### 1. Exact neutralization definition (read from source, not inferred)

**Source of truth:** `src/cohort_K_price.py` (Stage K, Job C — the script that built
`out/cohort_K_entries.parquet`). The architecture doc (`docs/STAGE_K_ARCHITECTURE.md`, §3) *describes*
the estimand loosely as "coin-day-neutralized: `raw − (coin-day-mean of raw)`" — **that description is
imprecise/stale relative to the actual code.** The real, executed neutralization is a **coin-MONTH
drift strip**, not coin-day, and it strips the coin's own *unconditional forward drift at that
horizon*, not a cross-sectional demean across wallets at the same timestamp. Precisely:

1. For each coin and each calendar month `m` (`ym = year*100+month`, UTC), take **every 5-minute bar
   timestamp in that coin's own bar grid** falling in month `m` (only if the month has ≥20 such bars).
2. For each horizon `h ∈ {1h,2h,4h,8h,24h}` (and also 5m/15m/30m/12h, not reported here), compute the
   **unconditional forward return** from every one of those bar timestamps: `entry = next_bar_close(bar_ts)`,
   `exit = next_bar_close(bar_ts + h)`, `r = exit/entry − 1`. Average `r` across all finite values →
   `drift[(coin, month, h)]` — i.e. *the mean h-hour forward return an entry at any random bar in that
   coin-month would have earned, unconditional on direction*.
3. For a cohort entry at time `b_ts` (month `m`, direction `dir ∈ {+1,−1}`) with raw signed markout
   `raw = dir·(exit_close/entry_close − 1)·1e4` (bp; `entry_close`/`exit_close` via the same
   `_next_bar_close_vec` forward primitive used everywhere in this study, so entry and exit are both
   strictly **post-fill, next-bar-close** — no same-bar degeneracy):
   ```
   neut = raw − dir · drift[(coin, month, h)] · 1e4        (bp)
   ```
   i.e. subtract the coin's own *directionally-signed* average drift for that month at that horizon.
   A long entry has the coin's positive-month drift subtracted; a short entry has it added back
   (equivalently: subtract `dir·drift`, so a short in an up-month gets a *larger negative* adjustment,
   correctly reflecting that shorting a rising coin is swimming upstream on drift alone).
4. This is **NOT a per-timestamp cross-sectional demean** (no "average across wallets/coins active at
   the same instant" is computed anywhere in this pipeline) and it is **NOT per-day** — the drift
   benchmark is a single scalar per (coin, calendar month, horizon), reused for every entry that
   coin/month/horizon regardless of which specific day or hour it fell in. Grain = **coin-month**, confirmed
   directly from `ym_of()` (`year*100+month`) being the only grouping key in the drift-table construction
   loop (`src/cohort_K_price.py` lines ~44–56).
5. Ledger caveat inherited from Stage F/prior stages and explicitly re-asserted in `STAGE_K_ARCHITECTURE.md`
   §3: this "neut" quantity is a **skill-measurement device, not a deployable return** — you cannot
   actually hedge/trade the coin-month mean-drift benchmark, so `neut` should never be re-quoted as a
   copyable/net-of-cost P&L number. It exists purely to answer "how much of raw markout is just the coin
   moving that month, versus something entry-specific."

**Practical read:** `neut_h = raw_h − dir·(coin's own average h-hour buy-and-hold drift that calendar
month)`. Two entries in the same coin-month get the *same* subtraction regardless of day/hour/regime
within the month — this is a coarse, monthly-grain drift strip, coarser than "coin-day" as the
architecture doc states.

### 2. Coin × horizon neutralized markout table (TEST split, out-of-sample; entries where the field
is priced at that horizon; bp = basis points)

Computed directly (not the wallet-equal-weighted Stage K estimator — see caveat below): per-entry
`neut_h`/`raw_h`, grouped by (coin, horizon), `mean`, `median`, `std`, `IQR` (`p75−p25`), `N`.

| coin | horizon | neut mean | neut median | neut std | neut IQR | N (test) | raw mean | raw median |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 1h | −0.13 | +0.05 | 58.6 | 55.4 | 86,619 | −0.22 | 0.00 |
| BTC | 2h | −0.34 | +0.13 | 79.8 | 75.8 | 86,619 | −0.52 | 0.00 |
| BTC | 4h | −0.16 | +0.38 | 101.5 | 101.2 | 86,572 | −0.54 | 0.00 |
| BTC | 8h | −1.23 | −0.21 | 130.6 | 143.7 | 86,436 | −1.99 | −0.83 |
| BTC | 24h | −2.71 | −2.49 | 223.6 | 280.7 | 85,913 | −4.84 | −3.71 |
| ETH | 1h | +0.18 | −0.73 | 77.1 | 67.5 | 30,006 | +0.05 | −0.95 |
| ETH | 2h | +0.95 | −0.38 | 103.6 | 94.0 | 29,995 | +0.68 | −0.63 |
| ETH | 4h | +1.99 | +0.70 | 137.3 | 127.6 | 29,994 | +1.42 | 0.00 |
| ETH | 8h | +1.16 | −0.61 | 180.6 | 178.5 | 29,941 | 0.00 | −1.79 |
| ETH | 24h | +3.58 | +1.98 | 303.1 | 358.3 | 29,827 | +0.22 | −1.73 |
| SOL | 1h | +0.10 | +0.47 | 85.1 | 75.6 | 17,063 | +0.07 | +0.34 |
| SOL | 2h | +2.39 | +1.67 | 110.7 | 106.5 | 17,058 | +2.32 | +1.57 |
| SOL | 4h | +3.50 | +1.36 | 146.8 | 150.3 | 17,057 | +3.32 | +1.54 |
| SOL | 8h | +3.91 | +3.77 | 189.8 | 220.3 | 17,012 | +3.52 | +3.99 |
| SOL | 24h | +4.49 | −0.06 | 324.8 | 420.8 | 16,936 | +3.46 | −1.14 |
| HYPE | 1h | +0.43 | −0.15 | 119.0 | 130.9 | 34,709 | +1.35 | +0.95 |
| HYPE | 2h | +0.78 | −1.70 | 163.2 | 185.8 | 34,689 | +2.58 | +0.47 |
| HYPE | 4h | −1.29 | −4.77 | 221.1 | 248.7 | 34,701 | +2.25 | −0.23 |
| HYPE | 8h | −5.19 | −8.01 | 301.3 | 355.5 | 34,649 | +1.87 | +0.35 |
| **HYPE** | **24h** | **−18.64** | **−21.29** | 516.0 | 647.5 | 34,497 | +2.77 | −1.61 |
| **POOLED** | 1h | +0.06 | −0.08 | 80.5 | 69.7 | 168,397 | +0.18 | 0.00 |
| **POOLED** | 2h | +0.40 | 0.00 | 109.2 | 95.6 | 168,361 | +0.62 | 0.00 |
| **POOLED** | 4h | +0.36 | +0.11 | 144.7 | 130.6 | 168,324 | +0.78 | +0.15 |
| **POOLED** | 8h | −1.10 | −0.80 | 192.3 | 183.7 | 168,038 | −0.28 | −0.44 |
| **POOLED** | 24h | −4.15 | −3.67 | 328.3 | 351.8 | 167,173 | −1.53 | −2.79 |

TRAIN split (same file, `split=="train"`, for comparison — 583,032 pooled entries):

| coin | horizon | neut mean | neut median | N (train) | raw mean | raw median |
|---|---|---:|---:|---:|---:|---:|
| BTC | 1h/2h/4h/8h/24h | −0.03 / +0.23 / +0.66 / +1.65 / +0.28 | +0.17/+0.45/+0.92/+1.53/+0.04 | 237,593 | −0.02/+0.02/+0.14/+0.65/−3.62 | 0.00/+0.10/+0.44/+0.53/−3.56 |
| ETH | 1h/2h/4h/8h/24h | +0.31/+0.66/+1.13/+2.29/−7.11 | +0.22/+0.47/+0.68/+1.84/−8.07 | 153,563 | +0.30/+0.63/+0.63/+1.53/−9.53 | +0.24/+0.45/+0.32/+1.22/−10.72 |
| SOL | 1h/2h/4h/8h/24h | +0.55/+1.62/+3.24/+5.60/+3.53 | +0.35/+1.10/+2.81/+5.34/+1.74 | 109,944 | +0.63/+1.31/+2.30/+4.51/−4.29 | +0.42/+0.89/+1.90/+4.32/−5.70 |
| HYPE | 1h/2h/4h/8h/24h | +0.36/−0.15/−1.72/−0.11/−17.30 | +0.32/−0.23/−2.25/−0.31/−18.11 | 81,932 | +0.42/−0.31/−1.60/−0.55/−22.86 | +0.36/−0.42/−2.04/−0.67/−24.08 |
| **POOLED** | 1h/2h/4h/8h/24h | +0.24/+0.61/+1.05/+2.06/−2.83 | +0.20/+0.50/+0.90/+2.00/−3.18 | 583,032 | +0.24/+0.51/+0.63/+1.30/−6.51 | +0.09/+0.27/+0.44/+1.14/−6.93 |

(Full split×coin×horizon×{mean,median,std,IQR,N} table for raw and neut, TRAIN+TEST, is cached at
`/private/tmp/claude-501/-Users-corywagamaneure-bablyon/048a04a6-ba4c-4990-aa6a-a3eae1a7cb1c/scratchpad/neut_termstructure_stats.parquet`
— session scratch, not a repo artifact; regenerate from `out/cohort_K_entries.parquet` in ~2s if needed.)

### 3. Raw vs neut contrast — how much of raw is just coin drift

- **BTC, ETH:** neut and raw are close at every horizon (within ~0.3–2.7 bp of each other) — BTC/ETH
  had comparatively little net coin-month drift over this window, so the "coin went up/down" component
  of raw markout is small for these two. The 24h gap is the largest (BTC raw −4.84 vs neut −2.71,
  i.e. ~2.1bp of the raw 24h number IS coin-month drift for BTC in TEST).
  ETH 8h: raw ≈ 0.00, neut +1.16 — a case where stripping ETH's own down-drift *reveals* a positive
  underlying skill residual that raw was masking.
- **SOL:** neut ≈ raw at 1h–8h (SOL's TEST-month drift was small); 24h neut (+4.49) vs raw (+3.46) diverge
  more, again because 24h accumulates more of the month's drift.
- **HYPE — this is where "how much of raw is just coin drift" is answered starkly.** Raw 24h markout is
  **mildly positive (+2.77 bp)**, but neut 24h is **−18.64 bp** — a **~21 bp swing**. HYPE had a large
  positive coin-month drift in the TEST window (the "HYPE hump" noted in prior EDA/memory) that was large
  enough to flip the *sign* of the 24h number once removed: the cohort's HYPE positions were, on a
  drift-adjusted basis, actually losing money at 24h, but riding HYPE's own rally made raw markout look
  flat-to-positive. This is the clearest quantitative illustration in this cohort of "raw markout can be
  almost entirely a coin-drift artifact rather than skill" — the entire reason Stage K/L/M treat `neut`
  (not raw) as the skill-measurement estimand, and why per-coin residuals (e.g. the Stage K "SOL/HYPE
  4h neut CI-excludes-0" finding) must always be read net of this caveat.
- **Term structure shape (POOLED, TEST, neut):** roughly flat/small near 0 at 1h–4h (+0.06 to +0.40 bp),
  turns negative at 8h (−1.10) and more negative at 24h (−4.15) — this pooled negative drift at longer
  horizons is dominated by HYPE's large negative 24h neut cell (N=34,497 of the 167,173 pooled 24h rows);
  BTC/ETH/SOL alone are flat-to-mildly-positive through 8h. **Caveat:** this is an unweighted, per-entry
  pooled mean — it is NOT the wallet-equal-weighted, cluster-bootstrap-CI'd estimand Stage K's formal test
  used (`src/cohort_K_analyze.py::cohort_ew`, which takes per-wallet mean first with a ≥10-entry floor,
  then equal-weights across wallets, then wallet-bootstraps a 95% CI). The formal Stage K TEST numbers
  (equal-weight, with CI) were: **1h −0.2 / 2h −0.1 / 4h +0.5 [−0.8,+1.9] / 8h −1.5 / 24h −4.3** (neut;
  ledger, `docs/FINDINGS_LEDGER.md` line ~373) — reassuringly close in shape/sign to the unweighted table
  above (both show near-zero 1h–4h, negative-and-growing 8h/24h), which is a light cross-check that the
  entry-weighting choice doesn't flip the qualitative picture, but **only the equal-weight+CI numbers are
  the calibrated, report-ready inferential result** — the table above is descriptive/facts-gathering only,
  no CI, do not quote it as a significance claim.

### 4. The 8h persistence-peak framing (why `neut_8h` specifically, from the ledger)

Per `docs/FINDINGS_LEDGER.md` (Stage M2, lines ~500–519 and ~608–612): **rank-persistence of wallets'
neutralized markout was tested across horizons and found to peak at 8h, not 24h or 4h.** Specifically
(audit-agent #10, corroborating the bug-corrected M2 recurrence result): *"the persistence is a slow-info
TERM STRUCTURE peaking at 8h (+0.219 [+0.154,+0.282]), monotone 1h→8h, robust to drop-HYPE/SOL and
BTC-only, stronger with reliability-weighting → 4h/equal-weight was mildly conservative."* This is a
**rank-IC term structure** (does a wallet's PAST neut markout rank predict its FUTURE neut markout rank,
by horizon) — a different quantity from the per-entry mean levels in the table above, but computed on the
same `neut_{4,8,24}h` columns of this same cohort_K_entries file.

Because of this 8h peak, the canonical persistent-wallet cohort (`src/cohort_M_freeze.py`, ledger
line ~608–611) was built by ranking wallets on **`neut_8h`** specifically: TRAIN-only, top-decile in
≥2 of 6 rolling TRAIN months by `neut_8h` recurrence → **121 wallets** (PRIMARY; STRICT ≥3-month
recurrence version = 28 wallets), persisted to `out/cohort_M_frozen.{txt,parquet}`. So `neut_8h` is not
an arbitrary horizon choice in this table — it is the specific column the downstream persistence/
deployability arc (Stages M1–M4) is built on, because 8h is where the *cross-time-predictability* of the
neutralized signal was strongest, even though the *level* of neut markout at 8h (per the table above) is
mildly negative pooled in TEST. (Those are not contradictory: a wallet's neut_8h RANK can be predictive
of its own future neut_8h rank even while the cohort's pooled neut_8h level is ~flat-to-negative — rank
persistence is about relative ordering, not the absolute mean.)

### 5. Provenance / sourcing chain

- `out/cohort_K_entries.parquet` ← built by `src/cohort_K_price.py` (Stage K Job C) ←
  reads `out/entries/part_*` (already-built per-fill entry table, filtered to the frozen
  `out/cohort_K.txt` wallet list) + `mkcommon._load_bars()` (5-min bar grid per coin).
- Cohort definition (`out/cohort_K.txt`, 1,694 wallets): `taker_share ≥ 0.70` AND `n_train ≥ 200`
  AND median taker hold ∈ [1h, 24h] AND `n_copyable ≥ 100` — see `docs/STAGE_K_ARCHITECTURE.md` §1.
  Outcome-independent by construction (selection never touches the markout outcome).
- Architecture/design doc: `docs/STAGE_K_ARCHITECTURE.md` (§3 estimands — note the coin-day vs
  coin-month discrepancy flagged in FACTS §1 above; §4 regime tags; §6 power/MDE/positive-control
  gates, all passed per the ledger).
- Ledger entries: `docs/FINDINGS_LEDGER.md` Stage K (lines ~361–399), Stage L (~403–429), Stage M2
  (~500–533), canonical cohort freeze (~608–612).

---

## FIGURES-TO-MAKE

1. **Neut term-structure line plot.** X-axis = horizon (1h,2h,4h,8h,24h, evenly spaced categorical,
   not log-time, to avoid implying a continuous process), Y-axis = mean neut markout (bp). One line per
   coin (BTC/ETH/SOL/HYPE) + a bold POOLED line. Use TEST split as primary (out-of-sample), TRAIN as a
   thin/dashed reference. This directly shows the HYPE 24h collapse (−18.6bp) as an outlier line diverging
   from the other three, and the pooled negative slope from 4h→24h.
2. **Raw-vs-neut overlay (per coin, small multiples or paired bars).** For each coin×horizon cell, two
   bars/points (raw, neut) side by side — visually shows "how much of raw is coin drift" as the gap
   between the two series. HYPE 24h is the headline panel (raw +2.8 vs neut −18.6 bp — arrow/annotation
   showing the ~21bp drift correction). Consider a diverging "drift removed" bar (`raw − neut`, signed) as
   a secondary panel per coin×horizon — this isolates the *coin-month drift contribution* itself as a
   quantity, which is arguably the more direct answer to "how much of raw markout is just coin drift."
3. **(Optional, ties to §4) 8h-peak annotation panel.** Not from this file's data (would need
   `cohort_M2_recurrence.py` output / ledger numbers, not re-derivable from `cohort_K_entries.parquet`
   alone) — a small inset or footnote figure showing the rank-IC-by-horizon curve (4h/8h/24h: 0.081/0.093/0.085
   adjacent-fold IC) alongside the mean-level term structure, to visually explain *why* neut_8h (not neut_4h
   or neut_24h) was chosen as the persistence-cohort-building column, since the two curves (level vs
   predictive-IC) are answering different questions and could otherwise look inconsistent to a reader.

## GAPS

- **Architecture-doc / code mismatch on neutralization grain.** `docs/STAGE_K_ARCHITECTURE.md` §3 says
  "coin-day-mean of raw"; the actually-executed `src/cohort_K_price.py` computes a **coin-MONTH** drift
  (`ym_of`, year*100+month grouping). The ledger's own prose is inconsistent too — Stage K's ledger entry
  (line 370) correctly says "coin-month drift-strip 'neut'" while §3 of the architecture doc still says
  coin-day. **This report uses the code (coin-month) as ground truth**, per the task instruction to read
  source; flagging so the team doesn't cite the architecture doc's "coin-day" language as the operative
  definition in the final write-up. (This is a separate, coarser-grained neutralization from the
  **wallet-persistence-arc's** "coin-day-neut" language used in Stages E–H, which is a *different*
  artifact/pipeline (`markout_stats.parquet`-based) — the two "neut" quantities across this study's stages
  are NOT the same grain and should not be conflated in the report; this doc's neut is specifically the
  cohort_K/coin-MONTH one.)
- **No CI on the table above.** Per CLAUDE.md convention, only Stage K's formal wallet-equal-weight,
  bootstrap-CI'd numbers (quoted in §3) are the calibrated, citable inferential result. The coin×horizon
  table in this doc is descriptive (entry-level, unweighted, no CI) — useful for the term-structure shape
  and the raw-vs-neut magnitude contrast, not for a significance claim. If the report wants per-coin CIs
  on neut markout (e.g. "is HYPE's −18.6bp 24h neut real"), that requires an additional (cheap,
  in-RAM) wallet-clustered bootstrap per coin×horizon on this same file — not yet computed, but doable
  without re-touching the tape.
- **std/IQR are entry-level dispersion, not sampling-error dispersion.** The std values (e.g. BTC 24h
  neut std=224bp) describe how spread-out individual entries are, not the uncertainty on the mean — do
  not divide by sqrt(N) naively for an SE, since entries are NOT independent (same-wallet, same-coin-day
  clustering; Stage K's own MDE calc uses per-wallet aggregation first for exactly this reason).
- **HYPE's 24h neut number is dominated by N≈34.5k entries but likely far fewer *independent* coin-days/
  wallets** — the −18.6bp is a striking number but this doc has not re-derived its cluster count; treat
  as a "fact to include with a footnote," not a stand-alone headline stat, until Stage K's own gates
  (already passed, per ledger) are cited alongside it.
- **This doc does not re-derive or re-verify Stage K/L/M's inferential verdicts** (those are already
  ledgered as: no aggregate copyable edge at cohort level — EARNED powered null; a small SOL/HYPE-specific
  4h neut residual that is most likely generic short-horizon reversal, not wallet skill; 8h-horizon rank
  persistence real-but-modest, method-scoped, not yet shown to survive net-of-cost). This doc's job was
  purely to document the term-structure FACTS and the exact neutralization mechanics for the report;
  the significance/deployability narrative should be pulled from the ledger sections cited above, not
  re-argued from this table.
- **5m/15m/30m/12h columns exist in the underlying pricing code path (`mkcommon.HORIZONS`) but were not
  requested/reported here** — only 1h/2h/4h/8h/24h are materialized in `cohort_K_entries.parquet` (the
  `HZ` dict in `cohort_K_price.py` only writes those 5). If the report later wants finer sub-hour
  granularity, that requires a re-run of Job C (a tape/bars pass) — not a light aggregation.
