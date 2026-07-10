"""alt_universe — point-in-time liquid-alt universe for the alt-breadth cohort study.

Per ALT_BREADTH_AUDIT_RESPONSE (binding): `day_ntl_vlm` is TRAILING-24h ROLLING (NOT cumulative) → the ADV
proxy for a coin-day is the LAST per-minute snapshot of that day (`row_number ORDER BY ts DESC = 1`), NEVER
max(). At formation day t, rank coins by the mean of that daily snapshot over the 30 PRIOR days (all < t; no
look-ahead), require ≥30 days of listing history, take those above a $ floor. Membership is re-ranked per
formation date (time-varying → no survivorship). Drop 3 low-book-coverage names (LAUNCHCOIN, MKR, AI16Z).

    .venv/bin/python -m research.studies.wallet_flow.alt_universe 20260301   # reproduce a formation-date universe
"""
from __future__ import annotations
import sys
import datetime as dt
from research.data.db import connect

FLOOR_USD = 2_000_000          # trailing-ADV floor (auditor: $2M → 49 names, $1M → 70)
LOOKBACK_DAYS = 30
MIN_HISTORY_DAYS = 30
MAJORS = ("BTC", "ETH", "SOL", "HYPE")
DROP_COVERAGE = ("LAUNCHCOIN", "MKR", "AI16Z")   # <90% impact-book coverage → undefined cost


def _daily_adv(con):
    """Per (coin, day): last-snapshot day_ntl_vlm (the true trailing-24h boundary value) + a listing-day count.
    Cached as a TEMP table; reused across formation dates."""
    con.execute("""CREATE OR REPLACE TEMP TABLE alt_adv AS
        WITH eod AS (
            SELECT coin, day, day_ntl_vlm,
                   row_number() OVER (PARTITION BY coin, day ORDER BY ts DESC) AS rn
            FROM asset_ctx)
        SELECT coin, day, day_ntl_vlm AS adv FROM eod WHERE rn = 1""")


def universe(con, formation_day: int, floor_usd: float = FLOOR_USD, include_majors: bool = False) -> list[str]:
    """Coins eligible at formation_day: mean(last-snapshot day_ntl_vlm) over the 30 prior calendar days,
    ≥ floor, with ≥MIN_HISTORY_DAYS of prior history. days are integer YYYYMMDD; convert to ordinal for the
    trailing window so month/day boundaries are handled correctly."""
    if not con.execute("SELECT 1 FROM information_schema.tables WHERE table_name='alt_adv'").fetchone():
        _daily_adv(con)
    fd = dt.datetime.strptime(str(formation_day), "%Y%m%d").date()
    lo = int((fd - dt.timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d"))
    hi = int(fd.strftime("%Y%m%d"))                          # STRICTLY < formation day (exclusive upper)
    rows = con.execute(f"""
        SELECT coin, avg(adv) AS mean_adv, count(*) AS ndays
        FROM alt_adv WHERE day >= {lo} AND day < {hi}
        GROUP BY coin HAVING count(*) >= {MIN_HISTORY_DAYS} AND avg(adv) >= {floor_usd}
        ORDER BY mean_adv DESC""").fetchall()
    names = [r[0] for r in rows]
    if not include_majors:
        names = [c for c in names if c not in MAJORS]
    return [c for c in names if c not in DROP_COVERAGE]


if __name__ == "__main__":
    day = int(sys.argv[1]) if len(sys.argv) > 1 else 20260301
    con = connect(warn_missing=False)
    _daily_adv(con)
    for floor, tag in ((2_000_000, "$2M"), (1_000_000, "$1M")):
        u = universe(con, day, floor_usd=floor, include_majors=True)
        alts = [c for c in u if c not in MAJORS]
        print(f"formation {day}, floor {tag}: {len(u)} incl-majors, {len(alts)} alts")
        print("  top 20:", u[:20])
    print("\n(auditor reproduced: $2M → 49 names, $1M → 70, on 2026-03-01)")
