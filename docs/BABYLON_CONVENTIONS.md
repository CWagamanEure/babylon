# Babylon Conventions

Code conventions for the Babylon Hyperliquid trading system.

- **Decimals, not floats** for anything touching price/size/PnL — models parse Hyperliquid JSON into
  `Decimal` (`babylon.data.models`).
- Config via pydantic-settings, `BABYLON_` env prefix, validated at startup (fail fast). The secret key is
  a `SecretStr` and is not exposed by repr or `model_dump`.
- Structured logging via structlog (`babylon.logging`); console mode for dev, JSON for prod.
- WS feed (`babylon.exchange.websocket`) is single-connection, auto-reconnecting with backoff, replays
  subscriptions, races against a stop event so `stop()` tears down a live connection promptly. Handlers
  are registered per channel; one bad handler never kills the feed.
- Captured data → Parquet partitioned `{kind}/{coin}/{YYYY-MM-DD}/{wallclock_epoch_ms}_{seq}.parquet`, with
  one file per kind/coin/event-day represented in a flush. Buffers are dropped only after all writes succeed,
  but writes go directly to final filenames and are not crash-safe against abrupt process or host failure.
  Read with polars `scan_parquet`.
- Tooling: `uv run pytest`, `uv run ruff check`, `uv run mypy src` (strict, kept green). CLI entry:
  `uv run babylon <cmd>`.

## Quant/Data Gotchas

Locked after a four-agent audit on 2026-06-27:

- **Trade `side` is the taker AGGRESSOR**, not the resting book side: HL `"B"` = market buy, `"A"` =
  market sell. Modeled as `TradeSide.BUY/SELL` with `.sign` (+1/-1). Don't reintroduce BID/ASK naming —
  it inverts order-flow/CVD signals.
- **Unique keys**: trades `(time, tid)`, L2 snapshots `(time, ver_num)`. Many events share a `time` ms —
  never key on `time` alone.
- **Live public-market capture storage = float64, execution = Decimal.** The models under
  `src/babylon/data/` downcast in `to_row()`; do terminal PnL in Decimal/integer ticks. This does not apply
  to the authoritative `data/raw/fills/` tape, whose monetary and size fields remain exact strings.
- Parquet partitions are by **event time** (`record["time"]`), not capture wall-clock. Store uses explicit
  per-kind schemas (in `store.py _SCHEMAS`) that MUST match each model's `to_row()` keys (asserted in
  `test_store.py`).
- L2 books are validated (`L2Book.is_valid()`) before persisting; recorder dedups identical consecutive
  snapshot times.
