# Followable-edge investigation — does the copy-trade edge actually exist?

Conducted 2026-06-30, after the 20-agent adversarial audit (`audit/SUMMARY.md`). Question: at the
deployed operating point, net of realistic cost and selection luck, is there a real followable edge?
Scripts: `scripts/selci2.py` (round-trip), `scripts/selci_fh.py` (fixed-horizon + lag sweep).
All runs RAM-safe via chunked subprocesses (per-wallet files only; never the monthly parquets).

## Method
- Universe: rolling past-only `past_univ[k]` (top-1500 by cumulative PAST notional, non-major coins),
  4 transitions. Leak-free (Audit 01 confirmed; not the frozen deploy CSV).
- Selection: top-50 wallets by TRAIN-window Sortino of their neutralized edge series.
- Pricing: follower-lagged candle markouts, market-neutralized (beta 1.245), wallet-cluster bootstrap
  that RE-RUNS selection inside each draw (fixes Audit 07: CI must include selection uncertainty).

## Result 1 — round-trip scoring: NO edge (and the apparent edge was bias)
| | gross neut | P(net>0)@8bp |
|---|---|---|
| uncorrected | +48 | 0.97 |
| + Audit 11 (leading hold-out) + Audit 09 (dangling MTM) | **−30** | 0.21 |

The entire +48 was two known biases: phantom round-trips from `startPosition=0` seeding (Audit 11) and
silently dropping open-at-cutoff losers (Audit 09). Corrected → negative. Round-trip scoring shows no edge.

## Result 2 — fixed-horizon scoring: the round-trip DEFINITION was hiding signal
Scoring every position OPENING by its neutralized return over a fixed horizon (keeps never-closers,
removes the open/closed disposition asymmetry) recovers a strong, persistent edge-over-field:
- 1h horizon: edge-over-field **+71**, positive in ALL 4 folds, CI clear of zero.
- 6h: +41, 4/4 folds. 24h: dead. 72h: noisy.
Selection (Sortino) was never the problem; the round-trip definition was.

## Result 3 — lag sensitivity: real, but partly inflated by microstructure
Genuine followable alpha survives execution lag; own-flow microstructure (Audit 17 reflexivity) decays.
1h edge-over-field by lag: 60s +71 → 5m +64 → **15m +37** → 30m +21 (all 4/4 folds, CI>0).
- It DECAYS ~half by 15 min → part of the headline +71 IS own-flow we can't capture.
- But it does NOT collapse (unlike the round-trip mirage) → a real ~+20–40bp residual survives realistic lag.

## Result 4 — realistic cost: survives
Repo cost model = full spread + 9bp fees → round-trip cost median 15bp, p75 22bp, mean 19bp.
At median cost + 15-min lag: 6h net **+31 [+13,+51]** (4/4), 1h net +29 [+18,+48] (4/4).
At conservative 22bp + 15-min lag: 6h net **+24 [+6,+44]** (4/4). Only the 30-min-lag corner breaks.

## Verdict
A real, out-of-sample-persistent (4/4 folds), lag-robust, cost-surviving short-horizon selection edge
exists — best at the **6h horizon, ~15-min lag: ~+24–31bp net over field.** Not deployable on faith yet.

## Remaining gates (none likely to erase a +24bp, 4/4-fold floor)
1. **Per-coin cost attribution** — current cost is flat; if edge concentrates in p90≈29bp coins, net is lower.
   Needs coin labels in the markout extract (one more pass).
2. **Capacity/depth** — can we fill at size 15 min behind on these (thin-alt) coins?
3. **Pin actual live detection→execution latency** — decides which lag column we live in.
4. **Then: paper-forward-test on the droplet** (the live experiment is exactly for this).

## Result 5 — selection metric: trimmed-mean beats Sortino (Sortino was hurting)
Metric panel at 6h/15-min, same pool/eligibility, only the SORT KEY varies, walk-forward 4 folds
(`selci_fh.py panel`). Ranked by OOS **log-growth** (compounding objective — drawdowns penalized,
matches the gate's own statistic):
| metric | net log-growth | arith eof | folds |
|---|---|---|---|
| trimmed-mean(10%) | +32.8 | +63 | 4/4 |
| mean | +32.3 | +60 | 4/4 |
| log_growth | +29.5 | +57 | 4/4 |
| sharpe | +28.7 | +48 | 4/4 |
| median | +24.2 | +53 | 4/4 |
| **sortino (old default)** | **+15.7** | +39 | 4/4 |
| n_trades | −18 | −2 | 0/4 (sanity: activity has no edge) |
- **Central-tendency metrics (mean/trimmed/median) beat risk-adjusted (Sortino/Sharpe)** — same
  ordering replicated at 1h. Sortino's downside penalty selects low-vol over high-edge → costs ~+20bp/field.
- **Drawdown concern tested, not assumed:** arith +63 → log-growth +33 (drawdowns roughly HALVE realized
  edge — so size/forecast off +33, not +63). But trimmed-mean STILL wins under log-growth; explicitly
  drawdown-aware metrics (log_growth, calmar) do NOT beat it → past drawdowns aren't predictive enough to
  SELECT on (drawdown-aware SIZING matters, not selection). NB log-growth here assumes whole-book bets →
  overstates the drag; fractional Kelly sizing shrinks it.
- **Field compounds NEGATIVE (−16.6 bps/trade)** — the average active wallet loses money net of cost;
  selection is the whole game (+33 vs −16.6).

## Result 6 — bet size relative to wallet history: NULL (bigger bets are WORSE, not better)
`selci_fh.py sizeedge`, 2,336 wallets, edge by bet size relative to each wallet's own median:
<0.5x +8.0, 0.5-1x +7.5, 1-2x +6.5, 2-5x +4.3, >5x +3.4 (6h; same at 1h). Per-wallet Spearman(size,edge)
≈ −0.01. Edge DECLINES with bet size — likely reflexivity (big bets move price = own impact eats the edge,
which we'd also suffer copying). "Only copy big bets" would select LOWER-edge trades. Size is useless as a
selection feature. (A 34-wallet smoke showed the opposite — small-sample noise; full pop flipped it.)

## Result 7 — persistence/recency metrics: none beat trimmed-mean (don't chase recent form)
`selci_fh.py persist`, walk-forward 4 folds, vs trimmed-mean baseline (net log-growth):
trimmed +32.8 (4/4) · consistency +31.4 (4/4, ties) · recency_wt +14.5 (3/4) · recent_third +11.6 (3/4)
· trend −2.7 · rolling_pos −10.1 (0/4). **No time-aware metric beats trimmed-mean; recency/trend HURT**
→ a wallet's recent hot streak mean-reverts; informedness is a STABLE wallet property best estimated over
the FULL train window. ~17 metrics tested across 3 panels (distributional/persistence/size); trimmed-mean
wins or ties every time and is principled (robust central tendency). **Metric-selection lever is exhausted.**

## Result 8 — per-coin cost attribution: SURVIVES (edge not hiding in thin coins)
`selci_fh.py coincost`: select top-50 by trimmed-mean, then net EACH trade at its own coin's
round-trip cost (spread_bps + 9). Selected-trade cost profile p50=14.2bp mean=17.2bp (≈ universe
median, NOT concentrated in high-spread coins). Per-coin net log-growth = +31.6 vs flat-15 +32.7,
**4/4 folds positive** (1h: +49.3 vs +51.6, 4/4). The flat-cost number was honest. LAST ANALYSIS GATE CLEARED.

## STATUS: every analysis gate cleared
selection-aware CI ✅ · lag→15min ✅ · flat cost ✅ · per-coin cost ✅ · metric=trimmed-mean ✅ ·
log-growth/drawdown ✅ · size-filter ❌null · recency ❌null. Edge real, 4/4 folds, ~+30bp/trade net
log-growth. ONLY remaining step = live paper-forward-test on the droplet (genuine future OOS).
Caveats a backtest can't settle: one historical period (Feb–Jun 2026); capacity/depth at size
(can we fill 50 wallets at 15-min lag without moving thin alts — reflexivity at scale); design-level
choices made with data knowledge (walk-forward mitigates, forward-test confirms).

## Operating point to forward-test (updated)
Universe = rolling past-notional top-N; **select top-50 by train-window TRIMMED-MEAN** of 6h fixed-horizon
neutralized edge; **~15-min lag**; size for ~15–22bp round-trip cost AND off the **log-growth (+33)** not the
arithmetic edge. Do NOT filter/weight by bet size. Expectation: ~+30bp/trade net log-growth over a field
that compounds negative.
