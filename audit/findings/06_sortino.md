# Audit 06 — Sortino / ranking math & stability  (agent: 06_sortino_ranking)

## Summary
Examined the Sortino ranking statistic across the live selection path
(`scheduler._sortino` + `select_roster`), the live capture scorer (`capture/scorer.py`),
the offline sweeps (`edge_sweep.py`, `convergence_test.py`, `convergence_his.py`), the
Kelly weighting (`weights.py`), and the reporting metric (`stats/metrics.py`). **Good news
first, bounding severity:** Sortino never feeds the GO/NO-GO gate — `rank_wallets`
(`skill.py:240`, the copy-backtest pipeline behind `log_growth_gate`) ranks by **median**,
and `_sortino` has a single shared definition used by the live roller and all offline
scripts. So every Sortino defect here is **selection-power (HIGH at most)** or
reporting-only — it cannot fabricate a false GO. The EPS-floor fix (9ddf901) is real but
**incompletely fixed**: the floor is *self-relative* to each wallet's own std, so it bounds
Sortino only at 4×Sharpe and still lets small-n, low-dispersion wallets explode the rank
(F1). There is also a *second, divergent* `sortino` in `stats/metrics.py` with the opposite
zero-downside behavior (F2), and no shrinkage/n-penalty at the selection stage (F3).

## Findings

### F1 — EPS-floor fix is self-relative → small-n, low-dispersion wallets still explode the rank  [HIGH]
- **Where:** `src/babylon/follow/scheduler.py:48-51` (`_sortino`), consumed at
  `scheduler.py:78` (`select_roster` ranking) and `scheduler.py:71-72` (eligibility floor
  `len(r) >= 2`).
- **Blast radius:** selection-power (live roster corruption → power loss → biases the live
  experiment toward INCONCLUSIVE; does **not** reach the gate). Same defect also weakens the
  optional `--stat sortino` diagnostic in `edge_sweep`/`convergence_*`, but those default to
  `median` and are not the headline.
- **Failure scenario:** The floor is `floor = 0.25 * r.std() + 1e-9` and the ratio is
  `mu / max(dd, floor)`. The docstring claims a no-loser wallet "scores ~4×Sharpe, not +∞."
  That bound is *relative to the wallet's own Sharpe*, which is itself unbounded for a
  tight, small sample:
  - n=2, returns `[+10, +30]` (both positive ⇒ `dd=0`): `mu=20`, `std=10`, `floor=2.5`,
    Sortino `= 20/2.5 = 8.0`.
  - A genuine high-n wallet with real edge but real downside, e.g. `mu=15`, `dd=40`:
    Sortino `= 0.375`.
  The lucky 2-RT wallet (Sortino 8) ranks ~20× above the genuine wallet (0.375) and
  saturates the top quintile / top-N. For *any* true-zero-edge wallet, both of 2 draws are
  positive ~25% of the time, so a large fraction of noise wallets with exactly 2 RTs get an
  inflated no-downside Sortino. Eligibility does **not** stop this: `len(r) >= 2` admits
  n=2, and the `activity >= min_positions` gate (`scheduler.py:72`) counts raw *fills*, not
  *returns* — a wallet with 6 fills can have only 2-3 closed RTs and still pass.
  - **Residual hard-explosion:** if all returns are *exactly* equal and positive (`std==0`),
    `floor = 1e-9` and Sortino `= mu·1e9`. Realistically rare in continuous bps data, but
    the 1e-9 absolute floor means the original +∞ artifact is only *probability-suppressed*,
    not eliminated.
- **Why it's real (not theoretical):** `select_roster` ranks strictly by
  `-_sortino(eligible[w])` with no n-penalty and no absolute scale in the floor; the floor
  references only that same wallet's `r.std()`. There is no cross-wallet or minimum-absolute
  dispersion term anywhere in the path. The known-issue list (#7) treats this as fixed; it is
  fixed only for the dd→0-with-std>0 case, not the std-also-small case that small samples
  routinely produce.
- **Confidence:** high (pure arithmetic on the shown lines; no execution needed).
- **Fix sketch:** make the floor reference an *absolute / pooled* dispersion scale, not the
  wallet's own std (e.g. `floor = max(0.25*r.std(), k*median_abs_return_across_pool)`), and/or
  add an explicit small-n penalty (shrink Sortino toward 0 by `n/(n+n0)` or raise the
  returns-eligibility floor above 2). Cheapest defensive change: raise the hard `len(r) >= 2`
  returns floor to a value where the no-downside-by-luck probability is small (e.g. ≥5-6).

### F2 — Two divergent `sortino` definitions in the tree (floored vs unfloored, opposite zero-downside)  [MED]
- **Where:** `src/babylon/follow/scheduler.py:34-51` (`_sortino`, floored) vs
  `src/babylon/stats/metrics.py:172-179` (`sortino`, unfloored). The metrics one is consumed
  by `compute_metrics` → `copy_backtest.py:134` (reported in `CopyBacktestResult.metrics`).
- **Blast radius:** reporting-only (the metrics version is in the report dataclass; the gate
  is `log_growth_gate`, selection is median `rank_wallets`). Listed because hypothesis #1
  specifically asked whether a second Sortino with a different floor exists — it does, just
  not on the live selection path.
- **Failure scenario:** The two functions disagree on the **sign-defining** zero-downside
  case. `scheduler._sortino`: no-downside ⇒ `mu/floor` ⇒ large *positive* (≈4×Sharpe, ranks
  **top**). `metrics.sortino` (line 179): `return mean/dd if dd > 0 else 0.0` ⇒ no-downside
  ⇒ **0.0** (ranks **bottom**, indistinguishable from a flat/edgeless wallet). Same name,
  opposite semantics. A reader comparing the live roster's Sortino to the copy-backtest
  report's Sortino for the same wallet would see contradictory numbers and could mis-tune
  thresholds. It also means the "Sortino" shown in the backtest report is *not* the statistic
  selection actually uses.
- **Why it's real:** both functions exist and are imported independently; nothing reconciles
  them. Confirmed `copy_backtest` ranks via `rank_wallets` (median), so this stays
  reporting-only today — but it is a live trap if anyone wires the backtest Sortino into a
  decision.
- **Confidence:** high (both definitions read directly).
- **Fix sketch:** have one call the other, or have `metrics.sortino` apply the same
  self-floor (or rename one) so the codebase has a single Sortino semantics.

### F3 — No shrinkage / n-penalty at the *selection* rank; SNR shrinkage exists only downstream in Kelly weights  [MED]
- **Where:** selection at `scheduler.py:78` (`sorted(..., key=-_sortino)`) has no shrinkage;
  the only shrinkage is `weights.py:34-36` (`snr = a.size*mu*mu/var; shrink = snr/(1+snr)`).
- **Blast radius:** selection-power. Prior audit (known #8 / task hypothesis #5) asked for
  rank shrinkage; it landed on the *Kelly weight*, not the *rank*. So a noisy small-n wallet
  is still **selected** into the roster by raw Sortino (displacing a better wallet — a power
  loss), then merely *under-weighted* by SNR. The self-healing is partial: an n=2 `[+10,+30]`
  wallet gets `snr = 2·400/100 = 8`, `shrink = 0.89`, raw weight `∝ 0.89·20/100 = 0.178` —
  a *material*, non-negligible weight, not a near-zero one. So noise wallets both occupy
  roster slots and carry real consensus weight.
- **Why it's real:** the rank key is the unshrunk `_sortino`; SNR shrink is applied only
  inside `_kelly_proportional` after the top-N cut. Roster membership (the displacement cost)
  is decided before any shrinkage runs.
- **Confidence:** high.
- **Fix sketch:** rank on a shrunk statistic (empirical-Bayes Sortino, or Sortino × n/(n+n0))
  rather than raw Sortino, so the top-quintile cut itself resists small-n noise.

### F4 — Downside target is MAR=0 gross-of-cost (consistent, but ignores per-RT cost)  [LOW]
- **Where:** `scheduler.py:48` (`neg = np.minimum(r, 0.0)`).
- **Blast radius:** selection-power.
- **Failure scenario:** downside is measured below **0**, and `r` is gross of the ~8 bp
  round-trip cost (cost is subtracted later as a pooled constant in `edge_sweep._boot_ci`).
  A wallet whose RTs cluster in `(0, +8)` bp gross is **net-negative** yet registers *zero*
  downside ⇒ inflated Sortino ⇒ selected, while a wallet with `+30/-10` swings (genuinely
  net-positive on average) eats a downside penalty. The MAR choice systematically favors
  low-vol, marginally-positive-gross wallets over higher-vol genuinely-profitable ones.
- **Why it's partly OK:** MAR=0 is documented intent (`Sign(Sortino)=sign(mean)` so selected
  wallets get positive Kelly weight) and it is **consistent** offline and live (single
  function), satisfying hypothesis #3's consistency requirement. The defect is the choice of
  threshold, not an inconsistency.
- **Confidence:** medium (the cost is constant across wallets so it doesn't *bias the field
  comparison*; it does bias *which* wallets rank top).
- **Fix sketch:** if cost-aware ranking is intended, set MAR to the per-RT cost
  (`np.minimum(r - cost, 0.0)`); otherwise document that ranking is deliberately gross.

## Checked and clean / could not rule out
- **Hypothesis #1 (live scorer reintroduces the explosion via a different floor): CLEAN for
  the live path.** `CaptureScorer` (`capture/scorer.py`) computes *no* Sortino — it only
  produces the returns array (closed RTs + MTM of opens); `RollScheduler` then applies the
  one shared `scheduler._sortino`. So the live capture path and the candle path use an
  identical floor by construction. (The only second definition is the reporting-only
  `metrics.sortino` — see F2.)
- **Hypothesis #4 (annualization / sqrt(n) frequency bias): CLEAN.** `_sortino` is a raw
  `mean/dd` ratio with no time-scaling or sqrt(n) factor, so it is dimensionless and
  sample-size-invariant in expectation — no high-frequency annualization bias. The frequency
  dependence that does exist enters only through estimate *variance* at small n, which is F1.
- **Hypothesis #6 (median vs Sortino select different rosters / different edge): could not
  settle statically** — resolving it needs running `edge_sweep`/`convergence_*`, which is
  out of scope for a STATIC pass and barred from loading the monthly fills. The in-repo
  reference numbers in `convergence_his.py:128` (median +10.7 vs Sortino +9.6 neutralized)
  suggest *modest* disagreement, i.e. the headline edge is not wholly rank-statistic
  dependent, but this is documentation, not a re-run. A bounded per-wallet probe ranking the
  same `elig` set both ways and comparing roster overlap would settle it.
- **Gate isolation: confirmed.** Sortino is absent from `rank_wallets`/`log_growth_gate`;
  the gate ranks by `median_bps` (`skill.py:240`). This is why every finding above is capped
  at HIGH (selection-power), not CRITICAL.
