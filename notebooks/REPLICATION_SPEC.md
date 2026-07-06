# Replication spec — locating informed wallets by markout screening (HL tape)

Produces the top-50 candidate list of 2026-07-02 (`report_figs/top50_wallets.csv`).
Reference implementation: babylon `scratch_conv/mlscreen.py` (bars/stats),
`mlscreen2.py` (extract/markout), `mlscreen_reports.py` (characterization).

## 0. Data
- Source: `s3://hl-mainnet-node-data/node_fills_by_block/hourly/<YYYYMMDD>/<H>.lz4`
  (requester-pays). Pair events by `tid`: exactly 2 events with opposite `crossed`;
  the crossed side is the taker. Emit both addresses per fill. Drop HIP-3 markets
  (coin contains ':'). Integrity: gzip-test every hour file; re-fetch misses (two passes);
  log completeness (hour-file count) BEFORE deleting anything.
- Fill schema: coin, ts(ms), px, sz, side('B'/'A' = taker buy/sell), taker, maker,
  notional, tid, zhash(bool: hash == 0x0 => TWAP/liquidation).
- Window used here: TRAIN 2025-10-01..2026-03-31 (preliminary; full spec 2025-08-01..),
  TEST 2026-04-01..2026-06-30 (SEALED — one pre-registered look, never used in selection).
- Exclude spot ('/' or '@' prefix coins). Keep all perps incl. majors.

## 1. Price bars (from the tape itself — no external candles)
5-minute bars per coin: close = last trade px in the bar, ties broken by tid
(deterministic). Coins with <100 bars over the window are unpriceable — skip.

## 2. Wallet eligibility filters (computed on TRAIN months ONLY)
Unit = "order" = fill group keyed (taker, coin, ts, side); zhash fills excluded from
order counting (kept in positions). Per wallet over the train window:
- 150 <= total taker orders <= 20,000
- >= 25 active days
- 0.5 <= orders/day <= 15   (span = last-first order ts, floor 1 day)
- mean order notional >= $500
No volume RANKING anywhere (that selects HFT). Dead wallets stay in the field.
Yield here: 23,154 eligible of ~470k takers (6 train months).

## 3. Position reconstruction (per wallet x coin)
- Union taker fills (sz signed by side) and maker fills (sign FLIPPED).
- Sort by (ts, tid). Position = cumsum.
- LEADING-EPISODE DROP: discard all fills up to and including the first time
  |position| * (that row's own fill px) < $1 (unknown pre-window inventory; without this you inherit the
  startPosition seeding bias). Coins that never return to flat are skipped entirely
  (declared limitation; biases AGAINST buy-and-hold — conservative).

## 4. Markout term structure (the screen statistic)
- Entry events: position-INCREASING taker fills. The scored size is the
  position-increasing COMPONENT only (a sign-flip fill opens |new position|,
  not the full fill size).
- PRICING — the critical convention: entry price = close of the FIRST 5m bar strictly
  AFTER the fill's own bar; exit price at horizon H likewise (first bar strictly after
  t+H's bar). NEVER the containing bar (its close can be the trader's own print) and
  NEVER any bar at-or-before the fill (pre-fill pricing manufactures fake edge — this
  killed a prior +30bp "edge"). Skip the fill if the next bar's START is more than 30min after the fill timestamp.
- Horizons: {1, 2, 4, 8, 12, 24, 48, 72, 168} hours.
- markout_$ = signed_size * (exit_px - entry_px); markout_bps = sign * (exit/entry - 1)*1e4.
- Train cell: exit lands before the split. Test cell: ENTRY on/after the split.
  Entries straddling the boundary are excluded from both.

## 5. Ranking
- Eligibility floor: >= 30 train entries scored at 24h.
- RANK = train dollar markout PnL at 24h. Top-50 = the candidate list.
- (For significance testing use the EQUAL-WEIGHT per-wallet mean bps, never dollar
  sums — dollar statistics beat random rosters on size alone.)

## 6. Characterization (train-side diagnostics)
Per top-50 wallet: long fraction (count & notional), monthly PnL (calendar months) +
profitable-month breadth, top-coin |PnL| share, majors share, crowding (coin-days with
>=10 roster wallets entering; report their PnL share), term-structure shape
(plateau vs spike-decay vs flat on the eq-wt bps curve).

## 7. Integrity rules (the ones that made previous results fake when broken)
1. Post-fill pricing everywhere (see 4). 2. Chronological split, eligibility and ranking
from train only; the test window is read ONCE, against 1,000 random same-size rosters
from the eligible field (equal-weight statistic, p97.5 bar for a 3-horizon family).
3. Winner's curse: train-side numbers of a train-selected roster prove nothing —
only the held-out placebo-relative read does. 4. Raw markouts contain market drift;
the placebo comparison is the drift control. 5. Every sort carries a tid tiebreaker
(reproducibility). 6. Completeness gate before the look (all months present, manifest
written). 7. Any deviation is written down BEFORE results are read.

## Expected outputs — STALE, do not cross-check yet
The previously listed numbers were computed on the preliminary Oct-Mar window under
pre-audit-round-4 conventions (full-fill reversal sizing, 30-day pseudo-months). They will be
regenerated from the final 8-month run under the current conventions and updated here. Until
then, replicate the METHOD above; do not tune to old numbers. Note on statistics: "entry-pooled"
mean = sum(bps)/sum(n) across wallets (activity-weighted); the pre-registered decision statistic
is the PER-WALLET mean of per-wallet averages (size- and activity-blind). Both should be reported;
they differ materially. Monthly diagnostics use CALENDAR months (UTC).
