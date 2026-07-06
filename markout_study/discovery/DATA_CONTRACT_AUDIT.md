# DATA_CONTRACT_AUDIT — position-metadata check before the frozen v1.0 counts audit

## RESTORATION VERDICT (2026-07-06, supersedes the infeasibility note below)
**Official backfill CAN restore v1.0.** The raw archive `s3://hl-mainnet-node-data/node_fills_by_block/hourly/YYYYMMDD/{hour}.lz4` contains the **complete per-user fill schema** for the whole window (verified on 2025-08-01): each event is `[user_address, {coin, px, sz, side, time, startPosition, dir, closedPnl, hash, oid, crossed, fee, tid, cloid, liquidation, builder, builderFee, feeToken}]`.
- **`startPosition`** is real and per-fill (self-anchoring — no q0=0 assumption, **no pre-window buffer needed**).
- **`dir`** is an explicit label set: `Open Long / Open Short` (increase), `Close Long / Close Short` (reduce/close), **`Short > Long` / `Long > Short` (flips)**, plus `Buy / Sell` for spot. Increase/reduce/close/flip is therefore recoverable **exactly** from `dir` (+ `startPosition` for residual/dust), better than a signed-fill ledger.
- **`closedPnl`**, full **`hash`** (⇒ `zhash` = `hash==0x0…0` reconstructable exactly; raw zero-hash frac = 20.4%), **`liquidation`** boolean (⇒ deterministic liquidation exclusion, resolving that ambiguity), **`oid`**, **`tid`**, user address all present.
- **Join to the current tape** by `tid` (+ wallet, coin, time) is 1:1 — `tid` exists in both.
- **Size / cost:** 211.9 GB LZ4-compressed for 2025-08…2026-06 (per-month 13.6–26.7 GB); ~**$19 egress** to local at $0.09/GB, **$0** on an in-region (us-east-1) box + ~negligible GET-request cost. Decompressed ≈ 0.5 TB; stream-filter to majors + needed fields, pair by `tid`, one hour at a time → RAM-safe on the 8 GB box.

The infeasibility below is **only** about the currently-loaded reduced projections (his export / cand2), which discarded these fields. It is not a property of the data that exists. The frozen v1.0 spec is unchanged; no q0 workaround is needed — the correct next step is a backfill of the authoritative archive, not a v1.1 redesign.

---

**Verdict (loaded projections only): Frozen v1.0 episode construction is INFEASIBLE on the currently-loaded reduced tape.** Increase/reduction/close/flip classification cannot be recovered from signed fills alone when the initial position is unknown, and `startPosition` is seeded to a constant `0.0` in the his/cand2 projections. The provisional run under `q0=0` is an **engineering diagnostic only**, not the frozen audit. (Superseded by the RESTORATION verdict above: the raw archive carries the missing fields.)

## 1. Schema inventory
| Source | Fields | Raw/derived | Identifies inc/red/close/flip w/o q0=0? |
|---|---|---|---|
| `other_repo_notes/fills_{Feb..Jun}.parquet` (upstream "his" export) | coin, ts, px, sz, **side**, taker, maker, notional, tid, **zhash** | third-party market-**trades** file | **No** — has trade `side` but **no `startPosition`, no `dir`, no `closedPnl`, no raw `hash`** |
| `scratch_conv/mlscreen/cand2_*.parquet` (our processed tape, 2025-08…2026-06) | wallet, ts, tid, coin, px, **sz (signed)**, crossed, zhash | derived from his export | **No** — `startPosition` dropped entirely; sign taken from `side` |
| `scratch_conv/mlscreen/cohort_fills_*.parquet` | coin, ts, px, sz, side, taker, maker, notional | derived (his) | No — same, no position metadata |
| `scratch_conv/mlscreen/positions_cert*.parquet` | open_ts, close_ts, direction, gross_pnl, fees, funding, net_pnl, entry_turnover, n_fills, hold_ms, open_at_end, reason, wallet, coin | **derived** round-trips | No — a *reconstruction* built from the same q0=0 signed fills + mark prices; inherits the artifact; not raw metadata or a snapshot |
| `scratch_conv/mlscreen/bars_*.parquet` | coin, bar (open, 5-min lattice), close | derived | n/a (prices) |
| live `data/follow/` fills (API) | includes real `startPosition` (forward only) | raw API | Yes — but **forward/live only, not the historical tape** |

## 2. Position-metadata coverage
- `startPosition`: **0% real** — literal `pl.lit(0.0)` in `split_his_fills.py:40`, `convergence_his.py:43,47`. Coverage across all historical rows/dates = constant 0.
- `dir` (Open/Close Long/Short): **absent** at every source.
- `closedPnl`: **absent** — the string does not occur anywhere in the codebase or any schema.
- Reduce-only / order metadata / account-position snapshots: **absent** in historical data.
- Prior team acknowledgement: `scripts/edge_sweep.py:16` ("his export carries no true startPosition (seeded 0)"), `scripts/selci_fh.py:9` and `selci2.py:110` ("Audit 11: drop leading position — possible pre-window seed artifact").

## 3. `zhash` semantic validation
- Transformation (our side): `hash = zhash ? ZERO_HASH : nonzero` (`skill.py` `ZERO_HASH`, `split_his_fills.py:33`); documented meaning `zhash=True ⇒ zero transaction hash ⇒ Hyperliquid TWAP (non-conviction) fills` (`convergence_his.py:33`).
- **Raw hash examples: unavailable** — the upstream his export already reduced the raw `hash` to the boolean `zhash` before it reached us (its schema has `zhash` but no `hash`). Row-level re-verification that every `zhash=true` is the all-zero hash **cannot be performed on our data**; the mapping is asserted by the pipeline/Hyperliquid semantics, not re-derivable here.
- **Correction to the earlier statement:** TWAP is therefore a **deterministic protocol-semantic flag** (`zhash=true`), **not** a statistical classifier needing a labelled precision threshold. TWAP exclusion is executable exactly (exclude `zhash=true`) **once episode construction is valid**. (Wash/bot still lack ground truth; liquidation is **not present in our processed tape**, **potentially** in unbuilt node-ledger data, and cannot currently be mapped to individual fills.)

## 4. ISO-week discrepancy
Correct ISO year-week key (`iso_year*100 + iso_week`, UTC) vs the provisional contiguous-7-day epoch bucket, measured on raw major-coin activity (well-defined, episode-independent): **552 of 32,919 wallets flip their ≥6-week status.** The epoch-bucket approximation is not acceptable; the ISO-week key is the correct frozen implementation. (True episode-based counts require valid episodes, which are infeasible under §2.)

## 5. Endpoint-presence correction
Presence is checked by **exact per-coin timestamp membership** (`searchsorted` + equality against the coin's close lattice), not `endpoint_ts ≤ global-max`. Per-coin 5-min lattice integrity (all months):
| Coin | bars | expected | internal missing bars | tape-end close |
|---|---|---|---|---|
| BTC | 96,169 | 96,193 | 24 | 1782864000000 |
| ETH | 96,168 | 96,192 | 24 | 1782864000000 |
| SOL | 96,168 | 96,192 | 24 | 1782864000000 |
| HYPE | 96,167 | 96,192 | 25 | 1782864000000 |
Internal missing bars are ~0.025% but **nonzero**, so exact membership (not a max-bound) is required; missing entry/endpoint bars must be reported separately from tape-end censoring. (Emitted as booleans/counts only; no markout values.)

## 6. Binary conclusion
**v1.0 episode construction is NOT executable exactly on the available data.** `startPosition` is unavailable (seeded 0.0) and no raw position/direction/`closedPnl` metadata or reliable snapshot exists in the historical tape; classification of reduction vs opening-short from signed fills is therefore unidentifiable. Do not treat the provisional waterfall as the official audit; do not declare J=20 / N_min=100 / any eligibility threshold feasible; do not proceed to positive controls. A position-aware episode definition (or a validated startPosition source) is a **v1.1** decision.
