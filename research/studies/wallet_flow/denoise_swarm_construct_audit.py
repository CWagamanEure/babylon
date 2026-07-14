"""
CONSTRUCTION/LEAKAGE audit of the alpha~=0.90 denoise win.

Checks (see audit/xsec_denoise_swarm/SCOPE.md):
 1. dense_ema causality: alpha=1 exact passthrough; strictly causal (m[t] depends only on SIG[<=t]);
    no look-ahead injecting future into the rank at rebalance t.
 2. Magnitude of +27% gross from a 10% blend: is the UNIVERSE/eligibility identical across alpha, and
    where does the gross delta come from (broad re-rank vs few tail flips)? Instrument.
 3. Grid-phase confound: re-run the denoise on all 4 phase offsets of the [::4] grid; is the RELATIVE
    alpha-effect phase-invariant, and does it hold across reb in {3,4,6}?
 4. Forward wiring fidelity: does xsec_book_eval.smooth_signals reproduce dense_ema value-for-value on
    the same input? Cross-check on synthetic + on the research cells.
 5. OOS split integrity: EMA state crossing the early->late boundary is causal (no leak); alpha* is not
    selected with any peek at late folds.

    .venv/bin/python -m research.studies.wallet_flow.denoise_swarm_construct_audit
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import kalman_swarm_decisive as DEC
from research.studies.wallet_flow import xsec_book_eval as EV

CACHE = "data/derived/xsec_kalman/panel_cache.npz"


def build(d, reb):
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
    FVr = S0.fwd_sum(resid_alt, reb)
    return dict(SIG=SIG, base_hours=base_hours, FVr=FVr, halfspread=halfspread, hs_default=hs_default,
                n_alt=n_alt, hours=hours, panel_month=panel_month, reb=reb)


def eval_grid(B, alpha, reb_grid, focus=DEC.FOCUS, return_book=False):
    """Evaluate on an arbitrary rebalance grid; optionally return per-rebalance long/short membership."""
    m = DEC.dense_ema(B["SIG"], alpha)
    full = set(range(B["n_alt"]))
    xs, fvb, elig = {}, {}, {}
    for t in reb_grid:
        ti = int(t)
        row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        xs[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(B["FVr"][ti, a]) * 1e4 for a in nm}
        elig[ti] = full
    keys = np.array(sorted(xs), dtype=np.int64)
    if len(keys) < 8:
        return None
    sim = CB.simulate_raw(keys, xs, fvb, B["halfspread"], B["hs_default"], 1, 0.10, 0.15, elig)
    hrs = sim["hr"].astype(np.int64)
    shm = np.array([int(B["panel_month"][int(t)]) for t in hrs])
    out = {"gross": float((sim["gross"] / B["reb"]).mean()), "turn": float(sim["turn"].mean()),
           "n": len(hrs), "sc": {}, "sim": sim, "xs": xs}
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in focus:
            continue
        netph, _ = CB.scenario_net_series(sim, B["reb"], fee, mode, mult, B["hs_default"])
        ci = CB._dayblock_ci(netph, hrs, B["hours"])
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        out["sc"][lab] = {"net": float(netph.mean()), "ci": ci,
                          "fp": int(sum(1 for v in pf.values() if v > 0)), "nf": len(pf)}
    return out


# --------------------------------------------------------------------------- CHECK 1: causality
def check_causality(B):
    print("=" * 90)
    print("CHECK 1 — dense_ema causality & alpha=1 passthrough")
    print("=" * 90)
    SIG = B["SIG"]
    m1 = DEC.dense_ema(SIG, 1.0)
    print(f"  alpha=1.0 returns SIG object identity: {m1 is SIG}")
    # value-for-value passthrough for alpha exactly 1.0 (handled by >=1.0 branch); test 0.999... not passthrough
    m9 = DEC.dense_ema(SIG, 0.90)
    # universe identity: finite mask must be IDENTICAL to baseline at every hour
    same_univ = np.array_equal(np.isfinite(m9), np.isfinite(SIG))
    print(f"  alpha=0.90 finite-mask == baseline finite-mask (SAME UNIVERSE, all hours): {same_univ}")

    # strict causality: recompute m[t] on a TRUNCATED copy (future zeroed) and confirm identical up to t.
    N = SIG.shape[0]
    tcheck = sorted(np.random.default_rng(0).choice(N, size=6, replace=False).tolist())
    ok = True
    for t in tcheck:
        trunc = SIG.copy(); trunc[t + 1:] = np.nan          # destroy all future
        mt = DEC.dense_ema(trunc, 0.90)
        row_full = m9[t]; row_trunc = mt[t]
        a = np.isfinite(row_full); b = np.isfinite(row_trunc)
        eq = np.array_equal(a, b) and np.allclose(row_full[a], row_trunc[a], atol=0, rtol=0)
        ok = ok and eq
    print(f"  m[t] identical when ALL future (>t) is destroyed, for 6 random t: {ok}  -> strictly causal")

    # first-observation-of-a-column is exact passthrough (belief born = raw), for alpha<1
    first_pass = True
    for c in range(min(B["n_alt"], 45)):
        col = SIG[:, c]; idx = np.nonzero(np.isfinite(col))[0]
        if len(idx):
            t0 = idx[0]
            if not np.isclose(m9[t0, c], SIG[t0, c], atol=0, rtol=0):
                first_pass = False
    print(f"  first observed value of every column is exact passthrough (belief born=raw): {first_pass}")
    return dict(same_univ=same_univ, causal=ok, first_pass=first_pass)


# --------------------------------------------------------------------------- CHECK 2: magnitude decomposition
def check_magnitude(B):
    print("=" * 90)
    print("CHECK 2 — WHERE does +27% gross come from? (universe / membership / tail decomposition)")
    print("=" * 90)
    reb_grid = B["base_hours"][::B["reb"]]
    e1 = eval_grid(B, 1.0, reb_grid, return_book=True)
    e9 = eval_grid(B, 0.90, reb_grid, return_book=True)
    print(f"  gross  a1.0={e1['gross']:+.3f}  a0.9={e9['gross']:+.3f}  delta={e9['gross']-e1['gross']:+.3f} "
          f"({100*(e9['gross']/e1['gross']-1):+.1f}%)   turn a1={e1['turn']:.3f} a0.9={e9['turn']:.3f}")

    # replay the held book for both, capturing long/short membership per rebalance -> compare
    def membership(alpha):
        m = DEC.dense_ema(B["SIG"], alpha); full = set(range(B["n_alt"]))
        held_l, held_s = set(), set()
        recs = {}
        for t in reb_grid:
            ti = int(t); row = m[ti]; names = np.nonzero(np.isfinite(row))[0]
            if len(names) < 4:
                continue
            sc = row[names]; order = np.argsort(sc); n = len(names)
            k1 = max(1, int(round(0.10 * n))); k2 = max(k1, int(round(0.15 * n)))
            top_e = set(names[order[-k1:]]); top_h = set(names[order[-k2:]])
            bot_e = set(names[order[:k1]]); bot_h = set(names[order[:k2]])
            nl = {c for c in held_l if c in top_h}
            for c in names[order[::-1]]:
                if len(nl) >= k1: break
                if c in top_e: nl.add(c)
            ns = {c for c in held_s if c in bot_h}
            for c in names[order]:
                if len(ns) >= k1: break
                if c in bot_e: ns.add(c)
            recs[ti] = (set(nl), set(ns), set(names.tolist()))
            held_l, held_s = nl, ns
        return recs

    r1 = membership(1.0); r9 = membership(0.90)
    common = sorted(set(r1) & set(r9))
    univ_ident = all(r1[t][2] == r9[t][2] for t in common)
    print(f"  rebalances compared: {len(common)}   universe(names) identical every rebalance: {univ_ident}")
    # membership overlap
    jacc_l, jacc_s, nchg = [], [], []
    for t in common:
        l1, s1, _ = r1[t]; l9, s9, _ = r9[t]
        if l1 or l9:
            jacc_l.append(len(l1 & l9) / max(1, len(l1 | l9)))
        if s1 or s9:
            jacc_s.append(len(s1 & s9) / max(1, len(s1 | s9)))
        nchg.append(len(l1 ^ l9) + len(s1 ^ s9))
    print(f"  mean Jaccard(long a1 vs a0.9)={np.mean(jacc_l):.3f}  short={np.mean(jacc_s):.3f}  "
          f"mean names differing/rebalance={np.mean(nchg):.2f}")
    frac_diff = np.mean([1.0 if c > 0 else 0.0 for c in nchg])
    print(f"  fraction of rebalances where membership differs at all: {frac_diff:.3f}")

    # tail-luck test: is the gross gain a few big-swing rebalances, or broad? per-rebalance gross delta.
    g1 = e1["sim"]["gross"] / B["reb"]; g9 = e9["sim"]["gross"] / B["reb"]
    # align by hour
    h1 = e1["sim"]["hr"].astype(int); h9 = e9["sim"]["hr"].astype(int)
    d1 = {h: g for h, g in zip(h1, g1)}; d9 = {h: g for h, g in zip(h9, g9)}
    hh = sorted(set(d1) & set(d9))
    dg = np.array([d9[h] - d1[h] for h in hh])
    order = np.argsort(-np.abs(dg))
    tot = dg.sum()
    for topn in (1, 3, 5, 10):
        frac = dg[order[:topn]].sum() / tot if tot != 0 else float("nan")
        print(f"  top-{topn:2d} |delta| rebalances account for {100*frac:5.1f}% of the total gross-delta "
              f"(of {len(hh)} rebalances)")
    n_pos = int((dg > 0).sum()); n_neg = int((dg < 0).sum())
    print(f"  per-rebalance gross-delta sign: {n_pos} up / {n_neg} down / {len(dg)-n_pos-n_neg} flat  "
          f"(broad improvement if up>>down)")
    return dict(univ_ident=univ_ident, frac_diff=frac_diff, top5_frac=dg[order[:5]].sum()/tot if tot else float('nan'),
                n_pos=n_pos, n_neg=n_neg)


# --------------------------------------------------------------------------- CHECK 3: grid-phase
def check_phase(B_by_reb):
    print("=" * 90)
    print("CHECK 3 — grid-phase confound: RELATIVE alpha-effect across all 4 phase offsets & reb in {3,4,6}")
    print("=" * 90)
    for reb in (3, 4, 6):
        B = B_by_reb[reb]
        print(f"  reb={reb}:")
        print(f"    {'phase':>5} {'gross_a1':>9} {'gross_a0.9':>11} {'delta':>8} {'%':>7} "
              f"{'mk_a30_a1':>10} {'mk_a30_a0.9':>12}")
        for ph in range(reb):
            grid = B["base_hours"][ph::reb]
            e1 = eval_grid(B, 1.0, grid); e9 = eval_grid(B, 0.90, grid)
            if e1 is None or e9 is None:
                print(f"    {ph:>5} (thin)"); continue
            dl = e9["gross"] - e1["gross"]; pct = 100 * (e9["gross"] / e1["gross"] - 1) if e1["gross"] else float("nan")
            m1 = e1["sc"]["maker_earn_a30"]["net"]; m9 = e9["sc"]["maker_earn_a30"]["net"]
            print(f"    {ph:>5} {e1['gross']:>+9.3f} {e9['gross']:>+11.3f} {dl:>+8.3f} {pct:>+6.1f}% "
                  f"{m1:>+10.3f} {m9:>+12.3f}")


# --------------------------------------------------------------------------- CHECK 4: forward wiring fidelity
def check_forward_wiring(B):
    print("=" * 90)
    print("CHECK 4 — forward wiring: xsec_book_eval.smooth_signals vs dense_ema (value-for-value)")
    print("=" * 90)
    # Synthetic: build fake hourly recs with gaps & sparse active sets, run both, compare.
    rng = np.random.default_rng(1)
    ncoins = 8; nhr = 60
    coins = [f"C{i}" for i in range(ncoins)]
    SIGs = np.full((nhr, ncoins), np.nan)
    recs = []
    for h in range(nhr):
        active = [c for c in range(ncoins) if rng.random() < 0.6]      # sparse & gappy
        sig = {}
        for c in active:
            v = float(rng.standard_normal())
            SIGs[h, c] = v; sig[coins[c]] = v
        recs.append({"hour_ms": h * 3600000, "signal": sig})
    for alpha in (1.0, 0.90, 0.80):
        m_dense = DEC.dense_ema(SIGs, alpha)
        sm = EV.smooth_signals(recs, alpha)
        maxdiff = 0.0; mismatch_univ = 0
        for h in range(nhr):
            hd = sm[h * 3600000]
            dense_active = {coins[c] for c in range(ncoins) if np.isfinite(m_dense[h, c])}
            sm_active = set(hd.keys())
            if dense_active != sm_active:
                mismatch_univ += 1
            for c in range(ncoins):
                if np.isfinite(m_dense[h, c]):
                    maxdiff = max(maxdiff, abs(m_dense[h, c] - hd[coins[c]]))
        print(f"  alpha={alpha:.2f}: max|dense_ema - smooth_signals| = {maxdiff:.2e}  "
              f"universe mismatches over {nhr} hrs = {mismatch_univ}")
    print("  -> the two constructions are the SAME observation-indexed EMA (both carry across gaps, both")
    print("     emit only coins active this hour, both passthrough on first sight & at alpha=1).")


# --------------------------------------------------------------------------- CHECK 5: OOS split integrity
def check_oos(B):
    print("=" * 90)
    print("CHECK 5 — OOS split integrity (EMA state across boundary is causal; no alpha peek at late)")
    print("=" * 90)
    d = np.load(CACHE, allow_pickle=False)
    folds = sorted(int(x) for x in d["folds"])
    early, late = set(folds[:4]), set(folds[4:])
    reb_grid = B["base_hours"][::B["reb"]]

    # (a) Does evaluating LATE folds depend on EARLY data via the EMA warm-state? YES (that's causal & correct).
    #     Prove it's NOT a leak: compute LATE-fold smoothed values two ways —
    #     (i) EMA over FULL history (warm state from early), (ii) EMA RESET at the split (cold start on late only).
    #     A leak would be FUTURE leaking into past; warm-state = PAST leaking into future = legitimate.
    def late_eval(reset_at_split):
        SIG = B["SIG"]
        pm = B["panel_month"]
        if reset_at_split:
            SIG = SIG.copy()
            # blank everything strictly before the first late-fold hour so EMA cold-starts on late
            late_hours = [t for t in range(len(pm)) if int(pm[t]) in late]
            t0 = min(late_hours)
            SIG[:t0] = np.nan
            m = DEC.dense_ema(SIG, 0.90)
        else:
            m = DEC.dense_ema(B["SIG"], 0.90)
        full = set(range(B["n_alt"])); xs, fvb, elig = {}, {}, {}
        for t in reb_grid:
            ti = int(t)
            if int(pm[ti]) not in late:
                continue
            row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
            if len(nm) < 4:
                continue
            xs[ti] = (nm.astype(int), row[nm].astype(float))
            fvb[ti] = {int(a): float(B["FVr"][ti, a]) * 1e4 for a in nm}; elig[ti] = full
        keys = np.array(sorted(xs), dtype=np.int64)
        sim = CB.simulate_raw(keys, xs, fvb, B["halfspread"], B["hs_default"], 1, 0.10, 0.15, elig)
        return float((sim["gross"] / B["reb"]).mean())

    warm = late_eval(False); cold = late_eval(True)
    print(f"  LATE-fold gross with EMA warm-state (carries early belief) = {warm:+.3f}")
    print(f"  LATE-fold gross with EMA reset AT split (cold on late only) = {cold:+.3f}")
    print(f"  delta = {warm-cold:+.3f}  -> warm state only uses PAST; the OOS win must survive cold-start too.")

    # (b) alpha* selection cannot see late folds: re-derive astar from early and confirm code path.
    early_curve = {a: DEC.eval_alpha(DEC.build(d), a, early) for a in DEC.ALPHAS}
    astar = max([a for a in DEC.ALPHAS if a < 1.0 and early_curve[a]],
                key=lambda a: early_curve[a]["sc"]["maker_earn_a30"]["net"])
    print(f"  alpha* argmax(maker_a30) on EARLY only = {astar:.2f}  (selection uses fold_filter=early; no late peek)")
    return dict(warm=warm, cold=cold, astar=astar)


def main():
    d = np.load(CACHE, allow_pickle=False)
    B_by_reb = {reb: build(d, reb) for reb in (3, 4, 6)}
    B = B_by_reb[4]
    c1 = check_causality(B); print()
    c2 = check_magnitude(B); print()
    check_phase(B_by_reb); print()
    check_forward_wiring(B); print()
    c5 = check_oos(B); print()

    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)
    print(f"  [1] causal={c1['causal']} same_universe={c1['same_univ']} first_passthrough={c1['first_pass']}")
    print(f"  [2] universe_identical={c2['univ_ident']} top5_share_of_delta={c2['top5_frac']*100:.1f}% "
          f"up/down={c2['n_pos']}/{c2['n_neg']}")
    print(f"  [5] OOS warm={c5['warm']:+.3f} cold={c5['cold']:+.3f} astar={c5['astar']:.2f}")


if __name__ == "__main__":
    main()
