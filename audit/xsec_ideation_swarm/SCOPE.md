# IDEATION SWARM — where is the xsec selection signal being AVERAGED AWAY, and what new constructions/filters recover it?

This is a GENERATIVE swarm, not a verification pass. Goal: each agent, from its lens, proposes a RANKED list of concrete,
testable IDEAS for signal we are leaving on the table — averaging-away hypotheses, steelman constructions, new filters.
Deliverable = ideas + how to test, NOT verdicts on existing findings.

## THE SYSTEM (what exists today)
- **Signal:** ~1500 skill-weighted "informed" wallets. Each hour, per alt a: `S_a = Σ_w W_w · q_{w,a}` where
  `q_{w,a} = sign(net_flow_{w,a}) − mean(sign over w's trailing-24h traded set)` (SIZE-BLIND breadth, demeaned), and
  `W_w = max(0, θ)` = train-frozen shrunk skill weight. Rank alts by S_a each hour → DECILE long-short (top/bottom 10%,
  hold-band 15%), EQUAL-weight, full 45-alt universe, rebalance reb hours.
- **Target/estimand:** cross-sectional RANK of forward BTC/ETH(+LOO-alt-index)-residual return over the hold. Dollar-neutral
  within alts. Metric = rank-IC (in-sample z≈8, +0.023) and the decile book's net bp/hr (maker EARNS spread; taker PAYS).
- **Data:** perps only (Hyperliquid), majors + 45 liquid alts. node_fills tape (per-wallet startPosition, size, dir).

## WHAT WE'VE LEARNED (the levers + the DEAD ENDS — do NOT re-propose the dead ones)
LIVE / real:
- **Directional CONSENSUS** `cons_a=|Σ W·sign(q)|/Σ W` (within-hour cross-wallet agreement) is a real R-driver: contested cells
  fwd-IC≈0, unanimous ≈+0.05; ranking by S·cons lifts the maker book (best combined config reb2+consensus ≈ +6.3 bp/hr net,
  backtest Sharpe ~13 — MAKER-fill-dependent). Suggestive-not-significant on the paired delta; hurts the taker.
- **HARVEST HORIZON** is the biggest lever: maker net monotone-decreasing in reb (reb1 +7.5 / reb2 +6.1 / reb4 +3.2 OOS), and
  the reb2-over-reb4 edge scales with realized vol → "harvest faster" is a process-noise response.
- **Breadth** (# distinct wallets) is a real R-driver (LLN). α=0.90 time-EMA is a tiny free denoise tilt.
DEAD / redundant (DON'T re-propose): dispersion-adaptive gain (mirage, inverts OOS); per-token reliability (doesn't persist);
per-wallet RECENCY as trust (skill is persistent, short-window hurts; only online/monthly W-refresh helps); SE/vote-variance
confidence (97% collinear with breadth — redundant); heavy smoothing (α<0.6 kills gross); per-wallet carry-forward before
aggregation (collapses gross — stale votes); conviction/vol-weighting the decile (no lift + turnover cost).
THE OPEN GATE: taker is break-even/negative; the MAKER leg is where the edge lives but hinges on the PASSIVE-FILL RATE
(unmeasurable offline — a live paper follower is running to measure it). Any idea should say whether it helps the maker-fill
problem or sidesteps it (taker-tradeable).

## WHERE SIGNAL IS PLAUSIBLY BEING AVERAGED AWAY (seed hypotheses — extend, don't be limited to these)
- **Aggregation:** 1500 wallets → one number per alt. Lost: wallet correlation/clustering (double-counting), per-coin
  SPECIALISTS vs generalists, lead-lag between early-mover and follower wallets, non-linear pooling (median/trimmed vs mean).
- **Size discarded:** the signal is deliberately size-BLIND. We know size matters (whale concentration is informative). Is there
  recoverable conviction/position-building signal in notional/size that breadth averages away — WITHOUT the whale-domination bug?
- **Target/book:** EQUAL-weight decile throws away expected-return magnitude; the 45-alt universe pools liquid+illiquid; one
  fixed horizon averages over heterogeneous per-name/per-regime decay; residualization may remove real alpha.
- **Time/event:** hourly bars average within-hour timing; reb2 is the fastest we tried but faster=better — how fast can we go?
  Event-time (liquidations, funding, listings) is unmodeled.
- **Cross-sectional structure:** each alt ranked independently — pairwise/sector/relative-value relationships and the
  "rotating INTO A OUT OF B is one paired bet" structure are scored separately.

## RESOURCES
- Fast cache `data/derived/xsec_kalman/panel_cache.npz` (post-aggregation cells: R,Cc,s_inf,hours,panel_month,disp,resid_alt,
  hs_arr,folds). Full pipeline (per-wallet votes, size, consensus) = `research/studies/wallet_flow/kalman_swarm_perwallet.py`
  load (~130s DuckDB). Raw fills tape has per-wallet size/startPosition/dir. Booking engine = `xsec_concentrated_book` (CB).
  asset_ctx (DuckDB) = funding/OI/vol/mark. Reservoir = alt fills for ALL coins ([[babylon-reservoir]]).
- Prior swarms: `audit/xsec_{kalman,denoise,adaptive_filter}_swarm/`. Findings: `research/studies/wallet_flow/FINDINGS.md`.

## GUARDRAILS (so ideas are real, not fishing)
Every idea must be implementable CAUSALLY (no look-ahead). Tag each idea with: (a) the averaging-away/signal hypothesis in one
line, (b) the concrete construction, (c) how to test it + data cost (cache / pipeline / new data), (d) leakage & overfit risk,
(e) does it help the maker-fill gate or sidestep to taker, (f) rough priority (EV vs cost). Phase-average any book claim;
OOS-validate; watch multiplicity. It's fine to propose a big structural pivot — flag it as such.

## DELIVERABLE (each agent)
A RANKED list of 5–10 concrete, testable ideas from your lens, each with the tags above, plus a 1-paragraph "if I could only
test ONE thing" recommendation. Prefer ideas that are (i) high-EV, (ii) not already dead, (iii) attack a real averaging-away
point. You MAY run a quick cache-based probe to pressure-test your top idea, but the deliverable is IDEAS, not a full study.
