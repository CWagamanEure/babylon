"""
adfilter_steelman_book — the DEPLOYABLE test of the adaptive observation-noise model.

Mechanism (from adfilter_steelman_diag): per-hour signal STRENGTH is the R-driver — strong-vote hours have
~2x the forward IC (low R, trust the obs), weak-vote hours collapse (high R, lean on the prior). The fixed
alpha=0.90 EMA smooths EVERY hour by 10% => it pays the stale-prior dilution cost even in the low-R hours where
the obs was already clean. The ADAPTIVE filter sets a per-hour gain alpha_t: ~1 (barely smooth) in strong/low-R
hours, low (smooth hard) in weak/high-R hours. Thesis: it recovers more of the denoise benefit while paying less
dilution => beats BOTH baseline (alpha=1) AND fixed alpha=0.90, phase-averaged + OOS.

R-model (strictly causal, OOS-honest): observable obs_t computed from THIS hour's votes only; standardized by
the EARLY-fold (train) mean/std (frozen), squashed to a reliability in [0,1]; alpha_t = alo + (ahi-alo)*rel_t.
alpha-map params are FROZEN on early folds and applied blind to late folds. No future in the conditioning.

Everything books through the IDENTICAL CB.simulate_raw / scenario_net_series engine on the frozen grid, and is
PHASE-AVERAGED across all reb offsets (a single-phase magnitude over-carries ~4x — hard-won guardrail).

    .venv/bin/python -m research.studies.wallet_flow.adfilter_steelman_book
"""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
OUT = Path("data/derived/xsec_kalman/adfilter_steelman_book.json")
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)


# ------------------------------------------------------------------ EMA engines
def dense_ema_scalar(SIG, alpha):
    """Fixed-gain causal EMA (matches DEC.dense_ema). alpha=1 -> passthrough."""
    if alpha >= 1.0:
        return SIG
    N, A = SIG.shape
    m = np.full((N, A), np.nan); prev = np.full(A, np.nan)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs)
        newv = np.where(np.isfinite(prev), alpha * obs + (1.0 - alpha) * prev, obs)
        prev = np.where(has, newv, prev)
        m[t] = np.where(has, prev, np.nan)
    return m


def dense_ema_perhour(SIG, alpha_t):
    """ADAPTIVE causal EMA: per-hour gain alpha_t[t] (broadcast to all coins that hour). Strictly causal iff
    alpha_t[t] uses only data <= t. alpha_t[t]=1 -> that hour is a passthrough (no blend)."""
    N, A = SIG.shape
    m = np.full((N, A), np.nan); prev = np.full(A, np.nan)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs); a = float(alpha_t[t])
        newv = np.where(np.isfinite(prev), a * obs + (1.0 - a) * prev, obs)
        prev = np.where(has, newv, prev)
        m[t] = np.where(has, prev, np.nan)
    return m


# ------------------------------------------------------------------ load
def load():
    d = np.load(CACHE, allow_pickle=False)
    R, Cc, s_inf = d["R"].astype(int), d["Cc"].astype(int), d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; resid_alt = d["resid_alt"]
    hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
    folds = sorted(int(x) for x in d["folds"])
    SIG = np.full((N, n_alt), np.nan); obs = set()
    fin = np.isfinite(s_inf)
    for i in np.nonzero(fin)[0]:
        SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
    base_hours = np.array(sorted(obs), dtype=np.int64)
    return dict(SIG=SIG, base_hours=base_hours, halfspread=halfspread, hs_default=hs_default,
                n_alt=n_alt, N=N, hours=hours, panel_month=panel_month, resid_alt=resid_alt, folds=folds)


# ------------------------------------------------------------------ causal per-hour observable + alpha map
def obs_series(SIG, which):
    """Per-hour causal observable. 'absmed' = median |vote|; 'sigma' = std of votes; 'combo' = mean of z's."""
    N = SIG.shape[0]
    am = np.full(N, np.nan); sg = np.full(N, np.nan)
    for t in range(N):
        row = SIG[t]; f = np.isfinite(row)
        if f.sum() >= 4:
            am[t] = np.median(np.abs(row[f])); sg[t] = row[f].std()
    if which == "absmed": return am
    if which == "sigma": return sg
    return None, am, sg  # combo handled in build_alpha


def build_alpha(SIG, panel_month, early, which, alo, ahi, k=1.0):
    """alpha_t = alo + (ahi-alo)*sigmoid(k * z_early(obs_t)). z standardized by EARLY-fold mean/std (frozen).
    Returns (alpha_t array, mean rel on late) — strictly causal + OOS-honest."""
    N = SIG.shape[0]
    if which == "combo":
        _, am, sg = obs_series(SIG, "combo")
        emask = np.array([int(panel_month[t]) in early and np.isfinite(am[t]) for t in range(N)])
        za = (am - am[emask].mean()) / (am[emask].std() + 1e-12)
        zs = (sg - sg[emask].mean()) / (sg[emask].std() + 1e-12)
        z = 0.5 * (za + zs)
    else:
        o = obs_series(SIG, which)
        emask = np.array([int(panel_month[t]) in early and np.isfinite(o[t]) for t in range(N)])
        mu, sd = o[emask].mean(), o[emask].std() + 1e-12
        z = (o - mu) / sd
    rel = 1.0 / (1.0 + np.exp(-k * z))                  # in (0,1): high obs -> rel~1 -> alpha~ahi (trust obs)
    alpha_t = alo + (ahi - alo) * rel
    alpha_t = np.where(np.isfinite(alpha_t), alpha_t, ahi)   # unobserved hours never rebalance anyway
    return alpha_t


# ------------------------------------------------------------------ booking engine (per-grid)
def book_grid(P, m, reb, grid):
    FVr = S0.fwd_sum(P["resid_alt"], reb)
    full = set(range(P["n_alt"])); xs, fvb, elig = {}, {}, {}
    for t in grid:
        ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4: continue
        xs[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}; elig[ti] = full
    keys = np.array(sorted(xs), dtype=np.int64)
    if len(keys) < 8: return None
    sim = CB.simulate_raw(keys, xs, fvb, P["halfspread"], P["hs_default"], 1, 0.10, 0.15, elig)
    hrs = sim["hr"].astype(np.int64)
    out = {"gross": float((sim["gross"] / reb).mean()), "turn": float(sim["turn"].mean()),
           "hrs": hrs, "reb": reb, "net": {}}
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in FOCUS: continue
        netph, _ = CB.scenario_net_series(sim, reb, fee, mode, mult, P["hs_default"])
        out["net"][lab] = {int(h): float(v) for h, v in zip(hrs, netph)}
    return out


def phase_book(P, m, reb):
    """Book m on all `reb` phase offsets; return per-(phase) books + the union hour->net maps for CI/fold."""
    books = []
    for ph in range(reb):
        grid = P["base_hours"][ph::reb]
        b = book_grid(P, m, reb, grid)
        if b is not None: books.append(b)
    return books


def summarize_phaseavg(P, books, fold_filter=None):
    """Phase-average each leg's per-hour net (each phase an independent grid), fold-filter optional.
    Returns per-leg {net (phase-avg of pooled means), fp/nf per-fold sign, gross}."""
    pm = P["panel_month"]
    res = {"gross": [], "turn": []}
    legnet = {lab: [] for lab in FOCUS}
    per_fold = {lab: {} for lab in FOCUS}   # month -> list of phase means
    for b in books:
        hrs = b["hrs"]
        sel = np.array([fold_filter is None or int(pm[int(h)]) in fold_filter for h in hrs])
        if sel.sum() < 8: continue
        res["gross"].append(b["gross"]); res["turn"].append(b["turn"])  # gross/turn not fold-split (coarse)
        for lab in FOCUS:
            nm = b["net"][lab]
            vals = np.array([nm[int(h)] for h in hrs[sel]])
            legnet[lab].append(float(vals.mean()))
            months = np.array([int(pm[int(h)]) for h in hrs[sel]])
            for mm in sorted(set(months.tolist())):
                per_fold[lab].setdefault(mm, []).append(float(vals[months == mm].mean()))
    out = {"gross": float(np.mean(res["gross"])) if res["gross"] else np.nan,
           "turn": float(np.mean(res["turn"])) if res["turn"] else np.nan, "legs": {}}
    for lab in FOCUS:
        pa = float(np.mean(legnet[lab])) if legnet[lab] else np.nan
        fm = {mm: float(np.mean(v)) for mm, v in per_fold[lab].items()}   # phase-avg per fold
        fp = int(sum(1 for v in fm.values() if v > 0)); nf = len(fm)
        st = ADJ.sign_test(list(fm.values()))
        out["legs"][lab] = {"net": pa, "fp": fp, "nf": nf, "sign_p": st["p"], "per_fold": fm}
    return out


def paired_phaseavg(P, books_a, books_b, fold_filter=None):
    """Phase-averaged PAIRED (a - b) per-leg lift with day-block CI + per-fold sign. Books aligned by hour
    within each phase (same grid). Each phase's paired diff pooled, then phase-averaged; CI via day-block on
    the concatenated paired series."""
    pm = P["panel_month"]; hours = P["hours"]
    out = {}
    for lab in FOCUS:
        allh, alld = [], []; per_fold = {}
        phase_means = []
        for ba, bb in zip(books_a, books_b):
            na, nb = ba["net"][lab], bb["net"][lab]
            common = [int(h) for h in ba["hrs"] if int(h) in nb and
                      (fold_filter is None or int(pm[int(h)]) in fold_filter)]
            if len(common) < 8: continue
            diff = np.array([na[h] - nb[h] for h in common])
            phase_means.append(float(diff.mean()))
            allh.extend(common); alld.extend(diff.tolist())
            months = np.array([int(pm[h]) for h in common])
            for mm in sorted(set(months.tolist())):
                per_fold.setdefault(mm, []).append(float(diff[months == mm].mean()))
        if not phase_means:
            out[lab] = None; continue
        allh = np.array(allh, dtype=np.int64); alld = np.array(alld)
        ci = CB._dayblock_ci(alld, allh, hours)
        fm = {mm: float(np.mean(v)) for mm, v in per_fold.items()}
        fp = int(sum(1 for v in fm.values() if v > 0)); nf = len(fm)
        st = ADJ.sign_test(list(fm.values()))
        out[lab] = {"lift": float(np.mean(phase_means)), "ci": ci, "fp": fp, "nf": nf,
                    "sign_p": st["p"], "n_phases": len(phase_means),
                    "phase_pos": int(sum(1 for v in phase_means if v > 0))}
    return out


def fmt_leg(s):
    if s is None: return "(thin)"
    return f"{s['net']:+.3f} {s['fp']}/{s['nf']}(p{s['sign_p']:.2f})"


def fmt_pair(s):
    if s is None: return "(thin)"
    lo, hi = s["ci"]; star = "*" if lo > 0 else ("-" if hi < 0 else " ")
    return f"{s['lift']:+.3f}[{lo:+.2f},{hi:+.2f}]{star} ph{s['phase_pos']}/{s['n_phases']} fold{s['fp']}/{s['nf']}"


# ------------------------------------------------------------------ main
def main():
    P = load()
    SIG = P["SIG"]; folds = P["folds"]; early = set(folds[:4]); late = set(folds[4:])
    print(f"folds {folds}  EARLY(train R-map) {sorted(early)}  LATE(OOS) {sorted(late)}")

    # -- references --
    m_base = SIG
    m_fixed = dense_ema_scalar(SIG, 0.90)

    # sanity: phase-0 reb4 must reproduce +3.735 / +4.764
    b0 = book_grid(P, m_base, 4, P["base_hours"][::4]); f0 = book_grid(P, m_fixed, 4, P["base_hours"][::4])
    print(f"\nSANITY reb4-phase0: baseline gross {b0['gross']:+.3f}  fixed0.90 gross {f0['gross']:+.3f} "
          f"(expect +3.735 / +4.764)")

    REBS = (4,)  # primary: the horizon where the fixed-alpha denoise lives; reb3/6 as robustness below
    RESULTS = {}

    # ================= PRIMARY: reb4, phase-averaged, ALL folds =================
    print("\n" + "=" * 104)
    print("PHASE-AVERAGED reb4 (all 4 offsets), ALL 7 folds — baseline vs fixed a=0.90 vs ADAPTIVE range")
    print("=" * 104)
    books_base = phase_book(P, m_base, 4)
    books_fixed = phase_book(P, m_fixed, 4)
    S_base = summarize_phaseavg(P, books_base)
    S_fixed = summarize_phaseavg(P, books_fixed)
    print(f"  {'config':<34} {'gross':>7} {'turn':>5}  " +
          "  ".join(f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>18}" for l in FOCUS))
    def prow(tag, S):
        print(f"  {tag:<34} {S['gross']:>+7.3f} {S['turn']:>5.2f}  " +
              "  ".join(f"{fmt_leg(S['legs'][l]):>18}" for l in FOCUS))
    prow("baseline (a=1)", S_base)
    prow("fixed a=0.90", S_fixed)

    GRID = [("absmed", 0.70, 1.00), ("absmed", 0.80, 1.00), ("absmed", 0.60, 0.98),
            ("sigma", 0.70, 1.00), ("sigma", 0.80, 1.00),
            ("combo", 0.70, 1.00), ("combo", 0.80, 1.00), ("combo", 0.60, 0.98)]
    adaptive_books = {}
    RESULTS["primary"] = {"baseline": S_base, "fixed": S_fixed, "adaptive": {}, "paired_vs_fixed": {},
                          "paired_vs_base": {}}
    for (which, alo, ahi) in GRID:
        alpha_t = build_alpha(SIG, P["panel_month"], early, which, alo, ahi)
        m_ad = dense_ema_perhour(SIG, alpha_t)
        bk = phase_book(P, m_ad, 4)
        adaptive_books[(which, alo, ahi)] = bk
        S = summarize_phaseavg(P, bk)
        prow(f"ADAPT {which} lo{alo} hi{ahi}", S)
        RESULTS["primary"]["adaptive"][f"{which}_{alo}_{ahi}"] = S

    # paired lift (adaptive - fixed) and (adaptive - baseline), phase-avg all folds
    print("\n  PAIRED phase-avg lift (ADAPT - FIXED0.90)  [day-CI] ph_pos/nph fold_pos/nf   ('*'=CI>0)")
    for key, bk in adaptive_books.items():
        pf = paired_phaseavg(P, bk, books_fixed)
        pb = paired_phaseavg(P, bk, books_base)
        RESULTS["primary"]["paired_vs_fixed"]["_".join(map(str, key))] = pf
        RESULTS["primary"]["paired_vs_base"]["_".join(map(str, key))] = pb
        tag = f"{key[0]} lo{key[1]} hi{key[2]}"
        print(f"    {tag:<22} vsFIX  " + "   ".join(f"{l.split('_')[-1] if 'maker' not in l else l[-3:]}:{fmt_pair(pf[l])}" for l in ("maker_earn_a30", "taker_top_smallclip")))

    # ================= OOS: fit R-map on EARLY, apply blind to LATE =================
    print("\n" + "=" * 104)
    print("OOS OVERFIT-KILLER — R-map standardization FROZEN on EARLY folds; evaluate LATE folds only, phase-avg")
    print("=" * 104)
    Sb_late = summarize_phaseavg(P, books_base, late)
    Sf_late = summarize_phaseavg(P, books_fixed, late)
    print(f"  {'config (LATE folds)':<34} {'gross':>7}  " +
          "  ".join(f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>18}" for l in FOCUS))
    def prow_l(tag, S):
        print(f"  {tag:<34} {S['gross']:>+7.3f}  " +
              "  ".join(f"{fmt_leg(S['legs'][l]):>18}" for l in FOCUS))
    prow_l("baseline (a=1)", Sb_late)
    prow_l("fixed a=0.90", Sf_late)
    RESULTS["oos"] = {"baseline": Sb_late, "fixed": Sf_late, "adaptive": {}, "paired_vs_fixed": {}, "paired_vs_base": {}}
    for key, bk in adaptive_books.items():
        S = summarize_phaseavg(P, bk, late)
        prow_l(f"ADAPT {key[0]} lo{key[1]} hi{key[2]}", S)
        RESULTS["oos"]["adaptive"]["_".join(map(str, key))] = S
    print("\n  OOS PAIRED lift on LATE folds (ADAPT - FIXED0.90) and (ADAPT - BASELINE):")
    for key, bk in adaptive_books.items():
        pf = paired_phaseavg(P, bk, books_fixed, late)
        pb = paired_phaseavg(P, bk, books_base, late)
        RESULTS["oos"]["paired_vs_fixed"]["_".join(map(str, key))] = pf
        RESULTS["oos"]["paired_vs_base"]["_".join(map(str, key))] = pb
        tag = f"{key[0]} lo{key[1]} hi{key[2]}"
        print(f"    {tag:<22} mk_a30 vsFIX {fmt_pair(pf['maker_earn_a30'])}  vsBASE {fmt_pair(pb['maker_earn_a30'])}")
        print(f"    {'':<22} tk_sc  vsFIX {fmt_pair(pf['taker_top_smallclip'])}  vsBASE {fmt_pair(pb['taker_top_smallclip'])}")

    # ================= ROBUSTNESS across reb in {3,4,6}, phase-averaged =================
    print("\n" + "=" * 104)
    print("ROBUSTNESS across reb in {3,4,6}, phase-averaged — paired (ADAPT combo lo0.7 - FIXED0.90) maker_a30")
    print("=" * 104)
    alpha_t = build_alpha(SIG, P["panel_month"], early, "combo", 0.70, 1.00)
    m_ad = dense_ema_perhour(SIG, alpha_t)
    RESULTS["robust_reb"] = {}
    for reb in (3, 4, 6):
        bk_ad = phase_book(P, m_ad, reb); bk_fx = phase_book(P, m_fixed, reb); bk_bs = phase_book(P, m_base, reb)
        pf = paired_phaseavg(P, bk_ad, bk_fx); pb = paired_phaseavg(P, bk_ad, bk_bs)
        RESULTS["robust_reb"][reb] = {"vs_fixed": pf, "vs_base": pb}
        print(f"  reb={reb}: mk_a30 vsFIX {fmt_pair(pf['maker_earn_a30'])}   vsBASE {fmt_pair(pb['maker_earn_a30'])}")
        print(f"  reb={reb}: tk_sc  vsFIX {fmt_pair(pf['taker_top_smallclip'])}   vsBASE {fmt_pair(pb['taker_top_smallclip'])}")

    OUT.write_text(json.dumps(RESULTS, indent=2, default=float))
    _log(f"wrote {OUT}")


if __name__ == "__main__":
    main()
