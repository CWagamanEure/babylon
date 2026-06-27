"""Book-wide exposure measurement.

The hard limiter (`NetRiskManager`) only constrains *total size* (net leverage,
gross, drawdown) — it's blind to direction and per-asset concentration. This
module *measures* what the limiter doesn't: how net-long/short the book is, how
concentrated it is in any one coin, and a market-neutrality proxy — so we can see
our exposure at any moment and (optionally) warn on thresholds.

Enforcement of directional / concentration caps is intentionally NOT here yet:
fixing one coin or one side needs a per-coin/per-side adjustment, which the
current uniform-scale reconciliation can't express without breaking fill
attribution. That lands with the correlation-aware allocator. For now: track +
warn. Metrics are floats (stats domain); Decimal→float is crossed on the way in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from babylon.logging import get_logger

log = get_logger("exposure")


@dataclass(frozen=True, slots=True)
class BookExposure:
    equity: float
    gross_long: float  # $ of long notional
    gross_short: float  # $ of short notional (positive)
    net_directional: float  # gross_long − gross_short (signed $; a beta proxy)
    net_leverage: float  # gross / equity
    directional_bias: float  # net_directional / gross ∈ [-1, 1]; 0 = balanced
    concentration: dict[str, float] = field(default_factory=dict)  # coin → |notional|/equity
    top_coin: str = ""
    top_concentration: float = 0.0  # max single-coin |notional| / equity

    @property
    def gross(self) -> float:
        return self.gross_long + self.gross_short

    @property
    def neutrality(self) -> float:
        """1.0 = perfectly balanced long/short $ (proxy for market-neutral);
        0.0 = entirely one-directional. Note: $-weighted, not beta-weighted —
        true beta-neutrality needs the correlation layer."""
        return 1.0 - abs(self.directional_bias)


def compute_exposure(
    net_by_coin: dict[str, Decimal], marks: dict[str, Decimal], equity: Decimal
) -> BookExposure:
    eq = float(equity)
    gross_long = 0.0
    gross_short = 0.0
    concentration: dict[str, float] = {}
    for coin, size in net_by_coin.items():
        if coin not in marks or size == 0:
            continue
        notional = float(size) * float(marks[coin])
        if notional > 0:
            gross_long += notional
        else:
            gross_short += -notional
        if eq > 0:
            concentration[coin] = abs(notional) / eq
    gross = gross_long + gross_short
    net_directional = gross_long - gross_short
    bias = net_directional / gross if gross > 0 else 0.0
    top_coin, top_conc = "", 0.0
    if concentration:
        top_coin = max(concentration, key=lambda c: concentration[c])
        top_conc = concentration[top_coin]
    return BookExposure(
        equity=eq,
        gross_long=gross_long,
        gross_short=gross_short,
        net_directional=net_directional,
        net_leverage=(gross / eq) if eq > 0 else 0.0,
        directional_bias=bias,
        concentration=concentration,
        top_coin=top_coin,
        top_concentration=top_conc,
    )


class ExposureMonitor:
    """Computes a `BookExposure` each tick and warns when soft thresholds (off by
    default) are breached. Tracks; does not enforce."""

    def __init__(
        self,
        *,
        max_directional_frac: float | None = None,  # |net directional| / equity
        max_concentration_frac: float | None = None,  # any one coin / equity
    ) -> None:
        self._max_dir = max_directional_frac
        self._max_conc = max_concentration_frac

    def assess(
        self, net_by_coin: dict[str, Decimal], marks: dict[str, Decimal], equity: Decimal
    ) -> BookExposure:
        exp = compute_exposure(net_by_coin, marks, equity)
        if self._max_dir is not None and exp.equity > 0:
            if abs(exp.net_directional) / exp.equity > self._max_dir:
                log.warning(
                    "exposure.directional",
                    net_directional=round(exp.net_directional, 2),
                    bias=round(exp.directional_bias, 3),
                    limit=self._max_dir,
                )
        if self._max_conc is not None and exp.top_concentration > self._max_conc:
            log.warning(
                "exposure.concentration",
                coin=exp.top_coin,
                frac=round(exp.top_concentration, 3),
                limit=self._max_conc,
            )
        return exp
