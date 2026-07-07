# `research/studies/` — strategy investigations

One subdirectory per research question / candidate strategy. Every study draws on the **same data
source** (`research.data`) and the **same rigor toolkit** (`research.lib`) — it never re-plumbs either.

```
research/
  data/                 # THE data source: tape, db.connect(), episodes, features   (shared, don't fork)
  lib/                  # THE methods: null models, bootstrap CIs, MDE/power, walk-forward CV, cost, backtest
  studies/
    _template/          # copy this to start a new study
    wallet_markout/     # (markout_study folds in here later)
    <your_study>/
```

## Starting a study

```bash
cp -r research/studies/_template research/studies/funding_carry
```

Then fill in `README.md` (the question + estimand) and `preregistration.md` (locked before you look at
results). A study imports the shared layers and nothing else:

```python
from research.data.db import connect          # the data
from research.lib import stats, power, cv, cost, backtest  # the rigor + the portfolio sim
con = connect()
```

## The one rule that keeps studies from stepping on each other

**Where does an artifact go?**
- **Reusable by another study → `research/data/`** builds it into `data/derived/` (code-stamped). A 5-min
  bar lattice, a funding series, a features panel — that's *substrate*, built once by a `research/data/*.py`
  writer, queried by everyone.
- **Specific to this study → its own `out/`.** Fitted params, a cohort table, this study's figures.

Rule of thumb: *if a second study would want it, it's `data/derived/`; if only this study cares, it's
`studies/<name>/out/`.* Nobody writes to `data/raw/` except the two ingest writers.

## Non-negotiables (from `../../CLAUDE.md`)

- **Report only out-of-sample, multiplicity-controlled numbers** as results — never an in-sample figure.
  Use `research.lib.cv.walkforward_splits` for the train/test separation and `research.lib.stats.bh_fdr`
  for multiplicity.
- **A null must EARN the word.** Before writing "no effect," produce all four: point estimate + CI
  (`cluster_bootstrap_ci`), positive-control MDE ≤ care-about (`power.power_check` /
  `inject_positive_control`), cross-unit sign test (`stats.sign_test`), and a construction-conservatism
  check. Missing any → the verdict is **inconclusive**, and you surface the positive point estimate.
- **Gross vs net stay separate.** Net numbers use `research.lib.cost` and are labelled NET; the cost
  model's spread/slippage must be calibrated before a net verdict is trusted.
- **Record findings before moving on.** Keep a findings ledger in the study (`FINDINGS.md`) — question,
  method, calibrated OOS result, caveats, artifacts; register dead-ends so they aren't re-run.
- **Firewall.** `studies/` is the exploratory lane. It must never feed the frozen
  `markout_study/gate_a/` pipeline, and nothing here is imported into `src/babylon/`.

## Two backtest layers (don't confuse them)

- **`research.lib.backtest`** — the *research* portfolio sim. Hand it target positions over a bar grid; it
  walks the price path, accrues funding, charges `research.lib.cost`, and returns an equity curve with a
  moving-block bootstrap CI. Use it to establish **gross/net edge over time**. Lightweight, HL-perps-native.
- **`src/babylon/backtest/` (`babylon backtest`)** — the *deployment* backtester. Replays archived L2
  through the **real engine** (fills against book depth, real reconciler/risk). Higher fidelity, and what a
  strategy graduates INTO before capital. A study never imports it (firewall).

## When a study proves an edge

It graduates by being **re-implemented** as a `Strategy` in `src/babylon/strategy/examples/` (a clean
re-write, not a research import — firewall). The study folder stays as the evidence and provenance.
