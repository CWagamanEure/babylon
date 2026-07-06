# RESTORE_PLAN_v1 — restore & run frozen Gate-A v1.0 from `node_fills_by_block`

**Status: APPROVED 2026-07-06 subject to corrections 1–4 (now applied) — full download NOT yet started.** Corrections: (1) exact Decimal128 position arithmetic, no epsilon; (2) no taker-only filter — process maker & taker; (3) frozen fill-level TWAP/liquidation rule (ledger-updating, non-episode-opening, no wallet %-threshold); (4) start-position anchoring + permanent source-row identity, narrowed quarantine. Frozen GATE_A_FROZEN_CONFIG v1.0 is otherwise unchanged; this plan only restores the position-carrying fills the loaded projections dropped, then runs the frozen episode build + counts-only feasibility audit as written. Execution proceeds only through the §7 staged gates (1 h → arithmetic+uniqueness check → 1 day → 1 month → full).

Source: `s3://hl-mainnet-node-data/node_fills_by_block/hourly/YYYYMMDD/{H}.lz4` (requester-pays). Window 2025-08 … 2026-06 = **211.9 GB LZ4**, 744 objects/month (~8,184 objects; verify each month = days×24 in the manifest).

---

## 1. Processing architecture (RAM-safe, in-region preferred)
Run in **us-east-1** (small EC2: 4–8 vCPU, 16 GB RAM, ~100 GB gp3 EBS) → **$0 egress**; only the ~15–25 GB filtered parquet leaves the region (or stays in S3). Local fallback = process on the 8 GB box paying ~$19 egress; slower, single-threaded.

Per hourly object (embarrassingly parallel across objects):
1. `GET` object → **stream** through `lz4.frame` incremental decoder (never materialize the whole file);
2. parse **line-delimited JSON** block-by-block; for each block iterate `events`;
3. **retain only `coin ∈ {BTC,ETH,SOL,HYPE}`** (perp symbols; drop spot `@N` / HIP-3). **Retain every per-user fill, maker AND taker** — `crossed` is stored as metadata but is **not** a drop filter (correction 2). Each user-event is one wallet fill; counterparties are **not** paired or collapsed;
4. project the normalized schema (§2), preserving nulls;
5. append to an in-memory buffer for that object; on completion write **one atomic parquet part** `fills_major/month=YYYYMM/day=YYYYMMDD/hourHH.parquet` (tmp-write + rename);
6. update the manifest row; discard raw bytes.

- **Temp disk:** streaming, one object at a time → transient decompressed ≈150–250 MB + a <~50 MB major-row buffer; **peak working < 1 GB**. Raw `.lz4` are **not** retained.
- **Final filtered dataset:** majors ≈ same row order-of-magnitude as the current cand2 major tape (~1.3×10⁸ fills) × ~18 columns, parquet-compressed ≈ **15–25 GB**.
- **Restart/checkpoint:** manifest-driven, idempotent per hour. On restart, skip any object whose manifest status = `done` **and** whose output part exists with matching `retained_major_rows`. Atomic rename means a killed process never leaves a half-part that reads as complete (contrast the ml-repo bug where a partial gz counted as done). A per-object `schema_version` + `code_commit` invalidates stale parts on a code change.

## 2. Authoritative normalized fill table + manifest
**Normalized schema (one row per user-event; nulls preserved, never zero-filled):**

| col | type | source |
|---|---|---|
| wallet | str | `events[i][0]` (user addr) |
| coin | str | field |
| ts | i64 ms | `time` |
| px | **str + Decimal128** | `px` |
| sz | **str + Decimal128** | `sz` (magnitude) |
| side | str `B`/`A` | `side` |
| start_position | **str + Decimal128** | `startPosition` |
| dir | str | `dir` |
| closed_pnl | **str + Decimal128** | `closedPnl` |
| hash | str (66) | `hash` (full) |
| oid | i64 | `oid` |
| tid | i64 | `tid` |
| cloid | str/null | `cloid` |
| crossed | bool | `crossed` |
| fee | **str + Decimal128** | `fee` |
| fee_token | str | `feeToken` |
| liquidation | bool/null | `liquidation` |
| builder | str/null | `builder` |
| builder_fee | **str + Decimal128/null** | `builderFee` |
| src_object | str | S3 key |
| block_number | i64 | block `block_number` |
| block_time | str | block `block_time` |
| event_index | i32 | **globally-increasing index within the source object** (see below) |

**Exact-decimal rule (correction 1):** for `px, sz, start_position, closed_pnl, fee, builder_fee` the **authoritative stored representation preserves the original numeric string and/or an exact Decimal128 parse** of it. Binary float64 is **never** the authoritative representation and **never** governs increase/reduce/close/flip classification; a convenience float column may be carried only for downstream numerical work. All position arithmetic and sign/zero tests use exact decimal at the asset's documented quantity precision (correction 1, §3).

**`event_index` (correction 4):** constructed as a **globally-increasing counter over emitted events within a single source object** (block order, then event order within `events[]`). The **permanent source-row key** is `(src_object, block_number, event_index, wallet, tid)`; the build **asserts this key is unique** per object and across the run — a duplicate is a hard error, not silently deduped.

**Fail-loud rule:** if any **frozen-required** field (`wallet, coin, ts, px, sz, side, start_position, dir, tid, hash`) is null on a retained major-coin row → record the offending `(src_object, block_number, event_index)`, increment a hard-error counter, and **abort the object** (no silent partial). Optional/absent fields (`cloid, liquidation, builder, builder_fee`) may be null.

**Manifest** (`manifest.parquet`, one row/object): `object_key, expected(bool), status∈{pending,done,failed}, size_bytes, etag, decoded_rows, retained_major_rows, ts_min, ts_max, hard_errors, schema_version, code_commit`. Completeness check = every `expected` object present with `status=done`; missing/failed listed explicitly (no silent gaps).

## 3. Mechanical transition classification — EXACT DECIMAL (dir = reconciliation only)
All quantities are exact Decimal128, each **quantized to the asset's documented quantity precision** (`szDecimals` per coin from the HL meta) before the sign/zero tests. **No epsilon.** Zero means exactly zero at that precision; a genuine small residual is never rounded to flat.
```
signed_fill = sz if side == "B" else -sz         # user's own side; B=buy(long+), A=sell(short-); Decimal
q_before    = start_position                      # Decimal, quantized to szDecimals[coin]
q_after     = quantize(q_before + signed_fill, szDecimals[coin])

if q_before == 0 or sign(signed_fill) == sign(q_before):
    cls = INCREASE                                # open-from-flat or add
elif sign(q_after) == sign(q_before) and abs(q_after) < abs(q_before):
    cls = REDUCE                                  # partial reduce, same side
elif q_after == 0:
    cls = CLOSE                                   # exactly flat
else:                                             # sign flipped, q_after != 0
    cls = FLIP
    close_qty    = abs(q_before)                  # closed leg
    residual_qty = abs(q_after)                   # newly opened leg
    residual_dir = sign(q_after)

# independent reconciliation — RECORD, never resolve:
expected = { 'Open Long':INCREASE,'Open Short':INCREASE,
             'Close Long':{REDUCE,CLOSE},'Close Short':{REDUCE,CLOSE},
             'Long > Short':FLIP,'Short > Long':FLIP,
             'Buy':SPOT,'Sell':SPOT }
disagree += (cls not in as_set(expected[dir]))    # tally by (dir, cls)
```
Verified against the sample: `startPosition=-131716.8, side=B, sz=1804.1, dir="Close Short"` → `q_after=-129912.7` (REDUCE of a short) ✓; `startPosition=14898.6, side=A, dir="Close Long"` → REDUCE of a long ✓. So HL `Close X` = *reducing toward flat* (partial included); arithmetic distinguishes REDUCE vs CLOSE, `dir` cannot.

**Chain-consistency check (independent of dir):** for consecutive same-`(wallet,coin)` fills, assert **exact-decimal** `start_position[k+1] == quantize(start_position[k] + signed_fill[k], szDecimals[coin])` (equality at quantity precision, no tolerance). Count breaks → detects missed fills, spot/perp mixing, or archive gaps; a break beyond exact precision quarantines the wallet-coin stream (§ correction 4). Report break rate per coin.

## 4. Join validation to the existing tape (cand2 = reference only)
Candidate keys, tested in order: `(tid,wallet)` → `(tid,wallet,coin)` → `(tid,wallet,coin,ts)`. For each report: uniqueness rate in **archive** and in **cand2**; unmatched archive rows; unmatched cand2 rows; 1:many & many:many counts; agreement of `px,sz,side,crossed` and reconstructed `zhash`; `ts` deltas. A raw trade yields **two per-user rows** (both counterparties) — these are kept as **separate wallet fills** (correction 2), so `tid` alone is ~2:1 in the archive; `(tid,wallet)` should be the narrowest stable unique key — **confirm, don't assume.** Use the narrowest key that is actually unique+stable. The rebuilt pipeline reads the **archive directly**; cand2 is used only to confirm the restored tape reproduces the known tape (coverage + field agreement), not as an input. **Note:** cand2 is a taker-biased projection, so unmatched-vs-cand2 rows are *expected* wherever the archive carries maker fills cand2 dropped — that is a coverage gain, not a join defect.

## 5. Protocol-semantic validation (on the restored archive)
- `zhash := (hash == 0x0…0)`; report zero-hash fraction (~20% expected; day-gate 12.5%) and agreement vs cand2 `zhash` on joined rows.
- `liquidation`: **struct** `{liquidatedUser, markPx, method}`, present only on liquidation fills; report presence-rate and `liquidatedUser==wallet` split per coin/month (day-gate: 81,656 rows, exactly 50/50 forced/counterparty, method=`market`).
- `start_position`: non-null coverage (target 100% on retained rows; any null = fail-loud §2). **Quantize to szDecimals before any test** — the raw archive carries float64 round-trip noise (day-gate: 930/1.8M HYPE positions like `985263.5699999999`); quantization recovers the exact protocol value and is why exact chain-consistency holds.
- **szDecimals** pinned from HL `meta` (`sz`-grain confirms BTC5/ETH4/SOL2/HYPE2 at 4.7M-row scale); recorded in manifest `schema_version`.
- `dir` value distribution; per-coin & per-hour `ts` coverage; duplicate `(tid,wallet,event)` rate; missing hourly objects (from manifest); internal time gaps.

## 5b. Fill-flag / episode rule — FROZEN (correction 3), ledger-consistent
- **Every** fill — including zero-hash TWAP and liquidation-origin fills — **updates the wallet's true position ledger** (`q_before`/`q_after` chain). Flags never remove a fill from the ledger.
- A **flagged fill (zhash TWAP or liquidation) may not open or extend a qualifying signal episode.** A flagged **reduce/close/flip still terminates or changes** an already-open episode under the ordinary transition + dust rules. A flagged **flip's residual opening leg does not create** a new qualifying episode.
- **`liquidation` is a struct** `{liquidatedUser, markPx, method}` (NOT a boolean), stamped on **both** sides of a liquidation trade (day-gate: 50/50 forced-party vs counterparty). **RULING A (NARROW, FROZEN 2026-07-06):**
  ```
  liquidation_origin = liquidation struct present
                       AND normalize(liquidation.liquidatedUser) == normalize(wallet)   # lowercase-hex compare
  liquidation_touching = liquidation struct present                                      # separate diagnostic only
  ```
  Both counterparties' fills update their ledgers. **Only the forced/liquidated wallet's fill (`liquidation_origin`) is prohibited from opening/extending a qualifying episode**; its reduces/closes/flips still terminate/change existing episodes normally. The counterparty's fill is an ordinary fill and **may open an episode** (it voluntarily supplied liquidity / took the other side). Rationale: broad treatment would discard discretionary flow merely for trading against a forced counterparty — that is not "liquidation-origin." **Required validation to report:** forced-party fills by transition class; counterparty fills by transition class; count where `liquidatedUser` matches neither per-user record of the trade; malformed/missing `liquidatedUser`.
- Episode counts, active days, J coverage, standardization, scores and outcomes use **only episodes opened by unflagged qualifying INCREASE fills.**
- **No wallet is excluded merely for having some TWAP/liquidation fills** — a wallet with too few unflagged qualifying episodes simply fails the frozen activity thresholds. **No wallet-level percentage threshold is invented.**
- **Accounting outputs only** (per wallet & fold, never a gate/score): total fills, zero-hash fills, liquidation fills, qualifying signal-opening fills.

## 6. Staged episode-build validation (firewalled: no markout/score/ranking shown)
Rebuild the frozen episode builder to consume **real `start_position` + `dir`** with **exact decimal** arithmetic (this *is* the frozen "startpos reconstructed" step, done exactly — the q0=0 ledger was the infeasible stand-in), applying the §5b fill-flag rule. Run **1 hour → 1 day → 1 month**; at each stage validate: exact position arithmetic & chain consistency; **source-row-key uniqueness** `(src_object,block_number,event_index,wallet,tid)`; INCREASE/REDUCE/CLOSE/FLIP counts; flip residual (`close_qty`,`residual_qty`,`residual_dir`); dust ($100 increase floor; reduction floor `max($100,10%·peak)`); 30-min gap boundaries; 8-h earliest-wins dedup; exact 5-min entry-close mapping (strict-after, per-coin lattice membership); per-coin endpoint existence at 1/2/4/8 h; §5b TWAP/liquidation episode rule (flagged fills update ledger but don't open episodes); the per-wallet/fold flag accounting; **deterministic rerun equality** (byte-identical parts on re-run). Only booleans/counts surface.

## 7. Staged execution gate → full backfill
Strict order, each stage a gate: **(1)** one-hour sample → **(2)** verify exact-decimal position arithmetic **and** source-row-key uniqueness → **(3)** one-day sample → **(4)** one-month validation → **(5)** only then the full backfill. Then: 2025-08 … 2026-06 → restored `fills_major` → frozen episode build (§5b, exact decimal, quarantine rule) → **counts-only feasibility audit** (the same 7-output firewalled audit, now on position-correct episodes). **No frozen threshold modified. No positive controls until the official counts audit passes.**

## 8. Compute / disk / transfer estimate
- **Transfer:** $0 in-region; ~$19 to local. GET requests ~8.2k × $0.0004/1k ≈ negligible.
- **Compute (PROVISIONAL engineering guidance — NOT an acceptance condition):** JSON parse + exact-decimal work is the bottleneck (~8.2k objects). In-region 8-core: parallel ~**30–60 min**; local 8 GB single-thread: several hours → overnight. Correctness gates (§7), not wall-clock, decide progression.
- **Disk:** temp < 1 GB (streaming); final normalized parquet **~15–25 GB**; episodes parquet ~ small (counts-only fields).

## MONTH GATE RESULT — 2025-08 (PASS, 2026-07-06)
Streamed 744/744 objects → **87,899,062 major fills**, 31 days, 3.4 GB Parquet, raw discarded.
- **Source-row-key `(src_object,block_number,event_index,wallet,tid)`: 100% unique** (87,899,062/87,899,062).
- **Chain-consistency: 15 breaks / 87,674,610 checks (1.7×10⁻⁷)** — genuine small position discontinuities (~0.003–0.5 unit), tied to vault/liquidation edge events or occasional missing fills → the 15 wallet-coin streams are **quarantined** per the frozen rule.
- **`dir` reconciliation: 858 "disagreements" = 100% unmapped label rows (606 `Liquidated *` + 252 `Net Child Vaults`); ZERO arithmetic errors.** Integer-tick classification matches HL `dir` on every normal Open/Close/flip fill.
- **`dir` taxonomy (11 labels):** Open Long 25.1M, Close Long 23.1M, Open Short 20.2M, Close Short 18.2M, Long>Short / Short>Long ~0.65M each (flips); rare: `Liquidated Cross/Isolated Long/Short` (~606 rows, event-descriptor labels — arithmetic authoritative), `Net Child Vaults` (252 rows, **2 protocol-vault wallets**).
- **Transitions:** INCREASE 45.33M / REDUCE 39.55M / CLOSE 1.71M / FLIP 1.30M. **zhash** 15.98M (18.2%).
- **Ruling A (liquidation, NARROW):** touching 605,310; forced-origin 302,655. **Forced-party by class: INCREASE 0 / REDUCE 228,556 / CLOSE 74,099 / FLIP 0** — forced wallets never open/increase, so the narrow no-open rule correctly has **zero** effect on episode-opening (forced fills are reduces/closes that still terminate episodes). Counterparty INCREASE 219,650 (these open episodes under narrow A; broad would have wrongly excluded them). **Integrity: malformed=0, liquidatedUser-matches-neither=0.** Qualifying signal-opening (unflagged INCREASE) = 35,080,977.

**Refinements for the full run (mechanical, no spec change):** (a) extend the `dir` reconciliation table to recognize `Liquidated *` (arithmetic authoritative) and `Net Child Vaults`; (b) **`dir=='Net Child Vaults'` is a deterministic protocol-vault signal** → add to the system/protocol exclusion family alongside zhash-TWAP and liquidation (resolves the "no labelled exclusion set" gap for vaults); (c) fix the cosmetic object-hours coverage metric (bad string slice; 744 parts confirmed present).

## Quarantine rule — FROZEN (correction 4)
A nonzero `q_before` on the first observed fill is **exactly classifiable** and is **NOT** left-censoring — do **not** quarantine for it. Quarantine a `(wallet,coin)` stream **only** when: `start_position` is missing; position arithmetic is invalid; consecutive fills fail the exact-precision chain-consistency check; an hourly archive object is missing within the stream's span; or the same source event is duplicated inconsistently. Report quarantined streams (count + reason) in attrition; the frozen left-censor quarantine is otherwise largely inert now that startpos is real (this is faithful v1.0 — the quarantine guarded the *missing* startpos, which no longer occurs).

## Study-scope clarification (correction 2)
~~The frozen study is taker entry-quality.~~ → **The frozen study evaluates qualifying position-increasing wallet fills regardless of maker/taker status; `crossed` is retained for diagnostics and later deployment analysis.**

## Resolved by these corrections
- **TWAP/liquidation granularity** → §5b frozen fill-level rule (ledger-updating, non-episode-opening; no wallet %-threshold).
- **Left-censor quarantine** → frozen quarantine rule above (nonzero first `q_before` is not censoring).
- **Maker/taker scope** → correction 2 (process both; no `crossed` drop filter).
- **Row identity** → §2 source-row key `(src_object,block_number,event_index,wallet,tid)`, uniqueness asserted.

## Remaining ambiguities (data-contract, resolved empirically — not silently)
1. **`Buy`/`Sell` dir on a major perp:** not expected (spot labels); if any appear on BTC/ETH/SOL/HYPE → data-contract error, fail-loud, do not classify.
2. **`tid` collision scope:** whether `tid` is unique within `(wallet)` globally or only within coin/time — resolved empirically in §4 before use as any join/dedup key.
3. **`szDecimals` source:** the per-coin quantity precision used for exact quantization is taken from the HL `meta` universe; the exact snapshot/version is recorded in the manifest `schema_version` and asserted stable across the window.
