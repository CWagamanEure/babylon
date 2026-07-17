"""FINAL SLATE BACKTEST — DESCRIPTIVE BOOK MECHANICS, burned folds 202511-202606.

Frozen final paper-slate specs; no design changes, no sizing sweep (S1 fixed $5k only).
  Book M: majors-native K30 @8h (cached majors_native entries rk<30, mk8), RT 5.5bp
          (4 fee + 1.5 lag-slip — kept at 5.5bp as in backtest_book.py Book B for
          consistency; the 7bp (4 + 2x1.5) alternative is NOT used, stated explicitly).
  Book G: GATED-ALT @8h — arm-T cohorts' E1 alt flat taker opens (exact
          termstructure_by_archetype entry spec, regenerated with coin/ts kept and
          verified against that cache), restricted to grinder-archetype wallets
          (cohort_census kmeans cluster 2), notional >= $250, coin trailing ADV >= $10M
          computed over the fold's FORMATION months from lake wallet_coin_day
          (honest/trailing — test-month ADV deliberately not used). RT 21.5bp.
  COMBINED = M + G. Sizing S1 $5k/entry; max 1 concurrent per (wallet,coin);
  $50k gross per coin cap. PnL attributed to entry day (UTC), 242-day span, zero days in.
Variant rows:
  (a) Book M ex-BOT: majors_archetype_classification.json BOT seats' entries dropped
      (entries only — descriptively no re-selection of replacement seats is possible).
  (b) Book G UNGATED: all archetypes, same >= $250 + trailing-ADV screen (gate delta).

Outputs: data/derived/copy_cohort/final_backtest_report.json
         + "FINAL SLATE BACKTEST" section appended to research/studies/copy_cohort/BACKTEST.md

Run: .venv/bin/python -m research.studies.copy_cohort.final_backtest
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np

from research.data.markout import REPO_ROOT
from . import backtest_book as bb
from . import lake
from .alt_fresh_validate import _ctx_parts

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
MAJN = DERIVED / "majors_native"
TS_CACHE = DERIVED / "termstructure_by_archetype"
G_CACHE = DERIVED / "final_slate_altG"
COHORTS = DERIVED / "alt_universe_cohorts.json"
CENSUS = DERIVED / "cohort_census.json"
BOTCLS = DERIVED / "majors_archetype_classification.json"
OUT_JSON = DERIVED / "final_backtest_report.json"
OUT_MD = REPO_ROOT / "research" / "studies" / "copy_cohort" / "BACKTEST.md"

FOLDS = bb.FOLDS
MAJORS = ("BTC", "ETH", "SOL", "HYPE")
STALE_MS = 90_000
H8_MS = 8 * 3_600_000
NOTL_MIN = 250.0
ADV_MIN = 10_000_000.0
GRINDER_CLUSTER = 2

# register the two final-slate books in the reused simulator
bb.HOLD_MS["M"] = H8_MS
bb.HOLD_MS["G"] = H8_MS
bb.COST_BP["M"] = 5.5    # 4 RT fee + 1.5 lag-slip (prior-backtest convention, stated)
bb.COST_BP["G"] = 21.5   # 20 RT fee + 1.5 lag-slip


# ------------------------------------------------------------- Book G entries
def _g_fold_entries(con, fold: int, wallets: list[str]) -> Path:
    """Arm-T E1 alt flat taker opens + 8h markout, KEEPING wallet/coin/ts/notl."""
    part = G_CACHE / f"entries_{fold}.parquet"
    if part.exists():
        return part
    part.parent.mkdir(parents=True, exist_ok=True)
    ctx = _ctx_parts(fold)
    if not ctx:
        raise RuntimeError(f"no asset_ctx for fold {fold}")
    majors = ",".join(f"'{m}'" for m in MAJORS)
    ctx_list = ",".join(f"'{p}'" for p in ctx)
    con.execute("CREATE OR REPLACE TEMP TABLE cw AS SELECT * FROM (SELECT UNNEST(?) AS wallet)",
                [sorted(wallets)])
    tmp = str(part) + ".tmp"
    con.execute(f"""COPY (
        WITH ent AS (
          SELECT o.wallet, o.coin, o.ts, o.dir_sign, CAST(o.notl AS DOUBLE) AS notl
          FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN cw USING (wallet)
          WHERE o.coin NOT IN ({majors})
        ),
        ctx AS (SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL),
        p0 AS (SELECT e.*, c.mid_px AS px0, c.ts AS ts0
               FROM ent e ASOF LEFT JOIN ctx c ON e.coin = c.coin AND e.ts >= c.ts),
        p1 AS (SELECT p0.*, c.mid_px AS px8, c.ts AS ts8
               FROM p0 ASOF LEFT JOIN ctx c ON p0.coin = c.coin AND (p0.ts + {H8_MS}) >= c.ts)
        SELECT wallet, coin, ts, notl,
               CASE WHEN px0 IS NOT NULL AND px0 > 0 AND (ts - ts0) <= {STALE_MS}
                      AND px8 IS NOT NULL AND ((ts + {H8_MS}) - ts8) <= {STALE_MS}
                    THEN dir_sign * (px8 - px0) / px0 * 1e4 END AS mk_8h
        FROM p1) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
    Path(tmp).replace(part)
    return part


def _g_adv_formation(con, fold: int, formation_months: list[int]) -> Path:
    """Coin ADV over the fold's formation months (trailing, honest), cached."""
    p = G_CACHE / f"adv_form_{fold}.parquet"
    if p.exists():
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in formation_months)
    tmp = str(p) + ".tmp"
    con.execute(f"""COPY (
        SELECT coin, SUM(CAST(notional AS DOUBLE)) / 2 / COUNT(DISTINCT day) AS adv
        FROM read_parquet([{globs}]) GROUP BY coin
    ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
    Path(tmp).replace(p)
    return p


def _verify_vs_termstructure(fold: int, part: Path) -> dict:
    """Regenerated entries must match the frozen termstructure cache (count + mk_8h)."""
    ref = TS_CACHE / f"fold={fold}" / "part.parquet"
    lc = duckdb.connect()
    a = lc.execute(f"""SELECT count(*), count(mk_8h), round(avg(mk_8h), 6)
                       FROM read_parquet('{part.as_posix()}')""").fetchone()
    b = lc.execute(f"""SELECT count(*), count(mk_8h), round(avg(mk_8h), 6)
                       FROM read_parquet('{ref.as_posix()}')""").fetchone()
    lc.close()
    ok = a[0] == b[0] and a[1] == b[1] and abs((a[2] or 0) - (b[2] or 0)) <= 1e-4
    return {"fold": fold, "n_new": a[0], "n_ref": b[0], "n_eval_new": a[1], "n_eval_ref": b[1],
            "avg_mk8_new": a[2], "avg_mk8_ref": b[2], "match": ok}


def load_book_g():
    """Returns candidate dict (all arm-T E1, screened by notl+ADV+evaluability),
    grinder gate mask, verification records, screen diagnostics."""
    cohorts = json.loads(COHORTS.read_text())
    census = json.loads(CENSUS.read_text())
    grinders = {w["wallet"] for w in census["wallets"] if w["cluster"] == GRINDER_CLUSTER}
    con = lake.connect()
    parts, verifs, diags = [], [], {}
    for f in FOLDS:
        info = cohorts["folds"][str(f)]
        members = sorted(info["arms"]["T"]["members"])
        part = _g_fold_entries(con, f, members)
        verifs.append(_verify_vs_termstructure(f, part))
        advp = _g_adv_formation(con, f, [int(m) for m in info["formation_months"]])
        lc = duckdb.connect()
        d = lc.execute(f"""
            SELECT e.wallet, e.coin, e.ts, e.mk_8h AS mk, {f} AS fold
            FROM read_parquet('{part.as_posix()}') e
            JOIN read_parquet('{advp.as_posix()}') a USING (coin)
            WHERE e.mk_8h IS NOT NULL AND e.notl >= {NOTL_MIN} AND a.adv >= {ADV_MIN}
            ORDER BY e.ts, e.wallet, e.coin""").fetchnumpy()
        tot, ev = lc.execute(f"""SELECT count(*), count(mk_8h)
                                 FROM read_parquet('{part.as_posix()}')""").fetchone()
        lc.close()
        diags[str(f)] = {"e1_total": int(tot), "e1_evaluable": int(ev),
                         "post_screen": int(d["ts"].size)}
        parts.append(d)
    con.close()
    c = {
        "wallet": np.concatenate([p["wallet"].astype(str) for p in parts]),
        "coin": np.concatenate([p["coin"].astype(str) for p in parts]),
        "ts": np.concatenate([np.asarray(p["ts"], np.int64) for p in parts]),
        "mk": np.concatenate([np.asarray(p["mk"], float) for p in parts]),
        "fold": np.concatenate([np.asarray(p["fold"], np.int64) for p in parts]),
    }
    o = np.lexsort((c["coin"], c["wallet"], c["ts"]))
    c = {k: v[o] for k, v in c.items()}
    gate = np.isin(c["wallet"], sorted(grinders))
    return c, gate, verifs, diags, len(grinders)


def load_book_m():
    """Cached majors_native entries rk<30 @8h; plus BOT-exclusion mask."""
    botcls = json.loads(BOTCLS.read_text())
    bots = {(int(f), w) for f, d in botcls.items() for w, v in d.items() if v["label"] == "BOT"}
    con = duckdb.connect()
    parts = []
    for f in FOLDS:
        parts.append(con.execute(f"""
            SELECT wallet, coin, ts, mk8 AS mk, {f} AS fold
            FROM '{(MAJN / f'entries_{f}.parquet').as_posix()}'
            WHERE rk < 30 AND mk8 IS NOT NULL
            ORDER BY ts, wallet, coin""").fetchnumpy())
    con.close()
    c = {
        "wallet": np.concatenate([p["wallet"].astype(str) for p in parts]),
        "coin": np.concatenate([p["coin"].astype(str) for p in parts]),
        "ts": np.concatenate([np.asarray(p["ts"], np.int64) for p in parts]),
        "mk": np.concatenate([np.asarray(p["mk"], float) for p in parts]),
        "fold": np.concatenate([np.asarray(p["fold"], np.int64) for p in parts]),
    }
    o = np.lexsort((c["coin"], c["wallet"], c["ts"]))
    c = {k: v[o] for k, v in c.items()}
    exbot = np.array([(int(f), w) not in bots for f, w in zip(c["fold"], c["wallet"])])
    n_bot_seats = len(bots)
    return c, exbot, n_bot_seats


# ------------------------------------------------------------------------ main
def run() -> None:
    cm, exbot_mask, n_bot_seats = load_book_m()
    cg, gate_mask, verifs, g_diags, n_grinders = load_book_g()
    assert all(v["match"] for v in verifs), f"Book G cache verification FAILED: {verifs}"
    print(f"M entries={cm['ts'].size:,} (ex-BOT keeps {exbot_mask.sum():,}); "
          f"G screened entries={cg['ts'].size:,} (grinder-gated {gate_mask.sum():,}; "
          f"{n_grinders} grinder wallets in census)", flush=True)
    for v in verifs:
        print(f"  verify fold {v['fold']}: n={v['n_new']}=={v['n_ref']} "
              f"avg_mk8 {v['avg_mk8_new']} vs {v['avg_mk8_ref']} -> {v['match']}", flush=True)

    s1 = lambda c: np.full(c["ts"].size, bb.S1_SIZE)
    sims = {
        "M": bb.simulate(cm, s1(cm), "M"),
        "M_exbot": bb.simulate(cm, s1(cm), "M", mask=exbot_mask),
        "G_gated": bb.simulate(cg, s1(cg), "G", mask=gate_mask),
        "G_ungated": bb.simulate(cg, s1(cg), "G"),
    }
    fr = {k: bb.trade_frames(v) for k, v in sims.items()}
    rows = {
        "Book M (majors K30 @8h, RT 5.5bp) / S1": bb.book_stats([fr["M"]]),
        "Book M ex-BOT (entries dropped, no re-selection) / S1": bb.book_stats([fr["M_exbot"]]),
        "Book G (GATED-ALT grinder @8h, RT 21.5bp) / S1": bb.book_stats([fr["G_gated"]]),
        "Book G UNGATED (all archetypes, same screens) / S1": bb.book_stats([fr["G_ungated"]]),
        "COMBINED (M + G gated) / S1": bb.book_stats([fr["M"], fr["G_gated"]]),
    }

    # monthly net PnL for COMBINED
    fold_all = np.concatenate([fr["M"]["fold"], fr["G_gated"]["fold"]])
    net_all = np.concatenate([fr["M"]["net"], fr["G_gated"]["net"]])
    gross_all = np.concatenate([fr["M"]["gross"], fr["G_gated"]["gross"]])
    monthly = {str(f): {"net_usd": round(float(net_all[fold_all == f].sum()), 2),
                        "gross_usd": round(float(gross_all[fold_all == f].sum()), 2),
                        "trades": int((fold_all == f).sum())} for f in FOLDS}

    gate_delta = {
        "gated_net_usd": rows["Book G (GATED-ALT grinder @8h, RT 21.5bp) / S1"]["total_net_pnl_usd"],
        "ungated_net_usd": rows["Book G UNGATED (all archetypes, same screens) / S1"]["total_net_pnl_usd"],
        "gated_net_bp": rows["Book G (GATED-ALT grinder @8h, RT 21.5bp) / S1"]["avg_trade_net_bp"],
        "ungated_net_bp": rows["Book G UNGATED (all archetypes, same screens) / S1"]["avg_trade_net_bp"],
    }

    report = {
        "label": "FINAL SLATE BACKTEST — DESCRIPTIVE BOOK MECHANICS, burned folds 202511-202606, "
                 "no design changes, no sizing sweep (S1 only)",
        "stamp": {"folds": FOLDS, "span": [str(bb.SPAN_D0), str(bb.SPAN_D1)], "n_days": bb.N_DAYS,
                  "burned": "all 8 folds consumed by construction/selection studies; "
                            "nothing here is out-of-sample"},
        "frozen_specs": {
            "book_M": "majors-native K30 @8h (cached majors_native entries rk<30, mk8, "
                      "BTC/ETH/SOL/HYPE); RT 5.5bp (4 fee + 1.5 lag-slip) — kept at 5.5bp as in "
                      "the prior backtest (backtest_book.py Book B) for consistency; the 7bp "
                      "(4 + 2x1.5) variant is NOT used",
            "book_G": "GATED-ALT @8h — arm-T E1 alt flat taker opens (exact "
                      "termstructure_by_archetype spec, regenerated with coin/ts and verified "
                      "against that cache), grinder-archetype wallets only (census kmeans "
                      "cluster 2, post-hoc pooled labels), notional >= $250, coin ADV >= $10M "
                      "computed over the fold's FORMATION months from lake wallet_coin_day "
                      "(trailing, honest — test-month ADV not used); RT 21.5bp (20 + 1.5)",
            "sizing": "S1 fixed $5k/entry only; max 1 concurrent per (wallet,coin); "
                      "$50k gross per coin cap; hold 8h both books",
            "px_basis": "asset_ctx mid ASOF <=90s both ends; unevaluable dropped",
            "pnl_attribution": "entry day (UTC); zero-PnL days included; DD% of peak gross expo",
            "variants": {"M_exbot": "majors_archetype_classification BOT seats' entries dropped "
                                    "(entries only; descriptively no re-selection possible)",
                         "G_ungated": "all archetypes, same $250 + trailing-ADV screens"},
        },
        "book_g_cache_verification": verifs,
        "book_g_screen_diags": g_diags,
        "bot_seat_walletfolds": n_bot_seats,
        "grinder_wallets_census": n_grinders,
        "rows": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                 for k, v in rows.items()},
        "skips": {k: {"n_skip_wallet_coin_concurrent": v["n_skip_wc"],
                      "n_skip_coin_cap": v["n_skip_cap"], "n_accepted": int(v["idx"].size)}
                  for k, v in sims.items()},
        "monthly_pnl_combined_S1": monthly,
        "gate_delta": gate_delta,
    }
    OUT_JSON.write_text(json.dumps(report, indent=1))
    print(f"-> {OUT_JSON}", flush=True)

    hdr = ("| row | trades | net PnL $ | gross PnL $ | Sharpe | Sortino | maxDD $ | maxDD % | "
           "hit(d) | avg expo $ | max expo $ | net bp/trade |")
    sep = "|" + "---|" * 12
    lines = [
        "", "---", "",
        "# FINAL SLATE BACKTEST (burned folds 202511-202606 — DESCRIPTIVE, not out-of-sample)", "",
        "**Burned-fold stamp:** all 8 folds were consumed by the construction/selection studies;",
        "no design changes, no sizing sweep (S1 fixed $5k/entry only), nothing here is OOS.", "",
        f"- Book M: {report['frozen_specs']['book_M']}",
        f"- Book G: {report['frozen_specs']['book_G']}",
        f"- {report['frozen_specs']['sizing']}",
        f"- {report['frozen_specs']['pnl_attribution']}; span {bb.SPAN_D0}..{bb.SPAN_D1} "
        f"({bb.N_DAYS} days). Hit rate = share of nonzero-PnL days positive.", "",
        "## Stats", "", hdr, sep,
    ]
    for k, v in rows.items():
        lines.append(
            f"| {k} | {v['trades']:,} | {v['total_net_pnl_usd']:+,.0f} | "
            f"{v['total_gross_pnl_usd']:+,.0f} | {v['ann_sharpe']} | {v['ann_sortino']} | "
            f"{v['max_dd_usd']:,.0f} | {v['max_dd_pct_of_peak_expo']}% | {v['hit_rate_daily']} | "
            f"{v['avg_gross_expo_usd']:,.0f} | {v['max_gross_expo_usd']:,.0f} | "
            f"{v['avg_trade_net_bp']:+.1f} |")
    lines += ["", "## Monthly net PnL — COMBINED S1", "",
              "| month | trades | gross $ | net $ |", "|---|---|---|---|"]
    for f in FOLDS:
        m = monthly[str(f)]
        lines.append(f"| {f} | {m['trades']:,} | {m['gross_usd']:+,.0f} | {m['net_usd']:+,.0f} |")
    lines += ["", "## Gate delta (Book G grinder gate vs ungated)", "",
              f"```{json.dumps(gate_delta, indent=1)}```", "",
              "## Book G cache verification (regenerated E1 vs frozen termstructure cache)", "",
              f"```{json.dumps(verifs, indent=1)}```", ""]
    with OUT_MD.open("a") as fh:
        fh.write("\n".join(lines))
    print(f"-> appended to {OUT_MD}", flush=True)

    for k, v in rows.items():
        print(f"{k:<55} n={v['trades']:>5,} net=${v['total_net_pnl_usd']:>+10,.0f} "
              f"SR={v['ann_sharpe']} dd%={v['max_dd_pct_of_peak_expo']} "
              f"bp={v['avg_trade_net_bp']:+.1f}", flush=True)


if __name__ == "__main__":
    run()
