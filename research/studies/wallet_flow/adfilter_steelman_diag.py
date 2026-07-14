"""
adfilter_steelman_diag — MECHANISM PROOF for the adaptive observation-noise (R) model.

STEELMAN thesis: the deployable edge is a HETEROSKEDASTIC measurement model (per-cell R), not the fixed
alpha=0.90 EMA. Step 1 (this file): show the signal's CONDITIONAL forward IC is strongly heteroskedastic in
CAUSAL, cache-computable observables, IN-SAMPLE and OOS (early->late fold). Those observables are the R-drivers
(inverse-R proportional to conditional forward IC). No booking here — pure mechanism.

Observables tested (all strictly causal, use only data <= t):
  A. disp[t]          cross-sectional std of TRAILING residual momentum (per-hour regime; from the cache).
  B. sigmaS[t]        cross-sectional std of the hour's votes s_inf (vote spread / separation).
  C. absmedS[t]       cross-sectional median |s_inf| this hour (signal magnitude).
  D. coin_rel[t,a]    per-COIN trailing realized sign-hit-rate (rolling, fully-realized fwd windows only).

Diagnostic: per-hour cross-sectional rank-IC(t) = Spearman(s_inf[t,live], fwd4resid[t,live]) over ALL 5030
observed hours (45 names each). Bucket by the observable's IN-SAMPLE (early-fold) quantile edges; report mean
IC per bucket, EARLY (folds 0-3) and LATE (folds 4-6) separately + a per-hour sign share. For the per-cell
coin_rel driver, bucket CELLS and report the cell-level forward sign-agreement per bucket.

    .venv/bin/python -m research.studies.wallet_flow.adfilter_steelman_diag
"""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
OUT = Path("data/derived/xsec_kalman/adfilter_steelman_diag.json")
REB = 4
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)


def _rank(x):
    return np.argsort(np.argsort(x)).astype(float)


def spearman(x, y):
    if len(x) < 4: return np.nan
    rx, ry = _rank(x), _rank(y)
    rx -= rx.mean(); ry -= ry.mean()
    d = np.sqrt((rx * rx).sum() * (ry * ry).sum())
    return float((rx * ry).sum() / d) if d > 0 else np.nan


def load():
    d = np.load(CACHE, allow_pickle=False)
    R, Cc, s_inf = d["R"].astype(int), d["Cc"].astype(int), d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
    n_alt = int(d["n_alt"]); N = len(hours); folds = sorted(int(x) for x in d["folds"])
    SIG = np.full((N, n_alt), np.nan)
    fin = np.isfinite(s_inf); SIG[R[fin], Cc[fin]] = s_inf[fin]
    FV = S0.fwd_sum(resid_alt, REB) * 1e4                       # forward REB-hour resid return, bp
    return dict(SIG=SIG, FV=FV, disp=disp, panel_month=panel_month, n_alt=n_alt, N=N, folds=folds, hours=hours)


def main():
    P = load(); SIG = P["SIG"]; FV = P["FV"]; disp = P["disp"]; pm = P["panel_month"]
    folds = P["folds"]; early = set(folds[:4]); late = set(folds[4:])
    N = P["N"]; n_alt = P["n_alt"]

    obs_hours = np.array([t for t in range(N) if np.isfinite(SIG[t]).sum() >= 4], dtype=np.int64)
    _log(f"obs hours {len(obs_hours)}  (early {sum(int(pm[t]) in early for t in obs_hours)}, "
         f"late {sum(int(pm[t]) in late for t in obs_hours)})")

    # ---- per-hour cross-sectional rank-IC (only cells with finite fwd return) ----
    ic = {}
    live_mask = {}
    for t in obs_hours:
        row = SIG[t]; fr = FV[t]
        m = np.isfinite(row) & np.isfinite(fr)
        live_mask[int(t)] = m
        ic[int(t)] = spearman(row[m], fr[m]) if m.sum() >= 4 else np.nan

    # ---- causal per-hour observables ----
    sigmaS = {}; absmedS = {}
    for t in obs_hours:
        row = SIG[t]; fin = np.isfinite(row)
        sigmaS[int(t)] = float(row[fin].std())
        absmedS[int(t)] = float(np.median(np.abs(row[fin])))
    dispv = {int(t): float(disp[int(t)]) for t in obs_hours}

    def bucket_report(name, obsmap, nq=5):
        """Bucket obs hours by IN-SAMPLE (early) quantile edges of obsmap; report mean per-hour IC per bucket,
        EARLY and LATE separately. Monotone IC across buckets => heteroskedastic R-driver."""
        eh = [t for t in obs_hours if int(pm[t]) in early and np.isfinite(ic[int(t)]) and np.isfinite(obsmap[int(t)])]
        lh = [t for t in obs_hours if int(pm[t]) in late and np.isfinite(ic[int(t)]) and np.isfinite(obsmap[int(t)])]
        ev = np.array([obsmap[int(t)] for t in eh])
        edges = np.quantile(ev, np.linspace(0, 1, nq + 1))
        edges[0] = -np.inf; edges[-1] = np.inf
        rows = []
        for split, hs in (("EARLY", eh), ("LATE", lh)):
            for b in range(nq):
                sel = [t for t in hs if edges[b] <= obsmap[int(t)] < edges[b + 1]]
                ics = np.array([ic[int(t)] for t in sel])
                rows.append({"split": split, "bucket": b, "n": len(sel),
                             "mean_ic": float(np.nanmean(ics)) if len(ics) else np.nan,
                             "pos_share": float(np.mean(ics > 0)) if len(ics) else np.nan,
                             "obs_lo": float(edges[b]) if np.isfinite(edges[b]) else None,
                             "obs_hi": float(edges[b + 1]) if np.isfinite(edges[b + 1]) else None})
        print(f"\n--- {name}  (bucket edges frozen on EARLY quantiles; per-hour cross-sectional IC) ---")
        print(f"  {'bucket':>6} {'EARLY_IC':>9} {'E_n':>5} {'E_pos%':>7}   {'LATE_IC':>9} {'L_n':>5} {'L_pos%':>7}")
        e_ic, l_ic = [], []
        for b in range(nq):
            er = [r for r in rows if r["split"] == "EARLY" and r["bucket"] == b][0]
            lr = [r for r in rows if r["split"] == "LATE" and r["bucket"] == b][0]
            e_ic.append(er["mean_ic"]); l_ic.append(lr["mean_ic"])
            print(f"  {b:>6} {er['mean_ic']:>+9.4f} {er['n']:>5} {100*er['pos_share']:>6.1f}%   "
                  f"{lr['mean_ic']:>+9.4f} {lr['n']:>5} {100*lr['pos_share']:>6.1f}%")
        e_ic = np.array(e_ic); l_ic = np.array(l_ic)
        # monotonicity via Spearman(bucket_index, IC); range = max-min
        sp_e = spearman(np.arange(nq).astype(float), e_ic)
        sp_l = spearman(np.arange(nq).astype(float), l_ic)
        print(f"  IC range EARLY {np.nanmax(e_ic)-np.nanmin(e_ic):+.4f} (spearman b vs IC {sp_e:+.2f})  |  "
              f"LATE {np.nanmax(l_ic)-np.nanmin(l_ic):+.4f} (spearman {sp_l:+.2f})")
        return {"rows": rows, "early_ic": e_ic.tolist(), "late_ic": l_ic.tolist(),
                "sp_early": sp_e, "sp_late": sp_l, "edges": edges.tolist()}

    print("=" * 96)
    print("HETEROSKEDASTICITY DIAGNOSTIC — is conditional forward IC strongly driven by a causal observable?")
    print("  (positive monotone => trust HIGH-IC bucket cells (low R), smooth LOW-IC bucket cells (high R))")
    print("=" * 96)
    RES = {}
    RES["A_disp"] = bucket_report("A. disp[t]  (cross-sec std of trailing momentum — REGIME)", dispv)
    RES["B_sigmaS"] = bucket_report("B. sigmaS[t]  (cross-sec std of votes s_inf — vote SEPARATION)", sigmaS)
    RES["C_absmedS"] = bucket_report("C. absmedS[t]  (median |s_inf| this hour — signal MAGNITUDE)", absmedS)

    # ---- D. per-COIN trailing reliability (cell-level), rolling causal, fully-realized windows only ----
    print("\n" + "=" * 96)
    print("D. per-COIN trailing reliability (cell-level R-driver)")
    print("=" * 96)
    # for each coin, walk its observed hours; realized fwd known only once t+REB has passed => use obs hours
    # whose fwd window ended at or before the CURRENT hour. reliability = trailing mean sign-agreement.
    KWIN = 40   # trailing observations
    coin_rel = np.full((N, n_alt), np.nan)
    for a in range(n_alt):
        ts = np.array([t for t in obs_hours if np.isfinite(SIG[t, a]) and np.isfinite(FV[t, a])], dtype=np.int64)
        if len(ts) < KWIN + 5: continue
        sgn = np.sign(SIG[ts, a]) * np.sign(FV[ts, a])       # +1 correct, -1 wrong (realized)
        for i, t in enumerate(ts):
            # only past obs whose fwd window fully realized by hour t: obs time u with u+REB <= t
            past = [j for j in range(i) if ts[j] + REB <= t]
            if len(past) >= KWIN // 2:
                w = past[-KWIN:]
                coin_rel[t, a] = float(sgn[w].mean())
    # bucket cells by early-fold quantile of coin_rel; report forward sign-agreement per bucket
    cells = [(int(t), a) for t in obs_hours for a in range(n_alt)
             if np.isfinite(coin_rel[t, a]) and np.isfinite(SIG[t, a]) and np.isfinite(FV[t, a])]
    ce = [(t, a) for (t, a) in cells if int(pm[t]) in early]
    cl = [(t, a) for (t, a) in cells if int(pm[t]) in late]
    rv = np.array([coin_rel[t, a] for (t, a) in ce])
    edges = np.quantile(rv, np.linspace(0, 1, 6)); edges[0] = -np.inf; edges[-1] = np.inf
    print(f"  cells: early {len(ce)}  late {len(cl)}  (trailing K<={KWIN}, realized-only)")
    print(f"  {'bucket':>6} {'E_agree':>8} {'E_n':>7}   {'L_agree':>8} {'L_n':>7}")
    d_rows = []
    for b in range(5):
        se = [(t, a) for (t, a) in ce if edges[b] <= coin_rel[t, a] < edges[b + 1]]
        sl = [(t, a) for (t, a) in cl if edges[b] <= coin_rel[t, a] < edges[b + 1]]
        ea = np.mean([np.sign(SIG[t, a]) * np.sign(FV[t, a]) for (t, a) in se]) if se else np.nan
        la = np.mean([np.sign(SIG[t, a]) * np.sign(FV[t, a]) for (t, a) in sl]) if sl else np.nan
        d_rows.append({"bucket": b, "e_agree": float(ea), "e_n": len(se), "l_agree": float(la), "l_n": len(sl)})
        print(f"  {b:>6} {ea:>+8.4f} {len(se):>7}   {la:>+8.4f} {len(sl):>7}")
    RES["D_coin_rel"] = {"rows": d_rows, "KWIN": KWIN}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(RES, indent=2, default=float))
    _log(f"wrote {OUT}")
    print("\nLegend: EARLY = folds 0-3 (discovery), LATE = folds 4-6 (OOS confirm). A monotone IC gradient that")
    print("REPLICATES on LATE is a real R-driver; an early-only gradient is in-sample heteroskedasticity mining.")


if __name__ == "__main__":
    main()
