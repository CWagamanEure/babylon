"""
taker_posbuilding — the ONE unfalsified taker-revival escape (taker-revival swarm, 3 agents converged): is a genuinely SLOWER estimand
hiding in the position-BUILDING (accumulation) subset? The pooled signal is decay-locked (HL~4h → turnover ~1.3/reb → fee×turnover kills
the taker). Hypothesis: votes that OPEN/ADD to a position (new conviction) are slower & stickier than FLIP/TRIM churn, so the ADD-only
signal could have a longer HL + lower turnover → taker-viable. Distinct from EMA-smoothing (which lags the SAME fast signal 1:1).

Method: reconstruct each wallet's running position per coin via CAUSAL cumsum of signed flow (the notional proxy; no startPosition in the
awb tape). Classify each (w,c,hour) vote OPEN/ADD (sign(flow)==sign(prev position) or prev≈0) vs TRIM/FLIP. Build S_a from ADD-only votes
(same frozen skill weights, ⊥[crowd,mom]). Measure vs the FULL signal: (1) marginal-IC alpha-decay curve + half-life, (2) realized turnover,
(3) taker net (turnover-aware, phase-avg, per-fold sign, day-block CI). KILL CRITERION (pre-stated): break-even taker fee ≥ 2.4 at ≥5/7 folds.

    .venv/bin/python -m research.studies.wallet_flow.taker_posbuilding
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
from research.studies.wallet_flow import kalman_swarm_perwallet as PW
from research.studies.wallet_flow.ideation_tier1_eval import book, _dayblock_ci, _sign_test, _spear

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)
OUT = Path("data/derived/xsec_taker_posbuild")


def load_with_flow():
    """PW.load's structure + the per-(wcode,ccode,r) NET SIGNED FLOW magnitude (for causal position reconstruction)."""
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    Path(PW.DUCK_TMP).mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{PW.DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins)
    resid, hours = panel["resid"], panel["hours"]; panel_month = panel["month"]; N = panel["N"]; hmin = int(hours[0])
    alt_names = [c for c in coins if c not in A.FACTORS]
    alt_cols = [panel["ci"][c] for c in alt_names]; n_alt = len(alt_cols)
    col_to_ac = {panel["ci"][c]: k for k, c in enumerate(alt_names)}
    LAG_ac = S0.trailing_resid_mom(resid)[:, alt_cols]; resid_alt = resid[:, alt_cols].astype(np.float64)
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
    acx = np.array([col_to_ac.get(panel["ci"].get(str(c), -1), -1) for c in ag["coin"]])
    good = ok & (acx >= 0); CROWD[ar[good], acx[good]] = ag["allflow"].astype(float)[good]
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cid AS SELECT * FROM (VALUES
        {",".join(f"('{c}',{k})" for k, c in enumerate(alt_names))}) AS t(coin, ccode)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE wid AS SELECT wallet,(row_number() OVER (ORDER BY wallet))-1 AS wcode
        FROM (SELECT DISTINCT wallet FROM awb WHERE coin NOT IN ('BTC','ETH') AND flow<>0)""")
    # NET signed flow per (wcode,ccode,hour) — magnitude kept for position reconstruction
    rows = con.execute(f"""SELECT w.wcode, c.ccode, ((wb.h-{hmin})//3600000)::INT AS r, wb.mth,
               sum(wb.flow) AS flow
        FROM awb wb JOIN wid w USING(wallet) JOIN cid c ON wb.coin=c.coin WHERE wb.flow<>0
        GROUP BY 1,2,3,4""").fetchnumpy()
    nW = int(con.execute("SELECT count(*) FROM wid").fetchone()[0])
    wcode = rows["wcode"].astype(np.int32); ccode = rows["ccode"].astype(np.int32)
    r = rows["r"].astype(np.int32); mth = rows["mth"].astype(np.int32); flow = rows["flow"].astype(np.float64)
    keep = (r >= 0) & (r < N) & (flow != 0)
    wcode, ccode, r, mth, flow = wcode[keep], ccode[keep], r[keep], mth[keep], flow[keep]
    s = np.sign(flow).astype(np.int8)
    _q_sim, q_trail = ADJ.build_q_fixed(wcode, r, s.astype(np.float64), N)
    months = sorted(set(int(x) for x in np.unique(mth))); folds = months[4:]
    first_row = {"_ms": {}}
    for m in folds:
        rr = r[mth == m]; first_row[m] = int(rr.min()); first_row["_ms"][m] = int(hours[rr.min()])
    U4 = S0.xsec_rank(S0.fwd_sum(resid, PW.H_TRAIN), alt_cols)[:, alt_cols]
    return dict(wcode=wcode, ccode=ccode, r=r, mth=mth, flow=flow, s=s, q=q_trail, U4=U4, LAG_ac=LAG_ac, nW=nW, N=N,
                folds=folds, first_row=first_row, CROWD=CROWD, resid_alt=resid_alt, hours=hours,
                panel_month=panel_month, halfspread=halfspread, hs_default=hs_default, n_alt=n_alt)


def classify_addonly(D):
    """Per (wallet,coin), causal running position = cumsum of signed flow over hour order. ADD/OPEN if sign(flow_t)==sign(pos_{t-1})
    or pos_{t-1}≈0; else TRIM/FLIP. Returns boolean mask (len rows) True=ADD/OPEN."""
    w, c, r, f = D["wcode"].astype(np.int64), D["ccode"].astype(np.int64), D["r"].astype(np.int64), D["flow"]
    key = w * D["n_alt"] + c
    order = np.lexsort((r, key))                                  # sort by (w,c) then hour
    ks, rs, fs = key[order], r[order], f[order]
    # running position BEFORE this trade, within each (w,c) segment
    csum = np.cumsum(fs)                                          # inclusive
    prev_pos = csum - fs                                          # exclusive (position before this hour's flow)
    seg_start = np.empty(len(ks), bool); seg_start[0] = True; seg_start[1:] = ks[1:] != ks[:-1]
    # reset cumsum at each (w,c) boundary: subtract the running total at the last row of the previous segment
    base = np.zeros(len(ks))
    # compute per-segment offset: value of csum just before each segment start
    start_idx = np.nonzero(seg_start)[0]
    offset_at_start = np.concatenate([[0.0], csum[start_idx[1:] - 1]])
    seg_id = np.cumsum(seg_start) - 1
    prev_pos = prev_pos - offset_at_start[seg_id]                 # position before this trade, segment-local
    is_add = (np.abs(prev_pos) < 1e-9) | (np.sign(fs) == np.sign(prev_pos))
    mask = np.zeros(len(ks), bool); mask[order] = is_add
    return mask


def build_signal(D, add_mask=None):
    """Per-fold S_a = Σ W·q over cells (optionally ADD-only), residualized ⊥[crowd,mom] → dense s_inf[N,n_alt]."""
    N, n_alt = D["N"], D["n_alt"]; u_row = D["U4"][D["r"], D["ccode"]]
    Rl, Cl, Sl = [], [], []
    for m in D["folds"]:
        W = PW.fold_weight(D, m)
        te = (D["mth"] == m) & np.isfinite(u_row)
        if add_mask is not None: te = te & add_mask
        wte, cte, rte, qte = D["wcode"][te], D["ccode"][te], D["r"][te], D["q"][te]
        Wte = W[wte]; liv = Wte > 0
        wte, cte, rte, qte, Wte = wte[liv], cte[liv], rte[liv], qte[liv], Wte[liv]
        if len(wte) == 0: continue
        key = rte.astype(np.int64) * n_alt + cte.astype(np.int64)
        uk, inv = np.unique(key, return_inverse=True)
        S = np.zeros(len(uk)); np.add.at(S, inv, Wte * qte)
        Rl.append((uk // n_alt).astype(np.int64)); Cl.append((uk % n_alt).astype(np.int64)); Sl.append(S)
    R = np.concatenate(Rl); C = np.concatenate(Cl); S = np.concatenate(Sl)
    crowd = D["CROWD"][R, C].copy(); lag = D["LAG_ac"][R, C].copy()
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    s_inf = S0.residualize(S[:, None].astype(np.float64), np.column_stack([crowd, lag]), R)[:, 0]
    SIG = np.full((N, n_alt), np.nan); fin = np.isfinite(s_inf); SIG[R[fin], C[fin]] = s_inf[fin]
    return SIG


def decay_curve(SIG, resid_alt, n_alt, lags=(1, 2, 3, 4, 6, 8, 12, 24)):
    """Marginal IC(SIG_t, single-hour resid at t+k) across lags — the alpha-decay shape / half-life."""
    res = {}
    for k in lags:
        fwd = np.full_like(resid_alt, np.nan); fwd[:-k] = resid_alt[k:]
        res[k] = _spear(SIG.flatten(), S0.xsec_rank(fwd, list(range(n_alt))).flatten())
    return res


def taker_eval(SIG, D, tag):
    FV = {r: S0.fwd_sum(D["resid_alt"], r) * 1e4 for r in (4, 8, 12)}
    hs = D["halfspread"]; hs_def = D["hs_default"]; N = D["N"]; pm = D["panel_month"]; hours = D["hours"]
    rows = {}
    for reb in (4, 8, 12):
        pool = {"hr": [], "gross": [], "ntrade": [], "hs": [], "turn": []}
        for ph in range(reb):
            s = book(SIG, D["resid_alt"], FV[reb], hs, hs_def, reb, "equal", 0.10, 0.15, phase=ph)
            for kk in pool: pool[kk].extend(s[kk].tolist())
        P = {kk: np.array(v, float) for kk, v in pool.items()}
        if len(P["hr"]) < 8: continue
        hrs = P["hr"].astype(np.int64); shm = np.array([int(pm[t]) for t in hrs])
        cost = P["ntrade"] * 2.4 + P["hs"]                         # taker: top-tier fee + impact spread
        net = (P["gross"] - cost) / reb
        lo, hi = _dayblock_ci(net, hrs, hours)
        pf = {int(m): float(net[shm == m].mean()) for m in sorted(set(shm.tolist()))}
        st = _sign_test(list(pf.values()))
        g_hr = (P["gross"] / reb).mean(); turn = P["turn"].mean()
        be = float((P["gross"].mean() - P["hs"].mean()) / max(P["ntrade"].mean(), 1e-9))  # break-even fee/side (spread paid)
        rows[reb] = {"gross_hr": float(g_hr), "turn": float(turn), "net_hr": float(net.mean()), "ci95": [lo, hi],
                     "folds_pos": st["pos"], "n_folds": st["n"], "sign_p": st["p"], "break_even_fee": be}
        print(f"    [{tag}] reb{reb}: gross {g_hr:+.2f}/hr turn {turn:.2f}  taker net {net.mean():+.2f}/hr "
              f"CI[{lo:+.2f},{hi:+.2f}] {st['pos']}/{st['n']} p{st['p']:.2f}  BE-fee {be:+.2f}bp/side")
    return rows


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    D = load_with_flow(); _log(f"loaded {len(D['wcode']):,} cells, nW={D['nW']}")
    add_mask = classify_addonly(D)
    frac = add_mask.mean(); _log(f"ADD/OPEN fraction = {frac:.1%} of votes ({add_mask.sum():,}/{len(add_mask):,})")
    SIG_full = build_signal(D, None); _log("full signal built")
    SIG_add = build_signal(D, add_mask); _log("ADD-only signal built")
    n_alt = D["n_alt"]
    print("\n== ALPHA-DECAY (marginal IC by lag; is ADD-only slower?) ==")
    dc_full = decay_curve(SIG_full, D["resid_alt"], n_alt); dc_add = decay_curve(SIG_add, D["resid_alt"], n_alt)
    print("  lag(h): " + "  ".join(f"{k:>7}" for k in dc_full))
    print("  full  : " + "  ".join(f"{dc_full[k]:+.4f}" for k in dc_full))
    print("  ADD   : " + "  ".join(f"{dc_add[k]:+.4f}" for k in dc_add))
    print("\n== TAKER BOOK (turnover-aware, top-tier fee 2.4 + impact spread; per-fold sign, day-block CI) ==")
    print("  FULL signal (baseline — reproduces the known taker-dead):")
    r_full = taker_eval(SIG_full, D, "full")
    print("  ADD-ONLY signal (the accumulation-cohort escape):")
    r_add = taker_eval(SIG_add, D, "ADD")
    res = {"add_fraction": float(frac), "decay_full": dc_full, "decay_add": dc_add, "taker_full": r_full, "taker_add": r_add}
    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    _log(f"wrote {OUT/'results.json'}")
    # KILL CRITERION
    best = max((v["break_even_fee"], v["folds_pos"], reb) for reb, v in r_add.items()) if r_add else (None, 0, None)
    print(f"\nKILL CRITERION (break-even fee ≥2.4 at ≥5/7 folds): ADD-only best break-even fee = "
          f"{best[0] if best[0] is not None else 'na'} at {best[1]}/7 folds → "
          f"{'SURVIVES' if (best[0] is not None and best[0] >= 2.4 and best[1] >= 5) else 'FAILS → taker dead from this angle too'}")


if __name__ == "__main__":
    run()
