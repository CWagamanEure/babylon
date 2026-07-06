"""
THE MAKER vs TAKER angle. A follower can only copy TAKER (aggressive, directional) fills — you cannot
copy providing liquidity. If the high-volume "winners" are makers, their edge (spread/rebate capture)
is real-but-non-copyable. This reconciles "they trade huge volume so they're not lucky" with "their
edge doesn't transfer to a copier."

Universe: wallets with >=2000 TRAIN (ts<Feb1) majors fills. Test ts>=Mar1. Majors=BTC/ETH/SOL/HYPE.
Realized round-trip PnL via avg-cost ledger (what a zero-lag copier books). Two ledgers per wallet:
  (A) FULL  ledger over ALL fills   -> realized attributed to maker-closing vs taker-closing.
  (B) TAKER-ONLY ledger over crossed=True fills only -> the CLEAN copyable directional portfolio.
Classification (maker share) uses TRAIN-window behaviour only (a train-time selector, no test leak).
"""
import glob, sys
from datetime import datetime, timezone
import numpy as np
import polars as pl

COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
def ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = ms(2026, 2, 1); TEST_LO = ms(2026, 3, 1)
TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_*.parquet"))
COST_BPS = {"BTC": 8.0, "ETH": 8.0, "SOL": 10.0, "HYPE": 14.0, "SPX": 12.0}  # round-trip taker cost


def closes_full(px, sz, ts, cr):
    """avg-cost ledger over ALL fills. per closing event -> (ts, realized_usd, closed_notional, closing_maker)."""
    q = avg = 0.0; out = []
    for p, s, t, c in zip(px, sz, ts, cr):
        if q == 0.0 or (s > 0) == (q > 0):
            avg = (avg * abs(q) + p * abs(s)) / (abs(q) + abs(s)); q += s
        else:
            close = min(abs(s), abs(q))
            out.append((t, close * (p - avg) * (1.0 if q > 0 else -1.0), close * p, (not c)))
            nq = q + s
            if (nq > 0) != (q > 0) and nq != 0.0: avg = p
            q = nq
            if abs(q) < 1e-12: q = 0.0; avg = 0.0
    return out


def closes_taker(px, sz, ts, cr):
    """avg-cost ledger over TAKER (crossed=True) fills only -> (ts, realized_usd, closed_notional)."""
    m = cr.astype(bool)
    if not m.any(): return []
    px, sz, ts = px[m], sz[m], ts[m]
    q = avg = 0.0; out = []
    for p, s, t in zip(px, sz, ts):
        if q == 0.0 or (s > 0) == (q > 0):
            avg = (avg * abs(q) + p * abs(s)) / (abs(q) + abs(s)); q += s
        else:
            close = min(abs(s), abs(q))
            out.append((t, close * (p - avg) * (1.0 if q > 0 else -1.0), close * p))
            nq = q + s
            if (nq > 0) != (q > 0) and nq != 0.0: avg = p
            q = nq
            if abs(q) < 1e-12: q = 0.0; avg = 0.0
    return out


def stats(recs):
    """recs list of (realized_usd, notional). -> (n, eqw_bps_mean, t, vw_bps) or None if <20."""
    if len(recs) < 20: return None
    r = np.array([x[0] for x in recs]); n_ = np.array([x[1] for x in recs])
    good = n_ > 0; r = r[good]; n_ = n_[good]
    if r.size < 20: return None
    bps = r / n_ * BP
    mean = bps.mean(); sd = bps.std()
    t = mean / (sd / np.sqrt(bps.size)) if sd > 0 else 0.0
    return bps.size, mean, t, r.sum() / n_.sum() * BP


def main():
    lf = pl.scan_parquet(TAPE).filter(pl.col("coin").is_in(COINS))
    cnt = (lf.filter(pl.col("ts") < TRAIN_HI).group_by("wallet").agg(n=pl.len())
           .filter(pl.col("n") >= 2000).select("wallet").collect())
    uni = sorted(cnt["wallet"].to_list())
    print(f"universe (>=2000 train majors fills): {len(uni)} wallets", flush=True)

    W = {}; BATCH = 150   # lowered 500->150 for 8GB-box RAM safety (whale-heavy batch peak)
    for bi in range(0, len(uni), BATCH):
        batch = set(uni[bi:bi + BATCH])
        df = (lf.filter(pl.col("wallet").is_in(batch))
              .select("wallet", "coin", "ts", "tid", "px", "sz", "crossed")
              .collect().sort(["ts", "tid"]))
        for (wal, coin), g in df.group_by(["wallet", "coin"], maintain_order=True):
            px = g["px"].to_numpy(); sz = g["sz"].to_numpy(); ts = g["ts"].to_numpy(); cr = g["crossed"].to_numpy()
            d = W.setdefault(wal, {"trF": [], "teF": [], "trT": [], "teT": [],
                                   "mk_n": 0, "tk_n": 0, "mk_v": 0.0, "tk_v": 0.0})
            # train-window maker/taker fill counts & notional (classification basis)
            trm = ts < TRAIN_HI
            crt = cr[trm]; notl = (np.abs(sz) * px)[trm]
            d["mk_n"] += int((~crt).sum()); d["tk_n"] += int(crt.sum())
            d["mk_v"] += float(notl[~crt].sum()); d["tk_v"] += float(notl[crt].sum())
            for t, r, nn, mkclose in closes_full(px, sz, ts, cr):
                if t < TRAIN_HI: d["trF"].append((r, nn, mkclose))
                elif t >= TEST_LO: d["teF"].append((r, nn, mkclose))
            for t, r, nn in closes_taker(px, sz, ts, cr):
                if t < TRAIN_HI: d["trT"].append((r, nn))
                elif t >= TEST_LO: d["teT"].append((r, nn))
        del df
        print(f"  batch {bi//BATCH+1}/{(len(uni)-1)//BATCH+1} ({bi+len(batch)} wallets)", flush=True)

    rows = []
    for wal, d in W.items():
        stF, seF = stats([(r, n) for r, n, _ in d["trF"]]), stats([(r, n) for r, n, _ in d["teF"]])
        stT, seT = stats(d["trT"]), stats(d["teT"])
        mk_n, tk_n = d["mk_n"], d["tk_n"]; mk_v, tk_v = d["mk_v"], d["tk_v"]
        if mk_n + tk_n == 0: continue
        mkshare_n = mk_n / (mk_n + tk_n)
        mkshare_v = mk_v / (mk_v + tk_v) if (mk_v + tk_v) > 0 else np.nan
        # maker- vs taker-closing realized PnL decomposition, per window (of the FULL ledger)
        def split_pnl(recs):
            mr = sum(r for r, n, mk in recs if mk); mn = sum(n for r, n, mk in recs if mk)
            tr = sum(r for r, n, mk in recs if not mk); tn = sum(n for r, n, mk in recs if not mk)
            return mr, mn, tr, tn
        trmr, trmn, trtr, trtn = split_pnl(d["trF"]); temr, temn, tetr, tetn = split_pnl(d["teF"])
        rows.append((wal, mk_n + tk_n, mkshare_n, mkshare_v, mk_v + tk_v,
                     *(stF or (0, np.nan, np.nan, np.nan)), *(seF or (0, np.nan, np.nan, np.nan)),
                     *(stT or (0, np.nan, np.nan, np.nan)), *(seT or (0, np.nan, np.nan, np.nan)),
                     trmr, trmn, trtr, trtn, temr, temn, tetr, tetn))
    cols = ["wallet", "trN", "mkshare_n", "mkshare_v", "trGross",
            "ntrF", "trF_eqw", "trF_t", "trF_vw", "nteF", "teF_eqw", "teF_t", "teF_vw",
            "ntrT", "trT_eqw", "trT_t", "trT_vw", "nteT", "teT_eqw", "teT_t", "teT_vw",
            "trMkR", "trMkN", "trTkR", "trTkN", "teMkR", "teMkN", "teTkR", "teTkN"]
    R = pl.DataFrame(rows, schema=cols, orient="row")
    R.write_parquet("out/maker_taker_split.parquet")
    print(f"\nper-wallet rows: {R.height}  ->  out/maker_taker_split.parquet")


if __name__ == "__main__":
    main()
