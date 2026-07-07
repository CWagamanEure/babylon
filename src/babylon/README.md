# `src/babylon/` — the deployable trading engine

The production lane. Async-first quant trading engine for [Hyperliquid](https://hyperliquid.xyz).
Installs as the `babylon` package (`pyproject.toml`). **Production code only — never imports from
`research/` or `markout_study/`.**

> Everything here runs in **paper / backtest only**. No code path places a real signed order yet — the
> live signing executor and terminal UI are the genuinely-absent pieces (see status table).

Full design: [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) (engine v2), plus `docs/BACKTEST.md`,
`docs/JOURNAL.md`, `docs/LIVE_FOLLOW.md`, `docs/HARVEST_EXECUTOR.md`, `docs/LIVE_CAPTURE.md`.

## CLI

Entry point `babylon = babylon.cli:app` (Typer):

```bash
babylon mids                          # snapshot all mids (connectivity check)
babylon book BTC                      # top of book for one coin
babylon stream --coin BTC             # live trade prints
babylon record --coin BTC [--bbo]     # capture trades + L2 (+BBO) → Parquet under BABYLON_DATA_DIR
babylon backfill --coin BTC --start 20260601 [--end --hour --levels]   # historical L2 from S3
babylon backtest --coin BTC --start 20260601   # replay archived L2 through the real engine (Momentum)
babylon paper --coin BTC [--journal]  # MA-crossover toy in PAPER mode on the live feed
```

The **copy-trade follow system has its own argparse CLI** (not wired into the Typer app), run as a module:
```bash
python -m babylon.follow.main [--gate | --dry-run] [--selection roundtrip|markout|fixed] [--testnet]
```

## Config & secrets
`config.py` — `Settings` (pydantic-settings), env prefix **`BABYLON_`**, loads `.env`. `get_settings()`
singleton. Keys: `network` (default **testnet**), `account_address`, `secret_key` (`SecretStr`, never
logged), `data_dir`, `log_level`. Fails fast on half-configured trading; `can_trade` / `is_mainnet`
properties. `logging.py` — structlog (`get_logger`).

## The engine tick (within-tick phase order, strictly ordered)
`edge update → strategy directions → Sizer → per-strategy Risk → Net Risk uniform scale → Reconciler →
Executor → ledger attribution + invariant assert`. Orchestrated by `engine/engine.py::Engine`.
Strategies emit **direction only**; the Sizer owns magnitude; Net Risk owns the real account.

## Subpackages

| Package | Role & key modules |
| --- | --- |
| `exchange/` | HL connectivity. `rest.InfoClient` (async read-only `/info`), `websocket.WebSocketFeed` (auto-reconnect + heartbeat), `feed.Feed`/`NullFeed` (backtest seam), `constants.endpoints_for`. Order signing deferred. |
| `data/` | `models` (typed `Trade`/`L2Book`/`Bbo`/`Candle`; Decimal internal, float storage), `recorder`, `store.ParquetStore` (event-time partitioned), `archive.HyperliquidArchive` (S3 L2 backfill), `replay.L2Replay`, `candles`, `wallet_fills` (per-wallet copy-trade source). |
| `strategy/` | `base.Strategy` ABC (direction + `edge_prior`). `examples/ma_crossover.MACrossover` (paper), `examples/momentum.Momentum` (backtest). |
| `engine/` | `engine.Engine` (orchestrator), `clock.RealClock`/`SimClock` (replay seam), `context.MarketView`/`Context`. |
| `sizing/` | `kelly` (tail-aware log-growth maximization, stress floor, fractional cap), `edge.EdgeModel`/`BootstrapEdgeModel` (empirical return dist + pseudo-count confidence), `sizer.Sizer`. |
| `portfolio/` | `ledger.Ledger`/`Position` (per-strategy virtual ledgers, avg-cost PnL), `reconcile.Reconciler` (target→orders, deadband, cloids). |
| `risk/` | `manager.RiskManager` (per-strategy cap), `net.NetRiskManager` (real account: no-leverage, gross cap, latching max-DD kill → one uniform scale), `exposure` (measure/warn), `killswitch`. |
| `execution/` | `base.Executor` Protocol, `paper.PaperExecutor` (taker cross-spread, zero risk), `backtest.BacktestExecutor` + `fill_model` (walks replayed depth). **No `live.py` yet.** |
| `backtest/` | `runner.Backtester` (deterministic event-time driver through the *real* `engine._tick()`; gap-aware, staleness guard), `config`. |
| `journal/` | `journal.Journal` (SQLite WAL, `synchronous=FULL`, single-writer flock, money as scaled int; durable paper crash-recovery). |
| `stats/` | `metrics` (log-growth + max-DD; Sharpe flagged unreliable when Hill α<4), `gate.log_growth_gate` (moving-block bootstrap "is-it-real" lower bound), `decay.EdgeTracker` (EWMA), `monitor`. |
| `follow/` | **Copy-trade paper system** (largest subpackage) — the pre-registered forward experiment. `live`/`runner`/`watcher` (poll → consensus → reconcile → PaperExecutor), `strategy`/`weights`/`skill`/`followable`/`selection`, `harvest*` (6h-drift markout harvester), `experiment`/`measure`/`gate_feed`/`oos`/`walkforward` (governance + offline validation). |
| `follow/capture/` | Live trade-capture + **shadow**-markout scoring (`ingest`/`stepper`/`markout`/`scorer`/`store`). ⚠ Built + tested but **NOT wired into the live roll** — the candle path is the backbone until validated. |

## Build status (supersedes the root README's old table)

Everything below is **built and exercised** unless noted:

- ✅ config · logging · REST · WebSocket · data models · recorder/store · archive
- ✅ strategy · engine · Kelly sizing + edge · ledger + risk · paper executor
- ✅ **durable journal** (`paper --journal`) · **backtest executor + harness** (`babylon backtest`) · **stats/measurement**
- ✅ **follow copy-trade system** (own harness + argparse CLI)
- ⚠ `follow/capture/` shadow scorer — built + tested, **not yet wired live**
- ❌ **live signing executor** — absent (`rest.py`: signing "will live in a separate execution module")
- ❌ **terminal UI** — not present

Net: paper + backtest work end-to-end; no real orders are placed.

## Development
```bash
uv run pytest        # tests
uv run ruff check    # lint
uv run mypy src      # strict types
```

### Data-fidelity rules
- Storage is float64; **execution/PnL stays Decimal or integer ticks**.
- L2 keyed `(time, ver_num)`, trades `(time, tid)` — many events share a `time` ms; never key on `time` alone.
- Trade `side` is the **taker aggressor** (`B` = market buy).
- Partitions are by **event time**, not capture wall-clock.
