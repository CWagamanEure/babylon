# Audit 16 — Capture scorer & re-derivability  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/16_scorer.md`.

## Scope
The Scorer turns stored round-trips into a rolling Sortino that feeds RollScheduler via
ReturnsFn/CutoffFn. The prior audit's #1 CRITICAL is re-derivability: a mutable, non-deterministic
scoring DB means the roster can't be proven to be the honest output of the rule.

## Read
- `src/babylon/follow/capture/scorer.py`, `tests/test_capture_scorer.py`.
- `docs/LIVE_CAPTURE.md` must-fix #1 (pre-registration / re-derivability), the ReturnsFn/CutoffFn interface.
- Cross-ref audit 18 (gate/pre-registration) — coordinate, don't duplicate.

## Adversarial hypotheses to test
1. **Determinism of the score.** Given the same committed inputs, does the Scorer produce the same
   ranking every time? Sources of non-determinism: ephemeral book snapshots, `late_markout` timing,
   dict/set iteration order, float accumulation order. Any one breaks re-derivability. Enumerate them.
2. **run_id DB-hash.** Prior audit fix: "snapshot the per-T0 `{roundtrip_id→ret_bps}` used, fold its
   content-hash into run_id." Is this implemented? If not, the manifest proves the *outcome* but not
   that it's the honest *output of the rule* — a tampered/buggy DB silently changes the roster with
   no audit trail. **Check whether this fix landed.**
3. **Cutoff semantics.** `SELECT ret_bps WHERE wallet=? AND exit_t >= cutoff`. Is `cutoff` the same
   value used by the gate's pre-registration? An off-by-one or a mutable cutoff lets the score drift.
4. **Bootstrap blend (must-fix #4).** Fresh live wallets enter at the noisy floor co-ranked with
   coarse candle scores — two differently-biased estimators on one scale + winner's-curse. Is there
   stratification/quota-per-source or calibration onto one scale? Or do candle-scored and
   live-scored wallets still compete directly?
5. **Source tagging.** Each RT is `source=live` or `source=candle`. Does the Scorer mix sources in a
   single Sortino without accounting for their different bias/variance? Confirm the live-eligibility
   floor is well above 6 (prior audit said "raise ≫6").

## RAM
STATIC.
