# Babylon — Trading Engine Architecture (v2)

The design blueprint for the live/paper/backtest trading engine. Phase 1 (data +
connectivity) is built; this document covers the engine layered on top.

> **Build status:** the end-to-end **paper skeleton** is built and running on the
> live feed — `Strategy`/`Context`/`Clock`, core types, tail-aware Kelly `Sizer` +
> Bayesian `EdgeModel`, per-strategy `Ledger`, per-strategy `RiskManager` +
> `NetRiskManager`, `Reconciler`, `PaperExecutor`, and the `Engine` loop, driven
> by a toy MA-crossover (`babylon paper`). Not yet built: durable journal,
> backtest/live executors, the `stats/` measurement layer, funding & mark/oracle
> data. Several v2 hardening items (off-loop stats, funding, mark price, durable
> state) are deliberately stubbed in the skeleton and flagged in code with TODOs.
>
> **A second four-lens audit** (over the engine code) was applied and its
> confirmed bugs fixed: the **attribution invariant** (net-risk deleverage/halt of
> a held position no longer desyncs ledger from executor — fills carry an exact
> residual), the **Kelly cliff** (a hard `max_fraction` cap + regime-anchored
> stress, so leverage no longer scales as 1/worst-observed-loss), a **deterministic
> cloid** (idempotent), a **latched** max-DD kill, a **gross-virtual cap**,
> **net-of-fee** edge returns, edge direction from the actual position, per-strategy
> tick isolation + quarantine, per-strategy RNG, deterministic sizing (no per-call
> resampling), and `on_start`/`on_fill` hooks.

> **v2** incorporates a four-lens architecture audit (quant-stats, execution/HL
> perps, software, risk/adversarial). The headline correction: v1 reasoned in
> *virtual / per-strategy / IID / single-name* space; the account that actually
> gets liquidated lives in *net / correlated / serially-dependent / perp-with-
> funding* space. v2 adds the net-account layer, funding, mark/oracle pricing,
> durable state, and a tail-and-dependence-aware sizing kernel.

## Guiding principle: one strategy, three modes

A `Strategy` runs **identically** in backtest, paper, and live. The only things
that change are the **`Executor`** (who fills orders) and the **`Clock`** (who
advances time). Strategies consume a mode-agnostic `Context` and emit *signals*,
never raw orders.

**Honest bound on the abstraction (audit C2):** "same code in 3 modes" is true;
"validated in backtest ⇒ works live" is **not**, and the doc no longer claims it.
Our archive is L2-snapshot-only (no historical trades, no funding, ~1.85/s), so
order-flow strategies can't be backtested at all, and backtest fills omit
latency/queue/slippage/funding. Therefore **backtest seeds a deliberately *weak*
prior**, never a validation that shortcuts paper/probation. Paper and backtest
share one **versioned `FillModel`** seam (latency/slippage/partial-fill/funding
assumptions pinned to the strategy version).

```
                 ┌────────────── identical strategy code in all 3 modes ──────────────┐
 market data  →  Data Router → Strategies → Sizer → Risk → Net Risk → Reconciler → Executor
 (WS │ archive)   + MarketView   (Signals)  (Kelly  (per-     (account   (diff vs   ┌─────────┐
 + funding        + indicators)      ↑       kernel) strat)    caps,DD,   actual)   │Backtest │
 + mark/oracle                       │               correl)   CVaR,kill)    │       │Paper    │
                                  on_fill ◄── Ledger (per-strat PnL + funding ◄──────│Live(HL) │
                                              attribution; unit-returns) ◄─ fills    └─────────┘
                                              → smoothed equity feeds Sizer + EdgeModels
```

## Components & responsibilities

- **Engine** (`engine/engine.py`) — owns the event loop, strategy registry, data
  router; drives a **strict within-tick phase order** (below); reconciles on a
  cadence and on events; rebuilds from the durable journal on boot.
- **Clock** (`engine/clock.py`) — `RealClock` (paper/live) vs `SimClock`
  (backtest). Everything time-related goes through `ctx.now()`; no engine-path
  code calls wall-clock/`random`. `SimClock` defines a **total event order**
  `(time, channel_priority, tie_key=tid/ver_num, insertion_order)`.
- **Data Router / MarketView** (`engine/router.py`, `context.py`) — fans feed
  messages to strategies; owns a **shared** indicator cache keyed by
  `(coin, indicator, params)`, updated **incrementally O(1)**; exposes L2 mid
  **and mark and oracle price**, positions, predicted funding. Trading is gated
  until indicators are warm (warmup replayed from archive/candles on restart).
- **Strategy** (`strategy/base.py`) — ABC; emits `Signal(coin, direction)`. Edge
  magnitude comes from its attached **EdgeModel**, not the signal.
- **Sizer** (`sizing/`) — Kelly within each strategy's capital budget (kernel
  below). Reads a **frozen snapshot** of smoothed equity + last-published edge;
  never computes heavy stats inline.
- **Risk (per-strategy)** (`risk/`) — per-asset caps, stale-data guard, order-rate
  cap, the per-strategy demote/kill triggers.
- **Net Risk Manager** (`risk/net.py`) — **new, first-class.** Owns the *real*
  account: net **and gross** exposure caps, account-level max-DD kill, portfolio
  CVaR, correlation/concentration limits, liquidation-distance guard. Has its own
  kill authority and resolves kills atomically at the net level.
- **Reconciler** (`portfolio/reconcile.py`) — nets per-strategy virtual targets to
  one desired exchange position per coin; applies **deadbands/hysteresis +
  min-trade-size**; emits **maker-first** idempotent orders (deterministic
  `cloid`); throttled by remaining rate budget.
- **Executor** (`execution/`) — one interface: `LiveExecutor` (HL SDK signing via a
  **single serialized nonce allocator**, reduce-only exits, server-side stops),
  `PaperExecutor` (sim fills vs live book — **taker-fidelity only**),
  `BacktestExecutor` (sim fills vs archive). Both sim executors share the
  versioned `FillModel`.
- **Ledger** (`portfolio/ledger.py`) — per-strategy virtual positions, entry
  prices, realized/unrealized PnL, **funding accrual**; logs **unit returns**
  (net-of-cost) separately from sized PnL; attributes fills (below); feeds
  **smoothed** equity to the Sizer.
- **State / journal** (`engine/state.py`) — **new.** Append-only event journal
  (fills, signals, reconciler decisions, `cloid→{strategy:delta}` written *before*
  send) + periodic posterior snapshots. Durable vs recomputable tiering (below).

## Account model: single account + virtual ledgers + netting

One real Hyperliquid account; each strategy keeps a **virtual** position/PnL
ledger; the reconciler **nets** overlapping positions before touching the
exchange (StratA +1 BTC, StratB −0.5 BTC → exchange +0.5). Capital is one pool
(correct for whole-bankroll Kelly).

**Risk is controlled on the net AND the gross (audit C1/C2):**
- No-leverage cap uses **mark price**: Σ|net exchange notional| ≤ equity.
- A separate **gross virtual cap** (Σ|per-strategy notional|) bounds internal
  netting, so the book can't quietly run 3× gross under a flat-looking net.
- **Phantom-flatten guard:** when a peer strategy's exit mechanically jumps a
  survivor's real exposure, that new exposure must re-pass net/per-asset caps
  *before* it stands — trim, don't blindly grow.

**Fill attribution (audit, execution #4):** each strategy settles against its
*own* virtual target at the fill VWAP; internal crossing (A vs B) is a **virtual
fill at mark**, not a real order. Netting's saved spread/fees is a separately
allocated line, not folded into entry prices. Partial fills: same-sign-as-net
strategies fill first; an offsetting strategy's virtual position only changes when
its flow is actually executed/internalized. The `cloid→{strategy:delta}` map is
journaled before send so attribution survives a crash.

## Funding — first-class (audit, execution #1, CRITICAL)

Perps pay funding hourly (1/8 of the 8h rate) on the **oracle** price; it is
frequently *larger* than directional alpha on a ≤1× book and spikes to ±4%/hr in
squeezes. Therefore:
- **Data:** add `fundingHistory`/`predictedFundings`/`userFunding` to the
  `InfoClient` (they don't exist yet) and surface predicted funding in MarketView.
- **Ledger:** accrue `position × oracle_px × funding_rate` into per-strategy
  realized PnL each hourly stamp, by net virtual position.
- **Edge:** unit returns are **funding-inclusive total returns**. Price-only
  returns systematically *oversize* (the worst Kelly failure) and make carry/
  funding-harvest strategies invisible. Predicted funding is also a first-class
  signal input so carry strategies can exist.

## Pricing: mid ≠ mark ≠ oracle (audit, execution #8)

- **Mark price** — unrealized PnL, margin, the no-leverage cap, liquidation distance.
- **Oracle price** — funding accrual.
- **L2 mid** — execution decisions only (and it's manipulable on a thin book).

A continuous **liquidation-distance / margin-ratio guard** (from
`clearinghouseState`) keeps hard headroom below maintenance margin; funding-owed
is treated as a continuous equity drain in the no-leverage check.

## Sizing: Kelly kernel (tail- and dependence-aware)

Capital is sliced into per-strategy **budgets** (Σ ≤ 100%). Within its budget each
strategy runs fractional Kelly, but the kernel is built for the fat-tailed,
serially-dependent regime it actually faces (audit C1/C4/H1):

```
# 1. Resample the strategy's net-of-cost unit returns with a STATIONARY/BLOCK
#    bootstrap (Politis–Romano; block length from ACF) — preserves vol-clustering
#    and autocorrelation, which govern clustered-drawdown / ruin risk.
# 2. Inject a STRESS FLOOR: a synthetic worst loss ≥ ~1.5–2× the worst observed,
#    because the catastrophic loss is the one the sample hasn't drawn yet.
# 3. Maximize log-growth over that distribution:
f* = argmax_f  E_blockboot+stress[ log(1 + f·r) ]
# 4. Shrink for estimation uncertainty (replaces the undefined v1 shrink):
f  = kelly_fraction × (SNR/(1+SNR)) × f*        # SNR = edge² / Var_posterior(edge)
target_notional = budget_slice_equity × clamp(f)   # mark-priced; net+gross+per-asset caps
```

`kelly_fraction` (~0.25) is a final standing cap; the `SNR/(1+SNR)` term → 0 at
cold-start and → 1 as the posterior concentrates, unifying "fractional" and
"shrink." *(Deferred, audit H1/C1: full posterior-predictive Kelly and EVT/GPD
tail extrapolation — the stress floor is the pragmatic stand-in; EVT-fitting a
tail you haven't seen is itself noisy on small live samples.)*

**Correlation (audit C2):** decoupled per-strategy Kelly + a net-notional cap can
still be aggregate **super-Kelly** when strategies load a common factor (netting
only helps when they *oppose*). v1 adds a **diversification haircut** on the budget
vector (scale by effective-number-of-bets) plus the Net Risk Manager's
portfolio-level vol/growth cap. *(Deferred: full joint Σ⁻¹μ Kelly.)*

### EdgeModel — Bayesian prior + online update

Edge is a per-strategy **estimated distribution**, decoupled from signal logic.
It hands the Sizer a **sampler / posterior-predictive draws** (not `(μ, σ)` —
audit H5), plus `confidence`. One mechanism, three priors:

| Strategy type | Prior source | Updated by |
|---|---|---|
| Systematic, backtested | backtest stats, **weak** prior (no fill realism) | live realized PnL |
| Copy-trade a wallet | wallet's **lag-and-fee-adjusted** track record | wallet + own realized PnL |
| New / unproven | weak/zero prior → sizes ≈ 0 | live PnL as it accrues |

## Copy-trading (audit, execution #5 / risk H3 / quant M3)

A copy-trade strategy mirrors a wallet's position deltas (HL `clearinghouseState`/
`userFills` via `InfoClient`), sized by **our** Kelly on **our** achievable edge —
which is *not* the wallet's raw track record:
- **Lag = adverse selection, not just decay** — re-mark their fills at *our*
  post-latency taker price; seed the prior from that.
- **Exclude maker-dominated wallets** — copying a market-maker *as a taker* makes
  you their exit liquidity (their PnL is spread+rebate+funding you can't capture).
  Classify by maker/taker ratio + funding dependence.
- **Assume adversarial / gameable history** — public records are wash-tradeable
  and baitable; PSR-style gates don't detect manipulation. Weak prior regardless
  of their Sharpe; flag wash-trade signatures; **per-wallet and aggregate copy
  caps**; build wallet-selection anti-gaming *before* any live copy capital.

## Measurement & statistics (`stats/`)

Returns are fat-tailed, sometimes with **undefined variance** (Hill α ≤ 2), so
t-stats/means/Sharpe are unreliable. Reads the Ledger; logs **net-of-cost unit
returns** separately from sized PnL (no sizing feedback into edge).

**Performance dashboard (per strategy):** realized **log-growth rate** (= the
objective) and the **max-drawdown family** (current DD, duration, Calmar, Ulcer);
**CVaR / expected shortfall**; median/MAD and **Omega**; **Beta-Binomial
hit-rate** (auxiliary only — see below). Sharpe/Sortino reported but flagged when
α < 4.

**"Is-it-real" gate (audit C3 — replaces PSR):** PSR/DSR are Sharpe-derived and
need finite 3rd/4th moments the fat-tail premise denies. Gate instead on a
**stationary-bootstrap confidence bound of realized log-growth > 0** — the same
statistic as the objective — and a **distribution-free false-strategy/FDR**
correction for wallet screening.

**Edge-decay detection (audit M1 — restructured):** **continuous tracking is
primary** — a state-space / EWMA estimate of the edge with a tuned half-life feeds
`shrink()` directly (alpha erosion is gradual, not a sharp break). **BOCPD is
secondary**, only for genuine abrupt regime breaks (hazard calibrated per-strategy
from an alpha-half-life prior), run on a power-preserving robust statistic
(Huberized magnitude), not pure sign. A detected change governs the **effective
window** every stationarity-assuming estimator uses (forget-and-rewiden).

Libraries: `empyrical`/`quantstats` for standard metrics, `ruptures` for
change-points; block-bootstrap log-Kelly, Hill, Beta-Binomial, CVaR, Ulcer,
EWMA/state-space edge tracker implemented in-house.

## Strategy lifecycle: paper → probation → full

1. **Paper** — every new strategy runs paper-only until it has a track record.
   *Maker/passive strategies skip straight to live-probation at min size* — paper
   (touch-fill) structurally over-credits them (audit, execution #6).
2. **Probation** — earns live capital at *minimum* size.
3. **Full** — the edge tracker's growing confidence ramps it toward its budget.

## Safety (always-on, real money)

- **Kill-switch semantics (audit C3):** **soft** (stop adding risk, passive
  reduce-only bleed-down / scale-out) vs **hard** (catastrophic — immediate
  flatten, explicitly accepting it locks the loss). Default to soft. Kills are
  resolved by the Net Risk Manager in **one atomic, netting-aware pass** so
  halting one strategy can't cascade peers into forced liquidation.
- **Exchange-resident protection (audit C4):** reduce-only **native stop orders**
  on Hyperliquid sized to the net position, refreshed each reconcile — they keep
  working when the engine is dead. Plus a **dead-man's switch**: a separate
  watchdog that de-risks if the engine heartbeat stops within N seconds.
- **Degraded-mode matrix (audit H4) — fail toward *less* risk, never trade blind:**
  stats down → `shrink` → 0 (don't coast on stale edge); feed stale → no new risk,
  lean on resting stops; executor down → exchange-resident stops are the backstop.
- **Connectivity-loss policy:** keep reduce-only protective orders resting, cancel
  risk-adding orders, sanity-check price/staleness before resuming.
- **Pro-cyclical equity (audit H1):** Kelly sizes off **smoothed/realized
  high-water-throttled** equity (with resize rate-limiting), while margin/no-lev
  use the conservative real mark-to-market number — so a drawdown doesn't force
  selling into its own move.
- **Key management:** HL **agent/API wallet that can trade but not withdraw**;
  withdrawal-whitelist to a separate cold wallet; only working capital in the
  account; signing key in a real secrets manager.
- Per-strategy & net order-rate caps **exempt reduce-only/protective orders** so a
  throttle can never block de-risking.

**Auto-demote (→ probation) / halt triggers** — net-coordinated, driven by `stats/`:
- **Account & per-strategy max-DD breach** (hard survival constraint).
- **Log-growth decay** — the continuous tracker (not BOCPD) crosses a downward threshold.
- **Realized CVaR / DD breach** — the thing we actually care about, monitored directly.
- *(Hit-rate collapse and Hill-α fattening are **continuous size-reduction**
  signals, not hard kills — both are too orthogonal-to-growth / too noisy to gate
  capital on; audit H2/H3.)*

## Engineering invariants (audit, software)

- **Durable state (C1):** event-sourced journal is source-of-truth; periodic
  snapshots of EdgeModel posteriors, BOCPD/edge-tracker state, Beta-Binomial
  counts, ledgers, `cloid→delta` map (all **durable**). Indicators, dashboard
  metrics = **recomputable** (replay on boot). Journal fsyncs, off-loop, separate
  from the buffered `ParquetStore`.
- **Heavy stats off-loop (C3):** bootstrap-Kelly / BOCPD run on a **slow cadence**
  (bar/timer), vectorized in numpy via `asyncio.to_thread` (or a process pool);
  the Sizer reads the **last-published** edge with a defined **staleness bound**.
- **Within-tick phase order (H2):** (1) apply queued fills → (2) update
  MarketView/indicators → (3) strategies emit signals → (4) Sizer reads a frozen
  equity+edge snapshot → (5) Risk + Net Risk → (6) Reconciler diffs → (7) Executor.
  A fill mid-tick is queued for phase 1 of the next tick. Single-writer per store.
- **Determinism (H1):** one seeded `numpy.Generator` threaded through all
  stochastic code; per-worker seeds from `(strategy_id, tick_index)`; seed in run
  metadata.
- **Decimal/float boundary:** `Signal.direction`/`EdgeEstimate`/returns = float
  (numpy domain); `Order`/`Fill`/`TargetPosition`/ledger position+entry+PnL =
  `Decimal` (or integer ticks via `meta` sizeDecimals); convert once at the
  Executor→Fill seam.
- **Config/versioning (M2):** per-strategy pydantic configs; a versioned strategy
  manifest (id+version+params+prior+code-hash); Σbudget validated fail-fast; a
  param/prior change = **new version requiring re-probation** (or a reconciler-
  ramped reconfigure event).
- **Error policy:** unlike the data layer's "swallow & continue," a thrown
  Sizer/Risk/Reconciler exception is fatal-or-quarantine within a **tick
  transaction** that rolls back the strategy's contribution — never a half-applied
  shared-state mutation.
- **Order lifecycle:** deterministic `cloid` keyed to (strategy, target-epoch);
  on-boot reconcile reads `openOrders`+fills before re-emitting; ALO re-quote loop
  with taker fallback; reduce-only exits; single serialized signer/nonce allocator.

## Module layout

```
src/babylon/
  engine/      engine.py · router.py · clock.py · context.py · state.py
  strategy/    base.py · registry.py · examples/
  signals/     indicators (shared, incremental) + signal primitives
  sizing/      kelly.py · allocator.py · edge.py        # block-boot log-Kelly + Bayesian EdgeModel
  stats/       metrics.py · tails.py · decay.py · gate.py   # dashboard, Hill/CVaR, EWMA tracker, log-growth gate
  risk/        manager.py · net.py · limits.py · killswitch.py
  portfolio/   ledger.py · account.py · reconcile.py
  execution/   base.py · paper.py · live.py · backtest.py · orders.py · fillmodel.py
  (existing)   data/ (+ funding, mark/oracle) · exchange/ · config.py
```

## Core data models (sketch)

```python
Signal(coin, direction: float)                 # -1..+1 within a strategy
EdgeEstimate(sampler: Callable[[int], np.ndarray], confidence: float)  # draws, not (mu,sigma)
TargetPosition(coin, size: Decimal)            # signed, strategy-virtual
Order(coin, size: Decimal, price: Decimal|None, reduce_only: bool, tif, cloid: str)  # cloid deterministic
Fill(coin, size: Decimal, price: Decimal, time, strategy, cloid)
Funding(coin, rate: float, oracle_px: Decimal, time)
```

## Build phases

1. **Paper trader** — Strategy + Context + Clock, core models, `PaperExecutor`,
   minimal Sizer + one EdgeModel + per-strategy + Net Risk, durable journal, on
   live data. No signing; runnable for weeks.
2. **Backtester** — `BacktestExecutor` + `SimClock` + shared `FillModel` over the
   archive; same strategy code; seeds **weak** EdgeModel priors.
3. **Live** — `LiveExecutor` (serialized signer, server-side stops, dead-man's
   switch) + reconciliation + droplet/systemd deployment, secrets, monitoring.

## Decisions locked

v1 (2026-06-27): single account + virtual ledgers + netting · per-strategy budget,
fractional Kelly · `EdgeModel` Bayesian prior + online update · copy-trade sized by
our Kelly on the wallet's edge · target-position reconciliation · build paper-first.

v2 (post-audit): **Net Risk Manager + diversification haircut** (net/gross/DD/CVaR/
correlation) · **Kelly kernel = block/stationary bootstrap + stress floor +
SNR-scaled shrink** (not IID empirical) · **funding first-class** end-to-end ·
**mark/oracle pricing** + liquidation guard · **log-growth bootstrap gate** (not
PSR/DSR) · **continuous decay tracking primary, BOCPD secondary** · hit-rate/Hill =
continuous reduction, not hard kills · **soft/hard kill semantics**, net-coordinated
· **exchange-resident stops + dead-man's switch** · **durable event journal** ·
**off-loop stats + within-tick phase order + seeded determinism** · copy-trade =
lag/fee-adjusted edge + maker exclusion + anti-gaming · paper = taker-fidelity only
(maker → live-probation) · `EdgeEstimate` carries a sampler, not `(μ,σ)`.

## Open / deferred (with rationale)

- **Full posterior-predictive Kelly + EVT/GPD tail** — stress floor + SNR-shrink is
  the v1 stand-in; EVT on small live samples is itself unstable.
- **Full joint Σ⁻¹μ correlation Kelly** — diversification haircut + net cap first.
- **Backtest/paper queue modeling** (maker fill realism) — taker-only fidelity for
  now; maker strategies validate in live-probation.
- **Wallet-selection/ranking meta-strategy** (incl. anti-gaming) — required before
  live copy capital, not before the framework.
- **HA / multi-process failover** — single instance + dead-man's switch + exchange-
  resident stops for now.
```
