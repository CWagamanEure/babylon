"""PYRAMID-ALT — DESCRIPTIVE MECHANICS VERIFICATION on burned folds 202511-202606.

Implements the FROZEN spec of PYRAMID_ALT_PREREG.md exactly (lead arm), solely to verify
plumbing/dollar accounting of the ladder before the forward paper trader. STAMP: burned folds;
NO variants, NO parameter exploration; nothing here may be tuned from the result; the arm's
evaluation is FORWARD ONLY per the prereg's pre-set criteria.

Frozen spec implemented:
  - Selector: per fold, top-100 by t_stat from the informedness pool (data <= T-1), frozen-133
    excluded, pure-maker wallets excluded (formation taker share < 0.1 from lake wallet_coin_day).
  - Universe: alt perps (not BTC/ETH/SOL/HYPE) with TRAILING 3-mo (formation months) ADV >= $10M;
    signals with collapsed notional >= $250 only.
  - Signals per (wallet,coin): flat taker opens (lake open_entries) + adds (lake perp_fills:
    crossed Open* with start_position != 0), collapsed per (wallet,coin,ts,dir) block event;
    adds coinciding with a flat-open event (same wallet,coin,ts) are deduped to one signal.
  - Ladder: 1st flat-open = WATCH (no position; watch lives for that UTC calendar day).
    2nd signal (any add/re-open, same day while watching) = ENTER 1 unit at NEXT asset_ctx mid
    (<= 90s ahead). 3rd/4th signal = ADD 1 unit each (max 3 units; thesis window = while any
    position open, day-bound only in the watch state). Nothing after the 4th signal.
  - Exit: ALL units 8h after the last FILLED add; asset_ctx mid backward-ASOF <= 90s (forward
    fallback <= 10min, flagged). Unit = $2,500; caps: 3u/(wallet,coin), $50k gross/coin,
    $250k book gross. Cost: 21.5bp RT taker per unit.
  Deviations recorded (accounting hygiene, not tuning): the trader-full-exit hard stop and the
  maker shadow book are NOT simulated in this pass (forward paper trader implements both);
  entry basis is the per-minute asset_ctx mid, not the tape print (lag_haircut showed <= ~1.4bp
  median slippage at 30s).

Phases:
    python -m research.studies.copy_cohort.pyramid_book prep   # cohorts + caches + wallets json
    python -m research.studies.copy_cohort.pyramid_book run    # simulate + report (needs adds)

Adds are pulled on the DROPLET (established per-fill pattern): scp pyramid_wallets.json +
research/studies/copy_cohort assets, run /root/pull_pyramid_adds_droplet.py, scp back to
data/derived/copy_cohort/pyramid/adds/fold=YYYYMM.parquet.
"""
from __future__ import annotations

import heapq
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS
from . import lake
from .alt_fresh_validate import MAJORS, _ctx_parts

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
PYR = DERIVED / "pyramid"
ADDS_DIR = PYR / "adds"
POOL_DIR = DERIVED / "informedness"
FROZEN = DERIVED / "frozen_alt_universe.json"
COHORTS_JSON = PYR / "pyramid_cohorts.json"
WALLETS_JSON = PYR / "pyramid_wallets.json"
OUT_JSON = DERIVED / "pyramid_mechanics_report.json"
OUT_MD = REPO_ROOT / "research" / "studies" / "copy_cohort" / "BACKTEST.md"

FOLDS = MONTHS[3:]                     # 202511..202606 (burned)
K = 100
TAKER_MIN = 0.1
CAND_BUFFER = 400                      # taker-share screened candidate depth (must yield >= K)
ADV_MIN = 10_000_000.0
NOTL_MIN = 250.0
UNIT_USD = 2_500.0
MAX_UNITS = 3
COIN_CAP = 50_000.0
BOOK_CAP = 250_000.0
COST_RT_BP = 21.5
HOLD_MS = 28_800_000                   # 8h after last filled add
ENTRY_STALE_MS = 90_000                # next print within 90s or the unit is a miss
EXIT_STALE_MS = 90_000
EXIT_FWD_MAX_MS = 600_000
DAY_MS = 86_400_000
SPAN_T0_MS = int(datetime(2025, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
N_DAYS = 242
N_BOOT = 2000
SEED = 20260717

STAMP = ("DESCRIPTIVE MECHANICS VERIFICATION — burned folds 202511-202606; frozen spec "
         "PYRAMID_ALT_PREREG.md; no variants, no parameter exploration, nothing tuned from "
         "this result; evaluation of the arm is FORWARD ONLY (paper trader).")


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=REPO_ROOT).stdout.strip()
    except Exception:
        return "unknown"


def _formation_months(fold: int) -> list[int]:
    i = MONTHS.index(fold)
    return MONTHS[i - 3:i]


# --------------------------------------------------------------- cohort (prep)
def _taker_share(con, fold: int, cands: list[str]) -> dict[str, float]:
    """Formation taker share (sum n_taker / sum n_fills, lake wallet_coin_day) per candidate."""
    p = PYR / f"taker_{fold}.parquet"
    if not p.exists():
        globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in _formation_months(fold))
        con.execute("CREATE OR REPLACE TEMP TABLE tw AS SELECT UNNEST(?) AS wallet", [sorted(cands)])
        tmp = str(p) + ".tmp"
        con.execute(f"""COPY (
            SELECT d.wallet, SUM(d.n_taker) AS n_taker, SUM(d.n_fills) AS n_fills
            FROM read_parquet([{globs}]) d JOIN tw USING (wallet) GROUP BY d.wallet
        ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
        Path(tmp).replace(p)
        print(f"  fold {fold}: taker-share cached", flush=True)
    lc = duckdb.connect()
    rows = lc.execute(f"SELECT wallet, n_taker, n_fills FROM read_parquet('{p.as_posix()}')").fetchall()
    lc.close()
    return {w: (float(nt) / float(nf) if nf else 0.0) for w, nt, nf in rows}


def _cohort(con, fold: int) -> dict:
    """Top-100 by t_stat, frozen-133 + taker_share<0.1 excluded (deterministic tie-break)."""
    frozen = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    lc = duckdb.connect()
    d = lc.execute(f"""SELECT wallet, t_stat
                       FROM read_parquet('{(POOL_DIR / f'fold={fold}' / 'pool.parquet').as_posix()}')
                       WHERE t_stat IS NOT NULL""").fetchnumpy()
    lc.close()
    w = d["wallet"].astype(str)
    t = np.asarray(d["t_stat"], float)
    keep = np.array([x not in frozen for x in w])
    w, t = w[keep], t[keep]
    order = np.lexsort((w, -t))                       # t desc, wallet asc (deterministic)
    cand = w[order[:CAND_BUFFER]].tolist()
    cand_t = {x: float(tt) for x, tt in zip(cand, t[order[:CAND_BUFFER]])}
    share = _taker_share(con, fold, cand)
    passed = [x for x in cand if share.get(x, 0.0) >= TAKER_MIN]
    if len(passed) < K:
        raise RuntimeError(f"fold {fold}: only {len(passed)} of top-{CAND_BUFFER} pass the "
                           f"taker screen — raise CAND_BUFFER")
    sel = passed[:K]
    return {"wallets": sel, "formation_months": _formation_months(fold),
            "n_screened_out_of_top100_rank": int(sum(1 for x in cand[:K] if x not in sel)),
            "t_range": [cand_t[sel[-1]], cand_t[sel[0]]],
            "taker_share_min_selected": min(share[x] for x in sel)}


# ------------------------------------------------------ trailing formation ADV
def _advm(con, month: int) -> Path:
    """Per-month per-coin (sum notional / 2, distinct active days) — exact 3-mo combinable."""
    p = PYR / f"advm_{month}.parquet"
    if not p.exists():
        tmp = str(p) + ".tmp"
        con.execute(f"""COPY (
            SELECT coin, SUM(CAST(notional AS DOUBLE)) / 2 AS notl_half,
                   COUNT(DISTINCT day) AS n_days
            FROM read_parquet('{lake.wcd_month_glob(month)}') GROUP BY coin
        ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
        Path(tmp).replace(p)
        print(f"  advm cached: {month}", flush=True)
    return p


def _liquid_alts(con, fold: int) -> dict[str, float]:
    """Trailing 3-mo (formation months) ADV >= $10M, majors excluded. Returns coin -> adv."""
    acc: dict[str, list[float]] = {}
    for m in _formation_months(fold):
        p = _advm(con, m)
        lc = duckdb.connect()
        for c, nh, ndd in lc.execute(
                f"SELECT coin, notl_half, n_days FROM read_parquet('{p.as_posix()}')").fetchall():
            a = acc.setdefault(c, [0.0, 0.0])
            a[0] += float(nh)
            a[1] += float(ndd)
        lc.close()
    return {c: a[0] / a[1] for c, a in acc.items()
            if c not in MAJORS and a[1] > 0 and a[0] / a[1] >= ADV_MIN}


# ------------------------------------------------------------------- signals
def _opens(con, fold: int, wallets: list[str]):
    p = PYR / f"opens_{fold}.parquet"
    if not p.exists():
        con.execute("CREATE OR REPLACE TEMP TABLE cw AS SELECT UNNEST(?) AS wallet", [sorted(wallets)])
        tmp = str(p) + ".tmp"
        con.execute(f"""COPY (
            SELECT o.wallet, o.coin, o.ts, o.dir_sign,
                   SUM(CAST(o.notl AS DOUBLE)) AS notl
            FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN cw USING (wallet)
            GROUP BY o.wallet, o.coin, o.ts, o.dir_sign
        ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
        Path(tmp).replace(p)
        print(f"  fold {fold}: opens cached", flush=True)
    lc = duckdb.connect()
    d = lc.execute(f"SELECT * FROM read_parquet('{p.as_posix()}')").fetchnumpy()
    lc.close()
    return d


def _adds(fold: int):
    p = ADDS_DIR / f"fold={fold}.parquet"
    if not p.exists():
        raise RuntimeError(
            f"missing adds cache {p} — pull on the droplet: scp {WALLETS_JSON} + "
            "pull_pyramid_adds_droplet.py to root@10.116.0.4 (jump 167.71.29.107), run with "
            "/root/lakeenv/bin/python, scp fold=*.parquet back into data/derived/copy_cohort/pyramid/adds/")
    lc = duckdb.connect()
    d = lc.execute(f"SELECT * FROM read_parquet('{p.as_posix()}')").fetchnumpy()
    lc.close()
    lo, hi = (int(d["ts"].min()), int(d["ts"].max())) if d["ts"].size else (0, 0)
    if d["ts"].size and not (1.4e12 < lo <= hi < 2.1e12):
        raise RuntimeError(f"fold {fold}: adds ts not epoch-ms: [{lo}, {hi}]")
    return d


def _fold_signals(con, fold: int, wallets: list[str], liquid: dict[str, float]):
    """Merged eligible signal stream (ts-sorted): opens + adds, liquid alts, notl >= $250."""
    op = _opens(con, fold, wallets)
    ad = _adds(fold)
    wset = set(wallets)
    open_keys = set(zip(op["wallet"].astype(str).tolist(), op["coin"].astype(str).tolist(),
                        np.asarray(op["ts"], np.int64).tolist()))
    n_add_dedup = 0
    cols = {"wallet": [], "coin": [], "ts": [], "dir": [], "notl": [], "is_add": []}

    def push(d, is_add: bool):
        nonlocal n_add_dedup
        w = d["wallet"].astype(str)
        c = d["coin"].astype(str)
        ts = np.asarray(d["ts"], np.int64)
        dr = np.asarray(d["dir_sign"], np.int64)
        nl = np.asarray(d["notl"], float)
        m = np.array([x in liquid for x in c]) & (nl >= NOTL_MIN)
        if is_add:
            m &= np.array([x in wset for x in w])          # droplet list == cohort, but be safe
        idx = np.flatnonzero(m)
        if is_add and idx.size:
            dup = np.array([(w[j], c[j], int(ts[j])) in open_keys for j in idx])
            n_add_dedup += int(dup.sum())
            idx = idx[~dup]
        for k, v in (("wallet", w), ("coin", c), ("ts", ts), ("dir", dr), ("notl", nl)):
            cols[k].append(v[idx])
        cols["is_add"].append(np.full(idx.size, is_add))

    push(op, False)
    push(ad, True)
    s = {k: np.concatenate(v) for k, v in cols.items()}
    o = np.lexsort((s["is_add"], s["coin"], s["wallet"], s["ts"]))
    return {k: v[o] for k, v in s.items()}, n_add_dedup


# ----------------------------------------------------------------- ctx prices
def _ctx_by_coin(fold: int, coins: set[str]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    parts = _ctx_parts(fold)
    if not parts:
        raise RuntimeError(f"no asset_ctx for fold {fold}")
    cl = ",".join(f"'{c}'" for c in sorted(coins))
    pl = ",".join(f"'{p}'" for p in parts)
    lc = duckdb.connect()
    d = lc.execute(f"""SELECT coin, ts, mid_px FROM read_parquet([{pl}])
                       WHERE mid_px IS NOT NULL AND mid_px > 0 AND coin IN ({cl})
                       ORDER BY coin, ts""").fetchnumpy()
    lc.close()
    coin = d["coin"].astype(str)
    ts = np.asarray(d["ts"], np.int64)
    px = np.asarray(d["mid_px"], float)
    out = {}
    bounds = np.flatnonzero(np.r_[True, coin[1:] != coin[:-1], True])
    for i, j in zip(bounds[:-1], bounds[1:]):
        out[coin[i]] = (ts[i:j], px[i:j])
    return out


def _entry_px(ctx, coin, ts):
    """Next print at/after ts within ENTRY_STALE_MS -> (px, print_ts) or None."""
    arr = ctx.get(coin)
    if arr is None:
        return None
    t, p = arr
    i = np.searchsorted(t, ts, side="left")
    if i < t.size and t[i] - ts <= ENTRY_STALE_MS:
        return float(p[i]), int(t[i])
    return None


def _exit_px(ctx, coin, ts):
    """Backward ASOF <= EXIT_STALE_MS; forward fallback <= EXIT_FWD_MAX_MS (flagged)."""
    t, p = ctx[coin]
    i = np.searchsorted(t, ts, side="right") - 1
    if i >= 0 and ts - t[i] <= EXIT_STALE_MS:
        return float(p[i]), 0
    j = i + 1
    if j < t.size and t[j] - ts <= EXIT_FWD_MAX_MS:
        return float(p[j]), 1
    if i >= 0:
        return float(p[i]), 2
    return None, 3


# ------------------------------------------------------------------ simulator
def simulate_fold(fold: int, sig, ctx, funnel, units_out):
    theses: dict[tuple[str, str], dict] = {}
    hp: list[tuple[int, str, str]] = []     # lazy heap of (exit_ts, wallet, coin)
    gross_state = {"book": 0.0, "coin": {}}

    def close_thesis(key):
        th = theses.pop(key)
        gross_state["book"] -= UNIT_USD * len(th["units"])
        gross_state["coin"][key[1]] -= UNIT_USD * len(th["units"])
        px1, flag = _exit_px(ctx, key[1], th["exit_ts"])
        funnel["exit_flag_counts"][str(flag)] = funnel["exit_flag_counts"].get(str(flag), 0) + 1
        for u in th["units"]:
            gross = u["dir"] * (px1 - u["px0"]) / u["px0"] * UNIT_USD if px1 else 0.0
            if px1 is None:
                funnel["n_units_no_exit_px"] += 1
            units_out.append({
                "fold": fold, "wallet": key[0], "coin": key[1], "rung": u["rung"],
                "ts_sig": u["ts_sig"], "ts_fill": u["ts_fill"], "exit_ts": th["exit_ts"],
                "dir": u["dir"], "flip": u["dir"] != th["dir0"],
                "gross": gross, "net": gross - UNIT_USD * COST_RT_BP * 1e-4,
            })

    def flush_until(ts):
        while hp and hp[0][0] <= ts:
            ex, w, c = heapq.heappop(hp)
            th = theses.get((w, c))
            if th is not None and th["state"] == "open" and th["exit_ts"] == ex:
                close_thesis((w, c))

    def fire_unit(key, ts, dr, rung):
        """Cap + print checks; returns True iff a unit was filled."""
        if gross_state["book"] + UNIT_USD > BOOK_CAP:
            funnel["n_cap_skip_book"] += 1
            return False
        if gross_state["coin"].get(key[1], 0.0) + UNIT_USD > COIN_CAP:
            funnel["n_cap_skip_coin"] += 1
            return False
        got = _entry_px(ctx, key[1], ts)
        if got is None:
            funnel["n_miss_entry_px"] += 1
            return False
        px0, ts_fill = got
        th = theses[key]
        th["units"].append({"px0": px0, "ts_sig": int(ts), "ts_fill": ts_fill,
                            "dir": int(dr), "rung": rung})
        if th["dir0"] is None:
            th["dir0"] = int(dr)
        th["state"] = "open"
        th["exit_ts"] = int(ts) + HOLD_MS
        heapq.heappush(hp, (th["exit_ts"], key[0], key[1]))
        gross_state["book"] += UNIT_USD
        gross_state["coin"][key[1]] = gross_state["coin"].get(key[1], 0.0) + UNIT_USD
        return True

    n = sig["ts"].size
    for i in range(n):
        ts = int(sig["ts"][i])
        flush_until(ts)
        key = (str(sig["wallet"][i]), str(sig["coin"][i]))
        dr, is_add = int(sig["dir"][i]), bool(sig["is_add"][i])
        day = ts // DAY_MS
        th = theses.get(key)
        if th is None:
            if is_add:
                funnel["n_add_ignored_idle"] += 1
            else:
                theses[key] = {"state": "watch", "day": day, "count": 1, "units": [],
                               "dir0": None, "exit_ts": None}
                funnel["n_watch_started"] += 1
        elif th["state"] == "watch":
            if day == th["day"]:
                th["count"] += 1
                if th["count"] <= 4:
                    rung = len(th["units"]) + 1
                    if fire_unit(key, ts, dr, rung):
                        funnel["n_units_filled_rung"][str(rung)] = \
                            funnel["n_units_filled_rung"].get(str(rung), 0) + 1
                else:
                    funnel["n_after_4th"] += 1
            else:
                funnel["n_watch_expired"] += 1
                del theses[key]
                if is_add:
                    funnel["n_add_ignored_idle"] += 1
                else:
                    theses[key] = {"state": "watch", "day": day, "count": 1, "units": [],
                                   "dir0": None, "exit_ts": None}
                    funnel["n_watch_started"] += 1
        else:                                          # open
            th["count"] += 1
            if th["count"] <= 4 and len(th["units"]) < MAX_UNITS:
                rung = len(th["units"]) + 1
                if fire_unit(key, ts, dr, rung):
                    funnel["n_units_filled_rung"][str(rung)] = \
                        funnel["n_units_filled_rung"].get(str(rung), 0) + 1
            else:
                funnel["n_after_4th"] += 1
    # close everything left
    for key in sorted(k for k, t in theses.items() if t["state"] == "open"):
        close_thesis(key)
    theses.clear()


# ------------------------------------------------------------------- metrics
def daily_frames(units):
    day = np.clip((np.array([u["ts_fill"] for u in units], np.int64) - SPAN_T0_MS) // DAY_MS,
                  0, N_DAYS - 1)
    net = np.array([u["net"] for u in units])
    gross = np.array([u["gross"] for u in units])
    dnet, dgross, dsize = np.zeros(N_DAYS), np.zeros(N_DAYS), np.zeros(N_DAYS)
    np.add.at(dnet, day, net)
    np.add.at(dgross, day, gross)
    np.add.at(dsize, day, np.full(net.size, UNIT_USD))
    return dnet, dgross, dsize


def exposure_sweep(units):
    ev = []
    for u in units:
        ev.append((u["ts_fill"], UNIT_USD))
        ev.append((u["exit_ts"], -UNIT_USD))
    ev.sort()
    span0, span1 = SPAN_T0_MS, SPAN_T0_MS + N_DAYS * DAY_MS
    cur, mx, area, last = 0.0, 0.0, 0.0, span0
    for ts, d in ev:
        ts = min(max(ts, span0), span1)
        area += cur * (ts - last)
        last = ts
        cur += d
        mx = max(mx, cur)
    area += cur * (span1 - last)
    return area / (span1 - span0), mx


def block_boot_bp(dnet, dsize, rng):
    idx = rng.integers(0, N_DAYS, size=(N_BOOT, N_DAYS))
    tn, tsz = dnet[idx].sum(axis=1), dsize[idx].sum(axis=1)
    ok = tsz > 0
    bp = np.full(N_BOOT, np.nan)
    bp[ok] = tn[ok] / tsz[ok] * 1e4
    return ([round(float(np.nanpercentile(bp, q)), 2) for q in (2.5, 97.5)],
            round(float(np.nanmean(bp > 0)), 4))


# ---------------------------------------------------------------------- main
def prep():
    PYR.mkdir(parents=True, exist_ok=True)
    con = lake.connect()
    cohorts = {"config": {"k": K, "taker_min": TAKER_MIN, "cand_buffer": CAND_BUFFER,
                          "prereg": "PYRAMID_ALT_PREREG.md", "stamp": STAMP,
                          "code_commit": _git_commit()}, "folds": {}}
    for f in FOLDS:
        print(f"[prep] fold {f} cohort ...", flush=True)
        cohorts["folds"][str(f)] = _cohort(con, f)
        liq = _liquid_alts(con, f)
        cohorts["folds"][str(f)]["n_liquid_alts"] = len(liq)
        _opens(con, f, cohorts["folds"][str(f)]["wallets"])
        print(f"  fold {f}: {len(liq)} liquid alts, "
              f"{cohorts['folds'][str(f)]['n_screened_out_of_top100_rank']} of naive top-100 "
              "replaced by taker screen", flush=True)
    COHORTS_JSON.write_text(json.dumps(cohorts, indent=1))
    WALLETS_JSON.write_text(json.dumps(
        {str(f): cohorts["folds"][str(f)]["wallets"] for f in FOLDS}, indent=1))
    print(f"-> {COHORTS_JSON}\n-> {WALLETS_JSON} (ship to droplet for the adds pull)")


def run():
    cohorts = json.loads(COHORTS_JSON.read_text())
    con = lake.connect()
    funnel = {"n_signals": 0, "n_open_signals": 0, "n_add_signals": 0, "n_add_dedup_openfill": 0,
              "n_watch_started": 0, "n_watch_expired": 0, "n_add_ignored_idle": 0,
              "n_after_4th": 0, "n_miss_entry_px": 0, "n_cap_skip_book": 0, "n_cap_skip_coin": 0,
              "n_units_filled_rung": {}, "exit_flag_counts": {}, "n_units_no_exit_px": 0}
    units: list[dict] = []
    per_fold = {}
    for f in FOLDS:
        info = cohorts["folds"][str(f)]
        liq = _liquid_alts(con, f)
        sig, n_dedup = _fold_signals(con, f, info["wallets"], liq)
        funnel["n_add_dedup_openfill"] += n_dedup
        funnel["n_signals"] += int(sig["ts"].size)
        funnel["n_open_signals"] += int((~sig["is_add"]).sum())
        funnel["n_add_signals"] += int(sig["is_add"].sum())
        ctx = _ctx_by_coin(f, set(sig["coin"].tolist()))
        n0 = len(units)
        simulate_fold(f, sig, ctx, funnel, units)
        fu = units[n0:]
        gross = sum(u["gross"] for u in fu)
        net = sum(u["net"] for u in fu)
        per_fold[str(f)] = {
            "n_signals": int(sig["ts"].size), "n_liquid_alts": len(liq),
            "n_units": len(fu), "n_theses": len({(u["wallet"], u["coin"], u["exit_ts"]) for u in fu}),
            "gross_usd": round(gross, 2), "net_usd": round(net, 2),
            "net_bp_per_unit": round(net / (len(fu) * UNIT_USD) * 1e4, 2) if fu else None,
        }
        print(f"fold {f}: signals={sig['ts'].size:,} units={len(fu):,} "
              f"net ${net:,.0f} ({per_fold[str(f)]['net_bp_per_unit']}bp/u)", flush=True)

    if not units:
        raise RuntimeError("no units filled — plumbing broken")
    dnet, dgross, dsize = daily_frames(units)
    tot_net, tot_gross, tot_size = float(dnet.sum()), float(dgross.sum()), float(dsize.sum())
    mu, sd = float(dnet.mean()), float(dnet.std(ddof=1))
    dd = np.minimum.accumulate(np.cumsum(dnet) - np.maximum.accumulate(np.cumsum(dnet)))
    downside = float(np.sqrt(np.mean(np.minimum(dnet, 0.0) ** 2)))
    avg_exp, max_exp = exposure_sweep(units)
    rng = np.random.default_rng(SEED)
    ci_bp, p_gt0 = block_boot_bp(dnet, dsize, rng)
    hold_h = np.array([(u["exit_ts"] - u["ts_fill"]) / 3.6e6 for u in units])
    theses = {}
    for u in units:
        theses.setdefault((u["fold"], u["wallet"], u["coin"], u["exit_ts"]), []).append(u)
    th_sizes = np.array([len(v) for v in theses.values()])

    stats = {
        "n_units": len(units), "n_theses": int(th_sizes.size),
        "units_per_thesis_hist": {str(k): int((th_sizes == k).sum()) for k in (1, 2, 3)},
        "n_flip_units": int(sum(u["flip"] for u in units)),
        "total_gross_usd": round(tot_gross, 2), "total_net_usd": round(tot_net, 2),
        "total_traded_usd": round(tot_size, 2),
        "gross_bp_per_unit": round(tot_gross / tot_size * 1e4, 2),
        "net_bp_per_unit": round(tot_net / tot_size * 1e4, 2),
        "net_bp_per_unit_boot_ci": ci_bp, "p_net_bp_gt0": p_gt0,
        "ann_sharpe_daily": round(mu / sd * np.sqrt(365), 2) if sd > 0 else None,
        "ann_sortino_daily": round(mu / downside * np.sqrt(365), 2) if downside > 0 else None,
        "max_drawdown_usd": round(float(dd.min()), 2),
        "avg_gross_exposure_usd": round(avg_exp, 2), "max_gross_exposure_usd": round(max_exp, 2),
        "avg_hold_h_per_unit": round(float(hold_h.mean()), 2),
        "units_per_day": round(len(units) / N_DAYS, 2),
        "active_days": int((dsize > 0).sum()),
    }

    report = {
        "label": "PYRAMID-ALT frozen-ladder dollar mechanics (descriptive)",
        "stamp": STAMP,
        "config": {
            "selector": f"t_stat top-{K}, frozen-133 excluded, taker_share<{TAKER_MIN} excluded "
                        "(formation wallet_coin_day)",
            "universe": f"alt perps, trailing 3-mo formation ADV >= ${ADV_MIN:,.0f}, "
                        f"signals >= ${NOTL_MIN:,.0f} (block-collapsed)",
            "ladder": "1st flat-open=WATCH (UTC-day bound); 2nd sig=ENTER 1u; 3rd/4th=ADD 1u; "
                      "max 3u/(wallet,coin); exit ALL at last-filled-add + 8h",
            "execution": "entry = next asset_ctx mid <=90s; exit = backward-ASOF mid <=90s "
                         "(fwd fallback <=10min flagged)",
            "unit_usd": UNIT_USD, "coin_cap_usd": COIN_CAP, "book_cap_usd": BOOK_CAP,
            "cost_rt_bp": COST_RT_BP,
            "n_boot": N_BOOT, "seed": SEED, "boot_block": "calendar day (242)",
            "daily_attribution": "unit net/gross attributed to entry-fill UTC day",
            "deviations_from_prereg": [
                "trader-full-exit hard stop NOT simulated (forward paper trader implements it)",
                "maker shadow book NOT simulated",
                "entry basis = per-minute asset_ctx mid, not tape print (lag_haircut: ~1bp)",
                "adds collapsed per (wallet,coin,ts,dir) block event; add fills sharing a "
                "flat-open's exact ts deduped into the open signal",
            ],
            "code_commit": _git_commit(),
        },
        "funnel": funnel,
        "per_fold": per_fold,
        "stats": stats,
    }
    OUT_JSON.write_text(json.dumps(report, indent=1))
    print(json.dumps(stats, indent=1))
    append_md(report)
    print(f"-> {OUT_JSON}")
    return report


def append_md(report):
    s, f = report["stats"], report["funnel"]
    pf_rows = "\n".join(
        f"| {k} | {v['n_signals']:,} | {v['n_units']:,} | {v['n_theses']:,} | "
        f"{v['gross_usd']:+,.0f} | {v['net_usd']:+,.0f} | {v['net_bp_per_unit']} |"
        for k, v in report["per_fold"].items())
    md = f"""

# PYRAMID-ALT — DESCRIPTIVE MECHANICS VERIFICATION (frozen ladder, burned folds)

**STAMP: {STAMP}**

Spec: PYRAMID_ALT_PREREG.md lead arm — t_v1 top-100 (frozen-133 + taker<0.1 excluded), liquid
alts (trailing 3-mo formation ADV >= $10M), signals >= $250; ladder WATCH/ENTER/ADD/ADD
($2.5k units, max 3), exit all at last-filled-add + 8h; 21.5bp RT/unit. Deviations (recorded):
no trader-exit hard stop, no maker shadow, entry at next asset_ctx mid (not tape print).

| metric | value |
|---|---|
| units (theses) | {s['n_units']:,} ({s['n_theses']:,}; per-thesis 1/2/3 = {s['units_per_thesis_hist']['1']}/{s['units_per_thesis_hist']['2']}/{s['units_per_thesis_hist']['3']}) |
| gross / net PnL $ | {s['total_gross_usd']:+,.0f} / {s['total_net_usd']:+,.0f} |
| gross / net bp per unit | {s['gross_bp_per_unit']:+.1f} / {s['net_bp_per_unit']:+.1f} |
| net bp/unit day-block boot CI (2000) | [{s['net_bp_per_unit_boot_ci'][0]:+.1f}, {s['net_bp_per_unit_boot_ci'][1]:+.1f}], P(>0)={s['p_net_bp_gt0']:.3f} |
| ann Sharpe / Sortino (daily, 242d) | {s['ann_sharpe_daily']} / {s['ann_sortino_daily']} |
| max drawdown $ | {s['max_drawdown_usd']:,.0f} |
| avg / max gross exposure $ | {s['avg_gross_exposure_usd']:,.0f} / {s['max_gross_exposure_usd']:,.0f} |
| units/day; avg hold | {s['units_per_day']} ; {s['avg_hold_h_per_unit']}h |

Funnel: {f['n_signals']:,} eligible signals ({f['n_open_signals']:,} opens + {f['n_add_signals']:,} adds;
{f['n_add_dedup_openfill']:,} add-fills deduped into their flat-open) -> {f['n_watch_started']:,} watches
({f['n_watch_expired']:,} expired) -> units by rung {f['n_units_filled_rung']}; after-4th ignored
{f['n_after_4th']:,}; entry-px misses {f['n_miss_entry_px']:,}; cap skips book/coin
{f['n_cap_skip_book']}/{f['n_cap_skip_coin']}; flip units {s['n_flip_units']}; exit flags {f['exit_flag_counts']}
(0=backward<=90s, 1=fwd<=10min, 2=stale-backward, 3=none).

| fold | signals | units | theses | gross $ | net $ | net bp/u |
|---|---|---|---|---|---|---|
{pf_rows}

Artifact: `data/derived/copy_cohort/pyramid_mechanics_report.json`.
"""
    with OUT_MD.open("a") as fh:
        fh.write(md)
    print(f"-> appended to {OUT_MD}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    if mode == "prep":
        prep()
    elif mode == "run":
        run()
    else:
        raise SystemExit(f"unknown mode {mode}")
