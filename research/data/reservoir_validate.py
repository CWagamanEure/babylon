"""Reservoir alt-flow VALIDATION GATE (RESERVOIR_ALT_FILLS_SPEC §5 + §0, adapted to the 5-min aggregate).

  (A) MAJORS reconciliation vs node_fills (FAITHFULNESS): aggregate the node_fills `fills` tape to the SAME
      per (coin, 5-min bucket, crossed) SIGNED-NOTIONAL grid and compare to `alt_flow` (summed over wallets).
      Expect ~0 diff (per-fill inputs are byte-identical; only DEC(38,6) rounding differs).
  (B) ALT-SIDE completeness (ALL coins): two-sided invariant Σ flow_signed ≈ 0 per coin (both counterparties);
      non-empty; intra-day coverage (bucket span).

    python -m research.data.reservoir_validate 20260601        # a day present in BOTH sources
"""
from __future__ import annotations
import sys
from research.data.db import connect
from research.data import schema

MAJORS = schema.MAJORS
BUCKET_MS = 300_000
REL_TOL = 1e-4


def reconcile_majors(con, day: int):
    print(f"\n=== (A) MAJORS reconciliation vs node_fills (5-min signed-notional grid) — day {day} ===")
    inlist = "('" + "','".join(MAJORS) + "')"
    print(f"  {'coin':>5} {'cells':>8} {'maxAbsΔ$':>12} {'maxRelΔ':>10} {'Σsign nf':>14} {'Σsign af':>14}")
    allok = True
    for coin in MAJORS:
        r = con.execute(f"""
            WITH nf AS (
              SELECT (ts - ts%{BUCKET_MS}) AS bucket, crossed,
                     sum(CASE WHEN side='B' THEN notional_usd ELSE -notional_usd END)::DOUBLE AS f
              FROM fills WHERE day={day} AND coin='{coin}' GROUP BY bucket, crossed),
            af AS (
              SELECT bucket, crossed, sum(flow_signed)::DOUBLE AS f
              FROM alt_flow WHERE day={day} AND coin='{coin}' GROUP BY bucket, crossed)
            SELECT count(*),
                   max(abs(COALESCE(nf.f,0)-COALESCE(af.f,0))),
                   max(abs(COALESCE(nf.f,0)-COALESCE(af.f,0)) / (abs(COALESCE(nf.f,0))+1)),
                   sum(COALESCE(nf.f,0)), sum(COALESCE(af.f,0))
            FROM nf FULL OUTER JOIN af USING (bucket, crossed)""").fetchone()
        cells, maxabs, maxrel, snf, saf = r
        ok = (maxrel or 0) < REL_TOL
        allok &= ok
        print(f"  {coin:>5} {cells:>8,} {float(maxabs or 0):>12.2f} {float(maxrel or 0):>10.2e} "
              f"{float(snf or 0):>14.0f} {float(saf or 0):>14.0f}" + ("" if ok else "  <-- MISMATCH"))
    print(f"  => majors {'RECONCILE' if allok else 'MISMATCH — investigate'} (rel tol {REL_TOL})")
    return allok


def alt_asserts(con, day: int):
    print(f"\n=== (B) ALT-SIDE completeness (ALL coins) — day {day} ===")
    ok = True
    r = con.execute(f"""
        WITH per AS (SELECT coin, sum(flow_signed) AS signed, max(bucket) AS bmax, min(bucket) AS bmin
                     FROM alt_flow WHERE day={day} GROUP BY coin)
        SELECT count(*), max(abs(signed)), max(bmax), min(bmin) FROM per""").fetchone()
    ncoins, maxsigned, bmax, bmin = r
    # two-sided: Σ flow_signed per coin ≈ 0 (both counterparties). tolerance scales with notional (~$ per coin).
    t1 = float(maxsigned or 0) < 1.0                       # sub-dollar residual from DOUBLE summation
    ok &= t1
    print(f"  1. two-sided: {ncoins} coins; max|Σ flow_signed|=${float(maxsigned or 0):.4f}  "
          f"[{'PASS' if t1 else 'FAIL'}]")
    ds = int(con.execute(f"SELECT epoch_ms(strptime('{day}', '%Y%m%d'))").fetchone()[0])
    lead = (bmin - ds) / 60000.0
    lag = (ds + 86400000 - bmax) / 60000.0
    t2 = lead < 15 and lag < 15
    ok &= t2
    print(f"  2. coverage: first bucket +{lead:.1f}min from 00:00, last bucket -{lag:.1f}min from 24:00  "
          f"[{'PASS' if t2 else 'FAIL (partial day?)'}]")
    nrows = con.execute(f"SELECT count(*) FROM alt_flow WHERE day={day}").fetchone()[0]
    t3 = nrows > 0
    ok &= t3
    print(f"  3. non-empty: {nrows:,} agg rows  [{'PASS' if t3 else 'FAIL'}]")
    print(f"  => alt-side {'ALL PASS' if ok else 'FAILED — investigate'}")
    return ok


def run(day: int):
    con = connect(warn_missing=False)
    if not con.execute(f"SELECT count(*) FROM alt_flow WHERE day={day}").fetchone()[0]:
        print(f"[validate] no alt_flow rows for day {day} — ingest it first")
        return 2
    a = reconcile_majors(con, day)
    b = alt_asserts(con, day)
    print(f"\n=== GATE {'PASS' if (a and b) else 'FAIL'} (majors faithful={a}, alt-side complete={b}) ===")
    con.close()
    return 0 if (a and b) else 1


if __name__ == "__main__":
    raise SystemExit(run(int(sys.argv[1]) if len(sys.argv) > 1 else 20260601))
