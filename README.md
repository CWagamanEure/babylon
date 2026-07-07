# Babylon

A quantitative trading system for [Hyperliquid](https://hyperliquid.xyz) — programmatic execution with a
discretionary terminal layer for visualizing signals and firing manually. All trade decisions are
quantitatively driven.

The repo is **two lanes behind one firewall**:

- **`src/babylon/`** — the **deployable engine**. Production code only. Never imports from research.
- **`research/`** + **`markout_study/`** — the **analysis workbench**. Restores and queries the
  Hyperliquid tape, characterizes traders, runs the edge studies. Never shipped, never imported into the
  engine.

The firewall is load-bearing: the research lane computes *real* per-wallet PnL/markout; the frozen
validation pipeline (`markout_study/gate_a/`) runs only on synthetic/nullized data. They must not cross.
See [`docs/DATA_ARCHITECTURE.md`](docs/DATA_ARCHITECTURE.md).

## Repo map

| Path | What it is | README |
| --- | --- | --- |
| `src/babylon/` | Deployable async trading engine (paper + backtest today). | [`src/babylon/README.md`](src/babylon/README.md) |
| `research/` | Analysis workbench — DuckDB query layer over the Parquet tape, ingest, episodes, features. | [`research/README.md`](research/README.md) |
| `markout_study/` | The trader-markout / wallet-selection edge study (exploratory arc + frozen Gate-A pipeline). | [`markout_study/README.md`](markout_study/README.md) |
| `data/` | The Parquet lake (gitignored, regenerable): `raw/` tape + `derived/`. | see research README |
| `docs/` | Design & architecture notes. | [`docs/README.md`](docs/README.md) |
| `audit/` | Adversarial audit scaffolds + findings from the edge investigations. | — |
| `scripts/`, `notebooks/` | One-off tooling and analysis notebooks. | — |
| `tests/` | Engine test suite. | — |
| `deploy/` | Deployment config. | — |

`CLAUDE.md` holds the working conventions (report only out-of-sample multiplicity-controlled numbers; the
over-nulling gate; the standard architecture→audit→build→audit→run flow).

## The data pipeline

One authoritative tape, restored from Hyperliquid's node archive; everything else is a pure function of it
plus a code commit.

```
data/
  raw/                                       # IMMUTABLE, archive-sourced — the only precious bytes
    fills/month=YYYYMM/day=…/hourHH.parquet  # authoritative node_fills tape, majors {BTC,ETH,SOL,HYPE}
    asset_ctx/month=…                        # per-minute price/funding/OI, all coins (independent price)
    bars/coin=…                              # 5-min close lattice (not built yet)
  derived/                                   # REGENERABLE, code-stamped — safe to rebuild
    episodes/                                # per-(wallet,coin) position lifecycles
    wallet_features/                         # trader feature panels (not built yet)
```

Query it (no ETL — DuckDB views straight over Parquet):

```python
from research.data.db import connect
con = connect()
con.sql("SELECT coin, count(*) FROM fills WHERE month=202508 GROUP BY coin")
```

Money/size fields are stored as **exact strings** and cast to Decimal on demand — float is never
authoritative. Details, view list, and query conventions in [`research/README.md`](research/README.md).

## Engine — setup & usage

```bash
uv sync --extra dev          # create venv + install
cp .env.example .env         # then edit; start on testnet (BABYLON_ env prefix)
```

```bash
uv run babylon mids                      # snapshot all mids (connectivity check)
uv run babylon book BTC                  # top of book for one coin
uv run babylon stream --coin BTC         # live trade prints
uv run babylon record --coin BTC         # capture live trades + book → Parquet
uv run babylon backfill --coin BTC --start 20260601      # historical L2 from HL's S3 archive
uv run babylon backtest --coin BTC --start 20260601      # replay archived L2 through the real engine
uv run babylon paper --coin BTC          # paper-trade a toy strategy on the live feed (no signing)
```

Everything runs in **paper / backtest only** — no code path places a real signed order yet. The live
signing executor and terminal UI are the genuinely-absent pieces. Full subpackage map and current build
status: [`src/babylon/README.md`](src/babylon/README.md).

## Development

```bash
uv run pytest        # tests
uv run ruff check    # lint
uv run mypy src      # strict types
```

### Data-fidelity rules
- **Storage is float64; execution/PnL stays Decimal or integer ticks.**
- L2 snapshots key on `(time, ver_num)`, trades on `(time, tid)` — many events share a `time` ms, so
  never key on `time` alone.
- Trade `side` is the **taker aggressor** (`B` = market buy).
- Partitions are by **event time**, not capture wall-clock.
