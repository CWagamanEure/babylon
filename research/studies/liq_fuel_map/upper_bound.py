"""Upper-bound test: does the REALIZED liquidation-cascade reaction clear cost at per-minute resolution?

The audit's decisive gate. Using the *realized* cascade minute (perfect timing) is strictly more informed
than any *anticipated* fuel map, so this UPPER-BOUNDS the whole program: if a perfectly-timed reaction to
actual liquidations doesn't beat stressed cost, the (noisier) anticipation engine cannot. Builds no engine.

Signal per coin-minute from is_liq_origin fills:
  forced-SELL notional = long liqs (dir='Close Long', a forced sell → down pressure)
  forced-BUY  notional = short liqs (dir='Close Short', a forced buy → up pressure)
  net_forced = fb - fs      (<0 = net forced selling);   d = sign(net_forced)
Overshoot-revert (the fade edge): revert_h = -d * fwd_oracle_return(h)  (>0 = price reverts AGAINST the
forced push). Pre-drift (magnet): d * trailing_return  (>0 = price drifted WITH the push into the event).
Cost = contemporaneous (stressed) impact spread + 2x taker fee. Entry generously at oracle(t) (perfect
timing), exit oracle(t+h) — an upper bound. liq_mark_px NEVER used (edge3 scar).

  .venv/bin/python -m research.studies.liq_fuel_map.upper_bound build     # heavy scan -> out/liq_flow_by_min.parquet
  .venv/bin/python -m research.studies.liq_fuel_map.upper_bound analyze    # light -> prints the verdict table
"""
import os
import polars as pl
from research.data.db import connect

MAJORS = ("BTC", "ETH", "SOL", "HYPE")
MONTHS = [202508, 202509, 202510, 202511, 202512,
          202601, 202602, 202603, 202604, 202605, 202606]
OUT = os.path.join(os.path.dirname(__file__), "out", "liq_flow_by_min.parquet")
TAKER_FEE_BP = 4.5   # research.lib.cost DEFAULT taker; round-trip fee = 2x


def build():
    """One heavy pass, month-looped (bounded scans), -> per (coin, minute) forced sell/buy notional."""
    if os.path.exists(OUT):
        print(f"[build] {OUT} exists — skipping (delete to rebuild)")
        return
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='2500MB'; SET threads=2")
    frames = []
    for m in MONTHS:
        q = f"""
        SELECT coin, (ts - ts % 60000) AS minute_ts,
          sum(CASE WHEN dir='Close Long'  THEN notional_usd ELSE 0 END) AS fs_notional,
          sum(CASE WHEN dir='Close Short' THEN notional_usd ELSE 0 END) AS fb_notional,
          count(*) AS n_liq
        FROM fills
        WHERE month = {m} AND coin IN ('BTC','ETH','SOL','HYPE') AND is_liq_origin
        GROUP BY coin, minute_ts
        """
        df = con.execute(q).pl()
        frames.append(df)
        print(f"[build] {m}: {df.height} cascade-minutes")
    out = pl.concat(frames).sort(["coin", "minute_ts"])
    out.write_parquet(OUT)
    print(f"[build] wrote {out.height} rows -> {OUT}")


def analyze():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='2500MB'; SET threads=2")
    con.execute(f"CREATE OR REPLACE VIEW flow AS SELECT * FROM read_parquet('{OUT}')")
    sql = """
    WITH ctx AS (   -- dedupe asset_ctx to one row per coin-minute
      SELECT coin, (ts - ts % 60000) AS m,
             any_value(oracle_px) oracle, any_value(mid_px) mid,
             any_value(impact_bid_px) ib, any_value(impact_ask_px) ia
      FROM asset_ctx WHERE coin IN ('BTC','ETH','SOL','HYPE') AND mid_px>0
      GROUP BY coin, (ts - ts % 60000)
    ),
    w AS (
      SELECT coin, m, oracle, (ia-ib)/mid*1e4 AS spread_bp,
        LEAD(oracle,1)  OVER(PARTITION BY coin ORDER BY m) o1,  LEAD(m,1)  OVER(PARTITION BY coin ORDER BY m) m1,
        LEAD(oracle,5)  OVER(PARTITION BY coin ORDER BY m) o5,  LEAD(m,5)  OVER(PARTITION BY coin ORDER BY m) m5,
        LEAD(oracle,15) OVER(PARTITION BY coin ORDER BY m) o15, LEAD(m,15) OVER(PARTITION BY coin ORDER BY m) m15,
        LEAD(oracle,30) OVER(PARTITION BY coin ORDER BY m) o30, LEAD(m,30) OVER(PARTITION BY coin ORDER BY m) m30,
        LAG(oracle,15)  OVER(PARTITION BY coin ORDER BY m) opre, LAG(m,15) OVER(PARTITION BY coin ORDER BY m) mpre
      FROM ctx
    ),
    j AS (
      SELECT f.coin, f.minute_ts AS m, (f.minute_ts//86400000) AS day, f.fs_notional+f.fb_notional AS gross,
        sign(f.fb_notional - f.fs_notional) AS d, w.spread_bp,
        CASE WHEN w.m1-f.minute_ts  BETWEEN 55000 AND 65000     THEN (w.o1/w.oracle-1)*1e4 END  r1,
        CASE WHEN w.m5-f.minute_ts  BETWEEN 240000 AND 360000   THEN (w.o5/w.oracle-1)*1e4 END  r5,
        CASE WHEN w.m15-f.minute_ts BETWEEN 840000 AND 960000   THEN (w.o15/w.oracle-1)*1e4 END r15,
        CASE WHEN w.m30-f.minute_ts BETWEEN 1680000 AND 1920000 THEN (w.o30/w.oracle-1)*1e4 END r30,
        CASE WHEN f.minute_ts-w.mpre BETWEEN 840000 AND 960000  THEN (w.oracle/w.opre-1)*1e4 END rpre
      FROM flow f JOIN w ON f.coin=w.coin AND f.minute_ts=w.m
    ),
    ranked AS (SELECT *, ntile(10) OVER (PARTITION BY coin ORDER BY gross) decile FROM j WHERE d != 0)
    SELECT coin,
      count(*)                             AS n_top_cascades,
      round(avg(gross)/1e6,3)              AS mean_gross_Musd,
      round(avg(spread_bp),3)              AS mean_spread_bp,
      round(avg(d*rpre),3)                 AS predrift_15m_bp,   -- magnet: >0 drifts WITH push into event
      round(avg(-d*r1),3)                  AS revert_1m_bp,      -- fade edge (gross), >0 = reverts against push
      round(avg(-d*r5),3)                  AS revert_5m_bp,
      round(avg(-d*r15),3)                 AS revert_15m_bp,
      round(avg(-d*r30),3)                 AS revert_30m_bp,
      round(avg(spread_bp)+2*4.5,2)        AS roundtrip_cost_bp  -- stressed spread + 2x taker
    FROM ranked WHERE decile=10
    GROUP BY coin ORDER BY coin
    """
    print("=== UPPER BOUND: realized top-decile cascade reaction, majors (gross bp vs cost) ===")
    print(con.sql(sql))
    print("\nRead: revert_* is the GROSS reversion captured with PERFECT cascade timing. Compare to "
          "roundtrip_cost_bp.\npredrift>0 = magnet (price drawn in). Net edge = revert - roundtrip_cost. "
          "If revert < cost on the best coin (SOL), the anticipation engine cannot clear it either.")


if __name__ == "__main__":
    import sys
    {"build": build, "analyze": analyze}[sys.argv[1] if len(sys.argv) > 1 else "analyze"]()
