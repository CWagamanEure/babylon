"""
vote_split_breadth — the steelman's scope probe on the vote_source_split powered negative: does maker-vote
dilution appear where it was mechanically predicted — THIN-BREADTH cells (few wallets voting)?

The full-panel paired delta (maker−all = −0.0003, CI [−0.0042,+0.0034]) averages ~171 votes/cell, where noise
dilution mathematically vanishes. The 4.5× alt-timing precedent lives at ~12 effective wallets. PRE-REGISTERED
one-sided prediction (steelman pass, 2026-07-11): if dilution is real anywhere, the paired maker−all IC delta
is positive and LARGEST in the bottom breadth tercile. EXPLORATORY (not a primary; scope-bounds the negative).

Reuses the wbx cache + frozen pipeline; do_placebos off (the placebo question is settled by the main run).
Also dumps the per-cell signals to cells.npz so future probes skip the pipeline.

    PYTHONPATH=/Users/corywagamaneure/bablyon .venv/bin/python -m research.studies.wallet_flow.vote_split_breadth
"""
from __future__ import annotations
import functools, json, time
from pathlib import Path

import numpy as np

from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow.vote_source_split import (
    CACHE, OUT, WBX, DUCK_TMP, H, load_rows, paired_day_boot, fold_t)

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

S0.N_RAND = 2                       # placebo cols unused here; keep run_horizon's zero-fill cheap


def run():
    cache = np.load(CACHE, allow_pickle=True)
    hours = cache["hours"].astype(np.int64); resid_alt = cache["resid_alt"].astype(np.float64)
    n_alt = int(cache["n_alt"]); N = len(hours); hmin = int(hours[0])
    folds = [int(x) for x in cache["folds"]]

    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    alt_names = [c for c in coins if c not in A.FACTORS]
    assert len(alt_names) == n_alt
    con.execute(f"CREATE OR REPLACE VIEW wbx AS SELECT * FROM read_parquet('{WBX}/month=*.parquet')")
    A.build_cohort_tables(con, coins)
    U4 = S0.xsec_rank(S0.fwd_sum(resid_alt, H), list(range(n_alt)))
    LAG24 = S0.trailing_resid_mom(resid_alt)
    CROWD = np.full((N, n_alt), np.nan)
    ag = con.execute("SELECT coin, h, allflow FROM aagg WHERE coin NOT IN ('BTC','ETH')").fetchnumpy()
    ar = ((ag["h"].astype(np.int64) - hmin) // 3600000).astype(int); ok = (ar >= 0) & (ar < N)
    aci = {c: k for k, c in enumerate(alt_names)}
    acx = np.array([aci.get(str(c), -1) for c in ag["coin"]])
    good = ok & (acx >= 0); CROWD[ar[good], acx[good]] = ag["allflow"].astype(float)[good]

    rows, nW = load_rows(con, alt_names, hmin, N)
    first_row = {"_ms": {}}
    for m in folds:
        rr = rows["r"][rows["mth"] == m]; first_row[m] = int(rr.min()); first_row["_ms"][m] = int(hours[rr.min()])
    _log(f"rows {len(rows['r']):,}")

    sig = {}
    keys_by_arm = {}
    for arm, scol in (("all", "sall"), ("maker", "smk"), ("taker", "stk")):
        sel = rows[scol] != 0
        w_, c_, r_, m_ = rows["wcode"][sel], rows["ccode"][sel], rows["r"][sel], rows["mth"][sel]
        _qs, q_trail = ADJ.build_q_fixed(w_, r_, rows[scol][sel].astype(np.float64), N)
        R, Cc, Uc, Smat = S0.run_horizon(H, w_, c_, r_, m_, q_trail, U4, LAG24, nW, folds,
                                         first_row, None, do_placebos=False, seed=S0.SEED)
        crowd = CROWD[R, Cc].copy(); lag = LAG24[R, Cc].copy()
        for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
        s = S0.residualize(Smat[:, :1].astype(np.float64), np.column_stack([crowd, lag]), R)[:, 0]
        sig[arm] = (R, Cc, s, Uc)
        keys_by_arm[arm] = R.astype(np.int64) * n_alt + Cc.astype(np.int64)
        _log(f"arm {arm}: {len(R):,} cells, pooled IC {A._spear(s, Uc):+.4f}")

    # breadth = number of distinct voting wallets per (hour, coin) cell in the ALL arm (test months)
    sel = rows["sall"] != 0
    kk = rows["r"][sel].astype(np.int64) * n_alt + rows["ccode"][sel].astype(np.int64)
    uk, cnt = np.unique(kk, return_counts=True)
    Ra, Ca, sa, Ua = sig["all"]; key_all = keys_by_arm["all"]
    pos = np.searchsorted(uk, key_all)
    breadth = np.where((pos < len(uk)) & (uk[np.minimum(pos, len(uk) - 1)] == key_all),
                       cnt[np.minimum(pos, len(uk) - 1)], 0).astype(np.int64)
    # align maker cells to all cells (main run showed identical cell sets; verify)
    Rm, Cm, sm, Um = sig["maker"]; key_mk = keys_by_arm["maker"]
    om, oa = np.argsort(key_mk), np.argsort(key_all)
    assert len(key_mk) == len(key_all) and (key_mk[om] == key_all[oa]).all(), "cell sets differ"
    sm_al = np.empty_like(sm); sm_al[oa] = sm[om]        # maker signal aligned to all-arm cell order
    Rt, Ct, st, Ut = sig["taker"]; key_tk = keys_by_arm["taker"]
    ot = np.argsort(key_tk)
    st_al = np.empty_like(st); st_al[oa] = st[ot]

    np.savez(OUT / "cells.npz", R=Ra, Cc=Ca, u=Ua, s_all=sa, s_maker=sm_al, s_taker=st_al,
             breadth=breadth, hours=hours, folds=np.array(folds))
    _log(f"cells.npz written ({len(Ra):,} cells)")

    q33, q67 = np.percentile(breadth, [33.3, 66.7])
    strata = {"thin": breadth <= q33, "mid": (breadth > q33) & (breadth <= q67), "broad": breadth > q67}
    hr = hours[Ra]; edges = sorted(folds)
    out = {"breadth_cuts": [float(q33), float(q67)],
           "breadth_stats": {"mean": float(breadth.mean()), "median": float(np.median(breadth)),
                             "p10": float(np.percentile(breadth, 10)), "p90": float(np.percentile(breadth, 90))},
           "strata": {}}
    print(f"\nbreadth: median {np.median(breadth):.0f} votes/cell, terciles ≤{q33:.0f} / >{q67:.0f}")
    print(f"{'stratum':>7} {'n_cells':>8} {'IC_all':>8} {'IC_maker':>9} {'Δmk-all':>8} {'paired CI':>20} {'folds+':>7}")
    for name, mask in strata.items():
        ia = float(A._spear(sa[mask], Ua[mask])); im = float(A._spear(sm_al[mask], Ua[mask]))
        pbo = paired_day_boot((Ra[mask], sm_al[mask], Ua[mask]), (Ra[mask], sa[mask], Ua[mask]), hours, seed=21)
        pf = {}
        for i, m in enumerate(edges):
            lo = first_row["_ms"][m]; hi = first_row["_ms"][edges[i + 1]] if i + 1 < len(edges) else hr.max() + 1
            fs = mask & (hr >= lo) & (hr < hi)
            if fs.sum() >= 50:
                pf[str(m)] = float(A._spear(sm_al[fs], Ua[fs]) - A._spear(sa[fs], Ua[fs]))
        ft = fold_t(list(pf.values()))
        it = float(A._spear(st_al[mask], Ua[mask]))
        out["strata"][name] = {"n_cells": int(mask.sum()), "ic_all": ia, "ic_maker": im, "ic_taker": it,
                               "paired_boot": pbo, "per_fold_delta": pf, "fold_stats": ft}
        print(f"{name:>7} {int(mask.sum()):>8,} {ia:>+8.4f} {im:>+9.4f} {pbo['delta']:>+8.4f} "
              f"[{pbo['ci95'][0]:+.4f},{pbo['ci95'][1]:+.4f}] {ft['pos']}/{ft['n']} (sign_p {ft['sign_p']:.2f})")

    (OUT / "breadth_strata.json").write_text(json.dumps(out, indent=2, default=float))
    _log(f"wrote {OUT/'breadth_strata.json'}")
    return out


if __name__ == "__main__":
    run()
