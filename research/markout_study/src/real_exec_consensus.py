"""
REALISTIC-EXECUTION stress test of the consensus>=9 copy signal.

Signal: when >=9 cohort wallets (out/cohort_wallets.txt) open the same coin+direction within a
trailing 30-min window, copy the trade; exit 4-6h later. Idealized (mid-to-mid, flat COST_BPS)
OOS net ~ +12.6bp@4h / +15.5bp@6h. This script re-prices the SAME events against the raw fill
tape: real crossing prices both sides, detection lag / adverse entry, exit into the fade, funding,
and a capacity estimate. TEST = b_ts >= 2026-03-01.

Everything is grounded in the tape (../scratch_conv/mlscreen/cand2_*.parquet, crossed=taker fills).
"""
import glob
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import _load_bars, _next_bar_close_vec, COST_BPS

OUT = Path("out")
COINS = ["BTC", "ETH", "SOL", "HYPE"]
BP = 1e4
BAR = 300_000  # 5-min bar ms
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TEST_LO = _ms(2026, 3, 1)
WIN = 30 * 60_000            # trailing consensus window
CONS_THR = 9                 # >=9 earlier same-dir cohort entries in the trailing window
HZ = {"4h": 4 * 3_600_000, "6h": 6 * 3_600_000}
TAKER_FEE_BP = 3.5           # per side; HL taker ~1.5-4.5bp by tier. Sensitivity printed.
VWAP_W = 60_000              # window over which the follower's crossing VWAP is measured
TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_2026*.parquet"))


def nbc(L, t):
    return _next_bar_close_vec(L, t)


def build_events(cohort, lk):
    """Reproduce the consensus>=9 flagged cohort entries in TEST, per coin+dir. Returns a DataFrame
    with coin, b_ts, dir, cons, and a burst id (distinct burst = >30min gap in same coin+dir)."""
    rows = []
    for c in COINS:
        ec = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
              .filter((pl.col("coin") == c) & pl.col("wallet").is_in(cohort) & (pl.col("b_ts") >= TEST_LO))
              .select("b_ts", "dir", "notl").sort("b_ts").collect())
        b = ec["b_ts"].to_numpy(); d = ec["dir"].to_numpy().astype(np.int64)
        notl = ec["notl"].to_numpy()
        cons = np.zeros(b.size, np.int64)
        for sgn in (1, -1):
            idx = np.where(d == sgn)[0]
            tb = b[idx]
            pos = np.arange(idx.size)
            cons[idx] = pos - np.searchsorted(tb, tb - WIN)   # earlier same-dir entries in (t-WIN,t)
        rows.append(pl.DataFrame({"coin": [c] * b.size, "b_ts": b, "dir": d, "cons": cons, "notl": notl}))
    E = pl.concat(rows)
    F = E.filter(pl.col("cons") >= CONS_THR).sort(["coin", "dir", "b_ts"])
    # collapse consecutive flagged entries (same coin+dir, gap<=WIN) into one burst -> one follower trade
    fb = F.select("coin", "dir", "b_ts").to_numpy()
    burst = np.zeros(F.height, np.int64)
    bid = -1
    prev_key = None; prev_t = None
    for i in range(F.height):
        key = (fb[i, 0], fb[i, 1]); t = int(fb[i, 2])
        if key != prev_key or (t - prev_t) > WIN:
            bid += 1
        burst[i] = bid
        prev_key, prev_t = key, t
    F = F.with_columns(pl.Series("burst", burst))
    return E, F


def load_takers(coin):
    """Taker fills for one coin in TEST, split into buy/sell cumulative arrays for window VWAP."""
    df = (pl.scan_parquet(TAPE)
          .filter((pl.col("coin") == coin) & (pl.col("ts") >= TEST_LO - WIN) & pl.col("crossed"))
          .select("ts", "px", "sz").collect().sort("ts"))
    ts = df["ts"].to_numpy(); px = df["px"].to_numpy(); sz = df["sz"].to_numpy()
    out = {}
    for side, mask in (("buy", sz > 0), ("sell", sz < 0)):
        t = ts[mask]; p = px[mask]; s = np.abs(sz[mask])
        cps = np.concatenate([[0.0], np.cumsum(p * s)])
        cs = np.concatenate([[0.0], np.cumsum(s)])
        out[side] = (t, cps, cs)
    return out, ts, px, sz


def win_vwap(side_arr, a, b):
    """VWAP of takers on one side in [a,b). NaN if no volume. Also returns notional traded ($)."""
    t, cps, cs = side_arr
    i = np.searchsorted(t, a); j = np.searchsorted(t, b)
    vol = cs[j] - cs[i]
    if vol <= 0:
        return np.nan, 0.0
    return (cps[j] - cps[i]) / vol, cps[j] - cps[i]


def funding_cost_bps(coin, t0, t1, dr, fund):
    """Funding paid by the position over [t0,t1]. Longs pay sum(rate) when rate>0. bps."""
    ft, fr = fund[coin]
    i = np.searchsorted(ft, t0); j = np.searchsorted(ft, t1)
    if j <= i:
        return 0.0
    return dr * float(fr[i:j].sum()) * BP


def main():
    cohort = set(x for x in Path("out/cohort_wallets.txt").read_text().split("\n") if x)
    lk = _load_bars()
    fund = {}
    fd = pl.read_parquet("../scratch_conv/mlscreen/funding.parquet").filter(pl.col("coin").is_in(COINS))
    for c in COINS:
        g = fd.filter(pl.col("coin") == c).sort("time")
        fund[c] = (g["time"].to_numpy(), g["rate"].to_numpy())

    E, F = build_events(cohort, lk)
    n_flag = F.height
    n_burst = int(F["burst"].max()) + 1 if F.height else 0
    print(f"{'='*92}")
    print(f"CONSENSUS>={CONS_THR} REALISTIC EXECUTION  (TEST Mar-Jun'26)")
    print(f"{'='*92}")
    print(f"flagged cohort entries: {n_flag}   distinct bursts (>30min-separated): {n_burst}")
    print(f"per-coin flagged: " + "  ".join(f"{c}:{F.filter(pl.col('coin')==c).height}" for c in COINS))

    # ---- assemble per-coin tape and compute real round trips ----
    # For each flagged entry (event) we compute, per horizon:
    #   mid_entry = NBC(b_ts); mid_exit = NBC(b_ts+H)  (idealized reference, same primitive as +15bp calc)
    #   entry crossing VWAP (taker in dir) at b_ts+off; exit crossing VWAP (taker in -dir) at b_ts+H+off
    # Offsets probe the latency regime.
    ENTRY_OFFS = {"bar0(fast)": 0, "next5m": BAR, "lag15m": 3 * BAR}
    recs = []
    burst_first_move = []   # descriptive: 1st-wallet -> trigger mid move (adverse, already-realized)
    cap_rows = []
    for c in COINS:
        Fc = F.filter(pl.col("coin") == c)
        if Fc.height == 0:
            continue
        L = lk[c]
        sides, allts, allpx, allsz = load_takers(c)
        b = Fc["b_ts"].to_numpy(); d = Fc["dir"].to_numpy().astype(np.int64); bu = Fc["burst"].to_numpy()
        me = nbc(L, b)                                   # mid entry (idealized)
        # 1st-wallet-in-burst mid, to measure the already-realized adverse move
        Eall = E.filter(pl.col("coin") == c)
        for hlabel, H in HZ.items():
            mx = nbc(L, b + H)
            for oname, off in ENTRY_OFFS.items():
                for k in range(Fc.height):
                    dr = int(d[k])
                    ev = "buy" if dr > 0 else "sell"
                    xv = "sell" if dr > 0 else "buy"
                    a0 = int(b[k]) + off
                    epx, evol = win_vwap(sides[ev], a0, a0 + VWAP_W)
                    a1 = int(b[k]) + H + off
                    xpx, xvol = win_vwap(sides[xv], a1, a1 + VWAP_W)
                    if not (np.isfinite(epx) and np.isfinite(xpx) and np.isfinite(me[k]) and np.isfinite(mx[k])):
                        continue
                    real_gross = dr * (xpx / epx - 1.0) * BP
                    mid_drift = dr * (mx[k] / me[k] - 1.0) * BP
                    entry_slip = dr * (epx / me[k] - 1.0) * BP        # >0 = paid worse than mid
                    exit_slip = dr * (mx[k] / xpx - 1.0) * BP         # >0 = sold worse than mid
                    fund_bps = funding_cost_bps(c, int(b[k]), int(b[k]) + H, dr, fund)
                    net = real_gross - 2 * TAKER_FEE_BP - fund_bps
                    recs.append((c, hlabel, oname, dr, int(bu[k]), mid_drift, real_gross,
                                 entry_slip, exit_slip, fund_bps, net, evol))
        # capacity + first-move: per flagged event at bar0
        for k in range(Fc.height):
            dr = int(d[k]); ev = "buy" if dr > 0 else "sell"
            a0 = int(b[k])
            _, evol = win_vwap(sides[ev], a0, a0 + BAR)     # same-dir taker $ in the trigger bar
            _, evol60 = win_vwap(sides[ev], a0, a0 + VWAP_W)
            cap_rows.append((c, int(bu[k]), evol, evol60))
            # first same-dir cohort entry in the trailing window
            eb = Eall.filter((pl.col("dir") == dr) & (pl.col("b_ts") >= int(b[k]) - WIN)
                             & (pl.col("b_ts") <= int(b[k])))["b_ts"].to_numpy()
            if eb.size:
                m0 = nbc(L, int(eb.min())); m1 = me[k]
                if np.isfinite(m0) and np.isfinite(m1) and m0 > 0:
                    burst_first_move.append(dr * (m1 / m0 - 1.0) * BP)

    R = pl.DataFrame(recs, schema=["coin", "hz", "off", "dir", "burst", "mid_drift", "real_gross",
                                   "entry_slip", "exit_slip", "fund", "net", "evol"], orient="row")

    # ---- (1) adverse-entry descriptive ----
    fm = np.array(burst_first_move)
    print(f"\n{'-'*92}\n(1) ADVERSE ENTRY — mid move from FIRST same-dir cohort wallet in the window -> the")
    print(f"    trigger bar (already-realized move the crowd made before you can act):")
    print(f"    median {np.median(fm):+.1f} bp | mean {np.mean(fm):+.1f} bp | p75 {np.percentile(fm,75):+.1f}"
          f" | frac>0 {100*np.mean(fm>0):.0f}%   (N={fm.size})")
    print(f"    NOTE: the +15bp forward markout is priced FROM the trigger, so this move is already")
    print(f"    excluded from it. It is shown to confirm the crowd has moved (fills are into a run).")

    # ---- (2) real spread both sides, per coin (at the fast/bar0 offset, pooled over horizons dedup by event) ----
    print(f"\n{'-'*92}\n(2) REAL CROSSING COST both sides (tape VWAP vs bar-close mid), per coin:")
    print(f"    {'coin':5s} {'entry_slip':>11s} {'exit_slip':>10s} {'round-trip':>11s}   vs flat COST_BPS")
    s0 = R.filter((pl.col("off") == "bar0(fast)") & (pl.col("hz") == "4h"))
    for c in COINS:
        sc = s0.filter(pl.col("coin") == c)
        if sc.height == 0:
            continue
        es = sc["entry_slip"].mean(); xs = sc["exit_slip"].mean()
        print(f"    {c:5s} {es:>+11.2f} {xs:>+10.2f} {es+xs:>+11.2f}   (flat={COST_BPS[c]:.0f})")
    es = s0["entry_slip"].mean(); xs = s0["exit_slip"].mean()
    print(f"    {'ALL':5s} {es:>+11.2f} {xs:>+10.2f} {es+xs:>+11.2f}   (flat mean~9.8)")

    # ---- (3+4+6) net edge by horizon x latency, with funding, event-level and burst-level ----
    print(f"\n{'-'*92}\n(3-6) NET EDGE after real spread both sides + {2*TAKER_FEE_BP:.0f}bp fees + funding:")
    print(f"    (event = each flagged entry; burst = one follower trade per 30-min cluster)")
    for hlabel in HZ:
        print(f"\n  --- {hlabel} hold ---")
        print(f"    {'latency':14s} {'mid_drift':>9s} {'realGross':>9s} {'fund':>6s} {'NET/ev':>7s} "
              f"{'NET/burst':>9s} {'%pos/burst':>10s} {'N_ev':>5s}")
        for oname in ["bar0(fast)", "next5m", "lag15m"]:
            s = R.filter((pl.col("hz") == hlabel) & (pl.col("off") == oname))
            if s.height == 0:
                continue
            # burst-level: average events within a burst (one trade), then average across bursts
            bg = s.group_by("burst").agg(pl.col("net").mean(), pl.col("mid_drift").mean(),
                                         pl.col("real_gross").mean(), pl.col("fund").mean())
            netb = bg["net"].to_numpy()
            print(f"    {oname:14s} {s['mid_drift'].mean():>+9.1f} {s['real_gross'].mean():>+9.1f} "
                  f"{s['fund'].mean():>+6.2f} {s['net'].mean():>+7.1f} {np.mean(netb):>+9.1f} "
                  f"{100*np.mean(netb>0):>9.0f}% {s.height:>5d}")

    # ---- burst-level CI (cluster by burst) for the headline fast case ----
    print(f"\n{'-'*92}\n(verdict CI) burst-clustered net, FAST (bar0) execution:")
    rng = np.random.default_rng(7)
    for hlabel in HZ:
        s = R.filter((pl.col("hz") == hlabel) & (pl.col("off") == "bar0(fast)"))
        bg = s.group_by("burst").agg(pl.col("net").mean())
        v = bg["net"].to_numpy(); m = v.size
        boot = np.array([v[rng.integers(0, m, m)].mean() for _ in range(5000)])
        lo, hi = np.percentile(boot, [2.5, 97.5])
        print(f"    {hlabel}: net/burst {v.mean():+.1f} bp  95%CI [{lo:+.1f}, {hi:+.1f}]  "
              f"(N_burst={m})  {'EXCLUDES 0' if lo>0 else 'SPANS 0'}")

    # ---- (5) capacity ----
    cap = pl.DataFrame(cap_rows, schema=["coin", "burst", "vol_bar", "vol_60s"], orient="row")
    capb = cap.group_by("coin").agg(pl.col("vol_bar").median().alias("med_bar_$"),
                                    pl.col("vol_60s").median().alias("med_60s_$"))
    print(f"\n{'-'*92}\n(5) CAPACITY — same-direction TAKER $ volume available to fill into at the trigger:")
    print(f"    (a follower taking ~X% of one-side flow moves price ~X% of spread; rough ceiling)")
    print(capb.sort("coin"))
    print(f"    interpretation: median trigger-bar one-side taker flow above; sizing to ~1-5% of it")
    print(f"    keeps own-impact small vs the measured spread.")

    R.write_parquet(OUT / "real_exec_consensus.parquet")
    print(f"\n-> out/real_exec_consensus.parquet   (fee/side={TAKER_FEE_BP}bp; try 1.5 & 4.5 for sensitivity)")


if __name__ == "__main__":
    main()
