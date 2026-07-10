# Alt-breadth wallet-cohort — architecture audit scope (pre-build)

**Audit target:** `research/studies/wallet_flow/ALT_BREADTH_ARCHITECTURE.md` — find DESIGN flaws before we build
`alt_flow.py` and run on the alt cross-section. This is the payoff study: re-run the (real, placebo-hardened,
walk-forward-robust, but majors-taker-dead) informed-cohort signal on ~50 alts to test whether BREADTH lifts
gross/crossing above cost (taker or maker).

**Context you must read:**
- The arch doc above.
- The majors pipeline it ports from: `research/studies/wallet_flow/{flow.py, book.py, placebo.py, walkforward.py}`
  and its `FINDINGS.md` (what's already established — don't relitigate; build on it).
- The data: `alt_flow` view (Reservoir 5-min signed flow, all coins — SOME Apr–May 2026 days still landing) and
  `asset_ctx` (all-coin mid_px + day_ntl_vlm). Access via `from research.data.db import connect`.
- Firewall + source facts: `research/data/RESERVOIR_ALT_FILLS_SPEC.md`, memory `babylon-reservoir`.

**Discipline:** read-only on repo files; scratch scripts in the scratchpad OK (do NOT edit study files). Memory-safe
DuckDB (`memory_limit`, `threads=1`). Verify claims against the PARTIAL tape where you can (TRAIN months 202508–
202602 are complete; the hole is 2026-04-13→05-16 in TEST). Return findings ranked most-decisive first: (claim,
evidence, does it change the design?, severity, concrete fix). Follow `audit/AUDIT_PROTOCOL.md`.

**Highest-value checks:** (1) is the trailing-ADV universe genuinely point-in-time given `day_ntl_vlm` is DAILY
CUMULATIVE (intraday look-ahead trap)? (2) does the cohort freeze stay leak-free (A8) on the alt panel? (3) is the
breadth-vs-alt-cost tension framed honestly, and is the alt taker/maker cost modeled from real `asset_ctx` impact
spreads? (4) firewall — alt_flow must never reach gate_a/engine.
