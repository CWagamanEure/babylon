"""Stage 1 + FLOOR GATE — cross-sectional residual reversal, decorrelated rank-IC, net of cost.

Cheapest decisive read (ARCHITECTURE §9). BASELINE = BTC/ETH residual only. SECTOR = additionally hedge a
causal, leave-one-out common-alt factor (Stage-5 lite): does removing sector/common-residual comovement
stabilise the OOS flip found in the baseline (real in-sample, 6/6 OOS sign-flip, not regime-separable)?

Audit blockers (AUDIT_RESPONSE.md): A2 sign (long weak/short strong), A3 t+1 entry, A6 validity mask,
A7 completed-prior-day ADV, B10 out-of-fit betas, B12 rank-IC vs forward RESIDUAL return, A10 non-overlap +
bootstrap CI, A4/A5 point-in-time spread round-trip + 2x taker fee (SIZE penalty deferred -> net optimistic).
Sector factor uses cluster-mean-style LOO (B1): the common-alt factor excludes coin i when estimating its
sector beta (self-inclusion bias ~1/n removed).

  .venv/bin/python -m research.studies.xsec_statarb.gate         # baseline vs sector tables
  .venv/bin/python -m research.studies.xsec_statarb.gate diag    # per-month regime diagnostic
"""
import datetime as dt
import numpy as np
from research.data.db import connect

W = 720
FLOOR_ADV = 3e6
MAX_NAMES = 70
MIN_OBS = 360
FEE_BP = 4.5
QCUT = 5
GRID_H = [12, 24]
GRID_L = [12, 24, 72]
TEST_START_MS = int(dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def _to_day(ms):
    d = dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc)
    return d.year * 10000 + d.month * 100 + d.day


def _rank(x):
    return np.argsort(np.argsort(x)).astype(float)


def _spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return np.nan
    ra, rb = _rank(a[m]), _rank(b[m])
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra @ ra) * (rb @ rb))
    return (ra @ rb) / d if d > 0 else np.nan


def _boot_ci(x, n=2000, seed=0):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 5:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    return tuple(np.percentile(x[rng.integers(0, len(x), size=(n, len(x)))].mean(axis=1), [2.5, 97.5]))


def _load():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1500MB'; SET threads=2")
    con.execute("""CREATE OR REPLACE TEMP TABLE bars AS
        WITH v AS (SELECT coin, ts, (ts - ts%3600000) AS h,
                     mid_px, (impact_ask_px-impact_bid_px)/((impact_ask_px+impact_bid_px)*0.5) AS spr
                   FROM asset_ctx
                   WHERE mid_px>0 AND impact_bid_px>0 AND impact_ask_px>=impact_bid_px)
        SELECT coin, h, arg_max(mid_px, ts) AS mid, arg_max(spr, ts)*1e4 AS spr_bp
        FROM v GROUP BY coin, h""")
    b = con.execute("SELECT coin, h, mid, spr_bp FROM bars").fetchnumpy()
    a = con.execute("""WITH d AS (SELECT coin, day, max(day_ntl_vlm) AS vol FROM asset_ctx
                                  WHERE day_ntl_vlm>0 GROUP BY coin, day)
        SELECT coin, day, avg(vol) OVER (PARTITION BY coin ORDER BY day
               ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS adv FROM d""").fetchnumpy()
    return b, a


def _build():
    b, a = _load()
    coins, cols = np.unique(np.asarray(b["coin"], dtype=object), return_inverse=True)
    coins = [str(c) for c in coins]; ci = {c: i for i, c in enumerate(coins)}; C = len(coins)
    h_arr = b["h"].astype(np.int64); hmin, hmax = int(h_arr.min()), int(h_arr.max())
    hours = np.arange(hmin, hmax + 1, 3600000, dtype=np.int64); N = len(hours)
    rows = ((h_arr - hmin) // 3600000).astype(int)
    Lp = np.full((N, C), np.nan); Sp = np.full((N, C), np.nan)
    Lp[rows, cols] = np.log(b["mid"].astype(float)); Sp[rows, cols] = b["spr_bp"].astype(float)
    acoin = np.asarray(a["coin"], dtype=object)
    valid = np.isin(acoin, np.array(coins, dtype=object))
    ac = np.array([ci[str(c)] for c in acoin[valid]])
    ad = a["day"][valid].astype(np.int64); av = a["adv"][valid].astype(float)
    days = np.unique(ad); didx = {int(d): i for i, d in enumerate(days)}
    A = np.full((len(days), C), np.nan)
    A[np.array([didx[int(d)] for d in ad]), ac] = av
    day_of_h = np.array([_to_day(int(h)) for h in hours])
    R = np.diff(Lp, axis=0, prepend=np.nan)
    return dict(Lp=Lp, Sp=Sp, A=A, didx=didx, day_of_h=day_of_h, hours=hours, R=R,
                ci=ci, coins=coins, C=C, N=N, bI=ci["BTC"], eI=ci["ETH"], hmin=hmin, hmax=hmax)


def _betas(D, t):
    R, C, bI, eI = D["R"], D["C"], D["bI"], D["eI"]
    wlo = t - W + 1
    xb, xe = R[wlo:t + 1, bI], R[wlo:t + 1, eI]
    betas = np.full((C, 2), np.nan)
    base = np.isfinite(xb) & np.isfinite(xe)
    if base.sum() >= MIN_OBS:
        for c in range(C):
            if c == bI or c == eI:
                continue
            y = R[wlo:t + 1, c]; m = base & np.isfinite(y)
            if m.sum() >= MIN_OBS:
                Xd = np.column_stack([xb[m], xe[m], np.ones(m.sum())])
                betas[c] = np.linalg.lstsq(Xd, y[m], rcond=None)[0][:2]
    return betas


def _period(D, betas, t, L, H, sector):
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
    sig_i, fwd_i, spb = sig[idx], fwd[idx], Sp[t][idx]
    if sector:
        lo = t - W + 1
        seg = R[lo:t + 2 + H]                                    # rows: window + forward
        rB, rE = seg[:, bI], seg[:, eI]
        E = seg[:, idx] - np.outer(rB, betas[idx, 0]) - np.outer(rE, betas[idx, 1])   # BTC/ETH residual returns
        n = E.shape[1]
        F = np.nanmean(E, axis=1)                                # common-alt factor
        Ew, Fw = E[:W], F[:W]                                    # beta-window rows for gamma
        gam = np.full(n, np.nan)
        for j in range(n):
            floo = (n * Fw - Ew[:, j]) / (n - 1)                 # LOO factor (B1)
            m = np.isfinite(Ew[:, j]) & np.isfinite(floo)
            if m.sum() > 30 and np.var(floo[m]) > 0:
                gam[j] = np.cov(Ew[m, j], floo[m])[0, 1] / np.var(floo[m])
        alt_sig = np.nansum(F[W - L:W])                          # alt cumret over [t-L,t]
        alt_fwd = np.nansum(F[W + 1:W + H + 1])                  # alt cumret over [t+1,t+1+H]
        sig_i = sig_i - gam * alt_sig
        fwd_i = fwd_i - gam * alt_fwd
        keep = np.isfinite(gam) & np.isfinite(sig_i) & np.isfinite(fwd_i)
        sig_i, fwd_i, spb = sig_i[keep], fwd_i[keep], spb[keep]
        if len(sig_i) < 12:
            return None
    return -sig_i, fwd_i, spb                                    # fade = -residual


def _cell(D, sector, H, L, rebs, bcache):
    ic_s, ic_h, nt_s, gr_s = [], [], [], []
    for t in rebs:
        r = _period(D, bcache[t], t, L, H, sector)
        if r is None:
            continue
        fade, fr, spb = r
        ic = _spear(fade, fr)
        if not np.isfinite(ic):
            continue
        order = np.argsort(fade); k = max(1, len(fade) // QCUT)
        gross = (fr[order[-k:]].mean() - fr[order[:k]].mean()) * 1e4
        # two-leg round trip: BOTH baskets pay their full spread (enter+exit) + 2 crossings*fee each
        cost = spb[order[-k:]].mean() + spb[order[:k]].mean() + 4 * FEE_BP
        ic_s.append(ic); ic_h.append(int(D["hours"][t])); gr_s.append(gross); nt_s.append(gross - cost)
    return map(np.array, (ic_s, ic_h, gr_s, nt_s))


def run(sector=False):
    D = _build()
    N = D["N"]
    print(f"\n=== {'SECTOR-neutral (BTC/ETH + LOO common-alt)' if sector else 'BASELINE (BTC/ETH only)'} ===")
    print(f"{'H':>3} {'L':>3} {'per':>4} | {'IC':>7} {'IC 95%CI':>15} {'MDE':>6} {'%>0':>4} | "
          f"{'gross':>6} {'net':>7} | {'oosIC':>6} {'oosNet':>7} {'oos%>0':>6}")
    for H in GRID_H:
        rebs = list(range(W + max(GRID_L), N - H - 2, H))
        bcache = {t: _betas(D, t) for t in rebs}
        for L in GRID_L:
            ic_s, ic_h, gr_s, nt_s = _cell(D, sector, H, L, rebs, bcache)
            n = len(ic_s)
            if n < 5:
                print(f"{H:>3} {L:>3} {n:>4} | insufficient"); continue
            iclo, ichi = _boot_ci(ic_s); mde = 2.8 * np.nanstd(ic_s) / np.sqrt(n)
            oos = ic_h >= TEST_START_MS
            oic = np.nanmean(ic_s[oos]) if oos.sum() > 3 else np.nan
            ont = np.nanmean(nt_s[oos]) if oos.sum() > 3 else np.nan
            op = np.mean(ic_s[oos] > 0) if oos.sum() > 3 else np.nan
            print(f"{H:>3} {L:>3} {n:>4} | {np.nanmean(ic_s):>7.4f} [{iclo:>6.3f},{ichi:>6.3f}] {mde:>6.4f} "
                  f"{np.mean(ic_s > 0):>4.2f} | {np.nanmean(gr_s):>6.1f} {np.nanmean(nt_s):>7.1f} | "
                  f"{oic:>6.3f} {ont:>7.1f} {op:>6.2f}")


def diag(H=24, L=12, sector=False):
    from collections import defaultdict
    D = _build(); N = D["N"]; Lp, R, day_of_h, bI = D["Lp"], D["R"], D["day_of_h"], D["bI"]
    rebs = list(range(W + max(GRID_L), N - H - 2, H))
    mic, mnet = defaultdict(list), defaultdict(list)
    for t in rebs:
        r = _period(D, _betas(D, t), t, L, H, sector)
        if r is None:
            continue
        fade, fr, spb = r
        ic = _spear(fade, fr)
        if not np.isfinite(ic):
            continue
        order = np.argsort(fade); k = max(1, len(fade) // QCUT)
        gross = (fr[order[-k:]].mean() - fr[order[:k]].mean()) * 1e4
        cost = spb[order[-k:]].mean() + spb[order[:k]].mean() + 4 * FEE_BP  # two-leg round trip
        mo = day_of_h[t] // 100; mic[mo].append(ic); mnet[mo].append(gross - cost)
    btc = Lp[:, bI]; rbtc = R[:, bI]
    print(f"\n=== per-month  H={H} L={L} {'SECTOR' if sector else 'BASELINE'} ===")
    print(f"{'month':>7} {'n':>4} {'IC':>8} {'net_bp':>8} | {'BTC%':>7} {'BTCvol':>7}")
    for mo in sorted(mic):
        hm = (day_of_h // 100) == mo; bp = btc[hm]; bp = bp[np.isfinite(bp)]
        bret = (bp[-1] - bp[0]) * 100 if len(bp) > 2 else np.nan
        tag = "  <OOS" if mo >= 202604 else ""
        print(f"{mo:>7} {len(mic[mo]):>4} {np.mean(mic[mo]):>8.4f} {np.mean(mnet[mo]):>8.1f} | "
              f"{bret:>7.1f} {np.nanstd(rbtc[hm]) * 1e4:>7.1f}{tag}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "diag":
        diag(24, 12, False); diag(24, 12, True)
    else:
        run(False); run(True)
