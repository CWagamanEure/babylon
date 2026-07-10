# Edge-correctness audit (round 3) — SYNTHESIS

2026-07-01. 65-agent adversarial swarm on the deployed claim (+24–31bp net eof, 6h/15-min,
trimmed-mean, live harvest executor + two-condition GO gate). 18/18 findings confirmed by
3-lens verification; full detail in `FINDINGS.md`.

## Verdict

**The edge as claimed is not established, and the live experiment as coded cannot establish it.**
Two independent kill-chains:

### Chain A — the measurement: the headline number is probably not real

1. **F2 (fatal if true): the "15-min lag" is fictional.** `_close_at` on HOURLY candles prices
   entries at the last fully-closed hourly candle — on average 15–30 min *before* the leader's
   fill for the 60s/5m/15m lag cells. The estimator harvests pre-fill run-up + the leader's own
   impact. The sweep's own decay curve (71→64→37→21) is exactly what stale-pricing predicts;
   solving the pre/post-fill mixture puts the honestly-post-fill edge near **zero to negative**.
   Only the 30-min-lag column (+21 gross, breaks at conservative cost) is honestly priced.
2. **F3 + F7 + F16: winner's curse and multiplicity.** The deployed metric (trimmed-mean) is the
   max over ~17 metrics ranked by OOS performance on the same 4 folds; the quoted CI was computed
   under a *different* metric (Sortino) and field definition; the promised panel bootstrap CI was
   never computed (dead `rng`); ≥40 grid looks with one-sided 90% CIs and no correction — Šidák
   at ~8–10 effective looks moves the conservative-cost lower bound to ~−5bp. Fixed-horizon
   reframing was itself a second bite after round-trip came out −30.
3. **F11: "+24–31bp NET over field" was never measured as stated** — eof is only ever reported
   gross; "net" is the selected arm's absolute mean minus flat cost.
4. **F9 + F14: CIs too narrow** — wallet-cluster bootstrap ignores coin-episode crowding
   (design effect ~2x → conservative-cost CI [+6,+44] → roughly [−1,+49]) and resamples wallets
   independently per fold.
5. **F17, G5: cost surface and delisting censoring both push the same (optimistic) direction.**

Honest posterior on the deployed operating point: **~0 to +15bp, not clearly positive after
correction — and possibly negative once entry pricing is fixed (F2).**

### Chain B — the gate: as coded it answers a different question, in both directions

- **Spurious NO_GO:** F4 — the realized maxDD bound compounds every $3–15 tranche as a
  whole-book sequential bet; at cap_mult=20 tranche counts a −25% breach of that fictional curve
  is near-certain → NO_GO regardless of truth.
- **Spurious GO:** F1 (no stopping rule: post-min-n INCONCLUSIVE re-readable forever, dead
  horizon_cap_days, fresh multiplicity ticket every 14-day re-roll — round-1 18-F1 never landed),
  F6+F9 (gate_block=10 « overlap length; one herded coin episode can pass both legs), F8 (realized
  leg entered at ~30–60s embeds the fast-lag microstructure alpha the study itself classified as
  uncapturable → profitability leg can pass when the 15-min edge is zero), G1 (the "realized-net"
  leg is a beta-hedged SYNTHETIC with a free 190-coin basket hedge the executor doesn't hold).
- **Underpowered anyway:** F5 — power ~5–25% at 14 days under the team's own effect size and
  overlap structure; a rare day-14 GO certifies a 2–5x luck-inflated edge. F10 — min-n was
  pre-registered on round-trips but the reworked gate can judge on 30 harvests.
- **Population mismatch:** F12 (legs scored over different windows/rosters; frozen-fills re-rolls),
  F15 (funding carry silently regressed out of HarvestRunner — realized leg is gross-of-funding on
  6h perp holds), F18 (liveness-conditioned sample), F13 (capacity is a self-attested CLI flag).
- **Provenance/parity gaps (critic):** G2 frozen beta=1.245 everywhere, G3 frozen candidates CSV
  with no in-repo builder (same defect class as round-1 H2), G4 single-source unverifiable data +
  fail-open live conviction filter (missing hash ⇒ conviction=True), G5 delist survivorship +
  un-exitable tranches.

## What would actually settle it (priority order)

1. **Re-price entries at true post-fill timestamps (F2).** This is THE decisive test. Needs
   sub-hourly data: 1m/5m candles via HL candleSnapshot backfill, or the S3 L2 archive. If the
   6h edge at honest ≥15-min post-fill pricing is ~0, everything else is moot.
2. **Pre-register ONE confirmation cell** (metric, horizon, lag, cost, field definition, CI type)
   on data not yet used — the next N weeks of live fills — with a written stopping rule; fix
   F1 (lock post-min-n reads), F4 (per-tranche-weighted DD or drop the bound), F6 (block ≥
   overlap length or cluster by coin-episode), F15 (funding), G1 (gate on unhedged realized PnL
   or charge the hedge).
3. Only then re-arm the GO gate.

## Status of the droplet run

The live paper trade keeps accruing data and costs nothing — no need to stop it. But its gate
verdict must not be read as designed until Chain B fixes land, and the +24–31bp expectation
should be treated as unvalidated pending item 1.

---

# EMPIRICAL CONFIRMATION (added 2026-07-01, same day)

F2 was re-measured, not just argued. `scripts/selci_fh.py` gained `--pricing post` (strictly
post-fill: price = close of the candle CONTAINING t, stamp in (t, t+iv]; beta leg aligned to the
same instants) and `--candle-ms` (interval-aware). Control first: a RAM-safe streaming CI
(`scratch_conv/ci_stream.py`) reproduces the published numbers on the original extract exactly
(L900_H6 eof +39.3 [+19.6,+58.1] 4/4; lag curve 71/64/37/21 digit-for-digit).

**Stage 1 — same 4 folds, same ~1.07M openings, hourly candles, post-fill pricing:**
every cell GONE. Deployed cell L900_H6: eof **+0.4 [−14.4, +18.5]** (was +39.3 SURVIVES 4/4).
L60_H1: +3.9 (was +70.9). The published lag-decay curve was the artifact signature.

**Stage 2 — 15-minute candles (HL API serves ~5000 = back to 2026-05-10), single June fold
(train May 11→Jun 11, test Jun 11→28, k=3 past-only universe), post-fill pricing ≤15min after
fill+lag:** the 6h horizon is NEGATIVE at every lag (eof −8 to −25, deployed cell −25.2
[−49.2,+24.7]); even 60s lag gives −14.5 — so there is no first-30-minutes alpha for the fast
live executor to capture at 6h. The 1h horizon shows small gross positives (+12..+23, CI_lows
hugging zero, non-monotonic in lag, single fold) that round-trip cost (15–22bp) fully absorbs.

## Final verdict
The +24–31bp deployed edge was the hourly-candle stale-pricing artifact (pre-fill run-up +
leader impact credited to the follower). Honest post-fill measurement: **~0 gross at 6h across
4 folds, negative at 6h on fine-grained June data, nothing that survives cost anywhere.**

## Consequences
- The live experiment's premise is falsified; its selection ranks wallets by artifact skill and
  its gate's selection leg uses the same broken estimator.
- The droplet's REALIZED journal is, however, honest post-fill data — if left running it becomes
  a true forward measurement of this roster (expected ≈ 0 or negative net).
- Artifacts: `scratch_conv/selci_fh_post.jsonl` (4-fold hourly post), `scratch_conv/selci_fh15.jsonl`
  (June fold, 15m), `data/follow/candles15/` (191 coins 15m candles), `scratch_conv/ci_stream.py`.

---

# VERIFICATION PASS (user-requested, 2026-07-01)

Four independent checks on the collapse result — all pass:

1. **Unit tests of the pricing primitives.** `_close_post` returns exactly the containing
   candle's close with stamp strictly > t on 10k random probes (never pre-fill; None in gaps
   and past data end; boundary instants correct). `_close_at` stamp confirmed ≤ t on 10k probes
   (the artifact). `_basket_at` at close stamps returns the exact candle-index ratio (1k pairs).
2. **Independent recomputation.** 103 stored markouts sampled across all four extracts
   (15m post, hourly post, same-window hourly pre control) re-derived from raw candle parquets
   + basket with standalone code: 103/103 match to 1e-6. The streaming CI harness reproduces the
   published headline digit-for-digit as its own control.
3. **Same-window stale-vs-honest control (kills the "June had no edge" objection).** Exact
   stage-2 window/universe/fills (~63k test entries, identical n): STALE pricing manufactures
   eof +94.8 [+47,+145] at 60s/1h and +64.3 [+24,+105] at 60s/6h — SURVIVES; HONEST pricing on
   the same events: +11.6 and +5.4, everything GONE. Same data, only the pricing convention
   changed.
4. **No mechanical bias in the fix.** If post-fill pricing unfairly penalized entries (bid-ask
   bounce after taker buys), the FIELD mean would drop with the selected arm. It doesn't:
   field +6.6 → +0.7 (hourly 4-fold), −1.4 (15m). Only the SELECTED arm collapses (+45.9 → +1.1)
   — the artifact signature. Per-event, the entry price moves mean |92bp| (p50 56) between the
   stale and containing candle: that motion, mildly direction-tilted, is the manufactured edge.

Files: `scratch_conv/selci_fh15_ctl_pre.jsonl`, `selci_fh15_ctl_post.jsonl` (same-window controls).
