# EPISODE_SPEC — position-building episode construction (normative, frozen)

Deterministic rules. Input: per-wallet, per-coin, time-sorted fills `(fill_ts, price, signed size, crossed-flag, liquidation-flag)`. Output: episode records (`DATA_SCHEMA.md`). Markout prices come from 5-min bar **closes**, never from fill prices. **Gate A is a gross post-entry markout study — it contains no latency, spread, slippage, or execution modelling** (those belong only to Gate B, `DEPLOYMENT_INPUT_FREEZE.md`).

## Naming (do not overload one symbol)
- `fill_ts` — timestamp of a fill.
- `entry_price_ts` — the 5-min close used as the entry price (below).
- `endpoint_price_ts` — the horizon endpoint close.
- `simulated_fill_ts` — Gate-B only (measured detection/submission); absent from Gate A.

## Position ledger
Signed running position `q` per (wallet, coin), avg-cost ledger. `startpos` reconstructed from **all** fills before the window (D1); any wallet whose reconstructed position is left-censored (first observed action is a from-flat reduction/flip, or reconstructed `q` implies pre-window inventory) is **quarantined** until reconciled. A fill with signed size `s`: **Increase** if `q==0` or `sign(s)==sign(q)`; **Reduce** if `sign(s)!=sign(q)` and `|s|<|q|`; **Close** if `|s|==|q|`; **Flip** if `sign(s)!=sign(q)` and `|s|>|q|`.

## Entry-price convention (item 2 — frozen; 0–5 min bar-resolution lag, NOT copy latency)
5-min close timestamps lie on the UTC close lattice (multiples of 5 min). For a fill at `fill_ts = f`:

  entry_price_ts(f) = min { c : c a 5-min close timestamp, **c > f** }        (first close strictly after the fill)
  endpoint_price_ts(f,h) = entry_price_ts(f) + h
  m(e,h) = d_e · ( P(endpoint_price_ts) / P(entry_price_ts) − 1 ) · 1e4   [bp]

This is a fixed **0–5 minute** bar-resolution lag; it is never labelled or interpreted as execution/copy latency. **Boundary convention:** fill 1 ms **before** a close → use **that** close; fill **exactly at** a close → use the **next** close; fill 1 ms **after** a close → use the next close.

**Purge time** for a training score = `endpoint_price_ts < C` (SPEC §1 / Leakage).

**Frozen assertions:** (a) determine whether stored candle timestamps are bar-open or bar-close and **convert to this close-time convention before scoring**; (b) synthesized fills at exactly a close, at `−1 ms`, and at `+1 ms` must map to the entry closes above; (c) `entry_price_ts` never uses a close at or before `f`.

## Episode boundaries (frozen; gap = 30 min)
An **episode** is a maximal run of position-*increasing* fills in one (wallet, coin, direction), consecutive increases ≤ 30 min apart. **`fill_ts` of the opening increase** is the episode's signal timestamp; its `entry_price_ts` is derived above. It **terminates** at the first of: (1) a same-direction increase >30 min after the previous increase (opens a new episode); (2) any **qualifying reduction** (§Dust); (3) a **flip** (§Flip). Markouts are measured over fixed horizons from `entry_price_ts` regardless of the wallet's own exit.

## Dust (item 5 — frozen)
`$100` notional floor; frozen **reduction dust floor** = `max($100, 10% of episode peak notional)`.
- **Increasing** fills `<$100`: do **not** open/extend an episode, but **do** update `q`.
- If `q≠0` only from accumulated dust and no episode is open, the **next qualifying (≥$100) increase OPENS** an episode (direction = sign of that fill; **initial size = the qualifying fill only**; dust excluded from build price).
- **Reductions** below the reduction dust floor do **not** terminate; at/above it, terminate per rule 2.
- Repeated dust increases that cumulatively cross `$100`: **no** episode opens (only a single ≥$100 increase opens one); cumulative-dust-opens is a sensitivity.
- **Frozen tests:** dust-open→qualifying add; qualifying-open→dust reduction; dust-open→qualifying flip; repeated dust crossing threshold.

## Flip (item 6 — frozen)
Closing leg terminates the old episode at the flip `fill_ts` (not itself an episode). Opening leg creates a new episode from the **residual quantity only** (`|s|−|q|`); its `entry_price_ts` derives from the flip `fill_ts`; build price accrues from the residual onward. Old and new share the flip timestamp; the old episode keeps its own earlier markouts; overlap resolved by §Deduplication.

## Deduplication clock (item 13 — frozen)
Interval `[ entry_price_ts(e), entry_price_ts(e) + 8h ]`. Per (wallet, coin) stream:
1. sort episodes by `entry_price_ts` ascending;
2. **retain the earliest**; **suppress** any later episode whose `entry_price_ts` is **strictly earlier than** the retained episode's 8 h endpoint;
3. an episode **exactly at** the prior endpoint is **retained**; when the window closes, the next surviving episode becomes the anchor.
Overlap is same wallet AND coin; opposite directions are suppressed within the window (direction-aware = sensitivity); earliest wins; suppressed episodes are never revived. The **same deduplicated set feeds eligibility counts, the training score, the evaluation outcome, and the positive controls.**

## Exclusion flags (as-of cutoff; validated by labelled flow only — change 7)
**Do not exclude a wallet merely for being automated or a "bot" — automated trading may still contain information.** Primary exclusions target only: **liquidation / system flow**, **protocol TWAP / system execution**, **wash / self-crossing** (own net-exposure/self-cross detector), and **unreconciled ledger behaviour**. **Clearly mechanical slicing** (child fills that do not represent separate decisions) is handled by **aggregating the child fills into one episode** (via the 30-min/dedup construction), **not** by excluding the wallet; a wallet is excluded for slicing only when the slicing is unambiguous *and* leaves no discretionary decision. If slicer detection is uncertain, **aggregate, don't exclude.** Thresholds from a labelled set at **≥0.90 precision** (recall reported); if 0.90 is unreachable the flag family is disabled / sent to manual review, never run at lower precision. **No wallet-return relationship influences exclusion thresholds.**

## Markout definitions
- **First-entry gross markout** — as in §Entry-price convention; the sole Gate-A input (`SCORE_AND_OUTCOME_SPEC.md`).
- Copyability / average-build markouts are **Gate-B / descriptive only and sealed**; absent from Gate A.

All markouts are forward-only from a post-fill bar close; no endpoint lies inside its own signal bar.
