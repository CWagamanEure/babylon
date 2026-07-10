# Audit scope — Tier-2 markout ARCHITECTURE (design review, pre-build) 2026-07-08

You are auditing a DESIGN DOC (no code yet), not source. Target:
`docs/WALLET_FEATURES_TIER2_MARKOUT_ARCH.md`. Supporting intent:
`docs/WALLET_FEATURES_SPEC.md` §4c + pins P10/P12/P15; the completed episode schema in
`research/data/episodes_build.py` (`_ARROW`); the price panel columns in `research/data/schema.py`
(`ASSET_CTX_*`). Do NOT load any parquet (resource safety — a build may run; check `ps aux`).

## Why this audit is high-stakes
This is the "is there edge" measurement. The project's prior "+24–31 bp edge" was ENTIRELY a
stale-hourly-candle pricing artifact (memory `babylon-edge3-audit`): a believable, replicated,
multi-fold positive that was pure look-ahead in the price join. Your job is to find the design choice
that would let a *benign-noise or beta* result read as *skill*, or vice-versa (over-null).

## Run-specific focus (in addition to your persona lens + AUDIT_PROTOCOL.md)
- **The estimand (§3/§4) is the whole game.** Is `timing_alpha = raw_markout − dir_sign·μ_h(coin)`
  actually isolating entry-timing skill from beta/drift? Does subtracting a per-coin unconditional (or
  per-week) forward-return baseline over- or under-correct? Any circularity (marking with the same
  oracle series whose μ we subtract)? Shorts / dir_sign sign errors?
- **Anti-artifact (§7) + post-fill pricing (§0/§2).** Does `entry_bar_ts = first tick STRICTLY after
  open_ts` + oracle_px + ASOF-≤ actually preclude the edge3 stale-candle artifact? Is the placebo
  permutation null constructed correctly (shuffle within coin,week)?
- **Leakage / right-censoring (§5).** Per-horizon `entry_bar_ts + h ≤ C` AND `≤ last_ctx_tick`; μ_h
  estimated ≤C. Any path where post-cutoff price enters a panel-C number?
- **Over-null / over-carry (§6, CLAUDE.md gate).** Power gate `n_weeks<6→INCONCLUSIVE` + MDE; but also:
  10 horizons × 4 coins × cutoffs = a large multiple-comparisons surface. Is the argmax-of-horizons a
  winner's-curse trap? Is the permutation p + FDR applied across the WHOLE arc, not per-cell?
- **Shadow-Gate-A / firewall (§8, P10).** Is the `leakage_controls_applied=false` + `shadow__` namespace
  + `frozen_config.sha256`-before-viewing enough to stop this exploratory markout being read as the
  frozen verdict?

Report per AUDIT_PROTOCOL.md format. A clean bill on your lens is a valid result — say what you checked.
