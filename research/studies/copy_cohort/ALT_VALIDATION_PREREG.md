# Alt external-validation — PRE-REGISTRATION (frozen before any alt return is viewed)

Frozen 2026-07-14, before ingesting/reading a single alt markout. Purpose: an EXTERNAL validation of the
majors-frozen entry rule on the same wallets' ALT trades — a test of wallet-level skill portability. No part
of the entry rule may be modified based on alt results; secondary tests are reported, never used to re-tune.

## Independence (verified, non-negotiable)
- **Selection** (capped-PnL/active-day top-30, monthly) reads ONLY `data/raw/fills` (majors node_fills
  `closed_pnl`). No alt fills.
- **Scale classification** (`frozen_alt_universe.json`) = median MAJORS opening-taker notional over the 3-mo
  formation window, per wallet-fold; LARGE = top-half within fold. Majors episodes only.
- Therefore alt markout never influenced selection or classification. The frozen universe file is the ONLY
  selection/classification input the alt validation may read.

## Frozen inputs (locked)
- **Universe:** the 133 distinct wallets / 240 wallet-fold memberships in `frozen_alt_universe.json`
  (72 large / 168 small). Monthly cohort membership applies per its test month T (same 8 folds 202511–202606).
- **Scale / LARGE:** as frozen in that file (no recomputation).
- **Opening-taker episode (alts):** identical definition to majors — position OPEN (start_position/dir sign
  reconstruction, NOT buy/sell side), TAKER (`crossed_open`), guards `NOT opener_flagged`,
  `NOT entry_after_close`, `entry_lag_s ≤ 90`, `initial_notional_usd > 0`. Entry at `entry_bar_ts`.
- **Sizing:** fixed within-wallet (wallet-equal per decision). No source clip-size dependence.
- **Exit / cost:** fixed 8h; forward dir-signed markout `raw_markout_8h` from the alt price lattice (asset_ctx
  mark, same ≤90s staleness basis as majors). Round-trip cost `RT_COST_BP` treated as a REPORTED sensitivity
  (alt taker cost is higher/uncertain) — the primary metric is gross markout; a cost haircut is shown alongside.
- **Coin eligibility (frozen, pre-outcome):** a coin-month is eligible iff the alt price lattice has coverage
  to compute an 8h forward markout for its entries (price series spans entry..entry+8h with a tick ≤90s at
  both ends). Coins failing this are excluded on DATA grounds, decided BEFORE seeing returns. **No coin is ever
  excluded based on observed alt performance.**
- **Min coverage for an interpretable result:** ≥ 40 evaluable large-wallet alt entries across ≥ 3 folds and
  ≥ 5 wallets in the LARGE stratum (mirrors the majors evaluable count). Below this → report as underpowered,
  do not over-read.

## PRIMARY test (the clean question)
Do wallets classified LARGE-scale on majors formation data have positive copyable 8h ALT markout, and do they
out-rank the majors-classified SMALL wallets?
- **H1:** μ(large, alts) > 0
- **H2:** μ(large, alts) − μ(small, alts) > 0  ← the key one. Even if the whole alt book is negative (harder
  execution), replication of the LARGE−SMALL ranking validates the scale signal.
- **Metric:** wallet-equal 8h net bp (per wallet-fold mean → mean over wallet-folds).
  **Inference:** paired wallet-cluster bootstrap (H2 paired on the same wallet resample); fold-by-fold sign.

## SECONDARY tests (frozen now; reported, NOT used to re-tune the entry rule)
1. Large-wallet solo/initiator entries vs other entries (does the "large wallets lead" majors lead replicate?).
2. Small-wallet position-consensus vs small-wallet solo (does the "consensus rescues small" majors lead replicate?).
3. Performance by liquidity bucket (coin ADV / OI tertiles).
4. Performance by coin — descriptive, with NO post-hoc coin removal.
5. Leave-wallet-out and leave-coin-out robustness of H1/H2.

## Decision
- H2 replicates (large > small, most folds, not driven by 1 wallet/coin) → the scale signal is externally
  validated; THEN (and only then) proceed to exit optimization (MAE/MFE) and a deployable design.
- H2 fails with adequate coverage → the majors scale lead does not port to alts; report the powered negative.
- H2 underpowered even on alts → state that and stop (do not tune).
- Secondaries never change the frozen entry rule; they generate hypotheses for a future, separately-registered test.

## Build dependency (cost gate)
Requires the Reservoir raw alt-fills ingest (`research/data/reservoir_ingest.py`) — requester-pays S3 egress
(~$16 full window per the spec) — then an alt episode + 8h-markout build (adapt the majors
episodes/markout pipeline to `alt_fills` + asset_ctx). Firewall: alt data → `research/` only.
