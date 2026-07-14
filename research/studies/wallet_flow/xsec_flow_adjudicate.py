"""xsec_flow_adjudicate — ADJUDICATE the audit's competing claims about the Step-0 cross-sectional signal.

Read audit/xsec_flow_step0/FINDINGS.md. This is a focused RE-MEASUREMENT that reuses xsec_flow_step0's panel
build, fold loop, V-sim build_q, skill-weight/shrink, S aggregation, per-hour residualize, day_block_ci, _spear.

PRIMARY CONFIG (the honest arm): V-sim predictor, L2-neutralized S (⊥ crowd + ⊥ lagged momentum), h∈{4,24}.
We do NOT lead with the cell-count t = IC·√cells (correlated coin-hours are not IID). Headline significance is
the month-block sign test (per-fold ICs) + day-block CI. Skill increment = informed IC − P-random IC.

Three falsifiable outputs (all reported TWICE — all 7 folds AND clean folds m≥202603 where the fixed universe
is PIT-aligned, adjudicating survivorship):

  (A) GAP-LAG DECOMPOSITION (info vs impact, the decisive test) — on the h=4 S:
      - per-future-hour-k IC: IC(S_t, resid[t+k]) for the SINGLE future hour k=1..24 (not cumulative).
      - gapped-cumulative IC: IC(S_t, Σ_{j=g+1..g+h} resid[t+j]) for gaps g∈{0,1,2,4} at h=4, each w/ day-block CI.
      - DECISION: k concentrated at k=1 & ≤~0 by k≈3 AND gapped IC collapses g0→g1/g2 → IMPACT/flow-continuation
        (taker-hopeless). Smooth decay to k≈4-8 AND gapped survives g1/g2 → INFORMATION (genuine selection).

  (B) QUINTILE RETURN SPREAD (economics/magnitude) — per OOS hour rank L2-neutralized S into quintiles, mean
      forward RESIDUAL RETURN (bp, using fwd_sum(resid,h) VALUES not ranks) of top-Q minus bottom-Q, pooled over
      folds, h∈{4,24}. gross bp/crossing (1 crossing per h hrs), day-block CI, 1%-trimmed, per-fold. vs maker
      round-trip ~3.6bp (2×1.8bp half-spread) + taker fee +2.4/4.5bp.

  (C) SURVIVORSHIP ADJUDICATION — every metric on ALL 7 folds AND CLEAN folds (m≥202603) only.

Also fixes the V-trail trailing-window bug (correctness F1: close the window at the LAST SIBLING of the current
HOUR, not the current ROW) and reports corrected V-trail as SECONDARY. Positive control kept as a sanity check.

    PYTHONPATH=/Users/corywagamaneure/bablyon .venv/bin/python -m research.studies.wallet_flow.xsec_flow_adjudicate
"""
from __future__ import annotations
import time, functools, json, math, warnings
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import xsec_flow_step0 as S0

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

HS = (4, 24)
CLEAN_MIN = 202603          # clean folds: fixed universe (UNIV_FORMATION=20260301) is PIT/backward-looking here
N_RAND = 200               # >=200 P-random weight-shuffle draws for the skill-increment permutation p
GAP_H = 4                  # horizon for the gapped-cumulative arm of the gap-lag test
MAKER_HALF_BP = 1.8; MAKER_RT_BP = 2 * MAKER_HALF_BP     # maker half-spread; round-trip over the h-hour hold
TAKER_FEE_BP = (2.4, 4.5)
OUT = Path("data/derived/xsec_flow_adjudicate")
DUCK_TMP = f"{A.SCRATCH}/duck_xs_adj"


# ============================================================ V-TRAIL WINDOW-BUG FIX =========================
def build_q_fixed(wcode, r, s, N):
    """q_sim (unchanged, exact (wallet,hour) group mean) + q_trail with the CORRECTNESS-F1 FIX: the trailing
    24h window must close at the LAST SIBLING of the current HOUR, not the current ROW. In step0 the window end
    was `idx+1` (the current row's position in the globally-sorted key), so same-hour siblings received order-
    dependent, truncated trailing sets. Fix: end = searchsorted(Ks, wallet*HSPAN + r, side='right')."""
    HSPAN = np.int64(N + 100)
    K = wcode.astype(np.int64) * HSPAN + r.astype(np.int64)
    order = np.argsort(K, kind="stable")
    Ks = K[order]; ss = s[order].astype(np.float64)
    w_s = wcode[order].astype(np.int64); r_s = r[order].astype(np.int64)
    # V-sim: exact (wallet,hour) group mean (identical to step0; the bug never touched this arm)
    _, inv, cnt = np.unique(Ks, return_inverse=True, return_counts=True)
    gsum = np.bincount(inv, weights=ss)
    q_sim_s = ss - gsum[inv] / cnt[inv]
    # V-trail: trailing (r-23, r] window WITHIN the wallet; window closed at the last sibling of hour r
    thr = w_s * HSPAN + (r_s - (S0.W_REL - 1))
    start = np.searchsorted(Ks, thr, side="left")
    end = np.searchsorted(Ks, w_s * HSPAN + r_s, side="right")     # <-- FIX: last sibling of the current HOUR
    csum = np.concatenate([[0.0], np.cumsum(ss)])
    wsum = csum[end] - csum[start]; wcnt = end - start
    q_trail_s = ss - wsum / np.where(wcnt > 0, wcnt, 1)
    inv_order = np.empty_like(order); inv_order[order] = np.arange(len(order))
    return q_sim_s[inv_order], q_trail_s[inv_order]


# ============================================================ single-hour / gapped forward rank targets ======
def single_hour_rank(resid, k, alt_cols):
    """Per-hour cross-sectional rank of the SINGLE future hour-k residual return: Y[t]=resid[t+k]. (N x n_alt.)"""
    N, C = resid.shape
    Y = np.full((N, C), np.nan); Y[:-k] = resid[k:]
    return S0.xsec_rank(Y, alt_cols)[:, alt_cols]


def gapped_fwd_rank(resid, g, h, alt_cols):
    """Per-hour cross-sectional rank of the GAPPED cumulative target: Y[t]=Σ_{j=g+1..g+h} resid[t+j]. g=0 == the
    t+1..t+h baseline (== fwd_sum(resid,h)). (N x n_alt.)"""
    N, C = resid.shape
    Y = np.zeros((N, C))
    for j in range(g + 1, g + h + 1):
        sh = np.full((N, C), np.nan); sh[:-j] = resid[j:]; Y = Y + sh
    return S0.xsec_rank(Y, alt_cols)[:, alt_cols]


# ============================================================ significance helpers ============================
def sign_test(ic_list):
    """Two-sided binomial sign test over per-fold ICs (the month-block, cross-independent-unit significance)."""
    vals = [v for v in ic_list if v is not None and np.isfinite(v)]
    n = len(vals); npos = sum(1 for v in vals if v > 0)
    if n == 0: return {"n": 0, "n_pos": 0, "p": None}
    k = max(npos, n - npos)
    p = min(1.0, 2.0 * sum(math.comb(n, i) for i in range(k, n + 1)) * (0.5 ** n))
    return {"n": n, "n_pos": npos, "p": float(p), "per_fold": [float(v) for v in vals]}


def ic_and_ci(s, u, day, msk):
    ic = A._spear(s[msk], u[msk]); lo, hi = S0.day_block_ci(day[msk], s[msk], u[msk])
    return {"ic": float(ic), "ci95": [float(lo), float(hi)],
            "n_eff": int((np.isfinite(s[msk]) & np.isfinite(u[msk])).sum())}


# ============================================================ (C) IC ladder + skill, all & clean folds ========
def ladder_and_skill(Smat, R, C, Uc, hours, CROWD, LAG, FUND, clean_mask):
    """Per-hour cross-sectional residualize once per rung (L0..L3) on the FULL Smat, then evaluate informed IC,
    day-block CI, rotation IC and the SKILL INCREMENT (informed IC − mean P-random IC; perm p=(1+#≥)/(B+1)) on
    BOTH the all-folds mask and the clean-folds (m≥202603) mask. Residualize is per-hour so masking whole months
    is identical to refitting on the subset."""
    day = (hours[R] // 86400000).astype(np.int64)
    crowd = CROWD[R, C].copy(); lag = LAG[R, C].copy(); fund = FUND[R, C].copy()
    for a in (crowd, lag, fund): a[~np.isfinite(a)] = 0.0
    rungs = {"L0_raw": None, "L1_crowd": crowd[:, None],
             "L2_crowd_mom": np.column_stack([crowd, lag]),
             "L3_crowd_mom_fund": np.column_stack([crowd, lag, fund])}
    out = {"all": {}, "clean": {}}
    masks = {"all": np.ones(len(R), bool), "clean": clean_mask}
    for name, ctrl in rungs.items():
        Sn = S0.residualize(Smat, ctrl, R)
        s_inf = Sn[:, 0].astype(np.float64); rot = Sn[:, 1].astype(np.float64)
        rnd = Sn[:, 2:2 + N_RAND].astype(np.float64)
        for tag, msk in masks.items():
            ic = A._spear(s_inf[msk], Uc[msk])
            lo, hi = S0.day_block_ci(day[msk], s_inf[msk], Uc[msk])
            rnd_ics = np.array([A._spear(rnd[msk, j], Uc[msk]) for j in range(N_RAND)])
            pr_mean = float(np.nanmean(rnd_ics))
            nge = int(np.sum(rnd_ics >= ic))
            out[tag][name] = {
                "informed_ic": float(ic), "ci95": [float(lo), float(hi)],
                "n_eff": int((np.isfinite(s_inf[msk]) & np.isfinite(Uc[msk])).sum()),
                "rotation_ic": float(A._spear(rot[msk], Uc[msk])),
                "p_random_mean": pr_mean, "p_random_std": float(np.nanstd(rnd_ics)),
                "skill_increment": float(ic - pr_mean), "perm_p": float((1 + nge) / (N_RAND + 1)),
                # reported-but-demoted: the naive IID t the audit killed (kept only for transparency)
                "t_iid_demoted": float(ic * np.sqrt(max(1, (np.isfinite(s_inf[msk]) & np.isfinite(Uc[msk])).sum())))}
    return out


def per_fold_l2(Smat, R, C, Uc, hours, CROWD, LAG, panel_month):
    """L2-neutralized informed IC per held-out MONTH (the cross-independent-unit / month-block units)."""
    crowd = CROWD[R, C].copy(); lag = LAG[R, C].copy()
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    s_inf = S0.residualize(Smat, np.column_stack([crowd, lag]), R)[:, 0].astype(np.float64)
    cm = panel_month[R]; out = {}
    for m in sorted(np.unique(cm)):
        sel = cm == m
        out[int(m)] = float(A._spear(s_inf[sel], Uc[sel])) if sel.sum() >= 50 else None
    return out


# ============================================================ (A) gap-lag decomposition ========================
def gap_lag(resid, alt_cols, s_inf, R, C, hours, clean_mask, hgap=GAP_H, kmax=24):
    day = (hours[R] // 86400000).astype(np.int64)
    masks = {"all": np.ones(len(R), bool), "clean": clean_mask}
    kcurve = {"all": [], "clean": []}
    for k in range(1, kmax + 1):
        uk = single_hour_rank(resid, k, alt_cols)[R, C]
        for tag, msk in masks.items():
            kcurve[tag].append(float(A._spear(s_inf[msk], uk[msk])))
    gaps = {"all": {}, "clean": {}}
    for g in (0, 1, 2, 4):
        ug = gapped_fwd_rank(resid, g, hgap, alt_cols)[R, C]
        for tag, msk in masks.items():
            gaps[tag][f"g{g}"] = ic_and_ci(s_inf, ug, day, msk)
    # DECISION heuristic (numbers decide; verdict is a summary of them) — per mask
    verdict = {}
    for tag in ("all", "clean"):
        kc = np.array(kcurve[tag]); g0 = gaps[tag]["g0"]["ic"]; g1 = gaps[tag]["g1"]["ic"]; g2 = gaps[tag]["g2"]["ic"]
        k1 = kc[0]; k_late = float(np.nanmean(kc[2:4]))       # mean of hours k=3,4
        conc = (k1 > 0) and (k_late <= 0.25 * k1)             # concentrated at k=1, ~0 by k≈3
        gap_collapse = (g0 > 0) and (g1 < 0.5 * g0)           # gapped IC halves by a 1h gap
        gap_survive = (g0 > 0) and (g1 > 0.5 * g0) and (g2 > 0.4 * g0)
        smooth = (k1 > 0) and (float(np.nanmean(kc[3:8])) > 0.15 * k1)   # decay persists to k≈4-8
        if conc and gap_collapse:
            v = "IMPACT / flow-continuation (taker-hopeless)"
        elif smooth and gap_survive:
            v = "INFORMATION (genuine selection)"
        else:
            v = "MIXED / AMBIGUOUS (see numbers)"
        verdict[tag] = {"verdict": v, "k1": float(k1), "k3_4_mean": k_late,
                        "k4_8_mean": float(np.nanmean(kc[3:8])), "g0": float(g0), "g1": float(g1),
                        "g2": float(g2), "g1_over_g0": float(g1 / g0) if g0 else None,
                        "g2_over_g0": float(g2 / g0) if g0 else None}
    return {"k_curve": kcurve, "gapped": gaps, "decision": verdict}


# ============================================================ (B) quintile forward-return spread (bp) ==========
def _hour_spreads(s_inf, fv, R, msk, trim_thr=None):
    """Per OOS hour: rank cells by S into quintiles, mean forward-residual-return (bp) of top-Q minus bottom-Q."""
    s = s_inf[msk]; f = fv[msk]; rr = R[msk]
    spreads = []; hrs = []
    for hr in np.unique(rr):
        m = rr == hr; si = s[m]; fi = f[m]
        ok = np.isfinite(si) & np.isfinite(fi)
        if trim_thr is not None: ok &= (np.abs(fi) <= trim_thr)
        si = si[ok]; fi = fi[ok]; n = len(si)
        if n < 10: continue
        nq = n // 5
        if nq < 1: continue
        order = np.argsort(si)
        spreads.append((fi[order[-nq:]].mean() - fi[order[:nq]].mean()) * 1e4)   # bp
        hrs.append(int(hr))
    return np.array(spreads), np.array(hrs, dtype=np.int64)


def _spread_ci(spreads, hrs, hours, n=1000, seed=7):
    if len(spreads) < 10: return (np.nan, np.nan)
    days = (hours[hrs] // 86400000).astype(np.int64); ud = np.unique(days)
    loc = {d: np.nonzero(days == d)[0] for d in ud}; rng = np.random.default_rng(seed); st = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        sel = np.concatenate([loc[ud[p]] for p in pick]); st.append(spreads[sel].mean())
    s = np.array(st); return (float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5)))


def quintile_spread(s_inf, fv, R, hours, clean_mask, panel_month):
    fin = np.isfinite(fv)
    trim_thr = float(np.nanpercentile(np.abs(fv[fin]), 99)) if fin.any() else None     # drop top-1% |coin-hour ret|
    masks = {"all": np.ones(len(R), bool), "clean": clean_mask}
    res = {}
    for tag, msk in masks.items():
        sp, hr = _hour_spreads(s_inf, fv, R, msk)
        spt, hrt = _hour_spreads(s_inf, fv, R, msk, trim_thr=trim_thr)
        lo, hi = _spread_ci(sp, hr, hours)
        res[tag] = {"gross_bp": float(np.mean(sp)) if len(sp) else None, "ci95": [lo, hi],
                    "n_crossings": int(len(sp)), "trimmed1pct_bp": float(np.mean(spt)) if len(spt) else None,
                    "clears_maker_rt": bool((np.mean(sp) if len(sp) else -1) > MAKER_RT_BP)}
    # per-fold (all folds)
    pf = {}
    cm = panel_month[R]
    for m in sorted(np.unique(cm)):
        msk = cm == m; sp, _ = _hour_spreads(s_inf, fv, R, msk)
        pf[int(m)] = float(np.mean(sp)) if len(sp) else None
    res["per_fold_bp"] = pf
    return res


# ============================================================ MAIN =============================================
def run():
    OUT.mkdir(parents=True, exist_ok=True); Path(DUCK_TMP).mkdir(parents=True, exist_ok=True)
    S0.N_RAND = N_RAND                       # override step0's 30-draw placebo -> >=200 for the permutation p
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    print(f"[1/6] universe @ {A.UNIV_FORMATION}: {len(alts)} alts (+ {A.FACTORS} factors, EXCLUDED from signal)")

    print("[2/6] residual panel (causal rolling betas) ...")
    panel = A.build_resid(con, coins)
    resid, hours, ci = panel["resid"], panel["hours"], panel["ci"]
    panel_month = panel["month"]
    N, C = panel["N"], panel["C"]; hmin = int(hours[0])
    alt_names = [c for c in coins if c not in A.FACTORS]
    alt_cols = [ci[c] for c in alt_names]; n_alt = len(alt_cols)
    col_to_ac = {ci[c]: k for k, c in enumerate(alt_names)}
    _log(f"resid built ({N} hours, {n_alt} alts)")

    LAG_full = S0.trailing_resid_mom(resid); LAG_ac = LAG_full[:, alt_cols]
    U = {}; FV = {}
    for h in HS:
        Y = S0.fwd_sum(resid, h)
        U[h] = S0.xsec_rank(Y, alt_cols)[:, alt_cols]           # per-hour cross-sectional RANK target
        FV[h] = Y[:, alt_cols]                                  # forward-residual-return VALUE (log; ×1e4 = bp)
        _log(f"target rank u + fwd VALUE built for h={h}")

    print("[3/6] cohort tables (awb/aagg) + controls ...")
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
    _log("controls (crowd, funding) built")

    print("[4/6] flow rows (int-encoded, alt-only) ...")
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
    del rows; _log(f"flow rows: {len(s):,} over {nW:,} wallets")

    q_sim, q_trail = build_q_fixed(wcode, r, s.astype(np.float64), N)      # V-sim; V-trail (WINDOW-BUG FIXED)
    _log("q_sim / q_trail (fixed) built")

    months = sorted(set(int(x) for x in np.unique(mth))); folds = months[4:]
    first_row = {"_ms": {}}
    for m in folds:
        rr = r[mth == m]; first_row[m] = int(rr.min()); first_row["_ms"][m] = int(hours[rr.min()])
    n_clean = sum(1 for m in folds if m >= CLEAN_MIN)
    print(f"[5/6] WF folds: {folds}  ({len(folds)} total, {n_clean} clean m≥{CLEAN_MIN})")

    results = {"config": {"horizons": list(HS), "primary_predictor": "V-sim", "primary_neutralization": "L2 (⊥crowd,⊥mom)",
                          "folds": folds, "clean_min": CLEAN_MIN, "n_folds": len(folds), "n_clean_folds": n_clean,
                          "n_wallets": nW, "n_alts": n_alt, "n_rand": N_RAND, "maker_rt_bp": MAKER_RT_BP,
                          "taker_fee_bp": list(TAKER_FEE_BP), "universe_formation": A.UNIV_FORMATION},
               "primary_Vsim": {}, "secondary_Vtrail_fixed": {}}

    # ---------- PRIMARY: V-sim, both horizons ----------
    s_inf_h4_for_gaplag = None; R4 = C4 = None
    for h in HS:
        _log(f"=== PRIMARY V-sim  h={h} ===")
        R, Cc, Uc, Smat = S0.run_horizon(h, wcode, ccode, r, mth, q_sim, U[h], LAG_ac, nW, folds,
                                          first_row, (CROWD, LAG_ac, FUND), do_placebos=True, seed=S0.SEED)
        Smat = Smat.astype(np.float32)                 # halve memory for the 202-col placebo matrix
        clean_mask = panel_month[R] >= CLEAN_MIN
        lad = ladder_and_skill(Smat, R, Cc, Uc, hours, CROWD, LAG_ac, FUND, clean_mask)
        pf = per_fold_l2(Smat, R, Cc, Uc, hours, CROWD, LAG_ac, panel_month)
        st_all = sign_test([pf[m] for m in sorted(pf)])
        st_clean = sign_test([pf[m] for m in sorted(pf) if m >= CLEAN_MIN])
        # L2-neutralized informed S for gap-lag & quintile (per-hour residualize, informed column)
        crowd = CROWD[R, Cc].copy(); lag = LAG_ac[R, Cc].copy()
        for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
        s_inf_L2 = S0.residualize(Smat, np.column_stack([crowd, lag]), R)[:, 0].astype(np.float64)
        qsp = quintile_spread(s_inf_L2, FV[h][R, Cc], R, hours, clean_mask, panel_month)
        entry = {"ic_ladder": lad, "per_fold_L2": {str(k): v for k, v in pf.items()},
                 "month_block_sign_test": {"all": st_all, "clean": st_clean}, "quintile_spread": qsp}
        if h == GAP_H:
            gl = gap_lag(resid, alt_cols, s_inf_L2, R, Cc, hours, clean_mask)
            entry["gap_lag"] = gl; s_inf_h4_for_gaplag = True
        results["primary_Vsim"][f"h{h}"] = entry
        _print_primary(h, lad, pf, st_all, st_clean, qsp, entry.get("gap_lag"))
        del Smat, s_inf_L2

    # ---------- SECONDARY: V-trail (window-bug FIXED) ----------
    for h in HS:
        _log(f"=== SECONDARY V-trail (fixed)  h={h} ===")
        R, Cc, Uc, Smat = S0.run_horizon(h, wcode, ccode, r, mth, q_trail, U[h], LAG_ac, nW, folds,
                                          first_row, (CROWD, LAG_ac, FUND), do_placebos=True, seed=S0.SEED)
        Smat = Smat.astype(np.float32); clean_mask = panel_month[R] >= CLEAN_MIN
        lad = ladder_and_skill(Smat, R, Cc, Uc, hours, CROWD, LAG_ac, FUND, clean_mask)
        pf = per_fold_l2(Smat, R, Cc, Uc, hours, CROWD, LAG_ac, panel_month)
        st_all = sign_test([pf[m] for m in sorted(pf)])
        results["secondary_Vtrail_fixed"][f"h{h}"] = {"ic_ladder": lad,
            "per_fold_L2": {str(k): v for k, v in pf.items()}, "month_block_sign_test": {"all": st_all}}
        L2a = lad["all"]["L2_crowd_mom"]
        print(f"  V-trail(fixed) h={h}: L2 IC {L2a['informed_ic']:+.4f} CI[{L2a['ci95'][0]:+.4f},"
              f"{L2a['ci95'][1]:+.4f}] skill {L2a['skill_increment']:+.4f} p={L2a['perm_p']:.4f} | sign {st_all['n_pos']}/{st_all['n']}")
        del Smat

    # ---------- POSITIVE CONTROL (must still recover) ----------
    print("[6/6] POSITIVE CONTROL — inject synthetic edge, confirm recovery ...")
    pc = S0.positive_control(wcode, ccode, r, mth, s, U[24], LAG_ac, nW, folds, first_row,
                             hours, CROWD, FUND, n_alt, N)
    results["positive_control"] = pc
    print(f"    injected {pc['n_synth']} synth @ p={pc['edge_p']}: L0 IC {pc['L0_ic']:+.4f} (t {pc['L0_t']:+.1f}) "
          f"| L2 IC {pc['L2_ic']:+.4f} (t {pc['L2_t']:+.1f}) -> recovered={pc['recovered']}")

    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    print(f"\nwrote {OUT}/results.json")
    return results


def _print_primary(h, lad, pf, st_all, st_clean, qsp, gl):
    print(f"\n  ====== PRIMARY V-sim  h={h} ======")
    for tag in ("all", "clean"):
        print(f"  -- IC ladder ({tag} folds) --")
        for name, d in lad[tag].items():
            print(f"    {name:20s} IC {d['informed_ic']:+.4f} CI[{d['ci95'][0]:+.4f},{d['ci95'][1]:+.4f}] "
                  f"skill {d['skill_increment']:+.4f} (P-rand {d['p_random_mean']:+.4f}) p={d['perm_p']:.4f} "
                  f"rot {d['rotation_ic']:+.4f}")
    print(f"  per-fold L2: " + "  ".join(f"{k}:{v:+.4f}" if v is not None else f"{k}:na" for k, v in sorted(pf.items())))
    print(f"  month-block sign test: all {st_all['n_pos']}/{st_all['n']} p={st_all['p']} | "
          f"clean {st_clean['n_pos']}/{st_clean['n']} p={st_clean['p']}")
    for tag in ("all", "clean"):
        q = qsp[tag]
        print(f"  quintile spread ({tag}): gross {q['gross_bp']:+.3f}bp CI[{q['ci95'][0]:+.3f},{q['ci95'][1]:+.3f}] "
              f"trim1% {q['trimmed1pct_bp']:+.3f}bp | maker RT {MAKER_RT_BP}bp cleared={q['clears_maker_rt']} "
              f"(n={q['n_crossings']})")
    if gl:
        print("  -- GAP-LAG (h=4 S) --")
        kc = gl["k_curve"]["all"]
        print("    k-curve IC(S,resid[t+k]) all: " + " ".join(f"{v:+.3f}" for v in kc[:12]))
        for tag in ("all", "clean"):
            g = gl["gapped"][tag]
            print(f"    gapped ({tag}): " + "  ".join(f"g{gg}:{g['g'+str(gg)]['ic']:+.4f}" for gg in (0, 1, 2, 4)))
            print(f"    DECISION ({tag}): {gl['decision'][tag]['verdict']}")


if __name__ == "__main__":
    run()
