# Study: liq_reaction — liquidation-reaction on Hyperliquid majors

**Status:** DESIGN — **REDESIGNED after the 2026-07-07 5-agent design audit** ([`AUDIT_RESPONSE.md`](AUDIT_RESPONSE.md));
awaiting the EDA feasibility gate (go/no-go) before the primary (A1′) is frozen. **Owner:** Cory · **Lane:**
exploratory (`research/studies/`), firewalled from `gate_a/`.

> The original primary (unconditional pooled fade-mean at 15 min on `oracle_px`) was withdrawn as
> inconclusive-by-construction. The redesigned primary (A1′) is in [`PREREGISTRATION.md`](PREREGISTRATION.md);
> `ARCHITECTURE.md` below is the original design and is superseded by A1′ where they conflict.

## The question (one sentence)
After forced liquidation flow hits a major (BTC/ETH/SOL/HYPE), does price **revert (fade)** or **continue
(follow)** over minutes-to-hours, out-of-sample and net of cost — and is there a deployable signal?

## Why this first
Forced liquidation flow is **price-insensitive and mechanically labelled** in our tape (full liq struct:
`liq_user`/`liq_method`/`liq_mark_px`, `is_liq_origin`), so the overshoot→reversion story is the cleanest
forced-flow edge we can test. Direction (fade vs follow) is a genuine open empirical question. Building it
also creates the reusable **`flow-subset → signed forward-markout + full gauntlet`** harness that the TWAP,
OI-build, and builder studies re-parameterize.

## Documents
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the full design: data, the shared markout harness, the six
  sub-studies (A1–A6), measurement details, sequencing, risks.
- [`PREREGISTRATION.md`](PREREGISTRATION.md) — the **frozen** primary estimand (A1 LiqFade) + the null,
  positive-control/MDE, four-part over-null gate, walk-forward scheme, and stop rules. Locked before any
  result is looked at.
- [`FINDINGS.md`](FINDINGS.md) — the running ledger (updated at the end of each stage).

## Sub-study map (see ARCHITECTURE for detail)
| | Name | What | Status |
|---|---|---|---|
| **A1** | LiqFade | signed liq flow → forward fade-markout term structure (**the primary estimand**) | design |
| A3 | MarkGap | dose-response on `\|liq_mark_px − oracle_px\|` dislocation | design |
| A5 | RegimeSplit | condition on funding / premium / OI / hour / spread | design |
| A2 | CascadeFade | cluster detection + portfolio backtest (SOL/ETH/HYPE first; BTC = falsification) | design |
| A6 | BackstopEdge | book-liq vs HLP-backstop; is the edge already arbed? | design |

## Non-negotiables (from `../../../CLAUDE.md` and the candidate-swarm guards)
- **Never price entries off `liq_mark_px` or a liq fill's `px`** — the stale-price artifact that killed
  edge3. Entry/exit prices come from post-event **as-of `asset_ctx`** (`oracle_px`, `ctx.ts ≤ t`).
- Per-minute price is the floor → horizons are minutes+; we measure the slow executable residual.
- Only 4 majors → the **4-coin sign test** + time-pooling + **moving-block bootstrap** is the power lever.
- Report **gross AND net** (cost from `research.lib.cost` on `impact_bid/ask_px`); OOS/walk-forward only.
- A null earns the word only with point estimate + CI + positive-control MDE + cross-coin sign test.
