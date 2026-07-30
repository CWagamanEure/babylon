#!/usr/bin/env python3
"""Event x wallet x segment panel over the burst-event windows (targeted fills re-read).

Required by the 2026-07-26 CORRECTION to ladder A-H: rows C-H could not test their labeled
hypotheses because the only fills product available was the (coin, 5m, side) aggregate
attrib_5m -- skill sets were never joined to flow, n_top summed across buckets instead of
counting unique wallets, initiation used a daily aggregate position proxy, and opening share
was all-flow rather than smart flow. Every one of those defects needs wallet identity carried
alongside the flow, which is what this pass materializes.

For each burst event (12,725 events, 2025-11-02 .. 2026-07-22) and each wallet that traded the
event's coin inside [ts-30m, ts+240m], one row per (event_id, address, seg):

  score-asof        grp / score_t / score_dec from the walk-forward fold that owns the event's
                    month (trailing-3-month 30m-markout t, >=100 fills; reproduces
                    fold_cohort_map exactly -- verified 100% agreement on 2025-11 and 2026-03)
  side + notional   buy/sell notional and size, taker and maker split
  position path     pos_before (start_position of the wallet's first fill in the segment),
                    pos_after (start_position + signed size of its last fill), pos_delta
  open-close class  open / close / flip notional from the venue `direction` field
  entry time        first_rel_s / last_rel_s, seconds relative to the event timestamp

Segments (minutes relative to event ts):
  pre  [-30,-15)   sig  [-15,0]   p30  (0,30]   p120  (30,120]   p240  (120,240]
`sig` is exactly the frozen spec's signal window (burst bucket + prior 2), so event-level
aggregates over seg=="sig" are wallet-resolved versions of the attrib_5m features.

Output:
  data/panel_event_wallet/<date>.parquet   one file per event day
  data/panel_events.parquet                event index + episode ids (8h gap per coin)
  data/wallet_score_asof.parquet           address x fold -> score_t, score_dec, grp, n

Usage: python3 build_event_wallet_panel.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--dry-run]
Re-runnable: existing per-day outputs are skipped.
"""
import argparse
import io
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import boto3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

BASE = "/Users/corywagamaneure/incerto-research/candle-rolloff-fade"
OUT = f"{BASE}/data/panel_event_wallet"
BUCKET = "hydromancer-reservoir"
KEY = "by_dex/hyperliquid/fills/perp/all/date={ds}/fills.parquet"
WORKERS = 7   # concurrent day readers (each prefetches its column chunks 8-way)

COLS = ["coin", "price", "size", "side", "timestamp", "direction", "address",
        "crossed", "start_position", "is_liquidation", "fee"]
# (name, lo_min, hi_min) -- half-open [lo, hi) except sig which is inclusive of 0
SEGS = [("pre", -30, -15), ("sig", -15, 0), ("p30", 0, 30), ("p120", 30, 120), ("p240", 120, 240)]
PRE_M, POST_M = 30, 240
FIRST_FOLD, LAST_FOLD = "2025-11", "2026-07"
EPISODE_GAP_M = 480  # 8h, matches run_spec_search.episodes_first


# ---------------------------------------------------------------- score-asof
def build_scores():
    """address x fold -> trailing-3mo 30m-markout t-stat, decile, cohort group."""
    out = f"{BASE}/data/wallet_score_asof.parquet"
    if os.path.exists(out):
        return pd.read_parquet(out)
    wm = pd.read_parquet(f"{BASE}/data/wallet_month_markouts.parquet")
    months = sorted(wm.month.unique())
    frames = []
    for i in range(3, len(months)):
        fold = str(months[i])
        if not (FIRST_FOLD <= fold <= LAST_FOLD):
            continue
        tr = (wm[wm.month.isin(months[i - 3:i])].groupby("address")
              .agg(n=("n", "sum"), s=("s", "sum"), sq=("sq", "sum")))
        tr = tr[tr.n >= 100]  # same floor as fold_cohort_map
        mean = tr.s / tr.n
        var = (tr.sq / tr.n - mean ** 2).clip(lower=1e-12)
        t = mean / np.sqrt(var / tr.n)
        dec = pd.qcut(t.rank(method="first"), 10, labels=False)
        frames.append(pd.DataFrame({
            "address": tr.index, "fold": fold, "score_t": t.values,
            "score_dec": dec.values.astype("int8"), "score_n": tr.n.values,
            "grp": np.where(dec >= 8, "top", np.where(dec <= 1, "bot", "mid")),
        }))
    sc = pd.concat(frames, ignore_index=True)
    sc.to_parquet(out, index=False)
    print(f"scores: {len(sc):,} address-folds, {sc.fold.nunique()} folds", flush=True)
    return sc


# ---------------------------------------------------------------- event index
def build_events():
    ev = pd.read_parquet(f"{BASE}/data/burst_events.parquet")
    ev = ev[ev.ts >= pd.Timestamp("2025-11-02", tz="UTC")].copy()
    ev = ev.sort_values(["coin", "ts"]).reset_index(drop=True)
    ev["event_id"] = ev.coin + "|" + ev.ts.dt.strftime("%Y%m%dT%H%M")
    # Anchored episodes: the first unassigned event of a coin opens an episode covering
    # [ts, ts+8h); the next event after that span opens the next one. A gap-chained rule
    # (used by the ladder) lets a busy coin chain for weeks -- median 9 and max 427 events
    # per "episode" -- which is not a tradable unit and makes "one entry per episode"
    # meaningless. Anchoring bounds every episode at 8h.
    epi = np.empty(len(ev), dtype=np.int64)
    k = 0
    for _, idx in ev.groupby("coin", sort=False).indices.items():
        idx = np.sort(idx)
        t = ev.ts.values[idx]
        anchor = None
        for pos, i in enumerate(idx):
            if anchor is None or (t[pos] - anchor) >= np.timedelta64(EPISODE_GAP_M, "m"):
                anchor = t[pos]
                k += 1
            epi[i] = k
    ev["epi_id"] = epi
    gap = ev.groupby("coin")["ts"].diff().dt.total_seconds().div(60)
    ev["epi_chain_id"] = ((gap.isna()) | (gap >= EPISODE_GAP_M)).cumsum()  # ladder's rule, kept for contrast
    ev["epi_rank"] = ev.groupby("epi_id").cumcount()
    ev["epi_n"] = ev.epi_id.map(ev.epi_id.value_counts())
    ev["epi_ts0"] = ev.epi_id.map(ev.groupby("epi_id").ts.min())
    ev["fold"] = ev.ts.dt.strftime("%Y-%m")
    ev["date"] = ev.ts.dt.strftime("%Y-%m-%d")
    return ev


# ---------------------------------------------------------------- per-day work
class S3RangeFile(io.RawIOBase):
    """Seekable reader over a requester-pays S3 object, with parallel chunk prefetch.

    Local disk is not an option here (~2GB free against ~400MB/day files) and neither is
    buffering whole days in RAM (8.6GB total). Reading only the 11 columns we need cuts a day
    to ~90MB, but a *sequential* stream of ranged GETs runs at ~1MB/s -- the win only shows up
    once the column chunks are fetched concurrently, which is what `prefetch` does.
    """

    def __init__(self, bucket, key, threads=8):
        self.s3 = boto3.client("s3")
        self.bucket, self.key, self.threads = bucket, key, threads
        self.size = self.s3.head_object(Bucket=bucket, Key=key,
                                        RequestPayer="requester")["ContentLength"]
        self.pos = 0
        self.bytes_read = 0
        self.cache = {}          # (offset, length) -> bytes
        self.starts = []         # sorted offsets of cached chunks

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def _get(self, off, n):
        end = min(off + n, self.size) - 1
        body = self.s3.get_object(Bucket=self.bucket, Key=self.key, RequestPayer="requester",
                                  Range=f"bytes={off}-{end}")["Body"].read()
        self.bytes_read += len(body)
        return body

    def prefetch(self, ranges):
        """ranges: iterable of (offset, length) -- fetched concurrently and cached."""
        merged = []
        for off, ln in sorted(ranges):
            if merged and off <= merged[-1][0] + merged[-1][1] + (1 << 20):   # coalesce <1MB gaps
                o0, l0 = merged[-1]
                merged[-1] = (o0, max(l0, off + ln - o0))
            else:
                merged.append((off, ln))
        with ThreadPoolExecutor(max_workers=self.threads) as ex:
            for (off, ln), buf in zip(merged, ex.map(lambda r: self._get(*r), merged)):
                self.cache[(off, ln)] = buf
        self.starts = sorted(self.cache)

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        n = min(n, self.size - self.pos)
        for off, ln in self.starts:                      # serve from prefetched chunks
            if off <= self.pos and self.pos + n <= off + ln:
                buf = self.cache[(off, ln)][self.pos - off:self.pos - off + n]
                self.pos += len(buf)
                return buf
            if off > self.pos:
                break
        buf = self._get(self.pos, n)
        self.pos += len(buf)
        return buf


def _read_day(ds, coins):
    """Fetch just the needed column chunks of one day's fills and return an Arrow table."""
    src = S3RangeFile(BUCKET, KEY.format(ds=ds))
    md = pq.ParquetFile(src).metadata
    want = {i for i, name in enumerate(md.schema.names) if name in COLS}
    ranges = []
    for rg in range(md.num_row_groups):
        for ci in want:
            cc = md.row_group(rg).column(ci)
            off = cc.dictionary_page_offset or cc.data_page_offset
            ranges.append((int(off), int(cc.total_compressed_size)))
    src.prefetch(ranges)
    tbl = pq.read_table(src, columns=COLS, filters=[("coin", "in", list(coins))])
    src.cache.clear()
    return tbl, src.bytes_read


def _slim(ds, coins, windows):
    """Read one day's fills straight from S3, keeping only rows of `coins` in an event window.

    The decimal128 columns are cast to float in Arrow: letting pandas materialize them as
    Python Decimal objects and casting afterwards costs more than the transfer.
    """
    tbl, nbytes = _read_day(ds, coins)
    tbl = pa.table({name: (pc.cast(tbl[name], pa.float64())
                           if pa.types.is_decimal(tbl[name].type) else tbl[name])
                    for name in COLS})
    f = tbl.to_pandas()
    del tbl
    if f.empty:
        return f
    f = f.sort_values(["coin", "timestamp"], kind="stable").reset_index(drop=True)
    keep = np.zeros(len(f), dtype=bool)
    starts = f.coin.searchsorted(np.sort(f.coin.unique()), side="left")
    order = np.sort(f.coin.unique())
    bounds = {c: (starts[i], starts[i + 1] if i + 1 < len(starts) else len(f))
              for i, c in enumerate(order)}
    for coin, lo_hi in windows.items():
        if coin not in bounds:
            continue
        a, b = bounds[coin]
        ts = f.timestamp.values[a:b]
        for lo, hi in lo_hi:
            i = np.searchsorted(ts, np.datetime64(lo), "left")
            j = np.searchsorted(ts, np.datetime64(hi), "right")
            keep[a + i:a + j] = True
    f = f[keep].reset_index(drop=True)
    f["sgn"] = np.where(f.side.values == "buy", 1.0, -1.0)
    f["notional"] = f.price * f["size"]
    f["is_open"] = f.direction.isin(("Open Long", "Open Short"))
    f["is_close"] = f.direction.isin(("Close Long", "Close Short"))
    f["is_flip"] = f.direction.isin(("Long > Short", "Short > Long"))
    return f


def _agg_event(w, ev_ts, event_id):
    """w = one coin's fills inside one event window. -> per (address, seg) rows."""
    rel = (w.timestamp.values - np.datetime64(ev_ts.tz_localize(None))).astype("timedelta64[s]").astype(float)
    seg = np.full(len(w), "", dtype=object)
    for name, lo, hi in SEGS:
        lo_s, hi_s = lo * 60, hi * 60
        m = (rel >= lo_s) & (rel <= hi_s) if name == "sig" else (rel > lo_s) & (rel <= hi_s)
        if name == "pre":
            m = (rel >= lo_s) & (rel < hi_s)
        seg[m] = name
    w = w.assign(seg=seg, rel=rel)
    w = w[w.seg != ""]
    if w.empty:
        return None
    w["signed_sz"] = w.sgn * w["size"]
    w["taker_notl"] = np.where(w.crossed, w.notional, 0.0)
    w["buy_notl"] = np.where(w.sgn > 0, w.notional, 0.0)
    w["sell_notl"] = np.where(w.sgn < 0, w.notional, 0.0)
    w["tk_buy_notl"] = np.where(w.crossed & (w.sgn > 0), w.notional, 0.0)
    w["tk_sell_notl"] = np.where(w.crossed & (w.sgn < 0), w.notional, 0.0)
    w["open_notl"] = np.where(w.is_open, w.notional, 0.0)
    w["close_notl"] = np.where(w.is_close, w.notional, 0.0)
    w["flip_notl"] = np.where(w.is_flip, w.notional, 0.0)
    w["liq_notl"] = np.where(w.is_liquidation, w.notional, 0.0)
    g = w.groupby(["address", "seg"], sort=False)
    a = g.agg(
        n=("notional", "size"), n_taker=("crossed", "sum"),
        notl=("notional", "sum"), taker_notl=("taker_notl", "sum"),
        buy_notl=("buy_notl", "sum"), sell_notl=("sell_notl", "sum"),
        tk_buy_notl=("tk_buy_notl", "sum"), tk_sell_notl=("tk_sell_notl", "sum"),
        signed_sz=("signed_sz", "sum"), max_clip=("notional", "max"),
        open_notl=("open_notl", "sum"), close_notl=("close_notl", "sum"),
        flip_notl=("flip_notl", "sum"), liq_notl=("liq_notl", "sum"),
        fee=("fee", "sum"), first_rel_s=("rel", "min"), last_rel_s=("rel", "max"),
        px_first=("price", "first"), px_last=("price", "last"),
    ).reset_index()
    # position path: start_position of the first fill, and of the last fill + its own size
    first = g.head(1)[["address", "seg", "start_position"]].rename(columns={"start_position": "pos_before"})
    last = g.tail(1)[["address", "seg", "start_position", "signed_sz"]]
    last = last.assign(pos_after=last.start_position + last.signed_sz)[["address", "seg", "pos_after"]]
    a = a.merge(first, on=["address", "seg"]).merge(last, on=["address", "seg"])
    a["pos_delta"] = a.pos_after - a.pos_before
    a["event_id"] = event_id
    return a


def process_day(ds, ev_day, frames, scores_fold):
    rows = []
    day_frames = [f for f in frames if f is not None and len(f)]
    if not day_frames:
        return None
    F = pd.concat(day_frames, ignore_index=True).sort_values(
        ["coin", "timestamp"], kind="stable").reset_index(drop=True)
    for coin, evc in ev_day.groupby("coin", sort=False):
        c = F[F.coin.values == coin]
        if c.empty:
            continue
        ts_arr = c.timestamp.values
        for r in evc.itertuples():
            t0 = r.ts.tz_localize(None)
            i = np.searchsorted(ts_arr, np.datetime64(t0 - pd.Timedelta(minutes=PRE_M)), "left")
            j = np.searchsorted(ts_arr, np.datetime64(t0 + pd.Timedelta(minutes=POST_M)), "right")
            if j <= i:
                continue
            a = _agg_event(c.iloc[i:j], r.ts, r.event_id)
            if a is not None:
                rows.append(a)
    if not rows:
        return None
    P = pd.concat(rows, ignore_index=True)
    P = P.merge(scores_fold, on="address", how="left")
    P["grp"] = P.grp.fillna("uns")
    P["seg"] = P.seg.astype("category")
    return P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-11-02")
    ap.add_argument("--end", default="2026-07-22")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    scores = build_scores()
    ev = build_events()
    ev.to_parquet(f"{BASE}/data/panel_events.parquet", index=False)
    print(f"events: {len(ev):,} | episodes: {ev.epi_id.nunique():,} | "
          f"days: {ev.date.nunique()} | coins: {ev.coin.nunique()}", flush=True)

    dates = sorted(d for d in ev.date.unique() if args.start <= d <= args.end)
    todo = [d for d in dates if not os.path.exists(f"{OUT}/{d}.parquet")]
    if args.dry_run:
        todo = todo[:1]
    print(f"days to build: {len(todo)}/{len(dates)}", flush=True)
    if not todo:
        return

    # windows per file-day: an event needs its own day plus neighbours it spills into
    by_date = {d: g for d, g in ev.groupby("date")}
    need = {}  # file-day -> {coin: [(lo,hi)]}
    for d in todo:
        for r in by_date[d].itertuples():
            lo = (r.ts - pd.Timedelta(minutes=PRE_M)).tz_localize(None)
            hi = (r.ts + pd.Timedelta(minutes=POST_M)).tz_localize(None)
            for fd in sorted({lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d")}):
                need.setdefault(fd, {}).setdefault(r.coin, []).append((lo, hi))
    file_days = sorted(need)

    # S3 reads run several file-days ahead of the aggregation; a single ranged read is
    # bandwidth-starved on its own, so the parallelism is what carries the throughput.
    # The semaphore is released on consumption, bounding how many slim frames are held.
    sem = threading.Semaphore(WORKERS + 2)
    pool = ThreadPoolExecutor(max_workers=WORKERS)

    def fetch(fd):
        sem.acquire()
        t0 = time.time()
        for attempt in range(3):
            try:
                w = need[fd]
                s = _slim(fd, set(w), w)
                print(f"  slim {fd}: {len(s):,} rows in {time.time()-t0:.0f}s", flush=True)
                return s
            except Exception as e:  # noqa: BLE001
                print(f"{fd} READ-ERR ({attempt+1}/3) {type(e).__name__}: {e}", flush=True)
        return None

    futs = {fd: pool.submit(fetch, fd) for fd in file_days}
    slim = {}

    def get_slim(fd):
        if fd not in futs:
            return None
        if fd not in slim:
            slim[fd] = futs[fd].result()
            sem.release()
        return slim[fd]

    for d in todo:
        prv = (pd.Timestamp(d) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        nxt = (pd.Timestamp(d) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        frames = [get_slim(x) for x in (prv, d, nxt)]
        t_agg = time.time()
        fold = by_date[d].fold.iloc[0]
        sc = scores[scores.fold == fold][["address", "score_t", "score_dec", "score_n", "grp"]]
        P = process_day(d, by_date[d], frames, sc)
        if P is None:
            pd.DataFrame(columns=["event_id", "address", "seg"]).to_parquet(f"{OUT}/{d}.parquet")
            print(f"{d} EMPTY", flush=True)
        else:
            P.to_parquet(f"{OUT}/{d}.parquet", index=False)
            print(f"{d} ok: {len(P):,} rows, {P.address.nunique():,} wallets, "
                  f"{P.event_id.nunique()}/{len(by_date[d])} events, agg {time.time()-t_agg:.0f}s", flush=True)
        for old in [x for x in slim if x < prv]:
            slim.pop(old, None)
    pool.shutdown(wait=False)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
