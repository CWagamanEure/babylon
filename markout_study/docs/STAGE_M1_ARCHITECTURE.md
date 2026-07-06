# Stage M1 — Historical SCREEN (discovery): nominate a frozen forward-test shortlist. NOT proof.

**Status:** ARCHITECTURE (pre-build). Flow: design-audit → build → code-audit → run → steelman → ledger.
**Doctrine:** *history nominates the wallets; new (forward) data judges them.* Stage 1 produces a ranked shortlist
+ frozen rules + wallet-specific power estimates. It makes **no** claim of individual proof. All "significance"
lives in Stage 2 (forward). The one honest inference Stage 1 CAN make: **does the screen persist into a holdout
at all?** (train→test dry-run) — if a shrinkage-ranked historical shortlist does not out-perform in a holdout,
the forward test is likely futile; if it does, forward is worth arming.

## 0. Required deliverables (this doc guarantees all 10)
1) ranked historical shortlist  2) explained shrinkage estimator  3) SEPARATE rankings for net-profitability and
benchmark-relative  4) no forward info in selection  5) frozen 10–20 wallet list  6) frozen execution + exit rules
7) wallet-specific power estimates from ACTIVE DAYS  8) Romano–Wolf critical values COMPUTED (not assumed)
9) explicit handling of the TWO testing families  10) predefined inactivity/attrition rules.

## 1. The two testing families (kept SEPARATE — do not merge into a worst-case)
- **Family A — copyable profitability:** `H0_A: E[net_copied_return] <= 0`. Outcome = net copied return (gross −
  cost). Benchmark = zero. Lower variance → more powered. The business question ("is it profitable to copy?").
- **Family B — incremental information:** `H0_B: E[copied_return − fade_return] <= 0`. Outcome = copied minus the
  ONE frozen mechanical fade (Stage-L generic benchmark, priced per-coin at the wallet's H). Higher variance (F1:
  the fade is direction-mismatched ~half the time, ρ<0, so var(A−fade) > var(A)) → strictly LESS powered; secondary.
  NOTE: "beats fade" ≠ "informed" for a trend-rider (it beats the fade by carrying directional beta) — Family B
  is reported, not used to veto Family A. A wallet can be A-positive (worth copying) yet B-null (no info edge);
  both are reported. No worst-case-of-{fade,momentum}.
Rank, filter, and power-estimate each family separately. The fade benchmark is a real per-coin strategy return
(NOT the market-residual used in M0) so it is well-defined for BTC too — no BTC-degeneracy in Family B.

## 2. Unit + outcomes
Episodes = wallet+coin+direction position lifetimes (reuse `cohort_K_archfeat.ledger` episode emitter). Per episode:
- `copied_entry_px` = next-bar close after entry (conservative ~<=5min copy latency).
- exit at the wallet's FROZEN horizon H = its TRAIN median hold (per §7).
- `net_return = dir*(px(entry+H)/copied_entry_px − 1)*1e4 − round_trip_cost(coin)` (cost = fee+spread proxy per
  coin, labelled an UPPER-BOUND; real BBO deferred to the forward harness).
- `fade_return` = mechanical fade priced at the same (coin, entry_ts, H). `alpha = net_return − fade_return`.

## 3. Discovery structure — no forward info in selection (deliverable #4)
Two passes, both historical, both leak-free:
- **(a) DRY-RUN (the immediate honest read):** select the shrinkage-ranked top-20 on **TRAIN only** (ts<Feb1),
  then measure their **TEST** (≥Mar1) net_return + alpha with a day-block bootstrap. This asks *does the screen
  persist into a holdout?* Report the top-20's TEST net_return distribution + how many stay positive vs a random
  20. (Caveat: TEST is a within-historical holdout, partially examined across the arc — a directional validity
  check, not the real forward confirmation.)
- **(b) FROZEN SHORTLIST for forward:** re-rank on **ALL 11 months** (more data → better nomination; forward data
  is the untouched judge), emit the frozen list + rules. Selection never touches future data (none exists yet).
TEST is NOT used to pick (a)'s list; forward is not used to pick (b)'s. Both satisfy #4.

## 4. Shrinkage estimator (deliverable #2 — explained)
Raw per-wallet means are winner's-curse-biased (low-N wallets produce extreme means). Empirical-Bayes / James–Stein:
```
m_i      = wallet i's mean (net_return or alpha), from n_i active DAYS (day-level means, so units are independent)
s_i^2    = within-wallet day-variance / n_i           (sampling variance of m_i)
tau^2    = max(0, Var_i(m_i) − mean_i(s_i^2))          (between-wallet TRUE-mean variance, method of moments)
B_i      = tau^2 / (tau^2 + s_i^2)                     (reliability: ->1 for many days, ->0 for few)
m_i_hat  = mu + B_i*(m_i − mu)                          (shrink toward pooled mean mu; low-N shrinks hardest)
```
Rank on `m_i_hat`, NOT the raw mean. This is what pulls a lucky 30-day wallet back toward the pack and stops the
shortlist from being the low-N tail. Report raw vs shrunk side by side so the shrinkage is visible.

## 5. Ranking + outcome-independent filters (applied to the shrunk score)
Rank each family by `m_i_hat`, then require (pre-registered, before reading the ranks):
- **active days** >= 30 (day-block validity; report the number per wallet).
- **cross-month consistency:** positive in >= ceil(0.6 * active months) of its active months (sign stability).
- **low concentration:** no single day > 20% and no single coin > 50% of cumulative net_return (kills HYPE/SOL
  burst artifacts — the arc's recurring false positive).
- **episode count** >= 100 (data richness, secondary to active days).
- **horizon stability (anti horizon-mining, ChatGPT's adjacent-horizon rule):** the horizon is FROZEN at the
  wallet's TRAIN median hold (never argmax'd — we do NOT enumerate wallet×horizon finalists, so the family stays
  wallet-count). As a robustness FILTER, the wallet's edge at its frozen H must not be a lone spike: require
  net_return >= 0 at BOTH grid-neighbors of H in {1h,2h,4h,8h,24h}. A wallet positive only at exactly one horizon
  and negative at both neighbors is rejected as noise. (E.g. H=4h must also be >=0 at 2h and 8h.)

## 6. Frozen shortlist (deliverable #5)
Take the top of the filtered Family-A ranking; **over-select to ~25–30** to survive forward attrition, then the
final frozen forward set = top **10–20**. Emit both the A-ranked and B-ranked lists (a wallet can be on one, both,
or neither). Freeze to `out/stageM1_shortlist.parquet` (wallet, ranks, shrunk scores, n_days, filters passed).

## 7. Frozen execution + exit rules (deliverable #6) — frozen BEFORE forward
- entry latency: next-bar close (~<=5min); sizing: fixed notional per episode (equal-weight; documented).
- exit: fixed H = wallet's TRAIN median hold (one policy per wallet, no argmax).
- cost model: per-coin fee+spread proxy (upper bound; forward harness replaces with real BBO).
- benchmark: the single frozen mechanical fade (per-coin, at H).
- exclusions: wash/crossed handling per mkcommon; majors only.

## 8. Wallet-specific power estimates (deliverable #7) — in ACTIVE DAYS
Per finalist, for BOTH families: day-level sigma, and `D_required(edge) = (crit * day_sigma / edge)^2` active days
for target edges {10,15,20,25} bp. Report each finalist's current active-days rate (active days / calendar day)
and the implied forward CALENDAR time to reach D_required. Family B's larger sigma → larger D_required (state it).

## 9. Romano–Wolf critical values — COMPUTED (deliverable #8)
Compute the max-t critical value by JOINT day-block bootstrap over EXACTLY the frozen shortlist (10–20), studentized
by a moderated (limma-style) per-wallet SE (F5 fix), one-sided, FWER control at 0.05 AND 0.01. Report the crit for
the 10-, 15-, 20-wallet family sizes so the Stage-2 hurdle is known in advance (it is ~2.6–3.2, NOT the 4.78 of the
600-wallet certification family). This is the number Stage 2 will use; compute it now on the frozen family.

## 10. Inactivity / attrition rules (deliverable #10) — predefined
- A finalist that produces < 30 active days OR < 100 episodes in the forward window is **dropped** (insufficient
  data), NOT counted as a fail — its slot is why we over-select to 25–30.
- Behavior-drift guard: if a finalist's forward median hold moves > 2x its frozen H, or its taker-share drops
  below 0.6, flag as "regime-changed" and evaluate separately (its frozen exit rule may no longer fit).
- Wallet death: no forward episodes for 30 consecutive calendar days → retired from the active set.

## 11. Execution plan — RAM-safe, in-memory (reuse M0/Stage-L machinery)
- M1a: episodes + net_return + fade alpha (reuse ledger episodes + Stage-L placebo pricer + M0's day aggregation).
- M1b: shrinkage + rankings (A and B) + filters + dry-run (train-select→test-judge) + frozen all-history shortlist.
- M1c: per-wallet power table + computed RW crit on the frozen family.
- Outputs: `out/stageM1_shortlist.parquet`, `out/stageM1_power.txt`, `out/stageM1_dryrun.txt`.
All in-memory on cohort_K_entries + bars (+ a cohort-only tape pass only if episode holds need it). Peak ≤ ~1GB.

## 12. Failure modes for the design audit
- Dry-run leakage (test used in selecting the dry-run list) → must select on train only.
- Shrinkage mis-estimated (tau^2 negative / wrong level) → verify method-of-moments, day-level units.
- Cost proxy so loose Family A is meaningless → label upper-bound; Family B (cost cancels) is the robust leg.
- The screen has NO real signal (train top-20 don't persist in test) → then say so; the shortlist is then just a
  prior with an honest low hit-rate, and forward EV is low. Do not dress a non-persistent screen as a candidate set.
- Concentration/consistency filters gameable or too loose (HYPE/SOL burst survives) → per-coin AND per-day caps.
- Over-selection (25–30) inflating the eventual RW family → the RW crit is computed on the FINAL frozen 10–20 only.
- Attrition rules used post-hoc to excuse failures → they are frozen here, pre-forward.
