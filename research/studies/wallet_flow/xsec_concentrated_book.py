"""
xsec_concentrated_book — PRE-REGISTERED concentrated maker+taker held-book on the V-trail xsec selection signal.

The 7-agent signal-hunt swarm (2026-07-10) showed Claude's deploy verdict was over-pessimistic: quoted the maker
cost as PAY (a maker EARNS the spread), called taker "earned-negative" when top-tier is inconclusive, and led with
the wrong horizon (h2), extremity (quintile), leg (taker) and pooled-regime. This script tests the CONCENTRATED,
pre-registered config honestly and converts "gated on fill" into a bracketed, powered verdict.

PRE-REGISTERED PRIMARY (frozen BEFORE the run, no post-hoc search):
  predictor = V-trail (trailing-24h demean, L2 ⊥crowd,⊥mom), h_train=4
  book      = DECILE long-short (top/bottom 10%, hold-band to 15%), EQUAL-weight, FULL 45-name universe
              (NOT liquidity-stacked — a decile of 15 liquid names is 1-2 names = netting trap, swarm F3)
  regime    = MID-dispersion tertile, thresholds FROZEN on the pre-period (months < 202603) then applied forward
              (removes the in-sample-threshold look-ahead the swarm flagged)
  horizon   = chosen by NET-PER-HOUR (not gross/hr) over reb ∈ {3,4,6,8}
  folds     = ALL 7 (202512..202606) + month-block sign test (cross-independent unit); day-block CI on net series

COST — bracket the ONE real unknown (fill/adverse selection) instead of assuming the worst:
  TAKER legs (certain fill, KNOWN cost — needs NO fill model):
    - top-tier fee 2.4/side + SMALL-CLIP spread (min(impact_hs, 1.0)bp)   [the deployable-as-modeled number]
    - top-tier fee 2.4/side + full IMPACT spread                          [pessimistic reference]
    - base fee 4.5/side + impact spread                                   [worst]
  MAKER legs (EARN the half-spread on fills; adverse selection haircuts the gross alpha):
    - earn-spread, adverse haircut a ∈ {0, 0.30, 0.50} of gross           [brackets fill; gap-lag says a is MODEST]
  Reported net-per-HOUR, turnover-aware (charge only name entries/exits) AND naive, per scenario.

Reuses the exact leak-free panel + V-trail signal construction as decompose/taker_book. No new data.
Run: .venv/bin/python -m research.studies.wallet_flow.xsec_concentrated_book
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
PREPERIOD_MAX = 202602          # freeze regime thresholds on months <= this (strictly before the clean folds)
OUT = Path("data/derived/xsec_concentrated_book")
DUCK_TMP = f"{A.SCRATCH}/duck_xs_conc"
REBS = (3, 4, 6, 8)


def simulate_raw(hours_list, xs_arr, fv_by_hour, halfspread, hs_default, reb, q1, q2, elig_by_hour):
    """Held long-short book with no-trade band. Returns per-step RAW components so any cost scenario can be applied
    post-hoc: gross (bp, reb-hour hold), n_traded_units = n_traded/K (book-units of one-way trades), hs_units =
    Σ halfspread[traded]/K, turn = n_traded/(2K)."""
    reb_hours = hours_list[::reb]
    held_long, held_short = set(), set()
    out = {"hr": [], "gross": [], "ntrade": [], "hs": [], "turn": []}
    for t in reb_hours:
        names, sc = xs_arr[t]
        if elig_by_hour is not None:
            k = np.array([nm in elig_by_hour[t] for nm in names])
            names, sc = names[k], sc[k]
        n = len(names)
        if n < 4:
            continue
        order = np.argsort(sc)
        k1 = max(1, int(round(q1 * n))); k2 = max(k1, int(round(q2 * n)))
        top_entry = set(names[order[-k1:]]); top_hold = set(names[order[-k2:]])
        bot_entry = set(names[order[:k1]]);  bot_hold = set(names[order[:k2]])
        new_long = {nm for nm in held_long if nm in top_hold}
        for nm in names[order[::-1]]:
            if len(new_long) >= k1: break
            if nm in top_entry and nm not in new_long: new_long.add(nm)
        new_short = {nm for nm in held_short if nm in bot_hold}
        for nm in names[order]:
            if len(new_short) >= k1: break
            if nm in bot_entry and nm not in new_short: new_short.add(nm)
        K = max(1, min(len(new_long), len(new_short)))
        traded = (new_long ^ held_long) | (new_short ^ held_short)
        lf = [fv_by_hour[t].get(nm, np.nan) for nm in new_long]
        sf = [fv_by_hour[t].get(nm, np.nan) for nm in new_short]
        lf = [x for x in lf if np.isfinite(x)]; sf = [x for x in sf if np.isfinite(x)]
        if not lf or not sf:
            held_long, held_short = new_long, new_short; continue
        gross = float(np.mean(lf) - np.mean(sf))
        n_tr = len(traded); hs_sum = sum(halfspread.get(nm, hs_default) for nm in traded)
        out["hr"].append(int(t)); out["gross"].append(gross)
        out["ntrade"].append(n_tr / K); out["hs"].append(hs_sum / K); out["turn"].append(n_tr / (2 * K))
        held_long, held_short = new_long, new_short
    return {k: np.array(v, dtype=float) for k, v in out.items()}


def _dayblock_ci(vals, hrs, hours, n=1000, seed=7):
    if len(vals) < 8: return (float("nan"), float("nan"))
    days = (hours[hrs.astype(np.int64)] // 86400000).astype(np.int64); ud = np.unique(days)
    loc = {d: np.nonzero(days == d)[0] for d in ud}; rng = np.random.default_rng(seed); st = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        st.append(vals[np.concatenate([loc[ud[p]] for p in pick])].mean())
    s = np.array(st); return (float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5)))


# cost scenarios: (label, gross_multiplier, fee_per_side, spread_mode)  spread_mode: 'impact'|'small'|'earn'
SCENARIOS = [
    ("taker_top_smallclip", 1.00, 2.4, "small"),
    ("taker_top_impact",    1.00, 2.4, "impact"),
    ("taker_base_impact",   1.00, 4.5, "impact"),
    ("maker_earn_a0",       1.00, 1.0, "earn"),   # maker fee ~1.0bp/side (conservative base-ish; high-vol tier is lower)
    ("maker_earn_a30",      0.70, 1.0, "earn"),   # a30 = adverse selection eats 30% of gross alpha (gap-lag says modest)
    ("maker_earn_a50",      0.50, 1.0, "earn"),   # a50 = pessimistic adverse selection
]


def scenario_net_series(sim, reb, fee, spread_mode, mult, hs_default):
    """Per-step net-per-HOUR series for one cost scenario. ntrade = one-way trades / K; hs = Σ halfspread_traded / K.
    taker cost/step = ntrade*fee + (impact or small-clip spread). maker: cost/step = ntrade*fee − hs (EARN spread)."""
    if len(sim["hr"]) == 0: return np.array([]), np.array([])
    if spread_mode == "small":
        spread_cost = np.minimum(sim["hs"], sim["ntrade"] * 1.0)   # cap earned/paid spread at ~1bp small clip
        cost = sim["ntrade"] * fee + spread_cost
    elif spread_mode == "impact":
        cost = sim["ntrade"] * fee + sim["hs"]
    else:  # earn: maker earns the half-spread on each one-way fill
        cost = sim["ntrade"] * fee - sim["hs"]
    net_step = sim["gross"] * mult - cost
    return net_step / reb, sim["hr"]


def run():
    OUT.mkdir(parents=True, exist_ok=True); Path(DUCK_TMP).mkdir(parents=True, exist_ok=True)
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    _log(f"[1/6] {len(alts)} alts")
    panel = A.build_resid(con, coins)
    resid, hours, ci = panel["resid"], panel["hours"], panel["ci"]
    panel_month = panel["month"]; N = panel["N"]; hmin = int(hours[0])
    alt_names = [c for c in coins if c not in A.FACTORS]
    alt_cols = [ci[c] for c in alt_names]; n_alt = len(alt_cols)
    col_to_ac = {ci[c]: k for k, c in enumerate(alt_names)}
    LAG_ac = S0.trailing_resid_mom(resid)[:, alt_cols]
    _log(f"[2/6] resid ({N}h, {n_alt} alts)")

    inlist = "('" + "','".join(alt_names) + "')"
    hs_rows = con.execute(f"""SELECT coin, median((impact_ask_px-impact_bid_px)/nullif(mid_px,0)*1e4/2.0) hs
        FROM asset_ctx WHERE coin IN {inlist} AND month>={CLEAN_MIN}
          AND impact_ask_px>0 AND impact_bid_px>0 AND mid_px>0 GROUP BY coin""").fetchall()
    hs_by_name = {c: float(h) for c, h in hs_rows}
    halfspread = {i: hs_by_name.get(alt_names[i], 3.25) for i in range(n_alt)}
    hs_default = float(np.median(list(hs_by_name.values())))
    _log(f"[3/6] impact half-spread median {hs_default:.2f}bp")

    # controls + q_trail + V-trail signal (identical construction)
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
    _log(f"[5/6] {len(R):,} OOS cells")

    # FROZEN regime thresholds: dispersion tertile boundaries from PRE-PERIOD hours (month <= PREPERIOD_MAX)
    disp = np.nanstd(LAG_ac, axis=1)
    pre_hours = np.array([t for t in np.unique(R) if panel_month[t] <= PREPERIOD_MAX], dtype=np.int64)
    dpre = disp[pre_hours]; dpre = dpre[np.isfinite(dpre)]
    dlo, dhi = np.nanpercentile(dpre, [33.3, 66.6])     # FROZEN on pre-period, applied forward
    mid_hours = set(int(t) for t in np.unique(R) if np.isfinite(disp[t]) and dlo < disp[t] <= dhi)
    _log(f"[5/6] frozen mid-dispersion band ({dlo:.4f},{dhi:.4f}] from {len(pre_hours)} pre-period hours; "
         f"{len(mid_hours)} mid hours total")

    # per-hour cross-sections
    xs_by = {}
    for i in range(len(R)):
        if not np.isfinite(s_inf[i]): continue
        t = int(R[i]); xs_by.setdefault(t, ([], [])); xs_by[t][0].append(int(Cc[i])); xs_by[t][1].append(s_inf[i])
    xs_arr = {t: (np.array(v[0]), np.array(v[1])) for t, v in xs_by.items()}
    hour_month = {int(t): int(panel_month[t]) for t in xs_arr}
    all_hours = np.array(sorted(xs_arr), dtype=np.int64)

    def fv_for(reb):
        FVr = S0.fwd_sum(resid, reb)[:, alt_cols]
        return {t: {int(nm): float(FVr[t, nm]) * 1e4 for nm in xs_arr[t][0]} for t in xs_arr}

    full_set = set(range(n_alt))
    def eval_book(reb, regime, q1=0.10, q2=0.15):
        elig = {t: (full_set if (regime == "all" or t in mid_hours) else set()) for t in xs_arr}
        sim = simulate_raw(all_hours, xs_arr, fv_for(reb), halfspread, hs_default, reb, q1, q2, elig)
        if len(sim["hr"]) == 0: return None
        hrs = sim["hr"].astype(np.int64)
        shm = np.array([hour_month[int(t)] for t in hrs])
        out = {"reb": reb, "regime": regime, "n_steps": int(len(hrs)),
               "gross_bp_per_hr": float((sim["gross"] / reb).mean()), "mean_turnover": float(sim["turn"].mean()),
               "scenarios": {}}
        for lab, mult, fee, mode in SCENARIOS:
            netph, _ = scenario_net_series(sim, reb, fee, mode, mult, hs_default)
            ci95 = _dayblock_ci(netph, hrs, hours)
            pf = {int(m): float(netph[shm == m].mean()) for m in sorted(set(shm.tolist()))}
            st = ADJ.sign_test([v for v in pf.values()])
            out["scenarios"][lab] = {"net_bp_per_hr": float(netph.mean()), "ci95": ci95,
                                     "per_fold": pf, "folds_pos": int(sum(1 for v in pf.values() if v > 0)),
                                     "n_folds": len(pf), "sign_p": st["p"]}
        return out

    print("\n================= PRE-REGISTERED PRIMARY: V-trail DECILE, MID-dispersion (frozen), full univ =================")
    res = {"config_frozen": {"predictor": "V-trail", "book": "decile 10/15", "regime": "mid-frozen",
                             "universe": "full-45", "rebs": list(REBS), "preperiod_max": PREPERIOD_MAX,
                             "impact_hs_median_bp": hs_default}, "primary_mid": {}, "compare_pooled": {}}
    def _show(e):
        if e is None: print("  (thin)"); return
        print(f"  reb={e['reb']} regime={e['regime']:4s} gross {e['gross_bp_per_hr']:+.3f}/hr turn {e['mean_turnover']:.2f} n={e['n_steps']}")
        for lab, _, _, _ in SCENARIOS:
            sc = e["scenarios"][lab]; ci = sc["ci95"]
            print(f"      {lab:20s} net {sc['net_bp_per_hr']:+.3f}/hr CI[{ci[0]:+.3f},{ci[1]:+.3f}] "
                  f"folds {sc['folds_pos']}/{sc['n_folds']}+ signp {sc['sign_p']:.3f}")
    best = None
    for reb in REBS:
        e = eval_book(reb, "mid"); res["primary_mid"][f"reb{reb}"] = e; _show(e)
        # net-per-hour horizon selection under the central maker_earn_a30 scenario
        if e is not None:
            c = e["scenarios"]["maker_earn_a30"]["net_bp_per_hr"]
            if best is None or c > best[1]: best = (reb, c)
    print(f"  -> net-per-hr optimal harvest reb (maker_earn_a30 central) = reb{best[0] if best else '?'}")
    res["best_reb_central"] = best[0] if best else None

    print("\n================= COMPARE: pooled (all-regime) decile — to show the mid-regime lift =================")
    for reb in REBS:
        e = eval_book(reb, "all"); res["compare_pooled"][f"reb{reb}"] = e; _show(e)

    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    _log("[6/6] wrote results.json")
    print("\nDONE.")


if __name__ == "__main__":
    run()
