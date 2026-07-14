"""
kalman_swarm_prosecutor_null — PROSECUTOR agent for the xsec-kalman signal-hunt swarm.

Job: rigorously test whether Result 11's negative ("smoothing doesn't help; the no-smoothing baseline is the
maximum") is CORRECT, and null the lone marginal flip (mid, alpha0.6, stale>=4: taker_top_smallclip
CI->[+0.1,+5.5], 6/7). Argue the benign-noise explanation. Explicit about the OVER-CARRY gate.

Reuses the frozen cache + CB.simulate_raw / CB.scenario_net_series EXACTLY (does not touch the frozen files).

Sections:
  (0) Reproduce baseline (alpha=1,stale=0) -> must match compare_pooled reb4 (taker_smallclip +1.42, maker_a30 +4.35).
  (1) Full alpha x stale sweep, net-vs-alpha curve per FOCUS scenario, pooled + mid. Monotone-worse test.
  (2) The lone flip: point estimate vs baseline (unchanged?), per-fold, and a multiple-comparisons tally over
      the whole grid (how many CI-excludes-0 flips expected by chance; is this one inside that expectation).
      Also: is the "6/7 across stale>=4" three independent confirmations or ONE inert-duplicated cell?
  (3) Non-independence: month-block (fold) bootstrap + weekly moving-block bootstrap vs the day-block CI for
      the flip cell -> does the marginal flip survive a stricter, autocorr/pool-aware resample?
  (4) Mechanism: dGross/dalpha vs dTurnover/dalpha at alpha=1 (the derivative). Break-even: gross lost per unit
      turnover saved vs cost saved per unit turnover -> is ANY turnover-for-gross trade net-positive, or is it
      unfavorable from alpha=1?

    .venv/bin/python -m research.studies.wallet_flow.kalman_swarm_prosecutor_null
"""
from __future__ import annotations
import time
import numpy as np

from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_kalman as KAL

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

REB = KAL.REB
ALPHAS = KAL.ALPHAS
STALES = KAL.STALES
FOCUS = KAL.FOCUS


def load():
    d = np.load(KAL.CACHE, allow_pickle=False)
    R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
    hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}

    SIG = np.full((N, n_alt), np.nan)
    obs_hours = set()
    for i in range(len(R)):
        if np.isfinite(s_inf[i]):
            SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs_hours.add(int(R[i]))
    base_hours = np.array(sorted(obs_hours), dtype=np.int64)
    reb_grid = base_hours[::REB]
    hour_month = {int(t): int(panel_month[int(t)]) for t in reb_grid}
    FVr = S0.fwd_sum(resid_alt, REB)

    dfin = disp[np.isfinite(disp)]
    dlo, dhi = np.nanpercentile(dfin, [33.3, 66.6])
    mid_ok = {int(t): (dlo < disp[int(t)] <= dhi) for t in reb_grid}
    return dict(SIG=SIG, reb_grid=reb_grid, hour_month=hour_month, FVr=FVr, halfspread=halfspread,
                hs_default=hs_default, n_alt=n_alt, hours=hours, mid_ok=mid_ok)


def eval_cell(D, alpha, stale, regime, want_series=None):
    """Replicate xsec_kalman.eval_cell EXACTLY. If want_series is a scenario label, also return the per-step net
    series + hrs for that scenario (for stricter bootstraps)."""
    SIG = D["SIG"]; reb_grid = D["reb_grid"]; hour_month = D["hour_month"]; FVr = D["FVr"]
    halfspread = D["halfspread"]; hs_default = D["hs_default"]; n_alt = D["n_alt"]; hours = D["hours"]
    mid_ok = D["mid_ok"]; full_set = set(range(n_alt))

    m = KAL.ema_smooth(SIG, alpha, stale) if (stale > 0 or alpha < 1.0) else SIG
    xs_arr, fvb, elig = {}, {}, {}
    for t in reb_grid:
        ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4: continue
        xs_arr[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
        elig[ti] = full_set if (regime == "all" or mid_ok[ti]) else set()
    keys = np.array(sorted(xs_arr), dtype=np.int64)
    if len(keys) < 8: return None
    sim = CB.simulate_raw(keys, xs_arr, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
    if len(sim["hr"]) < 8: return None
    hrs = sim["hr"].astype(np.int64); shm = np.array([hour_month[int(t)] for t in hrs])
    cell = {"alpha": alpha, "stale": stale, "regime": regime, "n_steps": int(len(hrs)),
            "gross_bp_per_hr": float((sim["gross"] / REB).mean()), "mean_turnover": float(sim["turn"].mean()),
            "scenarios": {}}
    series = None
    for lab, mult, fee, mode in CB.SCENARIOS:
        netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, hs_default)
        ci95 = CB._dayblock_ci(netph, hrs, hours)
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        st = ADJ.sign_test([v for v in pf.values()])
        cell["scenarios"][lab] = {"net": float(netph.mean()), "ci95": ci95,
                                  "folds_pos": int(sum(1 for v in pf.values() if v > 0)),
                                  "n_folds": len(pf), "sign_p": st["p"],
                                  "per_fold": {int(k): float(v) for k, v in pf.items()}}
        if want_series is not None and lab == want_series:
            series = (netph.copy(), hrs.copy(), shm.copy())
    return cell, series if want_series is not None else cell


def _cell(D, a, s, reg):
    r = eval_cell(D, a, s, reg)
    return r[0] if isinstance(r, tuple) else r


# ---------- stricter bootstraps ----------
def month_block_ci(netph, shm, n=2000, seed=11):
    """Resample the 7 folds (months) with replacement -> the cross-independent-unit CI. Each month's steps move
    together (respects within-fold non-independence + shared wallet pool within a fold)."""
    if len(netph) < 8: return (float("nan"), float("nan"))
    months = np.unique(shm); loc = {mm: np.nonzero(shm == mm)[0] for mm in months}
    rng = np.random.default_rng(seed); st = []
    for _ in range(n):
        pick = rng.integers(0, len(months), size=len(months))
        idx = np.concatenate([loc[months[p]] for p in pick])
        st.append(netph[idx].mean())
    s = np.array(st); return (float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5)))


def weekly_block_ci(netph, hrs, hours, n=2000, seed=13):
    """Moving-block bootstrap over calendar weeks -> respects serial autocorrelation the day-block ignores."""
    if len(netph) < 8: return (float("nan"), float("nan"))
    weeks = (hours[hrs.astype(np.int64)] // (7 * 86400000)).astype(np.int64)
    uw = np.unique(weeks); loc = {w: np.nonzero(weeks == w)[0] for w in uw}
    rng = np.random.default_rng(seed); st = []
    for _ in range(n):
        pick = rng.integers(0, len(uw), size=len(uw))
        idx = np.concatenate([loc[uw[p]] for p in pick])
        st.append(netph[idx].mean())
    s = np.array(st); return (float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5)))


def main():
    D = load()
    _log("cache loaded")

    # ================= (0) BASELINE REPRODUCTION =================
    print("\n" + "=" * 92)
    print("(0) BASELINE REPRODUCTION  (alpha=1, stale=0)  -- must match compare_pooled reb4")
    print("=" * 92)
    base_all = _cell(D, 1.0, 0, "all")
    base_mid = _cell(D, 1.0, 0, "mid")
    for lab in FOCUS:
        sc = base_all["scenarios"][lab]
        print(f"  pooled {lab:22s} net={sc['net']:+.3f}  CI[{sc['ci95'][0]:+.2f},{sc['ci95'][1]:+.2f}]  "
              f"{sc['folds_pos']}/{sc['n_folds']}")
    print(f"  --> taker_smallclip {base_all['scenarios']['taker_top_smallclip']['net']:+.2f} (expect ~+1.42), "
          f"maker_a30 {base_all['scenarios']['maker_earn_a30']['net']:+.2f} (expect ~+4.35), "
          f"maker_a50 {base_all['scenarios']['maker_earn_a50']['net']:+.2f} (expect ~+3.60)")
    sc = base_mid["scenarios"]["taker_top_smallclip"]
    print(f"  mid taker_smallclip {sc['net']:+.2f} CI[{sc['ci95'][0]:+.2f},{sc['ci95'][1]:+.2f}] "
          f"{sc['folds_pos']}/{sc['n_folds']}  (expect +2.75 CI[-0.2,+5.9])")

    # ================= (1) FULL SWEEP + MONOTONICITY =================
    # NOTE: with stale=0 a belief lives only the hour it is observed, so there is never a prior to blend ->
    # alpha is INERT at stale=0. The real smoothing lever is alpha<1 AND stale>0. Use STALE=8 (effective regime;
    # stale is inert beyond ~4h because names are rarely dormant that long) for the net-vs-alpha curve.
    SREF = 8
    print("\n" + "=" * 92)
    print(f"(1) NET-vs-ALPHA CURVE  (stale={SREF}; the ACTIVE smoothing regime -- alpha is inert at stale=0)")
    print("=" * 92)
    grid = {}  # (regime,alpha,stale) -> cell
    for reg in ("all", "mid"):
        for a in ALPHAS:
            for s in STALES:
                grid[(reg, a, s)] = _cell(D, a, s, reg)
    _log("full grid evaluated")

    mono = {}
    for reg in ("all", "mid"):
        print(f"\n  regime={reg}")
        print(f"    {'alpha':>6} {'gross/hr':>9} {'turn':>6}   " +
              "  ".join(f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>14}" for l in FOCUS))
        for a in ALPHAS:
            s_use = 0 if a == 1.0 else SREF          # alpha=1 is baseline (blend-free) regardless of stale
            c = grid[(reg, a, s_use)]
            row = [f"{c['scenarios'][l]['net']:+7.2f}" for l in FOCUS]
            print(f"    {a:>6} {c['gross_bp_per_hr']:>+8.3f} {c['mean_turnover']:>6.2f}   " +
                  "  ".join(f"{r:>14}" for r in row))
        for lab in FOCUS:
            nets = [grid[(reg, a, 0 if a == 1.0 else SREF)]['scenarios'][lab]['net'] for a in ALPHAS]  # alpha 1.0..0.2
            # monotone WORSE as smoothing strengthens = net decreasing as alpha decreases = nets non-increasing
            decreasing = all(nets[i] >= nets[i + 1] - 1e-9 for i in range(len(nets) - 1))
            argmax_is_baseline = (int(np.argmax(nets)) == 0)
            mono[(reg, lab)] = (decreasing, argmax_is_baseline, nets)
            flag = "MONOTONE-WORSE, baseline=max" if (decreasing and argmax_is_baseline) else \
                   ("baseline=max (non-strict)" if argmax_is_baseline else "!! baseline NOT max")
            print(f"      {lab:22s} net@alpha[1.0,0.6,0.35,0.2]="
                  f"[{','.join(f'{x:+.2f}' for x in nets)}]  {flag}")

    # verify stale inertness
    print("\n  stale-inertness check (pooled, taker_smallclip, alpha=0.6): net across stale=0,4,8,24")
    ss = [grid[("all", 0.6, s)]['scenarios']['taker_top_smallclip']['net'] for s in STALES]
    print(f"    {['%+.4f' % x for x in ss]}  -> {'INERT (identical)' if max(ss)-min(ss) < 1e-9 else 'varies'}")

    # ================= (2) THE LONE FLIP + MULTIPLE COMPARISONS =================
    print("\n" + "=" * 92)
    print("(2) THE LONE FLIP  (mid, alpha=0.6, stale>=4, taker_top_smallclip)  vs baseline + MC tally")
    print("=" * 92)
    fb = base_mid["scenarios"]["taker_top_smallclip"]
    ff = grid[("mid", 0.6, 4)]["scenarios"]["taker_top_smallclip"]
    print(f"  mid baseline  (a1.0,s0): net={fb['net']:+.3f} CI[{fb['ci95'][0]:+.2f},{fb['ci95'][1]:+.2f}] "
          f"{fb['folds_pos']}/{fb['n_folds']}  sign_p={fb['sign_p']}")
    print(f"  the flip cell (a0.6,s4): net={ff['net']:+.3f} CI[{ff['ci95'][0]:+.2f},{ff['ci95'][1]:+.2f}] "
          f"{ff['folds_pos']}/{ff['n_folds']}  sign_p={ff['sign_p']}")
    print(f"  --> POINT-ESTIMATE SHIFT from smoothing: {ff['net']-fb['net']:+.4f} bp/hr  "
          f"(CI-width base={fb['ci95'][1]-fb['ci95'][0]:.2f} -> flip={ff['ci95'][1]-ff['ci95'][0]:.2f})")
    print(f"  per-fold nets  baseline: {[f'{v:+.2f}' for v in fb['per_fold'].values()]}")
    print(f"  per-fold nets  flip    : {[f'{v:+.2f}' for v in ff['per_fold'].values()]}")

    # is the "6/7 across stale>=4" independent or one inert-duplicated cell?
    flip_by_stale = {s: grid[("mid", 0.6, s)]["scenarios"]["taker_top_smallclip"] for s in STALES}
    print("\n  'confirmed across stale=4/8/24' -- are these independent? nets by stale (alpha0.6,mid):")
    for s in STALES:
        c = flip_by_stale[s]
        print(f"    stale={s:>2}: net={c['net']:+.3f} CI[{c['ci95'][0]:+.2f},{c['ci95'][1]:+.2f}]")
    dup = max(abs(flip_by_stale[4]['net'] - flip_by_stale[s]['net']) for s in (8, 24)) < 1e-9
    print(f"    -> {'IDENTICAL: stale>=4 is ONE cell replicated by an inert parameter, NOT 3 confirmations' if dup else 'differ'}")

    # multiple-comparisons tally across the whole grid.
    # The honest question is NOT "how many cells have CI-lo>0" (most are the strong MAKER baseline that trivially
    # stays significant, or the INERT stale=0 copy of baseline). It is: how many cells does SMOOTHING NEWLY push
    # across CI-lo>0 that were NOT already significant at their own baseline (same regime+scenario, alpha=1)?
    print("\n  MULTIPLE-COMPARISONS TALLY:")
    all_scen = [s[0] for s in CB.SCENARIOS]
    base_lo = {(reg, lab): grid[(reg, 1.0, 0)]["scenarios"][lab]["ci95"][0] for reg in ("all", "mid") for lab in all_scen}
    # collapse the inert stale dimension: use stale=8 (active) for alpha<1, stale=0 for alpha=1.
    new_flips, already_sig = [], 0
    n_distinct_smoothed = 0
    for reg in ("all", "mid"):
        for a in ALPHAS:
            s_use = 0 if a == 1.0 else 8
            for lab in all_scen:
                sc = grid[(reg, a, s_use)]["scenarios"][lab]
                lo = sc["ci95"][0]
                if a != 1.0:
                    n_distinct_smoothed += 1
                    if lo > 0 and base_lo[(reg, lab)] <= 0:               # smoothing MANUFACTURED significance
                        new_flips.append((reg, a, lab, sc["net"], sc["ci95"], base_lo[(reg, lab)]))
                    elif lo > 0:
                        already_sig += 1                                  # already significant at baseline (maker)
    exp_fp = n_distinct_smoothed * 0.025
    print(f"    distinct SMOOTHED looks (stale collapsed) = {n_distinct_smoothed}  "
          f"(2 regimes x 3 alpha<1 x {len(all_scen)} scenarios)")
    print(f"    of those, CI-lo>0 that were ALREADY significant at baseline (strong maker) = {already_sig} "
          f"(NOT flips -- baseline signal)")
    print(f"    SMOOTHING-MANUFACTURED flips (baseline lo<=0 -> smoothed lo>0):  {len(new_flips)}")
    for reg, a, lab, net, ci, blo in new_flips:
        print(f"      {reg:4s} a{a} {lab:22s} net={net:+.2f} CI[{ci[0]:+.2f},{ci[1]:+.2f}]  (baseline lo was {blo:+.2f})")
    print(f"    naive expected false flips @2.5% one-sided over {n_distinct_smoothed} looks = {exp_fp:.1f}")
    print(f"    -> {len(new_flips)} manufactured flip(s) vs ~{exp_fp:.1f} expected by chance "
          f"-> {'INSIDE chance expectation (benign noise)' if len(new_flips) <= exp_fp + 1 else 'above chance'}")

    # ================= (3) STRICTER BOOTSTRAPS ON THE FLIP =================
    print("\n" + "=" * 92)
    print("(3) NON-INDEPENDENCE: stricter bootstraps on the flip cell (mid, a0.6, s4, taker_smallclip)")
    print("=" * 92)
    _, series = eval_cell(D, 0.6, 4, "mid", want_series="taker_top_smallclip")
    netph, hrs, shm = series
    _, base_series = eval_cell(D, 1.0, 0, "mid", want_series="taker_top_smallclip")
    bnet, bhrs, bshm = base_series
    for name, (net_s, hr_s, shm_s) in (("flip a0.6", (netph, hrs, shm)), ("baseline a1.0", (bnet, bhrs, bshm))):
        day = CB._dayblock_ci(net_s, hr_s, D["hours"])
        wk = weekly_block_ci(net_s, hr_s, D["hours"])
        mo = month_block_ci(net_s, shm_s)
        print(f"  {name:14s} mean={net_s.mean():+.3f}  day-block CI[{day[0]:+.2f},{day[1]:+.2f}]  "
              f"weekly-block CI[{wk[0]:+.2f},{wk[1]:+.2f}]  month/fold-block CI[{mo[0]:+.2f},{mo[1]:+.2f}]")
    print("  (month/fold-block is the cross-independent-unit CI; the wallet pool overlaps WITHIN a fold, so the")
    print("   fold is the honest resampling unit. If its CI-lo crosses 0, the 'flip' does not survive.)")

    # ================= (4) MECHANISM: THE DERIVATIVE =================
    print("\n" + "=" * 92)
    print("(4) MECHANISM: turnover-for-gross slope at alpha=1  (is ANY trade net-positive?)")
    print("=" * 92)
    for reg in ("all", "mid"):
        c1 = grid[(reg, 1.0, 0)]; c6 = grid[(reg, 0.6, SREF)]         # baseline vs first smoothing step (stale active)
        G1, G6 = c1["gross_bp_per_hr"], c6["gross_bp_per_hr"]          # bp per hr
        T1, T6 = c1["mean_turnover"], c6["mean_turnover"]
        dG = G1 - G6; dT = T1 - T6                                     # gross lost, turnover saved (both >0 expected)
        print(f"\n  regime={reg}:  gross/hr {G1:+.3f}->{G6:+.3f} (lose {dG:+.3f})   "
              f"turnover {T1:.3f}->{T6:.3f} (save {dT:.3f})")
        if dT <= 1e-9:
            print("    turnover barely moved -> no turnover to trade; smoothing just decays gross. Unfavorable.")
            continue
        gross_lost_per_turn = dG / dT                                  # bp/hr of gross lost per unit turnover saved
        # cost saved per unit turnover for the taker_smallclip scenario:
        # cost/step = ntrade*fee + min(hs, ntrade); ntrade = 2*turn; per REB hours. small-clip spread ~<=1bp/side.
        fee = 2.4; hs_med = D["hs_default"]
        # small clip caps spread at ntrade*1.0, and hs_med(~3.2)>1 so per-side spread ~1.0bp; cost/turn-unit:
        cost_saved_per_turn_smallclip = (2.0 * (fee + 1.0)) / REB      # bp/hr saved per unit turnover (2 sides)
        cost_saved_per_turn_impact = (2.0 * fee + 2.0 * hs_med) / REB  # taker impact: full half-spread each side
        print(f"    gross LOST per unit turnover saved   = {gross_lost_per_turn:+.3f} bp/hr")
        print(f"    cost SAVED per unit turnover (smallclip, fee2.4+1.0 spr, /reb) = {cost_saved_per_turn_smallclip:+.3f} bp/hr")
        print(f"    cost SAVED per unit turnover (impact,  fee2.4+hs{hs_med:.1f},  /reb) = {cost_saved_per_turn_impact:+.3f} bp/hr")
        net_trade_smallclip = cost_saved_per_turn_smallclip - gross_lost_per_turn
        net_trade_impact = cost_saved_per_turn_impact - gross_lost_per_turn
        print(f"    NET of the first turnover-for-gross step:  smallclip {net_trade_smallclip:+.3f} bp/hr, "
              f"impact {net_trade_impact:+.3f} bp/hr")
        print(f"    -> {'FAVORABLE' if net_trade_smallclip > 0 else 'UNFAVORABLE'} for smallclip from alpha=1; "
              f"{'FAVORABLE' if net_trade_impact > 0 else 'UNFAVORABLE'} for impact.")

    _log("done")


if __name__ == "__main__":
    main()
