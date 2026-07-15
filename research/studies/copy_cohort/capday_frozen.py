"""FREEZE the alt-validation universe from MAJORS-ONLY data (pre-registration; run BEFORE any alt return).

Independence guarantee (the user's warning): both the capped-PnL selection AND the scale classification are
computed strictly from the frozen majors universe — selection from data/raw/fills (majors node_fills
closed_pnl), scale from majors opening-taker episodes only. No alt data touches either. Alt markout is
therefore a genuinely external test of wallet-level skill portability.

Emits `data/derived/copy_cohort/frozen_alt_universe.json`: per test-month cohort, each wallet's
formation-window (3-mo pre-cutoff) median MAJORS opening-taker notional (`scale_usd`) and its LARGE flag
(top-half within that fold). This file is the ONLY selection/classification input the alt validation may read.

    python -m research.studies.copy_cohort.capday_frozen
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from . import base as basemod
from .base import open_base
from . import capday_book as cb
from .capday_cohort import _window_days

DAY_MS = cb.DAY_MS
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "frozen_alt_universe.json"


def _formation_scale(con, wallets: list[str], lo_day: int, cutoff_ms: int) -> dict:
    """Per wallet: median MAJORS opening-taker notional over the formation window [lo_day, cutoff)."""
    g = open_base(con)
    con.register("fs_src", {"wallet": np.asarray(wallets, dtype=str)})
    con.execute("CREATE OR REPLACE TEMP TABLE fs AS SELECT DISTINCT wallet FROM fs_src")
    con.unregister("fs_src")
    d = con.execute(f"""
      SELECT b.wallet, median(b.initial_notional_usd) AS scale_usd, count(*) AS n_form
      FROM read_parquet('{g}') b JOIN fs ON b.wallet = fs.wallet
      WHERE b.crossed_open AND NOT b.opener_flagged AND NOT b.entry_after_close
        AND b.entry_lag_s <= {cb.ENTRY_LAG_MAX_S} AND b.initial_notional_usd > 0
        AND b.open_ts >= {lo_day * DAY_MS} AND b.open_ts < {cutoff_ms}
      GROUP BY b.wallet""").fetchnumpy()
    return {w: (float(s), int(n)) for w, s, n in
            zip(d["wallet"].astype(str), d["scale_usd"], d["n_form"])}


def run() -> dict:
    con = _connect()
    sel = cb._selection()
    universe, all_wallets = {}, set()
    for f, T in enumerate(cb.FOLDS):
        lo_day, _ = _window_days(T)
        cutoff = cb._cutoff_of(T)
        cohort = sorted(sel.cohorts[f])
        fs = _formation_scale(con, cohort, lo_day, cutoff)
        scales = {w: fs[w][0] for w in cohort if w in fs}
        med = float(np.median(list(scales.values()))) if scales else None
        members = {}
        for w in cohort:
            sc = scales.get(w)
            members[w] = {"scale_usd": sc, "n_formation": (fs[w][1] if w in fs else 0),
                          "large": (sc is not None and med is not None and sc >= med)}
            all_wallets.add(w)
        universe[str(T)] = {"cutoff_ms": cutoff, "formation_lo_day": lo_day,
                            "fold_scale_median_usd": med, "members": members}

    rep = {"frozen": True, "note": "MAJORS-ONLY selection+scale; alt returns NOT consulted. Pre-registration.",
           "config": {"cap": cb.CAP, "K": cb.K, "folds": cb.FOLDS,
                      "scale_def": "median majors opening-taker notional over 3-mo formation window (pre-cutoff)",
                      "large_def": "scale >= within-fold median (top half)",
                      "selection_source": "data/raw/fills majors node_fills closed_pnl (capped-PnL/active-day)",
                      "code_commit": basemod._git_commit()},
           "n_distinct_wallets": len(all_wallets),
           "distinct_wallets": sorted(all_wallets), "universe": universe}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))
    nlarge = sum(1 for T in universe for w, m in universe[T]["members"].items() if m["large"])
    ntot = sum(len(universe[T]["members"]) for T in universe)
    print(f"FROZEN alt-validation universe: {len(all_wallets)} distinct wallets, "
          f"{ntot} wallet-fold memberships ({nlarge} large / {ntot - nlarge} small)")
    print(f"  independence: selection={rep['config']['selection_source']}")
    print(f"                scale=majors episodes only (no alt data consulted)")
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
