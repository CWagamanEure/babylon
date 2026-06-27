"""Kill / demote decisions from the measurement layer.

Translates per-strategy and account metrics + edge-decay signals into actions:
- **demote** a strategy (→ quarantine: stop new risk) on a per-strategy max-DD
  breach or a decayed edge;
- **halt** the account on an account-level max-DD or realized-CVaR breach.

Per ``docs/ARCHITECTURE.md``, max-DD / log-growth-decay / realized-CVaR are HARD
triggers; hit-rate and Hill-α are soft size-reductions handled elsewhere, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from babylon.stats.metrics import Metrics


@dataclass(frozen=True, slots=True)
class KillConfig:
    strat_max_drawdown: float = 0.5  # per-strategy DD → demote
    account_max_drawdown: float = 0.25  # account DD → halt
    account_cvar: float = 0.5  # account CVaR (per-period) → halt
    decay_threshold: float = 0.0  # edge EWMA below this → demote


@dataclass(frozen=True, slots=True)
class KillDecision:
    demote: set[str] = field(default_factory=set)
    halt: bool = False
    reasons: dict[str, str] = field(default_factory=dict)


class KillSwitch:
    def __init__(self, config: KillConfig | None = None) -> None:
        self._cfg = config or KillConfig()

    def evaluate(
        self,
        *,
        strat_metrics: dict[str, Metrics],
        account_metrics: Metrics | None,
        edge_decayed: dict[str, bool],
    ) -> KillDecision:
        cfg = self._cfg
        demote: set[str] = set()
        reasons: dict[str, str] = {}
        for name, m in strat_metrics.items():
            if m.max_drawdown >= cfg.strat_max_drawdown:
                demote.add(name)
                reasons[name] = f"max_dd {m.max_drawdown:.3f}"
            elif edge_decayed.get(name):
                demote.add(name)
                reasons[name] = "edge decayed"
        halt = False
        if account_metrics is not None:
            if account_metrics.max_drawdown >= cfg.account_max_drawdown:
                halt = True
                reasons["__account__"] = f"max_dd {account_metrics.max_drawdown:.3f}"
            elif account_metrics.cvar5 >= cfg.account_cvar:
                halt = True
                reasons["__account__"] = f"cvar {account_metrics.cvar5:.3f}"
        return KillDecision(demote=demote, halt=halt, reasons=reasons)
