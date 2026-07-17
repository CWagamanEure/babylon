"""DESCRIPTIVE BOOK MECHANICS — frozen paper-trader candidates, burned folds 202511-202606.

No selection/design changes; sizing variants pre-declared, reported side-by-side, none
crowned by argmax. Books (frozen specs):
  A: K100 liquid-alt @1h  — top-100 by t_stat from informedness pool (frozen-133 excluded),
     cached ksweep entries (flat taker opens, notl>=$250), alt coins with test-month ADV>=$10M,
     1h hold, RT cost 21.5bp (20 fee + 1.5 lag-slippage).
  B: K30 majors-native @8h — cached majors_native entries rk<30, 8h hold, RT 5.5bp (4 + 1.5).
Entry/exit px = asset_ctx mid ASOF <=90s both ends (already baked into cached mk / mk8, gross
dir-signed bp). Trade net bp = mk - RT.

Sizing variants (pre-declared):
  S1 fixed $5k/entry.
  S2 per-wallet-equal: $25k/day per selected wallet split equally across its that-day
     candidate entries in the book (post venue/notional/evaluability filters, pre skip rules).
  S3 vol-scaled: $5k * (20bp / coin trailing-30d daily vol bp) clipped [0.2x, 3x]; vol from
     asset_ctx daily last-tick mid closes, window = closes ending in [D-30, D-1], >=20 return
     obs else factor 1.0.
Position rules (all variants): max 1 concurrent position per (wallet, coin); max $50k gross
per coin at a time (skip entries beyond cap); PnL in $, no leverage assumptions.

ARCHETYPE GATE (Book A variant): formation coin_breadth>=10, taker_share in [0.2, 0.7],
>=100 active days. NOTE: the literal ">=100 distinct calendar days" is unsatisfiable in a
3-month (90-92 day) formation window (0 wallets pass, all folds); implemented as >=100
wallet-coin-day rows (sum over coins of per-coin active days), labeled as such.

PnL attribution: trade net PnL attributed to entry day (UTC). Span = 2025-11-01..2026-06-30
(242 calendar days), zero-PnL days included. Capital for DD% = peak gross exposure observed.

Outputs: data/derived/copy_cohort/backtest_report.json + research/studies/copy_cohort/BACKTEST.md

Run: .venv/bin/python -m research.studies.copy_cohort.backtest_book
"""
from __future__ import annotations

import datetime as dt
import heapq
import json

import duckdb
import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
KSWEEP = DERIVED / "ksweep"
MAJN = DERIVED / "majors_native"
GATEP = DERIVED / "backtest_gate_features.parquet"
OUT_JSON = DERIVED / "backtest_report.json"
OUT_MD = REPO_ROOT / "research" / "studies" / "copy_cohort" / "BACKTEST.md"

FOLDS = MONTHS[3:]                       # 202511..202606 (burned)
MAJORS = ("BTC", "ETH", "SOL", "HYPE")
ADV_MIN = 10_000_000.0
COST_A_BP = 21.5                         # 20 RT fee + 1.5 lag-slippage
COST_B_BP = 5.5                          # 4 RT fee + 1.5
HOLD_MS = {"A": 3_600_000, "B": 8 * 3_600_000}
COST_BP = {"A": COST_A_BP, "B": COST_B_BP}
COIN_CAP = 50_000.0
S1_SIZE = 5_000.0
S2_DAILY = 25_000.0
S3_BASE, S3_TARGET_BP, S3_CLIP = 5_000.0, 20.0, (0.2, 3.0)
VOL_WIN_D, VOL_MIN_OBS = 30, 20
DAY_MS = 86_400_000
SPAN_D0 = dt.date(2025, 11, 1)
SPAN_D1 = dt.date(2026, 6, 30)
N_DAYS = (SPAN_D1 - SPAN_D0).days + 1    # 242
EPOCH = dt.date(1970, 1, 1)
SPAN_T0_MS = (SPAN_D0 - EPOCH).days * DAY_MS
SPAN_T1_MS = ((SPAN_D1 - EPOCH).days + 1) * DAY_MS


# ---------------------------------------------------------------- candidates
def load_candidates() -> dict[str, dict[str, np.ndarray]]:
    """Book -> arrays (wallet, coin, ts, mk_bp, fold), evaluable + venue-filtered."""
    con = duckdb.connect()
    out = {}
    parts = {"A": [], "B": []}
    for f in FOLDS:
        e = (KSWEEP / f"entries_{f}.parquet").as_posix()
        a = (KSWEEP / f"adv_{f}.parquet").as_posix()
        mj = ",".join(f"'{m}'" for m in MAJORS)
        parts["A"].append(con.execute(f"""
            SELECT e.wallet, e.coin, e.ts, e.mk, {f} AS fold
            FROM '{e}' e JOIN '{a}' a USING (coin)
            WHERE e.mk IS NOT NULL AND a.adv >= {ADV_MIN} AND e.coin NOT IN ({mj})
            ORDER BY e.ts, e.wallet, e.coin""").fetchnumpy())
        parts["B"].append(con.execute(f"""
            SELECT wallet, coin, ts, mk8 AS mk, {f} AS fold
            FROM '{(MAJN / f'entries_{f}.parquet').as_posix()}'
            WHERE rk < 30 AND mk8 IS NOT NULL
            ORDER BY ts, wallet, coin""").fetchnumpy())
    for b in ("A", "B"):
        out[b] = {
            "wallet": np.concatenate([p["wallet"].astype(str) for p in parts[b]]),
            "coin": np.concatenate([p["coin"].astype(str) for p in parts[b]]),
            "ts": np.concatenate([np.asarray(p["ts"], np.int64) for p in parts[b]]),
            "mk": np.concatenate([np.asarray(p["mk"], float) for p in parts[b]]),
            "fold": np.concatenate([np.asarray(p["fold"], np.int64) for p in parts[b]]),
        }
        o = np.lexsort((out[b]["coin"], out[b]["wallet"], out[b]["ts"]))
        out[b] = {k: v[o] for k, v in out[b].items()}
    con.close()
    return out


# ---------------------------------------------------------------- S3 vol factors
def build_vol_factor(cands) -> dict[str, np.ndarray]:
    """Per-entry S3 factor: clip(20bp / trailing-30d daily close-to-close vol bp, 0.2, 3)."""
    coins = sorted(set(cands["A"]["coin"]) | set(cands["B"]["coin"]))
    cl = ",".join(f"'{c}'" for c in coins)
    months = [202509, 202510] + FOLDS
    globs = ",".join(f"'{(REPO_ROOT / 'data/raw/asset_ctx' / f'month={m}').as_posix()}/day=*/ctx.parquet'"
                     for m in months)
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'; SET threads=4")
    d = con.execute(f"""
        SELECT coin, day, arg_max(mid_px, ts) AS close
        FROM read_parquet([{globs}])
        WHERE coin IN ({cl}) AND mid_px IS NOT NULL
        GROUP BY coin, day ORDER BY coin, day""").fetchnumpy()
    con.close()
    coin_arr, day_arr, close_arr = d["coin"].astype(str), np.asarray(d["day"], np.int64), np.asarray(d["close"], float)
    day_ord = np.array([(dt.date(int(y // 10000), int(y % 10000 // 100), int(y % 100)) - EPOCH).days
                        for y in day_arr], np.int64)
    series = {}
    for c in coins:
        m = coin_arr == c
        series[c] = (day_ord[m], close_arr[m])          # already sorted

    factors = {}
    cache: dict[tuple[str, int], float] = {}
    for b in ("A", "B"):
        ts, coin = cands[b]["ts"], cands[b]["coin"]
        ent_day = ts // DAY_MS
        fac = np.ones(ts.size)
        for i in range(ts.size):
            key = (coin[i], int(ent_day[i]))
            f = cache.get(key)
            if f is None:
                dords, closes = series.get(coin[i], (np.empty(0, np.int64), np.empty(0)))
                lo = np.searchsorted(dords, ent_day[i] - VOL_WIN_D)
                hi = np.searchsorted(dords, ent_day[i])          # closes strictly before entry day
                f = 1.0
                if hi - lo >= VOL_MIN_OBS + 1:
                    w = closes[lo:hi]
                    r = w[1:] / w[:-1] - 1.0
                    if r.size >= VOL_MIN_OBS:
                        vol_bp = float(np.std(r, ddof=1)) * 1e4
                        if vol_bp > 0:
                            f = float(np.clip(S3_TARGET_BP / vol_bp, *S3_CLIP))
                cache[key] = f
            fac[i] = f
        factors[b] = fac
    return factors


# ---------------------------------------------------------------- sizing
def entry_sizes(c, book: str, sizing: str, vol_fac: np.ndarray) -> np.ndarray:
    n = c["ts"].size
    if sizing == "S1":
        return np.full(n, S1_SIZE)
    if sizing == "S3":
        return S3_BASE * vol_fac
    # S2: $25k/day per wallet split across its that-day candidate entries in this book
    day = (c["ts"] // DAY_MS).astype(np.int64)
    key = np.char.add(np.char.add(c["wallet"], "|"), day.astype(str))
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    return S2_DAILY / cnt[inv]


# ---------------------------------------------------------------- simulator
def simulate(c, sizes: np.ndarray, book: str, mask: np.ndarray | None = None):
    """Event-driven: max 1 open per (wallet,coin), $50k gross per coin. Returns accepted dict."""
    hold = HOLD_MS[book]
    idx = np.arange(c["ts"].size) if mask is None else np.flatnonzero(mask)
    open_wc: set[tuple[str, str]] = set()
    coin_gross: dict[str, float] = {}
    exits: list[tuple[int, str, str, float]] = []       # (exit_ts, wallet, coin, size)
    acc, skip_wc, skip_cap = [], 0, 0
    for i in idx:
        t = int(c["ts"][i])
        while exits and exits[0][0] <= t:
            _, w0, c0, s0 = heapq.heappop(exits)
            open_wc.discard((w0, c0))
            coin_gross[c0] = coin_gross.get(c0, 0.0) - s0
        w, coin, s = c["wallet"][i], c["coin"][i], float(sizes[i])
        if (w, coin) in open_wc:
            skip_wc += 1
            continue
        if coin_gross.get(coin, 0.0) + s > COIN_CAP + 1e-9:
            skip_cap += 1
            continue
        open_wc.add((w, coin))
        coin_gross[coin] = coin_gross.get(coin, 0.0) + s
        heapq.heappush(exits, (t + hold, str(w), str(coin), s))
        acc.append(i)
    acc = np.asarray(acc, np.int64)
    return {"idx": acc, "size": sizes[acc], "ts": c["ts"][acc], "mk": c["mk"][acc],
            "coin": c["coin"][acc], "wallet": c["wallet"][acc], "fold": c["fold"][acc],
            "hold_ms": hold, "cost_bp": COST_BP[book],
            "n_skip_wc": skip_wc, "n_skip_cap": skip_cap}


# ---------------------------------------------------------------- stats
def trade_frames(sim) -> dict[str, np.ndarray]:
    gross = sim["size"] * sim["mk"] / 1e4
    net = sim["size"] * (sim["mk"] - sim["cost_bp"]) / 1e4
    return {"ts": sim["ts"], "size": sim["size"], "gross": gross, "net": net,
            "exit_ts": sim["ts"] + sim["hold_ms"], "fold": sim["fold"]}


def book_stats(frames: list[dict[str, np.ndarray]]) -> dict:
    ts = np.concatenate([f["ts"] for f in frames])
    size = np.concatenate([f["size"] for f in frames])
    gross = np.concatenate([f["gross"] for f in frames])
    net = np.concatenate([f["net"] for f in frames])
    exit_ts = np.concatenate([f["exit_ts"] for f in frames])
    # daily net pnl over full span, entry-day attribution
    day_i = ((ts - SPAN_T0_MS) // DAY_MS).astype(np.int64)
    daily = np.zeros(N_DAYS)
    np.add.at(daily, np.clip(day_i, 0, N_DAYS - 1), net)
    mu, sd = daily.mean(), daily.std(ddof=1)
    dsd = float(np.sqrt(np.mean(np.minimum(daily, 0.0) ** 2)))
    eq = np.cumsum(daily)
    peak = np.maximum.accumulate(np.maximum(eq, 0.0))
    dd = peak - eq
    # time-weighted gross exposure (event-driven)
    ev_t = np.concatenate([ts, exit_ts])
    ev_d = np.concatenate([size, -size])
    o = np.argsort(ev_t, kind="stable")
    ev_t, ev_d = np.clip(ev_t[o], SPAN_T0_MS, SPAN_T1_MS), ev_d[o]
    expo = np.cumsum(ev_d)
    seg_t = np.diff(np.concatenate([[SPAN_T0_MS], ev_t, [SPAN_T1_MS]])).astype(float)
    expo_path = np.concatenate([[0.0], expo])
    avg_expo = float((expo_path * seg_t).sum() / (SPAN_T1_MS - SPAN_T0_MS))
    max_expo = float(expo_path.max()) if expo_path.size else 0.0
    capital = max_expo if max_expo > 0 else 1.0
    active = daily != 0
    return {
        "trades": int(ts.size),
        "total_net_pnl_usd": round(float(net.sum()), 2),
        "total_gross_pnl_usd": round(float(gross.sum()), 2),
        "ann_sharpe": round(float(mu / sd * np.sqrt(365)), 2) if sd > 0 else None,
        "ann_sortino": round(float(mu / dsd * np.sqrt(365)), 2) if dsd > 0 else None,
        "max_dd_usd": round(float(dd.max()), 2),
        "max_dd_pct_of_peak_expo": round(float(dd.max() / capital * 100), 2),
        "hit_rate_daily": round(float((daily[active] > 0).mean()), 3) if active.any() else None,
        "n_active_days": int(active.sum()), "n_days": N_DAYS,
        "avg_gross_expo_usd": round(avg_expo, 0),
        "max_gross_expo_usd": round(max_expo, 0),
        "avg_trade_net_bp": round(float(net.sum() / size.sum() * 1e4), 2) if size.sum() > 0 else None,
        "avg_trade_gross_bp": round(float(gross.sum() / size.sum() * 1e4), 2) if size.sum() > 0 else None,
        "_daily": daily,
    }


# ---------------------------------------------------------------- main
def run() -> None:
    cands = load_candidates()
    print(f"candidates: A={cands['A']['ts'].size:,}  B={cands['B']['ts'].size:,}", flush=True)
    vol_fac = build_vol_factor(cands)
    for b in ("A", "B"):
        f = vol_fac[b]
        print(f"S3 factors {b}: median={np.median(f):.3f} at-floor={np.mean(f <= S3_CLIP[0] + 1e-12):.1%} "
              f"fallback1.0={np.mean(f == 1.0):.1%}", flush=True)

    # archetype gate (coin-day reading; literal >=100 distinct days = 0 wallets, all folds)
    gc = duckdb.connect()
    gd = gc.execute(f"""SELECT fold, wallet FROM '{GATEP.as_posix()}'
                        WHERE f_coin_breadth >= 10 AND f_taker_share BETWEEN 0.2 AND 0.7
                          AND f_ncd >= 100""").fetchall()
    lit = gc.execute(f"""SELECT count(*) FROM '{GATEP.as_posix()}'
                         WHERE f_coin_breadth >= 10 AND f_taker_share BETWEEN 0.2 AND 0.7
                           AND f_nd >= 100""").fetchone()[0]
    gc.close()
    gate = {(int(f), w) for f, w in gd}
    a = cands["A"]
    gate_mask = np.array([(int(f), w) in gate for f, w in zip(a["fold"], a["wallet"])])
    print(f"archetype gate: {len(gate)} wallet-folds pass (coin-day reading); literal-days passes={lit}; "
          f"A entries gated {gate_mask.sum():,}/{gate_mask.size:,}", flush=True)

    sizings = ("S1", "S2", "S3")
    sims: dict[str, dict] = {}
    rows: dict[str, dict] = {}
    for s in sizings:
        for b in ("A", "B"):
            sz = entry_sizes(cands[b], b, s, vol_fac[b])
            sims[f"{b}/{s}"] = simulate(cands[b], sz, b)
            rows[f"Book {b} ({'K100 liquid-alt @1h' if b == 'A' else 'K30 majors @8h'}) / {s}"] = \
                book_stats([trade_frames(sims[f"{b}/{s}"])])
        rows[f"Combined (A+B) / {s}"] = book_stats(
            [trade_frames(sims[f"A/{s}"]), trade_frames(sims[f"B/{s}"])])
        # archetype-gated Book A: S2 sizes recomputed on the gated candidate set
        szg = entry_sizes({k: v[gate_mask] for k, v in cands["A"].items()}, "A", s,
                          vol_fac["A"][gate_mask]) if s == "S2" else \
            entry_sizes(cands["A"], "A", s, vol_fac["A"])[gate_mask]
        cg = {k: v[gate_mask] for k, v in cands["A"].items()}
        simg = simulate(cg, szg, "A")
        sims[f"Agate/{s}"] = simg
        rows[f"Book A ARCHETYPE-GATED / {s}"] = book_stats([trade_frames(simg)])

    # monthly pnl for combined S1
    monthly = {}
    for s_key, lbl in ((("A/S1", "B/S1"), "combined_S1"),):
        fr = [trade_frames(sims[k]) for k in s_key]
        fold_all = np.concatenate([f["fold"] for f in fr])
        net_all = np.concatenate([f["net"] for f in fr])
        gross_all = np.concatenate([f["gross"] for f in fr])
        monthly[lbl] = {str(f): {"net_usd": round(float(net_all[fold_all == f].sum()), 2),
                                 "gross_usd": round(float(gross_all[fold_all == f].sum()), 2),
                                 "trades": int((fold_all == f).sum())} for f in FOLDS}

    skips = {k: {"n_skip_wallet_coin_concurrent": v["n_skip_wc"], "n_skip_coin_cap": v["n_skip_cap"],
                 "n_accepted": int(v["idx"].size)} for k, v in sims.items()}

    # S2 composition diagnostic: gross mk by wallet-day candidate-entry count (pre skip rules)
    s2_comp = {}
    for b in ("A", "B"):
        c = cands[b]
        day = (c["ts"] // DAY_MS).astype(np.int64)
        key = np.char.add(np.char.add(c["wallet"], "|"), day.astype(str))
        _, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        n_day = cnt[inv]
        s2_comp[b] = {f"{lo}-{hi if hi < 10**8 else 'inf'}": {
            "n": int(m.sum()), "mean_gross_mk_bp": round(float(c["mk"][m].mean()), 1)}
            for lo, hi in ((1, 1), (2, 3), (4, 10), (11, 10**9))
            if (m := (n_day >= lo) & (n_day <= hi)).any()}

    report = {
        "label": "DESCRIPTIVE BOOK MECHANICS — frozen paper-trader candidates, burned folds 202511-202606",
        "stamp": {"folds": FOLDS, "span": [str(SPAN_D0), str(SPAN_D1)], "n_days": N_DAYS,
                  "note_span": "prompt said 244-day span; actual calendar span of the 8 fold "
                               "months is 242 days (2026 Feb = 28d)"},
        "frozen_specs": {
            "book_A": "top-100 by t_stat from informedness pool (frozen-133 excluded), cached "
                      "ksweep entries (flat taker opens, notl>=$250), alt coins test-month "
                      "ADV>=$10M, hold 1h, RT 21.5bp (20 fee + 1.5 lag-slip)",
            "book_B": "cached majors_native selections/entries rk<30 (BTC/ETH/SOL/HYPE), hold 8h, "
                      "RT 5.5bp (4 fee + 1.5 lag-slip)",
            "px_basis": "asset_ctx mid ASOF <=90s both ends (baked into cached mk/mk8); "
                        "unevaluable dropped",
            "position_rules": "max 1 concurrent per (wallet,coin); max $50k gross per coin; "
                              "skip beyond cap",
            "pnl_attribution": "entry day (UTC); zero-PnL days included",
            "sizing": {"S1": "fixed $5k/entry",
                       "S2": "$25k/day per selected wallet split equally across its that-day "
                             "candidate entries in the book (pre skip rules)",
                       "S3": "$5k * clip(20bp / trailing-30d daily close vol bp, 0.2, 3); "
                             ">=20 return obs in [D-30,D-1] else factor 1.0"},
            "archetype_gate": "formation coin_breadth>=10, taker_share in [0.2,0.7], active days "
                              ">=100 implemented as >=100 wallet-coin-day rows (literal >=100 "
                              "distinct days is unsatisfiable in a 90-92 day window: 0 pass)",
        },
        "s3_factor_diag": {b: {"median": round(float(np.median(vol_fac[b])), 3),
                               "share_at_floor_0.2": round(float(np.mean(vol_fac[b] <= 0.2 + 1e-12)), 3),
                               "share_fallback_1.0": round(float(np.mean(vol_fac[b] == 1.0)), 3)}
                           for b in ("A", "B")},
        "archetype_gate_diag": {"wallet_folds_pass": len(gate), "literal_days_pass": int(lit),
                                "gated_A_entries": int(gate_mask.sum()),
                                "total_A_entries": int(gate_mask.size)},
        "rows": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in rows.items()},
        "skips": skips,
        "s2_composition_gross_mk_by_walletday_count": s2_comp,
        "monthly_pnl": monthly,
    }
    OUT_JSON.write_text(json.dumps(report, indent=1))
    print(f"-> {OUT_JSON}", flush=True)

    # markdown
    hdr = ("| row | trades | net PnL $ | gross PnL $ | Sharpe | Sortino | maxDD $ | maxDD % | "
           "hit(d) | avg expo $ | max expo $ | net bp/trade |")
    sep = "|" + "---|" * 12
    lines = [
        "# BACKTEST — DESCRIPTIVE BOOK MECHANICS (frozen candidates, burned folds 202511-202606)", "",
        "**DESCRIPTIVE ONLY.** Burned-fold stamp: all 8 folds (202511-202606) were consumed by the",
        "construction/selection studies; nothing here is out-of-sample and no sizing variant is",
        "crowned by argmax. Frozen specs (no selection/design changes):", "",
        f"- Book A: {report['frozen_specs']['book_A']}",
        f"- Book B: {report['frozen_specs']['book_B']}",
        f"- Px basis: {report['frozen_specs']['px_basis']}",
        f"- Position rules: {report['frozen_specs']['position_rules']}",
        f"- Costs: A RT = 21.5bp, B RT = 5.5bp; gross AND net reported.",
        f"- Sizing: S1 {report['frozen_specs']['sizing']['S1']}; S2 {report['frozen_specs']['sizing']['S2']}; "
        f"S3 {report['frozen_specs']['sizing']['S3']}",
        f"- Archetype gate: {report['frozen_specs']['archetype_gate']}",
        f"- Span {SPAN_D0}..{SPAN_D1} ({N_DAYS} days; prompt said 244, actual calendar = 242). "
        "PnL attributed to entry day (UTC). DD% of peak gross exposure (capital = max gross "
        "exposure observed). Hit rate = share of nonzero-PnL days positive.", "",
        "## Stats (books x sizings)", "", hdr, sep,
    ]
    for k, v in rows.items():
        lines.append(
            f"| {k} | {v['trades']:,} | {v['total_net_pnl_usd']:+,.0f} | {v['total_gross_pnl_usd']:+,.0f} "
            f"| {v['ann_sharpe']} | {v['ann_sortino']} | {v['max_dd_usd']:,.0f} "
            f"| {v['max_dd_pct_of_peak_expo']}% | {v['hit_rate_daily']} | {v['avg_gross_expo_usd']:,.0f} "
            f"| {v['max_gross_expo_usd']:,.0f} | {v['avg_trade_net_bp']:+.1f} |")
    lines += ["", "## Monthly PnL — Combined S1", "", "| month | trades | gross $ | net $ |", "|---|---|---|---|"]
    for f in FOLDS:
        m = monthly["combined_S1"][str(f)]
        lines.append(f"| {f} | {m['trades']:,} | {m['gross_usd']:+,.0f} | {m['net_usd']:+,.0f} |")
    lines += ["", "## S2 composition (gross mk bp by wallet-day candidate-entry count)",
              "", "S2 gives $25k/cnt per entry, so single-entry wallet-days get the largest size.",
              "", f"```{json.dumps(s2_comp, indent=1)}```",
              "", "## S3 factor diagnostics",
              "", f"```{json.dumps(report['s3_factor_diag'], indent=1)}```",
              "", "## Archetype gate diagnostics",
              "", f"```{json.dumps(report['archetype_gate_diag'], indent=1)}```", ""]
    OUT_MD.write_text("\n".join(lines))
    print(f"-> {OUT_MD}", flush=True)

    for k, v in rows.items():
        print(f"{k:<45} n={v['trades']:>5,} net=${v['total_net_pnl_usd']:>+10,.0f} "
              f"SR={v['ann_sharpe']} dd%={v['max_dd_pct_of_peak_expo']} bp={v['avg_trade_net_bp']:+.1f}",
              flush=True)


if __name__ == "__main__":
    run()
