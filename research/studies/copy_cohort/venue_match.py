"""DESCRIPTIVE re-cut of the two frozen books by FORMATION venue-specialization.

LABEL: DESCRIPTIVE — burned folds 202511-202606; re-cut of existing frozen-book measurements
by a pre-existing feature (formation majors notional share from lake wallet_coin_day); NO new
selection. Post-hoc-motivated: the feature pre-existed but the cut was chosen after the
wallet-attribution pass (its worst5/best5 majors-share lean, MW p~0.07). Cells are dependent
(same wallets appear in both books and across folds).

Feature: per (wallet, fold), majors_share = majors notional / total notional over that fold's
3 formation months (lake alt_universe_wallet_coin_day; majors = BTC/ETH/SOL/HYPE).

Buckets:
  M book (majors-native K30@8h): MATCHED majors_share >= 0.8 | MIXED (0.2, 0.8) | MISMATCHED <= 0.2
  P book (pyramid-alt ladder):   MATCHED majors_share <= 0.2 | MIXED (0.2, 0.8) | MISMATCHED >= 0.8

Per book x bucket: n wallet-folds, n trades/units, pooled net bp/trade, wallet-fold-equal
winsorized gross bp (per-trade gross winsorized at the BOOK's [1,99] pct, then equal-weight
mean of wallet-fold means), day-block bootstrap CI on pooled net bp (1000 reps, 242-day span,
entry-day blocks), % wallet-folds positive by net.

    python -m research.studies.copy_cohort.venue_match
"""
from __future__ import annotations

import json
from collections import defaultdict

import duckdb
import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS
from . import lake
from . import pyramid_book as pb
from .alt_fresh_validate import MAJORS

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
MN = DERIVED / "majors_native"
VM = DERIVED / "venue_match"
OUT_JSON = DERIVED / "venue_match_report.json"
OUT_MD = REPO_ROOT / "research" / "studies" / "copy_cohort" / "WALLET_ATTRIBUTION.md"

FOLDS = MONTHS[3:]                       # 202511..202606
K_M = 30
COST_M_BP = 5.5
UNIT_USD = 2_500.0
DAY_MS = 86_400_000
SPAN_T0_MS = pb.SPAN_T0_MS               # 2025-11-01 UTC
N_DAYS = pb.N_DAYS                       # 242
N_BOOT = 1000
SEED = 20260717
CASE_WALLET = "0xa1b6d8efbcb2fb750a84dbc05649fa4968034f04"

STAMP = ("DESCRIPTIVE re-cut of frozen books by formation venue-specialization; burned folds "
         "202511-202606; feature pre-existing, cut chosen post-hoc after attribution; "
         "dependent cells; hypothesis-grade — no new selection derived from this.")


def _formation_months(fold: int) -> list[int]:
    i = MONTHS.index(fold)
    return MONTHS[i - 3:i]


# ---------------------------------------------------------------- book loaders
def load_m_trades():
    """per-trade arrays: wallet, fold, ts, gross_bp (mk8), net_bp."""
    con = duckdb.connect()
    w, fold, ts, g = [], [], [], []
    for f in FOLDS:
        d = con.execute(
            f"SELECT wallet, ts, mk8 FROM read_parquet('{(MN / f'entries_{f}.parquet').as_posix()}') "
            f"WHERE rk < {K_M} AND mk8 IS NOT NULL AND isfinite(mk8)").fetchnumpy()
        w.append(d["wallet"].astype(str))
        fold.append(np.full(d["wallet"].size, f))
        ts.append(np.asarray(d["ts"], np.int64))
        g.append(np.asarray(d["mk8"], float))
    con.close()
    gross = np.concatenate(g)
    return (np.concatenate(w), np.concatenate(fold), np.concatenate(ts),
            gross, gross - COST_M_BP)


def load_p_units():
    """Re-sim the frozen pyramid ladder from caches (identical path to wallet_attribution)."""
    cohorts = json.loads(pb.COHORTS_JSON.read_text())
    funnel = {"n_watch_started": 0, "n_watch_expired": 0, "n_add_ignored_idle": 0,
              "n_after_4th": 0, "n_miss_entry_px": 0, "n_cap_skip_book": 0,
              "n_cap_skip_coin": 0, "n_units_filled_rung": {}, "exit_flag_counts": {},
              "n_units_no_exit_px": 0}
    units: list[dict] = []
    for f in pb.FOLDS:
        info = cohorts["folds"][str(f)]
        liq = pb._liquid_alts(None, f)                       # advm caches exist -> con unused
        sig, _ = pb._fold_signals(None, f, info["wallets"], liq)
        ctx = pb._ctx_by_coin(f, set(sig["coin"].tolist()))
        n0 = len(units)
        pb.simulate_fold(f, sig, ctx, funnel, units)
        print(f"  P fold {f}: {len(units) - n0:,} units", flush=True)
    w = np.array([u["wallet"] for u in units])
    fold = np.array([u["fold"] for u in units])
    ts = np.array([u["ts_fill"] for u in units], np.int64)
    gross_bp = np.array([u["gross"] for u in units]) / UNIT_USD * 1e4
    net_bp = np.array([u["net"] for u in units]) / UNIT_USD * 1e4
    return w, fold, ts, gross_bp, net_bp


# ------------------------------------------------------ formation venue profile
def formation_shares(need: dict[int, set[str]]) -> dict[tuple[str, int], float | None]:
    """(wallet, fold) -> formation majors_share; cached per fold under venue_match/."""
    VM.mkdir(parents=True, exist_ok=True)
    out: dict[tuple[str, int], float | None] = {}
    con = None
    majors = ",".join(f"'{m}'" for m in MAJORS)
    for f in sorted(need):
        p = VM / f"form_{f}.parquet"
        wallets = sorted(need[f])
        if not p.exists():
            if con is None:
                con = lake.connect()
            globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in _formation_months(f))
            con.execute("CREATE OR REPLACE TEMP TABLE vw AS SELECT UNNEST(?) AS wallet", [wallets])
            tmp = str(p) + ".tmp"
            con.execute(f"""COPY (
                SELECT d.wallet,
                       SUM(CAST(d.notional AS DOUBLE))                                  AS notl,
                       COALESCE(SUM(CAST(d.notional AS DOUBLE))
                                FILTER (WHERE d.coin IN ({majors})), 0)                 AS notl_maj
                FROM read_parquet([{globs}]) d JOIN vw USING (wallet)
                GROUP BY d.wallet
            ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
            (VM / f"form_{f}.parquet.tmp").replace(p)
            print(f"  formation venue cached: fold {f} ({len(wallets)} wallets)", flush=True)
        lc = duckdb.connect()
        rows = lc.execute(
            f"SELECT wallet, notl, notl_maj FROM read_parquet('{p.as_posix()}')").fetchall()
        lc.close()
        got = {w: (float(nm) / float(n) if n else None) for w, n, nm in rows}
        for w in wallets:
            out[(w, f)] = got.get(w)
        missing_cached = need[f] - {r[0] for r in rows}
        if missing_cached and con is None:
            # cache was built for a smaller wallet list — rebuild
            p.unlink()
            return formation_shares(need)
    return out


# ------------------------------------------------------------------ bucketing
def bucket_of(share: float | None, book: str) -> str:
    if share is None:
        return "UNKNOWN"
    if book == "M":
        return "MATCHED" if share >= 0.8 else ("MISMATCHED" if share <= 0.2 else "MIXED")
    return "MATCHED" if share <= 0.2 else ("MISMATCHED" if share >= 0.8 else "MIXED")


def block_boot_ci(net_usd: np.ndarray, day: np.ndarray, rng) -> tuple[list[float], float]:
    """Day-block bootstrap CI on pooled net bp/trade over the 242-day span."""
    dnet, dsize = np.zeros(N_DAYS), np.zeros(N_DAYS)
    np.add.at(dnet, day, net_usd)
    np.add.at(dsize, day, np.full(net_usd.size, UNIT_USD))
    idx = rng.integers(0, N_DAYS, size=(N_BOOT, N_DAYS))
    tn, tsz = dnet[idx].sum(axis=1), dsize[idx].sum(axis=1)
    ok = tsz > 0
    bp = np.full(N_BOOT, np.nan)
    bp[ok] = tn[ok] / tsz[ok] * 1e4
    return ([round(float(np.nanpercentile(bp, q)), 2) for q in (2.5, 97.5)],
            round(float(np.nanmean(bp > 0)), 4))


def build_cut(book: str, w, fold, ts, gross_bp, net_bp, shares, rng):
    day = np.clip((ts - SPAN_T0_MS) // DAY_MS, 0, N_DAYS - 1).astype(np.int64)
    net_usd = net_bp * 1e-4 * UNIT_USD
    lo, hi = np.percentile(gross_bp, [1, 99])          # book-level winsor bounds
    gwin = np.clip(gross_bp, lo, hi)
    wf_share = {key: shares[key] for key in {(a, int(b)) for a, b in zip(w, fold)}}
    wf_bucket = {key: bucket_of(s, book) for key, s in wf_share.items()}
    trade_bucket = np.array([wf_bucket[(a, int(b))] for a, b in zip(w, fold)])

    total_net = float(net_usd.sum())
    out = {"winsor_bounds_gross_bp": [round(float(lo), 2), round(float(hi), 2)],
           "n_wallet_folds": len(wf_bucket), "buckets": {}}
    for b in ("MATCHED", "MIXED", "MISMATCHED", "UNKNOWN"):
        m = trade_bucket == b
        keys = [k for k, v in wf_bucket.items() if v == b]
        if not keys:
            continue
        # wallet-fold-equal winsorized gross
        wf_means, wf_net = [], []
        for key in keys:
            mm = (w == key[0]) & (fold == key[1])
            wf_means.append(float(gwin[mm].mean()))
            wf_net.append(float(net_usd[mm].sum()))
        wf_means, wf_net = np.array(wf_means), np.array(wf_net)
        ci, p_gt0 = (block_boot_ci(net_usd[m], day[m], rng) if m.sum() > 1
                     else ([None, None], None))
        out["buckets"][b] = {
            "n_wallet_folds": len(keys),
            "n_wallets": len({k[0] for k in keys}),
            "n_trades": int(m.sum()),
            "share_of_book_trades": round(float(m.mean()), 4),
            "net_usd": round(float(net_usd[m].sum()), 2),
            "share_of_book_net": round(float(net_usd[m].sum()) / total_net, 4)
                                 if total_net else None,
            "pooled_net_bp_per_trade": round(float(net_bp[m].mean()), 2),
            "pooled_gross_bp_per_trade": round(float(gross_bp[m].mean()), 2),
            "walletfold_equal_winsor_gross_bp": round(float(wf_means.mean()), 2),
            "net_bp_dayblock_boot_ci95": ci, "p_net_gt0": p_gt0,
            "frac_walletfolds_positive": round(float((wf_net > 0).mean()), 3),
            "median_majors_share": round(float(np.median(
                [wf_share[k] for k in keys if wf_share[k] is not None])), 3)
                if any(wf_share[k] is not None for k in keys) else None,
        }
    # monotonic check on pooled net bp: MISMATCHED < MIXED < MATCHED
    seq = [out["buckets"].get(b, {}).get("pooled_net_bp_per_trade")
           for b in ("MISMATCHED", "MIXED", "MATCHED")]
    have = [v for v in seq if v is not None]
    out["monotonic_pooled_net"] = bool(all(a < b for a, b in zip(have, have[1:]))) \
        if len(have) >= 2 else None
    seq_we = [out["buckets"].get(b, {}).get("walletfold_equal_winsor_gross_bp")
              for b in ("MISMATCHED", "MIXED", "MATCHED")]
    have_we = [v for v in seq_we if v is not None]
    out["monotonic_walletequal_gross"] = bool(all(a < b for a, b in zip(have_we, have_we[1:]))) \
        if len(have_we) >= 2 else None
    # case study
    cm = w == CASE_WALLET
    if cm.any():
        rows = []
        for f in sorted({int(x) for x in fold[cm]}):
            mm = cm & (fold == f)
            rows.append({"fold": f, "majors_share": wf_share.get((CASE_WALLET, f)),
                         "bucket": wf_bucket.get((CASE_WALLET, f)),
                         "n": int(mm.sum()), "net_bp": round(float(net_bp[mm].mean()), 2),
                         "net_usd": round(float(net_usd[mm].sum()), 2)})
        out["case_0xa1b6d8ef"] = rows
    return out


# ------------------------------------------------------------------ markdown
def md_section(rep) -> str:
    lines = ["\n\n## VENUE-MATCH RE-CUT (formation majors-share buckets)\n",
             f"**STAMP: {rep['stamp']}**\n",
             "Feature: formation (3-mo, pre-fold) majors notional share from lake "
             "wallet_coin_day; majors = BTC/ETH/SOL/HYPE. M buckets: MATCHED >= 0.8 / MIXED / "
             "MISMATCHED <= 0.2; P buckets mirrored (MATCHED <= 0.2). Wallet-equal gross = "
             "per-trade gross winsorized at book [1,99] pct, equal-weight over wallet-folds. "
             "CI = entry-day-block bootstrap (1000, 242-day span) on pooled net bp.\n"]
    for key, name in (("M", "MAJORS-NATIVE K30 @8h"), ("P", "PYRAMID-ALT ladder")):
        b = rep["books"][key]
        lines.append(f"\n### {name}\n")
        lines.append("| bucket | wf | wallets | trades | %book | net $ | net bp/tr | "
                     "we-gross bp | boot CI95 | P(>0) | %wf>0 | med maj% |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for bk in ("MATCHED", "MIXED", "MISMATCHED", "UNKNOWN"):
            r = b["buckets"].get(bk)
            if not r:
                continue
            ci = r["net_bp_dayblock_boot_ci95"]
            ci_s = f"[{ci[0]:+.1f}, {ci[1]:+.1f}]" if ci[0] is not None else "—"
            lines.append(
                f"| {bk} | {r['n_wallet_folds']} | {r['n_wallets']} | {r['n_trades']:,} | "
                f"{r['share_of_book_trades']:.0%} | {r['net_usd']:+,.0f} | "
                f"{r['pooled_net_bp_per_trade']:+.1f} | "
                f"{r['walletfold_equal_winsor_gross_bp']:+.1f} | {ci_s} | "
                f"{r['p_net_gt0'] if r['p_net_gt0'] is not None else '—'} | "
                f"{r['frac_walletfolds_positive']:.0%} | {r['median_majors_share']} |")
        lines.append(f"\nMonotone (MISMATCHED<MIXED<MATCHED): pooled net "
                     f"{b['monotonic_pooled_net']}, wallet-equal gross "
                     f"{b['monotonic_walletequal_gross']}.")
        if "case_0xa1b6d8ef" in b:
            cs = " ; ".join(
                f"{r['fold']}: maj%={r['majors_share']:.2f} {r['bucket']} n={r['n']} "
                f"{r['net_bp']:+.1f}bp (${r['net_usd']:+,.0f})"
                for r in b["case_0xa1b6d8ef"])
            lines.append(f"\nCase 0xa1b6d8ef: {cs}")
        lines.append("")
    lines.append(f"\nArtifact: `data/derived/copy_cohort/venue_match_report.json`.\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------- main
def run():
    print("[M] loading majors-native trades ...", flush=True)
    mw, mf, mts, mg, mn = load_m_trades()
    print(f"  M: {mw.size:,} trades, {np.unique(mw).size} wallets", flush=True)
    print("[P] re-simulating pyramid ladder from caches ...", flush=True)
    pw, pf, pts, pg, pn = load_p_units()
    print(f"  P: {pw.size:,} units, {np.unique(pw).size} wallets, "
          f"net ${float((pn * 1e-4 * UNIT_USD).sum()):,.0f}", flush=True)

    need: dict[int, set[str]] = defaultdict(set)
    for a, b in zip(mw, mf):
        need[int(b)].add(a)
    for a, b in zip(pw, pf):
        need[int(b)].add(a)
    print(f"[lake] formation venue profiles for "
          f"{sum(len(v) for v in need.values())} wallet-folds ...", flush=True)
    shares = formation_shares(dict(need))
    n_none = sum(1 for v in shares.values() if v is None)
    print(f"  shares resolved: {len(shares)} wallet-folds ({n_none} unknown)", flush=True)

    rng = np.random.default_rng(SEED)
    rep = {"label": "venue-match re-cut of frozen books M and P by formation majors-share",
           "stamp": STAMP,
           "config": {"majors": list(MAJORS), "buckets_M": "MATCHED>=0.8 / MIXED / MISMATCHED<=0.2",
                      "buckets_P": "MATCHED<=0.2 / MIXED / MISMATCHED>=0.8",
                      "formation": "3 months preceding fold, lake wallet_coin_day notional",
                      "winsor": "per-trade gross bp clipped at book [1,99] pct",
                      "boot": {"n": N_BOOT, "seed": SEED, "block": "entry UTC day",
                               "span_days": N_DAYS},
                      "unit_usd": UNIT_USD, "cost_m_bp": COST_M_BP, "cost_p_bp": pb.COST_RT_BP,
                      "n_unknown_walletfolds": n_none},
           "books": {"M": build_cut("M", mw, mf, mts, mg, mn, shares, rng),
                     "P": build_cut("P", pw, pf, pts, pg, pn, shares, rng)}}
    OUT_JSON.write_text(json.dumps(rep, indent=1))
    print(f"-> {OUT_JSON}")
    with OUT_MD.open("a") as fh:
        fh.write(md_section(rep))
    print(f"-> appended to {OUT_MD}")
    return rep


if __name__ == "__main__":
    run()
