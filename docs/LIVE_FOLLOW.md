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
