"""§6 power gate — BOTH components must pass before any forward number is looked at.

Component 1 — instrument MDE at the realized test level. Over each formation month as a pseudo-
forward leg, draw a random-K cohort, pool its episodes, and measure the SAME two-way (wallet ×
ISO-week) CGM CI half-width used at §5.5. MDE = (z_α+z_β)/z_α × pooled half-width. Powered iff
MDE ≤ care-about (5 bp). Sized to forward dimensions (single months, K=100, cluster counts as
realized) — NOT `power.mde_mean` on a wallet-nested σ, which is blind to cross-wallet week shocks.

Component 2 — planted-cohort SELECTION control. Plant a synthetic skilled sub-population (150 pool
wallets, +EDGE bp on every one of their episodes) into formation, split by time into a scoring
window and a pseudo-forward window, run the FULL pipeline (eb_shrink at the frozen wallet_week
level → top-K), and require (a) the top-K to capture the planted wallets well above chance and
(b) the recovered pseudo-forward cohort effect CI to cover +EDGE and exclude 0. A uniform edge
(power.inject_positive_control) can only test the evaluation arithmetic — it passes for ANY
selector — so it is NOT sufficient here; the planted sub-population is what tests selection.

    python -m research.studies.copy_cohort.power_gate run
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.stats import (eb_shrink, twoway_cluster_ci, inv_norm,
                                _cluster_sandwich_var_of_mean, t_ppf)
from . import selectors

OUT_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort"
REPORT_JSON = OUT_DIR / "power_gate_report.json"
CARE_ABOUT = 5.0
EDGE = 5.0
N_PLANT = 150
K = selectors.K_COHORT
SEED = 20260712
GATE_CUTOFF_MONTH = 202601          # fold-202602 formation (the shortest; conservative for power)
FORMATION_MONTHS = (202508, 202509, 202510, 202511, 202512, 202601)
POWER, ALPHA = 0.80, 0.05


def _months(open_ts: np.ndarray) -> np.ndarray:
    """epoch-ms → integer YYYYMM per row (UTC), vectorized."""
    m = open_ts.astype("datetime64[ms]").astype("datetime64[M]").astype(np.int64)  # months since 1970-01
    return (1970 + m // 12) * 100 + (m % 12 + 1)


def _mde_component(ep: dict, rng: np.random.Generator) -> dict:
    """Random-K cohort per formation month → pooled two-way CGM half-width → MDE.
    The CGM 'week' dimension MUST be plain cross-wallet ISO-week (`week_open`), NOT the wallet-nested
    `wk_code` — the latter is blind to the cross-wallet week shock the two-way CI exists to price and
    understates the MDE (audit F1/CRITICAL). `wk_code` is only for the eb_shrink selector cluster."""
    wk = ep["week_open"]
    month = _months(ep["open_ts"])
    ys, ws, wks = [], [], []
    for mo in np.unique(month):
        legmask = month == mo
        leg_w = np.unique(ep["w_code"][legmask])
        if leg_w.size < K:
            continue
        cohort = set(rng.choice(leg_w, size=K, replace=False).tolist())
        sel = legmask & np.isin(ep["w_code"], list(cohort))
        ys.append(ep["y"][sel]); ws.append(ep["w_code"][sel]); wks.append(wk[sel])
    if not ys:
        return {"error": "no legs with >=K pool wallets"}
    y = np.concatenate(ys); w = np.concatenate(ws); wkk = np.concatenate(wks)
    ci = twoway_cluster_ci(y, w, wkk)
    hw = (ci.hi - ci.lo) / 2.0
    z_a = inv_norm(1 - ALPHA / 2); z_b = inv_norm(POWER)
    mde = hw * (z_a + z_b) / z_a
    return {"pooled_halfwidth_bp": hw, "mde_bp": mde, "n_episodes": int(y.size),
            "twoway_df": ci.df, "powered": bool(mde <= CARE_ABOUT)}


def _planted_component(ep: dict, rng: np.random.Generator) -> dict:
    """Plant +EDGE on N_PLANT pool wallets; scoring = all but last formation month, pseudo-forward
    = last formation month; select top-K on scoring, evaluate on pseudo-forward. Integer codes."""
    months = _months(ep["open_ts"])
    fwd_month = int(months.max())
    score_mask = months < fwd_month
    fwd_mask = months == fwd_month
    # planted wallets (by w_code) must be active in BOTH windows so capture is measurable
    active_score = np.unique(ep["w_code"][score_mask])
    active_fwd = np.unique(ep["w_code"][fwd_mask])
    eligible = np.intersect1d(active_score, active_fwd)
    if eligible.size < N_PLANT:
        return {"error": f"only {eligible.size} wallets active in both windows"}
    planted = set(rng.choice(eligible, size=N_PLANT, replace=False).tolist())
    is_planted = np.isin(ep["w_code"], list(planted))
    y_inj = ep["y"] + EDGE * is_planted

    # select on the scoring window via the real eb_shrink at the frozen wallet_week level
    sw = score_mask
    r = eb_shrink(y_inj[sw], ep["w_code"][sw], ep["wk_code"][sw])
    rank = r.tstat if r.tau2_floored else r.shrunk
    order = np.argsort(np.where(np.isnan(rank), -np.inf, rank))[::-1]
    cohort = set(r.unit[order[:K]].tolist())          # top-K w_codes
    capture = len(cohort & planted) / N_PLANT

    # evaluate the selected cohort on the pseudo-forward window (episode-level two-way CGM);
    # week dimension = plain ISO-week (audit F1), not wallet-nested wk_code
    fw = fwd_mask & np.isin(ep["w_code"], list(cohort))
    y = y_inj[fw]; w = ep["w_code"][fw]; wkk = ep["week_open"][fw]
    ci = twoway_cluster_ci(y, w, wkk) if np.unique(wkk).size >= 5 else None
    # baseline: mean forward edge of a random-K cohort (should be ~0)
    rand_cohort = set(rng.choice(np.unique(ep["w_code"]), size=K, replace=False).tolist())
    fwr = fwd_mask & np.isin(ep["w_code"], list(rand_cohort))
    rand_mean = float(y_inj[fwr].mean()) if fwr.any() else float("nan")
    n_pool = int(np.unique(ep["w_code"]).size)
    return {"capture_rate": capture, "capture_vs_chance": capture / (K / max(n_pool, 1)),
            "recovered_mean_bp": float(y.mean()), "recovered_ci_lo": ci.lo if ci else None,
            "recovered_ci_hi": ci.hi if ci else None,
            "random_cohort_fwd_mean_bp": rand_mean, "n_fwd_episodes": int(y.size),
            "covers_edge": bool(ci and ci.lo <= EDGE <= ci.hi),
            "excludes_zero": bool(ci and ci.lo > 0),
            "passed": bool(ci and ci.lo > 0 and ci.lo <= EDGE <= ci.hi and capture > 0.5)}


def run() -> dict:
    con = selectors.connect()
    rng = np.random.default_rng(SEED)
    ep = selectors.formation_episodes(con, GATE_CUTOFF_MONTH)
    print(f"power gate: {ep['y'].size:,} formation episodes, {ep['pool'].size:,} pool wallets",
          flush=True)
    mde = _mde_component(ep, np.random.default_rng(SEED + 1))
    plant = _planted_component(ep, np.random.default_rng(SEED + 2))
    passed = bool(mde.get("powered") and plant.get("passed"))
    report = {"config": {"care_about_bp": CARE_ABOUT, "edge_bp": EDGE, "n_plant": N_PLANT, "K": K,
                         "gate_cutoff_month": GATE_CUTOFF_MONTH, "seed": SEED,
                         "frozen_cluster": selectors.FROZEN_CLUSTER},
              "component1_mde": mde, "component2_planted": plant,
              "GATE_PASSED": passed,
              "decision": ("PROCEED to forward run" if passed
                           else "STOP — redesign or declare data cannot resolve (anti-ratchet rule)")}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str))
    print(f"power gate: MDE={mde.get('mde_bp')}, planted capture={plant.get('capture_rate')}, "
          f"PASSED={passed} -> {REPORT_JSON}")
    return report


if __name__ == "__main__":
    run()
