# Harvest executor — event-driven 6h drift harvester

The live runner currently MIRRORS wallet positions (reconcile-to-consensus). The edge
investigation (audit/EDGE_INVESTIGATION.md, [[babylon-edge-investigation]]) showed:

- The followed wallets are FAST — median hold ~10 min, 82% closed before 6h.
- The validated edge is a **fixed-horizon markout**: a conviction taker-open by a selected
  wallet predicts ~+30bp net drift over the next **6h**, computed BLIND to the wallet's exit.

So the strategy is **informed-flow momentum, not copy-trading**: the wallet's ENTRY is the
signal; we hold our OWN 6h clock; their exit is irrelevant. Mirror-exit captures the wallet's
round-trip — the quantity measured NULL. This executor harvests the validated quantity instead.

## Model: one tranche per open event

Each detected conviction taker-open (`skill.open_events`, the single source of truth shared with
selection) spawns a **tranche** with its own lifecycle:

```
open event @ T (wallet w, coin c, dir d)
  └─ ENTER at  T + entry_lag      (entry_lag = lag_bucket_ms, 15 min)
        └─ HOLD 6h                (markout_horizon_ms)
              └─ EXIT at entry_fill_t + 6h   (reduce-only, this tranche's size)
                    └─ realized round-trip → journal → gate (TOP arm)
```

Tranches are independent: many overlap (same coin, same/different wallets, both directions). Our
book at any instant = Σ active tranches. A tranche is harvested EXACTLY ONCE (keyed by open-event
id) — the "don't re-enter while the wallet still holds" trap of the mirror model disappears,
because we're event-driven, not position-driven.

## Why per-tranche orders (not net-reconcile)

The mirror runner batches everything into one reconcile-to-net order per coin. The gate needs
per-round-trip realized returns; net-batching destroys entry↔exit attribution AND can net two
opposite events into no trade (hiding the spread cost the gate must see). So each tranche gets a
DEDICATED entry order and a dedicated reduce-only exit order. Each tranche pays its own spread
in+out — faithful to the validated per-trade cost model (~15bp).

## Lag policy

Target entry time = `open_event_t + entry_lag` (15 min, matching the lag the SELECTION was scored
at — keep them consistent). Executed at `max(now, target)`: if we detect late we enter
immediately (lag ≥ 15 min, conservative). Record the realized entry lag per tranche so we know
which point of the lag-decay curve we actually live on (the crux forward-test risk).

## Disposition-free by construction → the gate measurement becomes valid

The study's round-trip scoring was null because the WALLETS' round-trips are dirty (heterogeneous
holds, censored losers). OUR harvests are uniform 6h, every open harvested, nothing censored — so
our realized round-trips are disposition-free. `measure.py`'s "per-round-trip net return" framing
is then CORRECT as-is; the fix was the executor, not the gate. Each closed tranche emits one
realized round-trip (neutralized downstream against the basket) = one obs for the TOP arm.

## Components

1. **`harvest.HarvestLedger`** (pure, this commit): the tranche state machine. Time-driven by the
   caller (`now_ms`). Enforces gross/per-coin caps. Emits realized round-trips on close. No live
   deps → fully unit-testable. THIS IS THE KEYSTONE.
2. **open-event detection (live):** the watcher poll stream → incremental `open_events`. Feeds
   `ledger.on_open_event`. (next)
3. **`HarvestRunner` (live):** polls ledger for `due_entries`/`due_exits`, submits IOC orders via
   PaperExecutor, feeds fills back (`on_entry_fill`/`on_exit_fill`). Reuses the mirror runner's
   staleness/halt-flatten/heartbeat/checkpoint machinery. (next)
4. **gate feed:** journal closed tranches; assemble TOP (our realized neutralized returns) vs
   CONTROL (pool-mean field over same windows); call `measure`→`decide`. (after)

## OPEN design decisions (NOT settled by the validation — flag before building 3)

The investigation validated PER-TRADE returns + selection. It did NOT validate a book-construction
/ sizing policy. These are genuine choices:

- **Per-event notional.** Equal notional per open event? Or wallet-Kelly-weighted? The validated
  field/selected means are equal-weight-per-open, which argues for equal notional per event. Kelly
  weights were a position-book concept; their meaning under per-event harvest is unclear.
- **Gross target & caps under overlap.** Σ active tranches fluctuates with signal arrival rate
  (~700 opens/wallet over the window → many overlaps). Need a gross cap and a per-event notional
  that targets a sane AVERAGE gross. Scale-to-fit on breach (log the drop — no silent truncation).
- **Drawdown sizing.** Memory: size off log-growth (+33), not arithmetic (+63); drawdowns ~halve
  realized edge. This is a sizing (not selection) lever and belongs here, not in selection.

The `HarvestLedger` is built sizing-AGNOSTIC: the caller passes a per-tranche notional, the ledger
only enforces caps + lifecycle. So these decisions can be made/changed without touching the core.
