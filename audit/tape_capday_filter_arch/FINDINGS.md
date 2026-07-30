# tape_capday_filter architecture audit — 2026-07-20 (4-agent swarm)

Scope: TAPE_CAPDAY_FILTER_ARCH.md v1.0 → v1.1. Auditors: stats-rigor (S), correctness (C),
firewall-leakage (FW), data-integrity (D). All findings folded into v1.1; tags inline in the doc.

HIGH (all resolved in v1.1):
- S1 arm-specific winsor p95 contaminates FALL−F0 delta → common union-pool limit + unwinsorized sensitivity.
- S2 8-block fold bootstrap undercovers → paired t 7df + wallet-cluster paired boot, quote wider.
- S3 screen-then-rank confounds removal with backfill → FRTS rank-then-screen arm + decomposition.
- C1 tape liq struct marks BOTH sides (78/78 measured) → F4 uses schema.LIQ_ORIGIN_SQL (own liq only).
- C2 filter-then-group truncates multi-fill entries (350 sp0-first multi-fill oids/hour sampled) →
  entry = oid whose FIRST fill is flat-open taker; aggregate all same-dir fills of the oid.
- D1 asset_ctx ends 2026-06-29; 202607 ctx dirs EMPTY → fold 202606 right-censored, ctx-coverage asserts +
  funnel reporting (doc's "first 3 days of next month" claim was false at the right edge).

MED: S4 8h "a-priori" label removed (burned-fold-selected horizon, stamped); S5 BH within primary family +
whole-grid tally; S6 delta-specific MDE with 7-df factor 3.26; C3 taker-share frozen count-weighted,
NCV-excluded; C4 day_notional = Σ abs(sz)·px; FW1 no `.lake` import — entries from data/raw/fills only,
asserted; D2 NULL-oid guard + (block_number,event_index) fallback; D3 union_by_name=true (all-NULL INT32
liq cols in zero-liq hours); D4 cache sha covers thresholds+SCHEMA_VERSION+ctx coverage, sha in filename.

LOW/NIT: C5 exclude Net Child Vaults from rollup; C7 builder_fee diagnostic; FW2 partial ctx day 20260530
noted; FW3 ts-based boundary asserts; FW4 frozen-133 overlap diagnostic + sensitivity; FW5 F5 0/0→PASS;
FW6 "forward ASOF" wording fixed; S7 dragger diagnostic = funnel-only; S8 book CI wider-of-two;
D5 flag policy declared (formation includes flagged ex-NCV, entries exclude flagged); D6 DECIMAL(38,18)
flatness cast, day_notional>0 active-day form; D7 integer partition predicates.

Clean bills: multiplicity-preserving weighted boot inheritance; seed scheme; formation/test temporal design;
fills tape completeness 202508–202606 (8016/8016 objects done, 0 hard errors); asset_ctx complete at day
grain 202511–202606 except the two documented edge cases; no PG/lane-firewall exposure.
