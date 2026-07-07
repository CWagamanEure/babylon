"""Shared research methodology — the rigor toolkit every study imports.

The point of this package is that the statistical gauntlet is written ONCE, tested once, and reused by
every strategy study, so rigor doesn't drift per study. It directly serves the over-nulling gate in
`CLAUDE.md`: a null verdict must earn the word with a point estimate + CI, a positive-control MDE, a
cross-unit sign test, and a construction check — the functions here are the building blocks for all four.

Pure numpy + stdlib (no scipy/statsmodels — not installed). Firewalled like the rest of `research/`:
never imported into `src/babylon/`.

    from research.lib import stats, power, cv, cost, backtest
"""
