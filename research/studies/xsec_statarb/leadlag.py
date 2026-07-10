"""Leader / lead-lag test — the mechanism the floor gate did NOT test.

The floor gate faded each coin's OWN residual (reversion). This asks the ORTHOGONAL question: does one coin's
BTC/ETH-neutral residual move PREDICT another coin's NEXT residual move (cross-coin lead-lag)? If so, which
coins LEAD (esp. HL-native ones like HYPE) — and can we trade the laggards catching up to the leader
(convergence = residual MOMENTUM, the opposite sign to the reversal we already tested).

Price-only (asset_ctx, all liquid coins) — needs NO wallet/fills data. Discipline: rolling CAUSAL BTC/ETH
beta (Gram-Schmidt, out-of-fit); rank leaders on TRAIN, confirm on held-out TEST (audit A9); asymmetry
(a true leader predicts others MORE than it is predicted by them).

  .venv/bin/python -m research.studies.xsec_statarb.leadlag
"""
import datetime as dt
import numpy as np
from research.studies.xsec_statarb.gate import _build, _boot_ci

W = 720
MINOBS = 240
FLOOR_ADV = 5e6
MAX_U = 80
TEST_MS = int(dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
HL_NATIVE_HINT = ("HYPE",)   # known HL-native; others inferred by low BTC beta


def rolling_beta(y, x, W, minobs):
    good = np.isfinite(y) & np.isfinite(x)
    yv = np.where(good, y, 0.0); xv = np.where(good, x, 0.0); g = good.astype(float)
    cxy = np.concatenate([[0.], np.cumsum(xv * yv)]); cxx = np.concatenate([[0.], np.cumsum(xv * xv)])
    cx = np.concatenate([[0.], np.cumsum(xv)]); cy = np.concatenate([[0.], np.cumsum(yv)])
    cn = np.concatenate([[0.], np.cumsum(g)])
    N = len(y); lo = np.maximum(0, np.arange(N) - W + 1); hi = np.arange(N) + 1
    n = cn[hi] - cn[lo]; nn = np.where(n > 0, n, 1)
    cov = (cxy[hi] - cxy[lo]) - (cx[hi] - cx[lo]) * (cy[hi] - cy[lo]) / nn
    var = (cxx[hi] - cxx[lo]) - (cx[hi] - cx[lo]) ** 2 / nn
    beta = np.full(N, np.nan); ok = (n >= minobs) & (var > 0)
    beta[ok] = cov[ok] / var[ok]
    return beta


def _zc(M):
    """column z-score over finite entries; NaN->0 (for complete-case dot products)."""
    Z = np.zeros_like(M)
    for j in range(M.shape[1]):
        col = M[:, j]; f = np.isfinite(col)
        if f.sum() > 10:
            s = col[f].std()
            if s > 0:
                Z[f, j] = (col[f] - col[f].mean()) / s
    return Z


def run():
    D = _build()
    Lp, R, ci, coins, A, day_of_h = D["Lp"], D["R"], D["ci"], D["coins"], D["A"], D["day_of_h"]
    bI, eI, C, N = D["bI"], D["eI"], D["C"], D["N"]
    hours = D["hours"]
    rbtc = R[:, bI]
    eth_r = R[:, eI] - rolling_beta(R[:, eI], rbtc, W, MINOBS) * rbtc     # ETH orthogonal to BTC (once)

    # BTC/ETH-neutral residual returns per coin (Gram-Schmidt, causal betas), + mean BTC beta (HL-native proxy)
    resid = np.full((N, C), np.nan); btc_beta = np.full(C, np.nan)
    for c in range(C):
        if c in (bI, eI):
            continue
        bb = rolling_beta(R[:, c], rbtc, W, MINOBS)
        r1 = R[:, c] - bb * rbtc
        resid[:, c] = r1 - rolling_beta(r1, eth_r, W, MINOBS) * eth_r
        btc_beta[c] = np.nanmedian(bb)

    # liquid universe (median completed-day ADV), cap MAX_U, exclude BTC/ETH
    adv_med = np.nanmedian(np.where(np.isfinite(A), A, np.nan), axis=0)
    elig = np.array([(adv_med[c] if np.isfinite(adv_med[c]) else 0) >= FLOOR_ADV and c not in (bI, eI)
                     and np.isfinite(resid[:, c]).sum() > 2000 for c in range(C)])
    U = np.where(elig)[0]
    U = U[np.argsort(-adv_med[U])[:MAX_U]]
    names = [coins[c] for c in U]
    print(f"lead-lag universe: {len(U)} liquid coins (ADV>=${FLOOR_ADV:,.0f}); leaders ranked on TRAIN, "
          f"confirmed on held-out TEST (>=2026-04)")

    lead = resid[:-1][:, U]; fol = resid[1:][:, U]        # lead[t]=resid_t, fol[t]=resid_{t+1}
    hmask_row = hours[:-1]
    tr = hmask_row < TEST_MS; te = hmask_row >= TEST_MS

    def cmat(rowmask):
        rows = rowmask & np.isfinite(lead).all(1) & np.isfinite(fol).all(1)   # complete cases
        if rows.sum() < 200:
            return None, 0
        Zl = _zc(lead[rows]); Zf = _zc(fol[rows])
        return (Zl.T @ Zf) / rows.sum(), int(rows.sum())     # C[i,j]=corr(resid_i[t], resid_j[t+1])

    Ctr, ntr = cmat(tr); Cte, nte = cmat(te)
    k = len(U); off = ~np.eye(k, dtype=bool)
    # leader score = mean forward-corr into OTHER coins; follower = mean OTHER coins predicting me
    ldr_tr = np.array([Ctr[i, off[i]].mean() for i in range(k)])
    ldr_te = np.array([Cte[i, off[i]].mean() for i in range(k)])
    fol_te = np.array([Cte[off[:, j], j].mean() for j in range(k)])
    own_te = np.diag(Cte)                                   # own-residual autocorr (reversion if <0)

    print(f"\n(complete-case rows: train={ntr:,}, test={nte:,})")
    print(f"mean OWN-residual next-hour autocorr (TEST) = {np.nanmean(own_te):+.4f}  "
          f"(<0 = the reversion the floor gate traded)")
    print(f"mean CROSS lead-lag corr (TEST, off-diag)   = {np.nanmean(Cte[off]):+.4f}  "
          f"(>0 = laggards follow leaders next hour)\n")

    order = np.argsort(-ldr_tr)                             # rank leaders on TRAIN
    print(f"{'coin':>7} {'lead_TR':>8} {'lead_TE':>8} {'foll_TE':>8} {'net_TE':>8} {'btcBeta':>8}")
    for i in order[:15]:
        tag = " *HL?" if (names[i] in HL_NATIVE_HINT or btc_beta[U[i]] < 0.3) else ""
        print(f"{names[i]:>7} {ldr_tr[i]:>8.4f} {ldr_te[i]:>8.4f} {fol_te[i]:>8.4f} "
              f"{ldr_te[i]-fol_te[i]:>+8.4f} {btc_beta[U[i]]:>8.2f}{tag}")
    if "HYPE" in names:
        hi = names.index("HYPE")
        print(f"\nHYPE rank on TRAIN lead score: {list(order).index(hi)+1} / {k}  "
              f"(lead_TE={ldr_te[hi]:+.4f}, net_TE={ldr_te[hi]-fol_te[hi]:+.4f})")

    # convergence trade (light): does the top-TRAIN-leader's move predict each follower's next residual, OOS?
    Li = order[0]
    x = lead[:, Li]; ic_rows = te & np.isfinite(x)
    ics = []
    for j in range(k):
        if j == Li:
            continue
        m = ic_rows & np.isfinite(fol[:, j])
        if m.sum() > 200:
            a, b = x[m], fol[:, j][m]
            ra = np.argsort(np.argsort(a)).astype(float); rb = np.argsort(np.argsort(b)).astype(float)
            ra -= ra.mean(); rb -= rb.mean(); d = np.sqrt((ra @ ra) * (rb @ rb))
            ics.append((ra @ rb) / d if d > 0 else np.nan)
    ics = np.array([v for v in ics if np.isfinite(v)])
    print(f"\nconvergence (top leader '{names[Li]}' resid[t] -> each follower resid[t+1], TEST): "
          f"mean IC={ics.mean():+.4f} over {len(ics)} followers, {np.mean(ics>0)*100:.0f}% positive")
    print("\n>0 cross lead-lag + a leader that predicts followers OOS => the untested momentum/convergence "
          "edge is live and worth a full trade build; ~0 => no lead-lag structure, leader angle is also null.")


if __name__ == "__main__":
    run()
