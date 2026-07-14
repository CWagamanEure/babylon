"""
adfilter_crowding_composition — COHORT-COMPOSITION R-drivers for the xsec selection signal.

Swarm lens (audit/xsec_adaptive_filter_swarm/SCOPE.md): when noise traders / low-skill wallets CROWD into the
hour's vote, the per-(alt,hour) measurement S_a is noisier -> observation noise R rises -> the signal's forward IC
should COLLAPSE in those cells. We build CAUSAL per-(alt,hour) composition observables from the wallets voting on
that cell and test whether the forward IC is heteroskedastic in them (in-sample on EARLY folds, confirm OOS on LATE
folds). Then test whether GATING OUT high-R cells improves the phase-averaged decile book OOS.

Reuses the EXACT frozen pipeline: kalman_swarm_perwallet.load() (skill weights W per fold via fold_weight, V-trail
q, U4 forward rank, L2 crowd/mom controls, concentrated-book cost engine). Baseline (all cells, pooled reb4, single
phase) MUST reproduce the perwallet raw_base book (maker_a30 ~+4.35, taker_smallclip ~+1.42).

Per-(alt,hour) cell composition (each contributing wallet w casts vote v_w = W_w * q_{w,a,t}, W the train-frozen
skill weight -> fully causal):
  1. NW      = # distinct cohort wallets with W>0 voting (breadth; LLN -> more breadth = lower R)
  2. WHALE   = max_w|v_w| / Σ_w|v_w|              (one wallet dominates the vote = high R)
  3. LOWSH   = Σ_{low-skill}|v_w| / Σ_w|v_w|      ("noise traders crowding in" = high R)
  4. AGREE   = sign(Σ_{high-skill} v_w) * sign(Σ_{low-skill} v_w)   (disagreement -1 = high R)
Conditional IC in each bucket = Spearman(s_inf, U4[cell]) (the exact pooled OOS IC used everywhere).

    .venv/bin/python -m research.studies.wallet_flow.adfilter_crowding_composition
"""
from __future__ import annotations
import time, json, functools
from pathlib import Path
import numpy as np

from research.studies.wallet_flow import kalman_swarm_perwallet as KP
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

OUT = Path("data/derived/xsec_adfilter_crowding")
REB = 4
FOCUS = ("taker_top_smallclip", "maker_earn_a30")
NB = 5                    # buckets for the conditional-IC curve


# ------------------------------------------------------------------ per-cell composition aggregator ----------
def fold_cells(D, m, W):
    """For fold m, aggregate the OOS test-month rows into per-(alt,hour) cells AND the composition observables.
    Each contributing wallet-cell casts v = W_w * (Σ q on that w,c,r). stale=0 equivalent of run_horizon's S, so S
    reproduces the frozen signal; the extra outputs are the causal cohort-composition features."""
    n_alt, N = D["n_alt"], D["N"]
    u_row = D["U4"][D["r"], D["ccode"]]
    te = (D["mth"] == m) & np.isfinite(u_row)
    wte, cte, rte, qte = D["wcode"][te], D["ccode"][te], D["r"][te], D["q"][te]
    Wte = W[wte]
    live = Wte > 0
    wte, cte, rte, qte = wte[live], cte[live], rte[live], qte[live]
    if len(wte) == 0:
        return None
    # one endpoint per (wallet, coin, hour): sum q (matches run_horizon's per-cell q sum for a wallet)
    key_wcr = (wte.astype(np.int64) * n_alt + cte.astype(np.int64)) * N + rte.astype(np.int64)
    uk, inv = np.unique(key_wcr, return_inverse=True)
    qsum = np.zeros(len(uk)); np.add.at(qsum, inv, qte)
    w_u = (uk // (n_alt * N)).astype(np.int64)
    c_u = ((uk // N) % n_alt).astype(np.int64)
    r_u = (uk % N).astype(np.int64)
    W_u = W[w_u]
    vote = W_u * qsum
    absv = np.abs(vote)
    # skill tiers frozen on the fold's active wallets (W>0) — causal (train-frozen W)
    posW = W[W > 0]
    q25, q75 = np.percentile(posW, [25, 75])
    hi = (W_u >= q75).astype(np.float64)
    lo = (W_u <= q25).astype(np.float64)
    # group wallet-cells into (alt,hour) cells
    cellkey = r_u * n_alt + c_u
    uc, cinv = np.unique(cellkey, return_inverse=True)
    S = np.zeros(len(uc)); np.add.at(S, cinv, vote)
    absum = np.zeros(len(uc)); np.add.at(absum, cinv, absv)
    nw = np.zeros(len(uc)); np.add.at(nw, cinv, 1.0)
    whale = np.zeros(len(uc)); np.maximum.at(whale, cinv, absv)
    lo_abs = np.zeros(len(uc)); np.add.at(lo_abs, cinv, absv * lo)
    hi_net = np.zeros(len(uc)); np.add.at(hi_net, cinv, vote * hi)
    lo_net = np.zeros(len(uc)); np.add.at(lo_net, cinv, vote * lo)
    nhi = np.zeros(len(uc)); np.add.at(nhi, cinv, hi)
    nlo = np.zeros(len(uc)); np.add.at(nlo, cinv, lo)
    denom = np.where(absum > 0, absum, np.nan)
    return dict(R=(uc // n_alt).astype(np.int64), C=(uc % n_alt).astype(np.int64), S=S,
                NW=nw, WHALE=whale / denom, LOWSH=lo_abs / denom,
                AGREE=np.sign(hi_net) * np.sign(lo_net), NHI=nhi, NLO=nlo, ABSUM=absum)


def build_all(D):
    """Run every fold, return concatenated per-cell arrays + s_inf (L2 ⊥crowd,⊥mom) + fold membership."""
    keys = ["R", "C", "S", "NW", "WHALE", "LOWSH", "AGREE", "NHI", "NLO", "ABSUM"]
    acc = {k: [] for k in keys}; foldid = []
    for fi, m in enumerate(D["folds"]):
        W = KP.fold_weight(D, m)
        fc = fold_cells(D, m, W)
        if fc is None:
            continue
        for k in keys:
            acc[k].append(fc[k])
        foldid.append(np.full(len(fc["R"]), fi))
        _log(f"  fold {m}: {len(fc['R']):,} cells  W>0 {int((W>0).sum()):,}")
    out = {k: np.concatenate(acc[k]) for k in keys}
    out["fold"] = np.concatenate(foldid)
    R, C = out["R"].astype(np.int64), out["C"].astype(np.int64)
    # L2-neutralize S (⊥crowd, ⊥lagged momentum) per hour — EXACT concentrated-book recipe
    crowd = D["CROWD"][R, C].copy(); lag = D["LAG_ac"][R, C].copy()
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    out["s_inf"] = S0.residualize(out["S"][:, None].astype(np.float64), np.column_stack([crowd, lag]), R)[:, 0]
    out["U"] = D["U4"][R, C]
    out["month"] = D["panel_month"][R]
    return out


# ------------------------------------------------------------------ conditional IC in observable buckets -----
def cond_ic(s, u, f, mask, nb=NB, higher=True):
    """Bucket cells by f (within `mask`) into nb quantile bins; report Spearman(s,u) per bin. `higher`=is a HIGHER f
    the hypothesized higher-trust (lower-R) end. Returns bin edges, per-bin IC, per-bin n, and a monotone slope."""
    sel = mask & np.isfinite(s) & np.isfinite(u) & np.isfinite(f)
    ss, uu, ff = s[sel], u[sel], f[sel]
    if len(ss) < nb * 50:
        return None
    # quantile edges; if f is near-degenerate (e.g. AGREE in {-1,0,1}) fall back to value-groups
    uq = np.unique(ff)
    if len(uq) <= nb:
        groups = [(v, ff == v) for v in uq]
    else:
        edges = np.quantile(ff, np.linspace(0, 1, nb + 1))
        edges[0] -= 1e-9; edges[-1] += 1e-9
        groups = []
        for b in range(nb):
            gm = (ff > edges[b]) & (ff <= edges[b + 1])
            groups.append(((edges[b] + edges[b + 1]) / 2, gm))
    rows = []
    for lvl, gm in groups:
        if gm.sum() < 30:
            rows.append({"level": float(lvl), "n": int(gm.sum()), "ic": None, "fmean": None}); continue
        rows.append({"level": float(lvl), "n": int(gm.sum()),
                     "ic": float(A._spear(ss[gm], uu[gm])), "fmean": float(ff[gm].mean())})
    ics = [r["ic"] for r in rows if r["ic"] is not None]
    lvls = [r["fmean"] for r in rows if r["ic"] is not None]
    slope = float(np.polyfit(lvls, ics, 1)[0]) if len(ics) >= 3 else None
    return {"bins": rows, "slope_ic_per_f": slope, "n_total": int(len(ss)),
            "ic_lowbin": ics[0] if ics else None, "ic_highbin": ics[-1] if ics else None}


# ------------------------------------------------------------------ decile book (phase-averaged) -------------
def book_net(D, R, C, s_inf, keep_mask, hours_sel, pw=None):
    """Phase-averaged pooled decile long-short book over the selected hours. keep_mask gates cells IN (eligible for
    the cross-section). pw (optional) is a per-cell POSITIVE precision multiplier applied to s_inf BEFORE ranking —
    a soft adaptive-R weight that pulls low-precision (high-R) cells toward the middle instead of removing them.
    Returns net-bp/hr per FOCUS scenario, averaged over the 4 reb-phase offsets."""
    n_alt = D["n_alt"]
    sig = s_inf if pw is None else s_inf * pw
    xs = {}
    for i in hours_sel:
        if not (np.isfinite(sig[i]) and keep_mask[i]):
            continue
        t = int(R[i]); xs.setdefault(t, ([], [])); xs[t][0].append(int(C[i])); xs[t][1].append(float(sig[i]))
    xs_arr = {t: (np.array(v[0]), np.array(v[1])) for t, v in xs.items()}
    hrs_sorted = np.array(sorted(xs_arr), dtype=np.int64)
    FVr = S0.fwd_sum(D["resid_alt"], REB)
    fvb = {int(t): {int(a): float(FVr[int(t), a]) * 1e4 for a in xs_arr[int(t)][0]} for t in hrs_sorted}
    full = set(range(n_alt)); elig = {int(t): full for t in hrs_sorted}
    scen = {l: [] for l in FOCUS}
    for ph in range(REB):
        hh = hrs_sorted[ph:]
        if len(hh) < REB * 2:
            continue
        sim = CB.simulate_raw(hh, xs_arr, fvb, D["halfspread"], D["hs_default"], REB, 0.10, 0.15, elig)
        if len(sim["hr"]) == 0:
            continue
        for lab, mult, fee, mode in CB.SCENARIOS:
            if lab not in FOCUS: continue
            netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, D["hs_default"])
            if len(netph): scen[lab].append(float(netph.mean()))
    return {l: (float(np.mean(v)) if v else None) for l, v in scen.items()}, \
           {l: (len(v)) for l, v in scen.items()}


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    D = KP.load(); _log("loaded panel + fills")
    G = build_all(D); _log(f"built {len(G['R']):,} OOS cells across {len(D['folds'])} folds")

    nfold = len(D["folds"])
    early = G["fold"] < (nfold // 2)          # discover
    late = ~early                             # confirm OOS
    allm = np.ones(len(G["R"]), bool)
    s_inf, U = G["s_inf"], G["U"]

    # ---- 0) SANITY BASELINE: reproduce perwallet raw_base (pooled reb4, single phase) ----
    n_alt = D["n_alt"]
    xs = {}
    for i in range(len(G["R"])):
        if not np.isfinite(s_inf[i]): continue
        t = int(G["R"][i]); xs.setdefault(t, ([], [])); xs[t][0].append(int(G["C"][i])); xs[t][1].append(float(s_inf[i]))
    xs_arr = {t: (np.array(v[0]), np.array(v[1])) for t, v in xs.items()}
    hrs_sorted = np.array(sorted(xs_arr), dtype=np.int64)[::REB]
    FVr = S0.fwd_sum(D["resid_alt"], REB)
    fvb = {int(t): {int(a): float(FVr[int(t), a]) * 1e4 for a in xs_arr[int(t)][0]} for t in hrs_sorted}
    full = set(range(n_alt)); elig = {int(t): full for t in hrs_sorted}
    # hrs_sorted is ALREADY decimated -> book with reb=1 (matches perwallet eval_variant), net divided by REB after
    sim = CB.simulate_raw(hrs_sorted, xs_arr, fvb, D["halfspread"], D["hs_default"], 1, 0.10, 0.15, elig)
    base = {}
    for lab, mult, fee, mode in CB.SCENARIOS:
        netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, D["hs_default"])
        base[lab] = float(netph.mean()) if len(netph) else None
    print("\n==== SANITY BASELINE (pooled reb4 single-phase; must match perwallet raw_base) ====")
    print(f"  maker_earn_a30   {base['maker_earn_a30']:+.3f}  (target ~+4.35)")
    print(f"  taker_top_smallclip {base['taker_top_smallclip']:+.3f}  (target ~+1.42)")
    overall_ic = float(A._spear(s_inf, U))
    print(f"  pooled OOS IC (all cells) = {overall_ic:+.4f}")

    # ---- 1) CONDITIONAL-IC HETEROSKEDASTICITY per observable ----
    # (name, array, HIGHER-f-is-lower-R?)  hypothesis direction for each driver
    OBS = [("NW_breadth", G["NW"], True),        # more wallets -> lower R -> higher IC
           ("WHALE_conc", G["WHALE"], False),    # whale dominates -> higher R -> lower IC
           ("LOWSKILL_share", G["LOWSH"], False),# noise-traders crowd in -> higher R -> lower IC
           ("HL_AGREE", G["AGREE"], True)]       # skilled/unskilled agree -> lower R -> higher IC
    cond = {}
    print("\n==== CONDITIONAL FORWARD IC vs COHORT-COMPOSITION (Spearman s_inf vs U4) ====")
    for name, arr, higher in OBS:
        cond[name] = {}
        for tag, msk in (("all", allm), ("early_discover", early), ("late_OOS", late)):
            cond[name][tag] = cond_ic(s_inf, U, arr, msk)
        print(f"\n  -- {name} (hyp: {'HIGHER'if higher else'LOWER'} f = lower R = higher IC) --")
        for tag in ("early_discover", "late_OOS"):
            c = cond[name][tag]
            if c is None:
                print(f"    {tag:15s}: thin"); continue
            cells = "  ".join(f"[{b['fmean']:+.3g}:IC{b['ic']:+.4f}(n{b['n']})]" if b["ic"] is not None
                              else f"[{b['level']:+.3g}:na]" for b in c["bins"])
            print(f"    {tag:15s}: {cells}  slope={c['slope_ic_per_f']}")

    # ---- 2) GATING TEST: drop high-R cells, does the phase-averaged OOS book improve? ----
    # Build a combined R-score from the OOS-confirmed drivers (higher = noisier). Gate the worst quartile.
    late_idx = np.nonzero(late)[0]
    print("\n==== GATING: phase-averaged decile book, LATE (OOS) folds, drop worst-R cells ====")
    base_book, base_nph = book_net(D, G["R"], G["C"], s_inf, allm, late_idx)
    print(f"  baseline (all cells)         maker_a30 {fmt(base_book['maker_earn_a30'])}  "
          f"taker_smallclip {fmt(base_book['taker_top_smallclip'])}")
    gate = {"baseline": base_book}
    # per-observable single-driver gate: keep the trusted (low-R) fraction
    for name, arr, higher in OBS:
        a = arr.copy()
        rscore = a if not higher else -a   # rscore: higher = noisier
        fin = np.isfinite(rscore[late_idx])
        if fin.sum() < 100:
            continue
        for frac in (0.75, 0.50):
            thr = np.quantile(rscore[late_idx][fin], frac)
            keep = np.ones(len(G["R"]), bool)
            bad = np.isfinite(rscore) & (rscore > thr)
            keep[bad] = False
            bk, _ = book_net(D, G["R"], G["C"], s_inf, keep, late_idx)
            gate.setdefault(name, {})[f"keep{int(frac*100)}"] = bk
            print(f"  gate {name:15s} keep{int(frac*100)}%  maker_a30 {fmt(bk['maker_earn_a30'])}  "
                  f"taker_smallclip {fmt(bk['taker_top_smallclip'])}")

    # ---- 3) SOFT PRECISION-WEIGHT: multiply s_inf by a POSITIVE precision (keeps cross-section; pulls high-R
    #         cells toward the middle of the rank instead of deleting hours). Adaptive-R, the faithful test. ----
    print("\n==== SOFT PRECISION-WEIGHT: s_inf *= precision, phase-averaged decile book ====")
    NWn = G["NW"] / np.nanmedian(G["NW"])                      # breadth, normalized
    pweights = {
        "pw_breadth_sqrt": np.sqrt(np.clip(NWn, 1e-6, None)),
        "pw_inv_whale": np.clip(1.0 - G["WHALE"], 0.05, None),
        "pw_inv_lowskill": np.clip(1.0 - G["LOWSH"], 0.05, None),
        "pw_combo": np.sqrt(np.clip(NWn, 1e-6, None)) * np.clip(1.0 - G["WHALE"], 0.05, None),
    }
    pwres = {}
    for tag, idx in (("late_OOS", late_idx), ("all_folds", np.arange(len(G["R"])))):
        b0, _ = book_net(D, G["R"], G["C"], s_inf, allm, idx)
        pwres.setdefault(tag, {})["baseline"] = b0
        print(f"  [{tag}] baseline            maker_a30 {fmt(b0['maker_earn_a30'])}  "
              f"taker_smallclip {fmt(b0['taker_top_smallclip'])}")
        for name, pw in pweights.items():
            bk, _ = book_net(D, G["R"], G["C"], s_inf, allm, idx, pw=pw)
            pwres[tag][name] = bk
            print(f"  [{tag}] {name:18s} maker_a30 {fmt(bk['maker_earn_a30'])}  "
                  f"taker_smallclip {fmt(bk['taker_top_smallclip'])}")

    res = {"baseline_pooled_singlephase": base, "overall_oos_ic": overall_ic,
           "conditional_ic": cond, "gating_late_oos": gate, "precision_weight": pwres,
           "config": {"reb": REB, "nb": NB, "n_folds": nfold, "n_cells": int(len(G["R"]))}}
    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    _log(f"wrote {OUT/'results.json'}")


def fmt(x):
    return f"{x:+.3f}" if x is not None else "  na "


if __name__ == "__main__":
    run()
