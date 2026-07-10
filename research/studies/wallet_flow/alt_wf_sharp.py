"""alt_wf_sharp — the decisive disambiguator: walk-forward at the SHARP cohort knob (anti-ratchet obligation).

The pooled placebo revives when the cohort sharpens (top-2%/1% clear, p=.035/.020) — but that is an argmax over 5
Q-values AND the walk-forward that returned "no consistent lift" was run at the DILUTED Q=0.20. If the sharp-cohort
pass is a real edge it must REPLICATE across time folds at the sharp knob; if it's small-K selection variance it
won't. This runs the forward-month folds at Q in {0.02, 0.01}. PASS = folds consistently positive (sign test) with
the sharp knob; FAIL = the sweep's top-2% was an argmax fluke → the negative is earned at the hypothesis level.

    .venv/bin/python -m research.studies.wallet_flow.alt_wf_sharp
"""
from __future__ import annotations
import functools
import numpy as np
from math import comb
from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import alt_confirm as C

print = functools.partial(print, flush=True)
SHARP_QS = (0.05, 0.02, 0.01)
KF = 400


def main():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duckspill'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    coins = list(A.FACTORS) + A.universe(con, A.UNIV_FORMATION, include_majors=False)
    panel = A.build_resid(con, coins); A.build_cohort_tables(con, coins); A.register_resid(con, panel)
    print("[ready] walk-forward at sharp cohort knobs\n")
    for q in SHARP_QS:
        A.COHORT_Q = q            # _placebo reads A.COHORT_Q live
        print(f"=== Q = {q:.0%} ===")
        zs = []
        for m in C.FOLDS:
            emb = int(con.execute(f"SELECT min(h) FROM aresid WHERE month={m}").fetchone()[0]) - A.H*3600000
            pool_m, al_m = C._pool_alignment(con, m, emb)
            Dm = C._cells_and_flow(con, f"r.month = {m}", f"wb.mth = {m}")
            inf, mu, sd, z, p = C._placebo(Dm, pool_m, al_m, KF, C.SEED + m)
            zs.append(z)
            print(f"  {m}: informed {inf:+.4f}  random {mu:+.4f}±{sd:.4f}  z={z:+.2f}  p={p:.4f}")
        zs = np.array(zs); npos = int((zs > 0).sum())
        p_sign = sum(comb(len(zs), i) for i in range(npos, len(zs)+1)) / 2**len(zs)
        print(f"  --> {npos}/{len(zs)} folds informed>random, sign-test p={p_sign:.3f}, mean z={zs.mean():+.2f}, "
              f"min z={zs.min():+.2f}\n")


if __name__ == "__main__":
    main()
