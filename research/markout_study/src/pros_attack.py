"""Prosecution attacks on the consensus>=9 -> +15.5bp@6h signal."""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
sys.path.insert(0, "src")

OUT = Path("out")
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TEST_LO = _ms(2026, 3, 1)
Z = np.load(OUT / "pros_arrays.npz", allow_pickle=True)
b, d, cohcons, allcons_at = Z["b"], Z["d"], Z["cohcons"], Z["allcons_at"]
dip, cost, cid, R = Z["dip"], Z["cost"], Z["cid"], Z["R"]
HRS = list(Z["hrs"]); COINS = list(Z["coins"])
H = {h: k for k, h in enumerate(HRS)}
TEST = b >= TEST_LO


def net(mask, hh):
    col = R[:, H[hh]]
    m = mask & np.isfinite(col)
    if m.sum() == 0: return np.nan, 0, np.nan
    dd = col[m]; c = cost[mask & np.isfinite(col)].mean()
    return dd.mean() - c, int(m.sum()), dd.std(ddof=1) / np.sqrt(m.sum())


def netci(mask, hh):
    mean, n, se = net(mask, hh)
    return mean, n, se, (mean - 1.96 * se, mean + 1.96 * se) if n else (np.nan, np.nan)


print("=== SANITY: reproduce signal (TEST, consensus>=9) ===")
sig = TEST & (cohcons >= 9)
for hh in [4, 6, 8]:
    m, n, se = net(sig, hh)
    print(f"  {hh}h net={m:+6.2f}  n={n}  se={se:.2f}")

print("\n=== ATTACK 1: consensus threshold scan 5..15 (TEST, 6h) — spike or plateau? ===")
for K in range(5, 16):
    m6, n, se = net(TEST & (cohcons >= K), 6)
    print(f"  K>={K:2d}: 6h net={m6:+6.2f}  n={n:5d}  se={se:4.2f}  CI[{m6-1.96*se:+5.1f},{m6+1.96*se:+5.1f}]")

print("\n=== ATTACK 2: fine horizon grid (TEST, consensus>=9) — hump or lucky point? ===")
for hh in HRS:
    m, n, se = net(sig, hh)
    star = "  <==" if hh == 6 else ""
    print(f"  {hh:2d}h: net={m:+6.2f}  se={se:4.2f}  CI[{m-1.96*se:+5.1f},{m+1.96*se:+5.1f}]{star}")

print("\n=== ATTACK 3a: drop-one-coin (TEST, consensus>=9, 6h) ===")
for c in range(len(COINS)):
    m, n, se = net(sig & (cid != c), 6)
    mc, nc, sec = net(sig & (cid == c), 6)
    print(f"  drop {COINS[c]:5s}: 6h net={m:+6.2f} n={n:4d}  |  ONLY {COINS[c]}: {mc:+6.2f} n={nc:4d}")

print("\n=== ATTACK 3b: edge by month (TEST, consensus>=9, 6h) ===")
mo = np.array([datetime.fromtimestamp(x/1000, timezone.utc).strftime("%Y-%m") for x in b])
for mm in sorted(set(mo[sig])):
    m, n, se = net(sig & (mo == mm), 6)
    print(f"  {mm}: 6h net={m:+6.2f}  n={n:4d}  se={se:4.2f}")

print("\n=== ATTACK 3c: drop consensus BURSTS (cluster entries within 30min windows) ===")
# group signal entries into episodes: same coin, gap <30min => same episode
idx = np.where(sig)[0]
order = idx[np.lexsort((b[idx], cid[idx]))]
epi = np.zeros(order.size, int)
for i in range(1, order.size):
    same = cid[order[i]] == cid[order[i-1]] and (b[order[i]] - b[order[i-1]]) < WIN if False else False
# simpler: episode id by (coin, floor(b/2h)) then merge — use 6h buckets per coin
WIN = 30*60_000
ep_key = cid[sig].astype(np.int64) * 10**13 + (b[sig] // (3*3600_000))
uk, inv = np.unique(ep_key, return_inverse=True)
col6 = R[:, H[6]]
sig_col = sig & np.isfinite(col6)
# per-episode mean contribution
ep_net = []
for u in range(uk.size):
    mm = sig.copy(); sel = np.zeros(sig.sum(), bool); sel[inv == u] = True
    full = np.zeros_like(sig); full[np.where(sig)[0][inv == u]] = True
    m, n, se = net(full, 6)
    if n > 0: ep_net.append((m*n if not np.isnan(m) else 0, n, u))
print(f"  n episodes (3h buckets): {len(ep_net)}")
tot_mean, tot_n, _ = net(sig, 6)
# rank episodes by total drift contribution and drop top ones
cont = [( (net(np.isin(np.arange(sig.size), np.where(sig)[0][inv==u]),6)) ) for u in range(uk.size)]
contrib = []
for u in range(uk.size):
    full = np.zeros_like(sig); full[np.where(sig)[0][inv == u]] = True
    m, n, se = net(full, 6)
    if n > 0 and not np.isnan(m): contrib.append((m, n, u))
contrib.sort(key=lambda z: -z[0]*z[1])
for topk in [1, 3, 5, 10]:
    drop_u = set(z[2] for z in contrib[:topk])
    keep = sig.copy()
    for u in drop_u:
        keep[np.where(sig)[0][inv == u]] = False
    m, n, se = net(keep, 6)
    print(f"  drop top-{topk:2d} episodes: 6h net={m:+6.2f}  n={n:4d}  se={se:4.2f}")

print("\n=== ATTACK 4: GENERIC all-wallet crowding proxy (TEST) ===")
# at each cohort entry, compare cohort-consensus>=9 vs all-wallet trailing consensus percentile
# and separately measure the pure all-wallet consensus events
for c in COINS:
    A = np.load(OUT / f"pros_all_{c}.npz")
    ab, ad, ac, aR, acost = A["b"], A["d"], A["cons"], A["R"], A["cost"]
    at = ab >= TEST_LO
    col = aR[:, H[6]]
    # pick threshold on all-wallet consensus matching ~top few % (like cohort>=9 is ~6% of firing? no, 6% overall)
    for q in [0.99, 0.999, 0.9999]:
        thr = np.quantile(ac[at], q)
        mm = at & (ac >= thr) & np.isfinite(col)
        if mm.sum() < 20:
            print(f"  {c} allcons>=p{q}: n={mm.sum()} too few"); continue
        nn = (col[mm].mean() - acost[mm].mean())
        print(f"  {c} allcons>=p{q:.4f}(={thr:.0f}): 6h net={nn:+6.2f}  n={mm.sum()}")
print("DONE")
