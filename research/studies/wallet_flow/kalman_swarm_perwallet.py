"""
PER-WALLET pre-aggregation smoothing (the one lever the swarm left untested; needs the full pipeline).

Result 11's aggregate signal is too DENSE (43.5/45 alts every hour) for a staleness filter to bite. But each WALLET's
vote is SPARSE. This tests smoothing at the wallet level BEFORE aggregation: carry each wallet w's vote on alt a forward
across the hours w is quiet on a (up to `stale` hours; optional EMA blend α_w over w's successive votes), THEN aggregate
S_a = Σ_w W_w·(carried vote). Because the wallet support changes each hour, EMA does NOT commute with aggregation, so this
is genuinely distinct from the aggregate α≈0.9 denoise.

Reuses the EXACT skill-weight recipe (recency gate + h-embargo + shrink) from xsec_flow_step0.run_horizon and the
concentrated-book cost engine. Baseline (stale=0, α_w=1) MUST reproduce the raw book (maker_a30 +4.35, taker_smallclip +1.42).

    .venv/bin/python -m research.studies.wallet_flow.kalman_swarm_perwallet
"""
from __future__ import annotations
import time, json
from pathlib import Path
import numpy as np

from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)
H_TRAIN = 4; REB = 4
OUT = Path("data/derived/xsec_perwallet"); DUCK_TMP = f"{A.SCRATCH}/duck_xs_pw"
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")
# (label, stale_hours, alpha_w)  stale=0/α=1 == raw baseline; carry extends each wallet's vote forward
VARIANTS = [("raw_base", 0, 1.0), ("carry_s2", 2, 1.0), ("carry_s4", 4, 1.0), ("carry_s8", 8, 1.0),
            ("carry_s24", 24, 1.0), ("ema_s8_a0.6", 8, 0.6), ("ema_s24_a0.6", 24, 0.6)]


def load():
    OUT.mkdir(parents=True, exist_ok=True); Path(DUCK_TMP).mkdir(parents=True, exist_ok=True)
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins)
    resid, hours, ci = panel["resid"], panel["hours"], panel["ci"]
    panel_month = panel["month"]; N = panel["N"]; hmin = int(hours[0])
    alt_names = [c for c in coins if c not in A.FACTORS]
    alt_cols = [ci[c] for c in alt_names]; n_alt = len(alt_cols)
    col_to_ac = {ci[c]: k for k, c in enumerate(alt_names)}
    LAG_ac = S0.trailing_resid_mom(resid)[:, alt_cols]
    resid_alt = resid[:, alt_cols].astype(np.float64)
    inlist = "('" + "','".join(alt_names) + "')"
    hs_rows = con.execute(f"""SELECT coin, median((impact_ask_px-impact_bid_px)/nullif(mid_px,0)*1e4/2.0) hs
        FROM asset_ctx WHERE coin IN {inlist} AND month>={CB.CLEAN_MIN} AND impact_ask_px>0 AND impact_bid_px>0
          AND mid_px>0 GROUP BY coin""").fetchall()
    hs_by = {c: float(h) for c, h in hs_rows}
    halfspread = {i: hs_by.get(alt_names[i], 3.25) for i in range(n_alt)}
    hs_default = float(np.median(list(hs_by.values())))
    A.build_cohort_tables(con, coins)
    CROWD = np.full((N, n_alt), np.nan)
    ag = con.execute("SELECT coin, h, allflow FROM aagg WHERE coin NOT IN ('BTC','ETH')").fetchnumpy()
    ar = ((ag["h"].astype(np.int64) - hmin) // 3600000).astype(int); ok = (ar >= 0) & (ar < N)
    acx = np.array([col_to_ac.get(ci.get(str(c), -1), -1) for c in ag["coin"]])
    good = ok & (acx >= 0); CROWD[ar[good], acx[good]] = ag["allflow"].astype(float)[good]
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cid AS SELECT * FROM (VALUES
        {",".join(f"('{c}',{k})" for k, c in enumerate(alt_names))}) AS t(coin, ccode)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE wid AS SELECT wallet,(row_number() OVER (ORDER BY wallet))-1 AS wcode
        FROM (SELECT DISTINCT wallet FROM awb WHERE coin NOT IN ('BTC','ETH') AND flow<>0)""")
    rows = con.execute(f"""SELECT w.wcode, c.ccode, ((wb.h-{hmin})//3600000)::INT AS r, wb.mth,
               CASE WHEN wb.flow>0 THEN 1 WHEN wb.flow<0 THEN -1 ELSE 0 END AS s
        FROM awb wb JOIN wid w USING(wallet) JOIN cid c ON wb.coin=c.coin WHERE wb.flow<>0""").fetchnumpy()
    nW = int(con.execute("SELECT count(*) FROM wid").fetchone()[0])
    wcode = rows["wcode"].astype(np.int32); ccode = rows["ccode"].astype(np.int32)
    r = rows["r"].astype(np.int32); mth = rows["mth"].astype(np.int32); s = rows["s"].astype(np.int8)
    keep = (r >= 0) & (r < N); wcode, ccode, r, mth, s = wcode[keep], ccode[keep], r[keep], mth[keep], s[keep]
    _q_sim, q_trail = ADJ.build_q_fixed(wcode, r, s.astype(np.float64), N)
    months = sorted(set(int(x) for x in np.unique(mth))); folds = months[4:]
    first_row = {"_ms": {}}
    for m in folds:
        rr = r[mth == m]; first_row[m] = int(rr.min()); first_row["_ms"][m] = int(hours[rr.min()])
    U4 = S0.xsec_rank(S0.fwd_sum(resid, H_TRAIN), alt_cols)[:, alt_cols]
    return dict(wcode=wcode, ccode=ccode, r=r, mth=mth, q=q_trail, U4=U4, LAG_ac=LAG_ac, nW=nW, N=N,
                folds=folds, first_row=first_row, CROWD=CROWD, resid_alt=resid_alt, hours=hours,
                panel_month=panel_month, halfspread=halfspread, hs_default=hs_default, n_alt=n_alt)


def fold_weight(D, m, h=H_TRAIN):
    """Exact run_horizon skill weight for fold m: recency gate + h-embargo + shrink. Returns W[nW]."""
    wcode, r, mth, q, U4, LAG_ac, nW = D["wcode"], D["r"], D["mth"], D["q"], D["U4"], D["LAG_ac"], D["nW"]
    u_row = U4[r, D["ccode"]]
    ft = D["first_row"][m]
    r1, r2 = S0._prev(S0._prev(m)), S0._prev(m)
    rec = np.isin(mth, (r1, r2))
    Nk = U4.shape[0] + 100
    kk = np.unique(wcode[rec].astype(np.int64) * Nk + r[rec].astype(np.int64))
    elig_w = np.bincount((kk // Nk).astype(np.int64), minlength=nW)
    elig = elig_w >= S0.MIN_RECENT_H
    tr = (mth < m) & (r < (ft - h)) & np.isfinite(u_row)
    wt, ut, qt = wcode[tr], u_row[tr], q[tr]
    n_i = np.bincount(wt, minlength=nW).astype(float)
    g = np.bincount(wt, weights=qt * ut, minlength=nW) / np.where(n_i > 0, n_i, 1)
    lam = np.median(n_i[n_i > 0]) if (n_i > 0).any() else 1.0
    theta = g * n_i / (n_i + lam)
    return np.where((n_i >= S0.MIN_TRAIN_OBS) & elig, np.maximum(0.0, theta), 0.0)


def carry_aggregate(D, m, W, stale, alpha_w):
    """Aggregate S_a over the fold's hours with each wallet's vote CARRIED forward up to `stale` hours (EMA α_w over a
    wallet's successive votes on the same alt). Returns dense S[N,n_alt] and a live-count[N,n_alt]. Vectorized range-add."""
    N, n_alt = D["N"], D["n_alt"]
    u_row = D["U4"][D["r"], D["ccode"]]
    te = (D["mth"] == m) & np.isfinite(u_row)
    wte, cte, rte, qte = D["wcode"][te], D["ccode"][te], D["r"][te], D["q"][te]
    Wte = W[wte]
    live = Wte > 0
    wte, cte, rte, qte, Wte = wte[live], cte[live], rte[live], qte[live], Wte[live]
    if len(wte) == 0:
        return None, None
    # sum q per (w,c,r) so each wallet-cell is one segment endpoint (matches run_horizon's per-cell q sum)
    key = (wte.astype(np.int64) * n_alt + cte.astype(np.int64)) * N + rte.astype(np.int64)
    uk, inv = np.unique(key, return_inverse=True)
    qsum = np.zeros(len(uk)); np.add.at(qsum, inv, qte)
    w_u = (uk // (n_alt * N)).astype(np.int64)
    c_u = ((uk // N) % n_alt).astype(np.int64)
    r_u = (uk % N).astype(np.int64)
    Wc = W[w_u]
    # sort by (w,c,r); segment end = next same-(w,c) trade or r+stale+1
    order = np.lexsort((r_u, c_u, w_u))
    w_s, c_s, r_s, q_s, W_s = w_u[order], c_u[order], r_u[order], qsum[order], Wc[order]
    grp = w_s * n_alt + c_s
    same_next = np.empty(len(grp), bool); same_next[-1] = False
    same_next[:-1] = grp[1:] == grp[:-1]
    next_r = np.empty(len(r_s), np.int64); next_r[:-1] = r_s[1:]; next_r[-1] = N
    seg_end = np.where(same_next, np.minimum(next_r, r_s + stale + 1), r_s + stale + 1)
    seg_end = np.minimum(seg_end, N)
    # EMA over a wallet's successive votes (α_w=1 => e_k=q_k, pure carry of latest vote)
    if alpha_w >= 1.0:
        e = q_s.copy()
    else:
        e = np.empty_like(q_s)
        prev = 0.0; prev_grp = -1
        for i in range(len(q_s)):
            if grp[i] != prev_grp:
                e[i] = q_s[i]; prev_grp = grp[i]
            else:
                e[i] = alpha_w * q_s[i] + (1.0 - alpha_w) * prev
            prev = e[i]
    val = W_s * e
    DELTA = np.zeros((N, n_alt)); ONES = np.zeros((N, n_alt))
    inr = seg_end < N                                          # range-add via diff array: +val at start, -val at end
    np.add.at(DELTA, (r_s, c_s), val)
    np.add.at(DELTA, (seg_end[inr], c_s[inr]), -val[inr])
    liveW = (W_s > 0).astype(float)
    np.add.at(ONES, (r_s, c_s), liveW)
    np.add.at(ONES, (seg_end[inr], c_s[inr]), -liveW[inr])
    S = np.cumsum(DELTA, axis=0); LIVE = np.cumsum(ONES, axis=0)
    return S, LIVE


def eval_variant(D, stale, alpha_w):
    cells_r, cells_c, cells_S = [], [], []
    folds = D["folds"]
    for fi, m in enumerate(folds):
        W = fold_weight(D, m)
        S, LIVE = carry_aggregate(D, m, W, stale, alpha_w)
        if S is None:
            continue
        lo = D["first_row"][m]
        hi = D["first_row"][folds[fi + 1]] if fi + 1 < len(folds) else D["N"]
        hh = np.arange(lo, min(hi, D["N"]))
        for c in range(D["n_alt"]):
            live = LIVE[hh, c] > 1e-12
            u = D["U4"][hh, c]
            sel = live & np.isfinite(u)
            if sel.any():
                hs = hh[sel]
                cells_r.append(hs); cells_c.append(np.full(len(hs), c)); cells_S.append(S[hs, c])
    R = np.concatenate(cells_r); C = np.concatenate(cells_c); Smat = np.concatenate(cells_S)[:, None]
    crowd = D["CROWD"][R, C].copy(); lag = D["LAG_ac"][R, C].copy()
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    s_inf = S0.residualize(Smat.astype(np.float64), np.column_stack([crowd, lag]), R)[:, 0]
    # book (pooled all-regime, reb4) via CB engine
    xs = {}; hours = D["hours"]; pm = D["panel_month"]; n_alt = D["n_alt"]
    for i in range(len(R)):
        if not np.isfinite(s_inf[i]): continue
        t = int(R[i]); xs.setdefault(t, ([], [])); xs[t][0].append(int(C[i])); xs[t][1].append(s_inf[i])
    xs_arr = {t: (np.array(v[0]), np.array(v[1])) for t, v in xs.items()}
    all_hours = np.array(sorted(xs_arr), dtype=np.int64)[::REB]
    FVr = S0.fwd_sum(D["resid_alt"], REB)
    fvb = {int(t): {int(a): float(FVr[int(t), a]) * 1e4 for a in xs_arr[int(t)][0]} for t in all_hours}
    full = set(range(n_alt)); elig = {int(t): full for t in all_hours}
    sim = CB.simulate_raw(all_hours, xs_arr, fvb, D["halfspread"], D["hs_default"], 1, 0.10, 0.15, elig)
    hrs = sim["hr"].astype(np.int64); shm = np.array([int(pm[int(t)]) for t in hrs])
    out = {"gross": float((sim["gross"] / REB).mean()), "turn": float(sim["turn"].mean()),
           "n_cells": int(len(R)), "n_steps": int(len(hrs)), "sc": {}}
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in FOCUS: continue
        netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, D["hs_default"])
        ci = CB._dayblock_ci(netph, hrs, hours)
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        out["sc"][lab] = {"net": float(netph.mean()), "ci": ci,
                          "fp": int(sum(1 for v in pf.values() if v > 0)), "nf": len(pf)}
    return out


def run():
    D = load(); _log("loaded panel + fills")
    res = {}
    print(f"\n{'variant':>14} {'cells':>8} {'gross':>7} {'turn':>6}  " +
          "  ".join(f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>20}" for l in FOCUS))
    for lab, stale, aw in VARIANTS:
        e = eval_variant(D, stale, aw); res[lab] = {"stale": stale, "alpha_w": aw, **e}
        cols = []
        for l in FOCUS:
            sc = e["sc"][l]; loo, hi = sc["ci"]; star = "*" if loo > 0 else ("-" if hi < 0 else " ")
            cols.append(f"{sc['net']:+5.2f}[{loo:+4.1f},{hi:+4.1f}]{sc['fp']}/{sc['nf']}{star}")
        tag = "  <=BASE(must match raw)" if lab == "raw_base" else ""
        print(f"{lab:>14} {e['n_cells']:>8} {e['gross']:>+7.2f} {e['turn']:>6.2f}  " +
              "  ".join(f"{c:>20}" for c in cols) + tag)
    OUT.mkdir(parents=True, exist_ok=True); (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    _log(f"wrote {OUT/'results.json'}")
    print("\nBaseline raw_base must reproduce: maker_a30 ~+4.35, taker_smallclip ~+1.42 (pooled reb4).")


if __name__ == "__main__":
    run()
