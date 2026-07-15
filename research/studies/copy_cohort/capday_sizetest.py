"""Step 3d — the DEFINITIVE relative-size sizing test (equal budget, exposure-normalized, paired, WF-α).

Addresses every confound in the earlier size work (user's correction):
  - EQUAL WALLET BUDGET B (removes the wallet-wealth confound in "actual notional"); within-wallet variation
    comes ONLY from RELATIVE size r_it = entry_notl_it / strict-prior-median-notl_i (leakage-safe).
  - g(r)=r^α, α∈{0,0.25,0.5,1}, capped g(r)≤CAP (frozen from formation) so one whale entry can't dominate.
  - EXPOSURE-NORMALIZED: every variant's weights are renormalized to the SAME total gross exposure (Σŵ=1),
    so ES / worst-fold / drawdown are comparable and α=1's mean is not just higher leverage. Peak-concurrent
    capital usage is reported so any residual leverage difference is visible.
  - PAIRED inference: Δα = R_α − R_{α=0} on IDENTICAL entries, wallet-CLUSTER bootstrap (wallets recur across
    folds). Report Δmean, ΔES, Δworst-fold, P(Δ>0) — not two separate CIs.
  - HONEST α selection: a walk-forward rule picks α from PRIOR folds only and is scored on the next fold; the
    adaptive book is compared to the fixed α=0 baseline, NOT to the best ex-post α.

Only if the sequentially-selected sizing rule fails is "relative size gives no usable sizing signal at this N"
defensible. Same frozen cohort/entries/book as capday_book (8h q50-prior evaluable set).

    python -m research.studies.copy_cohort.capday_sizetest
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from research.lib.stats import t_ppf
from . import base as basemod
from . import capday_book as cb
from .capday_sizecurve import _load, _evaluable

HORIZON = "8h"
DAY_MS = cb.DAY_MS
H_MS = cb.HORIZON_MS[HORIZON]
ALPHAS = (0.0, 0.25, 0.5, 1.0)
CAP = 3.0                         # frozen max multiplier g(r) ≤ 3
N_BOOT = 2000
SEED = 20260714
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_sizetest_report.json"


def _weights(r: np.ndarray, alpha: float) -> np.ndarray:
    """Equal-budget relative-size weight g(r)=min(r^α, CAP), then renormalize to Σ=1 (equal gross exposure)."""
    g = np.minimum(np.power(r, alpha), CAP)
    s = g.sum()
    return g / s if s > 0 else g


def _metrics(w: np.ndarray, net_bp: np.ndarray, wallet: np.ndarray, fold: np.ndarray, ts: np.ndarray) -> dict:
    """All risk metrics on an exposure-normalized (Σw=1) book. Contributions in bp-of-total-book."""
    c = w * net_bp                                   # entry contribution; Σc = book mean net bp
    R = float(c.sum())
    key = np.array([f"{ww}|{ff}" for ww, ff in zip(wallet, fold)])
    uk, ki = np.unique(key, return_inverse=True)
    wf_c = np.bincount(ki, weights=c)                # per wallet-fold contribution (bp of book)
    k5 = max(1, int(np.ceil(0.05 * wf_c.size)))
    es5 = float(np.sort(wf_c)[:k5].mean())
    worst_wf = float(wf_c.min())
    pos = wf_c[wf_c > 0]
    top3w = float(np.sort(pos)[::-1][:3].sum() / pos.sum()) if pos.sum() > 0 else None
    # folds
    ufo, fi = np.unique(fold, return_inverse=True)
    fold_c = np.bincount(fi, weights=c)
    absf = np.abs(fold_c); fold_hhi = float(((absf / absf.sum()) ** 2).sum()) if absf.sum() > 0 else None
    eff_folds = float(1.0 / fold_hhi) if fold_hhi else None
    loo_fold_min = float((R - fold_c).min())         # leave-one-fold-out book return
    median_fold = float(np.median(fold_c))
    # drawdown on cumulative-by-exit contribution
    exit_ts = ts + H_MS
    o = np.argsort(exit_ts, kind="stable")
    eq = np.cumsum(c[o]); eq0 = np.r_[0.0, eq]
    maxdd = float((np.maximum.accumulate(eq0) - eq0).max())
    # capital usage: peak concurrent gross exposure (weights) vs total (=1)
    peak = cb._peak_exposure(np.asarray(ts, float), np.asarray(exit_ts, float), w)
    return {"mean_net_bp": R, "es5_wf_bp": es5, "worst_wf_bp": worst_wf,
            "top3_winner_share": top3w, "fold_hhi": fold_hhi, "eff_folds": eff_folds,
            "median_fold_bp": median_fold, "loo_fold_min_bp": loo_fold_min,
            "max_drawdown_bp": maxdd, "peak_concurrent_frac_of_total": float(peak),
            "n": int(net_bp.size), "n_wallet_folds": int(uk.size), "n_folds_positive": int((fold_c > 0).sum())}


def _paired_bootstrap(d: dict, alpha: float, rng) -> dict:
    """Wallet-cluster paired bootstrap of Δ = R_α − R_{α=0} on identical resampled entries."""
    r, net_bp, wallet = d["r"], d["net_bp"], d["wallet"]
    uw = np.unique(wallet)
    idx_by_w = {w: np.flatnonzero(wallet == w) for w in uw}
    dR = np.empty(N_BOOT); dES = np.empty(N_BOOT); dWF = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pick = rng.choice(uw, size=uw.size, replace=True)
        rows = np.concatenate([idx_by_w[w] for w in pick])
        rr = r[rows]; nb = net_bp[rows]
        wf = wallet[rows]; fo = d["fold"][rows]
        key = np.array([f"{a}|{c}" for a, c in zip(wf, fo)])
        _, ki = np.unique(key, return_inverse=True)
        for store, alp in ((0, alpha), (1, 0.0)):
            w = _weights(rr, alp); c = w * nb
            wf_c = np.bincount(ki, weights=c)
            k5 = max(1, int(np.ceil(0.05 * wf_c.size)))
            if store == 0:
                Ra, ESa, WFa = c.sum(), np.sort(wf_c)[:k5].mean(), wf_c.min()
            else:
                R0, ES0, WF0 = c.sum(), np.sort(wf_c)[:k5].mean(), wf_c.min()
        dR[b] = Ra - R0; dES[b] = ESa - ES0; dWF[b] = WFa - WF0
    def _ci(x):
        return [float(np.quantile(x, 0.025)), float(np.quantile(x, 0.975))]
    return {"delta_mean_bp": float(dR.mean()), "delta_mean_ci": _ci(dR), "p_delta_gt0": float((dR > 0).mean()),
            "delta_es5_bp": float(dES.mean()), "delta_es5_ci": _ci(dES),
            "delta_worst_wf_bp": float(dWF.mean()), "delta_worst_wf_ci": _ci(dWF)}


def _walk_forward_alpha(d: dict) -> dict:
    """Pick α on prior folds only (max prior-fold mean), score on the next fold; accumulate adaptive book.
    Compare adaptive vs fixed α=0 across the scored folds (fold 0 seeds with α=0)."""
    folds = sorted(set(d["fold"].tolist()))
    r, net_bp, fold = d["r"], d["net_bp"], d["fold"]
    def fold_R(alpha, fsel):
        m = np.isin(fold, list(fsel))
        if m.sum() == 0:
            return None
        w = _weights(r[m], alpha)
        return float((w * net_bp[m]).sum())
    chosen, adaptive_fold, base_fold = [], [], []
    for i, T in enumerate(folds):
        if i == 0:
            a = 0.0
        else:
            prior = folds[:i]
            scores = {al: np.mean([fold_R(al, [pf]) for pf in prior]) for al in ALPHAS}
            a = max(scores, key=scores.get)
        chosen.append(a)
        adaptive_fold.append(fold_R(a, [T]))
        base_fold.append(fold_R(0.0, [T]))
    scored = slice(1, len(folds))                       # folds actually chosen out-of-sample
    adap = np.array(adaptive_fold[scored], float); base = np.array(base_fold[scored], float)
    return {"chosen_alpha_by_fold": chosen, "adaptive_fold_bp": adaptive_fold, "baseline_fold_bp": base_fold,
            "adaptive_mean_oos_bp": float(adap.mean()), "baseline_mean_oos_bp": float(base.mean()),
            "adaptive_minus_baseline_bp": float((adap - base).mean()),
            "adaptive_worst_fold_bp": float(adap.min()), "baseline_worst_fold_bp": float(base.min()),
            "n_scored_folds": int(adap.size)}


def run() -> dict:
    con, sel, ep, midx, index, clips = _load()
    e = _evaluable(sel, ep, midx, index, clips)
    med = e["med"]; notl = e["notl"]
    good = (med > 0) & np.isfinite(med) & (notl > 0)
    d = {"r": (notl[good] / med[good]), "net_bp": e["net_bp"][good], "wallet": e["wallet"][good],
         "fold": e["fold"][good], "ts": e["ts"][good], "med": med[good], "notl": notl[good]}
    rng = np.random.default_rng(SEED)

    variants = {}
    for a in ALPHAS:
        w = _weights(d["r"], a)
        m = _metrics(w, d["net_bp"], d["wallet"], d["fold"], d["ts"])
        if a > 0:
            m["paired_vs_alpha0"] = _paired_bootstrap(d, a, np.random.default_rng(SEED + int(a * 100)))
        variants[f"alpha_{a}"] = m
    wf = _walk_forward_alpha(d)

    rep = {"config": {"horizon": HORIZON, "alphas": ALPHAS, "cap": CAP, "n_boot": N_BOOT, "seed": SEED,
                      "r_def": "entry_notl / strict-prior-median-notl (equal wallet budget)",
                      "exposure_normalized": True, "code_commit": basemod._git_commit(),
                      "n_evaluable": int(d["r"].size)},
           "variants": variants, "walk_forward_alpha": wf}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))

    print(f"\n=== DEFINITIVE relative-size test (equal budget, exposure-normalized, CAP={CAP}, n={d['r'].size}) ===")
    print(f"{'variant':>10} {'meanBp':>7} {'ES5':>7} {'worstWF':>7} {'t3win':>6} {'effFld':>6} {'medFld':>7} {'maxDD':>7} {'peak%':>6} {'f+':>3}")
    for name, m in variants.items():
        print(f"{name:>10} {_f(m['mean_net_bp']):>7} {_f(m['es5_wf_bp']):>7} {_f(m['worst_wf_bp']):>7} "
              f"{_f(m['top3_winner_share'],2):>6} {_f(m['eff_folds'],1):>6} {_f(m['median_fold_bp']):>7} "
              f"{_f(m['max_drawdown_bp']):>7} {_f(m['peak_concurrent_frac_of_total']*100,1):>6} {m['n_folds_positive']:>3}")
    print(f"\nPAIRED Δ vs α=0 (wallet-cluster bootstrap, {N_BOOT} reps):")
    for a in ALPHAS[1:]:
        p = variants[f"alpha_{a}"]["paired_vs_alpha0"]
        print(f"  α={a}: Δmean {p['delta_mean_bp']:+.1f}bp CI[{p['delta_mean_ci'][0]:+.1f},{p['delta_mean_ci'][1]:+.1f}] "
              f"P(Δ>0)={p['p_delta_gt0']:.2f} | ΔES5 {p['delta_es5_bp']:+.1f} | Δworst {p['delta_worst_wf_bp']:+.1f}")
    print(f"\nWALK-FORWARD α (selected on prior folds only): chosen={wf['chosen_alpha_by_fold']}")
    print(f"  adaptive OOS mean {wf['adaptive_mean_oos_bp']:+.1f}bp vs baseline(α=0) {wf['baseline_mean_oos_bp']:+.1f}bp "
          f"-> Δ {wf['adaptive_minus_baseline_bp']:+.1f}bp | adaptive worst-fold {wf['adaptive_worst_fold_bp']:+.1f} "
          f"vs {wf['baseline_worst_fold_bp']:+.1f} (n={wf['n_scored_folds']} scored folds)")
    print(f"-> {OUT}")
    return rep


def _f(x, nd=1):
    return "" if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(x, nd)


if __name__ == "__main__":
    run()
