# AUDIT_CHANGE_CONTROL — classification of the 5-agent findings (ruling #13)

Each finding is classified: **CF** correctness fix · **LP** leakage prevention · **EC** estimand clarification · **FC** feasibility constraint · **NF** new degree-of-freedom (may NOT silently modify the primary config). Only CF/LP/EC/FC may change the primary configuration before freeze.

| # | Finding (source) | Class | Applied to primary? |
|---|---|---|---|
| A1 | Directional book variance-blind → variance-reduce the *measurement* estimand | EC + FC | Yes, but via the **basket-minus-field contrast** (market-common component cancels), **not** by residualizing the score — the Gate-A score is **gross** signed markout (business monetizes beta timing). Residual return is a secondary diagnostic only. Directional book is the sealed deployment number. |
| A2 | Standardized score ≠ bp return; exit horizon undefined | CF/EC | Yes — one representative exit horizon (band median = 4 h) in bp for the deployable book & Gates B/C; standardized aggregate is the Gate-A ranking score only |
| A3 | 5-min bars quantize 60 s latency to a no-op | FC | Yes — latency instrumented (ruling #5); within-bar adverse-fill haircut folded into decomposed cost (ruling #6); copyability labelled not-deployment-grade until measured |
| A4 | ≥4 active months burns fold front → ~4–6 folds | FC | Yes — stated honestly; ≥3 months is a sensitivity; min-months is a `[PENDING AUDIT]` justified by power, not returns |
| A5 | Shrinkage collapses to mean under beta-dominated day scores | EC | Partly — score stays gross (per business objective); the audit must report τ vs mean posterior-SD so identifiability is demonstrated, and inference uses the basket-minus-field contrast. If τ² is not identifiable at the ≥30-day floor, that is a reported feasibility limit, not a reason to residualize. |
| A6 | Positive control under-specified | CF | Yes — ruling #12 governs (few-bp cross-sectional spread; must clear real CIs) |
| B1 | Forward window crosses cutoff → contaminates score/SD/shrinkage | LP | Yes — horizon-matched purge (ruling #10); exclude episodes whose markout window crosses cutoff (8 h purge, mid band) |
| B2 | Hold / active-days for still-open positions read post-C data | LP | Yes — hold on position lifetime, censored at C; no eligibility value consumes ts ≥ C |
| B3 | Automated checks blind to bar-ts leak; identity shuffle only | LP | Yes — add forward-endpoint bar-ts assertion + temporal placebo |
| B4 | τ\* leaks basket frequency into "public" benchmark | LP | Yes — benchmark fitted prior-data-only inside each fold, wallet-independent target (ruling #7) |
| C1 | Two bands = two headline shots | FC | Yes — Phase A = mid band only (confirmatory); low band = Phase B feasibility; not pooled (ruling #1) |
| C2 | Eyeballed `[PENDING AUDIT]` thresholds | CF/LP | Yes — each justified by accounting/reliability/capacity/ops, not returns (ruling #8) |
| C3 | Gate-A "beyond noise" not falsifiable | CF | Yes — frozen Spearman(decile, return) + month-block sign test |
| C4 | Start-month / fold-count lever | CF/LP | Yes — start month & fold count frozen mechanically; ±1 start-month robustness reported |
| C5 | Equal-wallet smuggling as headline | EC | Yes — only wallet-day deployable sizing can set the deployment number; equal-wallet descriptive |
| C6 | Sensitivities compounding (3²³) | CF | Yes — strictly one-fork-off-primary, non-compounding; grid descriptive-only |
| C7 | Sign test miscalibrated (5/7, p≈0.23) | CF | Yes — ≥6/7 or cross-unit sign test pooling coins × folds (ruling #11) |
| D1 | Left-censored ledger → phantom shorts | CF (critical) | Yes — startpos reconstruction + hard quarantine gate (ruling #3) |
| D2 | `hold_est_h` undefined; termination truncates it | CF/EC | Yes — hold on flat→flat lifetime, decoupled from episode termination |
| D3 | Fragmentation inflates episode counts / correlates markouts | CF | Yes — dedupe to non-overlapping forward windows for the eligibility count and every per-episode statistic |
| D4 | Dust on opens only; `q≠0` no-open-episode state | CF | Yes — min-reduction dust floor; resolve the `q≠0` state explicitly |
| D5 | Exclusion flags circular, no positive control | CF/FC | Yes — hand-labelled control set, precision/recall + 4-way confusion, wash gets own detector, flags checked vs markout |
| E1 | Comparator is a strawman → promote regression to co-primary | **NF** | **No** — ruling #7 keeps threshold-reversal primary and the market-state regression a serious *secondary*; not silently promoted |
| E2 | Gate B/C not independent; C-pass+B-fail | EC | Yes — report benchmark's own return; C interpretable only if ≥1 of {basket, benchmark} profitable; C-pass+B-fail ≠ evidence for wallet layer |
| E3 | Orthogonal-component OLS intercept unidentifiable at n≈7 | CF | Yes — shared-vs-orthogonal split at the episode level, within-fold |
| E4 | Gate-C null can't earn "unnecessary" at n≈7 | EC | Yes — Gate-C null is inconclusive unless its own MDE (in T2) is small |

Confirmed sound (no change): first-entry markout + round-trip cost once per episode is the correct copy model; the wallet's size/conviction (`peak_notl`) dropped by equal-notional sizing is labelled a design assumption; Gate A and Gate B are near-mechanically linked — reported as one finding, two facets.
