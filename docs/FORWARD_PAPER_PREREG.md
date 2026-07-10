# PRE-REGISTRATION — forward paper test of the rolling-WF basket process (frozen 2026-07-10)

> Sealed in git: commit `c9fad88` (2026-07-10) — the code+docs state of record for this protocol.

The adjudicating experiment for the rolling walk-forward result (label of record: "suggestive,
regime-concentrated, variant-selected, placebo-4σ non-random; n=5 months" — 4-agent swarm 2026-07-09).
Live system: `babylon-basket` on droplet 167.71.29.107 (`src/babylon/follow/basket_main.py`), paper-only.
July-2026+ data is untouched by any analysis in this program — this is the de-asterisked test.

## Frozen procedure (v1 — exactly what was walk-forward tested)
- Basket: top-20 (wallet, coin, horizon) by the frozen L=6 rolling rules (`research/data/rolling_wf.py
  live`), refreshed MONTHLY (batch pipeline runs locally, `scripts/deploy_basket.sh` ships + restarts).
  Record each refresh's discovery window here:
  - refresh #1 (deployed 2026-07-09): discovery 2026-01-01 → 2026-06-29, basket sha 1e53a112cac97976.
- Copy rule: enter 2 min after a basket wallet's detected open in ITS basket coin; flat $50/tranche;
  exit on the row's frozen horizon clock (never mirror wallet exits); fees 4.5bp/side + 1bp impact in
  the paper fills. No event-level taker/TWAP filter; leading opens KEPT (config epoch 2: the
  skip_leading bug was fixed 2026-07-09 23:13 UTC — epoch 1, 22:26–23:13 UTC, silently dropped opens
  and is excluded from evaluation).

## Frozen evaluation (declared BEFORE any forward data accumulated)
All series computed offline from `realized.jsonl` (per-tranche atoms; weighting is analysis-time).
- **PRIMARY: wallet-day equal weight** — per wallet-coin per UTC day mean of raw_bps net of the 5bp
  round-trip line; per-day basket = mean over active wallet-coins; day-block bootstrap. This is the
  estimand the historical walk-forward validated. Verdict quantities: net mean, 95% CI, MDE,
  months>0 count, and the **ex-HYPE line reported with equal standing** (HYPE carried the backtest).
- **SECONDARY: event-weighted** — plain mean over tranches (what flat sizing realizes).
- **EXPLORATORY (reported, never the verdict):** (a) prior-window-recurrence-weighted — weight
  wallet-coins by # consecutive PRIOR monthly selections (the deployable analog of the +43bp
  recurrent-5 finding, which carried look-ahead); (b) q-weighted — weight by −log10(disc_p).
- **EXCLUDED: discovery-magnitude weighting** (∝ disc_gross_bp) — pre-registered OUT: the steelman
  audit showed harder selection on the point estimate degrades OOS (winner's curse, top-decile −44bp).
- Minimum evaluation window: 3 calendar months / ≥60 basket-active days before ANY verdict is read.
  Earlier peeks are operational health checks only, never performance reads.

## AMENDMENTS (declared before ANY performance read; forward window began 2026-07-09)
**A1 (2026-07-10) — evaluation formula corrected: the original "raw_bps net of 5bp" DOUBLE-COUNTS costs.**
Audit finding (CRITICAL, estimand-parity agent): `realized.jsonl:raw_bps` is computed from PAPER FILL prices
into which the executor already folds 4.5bp fee + 1.0bp impact PER SIDE (= 11.0bp round-trip; verified
`fill_model.py:106`, `paper.py:100`, pinned by `test_raw_bps_embeds_fee_and_impact_roundtrip`) plus the real
spread + depth-walk. Subtracting another 5bp would rig the primary toward a false null. CORRECTED frozen
formula (f = (fee_bps+impact_bps)/1e4 from that epoch's manifest line; d = direction):
  1. Load realized.jsonl, DEDUP BY id FIRST-WINS (= RealizedJournal.load; at-least-once delivery means
     crash-restart duplicates are expected). Drop config-epoch-1 rows (2026-07-09 22:26–23:13 UTC).
  2. Un-fold: P_in = entry_px/(1+d·f); P_out = exit_px/(1−d·f);
     gross_vwap_bps = d·(P_out/P_in − 1)·1e4   (≈ raw_bps + 11.0; still pays real spread+depth — a
     conservative residual vs the oracle-mid backtest gross, reported, not removed).
  3. PRIMARY atom: net_i = gross_vwap_bps_i − 5.0 (≈ raw_bps + 6.0). NEVER raw_bps − 5.
     ALSO report raw_bps unmodified as the all-in deployable line (real 11bp+spread costs, nothing further).
  4. Aggregate exactly as the backtest: (wallet, coin, UTC day of entry_ms) means → per-day basket mean →
     day-block bootstrap; net mean, 95% CI, MDE, months>0, ex-HYPE at equal standing.
  5. Report alongside the verdict: realized entry_lag_ms distribution, (exit_ms−entry_ms)−horizon
     distribution, and coverage counters incl. entry_nofill (thin-book drop diagnostics).
**A2 (2026-07-10) — estimand label:** the live series is COPIER-ANCHORED `[t_open+lag, t_open+lag+h]` (both
endpoints shift by the ~2min lag), a deployable variant of the backtest's trader-anchored window. The verdict
is self-contained on the live series (CI-based), never a numeric match to the backtest's +16.5.
**A3 (2026-07-10) — honest baseline restated (cross-selector audit):** the backtest supporting this deployment
is an underpowered, selection-inflated positive — family-adjusted p≈0.17 (3 selectors on the same 5 forward
months; max-T), month-clustered p≈0.09–0.10, HYPE-concentrated (ex-HYPE net +1.4bp). Interim reads must use
this baseline; the forward run is the arbiter precisely because of it.

## Verdict rules (frozen)
- Process CONFIRMED iff the PRIMARY net CI-low > 0 over the evaluation window AND the ex-HYPE point
  estimate > 0. Earned-null iff MDE ≤ 8bp and CI-high < 8bp. Else INCONCLUSIVE → extend one month at
  a time to a 6-month cap, then close as inconclusive.
- A v2 (informedness-weighted sizing) may be pre-registered ONLY as an A/B against the running v1,
  never as a retroactive re-weighting of v1's verdict.
