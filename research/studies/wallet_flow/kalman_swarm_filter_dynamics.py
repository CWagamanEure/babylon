"""
kalman_swarm_filter_dynamics — STEP 1: estimate the per-alt signal dynamics from the data and derive the
OPTIMAL steady-state Kalman gain. Answers: is the signal a persistent latent state (gain << 1 helps) or a
fast/near-white process (optimal gain ~ 1 = the no-smoothing baseline)?

Model per alt (hour axis, consecutive OBSERVED hours):  local-level / AR(1)+noise
    y_t = x_t + e_t ,  Var(e)=Rn   (observation noise)
    x_t = phi * x_{t-1} + w_t ,  Var(w)=Qn   (latent state = "cohort conviction")
If observed = state + white noise:  rho_y(k) = phi^k * lambda,  lambda = Var(x)/Var(y) (signal fraction).
  -> phi_hat  = rho(2)/rho(1)      (state persistence, geometric-decay ratio)
  -> lambda   = rho(1)/phi_hat     (fraction of observed variance that is true state)
Given (phi, lambda) the steady-state Kalman gain solves the scalar Riccati recursion.
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import kalman_swarm_filter_lib as L


def autocorr_gapaware(SIG, kmax=8, standardize_cs=False):
    """Per-alt lag-k autocorrelation using only pairs (t, t+k) both observed. Pools across alts.
    If standardize_cs: z-score each hour's cross-section first (rank-like level, scale-free per hour)."""
    N, A = SIG.shape
    M = SIG.copy()
    if standardize_cs:
        for t in range(N):
            row = M[t]; fin = np.isfinite(row)
            if fin.sum() >= 3:
                mu = row[fin].mean(); sd = row[fin].std()
                if sd > 0:
                    M[t, fin] = (row[fin] - mu) / sd
    rhos = []
    for k in range(0, kmax + 1):
        xs, ys = [], []
        a = M[:-k] if k > 0 else M
        b = M[k:] if k > 0 else M
        both = np.isfinite(a) & np.isfinite(b)
        xa = a[both]; xb = b[both]
        if len(xa) < 100:
            rhos.append(np.nan); continue
        # centered correlation
        xa = xa - xa.mean(); xb = xb - xb.mean()
        denom = np.sqrt((xa * xa).sum() * (xb * xb).sum())
        rhos.append(float((xa * xb).sum() / denom) if denom > 0 else np.nan)
    return np.array(rhos)


def steady_state_gain(phi, lam, iters=2000):
    """Steady-state scalar Kalman gain for x_t=phi x_{t-1}+w, y_t=x_t+e. Normalize Var(y)=1:
    Var(x)=lam, Rn=1-lam, Qn=lam*(1-phi^2). Returns (K, halflife_state_hours)."""
    lam = min(max(lam, 1e-6), 0.999999)
    Rn = 1.0 - lam
    Qn = lam * (1.0 - phi * phi)
    P = lam  # init at stationary state var
    K = 1.0
    for _ in range(iters):
        Ppred = phi * phi * P + Qn
        K = Ppred / (Ppred + Rn)
        P = (1.0 - K) * Ppred
    hl = np.log(0.5) / np.log(abs(phi)) if 0 < abs(phi) < 1 else (np.inf if abs(phi) >= 1 else 0.0)
    return float(K), float(hl)


def main():
    P = L.load_panel()
    SIG = P["SIG"]
    print("=" * 90)
    print("SIGNAL DYNAMICS — per-alt, hour axis, gap-aware autocorrelation (pooled across 45 alts)")
    print("=" * 90)

    for label, std in [("LEVEL (s_inf, residualized)", False), ("CS-STANDARDIZED per hour (z-space)", True)]:
        rho = autocorr_gapaware(SIG, kmax=8, standardize_cs=std)
        print(f"\n[{label}]")
        print("  lag(h):   " + "  ".join(f"{k:>6d}" for k in range(0, 9)))
        print("  rho:      " + "  ".join(f"{r:+6.3f}" if np.isfinite(r) else "   nan" for r in rho))
        r1, r2 = rho[1], rho[2]
        if np.isfinite(r1) and np.isfinite(r2) and r1 > 0 and r2 > 0:
            phi = r2 / r1
            lam = min(r1 / phi, 0.999)
            K, hl_state = steady_state_gain(phi, lam)
            # observed-signal half-life (how fast rho decays in k): rho(k) ~ lam*phi^k
            hl_obs = np.log(0.5) / np.log(phi) if 0 < phi < 1 else np.inf
            print(f"  -> phi_hat (state persistence, rho2/rho1)        = {phi:.3f}")
            print(f"  -> lambda  (signal fraction of obs var, rho1/phi)= {lam:.3f}  (obs-noise fraction {1-lam:.3f})")
            print(f"  -> state half-life                               = {hl_state:.2f} h")
            print(f"  -> OPTIMAL steady-state Kalman gain K*            = {K:.3f}")
            print(f"     (K*=1 => trust each new obs fully = NO-SMOOTHING baseline is optimal)")
        else:
            print("  -> rho too small/negative to fit a persistent-state model (near-white signal).")

    # direct 'survival' read to compare with gap-lag decay (67% @1h, 33% @2h)
    rho = autocorr_gapaware(SIG, kmax=4, standardize_cs=False)
    if np.isfinite(rho[1]):
        print("\n[cross-check vs gap-lag decay ~67%@1h, ~33%@2h]")
        print(f"  observed rho(1h)={rho[1]:+.3f}  rho(2h)={rho[2]:+.3f}  ratio(2/1)={rho[2]/rho[1] if rho[1] else float('nan'):.3f}")

    # what gain does a given EMA alpha correspond to, and what half-life of memory does it impose?
    print("\n[EMA memory reference] alpha -> effective averaging window / imposed memory half-life")
    for a in (1.0, 0.6, 0.35, 0.2):
        hl = np.log(0.5) / np.log(1 - a) if a < 1 else 0.0
        print(f"  alpha={a:>4}: EMA memory half-life {hl:5.2f} h   (span ~{(2-a)/a:4.1f} h)")


if __name__ == "__main__":
    main()
