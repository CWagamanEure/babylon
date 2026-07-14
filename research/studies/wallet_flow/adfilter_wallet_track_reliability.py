"""
adfilter_wallet_track_reliability — DYNAMIC per-wallet track-record as the precision (inverse-R) weight.

Swarm lens (audit/xsec_adaptive_filter_swarm/SCOPE.md): the xsec selection signal weights each wallet by a
STATIC, train-frozen skill weight W. The user's hypothesis: a trader's PAST RECORD should set the trust on
their vote, and a CAUSAL, rolling reliability may beat the frozen W. We test whether weighting S_a = Sum_w
trust_w * q by a dynamic reliability lifts the signal's FORWARD IC vs static W.

Replicates the full-pipeline load (kalman_swarm_perwallet.load): wcode, ccode, r, mth, q(=q_trail), U4(h=4),
LAG_ac, CROWD, nW, folds. Reliability of wallet w at hour t = causal rolling aggregate of that wallet's per-
vote forward score (q * u) over its votes whose outcome has ALREADY RESOLVED (embargo: a vote at t' is usable
only at t' + h). Two window flavours: EXPANDING (all past) and TRAILING (recent record only).

Trust schemes compared (same target U4, same cell universe each fold -> differences are purely the weight):
  A  static      trust = W                                (frozen skill weight; == run_horizon baseline)
  B  dyn_mean    trust = max(0, rel_mean)                  (recent forward-IC of the wallet's votes)
  B  dyn_hit     trust = max(0, 2*hitrate-1)               (recent sign-hit-rate, re-centred)
  B  dyn_open    dyn_mean but WITHOUT the train eligibility gate (recent record can ADD wallets W dropped)
  C  bayes       trust = max(0, shrink[(n_prior*g + n_rec*rel_mean)/(n_prior+n_rec)])   (prior W + evidence)
  D  gate        trust = W * 1[not recently cold]          (frozen weight, drop wallets whose record collapsed)

Diagnostics: pooled + per-fold + early/late L2-neutralised IC (Spearman of S vs forward-resid rank), month-
block sign test, head-to-head per-fold (dynamic - static), a DIRECT recent-vs-frozen predictor test
(Spearman of each vote's realised forward score against its recent reliability vs against its frozen W), and a
skill-rotation check (corr of recent reliability with the frozen skill).  CAUSAL throughout; embargo respected.

    PYTHONPATH=/Users/corywagamaneure/bablyon .venv/bin/python -m research.studies.wallet_flow.adfilter_wallet_track_reliability
"""
from __future__ import annotations
import time, functools, json, warnings
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")

from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import kalman_swarm_perwallet as KP

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

H = KP.H_TRAIN                       # forward horizon of U4 (=4) -> embargo of the reliability outcome
MIN_REL = 8                          # min RESOLVED recent votes before a wallet earns a dynamic trust
PRIOR_CAP = 40                       # Bayesian prior strength (pseudo-obs) for the frozen-W prior in scheme C
OUT = Path("data/derived/xsec_adfilter_walletrack"); OUT.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------- causal per-wallet reliability -------------
def reliability(wcode, r, score, contrib, N, h, W_win):
    """For every flow row i: rolling aggregate of `score` over the SAME wallet's votes whose outcome has
    resolved by hour r_i - h (embargo) and lie within the trailing W_win hours. `contrib` masks rows with a
    finite outcome (only resolved votes count). Fully vectorised via a wallet*BIG+hour key + searchsorted.
    Returns (rel_mean, rel_cnt) aligned to the input row order. Window (r-h-W_win, r-h]."""
    BIG = np.int64(2 * N + 100)                                   # > maxhour + window span => wallet-disjoint keys
    keys = wcode.astype(np.int64) * BIG + r.astype(np.int64)
    order = np.argsort(keys, kind="stable")
    ks = keys[order]
    cs_val = np.concatenate([[0.0], np.cumsum((score * contrib)[order].astype(np.float64))])
    cs_cnt = np.concatenate([[0.0], np.cumsum(contrib[order].astype(np.float64))])
    up = wcode.astype(np.int64) * BIG + (r.astype(np.int64) - h)          # outcomes resolved by r-h
    lo = wcode.astype(np.int64) * BIG + (r.astype(np.int64) - h - W_win)  # trailing-window lower edge
    iu = np.searchsorted(ks, up, side="right")
    il = np.searchsorted(ks, lo, side="right")
    wsum = cs_val[iu] - cs_val[il]; wcnt = cs_cnt[iu] - cs_cnt[il]
    rel = wsum / np.where(wcnt > 0, wcnt, 1.0)
    return rel, wcnt


# ----------------------------------------------------------------- per-fold static skill internals -----------
def fold_internals(D, m, h=H):
    """Exact run_horizon / KP.fold_weight skill weight for fold m PLUS the internals (train g, n, lambda, elig)
    that the Bayesian blend needs. Reproduces the frozen static W bit-for-bit."""
    wcode, r, mth, q, U4, nW = D["wcode"], D["r"], D["mth"], D["q"], D["U4"], D["nW"]
    u_row = U4[r, D["ccode"]]
    ft = D["first_row"][m]
    r1, r2 = S0._prev(S0._prev(m)), S0._prev(m)
    rec = np.isin(mth, (r1, r2)); Nk = U4.shape[0] + 100
    kk = np.unique(wcode[rec].astype(np.int64) * Nk + r[rec].astype(np.int64))
    elig_w = np.bincount((kk // Nk).astype(np.int64), minlength=nW)
    elig = elig_w >= S0.MIN_RECENT_H
    tr = (mth < m) & (r < (ft - h)) & np.isfinite(u_row)
    wt, ut, qt = wcode[tr], u_row[tr], q[tr]
    n_i = np.bincount(wt, minlength=nW).astype(float)
    g = np.bincount(wt, weights=qt * ut, minlength=nW) / np.where(n_i > 0, n_i, 1)
    lam = np.median(n_i[n_i > 0]) if (n_i > 0).any() else 1.0
    theta = g * n_i / (n_i + lam)
    elig_mask = (n_i >= S0.MIN_TRAIN_OBS) & elig
    W = np.where(elig_mask, np.maximum(0.0, theta), 0.0)
    return dict(n_i=n_i, g=g, lam=float(lam), elig_mask=elig_mask, W=W)


# ----------------------------------------------------------------- IC helpers --------------------------------
def l2_ic(R, C, S, U4, CROWD, LAG_ac, hours, panel_month, folds):
    """L2-neutralised (perp crowd, perp lag-mom) pooled Spearman IC of S vs forward rank, + day-block CI, +
    per-fold, + early/late aggregate. R,C,S are pooled cell arrays across folds."""
    u = U4[R, C]
    crowd = CROWD[R, C].copy(); lag = LAG_ac[R, C].copy()
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    s_inf = S0.residualize(S[:, None].astype(np.float64), np.column_stack([crowd, lag]), R)[:, 0]
    ok = np.isfinite(s_inf) & np.isfinite(u)
    day = (hours[R] // 86400000).astype(np.int64)
    ic = A._spear(s_inf[ok], u[ok]); lo, hi = S0.day_block_ci(day[ok], s_inf[ok], u[ok])
    cm = panel_month[R]; pf = {}
    for mm in sorted(folds):
        sel = (cm == mm) & ok
        pf[int(mm)] = float(A._spear(s_inf[sel], u[sel])) if sel.sum() >= 50 else None
    half = len(folds) // 2
    early_m, late_m = set(folds[:half]), set(folds[half:])
    esel = np.isin(cm, list(early_m)) & ok; lsel = np.isin(cm, list(late_m)) & ok
    return {"ic": float(ic), "ci95": [float(lo), float(hi)], "n_eff": int(ok.sum()),
            "per_fold": pf, "early_ic": float(A._spear(s_inf[esel], u[esel])),
            "late_ic": float(A._spear(s_inf[lsel], u[lsel])),
            "sign_test": ADJ.sign_test([pf[m] for m in sorted(pf)]),
            "_s_inf": s_inf, "_ok": ok, "_u": u}


# ----------------------------------------------------------------- MAIN --------------------------------------
def run():
    D = KP.load(); _log("loaded panel + fills (full pipeline)")
    wcode, ccode, r, mth = D["wcode"], D["ccode"], D["r"], D["mth"]
    q, U4, N, n_alt = D["q"], D["U4"], D["N"], D["n_alt"]
    CROWD, LAG_ac, hours, panel_month = D["CROWD"], D["LAG_ac"], D["hours"], D["panel_month"]
    folds = D["folds"]

    # per-vote realised forward score (causal outcome, resolves at r+H); contrib = only resolved votes count
    u_row = U4[r, ccode]
    finite = np.isfinite(u_row)
    score = np.where(finite, q * u_row, 0.0)          # continuous IC-style per-vote score
    hit = np.where(finite, np.sign(q * u_row), 0.0)   # sign-hit in {-1,0,+1} -> mean = 2*hitrate-1
    contrib = finite.astype(np.float64)
    _log(f"rows {len(r):,}  resolved votes {int(finite.sum()):,}  wallets {D['nW']:,}")

    # two reliability windows: EXPANDING (all past) and TRAILING 30d (recent record = the hypothesis)
    WINDOWS = {"expand": 10 * N, "trail30d": 24 * 30, "trail7d": 24 * 7}
    REL = {}
    for wn, ww in WINDOWS.items():
        rm, rc = reliability(wcode, r, score, contrib, N, H, ww)
        rh, _ = reliability(wcode, r, hit, contrib, N, H, ww)
        REL[wn] = {"mean": rm, "hit": rh, "cnt": rc}
        _log(f"reliability[{wn}] built  (median resolved-cnt on votes = {np.median(rc[finite]):.0f})")

    # ---------------- build cells once per fold; compute S per scheme (shared cell universe) ----------------
    def eval_window(wn):
        rel_mean, rel_hit, rel_cnt = REL[wn]["mean"], REL[wn]["hit"], REL[wn]["cnt"]
        schemes = ["A_static", "B_dyn_mean", "B_dyn_hit", "B_dyn_open", "C_bayes", "D_gate"]
        acc = {s: {"r": [], "c": [], "S": []} for s in schemes}
        # recent-vs-frozen direct predictor test accumulators
        pred = {"score": [], "rel": [], "W": [], "g": [], "mth": []}
        for m in folds:
            FI = fold_internals(D, m)
            te = (mth == m) & finite
            wte, cte, rte, qte = wcode[te], ccode[te], r[te], q[te]
            rm, rh, rcn = rel_mean[te], rel_hit[te], rel_cnt[te]
            Wte = FI["W"][wte]; elig = FI["elig_mask"][wte].astype(np.float64)
            has = (rcn >= MIN_REL).astype(np.float64)
            # scheme trusts
            t_static = Wte
            t_mean = elig * has * np.maximum(0.0, rm)
            t_hit = elig * has * np.maximum(0.0, rh)
            t_open = has * np.maximum(0.0, rm)
            n_prior = np.minimum(FI["n_i"][wte], PRIOR_CAP); g_te = FI["g"][wte]
            post = (n_prior * g_te + rcn * rm) / np.where((n_prior + rcn) > 0, n_prior + rcn, 1.0)
            theta_post = post * (n_prior + rcn) / (n_prior + rcn + FI["lam"])
            t_bayes = elig * np.maximum(0.0, theta_post)
            cold = (rcn >= MIN_REL) & (rm <= 0.0)
            t_gate = Wte * np.where(cold, 0.0, 1.0)
            trusts = {"A_static": t_static, "B_dyn_mean": t_mean, "B_dyn_hit": t_hit,
                      "B_dyn_open": t_open, "C_bayes": t_bayes, "D_gate": t_gate}
            key = rte.astype(np.int64) * n_alt + cte.astype(np.int64)
            ukey, uinv = np.unique(key, return_inverse=True)
            cr = (ukey // n_alt).astype(np.int64); cc = (ukey % n_alt).astype(np.int64)
            for s in schemes:
                Ss = np.bincount(uinv, weights=trusts[s] * qte, minlength=len(ukey))
                acc[s]["r"].append(cr); acc[s]["c"].append(cc); acc[s]["S"].append(Ss)
            # predictor test: only over the eligible universe (fair recent-vs-frozen comparison)
            pm = FI["elig_mask"][wte] & (rcn >= MIN_REL)
            pred["score"].append((qte * u_row[te])[pm]); pred["rel"].append(rm[pm])
            pred["W"].append(Wte[pm]); pred["g"].append(g_te[pm]); pred["mth"].append(np.full(int(pm.sum()), m))
        res = {}
        for s in schemes:
            R = np.concatenate(acc[s]["r"]); C = np.concatenate(acc[s]["c"]); S = np.concatenate(acc[s]["S"])
            res[s] = l2_ic(R, C, S, U4, CROWD, LAG_ac, hours, panel_month, folds)
        # head-to-head per-fold dynamic - static
        for s in schemes:
            if s == "A_static": continue
            diff = {m: (res[s]["per_fold"][m] - res["A_static"]["per_fold"][m])
                    if (res[s]["per_fold"][m] is not None and res["A_static"]["per_fold"][m] is not None) else None
                    for m in sorted(folds)}
            res[s]["vs_static_perfold"] = {int(k): (float(v) if v is not None else None) for k, v in diff.items()}
            res[s]["vs_static_sign"] = ADJ.sign_test([v for v in diff.values()])
        # direct recent-vs-frozen predictor test
        sc = np.concatenate(pred["score"]); rl = np.concatenate(pred["rel"])
        Wv = np.concatenate(pred["W"]); gv = np.concatenate(pred["g"]); pmth = np.concatenate(pred["mth"])
        ok = np.isfinite(sc)
        predtest = {"n": int(ok.sum()),
                    "ic_recent_vs_realized": float(A._spear(rl[ok], sc[ok])),
                    "ic_frozenW_vs_realized": float(A._spear(Wv[ok], sc[ok])),
                    "ic_frozeng_vs_realized": float(A._spear(gv[ok], sc[ok])),
                    "corr_recent_vs_frozeng": float(A._spear(rl[ok], gv[ok]))}
        pf_rec, pf_frz = {}, {}
        for m in sorted(folds):
            sm = (pmth == m) & ok
            if sm.sum() >= 200:
                pf_rec[int(m)] = float(A._spear(rl[sm], sc[sm])); pf_frz[int(m)] = float(A._spear(Wv[sm], sc[sm]))
        predtest["per_fold_recent"] = pf_rec; predtest["per_fold_frozenW"] = pf_frz
        predtest["recent_beats_frozen_folds"] = int(sum(1 for m in pf_rec if pf_rec[m] > pf_frz.get(m, -9)))
        predtest["n_folds"] = len(pf_rec)
        for s in schemes:  # drop bulky internals before json
            for k in ("_s_inf", "_ok", "_u"): res[s].pop(k, None)
        return {"schemes": res, "predictor_test": predtest}

    OUTALL = {"config": {"H_embargo": H, "MIN_REL": MIN_REL, "PRIOR_CAP": PRIOR_CAP, "windows": WINDOWS,
                         "folds": folds, "n_wallets": D["nW"], "n_alts": n_alt}, "by_window": {}}
    for wn in WINDOWS:
        _log(f"=== window {wn} ===")
        OUTALL["by_window"][wn] = eval_window(wn)
        _print_window(wn, OUTALL["by_window"][wn], folds)

    (OUT / "results.json").write_text(json.dumps(OUTALL, indent=2, default=float))
    _log(f"wrote {OUT/'results.json'}")
    return OUTALL


def _print_window(wn, W, folds):
    R = W["schemes"]
    print(f"\n============================== WINDOW = {wn} ==============================")
    print(f"  {'scheme':>12}  {'pooledIC':>9}  {'CI95':>18}  {'early':>7} {'late':>7}  {'sign':>6}  vs-static(sign)")
    base = R["A_static"]["ic"]
    for s in ("A_static", "B_dyn_mean", "B_dyn_hit", "B_dyn_open", "C_bayes", "D_gate"):
        d = R[s]; ci = d["ci95"]; st = d["sign_test"]
        vs = ""
        if s != "A_static":
            vst = d["vs_static_sign"]; delta = d["ic"] - base
            vs = f"  d{delta:+.4f} {vst['n_pos']}/{vst['n']}p={vst['p']}"
        star = "*" if ci[0] > 0 else (" ")
        print(f"  {s:>12}  {d['ic']:+.4f}{star}  [{ci[0]:+.4f},{ci[1]:+.4f}]  {d['early_ic']:+.4f} {d['late_ic']:+.4f}  "
              f"{st['n_pos']}/{st['n']}{vs}")
    pt = W["predictor_test"]
    print(f"  -- recent-vs-frozen predictor of a vote's realised forward score (n={pt['n']:,}) --")
    print(f"     IC(recent reliability -> realised)  {pt['ic_recent_vs_realized']:+.4f}")
    print(f"     IC(frozen W          -> realised)  {pt['ic_frozenW_vs_realized']:+.4f}")
    print(f"     IC(frozen g          -> realised)  {pt['ic_frozeng_vs_realized']:+.4f}")
    print(f"     corr(recent, frozen g) = {pt['corr_recent_vs_frozeng']:+.4f}   "
          f"recent beats frozen in {pt['recent_beats_frozen_folds']}/{pt['n_folds']} folds")


if __name__ == "__main__":
    run()
