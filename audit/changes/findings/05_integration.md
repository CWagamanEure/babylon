# A5 — Integration readiness + investigation fidelity

Scope: will `markout_returns` wire cleanly into the live selection path (SelectionAdapter /
select_roster), and does it implement the EXACT operating point validated in
`audit/EDGE_INVESTIGATION.md`? Static review only (no execution).

Bottom line: the new `markout_returns` function is internally faithful to the validated study on
the parts it controls (seam boundary, taker/conviction filters, candle-close pricing, neutralization
math), BUT it is NOT a drop-in for the current `returns_fn`, and the *surrounding wiring* — the
frozen `locked_config` numbers and the hard-coded `_sortino` ranking — currently encodes a DIFFERENT
operating point than the one that was validated. Several values must change before "live ≡ validated"
holds. None of these are bugs in `markout_returns` itself; they are integration/config gaps.

---

## HIGH — `markout_returns` is not signature-compatible with `returns_fn`; a naive swap raises
- where: `selection.py:56-63` (`returns_fn` calls `followable_returns(..., min_hold_ms=..., before_ms=...)`)
  vs `followable.py:128-134` (`markout_returns(..., horizon_ms=..., before_ms=...)`, **no** `min_hold_ms`).
- scenario: replacing `followable_returns` with `markout_returns` keeping the same kwargs →
  `TypeError` (`min_hold_ms` unexpected; required `horizon_ms` missing). So `returns_fn`'s body MUST
  be rewritten, not just have the callee name swapped.
- why real: signatures differ exactly here — `followable_returns` filters round-trips by
  `min_hold_ms`; `markout_returns` scores every opening over `horizon_ms` and has no hold filter
  (correct — the study scores every OPEN regardless of close; min_hold is a round-trip concept).
- confidence: high. fix: rewrite `returns_fn` to call `markout_returns(..., horizon_ms=H, lag_ms=L,
  before_ms=t0_ms, basket=self._basket, beta=cfg.beta)`; drop `min_hold_ms` from the selection path.

## HIGH — there is NO `horizon_ms` to source the validated 6h from; `ExperimentConfig` has no field
- where: `experiment.py:34-65` (`ExperimentConfig` has `lag_bucket_ms`, `min_hold_ms`, `beta`, but
  **no horizon field**). `horizon_cap_days` (line 61) is the decision-window cap, unrelated.
- scenario: to call `markout_returns` you must supply `horizon_ms=21_600_000`. Nothing in the config
  carries it, so it gets hard-coded at the call site or a new config field is added. A hard-coded
  literal is a frozen-config leak (the experiment's whole premise is every knob is in the immutable,
  hashed `ExperimentConfig`); an unhashed horizon means two runs with different horizons share a
  run_id.
- why real: `markout_returns` makes `horizon_ms` a REQUIRED kwarg (good — can't be silently wrong),
  but the live harness has nowhere to put the validated value.
- confidence: high. fix: add `markout_horizon_ms: int` (and probably a dedicated selection-lag field;
  see next finding) to `ExperimentConfig` + `validate()` + `locked_config`, so it's hashed into the run_id.

## HIGH — `locked_config.lag_bucket_ms = 60_000` (60s) contradicts the validated ~15-min lag
- where: `main.py:61` (`lag_bucket_ms=60_000`) vs `EDGE_INVESTIGATION.md:44,107` (operating point is
  ~15-min lag = 900_000 ms; 60s is the microstructure-inflated corner the study explicitly discounts,
  lines 33-34).
- scenario: current `returns_fn` sources the lag from `self._cfg.lag_bucket_ms`. If the markout
  rewrite keeps that pattern, live selection runs at **60s lag**, not 900s → it selects on an
  own-flow-inflated signal the investigation flagged as partly un-capturable. Live ≠ validated.
- why real: the frozen config literally holds 60_000; the plan's "lag=900000ms" is not what the
  committed config encodes today.
- confidence: high. fix: either set the selection lag to 900_000 in `locked_config`, or give markout
  its own `selection_lag_ms` field set to 900_000 (note `lag_bucket_ms` is described as "the SINGLE
  headline lag" used elsewhere for the live copy execution — overloading it for selection may be
  wrong; a separate field is cleaner). Whatever the choice, the selection lag passed to
  `markout_returns` must be 900_000, not 60_000.

## HIGH — `select_roster` hard-codes `_sortino`; ranking by trimmed-mean is a code change, and the
   trimmed-mean must match the study's exact percentile-based definition
- where: `scheduler.py:78` (`ranked = sorted(eligible, key=lambda w: -_sortino(eligible[w]))`).
- scenario: the validated metric is **trimmed-mean(10%)** (EDGE_INVESTIGATION result 5/7); Sortino was
  the WORST central metric (+15.7 vs +32.8 log-growth). select_roster has no metric-injection seam, so
  switching requires editing the function. Worse: the study's `trimmed10`
  (`selci_fh.py:187-191`) keeps points whose VALUE lies within the [10,90] PERCENTILE band
  (`a[(a>=lo)&(a<=hi)].mean()`, `-1e18` if `size<5`). A hand-rolled "trim 10% of the COUNT off each
  tail" (e.g. scipy `trim_mean`) is a DIFFERENT statistic and would diverge from the validated ranking.
- why real: ranking key is the thing the whole edge study optimized; getting the definition subtly
  wrong silently trades an unvalidated selection rule.
- confidence: high. fix: add a `metric_fn` param to `select_roster` (or replace `_sortino`), and reuse
  the EXACT percentile-band trimmed-mean from the study (ideally import one shared impl so live ≡ study
  by construction, mirroring how `open_events` is shared).

## MED — `basket=None` default makes `markout_returns` DIRECTIONAL; the validated signal is NEUTRALIZED
- where: `followable.py:131` (`basket=...=None`), `selection.py:35` (`self._basket = basket  # None ⇒
  directional`). EDGE_INVESTIGATION validated the **neutralized** series (beta 1.245).
- scenario: SelectionAdapter is documented as defaulting to the directional ("gated") measure. If the
  adapter is constructed with `basket=None` (the deployed-gate convention), `markout_returns` computes
  the DIRECTIONAL markout, not the neutralized one the edge study validated → different ranking.
- nuance: experiment.py's *decision gate* is intentionally directional (the "fragile neutralized"
  warning is about the GATE, not selection). But SELECTION was validated neutralized. So the adapter
  used for the markout selection path MUST be constructed WITH the real basket; reusing a
  `basket=None` directional adapter for selection is a fidelity break.
- confidence: high that the validated signal is neutralized; medium on how the adapter will be wired.
  fix: ensure the selection adapter passes the alt basket (and beta 1.245) into `markout_returns`.

## MED — `markout_returns` default `beta=1.0` ≠ validated `beta=1.245` (footgun if not passed)
- where: `followable.py:132` (`beta: float = 1.0`) vs `selci_fh.py:575`/`main.py:60` (1.245).
- scenario: any caller that neutralizes (`basket` set) but forgets `beta=` gets 1.0 neutralization,
  not 1.245 → wrong residual. Current `returns_fn` does pass `beta=self._cfg.beta`, and
  `locked_config.beta=1.245`, so the wired path is OK — but the DEFAULT silently contradicts the
  validated value. confidence: high. fix: no behavior change needed if the adapter keeps passing
  cfg.beta; consider dropping the default to force an explicit beta.

## MED — eligibility gate differs from the validated pool (raw-fill ≥20 vs min_train=5 markout entries)
- where: `scheduler.py:70-75` (activity gate: raw fill count ≥ `min_positions` AND `len(r) ≥ 2`),
  `main.py:60` (`min_positions=20`), vs the study's `min_train=5` (markout-ENTRY count;
  `selci_fh.py:359,564`).
- scenario: the validated panel gated on ≥5 markout ENTRIES; live gates on ≥20 RAW FILLS plus ≥2
  returns. These define different eligible pools, and the selection-aware result depends on pool
  composition. Note the raw-activity gate (commit fe44463) was introduced to fix ROUND-TRIP
  closed-count disposition bias — but markout entries carry NO open/closed asymmetry, so entry-count
  gating is already disposition-free for this signal; the raw-fill gate is a different (stricter,
  20-fill) pool than the one the edge was measured on.
- why real: a wallet with 6 markout entries but <20 raw fills is eligible in the study, ineligible
  live (and vice-versa). Plus trimmed-mean returns -1e18 for <5 entries, so the live ≥2 floor is
  partly moot for ranking but still changes who is "eligible."
- confidence: medium. fix: decide the gate explicitly against the validated `min_train=5` on markout
  entries; if keeping raw-activity gating, document that it widens/shifts the pool vs the validated run.

## LOW — `locked_config.train_days = 30` vs study default `train_days = 31`
- where: `main.py:59` (`train_days=30`) vs `selci_fh.py:573` (default 31). One-day-shorter train
  window than the validated extract default → marginally different per-wallet samples. May be
  intentional/overridden in `run_selci_fh.sh` (not readable here), so flagged low. fix: confirm the
  train window used in the validated run and match it.

---

## Things I checked that are FAITHFUL (no action)
- **Seam boundary matches.** `markout_returns` includes an entry iff `entry+lag+horizon < before_ms`
  (`followable.py:161-163`, strict via `>=` continue). The validated extract's TRAIN bucket is
  `end < t0` (`selci_fh.py:107-109`), same strict boundary with `before_ms=t0_ms`. Entries whose
  window straddles T0 are excluded identically → no look-ahead leak, train set matches.
- **cutoff_fn is orthogonal and needs no change.** `cutoff_fn` (`selection.py:74-82`) records the max
  train-window fill `tid` (`time < t0`) for the live CAPTURE seam; markout's `before_ms` guards the
  SELECTION returns. Different axes (tid boundary vs window-end boundary), both correct; markout
  excluding the last ~6.25h of straddler entries while their fills are ≤ cutoff_tid is expected, not a
  conflict. cutoff_fn stays as-is.
- **Filters match.** markout default `taker_only=True, conviction_only=True, drop_leading=False`
  (`followable.py:132-133,157-159`) == the study's `if topen and conv` with no leading-drop in the
  train/test arrays (`selci_fh.py:91`; leading only dropped in `cmd_ci --drop-leading`). Defaults are
  the validated point; setting `drop_leading=True` live would diverge, but the default is correct.
- **Pricing/neutralization math matches.** `_close_at` (last fully-closed candle, no look-ahead) and
  `_basket_ret_bps` are the SAME functions the study calls (`selci_fh.py:29,31,102-106`); the bps
  formula `dir*(eout/ein-1)*1e4 - dir*beta*basket` is identical.
- **Return contract fits select_roster.** Both `followable_returns` and `markout_returns` return a
  1-D `float64` `np.ndarray`; `select_roster`/`kelly_weights` only need an array per wallet — the
  per-ENTRY (vs per-round-trip) change doesn't break the type contract.
- **Single-wallet cache still works.** `markout_returns` reads the same df (and same columns:
  time/px/sz/side/crossed/startPosition/hash) the cached `_df` provides; returns_fn + cutoff_fn still
  share one read per wallet. No memory regression.

## Could not rule out (no execution / files not readable)
- Whether `run_selci_fh.sh` overrode `train_days`/lag defaults in the actual validated run (train_days
  30 vs 31; which lag column is the deploy point).
- The Kelly-weighting interpretation on per-ENTRY markout returns vs per-round-trip (weights.py
  docstring says "per-ROUND-TRIP"); marking on never-closed fixed-horizon returns changes the
  realized-PnL interpretation of the Kelly fraction. Not a wiring blocker, but worth a sizing review.
