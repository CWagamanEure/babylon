# Babylon

A quantitative trading system for [Hyperliquid](https://hyperliquid.xyz) — mostly
programmatic execution with a discretionary terminal UI layer for visualizing
signals and firing manually. All trade decisions are quantitatively driven.

## Status

**Phase 1 — Data foundation** ✅ · **Phase 2 — Engine (paper skeleton)** in progress.
Engine design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

| Layer             | Module                          | State |
| ----------------- | ------------------------------- | ----- |
| Config / secrets  | `babylon.config`                | ✅    |
| Logging           | `babylon.logging`               | ✅    |
| REST info client  | `babylon.exchange.rest`         | ✅    |
| WebSocket feed    | `babylon.exchange.websocket`    | ✅    |
| Data models       | `babylon.data.models`           | ✅    |
| Capture → Parquet | `babylon.data.recorder/store`   | ✅    |
| Historical L2 (S3)| `babylon.data.archive`          | ✅    |
| Strategy / Context| `babylon.strategy`,`engine`     | ✅    |
| Kelly sizing+edge | `babylon.sizing`                | ✅    |
| Ledger + risk     | `babylon.portfolio`,`risk`      | ✅    |
| Paper executor    | `babylon.execution.paper`       | ✅    |
| Engine (paper)    | `babylon.engine.engine`         | ✅    |
| Durable journal   | —                               | ⏳    |
| Backtest executor | —                               | ⏳    |
| Live executor     | —                               | ⏳    |
| Stats / measurement| —                              | ⏳    |
| Terminal UI       | —                               | ⏳    |

## Setup

```bash
uv sync --extra dev          # create venv + install
cp .env.example .env         # then edit; start on testnet
```

## Usage

```bash
uv run babylon mids                      # snapshot all mids (connectivity check)
uv run babylon book BTC                  # top of book for one coin
uv run babylon stream --coin BTC -c ETH  # live trade prints
uv run babylon record --coin BTC         # capture LIVE trades + book to Parquet

# Backfill HISTORICAL L2 snapshots from Hyperliquid's public S3 archive:
uv run babylon backfill --coin BTC --start 20260601               # one full day
uv run babylon backfill --coin BTC -c ETH --start 20260601 --end 20260603 --hour 0

# PAPER-trade the toy MA-crossover strategy on the live feed (no signing, no risk):
uv run babylon paper --coin BTC -c ETH
```

Captured data lands under `BABYLON_DATA_DIR` partitioned as
`{kind}/{coin}/{date}/{epoch_ms}.parquet`. Live and historical L2 share one
schema (`time`, `best_bid/ask`, `mid`, and `bid_px/bid_sz/ask_px/ask_sz` depth
lists) so the backtester reads both the same way.

### Historical archive notes

`babylon backfill` reads `s3://hyperliquid-archive/market_data/...`, which holds
**L2 book snapshots only** (~2/sec), uploaded roughly monthly. The bucket is
**requester-pays**: you need AWS credentials configured and you pay egress.
Historical *trades* are not in this bucket — they live in separate node buckets
and will be wired in later if needed.

## Architecture

Async-first. A single reconnecting WebSocket feed fans messages out to typed
handlers; the REST client covers read-only `/info` queries. Order signing (EIP-712)
will be delegated to the official `hyperliquid-python-sdk` in the execution layer.

## Development

```bash
uv run pytest        # tests (all green)
uv run ruff check    # lint (clean)
uv run mypy src      # types (strict, clean)
```

### Data-fidelity notes

- **Storage is float64; execution stays Decimal.** Market data is parsed to
  `Decimal` then downcast to `float` for Parquet (compact, analytics-friendly).
  Do terminal PnL/position rollups in Decimal or integer ticks.
- **L2 keys.** Trades are keyed `(time, tid)`, L2 snapshots `(time, ver_num)` —
  many events share a `time` ms, so never key on `time` alone.
- **Trade `side` is the taker aggressor** (`B` = market buy). See `TradeSide`.
- **Live L2 is coarser than the archive.** The WS `l2Book` feed delivers
  ~0.3 snapshots/sec vs the S3 archive's ~1.85/sec; treat the archive as the
  higher-fidelity historical source.
- Partitions are by **event time**, not capture wall-clock.
