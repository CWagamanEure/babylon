"""ANTICIPATION test: does the standing fuel imbalance predict the forward move toward the heavier side?

The actual test of the user's system (not the reaction). signal = (fuel_below - fuel_above)/(sum) in [-1,1];
>0 = more loaded fuel BELOW spot -> magnet thesis predicts DOWNWARD drift -> forward return should be NEGATIVE
-> corr(fwd_ret, signal) < 0. Reports corr + top/bottom-decile forward return (the tradable long/short
spread) at several horizons, GROSS (net-of-cost read is in the spread vs ~cost). Honest OOS: pick the sign on
TRAIN (first 8 months), report the held-out TEST (last 3) separately.

  .venv/bin/python -m research.studies.liq_fuel_map.analyze_signal SOL
"""
import os
import sys
from research.data.db import connect

SPLIT_M = 202604   # train < SPLIT, test >= SPLIT (last 3 months held out)


def analyze(coin):
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='2500MB'; SET threads=2")
    path = os.path.join(os.path.dirname(__file__), "out", f"fuel_series_{coin}.parquet")
    con.execute(f"CREATE OR REPLACE VIEW fs AS SELECT *, "
                f"(fuel_below-fuel_above)/(fuel_below+fuel_above+1) AS sig FROM read_parquet('{path}')")
    sql = f"""
    WITH ctx AS (SELECT (ts-ts%60000) m, any_value(oracle_px) px FROM asset_ctx
                 WHERE coin='{coin}' AND oracle_px>0 GROUP BY (ts-ts%60000)),
    w AS (SELECT m, px,
       LEAD(px,15) OVER(ORDER BY m) p15, LEAD(m,15) OVER(ORDER BY m) t15,
       LEAD(px,30) OVER(ORDER BY m) p30, LEAD(m,30) OVER(ORDER BY m) t30,
       LEAD(px,60) OVER(ORDER BY m) p60, LEAD(m,60) OVER(ORDER BY m) t60 FROM ctx),
    j AS (SELECT fs.sig, fs.n_open,
       CASE WHEN year(to_timestamp(fs.snap_m/1000))*100 + month(to_timestamp(fs.snap_m/1000)) >= {SPLIT_M}
            THEN 'test' ELSE 'train' END AS split,
       CASE WHEN w.t15-w.m BETWEEN 840000 AND 960000     THEN (w.p15/w.px-1)*1e4 END r15,
       CASE WHEN w.t30-w.m BETWEEN 1740000 AND 1860000   THEN (w.p30/w.px-1)*1e4 END r30,
       CASE WHEN w.t60-w.m BETWEEN 3540000 AND 3660000   THEN (w.p60/w.px-1)*1e4 END r60
       FROM fs JOIN w ON fs.snap_m=w.m WHERE fs.n_open>50),
    ranked AS (SELECT *, ntile(10) OVER (PARTITION BY split ORDER BY sig) sdec FROM j)
    SELECT split,
      count(*) n,
      round(corr(r15,sig),4) corr_15m,
      round(corr(r30,sig),4) corr_30m,
      round(corr(r60,sig),4) corr_60m,
      -- decile spread at 60m: top-sig (most below-fuel) minus bottom-sig; magnet => NEGATIVE
      round(avg(CASE WHEN sdec=10 THEN r60 END) - avg(CASE WHEN sdec=1 THEN r60 END),3) top_minus_bot_60m_bp
    FROM ranked GROUP BY split ORDER BY split DESC
    """
    print(f"=== ANTICIPATION signal: fuel imbalance -> forward return ({coin}) ===")
    print("corr<0 and top_minus_bot<0 => magnet (price drawn to heavier fuel). OOS = the 'test' row.")
    print(con.sql(sql))


if __name__ == "__main__":
    analyze(sys.argv[1] if len(sys.argv) > 1 else "SOL")
