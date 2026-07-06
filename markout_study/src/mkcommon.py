"""
Majors Markout Study — shared core (per ARCHITECTURE.md v3).

Everything correctness-critical lives here so the known-answer probe (probe.py) and the
batch engine (build_entries.py) exercise the SAME code. Reuses the audited, leak-free
pricing primitive `_next_bar_close_vec` from mlscreen2 (verified: prices the close of the
first bar starting strictly AFTER the fill's bar; NaN on >30-min gaps / delistings).
"""
import sys
from pathlib import Path

import numpy as np
from numba import njit

# audited helpers from the campaign engine (single source of truth)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scratch_conv"))
import mlscreen2  # noqa: E402
# mlscreen2.OUT is a RELATIVE path ("scratch_conv/mlscreen"); pin it absolute so bars/cand2
# resolve regardless of cwd (build_entries/probe run from anywhere).
mlscreen2.OUT = Path(__file__).resolve().parents[2] / "scratch_conv" / "mlscreen"
from mlscreen2 import BAR_MS, T0, _load_bars, _next_bar_close_vec  # noqa: E402

MAJORS = ["BTC", "ETH", "SOL", "HYPE", "SPX"]

# horizon ladder (label, milliseconds). Every entry is an integer multiple of BAR_MS
# (5 min) so entry and exit are always >= 1 distinct bar apart (no same-bar degeneracy).
_HR = 3_600_000
HORIZONS = [("5m", 5 * 60_000), ("15m", 15 * 60_000), ("30m", 30 * 60_000),
            ("1h", _HR), ("2h", 2 * _HR), ("4h", 4 * _HR), ("8h", 8 * _HR),
            ("12h", 12 * _HR), ("24h", 24 * _HR), ("48h", 48 * _HR),
            ("72h", 72 * _HR), ("168h", 168 * _HR)]
H_LABELS = [l for l, _ in HORIZONS]
H_MS = np.array([m for _, m in HORIZONS], dtype=np.int64)

MIN_NOTL = 100.0      # $ dust floor per entry (applied after pricing)
MIN_ENTRIES = 30      # per (wallet, coin) evidence-sufficiency floor (on non-dust entries)
FLAT_COEF = 1e-3      # flat_units(coin) = FLAT_COEF * median(|sz|); unit-based, price-agnostic
ALT_MIN_BARS = 500    # a "standard perp" for the ALT bucket needs >= this many in-window bars

# PLACEHOLDER round-trip cost (bps) per coin = 2*(taker_fee + half_spread + slippage);
# net_exec_bps is an UPPER BOUND on net edge pending BBO calibration (ARCHITECTURE §8).
COST_BPS = {"BTC": 8.0, "ETH": 8.0, "SOL": 10.0, "HYPE": 14.0, "SPX": 12.0}


def winsor_cap(ret_col):
    """p99 magnitude cap for a (coin,horizon) return column; None if too few finite points."""
    fin = np.isfinite(ret_col)
    if fin.sum() < 100:
        return None
    return float(np.percentile(np.abs(ret_col[fin]), 99))


def apply_winsor(ret_col, cap):
    """Winsorize |ret| at cap, re-apply sign. NaNs preserved. cap None -> unchanged."""
    if cap is None:
        return ret_col
    return np.sign(ret_col) * np.minimum(np.abs(ret_col), cap)

_EMPTY = (np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0, np.float64))
_EMPTY6 = _EMPTY + (np.empty(0, np.float64), np.empty(0, np.float64), np.empty(0, np.float64))


@njit(cache=True)
def _avg_entry_scan(px, sz, cum, flat_u):
    """Running average entry price of the OPEN inventory (fill-px basis). Scalar recurrence — a cumsum is
    WRONG because a partial reduce rebases the weight. `cum` = true position AFTER each fill (post burn-in).
    open-from-flat -> px; add (same sign) -> size-weighted; partial reduce -> unchanged; flip -> px; close -> NaN."""
    n = px.size
    a = np.empty(n)
    prev_pos = 0.0
    prev_a = np.nan
    for i in range(n):
        pos = cum[i]
        if abs(prev_pos) < flat_u:                       # was flat -> fresh open at this fill
            cur = px[i]
        elif (sz[i] > 0) == (prev_pos > 0):              # same sign as position -> ADD
            cur = (prev_a * abs(prev_pos) + px[i] * abs(sz[i])) / (abs(prev_pos) + abs(sz[i]))
        elif abs(pos) < flat_u:                          # opposing, lands flat -> full close
            cur = np.nan
        elif (pos > 0) == (prev_pos > 0):                # opposing, same side remains -> partial reduce
            cur = prev_a
        else:                                            # opposing, crosses zero -> FLIP, reset to this px
            cur = px[i]
        a[i] = cur
        prev_pos = pos
        prev_a = cur
    return a


def taker_entries(ts, sz, crossed, zhash, flat_u, px=None, return_pos=False):
    """Core entry construction for ONE (wallet, coin). Fills already sorted by (ts, tid);
    `sz` signed (cand2). Returns (b_ts, d, q):
      b_ts : entry bar-start time (ms)
      d    : entry direction (+1 long / -1 short)
      q    : opening size in UNITS (taker, non-wash, position-increasing increment)

    Reference-faithful (coin_term_structure.py): TRUE position (cum over ALL fills) drives
    burn-in and the per-fill opening increment `comp`, but a fill is SCORED as an entry only
    when it is TAKER (`crossed`) and NON-WASH (`~zhash`) and increases |position|. Maker/wash
    fills move position (so subsequent `comp` and burn-in are correct) but are never scored.
    Opening fills are then clustered to one entry per (bar, direction) by summing `comp`, so a
    same-bar taker sweep = one decision at the shared next-bar price.
    NOTE (supersedes v3 §4.3 "bar-net"): pure bar-net cannot mask maker/wash per fill, so we
    use per-fill masked detection + (bar,dir) clustering. Intrabar reversals are counted
    per-leg (rare; surfaced via the within-bar-flip fraction). Empty if never-flat or no
    taker opening. Pipeline: burn-in -> recompute cum -> masked opening -> cluster.
    """
    empty = _EMPTY6 if return_pos else _EMPTY
    if ts.size == 0:
        return empty
    cum = np.cumsum(sz)                        # TRUE position over ALL fills
    # --- burn-in: discard through first return-to-flat; drop group if never flat (#11) ---
    flat = np.abs(cum) < flat_u
    if not flat.any():
        return empty
    ff = int(np.argmax(flat))
    sl = slice(ff + 1, None)
    ts, sz, crossed, zhash = ts[sl], sz[sl], crossed[sl], zhash[sl]
    if return_pos:
        px = px[sl]                           # [V-Stage0] fill px on the same post-burn-in slice
    if ts.size == 0:
        return empty
    cum = np.cumsum(sz)                        # from known-flat 0 at slice start
    pb = np.empty_like(cum)
    pb[0] = 0.0
    pb[1:] = cum[:-1]
    # per-fill position increment: |q| for open/add (sign same or pb==0), |cum| for a flip residual
    same = (np.sign(pb) == np.sign(cum)) | (pb == 0.0)
    comp = np.where(same, np.abs(cum) - np.abs(pb), np.abs(cum))
    open_fill = (comp > flat_u) & crossed & (~zhash)   # TAKER, non-wash, position-increasing
    if not open_fill.any():
        return empty
    oi = np.nonzero(open_fill)[0]
    bar = (ts[oi] // BAR_MS) * BAR_MS
    d = np.sign(cum[oi]).astype(np.int64)
    q = comp[oi]
    # --- cluster opening fills by (bar, direction), summing comp ---
    order = np.lexsort((d, bar))
    bar, d, q = bar[order], d[order], q[order]
    new = np.empty(bar.size, bool)
    new[0] = True
    new[1:] = (bar[1:] != bar[:-1]) | (d[1:] != d[:-1])
    gid = np.cumsum(new) - 1
    ng = int(gid[-1]) + 1
    qs = np.zeros(ng)
    np.add.at(qs, gid, q)
    if not return_pos:
        return bar[new], d[new], qs
    # [V-Stage0] per-cluster: pos_after & avg_entry_px at the LAST opening fill; fill_vwap = Σ(px·comp)/Σcomp
    avg_full = _avg_entry_scan(px.astype(np.float64), sz.astype(np.float64), cum.astype(np.float64), float(flat_u))
    oi_s = oi[order]                                   # original fill index of each opening fill
    pos_s = cum[oi][order]                             # true position after the fill
    avg_s = avg_full[oi][order]
    pxw = np.zeros(ng); np.add.at(pxw, gid, px[oi][order] * q)   # comp-weighted px sum
    fill_vwap = pxw / qs
    gmax = np.full(ng, -1, np.int64); np.maximum.at(gmax, gid, oi_s)   # last (max orig-idx) fill per group
    is_last = oi_s == gmax[gid]                        # exactly one per group (fill indices distinct)
    pos_after = np.empty(ng); avg_entry = np.empty(ng)
    pos_after[gid[is_last]] = pos_s[is_last]
    avg_entry[gid[is_last]] = avg_s[is_last]
    return bar[new], d[new], qs, pos_after, avg_entry, fill_vwap


def price_entries(lk, b_ts, q):
    """Post-fill entry price + notional for a batch of same-coin entries.
    Returns (entry_px, notl) with NaN entry_px where the coin has no priceable next bar."""
    entry_px = _next_bar_close_vec(lk, b_ts)   # close of first bar strictly after bar b
    notl = q * entry_px
    return entry_px, notl


def markout_ret(lk, b_ts, d, entry_px):
    """Signed post-fill markout return per entry x horizon (raw, un-winsorized).
    Returns (n_entries, n_horizons) float array; NaN where entry or exit unpriceable.
    ret = d * (exit_close(b + h) / entry_close(b) - 1). Both endpoints use the same
    forward primitive, so both are strictly post-fill and consistent."""
    n = b_ts.size
    out = np.full((n, H_MS.size), np.nan)
    valid_entry = np.isfinite(entry_px) & (entry_px > 0)
    for j, hms in enumerate(H_MS):
        exit_px = _next_bar_close_vec(lk, b_ts + int(hms))
        ok = valid_entry & np.isfinite(exit_px) & (exit_px > 0)
        out[ok, j] = d[ok] * (exit_px[ok] / entry_px[ok] - 1.0)
    return out


def load_flat_units(cand_files):
    """flat_units(coin) = FLAT_COEF * median(|sz|) over the coin's fills. Unit-based so it
    works for $68k BTC and $0.0001 alts alike (re-audit NEW-4)."""
    import polars as pl
    med = (pl.scan_parquet(cand_files)
           .filter(pl.col("ts") >= T0)
           .group_by("coin")
           .agg(m=pl.col("sz").abs().median())
           .collect(engine="streaming"))
    return {str(c): FLAT_COEF * float(m) for c, m in zip(med["coin"], med["m"])}
