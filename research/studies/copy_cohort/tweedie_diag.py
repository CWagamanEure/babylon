"""Tweedie posterior-mean diagnostic (descriptive, off the frozen f-hat — no new selection claim).

Two jobs, both requested: (1) VERIFY the closed-form Tweedie correction equals a finite-difference
d/dz log f (exactness of the polynomial derivative); (2) REPORT the winner's-curse haircut and the
per-wallet sizing weights E[theta|z] for the arm-T selected cohort, per fold. Uses only the existing
informed.two_groups fit — no constants tuned.
"""
from __future__ import annotations

import glob
import json

import numpy as np
import pyarrow.parquet as pq

from research.studies.copy_cohort import informed


def _verify(z: np.ndarray) -> dict:
    """Exactness check: the closed-form correction (theta-z)/s0^2 must equal a central finite
    difference of the ACTUAL fitted log-density polyval(coef_f, .) — checked on the OCCUPIED
    support only (that is where theta is ever evaluated). Also report tail monotonicity of theta."""
    r = informed.two_groups(z)
    coef_f, s0 = r["coef_f"], r["sigma0"]
    z_lo, z_hi = r["z_lo"], r["z_hi"]
    theta_of = r["theta_of"]
    zg = np.linspace(z_lo + 1e-3, z_hi - 1e-3, 500)
    dlogf_cf = (theta_of(zg) - zg) / s0 ** 2                 # = polyval(coef_f', zg)
    h = 1e-4
    dlogf_num = (np.polyval(coef_f, zg + h) - np.polyval(coef_f, zg - h)) / (2 * h)
    err = np.max(np.abs(dlogf_cf - dlogf_num))
    # tail monotonicity where selection lives: from the null center out to the right edge
    zt = np.linspace(r["mu0"] + 2 * s0, z_hi, 300)
    tail_mono = bool(np.all(np.diff(theta_of(zt)) >= -1e-9))
    return {"deriv_max_abs_err": float(err), "deriv_ok": bool(err < 1e-4),
            "theta_tail_monotone": tail_mono,
            "occupied_support": [float(z_lo), float(z_hi)]}


def main() -> None:
    cohorts = json.load(open("data/derived/copy_cohort/alt_universe_cohorts.json"))
    out = {"folds": {}, "verify": None}
    verified = False
    for pf in sorted(glob.glob("data/derived/copy_cohort/informedness/fold=*/pool.parquet")):
        fold = pf.split("fold=")[1].split("/")[0]
        d = pq.read_table(pf).to_pydict()
        z = np.asarray(d["z"], float)
        wal = np.asarray(d["wallet"], object)
        tstat = np.asarray(d["t_stat"], float)
        r = informed.two_groups(z)
        theta = r["theta_of"](z)
        if not verified:
            out["verify"] = _verify(z)
            verified = True
        # arm-T selected wallets for this fold (if present in the frozen roster)
        armT = (cohorts.get("folds", {}).get(fold, {}).get("arms", {}).get("T", {}).get("members", {}))
        sel_wallets = list(armT.keys())
        idx = {w: i for i, w in enumerate(wal)}
        si = np.array([idx[w] for w in sel_wallets if w in idx], dtype=int)
        if si.size == 0:
            # fall back to top-30 by t (same rule) if roster fold naming differs
            si = np.argsort(-tstat)[:30]
        z_sel, th_sel = z[si], theta[si]
        haircut = z_sel - th_sel
        w_pos = np.clip(th_sel, 0, None)
        wnorm = (w_pos / w_pos.sum()).tolist() if w_pos.sum() > 0 else []
        out["folds"][fold] = {
            "n_pool": int(z.size), "n_selected": int(si.size),
            "mu0": r["mu0"], "sigma0": r["sigma0"], "pi0": r["pi0"],
            "z_sel_mean": float(z_sel.mean()), "theta_sel_mean": float(th_sel.mean()),
            "haircut_mean_z": float(haircut.mean()),
            "shrink_factor_mean": float((th_sel / z_sel).mean()),
            "theta_sel_min": float(th_sel.min()), "theta_sel_max": float(th_sel.max()),
            "sizing_weight_max": float(max(wnorm)) if wnorm else None,
            "sizing_weight_top5_share": float(np.sort(wnorm)[::-1][:5].sum()) if wnorm else None,
        }
    json.dump(out, open("data/derived/copy_cohort/tweedie_diag_report.json", "w"), indent=1)
    # console summary
    v = out["verify"]
    print(f"DERIV CHECK: max|err|={v['deriv_max_abs_err']:.2e} ok={v['deriv_ok']} "
          f"tail_monotone={v['theta_tail_monotone']} support={v['occupied_support']}")
    print(f"{'fold':8} {'zsel':>6} {'theta':>7} {'haircut':>8} {'shrink':>7} {'top5wt':>7}")
    for fold, f in out["folds"].items():
        print(f"{fold:8} {f['z_sel_mean']:6.2f} {f['theta_sel_mean']:7.2f} "
              f"{f['haircut_mean_z']:8.2f} {f['shrink_factor_mean']:7.2f} "
              f"{(f['sizing_weight_top5_share'] or 0):7.2f}")


if __name__ == "__main__":
    main()
