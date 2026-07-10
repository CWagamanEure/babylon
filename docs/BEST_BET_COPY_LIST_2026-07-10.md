# BEST-BET COPY-TRADING CANDIDATES — 2026-07-10

**What this is:** the currently-active wallet-coin pairs most likely to continue showing positive copyable
markout next month, per everything this research arc established. **What this is NOT:** proven skilled
traders — no individual wallet on this list is statistically established, and the process that generates it
is itself an *underpowered, HYPE-concentrated positive* (family-adjusted p≈0.17) under live forward
adjudication (`docs/FORWARD_PAPER_PREREG.md`).

**Construction (annotation of already-validated selections — no new selector):**
base = the frozen rolling L=6 top-20 (`live_basket.parquet`, sha 1e53a112cac97976), tiered by the three
evidence-backed corroboration signals: (1) **recurrence** — re-selected across consecutive monthly rolling
windows (the strongest sub-signal found, +43bp net in its look-ahead-tainted form); (2) **cross-selector
consensus** — also top-20 under the independent persistence-score ranking on the same trailing window
(near-disjoint methods agreeing, the ex-HYPE-corroboration logic); (3) **coin discount** — HYPE pairs carry
regime risk (HYPE drove the backtest; ex-HYPE the edge is ~+1-2bp net, thin).

## TIER A — corroborated (best bets)

| wallet | coin@hz | disc gross | why |
|---|---|---|---|
| `0xf4ea2934a85d1f0b5910f5ab8b545bcf724b48f4` | BTC@2h | +22.7 | **consensus (persistence rank 3), non-HYPE** |
| `0x01e0e54736c7409ba2ff0aa9188cb1b4fb0a4f6b` | BTC@8h | +44.3 | **consensus (persistence rank 11), non-HYPE** |
| `0xd7dc4b4ad3a7840f042a46d24b897fbe6ad14cb5` | HYPE@2h | +53.6 | **recurrence 3/6 + the single cross-METHOD survivor of the strict prereg protocol + positive own-PnL** — the most persistent name in the entire investigation |
| `0x404c2909fdcf65a0c5bcfbc786b57e944a1c732b` | BTC@2h | +51.9 | recurrence 3/6, non-HYPE |
| `0xd6283660c72ef0a9b3be39fb392eb9812279c1a3` | HYPE@4h | +117.5 | recurrence 3/6 (HYPE discount applies) |
| `0xef96d013bdb1a5dfe553999f19b5091b9a299383` | ETH@8h | +83.8 | recurrence 2/6, non-HYPE |
| `0xcfbb55fcb05534e21f3a87a095c2dbd3df6bfcd7` | HYPE@8h | +155.8 | recurrence 2/6 (HYPE discount; biggest number = most winner's-curse-inflated) |

## TIER B — current selection, uncorroborated (the rest of the live basket)

BTC: `0xf041b8e7…319f`@1h +24.5 · `0xb381b8bf…6290`@8h +49.5 · `0x432bbc86…2f05`@4h +41.4 ·
`0x5d0ea09c…72e8`@8h +103.3 · `0xb54ddcd2…9f80`@8h +63.0 · `0x672dc456…6ca1`@4h +43.6 ·
`0xe20307dc…0d3d`@1h +14.0 · `0xb2a96802…d28f`@8h +53.8
ETH: `0x8e6ed79c…05b4`@1h +33.4 · SOL: `0xcaad4d59…0ef4`@1h +91.5 · `0xf096efd7…7553`@8h +78.9
HYPE: `0xee57a50f…0ee0`@2h +123.6 · `0xad3749b9…d615`@8h +47.4

## TIER C — steady-cohort watchlist (persistence top-20 not in the live basket)

Operationally most reliable (7% attrition cohort) but measured edge below cost; smaller expected markout,
much higher probability of still trading next quarter. Notables: `0xd595710a…6d89` HYPE +45.8 ·
`0x45bafad5…9082` HYPE +51.6 · `0x25f1d56b…32a3` ETH +24.6 · `0xc7f10fbe…deb0` BTC +20.6
(full set: run `score_window` on the trailing window; heavy HYPE concentration — same discount applies).

## How to copy them (the rules the evidence forced)
1. **Copy ENTRIES only; exit on the frozen horizon clock** (mirroring their exits kills the edge — measured).
2. A 1–2 minute delay costs ~nothing (99% capture); no latency investment needed.
3. **Expect ~93–97% of the discovery numbers to evaporate** — a "+50bp" discovery wallet is a +5–15bp
   forward wallet at best. Costs (~10.5bp RT at base tier) eat most of that; fee tiers matter more than picks.
4. **Refresh monthly under the same frozen rules** — ~half of any list goes quiet within months; the
   refresh IS the strategy. A static version of this list decays to nothing (measured, repeatedly).
5. HYPE pairs: halve your trust per bp (regime concentration).
6. Verdict authority stays with the forward paper run — nothing here is confirmed until it earns it there.
