"""
kalman_swarm_filter_run — STEP 2-5: proper causal Kalman (est. Q/R), adaptive-gain KF, filter-in-rank/z space,
turnover-vs-net frontier, and the non-causal fixed-lag smoother diagnostic (upper bound). Every variant books
through the IDENTICAL CB cost engine on the frozen baseline rebalance grid; only the per-alt signal differs.

Design choice to ISOLATE the gain effect from carry-forward (which Result 11 proved inert): each filter EMITS a
value only at hours where the name was OBSERVED (same eligible set as baseline). The emitted value is the
filtered estimate. Gaps are propagated (phi^gap decay of the prior) but do not create new live names.
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import kalman_swarm_filter_lib as L

PHI = 0.579          # estimated state persistence (rho2/rho1, level space)
LAM = 0.405          # estimated signal fraction of observed variance
KSTAR = 0.365        # optimal steady-state gain from the Riccati fit


def _cs_standardize(SIG):
    """z-score each hour's observed cross-section (scale-free per-hour level)."""
    M = np.full_like(SIG, np.nan)
    for t in range(SIG.shape[0]):
        row = SIG[t]; fin = np.isfinite(row)
        if fin.sum() >= 3:
            mu = row[fin].mean(); sd = row[fin].std()
            M[t, fin] = (row[fin] - mu) / sd if sd > 0 else 0.0
    return M


def _cs_rank(SIG):
    """cross-sectional rank in [-0.5,0.5] each hour (scale-free, the actual book observable)."""
    M = np.full_like(SIG, np.nan)
    for t in range(SIG.shape[0]):
        row = SIG[t]; fin = np.isfinite(row); n = int(fin.sum())
        if n >= 2:
            vals = row[fin]
            rank = np.argsort(np.argsort(vals)).astype(float)
            M[t, fin] = rank / (n - 1) - 0.5
    return M


def kalman_causal(SIG, phi=PHI, lam=LAM, gain=None, adaptive=False, emit_observed_only=True):
    """Strictly-causal scalar Kalman per alt. Emits filtered estimate only at observed hours (default).
    Fixed-gain if `gain` given, else steady-state gain from (phi,lam); adaptive scales gain up on large
    innovations (normalized innovation |nu|/sqrt(S) > 1 => trust obs more)."""
    N, A = SIG.shape
    Rn = 1.0 - lam; Qn = lam * (1.0 - phi * phi)
    xhat = np.full(A, np.nan); Ppost = np.full(A, lam)
    last = np.full(A, -1, dtype=np.int64)
    out = np.full((N, A), np.nan)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs)
        idx = np.nonzero(has)[0]
        for a in idx:
            if last[a] < 0 or not np.isfinite(xhat[a]):
                xhat[a] = obs[a]; Ppost[a] = Rn      # init on first obs
            else:
                g = t - last[a]
                xp = (phi ** g) * xhat[a]
                Pp = (phi ** (2 * g)) * Ppost[a] + Qn * (0 if g <= 0 else sum(phi ** (2 * j) for j in range(g)))
                nu = obs[a] - xp
                S = Pp + Rn
                if gain is not None:
                    K = gain
                    if adaptive:
                        z = abs(nu) / np.sqrt(S) if S > 0 else 0.0
                        K = min(1.0, gain * (1.0 + 0.5 * max(0.0, z - 1.0)))  # innovation-driven gain boost
                    xhat[a] = xp + K * nu; Ppost[a] = (1 - K) * Pp
                else:
                    K = Pp / S
                    if adaptive:
                        z = abs(nu) / np.sqrt(S) if S > 0 else 0.0
                        K = min(1.0, K * (1.0 + 0.5 * max(0.0, z - 1.0)))
                    xhat[a] = xp + K * nu; Ppost[a] = (1 - K) * Pp
            last[a] = t
            out[t, a] = xhat[a]
    return out


def fixed_lag_smoother(SIG, phi=PHI, lam=LAM, lag=2):
    """NON-CAUSAL diagnostic: two-sided smoother. Uses future obs up to `lag` hours ahead. CANNOT be deployed;
    only bounds how much any filter could recover. Implemented as forward Kalman + limited backward pass per alt."""
    N, A = SIG.shape
    Rn = 1.0 - lam; Qn = lam * (1.0 - phi * phi)
    out = np.full((N, A), np.nan)
    for a in range(A):
        col = SIG[:, a]; obs_t = np.nonzero(np.isfinite(col))[0]
        if len(obs_t) < 3:
            out[obs_t, a] = col[obs_t]; continue
        # forward filter on the observed subsequence (treat consecutive obs as unit steps w/ gap propagation)
        n = len(obs_t)
        xf = np.zeros(n); Pf = np.zeros(n); xp_ = np.zeros(n); Pp_ = np.zeros(n)
        xf[0] = col[obs_t[0]]; Pf[0] = Rn
        for i in range(1, n):
            g = obs_t[i] - obs_t[i - 1]
            xp = (phi ** g) * xf[i - 1]
            Pp = (phi ** (2 * g)) * Pf[i - 1] + Qn * sum(phi ** (2 * j) for j in range(g))
            xp_[i] = xp; Pp_[i] = Pp
            K = Pp / (Pp + Rn)
            xf[i] = xp + K * (col[obs_t[i]] - xp); Pf[i] = (1 - K) * Pp
        # fixed-lag RTS: smooth using up to `lag` future observed points
        xs = xf.copy()
        for i in range(n):
            xi = xf[i]; Pi = Pf[i]
            jmax = min(n - 1, i + lag)
            # RTS backward recursion truncated to window [i, jmax]
            xtmp = xf[jmax]; Ptmp = Pf[jmax]
            for j in range(jmax, i, -1):
                g = obs_t[j] - obs_t[j - 1]
                Pp = Pp_[j]
                C = Pf[j - 1] * (phi ** g) / Pp if Pp > 0 else 0.0
                xtmp = xf[j - 1] + C * (xtmp - xp_[j]); Ptmp = Pf[j - 1] + C * (Ptmp - Pp) * C
            xs[i] = xtmp
        out[obs_t, a] = xs
    return out


def show(P, tag, m, regime, base):
    cell = L.book_from_matrix(P, m, regime)
    print(f"  {tag:38s} {L.fmt_focus(cell)}")
    return cell


def main():
    P = L.load_panel()
    SIG = P["SIG"]
    Z = _cs_standardize(SIG)
    RK = _cs_rank(SIG)

    for regime in ("all", "mid"):
        print("=" * 120)
        print(f"REGIME = {regime.upper()}   (focus: tk_smallclip, tk_impact, mk_a30, mk_a50; '*'=CI>0, '-'=CI<0)")
        print("=" * 120)
        base = show(P, "BASELINE (no smoothing)", SIG, regime, None)

        print("\n-- proper causal Kalman, LEVEL space, gain from estimated Q/R (K*=0.365) --")
        show(P, "KF est-gain (K*~0.365)", kalman_causal(SIG, gain=None), regime, base)
        show(P, "KF adaptive-gain (innovation-driven)", kalman_causal(SIG, gain=None, adaptive=True), regime, base)

        print("\n-- filter in the RIGHT space: z-scored / rank observable --")
        show(P, "KF est-gain on Z (cs-standardized)", kalman_causal(Z, gain=None), regime, base)
        show(P, "KF est-gain on RANK", kalman_causal(RK, gain=None), regime, base)
        show(P, "KF adaptive on RANK", kalman_causal(RK, gain=None, adaptive=True), regime, base)

        print("\n-- turnover-vs-net FRONTIER: fixed-gain sweep on LEVEL (K=1 is baseline) --")
        for K in (1.0, 0.8, 0.6, 0.5, 0.365, 0.25, 0.15):
            m = SIG if K >= 1.0 else kalman_causal(SIG, gain=K)
            show(P, f"KF fixed gain K={K:.3f}", m, regime, base)

        print("\n-- NON-CAUSAL fixed-lag SMOOTHER (diagnostic upper bound; NOT deployable) --")
        for lag in (1, 2, 4):
            show(P, f"RTS smoother lag={lag} (LEVEL)", fixed_lag_smoother(SIG, lag=lag), regime, base)
        print()


if __name__ == "__main__":
    main()
