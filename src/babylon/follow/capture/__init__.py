"""Live trade-capture & shadow-markout scoring (docs/LIVE_CAPTURE.md).

Shadow recorder: ingest watched wallets' fills, reconstruct round-trips with ONE shared
stepper, shadow-mark each against the live book at +lag (source=live) or fall back to the
re-fetchable candle (source=candle), persist to SQLite, and expose a rolling Sortino score.
Scores NOTHING into selection until validated — the candle path stays the live backbone.
"""
