# Stage J — Archetype decomposition of the top-markout cohort (RAM-safe)

**Origin (2026-07-05).** 3-agent read-only audit (contamination auditor / steelman / typology designer)
of the "no OOS persistence" null. User's economic objection: high-volume traders can't persistently trade
at a negative edge or they go broke → we must be mis-measuring or mis-pooling.

## Audit conclusions (converged 3/3)
1. **No maker-share filter/stratification/column exists anywhere in the ranked universe.** A high-freq MM
   clearing ≥30 taker openings is scored as if its taker leg were directional skill. `oos_persistence.py:143`
   eligibility = taker-entry count only.
2. **`individual_persistence.py` / `wallet_level_persistence.py` SELECT FOR contaminants** (≥2000 fills → MMs)
   and book maker-closing spread-capture PnL as copyable edge (`per_close` runs full ledger, no crossed mask).
3. **The existing realized-PnL null is NOT clean:** full-ledger (maker+taker mixed), $-vw so one whale blows
   it out (cohort OOS −30.9bp, CI [−72.9,+10.3] spans 0), and ≥2000-fill HFT-only → **mid/low-freq informed
   trader excluded by construction**. Spearman −0.102.
4. `taker_entries` is correct at the HL-position level (reduces/closes not scored) but **blind to cross-venue
   hedges by construction** (HL-long leg of a Binance-short hedge scored as bullish entry). Unclosable w/o
   external venue data; detectable only via signatures (funding capture, flatness, one-sidedness).
5. The OOS *measurement* itself is clean — no repeat of the Stage-E NaN-drop bug.
6. **`maker_taker_split.py` and `steelman_features.py` CRASHED (OOM), never produced output.** RAM, not choice.

## The decomposition (powered on the full ≥2000-fill 5859-wallet universe; 177-cohort = composition overlay)
Splits: TRAIN ts<2026-02-01 / EMBARGO Feb / TEST ts>=2026-03-01. **All classification features TRAIN-only.**

### Execution plan — SERIAL, one heavy job at a time, each `scan_parquet` batched/per-coin, ≤~1.3GB peak.
Never `read_parquet` the 3.3GB tape. ramguard.sh caps POLARS_MAX_THREADS=3, aborts if <800MB reclaimable.

- **Job 1 (RUNNING FIRST): `maker_taker_split.py`** (BATCH 500→150). Output `out/maker_taker_split.parquet`:
  per-wallet `mkshare_n/mkshare_v`, TAKER-ONLY ledger persistence (`trT_vw,teT_vw,trT_t,teT_t`), full-ledger,
  maker-vs-taker-closing PnL split. **Decisive first read:** Spearman(trT_vw,teT_vw) stratified by mkshare_v
  buckets {<0.2,0.2-0.5,0.5-0.8,>0.8}; does taker-only persistence turn positive in the low-maker stratum?
- **Job 2:** re-run/extend `steelman_features.py` (BATCH=300) → Pass-A tape features (mkshare_n/v, hold,
  funding_capture_bps, gross_turnover, cadence, time_in_pos_frac, coin_hhi). Load funding.parquet fully once.
- **Job 3:** Pass-B entry-structure over `out/entries` per-coin (reuse `cohort_forensics.wallet_descriptors`):
  add_frac, avgdown_rate (martingale), momentum, coin_hhi, long_frac, notl_cv.
- **Job 4:** Pass-C windowed taker-markout@24h (raw + coin-day-neut) per-coin (reuse `how_they_trade.fwd/daymean`);
  per-(wallet,coin,window), floor n>=30 train & test. `markout_stats.parquet` is full-window → MUST recompute.
- **Job 5 (in-memory):** archetype labels — rule tree (priority order), TRAIN-only quantile cutpoints:
  1 MM/LP (mkshare_v>=0.6 & exit_maker>=0.5) · 2 funding-farmer (|funding_capture|>=Q3 & time_in_pos>=Q3 &
  price-flat) · 3 HFT scalper (hold<15min & cadence>=Q3 & taker_share>=0.6 & turnover>=Q3) · 4 pure-taker
  directional (taker_share>=0.8 & hold>=1h & hhi>=median & funding small) · 5 mixed. Robustness: 2-of-3 soft
  membership + optional k=5 KMeans(SEED=12345). Overlay: archetype histogram of the 177 cohort_wallets.txt.
- **Job 6 (in-memory):** per-archetype 4-part test — top-quartile TEST markout (raw+neut) w/ (wallet,coin-week)
  clustered bootstrap CI; per-archetype MDE = 2.8×SE_cluster + synthetic +10bp recovery check; cross-coin sign
  test (eff-N<4 caveat); Spearman(train,test) w/ clustered CI. Verdict per cell: live-positive / inconclusive /
  method-scoped-negative (the last EARNED only with tight CI AND MDE<=care-about).
- **Job 7:** separate steelman + "prosecute the positive" agents, then update FINDINGS_LEDGER Stage J.

### Verdict rubric (both error directions gated per CLAUDE.md)
- CONFIRM hypothesis: directional-taker TEST markout CI excludes 0 (MDE<=+10bp) while MM/funding/HFT <=0.
- INCONCLUSIVE: directional-taker leans positive, CI admits 0, MDE>care-about → surface point est + direction.
- METHOD-SCOPED NEGATIVE: directional-taker tight CI around 0/neg WITH MDE<=care-about (now constructible at
  N=5859, unlike the 30-entry cohort stages).
- Report raw AND coin-day-neut; neut is skill-measurement basis only, NOT a deployable return (Stage F).
