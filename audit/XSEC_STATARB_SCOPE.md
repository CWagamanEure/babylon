# Run scope — design-doc audit of xsec_statarb (2026-07-09)

**Target:** `research/studies/xsec_statarb/ARCHITECTURE.md` (a PRE-BUILD design doc — no code yet).
**Task:** red-team the *methodology/design*, not code. Your job is to find the design decision that would
**fabricate a false edge OR manufacture a false null** once this is built — before a line of code is written.
Anchor each finding to a doc **section (§N)** and quote the claim; there are no file:line yet.

**Resource safety (protocol §1, strict):** do NOT read the parquet lake (`data/**`), do NOT run `ingest`,
`episodes_build`, or any build/websocket. Reason statically. Data schemas: `research/data/schema.py`;
`asset_ctx` columns = ts, coin, funding, open_interest, prev_day_px, **day_ntl_vlm**, premium, oracle_px,
mark_px, mid_px, impact_bid_px, impact_ask_px (per-minute, 230 coins). `fills` = per-wallet, MAJORS ONLY.

**Known context to assume true:** the 2-asset minute-scale precursor (`../research/studies/liq_fuel_map/
FINDINGS.md`) found the residual reversal is real but ~2–5 bp (sub-cost) on majors; this study bets that
horizon + breadth + alts change the economics. Median alt impact spread ≈ 15 bp. Data span = 11 months.

**Highest-value concerns (non-exhaustive — think second-order):** point-in-time universe & survivorship;
any look-ahead in factor betas / PCA sector factors / signal / universe / wallet-cohort ranking; the L×H
sweep's multiple-comparisons/winner's-curse exposure and whether train-selects/test-confirms is enough;
overlapping-return t-stat inflation; MDE/power over 11 months at the primary horizon (is a deployable Sharpe
even detectable?); impact-spread→true-cost realism at position size; `day_ntl_vlm` semantics (daily
cumulative — is using it intraday a look-ahead?); realized-neutrality verification vs the "secret exposures";
research/ firewall. Report per protocol §5. A clean bill on your lens is a valid result — say so plainly.
