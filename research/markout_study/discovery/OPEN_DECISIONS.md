# OPEN_DECISIONS — unresolved choices requiring approval before freeze

These cannot be frozen from data alone; they need your call (business input) or a data check. Ordered by how much they affect the design.

1. **Data ceiling / feasibility (blocking).** The tape is ~11 months and cannot be backfilled via the info API (older fills aged out); the unbuilt S3 `node_fills_by_block` is the only deeper source. A monthly walk-forward yields ~6–9 evaluation folds, and the 48 h low band is the thinnest. **Decide:** proceed on 11 months accepting the low fold count (and the real chance of an inconclusive/underpowered verdict for the low band), or invest first in building the S3 history to power the low-frequency question properly? This gates whether the low band is worth its complexity now.

2. **Coin set (needs data check).** Primary is BTC/ETH/SOL/HYPE (validated bars). You emphasized "liquid coins where copying is plausible." **Decide:** keep majors-only primary, or expand to top-N liquid perps as the primary (requires we have clean bars + tape for them)? Expansion changes the universe materially.

3. **Dropping the taker-share filter interacts with a known ledger risk.** Removing the 0.70 taker cut surfaces maker-heavy wallets. Prior work flagged a phantom-round-trip bug in taker-close accounting for maker-heavy wallets. **Decide/confirm:** the episode ledger must be re-validated on maker-heavy wallets before trusting their episodes; do we gate maker-heavy wallets behind a ledger-correctness check, or accept them only if the check passes?

4. **Long-hold wallets vs fixed horizons.** With no hold cap, some wallets hold for days; our markout ends at 48 h. **Confirm intent:** we are measuring *entry quality on fixed horizons* (copyable regardless of the wallet's own hold), not trying to replicate their exit. I believe this is right, but it means a genuinely slow wallet's full edge may sit beyond 48 h and be undercounted.

5. **Latency assumption.** Primary 60 s detection→entry (sensitivities 5 s / 300 s). **Decide:** is 60 s realistic for our copy pipeline, or do you have a measured detection delay?

6. **Cost schedule.** Reusing {8,8,10,14} bp round-trip per episode as the assumption. **Decide:** confirm, or supply real per-coin taker fee + expected spread numbers (and whether to charge per side vs per round trip).

7. **Primary make-or-buy comparator.** Threshold reversal (frozen τ\*) is primary; market-state regression is the sensitivity. **Confirm** the threshold-reversal comparator is the fair "cheap public alternative," since the population is reversal-dominated.

8. **`[PENDING AUDIT]` targets to ratify** (finalized from the training-only power audit, but the targets need sign-off): min effective-N for reliability; 48 h retention thresholds (≥8 non-overlapping episodes, ≥20 wallets); per-wallet concurrent cap (≤4); coin cap (40%); exclusion-flag thresholds.

9. **Basket size / selection rule.** Primary top-40 by copyability; rank-weighted top-10–20% is the sensitivity. **Confirm** top-40 as primary.

10. **Embargo.** Primary 0 months (short episodes, entry uses no future data); 1-month embargo is a sensitivity. **Confirm** acceptable.

---

## Audit-elevated decisions (from DESIGN_AUDIT_v1.md — these now gate the freeze)

**A. Two-track restructure (load-bearing).** Two independent auditors converge that the deployment gate (directional post-cost copy book) is blind on 11 months of 5-min-bar data. Recommendation: **Track 1 — signal existence** (does the score rank wallets by *market-residual* next-period return; powered now via neutralization + cross-unit sign test) run immediately; **Track 2 — deployment / make-or-buy** (directional book that monetizes beta timing) kept but gated behind more data. **Decide:** accept the two-track split, or insist on a single combined deployment verdict now (which the audit says will return inconclusive-underpowered)?

**B. One primary horizon band.** Running both bands is two shots at the headline (no multiplicity control), and the 48 h band is structurally blind (right-censored, ≤15 slots/month). Recommendation: **one primary band; 48 h → descriptive-only.** **Decide which is primary:** mid {1,2,4,8} h (better-powered, closer to copy timescale) or a 24 h-capped low band {8,16,24} h (your new low-frequency territory, thinner). The non-primary band is reported at α/2, non-headline.

**C. Neutralization for measurement ≠ subtracting the fade from the score.** To make Track 1 powered, each wallet-day score is residualized against the contemporaneous market/beta move *before* shrinkage (variance reduction). This is a measurement tool; it does **not** subtract the reversal/fade signal you want to monetize (that stays in the Track-2 directional book). **Confirm** this distinction is acceptable.

**D. Deployment-gate data prerequisite.** If the training-only positive control (a few-bp cross-sectional spread) cannot clear Gate B's month-block interval on ~4–6 folds — the likely outcome — Track 2 needs the S3 `node_fills_by_block` backfill (more folds) and finer execution data before it can carry a headline. **Decide:** commission the S3 backfill for Track 2, defer Track 2 to forward paper-accrual, or accept a wide-CI/inconclusive deployment number for now?

**E. Copyability realism at 5-min granularity.** 5-min bars quantize the 60 s latency to a near-no-op, so copyability is optimistically biased and the latency sensitivities are unresolvable. **Decide:** accept a fixed within-bar adverse-fill haircut as the interim copyability model, or require finer bars / BBO before any copyability/deployment claim?

**F. Hard ledger-quarantine gate.** Accept the pre-window-position reconstruction + quarantine of any wallet whose reconstructed position is left-censored (fixes the phantom-short bug that dropping the taker filter would otherwise resurrect). Recommended: yes, as a hard gate.

Nothing is frozen until A–F and 1–10 are resolved and the mechanical spec fixes (Themes B–E of `DESIGN_AUDIT_v1.md`) are applied.
