"""
vote_source_split — is the xsec s_inf vote diluted by pooling MAKER and TAKER fills into one per-wallet flow?

Hypothesis (user, 2026-07-11): informed wallets express views patiently via resting limit orders; the current
vote s = sign(Σ flow_signed over BOTH crossed) may bury a maker sub-signal under taker noise. Precedent: the
alt-TIMING signal's maker-only split was 4.5× the combined IC (Result 9b lead #1, `alt_agg_maker_focus.py`).
This is the untested twin on the CROSS-SECTIONAL signal: rebuild the per-(wallet,coin,hour) vote from
maker-only (crossed=false) and taker-only (crossed=true) fills, push each through the IDENTICAL frozen
pipeline (V-trail q, WF shrunk-skill weights, recency gate, L2 ⊥[crowd,mom24] — `xsec_kalman.build_cache`
construction), and compare OOS.

Disciplines encoded:
  * ANCHOR: the "all" (both-sides) arm must reproduce the frozen cache s_inf cell-for-cell
    (data/derived/xsec_kalman/panel_cache.npz) AND the frozen book baseline (reb4 maker_a30 +3.17/hr,
    reb2 +5.37/hr phase-averaged) before any split number is read.
  * MATCHED-TREATMENT PLACEBOS: P-random (skill weights shuffled among eligibles) and P-rotation are built
    from the SAME arm's votes — a maker-only vote is mechanically contrarian (your resting bid fills on a
    down-move), and at the aggregate level all-wallet maker flow ≡ −OFI, so the placebos share that
    conditioning; informed-maker must beat random-maker, not zero.
  * FILL-MECHANICS RUNG: beyond the canonical L2 (⊥crowd, ⊥mom24), an L2f rung additionally residualizes on
    the CURRENT-hour resid + trailing-4h move — the horizon where passive-fill mechanics live. A maker "win"
    that dies at L2f is the reversal artifact, not information.
  * Fold-clustered inference (7 held-out months), day-block bootstrap CI, per-fold sign; phase-averaged books.

Stats-audit upgrades (2026-07-11 audit, findings F1-F6 — all encoded):
  * PRE-DECLARED PRIMARIES (Bonferroni ×2, α=0.025 each): (P1) paired IC delta maker−all at L2/H=4;
    (P2) paired book delta reb4 maker_a30. Everything else (taker arm, L0/L1/L2f rung ICs, reb2, other cost
    scenarios, gap-lag) is EXPLORATORY and labeled so.
  * Placebo band at BOTH L2 and L2f (F1), N_RAND=200 with (1+nge)/(B+1) perm-p (F3).
  * N-MATCHED control arm (F2): the all-arm votes subsampled per (coin,hour) cell to the maker arm's vote
    count, re-run through the full pipeline (weights refit on the subsample) — isolates "maker selects the
    informative votes" from "fewer votes = more attenuation". Plus intersection-cell ICs.
  * PAIRED day-block bootstrap on the maker−all delta on common days (F4) → CI + MDE ≈ 2.8×boot-SE (F5);
    exact two-sided fold sign test (max-side) + df=6 t caveat.
  * GAP-LAG curve (mechanism): IC vs single future hour k∈{1,2,3,4,6,8} — mechanical reversal pays at k=1
    and collapses under a gap; information survives it.

    PYTHONPATH=/Users/corywagamaneure/bablyon .venv/bin/python -m research.studies.wallet_flow.vote_source_split
"""
from __future__ import annotations
import functools, json, time
from pathlib import Path

import numpy as np

from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow.ideation_tier1_eval import phase_avg

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

H = 4
CACHE = Path("data/derived/xsec_kalman/panel_cache.npz")
OUT = Path("data/derived/xsec_vote_split")
WBX = OUT / "wbx"
DUCK_TMP = f"{A.SCRATCH}/duck_votesplit"
ARMS = ("all", "maker", "taker")           # + "nmatch" (all-votes subsampled to maker per-cell counts), run after
GAP_KS = (1, 2, 3, 4, 6, 8)
NM_SEED = 20260711
S0.N_RAND = 200                            # F3: 30 draws under-resolve the placebo band; perm-p floor 1/201


# ------------------------------------------------------------------ data: crossed-split wallet buckets --------
def build_wbx(con, coins):
    """Per (wallet, coin, hour): flow split by crossed. fmk = maker (crossed=false), ftk = taker, ftot = both.
    Same grouping as alt_flow.build_cohort_tables/awb; single pass per month so ftot matches awb up to fp noise."""
    inlist = "('" + "','".join(coins) + "')"
    WBX.mkdir(parents=True, exist_ok=True)
    months = [int(r[0]) for r in con.execute("SELECT DISTINCT month FROM alt_flow ORDER BY month").fetchall()]
    for m in months:
        p = WBX / f"month={m}.parquet"
        if p.exists() and p.stat().st_size > 0: continue
        con.execute(f"""COPY (SELECT wallet, coin, (bucket - bucket%3600000) AS h, {m} AS mth,
               COALESCE(sum(flow_signed) FILTER (NOT crossed), 0) AS fmk,
               COALESCE(sum(flow_signed) FILTER (crossed), 0) AS ftk,
               sum(flow_signed) AS ftot
            FROM alt_flow WHERE month={m} AND coin IN {inlist}
            GROUP BY wallet, coin, h) TO '{p}' (FORMAT PARQUET)""")
        _log(f"wbx {m} written")
    con.execute(f"CREATE OR REPLACE VIEW wbx AS SELECT * FROM read_parquet('{WBX}/month=*.parquet')")
    nnull = con.execute(f"SELECT count(*) FILTER (crossed IS NULL) FROM alt_flow WHERE coin IN {inlist}").fetchone()[0]
    if nnull: print(f"    ⚠️ {nnull:,} alt_flow rows have crossed IS NULL (excluded from BOTH split arms)")


def load_rows(con, alt_names, hmin, N):
    """Int-encoded rows over the union of wallets with ANY nonzero flow (either side). Returns dict of arrays."""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cid AS SELECT * FROM (VALUES
        {",".join(f"('{c}',{k})" for k, c in enumerate(alt_names))}) AS t(coin, ccode)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE wid AS
        SELECT wallet, (row_number() OVER (ORDER BY wallet)) - 1 AS wcode
        FROM (SELECT DISTINCT wallet FROM wbx
              WHERE coin NOT IN ('BTC','ETH') AND (fmk<>0 OR ftk<>0 OR ftot<>0))""")
    rows = con.execute(f"""SELECT w.wcode, c.ccode, ((wb.h - {hmin})//3600000)::INT AS r, wb.mth,
               CASE WHEN wb.fmk>0 THEN 1 WHEN wb.fmk<0 THEN -1 ELSE 0 END AS smk,
               CASE WHEN wb.ftk>0 THEN 1 WHEN wb.ftk<0 THEN -1 ELSE 0 END AS stk,
               CASE WHEN wb.ftot>0 THEN 1 WHEN wb.ftot<0 THEN -1 ELSE 0 END AS sall
        FROM wbx wb JOIN wid w USING(wallet) JOIN cid c ON wb.coin=c.coin
        WHERE wb.fmk<>0 OR wb.ftk<>0 OR wb.ftot<>0""").fetchnumpy()
    nW = int(con.execute("SELECT count(*) FROM wid").fetchone()[0])
    d = dict(wcode=rows["wcode"].astype(np.int32), ccode=rows["ccode"].astype(np.int32),
             r=rows["r"].astype(np.int32), mth=rows["mth"].astype(np.int32),
             smk=rows["smk"].astype(np.int8), stk=rows["stk"].astype(np.int8), sall=rows["sall"].astype(np.int8))
    del rows
    keep = (d["r"] >= 0) & (d["r"] < N)
    return {k: v[keep] for k, v in d.items()}, nW


# ------------------------------------------------------------------ stats helpers ------------------------------
def sign_p(vals):
    """Exact two-sided fold sign test, max-side (a 1/7-positive lean is as significant as 6/7 — F4d)."""
    from math import comb
    v = [x for x in vals if np.isfinite(x)]; n = len(v); k = sum(1 for x in v if x > 0)
    if n == 0: return float("nan")
    kmax = max(k, n - k)
    return float(min(1.0, 2 * sum(comb(n, i) for i in range(kmax, n + 1)) / 2 ** n))


def fold_t(vals):
    v = np.array([x for x in vals if np.isfinite(x)], float)
    if len(v) < 2: return {"mean": float("nan"), "t": float("nan"), "t_p": float("nan"), "sign_p": float("nan"),
                           "n": int(len(v)), "pos": int((v > 0).sum())}
    sd = v.std(ddof=1)
    t = v.mean() / (sd / np.sqrt(len(v))) if sd > 0 else float("inf") * np.sign(v.mean() or 1)
    try:
        from scipy import stats as sps
        tp = float(2 * sps.t.sf(abs(t), len(v) - 1))
    except Exception:
        tp = float("nan")
    return {"mean": float(v.mean()), "t": float(t), "t_p": tp, "sign_p": sign_p(vals),
            "n": int(len(v)), "pos": int((v > 0).sum())}


def paired_day_boot(cells_a, cells_b, hours, n=1000, seed=11):
    """Paired day-block bootstrap of IC_a − IC_b: same day-resample applied to both arms' cells (F4a).
    cells_* = (R, s, u). Returns delta point est, CI, boot SE, MDE≈2.8·SE."""
    rng = np.random.default_rng(seed)
    out = []
    da = (hours[cells_a[0]] // 86400000).astype(np.int64); db = (hours[cells_b[0]] // 86400000).astype(np.int64)
    ud = np.unique(np.concatenate([da, db]))
    la = {d: np.nonzero(da == d)[0] for d in ud}; lb = {d: np.nonzero(db == d)[0] for d in ud}
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        ia = np.concatenate([la[ud[p]] for p in pick]); ib = np.concatenate([lb[ud[p]] for p in pick])
        va = A._spear(cells_a[1][ia], cells_a[2][ia]); vb = A._spear(cells_b[1][ib], cells_b[2][ib])
        if np.isfinite(va) and np.isfinite(vb): out.append(va - vb)
    s = np.array(out)
    pt = float(A._spear(cells_a[1], cells_a[2]) - A._spear(cells_b[1], cells_b[2]))
    return {"delta": pt, "ci95": [float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))],
            "boot_se": float(s.std(ddof=1)), "mde_2p8se": float(2.8 * s.std(ddof=1)), "n_boot": int(len(s))}


def nmatch_rows(rows, sel_all, sel_mk, n_alt, seed=NM_SEED):
    """F2 attenuation control: subsample the ALL-arm rows so every (r,coin) cell has exactly the MAKER arm's
    vote count (min with available). Whole sample (train+test) so weight-fit sparsity is matched too."""
    rng = np.random.default_rng(seed)
    key_mk = rows["r"][sel_mk].astype(np.int64) * n_alt + rows["ccode"][sel_mk]
    uk, kc = np.unique(key_mk, return_counts=True)
    idx_all = np.nonzero(sel_all)[0]
    key_all = rows["r"][idx_all].astype(np.int64) * n_alt + rows["ccode"][idx_all]
    perm = rng.permutation(len(idx_all))
    kp = key_all[perm]
    order = np.argsort(kp, kind="stable")
    ks = kp[order]
    starts = np.r_[0, np.flatnonzero(np.diff(ks)) + 1]
    cum = np.arange(len(ks)) - np.repeat(starts, np.diff(np.r_[starts, len(ks)]))
    pos = np.searchsorted(uk, ks)
    quota = np.where((pos < len(uk)) & (uk[np.minimum(pos, len(uk) - 1)] == ks), kc[np.minimum(pos, len(uk) - 1)], 0)
    keep_sorted = cum < quota
    keep = np.zeros(len(rows["r"]), bool)
    keep[idx_all[perm[order[keep_sorted]]]] = True
    return keep


def eval_arm(R, Cc, Uc, Smat, hours, folds, first_ms, CROWD, LAG24, CUR, MOM4):
    """IC rungs for the informed column; canonical-L2 placebo comparison; per-fold L2 ICs."""
    crowd = CROWD[R, Cc].copy(); lag = LAG24[R, Cc].copy()
    cur = CUR[R, Cc].copy(); m4 = MOM4[R, Cc].copy()
    for a in (crowd, lag, cur, m4): a[~np.isfinite(a)] = 0.0
    day = (hours[R] // 86400000).astype(np.int64)
    rungs = {"L0_raw": None, "L1_crowd": crowd[:, None],
             "L2_crowd_mom24": np.column_stack([crowd, lag]),
             "L2f_fillmech": np.column_stack([crowd, lag, cur, m4])}
    out = {"rungs": {}}
    for name, ctrl in rungs.items():
        s = S0.residualize(Smat[:, :1].astype(np.float64), ctrl, R)[:, 0]
        ic = A._spear(s, Uc)
        lo, hi = S0.day_block_ci(day, s, Uc)
        out["rungs"][name] = {"ic": float(ic), "ci95": [float(lo), float(hi)],
                              "n_eff": int((np.isfinite(s) & np.isfinite(Uc)).sum())}
    # placebo band (rotation + N_RAND weight-shuffles) at BOTH the canonical L2 AND the fill-mechanics L2f (F1)
    s_inf = None
    for rung in ("L2_crowd_mom24", "L2f_fillmech"):
        Sn = S0.residualize(Smat.astype(np.float64), rungs[rung], R)
        if rung == "L2_crowd_mom24": s_inf = Sn[:, 0]
        rnd = np.array([A._spear(Sn[:, 2 + j], Uc) for j in range(S0.N_RAND)])
        ic = out["rungs"][rung]["ic"]
        nge = int(np.nansum(rnd >= ic))
        out.setdefault("placebo", {})[rung] = {
            "rotation_ic": float(A._spear(Sn[:, 1], Uc)),
            "rand_mean": float(np.nanmean(rnd)), "rand_sd": float(np.nanstd(rnd, ddof=1)),
            "rand_p95": float(np.nanpercentile(rnd, 95)),
            "z_vs_rand": float((ic - np.nanmean(rnd)) / np.nanstd(rnd, ddof=1)),
            "perm_p": float((1 + nge) / (S0.N_RAND + 1))}
        del Sn
    hr = hours[R]; edges = sorted(folds); pf = {}
    for i, m in enumerate(edges):
        lo = first_ms[m]; hi = first_ms[edges[i + 1]] if i + 1 < len(edges) else hr.max() + 1
        sel = (hr >= lo) & (hr < hi)
        pf[str(m)] = float(A._spear(s_inf[sel], Uc[sel])) if sel.sum() >= 50 else float("nan")
    out["per_fold_L2"] = pf; out["fold_stats"] = fold_t(list(pf.values()))
    return out, s_inf


# ------------------------------------------------------------------ MAIN ---------------------------------------
def run():
    OUT.mkdir(parents=True, exist_ok=True); Path(DUCK_TMP).mkdir(parents=True, exist_ok=True)
    cache = np.load(CACHE, allow_pickle=True)
    hours = cache["hours"].astype(np.int64); panel_month = cache["panel_month"].astype(np.int64)
    resid_alt = cache["resid_alt"].astype(np.float64); n_alt = int(cache["n_alt"]); N = len(hours)
    hs_arr = cache["hs_arr"].astype(np.float64); hs_def = float(cache["hs_default"])
    hs = {i: float(hs_arr[i]) for i in range(n_alt)}
    folds = [int(x) for x in cache["folds"]]
    hmin = int(hours[0])

    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    alt_names = [c for c in coins if c not in A.FACTORS]
    assert len(alt_names) == n_alt, f"universe mismatch: {len(alt_names)} vs cache {n_alt}"
    print(f"[1/6] universe: {n_alt} alts; folds {folds}")

    # targets/controls from the cache panel (identical by construction to build_cache: per-column ops)
    U4 = S0.xsec_rank(S0.fwd_sum(resid_alt, H), list(range(n_alt)))
    LAG24 = S0.trailing_resid_mom(resid_alt)
    MOM4 = S0.trailing_resid_mom(resid_alt, w=4)
    CUR = resid_alt
    UGAP = {k: ADJ.single_hour_rank(resid_alt, k, list(range(n_alt))) for k in GAP_KS}
    print("[2/6] crossed-split wallet buckets ...")
    build_wbx(con, coins)
    A.build_cohort_tables(con, coins)                      # aagg for CROWD (files exist -> just views)
    CROWD = np.full((N, n_alt), np.nan)
    ag = con.execute("SELECT coin, h, allflow FROM aagg WHERE coin NOT IN ('BTC','ETH')").fetchnumpy()
    ar = ((ag["h"].astype(np.int64) - hmin) // 3600000).astype(int); ok = (ar >= 0) & (ar < N)
    aci = {c: k for k, c in enumerate(alt_names)}
    acx = np.array([aci.get(str(c), -1) for c in ag["coin"]])
    good = ok & (acx >= 0); CROWD[ar[good], acx[good]] = ag["allflow"].astype(float)[good]

    print("[3/6] flow rows (union wallet space) ...")
    rows, nW = load_rows(con, alt_names, hmin, N)
    first_row = {"_ms": {}}
    for m in folds:
        rr = rows["r"][rows["mth"] == m]; first_row[m] = int(rr.min()); first_row["_ms"][m] = int(hours[rr.min()])
    _log(f"rows {len(rows['r']):,} | wallets {nW:,}")
    smap = {"all": "sall", "maker": "smk", "taker": "stk"}
    # vote-composition diagnostics
    both = (rows["smk"] != 0) & (rows["stk"] != 0)
    diag = {"rows_total": int(len(rows["r"])),
            "rows_maker": int((rows["smk"] != 0).sum()), "rows_taker": int((rows["stk"] != 0).sum()),
            "rows_both_sides_same_hour": int(both.sum()),
            "sign_agree_when_both": float((rows["smk"][both] == rows["stk"][both]).mean())}
    print(f"    maker rows {diag['rows_maker']:,} | taker rows {diag['rows_taker']:,} | "
          f"both-in-hour {diag['rows_both_sides_same_hour']:,} (sign-agree {diag['sign_agree_when_both']:.2f})")

    results = {"config": {"H": H, "folds": folds, "n_alt": n_alt, "nW": nW, "n_rand": S0.N_RAND,
                          "primaries": ["P1 paired IC delta maker-all @L2/H4",
                                        "P2 paired book delta reb4 maker_a30"],
                          "alpha_per_primary": 0.025}, "diag": diag, "arms": {}}
    S_by_arm, cells_by_arm = {}, {}
    sel_by_arm = {arm: rows[smap[arm]] != 0 for arm in ARMS}
    sel_by_arm["nmatch"] = None                                # filled after maker runs

    def run_one_arm(arm, sel, s_vals):
        w_, c_, r_, m_ = rows["wcode"][sel], rows["ccode"][sel], rows["r"][sel], rows["mth"][sel]
        _q_sim, q_trail = ADJ.build_q_fixed(w_, r_, s_vals, N)
        R, Cc, Uc, Smat = S0.run_horizon(H, w_, c_, r_, m_, q_trail, U4, LAG24, nW, folds,
                                         first_row, None, do_placebos=True, seed=S0.SEED)
        ev, s_inf = eval_arm(R, Cc, Uc, Smat, hours, folds, first_row["_ms"], CROWD, LAG24, CUR, MOM4)
        del Smat
        ev["n_cells"] = int(len(R)); ev["n_rows"] = int(sel.sum())
        # gap-lag curve (exploratory mechanism diagnostic): IC vs SINGLE future hour k
        ev["gap_lag"] = {f"k{k}": float(A._spear(s_inf, UGAP[k][R, Cc])) for k in GAP_KS}
        results["arms"][arm] = ev
        SIG = np.full((N, n_alt), np.nan); fin = np.isfinite(s_inf)
        SIG[R[fin], Cc[fin]] = s_inf[fin]
        S_by_arm[arm] = SIG; cells_by_arm[arm] = (R, Cc, s_inf, Uc)
        r2 = ev["rungs"]["L2_crowd_mom24"]; ft = ev["fold_stats"]
        pl2 = ev["placebo"]["L2_crowd_mom24"]; plf = ev["placebo"]["L2f_fillmech"]
        print(f"    L2 IC {r2['ic']:+.4f} CI[{r2['ci95'][0]:+.4f},{r2['ci95'][1]:+.4f}] cells {ev['n_cells']:,} "
              f"rows {ev['n_rows']:,} | folds {ft['pos']}/{ft['n']} t={ft['t']:+.2f} (p={ft['t_p']:.3f} "
              f"sign_p={ft['sign_p']:.3f})")
        print(f"    placebo L2: rand {pl2['rand_mean']:+.4f}±{pl2['rand_sd']:.4f} z={pl2['z_vs_rand']:+.2f} "
              f"perm_p={pl2['perm_p']:.4f} | L2f: z={plf['z_vs_rand']:+.2f} perm_p={plf['perm_p']:.4f}")
        print(f"    rungs: " + "  ".join(f"{k} {v['ic']:+.4f}" for k, v in ev["rungs"].items()))
        print(f"    gap-lag: " + "  ".join(f"k{k} {ev['gap_lag'][f'k{k}']:+.4f}" for k in GAP_KS))

    for arm in ARMS:
        print(f"[4/6] arm={arm} ...")
        run_one_arm(arm, sel_by_arm[arm], rows[smap[arm]][sel_by_arm[arm]].astype(np.float64))
    print("[4/6] arm=nmatch (all-votes subsampled to maker per-cell counts — F2 attenuation control) ...")
    sel_nm = nmatch_rows(rows, sel_by_arm["all"], sel_by_arm["maker"], n_alt)
    sel_by_arm["nmatch"] = sel_nm
    run_one_arm("nmatch", sel_nm, rows["sall"][sel_nm].astype(np.float64))

    # ---- ANCHOR (hard gate — F7): all-arm must reproduce the frozen cache s_inf ----
    print("[5/6] anchor checks ...")
    Ra, Ca, sa, Ua = cells_by_arm["all"]
    key_new = Ra.astype(np.int64) * n_alt + Ca.astype(np.int64)
    Rc0, Cc0 = cache["R"].astype(np.int64), cache["Cc"].astype(np.int64)
    key_old = Rc0 * n_alt + Cc0; s_old = cache["s_inf"].astype(np.float64)
    o_new, o_old = np.argsort(key_new), np.argsort(key_old)
    same_cells = len(key_new) == len(key_old) and bool((key_new[o_new] == key_old[o_old]).all())
    anchor_ok = False
    if same_cells:
        a, b = sa[o_new], s_old[o_old]
        m = np.isfinite(a) & np.isfinite(b)
        cc = float(np.corrcoef(a[m], b[m])[0, 1]) if m.sum() > 2 else float("nan")
        mx = float(np.max(np.abs(a[m] - b[m]))) if m.any() else float("nan")
        anchor_ok = np.isfinite(cc) and cc > 0.999           # float32 cache vs float64 rebuild → tiny Δ expected
        results["anchor"] = {"same_cells": True, "corr": cc, "max_abs_diff": mx, "passed": bool(anchor_ok)}
        print(f"    cells match ({len(key_new):,}); corr(s_inf, cache)={cc:.6f} max|Δ|={mx:.2e} "
              f"→ {'PASS' if anchor_ok else '⛔ FAIL'}")
    else:
        inter = np.intersect1d(key_new, key_old)
        results["anchor"] = {"same_cells": False, "n_new": int(len(key_new)), "n_old": int(len(key_old)),
                             "n_common": int(len(inter)), "passed": False}
        print(f"    ⛔ ANCHOR FAIL: cell sets differ — new {len(key_new):,} old {len(key_old):,} "
              f"common {len(inter):,}")
    if not anchor_ok:
        print("    ⛔ split numbers below are NOT trustworthy until the anchor is fixed (stamped in results.json)")

    # signal cross-correlations on common cells + INTERSECTION-cell ICs (F2)
    def cellmap(arm, idx):
        R, Cc, s, u = cells_by_arm[arm]
        return dict(zip((R.astype(np.int64) * n_alt + Cc.astype(np.int64)).tolist(), (s if idx == 0 else u).tolist()))
    cm = {arm: cellmap(arm, 0) for arm in cells_by_arm}
    xc = {}
    for a1, a2 in (("maker", "all"), ("taker", "all"), ("maker", "taker"), ("nmatch", "all")):
        ks = set(cm[a1]) & set(cm[a2])
        v1 = np.array([cm[a1][k] for k in ks]); v2 = np.array([cm[a2][k] for k in ks])
        mm = np.isfinite(v1) & np.isfinite(v2)
        xc[f"{a1}_vs_{a2}"] = {"n": int(mm.sum()), "corr": float(np.corrcoef(v1[mm], v2[mm])[0, 1])}
    results["signal_corr"] = xc
    print("    signal corr: " + "  ".join(f"{k} {v['corr']:+.3f} (n={v['n']:,})" for k, v in xc.items()))
    inter_keys = None
    Rm, Cm_, sm, Um = cells_by_arm["maker"]
    key_mk = Rm.astype(np.int64) * n_alt + Cm_.astype(np.int64)
    inter_keys = np.intersect1d(key_new, key_mk)
    in_all = np.isin(key_new, inter_keys); in_mk = np.isin(key_mk, inter_keys)
    ic_all_int = float(A._spear(sa[in_all], Ua[in_all])); ic_mk_int = float(A._spear(sm[in_mk], Um[in_mk]))
    results["intersection"] = {"n_cells": int(len(inter_keys)),
                               "ic_all": ic_all_int, "ic_maker": ic_mk_int,
                               "delta_maker_minus_all": float(ic_mk_int - ic_all_int)}
    print(f"    intersection cells {len(inter_keys):,}: IC all {ic_all_int:+.4f}  maker {ic_mk_int:+.4f}  "
          f"Δ {ic_mk_int-ic_all_int:+.4f}")

    # PAIRED day-block bootstrap on the deltas (F4a) — P1 primary is maker−all; nmatch−all reads attenuation
    pb = {}
    pb["maker_minus_all"] = paired_day_boot((Rm, sm, Um), (Ra, sa, Ua), hours)
    Rn, Cn, sn, Un = cells_by_arm["nmatch"]
    pb["nmatch_minus_all"] = paired_day_boot((Rn, sn, Un), (Ra, sa, Ua), hours, seed=12)
    pb["maker_minus_nmatch"] = paired_day_boot((Rm, sm, Um), (Rn, sn, Un), hours, seed=13)
    results["paired_boot"] = pb
    for k, v in pb.items():
        print(f"    paired-boot {k}: Δ {v['delta']:+.4f} CI[{v['ci95'][0]:+.4f},{v['ci95'][1]:+.4f}] "
              f"SE {v['boot_se']:.4f} (MDE≈{v['mde_2p8se']:.4f})")

    # ---- books (phase-averaged, frozen engine) ----
    print("[6/6] books (phase-avg) ...")
    FV = {r: S0.fwd_sum(resid_alt, r) * 1e4 for r in (2, 4)}
    for arm in list(ARMS) + ["nmatch"]:
        results["arms"][arm]["book"] = {}
        for reb in (4, 2):
            e = phase_avg(S_by_arm[arm], resid_alt, FV, hs, hs_def, reb, panel_month, hours, weight="equal")
            results["arms"][arm]["book"][f"reb{reb}"] = e
            if e is None: print(f"    {arm} reb{reb}: thin"); continue
            mk = e["sc"]["maker_a30"]; tk = e["sc"]["taker_small"]; lo, hi = mk["ci95"]
            print(f"    {arm:6s} reb{reb}  gross {e['gross_bp_hr']:+6.2f}/hr turn {e['turn']:.2f} | "
                  f"maker_a30 {mk['net_bp_hr']:+6.2f} CI[{lo:+.2f},{hi:+.2f}] {mk['folds_pos']}/{mk['n_folds']} "
                  f"SR {mk['sharpe']:+.2f} | taker_small {tk['net_bp_hr']:+6.2f} {tk['folds_pos']}/{tk['n_folds']}")

    # paired per-fold deltas, IC and maker_a30 net (exact sign p, df=6 t)
    results["paired"] = {}
    pf_all = results["arms"]["all"]["per_fold_L2"]
    for arm in ("maker", "taker", "nmatch"):
        pf_a = results["arms"][arm]["per_fold_L2"]
        d_ic = {k: pf_a[k] - pf_all[k] for k in pf_all if np.isfinite(pf_a[k]) and np.isfinite(pf_all[k])}
        results["paired"][f"ic_{arm}_minus_all"] = {"per_fold": d_ic, "stats": fold_t(list(d_ic.values()))}
    for reb in (4, 2):
        ba = results["arms"]["all"]["book"][f"reb{reb}"]; bm = results["arms"]["maker"]["book"][f"reb{reb}"]
        if ba and bm:
            fa = ba["sc"]["maker_a30"]["per_fold"]; fm = bm["sc"]["maker_a30"]["per_fold"]
            dd = {str(k): fm[k] - fa[k] for k in fa if k in fm}
            results["paired"][f"book_reb{reb}_maker_a30_delta"] = {"per_fold": dd, "stats": fold_t(list(dd.values()))}

    print("\n  ================ PRE-DECLARED PRIMARIES (Bonferroni ×2, α=0.025 each) ================")
    p1 = results["paired"]["ic_maker_minus_all"]["stats"]; pb1 = pb["maker_minus_all"]
    print(f"  P1 paired IC Δ(maker−all) @L2/H4: mean {p1['mean']:+.4f} t {p1['t']:+.2f} (df6 p={p1['t_p']:.3f}) "
          f"{p1['pos']}/{p1['n']} folds sign_p={p1['sign_p']:.3f} | paired-boot Δ {pb1['delta']:+.4f} "
          f"CI[{pb1['ci95'][0]:+.4f},{pb1['ci95'][1]:+.4f}] MDE {pb1['mde_2p8se']:.4f}")
    p2 = results["paired"].get("book_reb4_maker_a30_delta", {}).get("stats", {})
    if p2:
        print(f"  P2 paired book Δ(maker−all) reb4 maker_a30: mean {p2['mean']:+.2f} bp/hr t {p2['t']:+.2f} "
              f"(df6 p={p2['t_p']:.3f}) {p2['pos']}/{p2['n']} folds sign_p={p2['sign_p']:.3f}")
    if not anchor_ok:
        print("  ⛔ ANCHOR FAILED — primaries not readable")

    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=float))
    _log(f"wrote {OUT/'results.json'}")
    return results


if __name__ == "__main__":
    run()
