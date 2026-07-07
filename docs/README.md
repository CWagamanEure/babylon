# `docs/` — design & architecture notes

Design docs and architecture plans. Most are written "for audit" — a plan is drafted here, put through
an agent-swarm audit, then built. Status is stated at the top of each file.

| Doc | What it covers |
| --- | --- |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The deployable trading engine (`src/babylon/`) — strategies, engine loop, sizing, portfolio/risk, execution. **v2.** |
| [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md) | The data pipeline & repo-cleanup plan: raw-vs-derived rules, the research↔Gate-A firewall, the target `research/` layout, the DuckDB query layer. |
| [`WALLET_FEATURES_SPEC.md`](WALLET_FEATURES_SPEC.md) | **v2 spec** for the three-table trader-feature system (episodes base + leakage-safe `(address,coin,cutoff,window)` panels + cross-coin rollup). Tiered by data dependency; StableEdge markout estimator. This is what `research/data/episodes_build.py` implements. |
| [`BACKTEST.md`](BACKTEST.md) | Backtester architecture plan — replay archived L2 through the real engine, report-only. |
| [`LIVE_CAPTURE.md`](LIVE_CAPTURE.md) | Live capture & score architecture. |
| [`LIVE_FOLLOW.md`](LIVE_FOLLOW.md) | Live wallet-follow paper trader plan. |
| [`HARVEST_EXECUTOR.md`](HARVEST_EXECUTOR.md) | Event-driven 6h drift-harvest executor. |
| [`JOURNAL.md`](JOURNAL.md) | Durable state-journal design (crash recovery, SQLite schema). **v3.** |

See also the root [`README.md`](../README.md) for the two-lane overview, [`../CLAUDE.md`](../CLAUDE.md)
for working conventions (the over-nulling gate), and [`../markout_study/`](../markout_study/) for the
frozen edge study.
