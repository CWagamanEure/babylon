# Study: liq_fuel_map — liquidation-fuel state estimation

**Status:** REGISTERED-NULL (fade/overshoot-revert thesis) — **engine NOT built.** The audit's upper-bound
gate (`upper_bound.py`, `FINDINGS.md`) returned a **powered negative**: with perfect cascade timing, majors
*continue* (−15 to −35 bp), they don't revert; a +35–65 bp magnet pre-drift shows the crowd already
front-runs the public on-chain liq map. Fade = wrong sign; follow = crowded/already-priced. Do not build the
M1–M4 engine. (Prior design audit: all 5 REVISE; the "private map" moat was falsified — it's a shipped
on-chain product.)
**Owner / date:** Cory · 2026-07-07 · **Lane:** exploratory (`research/studies/`), firewalled from `gate_a/`.

## The question (one sentence)
Can we reconstruct the market's hidden **liquidation-fuel map** on majors — where forced liquidation flow
will trigger — forecast the **probability of reaching** each zone with a realized-variance model, and trade
the anticipated forced flow (directional pressure / overshoot-revert) out-of-sample, net of stressed cost?

## Why this (the edge premise)
The price/basis/funding layer is arbed on majors (`../basis/FINDINGS.md`). The one state **only we** can
estimate is *positioning*: `start_position` on every fill rebuilds every wallet's running position (verified
100%-exact, `FINDINGS.md`), hence the fuel map. It's private and not published; the vol forecast it needs is
standard. The bet leans on forecasting **volatility** (forecastable), never **price direction**
(unforecastable). Redeems the shelved `../liq_reaction/` study by *anticipating* forced flow rather than
reacting after it prints.

## Documents
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the full two-layer design (fuel-map engine + vol/hitting brain),
  the empirical liq-price model, the two-stage validation (mechanism vs edge), gates, compute plan, and the
  open questions for the audit swarm. **Read this first.**
- [`FINDINGS.md`](FINDINGS.md) — running ledger; feasibility results (reconstruction 100%; fuel real/bursty).

## Two layers (fail independently — validated separately)
| Layer | Produces | Success metric (§6 of ARCHITECTURE) |
|---|---|---|
| **A — Fuel-map engine** | `L(x,t)` fuel curve from reconstructed positions + empirical liq-distance model | Stage-1 **mechanism**: does the map predict where `is_liq_origin` liqs actually fire / forward vol? |
| **B — The brain** | `E[F](t,h)` expected forced flow (vol-forecast × hitting prob) + asymmetry | Stage-2 **edge**: does anticipated flow predict *price* beyond what's already priced (crowd-anticipation control)? |

## Non-negotiables (from `../../../CLAUDE.md` + this repo's scars)
- Reconstruct via side-sign + `(ts, event_index)` order (memory `babylon-position-reconstruction`).
- `liq_mark_px` / any liq fill `px` is a SIGNAL, never a tradable entry price (edge3 scar).
- Unit of inference = the **day**; OOS/walk-forward only; gross primary + net-at-stressed-spread band.
- A null earns the word only with point estimate + CI + positive-control MDE + cross-unit sign test; every
  positive faces separate steelman AND prosecute-the-positive passes.
- Day-chunked compute with carryover (no month-wide window — it timed out vs the running build).
