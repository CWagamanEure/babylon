# Cohort Forensics v2.1 — trader typology + drawdown forensics → feature battery

**Status:** v2.1, post two audit rounds (v1: 4-agent swarm; v2 deltas: Stage-0 correctness + methodology).
A **hypothesis-GENERATING** front-end to the feature→held-out-edge analysis. DESCRIPTIVE: characterize the top
cohort and dissect its worst episodes to propose *testable* features/risk patterns. **Nothing here is a
"finding" — the separate, inferential, OOS feature stage turns hypotheses into findings.** `[Bx]`/`[Mx]` =
methodology-audit, `[Fx]` = feasibility-audit, `[Ix]` = idea-gen, `[Vx]` = v2-delta audit. **Date:** 2026-07-04

**v2.1 changes (from the v2-delta audit):** bottom cohort redefined censoring-aware on a markout-equity curve
`[V-B1]`; §4 four gates are a graded **scorecard that ranks candidates for OOS, NOT a pass/fail AND** (a hard
AND is itself a forensic over-null) `[V-M2]`; covariance-clustering effective-N dropped for two-way
cluster-robust bootstrap `[V-M3]`; matrix methods (factor-residual) fit on the FULL FIELD not the cohort
`[V-M4]`; held-out OOS tightened against crowding leakage `[V-M5]`; Stage-0 `avg_entry_px` is a numba-JIT
recurrence + fill-VWAP comparator, not a cumsum `[V-Stage0]`.

## 0. Purpose & the TWO symmetric traps (the spine)
Boss's ask: dig into the top cohort's trades — *what type of traders are they, and what causes the severe
drawdowns we might avoid.* Two failure modes, both gated here:
- **Over-nulling** (`babylon/CLAUDE.md`): every characterization is cohort **vs a control with a CI**, never
  eyeballed; a null gap defaults to "inconclusive," not "no difference."
- **Over-fitting / hindsight**: a "drawdown cause" read off realized losses and bolted on as a rule is fit to
  noise. **Every pattern is a HYPOTHESIS for the OOS stage, never an inline rule.**

**⚠ THE SURVIVORSHIP CORRECTION (was the fatal flaw in v1) `[B2]`.** Wallets enter the cohort because their
full-window edge is HIGH → their drawdowns are, by construction, **dips that RECOVERED**. The wallets whose
averaging-down actually blew them up have low edge and are selected OUT. **You cannot learn "avoidable
drawdowns" from survivors alone.** The actionable signal is what distinguishes **drawdowns-that-recovered
(top cohort) from drawdowns-that-didn't (a bottom / blow-up cohort)** — so §2 adds that contrast and §4 is
built on it. Standing caveat repeated in every deliverable: the cohort is noise-limited (MDE≈160bp) → a
**skilled+lucky mix**; some "causes" are variance, not mistakes.

## 1. Data reality & the Stage-0 build change (design to what EXISTS) `[F1,F3,F5,F6]`
Empirically verified against the data — several v1 assumptions were wrong:
- **`out/entries`** (7.33M rows, 362k wallet-coins): `wallet, coin, b_ts(5-min), dir(±1), q, entry_px, notl`.
  **Opens/adds ONLY — closes discarded.** Cumulating `dir·q` here tracks phantom cumulative-opening-volume,
  NOT position (terminal |Σdir·q| = 38–177 entry-sizes; 97% trade both directions) `[F1]`.
- **‼ STAGE 0 (prerequisite build) `[F1, V-Stage0]`:** raw `cand2_*.parquet` has signed sizes *with closes*,
  and `taker_entries` (mkcommon.py:61) ALREADY computes true running `cum` — it just isn't emitted. Extend
  `build_entries.py` to emit, per opening entry: **`pos_after`** = `cum[oi]` (true signed position after the
  fill — FREE, just emit it); **`avg_entry_px`** = running average entry of the OPEN inventory; **`fill_vwap`**
  = the opening cluster's own fill-VWAP (same-basis comparator for the averaging-down test). Implementation
  (audit-confirmed correct/leak-free/additive — existing columns byte-identical): pass raw fill `px` into
  `taker_entries`; `avg_entry_px` is a **numba-JIT'd scalar recurrence, NOT a cumsum** (partial reduces rebase
  the weight → a cumsum is wrong; a Python loop is ~20 min over 225.8M fills): `open→a=px;
  add(same sign)→size-weighted update; partial reduce→a unchanged; flip→a=px; full close→NaN` on the same
  `flat_u` threshold as burn-in. Emit at the **last opening fill per (bar,dir) cluster** (max original index).
  **Basis note:** `avg_entry_px`/`fill_vwap` are fill-px basis; `entry_px` is next-bar-close basis — the
  averaging-down test compares `fill_vwap` vs `avg_entry_px` (both fill-basis), never against `entry_px`.
  **If Stage 0 is not done, the entire position-aware leg (§3 add-behavior, §4 inventory drawdown, martingale)
  is dropped** — no phantom-position metrics ship.
- **Bars** = `(coin, bar, close)` ONLY — no OHLC/volume `[F3]`. Consequences: realized vol is close-to-close
  (no Parkinson/GK); **"adverse-move size" is intrabar-blind → relabel "close-to-close excursion"** and note it
  understates true intrabar drawdown; **no volume regime from bars.**
- **Volume/flow proxy** comes from the raw `cand2` taker tape (per-fill `px, sz, crossed, zhash` for ALL
  tracked wallets) — usable for participation/impact/adverse-selection `[I-behav2, I-quant6]`.
- **Real OHLCV** exists at `data/follow/candles/{COIN}.parquet` but **hourly, majors only** — optional coarser
  join for true high/low (entry-lifecycle stage, intrabar adverse move).
- **Funding**: `_load_funding()` stub exists (mlscreen2.py) — cheapest external pull (§6).
- **RAM fine** (one major at a time; BTC 2.13M×7 <1GB). **Cohorts THIN** `[F6]`: top-10/50 cluster near the
  30-entry floor (top-10 median 32–70 entries; SPX unusable, 130 wallets). ⇒ typology is **archetype/pooled-
  level, NOT per-wallet points**; raise the *fingerprint* floor to ≥80; CI-gate & gray sub-N wallets.

## 2. Cohorts & controls — survivor AND non-survivor, matched, split-stable `[B2,M4,M5]`
- **Top (survivor) cohorts:** top-10 (deep) + top-50 (breadth) by `vw_edge@24h` expanding, per major + pooled.
- **Bottom / unrecovered-drawdown cohort `[B2, V-B1]` (NEW, load-bearing — but only OBSERVABLE quantities):**
  we CANNOT see "blew up" (no exits, no balances; a wallet that stops appearing may have blown up, churned, or
  just stopped — indistinguishable). So define it on an OBSERVABLE **markout-equity curve** (§4): the bottom
  cohort = wallets whose **terminal drawdown episode is large and still OPEN at window end (right-censored,
  explicitly flagged)** — "cumulative-markout curve ended well below a prior peak, not recovered by window
  end." NOT "worst `vw_edge`" (that is a steady-bleeder selector, blind to a single blow-up episode); `vw_edge`
  is a *reported attribute*, not the selector `[V-m7]`. The §4 contrast is top-cohort recovered-drawdowns vs
  bottom-cohort terminal-unrecovered(censored)-drawdowns. Label it **markout-equity drawdown** — silent on
  actual liquidation.
- **Controls, every claim reported cohort-vs-control with CI `[M4]`:** (a) **random-N matched on activity
  (entry-count) and notional decile** — because `vw_edge` is volume-weighted, an unmatched random-N makes the
  cohort look like "high-cadence whales" mechanically; matching removes the selection artifact. (b) **field.**
  (c) **ew-selected cohort cross-check**: if a trait vanishes under equal-weight selection it was volume-
  induced. Report **coin composition vs field** and run typology **within-coin** (the HYPE hump must not leak
  through the pooled top-10) `[M4]`.
- **Split-half stability `[M5]`:** select on window-half A, characterize on half B. A skill-linked trait
  persists across the split; a luck-induced enrichment washes out. (Bottom-cohort + split-half are the two
  cheap skill/luck discriminators; a *null* gap under luck attenuation is especially inconclusive — gate.)
  **Floor caveat `[V-m6]`:** a top-10 wallet has ~40 entries → ~20/half, below the 30 floor. So run split-half
  either with a reduced per-half floor (≥15) OR — preferred — as a **field/pooled-level** skill-vs-luck check
  (does the archetype enrichment persist across halves at the population level), not per-cohort-wallet.

## 3. (A) Typology — archetype-level descriptors, vs matched control, split-stable
Per wallet compute; **report at archetype/cohort-pooled level with CIs** (thin cohorts `[F6]`). Descriptors:
- **Base `[F4]` (computable now):** cadence / inter-entry-time; size (median notl, CV, field percentile);
  direction ratio & net bias; coin concentration (Herfindahl); vol-regime entry share (close-to-close).
- **Timing-vs-move `[F3]`:** sign-corr of `dir` with preceding k-bar close return (momentum vs mean-reversion).
- **Add behavior — REQUIRES Stage 0 `[F1]`:** share of entries adding to an open same-dir position; true
  **averaging-down rate** (add below `avg_entry_px`); else fall back to the weaker "same-dir worse-price streak
  since last flip" proxy.
- **Skill/luck discriminators (the class the noise-limited cohort most needs — independent of edge *level*):**
  **conviction calibration `[I-behav3]`** (within-wallet slope of markout on size-z: does it up-size its
  better trades?); **PnL-Herfindahl `[I-behav7]`** (is edge one lucky coin-month or broad?); **factor-residual
  alpha `[I-quant1]`** (residualize each wallet's edge on PC1≈crypto-beta → is edge shared beta?); **edge
  autocorrelation / half-life `[I-quant4]`**.
- **RULE for all matrix methods `[V-M4]`:** any wallet×bucket decomposition (factor-residual) is **fit on the
  FULL FIELD** (tall ~16k×12 matrix → PC1 well-defined; extract the top singular vector only), and the cohort's
  loadings are *read off* — NEVER fit within the ~50-wallet cohort (rank-deficient). Missing cells (a wallet
  inactive in a bucket) handled explicitly (mask/impute), not silently zero-filled.
- **Deployability signatures:** **markout-shape + copyability-at-15min-lag `[I-quant3,I-behav9]`** (front-loaded
  fast-decay = latency/impact, evaporates for a copier; slow monotone build = informed, survives lag);
  **size-elasticity of edge `[I-quant5]`** (does per-trade edge shrink with own size?); **reflexivity /
  participation `[I-behav2]`** (entry notl ÷ coin-bar tape volume; is the short-horizon markout own footprint?).
- **Output:** cluster into a small set of interpretable archetypes (seeded); report **archetype prevalence in
  top vs matched-control (CI)**, not raw counts.

## 4. (B) Drawdown forensics — ONE object, a graded scorecard (NOT a filter), de-clustered `[B1,B2,M1,M2,M3,V-M2,V-M3]`
**The single outcome object `[B1,F5,V-M2]`:** all of §4 is defined on ONE object — the **inventory-aware
markout-equity curve**: mark the true running net position (`pos_after`, Stage 0) to bar close over time →
a per-wallet equity path; drawdown episode = peak→trough. Bounded two ways (never-closed worst case;
inferred-hold cap from the markout-decay peak). **Decompose every drawdown into market-beta (net exposure ×
market move) vs alpha `[B1]`** — a beta drawdown on an unhedged long is not an avoidable *behavior*. Loss/win/
neutral tails and recovered/terminal-censored episodes are ALL defined on THIS curve (no per-entry-markout vs
per-episode-MTM unit mix `[V-M2]`). Without Stage 0, only the relabeled **"entry-timing-quality path"** (streaks
of badly-timed opens) is available — NOT "what a copier feels" (a copier needs an explicit exit model).

**⚠ GRADED SCORECARD, NOT a pass/fail AND `[V-M2]`.** §4 is a hypothesis GENERATOR (per §0); running hard
inference inside it (an AND of four CI gates) is *itself* a forensic over-null — with MDE≈160bp, thin cohorts,
and few independent units a cluster-robust CI essentially never excludes zero, so nothing would pass. Instead
**score each candidate pattern on four axes, each reported with its CI + an explicit "inconclusive" flag, and
RANK/annotate candidates for the OOS stage.** Significance-with-CI-exclusion is reserved for the OOS feature
test (§5), never adjudicated here. The four axes:
1. **Three-way tail asymmetry `[M1]`:** prevalence in the **big-LOSS vs big-WIN vs neutral** tail (all of the
   markout-equity curve). Elevated in losses *relative to wins* = candidate cause; elevated in BOTH = a
   symmetric variance amplifier (a sizing statement, not a mistake) — scored, not filtered.
2. **Top-vs-bottom separation `[B2]`:** does the behavior distinguish top-cohort recovered-drawdowns from
   bottom-cohort terminal-unrecovered(censored)-drawdowns? Common to both = just the style.
3. **De-clustered independence `[M2,V-M3]`:** report **raw wallet count AND #disjoint calendar windows**
   separately (they are different axes — one cascade = N=1 in *time*, correlated wallets = crowding). CI via
   **two-way cluster-robust / block bootstrap, clusters = (calendar-window, wallet)**. **Do NOT** use a
   return-covariance effective-N — with only 12 monthly buckets that matrix is rank-deficient/non-estimable
   `[V-M3]`; if a crowding discount is wanted use a coarse same-coin/dir/bucket co-occurrence count.
4. **Pre-entry-observable ONLY `[M3]`:** admissible causes use only info available AT entry (pre-entry vol/
   return trajectory, position state, size vs own norm). Post-entry "context" (incl. adverse-move) is a collider
   — the loss restated — kept in a **descriptive panel BARRED from becoming a feature.**

**Priority behavioral drawdown candidates (need Stage 0):** **martingale add-escalation `[I-behav5]`**
(up-sizing into a bleeding position — the account-killer, sharper than a flat averaging-down flag);
**post-loss tilt/revenge `[I-behav4]`** (size/speed/direction of the NEXT entry after a large loss).
**Output:** ranked scorecard; each row = {pattern, loss-vs-win-vs-neutral prevalence (+cluster-robust CI),
top-vs-bottom separation, wallet-count & #disjoint-windows, "inconclusive" flags, proposed OOS test}. **No
inline stops/rules — every row is a hypothesis for §5.**

## 5. Candidate feature battery + hardened OOS handoff `[M6]`
Every §3 descriptor and §4 pattern → a candidate feature spec: `{definition, hypothesis (predicts higher
future edge / lower drawdown), effect size we'd care about + required MDE, OOS test}`. **Tiers** (build order):
- **Tier 1 (feasible now, highest value):** conviction calibration, PnL-Herfindahl, factor-residual alpha
  (field-fit SVD per `[V-M4]`), edge autocorrelation, size-elasticity, markout-shape/copyability-at-lag.
  (Skill/luck + deployability discriminators; several drop straight into the `persistence_refine` `METRICS` axis
  and are scored by the existing config-selection-corrected null — the ready-made OOS harness.) **Moved OUT of
  Tier 1 `[V-M3,V-M4]`:** covariance effective-N crowding (not estimable → use the §4 coarse co-occurrence
  count instead).
- **Tier 2 (feasible, needs Stage 0 or the cand2 tape):** martingale escalation, post-loss tilt, true
  averaging-down, reflexivity/participation, adverse-selection via aggregate tape, regime-conditional surface.
- **Tier 3 (pull-gated, §6):** funding-adjusted edge, liquidation-cascade attribution.

**OOS handoff discipline `[M6,V-M5]` (so mined features don't relaunder the selection):** (a) validate on
held-out wallets **that are ALSO time-disjoint OR factor-residualized** — a wallet-disjoint split alone LEAKS
under crowding (held-out wallets trade the same coins/direction/time → shared beta carries the signal across
the split) `[V-M5]`; require wallet-disjoint **AND** (time-disjoint OR PC1-residualized edge). Never the
cohort's own later period (style persistence would proxy membership). (b) **Pre-register the whole battery and
its COUNT before the OOS stage sees test data**; features are correlated → a **battery-wide max-statistic
permutation null** — reuse the max-stat *principle* of `persistence_refine::config_null`, but as a NEW sibling
that permutes the **feature→outcome** label and maxes over the **feature set** (config_null is hardcoded to the
top-K wallet-ranking axis — not a literal reuse) `[V-M5]`. (c) A battery-level cross-feature aggregate/sign
test. A feature that "doesn't predict" is **inconclusive** unless its CI excludes the effect and MDE covers it.

## 6. External pulls — ranked by expected value (optional, audited if done) `[I-quant8,9]`
1. **Funding (do first):** loader stub exists, hourly, tiny. De-confounds the **24h primary edge** — is it
   price-alpha or just carry on inferred-hold inventory? First-order confound at our exact horizon.
2. **Liquidations:** the one true external drawdown-*cause* instrument (are losers run over by cascades?);
   complements funding (funding→edge attribution, liq→drawdown causation).
3. **OI** (crowding/capacity denominator) then **L2 book** (true imbalance + real spreads for the placeholder
   `COST_BPS`) — higher cost, defer until the proxies justify them.

## 7. Discipline checklist (build must satisfy)
1. Survivorship: bottom cohort = terminal-**unrecovered(censored)** markout-equity drawdown (NOT worst-vw_edge,
   NOT "blew up"); §4 is top-recovered-DD **vs** bottom-terminal-DD. ✔ §2/§4 `[B2,V-B1]`
2. Drawdown = ONE object: inventory-aware markout-equity curve of true position (Stage 0) + beta/alpha split;
   loss/win/neutral & recovered/terminal defined on it. Else relabel entry-timing path, drop "copier feels."
   No phantom-position metric ships. ✔ §1/§4 `[B1,F1,F5,V-M2]`
3. §4 is a **graded scorecard that RANKS candidates for OOS, NOT a pass/fail AND** (a hard AND is a forensic
   over-null); each axis w/ CI + "inconclusive"; significance lives in §5. De-clustering reports wallet-count
   AND #disjoint-windows via two-way cluster-robust bootstrap — **no covariance effective-N** (rank-deficient).
   Pre-entry-only causes; post-entry context descriptive, barred from features. ✔ §4 `[V-M2,V-M3,M1,M3]`
4. Every typology claim cohort-vs-**matched** control (+ew cross-check, within-coin) with CI; archetype-level;
   thin/SPX gray-out; split-half at reduced-floor or field-level. Matrix methods (factor-residual) fit on the
   **field**, not the cohort. ✔ §2/§3 `[M4,M5,F6,V-M4,V-m6]`
5. OOS handoff on held-out wallets **that are also time-disjoint OR PC1-residualized** (wallet-split alone leaks
   under crowding); pre-registered battery + a **new** feature→outcome max-stat null (not a config_null call);
   no inline rules; null → inconclusive w/ CI+MDE. ✔ §5 `[M6,V-M5]`
6. Data honesty: opens-only/exits-inferred; close-only bars (relabel adverse move, no vol regime); no
   funding/liq claims without the §6 pull. ✔ §1 `[F1,F3]`
7. Nothing is a finding — dig emits hypotheses; OOS stage emits findings. Determinism seeded; RAM one-major. ✔

## 8. Deliverable & build order
**Stage 0** (`build_entries.py` +`pos_after`,`avg_entry_px`,`fill_vwap`) → **Stage 1** typology
(`cohort_forensics.py` +figs, archetype table vs matched control) → **Stage 2** drawdown forensics
(top-recovered vs bottom-terminal, the graded four-axis scorecard) → **Stage 3** candidate-feature battery
table (Tier 1 first, several into the existing `METRICS`/null harness).
Deliverable: `notebooks/cohort_forensics.ipynb` (typology + drawdown gallery + battery) + the pre-registered
feature spec for the OOS stage. Flow: architecture(this) → re-audit deltas → build → code audit → run →
steelman/framing audit.
