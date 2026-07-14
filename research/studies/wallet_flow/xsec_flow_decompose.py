"""
xsec_flow_decompose — DECOMPOSE + RELAX pass on the SAME leak-free cells as xsec_flow_adjudicate.

Motivation (2026-07-10): the pooled adjudication returned a real but sub-cost lean (h=4 V-sim IC +0.018,
quintile spread ~+2bp/crossing, CI straddles the 3.6bp maker RT). Before ANY method-scoped negative we must
rule out that arbitrary thresholds + pooling are SUPPRESSING / HIDING the edge. This script relaxes each
arbitrary knob and unpools each average, on the identical V-sim/L2 signal (h_train=4), all OOS folds:

  (D1) HORIZON SWEEP  h_eval ∈ {1,2,3,4,6,8,12,24} — the gap-lag k-curve peaks at k=1-2, so h=4 may be the
       wrong harvest horizon. Report gross bp/crossing + day-block CI + per-HOUR-normalised rate; the SNR/cost
       sweet spot is argmax(net-per-hour), NOT h=4 by fiat.
  (D2) EXTREMITY + CONVICTION  quintile(20%) / decile(10%) / ventile(5%) / conviction-weighted long-short —
       equal-weighted quintiles discard the |S| gradient and the fat-tailed tail where the money is.
  (D3) PER-COIN + ADV-TERTILE  unpool the 45 alts: per-coin time-series IC(S,u), n_pos, SIGN TEST ACROSS COINS
       (coins = cross-independent units, the gate's combination test), split by pre-formation ADV tertile
       (is the edge in the illiquid/meme tail the liquidity screen dilutes?).
  (D4) REGIME SPLIT  bucket OOS hours by CAUSAL trailing cross-sectional dispersion (std of trailing-resid-mom
       across alts, known at t) — is the signal strong in high-dispersion/idiosyncratic hours and ~0 otherwise?
  (D5) COST LADDER  net bp/crossing at the best horizon under a cost ladder (zero → maker-earn → maker-pay →
       taker), so "sub-cost" is stated as a break-even, not a single arbitrary threshold.

OVER-CARRY DISCIPLINE (this is a multiple-comparisons machine): every sliced winner is reported (a) with a
day-block CI, (b) on ALL folds AND clean folds (≥202603) side-by-side, (c) with a sign test over the natural
independent unit of the slice, and (d) the per-coin / per-regime distributions are printed in full so a single
lucky cell can't masquerade as the headline. No argmax is reported without its siblings.

Reuses (identical construction → identical cells): A.build_resid / A.build_cohort_tables / A.universe,
S0.run_horizon / S0.fwd_sum / S0.residualize / S0.trailing_resid_mom, ADJ.build_q_fixed / ADJ._spread_ci /
ADJ.sign_test.  Run:  .venv/bin/python -m research.studies.wallet_flow.xsec_flow_decompose
"""
from __future__ import annotations
import time, json
from pathlib import Path
import numpy as np

from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

HS_EVAL = (1, 2, 3, 4, 6, 8, 12, 24)   # harvest-horizon sweep (signal is h_train=4-trained; eval strictly future)
H_TRAIN = 4                            # skill-weights trained on 4h-forward returns (matches adjudicate primary)
CLEAN_MIN = ADJ.CLEAN_MIN              # 202603
MAKER_RT_BP = ADJ.MAKER_RT_BP          # 3.6 bp round trip (maker half-spread ×2)
OUT = Path("data/derived/xsec_flow_decompose")
DUCK_TMP = f"{A.SCRATCH}/duck_xs_dec"


# ============================================================ generalized spread (extremity + conviction + submask)
def _hour_spreads_ext(s_inf, fv, R, msk, frac=0.2, conviction=False, trim_thr=None):
    """Per OOS hour: long-short forward-return (bp) of the top vs bottom `frac` of cells ranked by S.
    conviction=True → weight the long-short by demeaned S (Σ w·f / Σ|w|) instead of equal-weight extremes."""
    s = s_inf[msk]; f = fv[msk]; rr = R[msk]
    spreads = []; hrs = []
    for hr in np.unique(rr):
        m = rr == hr; si = s[m]; fi = f[m]
        ok = np.isfinite(si) & np.isfinite(fi)
        if trim_thr is not None: ok &= (np.abs(fi) <= trim_thr)
        si = si[ok]; fi = fi[ok]; n = len(si)
        if n < 10: continue
        if conviction:
            w = si - si.mean(); den = np.abs(w).sum()
            if den <= 0: continue
            spreads.append(float((w * fi).sum() / den) * 1e4)
        else:
            nq = int(n * frac)
            if nq < 1: continue
            order = np.argsort(si)
            spreads.append((fi[order[-nq:]].mean() - fi[order[:nq]].mean()) * 1e4)
        hrs.append(int(hr))
    return np.array(spreads), np.array(hrs, dtype=np.int64)


def spread_stat(s_inf, fv, R, hours, msk, frac=0.2, conviction=False, trim_thr=None):
    sp, hr = _hour_spreads_ext(s_inf, fv, R, msk, frac, conviction, trim_thr)
    if len(sp) < 10:
        return {"gross_bp": None, "ci95": [None, None], "n_crossings": int(len(sp))}
    lo, hi = ADJ._spread_ci(sp, hr, hours)
    return {"gross_bp": float(np.mean(sp)), "ci95": [lo, hi], "n_crossings": int(len(sp))}


# ============================================================ per-coin time-series IC ==========================
def per_coin_ic(s_inf, u, Cc, msk, alt_names):
    """For each alt: Pearson corr between S and the xsec-rank target u over that coin's OOS cells (across time).
    Positive → the signal ranks THIS coin correctly among its peers. Unpools the cross-sectional IC by name.
    Cc is the ALT-LOCAL column index (0..n_alt-1) as returned by run_horizon (ukey % n_alt)."""
    s = s_inf[msk]; uu = u[msk]; cc = Cc[msk]
    out = {}
    for c_col in np.unique(cc):
        m = cc == c_col; si = s[m]; ui = uu[m]
        ok = np.isfinite(si) & np.isfinite(ui); si = si[ok]; ui = ui[ok]
        if len(si) < 30 or si.std() == 0 or ui.std() == 0: continue
        out[alt_names[int(c_col)]] = {"ic": float(np.corrcoef(si, ui)[0, 1]), "n": int(len(si))}
    return out


def run():
    OUT.mkdir(parents=True, exist_ok=True); Path(DUCK_TMP).mkdir(parents=True, exist_ok=True)
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    _log(f"[1/5] universe @ {A.UNIV_FORMATION}: {len(alts)} alts (+ {A.FACTORS} factors)")

    panel = A.build_resid(con, coins)
    resid, hours, ci = panel["resid"], panel["hours"], panel["ci"]
    panel_month = panel["month"]
    N, C = panel["N"], panel["C"]; hmin = int(hours[0])
    alt_names = [c for c in coins if c not in A.FACTORS]
    alt_cols = [ci[c] for c in alt_names]; n_alt = len(alt_cols)
    col_to_ac = {ci[c]: k for k, c in enumerate(alt_names)}
    _log(f"[2/5] resid ({N} hours, {n_alt} alts)")

    LAG_full = S0.trailing_resid_mom(resid); LAG_ac = LAG_full[:, alt_cols]
    # forward-return VALUES (log ret; ×1e4 = bp) + rank target, per eval horizon
    FV = {}; U = {}
    for h in set(HS_EVAL) | {H_TRAIN}:
        Y = S0.fwd_sum(resid, h)
        FV[h] = Y[:, alt_cols]
        U[h] = S0.xsec_rank(Y, alt_cols)[:, alt_cols]
    _log("[2/5] fwd VALUES + rank targets built")

    # controls (crowd, funding) — identical to adjudicate
    A.build_cohort_tables(con, coins)
    CROWD = np.full((N, n_alt), np.nan)
    ag = con.execute("SELECT coin, h, allflow FROM aagg WHERE coin NOT IN ('BTC','ETH')").fetchnumpy()
    ar = ((ag["h"].astype(np.int64) - hmin) // 3600000).astype(int); ok = (ar >= 0) & (ar < N)
    acx = np.array([col_to_ac.get(ci.get(str(c), -1), -1) for c in ag["coin"]])
    good = ok & (acx >= 0); CROWD[ar[good], acx[good]] = ag["allflow"].astype(float)[good]
    FUND = np.full((N, n_alt), np.nan); inlist = "('" + "','".join(alt_names) + "')"
    fd = con.execute(f"""SELECT coin, (ts-ts%3600000) h, arg_max(funding, ts) f FROM asset_ctx
        WHERE coin IN {inlist} GROUP BY coin, h""").fetchnumpy()
    fr = ((fd["h"].astype(np.int64) - hmin) // 3600000).astype(int); ok = (fr >= 0) & (fr < N)
    fcx = np.array([col_to_ac.get(ci.get(str(c), -1), -1) for c in fd["coin"]])
    good = ok & (fcx >= 0); FUND[fr[good], fcx[good]] = fd["f"].astype(float)[good]

    # per-coin pre-formation ADV tertile (backward-looking: 30d before UNIV_FORMATION, same window as universe)
    import datetime as _dt
    fd0 = _dt.datetime.strptime(str(A.UNIV_FORMATION), "%Y%m%d").date()
    lo_d = int((fd0 - _dt.timedelta(days=30)).strftime("%Y%m%d")); hi_d = int(fd0.strftime("%Y%m%d"))
    adv_rows = con.execute(f"""SELECT coin, avg(adv) a FROM alt_adv WHERE day>={lo_d} AND day<{hi_d}
        AND coin IN {inlist} GROUP BY coin""").fetchall()
    adv_map = {c: float(a) for c, a in adv_rows}
    adv_vals = np.array([adv_map.get(nm, np.nan) for nm in alt_names])
    fin = np.isfinite(adv_vals)
    t1, t2 = np.nanpercentile(adv_vals[fin], [33.3, 66.6]) if fin.any() else (np.nan, np.nan)
    adv_tier = np.array(["mid"] * n_alt, dtype=object)   # per alt index
    adv_tier[adv_vals <= t1] = "low"; adv_tier[adv_vals > t2] = "high"; adv_tier[~fin] = "unk"
    _log(f"[3/5] controls + ADV tertiles (low≤{t1:,.0f} / high>{t2:,.0f} USD/day)")

    # flow rows → q_sim (V-sim, window-bug-fixed) — identical to adjudicate
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cid AS SELECT * FROM (VALUES
        {",".join(f"('{c}',{k})" for k, c in enumerate(alt_names))}) AS t(coin, ccode)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE wid AS
        SELECT wallet, (row_number() OVER (ORDER BY wallet)) - 1 AS wcode
        FROM (SELECT DISTINCT wallet FROM awb WHERE coin NOT IN ('BTC','ETH') AND flow<>0)""")
    rows = con.execute(f"""SELECT w.wcode, c.ccode, ((wb.h - {hmin})//3600000)::INT AS r, wb.mth,
               CASE WHEN wb.flow>0 THEN 1 WHEN wb.flow<0 THEN -1 ELSE 0 END AS s
        FROM awb wb JOIN wid w USING(wallet) JOIN cid c ON wb.coin=c.coin WHERE wb.flow<>0""").fetchnumpy()
    nW = int(con.execute("SELECT count(*) FROM wid").fetchone()[0])
    wcode = rows["wcode"].astype(np.int32); ccode = rows["ccode"].astype(np.int32)
    r = rows["r"].astype(np.int32); mth = rows["mth"].astype(np.int32); s = rows["s"].astype(np.int8)
    keep = (r >= 0) & (r < N); wcode, ccode, r, mth, s = wcode[keep], ccode[keep], r[keep], mth[keep], s[keep]
    del rows
    q_sim, q_trail = ADJ.build_q_fixed(wcode, r, s.astype(np.float64), N)
    _log(f"[3/5] flow rows {len(s):,} → q_sim built")

    months = sorted(set(int(x) for x in np.unique(mth))); folds = months[4:]
    first_row = {"_ms": {}}
    for m in folds:
        rr = r[mth == m]; first_row[m] = int(rr.min()); first_row["_ms"][m] = int(hours[rr.min()])

    res = {"config": {"h_train": H_TRAIN, "predictors": ["V-sim", "V-trail"], "neutralization": "L2 (⊥crowd,⊥mom)",
                      "folds": folds, "clean_min": CLEAN_MIN, "n_alts": n_alt, "maker_rt_bp": MAKER_RT_BP,
                      "hs_eval": list(HS_EVAL), "univ_formation": A.UNIV_FORMATION}}

    def decompose(pname, q):
        """Full decompose (D1-D5 + gap-lag) for one predictor's L2 h_train=4 signal on its own OOS cells."""
        _log(f"[4/5] {pname}: training h_train={H_TRAIN} signal ...")
        R, Cc, Uc, Smat = S0.run_horizon(H_TRAIN, wcode, ccode, r, mth, q, U[H_TRAIN], LAG_ac, nW, folds,
                                         first_row, (CROWD, LAG_ac, FUND), do_placebos=False, seed=S0.SEED)
        Smat = Smat.astype(np.float32)
        crowd = CROWD[R, Cc].copy(); lag = LAG_ac[R, Cc].copy()
        for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
        s_inf = S0.residualize(Smat[:, :1], np.column_stack([crowd, lag]), R)[:, 0].astype(np.float64)  # L2 signal
        clean_mask = panel_month[R] >= CLEAN_MIN
        all_mask = np.ones(len(R), bool)
        _log(f"[4/5] {pname}: {len(R):,} OOS cells, {clean_mask.sum():,} clean (≥{CLEAN_MIN})")
        out = {"n_cells": int(len(R))}

        def _both(fn):
            return {"all": fn(all_mask), "clean": fn(clean_mask)}

        # (D1) HORIZON SWEEP
        print(f"\n===== [{pname}] (D1) HORIZON SWEEP (L2 signal, quintile long-short) =====")
        d1 = {}
        for h in HS_EVAL:
            fv = FV[h][R, Cc]
            st = _both(lambda m, fv=fv: spread_stat(s_inf, fv, R, hours, m))
            for tag in ("all", "clean"):
                g = st[tag]["gross_bp"]
                st[tag]["per_hour_bp"] = (g / h) if g is not None else None
                st[tag]["net_at_maker_bp"] = (g - MAKER_RT_BP) if g is not None else None
            d1[f"h{h}"] = st
            a, c = st["all"], st["clean"]
            print(f"  h={h:2d}  ALL gross {a['gross_bp']:+.3f}bp CI[{a['ci95'][0]:+.2f},{a['ci95'][1]:+.2f}] "
                  f"/hr {a['per_hour_bp']:+.3f}  net@maker {a['net_at_maker_bp']:+.3f} | "
                  f"CLEAN {c['gross_bp']:+.3f} CI[{c['ci95'][0]:+.2f},{c['ci95'][1]:+.2f}]")
        out["D1_horizon_sweep"] = d1
        cand = [(h, d1[f"h{h}"]["all"]["gross_bp"]) for h in HS_EVAL if d1[f"h{h}"]["all"]["gross_bp"] is not None]
        best_h = max(cand, key=lambda x: (x[1] or -9) / x[0])[0] if cand else H_TRAIN
        print(f"  -> best harvest horizon by net-per-hour: h={best_h}")

        # (D2) EXTREMITY + CONVICTION
        print(f"\n===== [{pname}] (D2) EXTREMITY + CONVICTION (h=4 and best-h={best_h}) =====")
        d2 = {}
        for h in sorted({H_TRAIN, best_h}):
            fv = FV[h][R, Cc]; entry = {}
            for name, kw in (("quintile", dict(frac=0.2)), ("decile", dict(frac=0.1)),
                             ("ventile", dict(frac=0.05)), ("conviction", dict(conviction=True))):
                entry[name] = _both(lambda m, fv=fv, kw=kw: spread_stat(s_inf, fv, R, hours, m, **kw))
            d2[f"h{h}"] = entry
            print(f"  -- h={h} --")
            for name in ("quintile", "decile", "ventile", "conviction"):
                a = entry[name]["all"]; c = entry[name]["clean"]
                print(f"    {name:11s} ALL {a['gross_bp']:+.3f}bp CI[{a['ci95'][0]:+.2f},{a['ci95'][1]:+.2f}] | "
                      f"CLEAN {c['gross_bp']:+.3f}bp CI[{c['ci95'][0]:+.2f},{c['ci95'][1]:+.2f}]")
        out["D2_extremity"] = d2

        # (D3) PER-COIN + ADV-TERTILE
        print(f"\n===== [{pname}] (D3) PER-COIN unpool + ADV tertile (h=4 rank target) =====")
        d3 = {}
        for tag, msk in (("all", all_mask), ("clean", clean_mask)):
            pc = per_coin_ic(s_inf, Uc, Cc, msk, alt_names)
            ics = np.array([v["ic"] for v in pc.values()])
            npos = int((ics > 0).sum()); ncoin = len(ics)
            stt = ADJ.sign_test(list(ics))    # coins as independent units
            tiers = {"low": [], "mid": [], "high": []}
            for nm, v in pc.items():
                tr = adv_tier[alt_names.index(nm)]
                if tr in tiers: tiers[tr].append(v["ic"])
            tier_stat = {t: {"n": len(x), "mean_ic": (float(np.mean(x)) if x else None),
                             "n_pos": int(np.sum(np.array(x) > 0)) if x else 0} for t, x in tiers.items()}
            d3[tag] = {"n_coins": ncoin, "n_pos": npos, "mean_ic": float(np.mean(ics)) if ncoin else None,
                       "median_ic": float(np.median(ics)) if ncoin else None, "sign_test_p": stt["p"],
                       "adv_tiers": tier_stat,
                       "per_coin": {k: round(v["ic"], 4) for k, v in sorted(pc.items(), key=lambda x: -x[1]["ic"])}}
            print(f"  [{tag}] {npos}/{ncoin} coins IC>0  mean {np.mean(ics):+.4f}  median {np.median(ics):+.4f}  "
                  f"sign-test p={stt['p']:.3f}")
            for t in ("low", "mid", "high"):
                ts = tier_stat[t]; mi = f"{ts['mean_ic']:+.4f}" if ts['mean_ic'] is not None else "  n/a "
                print(f"      ADV {t:4s}: n={ts['n']:2d}  mean_ic {mi}  {ts['n_pos']}/{ts['n']} pos")
        out["D3_per_coin"] = d3

        # (D4) REGIME SPLIT (causal trailing dispersion)
        print(f"\n===== [{pname}] (D4) REGIME split by causal trailing xsec dispersion (h=4) =====")
        dcell = disp_hour[R]; fin = np.isfinite(dcell)
        lo_q, hi_q = np.nanpercentile(dcell[fin], [33.3, 66.6])
        reg = np.where(dcell <= lo_q, "low", np.where(dcell > hi_q, "high", "mid"))
        d4 = {}; fv4 = FV[H_TRAIN][R, Cc]
        for bucket in ("low", "mid", "high"):
            bm = (reg == bucket)
            st = {"all": spread_stat(s_inf, fv4, R, hours, all_mask & bm),
                  "clean": spread_stat(s_inf, fv4, R, hours, clean_mask & bm)}
            d4[bucket] = st
            a = st["all"]; c = st["clean"]
            ab = f"{a['gross_bp']:+.3f}" if a['gross_bp'] is not None else " n/a "
            cb = f"{c['gross_bp']:+.3f}" if c['gross_bp'] is not None else " n/a "
            aci = f"[{a['ci95'][0]:+.2f},{a['ci95'][1]:+.2f}]" if a['gross_bp'] is not None else ""
            print(f"  dispersion {bucket:4s}: ALL gross {ab}bp {aci} (n={a['n_crossings']}) | CLEAN {cb}bp")
        out["D4_regime"] = d4

        # (GAP-LAG) info vs impact/autocorrelation — critical for V-trail (its trailing window could inflate)
        print(f"\n===== [{pname}] GAP-LAG (info vs own-impact / trailing-autocorr) =====")
        gl = ADJ.gap_lag(resid, alt_cols, s_inf, R, Cc, hours, clean_mask)
        out["gap_lag"] = gl
        kc = gl["k_curve"]["all"]
        print("  k-curve IC(S,resid[t+k]) all: " + " ".join(f"{v:+.3f}" for v in kc[:12]))
        for tag in ("all", "clean"):
            gp = gl["gapped"][tag]
            print(f"  gapped ({tag}): g0:{gp['g0']['ic']:+.4f} g1:{gp['g1']['ic']:+.4f} "
                  f"g2:{gp['g2']['ic']:+.4f} g4:{gp['g4']['ic']:+.4f}  DECISION: {gl['decision'][tag]}")

        # (D5) COST LADDER at best horizon
        print(f"\n===== [{pname}] (D5) COST LADDER at h={best_h} (quintile) =====")
        fvb = FV[best_h][R, Cc]
        base = spread_stat(s_inf, fvb, R, hours, all_mask); g = base["gross_bp"]
        ladder = {"zero": 0.0, "maker_earn_half(-1.8rt credit)": -MAKER_RT_BP, "maker_pay(3.6rt)": MAKER_RT_BP,
                  "taker_lo(4.8rt)": 2 * ADJ.TAKER_FEE_BP[0], "taker_hi(9.0rt)": 2 * ADJ.TAKER_FEE_BP[1]}
        d5 = {"best_h": best_h, "gross_bp": g, "ci95": base["ci95"], "net": {}}
        print(f"  gross {g:+.3f}bp/crossing CI[{base['ci95'][0]:+.2f},{base['ci95'][1]:+.2f}]  (break-even = {g:+.3f}bp)")
        for nm, cst in ladder.items():
            net = (g - cst) if g is not None else None
            d5["net"][nm] = net
            print(f"    − {nm:32s} → net {net:+.3f}bp  {'CLEARS' if net and net > 0 else 'sub-cost'}")
        out["D5_cost_ladder"] = d5
        del Smat
        return out

    disp_hour = np.nanstd(LAG_ac, axis=1)     # per-hour causal xsec dispersion of trailing resid-mom (shared)
    for pname, q in (("V-sim", q_sim), ("V-trail", q_trail)):
        print(f"\n############################## PREDICTOR: {pname} ##############################")
        res[pname] = decompose(pname, q)

    (OUT / "results.json").write_text(json.dumps(res, indent=2))
    _log(f"[5/5] wrote {OUT/'results.json'}")
    print("\nDONE.")


if __name__ == "__main__":
    run()
