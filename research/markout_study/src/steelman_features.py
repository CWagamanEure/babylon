"""
STEELMAN hunt: reconstruct per-wallet TRAIN conditioning features + TEST copy-return outcomes from the raw
tape, so we can test whether ANY pre-definable (train-only) subset persists OOS.

TRAIN ts < 2026-02-01 ; TEST ts >= 2026-03-01.  Majors only. Realized avg-cost round-trip PnL = zero-lag
copy return, gross of cost, in bps of closed notional.

Per wallet we emit:
  TRAIN features (all blind to test):
    ntr, tr_bps (eqw mean), tr_sd, tr_t, tr_vw (vw bps), tr_sharpe (per-close mean/sd),
    taker_share (sz-wtd crossed share of ALL train fills),
    exit_maker_share (sz-wtd maker share of CLOSING fills),
    med_hold_h (sz-wtd median holding hrs), n_coins, top_coin_share,
    mo_hit (fraction of active train months with positive realized), n_mo (active train months)
  TEST outcomes:
    nte, te_bps (eqw), te_t, te_vw (PRIMARY copy return), te_pos (frac closes >0)
"""
import glob, sys
from datetime import datetime, timezone
import numpy as np
import polars as pl

COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
def ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = ms(2026, 2, 1); TEST_LO = ms(2026, 3, 1)
TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_*.parquet"))
MO = 30.44 * 24 * 3600 * 1000  # ms per month approx (only used for labeling below via ts buckets)


def ledger(px, sz, ts, cr):
    """avg-cost ledger. returns list of closes (ts, realized_usd, notional, hold_ms, exit_crossed)."""
    q = avg = avg_ts = 0.0; out = []
    for p, s, t, c in zip(px, sz, ts, cr):
        if q == 0.0 or (s > 0) == (q > 0):
            w = abs(q) + abs(s)
            avg = (avg * abs(q) + p * abs(s)) / w
            avg_ts = (avg_ts * abs(q) + t * abs(s)) / w
            q += s
        else:
            close = min(abs(s), abs(q))
            out.append((t, close * (p - avg) * (1.0 if q > 0 else -1.0), close * p, t - avg_ts, bool(c)))
            nq = q + s
            if (nq > 0) != (q > 0) and nq != 0.0: avg = p; avg_ts = t
            q = nq
            if abs(q) < 1e-12: q = 0.0; avg = 0.0; avg_ts = 0.0
    return out


def month_key(t):
    d = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
    return d.year * 12 + d.month


def main():
    lf = pl.scan_parquet(TAPE).filter(pl.col("coin").is_in(COINS))
    cnt = (lf.filter(pl.col("ts") < TRAIN_HI).group_by("wallet").agg(n=pl.len())
           .filter(pl.col("n") >= 2000).select("wallet").collect())
    uni = sorted(set(cnt["wallet"].to_list()))
    print(f"universe (>=2000 train major fills): {len(uni)} wallets", flush=True)

    W = {}
    BATCH = 300
    for bi in range(0, len(uni), BATCH):
        batch = set(uni[bi:bi + BATCH])
        df = (lf.filter(pl.col("wallet").is_in(batch)).select("wallet", "coin", "ts", "px", "sz", "crossed")
              .collect().sort("ts"))
        for (wal, coin), g in df.group_by(["wallet", "coin"], maintain_order=True):
            g = g.sort("ts")
            px = g["px"].to_numpy(); sz = g["sz"].to_numpy(); tsr = g["ts"].to_numpy(); cr = g["crossed"].to_numpy()
            d = W.setdefault(wal, {"closes_tr": [], "closes_te": [], "coin_notl": {},
                                   "fill_notl": 0.0, "fill_taker_notl": 0.0})
            # fill-level taker share (train only), coin notional (train only)
            tr_fill = tsr < TRAIN_HI
            fn = np.abs(sz[tr_fill]) * px[tr_fill]
            d["fill_notl"] += fn.sum()
            d["fill_taker_notl"] += fn[cr[tr_fill]].sum()
            d["coin_notl"][coin] = d["coin_notl"].get(coin, 0.0) + fn.sum()
            for t, r, notn, hold, xc in ledger(px, sz, tsr, cr):
                if t < TRAIN_HI: d["closes_tr"].append((t, r, notn, hold, xc))
                elif t >= TEST_LO: d["closes_te"].append((t, r, notn))
        del df
        print(f"  batch {bi//BATCH+1}/{(len(uni)-1)//BATCH+1} done", flush=True)

    rows = []
    for wal, d in W.items():
        tr = d["closes_tr"]; te = d["closes_te"]
        if len(tr) < 20 or len(te) < 20: continue
        tr = [x for x in tr if x[2] > 0]; te = [x for x in te if x[2] > 0]
        if len(tr) < 20 or len(te) < 20: continue
        # train close-level
        t_ts = np.array([x[0] for x in tr]); t_r = np.array([x[1] for x in tr])
        t_no = np.array([x[2] for x in tr]); t_h = np.array([x[3] for x in tr]); t_xc = np.array([x[4] for x in tr])
        t_bps = t_r / t_no * BP
        n = t_bps.size; mean = t_bps.mean(); sd = t_bps.std()
        t_stat = mean / (sd / np.sqrt(n)) if sd > 0 else 0.0
        sharpe = mean / sd if sd > 0 else 0.0
        tr_vw = t_r.sum() / t_no.sum() * BP
        # holding (sz-weighted median)
        order = np.argsort(t_h); cum = np.cumsum(t_no[order])
        med_h = t_h[order][np.searchsorted(cum, cum[-1] / 2)] / 3.6e6
        # exit maker share (closing fills with crossed=False), sz-wtd
        exit_maker = t_no[~t_xc].sum() / t_no.sum()
        # taker share of all fills
        taker_share = d["fill_taker_notl"] / d["fill_notl"] if d["fill_notl"] > 0 else np.nan
        # coin concentration
        cn = d["coin_notl"]; tot = sum(cn.values())
        top_share = max(cn.values()) / tot if tot > 0 else np.nan
        n_coins = sum(1 for v in cn.values() if v > 0.01 * tot)
        # monthly hit rate on train realized
        mk = np.array([month_key(t) for t in t_ts])
        months = np.unique(mk); hits = 0
        for m in months:
            if t_r[mk == m].sum() > 0: hits += 1
        mo_hit = hits / months.size; n_mo = months.size
        # test outcomes
        e_r = np.array([x[1] for x in te]); e_no = np.array([x[2] for x in te])
        e_bps = e_r / e_no * BP
        te_mean = e_bps.mean(); te_sd = e_bps.std()
        te_t = te_mean / (te_sd / np.sqrt(e_bps.size)) if te_sd > 0 else 0.0
        te_vw = e_r.sum() / e_no.sum() * BP
        te_pos = float(np.mean(e_bps > 0))
        rows.append((wal, n, mean, sd, t_stat, tr_vw, sharpe, taker_share, exit_maker,
                     med_h, n_coins, top_share, mo_hit, n_mo,
                     e_bps.size, te_mean, te_t, te_vw, te_pos))

    R = pl.DataFrame(rows, schema=[
        "wallet", "ntr", "tr_bps", "tr_sd", "tr_t", "tr_vw", "tr_sharpe", "taker_share", "exit_maker",
        "med_hold_h", "n_coins", "top_coin_share", "mo_hit", "n_mo",
        "nte", "te_bps", "te_t", "te_vw", "te_pos"], orient="row")
    R.write_parquet("out/steelman_features.parquet")
    print(f"\nwrote {R.height} wallets -> out/steelman_features.parquet")
    print(R.describe())


if __name__ == "__main__":
    main()
