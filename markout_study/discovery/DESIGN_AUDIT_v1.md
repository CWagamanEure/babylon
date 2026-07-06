# DESIGN_AUDIT_v1 — consolidated findings from the 5-agent design swarm

Read-only adversarial audit of the pre-registration (lenses: leakage, degrees-of-freedom, power/feasibility, estimand/benchmark, episode/data-quality). All twelve docs reviewed. Findings below are the ones the design did **not** already close; each is actionable. Nothing is frozen; this is the input to the freeze decision.

## Headline conclusion (two auditors converge)

The design is **fixable** on leakage, degrees-of-freedom, episode-construction, and benchmark fairness (Themes B–E). But the **deployment question as written is blind by construction on this data** (Theme A): the primary Gate-B object is a *directional* copy book whose monthly σ (order 1,000–3,000 bp) dwarfs any plausible few-bp edge, evaluated on ~4–6 usable folds, priced on 5-minute bars that quantize the 60 s copy latency to a near-no-op. Two independent lenses (power, estimand) reach this separately.

**Recommendation: split into two tracks.**
- **Track 1 — signal existence (answerable now, 11 months).** Does the score rank wallets by *market-residual* next-period return? Measured on beta/market-neutralized residuals (variance-reduced), inference by cross-unit sign test over coins × folds. This is a legitimate, powered discovery result.
- **Track 2 — deployment & make-or-buy (gated behind more data).** The directional book P&L that monetizes beta timing — kept, per the stated goal, but reported with honest wide intervals and **not** treated as resolvable on 11 months of candles. Track 2 is gated behind the S3 `node_fills_by_block` backfill (more folds) and finer execution data (BBO / sub-bar) before it can carry a headline.

This preserves "monetize beta timing" (Track 2 keeps the directional book) while refusing to claim a deployment verdict the data cannot support.

---

## Theme A — the deployment estimand is under-powered / incoherent as written

- **A1 (power). Directional book is variance-blind.** Net-directional crypto σ_month ≈ 1,000–3,000 bp ⇒ MDE 20×–500× a few-bp edge. → Make the *signal-existence* estimand market/beta-neutralized (residualize each wallet-day score against contemporaneous coin/BTC move) **before** shrinkage and aggregation; this is the CLAUDE.md variance-reduction obligation and also fixes A5 (shrinkage collapse). Keep the directional book only as the Track-2 deployment number with wide CIs.
- **A2 (estimand). Score is SD-standardized (unitless) but Gate B calls it a bp return, and "exit at the fixed band horizon" is undefined (a band = 4 horizons).** → Freeze **one representative exit horizon per band in raw bp** for the deployable book and Gates B/C; reserve the standardized multi-horizon aggregate strictly for the Gate-A ranking score. Selection score ≠ return metric.
- **A3 (episode). 5-min bars quantize 60 s latency to a no-op** (copy entry price == info entry price in the same bar) → copyability collapses toward the information score and is optimistically biased; the 5 s/60 s/300 s sensitivities often land in the same bar and are unresolvable. → Report the fraction where latencies resolve to the same bar; add an explicit within-bar adverse-fill haircut, or obtain finer bars/BBO before treating copyability as deployment-grade.
- **A4 (power). ≥4-active-months eligibility burns the tape front** → effective folds ~4–6, not 6–9. → State honestly; consider ≥3 months as primary; front-load the universe-size-per-cutoff table (T1) as a hard go/no-go (< 5 folds clearing ≥40 wallets ⇒ characterization study, not a gated test).
- **A5 (power). Shrinkage with reliability=active-days collapses to the mean** when day-scores are beta-dominated (σ² large, τ² small). → Fixed by A1 neutralization; require the coverage audit to report estimated τ vs mean posterior-SD so τ² identifiability is demonstrated, not assumed.
- **A6 (power). Positive control under-specified** (magnitude + which inference layer). → Pin injection to a plausible few-bp *cross-sectional spread* consistent with IC≈0.11 (not a uniform bump); it must clear Gate B's month-block CI *and* Gate A's IC-CI on training folds. If it cannot, the pre-registered honest verdict is *inconclusive before spending an evaluation fold* → Track 2 needs the backfill.

## Theme B — leakage moved from eligibility to scoring

- **B1. Forward windows crossing the cutoff contaminate the score, standardization SD, and shrinkage mean** (embargo=0 operationalizes exactly this). → **Primary rule: only episodes with `t0 + h_max < C` feed any as-of-C score/SD/shrinkage** (window-completion filter); primary embargo ≥ band max horizon. Demote embargo=0 out of primary.
- **B2. Median-hold / active-days for positions still open at C read post-C data.** → Censor at C or exclude still-open episodes when computing eligibility; assert no eligibility value consumes a fill/bar with ts ≥ C.
- **B3. Automated checks are blind to this** — the assertion checks *fill* ts, but the leak is in forward-endpoint *bar* ts; the identity-shuffle preserves temporal structure. → Add a forward-endpoint bar-ts assertion (`t0+h < C` for scoring) and a temporal placebo (shift cutoff by h_max; the score must move).
- **B4. τ\* leaks the selected-basket frequency into the "public-only" benchmark** (also Theme E). → Match on a wallet-independent target and refit τ\* as-of-C from public data each fold.

## Theme C — degrees-of-freedom / multiplicity

- **C1. Two horizon bands = two shots at the A+B headline, no multiplicity correction** (kill rule fires only if *neither* band passes). → **One primary band** (headline); the other is an α/2-corrected, explicitly-secondary report. Forces the mid-vs-low decision (see OPEN_DECISIONS).
- **C2. `[PENDING AUDIT]` thresholds are eyeballed on training data** (shapes which wallets/bands survive). → Pre-register each as a mechanical, outcome-blind formula (a committed percentile; "min-N = the N where positive-control MDE ≤ X bp").
- **C3. Gate-A decile gradient "beyond noise" is not falsifiable.** → Replace with a frozen statistic + threshold (Spearman rank corr of decile vs next-month return, month-block sign test).
- **C4. Start-month / fold-count is a hidden lever** on ~7 folds. → Freeze mechanically before any eval-period return; require ±1-start-month robustness in the headline.
- **C5. Equal-wallet can be smuggled in as a headline** if wallet-day fails Gate B. → Only wallet-day sizing can satisfy Gate B; equal-wallet is descriptive, never a pass.
- **C6. Sensitivities not pinned to one-at-a-time** (surface becomes 3²³, not 36) and the robustness grid can leak into framing. → State strictly one-fork-off-primary, non-compounding; robustness grid is descriptive-only and cannot upgrade a primary failure.
- **C7. Gate-A sign test miscalibrated:** ≥⌈2/3⌉ of 7 = 5/7, binomial p≈0.23 (chance). → Require ≥6/7 (p=0.06) or 7/7, or a cross-unit sign test pooling coins × bands × folds for N.

## Theme D — episode construction / data quality

- **D1 (critical). Left-censored ledger: `q` starts at 0 with no pre-window position reconstruction** → a pre-existing long trimmed in-window is booked as a phantom SHORT open with wrong dir/t0/price and wrong-sign markout — the exact prior phantom-round-trip failure, and dropping the taker filter surfaces the carry/maker-heavy wallets most likely to have pre-window inventory. (cand2 does contain maker fills, so startpos is reconstructable.) → Reconstruct `startpos` from full available history before each cutoff; **hard quarantine gate**: drop any wallet whose first observed action is a from-flat reduction/flip or whose reconstructed `q` implies pre-window position, until reconciled.
- **D2. `hold_est_h` has no formula yet the ≥1 h gate selects on it; "any reduction terminates" truncates hold** → the gate silently selects build-and-sit and excludes active trimmers regardless of skill. → Define hold on position lifetime (flat→flat), decoupled from the termination rule.
- **D3. Fragmentation** ("any reduction terminates" + ">30-min gap = new episode" + dust) shatters one bet into N correlated episodes → inflates the ≥50-episode gate, `p_pos`, `coin_conc`; near-duplicate overlapping markouts. → Collapse fragments / dedupe to non-overlapping forward windows for the eligibility count and every per-episode statistic, not just the coverage table.
- **D4. Dust specified only for opens; a dust trim terminates an episode; "dust open ignored but updates q" creates `q≠0` with no open episode** (next fill mis-classified "add"). → Apply a min-reduction dust floor (or promote fork #8 "reduction ≥50% of peak"); resolve the `q≠0`, no-open-episode state explicitly.
- **D5. Exclusion flags (TWAP/wash/bot/slicer) share primitives, are circular with the episode-timing rule, and have no positive control** → non-randomly deletes skill-correlated wallets. → Hand-labeled control set; report per-flag precision/recall + 4-way confusion; give wash its own net-exposure/self-cross detector; check flags don't correlate with markout among retained wallets.

## Theme E — benchmark fairness (make-or-buy)

- **E1. Comparator is a strawman** (one global τ\* on one trailing-8h return) vs a wallet basket that conditions on coin/time/vol. → Gate C = beat the **max over public comparators {threshold reversal, market-state regression}**; promote the regression to co-primary.
- **E2. Gate B and Gate C not independent; "C-pass with B-fail" can reward a money-loser** beating a more-negative strawman. → Report the benchmark's own signed return; Gate C interpretable only when ≥1 of {basket, benchmark} is profitable; C-pass+B-fail is explicitly *not* evidence for the wallet layer.
- **E3. "Orthogonal component" = intercept of a 6–9-point OLS is unidentifiable and mechanically confounded.** → Do the shared-vs-orthogonal split at the episode level (return on basket episodes not co-triggered by the benchmark within its window), within-fold and high-N.
- **E4. A Gate-C null cannot earn "wallet layer unnecessary" at n≈7** unless its own MDE is shown ≤ the difference we'd care about. → Pre-register that a Gate-C null is *inconclusive* unless its MDE clears; compute that MDE in T2.
- Confirmed sound: first-entry markout + round-trip cost once per episode is the correct copy model; the wallet's size/conviction (`peak_notl`) is dropped by equal-notional sizing — label as an explicit design assumption. Gate A and Gate B are near-mechanically linked — treat as one finding, two facets.

## Changelist status

Themes B, C, D, E are mechanical fixes to the specs (apply at freeze). Theme A is the structural decision (two-track split, one primary band, neutralized signal-existence estimand, representative-horizon bp return, deployment gated behind data) — it needs the user's ruling first. Updated decisions in `OPEN_DECISIONS.md`.
