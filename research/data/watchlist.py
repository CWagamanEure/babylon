"""Monthly WATCHLIST compiler — annotation layer on the frozen basket (docs/WALLET_WATCHLIST_PLAN.md).

Membership = live_basket.parquet verbatim (selector mining closed; zero new selection). This script only
ANNOTATES and TIERS by the evidence-synthesis findings (2026-07-10, 360-slot forward dataset):
  - activity/recency = the strongest predictors in the repo (recency<=4d -> 0.99 next-month trade hazard;
    days30>=15 -> 0.91) -> Tier A gate
  - 1h-horizon tilt (+11.2 +/- 5.3bp forward, the only cohort clearing 10.5bp costs)
  - disc_gross allowed ONLY as a capped tie-break (r~+0.10; NON-monotonic - 60-100bp bin goes negative)
  - NO recurrence bonus (clean prior-windows number: repeats -16bp vs first-timers +6 - the +43bp was
    look-ahead); NO consensus bonus (2-source slots -7.5bp) - both kept as informational labels
  - star tier: 0xd7dc4b...14cb5 (11-month positive record + independent protocol confirmation + own PnL);
    0x42bbf95f...bccc0 elevated-with-caveat (6/6 positive but post-hoc-selected)
Also scores LAST month's list from the tape (wallet-day means at frozen horizon) and appends the scorecard.

    python -m research.data.watchlist            # compile this month's report + score last month
"""
from __future__ import annotations
import datetime
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from .markout import HORIZONS, REPO_ROOT
from .family_wf import _con, _fcol, _groups
from .features_markout import ENTRY_LAG_MAX_S

TAPE_END = "2026-06-29"          # advance with each refresh
STAR = {"0xd7dc4b4ad3a7840f042a46d24b897fbe6ad14cb5"}                  # independent confirmation
ELEVATED = {"0x42bbf95f8760d811bf7035df5f631a1b535bccc0"}              # post-hoc record (caveat)
DAY = 86_400_000
OUT = REPO_ROOT / "data" / "derived" / "watchlist"
DOCS = REPO_ROOT / "docs"


def _activity(con, pairs, end_ts):
    """(wallet,coin) -> (days30, recency_days) from the episode lake, trailing from end_ts."""
    ep = str(REPO_ROOT / "data/derived/episodes/month=*/episodes.parquet")
    con.execute("CREATE OR REPLACE TEMP TABLE wl(wallet VARCHAR, coin VARCHAR)")
    con.executemany("INSERT INTO wl VALUES (?, ?)", sorted(pairs))
    rows = con.execute(f"""SELECT e.wallet, e.coin,
        count(DISTINCT CASE WHEN e.open_ts >= {end_ts} - 30::BIGINT*{DAY} THEN e.open_ts // {DAY} END),
        ({end_ts} - max(e.open_ts)) / {DAY}.0
      FROM read_parquet('{ep}', hive_partitioning=true) e JOIN wl USING(wallet, coin)
      GROUP BY e.wallet, e.coin""").fetchall()
    return {(w, c): (int(d30), float(rec)) for (w, c, d30, rec) in rows}


def _tape_month_score(con, rows, lo, hi):
    """Score a prior list on the tape: wallet-day mean gross at the frozen horizon over [lo,hi)."""
    out = {}
    bycoin = {}
    for r in rows:
        bycoin.setdefault(r["coin"], []).append(r)
    for coin, rs in bycoin.items():
        mk = str(REPO_ROOT / f"data/derived/episodes_markout/coin={coin}/part-b*.parquet")
        con.execute("CREATE OR REPLACE TEMP TABLE wl(wallet VARCHAR)")
        con.executemany("INSERT INTO wl VALUES (?)", [(r["wallet"],) for r in rs])
        g = ", ".join(f"m.raw_markout_{h} AS g_{h}" for h in {r["horizon"] for r in rs})
        e = con.execute(f"""SELECT m.wallet, m.entry_bar_ts//{DAY} AS day, {g}
          FROM read_parquet('{mk}') m JOIN wl USING(wallet)
          WHERE m.entry_bar_ts>={lo} AND m.entry_bar_ts<{hi}
            AND NOT m.entry_after_close AND m.entry_lag_s<={ENTRY_LAG_MAX_S}""").fetchnumpy()
        wal = np.asarray(e["wallet"], dtype=object)
        if len(wal) == 0:
            continue
        order, uq, bounds = _groups(e)
        day = np.asarray(e["day"])[order]
        hz = {r["wallet"]: r["horizon"] for r in rs}
        for gi in range(len(uq)):
            s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]
            v = _fcol(e, f"g_{hz[w]}")[order][s:ez]; d = day[s:ez]
            m = ~np.isnan(v)
            if not m.any():
                continue
            vv, dd = v[m], d[m]
            dm = [float(vv[dd == k].mean()) for k in np.unique(dd)]
            out[(w, coin)] = {"gross": float(np.mean(dm)), "n_ep": int(m.sum()), "n_days": len(dm)}
    return out


def compile_month():
    con = _con()
    end_ts = con.execute(f"SELECT epoch_ms(TIMESTAMP '{TAPE_END}')").fetchone()[0]
    basket = pq.read_table(REPO_ROOT / "data/derived/rolling_wf/live_basket.parquet").to_pylist()
    act = _activity(con, [(r["wallet"], r["coin"]) for r in basket], end_ts)
    # persistence consensus label (informational only)
    from .persistence_wf import score_window
    lo_d = (datetime.datetime.strptime(TAPE_END, "%Y-%m-%d") - datetime.timedelta(days=180)).strftime("%Y-%m-%d")
    ps, _fam = score_window(con, lo_d, TAPE_END)
    ps_rank = {(c["wallet"], c["coin"]): i + 1 for i, c in enumerate(ps)}

    rows = []
    for r in basket:
        k = (r["wallet"], r["coin"])
        d30, rec = act.get(k, (0, 999.0))
        is_1h = r["horizon"] == "1h"
        tier = "STAR" if r["wallet"] in STAR else ("A" if (d30 >= 15 and rec <= 4) else "B")
        S = 3 * (d30 >= 15) + 2 * (rec <= 4) + 2 * is_1h + min(r["disc_gross_bp"], 60) / 60.0
        rows.append({**r, "days30": d30, "recency_d": round(rec, 1), "tier": tier,
                     "S": round(float(S), 2), "is_1h": is_1h, "hype": r["coin"] == "HYPE",
                     "ps_consensus_rank": ps_rank.get(k),
                     "elevated": r["wallet"] in ELEVATED})
    rows.sort(key=lambda r: ({"STAR": 0, "A": 1, "B": 2}[r["tier"]], -r["S"], r["rank"]))
    OUT.mkdir(parents=True, exist_ok=True)
    month = TAPE_END[:7]
    pq.write_table(pa.Table.from_pylist(rows), OUT / f"watchlist_{month}.parquet")

    # steady bench = persistence top-20 not on the copy list
    inb = {(r["wallet"], r["coin"]) for r in basket}
    bench = [c for c in ps if (c["wallet"], c["coin"]) not in inb][:20]

    doc = [f"# WALLET WATCHLIST — {month}",
           "",
           "These are the 20 wallet-coin pairs our frozen monthly selection process currently ranks most",
           "likely to keep beating copy costs, tiered by activity durability and the horizon cohort that",
           "clears realistic costs. We paper-trade this exact list live and re-score every name against what",
           "actually happened at each monthly refresh.",
           "",
           "**Rules:** copy ENTRIES only, exit on the row's frozen-horizon clock; 1–2 min delay is free;",
           "a wallet's discovery bp is NOT its forecast (above the bar, bigger = more inflated); HYPE rows:",
           "halve trust; refresh monthly — the refresh IS the strategy.",
           "",
           "**Expectations (measured forward, not discovery):** average active slot ≈ +4 bp gross/day;",
           "the 1h cohort ≈ +11 bp (the only tier clearing ~10.5 bp realistic costs); the day-weighted",
           "portfolio cleared costs in 4/5 historical forward months. ~80% of names will trade next month;",
           "Tier A ≈ 91–99%.",
           "",
           "## COPY LIST (frozen basket, annotated)",
           "",
           "| tier | wallet | coin@hz | S | days30 | recency | labels |"]
    doc.append("|---|---|---|---|---|---|---|")
    for r in rows:
        lab = []
        if r["wallet"] in STAR:
            lab.append("★ 11-mo positive record + protocol-confirmed")
        if r["elevated"]:
            lab.append("elevated (post-hoc record)")
        if r["is_1h"]:
            lab.append("1h-cohort")
        if r["hype"]:
            lab.append("HYPE-discount")
        if r["ps_consensus_rank"]:
            lab.append(f"consensus (pers #{r['ps_consensus_rank']})")
        doc.append(f"| {r['tier']} | `{r['wallet']}` | {r['coin']}@{r['horizon']} | {r['S']} | "
                   f"{r['days30']} | {r['recency_d']}d | {'; '.join(lab) or '—'} |")
    doc += ["", "## STEADY BENCH (pipeline, not PnL — highest survival odds, edge below cost)", ""]
    for c in bench[:12]:
        doc.append(f"- `{c['wallet']}` {c['coin']} score={c['score']:.3f} gross6={c['sg_gross6']:+.1f}bp")
    if "0x42bbf95f8760d811bf7035df5f631a1b535bccc0" not in {r["wallet"] for r in rows}:
        doc += ["", "**Elevated watch (not in basket):** `0x42bbf95f8760d811bf7035df5f631a1b535bccc0` BTC —",
                "6/6 positive forward slot-months (post-hoc-selected record; watch, size skeptically)."]
    doc += ["", "> Footnote: the process behind this list is a favorable-direction, not-yet-established",
            "> positive; the live paper scoreboard is the instrument that settles it",
            "> (docs/FORWARD_PAPER_PREREG.md)."]
    (DOCS / f"WALLET_WATCHLIST_{month}.md").write_text("\n".join(doc))
    print(f"compiled {len(rows)} copy rows + {len(bench)} bench -> docs/WALLET_WATCHLIST_{month}.md")
    for r in rows[:8]:
        print(f"  {r['tier']:4s} {r['wallet'][:14]}… {r['coin']}@{r['horizon']} S={r['S']} "
              f"d30={r['days30']} rec={r['recency_d']}d")


if __name__ == "__main__":
    compile_month()
