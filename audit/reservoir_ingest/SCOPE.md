# Reservoir alt-fills ingest — pre-build audit swarm scope

**What we're auditing:** the SPEC at `research/data/RESERVOIR_ALT_FILLS_SPEC.md` (design, not code yet) — find
design flaws BEFORE we build `reservoir_ingest.py` and pull 145 GB. Verify claims against REAL DATA, don't just
read the doc.

**Assets you have:**
- The spec: `research/data/RESERVOIR_ALT_FILLS_SPEC.md`.
- A real downloaded day: `/private/tmp/claude-501/-Users-corywagamaneure-bablyon/e7986c68-b22e-4ff8-a672-1a1b4b625c30/scratchpad/reservoir_day.parquet` (Reservoir perp/all, date=2026-06-01, 437 MB, 6.95M fills). Read it with DuckDB/`.venv/bin/python`.
- The authoritative node_fills majors tape via `from research.data.db import connect` → `fills` view (BTC/ETH/SOL/HYPE).
- More Reservoir days if needed: `aws s3 cp s3://hydromancer-reservoir/by_dex/hyperliquid/fills/perp/all/date=YYYY-MM-DD/fills.parquet <dest> --request-payer requester --region ap-northeast-1` (each cp ≈ $0.05; use sparingly, prefer the cached day).

**Discipline:** read-only on repo files (you MAY write scratch scripts in the scratchpad; do NOT edit the spec or
study files). Memory-safe DuckDB (`SET memory_limit='1200MB'; SET threads=1`). Follow `audit/AUDIT_PROTOCOL.md`
(verify-before-report, blast-radius severity, no edits). Return findings ranked most-decisive first; each with
(claim, evidence/number reproduced, does it block the build?, severity, fix).

**The single highest-value check** (whoever gets it): does Reservoir record **BOTH counterparties** of each trade
(like node_fills — so aggregate signed flow ≈ 0, which the whole wallet_flow OFI/flow construction relies on),
or a deduped/one-sided view? The 2026-06-01 sample showed a matched XPL buy(maker) + sell(taker) pair at
identical px/size — suggesting both sides. CONFIRM rigorously on a full day (Σ signed size per coin ≈ 0? maker/
taker counts balance?). If it's one-sided or deduped, the flow math and the majors reconciliation both change.
