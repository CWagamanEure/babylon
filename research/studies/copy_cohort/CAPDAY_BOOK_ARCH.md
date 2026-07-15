# CAPDAY_BOOK — clean causal copy-book for the top-30 capped-PnL/active-day cohort

**Status:** architecture **v1.1** (post architecture-audit; see §12 for the audit resolutions A1–A17 that
amend the sections below). Audit trail: `audit/copy_cohort_capday_book/{SCOPE,FINDINGS}.md`.
**Lineage:** supersedes the retracted `book.py` (top-30/CAP=100k/8h — invalid: F1 masked-array Sharpe
fabrication, F2 liquidation lookahead, F3 non-executable entries; see
`audit/copy_cohort_top30_book/FINDINGS.md`). Ports the leakage-clean accounting of `arm_b_book.py`
(top-100/formation-bps/4h) onto the user's exact selector and adds the two untested levers the ledger
repeatedly flagged: **longer horizons (24h/48h) and the wallets' OWN exit.**

## 1. Question / estimand
Does a follower who copies the **top-30 capped-PnL-per-active-day** cohort's forward opening-taker majors
entries, dollar-sized by a leakage-safe prior-notional clip, earn a positive net book — and does the answer
change with exit horizon? Evaluated at **{8h, 24h, 48h, own-exit}**.

**Pre-registered PRIMARY horizon = 8h** (the user's literal spec — the claim under test). 24h/48h/own-exit
are pre-registered **secondary leads**: a positive there is a lead requiring FRESH-data confirmation, never
a headline CONFIRMED (controls the 4-horizon family-wise error — A6).

Two pre-registered estimands, both reported for every horizon:
- **PRIMARY (the "trade it" object):** dollar-weighted net bp of the q50-sized book, with a two-way
  **wallet × week** cluster CI (`_weighted_twoway_ci`, ported from `arm_b_book.py:110`; week = epoch-week
  bucket of the exit day).
- **CO-PRIMARY (anti-over-carry, the per-decision quantity a copier experiences):** a **genuine
  wallet-equal** mean net bp with a **wallet-clustered CI** — BUILT NEW (model on `capday_cohort.py`'s `we`
  path), NOT `arm_b_book.equal_wtd_net_bp`, which is episode-equal and would defeat the over-carry gate
  (A2). Its own invariant self-test is required.

Care-about margin = **5 bp** net (follower economics). Cost = **2×1.3 bp** taker round-trip (`RT_COST_BP`),
every horizon incl. own-exit (follower takes in and takes out).

## 2. Selection (the user's spec — reuse `capday_cohort._pool_scores`/`_window_days`)
Per test month T ∈ `MONTHS[3:]` (monthly roll): 3-month trailing formation window, data STRICTLY ≤ T−1
(`_window_days`), pool = wallets with ≥15 active days, metric = capped-PnL-per-active-day
(`_pool_scores`, CAP_DAILY=$100k), **cohort = top-30 by metric**. ADD a deterministic tiebreak
`(metric DESC, wallet ASC)` — a change from the current single-key `argsort()[::-1]` (fixes audit F9, A15).
No forward information touches selection (audit-confirmed pre-cutoff).

## 3. Forward follow + causal guards (the F1/F2/F3 fixes — non-negotiable)
Followed set = cohort's opening-taker episodes opened in T, pulled from the widened base table with, in the
WHERE clause (mirrors `arm_b_book._pull_episodes:331`, NOT the buggy `book.py`):
- `crossed_open AND NOT opener_flagged` — real taker openers;
- **`NOT entry_after_close` AND `entry_lag_s <= 90`** (F3 / F0) — executable, non-stale entries;
- **`initial_notional_usd > 0`**;
- **liquidation is NEVER a forward filter** (F2). `is_liquidation_close` is carried only as an ex-post
  diagnostic; it does not delete or select any followed entry.
Build the followed set from `arm_b_book._pull_episodes`'s WHERE clause — NOT `capday_cohort._forward_eval`
/ `_fwd_pool_episodes`, which still filter on `is_liquidation_close` (the retracted `book.py` F2 lookahead)
(A11). Report guard attrition (attempted → F0-eligible → sizeable → evaluable → censored) for cohort AND
random, broken out **per horizon** — `entry_after_close` is causally required only for own-exit pricing;
it is kept for all horizons (arm_b-audited, symmetric, tiny population) but its count is exposed (A12).

## 4. Sizing (leakage-safe, unchanged from `arm_b_book`)
Per (wallet, coin), clip = **qXX percentile of that wallet's PRIOR opening-taker notionals in that coin**,
strict-prior expanding, via the Fenwick order-statistic quantile (`_expanding_clips:59`) — all rows at a
timestamp are read before any insert, so same-ts entries cannot size one another. q50 PRIMARY, q75
SENSITIVITY. No prior same-coin trade → un-sizeable → skipped and COUNTED (never default-filled).

## 5. Horizons + own-exit (the new axis)
`horizon ∈ {8h, 24h, 48h, own}` is a parameter; each horizon runs the full pipeline independently (its own
matched-random book, CI, MDE, breadth) — no cross-horizon max is taken into one headline.
- **Fixed 8h/24h/48h:** `mk = raw_markout_<h>` (dir-signed, staleness-bounded, already in the master);
  exit_ts = `entry_bar_ts + H_MS`. Requires widening `base.py` MK_COLS (§7).
- **Own-exit:** `mk = raw_markout_close`, `exit_ts = close_bar_ts` (the matched close tick), from the
  **sidecar** (§7). Follower enters at `entry_bar_ts` and exits at the first price tick with `tick.ts ≥
  close_ts` (**FORWARD ASOF**, staleness `tick.ts − close_ts ≤ 90s`), i.e. "exit as soon as the wallet's
  close is observed," PLUS a `close_bar_ts ≥ entry_bar_ts` guard (else censor) so a sub-cadence scalp can't
  match a tick before entry (A1). Per-episode horizon (variable hold). `close_ts` NULL / >90s stale /
  beyond lattice → `raw_markout_close` NULL → **censored** (dropped from P&L, counted).
  - **Own-exit is double-tail-truncated on hold length** (short holds dropped by `NOT entry_after_close`,
    long holds censored at data end) — and hold length is the very axis own-exit bets on. So own-exit is
    reported as a **conditional-on-close** estimand with (a) evaluable-vs-attempted hold-duration
    distributions, (b) a **censoring-bounded bracket** (best/worst-case markout imputed to censored trades),
    (c) restriction to folds where the cohort's holds mostly complete in-window (flag/exclude the last fold)
    (A3). Its two-way CI reports BOTH entry-week and exit-week clustering; the WIDER is used for any gate,
    because overlapping multi-week holds break exit-week independence (A4).
  - Exit-detection lag reported as a SENSITIVITY (0 vs a small positive lag), not hidden.

## 6. Matched-random benchmark (longitudinal, fixes audit F6)
Reuse `arm_b_book.py`'s trajectory-preserving MCMC sampler internals (`_trajectory_arrays` / `_sample_paths`
/ `_try_move`, N=1000 paths, 4 chains) so random cohorts preserve real-wallet **tenure and persistence across
overlapping formation windows** — NOT `book.py`'s independent monthly redraws. NOTE the sampler consumes a
`FoldPanel.features`/`.pool` object from `selectors.build_formation`; capday `_pool_scores` returns no
features, so a **capday feature panel + a `FoldPanel`-shaped adapter must be BUILT** to feed it (A16).
Balance on capday formation features computed from episodes with **`open_ts < as_of_cutoff_ms(T−1)`**
(pre-cutoff only; asserted — A9), analogous to `selectors.py:199`: `act_q` (active-day count quantile),
`not_q` (median-notional quantile), `coin` (dominant formation coin), `long_h` (long-share≥0.5).
**MCMC ranks are DESCRIPTIVE, never finite-sample p-values** (stamped `mcmc_rank_status` in the report). The
sampler's validity gates (acceptance, unique-fraction, ESS≥400, chain-mean spread, dispersed starts) carry
over; if a gate fails the band is labeled non-interpretable.

## 7. Data build (additive, non-destructive)
- **Own-exit sidecar** — extend `research/data/markout.py` with a `close`-only mode: one **forward**-ASOF at
  `close_ts` on the same `px` view (A1), emitting `ph_close`, `raw_markout_close = dir_sign·(ph_close−p0)/p0·1e4`,
  `close_bar_ts` (matched tick, guarded `≥ entry_bar_ts`), `close_lag_s`, keyed by
  `(wallet,coin,opener_block,opener_event_index)` → `data/derived/episodes_markout_close/coin=*/part.parquet`,
  provenance-stamped with `schema_version` + **`code_commit`** (A10). Master untouched. Build-time tripwire:
  `count(*) == count(DISTINCT key)` (A14).
- **Base** — `base.py`: add `raw_markout_24h`, `raw_markout_48h` to `MK_COLS`; LEFT JOIN the close sidecar on
  the 1:1 key; bump `BASE_SCHEMA_VERSION`; per-coin done-markers carrying version+commit (A10); rebuild
  `data/derived/copy_cohort/base/` (4 majors, seconds). Tripwire: `n_rows(after) == n_rows(before)` (A14).
  A shared `open_base()` asserts on-disk `base_schema_version`/`source_markout_schema`/`code_commit` match
  before any query — no silent stale-cache reads (A5). Close columns live ONLY in the base for the book's
  exit pricing; the entry + sizing SQL must never reference `close_*`/`raw_markout_close` (asserted, A13).

## 8. Accounting invariants (the anti-fabrication contract — audit F1/F5)
- Every P&L / Sharpe / CI array is built ONLY on explicit **evaluable** rows = finite clip AND finite `mk`
  (assert `n_evaluable == finite-mk count`). NO masked `np.bincount` anywhere (the F1 defect).
- **Per-row `exit_ts` array** (`close_bar_ts` for own-exit, `entry_bar_ts + H` otherwise); `CAL_DAY_HI` is
  derived from the MAX realized exit_ts, not a fixed `H_MS` — else own-exit late closers IndexError or
  misbucket (A8). Every `exit_ts`/`exit_day`/peak-exposure computation uses this array.
- Sharpe: closed-trade net credited at **exit_ts** on a full UTC calendar with zero-days, sample SD
  (ddof=1), √365 (`_book:392`), initial equity 0 prepended. NOT credited at entry, NOT √252. Within-horizon
  descriptive only (A17).
- Report peak concurrent gross, net-return-on-peak-gross, leave-one-wallet / leave-one-week min–max,
  top-trade and top-wallet share of positive PnL (concentration = the over-carry mechanism).
- `_ci_invariants()` self-test must pass at run start (shift/scale/duplication/equal-clip identities).

## 9. Verdict rules (frozen; over-null AND over-carry applied symmetrically)
For each (horizon, q) report the always-pending quad: **point estimate + two-way CI + empirical MDE +
cross-unit breadth** (fold beats-random count, wallet/week net-positive fraction ranks).
Verdict applies to the PRIMARY 8h q50 cell; 24h/48h/own-exit yield secondary leads only (A6).
- **CONFIRMED live positive (deployable)** only if: two-way CI-low > 0 **AND** the CI/point does NOT exclude
  the +5 bp care-about (CI-hi ≥ 5 **or** point ≥ 5) **AND** wallet-equal co-primary CI-low > 0 **AND** ≥4/5
  folds beat the matched-random median **AND** wallet+week breadth ranks are not chance-like (A7).
- **REAL BUT SUB-ECONOMIC (not deployable)** — CI ⊂ (0, +5): a genuine but below-care-about edge; recorded,
  not deployed, not a confirmation (A7).
- **Method-scoped NEGATIVE** ("no copyable edge from this selector at horizon h") only if the CI EXCLUDES the
  +5 bp care-about on the high side with **MDE ≤ 5 bp** (a powered null — the anti-ratchet earns the word).
- **Otherwise INCONCLUSIVE/UNDERPOWERED** — surface the positive point estimate + direction, never bury it.
- Multiplicity ledger: 4 horizons × 2 q = 8 cells, enumerated; q75 and the secondary horizons are
  SENSITIVITY/lead, never promoted to a headline CONFIRMED. Any positive faces the mandatory separate
  steelman + prosecutor passes. Sharpe is within-horizon descriptive only, not cross-horizon comparable (A17).

## 10. Order of work
arch (this) → architecture audit swarm (`audit/copy_cohort_capday_book/SCOPE.md`) → sidecar build + probe →
base widen + rebuild → `capday_book.py` build → code audit swarm → run 4 horizons × 2 q → steelman +
prosecutor (separate agents) + construction-conservatism → `FINDINGS.md`.

## 12. Audit resolutions (v1.1 — binding index)
Full detail in `audit/copy_cohort_capday_book/FINDINGS.md`. These amend the sections above and are binding
on the build:
- **A1** own-exit = FORWARD ASOF at `close_ts`, ≤90s, guard `close_bar_ts ≥ entry_bar_ts` (§5/§7).
- **A2** wallet-equal co-primary is BUILT (mean + wallet-clustered CI), not `equal_wtd_net_bp` (§1).
- **A3** own-exit conditional-on-close: hold-duration dists + censoring-bounded bracket + last-fold flag (§5).
- **A4** own-exit/48h CI: report entry- AND exit-week clustering, use the wider for the gate (§5/§9).
- **A5** `open_base()` asserts on-disk schema_version + source_markout_schema + code_commit (§7).
- **A6** 8h is the single PRIMARY; 24h/48h/own-exit are secondary leads needing fresh confirmation (§1/§9).
- **A7** third verdict state "real but sub-economic"; CONFIRMED must not exclude +5 care-about (§9).
- **A8** per-row `exit_ts` array; `CAL_DAY_HI` from max realized exit_ts (§8).
- **A9** balancing features from `open_ts < cutoff(T−1)` only, asserted (§6).
- **A10** per-coin done-markers + `code_commit` in sidecar/base provenance (§7).
- **A11** followed set from `_pull_episodes`, never `_forward_eval` (§3).
- **A12** per-horizon `entry_after_close` attrition reported (§3).
- **A13** entry + sizing SQL never reference `close_*` (asserted) (§7).
- **A14** build tripwires: sidecar distinct-key, base row-count-unchanged (§7).
- **A15** selection adds `(metric DESC, wallet ASC)` tiebreak (§2).
- **A16** build a capday feature panel + `FoldPanel` adapter for the sampler (§6).
- **A17** Sharpe within-horizon descriptive only (§8/§9).

## 11. Honest prior
On majors the power wall (per-trade markout sd ~164 bp, ~54 forward cohort-wallet-months) makes UNRESOLVED
likely even clean — EXCEPT own-exit / 48h, where these position-traders' edge may live and per-trade $ is
larger. A clean UNRESOLVED with MDE≫5 is not a negative; a clean CI excluding +5 with MDE≤5 earns the
method-scoped negative. Alts (needs alt `closed_pnl` re-pull) remain the separate higher-upside path.
