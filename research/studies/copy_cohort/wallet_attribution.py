"""DESCRIPTIVE per-wallet attribution of the two frozen books (burned folds 202511-202606).

LABEL: DESCRIPTIVE — decomposition of already-run frozen books; NO new selection, nothing here
may be tuned into a selector without a fresh prereg. Ex-post worst/best-K rankings carry
winner/loser-curse by construction; all trait comparisons are hypothesis-grade (uncorrected).

Books:
  M = majors-native K30 @8h (cache data/derived/copy_cohort/majors_native/entries_*.parquet,
      rk<30, finite mk8; cost 5.5bp RT applied per trade; $2,500 equal-unit per trade assumed
      for $ attribution — the book is equal-weight by construction).
  P = pyramid-alt frozen ladder (re-simulated from caches via pyramid_book machinery; unit
      net already includes the 21.5bp RT cost; $2,500/unit).

Behavior metrics: lake alt_universe_wallet_coin_day + open_entries aggregated over the FULL
window 202508-202605 (union of formation windows) per wallet — a wallet-level descriptor, not
fold-specific. Hold-minutes proxy = median/mean gap between consecutive same-coin flat-open
entries (open_entries); this is a re-trade cadence proxy, NOT a true position hold time.

    python -m research.studies.copy_cohort.wallet_attribution
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
POOL = DERIVED / "informedness"
CENSUS = DERIVED / "cohort_census.json"
OUT_JSON = DERIVED / "wallet_attribution_report.json"
OUT_MD = REPO_ROOT / "research" / "studies" / "copy_cohort" / "WALLET_ATTRIBUTION.md"

FOLDS = MONTHS[3:]                       # 202511..202606
BEHAV_MONTHS = MONTHS[:-1]               # 202508..202605 (lake behavior window)
K_M = 30
COST_M_BP = 5.5
UNIT_USD = 2_500.0
STAMP = ("DESCRIPTIVE decomposition of frozen books, burned folds 202511-202606; ex-post "
         "rankings (winner/loser curse); trait tests hypothesis-grade, uncorrected; no new "
         "selection derived from this.")

BEHAV_COLS = ("trades_per_day", "fills_per_day", "taker_share", "coin_breadth",
              "majors_notl_share", "n_liq", "med_entry_notl", "med_gap_min", "avg_gap_min",
              "active_days", "total_notional")


# ------------------------------------------------------------------ book M trades
def load_m_trades():
    con = duckdb.connect()
    w, fold, bp = [], [], []
    form = defaultdict(lambda: {"t": [], "nd": []})
    for f in FOLDS:
        d = con.execute(
            f"SELECT wallet, mk8 FROM read_parquet('{(MN / f'entries_{f}.parquet').as_posix()}') "
            f"WHERE rk < {K_M} AND mk8 IS NOT NULL AND isfinite(mk8)").fetchnumpy()
        w.append(d["wallet"].astype(str))
        fold.append(np.full(d["wallet"].size, f))
        bp.append(np.asarray(d["mk8"], float) - COST_M_BP)
        # formation stats for the wallets that traded this fold
        ws = sorted(set(d["wallet"].astype(str).tolist()))
        if ws:
            wl = ",".join(f"'{x}'" for x in ws)
            for wal, t, nd in con.execute(
                    f"SELECT wallet, t_stat, nd FROM read_parquet("
                    f"'{(MN / f'sel_{f}.parquet').as_posix()}') WHERE wallet IN ({wl})").fetchall():
                form[wal]["t"].append(float(t))
                form[wal]["nd"].append(float(nd))
    con.close()
    return (np.concatenate(w), np.concatenate(fold), np.concatenate(bp), dict(form))


# ------------------------------------------------------------------ book P units
def load_p_units():
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
    form = defaultdict(lambda: {"t": [], "nd": []})
    con = duckdb.connect()
    traded = sorted({u["wallet"] for u in units})
    for f in pb.FOLDS:
        sel = set(cohorts["folds"][str(f)]["wallets"]) & set(traded)
        if not sel:
            continue
        wl = ",".join(f"'{x}'" for x in sorted(sel))
        p = (POOL / f"fold={f}" / "pool.parquet").as_posix()
        for wal, t, nd in con.execute(
                f"SELECT wallet, t_stat, nd FROM read_parquet('{p}') "
                f"WHERE wallet IN ({wl})").fetchall():
            form[wal]["t"].append(float(t))
            form[wal]["nd"].append(float(nd))
    con.close()
    return units, dict(form)


# ------------------------------------------------------------------ lake behavior
def behavior_metrics(wallets: list[str]) -> dict[str, dict]:
    con = lake.connect()
    con.execute("CREATE OR REPLACE TEMP TABLE uw AS SELECT UNNEST(?) AS wallet",
                [sorted(wallets)])
    wcd = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in BEHAV_MONTHS)
    ope = ",".join(f"'{lake.ope_month_glob(m)}'" for m in BEHAV_MONTHS)
    majors = ",".join(f"'{m}'" for m in MAJORS)
    print("  lake: wallet_coin_day aggregate ...", flush=True)
    rows = con.execute(f"""
        SELECT d.wallet,
               COUNT(DISTINCT d.day)                                    AS act_days,
               COUNT(DISTINCT d.coin)                                   AS breadth,
               SUM(d.n_fills)                                           AS nf,
               SUM(d.n_taker)                                           AS nt,
               SUM(d.n_open_flat)                                       AS nof,
               SUM(d.n_liq)                                             AS nliq,
               SUM(CAST(d.notional AS DOUBLE))                          AS notl,
               COALESCE(SUM(CAST(d.notional AS DOUBLE))
                        FILTER (WHERE d.coin IN ({majors})), 0)         AS notl_maj
        FROM read_parquet([{wcd}]) d JOIN uw USING (wallet)
        GROUP BY d.wallet""").fetchall()
    out = {}
    for wal, ad, br, nf, nt, nof, nliq, notl, nmaj in rows:
        out[wal] = {
            "active_days": int(ad), "coin_breadth": int(br),
            "fills_per_day": round(float(nf) / max(int(ad), 1), 2),
            "trades_per_day": round(float(nof) / max(int(ad), 1), 3),
            "taker_share": round(float(nt) / float(nf), 4) if nf else None,
            "n_liq": int(nliq),
            "total_notional": round(float(notl), 0),
            "majors_notl_share": round(float(nmaj) / float(notl), 4) if notl else None,
        }
    print("  lake: open_entries notional + gap proxy ...", flush=True)
    rows = con.execute(f"""
        WITH e AS (
          SELECT o.wallet, o.coin, o.ts, CAST(o.notl AS DOUBLE) AS notl
          FROM read_parquet([{ope}]) o JOIN uw USING (wallet)
        ),
        g AS (
          SELECT wallet, notl,
                 (ts - LAG(ts) OVER (PARTITION BY wallet, coin ORDER BY ts)) / 60000.0 AS gap
          FROM e
        )
        SELECT wallet, MEDIAN(notl), COUNT(*),
               MEDIAN(gap) FILTER (WHERE gap IS NOT NULL AND gap > 0),
               AVG(gap)    FILTER (WHERE gap IS NOT NULL AND gap > 0)
        FROM g GROUP BY wallet""").fetchall()
    for wal, mnotl, ne, mgap, agap in rows:
        o = out.setdefault(wal, {})
        o["med_entry_notl"] = round(float(mnotl), 1) if mnotl is not None else None
        o["n_flat_opens"] = int(ne)
        o["med_gap_min"] = round(float(mgap), 1) if mgap is not None else None
        o["avg_gap_min"] = round(float(agap), 1) if agap is not None else None
    con.close()
    return out


# ------------------------------------------------------------------ stats helpers
def dist_stats(x: np.ndarray) -> dict:
    x = np.asarray(x, float)
    if x.size == 0:
        return {}
    mu, sd = float(x.mean()), float(x.std(ddof=1)) if x.size > 1 else 0.0
    skew = float(((x - mu) ** 3).mean() / sd ** 3) if sd > 0 else None
    q = {f"p{p}": round(float(np.percentile(x, p)), 2) for p in (10, 25, 50, 75, 90)}
    return {"n": int(x.size), "mean": round(mu, 2), "median": q["p50"], **q,
            "sd": round(sd, 2), "skew": round(skew, 2) if skew is not None else None,
            "frac_positive": round(float((x > 0).mean()), 3)}


def mannwhitney_p(a, b) -> float | None:
    """Two-sided Mann-Whitney U, normal approximation with tie correction (numpy)."""
    a = np.asarray([v for v in a if v is not None], float)
    b = np.asarray([v for v in b if v is not None], float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    n1, n2 = a.size, b.size
    if n1 < 2 or n2 < 2:
        return None
    z = np.concatenate([a, b])
    order = z.argsort()
    ranks = np.empty(z.size)
    sz = z[order]
    i = 0
    while i < z.size:
        j = i
        while j + 1 < z.size and sz[j + 1] == sz[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    u = ranks[:n1].sum() - n1 * (n1 + 1) / 2
    mu = n1 * n2 / 2
    _, cnt = np.unique(z, return_counts=True)
    tie = (cnt ** 3 - cnt).sum()
    n = n1 + n2
    var = n1 * n2 / 12 * ((n + 1) - tie / (n * (n - 1)))
    if var <= 0:
        return None
    zs = (u - mu - np.sign(u - mu) * 0.5) / np.sqrt(var)
    from math import erf
    return round(2 * (1 - 0.5 * (1 + erf(abs(zs) / np.sqrt(2)))), 4)


# ------------------------------------------------------------------ per-book build
def build_book(name, wallets, folds, net_bp, net_usd, form, behav, census):
    """wallets/net_bp/net_usd are per-trade arrays; returns full book section."""
    uw = sorted(set(wallets.tolist()))
    per = []
    for wal in uw:
        m = wallets == wal
        nusd = float(net_usd[m].sum())
        fw = form.get(wal, {"t": [], "nd": []})
        row = {"wallet": wal, "n_trades": int(m.sum()),
               "net_usd": round(nusd, 2),
               "net_bp_per_trade": round(float(net_bp[m].mean()), 2),
               "n_folds_traded": int(np.unique(folds[m]).size),
               "form_t_mean": round(float(np.mean(fw["t"])), 2) if fw["t"] else None,
               "form_nd_mean": round(float(np.mean(fw["nd"])), 1) if fw["nd"] else None,
               "census_archetype": census.get(wal)}
        row.update({k: behav.get(wal, {}).get(k) for k in BEHAV_COLS})
        per.append(row)
    per.sort(key=lambda r: r["net_usd"])                     # worst first
    net = np.array([r["net_usd"] for r in per])
    ntr = np.array([r["n_trades"] for r in per])
    tot_net, tot_tr = float(net.sum()), int(ntr.sum())
    loss_tot = float(np.maximum(-net, 0).sum())
    win_tot = float(np.maximum(net, 0).sum())
    for r in per:
        r["share_gross_loss"] = round(max(-r["net_usd"], 0) / loss_tot, 4) if loss_tot else 0.0
        r["share_gross_win"] = round(max(r["net_usd"], 0) / win_tot, 4) if win_tot else 0.0

    # concentration
    conc = {"total_net_usd": round(tot_net, 2), "n_wallets": len(per), "n_trades": tot_tr,
            "book_net_bp_per_trade": round(tot_net / (tot_tr * UNIT_USD) * 1e4, 2),
            "gross_wallet_loss_usd": round(loss_tot, 2),
            "gross_wallet_win_usd": round(win_tot, 2)}
    for k in (1, 3, 5):
        conc[f"loss_share_worst_{k}"] = round(
            float(np.maximum(-net[:k], 0).sum()) / loss_tot, 4) if loss_tot else None
        conc[f"win_share_best_{k}"] = round(
            float(np.maximum(net[-k:], 0).sum()) / win_tot, 4) if win_tot else None
    worst_curve, best_curve = [], []
    for k in range(1, 11):
        rn, rt = float(net[k:].sum()), int(ntr[k:].sum())
        worst_curve.append({"drop": k, "net_usd": round(rn, 2),
                           "net_bp": round(rn / (rt * UNIT_USD) * 1e4, 2) if rt else None})
        rn, rt = float(net[:-k].sum()), int(ntr[:-k].sum())
        best_curve.append({"drop": k, "net_usd": round(rn, 2),
                          "net_bp": round(rn / (rt * UNIT_USD) * 1e4, 2) if rt else None})
    conc["drop_worst_k_expost"] = worst_curve
    conc["drop_best_k_expost"] = best_curve

    dist = {"per_wallet_net_bp": dist_stats(np.array([r["net_bp_per_trade"] for r in per])),
            "per_wallet_net_usd": dist_stats(net),
            "per_trade_net_bp": dist_stats(net_bp)}

    worst5, best5 = per[:5], per[-5:]
    metrics = list(BEHAV_COLS) + ["form_t_mean", "form_nd_mean", "n_trades"]
    prof = {}
    for k in metrics:
        aw = [r.get(k) for r in worst5]
        ab = [r.get(k) for r in best5]
        awn = [v for v in aw if v is not None]
        abn = [v for v in ab if v is not None]
        prof[k] = {"worst5_median": round(float(np.median(awn)), 3) if awn else None,
                   "best5_median": round(float(np.median(abn)), 3) if abn else None,
                   "mw_p": mannwhitney_p(aw, ab)}
    return {"per_wallet": per, "concentration": conc, "distribution": dist,
            "dragger_profile": prof,
            "worst5": [r["wallet"] for r in worst5], "best5": [r["wallet"] for r in best5]}


# ------------------------------------------------------------------ markdown
def md_wallet_table(per, top_n=None):
    rows = per if top_n is None else per[:top_n]
    hdr = ("| wallet | net $ | n | bp/tr | folds | loss% | win% | t | nd | tr/d | f/d | taker "
           "| brd | maj% | medNotl | gapMed(m) | liq | archetype |\n"
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    out = hdr
    for r in rows:
        out += ("| {w} | {net:+,.0f} | {n} | {bp:+.1f} | {fd} | {ls:.0%} | {ws:.0%} | {t} | {nd} "
                "| {td} | {fpd} | {tk} | {br} | {mj} | {mn} | {gp} | {lq} | {ar} |\n").format(
            w=r["wallet"][:10] + "…", net=r["net_usd"], n=r["n_trades"],
            bp=r["net_bp_per_trade"], fd=r["n_folds_traded"],
            ls=r["share_gross_loss"], ws=r["share_gross_win"],
            t=r["form_t_mean"], nd=r["form_nd_mean"], td=r.get("trades_per_day"),
            fpd=r.get("fills_per_day"), tk=r.get("taker_share"), br=r.get("coin_breadth"),
            mj=r.get("majors_notl_share"), mn=r.get("med_entry_notl"),
            gp=r.get("med_gap_min"), lq=r.get("n_liq"), ar=r.get("census_archetype") or "—")
    return out


def write_md(rep):
    lines = [f"# WALLET ATTRIBUTION — per-wallet decomposition of the two frozen books\n",
             f"**STAMP: {STAMP}**\n",
             "Behavior metrics = full-window (202508-202605) lake wallet_coin_day/open_entries "
             "descriptors; `gapMed` = median same-coin inter-entry gap in minutes (re-trade "
             "cadence proxy, NOT true hold). $ figures assume $2,500 equal units. Costs: "
             "5.5bp (M) / 21.5bp (P) RT per trade/unit.\n"]
    for name, key in (("MAJORS-NATIVE K30 @8h (M)", "M"), ("PYRAMID-ALT ladder (P)", "P")):
        b = rep["books"][key]
        c = b["concentration"]
        lines.append(f"\n## {name}\n")
        lines.append(f"Book: {c['n_wallets']} wallets, {c['n_trades']:,} trades/units, net "
                     f"${c['total_net_usd']:+,.0f} ({c['book_net_bp_per_trade']:+.1f}bp/trade); "
                     f"wallet-level gross loss ${c['gross_wallet_loss_usd']:,.0f} / "
                     f"gross win ${c['gross_wallet_win_usd']:,.0f}.\n")
        lines.append(f"Loss share worst 1/3/5: {c['loss_share_worst_1']:.0%} / "
                     f"{c['loss_share_worst_3']:.0%} / {c['loss_share_worst_5']:.0%}. "
                     f"Win share best 1/3/5: {c['win_share_best_1']:.0%} / "
                     f"{c['win_share_best_3']:.0%} / {c['win_share_best_5']:.0%}.\n")
        wc = " ".join(f"{r['drop']}:{r['net_usd']:+,.0f}$({r['net_bp']:+.1f}bp)"
                      for r in c["drop_worst_k_expost"])
        bc = " ".join(f"{r['drop']}:{r['net_usd']:+,.0f}$({r['net_bp']:+.1f}bp)"
                      for r in c["drop_best_k_expost"])
        lines.append(f"\nDrop-worst-K (ex-post): {wc}\n\nDrop-best-K (ex-post): {bc}\n")
        d = b["distribution"]
        lines.append("\n| distribution | n | mean | p10 | p25 | med | p75 | p90 | skew | %>0 |\n"
                     "|---|---|---|---|---|---|---|---|---|---|")
        for dk, dv in d.items():
            if dv:
                lines.append(f"| {dk} | {dv['n']} | {dv['mean']} | {dv['p10']} | {dv['p25']} | "
                             f"{dv['median']} | {dv['p75']} | {dv['p90']} | {dv['skew']} | "
                             f"{dv['frac_positive']:.0%} |")
        lines.append("\n### All wallets (worst -> best by net $)\n")
        lines.append(md_wallet_table(b["per_wallet"]))
        lines.append("\n### Worst-5 vs best-5 medians (Mann-Whitney p, uncorrected)\n")
        lines.append("| metric | worst5 med | best5 med | MW p |\n|---|---|---|---|")
        for k, v in b["dragger_profile"].items():
            lines.append(f"| {k} | {v['worst5_median']} | {v['best5_median']} | {v['mw_p']} |")
        lines.append("")
    lines.append("\nArtifact: `data/derived/copy_cohort/wallet_attribution_report.json`.\n")
    OUT_MD.write_text("\n".join(lines))
    print(f"-> {OUT_MD}")


# ------------------------------------------------------------------ main
def run():
    print("[M] loading majors-native K30 trades ...", flush=True)
    mw, mf, mbp, mform = load_m_trades()
    musd = mbp * 1e-4 * UNIT_USD
    print(f"  M: {mw.size:,} trades, {np.unique(mw).size} wallets", flush=True)

    print("[P] re-simulating pyramid ladder from caches ...", flush=True)
    units, pform = load_p_units()
    pw = np.array([u["wallet"] for u in units])
    pf = np.array([u["fold"] for u in units])
    pusd = np.array([u["net"] for u in units])
    pbp = pusd / UNIT_USD * 1e4
    print(f"  P: {pw.size:,} units, {np.unique(pw).size} wallets, "
          f"net ${pusd.sum():,.0f}", flush=True)

    census = {}
    cj = json.loads(CENSUS.read_text())
    for r in cj["wallets"]:
        census[r["wallet"]] = r.get("archetype") or (
            cj["clusters"].get(str(r.get("cluster")), {}).get("label"))

    union = sorted(set(mw.tolist()) | set(pw.tolist()))
    print(f"[lake] behavior metrics for {len(union)} wallets ...", flush=True)
    behav = behavior_metrics(union)

    rep = {"label": "per-wallet attribution of frozen books M (majors K30@8h) and P (pyramid-alt)",
           "stamp": STAMP,
           "config": {"unit_usd": UNIT_USD, "cost_m_bp": COST_M_BP,
                      "cost_p_bp": pb.COST_RT_BP, "folds": FOLDS,
                      "behavior_window": [BEHAV_MONTHS[0], BEHAV_MONTHS[-1]],
                      "hold_proxy": "median same-coin inter-entry gap (open_entries), minutes",
                      "m_dollar_note": "M book is equal-weight; $ = net_bp * 1e-4 * $2,500"},
           "books": {"M": build_book("M", mw, mf, mbp, musd, mform, behav, census),
                     "P": build_book("P", pw, pf, pbp, pusd, pform, behav, census)}}
    OUT_JSON.write_text(json.dumps(rep, indent=1))
    print(f"-> {OUT_JSON}")
    write_md(rep)
    return rep


if __name__ == "__main__":
    run()
