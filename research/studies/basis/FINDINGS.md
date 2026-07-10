# Findings ledger — basis (oracle vs HL-mid basis on majors)

Descriptive feasibility EDA (asset_ctx per-minute, majors, 2025-08 … 2026-06, ~478k min/coin).
Question: is there an oracle−mid basis **large enough AND long enough** to trade?

| Date | Question | Method | Result | Verdict | Artifacts |
| --- | --- | --- | --- | --- | --- |
| 2026-07-07 | Is the raw oracle−mid gap tradeable? | per-coin magnitude, sign, persistence | Median \|basis\| 3.5–4.6 bp ≫ spread (0.09–1.7 bp), BUT it's a **persistent directional offset** (signed mean −3.0/−3.1/−3.9 bp for BTC/ETH/SOL; +0.4 HYPE), ac1≈0.77–0.92, and it does **not** converge (corr_catchup≈0). | **Structural perp-vs-spot discount (carry), not a dislocation.** Untradeable as convergence; capturing it as carry needs a spot leg we don't have. | `eda_basis.py` |
| 2026-07-07 | Do dislocations *around* the structural level revert (net of cost)? | demean by trailing-60min mean; reversion beta at 1/5 min; large-dislocation (top-decile) tail | Tradeable dislocation is tiny (median 0.5–0.8 bp BTC/ETH/SOL; HYPE 1.8 bp < its 1.9 bp spread). Weak reversion (beta ≤0.20, SOL best). **Top-decile tail, 5-min hold: reversion 0.04/−0.21/−0.24/+0.18 bp vs round-trip spread 1.0–5.4 bp** — 10–100× below cost, and ETH/SOL are the *wrong sign* (tail continues, not reverts). | **EARNED NEGATIVE (powered).** No tradeable minute-scale oracle−mid convergence edge on majors. N≈478k/coin → tight CI; care-about (clear ~1–5 bp cost) decisively excluded; 4/4 coins fail; demeaned + tail + multi-horizon checked. | same |

| 2026-07-07 | Does funding/positioning predict forward returns (contrarian vs momentum)? | hourly funding → forward oracle return, majors + all ~200 coins, 1/4/8/24h; momentum-confound control; funding & trailing-return decile spreads | **Majors: ~nil** (corr ≤0.02, flips sign by horizon). **All coins:** funding is NOT a momentum proxy (corr −0.13) and predicts independently, BUT tiny & fragile — Pearson +0.04 vs robust funding decile D10−D1 = **−2.3 bp/8h** (linear/decile disagree ⇒ outlier-driven, not robust). Dominated by a large generic **alt short-term reversal** (trailing-ret decile D10−D1 = **−17 bp/8h**). | **UNTRADEABLE-FOR-US.** The only signal is in ALTS; we have **majors-only fills/execution** (no alt fills, no alt book) → can't trade or cost it. Majors (tradeable) are efficient. | `eda inline` |

## Dead-ends (do not re-run)
- **Funding/positioning → forward-return edge is an ALT effect, untradeable with current data.** Majors are
  efficient (no funding→return signal). Alts show a mild fragile funding-contrarian tilt (~2 bp/8h, decile,
  gross) swamped by a large generic alt short-term reversal (~17 bp/8h, decile, gross) — but we have
  **majors-only fills**, so no execution/cost for alts. Pursuing either needs **alt fills + alt L2**
  (data acquisition), and the alt-reversal edge is notoriously cost-heavy even then.
- **Minute-resolution oracle−mid basis-convergence / lead-lag-catch-up trade on majors.** Arbed away — the
  reversion is 1–2 orders of magnitude below cost, and in the large-move tail it flips to continuation. The
  cross-venue lead-lag is real but lives **sub-minute** (our earlier web swarm found ~−800ms HL-lag); it is
  gone by the time our per-minute snapshot sees it. Reviving the *faster* version needs sub-second/tick data
  (a data-acquisition trigger), not another minute-resolution re-run.

## Still open (NOT killed by this — different trades)
- **Funding/carry on the structural basis.** The persistent −3 bp perp discount (BTC/ETH/SOL) is a funding
  phenomenon; whether the basis level predicts collectable forward funding / carry (CANDIDATES D-family) is
  untested here and is a *carry* trade (beta/funding exposure), not convergence. Needs the funding analysis
  and ideally a hedge/spot leg.
- **HYPE is structurally different** (basis ≈ 0, HL-native) — worth remembering for any HL-native-vs-external
  angle, but its dislocation < spread so not tradeable as convergence either.
