# Alt-breadth wallet-cohort study — architecture

> ⚠ **`ALT_BREADTH_AUDIT_RESPONSE.md` (4-agent swarm) is BINDING and supersedes this doc where they conflict.**
> Key corrections: (1) breadth buys STATISTICAL POWER (Sharpe/MDE), NOT gross-per-crossing (N cancels in a
> dollar-neutral rank book) → expect a *powered* taker negative + a wider-cushion maker lead; (2) `day_ntl_vlm`
> is TRAILING-24h ROLLING (not "cumulative") → rank on the last-snapshot-per-prior-day, never max(); (3) factor
> set needs sector/PC factors (single alt-index leaks sector momentum); (4) H-embargo, alt-sourced flow,
> day-block bootstrap, per-coin cost bars, maker adverse-selection sim. Read the AUDIT_RESPONSE before building.

**The one structural lever the steelman swarm left open.** The informed-cohort signal is real, placebo-hardened,
walk-forward-robust at 1h — but TAKER-dead and only a promising MAKER lead, because on **4 majors** the gross is
breadth-starved (~+1.5 bp/hr, gross/crossing 1.27 bp < fees). The swarm's verdict: the sole untested fix is
**cross-sectional breadth** — more independent names per unit of turnover. The Reservoir `alt_flow` tape (all
~180 coins, per-wallet 5-min signed flow) now makes that testable. This study re-runs the exact majors pipeline
on a ~50-name alt cross-section and asks: **does breadth lift gross/crossing above cost — taker or maker?**

## The central tension (state it up front, don't bury the cost side)
- **Breadth HELPS gross:** N independent residual bets per hour instead of 4 → higher gross-per-crossing at the
  same turnover (the majors book paid a crossing every hour for a 4-name spread; a 50-name book pays similar
  turnover for a far wider cross-sectional spread).
- **Alt spreads HURT cost:** majors half-spread ≈ 0.07–0.97 bp (taker cost ≈ all fee, ~4.9 bp). Alts are WIDER
  — impact half-spread ~3–10 bp on ADV-capped liquid alts → taker per-crossing ~8–15 bp, a *higher* hurdle.
- **So the taker question is genuinely open** (breadth↑ gross vs alt-spread↑ cost — net either way), and the
  **maker question flips FAVORABLE on alts**: a maker EARNS the (wider) alt spread and pays ~0 fee, so wider
  spreads help the maker economics. This study measures both.

## Data (firewalled research lane; no engine/gate_a)
- **`alt_flow`** (Reservoir, `data/derived/alt_flow/`): per (wallet, coin, 5-min bucket, crossed) signed-notional
  `flow_signed`. Cohort flow = Σ flow_signed over cohort wallets per (coin, bucket); **OFI = filter crossed=true**
  (two-sided tape → all-rows Σ=0). Re-bucket 5-min → hourly for the primary horizon.
- **`asset_ctx`** (all coins, per-minute): `mid_px` (returns; filter mid_px>0 — the 0 is HL's no-book sentinel on
  ~17% of alt rows), `day_ntl_vlm` (DAILY CUMULATIVE → end-of-day = that day's volume; the UNIVERSE input).
- Window 202508–202606; TRAIN month<202603 / held-out TEST month≥202603 (matches the majors study).

## Universe (point-in-time — the audit's binding fix)
- At each formation day t, rank coins by **trailing 30-day ADV** = mean of prior-30-days end-of-day
  `day_ntl_vlm` (uses only days < t → no look-ahead). Take **top ~50** above a ~$1–2M/day floor.
- Require ≥30 days listing history (kills newborn-illiquidity noise); drop on delist; handle k-prefixed remaps
  (kPEPE…). Membership is TIME-VARYING (re-ranked), NOT a static full-sample top-N (survivorship leak).
- Include BTC/ETH always (factor anchors); optionally carry HYPE/SOL for a majors-vs-alts contrast.

## Residual returns (factor-neutral, causal)
- Per coin, hourly log return from `asset_ctx` mid_px (last mid in the hour).
- Neutralize on **BTC + ETH + a leave-one-out equal-weight alt-index** (the cross-section's own common factor),
  rolling CAUSAL beta (trailing window ending at t; out-of-fit) — Gram-Schmidt or sequential residualization,
  same discipline as `xsec_statarb/leadlag.py` + `flow.py`. Forward residual over H buckets, POST-bucket (A3).

## Cohort (leak-frozen; two selection variants per the user's aggregation point)
- **Alignment** = mean over the wallet's TRAIN buckets of sign(flow_signed) × fwd_resid; rank, freeze **top 20%**.
- Variant A — **cross-alt cohort** (informed across the whole alt cross-section): the breadth play.
- Variant B — **per-coin / HYPE-specialist cohorts** (rank wallets on their coin-specific alignment): tests the
  user's point that pooling the SELECTION dilutes an HL-native/per-coin edge. Compare A vs B.

## Inference (the full majors gauntlet — nothing less)
1. **Partial IC | OFI** (cohort flow residualized on OFI) vs forward residual; block-bootstrap CI over
   time-blocks (preserves cross-name dependence); per-coin sign; naive IC + OFI positive-control.
2. **Placebo** — K random same-size cohorts from the same eligibility pool; informed must beat the random
   distribution (the make-or-break; majors gave p=0.033).
3. **Walk-forward** — expanding-train / forward-month folds; informed IC positive AND beats random across folds.
4. **Book** — cross-sectional rank (or conviction/IC-weighted) book over the ~50 alts, t+1 entry, hourly hold;
   cost from `asset_ctx` impact half-spread PER COIN + fee; report gross, turnover, **gross/crossing**, net
   (taker AND maker), break-even, zero-cost Sharpe. Compare to the 4-name majors book head-to-head.
5. **Over-carry gauntlet** (equal standing): argmax honesty on any conditional winner (coin/hour/conviction),
   multiplicity across the arc, non-independence of names; a tight null on the load-bearing quantity outweighs a
   downstream lean.

## Decision
- **Taker:** does breadth push net-of-alt-cost ≥ 0 where 4 majors could not? (earned negative if not, with the
  gross/crossing-vs-alt-fee gap shown).
- **Maker:** does the wider-alt-spread maker ceiling clear break-even with headroom (as majors did, SR +4.7)?
  This is the likeliest live outcome — and the alt breadth + wider earned spread both push it up.
- Either way: honestly labeled per the OVER-NULLING GATE (point estimate + CI + MDE + cross-unit + placebo).

## Memory / compute discipline
- alt_flow is ~3.2 GB / ~305 M rows. Aggregate MONTH-BY-MONTH to cached wb/agg parquet (mirror `flow.py`);
  `SET memory_limit`, `threads=1`; never a global scan. Cohort freeze over ~130k wallets × 50 coins × hourly is
  the heavy step — cache it. Re-bucket 5-min→hourly at read.

## Build order
1. This doc → **swarm audit** (data-integrity/universe-lookahead, firewall, stats-rigor, determinism).
2. Build `alt_flow.py` (universe + residual + cohort + inference) reusing `flow.py`/`book.py` machinery.
3. Run on the COMPLETE tape (334/334) — the Apr–May test-window days must be present first.
4. Ledger the result in `FINDINGS.md`; prosecute both directions before finalizing.
