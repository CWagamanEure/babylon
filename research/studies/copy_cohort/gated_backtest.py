"""CONSENSUS-GATED BACKTEST — descriptive book mechanics of the two pre-registered gate
variants on the frozen books (burned folds 202511-202606).

⛔ STAMP: the consensus gate was adopted AFTER viewing the consensus decomposition
(consensus_report.json / WALLET_ATTRIBUTION.md grid). Every number here is therefore
EX-POST-CONDITIONED on burned folds and NOT quotable as forward evidence. This run exists
solely to see the BOOK MECHANICS (Sharpe/DD/exposure shape) of the two gate variants that
were named in the gate spec — no sweeps, no other windows/levels/thresholds were run.

Gates (both use the 6h trailing window, [t-6h, t) strictly before entry, same coin+dir,
distinct OTHER cohort wallets — identical tagging code to consensus_conditioning):
  CROWD gate       : keep entry iff >= 1 other cohort wallet agreed (skip solo; pair+crowd kept)
  SMART-MONEY gate : keep entry iff >= 1 TOP-HALF-formation-t cohort wallet agreed

Books (S1 sizing):
  A pyramid-alt : frozen ladder re-sim (reconciled) + v1.1 fills/day<1000 bot screen;
                  $2.5k/unit, ladder's own caps (3u/wallet-coin, $50k/coin, $250k book)
                  already applied INSIDE the sim; the gate is a pure unit filter on the
                  simulated stream (does not re-open cap headroom). Cost 21.5bp RT in net.
  B majors K30  : @8h, $2.5k equal-unit per entry — SAME convention as the prior
                  wallet_attribution backtest ("$ = net_bp * 1e-4 * $2,500"); book rules
                  applied here: max 1 concurrent trade per (wallet,coin) (entry skipped while
                  a prior same-wallet-coin trade is open), $50k/coin gross cap. Cost 5.5bp RT.

    python -m research.studies.copy_cohort.gated_backtest
"""
from __future__ import annotations

import heapq
import json
from datetime import datetime, timezone

import numpy as np

from research.data.markout import REPO_ROOT
from . import consensus_conditioning as cc
from . import pyramid_book as pb

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
OUT_JSON = DERIVED / "gated_backtest_report.json"
OUT_MD = REPO_ROOT / "research" / "studies" / "copy_cohort" / "BACKTEST.md"

UNIT_USD = 2_500.0
COIN_CAP = 50_000.0
HOLD_MS = 28_800_000                      # majors @8h
DAY_MS = 86_400_000
SPAN_T0 = int(datetime(2025, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
N_DAYS = 242
N_BOOT = 2000
SEED = 20260717

STAMP = ("DESCRIPTIVE BOOK MECHANICS — burned folds 202511-202606; consensus gate adopted "
         "AFTER viewing the consensus decomposition => all numbers EX-POST-CONDITIONED, NOT "
         "quotable as forward evidence; only the two pre-named gate variants run (no sweeps).")


# ------------------------------------------------------------------ loaders
def load_a_units():
    """Re-sim pyramid ladder (reconciled vs wallet_attribution) + v1.1 bot screen.

    Returns (kept unit dicts, signals_by_fold, tophalf_by_fold, recon, n_bot_units_dropped).
    """
    cohorts = json.loads(pb.COHORTS_JSON.read_text())
    funnel = {"n_watch_started": 0, "n_watch_expired": 0, "n_add_ignored_idle": 0,
              "n_after_4th": 0, "n_miss_entry_px": 0, "n_cap_skip_book": 0,
              "n_cap_skip_coin": 0, "n_units_filled_rung": {}, "exit_flag_counts": {},
              "n_units_no_exit_px": 0}
    units: list[dict] = []
    for f in pb.FOLDS:
        info = cohorts["folds"][str(f)]
        liq = pb._liquid_alts(None, f)                       # advm caches exist
        sig, _ = pb._fold_signals(None, f, info["wallets"], liq)
        ctx = pb._ctx_by_coin(f, set(sig["coin"].tolist()))
        n0 = len(units)
        pb.simulate_fold(f, sig, ctx, funnel, units)
        print(f"  A fold {f}: {len(units) - n0:,} units", flush=True)

    attr = json.loads(cc.ATTR.read_text())["books"]["P"]["concentration"]
    tot = round(sum(u["net"] for u in units), 2)
    recon = {"n_units_resim": len(units), "n_units_attr": attr["n_trades"],
             "net_usd_resim": tot, "net_usd_attr": attr["total_net_usd"]}
    if len(units) != attr["n_trades"] or abs(tot - attr["total_net_usd"]) > 1.0:
        raise RuntimeError(f"reconciliation FAILED: {recon}")
    print(f"  A reconciliation OK: {recon}", flush=True)

    screened: dict[int, list[str]] = {}
    fd_all: dict[int, dict[str, float]] = {}
    for f in pb.FOLDS:
        cw = cohorts["folds"][str(f)]["wallets"]             # formation-t descending order
        fd = cc._fillsday(None, f, cw)                       # cached
        fd_all[f] = fd
        screened[f] = [w for w in cw if fd.get(w, 0.0) < cc.FILLS_DAY_MAX]
    keep_units = [u for u in units
                  if fd_all[u["fold"]].get(u["wallet"], 0.0) < cc.FILLS_DAY_MAX]

    # counting signal pools + top-half sets (identical to consensus_conditioning.load_book_a)
    signals_by_fold, tophalf_by_fold = {}, {}
    from math import ceil
    for f in pb.FOLDS:
        sset = set(screened[f])
        op = pb._opens(None, f, cohorts["folds"][str(f)]["wallets"])
        ad = pb._adds(f)
        parts = []
        for d in (op, ad):
            w = d["wallet"].astype(str)
            m = np.array([x in sset for x in w])
            parts.append({"ts": np.asarray(d["ts"], np.int64)[m], "wallet": w[m],
                          "coin": d["coin"].astype(str)[m],
                          "dir": np.asarray(d["dir_sign"], np.int64)[m]})
        signals_by_fold[f] = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
        tophalf_by_fold[f] = set(screened[f][:ceil(len(screened[f]) / 2)])
    return keep_units, signals_by_fold, tophalf_by_fold, recon, len(units) - len(keep_units)


def consensus_counts(ent, sigs, tops):
    """Per-entry 6h other-wallet count + 6h top-half count (cc.count_consensus, per fold)."""
    n = ent["ts"].size
    n6 = np.zeros(n, np.int64)
    ntop = np.zeros(n, np.int64)
    for f in cc.FOLDS:
        m = ent["fold"] == f
        if not m.any():
            continue
        sub = {k: ent[k][m] for k in ("ts", "wallet", "coin", "dir")}
        o, ot = cc.count_consensus(sub, sigs[f], tops[f])
        n6[m] = o["6h"]
        ntop[m] = ot
    return n6, ntop


# ------------------------------------------------------------------ book builders
def build_b_book(ent, mask):
    """Majors dollar book: ts-ordered, max 1 concurrent per (wallet,coin), $50k/coin cap."""
    idx = np.flatnonzero(mask)
    order = idx[np.lexsort((ent["coin"][idx], ent["wallet"][idx], ent["ts"][idx]))]
    open_until: dict[tuple[str, str], int] = {}
    coin_heap: dict[str, list[int]] = {}
    keep, n_conc, n_cap = [], 0, 0
    for i in order:
        ts = int(ent["ts"][i])
        w, c = str(ent["wallet"][i]), str(ent["coin"][i])
        if open_until.get((w, c), -1) > ts:                  # exit==ts frees the slot
            n_conc += 1
            continue
        h = coin_heap.setdefault(c, [])
        while h and h[0] <= ts:
            heapq.heappop(h)
        if (len(h) + 1) * UNIT_USD > COIN_CAP:
            n_cap += 1
            continue
        ex = ts + HOLD_MS
        open_until[(w, c)] = ex
        heapq.heappush(h, ex)
        keep.append(i)
    k = np.array(keep, np.int64)
    return {"ts_fill": ent["ts"][k], "exit_ts": ent["ts"][k] + HOLD_MS,
            "net": ent["net_bp"][k] * 1e-4 * UNIT_USD,
            "gross": ent["gross_bp"][k] * 1e-4 * UNIT_USD,
            "n_candidates": int(idx.size), "n_skip_concurrent": n_conc, "n_skip_cap": n_cap}


def a_book(units, mask):
    k = np.flatnonzero(mask)
    return {"ts_fill": np.array([units[i]["ts_fill"] for i in k], np.int64),
            "exit_ts": np.array([units[i]["exit_ts"] for i in k], np.int64),
            "net": np.array([units[i]["net"] for i in k]),
            "gross": np.array([units[i]["gross"] for i in k]),
            "n_candidates": int(k.size), "n_skip_concurrent": 0, "n_skip_cap": 0}


def merge_books(a, b):
    out = {k: np.concatenate([a[k], b[k]]) for k in ("ts_fill", "exit_ts", "net", "gross")}
    out["n_candidates"] = a["n_candidates"] + b["n_candidates"]
    out["n_skip_concurrent"] = a["n_skip_concurrent"] + b["n_skip_concurrent"]
    out["n_skip_cap"] = a["n_skip_cap"] + b["n_skip_cap"]
    return out


# ------------------------------------------------------------------ stats
def exposure_sweep(ts_fill, exit_ts):
    ev = sorted([(int(t), UNIT_USD) for t in ts_fill] +
                [(int(t), -UNIT_USD) for t in exit_ts])
    span0, span1 = SPAN_T0, SPAN_T0 + N_DAYS * DAY_MS
    cur, mx, area, last = 0.0, 0.0, 0.0, span0
    for ts, d in ev:
        ts = min(max(ts, span0), span1)
        area += cur * (ts - last)
        last = ts
        cur += d
        mx = max(mx, cur)
    area += cur * (span1 - last)
    return area / (span1 - span0), mx


def row_stats(book, base_n, seed):
    """Full row stats on the 242-day daily-net frame (zero days included).

    Conventions (match pyramid_book): unit net/gross attributed to entry-fill UTC day;
    Sharpe/Sortino annualized sqrt(365); maxDD on the cumulative daily-net equity curve,
    maxDD% = maxDD$ / max gross exposure; hit rate = P(day net > 0 | day net != 0).
    """
    n = int(book["ts_fill"].size)
    day = np.clip((book["ts_fill"] - SPAN_T0) // DAY_MS, 0, N_DAYS - 1)
    dnet, dgross, dsize = np.zeros(N_DAYS), np.zeros(N_DAYS), np.zeros(N_DAYS)
    np.add.at(dnet, day, book["net"])
    np.add.at(dgross, day, book["gross"])
    np.add.at(dsize, day, np.full(n, UNIT_USD))
    tot_net, tot_gross, tot_size = float(dnet.sum()), float(dgross.sum()), float(dsize.sum())
    mu, sd = float(dnet.mean()), float(dnet.std(ddof=1))
    downside = float(np.sqrt(np.mean(np.minimum(dnet, 0.0) ** 2)))
    eq = np.cumsum(dnet)
    dd = eq - np.maximum.accumulate(eq)
    avg_exp, max_exp = exposure_sweep(book["ts_fill"], book["exit_ts"])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, N_DAYS, size=(N_BOOT, N_DAYS))
    tn, tsz = dnet[idx].sum(axis=1), dsize[idx].sum(axis=1)
    ok = tsz > 0
    bp = np.full(N_BOOT, np.nan)
    bp[ok] = tn[ok] / tsz[ok] * 1e4
    nz = dnet != 0
    return {
        "n_trades": n,
        "pct_of_ungated": round(n / base_n * 100, 1) if base_n else None,
        "n_gate_candidates": book["n_candidates"],
        "n_skip_concurrent": book["n_skip_concurrent"], "n_skip_cap": book["n_skip_cap"],
        "net_usd": round(tot_net, 2), "gross_usd": round(tot_gross, 2),
        "net_bp_per_trade": round(tot_net / tot_size * 1e4, 2) if tot_size else None,
        "net_bp_boot_ci95": [round(float(np.nanpercentile(bp, q)), 2) for q in (2.5, 97.5)],
        "p_net_bp_gt0": round(float(np.nanmean(bp > 0)), 4),
        "ann_sharpe": round(mu / sd * np.sqrt(365), 2) if sd > 0 else None,
        "ann_sortino": round(mu / downside * np.sqrt(365), 2) if downside > 0 else None,
        "max_dd_usd": round(float(dd.min()), 2),
        "max_dd_pct_of_max_exposure": round(float(-dd.min()) / max_exp * 100, 2) if max_exp else None,
        "daily_hit_rate": round(float((dnet[nz] > 0).mean()), 3) if nz.any() else None,
        "n_active_days": int(nz.sum()),
        "avg_gross_exposure_usd": round(avg_exp, 2),
        "max_gross_exposure_usd": round(max_exp, 2),
    }, dnet


def monthly_net(dnet):
    out = {}
    for d in range(N_DAYS):
        dt = datetime.fromtimestamp((SPAN_T0 + d * DAY_MS) / 1000, tz=timezone.utc)
        key = f"{dt.year}{dt.month:02d}"
        out[key] = round(out.get(key, 0.0) + float(dnet[d]), 2)
    return out


# ------------------------------------------------------------------ main
def run():
    print("[A] pyramid-alt re-sim + v1.1 screen ...", flush=True)
    a_units, sig_a, top_a, recon, n_bot_units = load_a_units()
    ent_a = {"ts": np.array([u["ts_sig"] for u in a_units], np.int64),
             "wallet": np.array([u["wallet"] for u in a_units]),
             "coin": np.array([u["coin"] for u in a_units]),
             "dir": np.array([u["dir"] for u in a_units], np.int64),
             "fold": np.array([u["fold"] for u in a_units], np.int64)}
    print(f"  A: {len(a_units):,} screened units ({n_bot_units:,} bot units dropped)", flush=True)

    print("[B] majors-native K30 entries + dir join ...", flush=True)
    ent_b, sig_b, top_b, n_amb = cc.load_book_b(None)        # opens caches exist
    print(f"  B: {ent_b['ts'].size:,} entries ({n_amb} ambiguous-dir dropped)", flush=True)

    print("[gate] consensus counts (6h; identical tagging to consensus_conditioning) ...",
          flush=True)
    a_n6, a_ntop = consensus_counts(ent_a, sig_a, top_a)
    b_n6, b_ntop = consensus_counts(ent_b, sig_b, top_b)

    all_a = np.ones(len(a_units), bool)
    books = {
        "A_ungated": a_book(a_units, all_a),
        "A_crowd": a_book(a_units, a_n6 >= 1),
        "A_smart": a_book(a_units, a_ntop >= 1),
        "B_ungated": build_b_book(ent_b, np.ones(ent_b["ts"].size, bool)),
        "B_crowd": build_b_book(ent_b, b_n6 >= 1),
        "B_smart": build_b_book(ent_b, b_ntop >= 1),
    }
    books["COMBINED_smart"] = merge_books(books["A_smart"], books["B_smart"])

    rows, dnets = {}, {}
    base = {"A": None, "B": None, "C": None}
    for i, (name, bk) in enumerate(books.items()):
        b = base["A" if name.startswith("A") else "B" if name.startswith("B") else "C"]
        st, dnet = row_stats(bk, b, SEED + i)
        if name == "A_ungated":
            base["A"] = st["n_trades"]
            st["pct_of_ungated"] = 100.0
        if name == "B_ungated":
            base["B"] = st["n_trades"]
            st["pct_of_ungated"] = 100.0
        rows[name] = st
        dnets[name] = dnet
        print(f"  {name:<15} n={st['n_trades']:>5,} net ${st['net_usd']:>+10,.0f} "
              f"({st['net_bp_per_trade']:+.1f}bp) SR {st['ann_sharpe']} "
              f"DD ${st['max_dd_usd']:,.0f}", flush=True)
    rows["COMBINED_smart"]["pct_of_ungated"] = None          # mixed baseline; per-book % above
    mo = monthly_net(dnets["COMBINED_smart"])

    rep = {"label": "consensus-gated backtest of the frozen books (descriptive book mechanics)",
           "stamp": STAMP,
           "config": {
               "span": "2025-11-01 .. 2026-07-01 UTC, 242 daily buckets, zero days included",
               "gates": {"crowd": ">=1 other cohort wallet, same coin+dir, [t-6h,t)",
                         "smart": ">=1 top-half-formation-t cohort wallet, same coin+dir, [t-6h,t)"},
               "book_a": "pyramid ladder re-sim (reconciled) + v1.1 fills/day<1000 screen; "
                         "$2.5k/unit; ladder caps applied inside the sim; gate = pure unit "
                         "filter (no cap headroom re-opened); cost 21.5bp RT in net",
               "book_b": "majors K30 @8h, $2.5k equal-unit per entry (wallet_attribution "
                         "convention); max 1 concurrent per (wallet,coin); $50k/coin cap; "
                         "net = mk8 - 5.5bp",
               "daily_attribution": "entry-fill UTC day (pyramid_book convention)",
               "max_dd_pct_basis": "maxDD$ / max gross exposure of the row",
               "daily_hit_rate": "P(day net > 0 | day net != 0)",
               "n_boot": N_BOOT, "seed": SEED, "boot_block": "calendar day (242)",
               "reconciliation": recon, "a_bot_units_dropped": n_bot_units,
               "b_ambiguous_dir_dropped": n_amb},
           "rows": rows,
           "monthly_net_combined_smart": mo}
    OUT_JSON.write_text(json.dumps(rep, indent=1))
    print(f"-> {OUT_JSON}")
    append_md(rep)
    return rep


ROW_TITLES = {
    "A_ungated": "1. Pyramid-alt — ungated",
    "A_crowd": "2. Pyramid-alt — CROWD gate",
    "A_smart": "3. Pyramid-alt — SMART gate",
    "B_ungated": "4. Majors K30@8h — ungated",
    "B_crowd": "5. Majors K30@8h — CROWD gate",
    "B_smart": "6. Majors K30@8h — SMART gate",
    "COMBINED_smart": "7. COMBINED — SMART gate",
}


def append_md(rep):
    lines = ["\n\n# CONSENSUS-GATED BACKTEST — descriptive book mechanics (burned folds)\n",
             f"**STAMP: {rep['stamp']}**\n",
             "Gate variants were named after viewing the consensus decomposition "
             "(WALLET_ATTRIBUTION.md grid) — these are the SAME entries re-weighted by an "
             "ex-post-chosen condition; the only legitimate use is sizing the forward paper "
             "expectation. S1 sizing: $2.5k/unit (alt ladder caps inside sim) and $2.5k/entry "
             "majors (wallet_attribution equal-unit convention), max 1 concurrent per "
             "(wallet,coin) + $50k/coin cap on majors; costs 21.5bp alt / 5.5bp majors RT.\n",
             "| row | n (%ungated) | net $ | gross $ | bp/tr | boot CI95 | SR | Sortino | "
             "maxDD $ (%maxExp) | hit | avg/max exp $ |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, title in ROW_TITLES.items():
        r = rep["rows"][k]
        pct = f" ({r['pct_of_ungated']}%)" if r["pct_of_ungated"] is not None else ""
        ci = r["net_bp_boot_ci95"]
        lines.append(
            f"| {title} | {r['n_trades']:,}{pct} | {r['net_usd']:+,.0f} | "
            f"{r['gross_usd']:+,.0f} | {r['net_bp_per_trade']:+.1f} | "
            f"[{ci[0]:+.1f}, {ci[1]:+.1f}] P>0={r['p_net_bp_gt0']:.2f} | {r['ann_sharpe']} | "
            f"{r['ann_sortino']} | {r['max_dd_usd']:,.0f} ({r['max_dd_pct_of_max_exposure']}%) | "
            f"{r['daily_hit_rate']} | {r['avg_gross_exposure_usd']:,.0f} / "
            f"{r['max_gross_exposure_usd']:,.0f} |")
    lines.append("\nMonthly net PnL, row 7 (COMBINED smart): " + "; ".join(
        f"{k}: {v:+,.0f}" for k, v in rep["monthly_net_combined_smart"].items()))
    lines.append("\nMajors book funnel (candidates -> skips): " + "; ".join(
        f"{k}: {rep['rows'][k]['n_gate_candidates']:,} cand, "
        f"{rep['rows'][k]['n_skip_concurrent']:,} concurrent-skip, "
        f"{rep['rows'][k]['n_skip_cap']} cap-skip"
        for k in ("B_ungated", "B_crowd", "B_smart")))
    lines.append("\nArtifact: `data/derived/copy_cohort/gated_backtest_report.json`.\n")
    with OUT_MD.open("a") as fh:
        fh.write("\n".join(lines))
    print(f"-> appended to {OUT_MD}")


if __name__ == "__main__":
    run()
