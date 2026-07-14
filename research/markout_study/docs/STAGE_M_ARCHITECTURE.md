# Stage M — Two-stage, multiplicity-controlled, out-of-sample test for a COPYABLE wallet edge

**Status:** ARCHITECTURE (pre-build). Standard flow: design-audit swarm → build → code-audit → run →
steelman/prosecute → ledger. All estimands/rules FROZEN before the confirmation window is read.

## 0. What this test is (and the two nulls it must reject)
Everything before Stage M measured markout of the wrong estimand (raw, per-fill, vs zero) at the wrong unit
(fills, not bets). Stage M tests the estimand the boss's objective actually needs:
- **Informed** (necessary): prices move favorably *after their entry*.
- **COPYABLE** (the real null): prices keep moving favorably *after you observe and copy them*, net of latency,
  cost — AND above what a mechanical benchmark earns at the same entries. A wallet can be informed yet uncopyable
  (edge gone in 100 ms) or copyable-looking yet just riding generic reversal/beta (Stage L killed exactly this).
So the null is **H0: μ_i ≤ (mechanical benchmark)**, one-sided, on **decision episodes**, out-of-sample,
multiplicity-controlled across the whole search.

## 1. Unit of observation — decision EPISODES, not fills
Collapse fills into one episode when they share **wallet + coin + direction** and are one contiguous
position-building sequence. Two equivalent constructions (build uses the ledger one):
- **Ledger episode (preferred):** a position lifetime from the avg-cost ledger (flat → … → flat/flip), reusing
  the `cohort_K_archfeat.ledger` episode emitter. One 30-min 200-fill BTC accumulation = ONE episode.
- Fallback: time-gap clustering (gap < 15 min) on `out/entries`.
Each episode carries: `wallet, coin, dir, entry_ts, copied_entry_px, exit_ts_frozen, day, gross_ret, alpha`.
Independence unit for inference is the **episode**, and (via the block bootstrap, §4) the **day**.

## 2. Outcome — net copyable ALPHA over a mechanical benchmark
Per episode, at the wallet's frozen horizon H (= its TRAIN median hold, outcome-independent, no argmax):
```
copied_entry_px      = next-bar close after entry_ts        (conservative ~<=5min copy latency; sub-bar δ unavailable)
gross_ret(H)         = dir * (px(entry_ts+H) / copied_entry_px - 1)
benchmark_ret(H)     = mechanical strategy priced at the SAME (coin, entry_ts, H): fade AND momentum AND
                       same-window-average (all pre-registered; primary = fade, the Stage-L generic reversal)
alpha(H)             = gross_ret(H) - benchmark_ret(H)
net_abs(H)           = gross_ret(H) - round_trip_cost(coin, size)     (for the absolute-profitability gate only)
```
**KEY — cost cancels in alpha:** copy and benchmark both pay the same round-trip cost, so
`alpha = (copy_net) - (benchmark_net) = copy_gross - benchmark_gross`. The CORE SPA/RW test is therefore
**cost-model-invariant** and runnable on today's data (fills+bars). The cost model (BBO ideal; calibrated
spread+fee+impact proxy as stopgap, labelled an upper bound) is needed ONLY for the separate `net_abs > 0`
acceptance gate, not for the significance test. μ_i = mean episode alpha for wallet i.

## 3. Chronological split (no random splitting — leaks regime/position across folds)
- **DISCOVERY:** build the candidate universe; FREEZE the episode rule, horizon H per wallet, benchmark set,
  latency, cost model, and ONE exit policy per wallet.
- **CONFIRMATION (untouched):** run SPA/RW on the frozen candidates + frozen rules only.
Split boundaries reuse the frozen TRAIN(<Feb1) / embargo(Feb) / TEST(>=Mar1) grid; if the confirmation window
is too short for ≥30–50 days per wallet, widen by re-cutting the discovery/confirm boundary (decided pre-run,
recorded) rather than shrinking the day requirement.

## 4. Inference — block bootstrap + two stages
**Block bootstrap:** moving-block over **calendar days**, block length L≈5 days, resampling ENTIRE days with
ALL wallets/tokens kept together within each block (preserves regime, serial correlation, cross-wallet
correlation, same-thesis clustering). B≈2000 resamples. Per wallet: mean alpha and block-bootstrap SE → studentized
`t_i = mean_i / se_boot_i`, one-sided (upper).
- **Stage 1 — Hansen SPA:** omnibus "does the universe contain ANY wallet beating the benchmark, after the
  search?" Test stat = max_i studentized mean alpha; null via the recentered (Hansen-consistent) block bootstrap;
  p_SPA = frac of bootstrap max-t ≥ observed. If p_SPA not significant → universe has no superior wallet, STOP.
- **Stage 2 — Romano–Wolf stepdown max-t:** if SPA passes, WHICH wallets survive. Family = wallet ×
  {horizons kept} × {entry-delay} × {exit policy}. Iterative: take max-t candidate, adjusted p from the
  bootstrap max-t null over the still-active family, reject if < α, remove, repeat. Controls FWER; exploits
  cross-test correlation (less crude than Bonferroni).

## 5. Acceptance criteria (a wallet is a SERIOUS candidate iff ALL hold)
1. Romano–Wolf adjusted one-sided **p < 0.01** AND positive **99% lower confidence bound** (on alpha).
2. **≥ 100–200 independent episodes** (exact floor set by the §7 power pre-check per variance) across
   **≥ 30–50 distinct days**.
3. **Beats the mechanical benchmark** (alpha > 0), not merely > 0 raw.
4. **net_abs > 0** after latency + cost (proxy now; flagged upper bound).
5. Positive in **multiple chronological subperiods**; **no single day / token / episode** contributes most of
   the alpha (concentration cap, e.g. top day ≤ 35% of cumulative alpha).
6. Holds in the **untouched confirmation window**.

## 6. Exit handling
Freeze **one** exit policy per wallet in DISCOVERY (primary = fixed H = TRAIN median hold). Either (a) freeze
that single policy and evaluate the complete copy strategy in confirmation, or (b) include every candidate exit
horizon in the RW family and pay the larger hurdle. Primary = (a). Never report the best exit post hoc.

## 7. POWER PRE-CHECK (Job M0 — the gate before building the harness)
The rigorous unit (episodes, not fills) + honest dependence (block bootstrap) SHRINKS effective N and WIDENS
CIs, so this can be null-by-construction. Before building Stage 1/2, MEASURE:
- per-episode residual σ of **alpha** (benchmark-paired) vs raw markout σ (=145bp/fill today) — how much does
  pairing + episode-collapse cut the noise?
- implied per-wallet MDE at 100 / 200 / 300 episodes, and the RW-corrected MDE across the universe size.
- the distribution of episodes-per-wallet and distinct-days-per-wallet: how many wallets even meet §5.2?
- a positive control: inject a +Xbp alpha into a random wallet's episodes; does SPA/RW recover it?
If MDE_RW ≫ any plausible copyable edge for ALL wallets → the design is blind; report that as the decisive
answer (no powered test constructible from this data → forward accrual), do NOT run a blind SPA/RW and relabel.
If some wallets clear → proceed to the full harness.

## 8. Execution plan — RAM-safe, strictly serial (ramguard, one heavy job at a time)
- **M0 (in-memory, gate):** episodes + alpha + power pre-check → `out/stageM_power.txt`. Reuses ledger episodes
  (from a cohort-only tape pass if needed, else from `out/entries`) + benchmark pricing (Stage-L placebo).
- **M1 (in-memory):** build the frozen episode table `out/stageM_episodes.parquet` (discovery+confirm labelled).
- **M2 (in-memory, heavy compute not RAM):** block-bootstrap + SPA (discovery) → candidate flag.
- **M3 (in-memory):** Romano–Wolf stepdown (confirmation) + acceptance criteria → `out/stageM_survivors.parquet`.
- **M4:** steelman/prosecute swarm → ledger.
No 3.3GB tape scan except (if episodes need it) a cohort-only majors pass, BATCH≤100. Peak ≤ ~1GB.

## 9. Open decisions to lock at audit
- Universe: cohort_K (1,694) only, or widen to all ≥N-episode taker wallets? (broader search → bigger RW hurdle
  but the honest family).
- Benchmark primary: mechanical fade (Stage-L generic reversal) — confirm it's the right generic null; add
  momentum + same-window-average as the pre-registered set.
- Block length L and confirmation-window length vs the ≥30–50 day requirement (tension: our TEST is ~4 months).
- Cost proxy calibration for the `net_abs` gate (BBO from S3 later; proxy now).
- Episode independence: is a position-lifetime truly independent, or do overlapping multi-coin episodes on the
  same thesis need day-level clustering only? (block bootstrap handles the day level regardless.)

## 10. Known failure modes for the design audit to pressure-test
- Episode-collapse + block bootstrap makes it blind-by-construction (power) → §7 gate is mandatory.
- SPA/RW benchmark = zero instead of the mechanical strategy → would flag generic-beta/reversal wallets (the
  Stage-L trap). The null MUST be benchmark-relative.
- Confirmation window too short for ≥30–50 days → underpowered per-wallet OOS leg.
- Horizon/exit argmax leaking in via the "kept horizons" family.
- Cost cancellation claim wrong if copy and benchmark trade different size/frequency (verify same sizing).
- Block bootstrap mis-implemented (not recentered for SPA; blocks too short vs hold H → overlapping outcomes
  split across blocks).
- Universe selection itself outcome-dependent (must be N/behavior-based, not performance).
