"""Prosecution round 2: episode-clustered CI (block bootstrap), split fragility, top-episode identification."""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
sys.path.insert(0, "src")
OUT = Path("out")
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TEST_LO = _ms(2026, 3, 1)
Z = np.load(OUT / "pros_arrays.npz", allow_pickle=True)
b, d, cohcons, cost, cid, R = Z["b"], Z["d"], Z["cohcons"], Z["cost"], Z["cid"], Z["R"]
HRS = list(Z["hrs"]); COINS = list(Z["coins"]); H = {h: k for k, h in enumerate(HRS)}
col6 = R[:, H[6]]
TEST = b >= TEST_LO
sig = TEST & (cohcons >= 9) & np.isfinite(col6)

# --- episode id: consecutive same-coin same-dir entries with gap<30min => one burst ---
idx = np.where(sig)[0]
key = np.array([f"{cid[i]}_{d[i]:+.0f}" for i in idx])
order = np.lexsort((b[idx], key))
oi = idx[order]
epi = np.zeros(oi.size, int)
for i in range(1, oi.size):
    same = (cid[oi[i]] == cid[oi[i-1]]) and (d[oi[i]] == d[oi[i-1]]) and (b[oi[i]] - b[oi[i-1]] < 30*60_000)
    epi[i] = epi[i-1] if same else epi[i-1] + 1
nep = epi.max() + 1
drift = col6[oi] - cost[oi]
print(f"signal: n_entries={oi.size}  n_episodes={nep}  raw mean net={drift.mean():+.2f}")

# per-episode aggregate (equal-weight per episode = 1 independent decision)
ep_mean = np.array([drift[epi == e].mean() for e in range(nep)])
ep_n = np.array([(epi == e).sum() for e in range(nep)])
print(f"episode-level mean net (equal-weight per burst)={ep_mean.mean():+.2f}  n_ep={nep}")

# --- block bootstrap over EPISODES (resample whole bursts) ---
rng = np.random.default_rng(1)
B = 5000
# entry-mean where each draw resamples episodes (preserves within-burst correlation)
ent_boot = np.empty(B); ep_boot = np.empty(B)
ep_ids = np.arange(nep)
ent_by_ep = [drift[epi == e] for e in range(nep)]
for k in range(B):
    pick = rng.choice(ep_ids, nep, replace=True)
    cat = np.concatenate([ent_by_ep[e] for e in pick])
    ent_boot[k] = cat.mean()
    ep_boot[k] = ep_mean[pick].mean()
print(f"\nBLOCK-BOOTSTRAP over episodes (entry-weighted mean net):")
print(f"  mean={drift.mean():+.2f}  95% CI [{np.percentile(ent_boot,2.5):+.2f}, {np.percentile(ent_boot,97.5):+.2f}]  P(net<=0)={np.mean(ent_boot<=0):.3f}")
print(f"BLOCK-BOOTSTRAP over episodes (episode-weighted mean net):")
print(f"  mean={ep_mean.mean():+.2f}  95% CI [{np.percentile(ep_boot,2.5):+.2f}, {np.percentile(ep_boot,97.5):+.2f}]  P(net<=0)={np.mean(ep_boot<=0):.3f}")

# --- top episodes by total drift contribution ---
ep_tot = np.array([drift[epi == e].sum() for e in range(nep)])
tot = drift.sum()
o = np.argsort(-ep_tot)
print(f"\ntotal drift (sum) across all entries = {tot:.0f} bp; mean={tot/oi.size:+.2f}")
print("TOP episodes by drift contribution:")
for e in o[:8]:
    m = epi == e
    t0 = b[oi[m]].min()
    dt = datetime.fromtimestamp(t0/1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
    cc = COINS[cid[oi[m]][0]]; dd = d[oi[m]][0]
    print(f"  {cc:5s} dir={dd:+.0f} {dt}  n={m.sum():3d}  epmean={drift[m].mean():+7.1f}  contrib={ep_tot[e]:+8.0f} ({100*ep_tot[e]/tot:+5.1f}% of total)")
cum = np.cumsum(ep_tot[o])
print(f"  top-3 episodes = {100*cum[2]/tot:.0f}% of total drift; top-5 = {100*cum[4]/tot:.0f}%; top-10 = {100*cum[9]/tot:.0f}%")

# --- ATTACK 5: split fragility. re-fit K on alternate train boundaries, test after ---
print("\n=== ATTACK 5: alternate train/test splits (fit K in [5,15] max 6h net on train, apply OOS) ===")
def fit_apply(train_hi, test_lo):
    tr = (b < train_hi) & np.isfinite(col6)
    te = (b >= test_lo) & np.isfinite(col6)
    best = None
    for K in range(5, 16):
        m = tr & (cohcons >= K)
        if m.sum() < 200: continue
        nt = (col6[m] - cost[m]).mean()
        if best is None or nt > best[1]: best = (K, nt)
    K = best[0]
    m = te & (cohcons >= K)
    nn = (col6[m] - cost[m]).mean()
    return K, nn, int(m.sum())
for thi, tlo, lab in [(_ms(2026,2,1),_ms(2026,3,1),"orig (train<Feb1, test>=Mar1)"),
                      (_ms(2026,1,1),_ms(2026,2,1),"train<Jan1, test>=Feb1"),
                      (_ms(2026,3,1),_ms(2026,4,1),"train<Mar1, test>=Apr1"),
                      (_ms(2026,4,1),_ms(2026,5,1),"train<Apr1, test>=May1"),
                      (_ms(2025,12,1),_ms(2026,1,1),"train<Dec1, test>=Jan1")]:
    K, nn, n = fit_apply(thi, tlo)
    print(f"  {lab:36s} fit K>={K:2d}  OOS 6h net={nn:+6.2f}  n={n}")
print("DONE")
