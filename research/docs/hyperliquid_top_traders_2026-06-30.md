# Hyperliquid traders: consistency and P&L shortlist

Report date: 2026-07-27  
Observation window: 2026-04-02 through 2026-06-30 UTC (90 closed calendar days)  
Latest available wallet-day fact: 2026-06-30  
Classification: private wallet-level research; not investment or copy-trading advice

> **EXPLORATORY DESCRIPTIVE SCREEN — NOT A BABYLON RESEARCH RESULT.** The ranking rule and
> eligibility gates were applied to the same observed window used to evaluate the wallets. There
> is no untouched out-of-sample period, multiplicity control, confidence interval on forward
> performance, positive-control MDE, execution model, or independent replication. The wallets are
> candidates for a separately preregistered prospective test, not validated traders or deployable
> copy targets.

## Descriptive shortlist

The primary rank is the one-sided 95% lower confidence bound (LCB) on daily net P&L after normalizing each active day to at most $100,000 of traded notional. It rewards economically meaningful P&L while penalizing volatility, inactivity, and uncertain estimates.

The first four wallets rank highest under this post-hoc descriptive score. Rank 5 has high historical profit and score values but is materially fragile: 98.1% of traded notional was HYPE and 38.2% of normalized P&L came from its best day. None of these observations establishes forward persistence.

| Rank | Wallet | LCB/day | Raw P&L | Capped P&L | Ex-best-day P&L | Active days | Win % | p(informed) | Max DD | Best-day % | Top coin (% notional) |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | `0x6bea81d7a0c5939a5ce5552e125ab57216cc597f` | $3,905.60 | $2,319,304 | $500,272 | $465,079 | 56 | 82.1% | 99.12% | $2,256 | 7.0% | BTC (57.1%) |
| 2 | `0x266b5569ed3017e74dd48059c6db804e016eefcb` | $2,572.63 | $1,030,128 | $360,493 | $323,081 | 54 | 77.8% | 98.82% | $3,215 | 10.4% | HYPE (48.2%) |
| 3 | `0x091144e651b334341eabdbbbfed644ad0100023e` | $2,540.37 | $1,736,785 | $323,260 | $300,254 | 77 | 77.9% | 99.92% | $27,809 | 7.1% | LIT (30.1%) |
| 4 | `0xf28e1b06e00e8774c612e31ab3ac35d5a720085f` | $2,341.02 | $4,660,068 | $330,096 | $286,576 | 88 | 75.0% | 84.72% | $21,796 | 13.2% | ZEC (22.0%) |
| 5 | `0xd6e56265890b76413d1d527eb9b75e334c0c5b42` | $1,532.89 | $3,192,904 | $382,511 | $236,223 | 66 | 80.3% | 99.99% | $13,893 | 38.2% | HYPE (98.1%) |
| 6 | `0xac26cf5f3c46b5e102048c65b977d2551b72a9c7` | $1,434.26 | $516,294 | $239,703 | $192,157 | 68 | 97.1% | 97.20% | $2,020 | 19.8% | HYPE (27.6%) |
| 7 | `0xce5667f7194c4d9320acd28f1ee8b3d2adbdb27e` | $1,039.32 | $275,729 | $180,792 | $152,814 | 43 | 62.8% | 82.46% | $3,444 | 15.5% | HYPE (68.8%) |
| 8 | `0xa8cbf4200595efcd94b7526d04deafe0f284af2d` | $1,035.80 | $182,066 | $157,144 | $136,599 | 50 | 64.0% | 94.92% | $4,309 | 13.1% | MORPHO (91.9%) |
| 9 | `0xe17cf192fee50447687af1f689782d4abba8cbb1` | $989.14 | $373,143 | $127,461 | $118,803 | 89 | 69.7% | 86.80% | $10,321 | 6.8% | HYPE (43.0%) |
| 10 | `0x4101ce19ee81f24da894976e585f1e79119dbd93` | $812.50 | $107,348 | $106,991 | $93,125 | 65 | 76.9% | 95.56% | $706 | 13.0% | HYPE (48.8%) |
| 11 | `0xa180e7a0dd22d55e09a4c439e7bb2ae3c91dc0b7` | $781.26 | $161,357 | $111,236 | $94,427 | 90 | 64.4% | 94.74% | $4,737 | 15.1% | HYPE (23.7%) |
| 12 | `0xb27bbaadcdfeab937069b4d966ee6bf5a32c999b` | $694.10 | $136,164 | $96,640 | $85,588 | 66 | 63.6% | 84.23% | $2,030 | 11.4% | HYPE (19.8%) |
| 13 | `0x07fd993f0fa3a185f7207adccd29f7a87404689d` | $686.66 | $757,771 | $95,397 | $87,403 | 90 | 70.0% | 97.60% | $16,086 | 8.4% | HYPE (16.0%) |
| 14 | `0x5d9d19a3e5005225f13780fa10c198f87816670d` | $616.69 | $147,902 | $84,645 | $74,547 | 75 | 65.3% | 94.90% | $4,754 | 11.9% | HYPE (67.5%) |
| 15 | `0xad59ed47c226987cf458a63428ca10887773ba81` | $495.75 | $129,806 | $65,069 | $58,083 | 74 | 67.6% | 98.98% | $65 | 10.7% | ZEC (25.5%) |

## Selection method

The analysis used the reconciled `signals.hl_wallet_day` projection and exact `signals.hl_wallet_coin_day` facts. The source contains 35,024,594 wallet/coin/day rows across 719,514 wallets from 2025-08-01 through 2026-06-30. All database sessions were enforced read-only.

For wallet `w` and active day `d`:

`capped_pnl(w,d) = day_net × min(1, 100000 / max(day_notional, 1e-12))`

The ranking score treats inactive days as zero and uses all 90 calendar observations:

`LCB = mean(capped_pnl) - 1.645 × standard_error(capped_pnl)`

Candidates also had to satisfy every gate:

- at least 30 active days;
- positive raw P&L and positive capped P&L after removing the best day;
- positive capped P&L in April, May, and June;
- positive median active-day capped P&L;
- at least a 55% active-day win rate;
- zero recorded liquidations in the window; and
- `p_informed >= 0.80` under `capday100k_t_eb_v1`, fold 202606.

The `p_informed` score was trained on 2026-03-01 through 2026-05-31. It overlaps but does not exactly equal the report window; it is used as a persistence gate, not as the primary ranking statistic.

## Exact reproduction

The companion [`hyperliquid_top_traders_reproduce.sql`](./hyperliquid_top_traders_reproduce.sql)
contains the complete read-only PostgreSQL query. It starts from every wallet present in the
90-day window; there is no manual wallet list or cohort preselection. It then:

1. reads `signals.hl_wallet_day` from 2026-04-02 through 2026-06-30 inclusive;
2. calculates exact-decimal capped daily P&L and wallet aggregates;
3. joins the fixed `capday100k_t_eb_v1` score at fold `202606`;
4. applies every eligibility gate listed above;
5. orders by rounded LCB/day descending, then rounded ex-best-day P&L descending;
6. retains 15 wallets; and
7. calculates cumulative-path drawdown plus top-coin notional concentration from
   `signals.hl_wallet_coin_day` only for those 15 wallets.

The SQL adds wallet address ascending as a deterministic final tie-break. No such tie occurred in
the reported output, so this does not change the list. To export from any repository with a
PostgreSQL URL that can `SELECT` the two source tables and `signals.hl_wallet_scores`:

```bash
PGOPTIONS='-c default_transaction_read_only=on' \
  psql "$PGURL" -X --no-psqlrc --quiet --csv \
  -f /absolute/path/to/hyperliquid_top_traders_reproduce.sql \
  > hyperliquid_top_traders_reproduced.csv
```

Do not put the URL or credentials in the SQL, shell history, report, or output. The checked source
state was `wallet_day_v1`, status `reconciled`, source/backfill maximum day `2026-06-30`, reconciled
at `2026-07-24T21:42:05.901487+00:00`. The underlying wallet/coin/day source contained 35,024,594
rows and 719,514 distinct wallets over 2025-08-01 through 2026-06-30. A later correction or extended
snapshot may legitimately produce different results; record the projection state alongside any
rerun.

## Interpretation

- **LCB/day** is the conservative amount of normalized daily P&L supported after uncertainty is deducted. It is the primary rank.
- **Raw P&L** shows observed economic scale but is not comparable across wallet sizes.
- **Capped P&L** limits the advantage of very high turnover or capital scale.
- **Ex-best-day P&L** rejects one-hit performance.
- **Max DD** is drawdown of the observed cumulative capped-P&L path from a zero baseline. It is not account-equity drawdown.
- **Top coin share** is concentration by traded notional. Shares above roughly 65% merit strategy-specific review; they are not automatic disqualifications.

## Important limitations

This is a historical research screen, not a copy-trading recommendation. The latest data is 27 days old as of the report date. P&L is realized P&L net of fees; builder fees are excluded to match the existing Incerto capped-P&L method. The dataset does not establish current open exposure, account equity returns, latency-adjusted copyability, slippage, capacity, identity, survivorship, or whether multiple wallets are controlled by one entity. Before presenting any wallet as actionable, refresh the data and inspect current positions, coin-level behavior, and post-window performance.
