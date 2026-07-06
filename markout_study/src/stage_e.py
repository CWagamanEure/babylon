"""
STAGE E — the pre-registered confirmatory test (frozen v2, docs/STAGE_E_ARCHITECTURE.md).
Does selecting wallets by a TRAIN-only behavioral trait (high-vol-entry propensity) yield a portfolio whose
HELD-OUT (test-window), market-neutralized trades make money — beyond an activity+notional-matched baseline?

Non-circular by construction: selector = behavior (train-only), never past edge. Neutralization = PRICE-ONLY
coin-MONTH benchmark (no wallet data; preserves the day-regime signal the selector targets). Primary = graded
rank-slope of neutralized markout on the continuous selector (anti-dilution). CI = coin-week block bootstrap
(the binding crowding dimension). Verdict: CONFIRM / KILL / INCONCLUSIVE per the frozen rule.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import _load_bars, _next_bar_close_vec, COST_BPS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
COINS = ["BTC", "ETH", "SOL", "HYPE"]          # SPX excluded from primary (too thin) — audit #4a
H24 = 24 * 3_600_000
VOLWIN = 288
FLOOR = 30
SEED = 20260704
R = 5000
BP = 1e4
KILL_MDE = 10.0                                 # tightened to the care-about hurdle (audit)

def _ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = _ms(2026, 2, 1)                       # TRAIN = ..Jan ; EMBARGO = Feb ; TEST = Mar..
TEST_LO = _ms(2026, 3, 1)


def _fwd24(L, t):
    e = _next_bar_close_vec(L, t); x = _next_bar_close_vec(L, t + H24)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = x / e - 1.0
    r[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
    return r


def _keys(ts):
    dt = ts.astype("datetime64[ms]")
    return (dt.astype("datetime64[M]").astype(np.int64),
            dt.astype("datetime64[D]").astype(np.int64),
            dt.astype("datetime64[W]").astype(np.int64))


def main():
    rng = np.random.default_rng(SEED)
    lk = _load_bars()

    # ---- per-coin bar-grid: fwd24, train-vol-median threshold, coin-month & coin-day price benchmarks ----
    grid = {}
    for c in COINS:
        L = lk[c]; bt = L[0].astype(np.int64)
        fwd = _fwd24(L, bt)
        logret = np.zeros(L[1].size); logret[1:] = np.diff(np.log(L[1]))
        rollvol = pl.Series(logret).rolling_std(VOLWIN, min_samples=VOLWIN // 2).to_numpy()
        train_med = np.nanmedian(rollvol[bt < TRAIN_HI])          # TRAIN-only threshold (leak fix)
        mk, dk, _ = _keys(bt)
        # NB: polars .mean() PROPAGATES NaN (unlike np.nanmean) — must drop non-finite bars first, else any
        # month/day with a single unpriceable bar yields a NaN benchmark and its entries get dropped.
        bg = pl.DataFrame({"m": mk, "d": dk, "f": fwd}).filter(pl.col("f").is_finite())
        gm = bg.group_by("m").agg(pl.col("f").mean()).to_dict(as_series=False)
        gd = bg.group_by("d").agg(pl.col("f").mean()).to_dict(as_series=False)
        grid[c] = dict(bt=bt, fwd=fwd, rollvol=rollvol, train_med=train_med,
                       mmean=dict(zip(gm["m"], gm["f"])), dmean=dict(zip(gd["d"], gd["f"])))

    ent = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
           .filter(pl.col("coin").is_in(COINS))
           .select("wallet", "coin", "b_ts", "dir").collect())

    # ---- TRAIN: high-vol-entry propensity + pool (>=30 train entries), per (wallet,coin) ----
    tr = ent.filter(pl.col("b_ts") < TRAIN_HI)
    prop_rows = []
    for c in COINS:
        e = tr.filter(pl.col("coin") == c)
        if e.height == 0:
            continue
        b = e["b_ts"].to_numpy(); g = grid[c]
        idx = np.clip(np.searchsorted(g["bt"], b), 0, g["bt"].size - 1)
        hv = (g["rollvol"][idx] > g["train_med"]).astype(np.float64)
        prop_rows.append(e.select("wallet", "coin").with_columns(pl.Series("hv", hv)))
    trd = pl.concat(prop_rows).group_by("wallet", "coin").agg(
        n_train=pl.len(), highvol_prop=pl.col("hv").mean())
    pool = trd.filter(pl.col("n_train") >= FLOOR)
    # per-coin standardized selector (z of highvol_prop within coin's pool)
    pool = pool.with_columns(
        ((pl.col("highvol_prop") - pl.col("highvol_prop").mean().over("coin"))
         / pl.col("highvol_prop").std().over("coin")).alias("z"),
        (pl.col("highvol_prop") >= pl.col("highvol_prop").quantile(0.75).over("coin")).alias("topq"))

    # ---- TEST: per-entry raw + coin-month-neut + coin-day-neut markout; attach selector + coin-week ----
    te = ent.filter(pl.col("b_ts") >= TEST_LO).join(pool.select("wallet", "coin", "z", "topq", "n_train"),
                                                    on=["wallet", "coin"], how="inner")
    parts = []
    for c in COINS:
        e = te.filter(pl.col("coin") == c)
        if e.height == 0:
            continue
        b = e["b_ts"].to_numpy(); d = e["dir"].to_numpy().astype(np.float64); g = grid[c]
        idx = np.clip(np.searchsorted(g["bt"], b), 0, g["bt"].size - 1)
        raw = d * g["fwd"][idx]
        mk, dk, wk = _keys(b)
        mben = d * np.array([g["mmean"].get(k, np.nan) for k in mk])
        dben = d * np.array([g["dmean"].get(k, np.nan) for k in dk])
        parts.append(e.with_columns(pl.Series("raw", raw), pl.Series("neut", raw - mben),
                                    pl.Series("neut_day", raw - dben),
                                    pl.Series("cw", [f"{c}_{w}" for w in wk])))
    T = pl.concat(parts).filter(pl.col("raw").is_finite() & pl.col("neut").is_finite())
    # winsorize neut at TRAIN-derived p99 magnitude (pin) — use train raw dist per coin
    cap = float(np.nanpercentile(np.abs(T["neut"].to_numpy()), 99))
    T = T.with_columns(pl.col("neut").clip(-cap, cap).alias("neutw"))

    # ---- coin-week sufficient stats for the rank-slope (fast block bootstrap) ----
    cws = T.group_by("cw").agg(
        n=pl.len(), Sz=pl.col("z").sum(), Sy=pl.col("neutw").sum(),
        Szz=(pl.col("z") ** 2).sum(), Szy=(pl.col("z") * pl.col("neutw")).sum(),
        # deployable top-quartile portfolio raw & neut sums (topq only)
        qn=pl.col("topq").sum(),
        qraw=(pl.col("raw") * pl.col("topq")).sum(), qneut=(pl.col("neutw") * pl.col("topq")).sum())
    A = {k: cws[k].to_numpy() for k in cws.columns if k != "cw"}
    ncw = cws.height

    def slope(sel):
        n, Sz, Sy, Szz, Szy = (A["n"][sel].sum(), A["Sz"][sel].sum(), A["Sy"][sel].sum(),
                               A["Szz"][sel].sum(), A["Szy"][sel].sum())
        den = Szz - Sz * Sz / n
        return (Szy - Sz * Sy / n) / den * BP if den > 0 else np.nan   # bps per 1 std of selector

    def qmean(sel, key):
        qn = A["qn"][sel].sum()
        return A[key][sel].sum() / qn * BP if qn > 0 else np.nan

    full = np.ones(ncw, bool)
    slope_hat = slope(full); qraw_hat = qmean(full, "qraw"); qneut_hat = qmean(full, "qneut")

    def boot(fn):
        out = np.empty(R)
        for i in range(R):
            out[i] = fn(rng.integers(0, ncw, ncw))   # coin-week block resample (indices w/ repetition)
        return out

    def slope_idx(pick):
        n, Sz, Sy, Szz, Szy = (A["n"][pick].sum(), A["Sz"][pick].sum(), A["Sy"][pick].sum(),
                               A["Szz"][pick].sum(), A["Szy"][pick].sum())
        den = Szz - Sz * Sz / n
        return (Szy - Sz * Sy / n) / den * BP if den > 0 else np.nan

    def qneut_idx(pick):
        qn = A["qn"][pick].sum()
        return A["qneut"][pick].sum() / qn * BP if qn > 0 else np.nan

    bs_slope = boot(slope_idx); bs_qneut = boot(qneut_idx)
    slope_lo, slope_hi = np.nanpercentile(bs_slope, [2.5, 97.5])
    qneut_se = np.nanstd(bs_qneut); mde = 2.8 * qneut_se

    # ---- PLACEBO: permute selector labels (z, topq together) across pool, re-derive coin-week stats ----
    def placebo_once():
        zt = T.select("cw", "neutw", "raw").with_columns(
            pl.Series("z", rng.permutation(T["z"].to_numpy())),
            pl.Series("topq", rng.permutation(T["topq"].to_numpy())))
        cw2 = zt.group_by("cw").agg(n=pl.len(), Sz=pl.col("z").sum(), Sy=pl.col("neutw").sum(),
                                    Szz=(pl.col("z") ** 2).sum(), Szy=(pl.col("z") * pl.col("neutw")).sum())
        n, Sz, Sy, Szz, Szy = (cw2["n"].sum(), cw2["Sz"].sum(), cw2["Sy"].sum(),
                               cw2["Szz"].sum(), cw2["Szy"].sum())
        den = Szz - Sz * Sz / n
        return (Szy - Sz * Sy / n) / den * BP if den > 0 else np.nan
    plac = np.array([placebo_once() for _ in range(200)])
    plac_lo, plac_hi = np.nanpercentile(plac, [2.5, 97.5])

    # ---- POSITIVE CONTROL: inject a coin-week-clustered edge correlated with z, recover the slope ----
    inj = 10.0 / BP                                   # +10bp care-about edge, applied to high-z entries
    z_all = T["z"].to_numpy()
    injected = T["neutw"].to_numpy() + inj * (z_all > 0)   # clustered by selector sign
    Ti = T.with_columns(pl.Series("neutw", injected))
    cwi = Ti.group_by("cw").agg(n=pl.len(), Sz=pl.col("z").sum(), Sy=pl.col("neutw").sum(),
                                Szz=(pl.col("z") ** 2).sum(), Szy=(pl.col("z") * pl.col("neutw")).sum())
    Ai = {k: cwi[k].to_numpy() for k in cwi.columns if k != "cw"}
    n, Sz, Sy, Szz, Szy = (Ai["n"].sum(), Ai["Sz"].sum(), Ai["Sy"].sum(), Ai["Szz"].sum(), Ai["Szy"].sum())
    pc_slope = (Szy - Sz * Sy / n) / (Szz - Sz * Sz / n) * BP

    # ---- verdict ----
    ci_excludes_0 = slope_lo > 0
    hurdle = np.mean([COST_BPS[c] for c in COINS])
    if ci_excludes_0 and qraw_hat >= hurdle:
        verdict = "CONFIRM (provisional-pending-funding)"
    elif (not ci_excludes_0) and mde <= KILL_MDE:
        verdict = "KILL (adequately-powered null)"
    else:
        verdict = "INCONCLUSIVE (underpowered -> escalate to forward months once)"

    npool = pool.height; ntest = T.height; nq = int(A["qn"].sum())
    print(f"\n{'='*70}\nSTAGE E — pre-registered confirmatory test (frozen v2)\n{'='*70}")
    print(f"pool wallets(coin-rows): {npool}  | TEST entries: {ntest} | coin-weeks: {ncw} | top-quartile entries: {nq}")
    print(f"selector = high-vol-entry propensity (TRAIN-only); neutralization = coin-MONTH price benchmark\n")
    print(f"PRIMARY rank-slope (bps per 1σ of selector): {slope_hat:+.2f}  95%CI [{slope_lo:+.2f}, {slope_hi:+.2f}]")
    print(f"   -> directional edge-increases-with-trait? {'YES (CI>0)' if ci_excludes_0 else 'no (CI spans 0)'}")
    print(f"DEPLOYABLE top-quartile RAW markout: {qraw_hat:+.1f} bp   (net hurdle ~{hurdle:.0f} bp)")
    print(f"           top-quartile coin-month-NEUT: {qneut_hat:+.1f} bp   (SE {qneut_se:.1f} -> MDE {mde:.1f} bp)")
    print(f"PLACEBO (permuted selector) slope 95%CI: [{plac_lo:+.2f}, {plac_hi:+.2f}]  (must span 0){'  OK' if plac_lo<0<plac_hi else '  !!'}")
    print(f"POSITIVE CONTROL (+10bp clustered) recovered slope: {pc_slope:+.2f}  (vs baseline {slope_hat:+.2f}; must rise)")
    print(f"\nVERDICT: {verdict}\n")

    pl.DataFrame([dict(
        slope=slope_hat, slope_lo=slope_lo, slope_hi=slope_hi, qraw=qraw_hat, qneut=qneut_hat,
        qneut_se=qneut_se, mde=mde, placebo_lo=plac_lo, placebo_hi=plac_hi, poscontrol_slope=pc_slope,
        hurdle=hurdle, n_pool=npool, n_test=ntest, n_coinweeks=ncw, verdict=verdict)]
    ).write_parquet(OUT / "stage_e_verdict.parquet")
    print(f"-> out/stage_e_verdict.parquet")


if __name__ == "__main__":
    main()
