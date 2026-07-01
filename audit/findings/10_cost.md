# Audit 10 — Cost & netting model  (agent: 10_cost_netting)

## Summary
I examined the offline edge estimator (`scripts/edge_sweep.py`), the live cost model
(`execution/fill_model.py`, `execution/paper.py`, `follow/spread.py`, `follow/runner.py`),
the live sizer (`sizing/`), the capture scorer (`follow/capture/`), and the GO/NO-GO gate
(`follow/experiment.py`). The **gate itself is cost-robust** — it compares the difference of
two arms that both pay real per-coin cost via a depth-walking executor, so a flat-cost error
cannot fabricate a GO. But the **offline "deployable net" claim is materially inflated**: the
headline edge script nets a thin-alt, mid-to-mid universe at a flat **8 bp/RT — which is less
than the system's own taker fee alone (9 bp/RT)** and a fraction of what every other cost
surface in the repo charges (live config ~21 bp + spread; `copy_backtest` 30 bp; the per-coin
`spread.py` model 11–40+ bp). The capture scorer omits the taker fee entirely. Funding is
omitted offline on multi-day holds. Top severity: **HIGH** (offline-estimate), 4 findings + 2
clean checks.

## Findings

### F1 — Flat 8 bp round-trip cost understates real cost; below fees alone, mid-to-mid, on a thin-alt universe  [HIGH]
- **Where:** `scripts/edge_sweep.py:101` (`--cost-bps` default `8.0`), `:159` (`net = sm - args.cost_bps`),
  `:54-67` (`price()` marks mid-to-mid via candle close `_close_at`, no spread in the price).
- **Blast radius:** offline-estimate (the "+15–20 bp/RT net-relevant" tradeability claim and the
  pre-registration prior). **Not** gate-false-GO — see "Clean checks" for why the gate is immune.
- **Failure scenario:** `edge_sweep` prices each round-trip entry/exit at the **same candle-close
  mid** (`raw = dir·(eout/ein−1)·1e4`, `:63`), so the spread is *not* in the price; the flat
  `--cost-bps 8` is the *only* friction and must absorb 2 taker fees + 2 half-spreads + impact +
  funding. It cannot even cover the fees:
  - The system's own single-source taker fee is **4.5 bp/side** (`execution/fill_model.py:28`
    `TAKER_FEE = 0.00045`; `follow/spread.py:26` `TAKER_FEE_BPS = 4.5`) → **9.0 bp/RT in fees**.
    So `8 < 9`: the offline net is optimistic by ≥1 bp **before any spread/impact**.
  - The same repo's other cost surfaces all charge far more per RT:
    - Live experiment config (`follow/main.py:62`): `fee_bps=4.5, impact_bps=6.0` per leg →
      **21 bp/RT** of fee+impact, **plus** the real crossed spread (the executor walks the book,
      `execution/paper.py:100`, `fill_model.py:94-107`).
    - `follow/copy_backtest.py:73` default `cost_bps = 15.0` **per side** → **30 bp/RT**.
    - `follow/spread.py:53-62` per-coin per-side cost = `half_spread + 4.5`, ×2 for an RT:
      ~11 bp/RT on a 2 bp-spread liquid coin, **~30–40+ bp/RT on a 25–30 bp-spread alt**
      (half capped at 120 bp). The universe is explicitly **non-majors** (README §past_univ
      "top-1500 wallets"; the convergence note targets the thin-alt edge), where the spread term
      dominates and a flat 8 bp is a 3–5× understatement.
  - Consequence: README quotes "FAIR +17.4 bp/RT … **GROSS of fees**" (`other_repo_notes/README.txt:19,21`).
    The deployable net is `17.4 − real_cost`. At the system's *own* live cost (≥21 bp + spread)
    that is **negative**; even at the per-coin spread model it is ~zero on the thin-alt half. The
    flat-8 net (~+9 bp) shown by `edge_sweep` is fiction for the part of the universe where the
    edge is thinnest, so **the marginal selected wallet is likely net-negative**.
- **Why it's real (not theoretical):** a per-coin cost model already exists and is used elsewhere
  (`spread.py:per_side_cost_map`, `copy_backtest.cost_by_coin`), but the headline DEPLOYABLE-edge
  script hard-codes a single flat scalar that is *lower than the fee-only RT*. No guard reconciles
  `edge_sweep --cost-bps 8` with `TAKER_FEE`/`spread.py`/the live `fee_bps+impact_bps`.
- **Confidence:** high (the 8 < 9 fee inequality is from the repo's own constants; the per-coin
  model is in-repo). What would raise it further: the median sampled spread on the actual selected
  coins (in `spread.py` parquet output) to put a point number on the thin-alt RT cost.
- **Fix sketch:** drop the flat `--cost-bps`; subtract the **per-coin** RT cost
  `2·per_side_cost_map(spreads)[coin]` (fee + real half-spread) per round-trip *before* taking the
  selected mean, matching `spread.py`/the live executor. At minimum default the flat cost to the
  live config's `2·(fee+impact)+spread_floor` (≈21 bp + spread), never below `2·TAKER_FEE`.

### F2 — Capture scorer omits the taker fee; must-fix #3 only half-implemented (touch handles spread, fee/per-coin cost never subtracted before Sortino)  [MED]
- **Where:** `follow/capture/markout.py:121-125` (`ret_bps = d·(exit_mk/entry_mk−1)·1e4`, marks are
  the aggressing touch only — **no fee term**); `follow/capture/scorer.py:33-46` (`returns_fn`
  returns closed+MTM with **no cost subtraction**); `scorer.py:43` (MTM exit at touch, also no fee).
- **Blast radius:** selection-power (capture feeds selection only, per `docs/LIVE_CAPTURE.md`
  audit-outcome §; and it is SHADOW/not-yet-wired). HIGH *at most*, not a false-GO.
- **Failure scenario:** `docs/LIVE_CAPTURE.md` must-fix #3 (HIGH) requires "subtract per-coin
  modeled round-trip cost (executor's cost source) BEFORE Sortino; mark at the aggressing touch not
  mid." The touch-marking half is done (entry=ask/exit=bid for a long, `markout.py:121-123`), so the
  **spread** is in `ret_bps`. But the **~9 bp/RT taker fee is omitted** and `scorer.py` subtracts no
  per-coin cost before the Sortino. So every wallet's captured score is **gross-of-fee** by ~9 bp.
  Because the fee shift is ~constant, it doesn't just rescale Sortino linearly — it changes the
  downside-deviation denominator and any absolute live-eligibility/"is this wallet net-positive"
  threshold, biasing the live roster toward wallets whose true net edge is below the fee floor.
- **Why it's real:** the doc explicitly labels this must-fix as the work to do, and the
  implementation stops at the spread; there is no fee/per-coin-cost line anywhere in `scorer.py` or
  `markout.py`. The "coherent by construction" claim the task flags as FALSE is confirmed: source is
  coherent (BookCache), cost is not.
- **Confidence:** high (the fee subtraction is simply absent from the code).
- **Fix sketch:** in `scorer.py.returns_fn`, subtract `2·TAKER_FEE_BPS + 2·half_spread[coin]`
  per returned round-trip (use the live executor's cost source) before passing to Sortino; or fold a
  fee haircut into `markout.FinalRoundtrip.ret_bps`. Gate this behind the swap-in (it is shadow now).

### F3 — Funding carry omitted from the offline estimate and the capture score on multi-day holds  [MED]
- **Where:** `scripts/edge_sweep.py` (no funding term anywhere; `min_hold_ms` default 1 h, `:99`,
  **no upper hold bound** in `extract_positions` `:48`); `follow/capture/markout.py`/`scorer.py`
  (price-ratio only). Contrast: `follow/runner.py:131-143` `accrue_funding` **does** book funding on
  the live arm.
- **Blast radius:** offline-estimate + selection-power. The live gate arm is unaffected (runner
  accrues funding), so this is an *inconsistency* between the offline/selection cost and the live cost.
- **Failure scenario:** these wallets take multi-hour-to-day holds (`docs` and `runner.py:134`
  comment "material on the multi-hour/day holds these wallets take"). A long held through positive
  funding pays ~0.01%/h ≈ 0.24 bp/h ≈ ~5–6 bp/day, multiples of that on multi-day holds — comparable
  to or larger than the entire flat 8 bp cost. Market-neutralization (`_basket_ret_bps`,
  `edge_sweep.py:65`) removes index *price* drift but **not** funding carry, so the omission survives
  in both directional and neutralized modes and is systematically upward for the long-hold tail.
- **Why it's real:** funding is modeled in the live runner but in neither offline estimator nor the
  capture markout; the flat cost is hold-duration-independent so funding cannot be hiding in it.
- **Confidence:** medium-high (funding sign depends on each coin's funding regime over the hold, so
  the magnitude is wallet-dependent; direction is upward for the long-biased multi-day tail). A
  per-coin funding-rate join over the hold windows would pin the magnitude.
- **Fix sketch:** accrue `Σ signed_notional · funding_rate` over `[entry_t, exit_t]` per RT (reuse
  `runner.accrue_funding`'s convention) and subtract from `ret_bps`, offline and in capture.

### F4 — `cost_floor_bps=15` is declared "the realistic RT cost, MAR must clear it" but is never used in the gate; `mar_bps=8 < cost_floor=15` contradiction  [LOW]
- **Where:** `follow/experiment.py:65` (field doc "MAR must clear it"), `:84` (assert only checks
  `>=0`), `_rule` `:314-339` (uses `cfg.mar_bps` against `top_minus_control_ci_low`; **`cost_floor_bps`
  never referenced**). Set in `follow/main.py:64-65` `mar_bps=8.0, cost_floor_bps=15.0`.
- **Blast radius:** reporting/decision-clarity only — **not** a false-GO (the gate metric is a
  difference of two realized-cost arms; see Clean checks).
- **Failure scenario:** the config advertises a 15 bp realistic cost floor that the MAR "must clear,"
  yet (a) the gate rule never subtracts or checks it, and (b) `mar_bps=8 < cost_floor=15`, so the
  stated invariant is both unimplemented and internally contradictory. A reader trusting the field
  doc would believe the gate enforces a 15 bp net hurdle; it does not.
- **Why it's real:** grep confirms `cost_floor_bps` appears only at its definition and assignment,
  never in any return/threshold computation.
- **Confidence:** high (mechanical: the symbol is unused in logic).
- **Fix sketch:** either remove the dead param + misleading doc, or wire it: require
  `mar_bps >= cost_floor_bps` in `__post_init__` and document that the gate's difference metric is
  cost-invariant so the floor applies to the *absolute* arm report, not the difference.

## Clean checks (held up)

- **Gate is NOT vulnerable to cost understatement (no false-GO from this area).** `_rule`
  (`experiment.py:314-339`) gates on `top_minus_control_ci_low >= mar_bps` — the **difference** of
  the top roster and a control arm (`pool_mean`/random/sign-shuffle, `main.py:63`). Both arms trade
  through the same `PaperExecutor.submit_book` depth-walk that pays **real per-coin** fee+impact+
  crossed-spread (`paper.py:73-104`, `fill_model.py:88-107`), so the common cost cancels and any
  residual is the *true* cost difference of the two rosters. A flat-cost error in the offline script
  cannot leak into this. This is the blast-radius bound: F1/F3 corrupt the *offline claim*, not the GO.
- **No headline uses `edge_v_field` as deployable P&L (known issue #3 intact).** `edge_sweep`
  prints `net` and `edge_v_field` separately (`:161-163`); README labels the +17.4 bp number
  "**GROSS of fees**" (`README.txt:21`) and frames +15–20 as the gross-on-this-universe figure, not
  a net deployable. The gate quotes `top_minus_control` (a realized-net difference), not edge-over-
  field as P&L.
- **Netting double-count: not material / conservative.** `edge_sweep` charges cost once per RT and
  computes the selected return on the same per-RT basis (`net = sm - cost`, `:159`), so cost and
  return share one aggregation — no double-count. Live consensus netting (`runner._target`,
  `FixedFractionSizer`, `runner.py:145+`) crosses the spread *fewer* times than per-wallet-RT when
  wallets agree, i.e. realized cost is **lower** than the per-RT model — conservative, not inflating.
  The real gap is the *level* of the flat cost (F1), not netting direction. Confidence: medium (I did
  not trace the full consensus-rebalance turnover accounting; a count of net position changes vs
  underlying wallet-RTs would settle it).
- **Live sizer cost-consistency:** `FixedFractionSizer` (`sizing/sizer.py:52-74`) sizes by a fixed
  fraction and does not bake in an edge-net assumption, so it does not "over-lever the thin-edge tail"
  on a wrong cost — the cost lives in the executor's fill price, not the sizer. The Kelly `Sizer`
  (used for non-copy strategies) consumes returns that the engine already nets at
  `TAKER_FEE + half_spread` per side (`engine.py:560-565`), consistent with `spread.py`. No cost
  inconsistency found in `sizing/`.

## What I could not rule out
- The exact per-coin spread distribution on the *selected* coins (would convert F1's "3–5×" into a
  point bp number) — needs the `spread.py` sampled-spread parquet, not read here (STATIC; no live book).
- The sign/size of funding over the actual hold windows (F3) — needs a funding-rate join, not run.
