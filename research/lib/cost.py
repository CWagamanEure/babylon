"""Trading-cost model — keep gross and net in separate namespaces, never conflate.

A shared, explicit cost skeleton so every study nets out fees + spread + slippage the SAME way, and
labels gross-vs-net everywhere (a recurring pitfall — see memory `babylon-pitfalls`). The defaults below
are PLACEHOLDERS pinned to Hyperliquid's public taker/maker schedule; the spread and slippage terms must
be CALIBRATED per coin from the L2 book (`data/l2Book/`, or BBO capture) before any net number is trusted.

⚠️ A net verdict is only as good as this calibration. Until spread/slippage are measured, report GROSS
with the cost as an explicit sensitivity band, not a single netted point.

Pure stdlib.
"""
from __future__ import annotations
from dataclasses import dataclass

# Hyperliquid public fee schedule (bps of notional). Update if tiers change.
TAKER_FEE_BP = 4.5      # placeholder — verify against current HL tier for the account
MAKER_FEE_BP = 1.5      # placeholder


@dataclass(frozen=True)
class CostModel:
    """Per-side cost in basis points of notional. All fields are bps.

    total_per_side = fee + half_spread + slippage. A round trip pays this twice (entry + exit),
    unless one leg is passive (use maker fee + 0 half-spread for a resting fill).
    """
    taker_fee_bp: float = TAKER_FEE_BP
    maker_fee_bp: float = MAKER_FEE_BP
    half_spread_bp: float = 0.0    # CALIBRATE from the book (per coin) — 0 = not yet measured
    slippage_bp: float = 0.0       # CALIBRATE: market-impact for the target clip size

    def per_side_bp(self, taker: bool = True) -> float:
        fee = self.taker_fee_bp if taker else self.maker_fee_bp
        cross = self.half_spread_bp if taker else 0.0
        return fee + cross + self.slippage_bp

    def round_trip_bp(self, taker_in: bool = True, taker_out: bool = True) -> float:
        return self.per_side_bp(taker_in) + self.per_side_bp(taker_out)

    def net_edge_bp(self, gross_edge_bp: float, taker_in: bool = True, taker_out: bool = True) -> float:
        """Gross per-round-trip edge minus the round-trip cost. Label the result NET explicitly."""
        return gross_edge_bp - self.round_trip_bp(taker_in, taker_out)


# A conservative all-taker default for quick gross→net sanity checks (spread/slippage still zero
# until calibrated — so this UNDERSTATES real cost). Do not ship a net verdict on this alone.
DEFAULT = CostModel()
