# FINDINGS LEDGER — wallet-features / copy-trade arc (2026-07-07 → 2026-07-10)

The report-ready backbone (CLAUDE.md convention): one entry per stage — question, method, calibrated
result, caveats, artifacts. Labels below are the SETTLED ones (post all audits); superseded interim
numbers are marked. Companion ledger for the earlier markout study: `markout_study/docs/FINDINGS_LEDGER.md`.

## 1. Tier-1 build — episode lake + per-wallet panels
- **Q:** is a leakage-safe per-trader feature layer constructible from the fills tape?
- **Method:** lifecycle-episode walker (flat→…→flat/FLIP, exact-integer ticks, carry-seed across months),
  5-agent audit; Table-2 panels (close-attribution membership, two-source join).
- **Result:** 33,794,649 episodes (40 cols); 12,988,131 panel rows (78 cols); 0 invariant/leakage violations.
- **Caveats:** float PnL cast at SQL boundary; partitioned by close-month.
- **Artifacts:** `data/derived/episodes/`, `data/derived/addr_coin_features/`,
  `research/data/{episodes_build,features}.py`, `docs/WALLET_FEATURES_TABLE23_ARCH.md`.

## 2. Tier-2 markout estimand — build + 3-agent design audit
- **Q:** how to measure entry-timing skill without the stale-price artifact that killed edge3?
- **Method:** post-fill entry anchor (first oracle tick STRICTLY after open), per-minute oracle ASOF with
  ≤90s staleness bound, per-episode raw markout ×10 horizons; μ drift baseline at aggregation time.
- **Result:** design audit produced overrides R1–R11 — headline estimator = wallet-day-weighted mean
  (median-of-means proven biased ±7bp under skew → SPEC P15 superseded); μ leakage fixed; episode keys
  proven non-unique → 1:1 augmentation.
- **Artifacts:** `research/data/{markout,mu_baseline,features_markout}.py`,
  `docs/WALLET_FEATURES_TIER2_MARKOUT_ARCH.md` (v2 override block).

## 3. Horizon structure — AUC vs per-horizon (user call)
- **Result:** averaging across horizons buries signal: 16 all-4-horizon survivors vs 1,213 at ≥1 horizon;
  69% of candidates are horizon-specific. Per-horizon is the unit; argmax must be multiplicity-charged.

## 4. In-sample luck test (`permute_timing.py`)
- **Result:** 258/2,134 hygiene-clean candidates beat 1000× random-entry-timing shuffles (max-stat horizon
  correction, BH q=.10 over 20,831 family). Real IN-SAMPLE timing structure exists.
- **Caveats:** in-sample only; module carried the MaskedArray bug until 2026-07-10 (sweep verdict: SAFE,
  ≤0.2% distortion).

## 5. OOS persistence — cohort level (`persistence.py`) — POWERED METHOD-SCOPED NEGATIVE
- **Result:** select on p1 timing_alpha, measure p2: 1h +1.13 CI[−0.65,+2.92] sign 52%; 8h −8.89 REVERTS.
  MDE 2.5–5bp ≤ 8bp care ⇒ earned. Historical timing_alpha does not select forward-persistent cohorts.
- **Caveats:** 8h cell later shown HYPE-stale-oracle-heavy; module verified NOT affected by the numpy bug.

## 6. What persists instead (steelman byproduct, `steelman_pnl.py`)
- **Result:** dollar-PnL rank rho +0.28 ≈ mostly SIZE (size rho +0.835); ROI-skill rho +0.17 weak,
  absolute-negative in the window. Size persists; skill barely.

## 7. Discover→confirm arc → "4 replicated traders" — SETTLED: OVER-CARRY, RETRACTED
- **Result of record:** "reproducible sub-cost structural residual, skill unproven." Fisher independence
  empirically false (cross-half r +0.04–0.08); 3/4 net losers; #4 uncopyable maker. Cohort OOS +2bp ≪ care.
- **Artifacts:** `research/data/discover_confirm.py` (postscript), `data/derived/confirmed_traders/`
  (README warns against face-value reads).

## 8. Pre-registered confirmatory protocol — original (21 candidates)
- **Result:** 2,878→21 frozen→7 testable; Tier-A basket +1.41 CI[−10.81,+13.62] MDE 17.45 → INCONCLUSIVE
  (attrition-starved); style p=0.429. Superseded by A1+A2 run (entry 9).

## 9. Confirmatory A1+A2 (no PnL gate, q_disc=0.20) — 83 candidates
- **Result:** 11,562→4,058→83→31 testable; Tier-A basket −2.18 CI[−7.76,+3.39] MDE 7.97 → EARNED-NULL by
  frozen rule (knife-edge margin 0.03bp — re-certified with fixed code 2026-07-10, see cert rerun);
  Tier-B: 1 confirmed wallet 0xd7dc4b4ad3a7…14cb5 (HYPE@1h, +40.7bp/40d, p=2e-4; also positive-PnL —
  the only wallet where markout+replication+profit ever aligned).
- **Caveats:** mined-tape asterisk; MaskedArray bug in the original run (sweep: SAFE, attenuation-only).
- **Artifacts:** `docs/CONFIRMATORY_PREREG.md` (+amendments), `docs/WALLET_CANDIDATES_2026-07-09.md`,
  `data/derived/confirmatory/`.

## 10. Full-family static walk-forward (`family_wf.py`, user's corrected stats)
- **Result:** BH over the ENTIRE 9,743 family (hurdle-in-null, 2-stage bootstrap, labels-not-gates) →
  3 survivors → forward: 67% attrition, survivor flipped +49→−12bp, basket −17bp net. **Static frozen
  lists are dead as a deployment shape** (converges with entries 5, 8, 9).

## 11. ROLLING walk-forward (`rolling_wf.py`) — the deployed selector — LABEL OF RECORD (post all audits)
- **Result (corrected, post NaN-fix):** L=6: gross +16.49 net +11.49 CI_gross[+1.4,+31.6], day-p 0.067;
  **month-clustered p ≈ 0.09–0.10; family-adjusted (max-T over 3 same-window selectors) p ≈ 0.17**
  (≈0.2–0.25 counting entries 9–10's looks); HYPE-carried (**ex-HYPE net +1.4bp, p≈0.4**); 4/5 months;
  MDE 21.6bp. L=3: nothing (+0.13 net). Placebo: 0/500 random baskets reach it (~4σ — not noise).
- **Label:** *underpowered, selection-inflated, HYPE-concentrated positive — direction favorable, nothing
  established.* [SUPERSEDED interim claims: "+21.5/+16.5 p=.0087" (pre-bug-fix) and "suggestive p=.067"
  quoted without the family charge.]
- **Deployment rationale:** paper-copy forward on untouched data is exactly the instrument that resolves
  selection inflation; several months needed at this MDE.

## 12. Copyability + live-parity audits (pre-deploy swarm + full-stack swarm)
- **Results:** edge survives copy delay (99% at 1–2min — conviction taker flow); **exit-on-frozen-clock
  mandatory** (mirroring trader exits kills it); realistic taker cost ~10.5bp RT → corrected net ≈ +6bp/day
  marginal; **paper `raw_bps` embeds ~11bp RT + spread → evaluation must UN-FOLD costs
  (FORWARD_PAPER_PREREG amendment A1) — the original formula double-counted and would have rigged a false
  null**; refresh-seam bugs (new-wallet KeyError, orphaned-coin exits) found and fixed pre-refresh.
- **The MaskedArray/fetchnumpy bug (F1):** NULLs read as ~0.0 through np.asarray; fixed via `_fcol` in all
  conclusion-bearing modules (2026-07-10); repo-wide sweep triaged every recorded verdict SAFE (null rates
  0.00–0.45%, attenuation-only); `src/babylon/` clean.

## 13. Persistence-score selector (`persistence_wf.py`, frozen user spec, run ONCE) — REJECTED FOR DEPLOYMENT
- **Result:** combined 148d gross +1.89 net −3.11 CI_gross[−4.14,+7.93]; 1/5 months; attrition only 7%.
  Line-level audit: numbers reproduce bit-exactly, no flip-capable bug.
- **Calibrated label (per stats audit — over-null gate applied):** deployment rejection EARNED (edge <8bp
  gross at ~97% one-sided, p=0.026); epistemic "no edge" NOT earned (MDE ≈8–9bp vs 3bp-excess care ⇒
  INCONCLUSIVE below 8bp). **Registered live underpowered positive: the EX-HYPE cut — gross +7.43 /
  net +2.43 CI[−0.64,+15.49], 4/5 months gross-positive — corroborated by rolling-L6's ex-HYPE cut
  (+6.42 gross) from a nearly disjoint cohort (7/153 overlap).**
- **Retraction:** the "steadiness vs edge are substitutes" narrative is UNSUPPORTED (trait→forward
  correlations all |r|<0.11, n=160; the selector divergence is one HYPE cohort, itself p≈0.10).
- **BINDING: selector mining on this tape is CLOSED — no 4th variant. The forward paper run adjudicates.**

## 14. LIVE DEPLOYMENT — babylon-basket paper follower (2026-07-09→)
- **What:** droplet 167.71.29.107, systemd `babylon-basket`, frozen top-20 basket (sha 1e53a112cac97976),
  2-min entry lag, per-row frozen-horizon clock exits, PaperExecutor (no signing code exists).
- **Scorecard:** `docs/FORWARD_PAPER_PREREG.md` incl. amendments A1 (cost un-fold formula), A2 (copier-
  anchored estimand label), A3 (honest baseline = family-adjusted p≈0.17). Config epoch 1 (22:26–23:13Z
  2026-07-09, skip_leading bug) EXCLUDED. Min 3 months / 60 active days before any verdict.
- **Refresh:** monthly — local pipeline → `rolling_wf live` → `scripts/deploy_basket.sh`.

## DEAD-END REGISTER (do not re-run)
- Static frozen wallet lists (entries 5, 8–10: attrition + regression kill them all).
- Realized-PnL>0 as a discovery GATE (over-filters 75%; keep as reported column).
- Hard two-way BH intersection (effective FDR ~1e-3; underpowered by construction).
- Discovery-magnitude (point-estimate) weighting/selection (winner's curse; top-decile −44bp OOS).
- Mirroring trader exits (kills the edge; clock exits mandatory).
- AUC horizon-averaging (buries horizon-specific signal).
- Median-of-means as headline estimator (biased ±7bp under skew; diagnostic only).
- skip_leading event filter in the LIVE follower (drops nearly all true opens; offline-only concept).

## OPEN QUESTIONS (live)
- Does the rolling procedure earn net capture on untouched July+ data? (The deployed experiment.)
- The ex-HYPE small-positive residual (entries 11, 13) — real sub-care edge or noise? Forward data decides.
- Wallet 0xd7dc4b…14cb5 — the single cross-method survivor; track, don't worship.
- Realistic cost path (fee tiers/maker entries) if forward capture confirms at ~+6bp/day marginal.
