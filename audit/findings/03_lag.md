# Audit 03 — Follower-lag pricing model  (agent: 03_follower_lag)

## Summary
I traced the `lag` constant end-to-end: where it is defined, what value feeds the offline
edge estimate, the live selection ranking, the capture markout, and what the *real* live
detect→enter latency actually is. The lag model is **honest in direction but mis-specified in
two ways that inflate confidence in lag-robustness and bias selection optimistic**. The
single most important finding: at the system's **hourly** candle resolution the deployed
`lag_bucket_ms=60_000` is **almost a no-op** — it changes the priced candle for only ~1.7% of
legs versus `lag=0`, so the offline sweep's apparent "edge survives realistic lag" is largely
a quantization artifact, not evidence. None of this can fake a GO: the gate reads realized
paper fills priced at the real L2 book and real latency (no candle-lag in `decide`/`Results`),
so every finding is bounded to **offline-estimate / selection-power**, not gate-false-GO.

## Lag value census (hypothesis 1 — "is lag one shared value?")
- **`lag_bucket_ms = 60_000` (60s)** — `main.py:61` `locked_config`. The "SINGLE headline lag"
  (`experiment.py:52`). Flows ONLY to `selection.py:62` (`followable_returns(... lag_ms=cfg.lag_bucket_ms)`).
- **`rank_followable` default `lag_ms = 300_000` (5min)** — `followable.py:131`; **`oos.py:44/107`
  default `300_000`.** Different default; overridden in the live path by config, but a direct/older
  analysis caller silently prices at 5-min lag.
- **edge_sweep `--lags = "0,30000,60000,300000,900000"`** — `edge_sweep.py:102` (point lags).
- **convergence_test / convergence_his `--lag-ms` default `60_000`** — `convergence_test.py:108`,
  `convergence_his.py:72`.
- **capture `MarkoutScheduler(lag_ms=…)`** — `markout.py:79`, a **required param with no default
  and NO link to `ExperimentConfig.lag_bucket_ms`.** It is never instantiated in `src/` — only in
  tests, at hardcoded `0 / 10 / 60_000` (`tests/test_capture_*`). `CaptureScorer` (the eventual
  live ReturnsFn, `scorer.py`) never receives `config`.
- **Gate (`decide`/`Results`, `experiment.py:253–311`)** — uses NO lag. Confirms blast-radius bound.

So lag is **not** one enforced shared value; it is repeated as ≥3 different defaults across
modules and is structurally disconnected on the capture path.

## Findings

### F1 — Hourly-candle resolution quantizes the 60s follower lag into a near-no-op  [HIGH]
- **Where:** `followable.py:37` (`_CANDLE_MS = 3_600_000`), `:40-50` (`_close_at`), applied at
  `:74-75` / `:115-116`; same logic in `edge_sweep.py:54-66`. Driven by `lag_bucket_ms=60_000`
  (`main.py:61`) for selection.
- **Blast radius:** offline-estimate + selection-power (NOT gate — see Summary).
- **Failure scenario:** `_close_at(lookup, t)` returns the close of the last candle *fully closed*
  by `t`, i.e. index `searchsorted(times, t − 3_600_000) − 1`. That index changes only when
  `t+lag` crosses an hour boundary that `t` had not. Probability ≈ `lag / 3_600_000`. For the
  deployed `lag=60s` that is **1.7%** of entry legs and 1.7% of exit legs; the other ~98% are
  priced at the **identical hourly close** whether `lag` is 0s, 30s, or 60s. Consequences:
  1. The edge_sweep showing the edge roughly flat across `lag = 0 → 900s` is **not** evidence of
     lag-robustness — for lags ≤15min, ≪ the 1h candle, the same candle is reused for the large
     majority of legs, so the sweep cannot *see* intra-lag decay. The convexity / right-skew
     concern (hypothesis 2) is invisible at this resolution by construction.
  2. The intra-lag adverse price drift a real follower actually eats over the 60s (the whole
     reason to model lag) is captured for ~1.7% of legs and dropped for the rest → the candle
     proxy **under-states** real follower lag cost in both the offline number and the live
     candle-selection ranking.
- **Why it's real (not theoretical):** the lag is added (`p.entry_t + lag_ms`) and then snapped to
  an hourly grid; arithmetic above is exact from `_CANDLE_MS` and `searchsorted`. The live paper
  executor is NOT affected (it fills at the real L2 book at the real time, `runner.py:211`), which
  is precisely why the gate stays honest while the offline/selection estimate does not.
- **Mitigant (keeps it HIGH not CRITICAL):** the doc's own defense — long-hold selection makes the
  intra-hour drift small vs the multi-hour move (`followable.py:7-9`) — bounds the *magnitude* for
  the target population. And the capture path (real book at `+lag`, `markout.py:121-123`) would
  fix it, but is shadow / unwired (`scorer.py` header).
- **Confidence:** high (arithmetic). What would raise it to a quantified bp impact: re-pricing one
  transition's selected RTs at lag 0 vs 60s vs the real-book markout — a bounded per-wallet probe.
- **Fix sketch:** state explicitly that 60s lag ≈ 0s lag at hourly resolution; do not cite the
  lag-sweep flatness as lag-robustness. For a real lag test, price the lag window off sub-hour
  data (or the capture real-book markout), not hourly candles.

### F2 — `lag` is a scalar, and the real live detect→enter latency is roster-size-dependent, not the 60s constant  [MED→HIGH]
- **Where:** scalar lag everywhere (`lag_bucket_ms`, `markout.py:80 self._lag`, `edge_sweep.py:136`
  point lags). Real latency path: `live.py:88` `poll_interval_s=2.0` → `watcher.py:45/49`
  `_Throttle(2.0)` → `wallet_fills.py:31-45` (a **global IP-wide** 1-call-per-2s limiter) →
  `runner.py:229-242` `poll()` sweeps the whole roster sequentially under that one throttle.
- **Blast radius:** selection-power (the gate sees the *real* latency in the realized paper fills).
- **Failure scenario:** with `max_roster=50` (`main.py:151`) and a global 2s throttle, one full
  poll sweep costs ≥50 REST calls ≥ **100s** (more with pagination `watcher.py:90-108` and the
  every-5-cycles truth-up chunk `runner.py:310`). A given wallet is therefore re-polled only every
  ~100s, so a fill's detection latency is ~uniform on `[0, sweep]` → **median ≈50–60s, tail
  ≥100–120s**, then `+tick_s=2s` to act. The 60s scalar happens to ≈ the current median, but only
  by the coincidence `roster=50 × throttle=2s ≈ 100s sweep`. Raise the roster, slow the throttle on
  rate-limit, or hit the reconnect blind window (LIVE_CAPTURE.md:154) and the real latency blows
  past the 60s the edge was validated at → deployed edge < measured. A single scalar also cannot
  represent the **right-skewed** distribution the prior audit explicitly asked to pin to p50/p75
  (LIVE_CAPTURE.md:127); for a lag-convex-down edge the mean-over-distribution < edge-at-median.
- **Why it's real:** `_Throttle` docstring confirms it is one shared limiter
  (`wallet_fills.py:32-33`); `poll()` iterates wallets serially behind it. Nothing pins
  `lag_bucket_ms` to a *measured* latency — it is a hand-set constant in `locked_config`.
- **Confidence:** medium-high on the mechanism; low on the exact bp because F1's hourly
  quantization means even a 60s→120s latency change repaints <2% more legs offline. (The two
  findings interact: F1 says the offline model can barely register F2's latency variation.)
- **Fix sketch:** measure the live poll→fill→order latency distribution in the paper run and set
  `lag_bucket_ms` from its p50/p75; document that selection lag scales with roster size.

### F3 — "One config value, shared" lag invariant is documented but NOT enforced in code  [MED]
- **Where:** invariant at LIVE_CAPTURE.md:86; `markout.py:79` (`lag_ms` unbound to config);
  `scorer.py:24-31` (`CaptureScorer` takes no `ExperimentConfig`); `followable.py:131` /
  `oos.py:44` default `300_000` ≠ deployed `60_000`.
- **Blast radius:** selection-power / offline-estimate.
- **Failure scenario:** when the capture scorer is wired as the live `ReturnsFn`, whoever
  constructs `MarkoutScheduler(lag_ms=X)` chooses `X` freely — nothing asserts `X ==
  config.lag_bucket_ms`. A copy-paste of a test's `lag_ms=0`/`10`, or a hardcoded 30s/300s, would
  silently price the capture selection score at a different lag than the offline/gate config, with
  no validation tripwire (`config.validate()` only checks `lag_bucket_ms >= 0`, `experiment.py:73`).
  Separately, any analyst calling `rank_followable`/`oos` with defaults prices at 5-min lag while
  believing they used the 60s deployed config.
- **Why it's real:** `lag_bucket_ms` flows to exactly one site (`selection.py:62`); grep confirms
  no `src/` path passes it to `MarkoutScheduler` or to `CaptureScorer`.
- **Confidence:** high (structural — capture is unwired today, so this is a latent hole to close
  before the swap, not a live bug).
- **Fix sketch:** derive every lag from `ExperimentConfig.lag_bucket_ms`; have `CaptureScorer`
  take the config and assert `scheduler._lag == cfg.lag_bucket_ms`; align the `followable`/`oos`
  defaults to 60_000 or drop the defaults so the caller must pass it.

### F4 — `lag=0` sweep row is meaningless at hourly resolution and unguarded  [LOW/NIT]
- **Where:** `edge_sweep.py:102` (`--lags` includes `0`), printed at `:161-163`.
- **Blast radius:** reporting-only.
- **Failure scenario (hypothesis 5):** `lag=0` is an impossible instantaneous follower; worse, at
  hourly resolution (F1) `lag=0` prices at the last *fully-closed* hourly candle — up to ~1h
  *before* the fill — and is numerically ~identical to `lag=60s` for 98% of legs. No code prevents
  someone quoting the `lag=0` row as a headline. The README headline (~+15–20bp, line 19-22) and
  deployed config are at 60s, so it is not currently mis-quoted, but the guard is absent.
- **Confidence:** high. **Fix sketch:** drop `0` from the default sweep or label the row
  "diagnostic, non-deployable."

### F5 — Entry/exit modeled symmetric at `+lag`, but live book-staleness tolerance is asymmetric  [LOW]
- **Where:** model symmetric (`followable.py:74-75`, `markout.py:94/103`); live runner
  `staleness_ms=30_000` entry vs `exit_staleness_ms=300_000` exit (`runner.py:64-65`, used at
  `:179` and `:200`).
- **Blast radius:** selection-power / execution realism.
- **Failure scenario (hypothesis 4):** detection latency itself IS symmetric (entry and exit are
  both found by the same poll sweep), so the symmetric `+lag` assumption is broadly right. But live
  execution will act on an EXIT against a book up to 300s stale while gating ENTRY at 30s — so in
  stressed/stale conditions the realized exit price drifts further from the modeled `+60s` than the
  realized entry does. Sign of the bias is indeterminate (conservative for risk, ambiguous for
  edge). Minor.
- **Confidence:** medium. **Fix sketch:** note the asymmetry in the model's documented assumptions;
  no code change needed for correctness.

## What I checked and could not rule out
- Confirmed `lag_bucket_ms` does **not** reach `decide`/`Results` — the GO/NO-GO gate carries no
  candle-lag, so no lag mis-spec can fabricate a GO (consistent with the doc's blast-radius claim).
- I did **not** run any probe (STATIC task; resource rules). The unquantified items are: the exact
  bp gap between candle-lag pricing and real-book pricing over the lag window (F1), and the measured
  live latency distribution (F2). Both are settleable with a bounded per-wallet probe (≤20 wallet
  files, streaming) and would convert F1/F2 from "mechanism shown" to a number.
