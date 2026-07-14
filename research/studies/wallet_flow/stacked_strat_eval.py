"""
Stacked-strategy economics: baseline vs α=0.90 denoise vs consensus-weight vs BOTH, at reb4 AND reb2, PHASE-AVERAGED,
with net bp/hr + annualized Sharpe + day-block CI + per-fold sign. Answers "what's the PnL/Sharpe of the combined strat".

Consensus needs per-wallet votes → full pipeline (~130s). Baseline must reproduce the honest phase-avg reb4 maker (+3.17).
    .venv/bin/python -m research.studies.wallet_flow.stacked_strat_eval
"""
from __future__ import annotations
import time, json
from pathlib import Path
import numpy as np
from research.studies.wallet_flow import kalman_swarm_perwallet as PW
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)
OUT = Path("data/derived/xsec_stacked"); HRS_YEAR = 8760.0
FOCUS = ("maker_earn_a30", "maker_earn_a50", "taker_top_smallclip")


def dense_ema(SIG, alpha):
    if alpha >= 1.0:
        return SIG
    N, A = SIG.shape
    m = np.full((N, A), np.nan); prev = np.full(A, np.nan)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs)
        newv = np.where(np.isfinite(prev), alpha * obs + (1.0 - alpha) * prev, obs)
        prev = np.where(has, newv, prev)
        m[t] = np.where(has, prev, np.nan)
    return m


def aggregate(D):
    """Per-fold: S_a = Σ W·q and consensus = |Σ W·sign(q)|/Σ W per (hour,alt) cell → residualize S ⊥crowd,mom → s_inf."""
    n_alt = D["n_alt"]; u_row = D["U4"][D["r"], D["ccode"]]
    Rl, Cl, Sl, Kl = [], [], [], []
    for m in D["folds"]:
        W = PW.fold_weight(D, m)
        te = (D["mth"] == m) & np.isfinite(u_row)
        wte, cte, rte, qte = D["wcode"][te], D["ccode"][te], D["r"][te], D["q"][te]
        Wte = W[wte]; live = Wte > 0
        wte, cte, rte, qte, Wte = wte[live], cte[live], rte[live], qte[live], Wte[live]
        key = rte.astype(np.int64) * n_alt + cte.astype(np.int64)
        uk, inv = np.unique(key, return_inverse=True)
        S = np.zeros(len(uk)); num = np.zeros(len(uk)); den = np.zeros(len(uk))
        np.add.at(S, inv, Wte * qte)
        np.add.at(num, inv, Wte * np.sign(qte))
        np.add.at(den, inv, Wte)
        cons = np.where(den > 0, np.abs(num) / den, 0.0)
        Rl.append((uk // n_alt).astype(np.int64)); Cl.append((uk % n_alt).astype(np.int64))
        Sl.append(S); Kl.append(cons)
    R = np.concatenate(Rl); C = np.concatenate(Cl); S = np.concatenate(Sl); CONS = np.concatenate(Kl)
    crowd = D["CROWD"][R, C].copy(); lag = D["LAG_ac"][R, C].copy()
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    s_inf = S0.residualize(S[:, None].astype(np.float64), np.column_stack([crowd, lag]), R)[:, 0]
    return R, C, s_inf, CONS


def book_config(D, SIG, CONS, alpha, use_cons, reb):
    """Phase-averaged book of a signal transform. Returns pooled per-step net series per scenario + per-phase Sharpes."""
    n_alt = D["n_alt"]; N = D["N"]; hours = D["hours"]; pm = D["panel_month"]
    sig = dense_ema(SIG, alpha)
    if use_cons:
        sig = sig * CONS                                    # rank by (smoothed) S · consensus
    FVr = S0.fwd_sum(D["resid_alt"], reb)
    obs_hours = np.array(sorted(set(int(t) for t in np.nonzero(np.isfinite(SIG).any(axis=1))[0])), dtype=np.int64)
    pooled = {"hr": [], "gross": [], "ntrade": [], "hs": [], "turn": []}
    sharpes = {lab: [] for lab, *_ in CB.SCENARIOS if lab in FOCUS}
    full = set(range(n_alt))
    for ph in range(reb):
        grid = obs_hours[ph::reb]
        xs, fvb, elig = {}, {}, {}
        for t in grid:
            ti = int(t); row = sig[ti]; nm = np.nonzero(np.isfinite(row))[0]
            if len(nm) < 4: continue
            xs[ti] = (nm.astype(int), row[nm].astype(float))
            fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
            elig[ti] = full
        keys = np.array(sorted(xs), dtype=np.int64)
        if len(keys) < 8: continue
        sim = CB.simulate_raw(keys, xs, fvb, D["halfspread"], D["hs_default"], 1, 0.10, 0.15, elig)
        if len(sim["hr"]) < 8: continue
        for k in pooled: pooled[k].extend(list(sim[k]))
        for lab, mult, fee, mode in CB.SCENARIOS:
            if lab not in FOCUS: continue
            netph, _ = CB.scenario_net_series(sim, reb, fee, mode, mult, D["hs_default"])
            per_cross = netph * reb                          # net over each reb-hour hold
            if per_cross.std() > 0:
                sharpes[lab].append(per_cross.mean() / per_cross.std() * np.sqrt(HRS_YEAR / reb))
    hrs = np.array(pooled["hr"], dtype=np.int64)
    shm = np.array([int(pm[int(t)]) for t in hrs])
    simp = {k: np.array(v, dtype=float) for k, v in pooled.items()}
    out = {"reb": reb, "n_steps": len(hrs), "gross_bp_hr": float((simp["gross"] / reb).mean()),
           "turn": float(simp["turn"].mean()), "sc": {}}
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in FOCUS: continue
        netph, _ = CB.scenario_net_series(simp, reb, fee, mode, mult, D["hs_default"])
        ci = CB._dayblock_ci(netph, hrs, hours)
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        out["sc"][lab] = {"net_bp_hr": float(netph.mean()), "ci95": ci,
                          "sharpe": float(np.mean(sharpes[lab])) if sharpes[lab] else float("nan"),
                          "folds_pos": int(sum(1 for v in pf.values() if v > 0)), "n_folds": len(pf)}
    return out


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    D = PW.load(); _log("pipeline loaded")
    R, C, s_inf, CONS = aggregate(D); _log(f"aggregated {len(R):,} cells")
    N = D["N"]; n_alt = D["n_alt"]
    SIGm = np.full((N, n_alt), np.nan); CONSm = np.full((N, n_alt), np.nan)
    fin = np.isfinite(s_inf)
    SIGm[R[fin], C[fin]] = s_inf[fin]; CONSm[R[fin], C[fin]] = CONS[fin]
    configs = [("baseline",            1.0, False), ("denoise α0.90",      0.90, False),
               ("consensus",           1.0, True),  ("BOTH denoise+cons",  0.90, True)]
    results = {}
    for reb in (4, 2):
        print(f"\n================ reb={reb} (PHASE-AVERAGED) ================")
        print(f"{'config':>20} {'gross/hr':>8} {'turn':>5}   " +
              "  ".join(f"{l.replace('maker_earn_','mk_').replace('taker_top_','tk_'):>26}" for l in FOCUS))
        for tag, alpha, uc in configs:
            e = book_config(D, SIGm, CONSm, alpha, uc, reb); results[f"reb{reb}/{tag}"] = e
            cols = []
            for l in FOCUS:
                sc = e["sc"][l]; lo, hi = sc["ci95"]; star = "*" if lo > 0 else (" " if hi > 0 else "-")
                cols.append(f"{sc['net_bp_hr']:+5.2f}/hr SR{sc['sharpe']:+4.1f}[{lo:+.1f},{hi:+.1f}]{sc['folds_pos']}/{sc['n_folds']}{star}")
            print(f"{tag:>20} {e['gross_bp_hr']:>+8.2f} {e['turn']:>5.2f}   " + "  ".join(f"{c:>26}" for c in cols))
    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=float))
    _log(f"wrote {OUT/'results.json'}")
    print("\nnet in bp/HOUR (maker legs EARN the spread; SR = annualized Sharpe, phase-avg; '*'=day-block CI>0).")
    print("Baseline reb4 maker_a30 should ≈ +3.17/hr (honest phase-avg). MAKER legs are passive-fill-dependent.")


if __name__ == "__main__":
    run()
