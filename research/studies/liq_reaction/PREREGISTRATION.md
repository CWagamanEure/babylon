# liq_reaction — PREREGISTRATION (A1′, redesigned after the 2026-07-07 design audit)

**Status: REDESIGNED, NOT YET FROZEN.** The original A1 (unconditional pooled fade-mean at 15 min on
`oracle_px`) was withdrawn: a 5-agent design audit found it **inconclusive-by-construction** (an over-null
trap) — see `AUDIT_RESPONSE.md` for the finding-by-finding trail. This doc is the powered redesign (A1′).
It is frozen only after the **EDA feasibility gate** (§7) fills the pinned constants; if that gate says the
data can't resolve it, we say so and stop (anti-ratchet), we do not loop the blind test.

## 0. Why the redesign (the audit's core result)
Three independent reviewers reached the same place: the frozen headline must be the leg that can *resolve*
the question, not the leg that averages it away. Four load-bearing changes:
1. **Price = `mid_px`, not `oracle_px`.** `oracle_px` is an external CEX-median index blind to HL's own
   book overshoot → a false NULL. `mid_px` is the traded book mid (>0 for majors) and, unlike `mark_px`,
   is not EMA-smoothed (so no relaxation artifact). The bounce artifact is neutralized by **never entering
   at the liq fill price** + placebo-differencing (below), not by hiding in the oracle.
2. **Estimand = placebo-differenced ABNORMAL reversion.** `forced_dir = −sign(start_position)` is nearly
   `−sign(recent move)`, so raw `forced_dir·fwd_ret` is a generic "reversion-after-a-big-move" detector.
   Subtract a **signed-move-and-vol-matched non-liq placebo** → what remains is the liquidation-*specific*
   reversion. This is simultaneously the confound control AND the variance reduction that makes it powered.
3. **Primary event set = the BOOK-market-order tranche** of margin liquidations only — exclude the
   backstop/HLP-at-mark tranche (no book overshoot to fade; HLP is the counterparty capturing it) and ADL
   (closes *profitable* positions; opposite selection). Pooling these mixes opposite-signed mechanisms.
4. **Unit of inference = the DAY.** The 4 majors co-move and liquidations cluster on a few stress days, so
   the independent unit is the market-wide day, not the event or the coin. Cluster / permute / compute MDE
   at day resolution. The 4-coin sign test is DEMOTED to corroboration (at n=4 it can't reach p<.05 and the
   coins aren't independent).

## 1. Primary hypothesis & estimand (A1′)
**H:** on the book-order-tranche subset of large single-name liquidations, forced flow produces an
**abnormal** short-horizon reversion in the tradable book mid, over and above the generic reversion any
same-signed move exhibits. Sign is an open question — fade (>0) and follow (<0) are treated symmetrically.

**Primary estimand:**
`FADE_abn(h*) = mean_day( fade_liq − fade_placebo )`, in bp, where per event
`fade = signal_sign · (mid_px(entry_ts + h*) / mid_px(entry_ts) − 1) · 1e4`,
`signal_sign` = fade convention (>0 ⇒ reversion), `entry_ts` = first `asset_ctx.ts` **strictly after**
`t_decision = max(liq-fill ts in the event)`, and `fade_placebo` = the same quantity over a
**signed-move-and-vol-matched non-liq control** (§4). Aggregation is **mean-of-day-means** (the bootstrap
statfn matches this exactly), reported per-coin then pooled; event-weighted and coin-equal weightings
reported as dominance diagnostics.

**Conditioners (co-primary, not exploratory):** dose = `|L| / open_interest` (size-vs-depth); regime =
funding-sign / trend-state. Report the fade-subset and follow-subset **separately** — never only the pooled
cancellation. The unconditional pooled mean is reported as a CONTROL expected ≈ 0.

**Primary horizon `h*`:** chosen by **SNR** from the EDA tranche-decay term structure on TRAIN months
(physical prior: the partial-liq 20%/30s tranche staggers forced book flow over minutes), frozen before the
OOS test. NOT pre-committed to 15 min.

## 2. Decision rule
- **Fade edge:** `FADE_abn(h*) > 0`, **day-clustered CI lower bound > 0**, dose-monotone (larger `|L|/OI` →
  larger reversion), and **BTC/ETH/SOL corroborate the sign without needing HYPE** (HYPE's mid/oracle may be
  HL-endogenous). Report gross as the scientific result.
- **Follow edge:** the same with `< 0`.
- **Inconclusive:** day-clustered CI includes the care-about size OR positive-control MDE > care-about →
  INCONCLUSIVE (never "no effect"). **But A1′ IS the powered attempt** — a *tight* day-clustered null with
  MDE ≤ care-about earns a **method-scoped negative** ("no abnormal book-tranche liq-reversion at h\* on
  majors"). If the EDA gate (§7) shows MDE ≫ care-about even after differencing, the honest conclusion is
  "the data cannot resolve this" — write it and stop.

## 3. The four-part over-null gate (all four required before ANY null verdict)
1. **Point estimate + CI** — `FADE_abn` as mean-of-day-means; CI via `cluster_bootstrap_ci` clustering on
   **day** (statfn = mean-of-day-means, matched to the point estimate). (No StableEdge — that estimator is
   not implemented in `research/lib/`; dropped from the frozen gate.)
2. **Positive-control MDE ≤ care-about** — MDE from the **day-clustered SE** (`(z_{1-α/2}+z_power)·SE_day`),
   NOT `√n_events`. Positive control = inject a known reversion and run the FULL clustered inference,
   checking the day-clustered CI excludes 0 with the intended power (a power curve, not a constant-shift).
3. **Cross-coin corroboration** — sign agreement is reported as color; it is NOT a gate (n=4 floor p=0.125).
   The BTC/ETH/SOL-without-HYPE requirement (§2) replaces it as the cross-unit check.
4. **Construction-conservatism** — the placebo differencing + raw-and-matched side-by-side; tail-day
   with/without; day-level (not coin-day) clustering so a market-wide crash isn't 4 "independent" units.

## 4. Nulls, placebo, cost, OOS (frozen at EDA)
- **Placebo / matched baseline (now the ESTIMATOR, not just a null):** each liq event is matched to non-liq
  coin-minutes on **strictly pre-event, lagged** signed trailing-return and volatility (excluding the event
  minute and the h-window), same coin/session; the control carries the liq event's `signal_sign`. Report
  common-support diagnostics; where support is thin, prefer a **within-coin time-shift placebo** (same coin,
  same signed trailing move, event time shifted a random offset with no liq).
- **Permutation null:** permute `signal_sign` at the **day/cascade cluster level** (not per event — that
  under-disperses the null), seed pinned (study-local, NOT the Gate-A seed).
- **Multiplicity:** `bh_fdr` across the secondary {horizon × coin} grid; the headline is h\* only; any other
  horizon is descriptive and cannot be promoted post-hoc; the full comparison count across A1′/A3/A5/A6 is
  logged for the over-carry tally.
- **Cost:** **gross is the primary scientific result.** Net = a bounded sensitivity BAND computed at the
  **median AND a high-percentile / contemporaneous** event-time `impact` spread (the proxy is least
  trustworthy exactly at stress minutes) + taker latency. A wide/negative net does NOT override a clean
  gross positive (that would be over-nulling on an untrustworthy proxy).
- **OOS / walk-forward:** all design choices (event threshold Q,W; the h\* SNR pick; dose/regime cutoffs;
  matching spec) are set on TRAIN months and applied unchanged to TEST months via `cv.walkforward_splits`.
- **Data hygiene:** ASOF matches carry a **max-staleness bound** (reject if matched `ctx.ts` > ~90 s before
  target); drop events whose [entry, entry+h) span crosses a missing-minute run (2026-05-30 partial day,
  any gap); right-censor the global tail.

## 5. Tail-day policy (frozen)
Oct-10-2025 and Jan-31-2026 (and any ADL-flagged / extreme-|L|/OI day) are a categorically different
mechanism (ADL at stale oracle, multi-day recovery) and hold a large share of all extreme liq notional.
Report `FADE_abn(h*)` **with and without** them; the ADL subset is a **separate labelled estimand**, never
folded into A1′. Moving-block bootstrap does not fix a point-mass regime — day-clustering + this policy do.

## 6. Constants to PIN at EDA-freeze (blank until the §7 gate runs)
- `BOOK_TRANCHE` = the `liq_method` value(s) for book market-order liqs; `BACKSTOP`/`ADL` values (excluded).
- Event threshold quantile `Q`, lookback `W` (causal `[t−W, t)`, per coin).
- `h*` (SNR-chosen from the train term structure); dose cutoffs (`|L|/OI` bins); regime definitions.
- Matching spec (lagged-vol/return window, bins, session).
- `CARE_ABOUT_BP` (net reversion we'd deploy on; ≥ stressed round-trip cost by a margin) — pin BEFORE the
  h\* result.
- forced_dir quarantine rule (drop events with `sign(start_position)` vs `side` disagreement > threshold;
  split out ADL/HLP-unwind rows).

## 7. EDA feasibility GATE (descriptive, TRAIN months only — run BEFORE freezing; a go/no-go)
This is not a test; it is the powered-design homework the anti-ratchet rule requires. It must answer:
1. **`liq_method` values + non-null coverage of `liq_method`/`liq_mark_px` on `is_liq_origin` rows** (A3/A6
   are contingent on this; if the struct sits on the counterparty row, re-key with double-count care).
2. **`|Δoracle_px|` vs `|Δmid_px|`** on known cascade minutes — confirm oracle is blind and mid sees the
   overshoot (validates change #1).
3. **Event-day count per coin + forward-return σ → the REAL MDE at day-cluster resolution**, before and
   after placebo-differencing. If MDE ≫ care-about even differenced → data cannot resolve it → stop.
4. **Tranche-decay term structure** on train months → pick `h*` by SNR.
5. **HYPE mid/oracle exogeneity** vs BTC/ETH/SOL.
6. **forced_dir↔side agreement**; base rates; common-support of the placebo match.

## 8. Stop rules
One powered primary (A1′). If A1′ is INCONCLUSIVE with MDE ≫ care-about, do not re-run — either the EDA
gate already said "unresolvable" (stop, write it) or a single further variance-reduction is attempted and
documented. A tight day-clustered null with MDE ≤ care-about is an EARNED method-scoped negative — a real
result, write it and stop. Any positive must pass BOTH the steelman and the prosecute-the-positive passes
(separate agents) before it reaches the ledger as a live positive.
