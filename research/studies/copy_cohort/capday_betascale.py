"""Step 3e — BETWEEN-wallet SCALE test (β): does typical wallet scale identify the informed wallets?

The within-wallet clip-size test (capday_sizetest, α) was rejected. But the +16.7bp book died under EQUAL
wallet budget, which the user notes is NOT proof that wealth accidentally made the edge — typical wallet scale
may IDENTIFY more-informed / institution-like / low-frequency discretionary wallets whose trades carry more
economic significance. That is a BETWEEN-wallet selection axis, never cleanly tested.

Design (frozen, leakage-safe): give each wallet-FOLD a fixed formation weight w_i ∝ scale_i^β, where
scale_i = the wallet's strict-prior median opening notional as of the formation cutoff (its expanding median
at its first in-test entry). Keep each wallet's trades EQUAL-sized within the wallet and split the wallet's
budget across them (so the wallet-fold — not the trade count — is the exposure unit); normalize total gross
exposure to 1 (comparable ES / tails). This isolates BETWEEN-wallet scale from within-wallet clip size (α,
rejected) and from activity (trade count).

  β∈{0,0.25,0.5,1}.  β=0 = wallet-fold-equal (the anti-over-carry book, ~−7bp).  β=1 ∝ scale.
  Inference: PAIRED Δ=R_β−R_{β=0}, wallet-cluster bootstrap; walk-forward β (prior folds only) vs β=0.
  Plus: sort wallet-folds into median-notional QUARTILES and report equal-weight OOS 8h net bp within each
  (wallet-clustered CI). If only the larger-scale quartiles are positive, THAT is the selection edge.

    python -m research.studies.copy_cohort.capday_betascale
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from . import base as basemod
from . import capday_book as cb
from .capday_sizecurve import _load, _evaluable
from .capday_sizetest import _metrics, N_BOOT, SEED

BETAS = (0.0, 0.25, 0.5, 1.0)
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_betascale_report.json"


def _prep(d: dict) -> dict:
    """Per-entry: scale_i (wallet-fold formation median, leakage-safe) and n_wf (wallet-fold entry count)."""
    wallet, fold, ts, med = d["wallet"], d["fold"], d["ts"], d["med"]
    key = np.array([f"{w}|{f}" for w, f in zip(wallet, fold)])
    uk, ki = np.unique(key, return_inverse=True)
    scale = np.empty(uk.size); n_wf = np.bincount(ki).astype(float)
    for u in range(uk.size):
        ii = np.flatnonzero(ki == u)
        scale[u] = float(med[ii[np.argmin(ts[ii])]])         # expanding prior median at first in-test entry
    return {"key": key, "ki": ki, "scale_per_wf": scale, "n_wf_per_wf": n_wf,
            "scale": scale[ki], "n_wf": n_wf[ki], **d}


def _weights(scale: np.ndarray, n_wf: np.ndarray, beta: float) -> np.ndarray:
    g = np.power(scale, beta) / n_wf                         # wallet-fold budget ∝ scale^β, split within
    s = g.sum()
    return g / s if s > 0 else g


def _paired_bootstrap(p: dict, beta: float, rng) -> dict:
    scale, n_wf, net_bp, wallet, fold = p["scale"], p["n_wf"], p["net_bp"], p["wallet"], p["fold"]
    uw = np.unique(wallet); idx_by_w = {w: np.flatnonzero(wallet == w) for w in uw}
    dR = np.empty(N_BOOT); dWF = np.empty(N_BOOT)
    for b in range(N_BOOT):
        rows = np.concatenate([idx_by_w[w] for w in rng.choice(uw, size=uw.size, replace=True)])
        sc, nw, nb = scale[rows], n_wf[rows], net_bp[rows]
        key = np.array([f"{a}|{c}" for a, c in zip(wallet[rows], fold[rows])])
        _, ki = np.unique(key, return_inverse=True)
        for store, be in ((0, beta), (1, 0.0)):
            w = _weights(sc, nw, be); c = w * nb
            wf_c = np.bincount(ki, weights=c)
            if store == 0:
                Ra, WFa = c.sum(), wf_c.min()
            else:
                R0, WF0 = c.sum(), wf_c.min()
        dR[b] = Ra - R0; dWF[b] = WFa - WF0
    return {"delta_mean_bp": float(dR.mean()), "delta_mean_ci": [float(np.quantile(dR, .025)), float(np.quantile(dR, .975))],
            "p_delta_gt0": float((dR > 0).mean()), "delta_worst_wf_bp": float(dWF.mean())}


def _walk_forward(p: dict) -> dict:
    folds = sorted(set(p["fold"].tolist()))
    scale, n_wf, net_bp, fold = p["scale"], p["n_wf"], p["net_bp"], p["fold"]
    def fold_R(beta, T):
        m = fold == T
        if m.sum() == 0:
            return None
        return float((_weights(scale[m], n_wf[m], beta) * net_bp[m]).sum())
    chosen, adap, base = [], [], []
    for i, T in enumerate(folds):
        if i == 0:
            b = 0.0
        else:
            scores = {be: np.mean([fold_R(be, pf) for pf in folds[:i]]) for be in BETAS}
            b = max(scores, key=scores.get)
        chosen.append(b); adap.append(fold_R(b, T)); base.append(fold_R(0.0, T))
    a = np.array(adap[1:], float); bs = np.array(base[1:], float)
    return {"chosen_beta_by_fold": chosen, "adaptive_fold_bp": adap, "baseline_fold_bp": base,
            "adaptive_mean_oos_bp": float(a.mean()), "baseline_mean_oos_bp": float(bs.mean()),
            "adaptive_minus_baseline_bp": float((a - bs).mean()),
            "adaptive_worst_fold_bp": float(a.min()), "baseline_worst_fold_bp": float(bs.min())}


def _quartiles(p: dict) -> dict:
    """Wallet-folds into scale quartiles; equal-weight (per wallet-fold mean) OOS 8h net bp, wallet-clustered."""
    scale_wf = p["scale_per_wf"]; ki = p["ki"]; net_bp = p["net_bp"]; wallet = p["wallet"]
    wf_mean = np.bincount(ki, weights=net_bp) / np.bincount(ki)          # per wallet-fold mean net bp
    wf_wallet = np.array([wallet[np.flatnonzero(ki == u)[0]] for u in range(scale_wf.size)])
    edges = np.quantile(scale_wf, [0.25, 0.5, 0.75])
    q = np.searchsorted(edges, scale_wf, side="right")
    out = {}
    for qi in range(4):
        m = q == qi
        vals = wf_mean[m]; wals = wf_wallet[m]
        ci = cb._wallet_equal_ci(vals, wals)                            # cluster by wallet across wallet-folds
        out[f"Q{qi+1}"] = {"n_wallet_folds": int(m.sum()),
                           "scale_range_usd": [float(scale_wf[m].min()), float(scale_wf[m].max())] if m.any() else None,
                           "equal_weight_net_bp": float(vals.mean()) if vals.size else None,
                           "wallet_ci": [ci.get("ci_lo"), ci.get("ci_hi")], "n_wallets": ci.get("n_wallets")}
    return out


def run() -> dict:
    con, sel, ep, midx, index, clips = _load()
    e = _evaluable(sel, ep, midx, index, clips)
    med = e["med"]; good = (med > 0) & np.isfinite(med)
    d = {k: e[k][good] for k in ("wallet", "coin", "fold", "ts", "notl", "med", "net_bp")}
    p = _prep(d)
    rng = np.random.default_rng(SEED)

    variants = {}
    for b in BETAS:
        w = _weights(p["scale"], p["n_wf"], b)
        m = _metrics(w, p["net_bp"], p["wallet"], p["fold"], p["ts"])
        if b > 0:
            m["paired_vs_beta0"] = _paired_bootstrap(p, b, np.random.default_rng(SEED + int(b * 100)))
        variants[f"beta_{b}"] = m
    wf = _walk_forward(p)
    quart = _quartiles(p)

    rep = {"config": {"betas": BETAS, "n_boot": N_BOOT, "seed": SEED,
                      "scale_def": "wallet-fold strict-prior median opening notional at first in-test entry",
                      "weight": "w_i ∝ scale^β / n_wf (wallet-fold budget unit), Σ normalized",
                      "code_commit": basemod._git_commit(), "n_evaluable": int(p["net_bp"].size)},
           "variants": variants, "walk_forward_beta": wf, "scale_quartiles": quart}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))

    print(f"\n=== BETWEEN-WALLET SCALE test (β), equal-within-wallet, exposure-normalized, n={p['net_bp'].size} ===")
    print(f"{'variant':>9} {'meanBp':>7} {'ES5':>7} {'worstWF':>7} {'t3win':>6} {'effFld':>6} {'medFld':>7} {'f+':>3}")
    for name, m in variants.items():
        print(f"{name:>9} {_f(m['mean_net_bp']):>7} {_f(m['es5_wf_bp']):>7} {_f(m['worst_wf_bp']):>7} "
              f"{_f(m['top3_winner_share'],2):>6} {_f(m['eff_folds'],1):>6} {_f(m['median_fold_bp']):>7} {m['n_folds_positive']:>3}")
    print(f"\nPAIRED Δ vs β=0 (wallet-cluster bootstrap, {N_BOOT} reps):")
    for b in BETAS[1:]:
        pb = variants[f"beta_{b}"]["paired_vs_beta0"]
        print(f"  β={b}: Δmean {pb['delta_mean_bp']:+.1f}bp CI[{pb['delta_mean_ci'][0]:+.1f},{pb['delta_mean_ci'][1]:+.1f}] "
              f"P(Δ>0)={pb['p_delta_gt0']:.2f} | Δworst {pb['delta_worst_wf_bp']:+.1f}")
    print(f"\nWALK-FORWARD β (prior folds only): chosen={wf['chosen_beta_by_fold']}")
    print(f"  adaptive OOS {wf['adaptive_mean_oos_bp']:+.1f}bp vs baseline(β=0) {wf['baseline_mean_oos_bp']:+.1f}bp "
          f"-> Δ {wf['adaptive_minus_baseline_bp']:+.1f}bp")
    print(f"\nSCALE QUARTILES (equal-weight per wallet-fold, wallet-clustered CI):")
    for qk, qv in quart.items():
        ci = qv["wallet_ci"]; sr = qv["scale_range_usd"]
        print(f"  {qk}: net {_f(qv['equal_weight_net_bp']):>7}bp CI[{_f(ci[0]):>7},{_f(ci[1]):>7}] "
              f"nWF={qv['n_wallet_folds']:>2} scale=${_f(sr[0],0)}-${_f(sr[1],0)}")
    print(f"-> {OUT}")
    return rep


def _f(x, nd=1):
    return "" if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(x, nd)


if __name__ == "__main__":
    run()
