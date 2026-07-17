# WALLET ATTRIBUTION — per-wallet decomposition of the two frozen books

**STAMP: DESCRIPTIVE decomposition of frozen books, burned folds 202511-202606; ex-post rankings (winner/loser curse); trait tests hypothesis-grade, uncorrected; no new selection derived from this.**

Behavior metrics = full-window (202508-202605) lake wallet_coin_day/open_entries descriptors; `gapMed` = median same-coin inter-entry gap in minutes (re-trade cadence proxy, NOT true hold). $ figures assume $2,500 equal units. Costs: 5.5bp (M) / 21.5bp (P) RT per trade/unit.


## MAJORS-NATIVE K30 @8h (M)

Book: 51 wallets, 5,494 trades/units, net $+27,675 (+20.1bp/trade); wallet-level gross loss $9,722 / gross win $37,397.

Loss share worst 1/3/5: 35% / 66% / 76%. Win share best 1/3/5: 19% / 51% / 67%.


Drop-worst-K (ex-post): 1:+31,068$(+24.6bp) 2:+33,576$(+27.6bp) 3:+34,129$(+28.1bp) 4:+34,671$(+28.8bp) 5:+35,046$(+30.5bp) 6:+35,392$(+30.9bp) 7:+35,690$(+35.6bp) 8:+35,968$(+35.9bp) 9:+36,218$(+37.2bp) 10:+36,448$(+37.7bp)

Drop-best-K (ex-post): 1:+20,500$(+15.8bp) 2:+14,138$(+11.2bp) 3:+8,673$(+7.3bp) 4:+5,315$(+4.8bp) 5:+2,701$(+2.8bp) 6:+643$(+0.7bp) 7:-1,062$(-1.3bp) 8:-2,492$(-3.2bp) 9:-3,822$(-5.0bp) 10:-4,860$(-8.4bp)


| distribution | n | mean | p10 | p25 | med | p75 | p90 | skew | %>0 |
|---|---|---|---|---|---|---|---|---|---|
| per_wallet_net_bp | 51 | -10.42 | -77.46 | -31.05 | -2.12 | 34.49 | 72.86 | -1.45 | 49% |
| per_wallet_net_usd | 51 | 542.65 | -345.86 | -92.38 | -5.79 | 655.22 | 2058.8 | 1.89 | 49% |
| per_trade_net_bp | 5494 | 20.15 | -400.06 | -192.82 | 4.95 | 200.08 | 454.16 | 0.5 | 51% |

### All wallets (worst -> best by net $)

| wallet | net $ | n | bp/tr | folds | loss% | win% | t | nd | tr/d | f/d | taker | brd | maj% | medNotl | gapMed(m) | liq | archetype |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0xa899133b… | -3,393 | 445 | -30.5 | 1 | 35% | 0% | 9.43 | 86.0 | 16.65 | 101.28 | 0.2817 | 34 | 0.3522 | 200.5 | 520.7 | 18 | diversified alt grinder (maker-lean, high breadth) |
| 0x0bb81e51… | -2,508 | 190 | -52.8 | 2 | 26% | 0% | 8.27 | 68.0 | 5.608 | 19.92 | 0.3491 | 1 | 1.0 | 123.5 | 54.4 | 0 | single-alt specialist |
| 0xa9fef2e3… | -553 | 9 | -245.7 | 1 | 6% | 0% | 7.5 | 53.0 | 2.494 | 15.25 | 0.9895 | 5 | 0.8102 | 1638.0 | 268.6 | 5 | — |
| 0x68350a86… | -542 | 28 | -77.5 | 1 | 6% | 0% | 7.05 | 80.0 | 5.578 | 21.03 | 0.3731 | 1 | 1.0 | 255.6 | 47.8 | 0 | — |
| 0x4331ca6f… | -375 | 227 | -6.6 | 1 | 4% | 0% | 8.2 | 39.0 | 9.194 | 1155.58 | 0.7925 | 5 | 0.9509 | 4077.7 | 35.3 | 0 | — |
| 0x3ce3794d… | -346 | 21 | -65.9 | 1 | 4% | 0% | 6.5 | 35.0 | 2.842 | 22.55 | 0.993 | 7 | 0.4723 | 200.8 | 181.0 | 0 | — |
| 0x3cb800a5… | -298 | 562 | -2.1 | 5 | 3% | 0% | 7.89 | 75.2 | 5.481 | 22.45 | 0.3838 | 1 | 1.0 | 327.3 | 51.2 | 0 | single-alt specialist |
| 0xfdbaf653… | -278 | 5 | -222.4 | 1 | 3% | 0% | 6.1 | 47.0 | 0.883 | 158.79 | 0.178 | 16 | 0.3341 | 1476.0 | 10951.5 | 0 | — |
| 0x47096aea… | -250 | 112 | -8.9 | 1 | 3% | 0% | 8.1 | 75.0 | 8.907 | 70.27 | 0.3647 | 1 | 1.0 | 110.0 | 27.4 | 0 | — |
| 0xd72f09cc… | -230 | 31 | -29.7 | 1 | 2% | 0% | 7.66 | 29.0 | 1.485 | 103.85 | 0.622 | 4 | 0.9901 | 1326.9 | 535.0 | 11 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x78052a12… | -203 | 14 | -57.9 | 2 | 2% | 0% | 6.22 | 53.0 | 1.178 | 10.91 | 0.7933 | 19 | 0.9539 | 2709.3 | 794.4 | 0 | — |
| 0x988fd4e6… | -171 | 1 | -682.3 | 1 | 2% | 0% | 6.2 | 52.0 | 0.123 | 3.1 | 0.3722 | 2 | 0.9314 | 232.5 | 5540.6 | 1 | — |
| 0x7e6beebe… | -101 | 14 | -28.9 | 1 | 1% | 0% | 6.4 | 77.0 | 1.5 | 36.7 | 0.3711 | 31 | 0.9746 | 1028.9 | 1237.8 | 0 | — |
| 0x1458ab4a… | -84 | 1 | -334.8 | 1 | 1% | 0% | 10.04 | 49.0 | 3.551 | 27.86 | 0.6374 | 6 | 0.79 | 34.3 | 324.8 | 0 | micro dust grinder (tiny taker accounts) |
| 0x402740cb… | -77 | 57 | -5.4 | 1 | 1% | 0% | 7.71 | 86.0 | 6.719 | 35.54 | 0.9006 | 2 | 1.0 | 51.4 | 75.0 | 0 | — |
| 0x87d93a74… | -64 | 57 | -4.5 | 2 | 1% | 0% | 7.4 | 53.0 | 2.452 | 79.47 | 0.7581 | 1 | 1.0 | 6559.0 | 74.3 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0xdb923b47… | -63 | 8 | -31.6 | 1 | 1% | 0% | 6.93 | 25.0 | 0.462 | 4.56 | 0.6742 | 1 | 1.0 | 7662.2 | 3110.7 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0xb2e3acb1… | -49 | 1 | -194.3 | 1 | 0% | 0% | 7.47 | 62.0 | 0.176 | 15.39 | 0.5281 | 1 | 1.0 | 893.3 | 5130.6 | 12 | single-alt specialist |
| 0xa775d1bd… | -48 | 3 | -63.6 | 2 | 0% | 0% | 7.91 | 90.0 | 24.639 | 20700.77 | 0.4986 | 4 | 0.9646 | 240.0 | 5.2 | 0 | HFT / market-maker bot (institutional scale) |
| 0xfed45940… | -26 | 11 | -9.6 | 2 | 0% | 0% | 7.57 | 79.5 | 0.317 | 29.22 | 0.6171 | 22 | 0.9926 | 1112.6 | 2373.8 | 8 | diversified alt grinder (maker-lean, high breadth) |
| 0x7ccf204e… | -18 | 4 | -18.3 | 1 | 0% | 0% | 6.28 | 73.0 | 0.582 | 73.9 | 0.5494 | 59 | 0.5345 | 1096.4 | 14562.9 | 151 | — |
| 0xd9ffc44a… | -12 | 1 | -48.4 | 1 | 0% | 0% | 8.85 | 23.0 | 0.649 | 35.89 | 0.3387 | 4 | 0.9623 | 5852.4 | 1352.0 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x5bd30e48… | -11 | 1 | -42.6 | 1 | 0% | 0% | 9.99 | 92.0 | 1.307 | 50.47 | 0.1362 | 7 | 0.9925 | 1481.0 | 623.4 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0xfe8f04b3… | -10 | 3 | -13.1 | 1 | 0% | 0% | 7.24 | 72.0 | 2.738 | 23.82 | 0.9786 | 14 | 0.9314 | 2576.2 | 336.5 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x1003d8c5… | -7 | 3 | -9.3 | 2 | 0% | 0% | 6.62 | 59.5 | 0.207 | 12.05 | 0.104 | 24 | 0.9945 | 1164.7 | 11160.2 | 0 | — |
| 0xa68011e9… | -6 | 3 | -7.7 | 1 | 0% | 0% | 7.96 | 15.0 | 0.136 | 5.55 | 0.4836 | 1 | 1.0 | 1211.0 | 20673.6 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x545d57c7… | +15 | 6 | +9.8 | 1 | 0% | 0% | 8.64 | 88.0 | 4.448 | 315.28 | 0.6063 | 28 | 0.2009 | 563.1 | 136.8 | 9 | diversified alt grinder (maker-lean, high breadth) |
| 0x95e2687b… | +27 | 3 | +35.4 | 1 | 0% | 0% | 6.06 | 53.0 | 0.088 | 21.75 | 0.466 | 3 | 1.0 | 2315.4 | 41720.4 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x00edc3e6… | +30 | 4 | +29.9 | 2 | 0% | 0% | 6.78 | 67.5 | 0.223 | 8.05 | 0.3275 | 1 | 1.0 | 595.3 | 5181.7 | 0 | single-alt specialist |
| 0x565b1c32… | +50 | 1 | +200.1 | 1 | 0% | 0% | 6.43 | 82.0 | 0.582 | 12.57 | 0.312 | 42 | 0.7174 | 161.2 | 2933.7 | 0 | diversified alt grinder (maker-lean, high breadth) |
| 0x1b53fb81… | +140 | 47 | +11.9 | 1 | 0% | 0% | 6.84 | 43.0 | 2.211 | 20.92 | 0.8292 | 31 | 0.8887 | 1985.7 | 219.4 | 0 | — |
| 0xb4de3608… | +149 | 22 | +27.0 | 1 | 0% | 0% | 7.25 | 32.0 | 4.571 | 15.26 | 0.554 | 10 | 0.3382 | 850.2 | 509.9 | 26 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x81f6b887… | +168 | 45 | +14.9 | 3 | 0% | 0% | 6.5 | 72.0 | 1.174 | 285.63 | 0.4691 | 34 | 0.8301 | 1500.5 | 1829.4 | 0 | diversified alt grinder (maker-lean, high breadth) |
| 0xad68fabb… | +222 | 45 | +19.7 | 2 | 0% | 1% | 7.19 | 65.5 | 1.192 | 55.47 | 0.9856 | 20 | 0.9968 | 739.6 | 1285.3 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x6049ddfd… | +226 | 2 | +452.6 | 1 | 0% | 1% | 8.14 | 43.0 | 0.531 | 108.97 | 0.4231 | 10 | 0.7611 | 1722.7 | 5150.9 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0xa297d934… | +256 | 28 | +36.6 | 1 | 0% | 1% | 6.14 | 37.0 | 3.189 | 32.41 | 0.9998 | 19 | 0.8477 | 499.8 | 827.6 | 11 | — |
| 0x6f4823e6… | +428 | 48 | +35.6 | 1 | 0% | 1% | 6.34 | 53.0 | 3.685 | 500.24 | 0.7234 | 22 | 0.9838 | 1070.9 | 80.2 | 0 | — |
| 0x55fb9136… | +556 | 49 | +45.4 | 1 | 0% | 1% | 11.62 | 30.0 | 16.946 | 166.27 | 0.4857 | 1 | 1.0 | 1500.1 | 8.8 | 0 | single-alt specialist |
| 0xe6e65bce… | +754 | 53 | +56.9 | 3 | 0% | 2% | 6.73 | 73.7 | 2.014 | 15.1 | 0.9973 | 2 | 1.0 | 834.6 | 480.0 | 0 | — |
| 0x28135406… | +841 | 18 | +186.9 | 2 | 0% | 2% | 6.71 | 36.0 | 1.248 | 341.12 | 0.3761 | 27 | 0.8455 | 538.0 | 2234.8 | 4 | — |
| 0x7cb88319… | +999 | 119 | +33.6 | 1 | 0% | 3% | 8.1 | 16.0 | 5.694 | 21.34 | 0.3371 | 1 | 1.0 | 304.1 | 53.0 | 0 | single-alt specialist |
| 0xa1b6d8ef… | +1,038 | 741 | +5.6 | 3 | 0% | 3% | 7.45 | 91.3 | 19.917 | 111.72 | 0.4246 | 24 | 0.4267 | 542.8 | 116.0 | 0 | diversified alt grinder (maker-lean, high breadth) |
| 0x329c787b… | +1,330 | 73 | +72.9 | 2 | 0% | 4% | 6.43 | 84.5 | 6.685 | 555.11 | 0.7208 | 23 | 0.9303 | 1984.7 | 44.1 | 1 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x0c657a1e… | +1,430 | 202 | +28.3 | 2 | 0% | 4% | 8.15 | 53.0 | 13.504 | 56.13 | 0.4402 | 94 | 0.8104 | 71.3 | 582.4 | 45 | diversified alt grinder (maker-lean, high breadth) |
| 0xc22db2c0… | +1,705 | 208 | +32.8 | 3 | 0% | 5% | 6.89 | 80.0 | 2.534 | 22.4 | 0.4474 | 5 | 0.7964 | 303.1 | 250.0 | 0 | — |
| 0xafe62f92… | +2,059 | 380 | +21.7 | 3 | 0% | 6% | 7.87 | 76.0 | 5.32 | 21.1 | 0.3858 | 2 | 0.9997 | 425.3 | 47.6 | 1 | single-alt specialist |
| 0xdc899ed4… | +2,614 | 516 | +20.3 | 4 | 0% | 7% | 7.84 | 63.8 | 6.474 | 28.84 | 0.4326 | 1 | 1.0 | 744.9 | 33.9 | 0 | single-alt specialist |
| 0xae6b807e… | +3,358 | 330 | +40.7 | 3 | 0% | 9% | 9.91 | 66.0 | 4.01 | 95.37 | 0.6515 | 1 | 1.0 | 1093.8 | 116.7 | 0 | single-alt specialist |
| 0x1d14c622… | +5,465 | 302 | +72.4 | 3 | 0% | 15% | 7.21 | 53.0 | 5.611 | 24.9 | 0.4174 | 1 | 1.0 | 749.6 | 44.1 | 0 | single-alt specialist |
| 0x7d4886f3… | +6,362 | 146 | +174.3 | 2 | 0% | 17% | 7.49 | 85.0 | 5.846 | 31.4 | 0.4149 | 1 | 1.0 | 683.9 | 45.7 | 0 | single-alt specialist |
| 0x6c30f718… | +7,175 | 294 | +97.6 | 3 | 0% | 19% | 11.31 | 47.0 | 5.531 | 34.49 | 0.4663 | 1 | 1.0 | 1136.4 | 51.0 | 0 | single-alt specialist |


### Worst-5 vs best-5 medians (Mann-Whitney p, uncorrected)

| metric | worst5 med | best5 med | MW p |
|---|---|---|---|
| trades_per_day | 5.608 | 5.611 | 0.8345 |
| fills_per_day | 21.03 | 31.4 | 0.6761 |
| taker_share | 0.373 | 0.433 | 0.6761 |
| coin_breadth | 5.0 | 1.0 | 0.0707 |
| majors_notl_share | 0.951 | 1.0 | 0.072 |
| n_liq | 0.0 | 0.0 | 0.1797 |
| med_entry_notl | 255.6 | 749.6 | 0.6761 |
| med_gap_min | 54.4 | 45.7 | 0.2963 |
| avg_gap_min | 532.1 | 291.3 | 0.0367 |
| active_days | 160.0 | 116.0 | 0.5309 |
| total_notional | 2358094.0 | 6017223.0 | 0.5309 |
| form_t_mean | 8.2 | 7.84 | 0.8345 |
| form_nd_mean | 68.0 | 63.8 | 0.7533 |
| n_trades | 190.0 | 302.0 | 0.2101 |


## PYRAMID-ALT ladder (P)

Book: 104 wallets, 3,668 trades/units, net $+233 (+0.2bp/trade); wallet-level gross loss $32,554 / gross win $32,787.

Loss share worst 1/3/5: 23% / 45% / 54%. Win share best 1/3/5: 9% / 19% / 28%.


Drop-worst-K (ex-post): 1:+7,595$(+10.9bp) 2:+11,492$(+17.6bp) 3:+14,869$(+26.8bp) 4:+16,392$(+30.4bp) 5:+17,830$(+33.7bp) 6:+19,200$(+38.6bp) 7:+20,241$(+42.0bp) 8:+21,147$(+44.5bp) 9:+22,045$(+48.0bp) 10:+22,881$(+49.9bp)

Drop-best-K (ex-post): 1:-2,662$(-3.0bp) 2:-4,425$(-5.0bp) 3:-6,021$(-6.8bp) 4:-7,544$(-8.6bp) 5:-9,044$(-10.5bp) 6:-10,391$(-12.2bp) 7:-11,610$(-13.6bp) 8:-12,816$(-15.1bp) 9:-14,013$(-16.6bp) 10:-15,206$(-18.2bp)


| distribution | n | mean | p10 | p25 | med | p75 | p90 | skew | %>0 |
|---|---|---|---|---|---|---|---|---|---|
| per_wallet_net_bp | 104 | 28.65 | -170.6 | -66.23 | 31.5 | 114.32 | 300.81 | -0.46 | 59% |
| per_wallet_net_usd | 104 | 2.24 | -809.63 | -231.39 | 79.5 | 440.25 | 978.91 | -3.03 | 59% |
| per_trade_net_bp | 3668 | 0.25 | -485.25 | -221.32 | 5.43 | 211.52 | 487.59 | 0.03 | 51% |

### All wallets (worst -> best by net $)

| wallet | net $ | n | bp/tr | folds | loss% | win% | t | nd | tr/d | f/d | taker | brd | maj% | medNotl | gapMed(m) | liq | archetype |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0x223537ac… | -7,362 | 888 | -33.2 | 7 | 23% | 0% | 9.41 | 91.0 | 5.368 | 22403.44 | 0.4056 | 38 | 0.0 | 585.4 | 273.3 | 3 | HFT / market-maker bot (institutional scale) |
| 0x3979bdf7… | -3,897 | 174 | -89.6 | 2 | 12% | 0% | 6.11 | 45.0 | 23.915 | 816.49 | 0.9998 | 136 | 0.1133 | 810.5 | 313.1 | 0 | — |
| 0xa1b6d8ef… | -3,377 | 390 | -34.6 | 6 | 10% | 0% | 7.85 | 91.2 | 19.917 | 111.72 | 0.4246 | 24 | 0.4267 | 542.8 | 116.0 | 0 | diversified alt grinder (maker-lean, high breadth) |
| 0x2d6efe28… | -1,523 | 61 | -99.9 | 1 | 5% | 0% | 7.02 | 90.0 | 33.692 | 660.31 | 0.6105 | 161 | 0.1097 | 251.9 | 387.9 | 0 | — |
| 0x11eee2e0… | -1,438 | 40 | -143.8 | 1 | 4% | 0% | 5.55 | 92.0 | 3.163 | 176.7 | 0.9227 | 50 | 0.7755 | 1331.6 | 1525.3 | 1204 | — |
| 0xad64f33f… | -1,369 | 125 | -43.8 | 2 | 4% | 0% | 6.96 | 68.0 | 3.522 | 83.03 | 0.9994 | 25 | 0.5011 | 1221.1 | 956.5 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x72795661… | -1,041 | 63 | -66.1 | 5 | 3% | 0% | 9.38 | 90.6 | 5.332 | 28307.52 | 0.4192 | 58 | 0.4132 | 867.9 | 158.4 | 20 | HFT / market-maker bot (institutional scale) |
| 0x9da99bb7… | -906 | 24 | -151.1 | 1 | 3% | 0% | 8.81 | 88.7 | 1.135 | 108.47 | 0.3483 | 31 | 0.008 | 263.5 | 877.6 | 37 | diversified alt grinder (maker-lean, high breadth) |
| 0xc9b21c27… | -898 | 64 | -56.1 | 2 | 3% | 0% | 5.75 | 89.0 | 5.827 | 202.78 | 0.4594 | 145 | 0.1337 | 20.3 | 500.1 | 49 | — |
| 0xf19f167d… | -836 | 3 | -1115.2 | 1 | 3% | 0% | 7.71 | 27.0 | 4.846 | 29.58 | 0.9997 | 17 | 0.8088 | 1504.4 | 68.7 | 1 | — |
| 0xd8f59a3a… | -826 | 193 | -17.1 | 2 | 3% | 0% | 7.16 | 79.0 | 11.46 | 56.12 | 0.9168 | 31 | 0.1657 | 250.0 | 100.7 | 7 | diversified alt grinder (maker-lean, high breadth) |
| 0xa9d7045c… | -771 | 3 | -1027.7 | 1 | 2% | 0% | 6.38 | 52.0 | 2.924 | 129.01 | 0.7469 | 148 | 0.3316 | 457.5 | 3955.7 | 158 | — |
| 0x3454c7aa… | -741 | 10 | -296.6 | 2 | 2% | 0% | 8.82 | 71.5 | 1.141 | 20.54 | 0.8272 | 33 | 0.0713 | 518.6 | 2362.3 | 22 | diversified alt grinder (maker-lean, high breadth) |
| 0xc6fb6956… | -729 | 23 | -126.8 | 1 | 2% | 0% | 7.37 | 38.5 | 1.354 | 88.2 | 0.5215 | 12 | 0.2321 | 284.0 | 272.1 | 62 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0xf55f9ad7… | -709 | 61 | -46.5 | 1 | 2% | 0% | 8.24 | 44.0 | 5.554 | 70.24 | 0.2391 | 21 | 0.4363 | 426.6 | 623.8 | 0 | diversified alt grinder (maker-lean, high breadth) |
| 0xaa1a3d25… | -639 | 28 | -91.2 | 2 | 2% | 0% | 6.29 | 51.0 | 1.511 | 18.86 | 0.9977 | 5 | 0.2745 | 1325.5 | 550.5 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0xb65dd7c5… | -573 | 14 | -163.8 | 2 | 2% | 0% | 6.69 | 75.5 | 3.264 | 35.76 | 0.1438 | 17 | 0.3385 | 306.8 | 2100.5 | 0 | — |
| 0x02938da2… | -539 | 3 | -718.7 | 1 | 2% | 0% | 7.25 | 52.0 | 2.03 | 39.14 | 0.6689 | 44 | 0.8884 | 2156.3 | 555.3 | 0 | — |
| 0x02a5ebb4… | -537 | 75 | -28.6 | 2 | 2% | 0% | 8.85 | 65.0 | 4.25 | 15.87 | 0.9911 | 2 | 0.0011 | 352.3 | 125.1 | 0 | single-alt specialist |
| 0x587d941d… | -522 | 20 | -104.5 | 1 | 2% | 0% | 6.08 | 45.0 | 3.829 | 17.92 | 1.0 | 33 | 0.0898 | 360.4 | 4492.5 | 0 | — |
| 0xd262ce15… | -491 | 30 | -65.5 | 3 | 2% | 0% | 5.66 | 56.8 | 1.518 | 24.22 | 0.9996 | 5 | 0.1757 | 1201.0 | 505.6 | 0 | — |
| 0xb5f2fec8… | -302 | 7 | -172.4 | 2 | 1% | 0% | 7.06 | 90.3 | 3.077 | 15.43 | 0.9738 | 185 | 0.1706 | 98.9 | 20408.4 | 1 | diversified alt grinder (maker-lean, high breadth) |
| 0x0a391e4f… | -288 | 13 | -88.7 | 2 | 1% | 0% | 6.05 | 64.7 | 3.758 | 275.13 | 0.6292 | 26 | 0.9291 | 1084.5 | 72.6 | 0 | — |
| 0xe006b02e… | -263 | 3 | -350.6 | 1 | 1% | 0% | 7.33 | 71.0 | 3.337 | 112.11 | 0.7742 | 34 | 0.9081 | 1997.1 | 147.4 | 18 | — |
| 0x2edaa909… | -254 | 1 | -1016.0 | 1 | 1% | 0% | 6.14 | 61.0 | 29.903 | 209.4 | 0.7263 | 163 | 0.002 | 798.4 | 142.2 | 2 | — |
| 0x2d322644… | -243 | 3 | -323.4 | 1 | 1% | 0% | 7.04 | 59.0 | 4.215 | 24.75 | 0.9582 | 150 | 0.3304 | 499.2 | 2117.1 | 19 | — |
| 0x9a3ec40c… | -228 | 6 | -151.8 | 1 | 1% | 0% | 6.51 | 58.5 | 4.081 | 25.19 | 0.8401 | 33 | 0.2153 | 221.7 | 2125.3 | 0 | — |
| 0x809fb2bd… | -197 | 80 | -9.8 | 1 | 1% | 0% | 5.08 | 39.0 | 49.127 | 281.45 | 1.0 | 185 | 0.0253 | 494.0 | 120.5 | 13 | — |
| 0x7e6beebe… | -152 | 3 | -203.3 | 1 | 0% | 0% | 4.85 | 80.0 | 1.5 | 36.7 | 0.3711 | 31 | 0.9746 | 1028.9 | 1237.8 | 0 | — |
| 0xee621cac… | -150 | 9 | -66.6 | 1 | 0% | 0% | 6.15 | 38.0 | 3.712 | 60.87 | 0.9764 | 25 | 0.6588 | 1036.9 | 547.1 | 3 | — |
| 0xa880d6cc… | -105 | 105 | -4.0 | 1 | 0% | 0% | 8.65 | 91.0 | 1.528 | 22633.95 | 0.345 | 25 | 0.8628 | 857.0 | 583.7 | 0 | HFT / market-maker bot (institutional scale) |
| 0x7ccf204e… | -103 | 6 | -68.9 | 2 | 0% | 0% | 6.55 | 90.5 | 0.582 | 73.9 | 0.5494 | 59 | 0.5345 | 1096.4 | 14562.9 | 151 | — |
| 0x471b037b… | -97 | 9 | -43.3 | 1 | 0% | 0% | 6.16 | 84.0 | 3.871 | 18.15 | 1.0 | 34 | 0.0771 | 250.4 | 4101.9 | 0 | — |
| 0x714f7e72… | -91 | 2 | -181.2 | 1 | 0% | 0% | 6.18 | 19.0 | 1.4 | 4.69 | 0.5061 | 2 | 0.2136 | 917.3 | 2010.0 | 0 | — |
| 0x545d57c7… | -66 | 20 | -13.2 | 2 | 0% | 0% | 12.66 | 89.5 | 4.448 | 315.28 | 0.6063 | 28 | 0.2009 | 563.1 | 136.8 | 9 | diversified alt grinder (maker-lean, high breadth) |
| 0xf138b360… | -65 | 6 | -43.0 | 1 | 0% | 0% | 7.15 | 46.0 | 36.162 | 350.66 | 0.7936 | 177 | 0.056 | 44.1 | 139.0 | 0 | — |
| 0x493670e9… | -52 | 1 | -209.7 | 1 | 0% | 0% | 4.75 | 50.0 | 0.111 | 14.74 | 0.2221 | 2 | 0.0 | 1118.9 | 9175.3 | 0 | — |
| 0xf8cbe336… | -42 | 1 | -166.4 | 1 | 0% | 0% | 5.45 | 21.0 | 0.892 | 3.49 | 0.9612 | 3 | 0.2226 | 899.3 | 2869.8 | 0 | — |
| 0x92d8c467… | -40 | 8 | -20.2 | 1 | 0% | 0% | 6.6 | 55.0 | 0.636 | 62.58 | 0.137 | 4 | 0.2939 | 1395.6 | 3162.5 | 91 | — |
| 0x2291a837… | -35 | 1 | -139.7 | 1 | 0% | 0% | 5.65 | 64.0 | 1.172 | 227.08 | 0.366 | 110 | 0.3609 | 378.8 | 272.9 | 2 | — |
| 0x12469989… | -26 | 1 | -102.6 | 1 | 0% | 0% | 5.49 | 27.0 | 7.146 | 26.05 | 0.464 | 128 | 0.024 | 203.9 | 2414.6 | 0 | — |
| 0x170a03a5… | -19 | 9 | -8.3 | 2 | 0% | 0% | 5.98 | 81.2 | 0.885 | 8578.53 | 0.3322 | 2 | 0.7247 | 3784.3 | 284.4 | 0 | — |
| 0xacec3acc… | -10 | 1 | -40.9 | 1 | 0% | 0% | 6.04 | 67.5 | 0.217 | 9.53 | 0.3127 | 124 | 0.0972 | 449.6 | 4387.7 | 1 | — |
| 0x74c44c09… | +2 | 3 | +2.9 | 1 | 0% | 0% | 8.6 | 78.0 | 0.923 | 18776.39 | 0.2696 | 15 | 0.0 | 326.0 | 1450.7 | 0 | HFT / market-maker bot (institutional scale) |
| 0x6e57cc9c… | +9 | 15 | +2.5 | 1 | 0% | 0% | 7.49 | 32.0 | 4.969 | 17.25 | 1.0 | 27 | 0.0992 | 370.2 | 3300.1 | 0 | — |
| 0x39ef0819… | +14 | 2 | +27.7 | 1 | 0% | 0% | 7.69 | 37.0 | 4.541 | 14.89 | 1.0 | 27 | 0.0989 | 266.9 | 3285.0 | 0 | — |
| 0xa297d934… | +16 | 1 | +64.3 | 1 | 0% | 0% | 6.08 | 37.0 | 3.189 | 32.41 | 0.9998 | 19 | 0.8477 | 499.8 | 827.6 | 11 | — |
| 0x730e4172… | +31 | 10 | +12.5 | 1 | 0% | 0% | 7.55 | 32.0 | 4.969 | 17.47 | 1.0 | 27 | 0.0987 | 354.6 | 3300.1 | 0 | — |
| 0x329c787b… | +37 | 9 | +16.5 | 1 | 0% | 0% | 7.45 | 84.5 | 6.685 | 555.11 | 0.7208 | 23 | 0.9303 | 1984.7 | 44.1 | 1 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x25026b82… | +49 | 2 | +99.0 | 1 | 0% | 0% | 6.42 | 66.0 | 2.287 | 10.33 | 0.6323 | 11 | 0.3748 | 420.0 | 3390.1 | 0 | — |
| 0xa180e7a0… | +60 | 3 | +79.7 | 1 | 0% | 0% | 6.83 | 89.0 | 0.701 | 369.93 | 0.6881 | 22 | 0.564 | 409.8 | 5798.0 | 0 | — |
| 0xfd5406b5… | +66 | 3 | +87.6 | 1 | 0% | 0% | 7.65 | 37.0 | 4.514 | 14.46 | 1.0 | 27 | 0.0993 | 266.5 | 3225.0 | 0 | — |
| 0x0c2cb719… | +93 | 3 | +124.4 | 1 | 0% | 0% | 5.68 | 65.0 | 8.48 | 339.48 | 0.9312 | 37 | 0.9522 | 2556.6 | 420.0 | 0 | — |
| 0xf352c4e3… | +99 | 2 | +197.7 | 1 | 0% | 0% | 5.11 | 68.0 | 1.341 | 12.71 | 0.6004 | 7 | 0.9415 | 551.8 | 1316.7 | 0 | — |
| 0x6f38f875… | +105 | 14 | +29.9 | 1 | 0% | 0% | 7.98 | 32.0 | 4.875 | 21.75 | 1.0 | 27 | 0.1017 | 628.9 | 3315.2 | 0 | — |
| 0x2f4c122a… | +107 | 15 | +28.6 | 1 | 0% | 0% | 7.01 | 73.5 | 2.484 | 74.85 | 0.1589 | 50 | 0.4037 | 22.7 | 829.5 | 0 | — |
| 0xe49a7651… | +108 | 7 | +61.5 | 2 | 0% | 0% | 6.07 | 76.7 | 1.134 | 144.97 | 0.9777 | 99 | 0.3852 | 139.9 | 18087.1 | 0 | — |
| 0xb4de3608… | +109 | 22 | +19.8 | 1 | 0% | 0% | 7.88 | 57.0 | 4.571 | 15.26 | 0.554 | 10 | 0.3382 | 850.2 | 509.9 | 26 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x75619063… | +124 | 15 | +33.0 | 1 | 0% | 0% | 7.18 | 31.0 | 5.0 | 18.58 | 1.0 | 27 | 0.109 | 426.7 | 3225.0 | 0 | — |
| 0x81844050… | +127 | 48 | +10.6 | 2 | 0% | 0% | 6.95 | 70.0 | 1.602 | 19263.28 | 0.3343 | 24 | 0.0 | 343.8 | 1708.7 | 0 | — |
| 0x2dd506b9… | +140 | 2 | +280.4 | 2 | 0% | 0% | 6.13 | 72.2 | 0.905 | 97.07 | 0.6063 | 87 | 0.5754 | 322.2 | 2755.9 | 152 | — |
| 0xe5e6ee25… | +144 | 7 | +82.5 | 1 | 0% | 0% | 6.81 | 87.0 | 4.308 | 71.15 | 0.6757 | 52 | 0.7204 | 1049.1 | 835.7 | 19 | — |
| 0x5d2da9ac… | +151 | 3 | +201.6 | 1 | 0% | 0% | 5.44 | 21.0 | 1.7 | 16.48 | 0.7294 | 20 | 0.556 | 599.5 | 4173.9 | 20 | — |
| 0x92e46562… | +164 | 2 | +328.3 | 1 | 0% | 0% | 5.77 | 88.0 | 0.34 | 61.45 | 0.8284 | 25 | 0.2311 | 1099.3 | 16127.0 | 1 | — |
| 0x41977c32… | +174 | 11 | +63.4 | 2 | 0% | 1% | 7.55 | 62.5 | 3.551 | 14.03 | 1.0 | 33 | 0.0723 | 171.9 | 4275.0 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x83c4c5a4… | +175 | 1 | +700.6 | 1 | 0% | 1% | 6.01 | 64.0 | 1.184 | 23.04 | 0.9055 | 34 | 0.478 | 775.6 | 4825.8 | 39 | — |
| 0xc029043c… | +204 | 9 | +90.5 | 2 | 0% | 1% | 5.89 | 90.0 | 0.488 | 8341.55 | 0.4246 | 4 | 0.8454 | 999.1 | 675.6 | 0 | — |
| 0x2a91e83f… | +227 | 3 | +302.6 | 1 | 0% | 1% | 6.02 | 74.0 | 2.494 | 22.95 | 0.9843 | 143 | 0.2029 | 33.0 | 19887.9 | 16 | — |
| 0xd4f3c94d… | +270 | 12 | +90.1 | 1 | 0% | 1% | 7.73 | 39.0 | 4.359 | 14.92 | 1.0 | 28 | 0.111 | 315.7 | 3300.1 | 0 | — |
| 0xa04f8793… | +283 | 19 | +59.5 | 1 | 0% | 1% | 7.76 | 39.0 | 4.385 | 19.31 | 1.0 | 28 | 0.1106 | 641.2 | 3285.0 | 0 | — |
| 0x2f3406ea… | +313 | 19 | +65.9 | 1 | 0% | 1% | 7.78 | 32.0 | 5.0 | 22.53 | 1.0 | 27 | 0.0989 | 636.4 | 3285.0 | 0 | — |
| 0x51631cdc… | +351 | 16 | +87.8 | 1 | 0% | 1% | 7.73 | 32.0 | 5.0 | 18.84 | 1.0 | 27 | 0.0976 | 485.5 | 3285.1 | 0 | — |
| 0x89694d45… | +359 | 15 | +95.7 | 1 | 0% | 1% | 7.56 | 32.0 | 4.906 | 17.16 | 1.0 | 27 | 0.1022 | 346.5 | 3225.1 | 0 | — |
| 0xb87251a8… | +373 | 5 | +298.2 | 1 | 0% | 1% | 6.49 | 33.0 | 34.154 | 167.54 | 1.0 | 8 | 0.533 | 50.3 | 45.1 | 0 | — |
| 0x07060861… | +394 | 14 | +112.6 | 1 | 0% | 1% | 7.92 | 40.0 | 4.325 | 15.1 | 1.0 | 28 | 0.1094 | 337.3 | 3315.2 | 0 | — |
| 0x8e3c09aa… | +427 | 14 | +122.1 | 1 | 0% | 1% | 7.77 | 32.0 | 5.0 | 17.47 | 1.0 | 27 | 0.0985 | 368.4 | 3285.0 | 0 | — |
| 0x443f4c4f… | +432 | 18 | +96.0 | 1 | 0% | 1% | 7.38 | 32.0 | 4.938 | 22.41 | 1.0 | 27 | 0.1005 | 606.5 | 3315.2 | 0 | — |
| 0xd83989ae… | +436 | 24 | +72.7 | 2 | 0% | 1% | 5.95 | 49.5 | 7.626 | 2897.69 | 0.9879 | 40 | 0.6405 | 916.8 | 18.7 | 0 | — |
| 0xdaf50e49… | +453 | 6 | +301.9 | 1 | 0% | 1% | 4.74 | 48.0 | 1.899 | 29.47 | 0.942 | 71 | 0.5587 | 643.9 | 1371.7 | 52 | — |
| 0x147f1dcd… | +517 | 35 | +59.1 | 2 | 0% | 2% | 5.92 | 44.5 | 3.7 | 16.06 | 1.0 | 33 | 0.0865 | 316.8 | 4440.1 | 0 | — |
| 0x8434b784… | +517 | 23 | +89.9 | 1 | 0% | 2% | 5.18 | 27.0 | 2.081 | 430.59 | 0.5205 | 46 | 0.7476 | 1113.1 | 808.8 | 0 | — |
| 0xd25a100d… | +549 | 7 | +313.9 | 1 | 0% | 2% | 5.95 | 65.0 | 0.951 | 397.45 | 0.4091 | 59 | 0.5755 | 816.9 | 4347.2 | 74 | — |
| 0x44021785… | +566 | 3 | +754.1 | 1 | 0% | 2% | 5.02 | 21.0 | 1.453 | 34.0 | 0.6831 | 4 | 0.8008 | 1000.0 | 951.5 | 0 | — |
| 0x38d2eca8… | +597 | 27 | +88.4 | 2 | 0% | 2% | 6.17 | 75.0 | 2.706 | 31.91 | 0.9936 | 94 | 0.5612 | 381.5 | 3497.5 | 243 | — |
| 0x2988d030… | +608 | 8 | +303.9 | 2 | 0% | 2% | 5.43 | 65.0 | 2.278 | 33.0 | 0.9998 | 16 | 0.51 | 999.8 | 272.3 | 0 | — |
| 0xdbd3de77… | +635 | 23 | +110.3 | 2 | 0% | 2% | 7.77 | 62.5 | 3.547 | 15.9 | 1.0 | 33 | 0.0736 | 281.3 | 4245.0 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x6a40c83d… | +683 | 9 | +303.4 | 1 | 0% | 2% | 6.72 | 38.0 | 3.274 | 16.14 | 1.0 | 32 | 0.0787 | 379.3 | 4380.0 | 0 | — |
| 0x38365db0… | +729 | 24 | +121.4 | 2 | 0% | 2% | 7.02 | 61.5 | 3.192 | 25.16 | 0.8406 | 33 | 0.2197 | 370.5 | 4079.3 | 0 | — |
| 0x7ab15897… | +764 | 53 | +57.7 | 2 | 0% | 2% | 5.41 | 29.0 | 1.986 | 84.25 | 0.7401 | 9 | 0.0721 | 926.8 | 106.5 | 0 | — |
| 0xa312114b… | +806 | 13 | +247.9 | 1 | 0% | 2% | 6.1 | 80.0 | 0.26 | 3074.44 | 0.4124 | 54 | 0.276 | 629.3 | 38698.7 | 22 | — |
| 0x5af5bc81… | +862 | 43 | +80.2 | 2 | 0% | 3% | 6.06 | 90.0 | 3.023 | 72.61 | 0.8349 | 73 | 0.3991 | 591.1 | 4522.7 | 27 | — |
| 0xf7474b6e… | +936 | 38 | +98.6 | 2 | 0% | 3% | 6.9 | 55.5 | 3.653 | 19.73 | 1.0 | 33 | 0.0778 | 433.0 | 4440.1 | 0 | — |
| 0xa55573fc… | +971 | 36 | +107.9 | 2 | 0% | 3% | 6.88 | 61.5 | 3.67 | 19.43 | 0.9995 | 33 | 0.0857 | 460.5 | 4431.8 | 0 | — |
| 0xb567367a… | +982 | 32 | +122.8 | 2 | 0% | 3% | 6.66 | 46.5 | 3.761 | 15.96 | 1.0 | 33 | 0.0937 | 285.5 | 4425.1 | 0 | — |
| 0x8ba1d0af… | +1,193 | 38 | +125.6 | 1 | 0% | 4% | 8.41 | 85.0 | 1.495 | 84.11 | 0.9358 | 15 | 0.3856 | 509.4 | 1427.7 | 13 | — |
| 0xd2efdde0… | +1,196 | 33 | +145.0 | 2 | 0% | 4% | 6.21 | 44.5 | 3.566 | 18.86 | 0.9987 | 32 | 0.0856 | 438.0 | 4454.6 | 0 | — |
| 0xa87d2af3… | +1,207 | 6 | +804.4 | 1 | 0% | 4% | 4.87 | 16.0 | 2.333 | 10.5 | 0.7831 | 11 | 0.3464 | 197.0 | 255.0 | 0 | — |
| 0x6adc6084… | +1,219 | 4 | +1218.5 | 1 | 0% | 4% | 8.2 | 55.0 | 2.105 | 82.22 | 0.7164 | 19 | 0.6583 | 1390.6 | 523.9 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0xccf59517… | +1,347 | 22 | +245.0 | 4 | 0% | 4% | 9.59 | 79.2 | 6.427 | 65.98 | 0.9383 | 172 | 0.0116 | 475.4 | 1315.4 | 10 | diversified alt grinder (maker-lean, high breadth) |
| 0x278c6a51… | +1,500 | 64 | +93.7 | 2 | 0% | 5% | 9.4 | 85.5 | 14.401 | 96.56 | 0.9697 | 185 | 0.5507 | 537.9 | 556.6 | 51 | diversified alt grinder (maker-lean, high breadth) |
| 0x52ea846a… | +1,523 | 29 | +210.1 | 2 | 0% | 5% | 7.52 | 69.5 | 3.717 | 19.39 | 1.0 | 34 | 0.08 | 430.9 | 4410.0 | 0 | aggressive mid-size taker (majors+alts, liq-prone) |
| 0x091144e6… | +1,595 | 13 | +490.8 | 1 | 0% | 5% | 7.21 | 90.0 | 9.082 | 2988.21 | 0.9421 | 53 | 0.2938 | 370.4 | 5.8 | 0 | — |
| 0x81f6b887… | +1,763 | 27 | +261.2 | 3 | 0% | 5% | 7.36 | 79.0 | 1.174 | 285.63 | 0.4691 | 34 | 0.8301 | 1500.5 | 1829.4 | 0 | diversified alt grinder (maker-lean, high breadth) |
| 0xe67f1419… | +2,895 | 97 | +119.4 | 4 | 0% | 9% | 5.39 | 87.2 | 2.284 | 344.08 | 0.3445 | 32 | 0.8402 | 751.1 | 1233.4 | 0 | — |


### Worst-5 vs best-5 medians (Mann-Whitney p, uncorrected)

| metric | worst5 med | best5 med | MW p |
|---|---|---|---|
| trades_per_day | 19.917 | 3.717 | 0.1437 |
| fills_per_day | 660.31 | 285.63 | 0.4034 |
| taker_share | 0.611 | 0.942 | 0.6761 |
| coin_breadth | 50.0 | 34.0 | 0.834 |
| majors_notl_share | 0.113 | 0.551 | 0.2963 |
| n_liq | 0.0 | 0.0 | 0.6072 |
| med_entry_notl | 585.4 | 537.9 | 0.8345 |
| med_gap_min | 313.1 | 1233.4 | 0.2963 |
| avg_gap_min | 2857.1 | 8896.2 | 0.2101 |
| active_days | 289.0 | 285.0 | 0.5309 |
| total_notional | 188193217.0 | 147272795.0 | 0.4034 |
| form_t_mean | 7.02 | 7.36 | 1.0 |
| form_nd_mean | 91.0 | 85.5 | 0.1732 |
| n_trades | 174.0 | 29.0 | 0.0947 |


Artifact: `data/derived/copy_cohort/wallet_attribution_report.json`.


## VENUE-MATCH RE-CUT (formation majors-share buckets)

**STAMP: DESCRIPTIVE re-cut of frozen books by formation venue-specialization; burned folds 202511-202606; feature pre-existing, cut chosen post-hoc after attribution; dependent cells; hypothesis-grade — no new selection derived from this.**

Feature: formation (3-mo, pre-fold) majors notional share from lake wallet_coin_day; majors = BTC/ETH/SOL/HYPE. M buckets: MATCHED >= 0.8 / MIXED / MISMATCHED <= 0.2; P buckets mirrored (MATCHED <= 0.2). Wallet-equal gross = per-trade gross winsorized at book [1,99] pct, equal-weight over wallet-folds. CI = entry-day-block bootstrap (1000, 242-day span) on pooled net bp.


### MAJORS-NATIVE K30 @8h

| bucket | wf | wallets | trades | %book | net $ | net bp/tr | we-gross bp | boot CI95 | P(>0) | %wf>0 | med maj% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MATCHED | 74 | 42 | 4,669 | 85% | +26,893 | +23.0 | +20.1 | [-22.7, +73.1] | 0.806 | 49% | 1.0 |
| MIXED | 11 | 9 | 819 | 15% | +767 | +3.8 | -30.9 | [-58.4, +58.1] | 0.518 | 36% | 0.459 |
| MISMATCHED | 1 | 1 | 6 | 0% | +15 | +9.8 | +15.3 | [-341.5, +946.1] | 0.467 | 100% | 0.192 |

Monotone (MISMATCHED<MIXED<MATCHED): pooled net False, wallet-equal gross False.

Case 0xa1b6d8ef: 202511: maj%=0.37 MIXED n=347 -12.0bp ($-1,044) ; 202512: maj%=0.40 MIXED n=212 -52.0bp ($-2,759) ; 202601: maj%=0.44 MIXED n=182 +106.4bp ($+4,841)


### PYRAMID-ALT ladder

| bucket | wf | wallets | trades | %book | net $ | net bp/tr | we-gross bp | boot CI95 | P(>0) | %wf>0 | med maj% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MATCHED | 77 | 51 | 2,083 | 57% | -2,216 | -4.3 | +55.0 | [-39.2, +32.6] | 0.399 | 49% | 0.086 |
| MIXED | 66 | 42 | 1,388 | 38% | +1,806 | +5.2 | +54.8 | [-33.9, +40.5] | 0.581 | 52% | 0.479 |
| MISMATCHED | 18 | 14 | 197 | 5% | +644 | +13.1 | +3.9 | [-76.8, +92.1] | 0.599 | 61% | 0.938 |

Monotone (MISMATCHED<MIXED<MATCHED): pooled net False, wallet-equal gross True.

Case 0xa1b6d8ef: 202511: maj%=0.37 MIXED n=132 -61.7bp ($-2,035) ; 202512: maj%=0.40 MIXED n=48 -38.7bp ($-465) ; 202601: maj%=0.44 MIXED n=53 +14.1bp ($+186) ; 202602: maj%=0.50 MIXED n=87 +11.2bp ($+244) ; 202603: maj%=0.52 MIXED n=45 -82.2bp ($-925) ; 202604: maj%=0.54 MIXED n=25 -61.2bp ($-382)


### Verdict (honest read)

The clean convergence story ("venue-match separates winners from losers in BOTH books") is NOT
confirmed as a monotone gradient; what survives is one-sided and book-specific:

- **M book**: the entire PnL sits in the MATCHED (majors-specialist) bucket — 97% of net $ from
  85% of trades, +23.0 vs +3.8 bp pooled, wallet-equal gross +20.1 vs −30.9 — but the MISMATCHED
  cell is EMPTY (1 wallet-fold, 6 trades: the majors-t selector structurally admits almost no
  true alt wallets), %wf>0 is ~equal (49% vs 36%), and the MATCHED CI still spans 0
  ([−22.7, +73.1]). This is the attribution p≈0.07 lean re-expressed on the same data, not new
  evidence. Addressable drag from the cut ≈ nil: dropping MIXED sheds 15% of flow carrying only
  ~3% of PnL — cheap, but it cannot have been what made the book work.
- **P book**: the hypothesis FAILS on pooled net — anti-monotone (MISMATCHED majors-profile
  wallets +13.1 > MIXED +5.2 > MATCHED alt-native −4.3). The alt-native pooled deficit is mostly
  the known taker-HFT dragger 0x223537ac (0.0 majors share ⇒ MATCHED; −$7.4k/888u); ex-dragger
  MATCHED pooled ≈ +17.2bp — i.e. the P drag is the BOT screen, not venue. The wallet-equal-gross
  monotonicity that does hold (+3.9 < +54.8 < +55.0) is (a) flat between MATCHED and MIXED and
  (b) rests on 18 mismatch wallet-folds / 197 units. No alt-native filter is justified.
- **Case 0xa1b6d8ef**: NOT a venue-flip story — maj% ≈ 0.37–0.54 (MIXED in both books, every
  fold). Its M profit is one fold (202601 +$4.8k vs losses before), its P losses similarly
  fold-concentrated: sign-flip = fold-timing noise, not venue mismatch.

Forward implication: supports only the already-registered M-book forward VARIANT (formation
majors_share ≥ 0.8 specialist filter — now quantified as shedding ~15% flow / ~3% PnL on burned
data) and reinforces the P-book fills/day bot screen amendment. It does NOT justify a P-book
venue filter. Load-bearing vs mirage: venue-match is a plausible, internally-consistent M-book
lean that has never cleared significance and gained no independent support from the P book here.

Artifact: `data/derived/copy_cohort/venue_match_report.json`.

---

# CONSENSUS CONDITIONING — pre-declared grid (definitions stamped 2026-07-17 13:19 UTC, BEFORE any outcome was computed)

**STAMP: DESCRIPTIVE — burned folds 202511–202606; conditioning EXISTING frozen-book entries on a
pre-declared consensus grid; NO new selection; nothing here may be tuned into a selector without a
fresh prereg. 18 grid cells + 2 score-weighted variant rows, all dependent (same entries re-binned).
Prior context: majors interaction study suggested "consensus rescues small wallets" but was sparse.**

## Books / entry sets (frozen, unchanged)
- **A = PYRAMID-ALT ladder units**: re-simulated from local caches via `pyramid_book.py` loaders,
  identically to `wallet_attribution.load_p_units` — exact reconciliation to
  `wallet_attribution_report.json` (3,668 units, book net +0.25 bp/unit) is REQUIRED before any
  conditioning. THEN the v1.1 bot screen is applied by dropping units whose wallet fails it (the sim
  itself runs on the full cohort so cap dynamics reconcile). v1.1 screen (PYRAMID_ALT_PREREG.md
  Amendment v1.1): formation fills/day = SUM(n_fills)/COUNT(DISTINCT day) over the fold's 3 formation
  months (lake `wallet_coin_day`, all coins) must be < 1000. Unit net already embeds 21.5 bp RT.
  Entry timestamp for conditioning = the unit's signal ts (`ts_sig`).
- **B = MAJORS-NATIVE K30 entries**: `data/derived/copy_cohort/majors_native/entries_{fold}.parquet`,
  rk < 30, finite mk8; gross = mk8; net = mk8 − 5.5 bp. No bot screen (matches the frozen side-book).
  Entry timestamp = the open's `ts`. `dir_sign` is not in the cache → recovered by joining
  (wallet, coin, ts) to a lake `open_entries` pull; entries whose key matches BOTH directions are
  dropped and counted (expected rare).

## Consensus definition (fixed)
For an entry/unit by wallet w at time t in coin c, direction d, and window W ∈ {1h, 6h, 24h}:
`n_others` = COUNT DISTINCT cohort wallets ≠ w (same fold's cohort) with ≥1 entry signal in coin c,
direction d, with signal ts ∈ **[t − W, t)** (strictly before t; same-ms signals excluded to avoid
same-block mechanical clustering). Levels: **solo** = 0 others, **pair** = 1, **crowd** = ≥2.

Counting signal pools (what counts as "another wallet opened c,d"):
- Book A: the fold cohort's flat opens (`pyramid/opens_{fold}.parquet`, lake open_entries
  block-collapsed) **plus** the pyramid adds caches (`pyramid/adds/fold={fold}.parquet`) — an add by
  another wallet counts as an entry signal. No notional/liquidity filter on counting signals. The
  counting cohort is the **v1.1-screened** fold cohort (bots excluded from counting too).
- Book B: the fold's K30 cohort majors flat opens from lake `open_entries` (block-collapsed per
  wallet, coin, ts, dir_sign; all majors, no notional filter). Counting cohort = the K30.

## Per-cell report (2 books × 3 W × 3 levels = 18 cells)
n; % of book entries (within book × W); entry-equal **net** bp (book costs 21.5 A / 5.5 B);
**wallet-equal winsorized gross bp** = winsor gross at p95 of |gross| within the cell → per-wallet
means → equal-weight mean over wallets; **1000-rep wallet-cluster bootstrap** percentile CI
[2.5, 97.5] on the wallet-equal winsorized gross (resample wallets with replacement; seeds
`default_rng(20260717 + cell_index)`, cell_index enumerated in fixed book/W/level order).

## Score-weighted variant (ONE extra row per book, W = 6h only)
Same grid but `n_others` counted only among the **top-half-t** cohort wallets: A = first ⌈n/2⌉ of the
screened fold cohort in formation-t descending order; B = rk < 15. Reported as the same 3 levels.

## Reads (pre-set)
- Monotonicity per (book, W): does wallet-equal winsorized gross rise solo → pair → crowd?
- Load-bearing test: a consensus definition is called load-bearing only if its crowd-vs-solo gap is
  CI-clearing AND direction-consistent across all 3 windows for that book; otherwise noise/suggestive.
- Deployability: share of book volume at each level.
- Caveats stamped up front: burned folds; 18+2 dependent cells (same entries re-binned, no
  multiplicity correction — descriptive); consensus level is correlated with coin/time-of-day
  activity, so any gradient is a *conditional descriptive*, not a causal or deployable claim.

Artifact (to be written after compute): `data/derived/copy_cohort/consensus_report.json`.

## CONSENSUS CONDITIONING — RESULTS (computed after the stamp above)


### Book A — PYRAMID-ALT (v1.1-screened units, cost 21.5bp) (2,319 entries)

| W | level | n | % | net bp (entry-eq) | gross bp (wallet-eq winsor) | boot CI95 | wallets |
|---|---|---|---|---|---|---|---|
| 1h | solo | 1,497 | 64.6% | -8.6 | +26.2 | [-37.1, +93.9] | 72 |
| 1h | pair | 306 | 13.2% | +10.5 | +71.0 | [-30.0, +166.1] | 51 |
| 1h | crowd | 516 | 22.3% | +92.2 | +12.1 | [-89.5, +108.8] | 49 |
| 6h | solo | 1,087 | 46.9% | -5.8 | +1.5 | [-69.0, +62.4] | 53 |
| 6h | pair | 478 | 20.6% | -1.8 | +67.4 | [-26.2, +157.4] | 57 |
| 6h | crowd | 754 | 32.5% | +59.8 | +31.8 | [-41.4, +102.8] | 64 |
| 24h | solo | 716 | 30.9% | -19.8 | +19.8 | [-40.1, +83.2] | 42 |
| 24h | pair | 524 | 22.6% | +12.9 | +26.4 | [-53.6, +109.0] | 46 |
| 24h | crowd | 1,079 | 46.5% | +42.0 | +33.1 | [-47.1, +108.8] | 77 |
| 6h-topT | solo: n=1386, 27.34bp / pair: n=349, 26.98bp / crowd: n=584, 98.68bp | | | | | | |

Monotonicity (wallet-eq winsor gross, solo->pair->crowd): 1h: [26.22, 71.05, 12.05] rises=False; 6h: [1.49, 67.36, 31.81] rises=False; 24h: [19.79, 26.39, 33.15] rises=True

Crowd-vs-solo gap (wallet-boot CI95): 1h: -14.2 [-123.5, +85.7]; 6h: +30.3 [-65.2, +135.6]; 24h: +13.4 [-84.8, +120.3]; 6h-topT variant: +71.3 [-11.9, +164.5]


### Book B — MAJORS-NATIVE K30 @8h (cost 5.5bp) (5,494 entries)

| W | level | n | % | net bp (entry-eq) | gross bp (wallet-eq winsor) | boot CI95 | wallets |
|---|---|---|---|---|---|---|---|
| 1h | solo | 1,783 | 32.5% | -0.1 | -1.6 | [-43.4, +39.8] | 50 |
| 1h | pair | 595 | 10.8% | -9.1 | +9.4 | [-65.2, +75.7] | 32 |
| 1h | crowd | 3,116 | 56.7% | +37.3 | +54.7 | [+15.1, +101.2] | 26 |
| 6h | solo | 1,140 | 20.7% | -9.8 | -27.8 | [-76.1, +12.1] | 41 |
| 6h | pair | 403 | 7.3% | -21.2 | -60.8 | [-128.2, -1.8] | 34 |
| 6h | crowd | 3,951 | 71.9% | +33.0 | +26.1 | [-40.7, +83.0] | 33 |
| 24h | solo | 743 | 13.5% | -4.4 | +0.6 | [-54.9, +52.0] | 33 |
| 24h | pair | 423 | 7.7% | -47.6 | -74.5 | [-138.4, -18.5] | 32 |
| 24h | crowd | 4,328 | 78.8% | +31.0 | +9.8 | [-36.9, +54.4] | 39 |
| 6h-topT | solo: n=1522, -62.26bp / pair: n=944, 16.11bp / crowd: n=3028, 58.84bp | | | | | | |

Monotonicity (wallet-eq winsor gross, solo->pair->crowd): 1h: [-1.55, 9.38, 54.72] rises=True; 6h: [-27.78, -60.79, 26.05] rises=False; 24h: [0.6, -74.47, 9.8] rises=False

Crowd-vs-solo gap (wallet-boot CI95): 1h: +56.3 [-6.8, +124.4]; 6h: +53.8 [-21.1, +127.8]; 24h: +9.2 [-59.8, +76.1]; 6h-topT variant: +121.1 [+31.6, +203.0]


Artifact: `data/derived/copy_cohort/consensus_report.json`.

## CONSENSUS CONDITIONING — RESULTS (computed after the stamp above)

*2026-07-17 audit re-print: every boot CI below is the WIDER of the wallet-cluster and (coin × calendar-day)-cluster CI (both stored in the JSON artifact); code_commit 1535c74-dirty.*


### Book A — PYRAMID-ALT (v1.1-screened units, cost 21.5bp) (2,319 entries)

| W | level | n | % | net bp (entry-eq) | gross bp (wallet-eq winsor) | boot CI95 (binding cluster) | wallets |
|---|---|---|---|---|---|---|---|
| 1h | solo | 1,497 | 64.6% | -8.6 | +26.2 | [-37.1, +93.9] (wallet) | 72 |
| 1h | pair | 306 | 13.2% | +10.5 | +71.0 | [-30.0, +166.1] (wallet) | 51 |
| 1h | crowd | 516 | 22.3% | +92.2 | +12.1 | [-63.4, +152.1] (coinday) | 49 |
| 6h | solo | 1,087 | 46.9% | -5.8 | +1.5 | [-69.0, +62.4] (wallet) | 53 |
| 6h | pair | 478 | 20.6% | -1.8 | +67.4 | [-26.2, +157.4] (wallet) | 57 |
| 6h | crowd | 754 | 32.5% | +59.8 | +31.8 | [-25.1, +131.5] (coinday) | 64 |
| 24h | solo | 716 | 30.9% | -19.8 | +19.8 | [-40.1, +83.2] (wallet) | 42 |
| 24h | pair | 524 | 22.6% | +12.9 | +26.4 | [-53.6, +109.0] (wallet) | 46 |
| 24h | crowd | 1,079 | 46.5% | +42.0 | +33.1 | [-47.1, +108.8] (wallet) | 77 |
| 6h-topT | solo: n=1386, 27.34bp / pair: n=349, 26.98bp / crowd: n=584, 98.68bp | | | | | | |

Monotonicity (wallet-eq winsor gross, solo->pair->crowd): 1h: [26.22, 71.05, 12.05] rises=False; 6h: [1.49, 67.36, 31.81] rises=False; 24h: [19.79, 26.39, 33.15] rises=True

Crowd-vs-solo gap (binding cluster boot CI95): 1h: -14.2 [-92.5, +132.1] (coinday); 6h: +30.3 [-65.2, +135.6] (wallet); 24h: +13.4 [-84.8, +120.3] (wallet); 6h-topT variant: +71.3 [-28.9, +170.4] (coinday)


### Book B — MAJORS-NATIVE K30 @8h (cost 5.5bp) (5,494 entries)

| W | level | n | % | net bp (entry-eq) | gross bp (wallet-eq winsor) | boot CI95 (binding cluster) | wallets |
|---|---|---|---|---|---|---|---|
| 1h | solo | 1,783 | 32.5% | -0.1 | -1.6 | [-43.4, +39.8] (wallet) | 50 |
| 1h | pair | 595 | 10.8% | -9.1 | +9.4 | [-65.2, +75.7] (wallet) | 32 |
| 1h | crowd | 3,116 | 56.7% | +37.3 | +54.7 | [-10.2, +106.1] (coinday) | 26 |
| 6h | solo | 1,140 | 20.7% | -9.8 | -27.8 | [-76.1, +12.1] (wallet) | 41 |
| 6h | pair | 403 | 7.3% | -21.2 | -60.8 | [-128.2, -1.8] (wallet) | 34 |
| 6h | crowd | 3,951 | 71.9% | +33.0 | +26.1 | [-40.7, +83.0] (wallet) | 33 |
| 24h | solo | 743 | 13.5% | -4.4 | +0.6 | [-54.9, +52.0] (wallet) | 33 |
| 24h | pair | 423 | 7.7% | -47.6 | -74.5 | [-138.4, -18.5] (wallet) | 32 |
| 24h | crowd | 4,328 | 78.8% | +31.0 | +9.8 | [-36.9, +54.4] (wallet) | 39 |
| 6h-topT | solo: n=1522, -62.26bp / pair: n=944, 16.11bp / crowd: n=3028, 58.84bp | | | | | | |

Monotonicity (wallet-eq winsor gross, solo->pair->crowd): 1h: [-1.55, 9.38, 54.72] rises=True; 6h: [-27.78, -60.79, 26.05] rises=False; 24h: [0.6, -74.47, 9.8] rises=False

Crowd-vs-solo gap (binding cluster boot CI95): 1h: +56.3 [-6.8, +124.4] (wallet); 6h: +53.8 [-21.1, +127.8] (wallet); 24h: +9.2 [-59.8, +76.1] (wallet); 6h-topT variant: +121.1 [+31.6, +203.0] (wallet)


Artifact: `data/derived/copy_cohort/consensus_report.json`.
