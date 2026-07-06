# AUDIT_ONLY_PLAN — pre-freeze, non-outcome implementation (item 11)

Purpose: resolve every `[AUDIT-ONLY]` Gate-A placeholder using **counts and coverage only**, so no threshold is set by inspecting wallet markout rankings or basket returns. This code may run before the confirmatory analysis; it is firewalled from outcomes.

## Hard firewall (what this code may NOT compute or emit)
- No wallet markout ranking, no θ̂-vs-Yband relationship, no selected-vs-field return, no per-wallet realized return, no decile-outcome table, no Gate-B/C output.
- Markout values may be computed **only** as inputs to the standardization scale σ̂ and to the positive-control MDE simulation — never aggregated to a per-wallet performance ranking or displayed.
- Output is inspected by a human only as the counts/rationale table below.

## Allowed computations
1. Fill and episode counts per wallet/coin/day/month.
2. Active-day and active-month coverage; universe size per candidate cutoff.
3. Ledger reconciliation (startpos, open/close classification, flips, partial reductions, phantom round trips) and the maker-heavy quarantine list.
4. Missingness / horizon completeness (wallet-days per horizon → J).
5. Timestamp completeness; episode overlap (non-overlapping counts).
6. Episode-count concentration across days/months.
7. Exclusion-flag precision/recall against the hand-labelled control set.
8. Positive-control **MDE** via the {0,3,5,10} bp injection grid on training folds (used only to pin the effective-N floor; the recovered numbers are simulated, not real wallet edges).

## Resolution rule per threshold
Each `[AUDIT-ONLY]` value is fixed by exactly one justification — **accounting correctness, minimum reliability, operational capacity, or data availability** — never by which value maximizes historical return.

## Required output: audit table (rule · rationale · wallets retained — NO performance)
| Threshold | Chosen value | Justification class | Wallets retained | Notes |
|---|---|---|---|---|
| Min active months | ⬜ | reliability | ⬜ | |
| J (wallet-days/horizon) | ⬜ | data availability | ⬜ | |
| Episode-count concentration cap | ⬜ | reliability | ⬜ | |
| Effective-N floor | ⬜ | reliability (MDE≤target) | ⬜ | from 0/3/5/10 grid |
| Liveness window | 30 d | operational | ⬜ | |
| Exclusion-flag thresholds | ⬜ | correctness | ⬜ | precision/recall attached |
| Start month / fold count | ⬜ | mechanical | ⬜ | derived from the above |

Once this table is filled and signed, the `[AUDIT-ONLY]` markers in `GATE_A_FROZEN_CONFIG.md` are replaced with the fixed values and Gate A can be frozen. Latency/cost stay unresolved (Gate-B/C only) and are frozen separately in `DEPLOYMENT_INPUT_FREEZE.md`.
