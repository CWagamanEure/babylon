# Stage L — Trader typology of the frozen cohort_K (WHO are they, and does any archetype carry edge?)

**Status:** ARCHITECTURE (pre-build). Standard flow: design-audit swarm → build → code-audit → run →
steelman/prosecute → ledger. Decision rules (§6) frozen before any archetype's TEST markout is read.

## 0. Motivation & priors
Stage K: the frozen behavioral cohort (1,694 mid-freq copyable takers, `out/cohort_K.txt`) has a **powered
aggregate null** at 4h (equal-weight +0.3 [−1.0,+1.7], MDE ~2bp, +10bp injection recovers). A powered zero on a
MIXTURE is exactly what you'd see if the cohort is mostly trader types that were **never informed flow** —
hedgers, TWAP/execution algos, vaults, residual MMs — diluting any real directional signal. This stage
decomposes WHO they are and reads each archetype's markout separately.
**Honest prior (set by the Stage-K audits):** the swarm already searched for ANY outcome-independent sub-cohort
with persistent CI-excludes-0 edge; only a likely-GENERIC, net-negative mean-reversion-style residual turned up.
So the expected outcome is that typology **EXPLAINS the zero** (mixture of non-informed types) more than it
reveals hidden alpha. Both are report-valuable. If a clean directional sub-type does pop with a powered
CI-excludes-0 4h edge, it graduates to its own test — but that is not the base case.

## 1. Scope & discipline
Universe = the FROZEN `out/cohort_K.txt` (1,694 wallets). **Classification is OUTCOME-INDEPENDENT and TRAIN-only**
(ts<2026-02-01): every archetype feature is behavior/identity, NEVER markout/performance. Coins BTC/ETH/SOL/HYPE.
Outcome (per-archetype markout) REUSES the already-priced `out/cohort_K_entries.parquet` (4h/etc raw+neut+regime+
split) — no re-pricing. Splits identical to all stages (TRAIN<Feb / embargo Feb / TEST≥Mar).

## 2. Archetype features (per wallet, TRAIN-only, from the raw tape via the mkcommon avg-cost ledger)
One serial batched tape pass over the cohort only (small). Per wallet:
- **`funding_capture_bps`** — Σ(−dir·Δcumfunding over hold)/Σnotl·1e4 (join `funding.parquet`). Hedger/carry signature.
- **`time_in_pos_frac`** — Σ hold_ms / (active span). Delta-neutral/vault ≈ high; scalper low.
- **`cadence_cv`** — CV (or MAD/median) of inter-entry intervals. LOW = clockwork ⇒ TWAP/execution-algo signature.
- **`size_cv`** (`notl_cv`) — CV of per-entry notional. LOW+regular cadence ⇒ TWAP; HIGH ⇒ conviction sizing.
- **`net_long_frac`** and **`|net_long_frac−0.5|`** — two-sided/neutral vs directional.
- **`add_frac` / `avgdown_rate`** (reuse `cohort_forensics.wallet_descriptors`, `pos_after`/`avg_entry_px`) —
  conviction-adds vs martingale.
- **`coin_hhi`** — concentration (specialist vs spread).
- **`regime_tilt`** = P(long|BULL_train)−P(long|BEAR_train) (momentum vs mean-reversion STYLE; from Stage-K neut file).
- **`gross_turnover_usd`, `n_decisions`, `med_hold_h`** (already have hold from Stage-K/hold_size_dist).

## 3. Entity/vault tagging (HL API, best-effort, identity not behavior)
Query HL info API per cohort address for vault/entity role (`{"type":"userRole"|"vaultDetails",...}` best-effort;
throttled, ~1.7k calls). Flag `is_vault`. Also flag known protocol addresses (HLP etc.) if identifiable. This is a
NETWORK job (RAM-free, slow), NOT a blocker — if the endpoint doesn't cleanly return roles, fall back to a
behavioral vault-proxy (very-high-N + systematic + two-sided) and label it a proxy, not ground truth.

## 4. Archetype definitions (transparent priority rule tree; TRAIN-only quantile cutpoints frozen before outcomes)
Evaluate in order (first match wins) → each wallet in exactly one class:
1. **VAULT / protocol** — `is_vault` true (or the high-confidence proxy).
2. **TWAP / execution-algo** — `cadence_cv` ≤ Q1 (clockwork) AND `size_cv` ≤ Q1 (uniform) AND directional-persistence
   within sessions. (Executing a parent order → markout ≈ 0 by design.)
3. **HEDGER / delta-neutral-carry** — not above AND `|funding_capture_bps|` ≥ Q3 AND `time_in_pos_frac` ≥ Q3 AND
   `|net_long_frac−0.5|` ≤ small AND low conviction (`size_cv` ≤ median). (On-HL signature only; cross-venue hedges
   are UNPROVABLE — label "hedger-like", not "hedger".)
4. **DIRECTIONAL** — not above AND `|net_long_frac−0.5|` ≥ median (takes a side) AND (`coin_hhi` ≥ median OR
   `size_cv` ≥ median conviction). The hypothesized intended-informed group; sub-split by `regime_tilt` sign
   (momentum vs mean-reversion) since Stage K showed style predicts markout.
5. **MIXED / unclassified** — remainder.
Robustness: a 2-of-3 soft-membership variant + optional k-means (SEED=fixed) to confirm the priority order isn't
driving the verdict. Emit the axis cross-tab so overlaps are visible.

## 5. Per-archetype markout test (reuse cohort_K_entries.parquet; equal-weight = honest estimand)
For each archetype g: PRIMARY = pooled TEST 4h markout (raw AND coin-month-neut, separately), equal-weight across
wallets, wallet-clustered bootstrap 95% CI. Also: per-coin (cross-unit sign test), the 24h (post-exit-drift
context), and the direction/regime split. Report the archetype's share of the cohort and its TRAIN markout.

## 6. Power + PRE-REGISTERED verdict rubric (per archetype; both gates)
- **Per-archetype MDE** = 2.8·SE_cluster, and a **+10bp injection positive control INTO THAT ARCHETYPE's TEST
  entries** — if the archetype's CI can't exclude 0 after a +10bp inject, it is **INCONCLUSIVE-by-construction**
  (too few wallets), reported as such, NEVER "null." (Splitting 1,694 into ~5 classes → some classes <~80 wallets
  will be blind — say so.)
- **LIVE POSITIVE (graduates)** iff pooled TEST 4h CI excludes 0 AND MDE ≤ +10bp AND ≥3/4 coins same sign AND not
  the generic-reversion artifact (see below). → its own follow-up test.
- **EXPECTED-ZERO CONFIRMED** for an archetype whose markout SHOULD be ~0 by construction (TWAP, hedger) — a tight
  zero there is a *characterization* success (confirms the type), not an edge failure.
- **INCONCLUSIVE** iff positive point but CI includes 0 / MDE>care-about → surface point+direction, not null.
- **Generic-vs-cohort guard:** any positive archetype driven by `regime_tilt` (mean-reversion style) must be
  flagged as probably the generic short-horizon reversal (Stage K) unless it beats a random-contrarian placebo.

## 7. Execution plan — RAM-safe, strictly serial (ramguard, one heavy job at a time)
- **Job L1 (network, RAM-free):** HL API vault/role tagging of the 1,694 cohort addresses → `out/cohort_K_vault.parquet`.
- **Job L2 (serial tape pass, cohort-only, BATCH≤150 streaming):** archetype features → `out/cohort_K_archfeat.parquet`.
  Reuse `steelman_features.ledger` (hold/funding), `cohort_forensics.wallet_descriptors` (add/martingale/hhi).
- **Job L3 (in-memory):** join features+vault+regime_tilt → apply §4 rule tree → `out/cohort_K_arch.parquet` (+ the
  177-style cross-tab). Print archetype sizes.
- **Job L4 (in-memory):** join archetype labels ⋈ `cohort_K_entries.parquet` → §5 per-archetype markout + §6 power
  (injection control per archetype) + verdict rubric. → `out/cohort_K_arch_markout.parquet`.
- **Job L5:** steelman/prosecute swarm (read-only) → update `docs/FINDINGS_LEDGER.md` Stage L.
Never read the 3.3GB tape wholesale; L2 filters to cohort wallets per-coin. Peak ≤ ~1 GB.

## 8. Known failure modes for the design audit to pressure-test
- Rule-tree priority order driving the archetype verdicts (→ soft-membership robustness).
- Per-archetype N too small → blind cells mislabeled null (→ mandatory per-archetype injection control).
- Hedger detection is on-HL-only (cross-venue invisible) — over-claiming "hedger" from a delta-neutral HL pattern.
- Vault API unreliable → proxy mislabels; keep proxy-vs-confirmed distinct.
- Multiplicity across ~5 archetypes × raw/neut × per-coin (→ FDR family enumerated; one primary per archetype).
- A "directional archetype positive" that is just the Stage-K generic reversion residual re-found (→ §6 guard).
- Classification uses any TEST-window info (leak) — must be strictly TRAIN-only.

---

## REVISION (post 3-agent design audit, 2026-07-05) — supersedes conflicting parts above
**Consolidated verdict: GO-WITH-FIXES.** Methodology audit (measured): with a **k≥10 per-wallet TEST floor**,
cross-wallet sd ≈ 23 bp → MDE≤10bp needs ~40 wallets; DIRECTIONAL(356)/MIXED(585)/TWAP(103)/DIR-mom(163)/
DIR-mrev(161) all POWERED; only HEDGER/VAULT (restrictive ∩, <60) blind → legitimately INCONCLUSIVE. So real
per-archetype verdicts ARE possible (not blind-by-construction). The SOL/ETH residual is REAL under per-wallet
equal-weight (verified: ETH +4.2 [+1.0,+7.5], SOL +4.2 [+0.4,+8.3]) — but small, alt-only, net-negative after
alt cost, = the recurring generic/SOL-HYPE residual, NOT new alpha.

**FROZEN spec changes:**
- **Estimand:** per-wallet mean → equal-weight across wallets, **k≥10 TEST-entry floor** (and k≥10 TRAIN for
  train stats). **neut_4h is the PRIMARY** skill leg; raw_4h is a deployability annotation (they coincide at 4h,
  corr 0.997 — the skill/deployable split is vacuous here, matters only at 24h context).
- **Care-about:** honest live effect ≈ +3 bp gross (net-negative vs ~5–14 bp alt cost). Report MDE vs +3 bp too.
- **Verdict rubric (frozen):** per archetype g, PRIMARY = pooled TEST neut_4h equal-wt (k≥10), wallet-clustered CI.
  - LIVE POSITIVE iff CI-excl-0 AND MDE≤care AND ≥3/4 coins same sign AND (if regime_tilt-driven) BEATS the
    placebo AND exceeds its magnitude. A regime_tilt-partitioned cell's ceiling WITHOUT beating placebo =
    "reproduces generic reversal (not new)".
  - EXPECTED-ZERO CONFIRMED (vault/TWAP/hedger) iff +10bp injection RECOVERS (CI-excl-0) AND observed CI within
    ±care-about. Else INCONCLUSIVE.
  - METHOD-SCOPED NEGATIVE (directional) iff tight zero with MDE≤care — an earned "no edge from this archetype".
  - INCONCLUSIVE otherwise (MDE≫care or CI admits care) — surface point+CI+direction, never "null".
- **Multiplicity:** PRIMARY family = 6 cells (neut_4h × {VAULT,TWAP,HEDGER,DIR-mom,DIR-mrev,MIXED}) → BH-FDR.
  Per-coin/regime = descriptive, NO CI-excl-0 claims. Cutpoints (Q1/median) + peel order FROZEN before outcomes.
  soft-membership + k-means = confirmatory-MUST-AGREE, not extra discovery.
- **LEAK FIX (mandatory):** ALL classification features computed strictly on ts<2026-02-01 (train). Do NOT reuse
  whole-window hold_size_dist.med_hold_h or markout_stats-volume coin_hhi; recompute train-only. regime_tilt from
  cohort_K_entries where split=='train'. is_vault = HL userRole (present-day identity, acceptable; log role dist).
- **NEW Job L-placebo (mandatory, pre-registered):** mechanical "fade the trailing-4h move, hold 4h" contrarian
  rule priced on bars (BTC/ETH/SOL/HYPE) over TEST → its neut_4h. The DIR-mean-rev cell is capped at "generic
  reversal" unless it beats this. (Random-cohort placebo = follow-up only if the cell trips positive.)
- **Structural limit (state in verdict):** equal-weight over a heterogeneous archetype cannot resolve a
  within-archetype skilled minority (within-archetype outcome-ranking = registered-dead winner's curse). A flat
  directional cell = "cannot resolve a skilled minority", not "no skilled directional traders exist".

**Intermediate schemas (for the build):**
- `out/cohort_K_vault.parquet`: wallet, role(str), is_vault(bool).
- `out/cohort_K_archfeat.parquet`: wallet + TRAIN-only features {funding_capture_bps, time_in_pos_frac,
  med_hold_h_train, cadence_cv, size_cv, net_long_frac, coin_hhi, add_frac, avgdown_rate, regime_tilt, n_train_dec}.
- `out/cohort_K_arch.parquet`: wallet, archetype(str), + soft-membership flags.
- `out/cohort_K_arch_markout.parquet`: archetype, n_wallets, train/test neut_4h eq-wt, CI, MDE, inject_recover,
  per-coin, verdict.
