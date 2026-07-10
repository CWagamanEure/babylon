# Pipeline audit (pre-run) — backfill + wallet-screen code, 2026-07-01

55-agent workflow: 5 finders x 2-lens verification. 23 confirmed, 2 killed.
All confirmed findings addressed in `scratch_conv/mlscreen2.py` + hardened
`run_backfill_months.sh` + PREREG amendments v1.1 BEFORE any new data was read.

## A1 [CRITICAL] (tape-integrity) mlscreen.py cannot run the pre-registered experiment: window/files hardcoded to Feb-Jun 2026, and the driver deletes fills.parquet before extract can ever see the backfilled months

**Mechanism:** mlscreen.py:30-31 hardcodes MONTH_FILES = backfill_202602..05 + multiday; T0=2026-02-01 and N_DAYS=140 (lines 36-37) end the grid at ~Jun 21, not Jun 30, and split_day default 89 puts the split at May 1, not the pre-registered Apr 1. cmd_pick (line 79) reads only stats_{0..4} (indexed legacy months) and cmd_extract (line 101) + _load_bars (line 116) loop only MONTH_FILES — the tagged outputs the driver produces for 202508-202601/202606 (bars_202508.parquet etc., run_backfill_months.sh:23-24) are never read by any downstream stage. Worse, cmd_extract has no --file/--tag support at all, and run_backfill_months.sh:26 does `rm -rf $DIR/hl_trades $DIR/fills.parquet` immediately after stats — so candidate-wallet fills for Aug 2025–Jan 2026 and Jun 2026 can never be extracted without re-downloading. Finally, cmd_daily's day index `np.clip(((t-T0)//DAY_MS), 0, N_DAYS-1)` (line 187) would silently lump every pre-Feb-2026 fill into day 0 if the new files were naively added without moving T0.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:30-31,36-37,79,101,116,187,278 vs /Users/corywagamaneure/bablyon/audit/edge3/PREREG_WALLET_SCREEN.md:15-20 ('TRAIN = 2025-08-01..2026-03-31, TEST = 2026-04-01..2026-06-30', 'multiday/fills.parquet is NOT used'); /Users/corywagamaneure/bablyon/scratch_conv/run_backfill_months.sh:23-26

**Effect:** As coded the pipeline reruns the old exploratory Feb-Jun cell (with multiday, which the prereg explicitly bans for June double-count risk) and calls it the confirmation. Eligibility in cmd_pick is computed over ALL months including Apr-Jun — direct test-window leakage into selection, violating 'No test-window information may enter eligibility' — which inflates the roster's apparent OOS transfer (wallets that survived/traded through the test window are preferentially eligible: survivorship + selection-on-test, the exact taxonomy in SUMMARY.md). Any attempt to bolt the new months on after the driver runs hits deleted raw fills or the day-0 clipping bug, forcing improvised rewrites after the data has been seen — i.e. the single pre-registered look is unexecutable without deviations.

---

## A2 [CRITICAL] (tape-integrity) The pre-registered decision rule is not implemented: ranking uses leader Sharpe not follower Sharpe, fee is 4.5bp not 3.0bp, the day-block bootstrap CI (condition 1) does not exist, the placebo (condition 2) is scored on leader series, and funding accrual is absent

**Mechanism:** PREREG line 35-39: rank eligible wallets by FOLLOWER-simulated train Sharpe at half-spread + 3.0bp/side. mlscreen cmd_analyze lines 240-241 rank by tr_sh computed from L (leader series): `tr_sh = np.array([_sharpe(x[:split]) for x in L]); top = np.argsort(-tr_sh)`. FEE_SIDE_BPS = 4.5 (line 35) with no 3.0/1.5/4.5 sensitivity plumbing. Decision condition 1 requires a one-sided 95% CI from a 5-day-block bootstrap of the roster's daily follower series — no bootstrap exists anywhere in cmd_analyze (lines 233-268); only point Sharpes are printed. Condition 2's placebo (lines 246-248) draws random rosters and scores them on L (leader), then compares against _sharpe(lead) — the leader roster — while the PASS decision is about the follower-simulated roster. Robustness checks 3a (drop top-|PnL| coin) and 3b (drop best test month) are also unimplemented, as is the prereg's funding accrual ('HL hourly funding accrued... coverage fraction reported' — mlscreen line 16 admits 'no funding accrual').

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:35,240-241,246-252 vs /Users/corywagamaneure/bablyon/audit/edge3/PREREG_WALLET_SCREEN.md:34-47,30-33

**Effect:** None of the three PASS/FAIL quantities the prereg defines are produced by the code. Leader-Sharpe ranking selects wallets whose edge is un-copyable (fast/maker-ish flow), so the follower OOS number answers a different question than registered; the missing bootstrap CI means condition 1 cannot be adjudicated at all; a leader-based placebo can pass condition 2 while the follower roster would fail it. Whatever is printed, reading it as the pre-registered verdict is a silent deviation — and implementing the missing pieces after seeing these outputs reopens the garden of forking paths the prereg was written to close (the round-3 F3/F16 winner's-curse failure mode, again). Additionally, zero funding on multi-day perp holds makes follower PnL gross-of-funding, typically an optimistic bias for crowded longs.

---

## A3 [MAJOR] (tape-integrity) Follower 'post-fill' price can be the leader's own fill print: containing-bar close on tape-derived bars embeds the leader's price/impact whenever the leader's fill is the last trade of its 5m bar

**Mechanism:** cmd_bars builds close = last trade px in each 5m bar from the tape itself (mlscreen.py:57), and the tape includes the candidate wallet's own fills. _post_close (lines 131-141) returns the close of the bar CONTAINING t: the stamp is post-fill (bar end > t), but the VALUE is the last print in that bar — if no one trades after the leader within the bar (routine in thin alts, and the leader's own reducing/opening prints are often the last trade), the follower is 'filled' at exactly the leader's price, with zero timing lag and the leader's own impact credited rather than charged. The gap branch (lines 136-139) correctly requires a strictly-later bar, but the main branch has no 'strictly after the fill print' guard. This is the same artifact family as the round-3 F2 collapse (own-impact/pre-fill pricing), reintroduced one level down: candle STAMP honesty was fixed, candle CONTENT provenance was not.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:57,131-141,194-197; contrast SUMMARY.md F2 verification which validated stamp>t but on exchange candles, not self-derived bars containing the leader's prints

**Effect:** Inflates fol0/folc — the exact quantity that decides prereg condition 1 — with the bias concentrated in illiquid coins where real copy slippage is worst and where the >=100-bar floor (line 166) still admits very sparse tapes. Sign is unambiguously optimistic for the follower (leader buys mark the bar close at/near the leader's price, below the achievable next-trade price). Given round 3 showed |92bp| median entry-price motion between adjacent pricing conventions dwarfing the claimed edge, this can single-handedly manufacture a PASS on condition 1.

---

## A4 [MAJOR] (tape-integrity) Silent tape holes: MISS hours are single-attempt, logged only to uncaptured stderr, never reconciled; a killed run leaves a truncated .gz that is forever marked 'already done'; fills_to_parquet has no completeness check before the raw is deleted

**Mechanism:** backfill_fills.py:44-48 makes ONE `aws s3 cp` attempt; any transient failure prints 'MISS' to stderr and returns 0 — the driver (run_backfill_months.sh) captures nothing, proceeds to convert, then `rm -rf`s the raw (line 26), making the gap permanent for this run. Separately, the resume check `if out.exists() and out.stat().st_size > 0: return -1` (backfill_fills.py:40-41) treats a PARTIAL gz from a killed process (gzip header alone is >0 bytes) as complete, so a crash mid-hour poisons that hour on every rerun. fills_to_parquet.py (lines 26-48) globs whatever hour-files exist with no expected-hour/day assertion — a half-done month converts to a plausible-looking truncated parquet, and mlscreen stats/bars consume it under the month tag with no row/day reconciliation. The prereg's own caveat 'archive MISS hours logged and reported' has no implementation: nothing persists the MISS list.

**Evidence:** /Users/corywagamaneure/projects/ml-forecasting-research/experiments/address_profile/backfill_fills.py:40-41,44-48; /Users/corywagamaneure/bablyon/scratch_conv/run_backfill_months.sh:18-26; /Users/corywagamaneure/projects/ml-forecasting-research/experiments/address_profile/fills_to_parquet.py:26-48 (no completeness assertion); PREREG_WALLET_SCREEN.md:54-55

**Effect:** Missing fills permanently offset every subsequent cumsum in cmd_daily's position reconstruction (mlscreen.py:174-208): the leading-episode flat detection fires at the wrong point or never, phantom carry positions accrue mark-to-market PnL for the rest of the window, and a missing reducing fill leaves a losing position 'open' indefinitely. On eligibility, a truncated train month deflates n_orders/days non-randomly — wallets near the 150-order/25-active-day thresholds drop out while the busiest survive, tilting the field the placebo is drawn from. Direction on the headline is unpredictable per wallet but the eligibility tilt and phantom-carry variance both corrupt the train ranking that the whole test hangs on; because raws are deleted, the corruption is undetectable and unrepairable after the fact.

---

## A5 [MINOR] (tape-integrity) Pairing by tid silently discards every trade that doesn't present as exactly 2 opposite-crossed events (duplicate/replayed archive lines, same-crossed anomalies) with no counter or report

**Mechanism:** backfill_fills.py:64-69: `if len(evs) != 2: continue` then `if f0['crossed'] == f1['crossed']: continue`. A tid whose events appear twice (duplicate blocks/replays in a node-sourced archive produce 4 events for a real trade) is dropped entirely rather than deduped by (tid, addr); single-visible-side or same-crossed records (possible for liquidation/ADL/backstop bookkeeping in node_fills) vanish likewise. No drop counters exist — process_hour returns only the written count, so an hour that ingested 500k events and emitted 480k pairs is indistinguishable from a clean one, and the raw is deleted afterward. Relatedly, the zhash flag (fills_to_parquet.py:38) that gates order counting in cmd_stats (mlscreen.py:66) inherits whatever hash semantics node_fills uses, which need not match the WS firehose semantics of the pre-existing Feb-Jun months — eligibility thresholds would then bind differently across train (node-sourced) vs test (WS-sourced) months.

**Evidence:** /Users/corywagamaneure/projects/ml-forecasting-research/experiments/address_profile/backfill_fills.py:64-69 (no dedup, no drop accounting); /Users/corywagamaneure/projects/ml-forecasting-research/experiments/address_profile/fills_to_parquet.py:38; /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:66

**Effect:** Each silently dropped fill is another hole in a wallet's position stream (same corruption path as the MISS-hour finding: offset cumsums, wrong episode boundaries, phantom carry). If liquidation exits are among the dropped classes, losing exits of bad wallets go missing and their positions keep being carried at market — a disposition-flavored distortion of exactly the tail losses the screen should penalize. Magnitude is unmeasured because the code measures nothing; at minimum the pipeline should emit per-hour ingested/paired/dropped counts before the prereg run so the 'tape completeness' assumption is a checked fact rather than hope.

---

## A6 [CRITICAL] (stats-pick-causality) cmd_pick computes eligibility on the COMBINED window including all TEST months — direct violation of the prereg's TRAIN-only causality requirement

**Mechanism:** PREREG_WALLET_SCREEN.md:22-26 requires eligibility (150-20000 orders, >=25 active days, 0.5-15 orders/day over the TRAIN span, >=$500 mean notional) computed on TRAIN = 2025-08..2026-03 only, with 'No test-window information may enter eligibility.' mlscreen.py cmd_pick (line 79) concatenates stats for range(len(MONTH_FILES)), i.e. stats_0..stats_4 = backfill_202602..202605 + multiday (Feb-Jun 2026). Under the prereg windows that is TWO train months (Feb, Mar) plus the ENTIRE test window (Apr, May, Jun). All four filters at lines 87-89 are then evaluated on summed n_orders, summed days, combined-window weighted mean_notional, and tpd = n_orders / global span where span = t_max - t_min (line 85) stretches across test. Concrete leak: a wallet with 100 train orders (fails the 150 floor) and 400 test orders passes n_orders>=150 purely on test activity; a wallet with 30 train-active days and dead-in-test passes, but one with 20 train days + 10 test days also passes on test days; a wallet at 18 orders/day in train that goes quiet in test gets its tpd diluted under the 15 cap by the test-extended span. The eligible field — from which both the top-50 roster and the 1000-roster placebo (decision rule 2) are drawn — is therefore conditioned on test-window survival and activity.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:79 (`pl.read_parquet(OUT / f"stats_{i}") for i in range(len(MONTH_FILES))`), :84-89 (days=sum, t_min/t_max global, filters), :30-31 (MONTH_FILES = 202602-202605 + multiday); /Users/corywagamaneure/bablyon/audit/edge3/PREREG_WALLET_SCREEN.md:19,22-26. Note the new train months produced by run_backfill_months.sh are tagged '202508'..'202601' (stats_202508.parquet etc.) and are never read by cmd_pick at all.

**Effect:** Classic selection-on-test-set / survivorship-into-test: wallets must be alive and trading in the test window to enter the field, and activity-boundary wallets are admitted/excluded using test information. This inflates the absolute test-window follower Sharpe and PnL of both the roster and the field (dead-in-test wallets that the prereg says 'stay in the field' are silently removed), biasing decision rule 1 (CI > 0) toward a spurious PASS. Fix required: cmd_pick must read only stats_202508..stats_202603 (train tags), with span/days/notional all train-windowed, and any partial-month overlap trimmed to 2025-08-01..2026-03-31.

---

## A7 [CRITICAL] (stats-pick-causality) The entire pipeline downstream of stats is hardwired to the exploratory Feb-Jun dataset (T0, N_DAYS, indexed files, multiday) — running it 'as pre-registered' either re-scores the hypothesis-generating data or double-counts June if naively extended

**Mechanism:** The prereg (lines 13-19) mandates Aug-2025..Jun-2026 with Jun 2026 from backfill_202606 and 'multiday/fills.parquet is NOT used — overlap would double-count.' But mlscreen.py hardcodes the old exploratory configuration everywhere: MONTH_FILES includes multiday and no 2025 months (:30-31), T0 = 2026-02-01 (:36), N_DAYS = 140 (:37), --split-day default 89 = the old Feb-Apr/May-Jun split (:278, docstring :13), _load_bars reads only bars_0..bars_4 (:116), cmd_extract and cmd_daily iterate MONTH_FILES / cand_0..cand_4 (:101, :152). Two failure paths: (a) run unmodified, the 'confirmation test' silently re-runs the exact 4.5-month sample whose positive result motivated the prereg — a non-independent confirmation guaranteed to look like transfer; (b) if MONTH_FILES is naively extended to include BOTH backfill_202606 and multiday, every June fill in the overlap appears twice in cand_ parquets, doubling sz in the cumsum position reconstruction (:171-181) — cum never matches true position, the |cum|*px < 1 flat detector and leading-episode drop misfire, and June (test-window) PnL contributions are roughly doubled. A smaller instance of the same seam bug already exists: backfill_202602 starts 2026-01-31 23:59 (comment :36), so under the prereg run its Jan-31 fills duplicate backfill_202601's, and cmd_pick's days=sum-of-per-month-n_unique (:83) double-counts that calendar day (and those orders) for every wallet active in that hour.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:30-31,36-37,79,101,116,152,278; /Users/corywagamaneure/bablyon/audit/edge3/PREREG_WALLET_SCREEN.md:15-16,19; /Users/corywagamaneure/bablyon/scratch_conv/run_backfill_months.sh:10 (produces tagged 202508..202601,202606 stats/bars that nothing downstream consumes).

**Effect:** Path (a) yields a fake PASS on in-sample data presented as the pre-registered confirmation; path (b) inflates and corrupts test-window (June) PnL magnitudes and Sharpe via duplicated fills and broken episode logic. Either way the reported number is not the pre-registered test. The window plumbing (T0=2025-08-01, N_DAYS~334, month list, split day = end of 2026-03-31, 202606 replacing multiday, seam dedup e.g. on tid) must be rewritten before the single look is spent.

---

## A8 [MAJOR] (stats-pick-causality) The 2000-wallet random cap is an undeclared deviation that changes the pre-registered estimand, and the sample is not actually reproducible despite the seed

**Mechanism:** The prereg declares no cap: the roster is 'top 50' of the eligible field and the placebo draws from 'the eligible field' (lines 39, 44-45), with 'Dead wallets stay in the field.' cmd_pick (:92-95) instead random.sample's 2000 wallets when more pass. Top-50-of-a-2000-subsample is a strictly weaker selection than top-50-of-field (if e.g. 10k pass, it approximates the field's top ~250th-quality cut), so the measured roster is a different estimand from the registered one. Worse for auditability: the wallet list order comes from a polars group_by aggregation (:80-90), whose row order is non-deterministic across runs/thread counts, so random.seed(42) + random.sample (:92-94) does NOT pin the sample — re-running pick yields a different 2000 and therefore a different roster and different test numbers. The 'single confirmation look' is not pinned to one realizable result, creating a re-run-until-pass loophole.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:80-96 (group_by then random.sample on unsorted taker list); /Users/corywagamaneure/bablyon/audit/edge3/PREREG_WALLET_SCREEN.md:34-45.

**Effect:** Selection-strength attenuation biases toward FAIL in expectation (conservative on the effect), but the estimand mismatch means neither PASS nor FAIL cleanly tests the registered hypothesis; the non-reproducibility silently permits multiple looks. Fix: drop the cap or pre-declare it as a Deviation, and sort the passer list (e.g. wallets = sorted(...)) before seeded sampling so the roster is a deterministic function of the data.

---

## A9 [MINOR] (stats-pick-causality) Order grouping key (taker, coin, ts, side) merges distinct same-block orders — n_orders undercounted and mean_notional overcounted at exactly the filter boundaries designed to exclude unfollowable wallets

**Mechanism:** cmd_stats (:67) defines an order as a (taker, coin, ts, side) group. HL fill `time` is the block timestamp (ms), shared by every fill in a block; a taker order executes within one block, so one order never splits across keys, but two or more distinct orders from the same taker on the same coin/side landing in the same block (typical for bots/HFT sending multiple orders per block) collapse into one 'order' whose notional is the sum (:68-69). The bias is one-directional: n_orders is undercounted and mean order notional overcounted, most strongly for the highest-frequency wallets. Those are precisely the wallets the 20000-order cap and 15-orders/day cap exist to exclude (HFT edge is unfollowable per the team's own taxonomy), and the $500 mean-notional floor is loosened for small wallets whose bursts get merged. The fill-level `hash` (the order/action hash, preserved by fills_to_parquet.py:38 and available in the parquet) would disambiguate orders exactly but is unused. wallet_screen.py:56 has the same limitation, so the cross-check cannot catch it.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:65-69,87-89; /Users/corywagamaneure/projects/ml-forecasting-research/experiments/address_profile/fills_to_parquet.py:34-38 (hash available); /Users/corywagamaneure/bablyon/scratch_conv/wallet_screen.py:56.

**Effect:** HFT/bot wallets leak under the frequency caps into the eligible field; their leader edge is short-horizon and evaporates under next-5m-bar follower pricing, so they drag the field and (if train-ranked highly) the roster's follower test Sharpe down — mostly a toward-FAIL contamination plus noise in the placebo distribution. Magnitude is bounded (only same-ms merges) but concentrated at the declared filter thresholds. Grouping by (taker, coin, hash) for non-zhash fills, or at least reporting the merge rate, would resolve it.

---

## A10 [CRITICAL] (reconstruction) Follower re-pricing can be zero-lag: _post_close returns the close of the bar CONTAINING the fill, and in thin coins that close is the leader's own print — timing haircut collapses to zero

**Mechanism:** mlscreen.py:131-141 — _post_close takes i = searchsorted(times, t, 'right')-1 and returns closes[i] whenever the bar containing t exists. Bars are built from the SAME tape that contains the candidate's fills (cmd_bars line 50-59 and cmd_extract line 99-111 both filter the identical PERP fills.parquet), so the 5m bar t//300000*300000 ALWAYS exists for every candidate fill — the leader's fill is itself a print in it. Two consequences: (1) the '30-min next-bar gap tolerance' branch (lines 135-139) is dead code, it can never fire; (2) the returned 'close' is the last print in the containing bar, which in a thin alt is frequently the leader's own fill — so fol0/folc (lines 194-197) price the follower at the leader's exact price with zero elapsed time and zero market impact. The docstring/prereg promise ('next-5m-bar close post-fill', mlscreen.py:12, PREREG line 36-37) is only honored when other traders print after the leader inside the same bar. Related same-family artifact: the daily MTM close dpx (line 57: last px in the day's final bar) can also be set by the wallet's own trade in a thin coin (mark-to-own-print).

**Evidence:** mlscreen.py:131-141 (_post_close), mlscreen.py:53-57 (bars from same tape), mlscreen.py:194-197 (fol0/folc use fp), PREREG_WALLET_SCREEN.md:36-37 ('every fill re-priced at the next 5m-bar close post-fill (≤30 min gap tolerance)')

**Effect:** Systematically understates the follower timing haircut, most severely in exactly the illiquid coins where copying is hardest (leader = sole print in bar → haircut literally 0, cost reduces to spread+fee on the leader's own price). Inflates follower train Sharpe (the pre-registered ranking metric) AND follower TEST Sharpe → biases decision rules 1 and 2 toward a false PASS. Magnitude scales with the roster's alt concentration, which cmd_analyze itself shows is high (top_coin_share/major_share tracking). Fix: require the re-pricing bar close to come from a print strictly after t that is not the wallet's own fill, or use the next bar (times[i]+BAR_MS) unconditionally.

---

## A11 [CRITICAL] (reconstruction) Funding accrual is entirely absent from cmd_daily, in direct violation of the pre-registration's Reconstruction section

**Mechanism:** PREREG_WALLET_SCREEN.md:31-32 requires 'HL hourly funding accrued on positions where the repo's HL 1h dataset covers the coin; coverage fraction reported alongside results.' cmd_daily (mlscreen.py:144-225) books only price PnL: fill-day term + carry. There is no funding term anywhere; the docstring admits it ('Caveats: no funding accrual (flagged)', line 16). A copy strategy holds the leader's positions for days-to-weeks (that is the whole point of the carry term at lines 199-208), and HL funding on crowded directional alt longs is routinely tens of bps/day — over an 8-month train + 3-month test this is first-order relative to the ~9bp/side explicit cost the sim does model.

**Evidence:** mlscreen.py:16 (caveat), mlscreen.py:144-225 (no funding code path), PREREG_WALLET_SCREEN.md:31-32 (funding is a registered reconstruction requirement, not a caveat)

**Effect:** Momentum-following rosters are typically net-long trending coins that PAY funding, so omission overstates both leader and follower net PnL → biases decision rule 1 toward false PASS; it also makes the run non-compliant with the prereg (must be logged as a Deviation, undermining the single-look guarantee). What must be added before the confirmation run: per-coin hourly funding rates joined from the repo's HL 1h dataset; an hourly (or day-aggregated) position step function extending the pos_at_day logic; accrual pnl[d] -= Σ_h pos_h * px_h * rate_h applied identically to lead, fol0, folc; and the promised coverage-fraction report (share of |PnL| in funding-covered coins).

---

## A12 [MAJOR] (reconstruction) Never-return-to-flat coins are dropped wholesale (ff == -1 → continue), truncating buy-and-hold PnL and tilting selection toward round-trip traders

**Mechanism:** mlscreen.py:174-177 — flat = |cumsum(sz)|*px < $1 evaluated at each fill row (using that row's fill px as the mark, which is fine as a dust test); if no row is ever flat, the ENTIRE coin is skipped for that wallet. The prereg only registers dropping 'fills before first return-to-flat' (PREREG line 29-30); the degenerate case silently deletes every one-directional position: a wallet whose flagship trade is a multi-month accumulate-and-hold contributes ZERO from that coin to train Sharpe, to the follower sim, and to coin_abs/major_share diagnostics. Note the inclusion decision uses the FULL 140-day window, but this does not leak test data into train PnL (a coin whose first flat falls in the test window contributes zero train PnL either way), so the damage is composition, not causality.

**Evidence:** mlscreen.py:173-178 (cum/flat/ff/continue), identical logic in wallet_screen.py:102-112, PREREG_WALLET_SCREEN.md:29-30 (registers only the leading-episode drop)

**Effect:** Both never-closed winners and never-closed losers vanish, so measured wallet PnL is conditioned on round-tripping: skilled let-winners-ride traders have their best coins zeroed (train Sharpe understated → excluded from the roster), while quick-realizers are retained — a disposition-bias-shaped selection tilt. Net direction on the test: attenuates the construct the screen claims to measure ('long-window position-level PnL') and biases toward false FAIL / degraded transfer, with the composition shift growing for positions opened late in the window (held into/through test). Mitigation to consider and pre-declare: mark never-flat coins to market from first observed fill (accepting the unknown startPosition offset only affects the untraded base, not the traded delta), or at minimum report the |notional| share being discarded.

---

## A13 [MAJOR] (reconstruction) Jun 1-5 tape gap is NOT masked as documented — stale day closes defer the entire 6-day move into a single test-window day (Jun 6), and the NaN-masking code is dead

**Mechanism:** _daily_closes (mlscreen.py:125-128) has no staleness limit: searchsorted returns the last bar at-or-before each day end, so NaN occurs ONLY before a coin's first-ever bar. For the Jun 1-5 gap, day-ends resolve to the stale May 31 close → dret = 0 for days 120-124 and the FULL May-31→Jun-6 move lands as one carry lump on day 125 (carry, lines 205-208). Both 'masking' guards are therefore dead in practice: the fill-day NaN skip (line 191) can never fire because a fill's own bar guarantees a finite dpx on its day, and the carry mask (line 207) only zeroes pre-listing days where pos is 0 anyway. The docstring's claim 'Jun 1-5 tape gap (carry masked)' (line 16) is false — gap PnL is fully included, just concentrated on one day.

**Evidence:** mlscreen.py:125-128 (_daily_closes, no staleness cutoff), mlscreen.py:191 and 205-208 (dead NaN handling), mlscreen.py:16 (incorrect docstring claim); day 125 = Jun 6 falls in the test window (split_day=89 = May 1, mlscreen.py:278)

**Effect:** One synthetic 6x-magnitude day inside the TEST window inflates test daily variance, depressing the roster's test Sharpe and fattening the 5-day block-bootstrap CI (decision rule 1 biased toward FAIL); blocks containing day 125 dominate the resample. The placebo comparison (rule 2) is roughly symmetric, but rule 3's 'exclude best test month' check is distorted because June carries a fake lump. For the 8-month confirmation run, every archive MISS hour/day (prereg line 55 anticipates them) will produce the same silent lump-on-resume. The team also believes gap PnL is excluded when it is not — the belief itself is the bug. Fix: either genuinely mask (set dret spanning a known gap to 0 AND exclude those days from the Sharpe/bootstrap day count) or pre-declare the deferred-lump convention and drop gap-adjacent days from the daily series.

---

## A14 [MINOR] (reconstruction) Pre-T0 fills are clipped INTO day 0 rather than excluded — currently ~1 minute of Jan 31 tape, but a silent violation of the prereg's 'Jul 27-31 excluded' rule for the 8-month run

**Mechanism:** mlscreen.py:187 — di = clip((t - T0)//DAY_MS, 0, N_DAYS-1): any fill with t < T0 gets di = 0 and is booked as sz*(dpx[0] − px) — marked from its true pre-window price to the END of day 0, importing up to ~25 hours of pre-window price move as day-0 PnL. Today the exposure is small (tape starts 01-31 23:59, docstring line 36; and most such fills die in the leading-episode drop since row 0..ff are removed). But the pre-registered run sets T0 = 2025-08-01 with 'Jul 27-31 2025 partial month excluded' (PREREG line 55): if the partial-month file is present in the input set, the same clip will silently fold up to 5 days of fills into day 0 with multi-day pre-window moves credited to them, instead of excluding them. Symmetrically, the upper clip folds post-window fills into the LAST test day.

**Evidence:** mlscreen.py:36 (T0 comment: 'data starts 01-31 23:59'), mlscreen.py:187 (clip), same pattern wallet_screen.py:125, PREREG_WALLET_SCREEN.md:55 ('Jul 27-31 2025 partial month excluded')

**Effect:** Adds spurious pre-window PnL to train day 0 (both leader and follower, same sign per wallet — direction depends on the pre-window move, so it is noise plus a small variance distortion in train Sharpe used for roster selection); at the test end, post-window fills clipped to the last day get near-zero marks. Small at current geometry, but a one-line correctness fix (filter t >= T0 and t < T0 + N_DAYS*DAY_MS instead of clipping) removes a prereg-compliance trap before the confirmation run.

---

## A15 [CRITICAL] (follower-sim) Roster selection and placebo use LEADER train Sharpe, not the pre-registered follower-simulated train Sharpe

**Mechanism:** PREREG_WALLET_SCREEN.md:35-36 registers 'Rank eligible wallets by follower-simulated train Sharpe (not leader Sharpe)'. cmd_analyze computes tr_sh from L (the leader series): mlscreen.py:238 'L = np.array([r["lead"]...])', :240 'tr_sh = np.array([_sharpe(x[:split]) for x in L])', :241 'top = np.argsort(-tr_sh)'. The 1,000-roster placebo (decision condition 2) is also built and compared on leader series: :247 '_sharpe(port(L, rng.choice(...)))' vs '_sharpe(lead)' at :251, while conditions 1-2 of the decision rule (PREREG:42-46) are defined on the FOLLOWER-simulated roster series.

**Evidence:** mlscreen.py:238-251 vs PREREG_WALLET_SCREEN.md:34-46. Note the follower series Fc/F0 exist (:238-239) and are only reported descriptively at :252, never used for ranking or for the placebo.

**Effect:** The code computes a different cell than the one pre-registered: a different roster (leader-ranked wallets over-select immediacy/latency alpha that dies under next-bar repricing, plausibly depressing follower OOS; but sign is not guaranteed) and a placebo test on the wrong variable. Whatever number comes out, it is not the registered confirmation test — the single-look guarantee is void unless this is fixed or logged as a deviation before results are read.

---

## A16 [CRITICAL] (follower-sim) Follower 'next-bar-close' price is guaranteed by — and in thin coins equal to — the leader's own fill print, zeroing the timing haircut

**Mechanism:** Bars are built from the same tape as the fills (cmd_bars, mlscreen.py:53-59), so every leader fill at time t creates its own 5m bar. _post_close (mlscreen.py:131-141) takes the close of the bar CONTAINING t: i = searchsorted(times,t,'right')-1; since the fill's bar-start (t//300000*300000) is always present, the condition 'times[i]+BAR_MS <= t' is never true and the ≤30-min gap fallback (:135-139) is dead code — fp is never None. The bar close is the last trade in that 5m window; when the leader's fill is the last (or only) print in the bar — the normal case in sparse alts — the follower is 'filled' at the leader's exact price px, i.e. zero repricing lag, then merely +cost.

**Evidence:** mlscreen.py:131-141 (_post_close containing-bar logic), :53-59 (bars from tape itself, close = last px in bar), :194-197 (fp used for fol0/folc). PREREG_WALLET_SCREEN.md:36-37 registers 'every fill re-priced at the NEXT 5m-bar close post-fill (≤30 min gap tolerance)' — the code takes the earlier, favorable reading, and the registered gap tolerance can never fire.

**Effect:** Systematic upward bias on the follower series (the PASS/FAIL variable). The timing haircut — which the team's own edge3 work showed can be the entire short-horizon alpha (round-trip edge vanished under honest pricing; measured edge was ~24-31bp WITH a 15-min lag) — collapses toward zero exactly in illiquid coins where copy PnL concentrates. fol0 ('timing-only') and folc are both inflated, pushing decision conditions 1 and 2 toward a false PASS, and the haircut decomposition (:254) will falsely attribute everything to explicit cost.

---

## A17 [MAJOR] (follower-sim) FEE_SIDE_BPS hard-coded at 4.5bp: the pre-registered 3.0bp decision cell is neither computed nor recoverable by interpolating fol0/folc

**Mechanism:** PREREG_WALLET_SCREEN.md:37-38 declares 'cost = per-coin half-spread + 3.0bp fee per side ... decision at 3.0' with 1.5/4.5 as context. mlscreen.py:35 sets FEE_SIDE_BPS = 4.5 and :186 folds it into the only costed series (folc); the --cost-mult knob that existed in wallet_screen.py:242-243 was removed. Only fol0 (zero cost) and folc(half+4.5) are emitted (:215-217). Because per-fill cost is (half_c + fee) with coin-varying half_c, the 3.0 cell is not a linear blend of the two outputs: interpolating fol0 + (3/4.5)*(folc-fol0) scales the SPREAD component by 2/3 as well, understating total spread cost by exactly one third of the spread leg.

**Evidence:** mlscreen.py:35, :186 'cost = (half.get(c, default_half) + FEE_SIDE_BPS) / 1e4', :253-254 (only leader/f0/fc sums available to analyze) vs PREREG_WALLET_SCREEN.md:36-38.

**Effect:** Run as-is, the decision is taken at 4.5bp — conservative (biased toward FAIL) but an undeclared prereg deviation. If the team instead interpolates to reach the declared 3.0 cell, the number is biased UP by ~(1/3)*(total half-spread cost) — for alt-heavy rosters where half-spreads (several bp to tens of bp) dominate the 3bp fee, this can exceed the fee leg itself and flip condition 1 toward PASS. Either path corrupts the registered cell; cmd_daily must be re-run with fee=3.0 (and 1.5/4.5 for context).

---

## A18 [MAJOR] (follower-sim) Latent phantom-position carry: a fill skipped by the gap path is dropped from follower PnL/cost but its size still enters the carry the follower inherits

**Mechanism:** In cmd_daily, when fp is None the fill contributes nothing to fol0/folc (mlscreen.py:194-197), but its sz is unconditionally included in pos_at_day via cumsum over ALL kept fills (:199-204), and 'coin_lead += carry; fol0 += carry; folc += carry' (:208) credits the follower with the full leader carry from the next day on. A follower who could not execute the fill is thus modeled as acquiring (or shedding) the position at the day close for free — zero spread, zero fee — a non-implementable strategy. In mlscreen this path is currently dead (finding 2 shows fp is never None), but it becomes live the moment finding 2 is fixed (strictly-later-bar repricing makes gaps real, concentrated at thin coins and tape-gap boundaries like Jun 1-5). It is ALREADY live in the cross-check variant: wallet_screen.py:122 sets fol_px to NaN from external hourly candles (reachable), :132-133 skips the fill, :151 'fol_pnl += carry  # same carry: follower mirrors the position' inherits it anyway.

**Evidence:** mlscreen.py:194-197 (skip), :199-208 (carry from cumsum of all sz added to fol0/folc); wallet_screen.py:122-151 (same structure, reachable).

**Effect:** Skipped fills escape 100% of execution cost and are entered/exited at the day close, precisely in the highest-cost, widest-spread coins and around tape-gap boundaries (some in the test window). Net direction: upward on folc (cost strictly avoided; price leg roughly zero-mean), and it silently breaks the leader-vs-follower haircut comparability. Any fix of the repricing rule MUST simultaneously exclude skipped-fill sz from the follower's pos_at_day (which then requires a separate follower position track), or the corrected run re-introduces this bias.

---

## A19 [MINOR] (follower-sim) Spread model coverage: median-of-known-halves default and a stale alt spreads.parquet mis-price exactly the coins where copy PnL concentrates

**Mechanism:** mlscreen.py:146-149: half-spreads come from data/follow/spreads.parquet (measured on the earlier Feb-Jun alts-only study) overlaid with a 4-coin majors dict {BTC:0.5, ETH:0.7, SOL:1.5, HYPE:2.0}; any coin absent from both gets default_half = median of the combined dict. For the 8-month prereg window (Aug 2025-Jun 2026), coins listed, delisted, or only active outside the old measurement window fall to the median: newly-listed illiquid alts (classic copy-alpha venues, true half-spreads far above median) are UNDER-costed, while liquid non-dict majors (XRP, DOGE, etc., which the majors dict omits) are OVER-costed at an alt-median half-spread.

**Evidence:** mlscreen.py:38 (4-coin dict), :146-149 (half.update + default_half = np.median(...)), :186 (half.get(c, default_half)). PREREG_WALLET_SCREEN.md:53-54 declares 'spread proxies not BBO-derived' but does not declare the median-default for unmapped coins or the staleness of the alt measurement relative to the 8-month window.

**Effect:** Understates follower cost in the illiquid tail (bias toward PASS, correlated with where thin-coin wallets make their PnL) and overstates it for liquid non-dict majors (distorts the MAJORS-HEAVY sub-roster at mlscreen.py:263-268 downward). Second-order relative to findings 2-4, but the coverage fraction (share of traded notional priced by default_half) should be reported per the prereg's own coverage-reporting norm before the result is read.

---

## A20 [CRITICAL] (selection-stats) Hardcoded window/data constants implement the already-peeked Feb–Jun split, not the registered Aug-2025..Jun-2026 windows; running defaults re-scores the exploratory split as 'confirmation'

**Mechanism:** mlscreen.py line 36: T0 = 1769904000000 = 2026-02-01; line 37: N_DAYS = 140; main() line 278: --split-day default 89 → split at 2026-05-01 — exactly the exploratory train(Feb–Apr)/test(May–Jun) look documented in the module docstring (line 13). The prereg (lines 19-20) requires TRAIN 2025-08-01..2026-03-31, TEST 2026-04-01..2026-06-30, so the constants must become T0=1754006400000 (2025-08-01), N_DAYS=334, split_day=243 (243 train days Aug-Mar, 91 test days Apr-Jun). MONTH_FILES (lines 30-31) still includes multiday/fills.parquet, which prereg line 15-16 forbids (overlap double-counts Jun), and omits backfill_202508–202601/202606 entirely — moreover cmd_pick (line 79), cmd_extract (line 101) and _load_bars (line 116) index files by integer position, so the tag-named stats_202508.parquet etc. produced by run_backfill_months.sh (lines 23-24) are never read. FEE_SIDE_BPS=4.5 (line 35) contradicts the declared decision cost of 3.0bp/side (prereg lines 37-38), and cmd_daily bakes a single cost into daily.jsonl (lines 186, 197) so the 1.5/4.5 sensitivity brackets can't be produced either. Finally, the majors-heavy sub-roster (lines 263-268) is a second selection look; prereg line 34 declares one cell, no panel — it must be dropped or pre-declared exploratory. split_day/top_n being CLI knobs (lines 277-278) with no date-pinning is itself a post-hoc-choice vector.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:30-37,79,101,116,186,263-268,277-278; /Users/corywagamaneure/bablyon/scratch_conv/run_backfill_months.sh:10,23-26 (raw fills deleted after bars/stats, so extract/daily for the six new train months also requires re-download — not wired); /Users/corywagamaneure/bablyon/audit/edge3/PREREG_WALLET_SCREEN.md:15-20,34-39.

**Effect:** As-is, 'analyze' silently scores the split the team already inspected — a textbook selection-on-test-set artifact guaranteeing an optimistically biased 'confirmation'; the 4.5bp fee (vs registered 3.0) additionally depresses the follower net number, and the multiday overlap would double-count June fills. Concrete required changes before the run: T0=1754006400000, N_DAYS=334, split_day=243 pinned (not CLI-defaulted), MONTH_FILES={backfill_202508..202606}, drop multiday, FEE_SIDE_BPS=3.0 with 1.5/4.5 rerun brackets, delete or pre-declare the majors sub-roster.

---

## A21 [CRITICAL] (selection-stats) The pre-registered decision rule is not implemented: no day-block bootstrap CI, no robustness checks, no funding accrual

**Mechanism:** Prereg conditions (lines 42-48): (1) one-sided 95% CI > 0 under a day-block bootstrap with block=5 on the roster's follower daily series; (3) sign-robustness excluding each wallet's top-|PnL| coin and excluding the best test month. grep for 'bootstrap'/'block' across mlscreen.py, wallet_screen.py, run_backfill_months.sh returns nothing; cmd_analyze (lines 233-268) prints only point Sharpes and PnL sums. Per-coin PnL is aggregated away in cmd_daily (only top_coin_share survives into daily.jsonl, line 219), so robustness check 3a cannot even be computed from the stored artifact. Funding accrual (prereg lines 31-33: 'HL hourly funding accrued... coverage fraction reported') is absent — the docstring itself flags 'no funding accrual' (line 16).

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:16,233-268 (no CI, no exclusion reruns, no funding); /Users/corywagamaneure/bablyon/audit/edge3/PREREG_WALLET_SCREEN.md:31-33,42-48.

**Effect:** Conditions 1 and 3 are unevaluable, so PASS/FAIL will inevitably be judged by eyeballing point estimates — post-hoc inference the prereg exists to prevent. Missing funding systematically mis-states multi-day carry PnL (for the 2025-26 period, longs in majors typically PAY funding, so long-carry wallets' leader/follower PnL is inflated), biasing condition 1 toward a spurious PASS for carry-heavy rosters.

---

## A22 [MAJOR] (selection-stats) Eligibility filters use the FULL period including the test window, violating the prereg's train-only causality requirement

**Mechanism:** cmd_pick (lines 79-89) concatenates stats over ALL months — n_orders, active days, orders/day span (t_min..t_max), mean notional are all computed through June 2026, i.e., through the TEST window. The maker-exit gate applied in cmd_analyze (line 236, `r["maker_exit_share"] <= 0.30`) uses red_mk/red_n accumulated in cmd_daily over every fill, train and test alike (lines 184-185). Prereg lines 22-26: 'Eligibility (causal — computed on TRAIN window only)... maker-exit share... (train window). No test-window information may enter eligibility.'

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:79-89,184-185,236 vs /Users/corywagamaneure/bablyon/audit/edge3/PREREG_WALLET_SCREEN.md:22-26.

**Effect:** The eligible field — which defines the roster candidates, the field benchmark, AND the placebo sampling pool — is conditioned on test-window behavior: wallets must remain active (tpd 0.5-15, days>=25 easier to hit with test activity) and keep a taker-style exit profile through the test period. That is survivorship/style selection on the test set; it inflates both the roster's and the field's measured OOS performance and shifts the placebo null, corrupting conditions 1 and 2 in an optimistic direction.

---

## A23 [MAJOR] (selection-stats) Weight floor 1/max(train gross,1) lets near-zero-train-activity wallets carry weight ~1.0 and dominate roster/field/placebo portfolios; Sharpe(std=0)=0.0 ranks flat-train wallets above negative-Sharpe wallets

**Mechanism:** Line 242: `wts = 1.0/np.maximum(np.abs(L[:, :split]).sum(axis=1), 1.0)`. Normal wallets have train gross |PnL| of 1e3-1e6, giving weights 1e-3..1e-6; a wallet whose train series is ~zero (e.g., all train activity in a never-flattened coin dropped by the leading-episode filter at lines 176-177, or activity starting only in test) gets weight 1.0 — 3-6 orders of magnitude above peers — so its raw test dollars dominate `port()` output. Because Sharpe is scale-invariant, tiny-gross wallets are NOT penalized in ranking: a micro-wallet with a steady +$0.01/day train series ranks top-50 (line 241) and then enters the roster at weight ~1/max(2.4,1)≈0.4 vs peers at 1e-5. Separately, `_sharpe` (lines 228-230) returns 0.0 when std<1e-12, so wallets flat in train rank above every negative-Sharpe wallet in `np.argsort(-tr_sh)`, and such weight-1.0 wallets are drawn into the 1000 random placebo rosters (line 247) where a single one dominates that draw's series.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/mlscreen.py:228-230,241-242,247; same construction replicated in wallet_screen.py line 188, so the earlier variant cross-validates nothing here.

**Effect:** The roster's daily test series can collapse into the idiosyncratic PnL of one or a few micro/flat-train wallets, making condition 1's Sharpe a high-variance measurement of noise rather than the 50-wallet screen; in the placebo, dominated draws fatten the null's tails and raise the 95th-percentile bar for condition 2. Direction is unpredictable per run, but it converts the pre-registered test into a lottery over which degenerate wallet lands where. Fix: enforce a minimum train gross (or train order count) at eligibility and treat std=0 as NaN/excluded rather than Sharpe 0.

---


## Killed (2)

- zhash exclusion from order counting but inclusion in PnL/follower sim lets TWAP/liquidation flow bypass the frequency screen while being fully charged in the follower simulation
- Roster is ranked by LEADER train Sharpe, but the prereg registers FOLLOWER-simulated train Sharpe; placebo and OOS comparison are also run on the leader series