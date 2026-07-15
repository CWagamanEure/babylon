# capday_book — architecture audit findings (consolidated)

**Date:** 2026-07-14. **Target:** `research/studies/copy_cohort/CAPDAY_BOOK_ARCH.md` (design, pre-build).
**Method:** 4-agent design audit — stats-rigor, firewall-leakage, data-integrity, docs-consistency;
static reasoning + tiny synthetic probes; no parquet reads. Below is the orchestrator's consolidation with
the disposition folded into arch **v1.1**.

## CRITICAL / HIGH — must be resolved before build (all folded into v1.1)

- **A1 [HIGH, data-integrity F1 + firewall note + stats F5] — own-exit ASOF direction.** §5 (forward) and
  §7 (backward) contradicted. Backward-ASOF at `close_ts` can match a tick EARLIER than `entry_bar_ts`
  (entry tick is strictly-after-open) → scrambled markout sign on short holds. **Resolution:** pin FORWARD
  ASOF (first tick with `tick.ts >= close_ts`), staleness `tick.ts − close_ts ≤ 90s`, PLUS an explicit
  `close_bar_ts >= entry_bar_ts` guard (else censor). §7 backward wording deleted.
- **A2 [HIGH, docs F1] — wallet-equal co-primary must be BUILT.** `arm_b_book.equal_wtd_net_bp` is
  **episode-equal** (per-trade mean), not wallet-equal; reusing it would defeat the over-carry gate.
  **Resolution:** `capday_book.py` builds a genuine wallet-equal mean + wallet-clustered CI (model on
  `capday_cohort.py`'s `we` path) with its own invariant self-test.
- **A3 [HIGH, stats F1] — own-exit evaluable set is double-tail-truncated on hold length**, and hold length
  is the exact axis own-exit bets on → length-biased, outcome-correlated subsample (short holds dropped by
  `NOT entry_after_close`; long holds censored at data end). Counting the censored rows does NOT de-bias.
  **Resolution:** own-exit reports (a) evaluable-vs-attempted hold-duration distributions, (b) a
  censoring-bounded bracket (best/worst-case markout imputed to censored trades) so the headline is a bound,
  (c) restricts to folds where the cohort's holds mostly complete in-window (flag/exclude the last fold);
  own-exit is framed as conditional-on-close, never as an unconditional mean.
- **A4 [HIGH, stats F2] — exit-week cluster CI understates variance for multi-week holds** (overlapping
  holding windows are correlated; own-exit/48h) → false CONFIRMED risk. **Resolution:** for own-exit and
  48h, report BOTH entry-week and exit-week clusterings and use the WIDER CI for any gate; stamp exit-week
  as a variance lower bound for holds > 1 week.
- **A5 [HIGH, data-integrity F2] — base schema version stamped but never verified** → stale-cache reads
  (fixed output path, no consumer assertion). **Resolution:** a shared `open_base()` reads `_BASE_META.json`
  and asserts `base_schema_version` + `source_markout_schema` + `code_commit` match before any query.

## MED — folded into v1.1

- **A6 [stats F3] — 4-horizon selection uncorrected (FWER ~0.19), no primary named.** **Resolution:**
  pre-register **8h as the single PRIMARY** (the user's literal spec — the claim under test). 24h/48h/own-exit
  are pre-registered **secondary leads**: a positive there is a lead requiring FRESH-data confirmation, never
  a headline CONFIRMED. This controls the horizon family.
- **A7 [stats F4] — verdict taxonomy overlap on (0,+5) bp.** A CI ⊂ (0,5) satisfied both CONFIRMED (CI-low>0)
  and the NEGATIVE CI condition. **Resolution:** add third state **"real but sub-economic / not deployable."**
  CONFIRMED now requires CI-low>0 AND the CI/point not excluding the +5 care-about (CI-hi ≥ 5 or point ≥ 5).
- **A8 [stats F5] — fixed-`H_MS` calendar/exit/peak-exposure paths break for variable own-exit.**
  **Resolution:** `capday_book.py` threads a per-row `exit_ts` array (`close_bar_ts` for own-exit,
  `entry+H` otherwise); `CAL_DAY_HI` from max realized exit_ts.
- **A9 [firewall F1] — matched-random balancing features unsourced; could read forward data.** **Resolution:**
  `coin`/`long_h`/`not_q`/`act_q` computed from episodes with `open_ts < as_of_cutoff_ms(T−1)`; assert no
  balancing feature reads a row at/after cutoff.
- **A10 [data-integrity F3/F4] — per-coin version gating + `code_commit` provenance** missing. **Resolution:**
  per-coin done-markers carrying `BASE_SCHEMA_VERSION`+`code_commit`; add git rev to sidecar + base meta.

## LOW / guardrails — folded

- **A11 [firewall F4]** — build the followed set from `arm_b_book._pull_episodes`'s WHERE clause, NOT
  `capday_cohort._forward_eval` / `_fwd_pool_episodes` (those still filter on `is_liquidation_close` = the
  retracted F2 lookahead).
- **A12 [firewall F2]** — report `entry_after_close` attrition PER HORIZON; the predicate is causally needed
  only for own-exit pricing; keep it (arm_b-audited-clean, symmetric, tiny population) but expose the count.
- **A13 [stats F6 + data-integrity spirit]** — keep close columns out of any SQL touched by selection/sizing;
  assert the entry + sizing queries never reference `close_*` / `raw_markout_close`.
- **A14 [data-integrity F5]** — build-time tripwires: sidecar `count(*) == count(DISTINCT key)`; base
  `n_rows(after) == n_rows(before)` on the LEFT JOIN.
- **A15 [docs F2]** — selection ADDS a `(metric DESC, wallet ASC)` tiebreak (fixes F9); drop the "unchanged"
  wording. **A16 [docs F3 / firewall F1]** — the MCMC sampler reuses, but a capday feature panel + a
  `FoldPanel`-shaped adapter must be BUILT (capday `_pool_scores` returns no features).
- **A17 [stats F7]** — Sharpe is within-horizon descriptive only; not comparable across horizons (own-exit's
  long zero-padded calendar mechanically deflates it). Label as such.

## Confirmed CLEAN (checked, no change)
- Engine firewall intact (no `src/babylon/` import of research). Selection strictly ≤ T−1
  (`_window_days`/`_pool_scores`). Sizing strict-prior, same-ts-safe (`_expanding_clips`). Sidecar key
  `(wallet,coin,opener_block,opener_event_index)` is genuinely 1:1 (ASOF ≤1 right row → no fan-out).
  NULL→NaN censoring is correct (dropped+counted, never zero-filled). Float is the sanctioned signal-layer
  convention; no money-exactness over-claim. The core own-exit lookahead question is SOUND — entry set frozen
  at open, `close_ts` reaches only the exit price, exit-at-close is causal; 0-lag optimism covered by the
  exit-lag sensitivity. `_weighted_twoway_ci` returns `ci_lo`/`point`/`df` as the verdict rules assume.

---

# CODE audit (2026-07-14, post-build) — findings + resolutions

4-agent code audit (correctness, stats-rigor, firewall-leakage, data-integrity) on the built
`capday_book.py` + own-exit sidecar + base. The three retracted `book.py` CRITICALs (F1 masked-array,
F2 liquidation lookahead, F3 non-executable) were confirmed NOT reproduced; core accounting (per-row
exit_ts, wallet-equal CI, dual-week CI, PnL sign/units, 1:1 sidecar key, determinism) confirmed correct.

| # | sev | finding | resolution |
|---|-----|---------|------------|
| C1 | HIGH | balancing-feature cutoff off by one month (`_cutoff_of=as_of_cutoff_ms(T)` = first instant of T+1) → whole test month leaked into the MATCHED-RANDOM benchmark (not the cohort estimate/CI). Flagged by all 3 auditors. | FIXED: `_cutoff_of(T)=as_of_cutoff_ms(MONTHS[i-1])` + runtime A9 assert in `_capday_features`. Re-ran. |
| C2 | MED | sampler validity gates (ESS/chain-spread/band-interpretable) dropped in the K=30 port | FIXED: ported `_random_diagnostics`+`_ess`; per-cell `random_band_interpretable` stamped. |
| C3 | MED | TV balance normalizer hard-coded `2*K=60` even when per-fold membership <30 | FIXED: per-fold `Kf` normalizer in `_try_move`/`final_max_tv`. |
| C4 | MED | week-breadth rank absent (only wallet-breadth) → CONFIRMED gate's wallet+week breadth incomplete | FIXED: `week_frac_net_positive` in light book + `descriptive_rank_week_breadth`. |
| C5 | MED | `sources` global-candidacy filter could crash the assert | ALREADY FIXED pre-audit (per-fold `pool_sets` membership). |
| C6 | MED | open_base doesn't verify sidecar provenance; only base_schema_version | FIXED: `open_close_sidecar()` guard (per-coin CLOSE_SCHEMA_VERSION) + base now also asserts source_markout_schema. |
| C7 | LOW-MED | `x or np.nan` drops legitimate 0.0 breadth values (mild conservative bias) | FIXED: explicit `None`-check `_col()` helper. |
| C8 | MED | own-exit bracket is q25/q75 impute, not a true bound | FIXED: added `TRUE_bound_minmax` alongside the IQR sensitivity + NOTE. |
| C9 | LOW | A14 base row-count tripwire / A13 literal assert absent (structural only) | ACCEPTED (low risk: base = mk⋈ep on 1:1 key, close cols not in base; entry/sizing SQL reference no close_*). |
| C10 | LOW | per-horizon `entry_after_close` attrition not surfaced (A12) | ACCEPTED as documented residual (symmetric, tiny pop; primary is 8h). |
| C11 | NIT | dead `_window_days(T) and` in MONTH_LO; wrong `_cutoff_of` docstring | FIXED. |
| — | LOW | secondary/q75 cells not individually role-stamped (F7) | FIXED: per-cell `role: PRIMARY|SECONDARY_LEAD|SENSITIVITY`. |

**Clean bill:** no masked bincount; liquidation never a forward filter; F0/F3 guards present; forward-ASOF
own-exit with `close_bar_ts>=entry_bar_ts` guard; strict-prior leakage-safe sizing; walk-forward fold
assignment correct; firewall intact (no `src/babylon` import); fixed SEED. Post-fix re-run is the reported
result.
