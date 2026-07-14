"""
Full significance analysis of the consensus>=9 signal (+15.5bp net 6h, n=1270 TEST).
Tasks: (1) collapse to independent events, (2) cluster bootstrap (coin-week, coin-day),
(3) effective N & MDE, (4) SKILL-vs-GENERIC-CROWDING placebo (activity-matched random cohorts),
(5) concentration (by coin / top events / drop-one-coin).
Guards over-null AND over-carry.
"""
import sys
from pathlib import Path
import numpy as np
import polars as pl

OUT = Path("out"); COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
WIN = 30 * 60_000; H6 = 6 * 3_600_000; DAY = 86_400_000
THR = 9
SEED = 20260705
rng = np.random.default_rng(SEED)


def consensus_counts(coin_id, b, d):
    """entry-count consensus (conditional_copy2 def): # earlier same-dir entries in (t-WIN,t), per coin."""
    cons = np.zeros(b.size)
    for c in range(len(COINS)):
        for sgn in (1.0, -1.0):
            idx = np.where((coin_id == c) & (d == sgn))[0]
            if idx.size == 0:
                continue
            tb = b[idx]; o = np.argsort(tb, kind="stable"); tbs = tb[o]
            pos = np.arange(tbs.size)
            cnt = (pos - np.searchsorted(tbs, tbs - WIN)).astype(float)
            cons[idx[o]] = cnt
    return cons


def subset_net(mk6, cost, mask):
    v = mk6[mask]; ok = np.isfinite(v)
    if ok.sum() == 0:
        return np.nan, 0
    return v[ok].mean() - cost[mask][ok].mean(), int(ok.sum())


def load_master():
    E = pl.read_parquet(OUT / "consensus_master.parquet")
    wallets = E["wallet"].to_numpy()
    uniq, wid = np.unique(wallets, return_inverse=True)
    cid = np.array([COINS.index(c) for c in E["coin"].to_numpy()])
    arr = dict(wid=wid.astype(np.int64), uniq=uniq, cid=cid,
               b=E["b_ts"].to_numpy(), d=E["dir"].to_numpy().astype(float),
               mk6=E["mk6"].to_numpy(), cost=E["cost"].to_numpy(),
               day=E["day"].to_numpy(), week=E["week"].to_numpy())
    return arr


def cohort_subset(arr, wallet_set):
    keep = np.array([w in wallet_set for w in arr["uniq"]])
    memb = keep[arr["wid"]]
    return memb


def cluster_boot(vals, cost, clusters, R=5000):
    """ratio-of-sums cluster bootstrap of (mean mk6 - mean cost). clusters = integer cluster id."""
    ok = np.isfinite(vals)
    vals, cost, clusters = vals[ok], cost[ok], clusters[ok]
    uc, inv = np.unique(clusters, return_inverse=True)
    m = uc.size
    # per-cluster sums
    svals = np.zeros(m); scost = np.zeros(m); cnt = np.zeros(m)
    np.add.at(svals, inv, vals); np.add.at(scost, inv, cost); np.add.at(cnt, inv, 1.0)
    out = np.empty(R)
    for i in range(R):
        pick = rng.integers(0, m, m)
        n = cnt[pick].sum()
        out[i] = (svals[pick].sum() - scost[pick].sum()) / n
    point = (svals.sum() - scost.sum()) / cnt.sum()
    return point, out, m


def greedy_events(b, mk6, cost, coin_id, block_ms):
    """collapse to non-overlapping coin blocks; one markout per event (mean of members)."""
    ev_mk = []; ev_cost = []; ev_n = []; ev_coin = []
    for c in range(len(COINS)):
        idx = np.where(coin_id == c)[0]
        if idx.size == 0:
            continue
        o = idx[np.argsort(b[idx], kind="stable")]
        bt = b[o]; mv = mk6[o]; cv = cost[o]
        start = bt[0]; members_m = []; members_c = []
        for k in range(bt.size):
            if bt[k] - start > block_ms:
                fm = [x for x in members_m if np.isfinite(x)]
                if fm:
                    ev_mk.append(np.mean(fm)); ev_cost.append(np.mean(members_c)); ev_n.append(len(members_m)); ev_coin.append(c)
                start = bt[k]; members_m = []; members_c = []
            members_m.append(mv[k]); members_c.append(cv[k])
        fm = [x for x in members_m if np.isfinite(x)]
        if fm:
            ev_mk.append(np.mean(fm)); ev_cost.append(np.mean(members_c)); ev_n.append(len(members_m)); ev_coin.append(c)
    return np.array(ev_mk), np.array(ev_cost), np.array(ev_n), np.array(ev_coin)


def main():
    arr = load_master()
    cohort = set(x for x in Path("out/cohort_wallets.txt").read_text().split("\n") if x)
    memb = cohort_subset(arr, cohort)
    # cohort subset arrays
    cid = arr["cid"][memb]; b = arr["b"][memb]; d = arr["d"][memb]
    mk6 = arr["mk6"][memb]; cost = arr["cost"][memb]; day = arr["day"][memb]; week = arr["week"][memb]
    cons = consensus_counts(cid, b, d)
    sel = cons >= THR
    net0, n0 = subset_net(mk6, cost, sel)
    print(f"{'='*78}\nREAL cohort cons>=9 subset: n={n0}  NET 6h = {net0:+.2f} bp\n{'='*78}")

    # subset arrays
    sb = b[sel]; smk = mk6[sel]; scost = cost[sel]; sday = day[sel]; sweek = week[sel]; scid = cid[sel]

    # ---------- TASK 1: collapse to independent events ----------
    print("\n--- TASK 1: collapse to INDEPENDENT events (non-overlapping coin blocks) ---")
    print(f"  raw selected entries n = {np.isfinite(smk).sum()}")
    for lab, blk in [("30min", 30 * 60_000), ("60min", 60 * 60_000), ("6h (non-overlap fwd window)", H6)]:
        em, ec, en, eco = greedy_events(sb, smk, scost, scid, blk)
        net = em.mean() - ec.mean()
        sd = em.std(ddof=1); se = sd / np.sqrt(em.size)
        lo, hi = net - 1.96 * se, net + 1.96 * se
        print(f"  block={lab:28s} events={em.size:4d}  net={net:+6.2f}  iid95%CI=[{lo:+6.2f},{hi:+6.2f}]"
              f"  {'EXCL 0' if lo>0 else 'SPANS 0'}  (design-eff {n0/em.size:.1f} entries/event)")

    # ---------- TASK 2: cluster bootstrap ----------
    print("\n--- TASK 2: cluster bootstrap of the entry-level net (ratio-of-sums) ---")
    for lab, cl in [("coin-DAY", scid.astype(np.int64) * 10**9 + sday),
                    ("coin-WEEK", scid.astype(np.int64) * 10**9 + sweek)]:
        point, boot, m = cluster_boot(smk, scost, cl)
        lo, hi = np.nanpercentile(boot, [2.5, 97.5]); se = np.nanstd(boot)
        print(f"  cluster={lab:9s} #clusters={m:4d}  point={point:+6.2f}  95%CI=[{lo:+6.2f},{hi:+6.2f}]"
              f"  SE={se:4.2f}  {'EXCLUDES 0' if lo>0 else 'SPANS 0'}")
    # iid (naive) for contrast
    pv = smk[np.isfinite(smk)]; iid_se = pv.std(ddof=1) / np.sqrt(pv.size)
    print(f"  (naive iid SE={iid_se:.2f}  -> CI=[{net0-1.96*iid_se:+.2f},{net0+1.96*iid_se:+.2f}])")

    # ---------- TASK 3: effective N & MDE ----------
    print("\n--- TASK 3: effective N & MDE ---")
    point_cd, boot_cd, m_cd = cluster_boot(smk, scost, scid.astype(np.int64) * 10**9 + sday)
    cl_se = np.nanstd(boot_cd)
    n_eff = (iid_se / cl_se) ** 2 * pv.size
    mde = 2.8 * cl_se
    print(f"  naive n = {pv.size}   coin-day clusters = {m_cd}   effective N ~ {n_eff:.0f}")
    print(f"  cluster SE = {cl_se:.2f} bp   MDE(2.8*SE, ~80% power) = {mde:.1f} bp")
    print(f"  +15.5 vs MDE: {'ABOVE MDE (detectable)' if net0 > mde else 'AT/BELOW MDE (marginal/blind)'}")

    # ---------- TASK 5: concentration ----------
    print("\n--- TASK 5: concentration ---")
    print("  by coin:")
    for c in range(len(COINS)):
        mk = smk[scid == c]; ok = np.isfinite(mk); cc = scost[scid == c][ok]
        if ok.sum():
            print(f"    {COINS[c]:5s} n={ok.sum():4d}  net={mk[ok].mean()-cc.mean():+7.2f}")
    # drop-one-coin
    print("  drop-one-coin (recompute net on remaining):")
    for c in range(len(COINS)):
        keep = scid != c
        net, n = subset_net(smk, scost, keep)
        print(f"    drop {COINS[c]:5s} -> n={n:4d}  net={net:+6.2f}")
    # top-event contribution (6h blocks)
    em, ec, en, eco = greedy_events(sb, smk, scost, scid, H6)
    order = np.argsort(-np.abs(em - em.mean()))
    tot = (em - ec).sum()
    for topk in [1, 3, 5, 10]:
        drop = np.ones(em.size, bool); drop[order[:topk]] = False
        net_wo = (em[drop] - ec[drop]).mean()
        print(f"    drop top-{topk:2d} most-extreme events -> net={net_wo:+6.2f} (from {em.mean()-ec.mean():+.2f})")

    # ---------- TASK 4: PLACEBO ----------
    print(f"\n{'='*78}\n--- TASK 4: SKILL vs GENERIC-CROWDING placebo (activity-matched random cohorts) ---\n{'='*78}")
    pw = pl.read_parquet(OUT / "consensus_wallet_counts.parquet")
    wc = dict(zip(pw["wallet"].to_list(), pw["n"].to_list()))
    # cohort counts (target activity distribution)
    coh_counts = np.array(sorted(wc.get(w, 0) for w in cohort))
    # pool: wallets with >=300 majors entries, EXCLUDING the real cohort
    pool = [(w, n) for w, n in wc.items() if n >= 300 and w not in cohort]
    pool_w = np.array([w for w, _ in pool]); pool_n = np.array([n for _, n in pool])
    o = np.argsort(pool_n); pool_w = pool_w[o]; pool_n = pool_n[o]
    print(f"  pool (>=300 majors entries, ex-cohort): {pool_w.size} wallets")
    print(f"  cohort activity: median {np.median(coh_counts):.0f}  pool median {np.median(pool_n):.0f}")

    def draw_matched():
        chosen = set(); ids = []
        for cnt in coh_counts:
            lo = np.searchsorted(pool_n, 0.7 * cnt); hi = np.searchsorted(pool_n, 1.4 * cnt)
            cand = np.arange(lo, hi)
            cand = cand[~np.isin(pool_w[cand], list(chosen))] if chosen else cand
            if cand.size == 0:  # widen
                cand = np.array([np.argmin(np.abs(pool_n - cnt))])
            pick = cand[rng.integers(cand.size)]
            chosen.add(pool_w[pick]); ids.append(pool_w[pick])
        return set(ids)

    THRS = [7, 8, 9, 10, 12]
    NDRAW = 300
    nets = []; ns = []; best_nets = []; btc_nets = []
    for i in range(NDRAW):
        ws = draw_matched()
        m = cohort_subset(arr, ws)
        ci = arr["cid"][m]; bb = arr["b"][m]; dd = arr["d"][m]
        mm = arr["mk6"][m]; cc = arr["cost"][m]
        cn = consensus_counts(ci, bb, dd)
        net, n = subset_net(mm, cc, cn >= THR)
        nets.append(net); ns.append(n)
        # max-over-threshold (mirror the argmax selection applied to the real cohort)
        cand = [subset_net(mm, cc, cn >= t) for t in THRS]
        cand = [x[0] for x in cand if x[1] >= 100]
        best_nets.append(max(cand) if cand else np.nan)
        # BTC-only (where the bulk of real entries live)
        bmask = (cn >= THR) & (ci == 0)
        bn, bnn = subset_net(mm, cc, bmask)
        btc_nets.append(bn if bnn >= 50 else np.nan)
    nets = np.array(nets); ns = np.array(ns)
    best_nets = np.array(best_nets); btc_nets = np.array(btc_nets)
    valid = np.isfinite(nets) & (ns >= 100)
    nv = nets[valid]
    print(f"\n  {NDRAW} activity-matched random cohorts, identical cons>=9 pipeline:")
    print(f"  random consensus-subset n: median {int(np.median(ns))}  (real={n0})")
    print(f"  random consensus NET 6h distribution (valid n>=100, {valid.sum()} draws):")
    for q in [1, 5, 25, 50, 75, 95, 99]:
        print(f"     p{q:02d} = {np.percentile(nv, q):+6.2f} bp")
    print(f"  random mean net = {nv.mean():+.2f}  sd = {nv.std():.2f}")
    frac_ge = (nv >= net0).mean()
    print(f"  REAL cohort net = {net0:+.2f} bp")
    print(f"  fraction of random cohorts with net >= real ({net0:+.1f}): {frac_ge:.3f}  (empirical p)")
    z = (net0 - nv.mean()) / nv.std()
    print(f"  z of real vs random-crowd distribution: {z:+.2f}")
    # robustness A: mirror the threshold-argmax selection on random cohorts too
    bn = best_nets[np.isfinite(best_nets)]
    real_best = 15.53  # cons>=9 is the argmax over THRS for the real cohort (verified in consensus_sig)
    print(f"\n  [robustness A] max-over-threshold {THRS}: random best-net median {np.median(bn):+.2f}, "
          f"p95 {np.percentile(bn,95):+.2f}; frac >= real_best({real_best:+.1f}) = {(bn>=real_best).mean():.3f}")
    # robustness B: BTC-only (bulk of entries), real BTC net = +7.48
    btcv = btc_nets[np.isfinite(btc_nets)]
    real_btc = 7.48
    print(f"  [robustness B] BTC-only consensus net: random median {np.median(btcv):+.2f}, "
          f"p95 {np.percentile(btcv,95):+.2f}; frac >= real_BTC({real_btc:+.1f}) = {(btcv>=real_btc).mean():.3f}")
    pl.DataFrame({"net": nets, "n": ns, "best": best_nets, "btc": btc_nets}).write_parquet(OUT / "consensus_placebo.parquet")


if __name__ == "__main__":
    main()
