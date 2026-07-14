"""
ASSUMPTIONS agent — sensitivity of the alpha~=0.90 denoise win to every arbitrary knob.

Reproduces the banked win off the leak-free cache, then perturbs each baked-in assumption and asks:
does the maker (maker_earn_a30) and taker (taker_top_smallclip) win SURVIVE?

Knobs probed (all off panel_cache.npz; no DuckDB — upstream signal knobs are baked into s_inf, flagged not run):
  1. alpha exact value + PER-FOLD plateau stability (is [0.85,0.93] a plateau or a 0.90 spike?)
  2. Filter SPACE: level vs cross-sectional-z vs cross-sectional-rank EMA.
  3. Book knobs: q1/q2 hold band (decile 10/15, quintile 20/25, ventile 5/10, band 10/20),
     reb in {3,4,6} x ALL grid phase offsets (the horizon agent flagged reb4 phase-0 as favorable).
  4. Cost stress: half-spread scale, maker fee, adverse-selection haircut.

    .venv/bin/python -m research.studies.wallet_flow.denoise_swarm_assumptions_sensitivity
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")


def dense_ema(SIG, alpha):
    """Per-column causal EMA blending every observed hour, belief carried across gaps. alpha=1 -> passthrough."""
    if alpha >= 1.0:
        return SIG
    N, Acol = SIG.shape
    m = np.full((N, Acol), np.nan)
    prev = np.full(Acol, np.nan)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs)
        newv = np.where(np.isfinite(prev), alpha * obs + (1.0 - alpha) * prev, obs)
        prev = np.where(has, newv, prev)
        m[t] = np.where(has, prev, np.nan)
    return m


def transform_space(SIG, space):
    """Per-hour cross-sectional transform BEFORE the EMA. level=identity, csz=standardize, rank=[-.5,.5]."""
    if space == "level":
        return SIG
    N, A = SIG.shape
    out = np.full((N, A), np.nan)
    for t in range(N):
        row = SIG[t]; fin = np.isfinite(row)
        n = int(fin.sum())
        if n < 2:
            continue
        v = row[fin]
        if space == "csz":
            mu = v.mean(); sd = v.std()
            out[t, fin] = (v - mu) / sd if sd > 0 else 0.0
        elif space == "rank":
            rk = np.argsort(np.argsort(v)).astype(float)
            out[t, fin] = rk / (n - 1) - 0.5
    return out


def build_cache(d):
    R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; resid_alt = d["resid_alt"]
    hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
    SIG = np.full((N, n_alt), np.nan)
    obs = set()
    for i in range(len(R)):
        if np.isfinite(s_inf[i]):
            SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
    base_hours = np.array(sorted(obs), dtype=np.int64)
    return dict(SIG=SIG, base_hours=base_hours, resid_alt=resid_alt, halfspread=halfspread,
                hs_default=hs_default, n_alt=n_alt, hours=hours, panel_month=panel_month)


def eval_variant(B, alpha, space="level", reb=4, phase=0, q1=0.10, q2=0.15,
                 hs_scale=1.0, fee_maker=1.0, fee_taker=2.4, fold_filter=None, focus=FOCUS):
    """Full pipeline for one knob setting. Returns gross/turn + per-focus-scenario net/ci/folds."""
    m = dense_ema(transform_space(B["SIG"], space), alpha)
    reb_grid = B["base_hours"][phase::reb]
    FVr = S0.fwd_sum(B["resid_alt"], reb)
    halfspread = {i: B["halfspread"][i] * hs_scale for i in B["halfspread"]}
    hs_def = B["hs_default"] * hs_scale
    full = set(range(B["n_alt"]))
    xs, fvb, elig = {}, {}, {}
    for t in reb_grid:
        ti = int(t)
        if fold_filter is not None and int(B["panel_month"][ti]) not in fold_filter:
            continue
        row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        xs[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
        elig[ti] = full
    keys = np.array(sorted(xs), dtype=np.int64)
    if len(keys) < 8:
        return None
    sim = CB.simulate_raw(keys, xs, fvb, halfspread, hs_def, 1, q1, q2, elig)
    if len(sim["hr"]) == 0:
        return None
    hrs = sim["hr"].astype(np.int64)
    shm = np.array([int(B["panel_month"][int(t)]) for t in hrs])
    out = {"gross": float((sim["gross"] / reb).mean()), "turn": float(sim["turn"].mean()),
           "n": len(hrs), "sc": {}}
    # custom cost scenarios so we can stress fee: (label, mult, fee, mode)
    scen = {"taker_top_smallclip": (1.00, fee_taker, "small"),
            "taker_top_impact":    (1.00, fee_taker, "impact"),
            "maker_earn_a30":      (0.70, fee_maker, "earn"),
            "maker_earn_a50":      (0.50, fee_maker, "earn"),
            "maker_earn_a0":       (1.00, fee_maker, "earn"),
            "maker_earn_a70":      (0.30, fee_maker, "earn")}
    for lab in focus:
        mult, fee, mode = scen[lab]
        netph, _ = CB.scenario_net_series(sim, reb, fee, mode, mult, hs_def)
        ci = CB._dayblock_ci(netph, hrs, B["hours"])
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        out["sc"][lab] = {"net": float(netph.mean()), "ci": ci,
                          "fp": int(sum(1 for v in pf.values() if v > 0)), "nf": len(pf), "pf": pf}
    return out


def _fmt(sc):
    lo, hi = sc["ci"]; star = "*" if lo > 0 else ("-" if hi < 0 else " ")
    return f"{sc['net']:+5.2f}[{lo:+4.1f},{hi:+4.1f}]{sc['fp']}/{sc['nf']}{star}"


def _line(tag, e):
    if e is None:
        print(f"{tag:26s}   (thin)"); return
    print(f"{tag:26s} g{e['gross']:+5.2f} tn{e['turn']:.2f}  "
          f"mk_a30 {_fmt(e['sc']['maker_earn_a30'])}  tk_sc {_fmt(e['sc']['taker_top_smallclip'])}")


def main():
    d = np.load(CACHE, allow_pickle=False)
    B = build_cache(d)
    folds = sorted(int(x) for x in d["folds"])
    early, late = set(folds[:4]), set(folds[4:])
    ALPHAS = [1.0, 0.95, 0.93, 0.91, 0.90, 0.89, 0.87, 0.85, 0.83, 0.80]

    print("=" * 110)
    print("BASELINE GATE (alpha=1, level, reb4, phase0, decile 10/15): expect mk_a30 +4.35, tk_sc +1.42, gross +3.74")
    _line("alpha=1.0 BASELINE", eval_variant(B, 1.0))
    _line("alpha=0.90 WIN", eval_variant(B, 0.90))

    # ---------------------------------------------------------------- 1. alpha plateau, POOLED and PER-FOLD
    print("\n" + "=" * 110)
    print("[1] ALPHA PLATEAU (pooled reb4 level). Is win broad over [0.85,0.93] or a spike at 0.90?")
    pooled = {a: eval_variant(B, a) for a in ALPHAS}
    for a in ALPHAS:
        _line(f"  alpha={a:.2f}", pooled[a])
    # per-fold plateau stability: is the plateau shape stable per single-fold, or only pooled?
    print("\n[1b] PER-FOLD maker_a30 net(alpha) — is the plateau stable per-fold, or a pooled artifact?")
    print(f"{'fold':>8} " + " ".join(f"a{a:.2f}".rjust(7) for a in [1.0, 0.90, 0.87, 0.85]))
    for f in folds:
        e = {a: eval_variant(B, a, fold_filter={f}) for a in [1.0, 0.90, 0.87, 0.85]}
        vals = " ".join((f"{e[a]['sc']['maker_earn_a30']['net']:+7.2f}" if e[a] else "   thin") for a in [1.0, 0.90, 0.87, 0.85])
        print(f"{f:>8} {vals}")

    # ---------------------------------------------------------------- 2. Filter SPACE
    print("\n" + "=" * 110)
    print("[2] FILTER SPACE (alpha=0.90, reb4). Is 'level' a lucky choice vs z-score / rank?")
    for sp in ("level", "csz", "rank"):
        _line(f"  space={sp} (a=1)", eval_variant(B, 1.0, space=sp))
        _line(f"  space={sp} (a=.90)", eval_variant(B, 0.90, space=sp))

    # ---------------------------------------------------------------- 3a. Book q1/q2 band
    print("\n" + "=" * 110)
    print("[3a] BOOK EXTREMITY / HOLD-BAND (reb4 level). Does denoise win survive quintile/ventile & band width?")
    for (q1, q2, name) in [(0.10, 0.15, "decile 10/15"), (0.10, 0.20, "decile 10/20"),
                           (0.20, 0.25, "quintile 20/25"), (0.20, 0.30, "quintile 20/30"),
                           (0.05, 0.10, "ventile 5/10")]:
        b1 = eval_variant(B, 1.0, q1=q1, q2=q2); b9 = eval_variant(B, 0.90, q1=q1, q2=q2)
        d30 = (b9['sc']['maker_earn_a30']['net'] - b1['sc']['maker_earn_a30']['net']) if (b1 and b9) else float('nan')
        dg = (b9['gross'] - b1['gross']) if (b1 and b9) else float('nan')
        _line(f"  {name} a1", b1); _line(f"  {name} a.90 (dMk{d30:+.2f} dG{dg:+.2f})", b9)

    # ---------------------------------------------------------------- 3b. reb x phase — the grid-phase robustness test
    print("\n" + "=" * 110)
    print("[3b] GRID-PHASE / REB ROBUSTNESS (level). For each reb, ALL phase offsets: does denoise lift hold everywhere?")
    print("     Reports gross a1 -> a.90 (delta, %), and maker_a30 a1 -> a.90 per (reb,phase).")
    for reb in (3, 4, 6):
        print(f"  --- reb={reb} ---")
        gdeltas = []; mkdeltas = []
        for ph in range(reb):
            b1 = eval_variant(B, 1.0, reb=reb, phase=ph); b9 = eval_variant(B, 0.90, reb=reb, phase=ph)
            if b1 is None or b9 is None:
                print(f"    phase {ph}: thin"); continue
            g1, g9 = b1['gross'], b9['gross']; pct = 100 * (g9 - g1) / abs(g1) if g1 else float('nan')
            m1 = b1['sc']['maker_earn_a30']; m9 = b9['sc']['maker_earn_a30']
            t9 = b9['sc']['taker_top_smallclip']
            gdeltas.append(g9 - g1); mkdeltas.append(m9['net'] - m1['net'])
            print(f"    phase {ph}: gross {g1:+5.2f}->{g9:+5.2f} ({pct:+5.1f}%)  "
                  f"mk_a30 {m1['net']:+5.2f}->{m9['net']:+5.2f} {_fmt(m9)}  tk_sc {_fmt(t9)}")
        if gdeltas:
            print(f"    reb{reb} phase-avg gross delta {np.mean(gdeltas):+.2f}  maker_a30 delta {np.mean(mkdeltas):+.2f}  "
                  f"(pos phases: g {sum(1 for x in gdeltas if x>0)}/{len(gdeltas)}, mk {sum(1 for x in mkdeltas if x>0)}/{len(mkdeltas)})")

    # ---------------------------------------------------------------- 5. Cost stress
    print("\n" + "=" * 110)
    print("[5] COST STRESS (alpha=0.90 vs a=1, reb4 level). Does the MAKER win survive stressing spread/fee/haircut?")
    print("  -- half-spread scale (maker EARNS spread, so LOWER spread HURTS maker; taker PAYS, higher HURTS taker) --")
    for hsx in (0.5, 0.75, 1.0, 1.5, 2.0):
        b1 = eval_variant(B, 1.0, hs_scale=hsx); b9 = eval_variant(B, 0.90, hs_scale=hsx)
        _line(f"  hs x{hsx:.2f} a1", b1); _line(f"  hs x{hsx:.2f} a.90", b9)
    print("  -- maker fee/side stress (base 1.0) --")
    for fm in (0.5, 1.0, 1.5, 2.0):
        b9 = eval_variant(B, 0.90, fee_maker=fm)
        _line(f"  makerfee={fm:.1f} a.90", b9)
    print("  -- adverse-selection haircut ladder (a0/a30/a50/a70) at a=0.90 vs baseline a=1 --")
    b1 = eval_variant(B, 1.0, focus=("maker_earn_a0", "maker_earn_a30", "maker_earn_a50", "maker_earn_a70"))
    b9 = eval_variant(B, 0.90, focus=("maker_earn_a0", "maker_earn_a30", "maker_earn_a50", "maker_earn_a70"))
    for lab in ("maker_earn_a0", "maker_earn_a30", "maker_earn_a50", "maker_earn_a70"):
        print(f"  {lab:16s} a1 {_fmt(b1['sc'][lab])}   a.90 {_fmt(b9['sc'][lab])}   "
              f"delta {b9['sc'][lab]['net']-b1['sc'][lab]['net']:+.2f}")

    print("\nDONE.")


if __name__ == "__main__":
    main()
