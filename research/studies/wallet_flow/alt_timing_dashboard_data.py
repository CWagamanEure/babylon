"""alt_timing_dashboard_data — compute the artifacts the alt-timing dashboard notebook visualizes.

Runs with the .venv (needs duckdb + research code). Builds, for the DEPLOYED recency-gated cohort
(data/derived/alt_timing/cohort.json), the in-sample evidence series the notebook plots:
  - the cohort's hourly breadth TILT over the whole tape + the BTC/ETH-neutral alt-INDEX and tight-BASKET returns
  - timing IC by horizon (H1/H4/H8) with a RANDOM-RECENT placebo band (the deployment-relevant null:
    does timing-selection beat random recently-active wallets?)
  - the smoothed-8h sign(tilt) BASKET BOOK: cumulative gross + net equity at maker / top-tier / base fee
  - the recency-gated walk-forward fold z's and the liveness census (measured numbers, provenance-labelled)
Emits to data/derived/alt_timing/dashboard/. The notebook (miniconda kernel) only loads + plots these.

    .venv/bin/python -m research.studies.wallet_flow.alt_timing_dashboard_data
"""
from __future__ import annotations
import functools, warnings, json
from pathlib import Path
import numpy as np
import pyarrow as pa, pyarrow.parquet as pq
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
Wb, MINOBS = 720, 240
HS = (1, 4, 8)                       # horizons for the timing IC
SMOOTH = 8                           # follower/prereg smoothing (dormant-cohort H8 config)
S_HEAD = 1                           # headline book smoothing (H1-matched to the live cohort's OOS signal)
SWEEP_SMOOTH = (1, 2, 4, 8)          # smoothing-sensitivity sweep (config vs H1 signal)
N_PLACEBO = 100                      # random-recent cohorts for the in-sample null band
N_PLACEBO_OOS = 60                   # random cohorts for the OOS null band (per-fold, pooled)
FEES = {"maker": 0.0, "toptier": 2.4, "base": 4.5}   # bp per crossing (on top of half-spread)
SEED = 20260710
OUT = Path("data/derived/alt_timing/dashboard")
COH = Path("data/derived/alt_timing/cohort.json")
RECENT_MONTHS = (202605, 202606); MIN_RECENT_H = 40; MINH = 20

# Measured evidence from the recency-gated WF + liveness runs (provenance: alt_mt_recency.py, census 2026-07-10).
# Stored (not recomputed — the placebo-per-fold WF is a ~10min job we already ran) so the notebook can show them.
WF_FOLDS = {  # recency-gated top-N by timing skill, per-fold z (informed vs random-recent), by horizon
    "folds": [202603, 202604, 202605, 202606],
    "H1": {"top1500": [3.1, 3.6, 1.7, -0.8], "top2500": [2.1, 3.8, 4.1, -0.8], "top300": [3.2, 2.7, -0.2, -0.5]},
    "H8": {"top1500": None, "top2500": [2.0, 2.2, 2.3, -2.0], "top300": [1.3, 1.5, 0.4, -0.1]},
    "note": "recency-gated (active last 2mo, >=40 alt-h); top-1500 H1 mean z +1.9, top-2500 H1 +2.3; weakest fold 202606",
}
CENSUS = {
    "dormant_top150":  {"n": 150, "live_pct": 9,  "alt_active_pct": 2,  "label": "old top-150 (all-history score, no recency)"},
    "recency_top1500": {"n": 200, "live_pct": 44, "alt_active_pct": 26, "label": "deployed recency-gated top-1500 (sample=200)"},
    "window": "last 24h, 2026-07-10",
}


def _ann_sharpe(x):
    x = x[np.isfinite(x)]
    if len(x) < 10 or x.std() == 0: return float("nan")
    return float(x.mean() / x.std() * np.sqrt(24 * 365))


def _prev(m):                        # previous YYYYMM
    y, mo = divmod(m, 100); mo -= 1
    return (y - 1) * 100 + 12 if mo == 0 else y * 100 + mo


def _rand_mask(rng, npool, nsel):
    mm = np.zeros(npool, bool); mm[rng.choice(npool, min(nsel, npool), replace=False)] = True; return mm


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(COH.read_text())
    cohort = list(cfg["cohort"]); basket = list(cfg["basket"]); cohort_sha = cfg["cohort_sha"]
    print(f"cohort {cohort_sha}: {len(cohort)} wallets, basket {basket}")

    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_dash'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False); coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins); A.build_cohort_tables(con, coins)
    hours, ci, N = panel["hours"], panel["ci"], panel["N"]; hmin = int(hours[0]); hh = hours.astype(np.int64)

    # ---- hourly mid lattice → BTC/ETH-neutral alt-INDEX and tight-BASKET returns (mirrors export_timing_cohort) ----
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbe AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d = con.execute("SELECT coin,h,mid FROM hbe").fetchnumpy()
    ca = np.asarray(d["coin"], dtype=object); ha = d["h"].astype(np.int64); C = len(coins)
    Lp = np.full((N, C), np.nan); rr = ((ha - hmin) // 3600000).astype(int); cc = np.array([ci[str(x)] for x in ca])
    ok = (rr >= 0) & (rr < N); Lp[rr[ok], cc[ok]] = np.log(d["mid"].astype(float)[ok]); R = np.diff(Lp, axis=0, prepend=np.nan)
    btc, eth = R[:, ci["BTC"]], R[:, ci["ETH"]]; eth_o = eth - rolling_beta(eth, btc, Wb, MINOBS) * btc

    def neutral(cols):
        s = np.nanmean(R[:, [ci[c] for c in cols]], axis=1)
        s = s - rolling_beta(s, btc, Wb, MINOBS) * btc
        return s - rolling_beta(s, eth_o, Wb, MINOBS) * eth_o
    idx = neutral(alts); bkt = neutral(basket)
    cs = np.where(np.isfinite(idx), idx, 0.0)
    fwH = {H: np.array([cs[h + 1:h + 1 + H].sum() if h < N - H else np.nan for h in range(N)]) for H in HS}
    bkt_next = np.array([bkt[h + 1] if h < N - 1 else np.nan for h in range(N)])   # book PnL: pos@t earns basket@t+1
    HOUR = 3600000
    # trailing-24h index momentum (PURE PAST return, zero forward info) — used to build the ROTATION-selected
    # placebo cohort (prosecutor Rank 1): if wallets ranked by alignment with PAST rotation reproduce the OOS IC,
    # the "skill" is passive alt-vs-majors rotation loading, not forward timing.
    lagmom = np.array([cs[max(0, h - 24):h].sum() if h > 0 else np.nan for h in range(N)])

    # ---- recency-eligible pool (the placebo universe) + int-encoded awb rows for vectorized tilt ----
    inlist = "('" + "','".join(alts) + "')"; rm = ",".join(str(m) for m in RECENT_MONTHS)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE elig AS SELECT wallet FROM alt_flow
        WHERE month IN ({rm}) AND coin IN {inlist}
        GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""")
    # ⚠️ AUDIT FIX (correctness F1): exclude BTC/ETH — awb spans FACTORS+alts, and counting majors votes in the
    # breadth tilt (a) contaminates the "alt" signal with risk-on/off majors flow and (b) diverges from the live
    # follower, which excludes majors. Alt-only tilt = the signal we actually deploy.
    rows = con.execute(f"""SELECT wb.wallet, wb.h, sign(wb.flow) s FROM awb wb JOIN elig e USING(wallet)
        WHERE wb.flow<>0 AND wb.coin NOT IN ('BTC','ETH')""").fetchnumpy()
    rw = np.asarray([str(x) for x in rows["wallet"]], dtype=object)
    rh = ((rows["h"].astype(np.int64) - hmin) // 3600000).astype(int); rs = rows["s"].astype(np.int64)
    uw, wcode = np.unique(rw, return_inverse=True)
    keep = (rh >= 0) & (rh < N); rh, rs, wcode = rh[keep], rs[keep], wcode[keep]
    print(f"eligible pool {len(uw):,} wallets, {len(rh):,} awb rows")

    def tilt_of(wmask):                # wmask: bool over uw (unique wallets) → per-hour breadth tilt
        sel = wmask[wcode]
        npos = np.bincount(rh[sel & (rs > 0)], minlength=N).astype(float)
        nneg = np.bincount(rh[sel & (rs < 0)], minlength=N).astype(float)
        den = npos + nneg; t = np.where(den > 0, (npos - nneg) / den, np.nan)
        return t, den                  # den = n_active voters that hour

    # ⚠️ AUDIT FIX (data-integrity/correctness F3): cfg value is the FULL relative spread (bp); the per-crossing
    # (mid→touch) cost is HALF of it. dpos already counts crossings (flip=2), so charge full/2 per unit.
    hsbp = float(np.mean(list(cfg.get("basket_half_spread_bp", {"x": 1.8}).values()))) / 2.0

    def smval(t, S):                                          # trailing-S-hour mean of tilt (the smoothed value)
        return np.array([np.nanmean(t[max(0, h - S + 1):h + 1]) if np.isfinite(t[max(0, h - S + 1):h + 1]).any()
                         else np.nan for h in range(N)])

    def possm(t, S):                                          # sign of trailing-S-hour mean tilt → position
        sm = smval(t, S); return np.where(np.isfinite(sm), np.sign(sm), 0.0)

    def book_of(pos):                                         # gross + net-by-fee series from a position array
        gross = pos * bkt_next; dpos = np.abs(np.diff(pos, prepend=0.0)); out = {"gross": gross}
        for name, fee in FEES.items():
            out[name] = gross - dpos * (hsbp + fee) / 1e4
        out["turnover"] = float(np.nanmean(dpos)); return out

    # ================= (A) IN-SAMPLE REFERENCE — SELECTION-INFLATED, not the edge =================
    # The deployed cohort was SCORED on all history, so its full-sample tilt-IC is circular (chosen to maximise
    # exactly this). Kept only to show the winner's-curse gap vs the OOS number below. DO NOT headline.
    rng = np.random.default_rng(SEED)
    cohort_set = set(cohort); cmask = np.array([w in cohort_set for w in uw]); nsel = int(cmask.sum()); npool = len(uw)
    tilt_is, nact_is = tilt_of(cmask); pos_is = possm(tilt_is, S_HEAD)
    ic_is = {}
    for H in HS:
        fw = fwH[H]; inf_ic = A._spear(tilt_is, fw)
        draws = np.array([A._spear(tilt_of(_rand_mask(rng, npool, nsel))[0], fw) for _ in range(N_PLACEBO)])
        mu, sd = float(np.nanmean(draws)), float(np.nanstd(draws))
        ic_is[f"H{H}"] = {"informed_ic": float(inf_ic), "placebo_mean": mu, "placebo_std": sd,
                          "z": float((inf_ic - mu) / sd) if sd > 0 else float("nan")}
        print(f"  [in-sample] H{H}: IC {inf_ic:+.4f} placebo {mu:+.4f}±{sd:.4f} z {ic_is[f'H{H}']['z']:+.2f} (CIRCULAR)")
    bk_is = book_of(pos_is)

    # ================= (B) WALK-FORWARD OOS — the honest, deployable estimate =================
    # Each fold: score wallets on train (< month m) only, recency-gate on the 2 months before m, take top-N by
    # score, evaluate that cohort's tilt on the HELD-OUT month m. Concatenate months → one OOS series.
    months = [int(r[0]) for r in con.execute("SELECT DISTINCT mth FROM awb ORDER BY mth").fetchall()]
    TESTM = months[4:]                                        # need >=3 train months + a 2-month recency window
    print(f"  OOS folds: {TESTM}")
    NSEL_OOS = min(len(cohort), 1500)
    oos_tilt = np.full(N, np.nan); rnd_series = np.full((N_PLACEBO_OOS, N), np.nan); rot_tilt = np.full(N, np.nan)
    for m in TESTM:
        ms_cut = int(con.execute(f"SELECT min(h) FROM awb WHERE mth={m}").fetchone()[0])
        emb = ms_cut - HOUR                                   # AUDIT FIX F5: embargo the H=1 seam hour from scoring
        fmask = np.isfinite(fwH[1]) & (hh < emb)
        con.register("fsrc", {"hms": hh[fmask].astype(np.int64), "fwd": fwH[1][fmask].astype(float)})
        con.execute("CREATE OR REPLACE TEMP TABLE ftab AS SELECT * FROM fsrc"); con.unregister("fsrc")
        lmask = np.isfinite(lagmom) & (hh < ms_cut)           # rotation score uses PAST-only, no embargo needed
        con.register("lsrc", {"hms": hh[lmask].astype(np.int64), "lag": lagmom[lmask].astype(float)})
        con.execute("CREATE OR REPLACE TEMP TABLE ltab AS SELECT * FROM lsrc"); con.unregister("lsrc")
        # AUDIT FIX F2: score on ALT-only signed flow (majors notional dominated sign(nf) before)
        sc = con.execute(f"""WITH wh AS (SELECT wallet,h,sum(flow) nf FROM awb
                WHERE mth<{m} AND coin NOT IN ('BTC','ETH') GROUP BY wallet,h)
            SELECT wh.wallet, avg(sign(wh.nf)*f.fwd) score,
                   avg(sign(wh.nf)*l.lag) rot FROM wh JOIN ftab f ON wh.h=f.hms JOIN ltab l ON wh.h=l.hms
            WHERE wh.nf<>0 GROUP BY wh.wallet HAVING count(*)>={MINH}""").fetchnumpy()
        wal_m = np.asarray([str(x) for x in sc["wallet"]], dtype=object)
        score_m = sc["score"].astype(float); rot_m = sc["rot"].astype(float)
        r1, r2 = _prev(_prev(m)), _prev(m)
        act = con.execute(f"""SELECT wallet FROM alt_flow WHERE month IN ({r1},{r2}) AND coin IN {inlist}
            GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""").fetchall()
        active = set(str(x[0]) for x in act)
        elig = np.array([w in active for w in wal_m]); wal_e = wal_m[elig]; sc_e = score_m[elig]; ro_e = rot_m[elig]
        if len(wal_e) < NSEL_OOS: continue
        cohort_m = set(wal_e[np.argsort(-sc_e)[:NSEL_OOS]])
        cohort_rot = set(wal_e[np.argsort(-ro_e)[:NSEL_OOS]])     # rotation/momentum-selected placebo cohort
        con.register("elig_arr", {"wallet": wal_e.astype(object)})
        # AUDIT FIX F1: alt-only fold tilt (was counting BTC/ETH votes)
        fr = con.execute(f"""SELECT wb.wallet, wb.h, sign(wb.flow) s FROM awb wb JOIN elig_arr e USING(wallet)
            WHERE wb.mth={m} AND wb.flow<>0 AND wb.coin NOT IN ('BTC','ETH')""").fetchnumpy(); con.unregister("elig_arr")
        fw_ = np.asarray([str(x) for x in fr["wallet"]], dtype=object)
        fh = ((fr["h"].astype(np.int64) - hmin) // 3600000).astype(int); fs = fr["s"].astype(np.int64)
        uwm, wcm = np.unique(fw_, return_inverse=True); kk = (fh >= 0) & (fh < N); fh, fs, wcm = fh[kk], fs[kk], wcm[kk]

        def fold_tilt(wmask):
            sel = wmask[wcm]
            npo = np.bincount(fh[sel & (fs > 0)], minlength=N).astype(float)
            nne = np.bincount(fh[sel & (fs < 0)], minlength=N).astype(float)
            den = npo + nne; return np.where(den > 0, (npo - nne) / den, np.nan)
        cm = np.array([w in cohort_m for w in uwm]); ft = fold_tilt(cm)
        mh = np.isfinite(ft); oos_tilt[mh] = ft[mh]                    # write this month's OOS tilt
        rcm = np.array([w in cohort_rot for w in uwm]); rft = fold_tilt(rcm)
        rmh = np.isfinite(rft); rot_tilt[rmh] = rft[rmh]              # rotation-selected cohort tilt
        for j in range(N_PLACEBO_OOS):
            rt = fold_tilt(_rand_mask(rng, len(uwm), NSEL_OOS)); rnd_series[j, mh] = rt[mh]
        print(f"    fold {m}: elig {len(wal_e):,}, cohort {len(cohort_m)}, OOS hours {int(mh.sum())}")

    tm = np.isfinite(oos_tilt)                                # AUDIT FIX F4: Sharpe over TEST hours only (pre-test
    pos_oos = possm(oos_tilt, S_HEAD)                         # flat hours have gross=0.0 (finite) and diluted it
    bk_oos = book_of(pos_oos)
    oos_sweep = {}                                            # smoothing-sensitivity: does ANY simple config monetize?
    for S in SWEEP_SMOOTH:
        bs = book_of(possm(oos_tilt, S))
        oos_sweep[str(S)] = {"gross_sharpe": _ann_sharpe(bs["gross"][tm]), "turnover": bs["turnover"],
                             **{f"net_sharpe_{n}": _ann_sharpe(bs[n][tm]) for n in FEES}}
        print(f"  [OOS sweep] smooth={S}: gross {oos_sweep[str(S)]['gross_sharpe']:+.2f} "
              f"net@toptier {oos_sweep[str(S)]['net_sharpe_toptier']:+.2f} turnover/hr {bs['turnover']:.3f}")
    ic_oos = {}
    for H in HS:
        fw = fwH[H]; inf_ic = A._spear(oos_tilt, fw)
        draws = np.array([A._spear(rnd_series[j], fw) for j in range(N_PLACEBO_OOS)])
        mu, sd = float(np.nanmean(draws)), float(np.nanstd(draws))
        n_eff = int((np.isfinite(oos_tilt) & np.isfinite(fw)).sum())
        rot_ic = float(A._spear(rot_tilt, fw))               # rotation-selected cohort IC (prosecutor Rank 1)
        ic_oos[f"H{H}"] = {"informed_ic": float(inf_ic), "placebo_mean": mu, "placebo_std": sd,
                           "z_vs_random": float((inf_ic - mu) / sd) if sd > 0 else float("nan"),
                           "t_vs_zero": float(inf_ic * np.sqrt(n_eff)) if n_eff > 0 else float("nan"),
                           "rotation_ic": rot_ic, "n_eff_hours": n_eff,
                           "placebo_draws": [float(x) for x in draws]}
        d = ic_oos[f"H{H}"]
        print(f"  [OOS] H{H}: IC {inf_ic:+.4f} | z_vs_random {d['z_vs_random']:+.2f} | "
              f"t_vs_zero {d['t_vs_zero']:+.2f} | ROTATION-selected IC {rot_ic:+.4f}")
    for name in FEES:
        print(f"  [OOS] book net Sharpe @{name}: {_ann_sharpe(bk_oos[name][tm]):+.2f}")
    print(f"  [OOS] gross Sharpe {_ann_sharpe(bk_oos['gross'][tm]):+.2f} turnover/hr {bk_oos['turnover']:.3f}")

    # ---- emit series parquet (in-sample + OOS columns) ----
    fin = np.isfinite(bkt_next)
    tbl = {"hour_ms": hh, "tilt": tilt_is, "smoothed": smval(tilt_is, S_HEAD), "n_active": nact_is,
           "fwd_idx_h1": fwH[1], "bkt_next": bkt_next, "pos_is": pos_is,
           "oos_tilt": oos_tilt, "oos_pos": pos_oos, "oos_in_test": np.isfinite(oos_tilt),
           "is_gross_cum_bp": np.nancumsum(bk_is["gross"]) * 1e4, "oos_gross_cum_bp": np.nancumsum(bk_oos["gross"]) * 1e4}
    for name in FEES:
        tbl[f"is_net_{name}_cum_bp"] = np.nancumsum(bk_is[name]) * 1e4
        tbl[f"oos_net_{name}_cum_bp"] = np.nancumsum(bk_oos[name]) * 1e4
    pq.write_table(pa.table({k: pa.array(v) for k, v in tbl.items()}), OUT / "series.parquet")

    book = {"half_spread_bp": hsbp,
            "in_sample": {"gross_sharpe": _ann_sharpe(bk_is["gross"]), "turnover": bk_is["turnover"],
                          **{f"net_sharpe_{n}": _ann_sharpe(bk_is[n]) for n in FEES}},
            "oos": {"gross_sharpe": _ann_sharpe(bk_oos["gross"][tm]), "turnover": bk_oos["turnover"],
                    **{f"net_sharpe_{n}": _ann_sharpe(bk_oos[n][tm]) for n in FEES},
                    "head_smooth": S_HEAD, "smooth_sweep": oos_sweep,
                    "test_months": TESTM, "n_test_hours": int(tm.sum())}}
    (OUT / "ic.json").write_text(json.dumps({"in_sample": ic_is, "oos": ic_oos}, indent=2))
    summary = {"cohort_sha": cohort_sha, "n_wallets": len(cohort), "basket": basket,
               "as_of_hour_ms": int(cfg.get("as_of_hour_ms", 0)), "n_hours": int(fin.sum()),
               "book": book, "wf_folds": WF_FOLDS, "census": CENSUS,
               "prereg": "docs/ALT_TIMING_PAPER_PREREG.md", "eligible_pool": int(len(uw))}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"wrote {OUT}/series.parquet, ic.json, summary.json  ({int(fin.sum())} usable hours)")


if __name__ == "__main__":
    main()
