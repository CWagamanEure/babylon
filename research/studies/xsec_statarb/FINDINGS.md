# Findings ledger — xsec_statarb (cross-sectional residual reversal on HL perps)

Design: `ARCHITECTURE.md`; binding audit corrections: `AUDIT_RESPONSE.md` (4-agent swarm, 12 blockers).
Firewalled research lane. Data: `asset_ctx` (230 coins, market data) — NO ingestion needed for the backbone.

## FLOOR GATE (2026-07-09, `gate.py`) — real in-sample, NON-STATIONARY, OOS-negative

**Spec.** BTC/ETH-only residual reversal (no sectors/composite/wallet). ~70 PIT-liquid alts, hourly bars,
non-overlapping H-hour holds. Blockers implemented: A2 sign (long weak/short strong), A3 t+1 entry,
A6 validity mask, A7 completed-prior-day ADV, B10 out-of-fit betas, B12 rank-IC vs forward **residual**
return, A10 non-overlap + bootstrap CI, A4/A5 point-in-time spread round-trip + 2× taker fee (SIZE penalty
deferred → net is an UPPER BOUND). Train <202604 / held-out ≥202604.

**Result.**
| cell | IC (full) | 95% CI | MDE | net bp | OOS IC | OOS net |
|---|---|---|---|---|---|---|
| H24 L12 | **0.038** | [0.014, 0.063] | 0.034 | +3.5 | **−0.014** | −55 |
| H24 L24 | 0.027 | [0.002, 0.050] | 0.035 | +5.5 | −0.026 | −55 |
| H12 L12 | 0.026 | [0.008, 0.042] | 0.024 | −12.1 | −0.016 | −33 |
| L=72h | ~0.006 | spans 0 | — | neg | ~0 | neg |

- **In-sample signal is real & powered:** IC CI excludes zero, IC > MDE, reversal at short lookback (≤24h),
  decays to noise by 72h. Per-month: 7/8 training months positive, several netting **+53 to +84 bp**.
- **OOS collapses (6/6 cells flip negative);** deployment-relevant net −33 to −55 bp.
- **The flip is NOT regime-separable.** Per-month IC vs BTC trend/vol: a −16% BTC month (202602) had the
  *best* IC (+0.08); a −20% month (202511) and a calm −3.6% month (202605) had the *worst* (−0.03, −0.05).
  No trend/vol variable separates good from bad → a simple regime filter cannot rescue it.
- **Crude construction gives ~0 Sharpe** even where IC>0 (huge per-period quintile variance; annualized
  Sharpe ≈0.2 in-sample) — IC→Sharpe conversion needs proper portfolio construction, not yet built.

**Verdict (gated).** NOT a null — a genuine, powered in-sample cross-sectional reversal exists (do not bury
it). NOT a live positive — it is **non-stationary**, fails the held-out quarter (6/6), is not separable by
BTC trend/vol, and is net-marginal even in-sample. Labeled: **real-but-non-stationary; deployment verdict
negative/unresolved.** Two things could still move it, both untested: (a) proper **portfolio construction**
(inverse-vol, more names, full neutralization) to convert the real IC into Sharpe; (b) **statistical
sector-neutralization** (Stage 5) — if the OOS flip is sector-momentum leaking through a BTC/ETH-only
residual, sector factors could stabilize it. If sector-neutralized reversal ALSO flips OOS, the
non-stationarity is fundamental → earned method-scoped negative. Wallet/composite legs untouched.

## SECTOR-neutral test (2026-07-09) — hypothesis FALSIFIED; signal real on walk-forward, COST-bound

Added a causal leave-one-out common-alt sector factor (Stage-5 lite, `gate.py run(sector=True)`). Result:
**almost no change** — in-sample IC 0.038→0.039 (H24/L12), 0.027→0.033 (H24/L24); OOS **still 6/6 negative**
(oosIC −0.01 to −0.03), net still ~0/negative. → the OOS weakness is **NOT sector-momentum leakage.**

**Correction to the earlier "non-stationary-dead" read.** On a full causal walk-forward (per-month, rolling
betas — every month effectively OOS), IC is positive in **8/10 months** (mean ~0.036); the last-3mo "flip"
overweighted one weak quarter. The signal is **real and mostly-positive causally**, not dead.

**The binding constraint is COST, not stationarity.** Gross quintile spread ~22 bp barely exceeds taker cost
~20 bp → net ≈ 0 (breakeven, huge per-period variance, Sharpe ~0.2), with a genuinely weak last quarter.
This is the SAME wall as `../liq_fuel_map/`: real small signal, eaten by taker cost. Per the anti-ratchet
rule the crude equal-weight + full-taker floor is a **blind instrument on NET** — NOT yet an earned negative
on tradeability. Untested levers: (a) inverse-vol × liquidity weighting + tightest-spread universe + turnover
reduction (lower *effective* cost, within taker, on data we HAVE); (b) maker/rebate execution (the real
lever — needs L2/BBO data we lack). Powered-construction test = the next decisive step.

## EARNED VERDICT (2026-07-09, steelman construction pass, `scratch_portfolio.py`) — taker-untradeable

A separate "steelman the positive" agent tested ~30+ constructions (inverse-vol, tight-spread subsets,
cost-aware, hysteresis × 2 cells). Findings:
- **Cost was under-charged ~2× in `gate.py`** (single-crossing not two-leg round trip). Corrected:
  round-trip cost ≈ **2·avg_spread + 4·fee ≈ 36 bp/period** (spreads ~9 bp on the ADV-capped top-70).
  Honest baseline net (H24/L12) ≈ **−15 bp/period**, not +3.5. `gate.py` cost line now fixed.
- **Every construction lever makes net WORSE, none is net-positive.** Inverse-vol HURTS (reversal lives in
  HIGH-vol names); tight-spread subset HURTS (signal lives in WIDER-spread/less-liquid names); cost-aware
  HURTS; hysteresis is the only one that helps net (still −8.7 bp, SR −1.6). Best net SR −0.94 full / −4.9 OOS.
- **Zero-cost (maker) Sharpe CEILING = only ~1.4 full-sample [CI −0.7, 3.7], NEGATIVE OOS.** Even with
  perfect free execution the deploy bar (net SR ≥ 1.0) is not cleared with any confidence, and OOS is
  negative → the book is **variance/power-limited, not merely cost-limited.** ~⅔ of the shortfall is taker
  cost, ~⅓ is a Sharpe/variance/OOS-instability wall no execution fixes.
- Walk-forward: IC>0 8/10 months (signal real); net>0 only 3/10 (needs gross ≳35 bp ≈ 2× cost). Last quarter
  is both cost-negative AND IC-weak (genuine decay patch atop the cost wall).

**GATED VERDICT.** Gross cross-sectional reversal IC is **real & powered** (0.038, CI excludes 0, MDE 0.034,
8/10 causal months) — NOT dead. **Net-positive TAKER book = earned powered NEGATIVE** (near-deterministic
~36 bp cost > ~22 bp best gross; every lever confirms; 30+ configs, zero net-positive). Maker/rebate path is
**unresolved and data-gated** (needs L2/BBO fill+adverse-selection modeling we lack) AND has a weak ceiling
(~1.4 in-sample, negative OOS) — a coin-flip even if built. OOS net-Sharpe itself is inconclusive-by-
construction (3-mo, MDE≈5.6); the powered negative rests on the real gross IC + near-deterministic cost gap +
the zero-cost ceiling failing the bar full-sample.

**Label:** *real gross signal, taker-untradeable (earned negative); maker path unresolved, data-gated, weak
ceiling.* Same wall as `../liq_fuel_map/`. Do not spend more construction effort on the taker book.
