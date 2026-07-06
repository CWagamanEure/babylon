"""
Stage M1 — COMPLETE pre-specified robustness + wallet-influence battery on the CORRECTED (train-only-selected) test.
DESCRIPTIVE ONLY. No new rankings/horizons/filters/benchmarks/weightings/variants. No wallet removed/replaced on test
performance. Reads the frozen artifacts (RAM-free): out/cohort_M1_ep.parquet (20 frozen wallets' priced episodes),
out/cohort_M1_top.parquet (train/test stats + shrunk score), out/cohort_M1_frozen.txt (ev/attr).

Pre-registered choices (locked before running):
  MIN_TE = 15 test days = evaluable bar (attrition below, NOT failure, NOT replaced).
  WINS   = clip episode net & alpha at the 1st/99th pct of the pooled EVALUABLE-test distribution (one cutoff).
  COSTS  : frozen {BTC5,ETH5,SOL8,HYPE8} and campaign {BTC8,ETH8,SOL10,HYPE14}. B (alpha) is cost-invariant by construction.
  Influence = leave-one-WALLET-out on the equal-weight basket (descriptive); dependence = remove top-1/2 +/- contributors.
"""
import numpy as np, polars as pl
RNG = np.random.default_rng(0)
COST_FROZEN = {"BTC": 5.0, "ETH": 5.0, "SOL": 8.0, "HYPE": 8.0}
COST_REAL = {"BTC": 8.0, "ETH": 8.0, "SOL": 10.0, "HYPE": 14.0}
DELTA = {k: COST_REAL[k] - COST_FROZEN[k] for k in COST_FROZEN}
MIN_TE = 15; WINS = (1.0, 99.0); NB = 2000

txt = open("out/cohort_M1_frozen.txt").read().split("\n")
ev = txt[txt.index("EV") + 1: txt.index("ATTR")]
attr = [w for w in txt[txt.index("ATTR") + 1:] if w]
top = pl.read_parquet("out/cohort_M1_top.parquet").sort("shrunk_tr_alpha", descending=True).with_row_index("rank", offset=1)
ep = pl.read_parquet("out/cohort_M1_ep.parquet")
te = ep.filter(pl.col("split") == "test").with_columns(
    net_real=pl.col("net") - pl.col("coin").replace_strict(DELTA, default=0.0),
    mon=pl.from_epoch(pl.col("day") * 86400, time_unit="s").dt.strftime("%Y-%m"))
picks = top["wallet"].to_list()                      # all 20, rank order

def matrix(frame, wallets, col):
    wd = frame.filter(pl.col("wallet").is_in(wallets)).group_by("wallet", "day").agg(v=pl.col(col).mean())
    ds = np.sort(wd["day"].unique().to_numpy()); wi = {w: i for i, w in enumerate(wallets)}; di = {int(d): i for i, d in enumerate(ds)}
    M = np.full((len(wallets), len(ds)), np.nan)
    for w, d, v in zip(wd["wallet"], wd["day"], wd["v"]):
        if w in wi: M[wi[w], di[int(d)]] = v
    return M, ds
def ew(M):
    pw = np.array([np.nanmean(M[i]) if np.isfinite(M[i]).any() else np.nan for i in range(M.shape[0])]); return np.nanmean(pw)
def pooled(M): return np.nanmean(M)
def boot(M, stat):
    obs = float(stat(M)); ND = M.shape[1]; bs = np.empty(NB)   # report the OBSERVED statistic as center, CI from bootstrap
    for b in range(NB):
        p = RNG.integers(0, ND, ND)
        with np.errstate(invalid="ignore"): bs[b] = stat(M[:, p])
    return obs, float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5)), float((bs <= 0).mean())
def day_loo(M, fn):                                            # leave-one-DAY-out on the SAME estimator as [5]
    base = fn(M); vals = np.array([fn(np.delete(M, k, axis=1)) for k in range(M.shape[1])]); return base, vals

Mnet, ds = matrix(te, ev, "net"); Mal, _ = matrix(te, ev, "alpha"); Mrn, _ = matrix(te, ev, "net_real")
NW = len(ev); ND = len(ds)

# ---- RW single-step max-t adj-p on the evaluable set (family B), identical machinery to the main test ----
te_al = np.array([np.nanmean(Mal[i]) for i in range(NW)])
se_al = np.array([np.nanstd(Mal[i]) / np.sqrt(np.isfinite(Mal[i]).sum()) for i in range(NW)])
s0 = np.nanmedian(se_al); se_m = np.sqrt((4 * s0 ** 2 + se_al ** 2) / 5); t_al = te_al / se_m
maxt = np.empty(NB)
for b in range(NB):
    p = RNG.integers(0, ND, ND); mb = np.array([np.nanmean(Mal[i, p]) for i in range(NW)]); maxt[b] = np.nanmax((mb - te_al) / se_m)
rwp = {ev[i]: float((maxt >= t_al[i]).mean()) for i in range(NW)}

# per-wallet own-day-block CI (net & alpha), for the table
def wci(frame, w, col):
    v = frame.filter(pl.col("wallet") == w).group_by("day").agg(m=pl.col(col).mean())["m"].to_numpy()
    if len(v) == 0: return (np.nan, np.nan, np.nan, np.nan)
    n = len(v); bs = np.array([v[RNG.integers(0, n, n)].mean() for _ in range(NB)])
    return float(v.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5), ), n

print("=" * 118)
print("[10]+[9] WALLET-LEVEL TABLE — all 20 frozen (train-only) wallets DESCRIPTIVE; formal CI/adj-p only for >=15 test-day evaluable")
print(f"{'wallet':>10} {'rank':>4} {'trD':>4} {'teD':>4} {'trNet':>6} {'teNet':>7} {'trAlf':>6} {'teAlf':>7} {'teAlf 95% CI':>16} {'RWp_B':>6} {'status':>8}")
for w in picks:
    r = top.filter(pl.col("wallet") == w).row(0, named=True)
    tnd = int(r["te_nd"]) if r["te_nd"] is not None else 0
    status = "EVAL" if tnd >= MIN_TE else "ATTRIT"
    if tnd >= MIN_TE:                                          # formal CI ONLY for evaluable (>=15 test days)
        am, alo, ahi, _ = wci(te, w, "alpha"); ci = f"[{alo:+.1f},{ahi:+.1f}]"
    else:
        ci = "(attrit n/a)"
    p = f"{rwp[w]:.3f}" if w in rwp else "  -  "
    tn = r["te_net_m"]; ta = r["te_alpha_m"]
    print(f"{w[:10]:>10} {int(r['rank']):>4} {int(r['tr_nd']):>4} {tnd:>4} {r['tr_net_m']:>6.1f} "
          f"{(float(tn) if tn is not None else float('nan')):>7.1f} {r['tr_alpha_m']:>6.1f} "
          f"{(float(ta) if ta is not None else float('nan')):>7.1f} {ci:>16} {p:>6} {status:>8}")
print(f"  evaluable: {NW}/20 | attrition (te_nd<{MIN_TE}, dropped NOT failed, NOT replaced): {20-NW}  -> {', '.join(w[:8] for w in attr)}")

print("\n" + "=" * 70 + "\n[5] EQUAL-WEIGHT-WALLET vs POOLED-WALLET-DAY (evaluable) + [1][2] day cuts")
for nm, M in [("A net (frozen cost)", Mnet), ("B alpha vs fade", Mal)]:
    e, elo, ehi, ep_ = boot(M, ew); pm, plo, phi, pp = boot(M, pooled)
    print(f"  {nm:22}: EW {e:+.2f} [{elo:+.2f},{ehi:+.2f}] p={ep_:.3f} | pooled {pm:+.2f} [{plo:+.2f},{phi:+.2f}] p={pp:.3f}")
# [1] leave-one-DAY-out + [2] drop-best-day, computed on the SAME two estimators reported in [5] (EW and pooled)
print("  [1] leave-one-DAY-out  +  [2] drop-best-day (baseline == [5] estimators):")
for nm, M in [("A net", Mnet), ("B alpha", Mal)]:
    for lbl, fn in [("EW ", ew), ("pool", pooled)]:
        base, vals = day_loo(M, fn); kb = int(np.argmin(vals))     # removing the most-positive day gives the min LOO value
        flip = not bool((np.sign(vals) == np.sign(base)).all())
        print(f"    {nm:7} {lbl}: base {base:+.2f} | LOO-day∈[{vals.min():+.2f},{vals.max():+.2f}] | drop-best-day {base:+.2f}->{vals.min():+.2f} (day {int(ds[kb])}) | any-day-flips-sign: {flip}")

print("\n[6] WINSORIZED sensitivity (episode net & alpha clipped to pooled test " + f"{WINS[0]:.0f}/{WINS[1]:.0f} pct)")
te_ev = te.filter(pl.col("wallet").is_in(ev))
nlo, nhi = np.percentile(te_ev["net"].to_numpy(), WINS); alo_, ahi_ = np.percentile(te_ev["alpha"].to_numpy(), WINS)
tw = te_ev.with_columns(netw=pl.col("net").clip(nlo, nhi), alw=pl.col("alpha").clip(alo_, ahi_))
Mnw, _ = matrix(tw, ev, "netw"); Maw, _ = matrix(tw, ev, "alw")
for nm, M in [("A net winsor", Mnw), ("B alpha winsor", Maw)]:
    e, elo, ehi, p = boot(M, ew); print(f"  {nm:16}: EW {e:+.2f} [{elo:+.2f},{ehi:+.2f}] p={p:.3f}   (cut net[{nlo:.0f},{nhi:.0f}] alpha[{alo_:.0f},{ahi_:.0f}])")

print("\n[7] Family A under BOTH cost tables (EW, evaluable)  |  [8] Family B cost-cancellation check")
for nm, M in [("frozen 5/5/8/8", Mnet), ("campaign 8/8/10/14", Mrn)]:
    e, elo, ehi, p = boot(M, ew); print(f"  A EW {nm:20}: {e:+.2f} [{elo:+.2f},{ehi:+.2f}] p={p:.3f}")
# [8] cost cancels in B iff BOTH legs pay the SAME cost. fade_net = copied_net - alpha (same coins/day/notional).
#   frozen legs: copied=net, fade=net-alpha -> B = alpha.   real legs: copied=net_real, fade=net_real-alpha -> B = alpha.
Bfroz, _ = matrix(te.with_columns(b=pl.col("net") - (pl.col("net") - pl.col("alpha"))), ev, "b")
Breal, _ = matrix(te.with_columns(b=pl.col("net_real") - (pl.col("net_real") - pl.col("alpha"))), ev, "b")
print(f"  [8] B alpha with MATCHED cost on both legs: frozen-cost EW {ew(Bfroz):+.4f} == real-cost EW {ew(Breal):+.4f} "
      f"(== stored alpha {ew(Mal):+.4f}) -> fee+spread cancel because copy & fade trade the SAME coin/day/notional.")
print(f"      CAVEAT: this cancellation is justified for fee+spread ONLY; market IMPACT differs by copier size and does NOT cancel (not modeled).")

print("\n[3] MONTHLY decomposition (evaluable, pooled)  |  [4] COIN decomposition")
for r in te_ev.group_by("mon").agg(A=pl.col("net").mean(), B=pl.col("alpha").mean(), n=pl.len()).sort("mon").iter_rows(named=True):
    print(f"  {r['mon']}: A net {r['A']:+.2f}  B alpha {r['B']:+.2f}  (n={r['n']})")
for r in te_ev.group_by("coin").agg(A=pl.col("net").mean(), B=pl.col("alpha").mean(), n=pl.len()).sort("n", descending=True).iter_rows(named=True):
    print(f"  {r['coin']:5}: A net {r['A']:+.2f}  B alpha {r['B']:+.2f}  (n={r['n']})")

print("\n" + "=" * 70 + "\nINDIVIDUAL-WALLET INFLUENCE (descriptive; NO removal/replacement on test perf)")
base_n, base_a = ew(Mnet), ew(Mal)
rows = []
for i, w in enumerate(ev):
    idx = [j for j in range(NW) if j != i]
    lo_n, lo_a = ew(Mnet[idx]), ew(Mal[idx])
    own_sd = float(np.nanstd(Mal[i])); own_te = int(np.isfinite(Mal[i]).sum())
    mix = te.filter(pl.col("wallet") == w).group_by("coin").agg(n=pl.len())
    tot = mix["n"].sum(); topc = mix.sort("n", descending=True).row(0, named=True)
    r = top.filter(pl.col("wallet") == w).row(0, named=True)
    rows.append((w, int(r["rank"]), int(r["tr_nd"]), own_te, float(np.nanmean(Mnet[i])), float(np.nanmean(Mal[i])),
                 base_n - lo_n, base_a - lo_a, own_sd, f"{topc['coin']}{100*topc['n']/tot:.0f}%"))
rows.sort(key=lambda x: -x[7])   # by alpha contribution
print(f"{'wallet':>10} {'rk':>3} {'trD':>4} {'teD':>4} {'teNet':>7} {'teAlf':>7} {'dNet':>6} {'dAlf':>6} {'daySD':>6} {'topCoin':>9}")
for w, rk, trd, ted, tn, ta, dn, da, sd, mx in rows:
    print(f"{w[:10]:>10} {rk:>3} {trd:>4} {ted:>4} {tn:>7.1f} {ta:>7.1f} {dn:>+6.2f} {da:>+6.2f} {sd:>6.1f} {mx:>9}")
# dependence on 1-2 wallets: remove top-2 positive and top-2 negative alpha contributors
order = sorted(range(NW), key=lambda i: base_a - ew(Mal[[j for j in range(NW) if j != i]]))  # ascending by contribution
pos2 = [i for i in reversed(order)][:2]; neg2 = order[:2]
def drop(ix):
    idx = [j for j in range(NW) if j not in ix]; return ew(Mnet[idx]), ew(Mal[idx])
dn2, da2 = drop(pos2); dnn, dan = drop(neg2)
print(f"  base EW: A net {base_n:+.2f}  B alpha {base_a:+.2f}")
print(f"  remove top-2 POSITIVE alpha contributors ({', '.join(ev[i][:8] for i in pos2)}): A {dn2:+.2f}  B {da2:+.2f}")
print(f"  remove top-2 NEGATIVE alpha contributors ({', '.join(ev[i][:8] for i in neg2)}): A {dnn:+.2f}  B {dan:+.2f}")
print(f"  -> B basket sign depends on <=2 wallets: {np.sign(da2)!=np.sign(base_a) or np.sign(dan)!=np.sign(base_a)}")
# flags: thin test coverage, disproportionate influence, or train->test top-coin drift
trtop = {r["wallet"]: r["coin"] for r in ep.filter(pl.col("split") == "train").group_by("wallet", "coin").agg(n=pl.len())
         .sort("n", descending=True).unique(subset="wallet", keep="first").iter_rows(named=True)}
tetop = {r["wallet"]: r["coin"] for r in te.group_by("wallet", "coin").agg(n=pl.len())
         .sort("n", descending=True).unique(subset="wallet", keep="first").iter_rows(named=True)}
print("  FLAGS (descriptive; no action taken on test perf):")
any_flag = False
for w, rk, trd, ted, tn, ta, dn, da, sd, mx in rows:
    fl = []
    if ted < 25: fl.append(f"thin-test({ted}d)")
    if abs(da) > 1.0: fl.append(f"high-influence(dAlf={da:+.1f})")
    if trtop.get(w) != tetop.get(w): fl.append(f"coin-drift({trtop.get(w)}->{tetop.get(w)})")
    if fl: any_flag = True; print(f"    {w[:10]}: {', '.join(fl)}")
if not any_flag: print("    none")
