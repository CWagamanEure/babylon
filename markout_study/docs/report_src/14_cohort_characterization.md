# 14 — Who the 121-wallet cohort are, and how they beat the average

**Scope.** Characterization of the canonical *recurring* cohort — the 121 wallets that landed
top-decile (TRAIN-only, `neut_8h`) in ≥2 of 6 train months (STRICT ≥3mo = 28). This is the
report's "who are they / what do they do differently" payoff. All numbers are **descriptive /
explanatory** (Phase 1) except the beat-the-field block, which is the cross-fold OOS persistence
result. Cohort file: `out/cohort_M_frozen.{txt,parquet}` (1,693 eligible wallets; 121 flagged
`primary`+`strict`, 1,572 `none`).

**One-line characterization.** *Aggressive contrarian mean-reverters who fade large, decelerating
moves at deep pullbacks below the 24h high — their "edge" is the mechanical short-horizon fade, done
harder and more consistently. It is a tilt, not a monolith: ~1 in 6 is not even a net fader.*

---

## FACTS

### A. Behavioral decomposition — entry-state, three groups (TRAIN)
Source: `src/cohort_P1_behavioral.py`, reported in `docs/FINDINGS_LEDGER.md` Phase-1 (lines 613–617).
RECURRING = the 121 cohort's entries; ORDINARY = all other cohort-eligible wallets' entries
(sampled ≤40k); CONTROL = random non-wallet TRAIN bars (sampled). Units = basis points unless noted.

| feature | RECURRING | ORDINARY | CONTROL | reading |
|---|---:|---:|---:|---:|
| \|trailing 8h move\| (`aret_8h`) | **175** | 151 | 72 | enter on much bigger moves than a random bar; somewhat bigger than ordinary wallets |
| signed 8h-in-trade-dir (`sret_8h`) | **−86** | −12 | n/a | enter *hard against* the 8h move — the contrarian/fade signature (ordinary barely fade) |
| distance below 24h high (`dist_hi`) | **−281** | −218 | −166 | enter far below the recent high — buying deep pullbacks / selling deep rips |
| acceleration (`accel`, last-hr minus prior-hr) | **−6.2** | ~0 | ~0 | fade *decelerating* moves (momentum already rolling over), not fresh breakouts |
| realized vol (2h/8h) | slightly higher | — | — | modestly elevated-vol entries (directional; exact figures not in ledger) |
| trade size, median notl | **~$4.1k** | ~$4k | — | similar *median* size to ordinary wallets… |
| trade size, mean notl (entry-weighted) | **~$162k** | lower | — | …but a much fatter large-trade tail (mean ≫ median) |

Takeaway: the distinguishing axis is **direction relative to the trailing move** (−86 vs −12), not
size. They are not a big-money cohort; they are a *disciplined-fader* cohort.

### B. Per-wallet fade classification — how homogeneous is the fade?
Source: `src/cohort_P1b_perwallet_fade.py` (per-wallet, ≥20 train entries; contrarian = `dir·move < 0`).

- **83%** of the 121 cohort are **net faders** (per-wallet mean signed-trailing-8h < 0) — vs a much
  lower share of ordinary wallets.
- **65%** are **consistent faders** (≥60% of their entries are contrarian).
- **44%** are **strong/homogeneous** faders (≥70% of entries contrarian).
- **Median fade-fraction 0.67** (cohort) vs **0.52** (ordinary) — cohort entries are contrarian
  two-thirds of the time; ordinary wallets are near coin-flip.

Reading: the fade is the **dominant but not universal** cohort trait — ~1 in 6 is not a net fader,
so "contrarian mean-reverter" is a central tendency, not a defining membership rule. **A tilt, not a
monolith.**

### C. How the cohort beats the field (the persistence signal)
Source: Stage M2 recurrence, `docs/FINDINGS_LEDGER.md` (lines 508–519). GROSS, coin-month-neutralized
markout (NOT net-of-cost, NOT vs the mechanical fade).

- **Top-decile forward edge +5.72 vs field +1.24 = +4.48 bp [+2.17, +7.54]**, positive in **9/10**
  folds — the load-bearing "they beat the average" number.
- **Adjacent-fold rank-IC: 8h +0.093 [+0.061, +0.126], 10/10 folds, sign-p = 0.002** (4h +0.081,
  24h +0.085). Persistence is a **slow-information term structure peaking at 8h** (audit #10:
  +0.219 [+0.154, +0.282] at 8h, monotone 1h→8h), robust to drop-HYPE/SOL and BTC-only.
- **Important over-carry caveat:** this +4.48 is generic short-horizon reversal — a *costless
  mechanical fade earns ~+9.5 bp at these same entry times* (Stage L). So "beats the average" = the
  fade works and the cohort executes it; it is **not** demonstrated wallet-specific skill and is
  **not net-of-cost deployable** (Stage M2/M3/M4: incremental alpha over the fade ≈ +1.0 bp, p≈0.44,
  CI wide). The characterization is honest as *behavioral signature*, not as an alpha claim.

### D. Cohort conviction / structural traits (computed from `out/cohort_M_frozen.parquet`)
Per-wallet medians, COHORT-121 vs the 1,572 non-cohort eligible wallets:

| trait | COHORT-121 (median) | OTHER (median) | note |
|---|---:|---:|---|
| `conv` (conviction rank) | **0.72** | 0.48 | cohort sits high on the continuous conviction score by construction/selection |
| `n_top` (top-decile months) | 2.0 (mean 2.27) | 0.0 | ≥2 by definition; STRICT subset ≥3 |
| `n_entries` (train entries) | 268 (mean 318) | 291 | **not** higher-activity than ordinary — similar entry counts |
| `n_days` active | 79 | 69 | modestly more persistent presence |
| `n_coins` traded | 4.0 | 3.0 | trade across the full majors set (market-timing trait shared across coins) |
| `notl_med` (per-wallet median size) | $4,053 | $3,941 | ~identical median size |
| `notl_mean` | $6,318 (wallet-mean-of-means $127k) | $6,477 | fat tail drives the mean |
| `dir_bias` (signed long-share − 0.5 proxy) | 0.36 (\|·\| median 0.44) | 0.31 | moderate directional tilt, not one-sided |

Reading: what separates the cohort is **conviction/consistency of the fade and cross-coin breadth**,
not trade size or raw activity. Supports "a tilt, not a monolith."

---

## FIGURES TO MAKE
1. **Behavioral bars (grouped) — RECURRING vs ORDINARY vs CONTROL** for the four discriminating
   features: `aret_8h` (175/151/72), `sret_8h` (−86/−12/—), `dist_hi` (−281/−218/−166),
   `accel` (−6.2/0/0). Highlight `sret_8h` as the signature axis. Source: `cohort_P1_behavioral.py`.
2. **Per-wallet fade-fraction histogram** (the 121 cohort, ≥20 train entries), with a reference line
   at 0.5 (coin-flip) and at the ordinary-wallet median 0.52; annotate cohort median 0.67 and the
   ≥0.60 (65%) / ≥0.70 (44%) thresholds. Overlay/side-by-side ordinary distribution. Source:
   `cohort_P1b_perwallet_fade.py`.
3. **Cohort-vs-field forward markout** — top-decile +5.72 vs field +1.24 (Δ +4.48 [+2.17,+7.54]),
   ideally the per-fold spread (9/10 folds) as a strip/dot plot, plus the 1h→8h rank-IC term
   structure (peak at 8h +0.093). Source: Stage M2, `cohort_M2_recurrence.py` outputs.
   *Caption must carry the over-carry caveat: gross, not net, ≈ mechanical fade.*
4. *(optional)* **Conviction/consistency contrast** — cohort vs other on `conv` (0.72 vs 0.48) and
   fade-fraction, small 2-panel, to make "consistency, not size" visual. Source:
   `cohort_M_frozen.parquet`.

---

## GAPS
- **`vol_2h`/`vol_8h`, `sret_1h/4h/24h`, `dist_lo`, `age_hi/lo`, `funding_bp` exact medians are not in
  the ledger** — only the four headline features are quoted. Getting them requires re-running
  `cohort_P1_behavioral.py` (a heavy bar-pricing pass — **blocked by RAM rules**). Figure 1 uses the
  four confirmed features; vol is stated directionally ("slightly higher").
- **Fade % (83/65/44) and fade-fraction medians (0.67 vs 0.52)** come from
  `cohort_P1b_perwallet_fade.py`, which prices bars — not independently re-verifiable here under RAM
  rules; taken from the task brief / script logic. If a printed run-log exists it should be cited
  directly.
- **$162k mean size** is the entry-weighted mean from `cohort_P1_behavioral.py`; the per-wallet
  parquet gives a wallet-mean-of-means of ~$127k. Both describe the same fat right tail — pick one
  framing and label it precisely (entry-weighted vs wallet-weighted).
- **Deferred behavioral features** (VWAP distance, volume/OI shocks, liquidations, basis, order-flow
  imbalance, maker/taker aggressiveness) are **not in this dataset** — reserved for the Phase-3
  forward log. The characterization is therefore on price-state + size + direction only.
- **The "beat the field" number is gross and ≈ the mechanical fade.** Any report framing must not
  present +4.48 bp as deployable cohort alpha; incremental-over-fade ≈ +1 bp (p≈0.44), and net-of-cost
  it is ~0 (Stages M2–M4). This is a *behavioral* characterization payoff, not an alpha claim.
