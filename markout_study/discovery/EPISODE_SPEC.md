# EPISODE_SPEC — position-building episode construction

Deterministic rules. Input: per-wallet, per-coin, time-sorted fills with (ts, price, signed size, crossed-flag, liquidation-flag). Output: episode records (`DATA_SCHEMA.md`).

## Position ledger

Maintain a signed running position `q` per (wallet, coin) via the same avg-cost ledger used in prior stages. A fill with signed size `s`:

- **Increase** if `q == 0` or `sign(s) == sign(q)` (open or add).
- **Reduce** if `sign(s) != sign(q)` and `|s| < |q|`.
- **Close** if `|s| == |q|` → flat.
- **Flip** if `sign(s) != sign(q)` and `|s| > |q|` → residual opens the opposite side.

## Episode boundaries (frozen; gap = 30 min)

An **episode** is a maximal run of position-*increasing* fills in one (wallet, coin, direction) such that consecutive increasing fills are ≤ 30 min apart. The episode **opens** at the first increasing fill from flat or in a new direction. It **terminates** at the first of:

1. a same-direction increasing fill more than 30 min after the previous increasing fill (→ this fill *opens a new episode*, even if position is still open);
2. any **reduction** fill (position decreases);
3. a **flip** (→ close current episode, open a new one in the new direction at the flip fill).

- **Signal time** `t0` = ts of the episode-opening fill (first observable increase).
- **Average build price** = size-weighted avg price of all increasing fills in the episode; **build end** = ts of the last increasing fill in the episode.
- Multiple episodes per (wallet, coin) per day are allowed and counted independently.
- Simultaneous positions in different coins are independent episode streams.

## Edge cases (frozen decisions)

- **Scaling after 30 min while still open:** starts a **new** episode (does not extend the old one). Rationale: a copier reacting to a fresh signal after a gap is a separate decision.
- **Alternating add/reduce:** the first reduction terminates the current episode; a later increase opens a new one. (Sensitivity fork #8 relaxes "any reduction" to "reduction ≥ 50% of episode peak.")
- **Flip:** two episodes — the old one terminates at the flip fill's timestamp; a new opposite-direction episode opens at the same fill.
- **Maker vs taker fills:** episodes are built from position changes regardless of maker/taker (no taker-share filter). The `crossed` flag is retained per fill for a copyability sub-analysis (a purely-maker build may be harder to detect/copy) but does not gate episode construction.
- **Sub-minimum notional dust:** increasing fills below the $100 notional floor are ignored for episode opening but still update `q`.

## Exclusion flags (Stage-1 universe; computed as-of cutoff)

A wallet-level flag is set from training-only fills:

- **Liquidation-origin:** fraction of closes tagged liquidation above a frozen threshold **[PENDING AUDIT]**; or exchange liquidation flag present.
- **TWAP/system flow:** near-uniform inter-fill spacing + near-constant clip size (coefficient of variation below a frozen threshold) across many fills — a mechanical scheduler signature.
- **Wash:** offsetting same-wallet fills with no net exposure change beyond a tolerance, or self-cross patterns.
- **Bot / mechanical slicer:** extreme fill frequency with sub-second regularity and uniform clip sizes; distinct from TWAP by cadence.
- Thresholds for each flag are frozen from a training-window distribution audit and listed in the freeze addendum; they are not tuned on evaluation data.

## Markout definitions

For horizon `h`, with `bar(t)` = close of the first 5-min bar with ts ≥ `t`:

- **First-entry gross markout** (information score input): `dir × (bar(t0 + h) / bar(t0) − 1) × 1e4` bp. Entry pricepoint `bar(t0)` is post-signal, next-bar (no look-ahead into the signal bar).
- **Copyability markout** (copyability score input): entry pricepoint `bar(t0 + latency)`; same forward endpoint; minus per-episode round-trip cost. Latency primary 60 s.
- **Average-build descriptive markout:** `dir × (bar(build_end + h) / avg_build_price − 1) × 1e4` — reported for description only; not used for copy selection (a copier cannot obtain the average build price in real time).

All markouts are forward-only from a post-signal pricepoint; no endpoint lies inside its own signal bar.
