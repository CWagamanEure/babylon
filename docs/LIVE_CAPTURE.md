# Live Capture & Score — architecture (draft for audit)

## Goal
Replace the coarse, backward-looking, candle-priced wallet ranking with a **forward,
sharp, self-building** one: from now on, capture every watched wallet's trades, shadow-mark
each round-trip against the **live order book at +lag** (the price *we* could actually get),
accumulate per-wallet followable returns, and expose a rolling **Sortino** score that feeds
`RollScheduler` — eliminating `followable_returns(candles)` for selection.

Two phases:
- **Phase 1 — known pool.** Capture the existing ~1,404 candidates (per-wallet `userFills`
  WS subs). Plugs straight into the current roller.
- **Phase 2 — discovery.** Ingest the full trade tape (HL node `--write-trades`) to harvest
  *new* addresses with edge that aren't in our list. Superset of Phase 1.

The candle path stays as a **bootstrap** until a wallet has enough live round-trips
(warm-up); then we switch that wallet to its live score.

## Why this shape
- The wallet's *own* fill price is their (uncopyable) execution. What we earn is the market
  price at `trade_time + lag`. That price isn't in their fills → we must snapshot the live
  book at the lagged moment. Doing it **live, forward** makes it sharp; doing it on history
  forces the candle proxy. So: capture forward.
- Same markout source as live execution (the L2 book) ⇒ selection and execution are priced
  coherently, by construction.

## Components
```
            ┌── l2Book WS ──► BookCache (in-mem: mid per coin)
            │                      │ (snapshot at due-time)
 userFills/ │                      ▼
 node tape ─┼─► Ingest ─► PositionTracker ─► MarkoutScheduler ─► RoundtripWriter ─► SQLite
            │   (dedup,    (dict[wallet→        (min-heap by      (finalize: ret_bps)   │
            │    cursor)    coin→signed pos])    due=t+lag)                             │
            │                                                                          ▼
            └──────────────────────────────────────────────────────  Scorer (rolling Sortino) ─► RollScheduler
```

1. **Ingest** — WS `userFills` per wallet (Phase 1) or node trade tape (Phase 2). Normalizes
   to `(wallet, coin, side, sz, px, time, tid, hash, startPosition)`. De-dups by `tid`;
   tracks a per-source `last_tid`/`last_time` cursor for restart.
2. **BookCache** — current L2 mid per coin from the l2Book WS feed (co-hosted). The markout
   price source — identical to live execution's.
3. **PositionTracker** — `dict[wallet → dict[coin → signed_size]]`, startPosition-anchored
   reconstruction (reuse `skill.reconstruct`). Emits `open`/`close` round-trip events.
4. **MarkoutScheduler** — min-heap keyed by `due = event_time + lag`. A loop pops due items,
   snapshots `BookCache` mid → fills the entry/exit markout for that round-trip.
5. **RoundtripWriter** — when both markouts known: `ret_bps = dir·(exit_mk/entry_mk−1)·1e4`;
   batched transactional insert into SQLite.
6. **SQLite** (durable):
   - `roundtrips(id, wallet, coin, entry_t, exit_t, dir, entry_mk, exit_mk, ret_bps)` —
     index `(wallet, exit_t)`.
   - `open_state(wallet, coin, signed_size, entry_t, entry_mk_px, taker_open, conviction)` —
     in-flight positions + their (already-taken) entry markouts, for restart.
   - `wallets(address, first_seen_ms, last_seen_ms, n_roundtrips)` — the discovered set.
   - `meta(key, value)` — schema version, ingest cursors, last_book_resync_ms.
7. **Scorer** — monthly (or per roll): `SELECT ret_bps WHERE wallet=? AND exit_t >= cutoff`
   → Sortino (μ/downside-dev). Feeds `RollScheduler` via the `ReturnsFn`/`CutoffFn` interface,
   replacing `SelectionAdapter`. Wallets with `< min_positions` live round-trips fall back to
   the candle bootstrap.

## Lifecycle of one round-trip
1. Fill ⇒ PositionTracker: flat→position ⇒ `open(wallet, coin, dir, t_entry)`.
2. Schedule entry markout `due = t_entry + lag`.
3. Fill(s) ⇒ position returns to flat ⇒ `close(wallet, coin, t_exit)`.
4. Schedule exit markout `due = t_exit + lag`.
5. At each due-time: read `BookCache[coin].mid` → store entry_mk / exit_mk.
6. Both present ⇒ compute `ret_bps` ⇒ persist finalized roundtrip; drop from open_state.

## Restart recovery
- Rebuild PositionTracker from `open_state`.
- Re-derive pending markouts: any `open_state` row whose `entry_mk` is null and whose
  `t_entry+lag` is still in the future → reschedule; if already past → mark immediately with
  the current mid and flag `late_markout` (lossy — see audit risks).
- Resume Ingest from the `meta` cursor; on reconnect, REST `clearinghouseState` per wallet to
  TRUTH-UP positions (a WS gap means missed fills → drift) before trusting new fills.

## Phase-2 discovery (full tape)
- Source: HL node `--write-trades` (every trade carries both addresses) → harvest every
  active address into `wallets`. Track a rolling "active in last 30d" candidate set.
- Score everyone the same way; `RollScheduler` candidate pool = active set with
  `n_roundtrips ≥ min_positions`. New edge-holders enter automatically; dormant ones age out.

## Locked invariants (so it can't silently corrupt)
- **Markout source == live-execution source** (same BookCache). Never candle, never wallet fill.
- **`lag` == the live system's real detect→enter latency.** One config value, shared.
- **Forward-only.** A round-trip is scored from data that all post-dates capture start; no
  backfill into the live score (backfill stays candle-tagged + separate).
- **Closed round-trips only** are scored (consistent with the gate), with the disposition
  caveat acknowledged (open losers never score → upward bias; mitigate by also recording
  unrealized marks at the cutoff — see audit).

---

# AUDIT OUTCOME + v2 REVISIONS (3-agent adversarial swarm)

**Blast radius (the orienting fact): the capture score feeds SELECTION ONLY.** The GO/NO-GO
gate (`measure`→`decide`) reads realized paper fills, not this score, and its hash-chained,
read-once, min-n-recomputed machinery is untouched. So a bad capture score **cannot fake a
GO** — it can only pick a worse roster → dilute the top arm → bias toward INCONCLUSIVE (a
*power* loss, not a false positive). This bounds everything below.

**The candle path it replaces already works** (validated OOS-persistent) and is
**deterministic + re-derivable** (fills+candles+config), which is what makes the
pre-registration auditable. So this upgrade is an *improvement, not a necessity* — sequence
accordingly.

## Must-fix before this can replace the candle path
1. **Pre-registration / re-derivability [CRITICAL].** A mutable, non-deterministic scoring
   DB (ephemeral book snapshots; `late_markout` depends on restart timing) means the roster
   is no longer re-derivable from committed inputs → the manifest is tamper-evident about
   the *outcome* but can't prove it's the honest *output of the rule*. FIX: snapshot the
   per-T0 `{roundtrip_id→ret_bps}` used, fold its content-hash into `run_id`, and make
   scoring DETERMINISTIC (drop `late_markout`; recompute from an archived/durable mid log).
2. **Open-position censoring / disposition bias [HIGH].** Closed-only scoring drops
   open-at-cutoff positions, which are disproportionately losers → +15bp (long-hold) to
   **+122bp in the 7-day warm-up (9× true edge)**, worst for our target population at the
   moment we'd first trust it. FIX: MTM every open position at the cutoff as a hard part of
   the Scorer query, and/or **fixed-horizon markouts** (mark at entry+H regardless of the
   wallet's exit).
3. **Cost + netting [HIGH].** The mid-to-mid, per-wallet, frictionless score is biased high
   vs what we NET (spread+impact+fee, netted-per-coin), diverging most at the roster
   boundary (gross≈cost floor) and on thin alts. The "coherent by construction" claim is
   FALSE (coherent *source* ≠ coherent *cost/aggregation*). FIX: subtract per-coin modeled
   round-trip cost (executor's cost source) BEFORE Sortino; mark at the aggressing touch not
   mid; score marginal-consensus contribution (or down-weight signal collinear with
   consensus); pin `lag` to the MEASURED live latency distribution (p50/p75), not a scalar.
4. **Warm-up bootstrap blend [HIGH].** Co-ranking coarse candle scores and sharp live scores
   on one scale = two differently-biased estimators + winner's-curse on the max; fresh live
   wallets enter at the noisy floor. FIX: stratify (quota per source) or calibrate onto one
   scale; shrink the Sortino RANK (empirical-Bayes), not just the Kelly weights; raise the
   live-eligibility floor ≫6.
5. **Phase-2 survivorship [HIGH].** "Active-30d + ≥min CLOSED round-trips" re-introduces the
   survivorship+disposition bias the broad pool removed, and makes the pool endogenous (same
   DB = discovery + score + control). FIX: eligibility on a performance-/disposition-FREE
   pre-T0 activity criterion (raw fill count), frozen per sub-period, hold the dead tail in
   the §v4.5 census; keep discovery SEPARATE from scoring.
6. **Reflexivity [MED→HIGH at scale].** We mark all wallets on the book OUR taker flow moves
   → inflates incumbents we trade. Negligible at $1k, real at target notional on thin alts.
   FIX: flow-independent reference (snapshot pre-order / net out our fills); bound + monitor
   our per-coin volume share.

## Engineering must-fixes
- **Bounded dedup** (the spec'd `tid` set is unbounded → ~3.5GB/day OOM): use the `last_tid`
  cursor + a windowed LRU, not an ever-growing set.
- **One shared `step(fill)→[events]` stepper** for batch AND live (don't fork `reconstruct`,
  which is batch+closed-only and emits no open event); handles flips (2 events), adds
  (size-weighted entry), out-of-order (reorder buffer), and an `unmarkable` flag for
  cold-start-seeded positions (null entry basis).
- **WS `userFills` replays on resubscribe** → bounded `seen_tids` LRU before applying.
- **Durable sampled-mid log** (or replay the S3 L2 archive) so a markout due-time that passed
  during downtime is looked up at its TRUE instant, else dropped — never `late_markout`.
- **Reconnect: backfill `userFillsByTime` BEFORE truth-up** (truth-up restores positions, not
  entry_t/markouts); **lazy** per-wallet truth-up (avoid the 23-min blind window at <1 req/s).
- **BookCache freshness contract** `(bid,ask,mid,ts)` + crossed/empty validation + short
  median/TWAP around t+lag, not a 1-ms mid.
- **Ops:** separate process under a hard memory cgroup (failure isolation from the trader);
  WAL + batched commits; shard the WS subs across connections; mids-only book feed (the
  l2Book full feed is the real GIL bottleneck).
- **Phase 2 is its own infra:** dedicated HL node box (≥4CPU/16GB, ~20GB logs/day) + capture
  box, a SECOND IP (escape the rate limit), Parquet-append + DuckDB (not SQLite) — ~$150–300/mo.

## Recommended sequencing (shadow-first)
1. **Keep the candle path live** for the running experiment (works, deterministic, preserves
   pre-registration). Do NOT swap.
2. **Build the capture service as a SHADOW recorder** now: ingest + markout + store, scoring
   nothing into selection. Zero risk to the experiment; starts accumulating sharp forward
   data immediately (also solves warm-up by pre-aging the data).
3. **Validate** the live-captured score over weeks against (a) the candle score and (b) our
   realized fills — confirm it predicts NET, calibrated, and that the disposition/cost fixes
   work.
4. **Swap in only with fixes #1–#4** (esp. the run_id DB-hash for re-derivability), once
   proven. Phase 2 (discovery) is a later, separate-infra project.

## Retention & resilience (droplet-bounded, fail-safe)
- **Cheap vs expensive:** round-trips (`ret_bps`) are tiny (~10 MB/month Phase-1) — keep ~1yr.
  Raw fills are bigger — keep a rolling ~3–7 days (restart + open-position buffer only). A
  per-second mid-log would be the real beast (~10 GB/month) → DON'T keep it; on restart DROP
  in-flight markouts that came due during downtime (lose a small fraction, no storage).
- Nightly prune: `DELETE WHERE exit_t < now − retention`. Config: `roundtrip_retention_days`
  (365), `fill_buffer_days` (7). Phase-1 disk stays < 1 GB.
- **Resilience invariant — candle is the re-fetchable FLOOR, live capture an additive upgrade.**
  Fills are always backfillable (REST `userFillsByTime`), so we never lose *when/what* a wallet
  traded. Only the markout *price* is ephemeral: a round-trip gets `source=live` (sharp book
  mark) when capture is healthy, else `source=candle` (re-fetchable proxy) — every round-trip
  is ALWAYS markable. A total capture failure degrades to exactly today's (validated) candle
  system; the capture layer can only sharpen, never break us below the floor. The `source` tag
  also serves the pre-registration determinism (reproducible-candle vs ephemeral-book marks).
