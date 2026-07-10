# Alt-breadth cohort — audit response (BINDING; 4-agent swarm, 2026-07-09)

Swarm audited `ALT_BREADTH_ARCHITECTURE.md` pre-build (leakage/firewall, universe/data-integrity, stats-rigor,
alt cost-realism). Verdict: **worth building, but the central framing was wrong** and there are binding leak/
construction fixes. This file supersedes the arch doc where they conflict. Build `alt_flow.py` to THIS.

## THE REFRAME (stats-rigor F1 — design-breaking)
"Breadth lifts gross-per-crossing" is FALSE. For a dollar-neutral rank book at gross-leverage 1,
gross/crossing ≈ transfer-coeff × IC × σ_xsec(resid) — **N cancels**. Breadth buys IR = IC·√BR → higher SHARPE
+ lower MDE, NOT per-crossing economics. The only lever on gross/crossing is DISPERSION: alt idio vol ≈120 bp vs
majors ≈69 bp (~1.7×), xsec dispersion ~84 vs ~58 bp (~1.45×) → projected alt gross/crossing **≈ 1.8–2.5 bp**
(vs majors 1.27), NOT a multiple-× jump. **Sell the study as: breadth → a POWERED, earnable taker verdict + a
tighter maker read — not "breadth makes taker clear cost."**

## PRE-REGISTERED BARS (lock before the run)
- **TAKER cost/crossing (real, from asset_ctx impact px, top-50 alts):** half-spread median ~3.0 bp → per-crossing
  = fee + hs ≈ **7.6 bp base / 5.5 bp top-tier**. Clears iff gross/crossing ≥ that; projected 1.8–2.5 → **expect
  an EARNED (powered) NEGATIVE**, deficit ~3–5.8 bp. Clearing top-tier needs alt IC ≈ 0.09 (~3× majors 0.030).
- **MAKER net/crossing = gross/crossing + earned_half_spread(~3 bp alt) − fee(~0) − adverse_selection.** Break-even
  cushion ≈ 1.8 + 3 ≈ **4.8 bp** (wider than majors' 1.27 vs 0.4). "Passes" ONLY if (a) zero-cost gross Sharpe CI
  excludes 0 (majors +4.69 [1.22,8.11]) AND (b) a modeled adverse-selection haircut still clears. Without a fill
  model the maker verdict is capped at **"promising-unresolved," non-deployable** (same ceiling as majors).
- **Partial IC | OFI** is the load-bearing quantity: pre-register CI-excludes-0 at 1h as the primary pass; a tight
  CI on gross/crossing BELOW alt taker cost = earned taker negative and DOMINATES any book-level lean.

## BINDING BUILD FIXES
**Leakage / freeze (leakage agent):**
- **F1 H-embargo:** exclude the last H train buckets from cohort alignment (their fwd_resid reaches into TEST).
  Add `wb.h + H*3600000 < first_test_hour_ms` to freeze/pool joins; re-apply at every walk-forward fold seam.
- **F2 alt-sourced:** do NOT reuse the majors `build_wallet_tables` (`FROM fills` = majors, "≥50 lifetime MAJOR
  trades" selector). Write an alt version over `alt_flow`: eligibility from alt activity; cohort/wallet flow =
  Σ flow_signed over BOTH crossed; OFI = Σ flow_signed FILTER(crossed=true). `alt_flow` has NO is_vault — drop the
  vault filter and note it (or source a vault list). Add Σ flow_signed ≈ 0 sanity (two-sided).
- **F4 causal LOO index:** per-coin panel on the FULL hourly calendar grid (NaN when out/newborn); LOO index from
  the THEN-CURRENT universe mask excluding coin i; keep cumsum trailing-beta + MIN_BETA_OBS (out-of-fit). No
  compaction across list/delist gaps.
- A3 re-bucket (5-min→hourly `bucket - bucket%3600000`) VERIFIED leak-safe (grid identity) — assert it.

**Universe (data-integrity + stats-rigor — corrects a FACTUAL error, also wrong in memory babylon-hl-hist):**
- `day_ntl_vlm` is **TRAILING-24h ROLLING**, NOT daily-cumulative (goes up AND down intraday; ~17,793 decreasing
  steps across coins on one day; midnight is continuous, no reset). Correct universe: ADV proxy = the **LAST
  per-minute snapshot of each prior coin-day** (`row_number() OVER (PARTITION BY coin,day ORDER BY ts DESC)=1`) —
  **NEVER `max(day_ntl_vlm)`** (non-monotone → max grabs an intraday peak, disagrees with the true boundary for
  177/225 coins by up to $936M). Average those over the **30 prior days (all < t)**; no intraday look-ahead.
  ≥30d listing history; drop-on-delist (0 delists this window — defensive no-op); time-varying re-rank (no static
  top-N = survivorship — 29 mid-window new listings, e.g. ZEC, make this binding); k-remap handler defensive
  (7 k-coins, none with a non-k twin → no rename events). **Reproduced: $2M floor → 49 names, $1M → 70.**
- **Drop 3 low-book-coverage names** (LAUNCHCOIN, MKR, AI16Z, <90% impact coverage) — do NOT default their cost.

**RUN GATE (data-integrity — do NOT run until ALL hold; TRAIN 202508–202602 is complete & safe to build/freeze now):**
- `alt_flow` 334/334 days present, incl. the isolated **2026-06-02** (real TEST hole = 04-18→05-16 block + 06-02).
- `asset_ctx` per-day complete (assert BTC rows to ≥23:00). **2026-05-30 is a PARTIAL price day (ends 06:57)** —
  re-ingest it or DROP 2026-05-30 from both flow+returns. asset_ctx has no 202607 → end-of-June forward windows run
  off the price series (right-censor those buckets, minor).

**Factor model (stats-rigor F4 — else the positive is un-prosecutable):**
- BTC + ETH + **3–5 causal sector/PC factors** (meme / L1 / DeFi / AI, OR top 3–5 PCs of the trailing alt-return
  matrix on the same rolling window). Residual-adequacy diagnostics: (i) no large sector off-diagonals post-
  neutralization; (ii) residual-on-sector-dummy betas ≈ 0; (iii) **sector-neutralized placebo** (random cohorts
  matched to the informed cohort's sector exposure).

**Inference / power (stats-rigor F3):**
- Alt MDE ≈ 0.008–0.010 (~2× tighter than majors) BUT **effective-N ≈ 15–25, not 50** (sector correlation).
- Bootstrap: **day-blocks (or moving block ≥ H+drift), NOT single-hour** (slow-drift autocorrelation, R6). Keep the
  time-block unit (never resample coin-hours independently). Report effective independent-block count with every CI.
- Per-coin sign test clustered on **sectors**, not the 50 coins.

**Cost realism (cost agent):**
- Per-coin impact half-spread is size-referenced (~$20k clip), not BBO — tighter for small clips on liquid names,
  realistic for size. State book results at a stated notional. **Capacity cap ≈ $0.2–1M gross** (thin-tail names
  bind); consider a higher ADV floor as a capacity lever.
- **Maker adverse-selection is UNMEASURED and can erase the +1.4 bp credit.** Resolve with data in hand: a targeted
  per-fill RE-PULL of the ~50 universe names from Reservoir → simulate resting-quote fills → measure post-fill
  signed markout on cohort names. (The kept 5-min flow aggregate dropped per-fill px, so this needs a scoped re-pull.)

## OVER-CARRY GAUNTLET (stats-rigor F5 — bake in BEFORE the run; equal standing to the steelman)
1. **Lock knobs to the majors findings:** primary horizon **1h ONLY** (2h was noise); `COHORT_Q=0.20`; **Variant A
   (cross-alt cohort) is PRIMARY**, Variant B (per-coin/HYPE-specialist) a SEPARATELY pre-registered hypothesis,
   not a rescue. Any per-coin/sector winner is an **argmax-of-50** → report the full distribution + clustered sign
   test, never the max as headline.
2. **Multiplicity across the whole arc:** placebo + walk-forward ARE the multiplicity controls — require both.
3. **"Alts EX majors" cut:** exclude BTC/ETH/SOL/HYPE from the book; confirm IC survives on pure alts (not the
   majors result re-expressed via the index or HYPE-heavy cohorts).
4. **Walk-forward mandatory** + **TEST-hole handling:** drop the 2026-04-13→05-16 buckets (don't interpolate);
   confirm the hole isn't coincident with a flattering/harming regime.
5. **Separate prosecutor agent** ("prosecute-the-positive / null-the-residual"): sector-beta leak, majors-in-
   disguise, effective-N inflation, argmax across coins/sectors/horizons/variants, wallet-pool overlap. Equal
   standing to the steelman pass.

## FIREWALL — confirmed clean (both agents)
`alt_flow` is a SEPARATE `derived/alt_flow/` view (schema.py DATASET_GLOBS, `simple_view_sql`, never
`fills_views_sql`); no `src/babylon`/`gate_a` import of research.data or read of alt_flow. TODO: add the SPEC-
mandated CI grep-guard as an actual test. Reconcile RESERVOIR spec §0 wording (`alt_fills`→`alt_flow`).
