"""
Stage 0 — known-answer single-wallet probe (pitfall #13 META-GUARD).

Runs the REAL mkcommon path on one (wallet, coin) and prints every intermediate so the
burn-in cut, bar-net entry construction, post-fill pricing, and one markout can be checked
by hand BEFORE any aggregate is trusted. Also runs synthetic hand-computed fixtures with
known answers (flip sizing, intrabar churn, within-bar flip, never-flat drop).

Usage: python probe.py [WALLET COIN]   (defaults to the largest-BTC wallet in shard 0x1)
"""
import sys
from glob import glob
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import (BAR_MS, T0, taker_entries, price_entries, markout_ret,
                      load_flat_units, _load_bars, H_LABELS, H_MS)

ROOT = Path(__file__).resolve().parents[1]
CAND = sorted(glob(str(ROOT.parent / "scratch_conv/mlscreen/cand2_*.parquet")))


def synthetic_fixtures():
    """Hand-computed known answers — no data, pure logic checks."""
    print("=" * 70, "\nSYNTHETIC FIXTURES (hand-computed expected values)\n" + "=" * 70)
    B = BAR_MS
    # Each test case prepends a [+1,-1] burn episode (bars 0,1) so burn-in discards it and the
    # REAL test episode starts from known-flat 0 at bar 2. (Burn-in always eats episode 1.)
    # crossed/zhash default all-taker non-wash unless the case tests masking.
    T = True; F = False
    cases = [
        # (name, ts, sz, crossed, zhash, flat_u, expected [(bar_idx, dir, q), ...])
        ("burn + open/add/reduce/flip/close, distinct bars",
         [0, B, 2*B, 3*B, 4*B, 5*B, 6*B], [1, -1, 10, 5, -6, -14, 5], [T]*7, [F]*7, 0.5,
         [(2, +1, 10), (3, +1, 5), (5, -1, 5)]),          # -6 reduces (no entry); +5 closes (no entry)
        ("burn + intrabar churn +10,-3,+5 in ONE bar -> sum taker opening comps = 15",
         [0, B, 2*B, 2*B, 2*B], [1, -1, 10, -3, 5], [T]*5, [F]*5, 0.5,
         [(2, +1, 15)]),                                   # per-fill masked comps (10+5), reduce -3 excluded
        ("burn + within-bar flip +10 then -14 in ONE bar -> long10 + short4",
         [0, B, 2*B, 2*B], [1, -1, 10, -14], [T]*4, [F]*4, 0.5,
         [(2, +1, 10), (2, -1, 4)]),                       # per-leg: open long10, flip-open short4
        ("never returns flat -> whole (wallet,coin) dropped",
         [0, B], [10, 5], [T]*2, [F]*2, 0.5, []),
        ("flat-at-start: first episode (+10,-10) burned in",
         [0, B, 2*B, 3*B], [10, -10, 8, 3], [T]*4, [F]*4, 0.5,
         [(2, +1, 8), (3, +1, 3)]),                        # +10,-10 is episode1 (burned); then open 8, add 3
        ("MAKER opening at bar2 excluded, position still tracked (taker add at bar3 = 5)",
         [0, B, 2*B, 3*B], [1, -1, 10, 5], [T, T, F, T], [F]*4, 0.5,
         [(3, +1, 5)]),                                    # +10 is maker (not scored); +5 taker add -> comp 5
        ("ZHASH (wash) opening excluded -> no entry",
         [0, B, 2*B], [1, -1, 10], [T, T, T], [F, F, T], 0.5, []),
    ]
    ok = True
    for name, ts, sz, cr, zh, fu, exp in cases:
        b, d, q = taker_entries(np.array(ts, np.int64), np.array(sz, float),
                                np.array(cr, bool), np.array(zh, bool), fu)
        got = sorted((int(bt // BAR_MS), int(dd), round(float(qq), 6)) for bt, dd, qq in zip(b, d, q))
        exp = sorted((bi, di, float(qi)) for bi, di, qi in exp)
        good = got == exp
        ok &= good
        print(f"  [{'PASS' if good else 'FAIL'}] {name}\n         got={got}\n         exp={exp}")
    print(f"\nSYNTHETIC: {'ALL PASS' if ok else 'FAILURES ABOVE'}\n")
    return ok


def real_wallet(wallet=None, coin="BTC"):
    print("=" * 70, "\nREAL-DATA TRACE\n" + "=" * 70)
    lookups = _load_bars()
    flat_u = load_flat_units(CAND)
    if wallet is None:
        # deterministic pick: among the top-volume shard-0x1 wallets, the first that actually
        # returns flat (episodic trader), so the trace is useful (always-on MMs never flatten).
        cand = (pl.scan_parquet(CAND)
                .filter(pl.col("wallet").str.starts_with("0x1") & (pl.col("coin") == coin) & (pl.col("ts") >= T0))
                .group_by("wallet").agg(v=(pl.col("sz").abs() * pl.col("px")).sum(), nf=pl.len())
                .filter((pl.col("nf") >= 50) & (pl.col("nf") <= 2000))
                .sort("v", descending=True).head(40).collect(engine="streaming"))
        clist = cand["wallet"].to_list()
        allf = (pl.scan_parquet(CAND)
                .filter(pl.col("wallet").is_in(clist) & (pl.col("coin") == coin) & (pl.col("ts") >= T0))
                .select("wallet", "ts", "tid", "sz", "crossed", "zhash")
                .collect(engine="streaming").sort(["wallet", "ts", "tid"]))
        wallet = None
        for w in clist:  # ranked by volume
            gg = allf.filter(pl.col("wallet") == w)
            b, _, _ = taker_entries(gg["ts"].to_numpy(), gg["sz"].to_numpy(),
                                    gg["crossed"].to_numpy(), gg["zhash"].to_numpy(), flat_u.get(coin, 1e-9))
            if b.size >= 5:
                wallet = w
                break
        assert wallet is not None, "no episodic BTC wallet found in sample"
    print(f"wallet={wallet}  coin={coin}  flat_units={flat_u.get(coin):.6g}")
    g = (pl.scan_parquet(CAND)
         .filter((pl.col("wallet") == wallet) & (pl.col("coin") == coin) & (pl.col("ts") >= T0))
         .select("ts", "tid", "sz", "px", "crossed", "zhash")
         .collect(engine="streaming").sort(["ts", "tid"]))
    ts = g["ts"].to_numpy(); sz = g["sz"].to_numpy()
    cr = g["crossed"].to_numpy(); zh = g["zhash"].to_numpy()
    cum = np.cumsum(sz)
    flat = np.abs(cum) < flat_u.get(coin, 1e-9)
    ff = int(np.argmax(flat)) if flat.any() else -1
    print(f"fills={ts.size:,}  taker={cr.sum():,}  wash(zhash)={zh.sum():,}  "
          f"first-flat idx={ff}  never-flat={not flat.any()}")
    b_ts, d, q = taker_entries(ts, sz, cr, zh, flat_u.get(coin, 1e-9))
    print(f"bar-net entries after burn-in: {b_ts.size:,}")
    if b_ts.size == 0:
        return
    lk = lookups[coin]
    entry_px, notl = price_entries(lk, b_ts, q)
    ret = markout_ret(lk, b_ts, d, entry_px)
    print("\nfirst 5 entries (hand-checkable):")
    print(f"{'bar_start_ms':>14} {'dir':>4} {'q(units)':>12} {'entry_px':>12} {'notl$':>12} "
          f"{'ret_1h':>9} {'ret_24h':>9}")
    i1h = H_LABELS.index("1h"); i24 = H_LABELS.index("24h")
    for i in range(min(5, b_ts.size)):
        print(f"{b_ts[i]:>14} {d[i]:>4} {q[i]:>12.4f} {entry_px[i]:>12.2f} {notl[i]:>12.0f} "
              f"{ret[i, i1h]*1e4:>8.1f}b {ret[i, i24]*1e4:>8.1f}b")
    # hand-verify entry 0's 1h markout against raw bar closes
    from mkcommon import _next_bar_close_vec
    b0 = int(b_ts[0])
    ep = _next_bar_close_vec(lk, np.array([b0]))[0]
    xp = _next_bar_close_vec(lk, np.array([b0 + 3_600_000]))[0]
    print(f"\nENTRY-0 CHECK: entry_px=close(bar after {b0})={ep:.2f}  "
          f"exit_1h=close(bar after {b0+3_600_000})={xp:.2f}  "
          f"ret=dir*({xp:.2f}/{ep:.2f}-1)={d[0]*(xp/ep-1)*1e4:+.1f}bps  "
          f"(matches table: {abs(d[0]*(xp/ep-1) - ret[0, i1h]) < 1e-12})")
    print(f"\ncoverage @168h for this wallet: "
          f"{np.isfinite(ret[:, H_LABELS.index('168h')]).mean():.1%}")


if __name__ == "__main__":
    ok = synthetic_fixtures()
    args = sys.argv[1:]
    real_wallet(args[0] if len(args) > 0 else None, args[1] if len(args) > 1 else "BTC")
    sys.exit(0 if ok else 1)
