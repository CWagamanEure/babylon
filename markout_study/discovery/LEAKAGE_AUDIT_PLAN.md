# LEAKAGE_AUDIT_PLAN (revised to match PREREGISTRATION_v2 / SPEC)

The prior study's headline leak was whole-window eligibility. This experiment fixes it structurally; this checklist must pass before any result is reported. The invariant list below matches the primary specification exactly (item 12).

## Invariant: everything used at cutoff C uses only `ts < C`
1. **Eligibility** — episode count, active days, active months, per-horizon wallet-day coverage (J), episode-count concentration, exclusion flags, liveness. **Median hold is NOT an eligibility variable** (removed from primary; a completed-episodes-only sensitivity per PREREG A.1). A wallet's eligibility at C must not depend on any future activity, future holding behavior, or any next-month return.
2. **Shrinkage fit** — universe mean μ̂_C, τ̂²_C, per-wallet V(w,C), posterior θ̂ — all on `ts < C`.
3. **Horizon standardization** — μ(C,h), σ̂(C,h), winsor quantiles — training-only, frozen per fold.
4. **Selection** — ranking and gates use only as-of-C θ̂. No return-based gate exists.
5. **Public benchmark** — Gate-C standalone strategy's rules fit on prior data inside each fold, wallet-independent (SPEC §12-ii); never on evaluation data.
6. **Cost/latency** — Gate-B/C only; fixed once `DEPLOYMENT_INPUT_FREEZE.md` is signed; never consulted during Gate A.

## Two boundary rules (frozen)
- **Training score:** every outcome **endpoint** feeding a score must lie **strictly before C** — exactly `endpoint_price_ts(e,h) < C` where `endpoint_price_ts` is the lattice endpoint **close** timestamp (NOT `entry+h` raw, NO +5 min), i.e. an 8 h purge at the mid band. (F2, matches SPEC §1 / CHANGELOG §8.)
- **Evaluation month:** an episode is assigned to month `m` by its **signal timestamp**; its 1–8 h endpoint **may extend past month-end** provided the endpoint exists on the tape and is **never used for any as-of-C selection**. This is the return being measured, not a leak.
- **Final-month right-censoring:** episodes whose endpoint bar does not exist on the tape (last ~8 h) are **omitted** from the outcome — **never zero-filled** and never assigned an artificial value.

## Automated checks (coded into the pipeline) — item 6
Two **hard leakage tests** (a difference is a hard failure), replacing the old "move-the-cutoff-and-see-the-score-change" placebo (which does not diagnose leakage):

1. **Post-cutoff perturbation invariance.** Build eligibility, scores, and selection at C. Then **arbitrarily corrupt / shuffle / replace every fill and price observation strictly after C** and rebuild all as-of-C outputs. Require **exact equality** of: eligible wallets, training episode records, standardization parameters, shrinkage parameters, wallet scores, and selected identities. Any difference = hard leakage failure.
2. **Physical-access test.** Run the as-of-C pipeline against a data view in which **every row at or after C is physically unavailable**. It must produce **the same result** as the full-data run.

Supporting (diagnostic, not proof):
- Per-fold assertion: every field feeding selection has max source **fill-ts < C** AND every scoring episode's **endpoint_price_ts < C**.
- **Cutoff-shift recomputation** — general diagnostic only; not evidence of leakage absence.
- **Identity shuffle** — permute wallet identities within a cutoff; ranking signal must collapse (guards identity leak; blind to temporal leaks, which tests 1–2 cover).

## Reporting
Pass/fail per check per fold is a required output table (T3). No headline number is reported until all checks pass on all folds. Audited by the design swarm.
