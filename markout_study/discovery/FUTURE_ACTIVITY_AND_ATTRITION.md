# FUTURE_ACTIVITY_AND_ATTRITION — the liveness/basket-availability estimand

> **Gate A estimates entry quality conditional on a scored wallet producing a next-month qualifying signal with complete 1/2/4/8-hour outcomes.** It is **not** evidence that a fixed wallet list remains available or deployable — that belongs to Gate B.

Companion to `SCORE_AND_OUTCOME_SPEC.md` §10. A wallet scored at cutoff C may produce **no** qualifying episode (or an endpoint-incomplete one) in evaluation month m, leaving Yband(w,m) undefined. We pre-register **two separate objects** and never conflate them.

## Object 1 — Conditional entry-quality (PRIMARY Gate A)
Conditional on the wallet producing a **complete 4-of-4-horizon next-month outcome** (SPEC §9), does the prior score rank the quality of those episodes? Rank IC, decile outcomes, and selected-minus-field all run over the **scored cross-section only** (SPEC §11: eligible, scoreable, finite θ̂) and within it use **complete-outcome wallets**. This is the primary Gate-A markout-quality estimand — *a wallet with no signal has no entry markout.* Inactive or endpoint-incomplete wallets are **not** assigned zero markout and are **not** removed on the sign/magnitude of any return.

## Object 2 — Liveness / basket availability (reported alongside; not an entry-quality claim)
Reported every fold, descriptively, for both the selected basket and the field:
- **P(active)** = probability a scored wallet produces ≥1 qualifying episode next month, selected vs field;
- **selected-wallet next-month episode count** distribution;
- **fraction of the selected basket that remains active** in month m;
- **number of days** on which the selected basket emits **any** signal;
- attrition curve: active fraction of a cohort over subsequent months.

## Eligible-but-unscoreable accounting (frozen, every fold)
Report the count and reason for wallets that were **eligible but unscoreable** (so entered neither selected nor field): <6 active weeks, invalid bootstrap estimate, missing required training horizons, degenerate/other. These are the attrition between the eligible universe and the scored cross-section (SPEC §11).

## Mandatory selected-vs-field comparison (item 14 — frozen, every fold)
Report, selected basket vs **scored (SPEC §11) field**, per fold:
| Metric | Selected | Field |
|---|---|---|
| next-month activity rate (P ≥1 episode) | ⬜ | ⬜ |
| four-horizon completeness rate (4-of-4 Yband) | ⬜ | ⬜ |
| next-month episode count (distribution) | ⬜ | ⬜ |
| next-month active-day count (distribution) | ⬜ | ⬜ |
| complete-wallet count | ⬜ | ⬜ |

**Explicit limitation (frozen):** because Gate A conditions on next-month activity *and* 4-of-4 completeness, it does **not** establish that a frozen wallet list remains available or deployable. That economic issue — attrition, thin liveness, capacity — is deferred to Gate B.

## Interpretation contract (frozen)
- **Gate A is explicitly conditional on future signal production.** It answers "when they trade, are their entries better?"
- **Gate B captures the economic cost of inactivity** — the wallet-day bounded book naturally earns zero on no-signal days, and low liveness shows up as thin deployment, not as a zeroed entry markout.
- A wallet that scores well but goes dark is a *liveness* failure (Object 2), **not** an entry-quality failure (Object 1). Both are reported so the two failure modes are never confused.
- No wallet is removed, up- or down-weighted in Gate A on the basis of its realized return. Selection and eligibility remain return-independent (PREREG A.1/A.8).
