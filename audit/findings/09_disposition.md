# Audit 09 — Disposition / MTM-at-cutoff / dangling positions  (agent: 09_disposition_mtm)

## Summary
I examined whether the MTM-at-cutoff fix truly removes the open-position censoring bias
(prior audit: +15 to +122 bp). The MTM correction is implemented **only in the shadow
`CaptureScorer`** (not wired; selection-only), so every finding here is **selection-power**,
not gate-false-GO — the GO/NO-GO gate measures realized forward P&L (`Results` =
"realized fill prices only", `experiment.py:255`), so a mis-selected roster biases toward
INCONCLUSIVE, never a fabricated edge. Within that bound the fix is **incompletely applied**:
(F1) the capture eligibility/discovery gate still counts CLOSED round-trips — the exact
anti-pattern commit fe44463 removed from the offline path; (F2) the cutoff MTM is itself
censored by book-staleness at T0, silently dropping the quiet/illiquid open losers it was
built to capture; (F3) the capture scorer scores a different population (no taker/conviction/
min-hold filter) than the offline path on which the +15–122 bp number was measured. The MTM
price source itself (H3) is clean.

## Findings

### F1 — Capture eligibility/discovery gates on CLOSED-round-trip COUNT, reintroducing the disposition bias fe44463 removed  [HIGH]
- **Where:** `src/babylon/follow/capture/scorer.py:52-54` (`active_candidates`) →
  `src/babylon/follow/capture/store.py:65-71` (`active_wallets`: `COUNT(*) ... GROUP BY
  wallet HAVING COUNT(*)>=min_n` over the roundtrips table, which holds only CLOSED+marked
  RTs). `CaptureScorer` exposes **no `activity_fn`**, so if it replaces `SelectionAdapter`,
  `select_roster` also falls into the closed-count `else` branch (`scheduler.py:73-75`).
- **Blast radius:** selection-power (capture is SHADOW, scorer.py:11; would be HIGH when wired).
- **Failure scenario:** Commit fe44463 changed the *offline* gate from closed-RT count to RAW
  FILL count precisely because "the closed-count gate re-introduces disposition correlation
  (it selects high-turnover wallets and shrinks the pool)" (`selection.py:65-67`,
  `scheduler.py:62-67`). The capture path was **not** given the same fix: a disposition-prone
  wallet that promptly closes its winners but sits on its losers accumulates ≥ `min_positions`
  (=20, `main.py:60`) CLOSED winning RTs and so passes `active_wallets` easily — while the open
  losers contribute nothing to the eligibility count. The MTM in `returns_fn` is supposed to be
  the sole counterweight, but it only adjusts the SCORE, not the ELIGIBILITY/DISCOVERY set, and
  it leaks (see F2). So the population the capture path discovers is biased toward exactly the
  disposition-prone, high-turnover-on-winners wallets fe44463 set out to stop selecting.
- **Why it's real:** `active_wallets` SQL counts only rows in `roundtrips`, and rows are only
  written on `process_due` finalization of a CLOSED RT (`markout.py:124-129`,
  `store.flush`). Open positions are never counted. There is no raw-fill-activity path in the
  capture subsystem at all — `FillIngest` keeps only a live buffer (`store.py:6`), so a
  raw-activity gate would need a separate counter that does not exist.
- **Confidence:** high (the offline fix exists and is documented as disposition-motivated; the
  capture discovery gate is the un-fixed mirror).
- **Fix sketch:** Gate capture discovery on a disposition-free pre-T0 raw-fill-activity count
  (mirror `SelectionAdapter.activity_fn`), not on `COUNT(*)` of closed roundtrips; supply it as
  `activity_by_wallet` to `select_roster` so the closed-count fallback is never taken.

### F2 — MTM-at-cutoff is censored by book staleness at T0 → quiet/illiquid open losers silently dropped  [MED→HIGH]
- **Where:** `src/babylon/follow/capture/scorer.py:38-44` (`snap = self._book.snap(coin,
  t0_ms, self._staleness); if snap is None ... continue`) and `markout.py:44-48`
  (`snap` returns None if no book, crossed, or `now - b.ts > staleness_ms`).
- **Blast radius:** selection-power (shadow).
- **Failure scenario:** The fix's whole premise (scorer.py:7-8, `open_marked` docstring
  markout.py:147-153) is that it MTMs **every** still-open position so disposition-prone open
  losers enter the score. But the mark requires a FRESH top-of-book for that coin **at the
  arbitrary cutoff instant T0** (within `staleness_ms`, default 30 s). The open losers a
  disposition wallet sits on are disproportionately in coins that have moved against it and gone
  quiet/illiquid — exactly the coins whose L2 book is most likely stale (or absent, if that coin
  isn't in the subscribed `BookCache` set) at a random T0. Each such position hits the
  `continue` and is dropped from the MTM, restoring the closed-only inflation for precisely the
  subpopulation the fix targets. Note the asymmetry with closed RTs: a closed RT's staleness is
  evaluated at the wallet's OWN exit instant (`exit_t+lag`, when that coin was by definition
  trading); an open position's staleness is evaluated at T0, an instant unrelated to its
  activity — so opens face a systematically harsher, activity-uncorrelated freshness test.
- **Why it's real:** the drop is silent (`continue`, no counter, unlike `process_due` which at
  least pops the key). There is no fixed-horizon-markout fallback (LIVE_CAPTURE.md must-fix #2
  offered "mark at entry+H regardless of the wallet's exit" as the alternative — not
  implemented), so a stale book at T0 has no recovery path.
- **Confidence:** medium — direction (stuck losers ↔ stale books) is a strong prior but
  unquantified here (STATIC). Would be settled by, per roll, logging the count and ret-sign of
  open positions dropped for `snap is None` vs marked; if dropped opens skew negative, the bias
  is confirmed and sized.
- **Fix sketch:** count dropped-stale opens; for a stuck open with no fresh book, fall back to a
  fixed-horizon markout from the durable mid log (must-fix #2 / engineering must-fix on the
  sampled-mid log), or carry the last valid mark — never silently omit.

### F3 — Capture scorer scores a DIFFERENT population than the +15–122 bp measurement / the offline gated path (no taker/conviction/min-hold filter)  [MED]
- **Where:** closed leg `store.returns` (`store.py:56-63`) = `SELECT ret_bps ... WHERE wallet,
  exit_t` with **no** taker/conviction/hold filter; open leg `open_marked`
  (`markout.py:147-158`) = all opens, no filter; `ingest.py:78-83` routes every Open/Close
  unfiltered. Contrast the offline gated path `followable_returns`
  (`followable.py:108-114`): filters `taker_only=True`, `conviction_only=True`,
  `min_hold_ms=3_600_000` (`main.py:60`).
- **Blast radius:** selection-power (shadow) + offline-vs-live estimator asymmetry (H2).
- **Failure scenario:** The +15 bp (long-hold) … +122 bp (warm-up) disposition magnitude was
  measured on the **taker-opened, conviction, ≥1 h** subset (the deployed `followable` filters).
  The capture scorer scores ALL round-trips — maker-opened, TWAP/liquidation (non-conviction),
  and sub-1 h scalps included. So the MTM correction is being applied to, and the wallet is
  ranked on, a population whose disposition profile is not the one the fix was calibrated/
  justified against (scorer.py docstring quotes the +122 bp figure as if the populations match).
  The store/scorer flags `taker_open`/`conviction` exist (`store.py:29`, `markout.py:74-75`) but
  are never used to filter — the columns are dead. This makes the live ranking a different
  estimator from the OOS-validated offline ranking it is meant to drop in for (H2): the offline
  candle path was validated; the capture series was not, and it is not even the same statistic.
- **Why it's real:** the filter is structurally absent on both legs; conviction/taker are stored
  but never read in any scoring query.
- **Confidence:** high (structural — the filter clauses simply do not exist in the capture path).
- **Fix sketch:** apply the same taker/conviction/min-hold predicates in `store.returns`,
  `open_marked`, and the cutoff MTM that `followable_returns` applies, so capture scores the
  identical followable subset the offline measure validated.

### F4 — `min_positions` floor does NOT keep us out of the +122 bp warm-up regime  [MED]
- **Where:** `scorer.py:52-54` / `store.active_wallets` floor = closed-RT count ≥ 20
  (`main.py:60`); `select_roster` Sortino floor = ≥ 2 returns (`scheduler.py:72`).
- **Blast radius:** selection-power (shadow).
- **Failure scenario:** H4 asks whether the eligibility floor excludes the regime where
  open-censoring dominates. It does not: the +122 bp blow-up came from "6 closed + many open."
  A disposition-prone wallet that closes winners fast trivially reaches 20 closed (winning) RTs
  while holding an unbounded book of open losers — it clears the floor and ranks high on the
  closed leg. Nothing in the floor scales with the open/closed ratio. The MTM is the only thing
  standing between this wallet and a top rank, and it is leaky (F2) and applied to the wrong
  population (F3) and not reflected in the discovery gate (F1). So at warm-up — the moment we'd
  first trust a fresh wallet — a high open:closed ratio wallet can still rank top.
- **Confidence:** medium (mechanism is clear; realized magnitude depends on F2's stale-drop rate
  and the wallet's actual open-loser book, neither quantifiable STATIC).
- **Fix sketch:** raise the live floor well above 6 (LIVE_CAPTURE must-fix #4 says "≫6"), and/or
  gate on an open:closed ratio cap so a wallet whose score rests mostly on un-markable opens is
  shrunk/excluded; combine with F1's raw-activity gate.

### F5 — MTM price source is consistent with normal exits (no favorable-source bias)  [CLEAN]
- **Where:** `scorer.py:42` (`exit_mk = snap.bid if d > 0 else snap.ask`) vs `markout.py:121-122`
  (entry aggresses `ask`/`bid`; normal exit `bid`/`ask`).
- **Finding:** H3 holds up. The cutoff mark comes from the SAME `BookCache` as a normal exit,
  at the SAME aggressing touch (a long marks the exit at the bid, a short at the ask), and
  `entry_mk` is the live aggressing OPEN touch — so the full round-trip spread cost is baked in
  identically to a closed RT (`markout.py:125` formula == `scorer.py:43` formula). No stale-but-
  favorable source, no mid-vs-touch mismatch. The only price-side caveat is the *staleness
  window* timing (F2), not the price source. Clean.

## What I could not rule out (STATIC limits)
- The actual sign/size of F2's dropped-open population (needs a per-roll instrumented run; not
  runnable here per resource rules).
- Whether the `BookCache` subscription set covers all coins candidate wallets hold opens in —
  if it is a subset, F2's censoring is larger (opens in unsubscribed coins → `snap is None`
  always). The subscription wiring lives in the capture service (not in scope files); flagged.

## Blast-radius note (gate)
The *deployed/gated* returns_fn is `followable_returns`, which is **also closed-only** (it never
emits an open position; `reconstruct`/`_positions_for` append only on close, `skill.py:108-120`).
So the disposition bias is present in the gated SELECTION too — but the gate's edge number
(`top_minus_control`, `experiment.py:258-264`) is computed from realized forward fills, so
disposition mis-selection lowers the top arm's realized return → biases toward NO_GO/
INCONCLUSIVE, **not a false GO**. I found no path by which the closed-only disposition bias
inflates the gate's realized top−control. The capture findings above are all power-losses unless/
until capture is wired into the gate (it is not).
