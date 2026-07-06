# DEPLOYMENT_INPUT_FREEZE — operational inputs for Gate B/C (SHELL — UNSIGNED)

**Status: NOT YET FROZEN.** This addendum is filled and signed at Execution-order step 6 (`PREREGISTRATION_v2.md` §A.14), from operational measurements only — **before any Gate-B or Gate-C output is inspected.** Until every field below is filled and the block is signed, Gate-B/C outcomes remain sealed.

## Invariants
- Values are set from **measured operational data**, never from strategy returns.
- The Gate-A-selected basket membership is already frozen and is **not** revisited here.
- Signing this file is a one-way gate: after signing, no input below may change for the primary Phase-A deployment evaluation.

## Latency (measured, ruling #5)
| Stage | Timestamp source | Measured value |
|---|---|---|
| Source event (fill on tape) | | ⬜ |
| Ingestion | | ⬜ |
| Signal-ready | | ⬜ |
| Order-submission (simulated) | | ⬜ |
| Expected fill | | ⬜ |
| **End-to-end latency distribution** | | p50 ⬜ · p90 ⬜ · **primary percentile ⬜** |

Primary deployment latency = **⬜** (conservative percentile, justified: ______). Scenario bounds 5 s / 300 s retained as sensitivities.

## Costs (measured/specified, ruling #6)
| Component | BTC | ETH | SOL | HYPE | Source |
|---|---|---|---|---|---|
| Taker fee (bp/side) | ⬜ | ⬜ | ⬜ | ⬜ | fee tier |
| Expected half-spread (bp/side) | ⬜ | ⬜ | ⬜ | ⬜ | measured by coin×time |
| Expected slippage @ copied notional (bp/side) | ⬜ | ⬜ | ⬜ | ⬜ | depth model |
| **Full per-side cost** | ⬜ | ⬜ | ⬜ | ⬜ | sum |

Copied notional (frozen): **⬜**. Charged **entry and exit separately**. Reported layers: gross / fee-only / fee+spread / full. The {8,8,10,14} bp schedule is retained as a **conservative sensitivity**, not the primary.

## Sign-off
Frozen by: __________  Date: __________  Confirmation: "No Gate-B/C output was consulted in setting the values above." ⬜
