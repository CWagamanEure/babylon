# Wallet candidate list — pre-registered confirmatory run A1+A2 (2026-07-09)

**83 discovery candidates** (frozen before OOS), of which **31 were testable out-of-sample** and
**1 was CONFIRMED** (Tier B FDR + >5bp cost hurdle). Sorted by discovery p_adj (strongest first).

⚠️ **Asterisk:** the entire tape (2025-08-01 → 2026-06-29), including the OOS window, was explored before this
protocol was frozen. All results are provisional until the identical frozen protocol re-runs on July-2026+
(untouched) data. **Basket verdict (primary test): EARNED-NULL** — the 31-trader OOS basket = −2.18bp
CI[−7.76, +3.39], MDE 7.97bp ≤ 8bp care-about: the cohort as a whole carries no ≥8bp forward timing edge.
The list below is therefore a *candidate* list, not a confirmed-edge list — with one individual exception.

- Column meanings: **disc α** = discovery-period mean timing_alpha (bp/trade; post-entry price move at the
  frozen horizon minus the coin's own drift — in-sample and selection-inflated). **OOS α** = same quantity on
  the held-out Feb–Jun window at the frozen horizon only (the honest expectation). **disc net PnL** = the
  wallet's own realized net USD in discovery (reported, NOT a gate — amendment A1).
- "not testable OOS" = fewer than 5 episodes or 10 distinct days in Feb–Jun (went quiet; ~60% attrition).

> ⚠️ **CODE-BUG CAVEAT (added 2026-07-10):** this run used code carrying the fetchnumpy MaskedArray NULL
> bug (NULLs entered means as ~0.0; ≤0.45% of rows). The EARNED-NULL's MDE margin was razor-thin
> (7.97 ≤ 8.00), so the verdict was re-certified with fixed code on 2026-07-10 — see the certification
> rerun record. The bug's direction attenuates estimates; it cannot have fabricated the confirmed wallet.

## The list

| # | wallet | coin | hz | disc α (bp) | disc p_adj | disc days | disc net PnL $ | OOS α (bp) | OOS p | OOS days | status |
|---|--------|------|----|------------:|-----------:|----------:|---------------:|-----------:|------:|---------:|--------|
| 1 | `0x286629e6869366ec964ce57fe1309e63f92ce74c` | BTC | 1h | +11.1 | 9.999e-05 | 56 | -1,249 | — | — | — | not testable OOS |
| 2 | `0xfa93afdd831d58a25f2b2293c64f383200630a3c` | SOL | 2h | +52.6 | 0.0002 | 11 | +2,118 | — | — | — | not testable OOS |
| 3 | `0xdd5af39ee347c1e88d18dad44a8d572f35bb2359` | ETH | 1h | +47.6 | 0.0002 | 29 | -985 | +13.4 | 0.2201 | 21 | tested, ns |
| 4 | `0xc8093c82aa7d7029cbd7f9c321870f09393ac165` | ETH | 1h | +45.2 | 0.0002 | 14 | +1,928 | — | — | — | not testable OOS |
| 5 | `0x6f79997d2d38ecab5076a3ec50d08a915e3217cd` | BTC | 2h | +34.9 | 0.0002 | 11 | -2,346 | -38.2 | 1 | 19 | tested, ns |
| 6 | `0x1fbe7279da134c53fa521f5ee65891948e775e17` | BTC | 2h | +24.3 | 0.0002 | 20 | +34,233 | — | — | — | not testable OOS |
| 7 | `0xc8a9556508ec672f7c4a1fa2a9edc0326525c310` | HYPE | 2h | +90.4 | 0.0003 | 16 | +6,762 | +75.2 | 0.0276 | 10 | tested, ns |
| 8 | `0xd23a1758e354ed0cc76ac40fe263b6f78c0638bb` | ETH | 2h | +45.8 | 0.0003 | 41 | +2 | — | — | — | not testable OOS |
| 9 | `0x060667a46311126fed4f4bf4eea8ff6d4fa21a17` | HYPE | 1h | +29.9 | 0.0003 | 13 | +22,244 | — | — | — | not testable OOS |
| 10 | `0x0c6a8ac4cbea16a47bde05f372987acae54b3601` | BTC | 4h | +26.4 | 0.0003 | 29 | -27,071 | — | — | — | not testable OOS |
| 11 | `0xa04a4b7b7c37dbd271fdc57618e9cb9836b250bf` | SOL | 8h | +217.1 | 0.0004 | 11 | -14,766,554 | — | — | — | not testable OOS |
| 12 | `0x6caec2722936eab5aef261422aed0066748cfdd4` | SOL | 8h | +149.4 | 0.0004 | 13 | -15,624 | -14.3 | 1 | 32 | tested, ns |
| 13 | `0x62e5dd6c2594a4cb57a88ed84e5d55af58c33ba7` | BTC | 8h | +81.9 | 0.0004 | 28 | +631 | +39.6 | 0.1514 | 18 | tested, ns |
| 14 | `0x9ec8ddc60a9619d3e538c923cb26d610a9906328` | BTC | 8h | +77.4 | 0.0004 | 29 | +484 | +84.1 | 0.06019 | 16 | tested, ns |
| 15 | `0x7e08c8404f27823f666dfc6b94f8d58421356b00` | BTC | 8h | +65.3 | 0.0004 | 29 | +124 | — | — | — | not testable OOS |
| 16 | `0x3d2b551c44bba75c280cc0ce1150010739a5c5dc` | BTC | 8h | +52.1 | 0.0004 | 34 | +16,085 | — | — | — | not testable OOS |
| 17 | `0x309d4370d9eeb7de84db309594af872920f2f989` | BTC | 2h | +50.5 | 0.0004 | 15 | -5,615 | — | — | — | not testable OOS |
| 18 | `0x8ae4c5b303bc77c3aa68f2b71f37c9fa6d3b3d60` | BTC | 1h | +46.7 | 0.0004 | 15 | -579,906 | — | — | — | not testable OOS |
| 19 | `0x4dec0a851849056e259128464ef28ce78afa27f6` | BTC | 2h | +40.4 | 0.0004 | 17 | +33,694 | -2.7 | 1 | 23 | tested, ns |
| 20 | `0xcafcbbf25e5d67c7700d8c49b0431a64fd7e89a8` | BTC | 2h | +26.1 | 0.0004 | 11 | -189,210 | — | — | — | not testable OOS |
| 21 | `0x1a136792a33067b755cdef03ce77e5cdb702a5ae` | BTC | 2h | +25.9 | 0.0004 | 24 | +23,345 | -2.7 | 1 | 61 | tested, ns |
| 22 | `0xbc0c696d8833166a880ea1676b0e087f2871b118` | BTC | 1h | +22.1 | 0.0004 | 40 | -7,028 | — | — | — | not testable OOS |
| 23 | `0x34ad3f00c4abbe169ec1203be34de622671381af` | BTC | 1h | +18.9 | 0.0004 | 27 | -95,292 | — | — | — | not testable OOS |
| 24 | `0xc45ee9d1cf539603560989a4d60c3930862b7ec5` | HYPE | 1h | +41.4 | 0.0005999 | 17 | -10,075 | — | — | — | not testable OOS |
| 25 | `0xad227f63d34e7251c1d0ab65e64eeea07aee4e44` | HYPE | 1h | +35.3 | 0.0005999 | 30 | -418,459 | +25.2 | 0.09829 | 27 | tested, ns |
| 26 | `0x9838024318904510abb78a917e1d0c7b5733a1e7` | BTC | 1h | +20.7 | 0.0005999 | 37 | -2,136 | +6.1 | 0.2288 | 18 | tested, ns |
| 27 | `0xea73db6c22ca00a06b02be3ee4a37a68c55ee73c` | HYPE | 1h | +16.4 | 0.0006999 | 107 | +5,811 | +5.1 | 0.2812 | 83 | tested, ns |
| 28 | `0x970b053ebc59b7a200c5d568ca9ad970b1557464` | SOL | 8h | +144.5 | 0.0007999 | 11 | -12,474 | — | — | — | not testable OOS |
| 29 | `0xbdf43c21da554253d4d8d87ebeb9a642bc5a4296` | ETH | 8h | +114.5 | 0.0007999 | 23 | -6,051 | — | — | — | not testable OOS |
| 30 | `0x45c42fbd450b5506f8dc819d46036630fe75b81e` | ETH | 2h | +54.6 | 0.0007999 | 46 | -1,671 | -9.7 | 1 | 32 | tested, ns |
| 31 | `0x6ed1abc83e952d29fcf2185923160dacb12be23d` | BTC | 4h | +38.8 | 0.0007999 | 17 | +134 | — | — | — | not testable OOS |
| 32 | `0x44b47f095b8a5775a71075d83f7cf84e23f37eca` | ETH | 1h | +15.4 | 0.0007999 | 30 | -3,568 | — | — | — | not testable OOS |
| 33 | `0xbc32ec088b04bd15deeb0f8a2345cdc797e05aa1` | HYPE | 4h | +209.8 | 0.0008999 | 10 | -35,889 | — | — | — | not testable OOS |
| 34 | `0xe6d03e6287a1a5a148b083f5fa51ce82039c62de` | ETH | 2h | +33.0 | 0.0008999 | 16 | +5,344 | — | — | — | not testable OOS |
| 35 | `0xaeb0791ac2f5fa62891babf69d1445ef094fc176` | ETH | 1h | +45.4 | 0.0012 | 10 | +123,664 | — | — | — | not testable OOS |
| 36 | `0x102467338792d8125d05856c4b4b43117c857fe3` | ETH | 1h | +29.8 | 0.0012 | 45 | -3,466 | +41.0 | 0.1132 | 17 | tested, ns |
| 37 | `0xee83afee1163e049573a3d0c3951842a53a07fe8` | BTC | 1h | +27.2 | 0.0012 | 25 | -3,005 | -6.7 | 1 | 60 | tested, ns |
| 38 | `0xbd1f46ef3d40c7761fe82fc188239aafaa077d3e` | HYPE | 2h | +19.6 | 0.0012 | 88 | +10,259 | — | — | — | not testable OOS |
| 39 | `0xd2543d37644c289656d3e17ec7e22333a8dac176` | BTC | 4h | +16.9 | 0.0012 | 38 | -232,830 | +2.2 | 0.4677 | 21 | tested, ns |
| 40 | `0x3c63a0eb2546ef562e75b8a26d7465e035b3ff4f` | BTC | 1h | +9.7 | 0.0012 | 67 | -21,790 | +1.8 | 0.3316 | 86 | tested, ns |
| 41 | `0x126220f27cddaba57d903c51a94caf002b2ed355` | HYPE | 1h | +8.6 | 0.0012 | 67 | +71,352 | — | — | — | not testable OOS |
| 42 | `0xf67aa6c7ceacd0addba8660ac3a5bed7ccf65f2b` | HYPE | 1h | +43.1 | 0.0013 | 22 | -6,160 | -46.8 | 1 | 11 | tested, ns |
| 43 | `0x729f002b41e2ea645adee9722bd93e56b00847a3` | ETH | 1h | +14.9 | 0.0013 | 95 | -2,532 | -24.1 | 1 | 15 | tested, ns |
| 44 | `0xcc660e4a6b1b1766911bf5e75e10b6aa66683b48` | HYPE | 1h | +64.5 | 0.0014 | 21 | -10,484 | — | — | — | not testable OOS |
| 45 | `0xfa52ae675d240cde1714de0238425a0b73036922` | BTC | 2h | +24.4 | 0.0014 | 10 | -99,798 | — | — | — | not testable OOS |
| 46 | `0x54069d1a01434813617e09b9426b03971c0ce123` | HYPE | 4h | +98.4 | 0.0015 | 45 | +31,314 | +33.4 | 0.3122 | 10 | tested, ns |
| 47 | `0x0faef09b4deaedb0b99d68131f76acbef7cb4c8c` | BTC | 2h | +27.2 | 0.0015 | 26 | -236,557 | +1.1 | 0.4162 | 28 | tested, ns |
| 48 | `0xf3e1ede4a2cdda0c6ed192df7eef6242eb21139f` | HYPE | 2h | +105.5 | 0.0016 | 24 | -12,096 | — | — | — | not testable OOS |
| 49 | `0x653e5d056acf05de57eac247c72128d86d2f07f7` | BTC | 8h | +90.8 | 0.0016 | 23 | +170,749 | +25.4 | 0.2355 | 36 | tested, ns |
| 50 | `0xb10c1c1a94a7cc9fb78cc49a4db6c4560c9256e7` | ETH | 2h | +51.4 | 0.0016 | 22 | +19,030 | — | — | — | not testable OOS |
| 51 | `0xd5b68c9a6500f3d045aefd55e283ef974055345c` | HYPE | 4h | +113.6 | 0.0018 | 17 | +1,625 | — | — | — | not testable OOS |
| 52 | `0xcebcef2f1dbf9866d73d9fc4865b348d0e77fd76` | BTC | 4h | +51.8 | 0.002 | 29 | -5,172 | — | — | — | not testable OOS |
| 53 | `0xcdf0c733561c848fa99c6a3d25f6f07724e22bd1` | HYPE | 1h | +62.4 | 0.0022 | 17 | +67,777 | — | — | — | not testable OOS |
| 54 | `0x68939867dfc17a1c22da4e4605c8446302deef70` | HYPE | 2h | +54.2 | 0.0022 | 18 | -92,398 | — | — | — | not testable OOS |
| 55 | `0x451333eb2f8230cda918db136623da9c26acea0b` | HYPE | 1h | +16.8 | 0.0022 | 77 | -21,759 | +2.4 | 0.402 | 49 | tested, ns |
| 56 | `0x819e8ca8c93c557184b850e601d89ffd1616da03` | ETH | 4h | +81.1 | 0.0024 | 14 | +29,558 | — | — | — | not testable OOS |
| 57 | `0x17e064e7bc114478f81b312f2e868a8052855023` | ETH | 1h | +68.7 | 0.0024 | 11 | +223,431 | — | — | — | not testable OOS |
| 58 | `0xc219b4d0e3c0236a3effc48c4c6c9c3cd22deb1b` | BTC | 4h | +52.1 | 0.0024 | 15 | +1,587 | — | — | — | not testable OOS |
| 59 | `0x3e945441d530bf7095adee1396c7dcc58bf71cc3` | BTC | 8h | +38.5 | 0.0024 | 66 | -4,072 | -58.0 | 1 | 36 | tested, ns |
| 60 | `0x858b8ef7d4da0ecb6d701a3ab59bc28493bcf43a` | HYPE | 1h | +32.7 | 0.0024 | 41 | -1,968,462 | — | — | — | not testable OOS |
| 61 | `0xd7dc4b4ad3a7840f042a46d24b897fbe6ad14cb5` | HYPE | 1h | +30.7 | 0.0024 | 33 | +11,034 | +40.7 | 0.0002 | 40 | **CONFIRMED** |
| 62 | `0xe2cc27bf177079fd13dfe86cef913b77224ddc4a` | BTC | 1h | +21.5 | 0.0024 | 22 | +260 | — | — | — | not testable OOS |
| 63 | `0x307dff1325886cb81917a75802de16c5d70fd210` | ETH | 2h | +23.8 | 0.0026 | 31 | -9,746 | — | — | — | not testable OOS |
| 64 | `0xd283996b5c11511ec1514efe722d097f65a88430` | HYPE | 2h | +20.4 | 0.0027 | 82 | +4,530 | — | — | — | not testable OOS |
| 65 | `0xafccdc2f3cda6b5488a41a037614899793a468a4` | BTC | 2h | +17.1 | 0.0027 | 30 | -15,863 | -4.2 | 1 | 10 | tested, ns |
| 66 | `0xe76a541af000e2ae9818ddeb8fa8ca6c6eeb357b` | ETH | 8h | +168.8 | 0.0028 | 11 | -22,766 | — | — | — | not testable OOS |
| 67 | `0xe96f8730b2e6b4bbc143bfd8febd42412d5bd792` | SOL | 1h | +52.6 | 0.0028 | 35 | +5,939 | — | — | — | not testable OOS |
| 68 | `0xbd81ddd44a8731753d54497f1e4fedd4e15e2707` | BTC | 1h | +23.0 | 0.0028 | 13 | -189 | — | — | — | not testable OOS |
| 69 | `0xa0fb6ca98432421a4cdfc9c6c986d293c70bf34c` | ETH | 1h | +22.3 | 0.0028 | 44 | -7,354 | — | — | — | not testable OOS |
| 70 | `0x31dad49b57ed4a29a0b8f34e26065ccaf8b20a14` | BTC | 1h | +22.7 | 0.0029 | 11 | +167 | — | — | — | not testable OOS |
| 71 | `0x3a3acfa1f06d477b9953abffd5e1fc8d1fc0f3c3` | BTC | 4h | +60.5 | 0.0032 | 20 | +1,604 | — | — | — | not testable OOS |
| 72 | `0x6f09d72f4da40eafea107c81e1a77de90a3128f8` | BTC | 8h | +34.7 | 0.0036 | 18 | +3,201 | — | — | — | not testable OOS |
| 73 | `0xbfa317b7468a97e4e6a7a3c138b86ca0b7395477` | BTC | 2h | +11.8 | 0.0036 | 57 | +10,595 | -4.9 | 1 | 82 | tested, ns |
| 74 | `0x9a68d2fa5f39407e1c1e9119f56817019bddf38d` | BTC | 2h | +36.4 | 0.0036 | 12 | -21,753 | — | — | — | not testable OOS |
| 75 | `0x1fca7d0461e850a07071872e954dacafbdeccff3` | HYPE | 2h | +107.3 | 0.0038 | 12 | +14,100 | +2.0 | 0.4921 | 10 | tested, ns |
| 76 | `0x977da36660efc8131eb534bfacea35de15349337` | HYPE | 4h | +124.5 | 0.0039 | 11 | -29,368 | -44.7 | 1 | 16 | tested, ns |
| 77 | `0xb282f8129895eabb03891d430e2ad6167b281dac` | HYPE | 1h | +56.6 | 0.0039 | 12 | +50,616 | — | — | — | not testable OOS |
| 78 | `0xe5738503419278b37fd2d146237338ee80a94e9e` | BTC | 4h | +31.2 | 0.0039 | 26 | -6,939 | +21.4 | 0.1275 | 16 | tested, ns |
| 79 | `0x3bfadaec294d1a7fcaf4439fffbeb79e0e5c1337` | HYPE | 1h | +12.2 | 0.0039 | 138 | -5,248 | -7.1 | 1 | 51 | tested, ns |
| 80 | `0x0e17627caad10377891055a7e4dab175f581ea36` | ETH | 1h | +44.3 | 0.004 | 21 | -59,836 | — | — | — | not testable OOS |
| 81 | `0x064e89061ce80cb1b41a2d2963d48d2e8cabde4a` | BTC | 8h | +33.4 | 0.004 | 25 | +397,833 | -12.5 | 1 | 22 | tested, ns |
| 82 | `0x29bf1706478b99aabee227b33853cac98c8f44db` | SOL | 1h | +30.9 | 0.004 | 27 | +10,451 | — | — | — | not testable OOS |
| 83 | `0x113b979f2c7edbf01b028db68383c0e383ce0f6e` | ETH | 4h | +25.6 | 0.004 | 26 | -1,466 | — | — | — | not testable OOS |
## The single confirmed wallet

`0xd7dc4b4ad3a7840f042a46d24b897fbe6ad14cb5` — HYPE @1h. OOS: **+40.7bp over 40 distinct days, p=0.0002**,
survives BH-FDR q=0.10 among the 31 tested and clears the 5bp cost hurdle. Independently notable: it also
passed the user's original 11-filter screen and has positive realized net PnL in discovery (+$11k on HYPE in
p1; +$28k whole-window in earlier profiling) — the only wallet where markout, OOS replication, and profit
all align. Single survivor at q=0.10 ⇒ still carries false-discovery risk + the tape asterisk.

## Exact steps to reproduce this list

Full detail: `docs/CONFIRMATORY_RECIPE.md` (data layer) + `docs/CONFIRMATORY_PREREG.md` (frozen protocol +
amendments A1/A2). Condensed:

1. **Inputs** (prebuilt): fills tape `data/raw/fills/` (S3 node_fills_by_block restore); episode lake
   `data/derived/episodes/` (`python -m research.data.episodes_build all_carry`, schema
   `episodes_v1_lifecycle_enriched_2026-07-07`); per-minute price panel `data/raw/asset_ctx/` (oracle_px).
2. **Markout backfill**: `python -m research.data.markout all` — per episode (excl. inherited_basis):
   entry = first oracle tick strictly after open_ts; raw_markout_h = dir·(P(entry+h)−P(entry))/P(entry)·1e4
   at h ∈ {5m…48h}, ASOF matches valid only within 90s staleness.
3. **Drift baseline**: `python -m research.data.mu_baseline all` — per-minute forward returns fwd_ret_h per coin.
4. **Discovery** (`python -m research.data.confirmatory discover`), window [2025-08-01, 2026-02-01):
   - timing_alpha per episode = raw_markout_h − dir·μ_h(coin, period), μ period-scoped (t+h ≤ period end);
     episodes require entry in window, close ≤ window end, not entry_after_close, entry_lag ≤ 90s.
   - Eligibility E1–E6 (episode lake, close_ts in window): ≥200 fills, ≥8 ISO weeks, ≥$1M notional,
     twap-flag share <30%, liq share <10%, taker share ≥50%. (A1: NO PnL gate.) → 11,562 wallet-coins.
   - E8: candidate horizons {1h,2h,4h,8h; HYPE-8h excluded} restricted to horizon ≤ 4× median hold;
     per horizon require ≥5 episodes and ≥10 distinct UTC days.
   - S1: best_horizon = argmax mean timing_alpha; require > 8bp. S3: mean excl. best day > 0.
   - S4: day-block bootstrap (B=10,000, seed 20260709) one-sided p at best horizon, ×n_horizons Bonferroni.
     → 4,058 pass S1–S3. BH-FDR **q=0.20** (A2) → **83 candidates**, frozen to
     `data/derived/confirmatory/candidates.parquet` before any OOS computation.
5. **OOS confirmation** (`python -m research.data.confirmatory oos`), window [2026-02-01, 2026-06-29),
   frozen horizon only, OOS-scoped μ, seed 20260710:
   - Testability: ≥5 episodes, ≥10 distinct days → 31/83.
   - Tier A (primary): per-day basket mean, day-block bootstrap → −2.18bp CI[−7.76,+3.39] MDE 7.97 → EARNED-NULL.
   - Tier B: per-trader day-block bootstrap H0 mean≤0, BH q=0.10, then OOS est > 5bp cost → 1 confirmed.
   - Style attribution (hour-of-day-matched null, B=1,000): p=0.71 → basket not distinguishable from footprint.
   - Output `data/derived/confirmatory/oos_results.parquet`.

Deterministic: seeded bootstraps, deterministic argmax tie-break (1h→8h order), hash-bucketed writes — a rerun
on the same tape reproduces every number above exactly *with the code as of this run*.
