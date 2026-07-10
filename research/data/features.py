"""Table 2/3 Tier-1 trader-feature panels — WALLET_FEATURES_SPEC §4-9, arch doc
`docs/WALLET_FEATURES_TABLE23_ARCH.md` (v2, post-audit).

EXPLORATORY lane — firewalled from Gate-A: this module imports the episode lake, the fills tape, and
`schema` constants ONLY. It must NEVER import anything under `markout_study/gate_a/`.

Each Table-2 row = TWO per-cell aggregations joined on (wallet):
  (A) episode-level over the episode lake, membership by `close_ts` (leakage-safe, §2).
  (B) fills-level over the fills tape, windowed by fill `ts` (activity/liveness/volume, §4B).
plus (C) n_open_at_cutoff over ALL episode partitions (no prune).

8GB box: DuckDB, memory_limit 5GB, threads 2, spill to .tmp; cells run SEQUENTIALLY, Table 2 chunked per
coin, Table 3 per wallet-hash bucket. Holistic aggregates (quantile) use list-form; concentration/LOO are
closed forms. Determinism: exact quantile_cont, float sums ROUNDed before write, pinned ORDER BY.

    python -m research.data.features cell BTC 202508 expanding   # one validation cell (prints, no write)
    python -m research.data.features table2                      # full Table 2 (88 cells)
    python -m research.data.features table3                      # full Table 3 (176 buckets)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from . import schema

REPO_ROOT = Path(__file__).resolve().parents[2]
EP_GLOB = str(REPO_ROOT / "data" / "derived" / "episodes" / "month=*/episodes.parquet")
FILLS_GLOB = str(REPO_ROOT / "data" / "raw" / "fills" / "month=*/day=*/*.parquet")
OUT_DIR = REPO_ROOT / "data" / "derived"
FEATURE_SCHEMA_VERSION = "wallet_features_tier1_v1_2026-07-08"
EXPECTED_EPISODE_SCHEMA = "episodes_v1_lifecycle_enriched_2026-07-07"   # leakage-F5 precondition

# 11 monthly cutoffs: cutoff(M) = first instant of month M+1 (P12). Stored as the data months.
MONTHS = [202508, 202509, 202510, 202511, 202512, 202601,
          202602, 202603, 202604, 202605, 202606]
DAY_MS = 86_400_000
WIN_90D_MS = 90 * DAY_MS


def _month_add(ym: int, k: int) -> int:
    """YYYYMM + k months."""
    y, m = divmod(ym, 100)
    idx = (y * 12 + (m - 1)) + k
    return (idx // 12) * 100 + (idx % 12) + 1


def _cutoff_ms(month: int) -> int:
    """First instant of the month AFTER `month`, in epoch ms UTC (the cutoff for that month)."""
    nxt = _month_add(month, 1)
    y, m = divmod(nxt, 100)
    # epoch ms of YYYY-MM-01T00:00:00Z via DuckDB (avoids tz libs); computed once.
    con = duckdb.connect()
    return con.execute("SELECT epoch_ms(make_timestamp(?, ?, 1, 0, 0, 0))", [y, m]).fetchone()[0]


def _candidate_months(C_ms: int, wstart_ms: int) -> list[int]:
    """Conservative close-month prune (leakage-F1: partition≈ts-month, 20/800M boundary fills). Include a
    ±1-month slack; the exact close_ts/ts predicate is the real correctness filter."""
    # month of a timestamp
    con = duckdb.connect()
    def ym(ms):
        return con.execute("SELECT CAST(strftime(make_timestamp(? * 1000), '%Y%m') AS BIGINT)", [ms]).fetchone()[0]
    hi = _month_add(ym(C_ms), 1)
    lo = _month_add(ym(max(wstart_ms, MONTHS_MIN_MS)), -1) if wstart_ms > 0 else MONTHS[0]
    return [m for m in MONTHS if lo <= m <= hi]


MONTHS_MIN_MS = 1_700_000_000_000   # ~2023; wstart floor for expanding sentinel


# ---------------------------------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------------------------------
def _episode_agg_sql(coin: str, C: int, wstart: int, months: list[int]) -> str:
    """(A) episode-level aggregates per wallet for one (coin, cutoff, window). Members = CLOSE∪FLIP with
    close_ts in (wstart, C]. Concentration on NON-NEGATIVE base (rollup-F2); win = realized_net>0 (§4A)."""
    mlist = ",".join(str(m) for m in months)
    return f"""
    WITH m AS (
      SELECT wallet, dir, close_kind, n_fills, n_adds, hold_minutes, build_minutes,
             realized_pnl_usd, realized_net_usd, fee_usd, builder_fee_usd,
             initial_notional_usd, peak_notional_usd, total_added_notional_usd,
             opener_flagged, opener_qualifying, is_liquidation_close, n_flagged_fills, n_liq_fills,
             close_ts, greatest(realized_net_usd, 0) AS pos_net
      FROM read_parquet('{EP_GLOB}', hive_partitioning=true, union_by_name=true)
      WHERE coin = '{coin}' AND month IN ({mlist})
        AND close_ts IS NOT NULL AND close_ts <= {C} AND close_ts > {wstart}
    ), g AS (
      SELECT wallet,
        count(*) AS n_realized,
        count(*) FILTER (close_kind='CLOSE') AS n_closes,
        count(*) FILTER (close_kind='FLIP')  AS n_flips,
        count(*) FILTER (dir='long')         AS n_long_episodes,
        count(*) FILTER (n_fills=1)          AS n_single_fill_episodes,
        count(*) FILTER (realized_net_usd>0) AS n_wins,
        count(*) FILTER (realized_net_usd<0) AS n_losses,
        count(*) FILTER (realized_net_usd=0) AS n_breakeven,
        sum(realized_pnl_usd) AS sum_realized_gross,
        sum(fee_usd) AS sum_fees, sum(builder_fee_usd) AS sum_builder_fees,
        sum(realized_net_usd) AS net_realized_pnl,
        sum(realized_net_usd) FILTER (realized_net_usd>0) AS sum_win_pnl,
        sum(realized_net_usd) FILTER (realized_net_usd<0) AS sum_loss_pnl,
        sum(hold_minutes) AS sum_hold_minutes,
        sum(initial_notional_usd) AS sum_initial_notional,
        sum(total_added_notional_usd) AS sum_added_notional,
        sum(peak_notional_usd) AS sum_peak_notional,
        sum(n_adds) AS sum_adds,
        avg((hold_minutes>=60)::INT)   AS frac_hold_ge_1h,
        avg((hold_minutes>=240)::INT)  AS frac_hold_ge_4h,
        avg((hold_minutes>=1440)::INT) AS frac_hold_ge_24h,
        avg(peak_notional_usd / nullif(initial_notional_usd,0)) AS peak_to_initial_notional_mean,
        max(realized_net_usd) AS best_episode_pnl, min(realized_net_usd) AS worst_episode_pnl,
        sum(pos_net) AS sum_pos, sum(pos_net*pos_net) AS sum_pos_sq,
        max(pos_net) AS max_pos, list_aggr(list_filter(max(pos_net, 5), x -> x>0), 'sum') AS top5_pos,
        sum(peak_notional_usd*peak_notional_usd) AS sum_peak_sq,
        max(close_ts) AS last_close_ts,
        sum(opener_flagged::INT) AS n_flagged_opens,
        sum(opener_qualifying::INT) AS n_qualifying_opens,
        sum(is_liquidation_close::INT) AS n_liquidation_closes,
        sum(n_flagged_fills) AS n_flagged_fills, sum(n_liq_fills) AS n_liq_fills,
        quantile_cont(hold_minutes, [0.1,0.5,0.9]) AS q_hold,
        quantile_cont(build_minutes, [0.5,0.9]) AS q_build,
        quantile_cont(n_adds::DOUBLE, [0.5,0.9]) AS q_adds,
        quantile_cont(initial_notional_usd, [0.5]) AS q_init,
        quantile_cont(peak_notional_usd, [0.5]) AS q_peak,
        quantile_cont(realized_net_usd, [0.5]) AS q_pnl
      FROM m GROUP BY wallet
    )
    SELECT wallet, n_realized, n_closes, n_flips, n_long_episodes, n_single_fill_episodes,
      n_wins, n_losses, n_breakeven, sum_realized_gross, sum_fees, sum_builder_fees, net_realized_pnl,
      sum_win_pnl, sum_loss_pnl, sum_hold_minutes, sum_initial_notional, sum_added_notional,
      sum_peak_notional, sum_adds, frac_hold_ge_1h, frac_hold_ge_4h, frac_hold_ge_24h,
      peak_to_initial_notional_mean, best_episode_pnl, worst_episode_pnl,
      n_flagged_opens, n_qualifying_opens, n_liquidation_closes, n_flagged_fills, n_liq_fills,
      last_close_ts,
      n_long_episodes::DOUBLE / n_realized AS long_episode_share,
      (2.0*n_long_episodes - n_realized) / n_realized AS directional_imbalance,
      n_flips::DOUBLE / n_realized AS flip_rate,
      net_realized_pnl / n_realized AS pnl_per_episode,
      net_realized_pnl / n_realized AS episode_pnl_mean,
      sum_adds::DOUBLE / n_realized AS adds_per_episode_mean,
      CASE WHEN (n_wins+n_losses)>0 THEN n_wins::DOUBLE/(n_wins+n_losses) END AS win_rate,
      CASE WHEN sum_loss_pnl<0 THEN sum_win_pnl / (-sum_loss_pnl) END AS profit_factor,
      CASE WHEN n_wins>0 THEN sum_win_pnl/n_wins END AS average_win,
      CASE WHEN n_losses>0 THEN sum_loss_pnl/n_losses END AS average_loss,
      CASE WHEN n_wins>0 AND n_losses>0 THEN (sum_win_pnl/n_wins)/(-sum_loss_pnl/n_losses) END AS payoff_ratio,
      net_realized_pnl - best_episode_pnl AS pnl_without_best_episode,
      net_realized_pnl - worst_episode_pnl AS pnl_without_worst_episode,
      CASE WHEN sum_pos>0 THEN sum_pos_sq/(sum_pos*sum_pos) END AS grossprofit_hhi,
      CASE WHEN sum_pos>0 THEN max_pos/sum_pos END AS top1_grossprofit_share,
      CASE WHEN sum_pos>0 THEN top5_pos/sum_pos END AS top5_grossprofit_share,
      CASE WHEN sum_peak_notional>0 THEN sum_peak_sq/(sum_peak_notional*sum_peak_notional) END AS notional_hhi,
      n_qualifying_opens::DOUBLE / n_realized AS qualifying_open_share,
      q_hold[1] AS hold_minutes_p10, q_hold[2] AS hold_minutes_median, q_hold[3] AS hold_minutes_p90,
      q_build[1] AS build_minutes_median, q_build[2] AS build_minutes_p90,
      q_adds[1] AS adds_per_episode_median, q_adds[2] AS adds_per_episode_p90,
      q_init[1] AS initial_notional_median, q_peak[1] AS peak_notional_median, q_pnl[1] AS episode_pnl_median,
      ({C} - last_close_ts)/{float(DAY_MS)} AS days_since_last_episode
    FROM g
    """


def _fills_agg_sql(coin: str, C: int, wstart: int, months: list[int]) -> str:
    """(B) fills-level activity per wallet: windowed by fill ts (not episode membership). Resolves active-days,
    days_since_last_fill leak, traded volume (rollup-F1/F6/F7)."""
    mlist = ",".join(str(m) for m in months)
    return f"""
    SELECT wallet,
      count(*) AS n_fills,
      count(*) FILTER (crossed) AS n_taker_fills,
      count(*) FILTER (NOT crossed) AS n_maker_fills,
      count(*) FILTER (side='B') AS n_buy_fills,
      count(*) FILTER (side<>'B') AS n_sell_fills,
      count(DISTINCT ts // {DAY_MS}) AS n_active_days,
      count(DISTINCT strftime(make_timestamp(ts*1000), '%G%V')) AS n_active_iso_weeks,
      count(DISTINCT strftime(make_timestamp(ts*1000), '%Y%m')) AS n_active_months,
      sum(abs(TRY_CAST(sz AS DOUBLE)) * TRY_CAST(px AS DOUBLE)) AS sum_traded_notional_usd,
      min(ts) AS first_fill_ts, max(ts) AS last_fill_ts,
      ({C} - max(ts))/{float(DAY_MS)} AS days_since_last_fill
    FROM read_parquet('{FILLS_GLOB}', hive_partitioning=true, union_by_name=true)
    WHERE coin = '{coin}' AND month IN ({mlist}) AND ts <= {C} AND ts > {wstart}
    GROUP BY wallet
    """


def _open_at_cutoff_sql(coin: str, C: int) -> str:
    """(C) count episodes OPEN at cutoff C (open_ts ≤ C < close_ts or NULL). ALL partitions, NO prune
    (a still-open position finalizes in a future partition)."""
    return f"""
    SELECT wallet, count(*) AS n_open_at_cutoff
    FROM read_parquet('{EP_GLOB}', hive_partitioning=true, union_by_name=true)
    WHERE coin = '{coin}' AND open_ts <= {C} AND (close_ts IS NULL OR close_ts > {C})
    GROUP BY wallet
    """


def _cell_relation(con, coin: str, C: int, wstart: int, months: list[int]) -> str:
    """Register the joined per-cell relation as a view; return its name. FULL OUTER join A⋈B⋈C on wallet
    (populations differ: a wallet may have fills but no member episode, or vice-versa)."""
    con.execute(f"CREATE OR REPLACE TEMP VIEW _epi AS {_episode_agg_sql(coin, C, wstart, months)}")
    con.execute(f"CREATE OR REPLACE TEMP VIEW _fil AS {_fills_agg_sql(coin, C, wstart, months)}")
    con.execute(f"CREATE OR REPLACE TEMP VIEW _opn AS {_open_at_cutoff_sql(coin, C)}")
    con.execute("""
    CREATE OR REPLACE TEMP VIEW _cell AS
    SELECT coalesce(e.wallet, f.wallet, o.wallet) AS wallet,
           e.* EXCLUDE (wallet), f.* EXCLUDE (wallet), o.n_open_at_cutoff,
           e.net_realized_pnl / nullif(f.n_active_days,0) AS pnl_per_active_day,
           e.net_realized_pnl / nullif(f.sum_traded_notional_usd,0) AS pnl_per_dollar_volume,
           e.n_realized::DOUBLE / nullif(f.n_active_days,0) AS episodes_per_active_day,
           f.n_taker_fills::DOUBLE / nullif(f.n_fills,0) AS taker_fill_share
    FROM _epi e
    FULL OUTER JOIN _fil f ON e.wallet = f.wallet
    FULL OUTER JOIN _opn o ON coalesce(e.wallet,f.wallet) = o.wallet
    """)
    return "_cell"


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("PRAGMA threads=2")
    con.execute("PRAGMA memory_limit='5GB'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{REPO_ROOT / '.tmp'}'")
    return con


def _assert_lake_ok(con) -> None:
    """leakage-F5 precondition: refuse to build unless the episode lake is the expected full-rebuild schema."""
    v = con.execute(f"""SELECT DISTINCT decode(value) FROM parquet_kv_metadata('{EP_GLOB}')
                        WHERE decode(key)='episode_schema_version'""").fetchall()
    got = {r[0] for r in v}
    if got != {EXPECTED_EPISODE_SCHEMA}:
        raise SystemExit(f"episode lake schema {got} != expected {{{EXPECTED_EPISODE_SCHEMA}}} — refuse to build")


def build_cell(coin: str, month: int, window: str, write: bool = False):
    """Build one (coin, cutoff=month-end, window) cell. window in {'expanding','90d'}. Validation entry point."""
    con = _connect()
    _assert_lake_ok(con)
    C = _cutoff_ms(month)
    wstart = 0 if window == "expanding" else C - WIN_90D_MS
    months = _candidate_months(C, wstart)
    t0 = time.time()
    _cell_relation(con, coin, C, wstart, months)
    n = con.execute("SELECT count(*) FROM _cell").fetchone()[0]
    # leakage assertion: no member episode may have close_ts > C
    leak = con.execute(f"""SELECT count(*) FROM read_parquet('{EP_GLOB}', hive_partitioning=true)
        WHERE coin='{coin}' AND month IN ({','.join(map(str,months))})
          AND close_ts IS NOT NULL AND close_ts <= {C} AND close_ts > {wstart} AND close_ts > {C}""").fetchone()[0]
    if leak != 0:
        raise SystemExit(f"LEAKAGE: {leak} members have close_ts > C in {coin} {month} {window}")
    # invariant checks over the cell (cheap; catch derivation bugs)
    inv = con.execute("""
      SELECT
        count(*) FILTER (n_realized IS NOT NULL AND n_realized <> n_wins+n_losses+n_breakeven) AS bad_realized,
        count(*) FILTER (n_fills IS NOT NULL AND n_taker_fills+n_maker_fills <> n_fills)         AS bad_taker,
        count(*) FILTER (n_fills IS NOT NULL AND n_buy_fills+n_sell_fills   <> n_fills)          AS bad_buy,
        count(*) FILTER (win_rate IS NOT NULL AND (win_rate<0 OR win_rate>1))                    AS bad_winrate,
        count(*) FILTER (grossprofit_hhi IS NOT NULL AND (grossprofit_hhi<0 OR grossprofit_hhi>1.0001)) AS bad_hhi,
        count(*) FILTER (n_realized IS NULL AND n_fills IS NULL AND n_open_at_cutoff IS NULL)    AS empty_rows
      FROM _cell""").fetchone()
    print(f"cell {coin} {month} {window}: rows={n:,} months={months} secs={time.time()-t0:.1f} "
          f"leak={leak} | invariants bad_realized={inv[0]} bad_taker={inv[1]} bad_buy={inv[2]} "
          f"bad_winrate={inv[3]} bad_hhi={inv[4]} empty_rows={inv[5]}")
    return con


COINS = list(schema.SZD.keys())   # BTC ETH SOL HYPE
WINDOWS = ["expanding", "90d"]
T2_DIR = OUT_DIR / "addr_coin_features"


def _code_commit() -> str:
    import subprocess
    try:
        h = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5).stdout.strip()
        d = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
                           capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{h}{'-dirty' if d else ''}" if h else "unknown"
    except Exception:
        return "unknown"


def _meta() -> dict:
    return {b"feature_schema_version": FEATURE_SCHEMA_VERSION.encode(),
            b"source_episode_schema": EXPECTED_EPISODE_SCHEMA.encode(),
            b"code_commit": _code_commit().encode()}


def _write_part(con, out: Path, C: int, month: int, window: str) -> int:
    """Materialize the current _cell view + identity cols to a parquet part (atomic), sorted by wallet."""
    out.parent.mkdir(parents=True, exist_ok=True)
    wstart = 0 if window == "expanding" else C - WIN_90D_MS
    rel = con.execute(f"""
      SELECT wallet AS address, {month} AS as_of_cutoff, '{window}' AS window_name,
             {wstart} AS window_start_ms, {C} AS window_end_ms, * EXCLUDE (wallet)
      FROM _cell ORDER BY wallet""").fetch_arrow_table()
    tbl = rel.replace_schema_metadata(_meta())
    tmp = out.with_suffix(".parquet.tmp")
    pq.write_table(tbl, tmp, compression="zstd")
    os.replace(tmp, out)
    return tbl.num_rows


def build_table2():
    """Full Table 2 — 4 coins × 11 cutoffs × 2 windows = 88 cells, per-coin chunked, sequential."""
    con = _connect()
    _assert_lake_ok(con)
    t0, total = time.time(), 0
    for coin in COINS:
        for month in MONTHS:
            C = _cutoff_ms(month)
            for window in WINDOWS:
                wstart = 0 if window == "expanding" else C - WIN_90D_MS
                months = _candidate_months(C, wstart)
                tm = time.time()
                _cell_relation(con, coin, C, wstart, months)
                out = T2_DIR / f"cutoff={month}" / f"window={window}" / f"coin={coin}" / "part.parquet"
                n = _write_part(con, out, C, month, window)
                total += n
                print(f"  T2 {coin} {month} {window}: {n:,} rows  {time.time()-tm:.0f}s", flush=True)
    print(f"=== Table 2: {total:,} rows in {time.time()-t0:.0f}s -> {T2_DIR} ===", flush=True)
    return {"rows": total}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cell"
    if cmd == "table2":
        print(build_table2()); sys.exit(0)
    if cmd == "cell":
        coin = sys.argv[2] if len(sys.argv) > 2 else "BTC"
        month = int(sys.argv[3]) if len(sys.argv) > 3 else 202508
        window = sys.argv[4] if len(sys.argv) > 4 else "expanding"
        con = build_cell(coin, month, window)
        cols = [d[0] for d in con.execute("SELECT * FROM _cell LIMIT 0").description]
        print(f"{len(cols)} columns: {cols}")
        # show one well-populated wallet as a sanity spot-check
        row = con.execute("""SELECT * FROM _cell WHERE n_realized >= 5 AND n_fills >= 10
                             ORDER BY net_realized_pnl DESC LIMIT 1""").fetchone()
        for k, v in zip(cols, row):
            print(f"  {k:32s} {v}")
    else:
        raise SystemExit(f"unknown command {cmd}")
