"""
kalman_swarm_filter_frontier — STEP 6 (the decisive one): does Result 11's coarse alpha grid (1.0->0.6->0.35)
step OVER a light-smoothing optimum? Fine-grid BOTH filter families (pure-EMA phi=1 = Result 11's exact filter;
phi-aware Kalman K), test phi-sensitivity of the K=0.8 candidate, and print full FOCUS + per-fold detail.

Finding: yes. Both families have a shallow interior optimum at LIGHT smoothing (EMA alpha~0.90, Kalman K~0.80)
that Result 11 never sampled. Turnover is ~flat across it -> the gain is DENOISING (better cross-sectional IC),
not turnover reduction. Robust across phi in [0.3,0.85], both regimes, 7/7 folds on the maker leg.
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import kalman_swarm_filter_lib as L
from research.studies.wallet_flow import kalman_swarm_filter_run as F


def pure_ema(SIG, alpha):
    """Result 11's filter: EMA with phi=1 (undecayed memory), emitted only at observed hours."""
    N, A = SIG.shape; prev = np.full(A, np.nan); out = np.full((N, A), np.nan)
    for t in range(N):
        obs = SIG[t]
        for a in np.nonzero(np.isfinite(obs))[0]:
            prev[a] = obs[a] if not np.isfinite(prev[a]) else alpha * obs[a] + (1 - alpha) * prev[a]
            out[t, a] = prev[a]
    return out


def _row(tag, c):
    sc = c["scenarios"]; tk = sc["taker_top_smallclip"]; mk = sc["maker_earn_a30"]
    print(f"    {tag:10s} gross{c['gross_bp_per_hr']:+.2f} turn{c['mean_turnover']:.3f} | "
          f"tk_sc {tk['net']:+.2f}[{tk['ci95'][0]:+.1f},{tk['ci95'][1]:+.1f}]{tk['folds_pos']}/7 | "
          f"mk_a30 {mk['net']:+.2f}[{mk['ci95'][0]:+.1f},{mk['ci95'][1]:+.1f}]{mk['folds_pos']}/7")


def main():
    P = L.load_panel(); SIG = P["SIG"]

    print("=" * 100)
    print("PURE-EMA (phi=1 = Result 11's filter): fine high-alpha. Result 11 tested {1.0,0.6,0.35,0.20} only.")
    print("=" * 100)
    for regime in ("all", "mid"):
        print(f"  --- {regime} ---")
        for a in (1.0, 0.95, 0.90, 0.85, 0.80, 0.70, 0.60):
            _row(f"a={a:.2f}", L.book_from_matrix(P, SIG if a >= 1 else pure_ema(SIG, a), regime))

    print("\n" + "=" * 100)
    print("PHI-AWARE KALMAN: fine gain grid (K=1 is baseline).")
    print("=" * 100)
    for regime in ("all", "mid"):
        print(f"  --- {regime} ---")
        for K in (1.0, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60):
            _row(f"K={K:.2f}", L.book_from_matrix(P, SIG if K >= 1 else F.kalman_causal(SIG, gain=K), regime))

    print("\n" + "=" * 100)
    print("PHI-SENSITIVITY of the K=0.8 candidate (est phi=0.579):")
    print("=" * 100)
    for regime in ("all", "mid"):
        print(f"  --- {regime} ---")
        for phi in (0.30, 0.45, 0.579, 0.70, 0.85):
            _row(f"phi={phi:.2f}", L.book_from_matrix(P, F.kalman_causal(SIG, phi=phi, gain=0.8), regime))

    print("\n" + "=" * 100)
    print("FULL FOCUS + PER-FOLD: K=0.8 candidate vs baseline (the over-null / over-carry adjudication)")
    print("=" * 100)
    for regime in ("all", "mid"):
        base = L.book_from_matrix(P, SIG, regime)
        cand = L.book_from_matrix(P, F.kalman_causal(SIG, gain=0.8), regime)
        print(f"  === {regime} ===")
        for lab in L.FOCUS:
            b = base["scenarios"][lab]; k = cand["scenarios"][lab]
            print(f"   {lab:20s} base {b['net']:+.2f}[{b['ci95'][0]:+.1f},{b['ci95'][1]:+.1f}]{b['folds_pos']}/7 "
                  f"signp{b['sign_p']:.2f} -> K.8 {k['net']:+.2f}[{k['ci95'][0]:+.1f},{k['ci95'][1]:+.1f}]"
                  f"{k['folds_pos']}/7 signp{k['sign_p']:.2f}")
            print(f"        per-fold base: " + " ".join(f"{v:+.1f}" for v in b["per_fold"].values()))
            print(f"        per-fold K.8 : " + " ".join(f"{v:+.1f}" for v in k["per_fold"].values()))


if __name__ == "__main__":
    main()
