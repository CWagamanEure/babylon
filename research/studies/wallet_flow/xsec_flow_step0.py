"""xsec_flow_step0 — Step 0 base-rate: is there ANY OOS cross-sectional alt-SELECTION edge in wallet flow,
once beta / rotation / momentum are stripped?  Built to XSEC_FLOW_STEP0_ARCH.md (binding).

The estimand (all per the arch doc):
  Universe  = PIT liquid alts, BTC/ETH EXCLUDED from signal + tilt (audit F1/F2 — they were the rotation leak).
  Target    = cross-sectional RANK of the forward BTC/ETH-residual return (rotation removed AT the target):
              resid via causal rolling betas (reuse A.build_resid) -> forward h-sum -> per-hour rank/(n-1) - 0.5.
              Horizons h in {4, 24}.
  Predictor = size-blind relative reallocation  q_{i,a,t} = sign(flow) - mean_{traded set}(sign(flow)).
              V-sim  = demean over coins the wallet traded THIS hour;  V-trail = over the trailing 24h traded set.
  Weight    = walk-forward TRAIN-ONLY shrunk skill score  g_i=mean(q*u), theta=g*n/(n+lambda), W=max(0,theta).
  Signal    = S_{a,t}=sum_i W_i*q_{i,a,t}, then a NEUTRALIZATION LADDER (per-hour cross-sectional regress-and-
              residualize): L0 raw, L1 (-)crowd flow, L2 (-)lagged residual momentum, L3 (-)funding. IC at EVERY rung.

Guards (from audit/alt_timing_dashboard/FINDINGS.md — must NOT repeat):
  * F1/F2 majors contamination -> BTC/ETH excluded from flow signal AND tilt (hedges/factors only).
  * F5 train/test seam leak     -> h-hour EMBARGO at the seam (train rows whose forward window enters test dropped).
  * causal rolling betas only (A.build_resid); expanding train, single held-out month folds; recency gate to the
    2 months before the fold.
  * TWO placebos baked in (both must be beaten): P-random (skill weights shuffled among recently-active wallets)
    and P-rotation (weights from wallets scored on alignment with LAGGED residual momentum — pure past).
  * report IC estimate + time-block(day)-bootstrap CI + IC-vs-zero t (NOT a bare z); per-fold AND pooled.
  * POSITIVE CONTROL: inject a synthetic cohort whose flow is correlated with the forward target; confirm the
    pipeline recovers it (proves not blind-by-construction / MDE <= care-about).
  * effective-N: correlation-cluster count of the top-weighted wallets (dedup caveat).

    PYTHONPATH=/Users/corywagamaneure/bablyon .venv/bin/python -m research.studies.wallet_flow.xsec_flow_step0
"""
from __future__ import annotations
import time, functools, json, warnings
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

HS = (4, 24)                     # horizons (slower = cheaper turnover, where x-sec selection should live)
W_REL = 24                       # trailing-hours window for the V-trail traded set
MIN_TRAIN_OBS = 5                # a wallet needs >= this many train (q,u) obs to earn a nonzero weight
MIN_RECENT_H = 40                # recency gate: distinct active alt-hours in the 2 months before the fold
MIN_COINS_XS = 8                 # per-hour min cross-section for a neutralization regression / IC
N_RAND = 30                      # P-random weight-shuffle draws (the random-recent null band)
BOOT = 1000                      # day-block bootstrap resamples for the IC CI
SEED = 20260710
OUT = Path("data/derived/xsec_flow_step0")
DUCK_TMP = f"{A.SCRATCH}/duck_xs0"
FACTORS = A.FACTORS              # ("BTC","ETH") — hedges/factors only, never in the signal or the tilt


def _prev(m):                    # previous YYYYMM
    y, mo = divmod(m, 100); mo -= 1
    return (y - 1) * 100 + 12 if mo == 0 else y * 100 + mo


# ------------------------------------------------------------------ target: forward resid + per-hour rank ------
def fwd_sum(resid, h):
    """Y[t,c] = sum_{k=1..h} resid[t+k,c]  (strictly future; NaN if any of the h future hours is NaN)."""
    N, C = resid.shape
    Y = np.zeros((N, C))
    for k in range(1, h + 1):
        sh = np.full((N, C), np.nan); sh[:-k] = resid[k:]
        Y = Y + sh                                   # NaN propagates -> require the full forward window
    return Y


def xsec_rank(Y, alt_cols):
    """u[t,c] = rank_a(Y)/(n_a-1) - 0.5 across the ALT cross-section each hour (only alt cols; NaN elsewhere)."""
    N, C = Y.shape
    U = np.full((N, C), np.nan)
    ac = np.asarray(alt_cols)
    for t in range(N):
        row = Y[t, ac]; fin = np.isfinite(row)
        n = int(fin.sum())
        if n < 2: continue
        vals = row[fin]
        rank = np.argsort(np.argsort(vals)).astype(float)     # 0..n-1
        U[t, ac[fin]] = rank / (n - 1) - 0.5
    return U


def trailing_resid_mom(resid, w=W_REL):
    """LAGMOM[t,c] = sum resid[t-(w-1)..t]  (pure PAST, known at end of hour t) — the momentum control + rotation
    placebo score input."""
    Rz = np.where(np.isfinite(resid), resid, 0.0)
    cs = np.cumsum(Rz, axis=0)
    LAG = np.array(cs)
    LAG[w:] = cs[w:] - cs[:-w]
    return LAG


# ------------------------------------------------------------------ predictor: relative reallocation q --------
def build_q(wcode, r, s, N):
    """q_sim  = s - mean_{coins traded this hour}(s);   q_trail = s - mean_{trailing-24h traded rows}(s).
    Fully vectorized via a wallet*HSPAN+hour key (sorted); demeans over the wallet's TRADED set only (never the
    full universe — never imputes shorts a wallet never held)."""
    HSPAN = np.int64(N + 100)
    K = wcode.astype(np.int64) * HSPAN + r.astype(np.int64)
    order = np.argsort(K, kind="stable")
    Ks = K[order]; ss = s[order].astype(np.float64)
    w_s = wcode[order].astype(np.int64); r_s = r[order].astype(np.int64)
    # V-sim: exact (wallet,hour) group mean
    _, inv, cnt = np.unique(Ks, return_inverse=True, return_counts=True)
    gsum = np.bincount(inv, weights=ss)
    q_sim_s = ss - gsum[inv] / cnt[inv]
    # V-trail: trailing (r-24, r] window within the wallet (searchsorted on the globally-sorted key)
    thr = w_s * HSPAN + (r_s - (W_REL - 1))
    start = np.searchsorted(Ks, thr, side="left")
    csum = np.concatenate([[0.0], np.cumsum(ss)])
    idx = np.arange(len(ss))
    wsum = csum[idx + 1] - csum[start]; wcnt = (idx + 1) - start
    q_trail_s = ss - wsum / wcnt
    inv_order = np.empty_like(order); inv_order[order] = np.arange(len(order))
    return q_sim_s[inv_order], q_trail_s[inv_order]


# ------------------------------------------------------------------ per-hour cross-sectional residualization --
def residualize(Smat, ctrl, cell_r):
    """Residualize every column of Smat (cells x ncol) on [1, ctrl] within each hour (cell_r groups). ctrl is
    cells x k (NaN pre-filled to 0). Hours with < MIN_COINS_XS coins are only mean-centered."""
    out = np.array(Smat)
    for hr in np.unique(cell_r):
        m = cell_r == hr; nm = int(m.sum())
        if nm < MIN_COINS_XS:
            out[m] = Smat[m] - Smat[m].mean(0); continue
        X = np.column_stack([np.ones(nm), ctrl[m]]) if ctrl is not None else np.ones((nm, 1))
        beta, _, _, _ = np.linalg.lstsq(X, Smat[m], rcond=None)
        out[m] = Smat[m] - X @ beta
    return out


def day_block_ci(days, sn, u, n=BOOT, seed=1):
    rng = np.random.default_rng(seed); ud = np.unique(days)
    loc = {d: np.nonzero(days == d)[0] for d in ud}; st = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        sel = np.concatenate([loc[ud[p]] for p in pick])
        v = A._spear(sn[sel], u[sel])
        if np.isfinite(v): st.append(v)
    s = np.array(st)
    return (np.percentile(s, [2.5, 97.5]) if len(s) > 10 else (np.nan, np.nan))


# ------------------------------------------------------------------ one horizon: WF folds -> per-cell S -------
def run_horizon(h, wcode, ccode, r, mth, q, U_h, LAG_ac, nW, folds, first_row, controls, do_placebos, seed=0,
                topk_by_w=None):
    """Walk-forward: score+shrink weights on TRAIN (with h-embargo), build S on the held-out month, plus the two
    placebos. Returns per-cell arrays (r,ccode,day,u + Smat columns [informed, rot, rand_0..N_RAND-1])."""
    rng = np.random.default_rng(seed)
    u_row = U_h[r, ccode]                                   # forward rank for each flow row (NaN if no target)
    mom_row = LAG_ac[r, ccode]                              # lagged residual momentum for each row (past)
    n_alt = U_h.shape[1]
    cells = {"r": [], "c": [], "u": [], "S": []}
    for m in folds:
        ft = first_row[m]
        # recency gate: eligible = active >= MIN_RECENT_H distinct alt-hours in the 2 months before the fold
        r1, r2 = _prev(_prev(m)), _prev(m)
        rec = np.isin(mth, (r1, r2))
        kk = np.unique(wcode[rec].astype(np.int64) * (U_h.shape[0] + 100) + r[rec].astype(np.int64))
        elig_w = np.bincount((kk // (U_h.shape[0] + 100)).astype(np.int64), minlength=nW)
        elig = elig_w >= MIN_RECENT_H
        # TRAIN score with h-embargo: drop train rows whose forward window reaches the test seam (r+h >= ft)
        tr = (mth < m) & (r < (ft - h)) & np.isfinite(u_row)
        wt, ut, qt, mt = wcode[tr], u_row[tr], q[tr], mom_row[tr]
        n_i = np.bincount(wt, minlength=nW).astype(float)
        g = np.bincount(wt, weights=qt * ut, minlength=nW) / np.where(n_i > 0, n_i, 1)
        lam = np.median(n_i[n_i > 0]) if (n_i > 0).any() else 1.0
        theta = g * n_i / (n_i + lam)
        W = np.where((n_i >= MIN_TRAIN_OBS) & elig, np.maximum(0.0, theta), 0.0)
        if topk_by_w is not None:                     # POLLABILITY: keep only the top-K wallets by skill weight
            pos = np.nonzero(W > 0)[0]
            if len(pos) > topk_by_w:
                cut = pos[np.argsort(W[pos])[::-1][:topk_by_w]]
                keepmask = np.zeros(nW, bool); keepmask[cut] = True
                W = np.where(keepmask, W, 0.0)
        # P-rotation weights: same shrink recipe, scored on alignment with LAGGED residual momentum (pure past)
        g_rot = np.bincount(wt, weights=qt * mt, minlength=nW) / np.where(n_i > 0, n_i, 1)
        theta_rot = g_rot * n_i / (n_i + lam)
        W_rot = np.where((n_i >= MIN_TRAIN_OBS) & elig, np.maximum(0.0, theta_rot), 0.0)
        # TEST month: aggregate weighted q to (coin,hour) cells
        te = (mth == m) & np.isfinite(u_row)
        if not te.any(): continue
        wte, cte, rte, qte = wcode[te], ccode[te], r[te], q[te]
        key = rte.astype(np.int64) * n_alt + cte.astype(np.int64)
        ukey, uinv = np.unique(key, return_inverse=True)
        cr = (ukey // n_alt).astype(np.int64); cc = (ukey % n_alt).astype(np.int64)
        def agg(wv): return np.bincount(uinv, weights=wv[wte] * qte, minlength=len(ukey))
        S_inf = agg(W); S_rot = agg(W_rot)
        cols = [S_inf, S_rot]
        if do_placebos:
            eidx = np.nonzero(elig)[0]; wpos = W[eidx]        # P-random: shuffle the skill weights among eligibles
            for _ in range(N_RAND):
                Wp = np.zeros(nW); Wp[eidx] = wpos[rng.permutation(len(eidx))]
                cols.append(agg(Wp))
        else:
            for _ in range(N_RAND): cols.append(np.zeros(len(ukey)))
        cells["r"].append(cr); cells["c"].append(cc)
        cells["u"].append(U_h[cr, cc])
        cells["S"].append(np.column_stack(cols))
        _log(f"  h={h} fold {m}: elig {int(elig.sum()):,}  W>0 {int((W>0).sum()):,}  cells {len(ukey):,}")
    R = np.concatenate(cells["r"]); C = np.concatenate(cells["c"]); Uc = np.concatenate(cells["u"])
    Smat = np.vstack(cells["S"])
    return R, C, Uc, Smat


def ic_ladder(R, C, Uc, Smat, hours, CROWD, LAG, FUND, do_placebos):
    """Report pooled OOS Spearman IC of neutralized S vs u at every rung (L0..L3), + day-block CI + t + placebos."""
    day = (hours[R] // 86400000).astype(np.int64)
    crowd = CROWD[R, C]; lag = LAG[R, C]; fund = FUND[R, C]
    for a in (crowd, lag, fund): a[~np.isfinite(a)] = 0.0
    rungs = {"L0_raw": None, "L1_crowd": crowd[:, None],
             "L2_crowd_mom": np.column_stack([crowd, lag]),
             "L3_crowd_mom_fund": np.column_stack([crowd, lag, fund])}
    out = {}
    for name, ctrl in rungs.items():
        Sn = residualize(Smat, ctrl, R)
        s_inf = Sn[:, 0]
        ic = A._spear(s_inf, Uc); n_eff = int((np.isfinite(s_inf) & np.isfinite(Uc)).sum())
        lo, hi = day_block_ci(day, s_inf, Uc)
        t = ic * np.sqrt(n_eff) if n_eff > 0 else np.nan
        res = {"informed_ic": float(ic), "ci95": [float(lo), float(hi)],
               "t_vs_zero": float(t), "n_eff": n_eff}
        if do_placebos:
            rot_ic = A._spear(Sn[:, 1], Uc)
            rnd = np.array([A._spear(Sn[:, 2 + j], Uc) for j in range(N_RAND)])
            res.update({"rotation_ic": float(rot_ic),
                        "p_random_mean": float(np.nanmean(rnd)), "p_random_std": float(np.nanstd(rnd)),
                        "p_random_p95": float(np.nanpercentile(rnd, 95)),
                        "p_random_draws": [float(x) for x in rnd],
                        "beats_random": bool(ic > np.nanpercentile(rnd, 95)),
                        "beats_rotation": bool(ic > rot_ic)})
        out[name] = res
    return out, day


def per_fold_ic(R, C, Uc, Smat, hours, folds, first_row, CROWD, LAG):
    """L2-neutralized informed IC per held-out month (the load-bearing 'is it novelty?' rung)."""
    crowd = CROWD[R, C]; lag = LAG[R, C]
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    Sn = residualize(Smat, np.column_stack([crowd, lag]), R)[:, 0]
    hr = hours[R]; out = {}
    edges = sorted(folds)
    for i, m in enumerate(edges):
        lo = first_row_ms(first_row, m)
        hi = first_row_ms(first_row, edges[i + 1]) if i + 1 < len(edges) else hr.max() + 1
        sel = (hr >= lo) & (hr < hi)
        if sel.sum() < 50: out[str(m)] = None; continue
        out[str(m)] = float(A._spear(Sn[sel], Uc[sel]))
    return out


def first_row_ms(first_row, m):  # ms of the first test hour of month m
    return first_row["_ms"][m]


# ------------------------------------------------------------------ effective-N (top-weight dedup caveat) -----
def effective_n(wcode, ccode, r, q, W, hours, n_alt, topk=60, thresh=0.6):
    """Correlation-cluster the top-weighted wallets on their per-(coin,hour) q vectors; report an independent-
    cluster count (a simple greedy single-linkage on |corr|>thresh)."""
    top = np.argsort(-W)[:topk]; top = top[W[top] > 0]
    if len(top) < 2: return {"n_top": int(len(top)), "n_clusters": int(len(top))}
    tset = {int(w): i for i, w in enumerate(top)}
    sel = np.isin(wcode, top)
    ws, cs, rs, qs = wcode[sel], ccode[sel], r[sel], q[sel]
    key = rs.astype(np.int64) * n_alt + cs.astype(np.int64)
    ukey, uinv = np.unique(key, return_inverse=True)
    M = np.zeros((len(top), len(ukey)))
    for w, ki, qi in zip(ws, uinv, qs): M[tset[int(w)], ki] += qi
    M = M - M.mean(1, keepdims=True)
    nrm = np.sqrt((M * M).sum(1)); nrm[nrm == 0] = 1
    Cm = (M @ M.T) / np.outer(nrm, nrm)
    parent = list(range(len(top)))
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            if abs(Cm[i, j]) > thresh: parent[find(i)] = find(j)
    return {"n_top": int(len(top)), "n_clusters": int(len({find(i) for i in range(len(top))})),
            "corr_thresh": thresh}


# ------------------------------------------------------------------ MAIN --------------------------------------
def run():
    OUT.mkdir(parents=True, exist_ok=True); Path(DUCK_TMP).mkdir(parents=True, exist_ok=True)
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(FACTORS) + alts
    print(f"[1/6] universe @ {A.UNIV_FORMATION}: {len(alts)} alts (+ {FACTORS} factors, EXCLUDED from signal)")

    print("[2/6] residual panel (causal rolling betas) ...")
    panel = A.build_resid(con, coins)
    resid, hours, ci = panel["resid"], panel["hours"], panel["ci"]
    N, C = panel["N"], panel["C"]; hmin = int(hours[0])
    alt_names = [c for c in coins if c not in FACTORS]
    alt_cols = [ci[c] for c in alt_names]; n_alt = len(alt_cols)
    col_to_ac = {ci[c]: k for k, c in enumerate(alt_names)}     # full-coin col -> alt-index position
    _log(f"resid built ({N} hours, {n_alt} alts)")

    # targets: forward rank U per horizon; controls indexed on the ALT cross-section (N x n_alt)
    resid_alt = resid[:, alt_cols]
    LAG_full = trailing_resid_mom(resid)                        # lagged momentum on full coin grid
    LAG_ac = LAG_full[:, alt_cols]
    U = {}
    for h in HS:
        Y = fwd_sum(resid, h); U[h] = xsec_rank(Y, alt_cols)[:, alt_cols]
        _log(f"target rank u built for h={h}")

    print("[3/6] cohort tables (awb/aagg) ...")
    A.build_cohort_tables(con, coins)
    # crowd flow (aagg.allflow) + funding (asset_ctx) on the alt cross-section
    CROWD = np.full((N, n_alt), np.nan)
    ag = con.execute("SELECT coin, h, allflow FROM aagg WHERE coin NOT IN ('BTC','ETH')").fetchnumpy()
    ar = ((ag["h"].astype(np.int64) - hmin) // 3600000).astype(int)
    ok = (ar >= 0) & (ar < N)
    acx = np.array([col_to_ac.get(ci.get(str(c), -1), -1) for c in ag["coin"]])
    good = ok & (acx >= 0); CROWD[ar[good], acx[good]] = ag["allflow"].astype(float)[good]
    FUND = np.full((N, n_alt), np.nan)
    inlist = "('" + "','".join(alt_names) + "')"
    fd = con.execute(f"""SELECT coin, (ts-ts%3600000) h, arg_max(funding, ts) f FROM asset_ctx
        WHERE coin IN {inlist} GROUP BY coin, h""").fetchnumpy()
    fr = ((fd["h"].astype(np.int64) - hmin) // 3600000).astype(int); ok = (fr >= 0) & (fr < N)
    fcx = np.array([col_to_ac.get(ci.get(str(c), -1), -1) for c in fd["coin"]])
    good = ok & (fcx >= 0); FUND[fr[good], fcx[good]] = fd["f"].astype(float)[good]
    _log("controls (crowd, funding) built")

    # int-encoded flow rows (wallet/coin -> int in duck so numpy stays compact); ALT-only, size-blind sign(flow)
    print("[4/6] flow rows (int-encoded, alt-only) ...")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cid AS SELECT * FROM (VALUES
        {",".join(f"('{c}',{k})" for k, c in enumerate(alt_names))}) AS t(coin, ccode)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE wid AS
        SELECT wallet, (row_number() OVER (ORDER BY wallet)) - 1 AS wcode
        FROM (SELECT DISTINCT wallet FROM awb WHERE coin NOT IN ('BTC','ETH') AND flow<>0)""")
    rows = con.execute(f"""SELECT w.wcode, c.ccode, ((wb.h - {hmin})//3600000)::INT AS r, wb.mth,
               CASE WHEN wb.flow>0 THEN 1 WHEN wb.flow<0 THEN -1 ELSE 0 END AS s
        FROM awb wb JOIN wid w USING(wallet) JOIN cid c ON wb.coin=c.coin
        WHERE wb.flow<>0""").fetchnumpy()
    nW = int(con.execute("SELECT count(*) FROM wid").fetchone()[0])
    wcode = rows["wcode"].astype(np.int32); ccode = rows["ccode"].astype(np.int32)
    r = rows["r"].astype(np.int32); mth = rows["mth"].astype(np.int32); s = rows["s"].astype(np.int8)
    keep = (r >= 0) & (r < N); wcode, ccode, r, mth, s = wcode[keep], ccode[keep], r[keep], mth[keep], s[keep]
    del rows
    _log(f"flow rows: {len(s):,} over {nW:,} wallets")

    q_sim, q_trail = build_q(wcode, r, s.astype(np.float64), N)
    _log("q_sim / q_trail built")

    # folds: expanding train, single held-out month (need >=3 train + 2 recency months)
    months = sorted(set(int(x) for x in np.unique(mth)))
    folds = months[4:]
    first_row = {"_ms": {}}
    for m in folds:
        rr = r[mth == m]; first_row[m] = int(rr.min()); first_row["_ms"][m] = int(hours[rr.min()])
    print(f"[5/6] WF folds (held-out months): {folds}")

    results = {"config": {"horizons": list(HS), "W_rel": W_REL, "folds": folds, "n_wallets": nW,
                          "n_alts": n_alt, "min_recent_h": MIN_RECENT_H, "min_train_obs": MIN_TRAIN_OBS,
                          "universe_formation": A.UNIV_FORMATION}, "ladder": {}}
    qvars = {"Vsim": q_sim, "Vtrail": q_trail}
    for h in HS:
        for qn, qv in qvars.items():
            _log(f"=== horizon h={h}  q={qn} ===")
            R, Cc, Uc, Smat = run_horizon(h, wcode, ccode, r, mth, qv, U[h], LAG_ac, nW, folds,
                                          first_row, (CROWD, LAG_ac, FUND), do_placebos=True, seed=SEED)
            lad, _ = ic_ladder(R, Cc, Uc, Smat, hours, CROWD, LAG_ac, FUND, do_placebos=True)
            pf = per_fold_ic(R, Cc, Uc, Smat, hours, folds, first_row, CROWD, LAG_ac)
            results["ladder"][f"h{h}_{qn}"] = {"rungs": lad, "per_fold_L2": pf}
            print(f"\n  ---- OOS IC ladder  h={h}  q={qn} ----")
            for name, d in lad.items():
                extra = (f"| P-rand {d['p_random_mean']:+.4f}±{d['p_random_std']:.4f} "
                         f"(p95 {d['p_random_p95']:+.4f}) | P-rot {d['rotation_ic']:+.4f} "
                         f"| beats rand={d['beats_random']} rot={d['beats_rotation']}")
                print(f"    {name:20s} IC {d['informed_ic']:+.4f}  CI[{d['ci95'][0]:+.4f},{d['ci95'][1]:+.4f}]"
                      f"  t {d['t_vs_zero']:+.2f}  {extra}")
            print(f"    per-fold L2: " + "  ".join(f"{k}:{v:+.4f}" if v is not None else f"{k}:na"
                                                    for k, v in pf.items()))

    # effective-N caveat (top-weighted wallets of the h=24 Vsim final fold-style weights, recomputed on all train)
    tr_all = (mth < folds[-1]) & (r < (first_row[folds[-1]] - 24)) & np.isfinite(U[24][r, ccode])
    n_i = np.bincount(wcode[tr_all], minlength=nW).astype(float)
    g = np.bincount(wcode[tr_all], weights=q_sim[tr_all] * U[24][r, ccode][tr_all], minlength=nW) / np.where(n_i > 0, n_i, 1)
    lam = np.median(n_i[n_i > 0]); Wfull = np.where(n_i >= MIN_TRAIN_OBS, np.maximum(0.0, g * n_i / (n_i + lam)), 0.0)
    effn = effective_n(wcode, ccode, r, q_sim, Wfull, hours, n_alt)
    results["effective_n"] = effn
    print(f"\n  effective-N (top {effn['n_top']} weighted wallets): {effn['n_clusters']} independent clusters "
          f"(|corr|>{effn.get('corr_thresh')})")

    # ---------------- POSITIVE CONTROL: inject a synthetic cohort correlated with the forward target ----------
    print("[6/6] POSITIVE CONTROL — inject synthetic edge, confirm recovery (MDE) ...")
    pc = positive_control(wcode, ccode, r, mth, s, U[24], LAG_ac, nW, folds, first_row,
                          hours, CROWD, FUND, n_alt, N)
    results["positive_control"] = pc
    print(f"    injected {pc['n_synth']} synth wallets @ edge p={pc['edge_p']}: "
          f"L0 IC {pc['L0_ic']:+.4f} (t {pc['L0_t']:+.2f}) | L2 IC {pc['L2_ic']:+.4f} (t {pc['L2_t']:+.2f}) "
          f"-> recovered={pc['recovered']}")

    (OUT / "ic_ladder.json").write_text(json.dumps(results, indent=2))
    print(f"\nwrote {OUT}/ic_ladder.json")
    return results


def positive_control(wcode, ccode, r, mth, s, U24, LAG_ac, nW, folds, first_row, hours, CROWD, FUND, n_alt, N,
                     n_synth=250, edge_p=0.70, cover=0.35, seed=SEED + 7):
    """Inject synthetic wallets whose sign(flow) aligns with sign(u_target) with prob edge_p on a `cover` fraction
    of alt cells across ALL months, then run the FULL pipeline (V-sim). If the pipeline is not blind-by-construction
    it must recover a clearly-positive IC (MDE <= the injected edge)."""
    rng = np.random.default_rng(seed)
    su = np.sign(U24)                                     # forward target sign on the (hour, alt) grid
    aw, ac, ar, am, asg = [], [], [], [], []
    hrows = np.nonzero(np.isfinite(U24).any(1))[0]
    for k in range(n_synth):
        wc = nW + k
        picks = hrows[rng.random(len(hrows)) < cover]
        for hh in picks:
            cand = np.nonzero(np.isfinite(U24[hh]))[0]
            if len(cand) < 4: continue
            m = rng.random(len(cand)) < 0.5; cand = cand[m]                    # trade ~half the cross-section
            if len(cand) < 2: continue
            sign_true = su[hh, cand]
            flip = rng.random(len(cand)) >= edge_p
            sg = np.where(flip, -sign_true, sign_true); sg[sg == 0] = 1
            aw += [wc] * len(cand); ac += cand.tolist(); ar += [int(hh)] * len(cand)
            am += [int(_month_of(hours[hh]))] * len(cand); asg += sg.astype(int).tolist()
    aw = np.array(aw, np.int32); ac = np.array(ac, np.int32); ar = np.array(ar, np.int32)
    am = np.array(am, np.int32); asg = np.array(asg, np.int8)
    W2 = np.concatenate([wcode, aw]); C2 = np.concatenate([ccode, ac]); R2 = np.concatenate([r, ar])
    M2 = np.concatenate([mth, am]); S2 = np.concatenate([s, asg]); nW2 = nW + n_synth
    q2, _ = build_q(W2, R2, S2.astype(np.float64), N)
    Rc, Cc, Uc, Smat = run_horizon(24, W2, C2, R2, M2, q2, U24, LAG_ac, nW2, folds, first_row,
                                   (CROWD, LAG_ac, FUND), do_placebos=False, seed=seed)
    crowd = CROWD[Rc, Cc]; lag = LAG_ac[Rc, Cc]
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    S0 = residualize(Smat[:, :1], None, Rc)[:, 0]
    S2n = residualize(Smat[:, :1], np.column_stack([crowd, lag]), Rc)[:, 0]
    n_eff = int((np.isfinite(S0) & np.isfinite(Uc)).sum())
    ic0 = A._spear(S0, Uc); ic2 = A._spear(S2n, Uc)
    return {"n_synth": n_synth, "edge_p": edge_p, "cover": cover,
            "L0_ic": float(ic0), "L0_t": float(ic0 * np.sqrt(n_eff)),
            "L2_ic": float(ic2), "L2_t": float(ic2 * np.sqrt(n_eff)), "n_eff": n_eff,
            "recovered": bool(ic2 * np.sqrt(n_eff) > 3.0 and ic2 > 0.02)}


def _month_of(ms):
    import datetime as dt
    return int(dt.datetime.utcfromtimestamp(int(ms) / 1000).strftime("%Y%m"))


if __name__ == "__main__":
    run()
