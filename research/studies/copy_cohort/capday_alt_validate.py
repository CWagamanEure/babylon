"""Alt EXTERNAL VALIDATION of the frozen scale-only entry rule (H1/H2 per ALT_VALIDATION_PREREG.md).

Reads ONLY: `frozen_alt_universe.json` (majors-frozen selection + scale/LARGE) and `alt_episodes/` (the
wallets' ALT opening-taker 8h markout). An alt entry counts iff its wallet is in that test-month's frozen
cohort; LARGE/SMALL is inherited from the frozen file (never recomputed on alts).

PRIMARY (gross 8h markout, wallet-equal = per wallet-fold mean → mean over wallet-folds; wallet-cluster CI):
  H1: μ(large, alts) > 0
  H2: μ(large) − μ(small) > 0     ← the key one (paired wallet-cluster bootstrap); replication of the
                                     large−small ranking validates the scale signal even if the alt book is
                                     negative in absolute terms (harder alt execution).
Cost: primary is GROSS; a taker-cost haircut is reported as a sensitivity (alt taker cost is higher/uncertain).
SECONDARIES (reported, never used to re-tune): per-coin (no post-hoc removal), leave-wallet-out,
leave-coin-out, liquidity buckets. Position-consensus secondary needs an alt holdings build (deferred; noted).

    python -m research.studies.copy_cohort.capday_alt_validate
"""
from __future__ import annotations

import glob
import json

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from . import capday_book as cb
from . import lake

FROZEN = REPO_ROOT / "data" / "derived" / "copy_cohort" / "frozen_alt_universe.json"
ALT_EP = str(REPO_ROOT / "data" / "derived" / "copy_cohort" / "alt_episodes" / "month=*" / "part.parquet")
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_alt_validation_report.json"
N_BOOT = 2000
SEED = 20260714
COST_SENS_BP = (0.0, 5.0, 10.0)          # gross + alt taker-cost haircuts
MIN_LARGE_ENTRIES, MIN_FOLDS, MIN_LARGE_WALLETS = 40, 3, 5


def _load():
    con = _connect()
    uni = json.loads(FROZEN.read_text())["universe"]
    # (wallet, fold_month) -> large bool ; membership set
    large_of, member = {}, set()
    for T, u in uni.items():
        for w, m in u["members"].items():
            member.add((w, int(T))); large_of[(w, int(T))] = bool(m["large"])
    d = con.execute(f"""SELECT wallet, coin, fold_month AS fold, dir_sign, notl, raw_markout_8h AS mk
        FROM read_parquet('{ALT_EP}')
        WHERE fold_month > 0 AND raw_markout_8h IS NOT NULL""").fetchnumpy()
    w = d["wallet"].astype(str); fold = d["fold"].astype(int)
    keep = np.array([(w[i], fold[i]) in member for i in range(w.size)])
    out = {k: d[k][keep] for k in ("coin",)}
    out["wallet"] = w[keep]; out["fold"] = fold[keep]
    out["mk"] = np.asarray(d["mk"][keep], float); out["notl"] = np.asarray(d["notl"][keep], float)
    out["large"] = np.array([large_of[(out["wallet"][i], out["fold"][i])] for i in range(out["wallet"].size)])
    out["coin"] = out["coin"].astype(str)
    return out


def _wallet_equal(mk, wallet, fold):
    """Per wallet-fold mean → mean over wallet-folds; + wallet-clustered CI (cluster on wallet)."""
    if mk.size == 0:
        return {"point_bp": None, "n": 0, "n_wf": 0, "n_wallets": 0}
    key = np.array([f"{w}|{f}" for w, f in zip(wallet, fold)])
    uk, ki = np.unique(key, return_inverse=True)
    wf_mean = np.bincount(ki, weights=mk) / np.bincount(ki)
    wf_wallet = np.array([wallet[np.flatnonzero(ki == u)[0]] for u in range(uk.size)])
    ci = cb._wallet_equal_ci(wf_mean, wf_wallet)      # wallet-clustered over wallet-folds
    return {"point_bp": float(wf_mean.mean()), "ci": [ci.get("ci_lo"), ci.get("ci_hi")],
            "n": int(mk.size), "n_wf": int(uk.size), "n_wallets": int(np.unique(wallet).size)}


def _pseudo(pick, idx):
    """Per-draw pseudo-cluster wallet labels ('wallet#j').

    AUDIT FIX 2026-07-17 (multiplicity-preserving cluster bootstrap): duplicate wallet
    picks previously collapsed in np.unique(wallet|fold) -> bootstrap variance understated.
    Tagging each draw as its own pseudo-cluster preserves multiplicity (ksweep-equivalent)."""
    return np.concatenate([np.full(idx[x].size, f"{x}#{j}") for j, x in enumerate(pick)])


def _paired_h2(e, rng):
    """Paired wallet-cluster bootstrap of Δ = R(large) − R(small)."""
    w = e["wallet"]; uw = np.unique(w); idx = {x: np.flatnonzero(w == x) for x in uw}
    dR = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pick = rng.choice(uw, size=uw.size, replace=True)
        rows = np.concatenate([idx[x] for x in pick])
        wal = _pseudo(pick, idx)                        # multiplicity-preserving labels
        mk = e["mk"][rows]; fold = e["fold"][rows]; large = e["large"][rows]
        def R(mask):
            if mask.sum() == 0:
                return np.nan
            key = np.array([f"{a}|{c}" for a, c in zip(wal[mask], fold[mask])])
            _, ki = np.unique(key, return_inverse=True)
            return (np.bincount(ki, weights=mk[mask]) / np.bincount(ki)).mean()
        dR[b] = R(large) - R(~large)
    dR = dR[np.isfinite(dR)]
    return {"delta_bp": float(dR.mean()), "ci": [float(np.quantile(dR, .025)), float(np.quantile(dR, .975))],
            "p_gt0": float((dR > 0).mean()), "n_boot_valid": int(dR.size)}


def _h1_bootstrap(mk, wallet, fold, rng):
    """Wallet-cluster bootstrap of R(large) for H1 (>0?)."""
    uw = np.unique(wallet); idx = {x: np.flatnonzero(wallet == x) for x in uw}
    R = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pick = rng.choice(uw, size=uw.size, replace=True)
        rows = np.concatenate([idx[x] for x in pick])
        wal = _pseudo(pick, idx)                        # multiplicity-preserving labels
        key = np.array([f"{a}|{c}" for a, c in zip(wal, fold[rows])])
        _, ki = np.unique(key, return_inverse=True)
        R[b] = (np.bincount(ki, weights=mk[rows]) / np.bincount(ki)).mean()
    return {"mean_bp": float(R.mean()), "ci": [float(np.quantile(R, .025)), float(np.quantile(R, .975))],
            "p_gt0": float((R > 0).mean())}


def run():
    e = _load()
    nlarge = int(e["large"].sum()); nfold = int(np.unique(e["fold"]).size)
    nlw = int(np.unique(e["wallet"][e["large"]]).size)
    coverage_ok = (nlarge >= MIN_LARGE_ENTRIES and nfold >= MIN_FOLDS and nlw >= MIN_LARGE_WALLETS)
    L = {k: e[k][e["large"]] for k in ("mk", "wallet", "fold", "coin")}
    S = {k: e[k][~e["large"]] for k in ("mk", "wallet", "fold", "coin")}

    rep = {"config": {"metric": "gross wallet-equal 8h markout bp", "cost_sens_bp": COST_SENS_BP,
                      "n_boot": N_BOOT, "seed": SEED, "code_commit": lake.git_describe(),
                      "prereg": "ALT_VALIDATION_PREREG.md",
                      "audit_2026_07_17": "multiplicity-preserving cluster boot"},
           "coverage": {"n_evaluable": int(e["mk"].size), "n_large_entries": nlarge,
                        "n_small_entries": int((~e["large"]).sum()), "n_folds": nfold,
                        "n_large_wallets": nlw, "n_coins": int(np.unique(e["coin"]).size),
                        "adequate": coverage_ok,
                        "thresholds": {"min_large_entries": MIN_LARGE_ENTRIES, "min_folds": MIN_FOLDS,
                                       "min_large_wallets": MIN_LARGE_WALLETS}}}
    # PRIMARY H1 / H2 (gross)
    rep["H1_large_gt0"] = {**_wallet_equal(L["mk"], L["wallet"], L["fold"]),
                           "bootstrap": _h1_bootstrap(L["mk"], L["wallet"], L["fold"], np.random.default_rng(SEED))}
    rep["small"] = _wallet_equal(S["mk"], S["wallet"], S["fold"])
    rep["H2_large_minus_small"] = _paired_h2(e, np.random.default_rng(SEED + 1))
    # cost sensitivity (subtract flat bp from every entry)
    rep["cost_sensitivity"] = {}
    for c in COST_SENS_BP:
        rep["cost_sensitivity"][f"cost_{c}bp"] = {
            "large": _wallet_equal(L["mk"] - c, L["wallet"], L["fold"])["point_bp"],
            "small": _wallet_equal(S["mk"] - c, S["wallet"], S["fold"])["point_bp"]}
    # SECONDARIES
    # per-fold H2
    fb = {}
    for f in sorted(set(e["fold"].tolist())):
        m = e["fold"] == f
        rl = _wallet_equal(L["mk"][L["fold"] == f], L["wallet"][L["fold"] == f], L["fold"][L["fold"] == f])["point_bp"]
        rs = _wallet_equal(S["mk"][S["fold"] == f], S["wallet"][S["fold"] == f], S["fold"][S["fold"] == f])["point_bp"]
        fb[str(f)] = {"large": rl, "small": rs, "delta": (rl - rs) if (rl is not None and rs is not None) else None,
                      "n_large": int((L["fold"] == f).sum())}
    rep["fold_by_fold_H2"] = fb
    nwin = sum(1 for v in fb.values() if v["delta"] is not None and v["delta"] > 0)
    rep["folds_H2_positive"] = f"{nwin}/{sum(1 for v in fb.values() if v['delta'] is not None)}"
    # per-coin (descriptive, NO post-hoc removal)
    percoin = {}
    for c in sorted(set(e["coin"].tolist())):
        m = e["coin"] == c
        if m.sum() < 5:
            continue
        rl = _wallet_equal(e["mk"][m & e["large"]], e["wallet"][m & e["large"]], e["fold"][m & e["large"]])
        percoin[c] = {"large_bp": rl["point_bp"], "n_large": rl["n"], "n_total": int(m.sum())}
    rep["per_coin_large"] = percoin
    # leave-wallet-out / leave-coin-out on H2 point
    def h2_point(mask=None):
        ee = e if mask is None else {k: e[k][mask] for k in e}
        rl = _wallet_equal(ee["mk"][ee["large"]], ee["wallet"][ee["large"]], ee["fold"][ee["large"]])["point_bp"]
        rs = _wallet_equal(ee["mk"][~ee["large"]], ee["wallet"][~ee["large"]], ee["fold"][~ee["large"]])["point_bp"]
        return (rl - rs) if (rl is not None and rs is not None) else None
    base_h2 = h2_point()
    lwo = [h2_point(e["wallet"] != w) for w in np.unique(e["wallet"][e["large"]])]
    lco = [h2_point(e["coin"] != c) for c in np.unique(e["coin"])]
    lwo = [x for x in lwo if x is not None]; lco = [x for x in lco if x is not None]
    rep["robustness"] = {"H2_point_bp": base_h2,
                         "leave_wallet_out_H2_min": float(np.min(lwo)) if lwo else None,
                         "leave_coin_out_H2_min": float(np.min(lco)) if lco else None}

    OUT.write_text(json.dumps(rep, indent=2, default=str))
    cov = rep["coverage"]
    print(f"\n=== ALT external validation (frozen scale-only) ===")
    print(f"coverage: {cov['n_evaluable']:,} evaluable alt entries | large {cov['n_large_entries']} "
          f"({cov['n_large_wallets']} wal) / small {cov['n_small_entries']} | {cov['n_folds']} folds | "
          f"{cov['n_coins']} coins | adequate={cov['adequate']}")
    h1 = rep["H1_large_gt0"]; bs = h1["bootstrap"]; s = rep["small"]; h2 = rep["H2_large_minus_small"]
    print(f"H1 large: {h1['point_bp']:+.1f}bp wal-CI[{_f(h1['ci'][0])},{_f(h1['ci'][1])}] "
          f"boot[{bs['ci'][0]:+.1f},{bs['ci'][1]:+.1f}] P(>0)={bs['p_gt0']:.2f}  (n={h1['n']}, wf={h1['n_wf']})")
    print(f"   small: {s['point_bp']:+.1f}bp (n={s['n']})")
    print(f"H2 large−small: Δ={h2['delta_bp']:+.1f}bp CI[{h2['ci'][0]:+.1f},{h2['ci'][1]:+.1f}] "
          f"P(Δ>0)={h2['p_gt0']:.2f} | folds+ {rep['folds_H2_positive']}")
    print(f"cost sens (large): " + " ".join(f"{k}={_f(v['large'])}" for k, v in rep["cost_sensitivity"].items()))
    r = rep["robustness"]
    print(f"robustness: H2 {_f(r['H2_point_bp'])} | leave-wallet-out min {_f(r['leave_wallet_out_H2_min'])} | "
          f"leave-coin-out min {_f(r['leave_coin_out_H2_min'])}")
    print(f"-> {OUT}")
    return rep


def _f(x, nd=1):
    return "" if x is None else round(x, nd)


if __name__ == "__main__":
    run()
