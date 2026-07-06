"""
Stage L, Job L2 (REVISED after build-audit): per-wallet TRAIN-ONLY archetype features for the frozen cohort_K.

WHY A TAPE PASS: out/entries only scores position-INCREASING taker fills (opens/adds) — exits/reductions are
never rows, so pos_after never returns to 0 and true holds/funding are NOT reconstructable from it. The
HEDGER archetype keys on funding_capture + time_in_pos, so those three features are built from a COHORT-ONLY,
TRAIN-restricted, MAJORS-only raw-tape avg-cost ledger (the steelman_features.ledger machinery, extended to
emit dir + entry_ts). The directional / cadence / concentration / conviction features are exact from
out/entries (opens), TRAIN-restricted. regime_tilt from out/cohort_K_entries (split=='train').

RAM-safe: cohort-only majors tape scan with predicate+projection pushdown, BATCH=100, one heavy job.
LEAK: every feature is TRAIN-only (ts < 2026-02-01). Deterministic, no RNG.
Output: out/cohort_K_archfeat.parquet
"""
import glob
from datetime import datetime, timezone
import numpy as np
import polars as pl

COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
def ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = ms(2026, 2, 1)                                  # frozen split boundary (== cohort_K_price.py)
TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_*.parquet"))
FUNDING = "../scratch_conv/mlscreen/funding.parquet"
BATCH = 100

cohort = sorted(set(l.strip() for l in open("out/cohort_K.txt") if l.strip()))
print(f"cohort: {len(cohort)} wallets", flush=True)


def ledger(px, sz, ts, cr):
    """avg-cost ledger over ALL fills. Returns (closes, episodes):
       closes   = per partial/full reduction: (close_ts, realized_usd, notional, hold_ms, dir, entry_ts)
                  -> used for funding (per-tranche accrual is the correct integral) and per-close stats.
       episodes = per position lifetime (flat -> ... -> flat, or flat -> ... -> flip): (open_ts, close_ts)
                  -> used for time_in_pos_frac / med_hold WITHOUT double-counting laddered scale-outs."""
    q = avg = avg_ts = 0.0; out = []; eps = []; ep_open = None
    for p, s, t, c in zip(px, sz, ts, cr):
        if q == 0.0 or (s > 0) == (q > 0):                # open / add (same side)
            if q == 0.0: ep_open = t                       # episode starts on first fill from flat
            w = abs(q) + abs(s)
            avg = (avg * abs(q) + p * abs(s)) / w
            avg_ts = (avg_ts * abs(q) + t * abs(s)) / w
            q += s
        else:                                             # reduce / close (opposite side)
            close = min(abs(s), abs(q))
            dirn = 1.0 if q > 0 else -1.0
            out.append((t, close * (p - avg) * dirn, close * p, t - avg_ts, dirn, avg_ts))
            nq = q + s
            if (nq > 0) != (q > 0) and nq != 0.0:          # flipped through zero: old episode ends, new begins
                if ep_open is not None: eps.append((ep_open, t))
                ep_open = t; avg = p; avg_ts = t
            q = nq
            if abs(q) < 1e-12:                             # returned to flat: episode ends
                q = 0.0; avg = 0.0; avg_ts = 0.0
                if ep_open is not None: eps.append((ep_open, t)); ep_open = None
    return out, eps


# ---- per-coin cumulative funding (rate integrated over time), for the funding-capture join ----
fund = pl.read_parquet(FUNDING).filter(pl.col("coin").is_in(COINS)).sort("coin", "time")
CUM = {}                                                  # coin -> (times[], cumrate[])
for coin, g in fund.group_by("coin", maintain_order=True):
    c0 = coin[0] if isinstance(coin, tuple) else coin
    CUM[c0] = (g["time"].to_numpy().astype(np.int64), np.cumsum(g["rate"].to_numpy().astype(float)))

def cum_at(coin, ts):
    """cumulative funding rate at/just-before each ts (0 if coin/funding missing)."""
    if coin not in CUM: return np.zeros(len(ts))
    t, c = CUM[coin]
    idx = np.searchsorted(t, ts, side="right") - 1
    return np.where(idx >= 0, c[np.clip(idx, 0, len(c) - 1)], 0.0)


# ---- HEAVY JOB: cohort-only, train-restricted, majors-only tape ledger -> hold/funding features ----
lf = pl.scan_parquet(TAPE).filter(pl.col("coin").is_in(COINS) & pl.col("wallet").is_in(cohort))
HOLD = {}
for bi in range(0, len(cohort), BATCH):
    batch = set(cohort[bi:bi + BATCH])
    df = (lf.filter(pl.col("wallet").is_in(batch))
          .select("wallet", "coin", "ts", "px", "sz", "crossed").collect().sort("ts"))
    for (wal, coin), g in df.group_by(["wallet", "coin"], maintain_order=True):
        g = g.sort("ts")
        px = g["px"].to_numpy(); sz = g["sz"].to_numpy(); tsr = g["ts"].to_numpy(); cr = g["crossed"].to_numpy()
        d = HOLD.setdefault(wal, {"lifetimes": [], "fcap_num": 0.0, "fcap_den": 0.0,
                                  "sum_life": 0.0, "min_ts": np.inf, "max_ts": -np.inf})
        trf = tsr < TRAIN_HI                              # active span from TRAIN fills
        if trf.any():
            d["min_ts"] = min(d["min_ts"], float(tsr[trf].min()))
            d["max_ts"] = max(d["max_ts"], float(tsr[trf].max()))
        closes, episodes = ledger(px, sz, tsr, cr)
        tr_cl = [x for x in closes if x[0] < TRAIN_HI and x[2] > 0]     # TRAIN closes, positive notional
        if tr_cl:                                                       # funding: per-tranche accrual (correct integral)
            c_ts = np.array([x[0] for x in tr_cl], dtype=np.int64)
            notl = np.array([x[2] for x in tr_cl])
            dirn = np.array([x[4] for x in tr_cl]); e_ts = np.array([x[5] for x in tr_cl], dtype=np.int64)
            dcum = cum_at(coin, c_ts) - cum_at(coin, e_ts)
            d["fcap_num"] += float(np.sum(-dirn * dcum * notl))        # long pays when rate>0 -> negative
            d["fcap_den"] += float(np.sum(notl))
        tr_ep = [(o, cl) for (o, cl) in episodes if o < TRAIN_HI]      # TRAIN position lifetimes (no double-count)
        for o, cl in tr_ep:
            life = cl - o
            d["lifetimes"].append(life); d["sum_life"] += float(life)
    del df
    print(f"  tape batch {bi//BATCH+1}/{(len(cohort)-1)//BATCH+1} done", flush=True)

hold_rows = []
for wal, d in HOLD.items():
    if not d["lifetimes"]: continue
    med_hold_h = float(np.median(np.array(d["lifetimes"]))) / 3.6e6
    span = d["max_ts"] - d["min_ts"]
    tip = (d["sum_life"] / span) if span > 0 else None                # can exceed 1 (concurrent multi-coin holds)
    fcap = (d["fcap_num"] / d["fcap_den"] * BP) if d["fcap_den"] > 0 else None
    hold_rows.append((wal, fcap, tip, med_hold_h))
H = pl.DataFrame(hold_rows, schema=["wallet", "funding_capture_bps", "time_in_pos_frac", "med_hold_h_train"],
                 orient="row")
print(f"hold/funding features for {H.height} wallets", flush=True)

# ---- EXACT features from out/entries (opens), TRAIN-restricted ----
E = (pl.scan_parquet(sorted(glob.glob("out/entries/part_*")))
     .filter(pl.col("wallet").is_in(cohort) & (pl.col("b_ts") < TRAIN_HI) & pl.col("coin").is_in(COINS))
     .select("wallet", "coin", "b_ts", "dir", "q", "notl", "pos_after", "avg_entry_px", "fill_vwap")
     .collect().sort("wallet", "b_ts"))       # MAJORS-only (consistent with tape/regime features & the study scope)
print(f"train entries (opens) for cohort: {E.height} rows", flush=True)

def _cv(x):
    x = np.asarray(x, float)
    return float(x.std() / x.mean()) if x.size >= 2 and x.mean() > 0 else None
cad = (E.group_by("wallet", maintain_order=True).agg(dt=pl.col("b_ts").diff().drop_nulls())
       .with_columns(cadence_cv=pl.col("dt").map_elements(_cv, return_dtype=pl.Float64)).select("wallet", "cadence_cv"))

base = E.group_by("wallet").agg(
    size_cv=(pl.col("notl").std() / pl.col("notl").mean()),
    net_long_frac=(pl.col("dir") == 1).mean(),
    n_train_dec=pl.len(),
)
hhi = (E.group_by("wallet", "coin").agg(v=pl.col("notl").sum())
       .with_columns(sh=pl.col("v") / pl.col("v").sum().over("wallet"))
       .group_by("wallet").agg(coin_hhi=(pl.col("sh") ** 2).sum()))

# add_frac (|pos_after| > |q| => increasing a prior same-side position); avgdown = add at adverse px vs running avg
eps = 1e-9
Eadd = E.with_columns(is_add=(pl.col("pos_after").abs() > pl.col("q").abs() * (1 + eps)))
Eadd = Eadd.with_columns(
    is_avgdown=(pl.col("is_add") & (pl.col("dir") * (pl.col("fill_vwap") - pl.col("avg_entry_px")) < 0)))
conv = Eadd.group_by("wallet").agg(
    add_frac=pl.col("is_add").mean(),
    n_add=pl.col("is_add").sum(), n_avgdown=pl.col("is_avgdown").sum(),
).with_columns(
    avgdown_rate=pl.when(pl.col("n_add") > 0).then(pl.col("n_avgdown") / pl.col("n_add")).otherwise(None)
).select("wallet", "add_frac", "avgdown_rate")

# ---- regime_tilt from cohort_K_entries (TRAIN only): P(long|BULL) - P(long|BEAR) ----
ck = pl.read_parquet("out/cohort_K_entries.parquet").filter(pl.col("split") == "train").select("wallet", "dir", "regime")
tilt = (ck.group_by("wallet").agg(
    p_bull=((pl.col("regime") == "BULL") & (pl.col("dir") == 1)).sum(),
    n_bull=(pl.col("regime") == "BULL").sum(),
    p_bear=((pl.col("regime") == "BEAR") & (pl.col("dir") == 1)).sum(),
    n_bear=(pl.col("regime") == "BEAR").sum(),
).with_columns(
    regime_tilt=pl.when((pl.col("n_bull") > 0) & (pl.col("n_bear") > 0))
    .then(pl.col("p_bull") / pl.col("n_bull") - pl.col("p_bear") / pl.col("n_bear")).otherwise(None)
).select("wallet", "regime_tilt"))

# ---- JOIN all features on the cohort wallet list ----
out = (pl.DataFrame({"wallet": cohort})
       .join(H, on="wallet", how="left").join(base, on="wallet", how="left")
       .join(cad, on="wallet", how="left").join(hhi, on="wallet", how="left")
       .join(conv, on="wallet", how="left").join(tilt, on="wallet", how="left"))
cols = ["wallet", "funding_capture_bps", "time_in_pos_frac", "med_hold_h_train", "cadence_cv", "size_cv",
        "net_long_frac", "coin_hhi", "add_frac", "avgdown_rate", "regime_tilt", "n_train_dec"]
out = out.select(cols)
out.write_parquet("out/cohort_K_archfeat.parquet")
print(f"\nwrote {out.height} wallets -> out/cohort_K_archfeat.parquet")
with pl.Config(tbl_cols=-1):
    print(out.describe())
