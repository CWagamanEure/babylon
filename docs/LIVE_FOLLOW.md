# Live wallet-follow paper trader — architecture plan (v1, for audit)

## 1. Goal & why

Every backtest number for the wallet-follow edge is a **prior**, not validation — the
pool was selected on past performance, so any historical measurement is
selection-contaminated. The only honest test is **forward**: freeze a follow set
*now*, paper-mirror it going forward at realistic latency/cost, and measure the true
followable PnL through the same stats + is-it-real gate. **Zero capital risk** (paper),
pure measurement. Success = the forward copy portfolio's log-growth gate clears with a
real, cost-survivable edge over weeks/months.

## 2. The clean-OOS contract (the whole point)

- **Selection is frozen at a cutoff `T0` (= deploy time)** from history strictly
  `< T0`. The follow set + each wallet's edge are computed once, journaled, and never
  re-fit on forward data. Forward PnL after `T0` is genuinely out-of-sample.
- Follow set = the **top quintile of the long-hold pool** by followable skill
  (`rank_followable`, ≥1h holds, taker, non-TWAP, neutralized), computed on data
  up to `T0`.
- Optional later: a slow **rolling** re-selection (e.g. monthly) — but v1 is frozen,
  because rolling re-introduces look-ahead unless each re-fit only uses pre-window data.

## 3. Components (reuse the engine; the wallets ARE the strategies)

The paper engine already does sizing → per-strategy netting ledgers → Kelly-on-edge →
reconcile → `PaperExecutor` → journal → stats/gate. The follow trader plugs into it by
making **each followed wallet a `FollowStrategy`** whose signal is the *sign of that
wallet's current net position* (per coin), and whose `EdgeModel` is **seeded from that
wallet's followable skill** — i.e. our Kelly sizes each wallet by its estimated edge
(the design in memory). Netting + risk + measurement come for free.

```
WalletWatcher (poll userFillsByTime per wallet, every poll_s)
   └─ maintains each wallet's live net position per coin (reconstruct, same code)
        │ position-change events
        ▼
FollowStrategy[wallet]  (signal = sign(wallet net pos in coin); universe = alt universe)
        │ directions
        ▼
Engine (paper)  sizer(Kelly on wallet edge) → per-strategy ledgers → NetRisk → reconcile
        │ orders
        ▼
PaperExecutor   fills at the LIVE market price NOW (WS l2Book) — a real follower's price,
        │       not the wallet's fill (the latency haircut is real, by construction)
        ▼
Ledger + Journal (durable) → PerformanceMonitor + gate  →  forward followable PnL
```

- **`WalletWatcher`** — new. Polls `userFillsByTime(wallet, since)` per followed wallet
  on a `poll_s` cadence, appends fills, reconstructs each wallet's current net position
  per coin (reuse `skill.reconstruct`'s logic incrementally). Emits the current
  position vector the strategies read. The poll cadence IS the follow latency we're
  testing (long-hold wallets tolerate 30–60s easily).
- **`FollowStrategy`** — new, thin `Strategy` subclass. `on_bar(ctx)` reads its wallet's
  current net position (from the watcher) for each universe coin and `ctx.signal(coin,
  sign(pos))`. `make_edge_model` seeds from the wallet's frozen followable skill.
- **`MarketView` / WS feed** — reuse. Subscribe `l2Book` for the coins we hold or any
  followed wallet is active in (live prices to mark + fill our copies).
- **Engine, Sizer, RiskManager, NetRiskManager, Reconciler, PaperExecutor, Ledger,
  Journal, PerformanceMonitor, gate** — all reused unchanged.

## 4. Wallet-activity ingestion — poll vs WS (key decision)

- **REST polling (recommended v1):** poll `userFillsByTime` per wallet every `poll_s`
  (start `since` = last seen). ~280 wallets / poll_s must stay under HL info weight
  limits (~60 weight-20 calls/min ⇒ poll the full set on a staggered ~5-min rotation,
  or fewer wallets faster). Latency = up to `poll_s` + the rotation period. Fine for
  hours-long holds; simple, robust, resumable.
- **WS `userFills` subscription:** lower latency but ~280 per-user subscriptions may
  exceed WS limits and complicate reconnection. Deferred.
- Latency is a *feature to measure*, not minimize — we record the actual detection lag
  per copy so the forward PnL is honestly attributable to a given follow latency.

## 5. Sizing & risk

- **Kelly on the wallet's edge** (the locked decision): each `FollowStrategy`'s
  `EdgeModel` seeded from its frozen followable-skill prior; the `Sizer` sizes it; the
  online `EdgeModel` updates from realized forward unit returns. Per-strategy budget =
  equal split (or skill-weighted) across the follow set; `NetRiskManager` enforces
  no-leverage + the account max-DD kill on the aggregate.
- Cost: `PaperExecutor` crosses the live spread (real per-coin cost paid by construction
  via WS bid/ask); plus the taker fee. No synthetic cost needed — it's live prices.

## 6. Durability & recording

- Journal records: the frozen follow set + each wallet's edge + `T0` (the run
  fingerprint); every copy order/fill attributed to its wallet; snapshots for crash
  recovery (the journal we already built + audited). Restart resumes the watcher from
  the last-seen fill time per wallet and the engine from the last snapshot.
- Output: forward equity curve + per-wallet attribution → `PerformanceMonitor` →
  log-growth / max-DD / CVaR / the bootstrap gate. **The gate clearing forward = the
  validation.**

## 7. Honest scope (what it does NOT do)

Paper only (no signing, no capital). Marks/fills at live top-of-book (no depth-walk
beyond the paper model; no market impact). Follows position *direction*, not the
wallet's exact size (sized by our own Kelly). Funding not modeled (perp carry omitted —
flag net-exposure coin-hours as before). A wallet using sub-second entries we detect
30–60s late: we get the lagged price by construction (that's the honest follower edge).
TWAP/liquidation fills excluded from signals (zero-hash). Selection frozen → no
adaptation to a wallet going cold within the window (a feature for clean OOS).

## 8. Open decisions (for the audit)

1. **Per-wallet `FollowStrategy` (≈280) vs one aggregate consensus strategy** — per-wallet
   gives attribution + per-wallet Kelly but stresses the engine's per-tick loop (280
   strategies × universe); aggregate is lighter but loses attribution. Which?
2. **Poll cadence & rotation** vs WS — latency/rate-limit/scale tradeoff.
3. **Coin subscription set** — all 187 universe (heavy) vs only coins currently
   held/active (dynamic resubscribe).
4. **Budget split** — equal vs skill-weighted across the follow set.
5. **Entry/exit semantics** — mirror only opens≥min_hold (skip the wallet's short
   scalps we can't follow), or mirror all? Exit when they close, or also on our own
   risk stop?
6. **Frozen vs rolling selection** — v1 frozen; when (if) to roll.

## 9b. POST-AUDIT REVISIONS (v2 — binding, from the 4-lens swarm)

The audit reshaped this from "a follow service" into a **controlled forward
experiment**. Binding decisions:

**Engine — AGGREGATE, not 280 strategies (CRITICAL).** 280 `FollowStrategy`s ×
187-coin universe makes `_tick`'s Phase-4 net/gross loop `O(S·C²)` ≈ 9.8M Decimal
adds/tick (seconds/tick vs a 2s cadence), and the 1/280 budget quantizes most
positions to zero (lot-grid deadband), and serializes a hundreds-of-MB edge blob per
snapshot. → **One aggregate consensus strategy**: per-coin signal = sign(edge-weighted
Σ of followed wallets' position signs), budget 1.0 (sizes off full equity), one
frozen per-coin prior. Per-wallet attribution is derived OFFLINE from the journaled
watcher positions (free), not in the hot loop.

**Sizing — FROZEN (HIGH).** The online `EdgeModel.update()` makes forward sizing
adaptive, contradicting §2/§7 and making the validator overfit forward. → frozen
prior-only EdgeModels (no-op update); `kill_switch=None` (NetRisk still latches the
account max-DD halt independently). Fold **T0 + a prior hash** into the recovery
fingerprint (today it's seed+roster only → a re-fit set could masquerade as a resume).

**Measurement — neutralized, per-round-trip, with CONTROL ARMS (CRITICAL).** The live
gate currently reads raw, per-tick, sized returns — raw is beta, per-tick is
autocorrelated (effective n ≪ nominal), sized overfits. → gate on **per-closed-copy,
basket-NEUTRALIZED return series** (one obs per round-trip, matching the in-sample
estimand). Run **control arms in parallel** (random-skill + bottom/median quintile,
same coins/window); the validation claim is **top − control**, never top > 0 (else an
up-alt regime fakes it). Report median followable bps side-by-side with the prior.

**Pre-registration + power (CRITICAL).** Resolve §8's six knobs into ONE config before
T0; hash {T0, frozen set+edges, config} into an immutable `run_id` logged to an
append-only registry; restart loads it and is HARD-BLOCKED from re-ranking. Publish a
power calc: detecting ~+4bp net vs ~80bp/trip needs **~1,500 round-trips → a quarter+**
at long-hold cadence; define the min-n before the gate verdict is read (NOT min_n=30).
Quote the headline at a fixed lag bucket. The honest claim is "one regime's OOS sample."

**Ingestion — POLL, not WS (CRITICAL).** WS user-fills is hard-capped at 10 unique
users/IP (≤100 even sharded) — infeasible for 280. → poll `userFillsByTime`; throttle
≥1.05s and budget by request-WEIGHT (userFillsByTime has a per-20-item surcharge),
realistic ~6-min sweep. Live position is **`startPosition`-anchored** (each fill's
`startPosition ± sz` is an absolute, self-correcting read — NOT a running sum, NOT
`reconstruct`, which only emits closed positions). Cursor = inclusive `since` +
persisted `tid` dedup; paginate in-poll on a 2000-cap burst. **`clearinghouseState`
truth-up** (weight-2, all 280 ≈ 28s/cycle) periodically + on cold-start — force-flat
any coin the exchange says is flat (kills the missed-close phantom). WS only for market
data: **`allMids` for marks** + targeted `l2Book` for held coins.

**Execution realism (HIGH).** Fold the **taker fee into the paper fill price** (today
equity is fee-blind — same bug the L2 backtest had). **Model funding** (material,
one-directional carry on hour-day holds; journal schema already supports
`funding_e8` + a FUNDING event). Wire the **staleness guard** (`MarketView.evict` is
defined but never called in the live loop) so we don't trade/mark on stale quotes.
Depth/size-cap the paper fill on thin alts. Persist the watcher's per-wallet net at the
engine's snapshot cut and restore BOTH on boot (else the book desyncs from the signal).

**Ops.** Supervisor (`Restart=always`), watcher heartbeat (halt on stale rather than
trade blind), periodic snapshot pruning + the forward-PnL report scheduler.

## 9. Build order (after audit)

1. `WalletWatcher` (incremental userFills poll + per-wallet live position) + tests.
2. `FollowStrategy` + edge-seed-from-skill + tests.
3. Wire into the engine paper loop; `babylon follow-live` CLI (selection at T0,
   journal, run). 4. Live smoke (short run, real WS + real wallet polls). 5. Deploy
   long-running; periodic forward-PnL report through the gate.

---

# v3 ARCHITECTURE (post-investigation — the spec to audit & build)

Supersedes v1/v2 design choices where they conflict. Reflects what the full
backtest+audit investigation established. **This is the spec for the pre-build audit.**

## v3.0 What the investigation actually established (the priors we build on)
- **Real per-trade signal:** top-quintile (rolling-selected) wallets' positions, priced
  on real L2 books OOS, carry +35-40bp gross directional return (front-loaded ~+7bp/hr
  hrs 1-2). Confirmed look-ahead-free, not survivorship, not bid-ask-bounce, ~100%
  capturable by a prompt follower. Well-sampled (thousands of trades).
- **As a plain long-only DIRECTIONAL copy** (mirror wallet positions incl. their shorts;
  NO basket hedge), retail-execution + taker cost: **Sharpe ~1.1, CAGR +34%, maxDD -19%**
  (measured hourly correlation, fully costed, not look-ahead).
- **NOT robust as market-neutral:** hedging out beta leaves thin/fragile alpha. The edge
  carries alt-beta (regime exposure) — a property to MANAGE, not eliminate.
- **Dead ends (do NOT build):** long-short "fade bad wallets" (their losses = their own
  spread cost, uncapturable); recency-exposure-weighting (un-charged turnover); any
  filter on REALIZED hold (look-ahead).
- **Open questions only forward data resolves:** out-of-regime durability (84-day, one
  up-alt regime), capacity (ZEC ~25% of PnL → concentration), and live execution quality.

## v3.1 Strategy — DIRECTIONAL copy, concentration-capped
- **Signal:** per coin, edge-weighted consensus of followed wallets' current net-position
  SIGN (the existing `FollowStrategy.consensus_sign`). Mirror direction (long AND short
  as the wallets hold). NO basket hedge (market-neutral was fragile; take the directional
  bet, size it).
- **Concentration cap (MANDATORY):** no single coin > `max_coin_frac` (e.g. 8%) of gross
  book; no single wallet > `max_wallet_frac` of the consensus weight. ZEC at 25% is the
  cardinal risk to neutralize. Cap via the sizer/reconciler.
- **Sizing:** `FixedFractionSizer` (per-coin fraction × consensus), gross-capped by
  NetRisk. NOT per-tick Kelly. Target a stated gross exposure (e.g. 1x) so the forward
  Sharpe is interpretable.

## v3.2 Selection — ROLLING, real-time-legal
- Re-rank wallets by FOLLOWABLE skill (taker, conviction, neutralized, candle/L2-marked)
  on a trailing TRAIN window (e.g. 30d); follow the top quintile on the next FOLLOW window
  (e.g. 14d); roll. Selection uses only pre-window data (verified disjoint).
- The roster updates at each roll. Recovery fingerprint must include the roster + T0 of
  each sub-period (a re-rank is a new pre-registered sub-experiment, not a silent change).

## v3.3 Ingestion — WalletWatcher (already built + audited)
- Poll `userFillsByTime` (WS user-fills hard-capped at 10 users/IP → poll for the full
  roster; WS only for the TEAM's low-latency execution path on the held subset).
- `startPosition`-anchored net positions (self-correcting), `clearinghouseState` truth-up
  (kills missed-close phantoms + cold-start seed), tid-dedup cursor, in-poll burst
  pagination. (All audited; 5 bugs fixed.)
- Weight-budgeted throttle (HL 1200 weight/min; userFillsByTime has per-item surcharge).
- Per-wallet error isolation + heartbeat; halt-on-stale rather than trade blind.

## v3.4 Execution — paper, with a configurable EXECUTION-QUALITY model
- Paper mode: fill at the follower's achievable price. **Execution quality is a config knob**
  spanning the realistic range we measured:
  - `retail`: enter at mid+lag (60s-5min) + full taker cost (spread+9bp) + ~6bp entry impact.
  - `validator` (the team's path): same/next-block entry ≈ wallet's price, maker-ish cost
    (~3-5bp). Model both; report the edge under each so the result isn't execution-assumption-
    dependent.
- Charge fee + slippage + entry-impact IN the fill price (the engine path already does this;
  do NOT double-subtract a separate cost). Depth/size-cap fills (thin alts). Funding accrual
  on multi-hour holds.

## v3.5 Measurement — the forward VALIDATION harness (the scientific core)
- **This run exists to answer the OOS/regime/capacity questions the backtest could not.**
- Gate on **per-round-trip realized return** (raw directional AND beta-decomposed), cost-
  inclusive, from a FROZEN-sizing arm (no online edge re-fit contaminating the measure).
- **Control arms in parallel** (random-skill + bottom-quintile rosters, same coins/window):
  the claim is top − control, not top > 0 (controls for the regime/beta tail).
- **Pre-registration:** one frozen config per sub-period; immutable `run_id = hash(T0,
  roster, edges, config)`; restart is HARD-BLOCKED from re-selecting. Power-budget the
  horizon (the per-trade edge is well-sampled, but the PORTFOLIO Sharpe needs months of
  forward trades to tighten the CI past the 84-day backtest).
- Track: realized Sharpe (with CI), maxDD, per-coin/per-wallet attribution (offline),
  capacity proxy (fill slippage vs size), and the live latency distribution.

## v3.6 Engineering & durability
- State journal (SQLite): watcher net positions + engine ledger checkpointed at the SAME
  snapshot cut; restore both consistently. Crash-recovery with fingerprint validation.
- Staleness guard wired into the live loop (evict stale quotes; never trade/mark on stale).
- Ops: supervisor (Restart=always), heartbeat, snapshot pruning, forward-PnL report
  scheduler.

## v3.7 Honest scope
- This is a PAPER forward experiment to validate (or kill) the directional copy edge OOS,
  measure capacity, and de-risk execution — BEFORE any capital. It is not a profit engine.
- Success = top − control significantly positive over a power-budgeted horizon, net of
  realistic cost, with manageable drawdown and capacity. Failure = it doesn't, and we
  shelve with a clean OOS answer.

---

# v4 BINDING REVISIONS (from the 3-lens architecture audit — pre-build, MUST hold)

The audits agreed: STRATEGY (v3.1, directional copy) is sound and rebuilds no dead-end.
The EXPERIMENT DESIGN must change before any code, or the run repeats this
investigation's own failure modes (false negative from underpower, false positive from
forking paths / survivorship / contaminated controls).

## v4.1 Re-point the question (what this run can and cannot answer)
- **It CAN answer (narrow, trustworthy):** does skill-based wallet *selection* beat a
  same-priced, eligible-pool control, OUT-OF-SAMPLE, in the forward regime, net of
  realistic cost, depth-capped at a stated notional?
- **It CANNOT answer on a months horizon:** portfolio Sharpe/CAGR/maxDD significance
  (needs ~years), cross-regime durability (one regime), full-size capacity. These are
  explicitly OUT OF SCOPE / descriptive only — never the headline or the gate.

## v4.2 The gate (replaces v3.5's ambiguity)
- **Primary metric:** per-round-trip **directional** (the deployed book; NOT neutralized),
  cost-inclusive net return, **top − primary-control**, headline = retail execution at one
  pinned lag bucket. Block-bootstrap 95% CI (block = follow window / overlapping-hold
  cluster) on **EFFECTIVE n** (the ~63 concurrent positions on shared beta make nominal n
  ≫ effective n).
- **Primary control = top-quintile − MEAN-of-eligible-pool** (and a random-roster arm),
  identically priced (same coins/lag/cost/caps → cost & beta cancel in the subtraction,
  so the SIGNAL headline is execution-invariant). The pool-mean arm is decision-relevant:
  if top ≈ pool-mean, the ranking is worthless (just follow everyone, cheaper/higher
  capacity). **Drop top−bottom from the verdict** (bottom's gap is the bad wallets' own
  execution cost — uncapturable — the +139bp ghost); keep only as a captioned diagnostic.
- Add a **sign-shuffle placebo** (random direction, same coin/window) to bound "any
  alt-long prints in an up regime."
- Sharpe/CAGR/maxDD are **descriptive, labeled single-regime & underpowered** — they do
  NOT drive go/no-go.

## v4.3 Pre-registration (close the forking-paths garden — the meta-lesson of this whole study)
Commit to an append-only registry BEFORE T0, then run blind to forward PnL until min-n:
- **ONE fully-numeric primary config** — every "e.g." resolved: max_coin_frac,
  max_wallet_frac, gross target, min_hold (selection only), train/follow lengths, the
  single headline lag bucket, min_positions, beta, universe, eligible-pool definition,
  control definition. **Retail execution is PRIMARY; validator is a labeled optimistic
  upside bound, never the headline.**
- **min-n** (nominal ≥1,500 round-trips AND an effective-n floor) **+ horizon cap ~9-12
  months**; **no verdict read before min-n; no peeking** (or a pre-declared group-sequential
  plan).
- **Numeric GO / NO-GO / INCONCLUSIVE**: GO = CI lower bound ≥ MAR above cost floor
  (e.g. +8-10bp net) AND top−control significant AND maxDD within bound AND depth-capped
  edge survives at target notional AND no single wallet/coin > X% of the spread. NO-GO =
  CI lb ≤ 0 OR top ≈ pool-mean OR cap kills it. INCONCLUSIVE = straddles MAR at horizon →
  no capital (one pre-declared extension max).
- **Commit the analysis-script hash**; one decision-maker reads ONCE against fixed thresholds.

## v4.4 Clean-OOS hardening (the contamination the fingerprint must catch)
- **`run_id = hash(T0, roster, per-wallet edge weights, full numeric config, per-wallet
  train-cutoff tid)`** — replaces the engine's seed+"follow"-name fingerprint, which lets
  a re-ranked roster resume silently. Restart HARD-BLOCKED from re-ranking; the roll
  SCHEDULE is pre-committed (cron-auto), no human re-fit.
- **Rolling seam:** train skill counts only round-trips **fully closed (incl. the lagged
  exit candle) strictly < the follow-window start**; freeze the train data snapshot at
  each T0 (no backfilled fills enter afterward); measure every forward round-trip from
  **OUR own fill at/after T0**, never the wallet's earlier entry.
- Charge **roster-churn turnover** at each roll (else it's the un-charged-turnover dead-end).

## v4.5 Survivorship census (honest dead tail)
Measure what a follower COMMITTED to the frozen roster at T0 actually earned, dead tail
included: hold every wallet to window-end, count dormant/blow-up periods (flat or realized
loss), never silently drop. Per-window census: N_followed / N_went_dark / N_blew_up /
N_active_at_close + per-wallet contribution distribution (one survivor can't carry it).
Pre-register a min-activity/min-history filter on the re-rank.

## v4.6 Execution fidelity (so the forward number == the +35-40bp prior)
- **Single cost source:** fold ALL cost (fee + spread + impact + slippage) into the
  realized fill price; the round-trip measure subtracts NOTHING further; journal
  `fee_e8`/`funding_e8` are report-only, never re-subtracted from a price-derived return.
- **PaperExecutor parity with `fill_model`**: add an impact/slippage knob, a depth/size
  cap, and a fill-price-source mode {live-touch | wallet-px (validator)} — or reuse
  `fill_model.fill()` fed the L2 book. Pass `taker_fee_bps=4.5` EXPLICITLY (default 0 =
  silent fee-blind bug). Pin the headline lag bucket.
- **Capacity:** depth-walk the real L2 and size-cap at a pre-registered max fraction of
  visible depth; report slippage-vs-size as the capacity proxy; run at a stated target
  notional (+ a larger one for decay). Headline = depth-capped, retail-lag, at stated
  notional (an UPPER bound; validator/same-block is more optimistic).

## v4.7 Engineering must-haves (unbuilt; integration risk)
- Watcher↔engine **atomic checkpoint** (engine holds the watcher, quiesces it via the
  per-wallet locks at the snapshot instant, co-writes both journal parts; `truth_up_all()`
  before the first post-restart tick).
- **Weight-aware throttle** (debit the userFillsByTime per-20-item surcharge) + 429 backoff
  on the watcher poll path; clarify the WS subset = ≤10 priority wallets (user-fills cap).
- **Staleness guard** (timestamp every quote; per-tick eviction before marks; halt-on-stale
  with a defined action). **Funding accrual** (periodic, material on multi-hour holds).
  **Watcher heartbeat** the engine consults.
- Per-coin cap via `RiskManager.clamp_target(per_asset_cap=…)` (no new logic); per-wallet
  weight cap = clip+renormalize at selection (new selection-side code). Note: `FrozenEdge`
  prior is INERT under `FixedFractionSizer` — edge enters only via consensus weights, not
  size; don't assume edge-scaled sizing.

---

## §v5 AS-BUILT (forward paper experiment — complete, audited, durable)

All five build steps are implemented, tested (65 follow tests), adversarially audited, and
hardened. Module map (`src/babylon/follow/` unless noted):

| concern | module | key surface |
|---|---|---|
| Pre-registration | `experiment.py` | `ExperimentConfig` (frozen, hash-bound), `RunManifest.build`, hash-chained tamper-evident `Registry`, read-once `decide()` |
| Per-wallet weights | `weights.py` | `kelly_weights` (SNR-shrunk inverse-variance, water-fill cap, thin-roster cap-respect) |
| Parity executor | `execution/paper.py` | `submit_book` (depth-walk VWAP, cost-in-price), `to_state`/`from_state` |
| Live run loop | `runner.py` | `FollowRunner` (two-clock, success-gated heartbeat, isolated loops, reduce-only dead-feed exit, flip hysteresis, chunked truth-up, MTM equity, funding, checkpoint), `attach_l2_feed` |
| Rolling re-rank | `scheduler.py` | `select_roster`, `RollScheduler.roll` (registers each sub-period's immutable manifest) |
| Measurement | `measure.py` | `measure` → `Results` → `decide`; block-bootstrap CI, effective-n, maxDD, concentration; `RollingEdgeMonitor` (observe-only) |
| Selection adapter | `selection.py` + `followable.followable_returns` | real fills → `returns_fn`/`cutoff_fn` (directional, seam-guarded) |
| Entrypoint | `live.py` | `LiveFollowSystem.build`/`run`; locks `wall_ms()`/`mono_ms()` clock contract |

**Run-loop audit (3-lens) outcomes, all fixed:** heartbeat-fresh-on-total-poll-failure
(CRITICAL), unisolated-tick zombie (HIGH), validator dead-arm (fail-fast), can't-flatten-
dead-feed (reduce-only exit), truth-up heartbeat starvation (chunked), clock contract
(two clocks). Verified-correct claims: tick() is await-free ⇒ atomic consensus snapshot;
weights cap provably correct (200k-fuzz) + unit-safe; submit_book bit-exact with the
backtest fill model.

**Real-data adapters + rolling re-rank — DONE.** `InfoClient` satisfies the watcher's
`FillSource`; `WebSocketFeed` is the l2Book feed; `fills_source.py` adds `RestFillsProvider`
(async prefetch + sync read, paginated past the 2000 cap) / `ParquetFillsProvider`. Mid-run
re-roll wired: `watcher.update_roster` + `runner.adopt_roster` + `LiveFollowSystem.reroll`/
`_roll_loop` (biweekly cadence, registers a new immutable manifest + adopts live).

**Remaining to ARM (ops/config + one small glue `main()`, no new core logic):**
1. `main()`: instantiate `InfoClient` + `WebSocketFeed` + `RestFillsProvider` +
   `SelectionAdapter`, load candle lookups + the candidate pool + 187-coin universe, lock the
   `ExperimentConfig` at T0, then `LiveFollowSystem.build(... prefetch=provider.prefetch,
   reset=adapter.reset)` + `run()`.
2. Deploy to the droplet, smoke under real load, then start. (Candidate pool + exact T0 are
   user decisions.)
