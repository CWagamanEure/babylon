"""Tier-2 μ baseline PRIMITIVE — per-minute unconditional forward returns (cutoff-independent, R2).

For every price minute t (a "pseudo-entry"), fwd_ret_<h>(t) = (P(t+h) − P(t))/P(t)·1e4, using the SAME
backward-ASOF + ≤90s staleness rule as the markout backfill (so μ and markout are measured on one ruler).
This is the ONLY μ artifact stored; it carries NO cutoff. The aggregation layer derives every baseline from it:
  μ_h(coin, ≤C)        = mean(fwd_ret_h) over minutes with (t + h) ≤ C          -- global (timing+selection)
  μ_h(coin, week, ≤C)  = mean(fwd_ret_h) over minutes in that ISO week with (t+h) ≤ C   -- weekly (intra-week)
The `(t+h) ≤ C` filter (applied at aggregation) is what makes the baseline leakage-safe AND correctly truncates
the straddle week (R2/R10). Direction-neutral by construction: timing_alpha = raw_markout − dir_sign·μ_h.

    python -m research.data.mu_baseline all      # ~seconds/coin (478k minutes each)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from .markout import (_connect, _price_view, HORIZONS, STALE_MS, COINS, REPO_ROOT)

OUT_DIR = REPO_ROOT / "data" / "derived" / "fwd_returns"
MU_SCHEMA_VERSION = "mu_baseline_v1_fwdret_2026-07-08"


def _fwd_sql() -> str:
    """One backward-ASOF per horizon off the price grid itself; fwd_ret NULL if t+h has no tick within 90s (R6)
    or runs past the last tick (data-availability censor — the ≤C censor is applied later at aggregation)."""
    joins, cols = [], []
    for name, h in HORIZONS.items():
        a = f"f_{name}"
        joins.append(f"ASOF JOIN px {a} ON (base.ts + {h}) >= {a}.ts")
        ph = f"CASE WHEN (base.ts + {h}) - {a}.ts <= {STALE_MS} THEN {a}.p END"
        cols.append(f"CASE WHEN (base.ts + {h}) - {a}.ts <= {STALE_MS} "
                    f"THEN (({ph}) - base.p)/base.p * 1e4 END AS fwd_ret_{name}")
    return f"""
      SELECT base.ts,
             strftime(make_timestamp(base.ts*1000), '%G%V') AS iso_week,
             {', '.join(cols)}
      FROM px base {' '.join(joins)}"""


def build_coin(con, coin: str) -> int:
    _price_view(con, coin)
    out = OUT_DIR / f"coin={coin}" / "part.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    con.execute(f"COPY ({_fwd_sql()}) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)")
    import os
    os.replace(tmp, out)
    return con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]


if __name__ == "__main__":
    con = _connect(); t0 = time.time()
    for c in (COINS if len(sys.argv) < 2 or sys.argv[1] == "all" else [sys.argv[1]]):
        tm = time.time(); n = build_coin(con, c)
        print(f"  fwd_returns {c}: {n:,} minutes  {time.time()-tm:.0f}s", flush=True)
    (OUT_DIR / "_MU_META.json").write_text(f'{{"mu_schema_version":"{MU_SCHEMA_VERSION}"}}')
    print(f"=== mu baseline done {time.time()-t0:.0f}s -> {OUT_DIR} ===")
