# Audit 16 — Capture scorer & re-derivability  (agent: 16_capture_scorer_rederivability)

## Summary
I examined `CaptureScorer` (`scorer.py`), its store/markout dependencies, the
`ReturnsFn/CutoffFn` contract in `scheduler.py`, and the manifest/run_id machinery in
`experiment.py`. The prior audit's #1 CRITICAL re-derivability fix (snapshot the per-T0
`{roundtrip_id→ret_bps}` and fold its content-hash into `run_id`, plus make scoring
deterministic) has **NOT landed** — `run_id` is computed from roster/weights/cutoffs/config
only, and the score reads the live, ephemeral `BookCache` at call time with no archived
mid-log. I also found the capture path silently mixes `source=live` and `source=candle`
round-trips in one Sortino, supplies no `activity_fn` (so swapping it in reverts eligibility
to the disposition-biased closed-count gate, known-issue #6), and does not raise the live
round-trip floor above 2. All are bounded to **selection-power / pre-registration integrity**
because `CaptureScorer` is shadow (not wired into the roll) and feeds selection only — none can
fake a GO. Note these matter the moment the planned swap-in happens.

## Findings

### F1 — Re-derivability fix (#1) did NOT land: run_id folds in no returns content-hash, and the MTM leg reads the live ephemeral book  [HIGH]
- **Where:** `src/babylon/follow/experiment.py:126` (`RunManifest.canonical`) + `:140`
  (`run_id`); `src/babylon/follow/scheduler.py:127` (`RunManifest.build`, no returns digest
  passed); `src/babylon/follow/capture/scorer.py:39` (`self._book.snap(coin, t0_ms, …)`).
- **Blast radius:** selection-power / pre-registration integrity (NOT gate-false-GO — capture
  feeds selection only and is shadow per `scorer.py:11`). By the prior audit's own framing this
  is their #1 CRITICAL; under this audit's blast-radius rule it is HIGH.
- **Failure scenario:** The prescribed fix (LIVE_CAPTURE.md:108-114) is two parts: (a) make
  scoring deterministic by recomputing open-position marks from an archived/durable mid log,
  and (b) snapshot the per-T0 `{roundtrip_id→ret_bps}` actually used and fold its content-hash
  into `run_id`. Neither is present. `canonical()` (experiment.py:126-138) serializes only
  `t0_ms, roster, edge_weights, train_cutoff_tids, config_hash, analysis_script_hash` — the
  return *series* that produced the ranking is nowhere in the hashed body, so `run_id` is
  invariant to the DB content that drove selection. Meanwhile `returns_fn` marks every open
  position against `self._book.snap(coin, t0_ms, self._staleness)` — the *current in-memory*
  `BookCache` top-of-book at the instant the roll executes (markout.py:44-48 returns the latest
  stored book, not a book "as of t0"). Re-run the roll five minutes later, or replay it for an
  audit, and the open-position MTMs change → `ret_bps` change → Sortino ranking can change →
  a *different roster* with the *same run_id* and a manifest that still verifies. The
  hash-chain (experiment.py:182-206) is then tamper-evident about the *outcome* but cannot
  prove the roster is the honest output of the rule on committed inputs — exactly the gap
  must-fix #1 named. The candle path escapes this only because its returns are deterministically
  re-derivable from fills+candles+config (LIVE_CAPTURE.md:104-106); the capture path is not.
- **Why it's real:** `scorer.py:38-43` reads live book state with zero persistence of the
  snapshot used; `experiment.py:120-122` builds the manifest with no returns digest argument,
  and there is no call site anywhere that passes one. Confirmed by grep: the only hashing in the
  follow tree (`run_id`/registry) covers manifest fields, never the return arrays.
- **Confidence:** high.
- **Fix sketch:** (1) Persist the `{(wallet,coin,rid)→ret_bps}` snapshot used at each T0 (incl.
  the open-position MTMs) to a durable per-T0 artifact; (2) add a `returns_digest` field to
  `RunManifest`, include it in `canonical()`; (3) replace the live `BookCache` read in the MTM
  leg with a lookup into an archived/durable sampled-mid log keyed at `t0`, so the score is a
  pure function of committed data. Until then, keep capture as shadow and do not swap.

### F2 — Determinism enumeration: open-book snapshot, dict-iteration order, and un-ordered SQL all make the score non-reproducible  [HIGH (subsumes F1 root causes) / MED for the float pieces]
- **Where:** `scorer.py:38` (`self._sched.open_marked(wallet)`), `scorer.py:39` (live book
  snap), `markout.py:147-158` (`open_marked` iterates `self._rt.items()`),
  `store.py:60-63` (`SELECT ret_bps … ` with **no `ORDER BY`**).
- **Blast radius:** selection-power / re-derivability.
- **Failure scenario — three independent non-determinism sources:**
  1. **Ephemeral book (dominant).** As F1: the open-position exit mark is the latest live book;
     two evaluations at different wall-clock times yield different `ret_bps`. This changes the
     *set* of values, so the Sortino genuinely differs — not just rounding.
  2. **Dict iteration order.** `open_marked` walks `self._rt` (a dict keyed by
     `(wallet,coin,rid)`), insertion-ordered by *fill arrival order*. After a restart, fills
     are re-ingested in a possibly different interleaving → the MTM list is built in a
     different order → `np.concatenate([closed, mtm])` then `np.mean` sums in a different order.
     Same multiset, but float-accumulation order differs.
  3. **Un-ordered SQL.** `store.returns` has no `ORDER BY`; SQLite row order is
     implementation-defined (index vs rowid, ties on `exit_t`). Again changes summation order.
  Sources 2-3 are order-only → tiny float deltas, which only flip a ranking at a near-exact
  Sortino tie, so MED on their own. Source 1 is the HIGH one and is the same defect as F1.
- **Why it's real:** none of these paths sorts or pins state; the test
  (`test_capture_scorer.py`) only asserts set-equality (`sorted(r.tolist())`) and signs, so it
  would not catch order- or book-dependence.
- **Confidence:** high for the enumeration; the float-tie flip is low-probability but possible.
- **Fix sketch:** add `ORDER BY rid` (or `exit_t, rid`) to `store.returns`; sort `open_marked`
  output by `(coin, rid)`; and the F1 archived-mid-log fix removes source 1.

### F3 — Look-ahead: open-position MTM accepts a book newer than the cutoff  [MED]
- **Where:** `scorer.py:39` → `markout.py:44-48` (`BookCache.snap`).
- **Blast radius:** selection-power (upward/biased score for open positions); offline only if
  the score is replayed.
- **Failure scenario:** `snap(coin, now=t0_ms, staleness_ms=30_000)` rejects a book only when
  `now - b.ts > staleness`, i.e. when the book is *older* than t0 by >30 s. A book with
  `b.ts > t0_ms` (newer than the cutoff) yields a negative difference → passes → the open
  position is marked at a price observed **after** the seam. In strict live-forward operation
  the latest book is ≈ wall-clock-now ≈ t0 so the leak is small, but there is no guard that
  `b.ts ≤ t0_ms`; any delayed roll, clock skew, or replay where the cache holds a post-t0 book
  marks the open MTM with future information. The closed-leg seam is correctly guarded
  (`store.returns` uses `exit_t < t0`), so this asymmetry means the open positions — the very
  ones the disposition fix adds — are the only legs that can see past the cutoff.
- **Why it's real:** the freshness predicate is one-sided (only catches staleness, not
  futureness); there is no `b.ts <= t0_ms` check.
- **Confidence:** medium (small in pure live; real under replay / delayed roll).
- **Fix sketch:** in the MTM leg require `b.ts <= t0_ms` (reject future books) in addition to
  the staleness bound — or, per F1, mark from the archived mid-log at exactly `t0`.

### F4 — Source tagging ignored: live and candle round-trips are blended in one Sortino  [MED]
- **Where:** `scorer.py:35` (`self._store.returns(wallet, lo, t0_ms)`); `store.py:56-63`
  (query selects `ret_bps` with **no `source` filter**); `markout.py:75` (`source` column
  exists, default `"live"`).
- **Blast radius:** selection-power.
- **Failure scenario:** the design (LIVE_CAPTURE.md:182-188) keeps `source=candle` round-trips
  in the store as the re-fetchable floor and asserts the forward-only invariant that "backfill
  stays candle-tagged + separate" (line 88). But `store.returns` pulls *all* rows for the
  wallet regardless of `source`, so the moment any `source=candle` rows coexist with
  `source=live` rows for a wallet (the explicit degraded-capture path), the Sortino mixes two
  differently-biased, differently-variance estimators (coarse candle-proxy marks vs sharp
  aggressing-touch book marks) on one scale with no weighting — precisely hypothesis 5. This
  also violates the stated forward-only separation invariant.
- **Why it's real:** there is no `WHERE source=?` anywhere in the read path, and the writer
  defaults `source="live"` but the schema and docs explicitly anticipate candle rows in the
  same table.
- **Confidence:** medium — depends on whether candle rows are actually written to this DB
  today (they are not in the current shadow wiring), but the code provides no guard, so it is a
  latent correctness bug the moment the documented degraded path is used.
- **Fix sketch:** parameterize `store.returns` by `source` (default `'live'`) and have the
  scorer score live-only, or carry source through and stratify/calibrate before ranking.

### F5 — Capture path supplies no activity_fn and no raised live floor → eligibility reverts to disposition-biased closed-count (known-issue #6) and winner's-curse floor (#4)  [MED]
- **Where:** `scorer.py` (class exposes `returns_fn`, `cutoff_fn`, `active_candidates` —
  **no `activity_fn`**); `scheduler.py:99,119-124` (activity gating only when `activity_fn`
  supplied); `scheduler.py:70-75` (fallback to `len(r) >= min_positions` closed-count gate);
  `scorer.py:52-54` (`active_candidates` gates on closed round-trip count).
- **Blast radius:** selection-power.
- **Failure scenario:** the raw-activity eligibility fix (commit fe44463, known-issue #6) is
  implemented in `SelectionAdapter.activity_fn` (selection.py:65-72) and consumed only when
  `RollScheduler` is given an `activity_fn`. `CaptureScorer` provides none, so a swap-in lands
  in the `else` branch of `select_roster` (scheduler.py:73-75) and gates eligibility on
  *closed-round-trip count* — exactly the disposition-correlated gate fe44463 removed. Worse,
  `active_candidates` (the capture discovery path) also gates on closed round-trip count
  (`store.active_wallets … HAVING COUNT(*)>=min_n`), re-introducing the survivorship+disposition
  coupling (must-fix #5). Separately, must-fix #4's "raise the live-eligibility floor ≫6" is
  not honored: with activity gating the only floor on the live *return series* is `len(r) >= 2`
  (scheduler.py:72), so a fresh wallet with 2 noisy live round-trips can be ranked and selected
  on the max of a tiny sample → winner's curse, the worst case at warm-up.
- **Why it's real:** confirmed by absence — there is no `activity_fn` method on `CaptureScorer`
  and no stratification/quota-per-source or empirical-Bayes shrink anywhere in `select_roster`
  (it is a plain `sorted(... -_sortino ...)`), so must-fix #4's stratify/calibrate/shrink is
  unimplemented.
- **Confidence:** high that the wiring is absent; medium on impact since the swap is not yet
  done (shadow).
- **Fix sketch:** add a raw-fill `activity_fn` to `CaptureScorer` (mirror selection.py) and
  pass it to `RollScheduler`; raise the live round-trip floor well above 6 for `source=live`
  wallets; add per-source stratification or rank-shrinkage before selection.

### F6 — cutoff_fn returns a timestamp where the manifest field is "train_cutoff_tids"  [LOW / NIT]
- **Where:** `scorer.py:48-50` (`cutoff_fn` returns `t0_ms`); contract at
  `scheduler.py:28-29` ("→ the wallet's last train-window fill **tid**"); stored into
  `RunManifest.train_cutoff_tids` (experiment.py:104,132-133).
- **Blast radius:** reporting-only (audit-record semantics). `train_cutoff_tids` is recorded in
  the manifest but is **not** consumed by the runner for live fill filtering (grep found no
  runtime use outside experiment.py/scheduler.py); the capture seam is enforced inside
  `store.returns` (`exit_t < t0`), which is correct. So functionally fine, but the manifest will
  carry ~1e13 timestamps under a field named/typed as tids for capture-scored wallets,
  inconsistent with the candle path (selection.py:74-82 returns a real max tid). An auditor
  reading the manifest cannot tell a timestamp from a tid.
- **Confidence:** high (it is functionally inert today, purely a record-semantics mismatch).
- **Fix sketch:** either rename the field to a source-agnostic `train_cutoff` or have the
  capture path record the wallet's last train-window fill tid (it has the fills via ingest).

## What I could not rule out / did not check
- Whether `source=candle` rows are ever actually written into the capture `RoundtripStore`
  today (F4 severity hinges on this). The writer path (FillIngest/stepper → markout) was out of
  scope; I confirmed only that the *read* path has no source guard. A grep of the ingest writer
  for a non-"live" source would settle it.
- The empirical magnitude of the warm-up winner's curse (F5) — that needs the live DB, which is
  out of scope for a static pass.
- Cross-ref: audit 18 owns the gate/pre-registration determinism of the *candle* path; F1 here
  is specifically the capture path's missing returns-digest, complementary to 18.
