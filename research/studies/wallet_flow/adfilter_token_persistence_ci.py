"""
adfilter_token_persistence_ci — POWER / CI addendum for the per-token reliability verdict.

The load-bearing quantity for the "per-coin R-driver" hypothesis is PERSISTENCE: does a coin's early-fold signal
IC predict its late-fold IC? The main script found rho=-0.226. This addendum (over-null gate compliance):
  - bootstrap CI on the cross-coin early->late IC rho (resample coins) at h in {2,4,6}
  - split-half at the OTHER cut (odd vs even folds) to rule out a single-split fluke
  - explicit positive-control note: the adaptive book DID lift taker +1.36bp IN-SAMPLE (early->early), so the
    OOS null is informative, not a blind instrument.
    .venv/bin/python -m research.studies.wallet_flow.adfilter_token_persistence_ci
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow.adfilter_token_reliability import rankdata, spearman

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
REB = 4

d = np.load(CACHE, allow_pickle=False)
R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
panel_month = d["panel_month"]; resid_alt = d["resid_alt"]; n_alt = int(d["n_alt"]); N = len(d["hours"])
folds = sorted(int(x) for x in d["folds"])
SIG = np.full((N, n_alt), np.nan); obs = set()
for i in range(len(R)):
    if np.isfinite(s_inf[i]): SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
base_hours = np.array(sorted(obs), dtype=np.int64)
month_of = {int(t): int(panel_month[int(t)]) for t in base_hours}

def coin_ic(c, hset, FVbp, phase=0):
    col_s = SIG[base_hours, c]; col_f = FVbp[base_hours, c]
    ok = np.isfinite(col_s) & np.isfinite(col_f) & np.array([month_of[int(t)] in hset for t in base_hours])
    idx = np.nonzero(ok)[0][phase::REB]
    return spearman(col_s[idx], col_f[idx], nmin=15)[0]

def boot_rho(a, b, nb=2000, seed=1):
    m = np.isfinite(a) & np.isfinite(b); a, b = a[m], b[m]; n = len(a)
    rng = np.random.default_rng(seed); st = []
    for _ in range(nb):
        p = rng.integers(0, n, n); r, _ = spearman(a[p], b[p], nmin=10)
        if np.isfinite(r): st.append(r)
    s = np.array(st)
    return float(np.median(s)), float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))

EARLY = set(folds[:4]); LATE = set(folds[4:])
ODD = set(folds[0::2]); EVEN = set(folds[1::2])
print(f"folds {folds}  early4={sorted(EARLY)} late3={sorted(LATE)}  odd={sorted(ODD)} even={sorted(EVEN)}\n")
print("=== Cross-coin persistence rho (IC_A vs IC_B), bootstrap 95% CI over coins ===")
for h in (2, 4, 6):
    FVbp = S0.fwd_sum(resid_alt, h) * 1e4
    for lab, A, B in (("early->late", EARLY, LATE), ("odd->even", ODD, EVEN)):
        icA = np.array([coin_ic(c, A, FVbp) for c in range(n_alt)])
        icB = np.array([coin_ic(c, B, FVbp) for c in range(n_alt)])
        r, _ = spearman(icA, icB, nmin=10)
        med, lo, hi = boot_rho(icA, icB)
        flag = "PERSISTENT" if lo > 0 else ("ANTI" if hi < 0 else "inconclusive/~0")
        print(f"  h={h} {lab:11s} rho={r:+.3f}  boot95[{lo:+.3f},{hi:+.3f}]  -> {flag}")
print("\nPositive control (from main run): adaptive shrink lifted taker net -0.578 -> +0.787 (+1.36bp) IN-SAMPLE")
print("early->early, so the instrument is NOT blind; its uniformly-negative OOS deltas are informative.")
