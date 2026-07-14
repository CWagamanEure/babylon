"""
DEPLOYABLE COPY-EDGE — quantify the actual out-of-sample edge of a copy-portfolio formed from the
top-conviction wallets, ranked on PAST market-neutral (coin-DAY-neutralized) edge, with honest
cluster-bootstrap CIs, positive-control MDE, cost/lag/funding netting, and decile dose-response.

Neutralization = coin-DAY price benchmark (the grain that produces the r~=0.61 train->test wallet
correlation; raw & coin-month give ~0). neut = d*(fwd - mean_fwd_over_coinday_bars). This is the
"market-neutral edge a beta-hedged copier targets" per the study's framing.

Split: TRAIN b_ts<2026-02-01 | EMBARGO Feb | TEST b_ts>=2026-03-01. 24h post-fill markout, leak-free.
Guards against OVER-CLAIM (the mirror of over-null): 15-min follower lag, cost hurdle, funding sensitivity,
HYPE-drop, positive fraction, single-epoch caveat.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import _load_bars, _next_bar_close_vec, COST_BPS

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "out"
COINS = ["BTC", "ETH", "SOL", "HYPE"]
H24 = 24 * 3_600_000; LAG = 15 * 60_000; BP = 1e4
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = _ms(2026, 2, 1); TEST_LO = _ms(2026, 3, 1)
NTRAIN_MIN = 300
SEED = 20260705


def build():
    """Per-entry table: raw & coin-day-neut 24h markout, plus the 15-min-lagged follower versions."""
    lk = _load_bars(); parts = []
    for c in COINS:
        L = lk[c]; bt = L[0].astype(np.int64)
        def fwd_at(off):
            e = _next_bar_close_vec(L, bt + off); x = _next_bar_close_vec(L, bt + off + H24)
            with np.errstate(all="ignore"): r = x / e - 1.0
            r[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
            return r
        fwd = fwd_at(0)                       # markout entering at the bar after b
        fwd_lag = fwd_at(LAG)                 # follower: enters 15 min later, same 24h window
        day = bt // 86_400_000
        bg = pl.DataFrame({"d": day, "f": fwd}).filter(pl.col("f").is_finite())
        dmean = dict(zip(*bg.group_by("d").agg(pl.col("f").mean()).to_dict(as_series=False).values()))
        ec = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
              .filter(pl.col("coin") == c).select("wallet", "b_ts", "dir", "notl").collect())
        b = ec["b_ts"].to_numpy(); dd = ec["dir"].to_numpy().astype(np.float64)
        i = np.clip(np.searchsorted(bt, b), 0, bt.size - 1)
        eday = b // 86_400_000
        dben = np.array([dmean.get(k, np.nan) for k in eday])          # coin-day field mean fwd
        # lagged entry's benchmark day (b+15min can cross midnight rarely) — use same daymean map
        eday_l = (b + LAG) // 86_400_000
        dben_l = np.array([dmean.get(k, np.nan) for k in eday_l])
        raw = dd * fwd[i]; neut = raw - dd * dben
        raw_l = dd * fwd_lag[i]; neut_l = raw_l - dd * dben_l
        wk = (b.astype("datetime64[ms]").astype("datetime64[W]")).astype(np.int64)
        parts.append(ec.with_columns(
            pl.Series("coin", [c] * ec.height), pl.Series("day", eday),
            pl.Series("raw", raw), pl.Series("neut", neut),
            pl.Series("raw_l", raw_l), pl.Series("neut_l", neut_l),
            pl.Series("cw", [f"{c}_{w}" for w in wk])))
    E = pl.concat(parts)
    # winsorize markout cols at TRAIN p99.5 magnitude (tame fat-finger; report is robust, see DOF note)
    trn = E.filter(pl.col("b_ts") < TRAIN_HI)
    for col in ["raw", "neut", "raw_l", "neut_l"]:
        cap = float(np.nanpercentile(np.abs(trn[col].to_numpy()[np.isfinite(trn[col].to_numpy())]), 99.5))
        E = E.with_columns(pl.col(col).clip(-cap, cap))
    return E.filter(pl.col("raw").is_finite() & pl.col("neut").is_finite())


def wallet_train_stats(tr):
    """Per wallet (pooled majors): n_train, neut edge, coin-day-CLUSTERED t-stat of neut markout."""
    cl = tr.group_by("wallet", "coin", "day").agg(cm=pl.col("neut").mean())   # cluster (coin-day) means
    cls = cl.group_by("wallet").agg(ncl=pl.len(), cedge=pl.col("cm").mean(), csd=pl.col("cm").std())
    n = tr.group_by("wallet").agg(n=pl.len(), edge=pl.col("neut").mean(), raw_edge=pl.col("raw").mean())
    W = n.join(cls, on="wallet").with_columns(
        t_eff=pl.col("cedge") / (pl.col("csd") / pl.col("ncl").sqrt()))
    return W.filter(pl.col("n") >= NTRAIN_MIN)


def main():
    rng = np.random.default_rng(SEED)
    E = build()
    tr = E.filter(pl.col("b_ts") < TRAIN_HI); te = E.filter(pl.col("b_ts") >= TEST_LO)
    W = wallet_train_stats(tr).filter(pl.col("t_eff").is_finite())
    # rank into deciles by day-clustered neut t-stat (decile 10 = highest conviction)
    W = W.with_columns(((pl.col("t_eff").rank() - 1) / pl.col("t_eff").len() * 10)
                       .floor().clip(0, 9).cast(pl.Int64).alias("dec"))
    print(f"{'='*88}\nDEPLOYABLE COPY-EDGE  (rank on TRAIN coin-day-neut t-stat, n_train>=300; TEST Mar-Jun'26)\n{'='*88}")
    print(f"train wallets (pooled majors, n_train>={NTRAIN_MIN}): {W.height}   deciles of ~{W.height//10} each")

    # --- reproduce the r~=0.61 train->test predictiveness (grounding) ---
    tes_w = te.group_by("wallet").agg(nt=pl.len(), edget=pl.col("neut").mean(), rawt=pl.col("raw").mean())
    Wc = W.join(tes_w, on="wallet", how="inner").filter(pl.col("nt") >= 20)
    x = Wc["edge"].to_numpy(); y = Wc["edget"].to_numpy(); ok = np.isfinite(x) & np.isfinite(y)
    print(f"train->test wallet neut-edge correlation (n_train>=300, nt>=20, N={ok.sum()}): "
          f"pearson r = {np.corrcoef(x[ok], y[ok])[0,1]:+.3f}")

    # ---- decile dose-response: TEST pooled edges by conviction decile ----
    dec_map = dict(zip(W["wallet"].to_list(), W["dec"].to_list()))
    te = te.with_columns(pl.col("wallet").replace_strict(dec_map, default=None).alias("dec")).filter(
        pl.col("dec").is_not_null())
    print(f"\n{'decile':>6s} {'#wall':>6s} {'n_test':>8s} {'raw bp':>8s} {'neut bp':>8s} "
          f"{'neut_lag bp':>11s} {'raw_lag bp':>10s} {'%pos(neut)':>10s}")
    nm = lambda ser: float(np.nanmean(ser.to_numpy()))   # nan-aware (polars .mean propagates NaN)
    rows = []
    for dq in range(10):
        s = te.filter(pl.col("dec") == dq)
        nw = W.filter(pl.col("dec") == dq).height
        r = nm(s["raw"]) * BP; nn = nm(s["neut"]) * BP
        nl = nm(s["neut_l"]) * BP; rl = nm(s["raw_l"]) * BP
        pos = 100 * (s["neut"] > 0).mean()
        rows.append((dq, nw, s.height, r, nn, nl, rl, pos))
        print(f"{dq+1:>6d} {nw:>6d} {s.height:>8d} {r:>+8.1f} {nn:>+8.1f} {nl:>+11.1f} {rl:>+10.1f} {pos:>9.0f}%")

    # ---- TOP DECILE deployable estimand + honest clustered CIs ----
    top = te.filter(pl.col("dec") == 9)
    topw = W.filter(pl.col("dec") == 9)
    neut_hat = nm(top["neut"]) * BP; raw_hat = nm(top["raw"]) * BP
    neutl_hat = nm(top["neut_l"]) * BP; rawl_hat = nm(top["raw_l"]) * BP
    print(f"\n{'-'*88}\nTOP DECILE (highest conviction) deployable portfolio  [{topw.height} wallets, {top.height} test entries]")
    print(f"  pooled OOS neut (market-neutral) markout : {neut_hat:+.2f} bp")
    print(f"  pooled OOS raw markout                   : {raw_hat:+.2f} bp")
    print(f"  15-min-lagged neut (follower-realizable) : {neutl_hat:+.2f} bp")
    print(f"  15-min-lagged raw                        : {rawl_hat:+.2f} bp")

    # cluster bootstraps on the TOP-DECILE neut edge -----------------------------------------
    def cluster_boot(df, key, valcol, R=5000):
        g = df.group_by(key).agg(s=pl.col(valcol).sum(), c=pl.len())
        s = g["s"].to_numpy(); c = g["c"].to_numpy(); m = s.size
        out = np.empty(R)
        for i in range(R):
            pick = rng.integers(0, m, m)
            out[i] = s[pick].sum() / c[pick].sum()
        return out * BP
    bw = cluster_boot(top, "wallet", "neut")       # cluster by wallet
    bcw = cluster_boot(top, "cw", "neut")          # cluster by coin-week
    # two-way (resample wallets AND coin-weeks jointly is complex; report both one-ways + the wider)
    def ci(b): return np.nanpercentile(b, [2.5, 97.5])
    wl, wh = ci(bw); cl_, ch = ci(bcw)
    print(f"\n  95% CI  cluster-by-WALLET   : [{wl:+.2f}, {wh:+.2f}] bp   (SE {np.nanstd(bw):.2f})")
    print(f"  95% CI  cluster-by-COIN-WEEK : [{cl_:+.2f}, {ch:+.2f}] bp   (SE {np.nanstd(bcw):.2f})")
    lo = min(wl, cl_); hi = max(wh, ch)
    print(f"  HONEST (wider of the two)    : [{lo:+.2f}, {hi:+.2f}] bp  -> {'EXCLUDES 0' if lo>0 else 'SPANS 0'}")
    binding_se = max(np.nanstd(bw), np.nanstd(bcw))
    # CI on the 15-min-lagged (follower-realizable) neut leg — the deployability-relevant quantity
    topL = top.filter(pl.col("neut_l").is_finite())
    blw = cluster_boot(topL, "wallet", "neut_l"); blcw = cluster_boot(topL, "cw", "neut_l")
    lwl, lwh = ci(blw); lcl, lch = ci(blcw)
    print(f"  LAGGED neut 95% CI wallet    : [{lwl:+.2f}, {lwh:+.2f}] ; coin-week [{lcl:+.2f}, {lch:+.2f}]  "
          f"-> {'EXCLUDES 0' if min(lwl,lcl)>0 else 'SPANS 0'}")

    # ---- POSITIVE-CONTROL MDE: inject a known edge into top-decile neut, does the CI recover it? ----
    mde = 2.8 * binding_se   # ~80% power at alpha=5% (two-sided) using the binding cluster SE
    print(f"\n  positive-control MDE (2.8 x binding SE) : {mde:.2f} bp")
    for inj in [5.0, 10.0, 20.0]:
        b_inj = cluster_boot(top.with_columns((pl.col("neut") + inj / BP)), "cw", "neut")
        ilo = np.nanpercentile(b_inj, 2.5)
        print(f"     inject +{inj:.0f}bp -> recovered {b_inj.mean():+.1f}bp, CI_lo {ilo:+.1f}  "
              f"{'(detected)' if ilo>0 else '(not detected)'}")

    # ---- COST + FUNDING NETTING ----
    # per-entry round-trip cost (coin COST_BPS) applied to raw & to the lagged (deployable) legs
    cst = top.with_columns(pl.col("coin").replace_strict(COST_BPS).alias("cost"))
    mean_cost = cst["cost"].mean()
    print(f"\n{'-'*88}\nNET-OF-COST / LAG / FUNDING (top decile)")
    print(f"  mean round-trip COST_BPS over cohort entries: {mean_cost:.1f} bp")
    net_raw = raw_hat - mean_cost
    net_neut = neut_hat - mean_cost           # beta-hedged copier: neutral edge minus cost
    net_neut_lag = neutl_hat - mean_cost      # + follower lag
    print(f"  raw  - cost                          : {net_raw:+.2f} bp")
    print(f"  NEUT - cost  (beta-hedged, no lag)   : {net_neut:+.2f} bp")
    print(f"  NEUT - cost - 15min lag              : {net_neut_lag:+.2f} bp   <-- KEY deployable number")
    for fund in [0, 5, 10, 15]:
        print(f"     ...minus {fund:>2d}bp/24h funding drag : {net_neut_lag - fund:+.2f} bp")

    # ---- OVER-CLAIM diagnostics: per-coin decomposition + HYPE-drop of the top decile ----
    print(f"\n{'-'*88}\nOVER-CLAIM GUARD — per-coin decomposition of the top-decile neut edge:")
    pc = top.group_by("coin").agg(
        n=pl.len(), neut=(pl.col("neut").fill_nan(None).mean() * BP),
        neut_l=(pl.col("neut_l").fill_nan(None).mean() * BP),
        raw=(pl.col("raw").fill_nan(None).mean() * BP))
    print(pc.sort("coin"))
    exH = top.filter(pl.col("coin") != "HYPE")
    bxh = cluster_boot(exH, "cw", "neut"); xl, xh = ci(bxh)
    print(f"  DROP-HYPE top-decile neut: {exH['neut'].mean()*BP:+.2f} bp  CI [{xl:+.2f},{xh:+.2f}]  "
          f"{'EXCLUDES 0' if xl>0 else 'SPANS 0'}")

    pl.DataFrame(rows, schema=["decile", "n_wall", "n_test", "raw_bp", "neut_bp", "neut_lag_bp",
                               "raw_lag_bp", "pct_pos"], orient="row").write_parquet(OUT / "deployable_deciles.parquet")
    print(f"\n-> out/deployable_deciles.parquet")


if __name__ == "__main__":
    main()
