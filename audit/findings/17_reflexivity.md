# Audit 17 — Reflexivity / reference price  (agent: 17_reflexivity)

## Summary
I examined whether the markout reference price the wallet score is built on is independent
of our own trading flow, whether our per-coin volume share is bounded/monitored, and whether
reflexivity can reach the GO/NO-GO gate. Conclusion: **clean bill at current scale, with one
documented-threshold caveat (LOW).** In the present system reflexivity is *structurally zero*
because the executor is paper-only — we place no real orders, so the public `l2Book` the
markout reads cannot contain our fills. The audit's must-fix #6 prescriptions ("flow-independent
reference / net out our fills" and "bound + monitor per-coin volume share") are **not implemented
in source** — they exist only as prose in `docs/LIVE_CAPTURE.md:140`. That is correct to defer
now, but it is an un-tracked precondition for live scaling. Reflexivity touches **selection only**
and cannot reach the gate. Severity stays LOW; the value here is pinning the threshold and the
fact that the guard is absent, not crying wolf.

## What I checked
- `src/babylon/follow/capture/markout.py` — `BookCache`, `MarkoutScheduler.process_due`
  (markout price source and timing).
- `src/babylon/execution/paper.py`, `src/babylon/execution/fill_model.py` — whether our fills
  mutate the book or are signed to the exchange.
- `src/babylon/follow/runner.py` (`on_book`, `submit_book` call, `attach_l2_feed`, sizing caps),
  `src/babylon/follow/live.py` — feed wiring and per-coin notional bounds.
- `src/babylon/follow/capture/scorer.py`, `ingest.py` — score consumption path.
- Repo-wide grep for any volume-share / participation / market-impact / self-fill / net-out
  monitor: **none exists** (only the doc prose at `docs/LIVE_CAPTURE.md:140`).

## Findings

### F1 — No flow-independent reference and no per-coin volume-share monitor; structurally moot in paper, an un-tracked precondition for live scaling  [LOW]
- **Where:** `src/babylon/follow/capture/markout.py:121-123` (markout reads public-book
  `snap.ask`/`snap.bid`); `src/babylon/execution/paper.py:55-104` (paper executor, no real
  orders); absent guard — `docs/LIVE_CAPTURE.md:140` (must-fix #6, prose only).
- **Blast radius:** selection-power (and only when LIVE, at scale). **Cannot reach the gate.**
- **Why it's not a live defect today (the structural argument):**
  - The markout reference is the public `l2Book` WS feed. `BookCache.update`
    (`markout.py:41`) is fed *only* by that feed; the runner's separate book dict
    (`runner.py:96-98`, `on_book`) is likewise WS-fed. Neither is ever written by our fills.
  - `PaperExecutor` "simulates fills against the live book... **No signing, no real orders —
    zero financial risk**" (`paper.py:1-7`). `submit_book` (`paper.py:73-104`) reads the
    passed-in frozen `Book`, folds fee+spread+impact into the *returned fill price*, and
    **never writes back** to `BookCache` or the runner's book. The depth walk in
    `fill_model.fill` (`fill_model.py:94-110`) is read-only over a frozen snapshot.
  - Therefore our flow never reaches the exchange → the public book the markout reads is
    flow-independent **by construction** while paper. The must-fix #6 "snapshot pre-order /
    net out our fills" isolation is *not needed* in this regime, which is why its absence is
    not a current bug.
- **The real gap:** the moment the system runs **live** (real taker orders), three properties
  flip and there is no code to catch it:
  1. Our entry/exit on a coin *does* move the public mid; the markout for every watched wallet
     on that coin at any nearby `t+lag` now reads a book we perturbed → the incumbents we trade
     score higher → we select them harder → we move them more (the feedback loop in must-fix #6).
  2. There is **no per-coin volume-share tracker and no alarm anywhere** (grep confirms). The
     only related caps are fidelity guards, not impact monitors: `max_coin_frac` (default 0.08,
     `runner.py:64`) bounds a per-coin *target* as a fraction of equity, and `max_depth_frac`
     (0.25, `fill_model.py:91-92`) makes a single *paper* fill no-fill if it would consume >25%
     of visible top-20 depth. Neither accumulates our traded volume against the coin's volume,
     and `max_depth_frac` does not run against a real book.
  3. The markout uses the *wallet's* event times (`entry_t+lag`, `exit_t+lag`), so the bias is
     only the slice where our flow temporally overlaps theirs on the same coin — bounded, but
     unmonitored.
- **Severity scaling / the threshold to document (so the team knows the ceiling):**
  - Per-coin notional is hard-capped at `max_coin_frac × budget` (`runner.py:145-152`): at the
    current **$1k** budget and 0.08 that is **≤ $80/coin**, and in practice far less — the
    consensus is diffuse and `min_rebalance_usd` (live.py passes 2.0) suppresses tiny targets.
  - Reflexivity becomes *material* only when a live taker order moves the mid by an amount
    comparable to the edge being measured (~15–20 bp/RT). A taker consuming fraction `f` of
    near-touch resting depth perturbs the mid on the order of `f ×` (spread/near-touch impact),
    so to bias a ~15–20 bp markout you must move the mid several bp, i.e. sweep a *non-trivial
    %* of near-touch depth. Order-of-magnitude threshold: **per-coin live notional ≳ ~1–5% of
    that coin's near-touch resting USD depth.** On the thin non-major universe (near-touch depth
    plausibly O($10k–$50k)), that is ~$100–$2,500 *per coin*.
  - So at $1k paper we sit **1–2 orders of magnitude below** the threshold *even on the thinnest
    coin* — and exactly zero in paper because no order is placed. The exposure window opens when
    live per-coin notional climbs toward ~1% of the median universe coin's near-touch depth;
    that is the point at which the must-fix #6 monitor must exist *before* the capital does.
    (I deliberately do not assert a single dollar figure — verifying median universe near-touch
    depth would require loading book/depth data, which is out of static scope; the fraction-of-
    depth framing is the defensible statement.)
- **Why it cannot reach the gate (severity ceiling):** the GO/NO-GO gate measures **realized
  paper fills** (`measure → decide`), not markouts (`docs/LIVE_CAPTURE.md:97-101`). The capture
  markout score feeds only `RollScheduler` selection via `CaptureScorer.returns_fn`
  (`scorer.py:33-46`) — and that scorer is **SHADOW, not even wired into the live roll yet**
  (`scorer.py:10-11`). Even under live trading, if our own flow moved our own realized fill
  price, the gate would correctly record the *worse price we actually got* — that is a real cost
  honestly captured, not an inflation. An inflated *markout* can only over-rank an incumbent
  (selection power), never fabricate a GO. Confirmed: selection-only, no gate path.
- **Confidence:** high on the structural claims (paper places no orders; book is WS-fed and
  never written by fills; no volume-share monitor exists; gate reads realized fills). Medium on
  the exact dollar threshold — it depends on live universe depth I did not (and per ground rules
  must not) load; the fraction-of-near-touch-depth bound is the high-confidence form.
- **Fix sketch (defer until pre-live, but track it):** (1) add a per-coin cumulative
  volume-share monitor in the runner that compares our traded notional to a rolling coin-volume
  estimate, with a hard cap + alarm at e.g. ~1% participation; (2) when live, make the markout
  reference flow-independent — snapshot the book *before* our order is submitted, or net our own
  fills out of the reference around `t±` our trade times; (3) gate the candle→capture-score swap
  (must-fix #1–#4) on this monitor existing, since the swap is what gives the markout score teeth
  in selection.

## What I could not rule out
- The precise live-notional dollar threshold on the *median* universe coin — needs near-touch
  depth data (out of static scope). I bounded it as a fraction of near-touch depth instead.
- Behavior under a *future* live executor that does write impact back or sends real orders — no
  such code exists today; this finding is the pre-condition flag for when it does.
