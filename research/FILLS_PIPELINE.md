# Reproducing the fills-derived datasets

Everything in `wallet_markout_router_v2` derives from one raw source: Hyperliquid perp fills.
This document is the build order, the exact definitions, and the traps. Follow it and you get
byte-comparable outputs.

---

## Source

```
s3://hydromancer-reservoir/by_dex/hyperliquid/fills/perp/all/date=<YYYY-MM-DD>/fills.parquet
```

Requester-pays. ~250–550 MB/day, 26 columns, ~4M rows/day. Every GET needs
`RequestPayer="requester"` — including the ranged reads below.

Columns used: `coin, price, size, side, timestamp, direction, address, crossed, start_position,
is_liquidation, fee`. The other 15 (tx_hash, order_id, client_order_id, builder, twap_id,
liquidation_mark_px, …) are never needed and are the bulk of the bytes.

### Trap 1 — read cost

Reading only the 11 needed columns cuts a day from ~400 MB to ~90 MB. A *sequential* stream of
ranged GETs runs at ~1 MB/s; the win only appears when the parquet column chunks are fetched
concurrently. `build_event_wallet_panel.py:S3RangeFile` does this: read the footer, compute
each needed column chunk's byte range from the row-group metadata, fetch them in parallel, serve
`read()` from the prefetched cache.

### Trap 2 — decimal columns

`price`, `size`, `start_position`, `fee` are `decimal128(20,10)`. Letting pandas materialize
them becomes one Python `Decimal` object per cell and costs more than the network transfer.
Cast to float **in Arrow** before `to_pandas()`:

```python
tbl = pa.table({n: (pc.cast(tbl[n], pa.float64()) if pa.types.is_decimal(tbl[n].type) else tbl[n])
                for n in COLS})
```

### Trap 3 — field semantics

* `size` is **unsigned**; direction comes from `side` ∈ {buy, sell}.
* `crossed == True` means **taker**. Everything in this strategy is taker-only.
* `start_position` is the signed position *before* the fill; position after = `start_position +
  sign*size`. This reconciles exactly except for ~4e-5 of rows.
* `direction` ∈ {Open Long, Open Short, Close Long, Close Short, Long > Short, Short > Long}
  gives the open/close/flip classification directly — do not re-derive it from position signs.

---

## Step 0 — price matrix (prerequisite for everything)

`data/cache_price_matrix.npz` with three arrays:

| key | shape | meaning |
|---|---|---|
| `P` | (minutes, coins) | 1-minute close prices |
| `idx` | (minutes,) | minute timestamps, UTC, contiguous |
| `cols` | (coins,) | coin symbols, must include `BTC` |

Discovery used 204 perps × 514,080 minutes (2025-07-31 → 2026-07-22).

**This matrix defines the time origin.** `b5` bucket offsets everywhere are minutes since
`idx[0]`. A different origin silently breaks every join downstream.

---

## Step 1 — daily fills aggregates (`stream_fills.py`)

One pass over each day's fills produces three files. Taker-only (`crossed == True`) throughout.

Per-fill quantities computed first:

```python
notional  = price * size
sgn       = +1 if side == "buy" else -1
t_min     = (timestamp - idx[0]) // 60s          # minutes since the matrix origin
markout_h = sgn * ((P[t+h, coin]/P[t, coin] - 1) - (P[t+h, BTC]/P[t, BTC] - 1))   # h ∈ {5,30,120}
```

Markouts are **BTC-adjusted** — the coin's return minus BTC's over the same window, signed by
trade direction.

### 1a. `wallet_day/<date>.parquet` — 29 columns, per `address`

`n_taker, taker_notl, s_notl (signed notional), buy_notl, sell_notl, open_notl, close_notl,
liq_notl, n_liq, fee, rpnl, n_coins, max_fill, first_min, last_min, builder_notl,
mo5w/mo5s/mo5sq, mo30w/mo30s/mo30sq, mo120w/mo120s/mo120sq, n_maker, maker_notl, maker_fee`

For each horizon: `w` = notional-weighted markout sum, `s` = plain sum, `sq` = sum of squares.
`s` and `sq` are what the wallet score is built from; `sq` exists so a variance can be formed
without keeping fill-level data.

### 1b. `coin_flow/<date>.parquet` — per `address × coin`

`s_notl, notional, open_notl, n_fills, mo30w`.

### 1c. `coin_5m/<date>.parquet` — per `coin × b5` — **the detector's input**

```python
b5          = (t_min // 5) * 5
small       = notional < 1_000
big         = notional >= 10_000
buy_small   = sum(notional where small and side == buy)
sell_small  = sum(notional where small and side == sell)
buy_big, sell_big = same with `big`
liq_notl    = sum(notional where is_liquidation)
n_fills     = row count
nw_buy_small, nw_sell_small = nunique(address) among SMALL fills, per side
```

Note the asymmetry: small is `< $1,000`, big is `>= $10,000`. Fills between are counted in
`n_fills` only.

---

## Step 2 — burst detector (`burst_detector.py`)

Per coin, per 5-minute bucket:

```
net   = buy_small - sell_small
norm  = median(trailing 7 DAILY small-volume totals) / 288
fire if   |net| > 25 * norm
    and   |net| > $3,000
    and   n_wallets_on_dominant_side >= 8
```

### Trap 4 — the norm is a daily total, not a bucket median

`norm` is the median of the last 7 **daily** totals of `buy_small + sell_small`, divided by 288
(the number of 5-minute buckets in a day). That is the *mean* 5-minute volume on a typical day.

It is **not** the median 5-minute bucket. Volume is spiky, so the median bucket is several times
smaller, and using it makes the detector fire ~4× too often (69,317 events instead of 16,163).
This is the single most important line in the pipeline to get right.

Additional rules:

* a coin's history advances only on days it actually traded; it needs **≥5 prior active days**
  before it can fire, and the history keeps the last 8 entries;
* the history is appended **after** the day is scanned, so the norm is strictly backward-looking;
* event timestamp = the bucket's **close** (`b5 + 5 minutes`) — the signal does not exist until
  the bucket completes;
* the coin must be in the price matrix with ≥30 minutes of prior and ≥121 minutes of forward
  data, else the event is dropped. This is why the event table covers 192 coins, not 204.

Output columns: `coin, ts, day, sgn, nw, pre30, week, r30, r120`.

---

## Step 3 — wallet score (`score_lib.load_wallet_months` + `strategy_lib.build_d0`)

```
from wallet_day, keep days where s_notl > 0            # net-buyer days only
aggregate per (address, month): n = Σ n_taker, s = Σ mo30s
per monthly vintage: trailing 3 months, require n >= 100
score = s / n                                          # mean 30-minute markout
```

The vintage's trailing window ends **one day before the vintage opens**, so no markout inside a
score completes after the first signal that score can act on.

---

## Step 4 — event × wallet panel (`build_event_wallet_panel.py`)

A second, targeted pass over the fills: for each burst event, every wallet trading that coin in
`[t−30m, t+240m]`, aggregated into five segments (`pre, sig, p30, p120, p240`). The `sig` segment
is `[t−15m, t]` — the signal window the router reads.

Per event × wallet × segment: notionals by side (taker and maker), position before/after/delta,
open/close/flip classification, first and last fill time, max clip, fees.

Only the `sig` segment is needed for the live signal; the rest exist for the arrival research.

---

## Cost and runtime

| Step | Volume | Wall time |
|---|---|---|
| Step 1 (full year, all fills) | ~140 GB read | hours |
| Step 2 (from cached `coin_5m`) | ~500 MB | ~2 min |
| Step 3 (from cached `wallet_day`) | 2.5 GB | ~4 min |
| Step 4 (targeted re-read, 263 days) | ~25 GB (column-pruned) | ~1 hr |

Requester-pays egress is roughly \$0.09/GB.

---

## Verification

Anyone rebuilding this should reproduce these exactly:

* `coin_5m` for 2026-03-05: ~52,150 rows;
* burst events over 2025-08-01 → 2026-07-22: **16,163 events, 192 coins**, first event
  2025-08-06 00:15 UTC, last 2026-07-22 18:40 UTC;
* wallet score reconstruction: reproduces the historical top/bottom-decile cohort mapping
  **exactly** at the 100-fill threshold;
* event × wallet panel: 7.2M rows, position paths reconciling on all but ~48 rows.

If the event count is ~69k, Trap 4 is the reason.
