# Study: liq_fuel_map — ARCHITECTURE (design, pre-audit)

**Status:** DESIGN. Feasibility validated (`FINDINGS.md`: 100% position-chaining; $451M/mo SOL liq fuel,
bursty). This doc is the full design for the two-layer engine + its validation gates, written to be torn at
by the design-audit swarm **before** any build. **Lane:** exploratory (`research/studies/`), firewalled
from `gate_a/` and never imported into `src/babylon/`.

## 0. Thesis (one paragraph)
The price layer on majors is arbed (`../basis/FINDINGS.md` — three dead price/basis/funding bets). Our
durable edge is a **state only we can estimate**: from `start_position` on every fill we reconstruct every
wallet's running position, hence the **liquidation-fuel map** `L(x,t)` = forced-sell/buy notional that
triggers at each price level. We then forecast the **probability of reaching** each level with a
**realized-variance model** and integrate to an **expected forced-flow** signal. The bet is well-founded
because the hard input is *volatility* (forecastable — vol clusters), never *price direction*
(unforecastable). The map is private; the vol forecast is standard; the **combination** is the edge.

## 1. Two layers (keep them separate — they fail independently)
- **Layer A — Fuel-map engine (static state):** positions → entry VWAP → empirical liq-price bands →
  `L(x,t)` per coin. Pure reconstruction + calibration. Its own success metric (Stage-1, §6) is *"does the
  map predict where liquidations actually fire?"* — checkable without any trading.
- **Layer B — The brain (dynamic signal):** realized-variance forecast → hitting probability → expected
  forced flow `E[F](t)` and its side-asymmetry. Its success metric (Stage-2, §6) is *"does anticipated flow
  predict price beyond what's already priced?"* — the money question.

A clean Layer A does **not** imply Layer B pays; §6 tests them separately and never lets Stage-1 launder
Stage-2.

## 2. Data contract
- **Fills tape** (`fills` view, majors, 2025-08…2026-06). Reconstruction contract (verified, see
  `FINDINGS.md` / memory `babylon-position-reconstruction`): signed size `+sz if side='B' else −sz`; order
  strictly `(ts, event_index)` within `(wallet, coin)`; `end_pos = start_position_d + signed_sz`. Exact-
  decimal `_d` casts only. Ground truth = `is_liq_origin` (`liq_user==wallet`); `liq_mark_px_d` = realized
  trigger price — **a SIGNAL, never a tradable entry** (edge3 scar).
- **asset_ctx** (per-minute, all coins): `oracle_px` (external, for returns & realized variance — leakage-
  safe, not our own book), `mark_px` (HL's liq-trigger reference), `impact_bid/ask_px` (stressed spread for
  cost), `open_interest` (fuel sanity / normalization), `funding`/`premium` (regime).
- **Margin schedule:** HL per-asset max leverage + maintenance-margin fraction (public). Used only as a
  PRIOR / sanity band — the operative liq-price model is **empirical** (§3.3).

## 3. Layer A — the fuel-map engine
### 3.1 Position reconstruction (validated)
Roll running position per `(wallet, coin)`. Compute-heavy month-wide window is barred (timed out vs the
build) → **day-chunked with carryover**: persist end-of-day per-wallet {position, entry-VWAP state}; seed the
next day. Deterministic, resumable, RAM-capped (`memory_limit`, `threads` low).

### 3.2 Entry VWAP per position episode
An *episode* = a maximal run where the signed position keeps the same sign. Reset on flat (pos→0) or flip
(`Long > Short`/`Short > Long`). Entry VWAP = size-weighted fill price over the episode's opening fills;
on partial closes the basis is unchanged, on adds it re-weights. Yields, per open position at time t:
`(side, size, entry_vwap)`.

### 3.3 Empirical liq-price model (the spine — dissolves "leverage unobserved")
We do NOT assume leverage. For every **realized** liquidation we observe the reconstructed
`entry_vwap`, `size`, coin, time, AND the realized `liq_mark_px_d`. So the **realized liq-distance**
`δ = (liq_px − entry_vwap)/entry_vwap` is directly measured. Estimate the conditional distribution
`f(δ | coin, size-bucket, side, regime)` from realized liqs (TRAIN months). Apply it to **standing**
positions → each open position contributes a *probabilistic* trigger location `entry_vwap·(1+δ)` smeared by
`f`. The margin-schedule closed form is only a prior / outlier check. (This also back-outs the implied
leverage distribution as a diagnostic.)
- **Cross vs isolated:** the liq `dir` label distinguishes cross (`Liquidated Cross …`); calibrate `f`
  separately for cross vs isolated where identifiable. For *standing* positions margin-mode is unobserved →
  `f` is the mode-averaged distribution (a stated approximation; Stage-1 measures how much it costs us).

### 3.4 The fuel curve
`L(x, t; h-agnostic)` = Σ over open positions of `size · notional · f_position(x)`, split into
**long-fuel (sells-if-price-falls, below spot)** and **short-fuel (buys-if-price-rises, above spot)**.
Emit on a price grid per coin at a fixed cadence (e.g. each minute), causal (`fills.ts < t` only).
Normalizations reported: raw USD, and as a fraction of `open_interest` (cross-time comparability).

### 3.5 Partial-observation caveat (name it loudly)
Cross-margin accounts liquidate off their whole (multi-coin) book; we see majors only → for those accounts
our per-coin trigger is biased. The majors map is therefore a **noisy proxy** of the true fuel field. Stage-1
calibration *is* the test of whether the proxy is good enough; we do not assert it a priori.

## 4. Layer B — the brain (map → tradable signal)
### 4.1 Realized-variance forecaster
`σ_h(t)` from `oracle_px` log-returns: baseline EWMA + HAR-RV (daily/weekly/monthly components), fit on
TRAIN, evaluated OOS by QLIKE/MSE against realized. Horizon set `h ∈ {5,15,30,60 min}` (per-minute floor;
sub-minute is HLP's). This is the *only* forecasting the edge leans on, and vol IS forecastable.

### 4.2 Hitting probability — calibrate, do NOT assume
Start from the driftless barrier prior `P(reach x in h) ≈ 2·(1 − Φ(d(x)/σ_h))`, `d(x)=|ln(x/S)|`. But
liq clusters are **magnets, not driftless barriers** (pin risk / stop-hunts create drift toward liquidity),
so the prior is wrong exactly where it matters. **Operative model = empirical:** regress the realized
indicator `1[price reached x within h]` on `d/σ_h` (and cluster-proximity features) on TRAIN → a calibrated
`P̂(hit)`. The barrier formula is the sanity anchor only.

### 4.3 Expected forced flow
`E[F](t,h) = ∫ L(x,t)·P̂(reach x in h) dx`, signed (long-fuel below = downward pressure). Report the
**net signed pressure** and the **asymmetry** (below−above). Optional impact layer: map `E[F]` → expected
price impulse via a calibrated flow→return response (from realized liq bursts).

## 5. Reflexivity / causality guards
- Everything at t uses only data `< t` (fills, vol window `[t−W,t)`); walk-forward all fitted objects (`f`,
  `σ_h`, `P̂`, cutoffs) via `research.lib.cv`.
- The map moves as it's consumed (positions liquidate/reopen) → keep `h` short and **re-emit** `L` each step;
  never reuse a stale map across the horizon.
- `mark_px` (HL's trigger reference) may pre-empt our fill-derived trigger; use it to cross-check `f`, not to
  leak future price. `liq_mark_px` never enters the return path.

## 6. Validation — two stages, gated separately
**Stage 1 — MECHANISM (Layer A):** does `L·P̂` predict *realized* forced flow and vol?
- Estimand M1: calibration of `P̂(hit)` vs realized reach-rates (reliability curve).
- Estimand M2: does high `E[F]`-toward-a-cluster predict elevated forward **realized variance** / a
  **cascade** (a burst of `is_liq_origin` toward that side) within h? OOS.
- Pass = the map has genuine predictive shape for liquidations/vol. *This is not yet an edge.*

**Stage 2 — EDGE (Layer B):** does anticipated flow predict **price** beyond what's priced?
- **S1 Directional (magnet vs repel — sign is OPEN):** signed fuel-pressure / asymmetry → forward `oracle`
  return. Do NOT pre-commit the sign.
- **S2 Overshoot-revert:** after a cluster is *depleted* (measured via realized `is_liq_origin` consuming it),
  does price revert? entry strictly after depletion is observed (causal), exit by time.
- **S3 Cascade-conditioned:** condition S1/S2 on high `E[F]` (the anticipation) vs matched low-`E[F]` controls.
- **Crowd-anticipation control (decisive):** re-run S1–S3 **after** removing the publicly-obvious signal —
  orthogonalize `E[F]` against naive/round-number/visible liq levels and recent-move reversion; the edge is
  the **residual increment** of our precise map over the crowd's rough guess. A signal that vanishes after
  this control is *already priced*, not ours.

## 7. Over-null AND over-carry gates (both directions, per CLAUDE.md)
- **Unit of inference = the DAY** (coins co-move; liqs cluster on stress days — top-3 days = 43% of SOL
  fuel). Cluster/permute/compute MDE at day resolution; block bootstrap in TIME.
- **Null earns the word** only with: point estimate + day-clustered CI; positive-control MDE ≤ care-about
  (inject a known flow→return response, recover it through the full pipeline); cross-unit (coin/day) sign
  agreement; construction-conservatism (the crowd-anticipation control is not accidentally built to null).
- **Over-carry guard:** any positive faces permutation null (day-level), FDR across the {S1,S2,S3}×h×coin
  grid, and **two separate agents** — a steelman-the-positive AND a prosecute-the-positive/null-the-residual
  pass — before it reaches the ledger. Post-hoc horizon/level argmax is barred; `h` chosen by Stage-1 SNR.
- Report **gross as the scientific result; net as a band** at median AND high-percentile *contemporaneous*
  `impact` spread + latency (the proxy is least trustworthy at cascade minutes). A wide net does not over-null
  a clean gross; a Stage-2 that only works gross is labeled "not deployable," not "edge."

## 8. Compute architecture
Day-chunked reconstruction with carryover state; DuckDB, `memory_limit`≈2GB / low threads (coexist with or
run after PID 3987). Per-coin, per-day parts under `out/`. Deterministic + resumable (re-run resumes from the
last completed day). No month-wide windows. `research/lib` reused for stats/power/cv/cost; nothing new that
duplicates it.

## 9. Milestones
- **M1:** engine (§3) + Stage-1 mechanism (§6). If the map has NO predictive shape for realized liqs → stop
  here and write the method-scoped negative (the map is too noisy on majors-only data).
- **M2:** brain (§4) + `E[F]` construction.
- **M3:** Stage-2 edge tests (§6) incl. the crowd-anticipation control.
- **M4:** cost/deployability gate (§7) → ledger, with steelman + prosecute passes.

## 10. Open questions FOR THE AUDIT SWARM
1. Episode/entry-VWAP correctness on flips, adds-during-drawdown, `dir` edge cases (vault, ADL rows).
2. Is `f(δ|…)` estimable with enough support per (coin,size,regime) bucket, or does thin support force
   pooling that blurs the map to uselessness? (feasibility)
3. Cross-margin bias magnitude — can we bound it, or does majors-only partial observation sink Stage-1?
4. Leakage surface in `P̂(hit)` calibration and the depletion detector (S2) — is "depletion observed" truly
   causal?
5. Reflexivity: is `h` short enough that `L` is stable, but long enough to clear the per-minute floor + cost?
6. Is the day the right unit, and is the positive-control MDE ≤ a care-about that clears stressed cost?
7. Does the crowd-anticipation control actually isolate *our* increment, or over-subtract into a false null?

## 11. Firewall & conventions
No import of `gate_a`/`src`; no float authority (exact `_d` casts); OOS/walk-forward only in results;
per-minute price floor; `liq_mark_px` never priced; findings recorded in `FINDINGS.md` at each milestone.
