# Steelman-the-taker-edge swarm — scope note

## The finding under attack (prosecute it — find the buried TAKER edge, or confirm it's truly dead)
`research/studies/wallet_flow/` established an informed-wallet-cohort signal that is:
- leak-free, factor-neutral, OFI-controlled, **placebo-hardened** (beats random same-size cohorts p=0.033),
  **walk-forward-robust** at 1h (5/5 folds positive & beat random), HYPE-strongest.
- But the **majors book (`book.py`) is TAKER-NEGATIVE**: gross +1.51 bp/hr, cost 5.78 bp/hr, net −4.27,
  net SR −13. Break-even needs ≤1.27 bp/crossing; taker fee alone is 4.5 bp (2.4 bp even at top volume tier).
  Conclusion currently written: "taker-untradeable, earned negative; only the maker path survives."

**Your mandate:** the user believes we are DISREGARDING A REAL TAKER EDGE. Find what the analysis missed that
could make a net-positive TAKER book. This repo has a *demonstrated bias toward false nulls* (see
`CLAUDE.md` OVER-NULLING GATE) — a "taker-dead" verdict is the safe-sounding conclusion and may be an
artifact of construction. BUT the mirror hazard (OVER-CARRY) is equal: **do not manufacture an edge — every
positive claim must come with a reproduced number and survive its own cost.**

## Key facts / numbers already established (verify, don't trust)
- Signal: per (coin,hour) frozen-informed-cohort net signed flow predicts factor-neutral 1h fwd residual.
  Partial IC | OFI ≈ +0.030 @1h (CI excl 0); 2h "noise" (IC-sense). HYPE per-coin IC highest.
- Book: hourly cross-sectional RANK weights over the 4 majors (dollar-neutral), t+1 entry, 1h hold.
  **Turnover = 1.19/hr (near-max for a 4-name rank book — it re-ranks every hour).**
- Cost = Σ|Δw| × (per-coin half-spread + 4.5 bp fee). Majors half-spread tiny: BTC .07 / ETH .23 / SOL .28 /
  HYPE .97 bp (from asset_ctx impact_bid/ask). So cost is ~all FEE, and turnover is the multiplier.
- dist.py: PnL fat-tailed but ~SYMMETRIC (skew +0.09); mean not left-tail-dragged. Edge CONCENTRATES in:
  (a) high signal-conviction deciles (gross +1.1→+3.85), (b) HYPE (leg +1.02) & BTC/ETH (+0.3), SOL a DRAG
  (−0.18), (c) some hours-of-day (h12Z net +2.25 taker-positive, but argmax-of-24 in-sample).

## Files (read first)
- `research/studies/wallet_flow/flow.py` (signal build, resid, cohort freeze — the leak discipline)
- `research/studies/wallet_flow/book.py` (the taker/maker book + cost model — the thing under attack)
- `research/studies/wallet_flow/dist.py` (distribution + conditional cuts)
- `research/studies/wallet_flow/FINDINGS.md` (the full ledger + current verdict)

## How to run (data is CACHED — reruns are ~1 min)
- `.venv/bin/python -m research.studies.wallet_flow.book` etc. Cached wb/agg parquet in the scratchpad.
- You MAY write NEW scratch scripts under the scratchpad dir to test a hypothesis. **Do NOT edit the study
  files** (`research/studies/wallet_flow/*`). Reuse their functions by importing.
- Memory-safe DuckDB: `SET memory_limit='900MB'; SET threads=1` (copy from book.py). The Mac jetsam-kills
  on OOM (exit 137/144) — keep single-threaded, aggregate month-by-month, don't pull the full tape.

## Output (return to orchestrator — this is data, not prose)
For each finding: (1) one-line claim; (2) the reproduced number / evidence (or "reasoned, not run"); (3) does
it flip or materially move the taker verdict? by how much (net bp/hr, SR)?; (4) severity high/med/low;
(5) what to build/run next to confirm. Rank most-decisive first. If you find NO real taker edge on your
angle, say so plainly and state what you ruled out (that is also a result). Verify before asserting.
