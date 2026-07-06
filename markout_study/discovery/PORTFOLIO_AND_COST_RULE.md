# PORTFOLIO_AND_COST_RULE — exact capital, cost, and sizing

The prior study's "wallet-day" figure averaged per-decision markouts with no capital constraint, so it was an average markout statistic, not a return. This experiment defines a real, bounded capital rule so the deployment number is a return. Two sizings are reported; the wallet-day deployable rule is primary for Gate B.

## Cost model (frozen)

- Per position (episode copy): round-trip cost {BTC 8, ETH 8, SOL 10, HYPE 14} bp, charged once (entry + exit combined). Applied to the notional actually deployed.
- Explicitly excluded (stated as limitation, not modelled without BBO): latency slippage beyond the fixed bar delay, size-dependent impact, funding, partial fills, queue position. The cost schedule is an assumption; sensitivity #13 stresses it +50%.

## Sizing 1 — equal-wallet (wallet-quality reading)

Each selected wallet is one unit of capital for the month; a wallet's monthly return is the equal-weighted mean over its copied episodes' copyability returns; the basket return is the equal-weighted mean over wallets. No capital constraint across overlapping positions — this measures per-wallet quality, not a deployable book, and is labelled as such.

## Sizing 2 — wallet-day deployable (Gate-B primary)

A bounded, implementable book:

- **Total capital = 1 book.** Split equally across the **N selected wallets** (per-wallet sleeve = 1/N of the book).
- Within a wallet's sleeve, capital is split equally across that wallet's **concurrently open** copied episodes, up to a per-wallet concurrent cap **[PENDING AUDIT, target ≤ 4]**; episodes beyond the cap are skipped (logged as capacity-dropped, not silently ignored).
- **Overlapping positions share sleeve capital** — a wallet cannot hold more than its sleeve; simultaneous episodes divide it. This is the capital constraint the prior statistic lacked.
- **Coin cap:** no more than **[PENDING AUDIT, target 40%]** of the book in one coin at any time; excess signals are scaled down pro-rata (logged).
- **Repeated entries** in the same coin/direction while a position is open extend, not stack (respect the concurrent cap).
- **Exit:** the fixed band horizon (entry selection is evaluated on fixed horizons; exit optimization is deferred per `PREREGISTRATION.md` §10).
- Monthly book return = capital-weighted aggregate of realized position returns net of cost; reported per month (fold-level).

## What is logged (so caps are not silent truncation)

Per month: capital-dropped episodes (over concurrent cap), coin-cap scale-downs, average book utilization, max concurrent exposure, turnover, and the fraction of signals actually taken. A basket that only "works" by ignoring its own capacity limits must be visible as such.

## Matched to the benchmark

The Gate-C public benchmark (`PUBLIC_BENCHMARK_SPEC.md`) runs under this identical rule (same caps, same cost, same latency, same sizing variants), so the make-or-buy difference is not an implementation artifact.
