# Audit 11 — startPosition seeding & position reconstruction  (agent: 11_startposition_reconstruction)

## Summary
I examined the leading-position hold-out across all three reconstructors: the batch
`skill.reconstruct`, the incremental `capture.CoinStepper`, and the `reconstruct_via_stepper`
equivalence harness, plus the two data sources that feed them (`split_his_fills.py`,
`fills_source.py`, `capture/ingest.py`). The hold-out *mechanism* (a position seeded with a
nonzero `startpos` gets `valid=False` / `rid==-1` and is dropped) is implemented correctly and
is bit-identical between the batch and streaming paths. **But neither production pipeline ever
feeds it a nonzero startpos**, so the hold-out is effectively dead code: the offline (his) edge
estimate seeds `startPosition=0` for every fill, and the live capture scorer constructs every
stepper at `startpos=0` and does not even carry `startPosition` on its `Fill` object. The
result is a real, sign-flippable leading round-trip that the guard was written to drop but never
does. Top severity MED (offline-estimate bias; acknowledged-but-only-partly-mitigated).

## Findings

### F1 — his-export seed-0 makes the leading-position hold-out INERT; mis-seeded/sign-flipped leading RT contaminates the mean-based offline edge  [MED]
- **Where:** `scripts/split_his_fills.py:40` (`pl.lit(0.0).alias("startPosition")`) feeding
  `src/babylon/follow/skill.py:84-87` (`pos=float(startpos[0]); valid = abs(pos) < tol`).
  Consumers: `scripts/edge_sweep.py:124-128`, `scripts/convergence_test.py:63-69`.
- **Blast radius:** offline-estimate (the headline ~+15-20 bp/RT claim). Does **not** reach the
  forward GO/NO-GO gate (which runs on live capture), so not a false-GO path.
- **Failure scenario:** The per-wallet his files set `startPosition=0` on *every* row (verified
  below). The offline scripts window the fills (`provider(w, train_lo, t1)`) and *then*
  reconstruct, so the first in-window fill is frequently a mid-position fill. Because
  `startpos[0]==0`, `reconstruct` takes `valid=True` and treats that fill as a fresh open. If the
  wallet actually held an *opposite-sign* position carried into the window, the leading RT is
  reconstructed with the **wrong direction** → `raw_bps` sign flips. If it held a *same-sign*
  position, the entry basis is truncated to only the in-window adds → wrong `entry_px`. The
  `valid=False` hold-out that exists precisely to drop this leading RT can never fire on this
  data. The contaminated RTs flow into `sel.mean()` / `net = sel.mean()-cost`
  (`edge_sweep.py:151,159`; `convergence_test.py:93`) — a **mean**, which is not robust to the
  sign-flipped outliers (median *ranking* largely is, so selection is mostly protected).
- **Why it's real (not theoretical):** empirically confirmed on
  `data/follow/fills_his/0x000007b83bf80adcc02897528403c640991a6544.parquet` (one wallet,
  streaming, ~32KB):
  - `startPosition.unique() == [0.0]` (uniformly zero, as `split_his_fills.py:40` dictates).
  - At an interior window boundary (span midpoint), the wallet carried a **true ZEC short of
    −890 contracts**, and its first post-boundary fill is a **BUY** (opposite sign). Seed-0
    reconstructs that buy as *opening a long* instead of *reducing the short* → leading-RT sign
    flip. 1 of the 2 coins with a carried position hit this.
  - The bias is bounded (~1 leading RT per (wallet,coin) per re-windowed transition), uncertain
    in sign, and is **acknowledged** in `edge_sweep.py:16-18` / `convergence_test.py` headers.
    The acknowledgment's defense ("identical bias in selected and field, so edge-over-field is
    comparable") only covers the *difference*; the reported `selected` and `net` numbers (the
    tradeability call) carry the contamination uncancelled, and the selected/field leading-RT
    noise is not guaranteed equal in magnitude/sign across a skill-biased top-N subsample.
- **Confidence:** high (data fact + code path both confirmed). What would raise the magnitude
  estimate to a number: re-running `edge_sweep` with vs without the leading RT dropped (it
  cannot be dropped without a real startPosition, so the honest fix is to drop the first
  reconstructed RT per (coin,window) as a proxy hold-out).
- **Fix sketch:** since the his export has no true startPosition, treat the first reconstructed
  position per (coin, window) as unobserved and hold it out unconditionally (drop the first
  `Close` per coin), OR re-derive a synthetic `startPosition` during the split by carrying the
  signed cumsum across the dataset and writing the real pre-fill position per row.

### F2 — live capture scorer can NEVER engage the cold-start hold-out: stepper built at startpos=0 and `Fill` carries no startPosition  [MED]
- **Where:** `src/babylon/follow/capture/ingest.py:74`
  (`st = self._steppers.setdefault(key, CoinStepper(key[1]))` — no `startpos` arg → defaults to
  0.0) and `ingest.py:27-36` (the `Fill` dataclass has **no `startPosition` field**), vs the
  hold-out logic in `capture/stepper.py:67-71` (`self.rid = -1 if self.pos != 0.0 else 0`).
- **Blast radius:** selection-power (capture feeds selection per `docs/LIVE_CAPTURE.md`), not the
  gate → HIGH at most, and bounded to a startup transient → MED.
- **Failure scenario:** The capture scorer ingests WS `userFills` and drives one `CoinStepper`
  per (wallet,coin), created lazily on first fill with `pos=0`. If capture begins observing a
  wallet that already holds a position (the normal case — wallets are followed mid-stream), the
  first observed fill is a partial close, and seed-0 reconstructs it as a fresh (possibly
  sign-flipped) open. The `valid=False`/`rid==-1` guard cannot trigger because it keys off
  `startpos != 0` at construction, and `startpos` is always 0. Worse, the `Fill` object does not
  even carry `startPosition`, so there is **no structural path** to ever seed a real one — the
  guard is unreachable in this pipeline regardless of what HL provides. The resulting leading RT
  gets an `Open` + markout scheduled + a scored `Close`.
- **Why it's real (not theoretical):** confirmed by reading the full ingest path — no
  `clearinghouseState`/REST truth-up feeds the stepper (the `clearinghouse_state` truth-up at
  `watcher.py:149` is a *different* module, the live position watcher, not the capture scorer).
  Magnitude is small: one mis-seed per (wallet,coin) at first observation (and again per coin
  after a process restart, since steppers cold-start at 0); after the first close the stepper is
  exact-zero and tracks correctly. So this is a bounded power loss, not a systematic gate bias.
- **Confidence:** high (code path fully traced).
- **Fix sketch:** add `startPosition` to `Fill`, and on first fill for a key construct
  `CoinStepper(coin, startpos=fill.startPosition)` so the existing `rid==-1` hold-out engages;
  or, if no startPosition is available at ingest, hold out the first round-trip per (wallet,coin)
  the same way F1 proposes.

### F3 — float-residual exact-zero reset and causal running-max tolerance: CLEAN  [NIT/clean]
- **Where:** `skill.py:84-119` vs `capture/stepper.py:65-127`.
- **Checked (known #15):** position close resets `pos = 0.0` **exactly** on both paths
  (`skill.py:113`, `stepper.py:117`), so a within-tolerance float residual cannot stale the next
  open's `entry_t`/`taker_open`. The flat tolerance is anchored to a **causal** running
  `maxabs` updated as `max(maxabs, abs(pos+d))` *before* the open/close branch on both paths
  (`skill.py:92-94`, `stepper.py:90-91`), with identical initialisation (`maxabs=abs(startpos)`)
  — so the batch reconstructor is bit-for-bit reproducible by the live stepper (no future-
  dependent tolerance). I could not construct a residual-staling or tol-divergence scenario.
  This guard holds.
- **Also checked:** the `valid`/hold-out *mechanism* itself is correct where exercised — the
  REST selection path (`fills_source.RestFillsProvider` → `fills_to_frame` reads the real
  `startPosition`, `fills_source.py:50`) does pass a true startpos into `_positions_for`, and
  there the leading-position drop works as intended. The defect is confined to the his-export
  and WS-capture inputs (F1/F2), not the reconstruction logic.

## What I could not rule out
- The exact bp magnitude F1 puts on the headline `selected`/`net` numbers — that needs a sweep
  re-run with a proxy hold-out, outside this RAM-bounded single-wallet probe.
- Whether the gate (`measure → decide`) ever ingests his-export RTs rather than live-capture
  RTs; I assumed the documented split (offline=his, gate=live). If the gate were ever fed the
  his offline RTs, F1 would escalate toward the gate-false-GO bucket. Worth one confirmation by
  whoever owns the gate wiring.

## Probe used (RAM-safe)
`vm_stat` checked (≈578 MB free + 2.4 GB inactive). One per-wallet file, `pl.scan_parquet(...)
.collect(engine="streaming")`, `POLARS_MAX_THREADS=2`. Never touched the monthly files.
