"""basis EDA — is there an oracle-vs-HL-mid basis large enough AND long enough to trade?

Descriptive only (no verdict). Reads ONLY asset_ctx (per-minute, majors) → RAM-safe alongside a build.
Answers: magnitude (large enough vs spread), persistence (long enough — lag-1 autocorr), which way it
reverts (does mid catch up to oracle), and artifact checks (signed premium vs symmetric noise; basis-vs-
premium consistency; mid_px<=0 sentinel). Run: .venv/bin/python -m research.studies.basis.eda_basis
"""
from research.data.db import connect

MAJORS = ("BTC", "ETH", "SOL", "HYPE")

SQL = """
WITH base AS (
  SELECT coin, ts, oracle_px, mid_px, mark_px, premium,
         (mid_px - oracle_px)/mid_px*1e4                     AS basis_bp,     -- signed: >0 = HL rich vs oracle
         (mark_px - oracle_px)/oracle_px*1e4                 AS mark_basis_bp,
         (impact_ask_px - impact_bid_px)/mid_px*1e4          AS spread_bp
  FROM asset_ctx
  WHERE coin IN ('BTC','ETH','SOL','HYPE') AND mid_px > 0
),
w AS (
  SELECT *,
    LEAD(mid_px) OVER (PARTITION BY coin ORDER BY ts) AS mid_next,
    LEAD(ts)     OVER (PARTITION BY coin ORDER BY ts) AS ts_next,
    LAG(basis_bp)OVER (PARTITION BY coin ORDER BY ts) AS basis_prev
  FROM base
),
r AS (
  SELECT *,
    CASE WHEN ts_next - ts BETWEEN 55000 AND 65000
         THEN (mid_next - mid_px)/mid_px*1e4 END AS fwd_mid_ret_bp   -- next-minute mid return (only ~1-min steps)
  FROM w
)
SELECT coin,
  count(*)                                        AS n,
  round(avg(basis_bp),3)                          AS mean_signed_basis_bp,   -- ~0 => symmetric noise; !=0 => persistent premium
  round(median(abs(basis_bp)),3)                  AS med_abs_basis_bp,
  round(quantile_cont(abs(basis_bp),0.99),2)      AS p99_abs_basis_bp,
  round(median(spread_bp),3)                      AS med_spread_bp,
  round(avg(mark_basis_bp),3)                      AS mean_mark_basis_bp,     -- consistency check vs mid-based basis
  round(avg(premium),6)                            AS mean_premium_raw,       -- scale-unknown field, printed raw
  round(corr(basis_bp, basis_prev),3)             AS ac1_basis,              -- PERSISTENCE: ~1 sticky (tradeable), ~0 flips each min
  round(corr(fwd_mid_ret_bp, -basis_bp),4)        AS corr_catchup,           -- >0 => mid catches up to oracle (tradeable direction)
  round(avg(CASE WHEN abs(basis_bp) > 2*spread_bp THEN 1 ELSE 0 END),3) AS frac_basis_gt_2spread
FROM r
GROUP BY coin ORDER BY coin
"""


def main():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='2GB'; SET threads=2")   # cap so it can't starve a concurrent build
    print(con.sql(SQL))


if __name__ == "__main__":
    main()
