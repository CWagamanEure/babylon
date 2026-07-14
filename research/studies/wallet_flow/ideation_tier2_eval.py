"""
ideation_tier2_eval — the two things the audit round left standing (FINDINGS.md 2026-07-11 audit entry):
  P1. MAKER FILL-RATE HAIRCUT SENSITIVITY on the fast-reb book. The convergent conclusion was that the fast-reb maker book is
      77% (reb4) → 109% (reb1) EARNED HALF-SPREAD, so the whole "faster=better" (reb1>reb2>reb4) result is gated on the passive-fill
      rate f. Model unfilled passive orders → taker fallback (pre-reg rule): cost/one-way-unit = f·(maker_fee − hs) + (1−f)·(taker_fee
      + hs); adverse-selection haircut a on gross alpha. At f=1 this IS the current maker book; at f=0 it IS the taker book — a clean
      bracket. THE question: does reb1/reb2 still beat reb4 NET at f=0.5–0.7?
  P2. The two MAKER KEEPERS from the concentration audit, tested risk-adjusted (Sharpe + per-fold sign + day-block CI, phase-avg):
      wider no-trade hold band (q2) and magnitude-weighting (soft ∝|signal| vs hard equal-weight decile).

Reuses the validated tier1 book/costing (harness reproduces the frozen baseline exactly).
    .venv/bin/python -m research.studies.wallet_flow.ideation_tier2_eval
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow.ideation_tier1_eval import (book, _dayblock_ci, _sign_test, CACHE, TAKER_FEE, MAKER_FEE)

OUT = Path("data/derived/xsec_ideation_tier2"); HRS_YEAR = 8760.0


def maker_fill_series(P, reb, f, adverse):
    """Partial-fill maker book: fraction f of each one-way trade fills PASSIVELY (earn hs), (1−f) falls back to TAKER (pay taker_fee+hs).
    adverse = gross-alpha multiplier (a30→0.7, a50→0.5). Returns per-step net-per-HOUR. f=1 ⇒ pure maker; f=0 ⇒ pure taker-impact."""
    per_unit = f * (MAKER_FEE - P["hs"] / np.maximum(P["ntrade"], 1e-9)) + (1 - f) * (TAKER_FEE + P["hs"] / np.maximum(P["ntrade"], 1e-9))
    cost = P["ntrade"] * per_unit
    return (P["gross"] * adverse - cost) / reb


def pooled_book(SIG, RA, FV, hs, hs_def, reb, panel_month, weight="equal", q1=0.10, q2=0.15):
    pool = {"hr": [], "gross": [], "ntrade": [], "hs": [], "turn": []}
    for ph in range(reb):
        s = book(SIG, RA, FV, hs, hs_def, reb, weight, q1, q2, phase=ph)
        for k in pool: pool[k].extend(s[k].tolist())
    P = {k: np.array(v, float) for k, v in pool.items()}
    return P if len(P["hr"]) >= 8 else None


def summarize(net, hrs, reb, panel_month, hours):
    shm = np.array([int(panel_month[t]) for t in hrs.astype(np.int64)])
    lo, hi = _dayblock_ci(net, hrs, hours)
    pf = {int(m): float(net[shm == m].mean()) for m in sorted(set(shm.tolist()))}
    st = _sign_test(list(pf.values()))
    per_cross = net * reb
    sr = float(per_cross.mean() / per_cross.std() * np.sqrt(HRS_YEAR / reb)) if per_cross.std() > 0 else float("nan")
    return {"net_bp_hr": float(net.mean()), "ci95": [lo, hi], "sharpe": sr,
            "folds_pos": st["pos"], "n_folds": st["n"], "sign_p": st["p"]}


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    d = np.load(CACHE, allow_pickle=True)
    R, Cc, s_inf = d["R"].astype(np.int64), d["Cc"].astype(np.int64), d["s_inf"].astype(np.float64)
    hours = d["hours"].astype(np.int64); panel_month = d["panel_month"].astype(np.int64)
    resid_alt = d["resid_alt"].astype(np.float64); hs_arr = d["hs_arr"].astype(np.float64)
    hs_def = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    hs = {i: float(hs_arr[i]) for i in range(n_alt)}
    fin = np.isfinite(s_inf)
    SIG = np.full((N, n_alt), np.nan); SIG[R[fin], Cc[fin]] = s_inf[fin]
    FV = {r: S0.fwd_sum(resid_alt, r) * 1e4 for r in (1, 2, 4)}
    results = {}

    # ---------- P1: maker fill-rate haircut sensitivity, reb ∈ {1,2,4} × f × adverse ----------
    print("================ P1 — MAKER FILL-RATE SENSITIVITY (unfilled → taker fallback; adverse a30=0.7) ================")
    print("  net bp/HR (SR, folds+); f=1 is pure maker (~100% passive fills), f=0 is pure taker. Q: does fast-reb survive partial fills?")
    print(f"  {'reb':>4} | " + " | ".join(f"f={f:<4}" for f in (1.0, 0.8, 0.6, 0.5, 0.3, 0.0)))
    adverse = 0.7
    fill_grid = (1.0, 0.8, 0.6, 0.5, 0.3, 0.0)
    for reb in (1, 2, 4):
        P = pooled_book(SIG, resid_alt, FV[reb], hs, hs_def, reb, panel_month)
        results.setdefault("P1", {})[f"reb{reb}"] = {}
        cells = []
        for f in fill_grid:
            net = maker_fill_series(P, reb, f, adverse); hrs = P["hr"]
            s = summarize(net, hrs, reb, panel_month, hours)
            results["P1"][f"reb{reb}"][f"f{f}"] = s
            star = "*" if s["ci95"][0] > 0 else ("-" if s["ci95"][1] < 0 else " ")
            cells.append(f"{s['net_bp_hr']:+5.2f}(SR{s['sharpe']:+4.1f}){s['folds_pos']}/{s['n_folds']}{star}")
        print(f"  {reb:>4} | " + " | ".join(cells))
    # break-even fill rate per reb (where net crosses 0), + is fast-reb still > reb4 at f=0.6?
    print("\n  break-even fill-rate f* (net→0) and fast-vs-reb4 at f=0.6:")
    def net_at(reb, f):
        P = pooled_book(SIG, resid_alt, FV[reb], hs, hs_def, reb, panel_month)
        return maker_fill_series(P, reb, f, adverse).mean()
    for reb in (1, 2, 4):
        fs = np.linspace(0, 1, 101); nets = np.array([net_at(reb, f) for f in fs])
        cross = fs[np.argmax(nets > 0)] if (nets > 0).any() else float("nan")
        results["P1"][f"reb{reb}"]["break_even_f"] = float(cross)
        print(f"    reb{reb}: break-even f* ≈ {cross:.2f}   net@f0.6 = {net_at(reb,0.6):+.2f}/hr")

    # ---------- P2: the two maker keepers, risk-adjusted (maker a30 = f=1 earn-spread) ----------
    print("\n================ P2 — MAKER KEEPERS risk-adjusted (maker earn-spread a30; phase-avg, per-fold sign) ================")
    print("  baseline = decile equal-weight (q1 .10 / q2 .15). Test: wider hold-band (q2) and magnitude-weight (soft ∝|signal|).")
    def maker_a30(P, reb, hrs):
        net = maker_fill_series(P, reb, 1.0, 0.7)               # f=1 pure maker earn-spread, a30
        return summarize(net, hrs, reb, panel_month, hours)
    configs = [("decile equal (base)", "equal", 0.10, 0.15),
               ("wide-band q2=0.30",   "equal", 0.10, 0.30),
               ("wide-band q2=0.40",   "equal", 0.10, 0.40),
               ("magnitude-weight",    "magnitude", 0.10, 0.15),
               ("magnitude + q2=0.30", "magnitude", 0.10, 0.30)]
    for reb in (4, 2):
        print(f"  --- reb{reb} ---")
        for tag, w, q1, q2 in configs:
            P = pooled_book(SIG, resid_alt, FV[reb], hs, hs_def, reb, panel_month, weight=w, q1=q1, q2=q2)
            if P is None: print(f"    {tag:22s} thin"); continue
            s = maker_a30(P, reb, P["hr"]); lo, hi = s["ci95"]
            results.setdefault("P2", {})[f"reb{reb}/{tag}"] = {**s, "turn": float(P["turn"].mean()), "gross_hr": float((P["gross"]/reb).mean())}
            star = "*" if lo > 0 else " "
            print(f"    {tag:22s} net {s['net_bp_hr']:+5.2f}/hr  SR {s['sharpe']:5.2f}  turn {P['turn'].mean():.2f}  "
                  f"CI[{lo:+.2f},{hi:+.2f}] {s['folds_pos']}/{s['n_folds']} p{s['sign_p']:.2f}{star}")

    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=float))
    print(f"\nwrote {OUT/'results.json'}")
    print("Read P1 as: the fill-rate f where fast-reb (reb1/2) stops beating reb4 net is the deploy-decisive threshold the live")
    print("follower must clear. P2: a keeper must lift SR (not just mean) AND hold per-fold sign to count.")


if __name__ == "__main__":
    run()
