# Babylon Pitfalls

Recurring statistical and engineering mistakes in Babylon copy-trade/edge-measurement work, and the guards
against them. Ranked by how badly they bias results. Originally compiled 2026-06-30; updated through 2026-07-04.

Several of these produced *believable but wrong* numbers (+159 bp/RT; a clean "no edge" zero), not crashes —
the dangerous kind. Quote any headline edge only at the *deployed* operating point, and cross-check against
an independent pipeline plus the live paper book before believing it.

## Statistical And Methodological

1. **Frozen-pool survivorship** — +159 bp/RT was on a whole-period survivor pool; on a past-only rolling
   universe it falls to ~+40–92. Select the universe using only data through time k (rolling, not frozen).
2. **Wallet's-own-edge vs follower's-lagged-edge** — price RTs at the follower's entry (candle close at
   fill_t+lag), not the wallet's sub-second fill.
3. **edge-over-field ≠ deployable edge** — a constant round-trip cost cancels in `sel−field`; the P&L number
   is *selected return net of cost*.
4. **Look-ahead pricing** — use the last *fully-closed* candle (`_close_at`), never the candle containing t.
5. **Seam leakage** — only count RTs fully closed before T0 (`before_ms`).
6. **Eligibility on closed-RT count** — gate on RAW ACTIVITY instead (survivorship flavor otherwise);
   commit fe44463.
7. **Sortino EPS-explosion** — floor the downside-deviation denominator; commit 9ddf901. Sortino ranking was
   wildly unstable across transitions (0→+77) — never trust without a CI.
8. **No CI / wrong bootstrap** — use a WALLET-CLUSTER bootstrap (resample wallets, not RTs; RTs within a
   wallet are correlated).
9. **Coverage bias** — only ~73% of volume is priceable (symbol perps; `@N` coins lack candles); compare only
   on the matched tradeable subset.
10. **Dangling / MTM-at-cutoff positions** — mark-to-market and dispose open positions at the cutoff, or hold
    out; commits 9ddf901/11a249d (`dangling-held-out`).
11. **startPosition mis-seeding** — a leading unobserved-open position must be held out; the
    `other_repo_notes` export has NO true startPosition (seeded 0) — residual bias on any number off it.

## Engineering Bugs That Corrupt Statistics

12. **polars non-streaming `.collect()` OOM** on 1GB parquet → use `engine="streaming"` / `sink_parquet`.
    polars 1.42 has NO partitioned sink.
13. **`partition_by(as_dict=True)` tuple-key regression** (polars 1.x keys by `('0x…',)`, not bare string)
    → silent `elig=0` "no edge". META-GUARD: validate any pipeline on a known-answer single-wallet probe
    before trusting an aggregate, especially a clean zero.
14. **Fills pagination dropping same-ms fills** — dedup by tid, re-fetch from last_t (not last_t+1).
15. **Float residual staling positions** — reset pos to EXACT 0 on close; use causal (running-max) tolerance
    to match the live stepper.
16. **Backward-peeking counterfactuals manufacture two-sided "skill"** (2026-07 majors-timing episode,
    killed z=+3.86): benchmarking entries vs a DAILY mean of forward returns includes windows starting
    BEFORE the entry → post-move contrarians (dip-buy/rip-sell) earn mechanical positive excess on BOTH
    sides with zero forward drift; style persists → fake month-over-month transfer. Even a two-sided
    (long AND short) certificate does NOT protect. GUARDS: any counterfactual must be measurable-at-entry
    (windows starting >= entry time or state-matched); always run the kill test by scoring selected rosters
    on the RAW copyable quantity (plain post-fill markout) — artifacts collapse there. Suspicion scales with
    effect size (per-entry excess >> known-copyable magnitudes = presumption of benchmark contamination).
17. **Stitching two extractions with different coin conventions** (2026-07-04): an 11-month PnL reconstruction
    merged droplet `parquet_cold/` (Aug–Jan, symbol coins BTC/ETH…) with `other_repo_notes/fills_*` (Feb–Jun),
    but the latter is a DIFFERENT, INCOMPLETE extraction: majors ENTIRELY MISSING, coded `@N` numeric perp
    IDs, ~15% less alt volume, and `@1 ≠ BTC`. A coin-venue test (majors harvest) silently matched NOTHING
    for Feb–Jun; "0 of 7000 wallets trade BTC in April" was the tell. GUARD: before merging sources, reconcile
    coin symbols AND per-coin volumes on a shared alt (same symbol) plus a major; a real relabel matches volume,
    a different extraction won't. For this legacy 11-month PnL reconstruction only, the canonical projection
    was `scratch_conv/mlscreen/cand2_*.parquet` (all 11 months, symbol-consistent, sz pre-signed,
    `crossed`=taker). Never substitute `cand2` for `data/raw/fills` in Gate-A, episode, or other work that
    needs `startPosition` or block identity. Per-coin-MONTH demeaning survives a label mismatch (never crosses
    months); cross-boundary coin-identity tests do not.
18. **Size-blind (equal-weight) metric flatters a non-deployable edge** (2026-07-04): a consistency
    (Sharpe/hit) wallet screen was significant EQUAL-WEIGHT (perm p=0.001) but NOT turnover-weighted/deployable
    (p=0.08) — the edge lived in small/illiquid trades (winning trades too small to fund; fundable large trades
    lose). Median-return and %-wallets-profitable are ALSO size-blind and hid aggregate-negative months.
    GUARD: always report the TURNOVER-WEIGHTED (capital-weighted) return and aggregate dollars, not just
    equal-weight mean / median / %profitable; judge any copy signal at deployable size. Also, "beats random"
    must compare to the random DISTRIBUTION (per-draw p-value), never to its mean; month tallies (`8/10 positive`)
    are NOT independent trials when cohorts share wallets — use a persistent-random-score permutation null.

## Infrastructure Note

The per-wallet split lives at `data/follow/fills_his/` (2431 wallets) via `scripts/split_his_fills.py`; sweep
via `scripts/edge_sweep.py`. The 8GB Mac swaps on full-month reshapes — pre-split once, then sweep cheaply.
For that legacy reconstruction only, the PnL engine (2026-07) is `scratch_conv/pnl_engine.py --cand2-glob
'scratch_conv/mlscreen/cand2_*.parquet'` (wallet-batched, memory-safe on 8GB) → `positions_c2.parquet`.
