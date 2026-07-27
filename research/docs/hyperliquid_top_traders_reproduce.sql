-- Reproduce the descriptive Hyperliquid consistency-and-P&L shortlist dated 2026-07-27.
--
-- Required PostgreSQL relations:
--   signals.hl_wallet_day(wallet, day, day_net, day_notional, n_fills, n_liquidations)
--   signals.hl_wallet_coin_day(wallet, coin, day, notional)
--   signals.hl_wallet_scores(wallet, fold_month, method, t_stat, p_informed)
--
-- Expected source state for the published CSV:
--   signals.hl_wallet_day_state.projection_key = 'wallet_day_v1'
--   status = 'reconciled'; source_max_day = backfilled_through = 2026-06-30
--
-- Run with psql --quiet --csv. This transaction is explicitly repeatable-read and read-only.

\set ON_ERROR_STOP on

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '240s';
SET LOCAL work_mem = '64MB';

WITH
params AS (
    SELECT
        DATE '2026-04-02' AS start_day,
        DATE '2026-06-30' AS end_day,
        90::numeric AS calendar_days,
        100000::numeric AS notional_cap,
        1.645::numeric AS one_sided_95_z,
        202606::integer AS score_fold,
        'capday100k_t_eb_v1'::text AS score_method
),
daily AS MATERIALIZED (
    SELECT
        d.wallet,
        d.day,
        d.day_net,
        d.day_notional,
        d.n_fills,
        d.n_liquidations,
        d.day_net
            * LEAST(
                1::numeric,
                p.notional_cap / GREATEST(d.day_notional, 0.000000000001::numeric)
            ) AS capped_pnl
    FROM signals.hl_wallet_day AS d
    CROSS JOIN params AS p
    WHERE d.day BETWEEN p.start_day AND p.end_day
),
wallet_aggregates AS (
    SELECT
        d.wallet,
        count(*) AS active_days,
        sum(d.day_net) AS raw_net_pnl,
        sum(d.capped_pnl) AS capped_pnl,
        max(d.capped_pnl) AS best_day_pnl,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY d.capped_pnl)
            AS median_active_day_pnl,
        sum(d.capped_pnl * d.capped_pnl) AS capped_pnl_sumsq,
        count(*) FILTER (WHERE d.capped_pnl > 0) AS winning_days,
        sum(d.n_fills) AS fills,
        sum(d.n_liquidations) AS liquidations,
        sum(d.capped_pnl) FILTER (WHERE d.day < DATE '2026-05-01') AS april_pnl,
        sum(d.capped_pnl) FILTER (
            WHERE d.day >= DATE '2026-05-01' AND d.day < DATE '2026-06-01'
        ) AS may_pnl,
        sum(d.capped_pnl) FILTER (WHERE d.day >= DATE '2026-06-01') AS june_pnl
    FROM daily AS d
    GROUP BY d.wallet
),
latest_scores AS (
    SELECT s.wallet, s.t_stat, s.p_informed
    FROM signals.hl_wallet_scores AS s
    CROSS JOIN params AS p
    WHERE s.method = p.score_method
      AND s.fold_month = p.score_fold
),
eligible AS (
    SELECT
        a.*,
        ls.t_stat AS prior_t_stat,
        ls.p_informed AS prior_p_informed,
        a.capped_pnl - a.best_day_pnl AS pnl_ex_best_day,
        a.capped_pnl / p.calendar_days
            - p.one_sided_95_z
            * sqrt(
                GREATEST(
                    0::numeric,
                    (
                        a.capped_pnl_sumsq
                        - a.capped_pnl * a.capped_pnl / p.calendar_days
                    ) / (p.calendar_days - 1)
                )
            ) / sqrt(p.calendar_days) AS lcb_daily_pnl
    FROM wallet_aggregates AS a
    JOIN latest_scores AS ls USING (wallet)
    CROSS JOIN params AS p
    WHERE a.active_days >= 30
      AND a.raw_net_pnl > 0
      AND a.capped_pnl - a.best_day_pnl > 0
      AND a.april_pnl > 0
      AND a.may_pnl > 0
      AND a.june_pnl > 0
      AND a.median_active_day_pnl > 0
      AND a.winning_days::numeric / a.active_days >= 0.55
      AND a.liquidations = 0
      AND ls.p_informed >= 0.80
),
shortlist AS MATERIALIZED (
    SELECT e.*
    FROM eligible AS e
    ORDER BY
        round(e.lcb_daily_pnl, 2) DESC,
        round(e.pnl_ex_best_day, 2) DESC,
        e.wallet ASC
    LIMIT 15
),
ranked AS (
    SELECT
        row_number() OVER (
            ORDER BY
                round(s.lcb_daily_pnl, 2) DESC,
                round(s.pnl_ex_best_day, 2) DESC,
                s.wallet ASC
        ) AS rank,
        s.*
    FROM shortlist AS s
),
cumulative AS (
    SELECT
        d.wallet,
        d.day,
        sum(d.capped_pnl) OVER (
            PARTITION BY d.wallet
            ORDER BY d.day
            ROWS UNBOUNDED PRECEDING
        ) AS cumulative_pnl
    FROM daily AS d
    JOIN ranked AS r USING (wallet)
),
peaks AS (
    SELECT
        c.wallet,
        c.day,
        c.cumulative_pnl,
        GREATEST(
            0::numeric,
            max(c.cumulative_pnl) OVER (
                PARTITION BY c.wallet
                ORDER BY c.day
                ROWS UNBOUNDED PRECEDING
            )
        ) AS peak_pnl
    FROM cumulative AS c
),
drawdowns AS (
    SELECT p.wallet, max(p.peak_pnl - p.cumulative_pnl) AS max_drawdown
    FROM peaks AS p
    GROUP BY p.wallet
),
coin_totals AS (
    SELECT c.wallet, c.coin, sum(c.notional) AS coin_notional
    FROM signals.hl_wallet_coin_day AS c
    JOIN ranked AS r USING (wallet)
    CROSS JOIN params AS p
    WHERE c.day BETWEEN p.start_day AND p.end_day
    GROUP BY c.wallet, c.coin
),
coin_ranked AS (
    SELECT
        c.wallet,
        c.coin,
        c.coin_notional,
        sum(c.coin_notional) OVER (PARTITION BY c.wallet) AS total_notional,
        row_number() OVER (
            PARTITION BY c.wallet
            ORDER BY c.coin_notional DESC, c.coin ASC
        ) AS coin_rank
    FROM coin_totals AS c
)
SELECT
    r.rank,
    r.wallet,
    round(r.lcb_daily_pnl, 2) AS lcb_daily_pnl,
    round(r.raw_net_pnl, 2) AS raw_net_pnl,
    round(r.capped_pnl, 2) AS capped_pnl_90d,
    round(r.pnl_ex_best_day, 2) AS pnl_ex_best_day,
    round(r.best_day_pnl, 2) AS best_day_pnl,
    round(r.best_day_pnl / r.capped_pnl * 100, 1) AS best_day_share_pct,
    round(r.median_active_day_pnl::numeric, 2) AS median_active_day_pnl,
    r.active_days,
    round(r.winning_days::numeric / r.active_days * 100, 1) AS active_day_win_pct,
    r.fills,
    r.liquidations,
    round(r.prior_t_stat::numeric, 3) AS prior_t_stat,
    round(r.prior_p_informed::numeric, 4) AS prior_p_informed,
    round(dd.max_drawdown, 2) AS max_drawdown,
    cr.coin AS top_coin,
    round(cr.coin_notional / cr.total_notional * 100, 1) AS top_coin_notional_share_pct
FROM ranked AS r
JOIN drawdowns AS dd USING (wallet)
JOIN coin_ranked AS cr ON cr.wallet = r.wallet AND cr.coin_rank = 1
ORDER BY r.rank;

ROLLBACK;
