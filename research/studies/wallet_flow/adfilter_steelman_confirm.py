"""
adfilter_steelman_confirm — focused second pass: is there ANY robust config where the ADAPTIVE-R filter
beats the FIXED alpha=0.90 EMA (not just the naive baseline)? Plus a WHERE-does-it-differ decomposition.

(1) Finer floor grid near fixed (lo in {0.82,0.85,0.88}) x steepness k in {0.7,1.5} x observable, phase-avg
    reb4, paired (ADAPT - FIXED) maker_a30 + taker_smallclip with day-CI + a phase-x-fold pooled sign test.
(2) Decomposition: split rebalance hours into STRONG vs WEAK signal-strength halves (causal, early-frozen
    median). In strong hours the adaptive filter uses alpha~1 (no smooth) while fixed uses 0.90 — does baseline
    (a=1) beat fixed there (i.e., is fixed PAYING a dilution cost adaptive avoids)? In weak hours does extra
    smoothing help? This is the mechanism test for whether adaptive CAN have headroom over the scalar EMA.

    .venv/bin/python -m research.studies.wallet_flow.adfilter_steelman_confirm
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import adfilter_steelman_book as BK

P = BK.load()
SIG = P["SIG"]; folds = P["folds"]; early = set(folds[:4]); late = set(folds[4:])
m_base = SIG; m_fixed = BK.dense_ema_scalar(SIG, 0.90)
books_base = BK.phase_book(P, m_base, 4); books_fixed = BK.phase_book(P, m_fixed, 4)


def pooled_phasefold_sign(P, books_a, books_b, lab, fold_filter=None):
    """Each (phase,fold) cell is a semi-independent unit; sign test on the paired (a-b) mean per cell."""
    pm = P["panel_month"]; units = []
    for ba, bb in zip(books_a, books_b):
        na, nb = ba["net"][lab], bb["net"][lab]
        common = [int(h) for h in ba["hrs"] if int(h) in nb and (fold_filter is None or int(pm[int(h)]) in fold_filter)]
        if not common: continue
        months = np.array([int(pm[h]) for h in common]); diff = np.array([na[h] - nb[h] for h in common])
        for mm in sorted(set(months.tolist())):
            v = diff[months == mm]
            if len(v) >= 3: units.append(float(v.mean()))
    if not units: return None
    st = ADJ.sign_test(units)
    return {"n_units": len(units), "pos": int(sum(1 for u in units if u > 0)), "p": st["p"],
            "mean": float(np.mean(units))}


print("=" * 100)
print("(1) FINE floor grid near fixed 0.90 — paired (ADAPT - FIXED0.90), phase-avg reb4")
print("    metric: mk_a30 lift[day-CI] | tk_sc lift | phase*fold sign(pos/n,p) — ALL folds then OOS-LATE")
print("=" * 100)
best = None
for which in ("absmed", "sigma", "combo"):
    for lo in (0.82, 0.85, 0.88):
        for k in (0.7, 1.5):
            alpha_t = BK.build_alpha(SIG, P["panel_month"], early, which, lo, 1.00, k=k)
            m_ad = BK.dense_ema_perhour(SIG, alpha_t)
            bk = BK.phase_book(P, m_ad, 4)
            pf_all = BK.paired_phaseavg(P, bk, books_fixed)
            pf_late = BK.paired_phaseavg(P, bk, books_fixed, late)
            sgn_all = pooled_phasefold_sign(P, bk, books_fixed, "maker_earn_a30")
            m30 = pf_all["maker_earn_a30"]; tsc = pf_all["taker_top_smallclip"]; m30L = pf_late["maker_earn_a30"]
            print(f"  {which:6s} lo{lo} k{k}: ALL mk_a30 {BK.fmt_pair(m30)}  tk_sc {m30 and BK.fmt_pair(tsc)}")
            print(f"  {'':17s}  LATE mk_a30 {BK.fmt_pair(m30L)}  | sign(all) {sgn_all['pos']}/{sgn_all['n_units']} p={sgn_all['p']:.2f} mean{sgn_all['mean']:+.3f}")
            score = m30["lift"] + m30L["lift"]
            if best is None or score > best[0]:
                best = (score, which, lo, k, m30, m30L)
print(f"\n  best-by(ALL+LATE mk_a30 lift over fixed): {best[1]} lo{best[2]} k{best[3]}  "
      f"ALL {best[4]['lift']:+.3f} LATE {best[5]['lift']:+.3f}")

# --------------------------------------------------------------------------- (2) decomposition
print("\n" + "=" * 100)
print("(2) STRONG vs WEAK hour decomposition (causal, early-frozen median of absmed signal strength)")
print("    Q: in STRONG hours does baseline(a=1) BEAT fixed(0.90)?  (if yes, adaptive alpha~1 there has headroom)")
print("=" * 100)
o = BK.obs_series(SIG, "absmed")
emask = np.array([int(P["panel_month"][t]) in early and np.isfinite(o[t]) for t in range(len(o))])
thr = np.median(o[emask])
strong = set(t for t in range(len(o)) if np.isfinite(o[t]) and o[t] >= thr)
print(f"  early-median absmed threshold = {thr:.4f}")

def subset_net(books, lab, hourset):
    pm = P["panel_month"]; phase_means = []
    for b in books:
        na = b["net"][lab]; hh = [int(h) for h in b["hrs"] if int(h) in hourset]
        if len(hh) >= 8: phase_means.append(np.mean([na[h] for h in hh]))
    return float(np.mean(phase_means)) if phase_means else np.nan

allh = set(range(len(o)))
weak = allh - strong
for lab in ("maker_earn_a30", "taker_top_smallclip"):
    print(f"  -- {lab} (phase-avg net) --")
    for name, hs in (("STRONG", strong), ("WEAK", weak)):
        nb = subset_net(books_base, lab, hs); nf = subset_net(books_fixed, lab, hs)
        verdict = "baseline>fixed (fixed over-smooths here)" if nb > nf else "fixed>=baseline (smoothing helps here)"
        print(f"     {name:6s}: baseline {nb:+.3f}   fixed0.90 {nf:+.3f}   delta(base-fix) {nb-nf:+.3f}  -> {verdict}")
