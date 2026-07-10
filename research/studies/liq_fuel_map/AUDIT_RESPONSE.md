# liq_fuel_map — DESIGN AUDIT response (2026-07-07)

Five adversarial design reviewers (leakage, feasibility, stats-design, economic-premise, correctness) tore at
`ARCHITECTURE.md` before any build. **All five: REVISE** (feasibility → REDESIGN of the whale portion if its
CRITICALs can't be mitigated). Two ran scoped probes; the rest reasoned from docs+schema (build PID 3987
respected). The audit **falsified the study's stated moat** and showed the engine's spine blurs exactly where
the tradable notional lives. **Decision: do NOT build the M1–M4 engine yet. Run one cheap upper-bound test
first** (two reviewers converged on it independently). Trail below.

## The pivotal result — the moat does not exist, and the whale fuel is unknowable
- **economic-F1 [CRITICAL, verified]:** "a state only we can estimate / private / not published" is **false**.
  Hyperliquid is fully on-chain; every position + exact liq price is public in the same node feed we ingest,
  and the exact liquidation-fuel map is already a **shipped commercial product** (Hyperdash, HyperTracker,
  CoinGlass, ChartInspect, Kiyotaka). Our only possible edge is a *quantitative increment* over a map the
  crowd already watches, or a *liquidity-provision premium* into price-insensitive forced flow. → **strike
  every "private/only-we" claim; the crowd-anticipation residual becomes the PRIMARY estimand, not a
  robustness check.**
- **The whale fuel — the notional that actually moves price — is triply unknowable** (three independent
  reviewers, same conclusion): correctness-F1 (positions opened before the 2025-08-01 tape edge have
  **unknowable entry basis** — size-correlated, ~100% at tape start, permanent for long-held whales) +
  feasibility-F4 (for **cross-margin** accounts δ isn't a function of the majors-only `entry_vwap` at all — a
  SOL leg liquidates because BTC tanked) + economic-F3 (we're blind to the cross whales; precise only on
  retail dust: median liq **$1,563**, liqs = **0.6% of volume**). We have high-resolution vision of the fuel
  that matters least and are blind/biased on the fuel that matters most.

## The spine (empirical f(δ)) does not have the data it assumes
- **feasibility-F1 [CRITICAL, probed]:** the cross/isolated label the spine relies on **does not exist** —
  liq rows carry only `dir ∈ {Close Long, Close Short}` and `liq_method = market`; no margin-mode field
  anywhere in the schema. §3.3's "the liq dir label distinguishes cross" is factually wrong. Mode is fully
  latent → can't calibrate by mode, can't even *identify* cross events to bound their bias (open-Q3 is
  unanswerable as posed).
- **feasibility-F2/F3 [HIGH, probed]:** liqs are ~**100:1 with-the-move** (long-liqs on down days); the
  short-fuel cells are ~empty (`>100k` short = 0). The below−above **asymmetry that IS the S1 signal** is a
  noise-dominated difference. After forced pooling, `f` collapses to a coarse `f(δ | coin, side)` — best
  where notional matters least. BTC/ETH/HYPE are thinner than SOL.

## Inference: effective N is ~10–30 stress regimes, not 42k liqs
- **stats-F1 [CRITICAL] + feasibility-F5 [HIGH]:** cascade signals (S3, M2) only light up on stress days
  (top-3 days = 43% of fuel); short-horizon reach-prob to leverage-distant clusters ≈ 0 off-stress. With the
  **day-union-across-coins** as the true unit (stats-F2: coins co-move → day×coin over-counts 4× and inflates
  CIs/sign tests), effective N is single-to-low-double-digit stress regimes over 11 months. **Positive-control
  MDE must be computed on the stress-day subset** before any Stage-2 number (positive OR null) is
  interpretable — else it's the anti-ratchet blind-instrument trap.

## Validation would leak / self-confirm (fix before trusting any result)
- **leakage-F1 [CRITICAL]:** S2 overshoot-revert is the **edge3 family** — depletion denominator/cluster
  selection taken from the *realized* set, or entry priced at the dislocated print, fabricates the headline
  edge. Pin: depletion fraction = causal-cum-liquidated / **map-L(x) fixed at cluster formation**; clusters
  from the causal map only; entry at `oracle_px`/`impact_ask` as-of `t_decision+latency`; run a
  **shuffled-liq-path null** — if "revert" survives randomized depletion, it was leakage.
- **leakage-F2 [HIGH, verified]:** `research/lib/cv.py` has **no purge/embargo** — forward-window (`h`)
  labels bleed across the fold boundary into every fitted object (P̂, σ_h, flow→return). Add embargo ≥ h.
- **leakage-F3 / stats-F3 [HIGH]:** Stage-1 "does L predict where liqs fire" is **near-tautological** (a real
  position at its real trigger *is* the liq) → it passes for free, and `h` is then picked on that rigged SNR.
  Score Stage-1 against a **matched null that keeps positions but destroys the model** (randomize δ within
  bucket / predict held-out wallets); pick `h` on skill-over-null.
- **leakage-F4 / stats-F3 [HIGH]:** the crowd-anticipation control must be a **nested/encompassing ΔR² test**
  (baseline = public-level model; treatment = +our map; incremental OOS ΔR², day-clustered), fit
  **walk-forward on TRAIN only**, with proxy VIF reported — NOT orthogonalize-and-discard (which would
  manufacture a false null on a collinear proxy). This is the construction-conservatism mirror.

## Correctness bugs in Layer A (fixable)
- **correctness-F3 [HIGH]:** `L = Σ size·notional·f` **double-counts size** (`notional` already = |sz|·px →
  size²); distorts the map shape quadratically toward whales, and overflows DECIMAL(38). Use
  `Σ notional·f` in scale-6 space.
- **correctness-F4 [HIGH]:** `+sz if side='B' else −sz` is a catch-all `else` — vault/ADL/null-side rows
  silently become sells. Make side→sign **total, fail-loud**; `is_vault`-exclude; decide ADL explicitly.
- **correctness-F2/F5/F8 [HIGH/MED]:** the entry-VWAP layer is **entirely unvalidated** by the "100% chain"
  (which only tests position arithmetic). Add a **`closed_pnl` reconciliation gate** (reconstructed
  entry_vwap vs `(exit_px−entry_vwap)·closed_size` ≈ realized `closed_pnl_d`); define add/close
  **sign-relative to position** (not by side); split zero-crossing/flip fills into close-portion +
  open-portion; **exclude `is_liq_origin` fills from VWAP accumulation**; sort `(ts, block_number,
  event_index)`.
- **correctness-F1 [CRITICAL]:** left-censored basis (above) — tag `basis_known ∈ {observed, censored}`;
  never invent basis from first-observed fill; Stage-1 reports **L(x,t) coverage = observed-basis notional /
  total open notional** and gates on it (a 60%-censored map is not a map).

## Compute (makes it buildable IF we proceed)
- **feasibility-F7 [MED]:** "emit L on a price grid **each minute**" is the naive reading that timed out
  (~400M rows). `L(x)` in price space only changes on a fill → build **event-driven**: one per-coin grid,
  add/subtract each position's kernel on its fills (one linear day-chunked pass), snapshot at change-points,
  evaluate the moving-spot integral per minute. Carryover state is small (tens of thousands of open
  positions) → RAM-trivial, coexists with the build. Rewrite §3.4/§8.
- **feasibility-F6 [MED]:** RV at h=5min = 5 squared returns (noisy); verify `oracle_px` actually moves each
  minute; likely drop h=5/15 for the vol leg.

## THE DECISION — cheap upper-bound test before any engine (economic + stats converged)
Measure the **realized** per-minute price reaction around **actual** liquidation cascades (from
`is_liq_origin`, already validated) — net of **stressed** spread — at h ∈ {1,5,15,30 min}, day-clustered on
the day-union unit. Using *realized* cascade timing is strictly **more informed** than any *anticipated*
fuel map, so it is a hard **upper bound on the whole program**: if a perfectly-timed reaction doesn't clear
cost at per-minute resolution, the anticipation engine (strictly noisier) cannot. It reuses the exact
structure that earned the basis negative, costs ~a day, and builds NO engine. Specifics:
1. Per coin·minute signed liq-notional (strip is_liq_origin double-count) → cascade-intensity series.
2. Top-decile cascade minutes: forward `oracle_px` return at h — (a) pre-cascade drift *into* the event
   (magnet; **require sign-stability across coins/days**) and (b) post-cascade overshoot-revert.
3. Net vs contemporaneous `impact_bid/ask` (widest at cascade minutes) + latency; day-union-clustered CI;
   compute the **stress-day-subset MDE** and check it's ≤ a care-about that clears stressed cost.

**Branch:** revert fat + sign-stable across coins + above stressed cost → THEN build the engine (with all
fixes) to get there *earlier* via anticipation, and measure our increment over the public map. Basis-like
(below cost / sign flips in the tail) → write the **method-scoped negative** now and save the M1–M4 build.
Either way this is a real, powered conclusion, not perpetual "inconclusive."

## What the audit confirmed CLEAN (kept)
Position reconstruction spine (signed-size + `(ts,event_index)` roll, start_position chaining — genuinely
validated); the causal "data < t" feature intent; `liq_mark_px` banned from the return path; the two-layer
split; the both-directions gate framing. The forced-flow **liquidity-provision premium** is the one real
economic force the dead price/basis bets lacked (forced sellers are price-insensitive) — honest prior on a
*deployable* Stage-2 edge ≈ **12%**, concentrated in S2-revert on top-decile SOL stress days.
