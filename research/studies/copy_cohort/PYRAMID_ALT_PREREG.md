# PYRAMID-ALT book — FORWARD PRE-REGISTRATION (lead paper-trader arm)

Frozen 2026-07-17. Burned folds 202511–202606 are exhausted (see FINDINGS.md addenda 5–9); every parameter
below is fixed BY PRINCIPLE from already-recorded measurements — no new burned-fold sweeps are permitted to
tune this spec. Evaluation is FORWARD ONLY (paper trader). One descriptive mechanics pass on burned data is
permitted solely to verify plumbing/accounting of this frozen spec (no variants, nothing tuned from it).

## Motivation (recorded facts)
Reconciliation (addendum 9): the alt copy edge concentrates in REPEAT entries fired while the trader is
already in position (+65.5 wf-equal gross on the full surface → −3.6 on first-entries-only); day-state
conditioning (≥2 same-day entries) flipped the K100@1h dollar book to +5.8 net (SR 1.17, underpowered).
Lag test: edge intact at 30s. Census/anatomy: human archetypes carry it; bots poison long horizons.

## Frozen spec
- Selector: t_v1 top-100 (universe t-stat, monthly refresh, data ≤ T−1), pure-maker wallets excluded
  (taker share < 0.1), liquidation-history screen (t_noliq variant runs as the B-arm).
- Universe: alt perps with TRAILING 3-mo ADV ≥ $10M; entries with notional ≥ $250 only.
- Signal ladder per (wallet, coin): trader's 1st flat-open = WATCH (no position). 2nd entry (any add or
  re-open same coin same day while thesis window open) = ENTER 1 unit. 3rd, 4th entry = ADD 1 unit each
  (max 3 units). Nothing after the 4th signal.
- Exit: 8h after the LAST add (the horizon of the measured repeat-entry surface); hard stop = trader's
  full exit observed (close their position → we close ours next print).
- Execution: market entry within 30s of the observed fill (lag-proof per lag_haircut); maker-entry
  recorded as a shadow variant (fill-or-miss at passive price) for cost comparison — no fees assumed
  saved until measured.
- Unit = $2,500; max 3 units/(wallet,coin); max $50k gross/coin; max $250k book gross.
- Costs (paper accounting): 21.5bp RT taker; shadow maker book at 2bp + miss-rate.
- Cadence: monthly cohort refresh (daily-rolling recorded as shadow scores only).

## Forward success criteria (pre-set)
After ≥ 60 trading days: net bp/trade > 0 with day-block bootstrap CI excluding 0 → promote to small live
capital. CI includes 0 → continue to 120 days. Point negative at 120 days → retire the arm. No re-tuning
of the ladder/horizon/caps during evaluation; any change = new registered arm.

## Slate context
Arms: (1) PYRAMID-ALT (this, lead), (2) majors-native K30 @8h (side-book; honest status: underpowered
positive, CI [−17.9,+42.1]), (3) vault-deposit ranking, (4) K100@1h day-state variant (small).

## Amendment v1.1 (2026-07-17, timing stamped)
Add to selector screens: fills/day < 1000 over formation (the pre-existing mechanical bot criterion from
majors_archetype_classification). Rationale: the taker-share screen implements "exclude uncopyable bot flow"
but misses TAKER-side HFT (attribution found a 22k-fills/day bot as the book's #1 dragger). This amendment
implements the original intent with the pre-existing criterion; HOWEVER it was adopted AFTER the wallet
attribution was viewed, so its effect on burned folds (+0.25 → ~+10bp net ex-post) must NOT be quoted as
evidence — forward criteria unchanged and adjudicate the amended spec as a whole.
