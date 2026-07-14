"""
adfilter_crowding_confidence — the DECISIVE R input: the composite's OWN internal confidence (cross-wallet
consensus / standard error) as the Kalman R, tested as a RANKING change vs the FIXED α=0.90 EMA (the near-
sufficient scalar filter — the real bar), not just vs baseline.

Reuses adfilter_crowding_composition's per-wallet reconstruction (each contributing wallet casts v_w = W_w·q_w on
an alt-hour; W train-frozen -> causal). Per (alt,hour) from {(W_w, q_w)} we form the sufficient stats and derive:
  n_eff = (ΣW)²/Σ(W²)                       Kish effective N
  var_w = Σ W q² / ΣW − (ΣW q/ΣW)²          weighted variance of the votes
  se    = sqrt((var_w + v0)/n_eff)          SE of the weighted mean (v0 = EB variance floor so 1-wallet/degenerate
                                            cells are NOT handed infinite precision — the key subtlety)
  prec  = 1/se² = n_eff/(var_w + v0)        the Kalman precision (1/R)
  cons  = |Σ W·sign(q)| / ΣW  ∈[0,1]        directional consensus

RANKING variants (A, the novel lever — reweights the cross-section, does NOT time-smooth):
  shrunk(λ): rank by s_inf · prec/(prec+λ)  (empirical-Bayes; down-weight contested cells)   λ tuned on EARLY
  t_rank:    rank by s_inf / se
  cons_rank: rank by s_inf · cons

Bar to beat = FIXED α=0.90 EMA (dense_ema). Every variant booked PHASE-AVERAGED over the 4 reb-4 offsets; PAIRED
(variant − fixedα) net delta with a day-block CI + per-fold sign; matched-DoF null (shuffle the precision/cons
schedule, same λ / #params -> P(random ≥ variant)); OOS: tune on EARLY (202512-202602), confirm LATE (202603-06).
Mechanism: conditional forward-IC bucketed by prec/cons (early AND late). Subtlety watch: does the confidence just
reward low-n / low-variance cells (bad, opposite of the breadth win)? -> report Spearman(prec,NW), etc.

    .venv/bin/python -m research.studies.wallet_flow.adfilter_crowding_confidence
"""
from __future__ import annotations
import time, json, functools
from pathlib import Path
import numpy as np

from research.studies.wallet_flow import kalman_swarm_perwallet as KP
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import adfilter_crowding_composition as CC
from research.studies.wallet_flow.kalman_swarm_decisive import dense_ema

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

OUT = Path("data/derived/xsec_adfilter_confidence")
REB = 4
FOCUS = ("maker_earn_a30", "taker_top_smallclip")
ALPHA_FIX = 0.90
KGRID = [0.0, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]     # λ = k · median(precision)
N_NULL = 60


# ------------------------------------------------------------------ per-cell sufficient stats ----------------
def fold_cells_conf(D, m, W):
    """Like CC.fold_cells but also emits ΣW, ΣW², ΣWq², ΣW·sign(q) per (alt,hour) -> SE / n_eff / consensus."""
    n_alt, N = D["n_alt"], D["N"]
    u_row = D["U4"][D["r"], D["ccode"]]
    te = (D["mth"] == m) & np.isfinite(u_row)
    wte, cte, rte, qte = D["wcode"][te], D["ccode"][te], D["r"][te], D["q"][te]
    live = W[wte] > 0
    wte, cte, rte, qte = wte[live], cte[live], rte[live], qte[live]
    if len(wte) == 0:
        return None
    key_wcr = (wte.astype(np.int64) * n_alt + cte.astype(np.int64)) * N + rte.astype(np.int64)
    uk, inv = np.unique(key_wcr, return_inverse=True)
    qsum = np.zeros(len(uk)); np.add.at(qsum, inv, qte)          # wallet w's net q on this (coin,hour)
    w_u = (uk // (n_alt * N)).astype(np.int64)
    c_u = ((uk // N) % n_alt).astype(np.int64)
    r_u = (uk % N).astype(np.int64)
    Wv = W[w_u]
    cellkey = r_u * n_alt + c_u
    uc, cinv = np.unique(cellkey, return_inverse=True)
    def agg(x):
        o = np.zeros(len(uc)); np.add.at(o, cinv, x); return o
    S = agg(Wv * qsum)                    # S_a = Σ W q
    SUMW = agg(Wv)
    SUMW2 = agg(Wv * Wv)
    SWQ2 = agg(Wv * qsum * qsum)          # Σ W q²
    SWSGN = agg(Wv * np.sign(qsum))       # Σ W sign(q)
    NW = agg(np.ones(len(cinv)))          # # contributing wallets
    return dict(R=(uc // n_alt).astype(np.int64), C=(uc % n_alt).astype(np.int64),
                S=S, SUMW=SUMW, SUMW2=SUMW2, SWQ2=SWQ2, SWSGN=SWSGN, NW=NW)


def build_conf(D):
    keys = ["R", "C", "S", "SUMW", "SUMW2", "SWQ2", "SWSGN", "NW"]
    acc = {k: [] for k in keys}; foldid = []
    for fi, m in enumerate(D["folds"]):
        W = KP.fold_weight(D, m)
        fc = fold_cells_conf(D, m, W)
        if fc is None:
            continue
        for k in keys:
            acc[k].append(fc[k])
        foldid.append(np.full(len(fc["R"]), fi))
    G = {k: np.concatenate(acc[k]) for k in keys}
    G["fold"] = np.concatenate(foldid)
    R, C = G["R"].astype(np.int64), G["C"].astype(np.int64)
    crowd = D["CROWD"][R, C].copy(); lag = D["LAG_ac"][R, C].copy()
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    G["s_inf"] = S0.residualize(G["S"][:, None].astype(np.float64), np.column_stack([crowd, lag]), R)[:, 0]
    G["U"] = D["U4"][R, C]; G["month"] = D["panel_month"][R]
    # derived confidence stats
    sw = np.where(G["SUMW"] > 0, G["SUMW"], np.nan)
    qbar = G["S"] / sw
    var_w = np.maximum(G["SWQ2"] / sw - qbar * qbar, 0.0)
    n_eff = np.where(G["SUMW2"] > 0, G["SUMW"] ** 2 / G["SUMW2"], np.nan)
    v0 = float(np.nanmedian(var_w[n_eff >= 3]))          # EB variance floor (avoid infinite precision on tiny cells)
    G["v0"] = v0
    se = np.sqrt((var_w + v0) / n_eff)
    G["var_w"] = var_w; G["n_eff"] = n_eff; G["se"] = se
    G["prec"] = 1.0 / (se * se)
    G["cons"] = np.abs(G["SWSGN"]) / sw
    return G


# ------------------------------------------------------------------ dense book (phase-averaged + paired) -----
def _book_phase(M, grid, D, FVr):
    n_alt = D["n_alt"]; full = set(range(n_alt)); xs, fvb, elig = {}, {}, {}
    for t in grid:
        ti = int(t); row = M[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        xs[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
        elig[ti] = full
    keys = np.array(sorted(xs), dtype=np.int64)
    if len(keys) < 8:
        return None
    sim = CB.simulate_raw(keys, xs, fvb, D["halfspread"], D["hs_default"], 1, 0.10, 0.15, elig)
    if len(sim["hr"]) < 4:
        return None
    hrs = sim["hr"].astype(np.int64); out = {}
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in FOCUS:
            continue
        netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, D["hs_default"])
        out[lab] = netph
    return hrs, out


def eval_matrix(M, D, FVr, base_hours, fold_set=None):
    """Phase-average the book over 4 reb offsets; return per-scenario concatenated (net, hr) across phases.
    fold_set filters the rebalance grid by month (OOS eval), matching kalman_swarm_decisive.eval_alpha."""
    acc = {l: {"net": [], "hr": []} for l in FOCUS}
    for ph in range(REB):
        grid = base_hours[ph::REB]
        if fold_set is not None:
            grid = grid[np.isin(D["panel_month"][grid.astype(int)], list(fold_set))]
        res = _book_phase(M, grid, D, FVr)
        if res is None:
            continue
        hrs, out = res
        for l in FOCUS:
            acc[l]["net"].append(out[l]); acc[l]["hr"].append(hrs)
    for l in FOCUS:
        acc[l]["net"] = np.concatenate(acc[l]["net"]) if acc[l]["net"] else np.array([])
        acc[l]["hr"] = np.concatenate(acc[l]["hr"]) if acc[l]["hr"] else np.array([], np.int64)
    return acc


def mean_net(acc, lab):
    v = acc[lab]["net"]; return float(v.mean()) if len(v) else None


def paired_delta(acc_v, acc_f, D, lab, seed=7):
    """PAIRED (variant − fixedα) per-step net delta (identical step sets), day-block CI + per-fold sign."""
    nv, hv = acc_v[lab]["net"], acc_v[lab]["hr"]
    nf, hf = acc_f[lab]["net"], acc_f[lab]["hr"]
    if len(nv) != len(nf) or len(nv) == 0 or not np.array_equal(hv, hf):
        return None
    dv = nv - nf
    days = (D["hours"][hv] // 86400000).astype(np.int64); ud = np.unique(days)
    loc = {d: np.nonzero(days == d)[0] for d in ud}; rng = np.random.default_rng(seed); st = []
    for _ in range(1000):
        pick = rng.integers(0, len(ud), size=len(ud))
        st.append(dv[np.concatenate([loc[ud[p]] for p in pick])].mean())
    lo, hi = float(np.percentile(st, 2.5)), float(np.percentile(st, 97.5))
    mo = D["panel_month"][hv]
    pf = {int(mm): float(dv[mo == mm].mean()) for mm in sorted(set(mo.tolist()))}
    return {"mean_delta": float(dv.mean()), "ci95": [lo, hi],
            "folds_pos": int(sum(1 for x in pf.values() if x > 0)), "n_folds": len(pf),
            "per_fold": pf, "n_steps": int(len(dv))}


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    D = KP.load(); _log("loaded panel + fills")
    G = build_conf(D); _log(f"built {len(G['R']):,} cells; v0(var floor)={G['v0']:.4g}")
    N, n_alt = D["N"], D["n_alt"]
    FVr = S0.fwd_sum(D["resid_alt"], REB)

    def dense(vals):
        M = np.full((N, n_alt), np.nan); M[G["R"], G["C"]] = vals; return M
    SIG = dense(G["s_inf"])
    base_hours = np.array(sorted(set(int(t) for t in G["R"])), dtype=np.int64)
    nfold = len(D["folds"])
    early = set(int(D["folds"][i]) for i in range(nfold // 2))
    late = set(int(D["folds"][i]) for i in range(nfold // 2, nfold))
    print(f"folds {list(D['folds'])}  EARLY(tune) {sorted(early)}  LATE(OOS) {sorted(late)}")

    # ---- 0) SANITY: reproduce baseline maker +4.356 (all folds, phase 0) ----
    b0 = _book_phase(SIG, base_hours[::REB], D, FVr)
    print(f"\n==== SANITY: baseline α=1 phase-0 maker_a30 = {b0[1]['maker_earn_a30'].mean():+.3f} (target +4.356) ====")

    # ---- reliability schedules ----
    med_prec = float(np.nanmedian(G["prec"]))
    prec = np.where(np.isfinite(G["prec"]), G["prec"], 0.0)
    se = np.where(np.isfinite(G["se"]) & (G["se"] > 0), G["se"], np.nan)
    cons = np.where(np.isfinite(G["cons"]), G["cons"], 0.0)
    print(f"  median precision={med_prec:.3g}  median n_eff={np.nanmedian(G['n_eff']):.2f}  "
          f"median var_w={np.nanmedian(G['var_w']):.4g}  median cons={np.nanmedian(cons):.3f}")

    # ---- SUBTLETY WATCH: does confidence just pick low-n / low-var cells? ----
    watch = {"spearman_prec_NW": float(A._spear(prec, G["NW"])),
             "spearman_prec_neff": float(A._spear(prec, G["n_eff"])),
             "spearman_prec_varw": float(A._spear(prec, G["var_w"])),
             "spearman_cons_NW": float(A._spear(cons, G["NW"])),
             "spearman_t_NW": float(A._spear(np.abs(G["s_inf"]) / se, G["NW"]))}
    hi_t = np.abs(G["s_inf"]) / se
    fin = np.isfinite(hi_t)
    thi = np.nanpercentile(hi_t[fin], 80); tlo = np.nanpercentile(hi_t[fin], 20)
    watch["meanNW_hi_t"] = float(np.nanmean(G["NW"][fin][hi_t[fin] >= thi]))
    watch["meanNW_lo_t"] = float(np.nanmean(G["NW"][fin][hi_t[fin] <= tlo]))
    print(f"\n==== SUBTLETY WATCH (does confidence reward participation or just low-n/low-var?) ====")
    print(f"  Spearman(prec, NW)={watch['spearman_prec_NW']:+.3f}  Spearman(prec, n_eff)={watch['spearman_prec_neff']:+.3f}"
          f"  Spearman(prec, var_w)={watch['spearman_prec_varw']:+.3f}")
    print(f"  Spearman(cons, NW)={watch['spearman_cons_NW']:+.3f}  Spearman(|t|, NW)={watch['spearman_t_NW']:+.3f}")
    print(f"  mean NW in top-|t| quintile={watch['meanNW_hi_t']:.1f} vs bottom={watch['meanNW_lo_t']:.1f}")

    # ---- 1) MECHANISM: conditional forward IC bucketed by reliability (early & late) ----
    allm = np.ones(len(G["R"]), bool)
    e_mask = np.isin(G["month"], list(early)); l_mask = np.isin(G["month"], list(late))
    mech = {}
    print(f"\n==== MECHANISM: conditional forward-IC (Spearman s_inf vs U4) by reliability ====")
    for name, arr in (("precision", prec), ("consensus", cons), ("inv_se_negse", -se), ("n_eff", G["n_eff"])):
        mech[name] = {t: CC.cond_ic(G["s_inf"], G["U"], arr, msk)
                      for t, msk in (("early", e_mask), ("late", l_mask))}
        for tg in ("early", "late"):
            c = mech[name][tg]
            if c is None:
                print(f"  {name:12s} {tg:5s}: thin"); continue
            cells = "  ".join(f"IC{b['ic']:+.4f}(n{b['n']})" if b["ic"] is not None else "na" for b in c["bins"])
            print(f"  {name:12s} {tg:5s}: {cells}  slope={c['slope_ic_per_f']}")

    # ---- 2) FIXED α=0.90 EMA benchmark (the bar) ----
    M_ema = dense_ema(SIG, ALPHA_FIX)
    acc_fix_all = eval_matrix(M_ema, D, FVr, base_hours)
    acc_fix_late = eval_matrix(M_ema, D, FVr, base_hours, late)
    acc_base_all = eval_matrix(SIG, D, FVr, base_hours)
    acc_base_late = eval_matrix(SIG, D, FVr, base_hours, late)
    print(f"\n==== BENCHMARKS (phase-averaged) ====")
    for tag, ab, af in (("all", acc_base_all, acc_fix_all), ("late", acc_base_late, acc_fix_late)):
        print(f"  [{tag}] baseline α=1  maker {CC.fmt(mean_net(ab,'maker_earn_a30'))} "
              f"taker {CC.fmt(mean_net(ab,'taker_top_smallclip'))}   |   "
              f"fixed α=0.90  maker {CC.fmt(mean_net(af,'maker_earn_a30'))} "
              f"taker {CC.fmt(mean_net(af,'taker_top_smallclip'))}")

    # ---- 3) VARIANTS: tune λ on EARLY (argmax maker_a30), confirm LATE, PAIRED vs fixed α ----
    def M_shrunk(lam, pvec=prec):
        return dense(G["s_inf"] * pvec / (pvec + lam))
    # tune λ on EARLY
    print(f"\n==== λ SWEEP (shrunk = s_inf·prec/(prec+λ)); tune on EARLY, argmax maker_a30 ====")
    early_curve = {}
    for k in KGRID:
        lam = k * med_prec
        acc = eval_matrix(M_shrunk(lam), D, FVr, base_hours, early)
        early_curve[k] = mean_net(acc, "maker_earn_a30")
        print(f"  k={k:>4}  λ={lam:9.3g}  EARLY maker_a30={CC.fmt(early_curve[k])}")
    kstar = max((k for k in KGRID if early_curve[k] is not None), key=lambda k: early_curve[k])
    lamstar = kstar * med_prec
    print(f"  -> k*={kstar} (λ*={lamstar:.3g})")

    variants = {
        f"shrunk_k{kstar}": M_shrunk(lamstar),
        "t_rank": dense(G["s_inf"] / se),
        "cons_rank": dense(G["s_inf"] * cons),
    }
    results = {"sanity_phase0_maker": float(b0[1]['maker_earn_a30'].mean()), "watch": watch,
               "mechanism": mech, "kstar": kstar, "lamstar": lamstar, "early_curve": early_curve,
               "benchmarks": {}, "variants": {}}
    for tag, a in (("baseline_all", acc_base_all), ("fixed_all", acc_fix_all),
                   ("baseline_late", acc_base_late), ("fixed_late", acc_fix_late)):
        results["benchmarks"][tag] = {l: mean_net(a, l) for l in FOCUS}

    print(f"\n==== VARIANTS vs FIXED α=0.90 (LATE / OOS, phase-averaged, PAIRED delta) ====")
    for vn, Mv in variants.items():
        acc_l = eval_matrix(Mv, D, FVr, base_hours, late)
        entry = {"late_net": {l: mean_net(acc_l, l) for l in FOCUS}, "paired_vs_fixed": {}}
        for l in FOCUS:
            pd = paired_delta(acc_l, acc_fix_late, D, l)
            entry["paired_vs_fixed"][l] = pd
        results["variants"][vn] = entry
        for l in FOCUS:
            pd = entry["paired_vs_fixed"][l]
            base = mean_net(acc_l, l); fx = mean_net(acc_fix_late, l)
            if pd is None:
                print(f"  {vn:14s} {l:20s} net {CC.fmt(base)} (fixed {CC.fmt(fx)})  [unpaired]")
            else:
                star = "*" if pd["ci95"][0] > 0 else ("-" if pd["ci95"][1] < 0 else " ")
                print(f"  {vn:14s} {l:20s} net {CC.fmt(base)} vs fixed {CC.fmt(fx)}  "
                      f"Δ={pd['mean_delta']:+.3f} CI[{pd['ci95'][0]:+.3f},{pd['ci95'][1]:+.3f}] "
                      f"folds+{pd['folds_pos']}/{pd['n_folds']}{star}")

    # ---- 4) MATCHED-DoF NULL: shuffle the reliability schedule (same λ / #params) ----
    print(f"\n==== MATCHED-DoF NULL: shuffle reliability across cells, P(random ≥ variant) [LATE maker_a30] ====")
    rng = np.random.default_rng(20260710)
    null = {}
    real_shrunk = mean_net(eval_matrix(M_shrunk(lamstar), D, FVr, base_hours, late), "maker_earn_a30")
    real_t = mean_net(eval_matrix(dense(G["s_inf"] / se), D, FVr, base_hours, late), "maker_earn_a30")
    real_c = mean_net(eval_matrix(dense(G["s_inf"] * cons), D, FVr, base_hours, late), "maker_earn_a30")
    for nm, real, gen in (
        ("shrunk", real_shrunk, lambda: M_shrunk(lamstar, prec[rng.permutation(len(prec))])),
        ("t_rank", real_t, lambda: dense(G["s_inf"] / se[rng.permutation(len(se))])),
        ("cons_rank", real_c, lambda: dense(G["s_inf"] * cons[rng.permutation(len(cons))])),
    ):
        draws = []
        for _ in range(N_NULL):
            v = mean_net(eval_matrix(gen(), D, FVr, base_hours, late), "maker_earn_a30")
            if v is not None:
                draws.append(v)
        draws = np.array(draws)
        p = float((1 + int((draws >= real).sum())) / (len(draws) + 1))
        null[nm] = {"real": real, "null_mean": float(draws.mean()), "null_p95": float(np.percentile(draws, 95)),
                    "p_random_ge": p, "n_draws": int(len(draws))}
        print(f"  {nm:10s} real maker_a30={CC.fmt(real)}  null mean={draws.mean():+.3f} "
              f"p95={np.percentile(draws,95):+.3f}  P(rand≥real)={p:.3f}")
    results["matched_null"] = null

    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=float))
    _log(f"wrote {OUT/'results.json'}")


if __name__ == "__main__":
    run()
