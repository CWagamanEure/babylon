"""
kalman_swarm_steelman_confirm — pin down the mild-LEVEL-EMA interior optimum found by the smoothing sweep.
Confirms: (a) the hump is smooth across a fine alpha grid (not a knife-edge cell); (b) per-fold sign at the
peak; (c) whether it survives joint with reb; (d) mid-dispersion regime. All strictly causal (ema uses <=t).
    .venv/bin/python -m research.studies.wallet_flow.kalman_swarm_steelman_confirm
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow.kalman_swarm_steelman_smoothing import (
    eval_book, SIG, ema_smooth, FOCUS, HDR, fmt)

def main():
    print("legend: net[CIlo,CIhi]folds+  *=CI>0  -=CI<0  sh=step-Sharpe\n")

    print("="*60, "\nA. FINE ALPHA on LEVEL EMA (reb4, all regime) — is the hump smooth?\n", "="*60)
    print(HDR)
    print("baseline a1.00         ", fmt(eval_book(SIG, 4)))
    for alpha in (0.95, 0.93, 0.91, 0.90, 0.89, 0.88, 0.87, 0.85, 0.83, 0.80):
        print(f"level a{alpha:<5}          ", fmt(eval_book(ema_smooth(SIG, alpha, 24), 4)))
    print()

    print("="*60, "\nB. PER-FOLD detail at the peak (level a0.90 vs baseline)\n", "="*60)
    for lab in FOCUS:
        b = eval_book(SIG, 4)["scenarios"][lab]["per_fold"]
        p = eval_book(ema_smooth(SIG, 0.90, 24), 4)["scenarios"][lab]["per_fold"]
        months = sorted(b)
        print(f"{lab:>20}: base ", " ".join(f"{m%100:02d}:{b[m]:+5.1f}" for m in months))
        print(f"{'':>20}  a.90 ", " ".join(f"{m%100:02d}:{p[m]:+5.1f}" for m in months))
    print()

    print("="*60, "\nC. LEVEL-EMA a0.90 x rebalance horizon\n", "="*60)
    print(HDR)
    for reb in (3, 4, 6, 8):
        print(f"reb{reb} fresh            ", fmt(eval_book(SIG, reb)))
        print(f"reb{reb} level a0.90      ", fmt(eval_book(ema_smooth(SIG, 0.90, 24), reb)))
        print()

    print("="*60, "\nD. MID-dispersion regime x level EMA\n", "="*60)
    print(HDR)
    print("mid fresh              ", fmt(eval_book(SIG, 4, regime="mid")))
    for alpha in (0.92, 0.90, 0.88, 0.85):
        print(f"mid level a{alpha:<5}      ", fmt(eval_book(ema_smooth(SIG, alpha, 24), 4, regime="mid")))
    print()

if __name__ == "__main__":
    main()
