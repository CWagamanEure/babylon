"""SCRATCH (steelman): does proper portfolio construction convert the real gross IC
into a net-positive taker book? Reuses gate._build/_betas. Does NOT edit gate.py.

Tests: (1) inverse-vol continuous cross-section weighting, dollar-neutral;
(2) tightest-spread liquid subset; (3) turnover reduction / hysteresis (overlapping book,
charge each crossing once, A5); (4) cost-aware weighting; (5) per-month walk-forward.

Resource-safe: _build sets memory_limit 1500MB. No ingest/episodes.
"""
import sys, datetime as dt
import numpy as np
from research.studies.xsec_statarb.gate import (
    _build, _betas, _boot_ci, _spear, W, FLOOR_ADV, MAX_NAMES, FEE_BP, QCUT, TEST_START_MS,
)

RNG = np.random.default_rng(0)


def period_full(D, betas, t, L, H):
    """Baseline (BTC/ETH-only) residual period, returning per-name arrays keyed by coin idx.
    Mirrors gate._period(sector=False) but also returns idx + trailing residual vol."""
    Lp, Sp, A, didx, day_of_h, R = D["Lp"], D["Sp"], D["A"], D["didx"], D["day_of_h"], D["R"]
    bI, eI = D["bI"], D["eI"]
    dpos = didx.get(int(day_of_h[t]))
    if dpos is None:
        return None
    adv = A[dpos]
    sig = (Lp[t] - Lp[t - L]) - ((Lp[t, bI] - Lp[t - L, bI]) * betas[:, 0] +
                                 (Lp[t, eI] - Lp[t - L, eI]) * betas[:, 1])
    fwd = (Lp[t + 1 + H] - Lp[t + 1]) - ((Lp[t + 1 + H, bI] - Lp[t + 1, bI]) * betas[:, 0] +
                                         (Lp[t + 1 + H, eI] - Lp[t + 1, eI]) * betas[:, 1])
    elig = (np.isfinite(adv) & (adv >= FLOOR_ADV) & np.isfinite(betas[:, 0]) & np.isfinite(sig) &
            np.isfinite(fwd) & np.isfinite(Sp[t]) & np.isfinite(Lp[t + 1]) & np.isfinite(Lp[t + 1 + H]))
    elig[bI] = elig[eI] = False
    idx = np.where(elig)[0]
    if len(idx) < 12:
        return None
    if len(idx) > MAX_NAMES:
        idx = idx[np.argsort(-adv[idx])[:MAX_NAMES]]
    # trailing per-hour residual vol per selected name
    lo = t - W + 1
    seg = R[lo:t + 1]
    rB, rE = seg[:, bI], seg[:, eI]
    resid = seg[:, idx] - np.outer(rB, betas[idx, 0]) - np.outer(rE, betas[idx, 1])
    vol = np.nanstd(resid, axis=0)
    vol[~np.isfinite(vol) | (vol <= 0)] = np.nanmedian(vol[np.isfinite(vol) & (vol > 0)]) if np.isfinite(vol).any() else 1.0
    fade = -sig[idx]                    # fade = -residual momentum
    return idx, fade, fwd[idx], Sp[t][idx], vol


def leg_norm(w):
    """Normalize so long leg sums to +1 and short leg to -1 (gross |w| = 2), dollar-neutral."""
    wl = np.clip(w, 0, None); ws = np.clip(w, None, 0)
    sl, ss = wl.sum(), -ws.sum()
    out = np.zeros_like(w)
    if sl > 0: out += wl / sl
    if ss > 0: out += ws / ss
    return out


def weights(scheme, fade, vol, spb, k=None):
    n = len(fade)
    r = np.argsort(np.argsort(fade)).astype(float)   # 0..n-1
    rc = r - r.mean()
    if scheme == "ew_quint":
        k = k or max(1, n // QCUT)
        w = np.zeros(n); order = np.argsort(fade)
        w[order[-k:]] = 1.0 / k; w[order[:k]] = -1.0 / k
        return w                                      # already leg-normalized
    if scheme == "invvol_quint":
        k = k or max(1, n // QCUT)
        w = np.zeros(n); order = np.argsort(fade)
        iv = 1.0 / vol
        top, bot = order[-k:], order[:k]
        w[top] = iv[top] / iv[top].sum(); w[bot] = -iv[bot] / iv[bot].sum()
        return w
    if scheme == "rank":                              # continuous rank, dollar-neutral
        return leg_norm(rc)
    if scheme == "rank_invvol":                       # rank / vol continuous
        return leg_norm(rc / vol)
    if scheme == "cost_aware":                        # rank/vol, down-weight wide spreads
        med = np.median(spb)
        pen = med / (spb + med)                       # in (0,1], ~1 for tight, ->0.5 median, small for wide
        return leg_norm(rc / vol * pen)
    if scheme == "cost_thresh":                       # only trade names whose |rank-signal| beats spread hurdle
        # crude EV: keep names where signal strength (proxied by |rc| percentile) high & spread tight
        return leg_norm(rc / vol * (spb < np.median(spb)))
    raise ValueError(scheme)


def ann_factor(H):
    return (24.0 / H) * 365.0


def sharpe_ci(rets, H, n=4000, seed=1):
    rets = np.asarray(rets, float); rets = rets[np.isfinite(rets)]
    if len(rets) < 5 or rets.std() == 0:
        return np.nan, (np.nan, np.nan)
    af = np.sqrt(ann_factor(H))
    sr = rets.mean() / rets.std() * af
    rng = np.random.default_rng(seed)
    bs = rets[rng.integers(0, len(rets), size=(n, len(rets)))]
    srs = bs.mean(axis=1) / bs.std(axis=1) * af
    return sr, tuple(np.percentile(srs[np.isfinite(srs)], [2.5, 97.5]))


def run_nonoverlap(D, H, L, scheme, subset_spread=None, cost=True):
    """Non-overlapping book: each period independent open+close. Round-trip cost per name = full spread + 2*fee.
    Returns per-period net bp, gross bp, ic, breadth, month keys."""
    N = D["N"]; day_of_h = D["day_of_h"]
    rebs = list(range(W + 72, N - H - 2, H))
    net, gross, ics, brd, mos, months_oos = [], [], [], [], [], []
    for t in rebs:
        r = period_full(D, _betas(D, t), t, L, H)
        if r is None:
            continue
        idx, fade, fwd, spb, vol = r
        if subset_spread is not None:                 # tightest-spread subset of size subset_spread
            keep = np.argsort(spb)[:subset_spread]
            fade, fwd, spb, vol, idx = fade[keep], fwd[keep], spb[keep], vol[keep], idx[keep]
            if len(fade) < 8:
                continue
        w = weights(scheme, fade, vol, spb)
        if np.all(w == 0):
            continue
        g = float(w @ fwd) * 1e4
        c = float(np.abs(w) @ (spb + 2 * FEE_BP)) if cost else 0.0   # round trip: full spread + 2 fee per |w|
        ic = _spear(fade, fwd)
        net.append(g - c); gross.append(g); ics.append(ic)
        brd.append(np.sum(np.abs(w) > 1e-9)); mos.append(day_of_h[t] // 100)
        months_oos.append(D["hours"][t] >= TEST_START_MS)
    return (np.array(net), np.array(gross), np.array(ics), np.array(brd),
            np.array(mos), np.array(months_oos))


def run_hysteresis(D, H, L, scheme, band):
    """Overlapping book with hysteresis: hold w across rebalances; only re-solve a name's target when its
    rank moves materially. Cost = per-crossing (half_spread + fee)*|Δw|  [A5]. Rebalance step = H (non-overlap
    holds still, but weights persist so turnover < full). PnL over each step uses next-step fwd for held names.
    Simplification: we rebalance every H hours and carry weights; net_t = w_prev @ fwd_t (return earned by the
    book held over [t, t+H]) minus trade cost to move w_prev -> w_target at t."""
    N = D["N"]; day_of_h = D["day_of_h"]
    rebs = list(range(W + 72, N - H - 2, H))
    prev_w = {}            # coin idx -> weight
    net, gross, mos, oos = [], [], [], []
    for t in rebs:
        r = period_full(D, _betas(D, t), t, L, H)
        if r is None:
            continue
        idx, fade, fwd, spb, vol = r
        w_t = weights(scheme, fade, vol, spb)
        tgt = {int(idx[i]): w_t[i] for i in range(len(idx))}
        spr = {int(idx[i]): spb[i] for i in range(len(idx))}
        # hysteresis: keep prev weight unless target differs by > band (material change), or name left universe
        new_w = {}
        allc = set(tgt) | set(prev_w)
        for c in allc:
            pt = prev_w.get(c, 0.0); tg = tgt.get(c, 0.0)
            if c not in tgt:
                new_w[c] = 0.0                          # exited universe -> must close
            elif abs(tg - pt) > band:
                new_w[c] = tg                           # material change -> move
            else:
                new_w[c] = pt                           # hold
        # trade cost to go prev_w -> new_w (charge each crossing once: half_spread + fee)
        cst = 0.0
        for c in set(new_w) | set(prev_w):
            dw = new_w.get(c, 0.0) - prev_w.get(c, 0.0)
            if dw != 0:
                hs = spr.get(c, 30.0) * 0.5             # half spread; if closing an exited name use last known/def
                cst += abs(dw) * (hs + FEE_BP)
        # return earned over [t, t+H] by the book we now hold (new_w), in residual space
        fwdmap = {int(idx[i]): fwd[i] for i in range(len(idx))}
        g = sum(new_w.get(c, 0.0) * fwdmap.get(c, 0.0) for c in new_w) * 1e4
        net.append(g - cst); gross.append(g)
        mos.append(day_of_h[t] // 100); oos.append(D["hours"][t] >= TEST_START_MS)
        prev_w = {c: v for c, v in new_w.items() if v != 0.0}
    return np.array(net), np.array(gross), np.array(mos), np.array(oos)


def report(tag, net, gross, ics, brd, oos, H):
    sr, (lo, hi) = sharpe_ci(net, H)
    osr, (olo, ohi) = sharpe_ci(net[oos], H) if oos.sum() > 5 else (np.nan, (np.nan, np.nan))
    gm = np.nanmean(gross); nm = np.nanmean(net)
    icm = np.nanmean(ics) if ics is not None and len(ics) else np.nan
    bm = np.nanmean(brd) if brd is not None and len(brd) else np.nan
    print(f"{tag:<34} n={len(net):>3} | gross {gm:>6.1f} net {nm:>6.1f} bp | "
          f"SR {sr:>5.2f} [{lo:>5.2f},{hi:>5.2f}] | oosSR {osr:>5.2f} [{olo:>5.2f},{ohi:>5.2f}] | "
          f"IC {icm:>6.3f} brd {bm:>4.0f}")
    return sr, (lo, hi), osr, nm


def main():
    D = _build()
    print(f"\nuniverse coins={D['C']} hours={D['N']}\n")
    for (H, L) in [(24, 12), (24, 24)]:
        print(f"===== H={H} L={L}  (per year ≈ {ann_factor(H):.0f} periods) =====")
        # 1. baseline EW quintile (sanity vs gate)
        for scheme in ["ew_quint", "invvol_quint", "rank", "rank_invvol", "cost_aware", "cost_thresh"]:
            net, gross, ics, brd, mos, oos = run_nonoverlap(D, H, L, scheme)
            report(f"[nonov] {scheme}", net, gross, ics, brd, oos, H)
        # 2. tightest-spread subsets
        for ss in [20, 30, 40]:
            net, gross, ics, brd, mos, oos = run_nonoverlap(D, H, L, "rank_invvol", subset_spread=ss)
            report(f"[nonov] rank_invvol spread<= top{ss}", net, gross, ics, brd, oos, H)
        # gross-only (no cost) -> Sharpe CEILING (best any taker/maker execution could reach)
        for sc in ["rank_invvol", "ew_quint", "rank"]:
            net, gross, ics, brd, mos, oos = run_nonoverlap(D, H, L, sc, cost=False)
            report(f"[nonov] {sc} GROSS(no cost=ceiling)", net, gross, ics, brd, oos, H)
        # 3. hysteresis / turnover reduction
        for band in [0.0, 0.02, 0.05, 0.1]:
            net, gross, mos, oos = run_hysteresis(D, H, L, "rank_invvol", band)
            report(f"[hyst b={band}] rank_invvol", net, gross, None, None, oos, H)
        print()


def walkforward(H=24, L=12, scheme="rank_invvol"):
    D = _build()
    net, gross, ics, brd, mos, oos = run_nonoverlap(D, H, L, scheme)
    print(f"\n=== per-month walk-forward  H={H} L={L} {scheme} (each month effectively OOS w/ rolling betas) ===")
    print(f"{'month':>7} {'n':>4} {'gross':>7} {'net':>7} {'IC':>7}")
    for mo in sorted(set(mos)):
        m = mos == mo
        tag = "  <OOS" if mo >= 202604 else ""
        print(f"{mo:>7} {m.sum():>4} {np.nanmean(gross[m]):>7.1f} {np.nanmean(net[m]):>7.1f} "
              f"{np.nanmean(ics[m]):>7.3f}{tag}")
    # cumulative net sign by month
    mm = sorted(set(mos))
    signs = [np.nanmean(net[mos == mo]) > 0 for mo in mm]
    print(f"months net>0: {sum(signs)}/{len(signs)}   IC>0: {sum(np.nanmean(ics[mos==mo])>0 for mo in mm)}/{len(mm)}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "wf":
        walkforward()
    else:
        main()
