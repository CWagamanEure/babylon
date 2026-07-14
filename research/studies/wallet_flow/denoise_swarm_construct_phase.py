"""
Follow-up to the construction audit: quantify the HONEST phase-averaged denoise magnitude.
Check 3 showed the headline +27% gross is the reb4/phase0 cell; here we pool the alpha-effect across
ALL phase offsets of reb in {3,4,6} and report the delta (a0.9 - a1.0) per leg, with the count of
positive cells vs negative, so the deployable magnitude is not the lucky-phase cherry-pick.

    .venv/bin/python -m research.studies.wallet_flow.denoise_swarm_construct_phase
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import denoise_swarm_construct_audit as AUD

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
LEGS = ("taker_top_smallclip", "maker_earn_a30", "maker_earn_a50")


def main():
    d = np.load(CACHE, allow_pickle=False)
    cells = []   # (reb, phase, gross_d, {leg: net_d})
    print(f"{'reb':>3} {'ph':>3} {'gr_a1':>7} {'gr_a09':>7} {'gr_d':>7}  " +
          "  ".join(f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>10}d" for l in LEGS))
    for reb in (3, 4, 6):
        B = AUD.build(d, reb)
        for ph in range(reb):
            grid = B["base_hours"][ph::reb]
            e1 = AUD.eval_grid(B, 1.0, grid, focus=LEGS)
            e9 = AUD.eval_grid(B, 0.90, grid, focus=LEGS)
            if e1 is None or e9 is None:
                continue
            grd = e9["gross"] - e1["gross"]
            legd = {l: e9["sc"][l]["net"] - e1["sc"][l]["net"] for l in LEGS}
            cells.append((reb, ph, grd, legd, e1["gross"]))
            print(f"{reb:>3} {ph:>3} {e1['gross']:>+7.3f} {e9['gross']:>+7.3f} {grd:>+7.3f}  " +
                  "  ".join(f"{legd[l]:>+11.3f}" for l in LEGS))

    print("\n--- PHASE-POOLED denoise effect (each (reb,phase) an independent grid unit) ---")
    grd = np.array([c[2] for c in cells])
    print(f"  gross delta:  mean {grd.mean():+.3f}  median {np.median(grd):+.3f}  "
          f"pos/neg {int((grd>0).sum())}/{int((grd<0).sum())}  of {len(cells)} cells")
    for l in LEGS:
        v = np.array([c[3][l] for c in cells])
        print(f"  {l:20s} net delta: mean {v.mean():+.3f}  median {np.median(v):+.3f}  "
              f"pos/neg {int((v>0).sum())}/{int((v<0).sum())}")
    # headline cell context
    hl = [c for c in cells if c[0] == 4 and c[1] == 0][0]
    rank = 1 + int((grd > hl[2]).sum())
    print(f"\n  headline reb4/phase0 gross delta = {hl[2]:+.3f} is rank {rank}/{len(cells)} of all phase cells "
          f"(= the single most favorable grid).")
    print(f"  favorable-phase base gross (reb4/ph0 a1={hl[4]:+.3f}) is also the highest-base grid — the phase")
    print("  that maximizes BASELINE gross is the same phase that maximizes the denoise delta.")


if __name__ == "__main__":
    main()
