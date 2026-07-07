"""Thin portfolio backtester for the research lane — funding- and cost-aware, HL-perps-native.

This is the *research* backtest (does a signal have gross/net edge over time), NOT the deployment
backtest. The high-fidelity, book-replay, real-engine backtester lives in `src/babylon/backtest/`
(`babylon backtest`) and is what a strategy graduates INTO. This one is deliberately lightweight: you
hand it target positions over a bar grid, it walks the price path, accrues funding, charges cost, and
returns an equity curve with clustered/blocked-bootstrap CIs. It reuses `research.lib.cost` for costs
and `research.lib.stats` for inference so every study nets out and infers the SAME way.

Design (why it's ~vectorized): the STRATEGY already decided the targets, so there is no decision-time
path dependence — only PnL accumulation, which is a cumulative sum. Positions are tracked in UNITS
(target_notional / execution price) so price PnL and funding are exact.

Conventions
-----------
- `target_notional[t, c]` = signed USD position the strategy wants in coin c held over interval [t, t+1]
  (long > 0). NaN target ⇒ flat (0).
- Execution at bar price `price[t, c]` (pass oracle_px / mark_px from asset_ctx). No slippage beyond the
  cost model — that's the point of `cost.half_spread_bp` / `slippage_bp` (calibrate before trusting NET).
- Funding: HL pays funding on notional; a long PAYS when funding > 0. `funding[t, c]` is the per-BAR
  rate (align it to your bar cadence). funding_pnl over [t, t+1] = -units[t]·price[t]·funding[t+1].
- Returns are on EQUITY: r[t] = net_pnl[t] / equity[t]  (equity[t] = start of interval [t, t+1]).

Pure numpy + stdlib.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence
import numpy as np

from .cost import CostModel, DEFAULT
from .stats import moving_block_bootstrap_ci, BootCI

Array = np.ndarray


@dataclass
class BacktestResult:
    bar_ts: Array                 # (T,)
    coins: tuple[str, ...]
    equity: Array                 # (T,) equity curve, equity[0] = equity0
    ret: Array                    # (T-1,) per-bar net return on equity
    pnl_gross: Array              # (T-1,) price PnL per bar (pre funding/cost)
    funding_pnl: Array            # (T-1,)
    cost_paid: Array              # (T-1,) always >= 0
    turnover_usd: Array           # (T-1,) traded notional per bar
    per_coin_pnl: dict            # coin -> net PnL over the run
    periods_per_year: float
    equity0: float

    # ---- headline metrics ----
    @property
    def total_return(self) -> float:
        return self.equity[-1] / self.equity[0] - 1.0

    @property
    def ruined(self) -> bool:
        """True if equity hit 0 (a bar's loss exceeded equity) — growth metrics are then undefined."""
        return bool((self.equity <= 0).any())

    @property
    def log_growth(self) -> float:
        """Mean per-bar log return — the growth-optimal objective. -inf if the account was ruined."""
        if self.ruined:
            return float("-inf")
        return float(np.mean(np.log1p(self.ret)))

    @property
    def sharpe(self) -> float:
        """Annualized. ⚠ UNRELIABLE under heavy tails (crypto perps are) — read alongside log_growth and
        the bootstrap CI, never alone. (Same caveat the engine's stats module flags via Hill-alpha.)"""
        sd = self.ret.std(ddof=1)
        return float(self.ret.mean() / sd * np.sqrt(self.periods_per_year)) if sd > 0 else float("nan")

    @property
    def max_drawdown(self) -> float:
        peak = np.maximum.accumulate(self.equity)
        return float((self.equity / peak - 1.0).min())

    @property
    def hit_rate(self) -> float:
        nz = self.ret[self.ret != 0]
        return float((nz > 0).mean()) if nz.size else float("nan")

    @property
    def total_turnover_usd(self) -> float:
        return float(self.turnover_usd.sum())

    @property
    def cost_drag(self) -> float:
        """Total cost as a fraction of starting equity (how much the cost model ate)."""
        return float(self.cost_paid.sum() / self.equity0)

    @property
    def funding_drag(self) -> float:
        return float(self.funding_pnl.sum() / self.equity0)

    def mean_return_ci(self, level: float = 0.95, n_boot: int = 5_000, seed=None) -> BootCI:
        """Moving-block bootstrap CI on the mean per-bar return (returns are autocorrelated ⇒ block)."""
        return moving_block_bootstrap_ci(self.ret, np.mean, n_boot=n_boot, level=level, seed=seed)

    def summary(self, seed: int | None = 0) -> str:
        ci = self.mean_return_ci(seed=seed)
        lines = [
            f"bars={self.equity.size}  coins={len(self.coins)}  equity0={self.equity0:,.0f}",
        ]
        if self.ruined:
            lines.append("⚠ RUINED — equity hit 0; growth metrics undefined")
        lines += [
            f"total_return   {self.total_return:+.2%}",
            f"log_growth/bar {self.log_growth:+.5f}   (mean-ret CI [{ci.lo:+.5f}, {ci.hi:+.5f}])",
            f"sharpe (ann.)  {self.sharpe:+.2f}   ⚠ heavy-tail-unreliable",
            f"max_drawdown   {self.max_drawdown:+.2%}   hit_rate {self.hit_rate:.1%}",
            f"turnover       ${self.total_turnover_usd:,.0f}   cost_drag {self.cost_drag:+.2%}   "
            f"funding_drag {self.funding_drag:+.2%}",
        ]
        return "\n".join(lines)


def simulate(bar_ts: Sequence[int], coins: Sequence[str], price: Array,
             target_notional: Array | None = None, funding: Array | None = None,
             cost: CostModel = DEFAULT, equity0: float = 1_000_000.0,
             periods_per_year: float = 365 * 24, taker: bool = True, *,
             target_units: Array | None = None) -> BacktestResult:
    """Walk a bar grid of target positions → equity curve + attribution.

    Pass EXACTLY ONE of:
      - `target_notional[t,c]` — signed USD position to hold over [t, t+1]. ⚠ A CONSTANT notional is NOT
        a static position: units = notional/price drift with price, so a fixed notional silently re-trades
        EVERY bar and pays phantom turnover/cost (worst on fine grids — this understates net edge). To
        actually HOLD a position, use `target_units` instead.
      - `target_units[t,c]` — signed position in UNITS (coins). A constant units target = zero turnover.
    price, funding are shape (T, C), aligned to `bar_ts` (T,) and `coins` (C,). NaN target ⇒ flat.
    `periods_per_year` defaults to hourly bars; pass 365 for daily, 365*24*12 for 5-min, etc.
    """
    if (target_notional is None) == (target_units is None):
        raise ValueError("pass exactly one of target_notional / target_units")
    ts = np.asarray(bar_ts)
    px = np.asarray(price, dtype=float)
    T, C = px.shape
    if not (np.isfinite(px).all() and (px > 0).all()):
        raise ValueError("price panel must be finite and > 0 (NaN/0/inf → inf units) — clean bars first")
    if target_units is not None:
        units = np.nan_to_num(np.asarray(target_units, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    else:
        tgt = np.nan_to_num(np.asarray(target_notional, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
        units = tgt / px                                     # (T, C) target units at each bar's price
    if units.shape != (T, C):
        raise ValueError(f"target {units.shape} != price {(T, C)}")
    fund = np.zeros((T, C)) if funding is None else np.nan_to_num(np.asarray(funding, float), nan=0.0)

    per_side = cost.per_side_bp(taker) / 1e4

    equity = np.empty(T)
    equity[0] = equity0
    ret = np.empty(T - 1)
    pnl_gross = np.empty(T - 1)
    funding_pnl = np.empty(T - 1)
    cost_paid = np.empty(T - 1)
    turnover = np.empty(T - 1)
    coin_pnl = np.zeros(C)

    prev_units = np.zeros(C)
    for t in range(T - 1):
        # rebalance at t: move prev_units -> units[t] at price[t]
        traded = np.abs(units[t] - prev_units) * px[t]
        c_t = traded.sum() * per_side
        # hold units[t] over [t, t+1]
        g = units[t] * (px[t + 1] - px[t])                   # per-coin price PnL
        f = -units[t] * px[t] * fund[t + 1]                  # per-coin funding PnL (long pays if funding>0)
        coin_pnl += (g + f) - traded * per_side              # per-coin net incl. that coin's cost

        pnl_gross[t] = g.sum()
        funding_pnl[t] = f.sum()
        cost_paid[t] = c_t
        turnover[t] = traded.sum()
        net = g.sum() + f.sum() - c_t
        ret[t] = net / equity[t]
        equity[t + 1] = equity[t] + net
        prev_units = units[t]

    return BacktestResult(
        bar_ts=ts, coins=tuple(coins), equity=equity, ret=ret, pnl_gross=pnl_gross,
        funding_pnl=funding_pnl, cost_paid=cost_paid, turnover_usd=turnover,
        per_coin_pnl={c: float(coin_pnl[i]) for i, c in enumerate(coins)},
        periods_per_year=periods_per_year, equity0=equity0,
    )


def pivot_panel(rows_ts: Sequence[int], rows_coin: Sequence[str], rows_val: Sequence[float],
                coins: Sequence[str] | None = None):
    """Long (ts, coin, value) → (bar_ts, coins, panel[T,C]). Missing cells = NaN. Convenience for
    turning a DuckDB query result into `simulate()` panels without pandas.
    """
    ts_arr = np.asarray(rows_ts)
    coin_arr = np.asarray(rows_coin)
    val_arr = np.asarray(rows_val, dtype=float)
    bar_ts = np.unique(ts_arr)
    coins = list(coins) if coins is not None else sorted(set(coin_arr.tolist()))
    ti = {t: i for i, t in enumerate(bar_ts.tolist())}
    ci = {c: j for j, c in enumerate(coins)}
    panel = np.full((bar_ts.size, len(coins)), np.nan)
    for t, c, v in zip(ts_arr.tolist(), coin_arr.tolist(), val_arr.tolist()):
        if c in ci:
            panel[ti[t], ci[c]] = v
    return bar_ts, tuple(coins), panel
