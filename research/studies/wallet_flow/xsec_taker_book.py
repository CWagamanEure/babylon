"""
xsec_taker_book — realistic TAKER book backtest of the V-trail cross-sectional selection signal.

User steer (2026-07-10): "we're still missing something that makes this work with TAKER fills." Taker SIDESTEPS
the unresolved maker fill/adverse-selection gate — you cross a KNOWN cost and fill for certain. The decompose D5
declared taker-dead but (a) tested the worst cell (quintile @ h=2, smallest gross) and (b) used a NAIVE cost
model (full round-trip charged EVERY rebalance = 100% turnover). This script fixes both with a real held-book
simulator, and grounds the cost in HL's actual impact prices (measured: liquid-alt taker RT ≈ 9–10 bp, NOT the
5–6 bp hand-wave; a few names ZEC/XRP/DOGE/SUI are ≪ that).

Same leak-free panel + V-trail L2 h_train=4 signal as `xsec_flow_decompose.py`. Then:
  • per-alt taker cost = fee + impact-half-spread(from asset_ctx impact_bid/ask, median over clean window), per name.
  • held long/short book, rebalanced every REB h, with a NO-TRADE BAND (enter top-Q1, hold until out of top-Q2).
  • cost charged ONLY on name entries/exits (turnover), not the whole book each step → the persistence discount.
  • metric = net bp per HOUR (gross/hr − turnover cost/hr); day-block bootstrap CI; per-fold; CLEAN folds ≥202603.
  • naive-cost (full-RT-every-rebalance) net reported ALONGSIDE turnover-aware, so the discount is auditable.

DISCIPLINE (over-carry — forking minefield): PRE-REGISTERED primary = {V-trail, L2, h_train=4, REB=4, decile,
band 10%/15%, full universe, taker fee 2.4/side + measured per-alt impact spread}. Everything else = explicitly
labelled secondary looks. Report primary FIRST; per-fold sign test; no argmax promoted to headline.

Run: .venv/bin/python -m research.studies.wallet_flow.xsec_taker_book
"""
from __future__ import annotations
import time, json
from pathlib import Path
import numpy as np

from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

H_TRAIN = 4
CLEAN_MIN = 202603
TAKER_FEE_BP = 2.4          # per side, top volume tier (HL); also reported at 4.5 base in the ladder
OUT = Path("data/derived/xsec_taker_book")
DUCK_TMP = f"{A.SCRATCH}/duck_xs_taker"

# pre-registered PRIMARY config
PRIMARY = dict(reb=4, q1=0.10, q2=0.15, universe="full", regime="all", fee=TAKER_FEE_BP)


# ============================================================ held-book simulator ============================
def simulate(hours_list, xs_by_hour, fv_by_hour, cost_bp, reb, q1, q2, elig_by_hour=None):
    """Simulate an equal-weight long-short book with a no-trade band, over one fold's OOS hours.
    hours_list: sorted unique OOS hour indices in the fold.
    xs_by_hour[t] = (names, scores) arrays for the cross-section at hour t (names = alt-local ids).
    fv_by_hour[t] = dict name->forward-return VALUE (bp already ×1e4) over the NEXT `reb` hours (NaN if missing).
    cost_bp[name] = one-way taker cost (fee + half-spread) in bp for that name.
    elig_by_hour[t] = optional set of names eligible this hour (ADV/regime filter); None = all.
    Returns per-step arrays: step_hour, gross_bp, turnover_frac, tcost_bp (turnover-aware), tcost_naive_bp."""
    reb_hours = hours_list[::reb]
    held_long, held_short = set(), set()   # name sets
    out = {"hr": [], "gross": [], "turn": [], "tcost": [], "naive": []}
    for t in reb_hours:
        names, sc = xs_by_hour[t]
        if elig_by_hour is not None:
            keep = np.array([n in elig_by_hour[t] for n in names])
            names, sc = names[keep], sc[keep]
        n = len(names)
        if n < 4:    # too thin to form even a 1x1 book this step; carry held book, no trade, no return credited
            continue
        order = np.argsort(sc)                          # ascending
        k1 = max(1, int(round(q1 * n)))
        k2 = max(k1, int(round(q2 * n)))
        rank = {nm: i for i, nm in enumerate(names[order])}   # 0=lowest score .. n-1=highest
        top_entry = set(names[order[-k1:]]); top_hold = set(names[order[-k2:]])
        bot_entry = set(names[order[:k1]]);  bot_hold = set(names[order[:k2]])
        # LONG side: keep held names still in top_hold, fill to k1 from top_entry (best first)
        new_long = {nm for nm in held_long if nm in top_hold}
        for nm in names[order[::-1]]:                   # highest score first
            if len(new_long) >= k1: break
            if nm in top_entry and nm not in new_long: new_long.add(nm)
        new_short = {nm for nm in held_short if nm in bot_hold}
        for nm in names[order]:                         # lowest score first
            if len(new_short) >= k1: break
            if nm in bot_entry and nm not in new_short: new_short.add(nm)
        K = max(1, min(len(new_long), len(new_short)))  # equal-weight per side by realized book size
        # turnover cost (one-way, per traded name, weight 1/K): entries+exits vs held
        traded = (new_long ^ held_long) | (new_short ^ held_short)   # symmetric diff both sides = opens+closes
        tcost = sum(cost_bp.get(nm, cost_bp["_default"]) for nm in traded) / K
        # naive cost: charge a FULL round-trip on the entire book every rebalance (2K names, one-way each ×2 sides implicit)
        naive = (sum(cost_bp.get(nm, cost_bp["_default"]) for nm in (new_long | new_short)) / K) * 2.0
        # gross return over next reb hours = mean(long fwd) − mean(short fwd)
        lf = [fv_by_hour[t].get(nm, np.nan) for nm in new_long]
        sf = [fv_by_hour[t].get(nm, np.nan) for nm in new_short]
        lf = [x for x in lf if np.isfinite(x)]; sf = [x for x in sf if np.isfinite(x)]
        if not lf or not sf:
            held_long, held_short = new_long, new_short; continue
        gross = float(np.mean(lf) - np.mean(sf))
        out["hr"].append(int(t)); out["gross"].append(gross); out["turn"].append(len(traded) / (2 * K))
        out["tcost"].append(tcost); out["naive"].append(naive)
        held_long, held_short = new_long, new_short
    return {k: np.array(v, dtype=float) for k, v in out.items()}


def _dayblock_ci(vals, hrs, hours, reb, n=1000, seed=7):
    """Day-block bootstrap of the per-step net series (blocks by calendar day; block ≥ reb via day granularity)."""
    if len(vals) < 8: return (np.nan, np.nan)
    days = (hours[hrs] // 86400000).astype(np.int64); ud = np.unique(days)
    loc = {d: np.nonzero(days == d)[0] for d in ud}; rng = np.random.default_rng(seed); st = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        sel = np.concatenate([loc[ud[p]] for p in pick])
        st.append(vals[sel].mean())
    s = np.array(st); return (float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5)))


def book_stats(sim, hours, reb, fee_ladder, cost_scale=1.0):
    """From a sim result, net-per-HOUR under a fee ladder (turnover-aware) + naive; day-block CI on the primary fee."""
    if len(sim["hr"]) == 0: return None
    hrs = sim["hr"].astype(np.int64)
    gross_ph = sim["gross"] / reb                       # per-hour gross
    res = {"n_steps": int(len(hrs)), "gross_bp_per_hr": float(gross_ph.mean()),
           "mean_turnover": float(sim["turn"].mean()), "net": {}, "net_naive": {}}
    for lab, fee in fee_ladder.items():
        # cost arrays scale with fee: cost_bp[name] = fee + halfspread; sim used fee=base; re-scale the FEE part only
        # (tcost/naive were computed with the base fee embedded per name; here we recompute via cost_scale on the whole
        #  cost — acceptable since fee is the dominant, uniform term; exact per-fee recompute done in run() per config.)
        net_ph = (sim["gross"] - sim["tcost"] * cost_scale) / reb
        res["net"][lab] = float(net_ph.mean())
        res["net_naive"][lab] = float(((sim["gross"] - sim["naive"] * cost_scale) / reb).mean())
    # day-block CI on the turnover-aware net at the primary fee (cost_scale=1)
    net_primary = (sim["gross"] - sim["tcost"]) / reb
    res["net_ci95_primary"] = _dayblock_ci(net_primary, hrs, hours, reb)
    return res


def run():
    OUT.mkdir(parents=True, exist_ok=True); Path(DUCK_TMP).mkdir(parents=True, exist_ok=True)
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    _log(f"[1/6] universe: {len(alts)} alts")

    panel = A.build_resid(con, coins)
    resid, hours, ci = panel["resid"], panel["hours"], panel["ci"]
    panel_month = panel["month"]; N = panel["N"]; hmin = int(hours[0])
    alt_names = [c for c in coins if c not in A.FACTORS]
    alt_cols = [ci[c] for c in alt_names]; n_alt = len(alt_cols)
    col_to_ac = {ci[c]: k for k, c in enumerate(alt_names)}
    LAG_full = S0.trailing_resid_mom(resid); LAG_ac = LAG_full[:, alt_cols]
    _log(f"[2/6] resid ({N}h, {n_alt} alts)")

    # per-alt taker cost: impact half-spread (bp) median over clean window + fee (added per-config)
    inlist = "('" + "','".join(alt_names) + "')"
    hs_rows = con.execute(f"""SELECT coin, median((impact_ask_px-impact_bid_px)/nullif(mid_px,0)*1e4/2.0) hs
        FROM asset_ctx WHERE coin IN {inlist} AND month>={CLEAN_MIN}
          AND impact_ask_px>0 AND impact_bid_px>0 AND mid_px>0 GROUP BY coin""").fetchall()
    halfspread = {c: float(h) for c, h in hs_rows}
    hs_default = float(np.median([v for v in halfspread.values()]))
    # ADV for tiers
    import datetime as _dt
    fd0 = _dt.datetime.strptime(str(A.UNIV_FORMATION), "%Y%m%d").date()
    lo_d = int((fd0 - _dt.timedelta(days=30)).strftime("%Y%m%d")); hi_d = int(fd0.strftime("%Y%m%d"))
    adv_map = {c: float(a) for c, a in con.execute(f"""SELECT coin, avg(adv) FROM alt_adv
        WHERE day>={lo_d} AND day<{hi_d} AND coin IN {inlist} GROUP BY coin""").fetchall()}
    adv_vals = np.array([adv_map.get(nm, np.nan) for nm in alt_names]); fin = np.isfinite(adv_vals)
    t1, t2 = np.nanpercentile(adv_vals[fin], [33.3, 66.6])
    high_adv = {i for i in range(n_alt) if adv_vals[i] > t2}
    # "cheap" names: impact half-spread <= 1.5 bp (ZEC/XRP/DOGE/SUI... measured)
    cheap = {i for i, nm in enumerate(alt_names) if halfspread.get(nm, hs_default) <= 1.5}
    _log(f"[3/6] taker cost: half-spread median {hs_default:.2f}bp; {len(cheap)} cheap(≤1.5bp) names; {len(high_adv)} high-ADV")

    # controls + q_trail + signal (reuse decompose construction exactly)
    A.build_cohort_tables(con, coins)
    CROWD = np.full((N, n_alt), np.nan)
    ag = con.execute("SELECT coin, h, allflow FROM aagg WHERE coin NOT IN ('BTC','ETH')").fetchnumpy()
    ar = ((ag["h"].astype(np.int64) - hmin) // 3600000).astype(int); ok = (ar >= 0) & (ar < N)
    acx = np.array([col_to_ac.get(ci.get(str(c), -1), -1) for c in ag["coin"]])
    good = ok & (acx >= 0); CROWD[ar[good], acx[good]] = ag["allflow"].astype(float)[good]
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cid AS SELECT * FROM (VALUES
        {",".join(f"('{c}',{k})" for k, c in enumerate(alt_names))}) AS t(coin, ccode)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE wid AS SELECT wallet,(row_number() OVER (ORDER BY wallet))-1 AS wcode
        FROM (SELECT DISTINCT wallet FROM awb WHERE coin NOT IN ('BTC','ETH') AND flow<>0)""")
    rows = con.execute(f"""SELECT w.wcode, c.ccode, ((wb.h-{hmin})//3600000)::INT AS r, wb.mth,
               CASE WHEN wb.flow>0 THEN 1 WHEN wb.flow<0 THEN -1 ELSE 0 END AS s
        FROM awb wb JOIN wid w USING(wallet) JOIN cid c ON wb.coin=c.coin WHERE wb.flow<>0""").fetchnumpy()
    nW = int(con.execute("SELECT count(*) FROM wid").fetchone()[0])
    wcode = rows["wcode"].astype(np.int32); ccode = rows["ccode"].astype(np.int32)
    r = rows["r"].astype(np.int32); mth = rows["mth"].astype(np.int32); s = rows["s"].astype(np.int8)
    keep = (r >= 0) & (r < N); wcode, ccode, r, mth, s = wcode[keep], ccode[keep], r[keep], mth[keep], s[keep]
    del rows
    _q_sim, q_trail = ADJ.build_q_fixed(wcode, r, s.astype(np.float64), N)
    months = sorted(set(int(x) for x in np.unique(mth))); folds = months[4:]
    first_row = {"_ms": {}}
    for m in folds:
        rr = r[mth == m]; first_row[m] = int(rr.min()); first_row["_ms"][m] = int(hours[rr.min()])
    U4 = S0.xsec_rank(S0.fwd_sum(resid, H_TRAIN), alt_cols)[:, alt_cols]
    _log("[4/6] training V-trail signal ...")
    R, Cc, Uc, Smat = S0.run_horizon(H_TRAIN, wcode, ccode, r, mth, q_trail, U4, LAG_ac, nW, folds,
                                     first_row, (CROWD, LAG_ac, np.zeros((N, n_alt))), do_placebos=False, seed=S0.SEED)
    Smat = Smat.astype(np.float32)
    crowd = CROWD[R, Cc].copy(); lag = LAG_ac[R, Cc].copy()
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    s_inf = S0.residualize(Smat[:, :1], np.column_stack([crowd, lag]), R)[:, 0].astype(np.float64)
    _log(f"[5/6] signal ready: {len(R):,} cells")

    # regime (causal trailing dispersion) per hour → mid-tertile set of hours
    disp = np.nanstd(LAG_ac, axis=1); dcell = disp[R]; dfin = np.isfinite(dcell)
    dlo, dhi = np.nanpercentile(dcell[dfin], [33.3, 66.6])
    mid_hours = set(int(h) for h in np.unique(R[(dcell > dlo) & (dcell <= dhi)]))

    # precompute per-hour cross-sections (over ALL folds; fold/clean masking applied via step-hour month)
    xs_by_hour = {}; fv_by_hour = {}
    fin_s = np.isfinite(s_inf)
    for i in range(len(R)):
        if not fin_s[i]: continue
        t = int(R[i]); nm = int(Cc[i])
        xs_by_hour.setdefault(t, ([], [])); xs_by_hour[t][0].append(nm); xs_by_hour[t][1].append(s_inf[i])
    # forward VALUE at horizon = reb is config-specific; build lazily per reb below
    hour_month = {int(t): int(panel_month[t]) for t in xs_by_hour}
    all_hours = np.array(sorted(xs_by_hour), dtype=np.int64)
    xs_arr = {t: (np.array(v[0]), np.array(v[1])) for t, v in xs_by_hour.items()}

    def fv_for(reb):
        FVr = S0.fwd_sum(resid, reb)[:, alt_cols]     # (N, n_alt) bp-scaled after ×1e4? fwd_sum is log-ret; ×1e4 below
        d = {}
        for t in xs_arr:
            names = xs_arr[t][0]
            d[t] = {int(nm): float(FVr[t, nm]) * 1e4 for nm in names}
        return d

    fee_ladder = {"fee2.4": 2.4, "fee4.5": 4.5}
    def cost_map(fee):
        c = {i: fee + halfspread.get(alt_names[i], hs_default) for i in range(n_alt)}
        c["_default"] = fee + hs_default
        # keyed by alt-local id used in sim (names are alt-local ints)
        return {**{k: v for k, v in c.items() if k != "_default"}, "_default": c["_default"]}

    def eval_config(name, reb, q1, q2, fee, universe="full", regime="all", clean_only=True):
        elig_names = None
        if universe == "high_adv": base = high_adv
        elif universe == "cheap": base = cheap
        else: base = set(range(n_alt))
        # per-hour eligible set (regime + universe); clean fold restriction handled by filtering step hours
        def hour_elig(t):
            if regime == "mid" and t not in mid_hours: return set()
            return base
        elig_by_hour = {t: hour_elig(t) for t in xs_arr}
        # restrict simulated hours to clean folds if requested
        hrs = np.array([t for t in all_hours if (hour_month[int(t)] >= CLEAN_MIN or not clean_only)], dtype=np.int64)
        fvb = fv_for(reb)
        cmap = cost_map(fee)
        sim = simulate(hrs, xs_arr, fvb, cmap, reb, q1, q2, elig_by_hour=elig_by_hour)
        st = book_stats(sim, hours, reb, {f"fee{fee}": fee})
        if st is None: return None
        # per-fold net (turnover-aware, this fee)
        pf = {}
        if len(sim["hr"]):
            shm = np.array([hour_month[int(t)] for t in sim["hr"]])
            netph = (sim["gross"] - sim["tcost"]) / reb
            for m in sorted(set(shm.tolist())): pf[int(m)] = float(netph[shm == m].mean())
        return {"config": dict(reb=reb, q1=q1, q2=q2, fee=fee, universe=universe, regime=regime, clean_only=clean_only),
                "stats": st, "per_fold_net": pf}

    print("\n================= TAKER BOOK — PRE-REGISTERED PRIMARY =================")
    res = {"impact_halfspread_median_bp": hs_default, "cheap_names": [alt_names[i] for i in sorted(cheap)],
           "taker_fee_side_bp": TAKER_FEE_BP, "primary": {}, "secondary": {}}
    prim = eval_config("primary", reb=4, q1=0.10, q2=0.15, fee=2.4, universe="full", regime="all")
    res["primary"] = prim
    def _show(tag, e):
        if e is None: print(f"  {tag:34s}  (too thin)"); return
        st = e["stats"]; ci = st["net_ci95_primary"]; fk = list(st["net"])[0]
        pf = e["per_fold_net"]; npos = sum(1 for v in pf.values() if v > 0)
        print(f"  {tag:34s} gross {st['gross_bp_per_hr']:+.3f}/hr  turn {st['mean_turnover']:.2f}  "
              f"NET {st['net'][fk]:+.3f}/hr CI[{ci[0]:+.3f},{ci[1]:+.3f}]  naive {st['net_naive'][fk]:+.3f}  "
              f"folds {npos}/{len(pf)}+")
    _show("PRIMARY decile/REB4/full/fee2.4", prim)

    print("\n================= SECONDARY LOOKS (labelled; not the headline) =================")
    sec = {}
    grid = [
        ("cheap-names decile REB4", dict(reb=4, q1=0.10, q2=0.15, fee=2.4, universe="cheap", regime="all")),
        ("high-ADV decile REB4",    dict(reb=4, q1=0.10, q2=0.15, fee=2.4, universe="high_adv", regime="all")),
        ("mid-regime quintile REB4",dict(reb=4, q1=0.20, q2=0.30, fee=2.4, universe="full", regime="mid")),
        ("mid-regime decile REB4",  dict(reb=4, q1=0.10, q2=0.15, fee=2.4, universe="full", regime="mid")),
        ("decile REB8 (slow)",      dict(reb=8, q1=0.10, q2=0.15, fee=2.4, universe="full", regime="all")),
        ("decile REB8 wide-band",   dict(reb=8, q1=0.10, q2=0.25, fee=2.4, universe="full", regime="all")),
        ("cheap+mid decile REB4",   dict(reb=4, q1=0.10, q2=0.15, fee=2.4, universe="cheap", regime="mid")),
        ("quintile REB4 full",      dict(reb=4, q1=0.20, q2=0.30, fee=2.4, universe="full", regime="all")),
        ("PRIMARY @ fee4.5",        dict(reb=4, q1=0.10, q2=0.15, fee=4.5, universe="full", regime="all")),
    ]
    for tag, cfg in grid:
        e = eval_config(tag, **cfg); sec[tag] = e; _show(tag, e)
    res["secondary"] = sec

    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    _log("[6/6] wrote results.json")
    print("\nDONE.")


if __name__ == "__main__":
    run()
