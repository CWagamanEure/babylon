# Issue 09 — The stale hourly-candle pricing artifact (a fake +24–31bp edge, caught & killed)

**Topic:** Issues & Solutions, Part A — the single biggest measurement trap in the whole
arc. A pricing bug in the historical measurement layer manufactured an apparent, robust,
cost-surviving copy edge that passed every analysis gate and was *deployed live* — then a
round-3 adversarial audit isolated the bug and a decisive re-measurement killed the edge.
This is the flagship "what we caught" story.

**Primary sources (verbatim numbers pulled from these):**
- memory `babylon-edge-investigation.md` (2026-06-30 — the build that produced the claim)
- memory `babylon-edge3-audit.md` (2026-07-01 — the round-3 kill)
- `audit/EDGE_INVESTIGATION.md` (the writeup behind the claim)
- `audit/edge3/SUMMARY.md` + `audit/edge3/FINDINGS.md` (the audit; finding **F2** is the bug)
- `markout_study/docs/FINDINGS_LEDGER.md:639-642` (registers it as the "third independent fall")

---

## FACTS — the arc in three acts

### Act 0 — why fixed-horizon markout was adopted (the round-trip decision)
Before the edge was ever claimed, a scoring-definition change was made that later proved
*load-bearing for the bug*.

- **Round-trip scoring showed NO edge — and the apparent one was pure bias.** Uncorrected
  round-trip neutralized edge looked like **+48bp** (P(net>0)=0.97). The entire +48 was two
  known biases: (i) *phantom round-trips* from `startPosition=0` seeding (Audit-11), and
  (ii) silently *dropping open-at-cutoff losers* (Audit-09, disposition asymmetry).
  Corrected → **−30bp, P(net>0)=0.21**. No edge.
  (`audit/EDGE_INVESTIGATION.md:15-22`; memory edge-investigation "The arc".)
- **Fixed-horizon scoring was adopted to remove those biases:** score *every position
  OPENING* by its neutralized return over a fixed horizon H. This keeps never-closers (~1.3%
  of events) and removes the open/closed disposition asymmetry — a genuinely better estimand.
  Under it, edge-over-field *returned*: **1h eof +71bp, positive in all 4 folds, CI clear of
  zero.** Conclusion at the time: "the round-trip DEFINITION was hiding signal; Sortino
  selection was never the problem." (`audit/EDGE_INVESTIGATION.md:24-29`.)
- **The trap:** the fixed-horizon estimator (`_close_at` on hourly candles) is *exactly* the
  code path the stale-pricing bug lived in. Fixing the round-trip biases uncovered a *second*,
  independent bug that pointed the other way (inflating, not nulling).

### Act 1 — the apparent edge (what was claimed and deployed)
Headline claim, fully gated and pushed to a live paper run on the droplet (2026-07-01):

> **A real, OOS-persistent, lag-robust, cost-surviving short-horizon selection edge:
> +24 to +31bp net over field at 6h horizon / 15-min lag, positive in 4/4 walk-forward
> folds, lower CI > 0 even at a conservative 22bp cost.**

Supporting numbers that made it look bullet-proof:
- **Lag-decay curve (the "signature"):** 1h edge-over-field by entry lag —
  **60s +71 → 5m +64 → 15m +37 → 30m +21**, all 4/4 folds, CI>0.
  Read at the time as: "decays ~half by 15min (own-flow/reflexivity we can't capture) but does
  NOT collapse → a real residual survives realistic lag." (`audit/EDGE_INVESTIGATION.md:33-35`.)
- **Cost survival:** repo cost model = full spread + 9bp fees → round-trip cost median 15bp,
  p75 22bp. At median cost + 15-min lag: **6h net +31 [+13,+51] (4/4)**, 1h net +29 [+18,+48].
- Deployed cell **L900_H6** (900s=15-min lag, 6h horizon): eof **+39.3 [+19.6, +58.1]**,
  survives 4/4.
- Passed every downstream gate: per-coin cost attribution (+31.6 vs flat +32.7, not a thin-alt
  mirage), metric selection (trimmed-mean), log-growth/drawdown, size-filter & recency both null.
  Memory edge-investigation "STATUS: every analysis gate cleared."

### Act 2 — why it was WRONG (audit finding F2, the stale-pricing bug)
Round-3 65-agent adversarial swarm (2026-07-01), `audit/edge3/`. 18/18 verified findings
confirmed; **F2 is the fatal one.**

**The bug:** entry markout was priced with `_close_at` on **HOURLY candles**, which returns
the **last fully-closed hourly candle** — on average **15–30 minutes BEFORE the leader's
actual fill.** So each "entry" was booked at a price that predates the signal. The follower
was therefore credited with:
1. the **pre-fill run-up** (the move that happened *before* the leader even traded), plus
2. the **leader's own market impact** (the move the leader's fill caused).

Both are *unharvestable* by a real follower who can only trade *after* observing the fill.

**The smoking gun:** the celebrated lag-decay curve **71→64→37→21 is exactly what stale
pricing predicts** — as you demand a larger nominal lag, more of the free pre-fill window is
priced away, so the fake edge shrinks monotonically. What looked like "real alpha that decays
but survives" was the artifact bleeding out. (`audit/edge3/SUMMARY.md:14-19`, FINDINGS F2.)

Compounding audit findings (why "net over field" was never even honest): F11 — "+24–31bp NET
over field" was *never actually measured*; eof was only ever computed gross. F3/F7 —
trimmed-mean was a winner-cursed argmax over ~17 metrics on the same 4 folds, CI quoted under
Sortino, ≥40 grid looks with no multiplicity correction (corrected lower bound ~−5bp).

### Act 3 — the fix and the corrected outcome (edge is DEAD)
**The fix:** `scripts/selci_fh.py` gained `--pricing post` — **strictly post-fill pricing:**
price = close of the candle *containing* t, stamped in the half-open interval (t, t+iv]; the
beta (neutralization) leg aligned to the same stamps; `--candle-ms` makes it interval-aware so
finer candles can be used. (`audit/edge3/SUMMARY.md:80-84`.)

**Control (proves the harness reproduces the claim):** with the OLD stale pricing, the code
reproduces the published numbers *digit-for-digit* — L900_H6 eof **+39.3 [+19.6,+58.1]** 4/4,
lag curve 71/64/37/21. So the only thing that changed downstream is the pricing timestamp.

**Corrected results:**

| Test | Cell | STALE (published) | HONEST post-fill | Source |
|---|---|---|---|---|
| Same 4 folds, ~1.07M openings, hourly | L900_H6 (6h/15m) | **+39.3 [+19.6,+58.1]** 4/4 | **+0.4 [−14.4, +18.5]** | edge3 SUMMARY:86-88 |
| Same 4 folds, hourly | L60_H1 (1h/60s) | **+70.9** | **+3.9** | edge3 SUMMARY:88 |
| Fine-grained, 15m candles, single June fold | 6h @ all lags | (n/a) | **NEGATIVE everywhere; deployed cell −25.2 [−49.2,+24.7]; even 60s lag −14.5** | edge3 SUMMARY:91-93 |

- On hourly post-fill pricing, **every one of the 8 surviving cells is GONE.** The deployed 6h
  cell collapses from +39.3 to **+0.4**, CI now straddling zero.
- On 15m candles (June, `k=3` past-only universe), the 6h horizon is **negative at every lag**
  — there is **no first-30-minute alpha** for a fast follower (even the 60s column is −14.5).
- **Same-window stale-vs-honest control** (kills any "June just had no edge" objection —
  identical ~63k test entries, same window/universe/fills): STALE pricing manufactures eof
  **+94.8 [+47,+145]** at 60s/1h and **+64.3 [+24,+105]** at 60s/6h (survives); HONEST pricing
  on the *identical* data collapses it. The **field** barely moves (+6.6 → +0.7 hourly, −1.4
  on 15m) while only the **SELECTED** arm collapses (+45.9 → +1.1) — the artifact signature.
  Per-event, the entry price moves a mean **|92bp| (p50 56bp)** between the stale candle and
  the containing candle, and that mildly direction-tilted motion IS the manufactured edge.
  (`audit/edge3/SUMMARY.md:124-133`.)

**Verdict (registered):** *"The +24–31bp deployed edge was entirely the hourly-candle
stale-pricing artifact — pre-fill run-up + leader impact credited to the follower. Honest
post-fill measurement: ~0 gross at 6h across 4 folds, negative at 6h on fine-grained June
data, nothing that survives cost anywhere."* The live experiment premise was falsified: the
roster was ranked by artifact skill and the gate's selection leg used the same broken
estimator. (`audit/edge3/SUMMARY.md:96-106`; ledger line 641 logs it as the "third independent
fall of this premise.")

---

## The one-paragraph "what we caught" story (report-ready)
A copy-trade edge measured at **+24–31bp net over field, 4/4 folds, surviving 22bp cost** was
built, passed every rigor gate we had, and was deployed to a live paper run. A round-3
adversarial audit then found that entry prices were being read from the last *closed hourly
candle* — 15–30 minutes *before* the leader's actual fill — so the strategy was booking the
pre-fill run-up and the leader's own market impact as if a follower could capture them. The
tell was hiding in plain sight: the "edge decays with lag but survives" curve (71→64→37→21) is
the exact fingerprint of pricing away a free look-ahead window. Re-pricing strictly *post-fill*
(close of the candle *containing* the fill) collapsed the deployed cell from **+39.3 to +0.4**,
and finer 15-minute candles turned it **negative**. The field arm was unmoved; only the
selected arm evaporated. The edge was an artifact.

---

## FIGURES-TO-MAKE
All numbers below already exist in the ledger/audit sources — no tape scan or bar-pricing
needed to draw them.

1. **Before-vs-after edge bar (the headline figure).** Grouped bars for the deployed cell
   **L900_H6 (6h/15-min)** and **L60_H1 (1h/60s)**: STALE (+39.3 / +70.9) vs HONEST post-fill
   (+0.4 / +3.9), with the +0.4 CI [−14.4,+18.5] drawn crossing zero. One glance = "the edge
   was the bug." *(All four numbers: edge3 SUMMARY:86-88.)*

2. **The lag-decay "artifact signature" line.** Plot the 1h eof lag curve 60s +71 → 5m +64 →
   15m +37 → 30m +21 and annotate it as "monotonic decay = free look-ahead window being priced
   away," i.e. the fingerprint, not alpha. *(edge-investigation:33; SUMMARY:17.)*

3. **Selected-vs-field collapse (same-window control).** Two mini before/after bars: FIELD
   arm +6.6 → +0.7 (barely moves) vs SELECTED arm +45.9 → +1.1 (collapses). Caption: "the fix
   only touches the selected arm — the artifact signature." *(SUMMARY:129-131.)*

4. **Round-trip → fixed-horizon → post-fill timeline.** A 3-step schematic of the estimand
   journey: round-trip +48 (=bias, corrected −30) → fixed-horizon +71 (recovered, deployed) →
   post-fill +0.4 (artifact killed). Shows two *different* bugs pointing in *opposite*
   directions. *(EDGE_INVESTIGATION:15-29; SUMMARY:86-88.)*

Optional: a "stale vs containing candle" schematic — a timeline with leader fill at t, the
stale close 15–30min earlier, the shaded pre-fill run-up + impact region = the fake edge; note
the mean |92bp| per-event price move between the two stamps. *(SUMMARY:132-133.)*

---

## GAPS / caveats for the writer
- **The corrected numbers are two-tier in confidence.** The hourly post-fill re-run is on the
  *full* 4 folds / 1.07M openings (strong: eof +0.4). The *negative* 6h result is from **15m
  candles on a single June fold only** — HL's `candleSnapshot` API serves only the last ~5000
  candles/interval (≈ May 10 onward), so fine-grained data can't reach the earlier folds. The
  robust claim is "collapses to ~0"; "goes negative" rests on one fold. Do not over-state the
  negative as multi-fold.
- **"~0 to +15bp" alternate phrasing exists.** `audit/edge3/SUMMARY.md:33-34` states the honest
  posterior as "~0 to +15bp, not clearly positive after correction — and possibly negative once
  entry pricing is fixed." That was the audit's *pre-re-measurement* estimate; the *actual*
  re-measurement (SUMMARY:86-99) then landed at +0.4 / negative. Quote the measured +0.4, and
  cite the ~0–15bp only as the audit's prior expectation, not the result.
- **This bug is narrowly a MEASUREMENT bug, not a strategy-logic bug.** The execution engine
  (ledger/expiry/sizing) was separately audited and found sound; the fault was purely in the
  historical price lookup used for backtest + gate. Worth stating so the reader doesn't
  over-generalize to "the whole system was broken."
- **Over-null guard (per CLAUDE.md):** the honest verdict is a *powered method-scoped negative*,
  not "inconclusive" — MDE is well inside the care-about band (the stale control shows the
  pipeline recovers +94.8 when an effect is present; the honest run shows +0.4 with a CI that
  excludes the deployed +30). The pipeline is demonstrably *able* to see the edge if it existed.
  That is what earns the word "artifact/dead" here rather than "underpowered."
- **Artifacts on disk** (for anyone rebuilding a figure): `scratch_conv/selci_fh_post.jsonl`
  (4-fold hourly post), `scratch_conv/selci_fh15.jsonl` (15m), `scratch_conv/selci_fh15_ctl_pre.jsonl`
  + `selci_fh15_ctl_post.jsonl` (same-window controls), `scratch_conv/ci_stream.py` (CI
  reproduction). These live in the babylon repo root, not under `markout_study/`.
