# Alt-complex-timing paper test — PRE-REGISTRATION (frozen 2026-07-10, BEFORE go-live)

Forward, out-of-sample adjudicating test of the **alt-complex-timing signal** (FINDINGS Result 9). The in-sample
evidence: gross signal real (placebo z≈4, momentum-independent), cost-surviving book positive in 4/4 OOS months but
**power-blocked** (net Sharpe ~1.3, CI incl 0 — 4 test months can't resolve it). This paper test accumulates the
genuine forward record that can. **PAPER ONLY — no signing/capital.** Freeze these rules now; do not revise
retroactively (the majors follower's `FORWARD_PAPER_PREREG.md` is the precedent).

## The signal & book (frozen)
- **Cohort:** RECENCY-GATED top-N wallets by TIMING skill (`export_timing_cohort.py`; cohort_sha in
  `data/derived/alt_timing/cohort.json`). Ranked by alignment of hourly directional lean with the forward
  BTC/ETH-neutral alt-index move, **restricted to wallets active in the last 2 tape months (≥40 alt-hours)** so the
  cohort is actually pollable live. **Why the gate (2026-07-10):** the first freeze (top-150 by raw mean score) was
  13/150 live on the dry-run — the strongest historical timers had churned OUT; their offline z≈4 is NOT
  live-harvestable. The signal is a **breadth** effect, so among live wallets it takes many more of them to
  reconstruct: recency-gated walk-forward gives **top-1500 ≈ mean z +2.0 @H1 (3/4 folds), top-2500 ≈ +2.3** — a
  real but MATERIALLY WEAKER signal than the offline ideal, and weakest in the most recent fold. Deployed N=1500
  (pollable ~1 call/sec → ~25 min/sweep). Re-ranked/refreshed MONTHLY (same recency gate) on the extended tape.
- **Signal:** each hour, poll the cohort's alt fills → `tilt = (#net-long − #net-short)/(#active)` across the alt
  universe. The follower LOGS the raw hourly tilt + mids; book PnL is computed OFFLINE. **Primary horizon H=1h**
  (the recency-gated live cohort's signal is strongest short-horizon — WF above; H4/H8 SECONDARY). Position =
  sign(smoothed tilt).
- **Instrument:** the frozen tight 7-name basket (XRP, PAXG, DOGE, SUI, BNB, LINK, AVAX), equal-weight, hedged vs
  BTC/ETH. Paper-mark against the BTC/ETH-neutralized basket return. Flat notional per position.
- **Cost:** charge realized half-spread (per-coin from asset_ctx, ~1.8 bp basket) + fee. Report net at fee ∈
  {0 (maker-fee), 2.4 (top-tier taker), 4.5 (base taker)}.

## PRIMARY metric & verdict rule (frozen)
- **PRIMARY:** annualized net Sharpe of the sign(smoothed-tilt) book at **top-tier taker fee (2.4bp)**, with a
  day-block bootstrap 95% CI, over the forward window only (hours after each cohort export's as_of).
- **SECONDARY (equal standing):** net Sharpe at maker-fee(0) and base(4.5); the raw signal IC vs forward index
  (does the live tilt still predict, z vs random-cohort shuffle); per-month sign.
- **CONFIRM** = PRIMARY CI-low > 0 AND positive in ≥⌈70%⌉ of forward months. **KILL** = PRIMARY point estimate ≤ 0
  over a ≥6-month window. In between = CONTINUE (still power-accumulating).
- **MIN WINDOW before ANY verdict: 6 forward months or 120 active trading days**, whichever later. (In-sample MDE
  logic: SR~1.3 needs ~2–4 yr for taker significance; expect CONTINUE for a long time — the maker path, if it
  works, is what clears it faster.)

## Guards (frozen)
- Cohort/basket/config are FROZEN per export; monthly refresh is the ONLY allowed change, logged with its as_of +
  cohort_sha. No horizon/smooth/deadband re-tuning on forward data (that would re-open the argmax we just closed).
- Forward window = strictly hours AFTER the active export's as_of (no scoring-window contamination).
- 202605-style weak months are EXPECTED (regime dependence seen in-sample) — do not stop/restart around them.
- A `v2` (e.g. timing-conviction-weighted sizing, or the maker-fill variant) runs only as a pre-registered A/B
  vs the running v1, never retroactively.
- Log every hour: tilt, smoothed, position, basket return, per-fee net, cumulative. State is append-only.

## Excluded / not claimed
- Any capital deployment (paper only). Any config picked by looking at forward returns. Any verdict before the min
  window. The maker-fill economics are a SEPARATE unresolved question (shared with majors Result 4) — if resolved
  favorably it lifts the numerator and shortens time-to-verdict, but is not assumed here.
