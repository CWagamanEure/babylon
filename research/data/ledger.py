"""Neutral exact-decimal position ledger + transition classification (WALLET_FEATURES_SPEC P1/P6/P9).

Shared math for the EXPLORATORY lane. Imports szDecimals from `schema.py` (single source for the research
lane) and re-implements the exact-integer-tick position arithmetic. `gate_a/common.py` keeps its own frozen
copy; the cross-lane equality test (P9d) `tests/test_ledger_gatea_parity.py` asserts they agree — do NOT
import gate_a here (firewall: this module must be reachable without pulling the frozen lane in).

Exactness (RESTORE §3): all position math is integer ticks = round(value · 10^szDecimals). No float, no
epsilon. Classification uses each fill's OWN `start_position` (per-row authoritative) + signed size.
"""
from __future__ import annotations
from decimal import Decimal
from typing import NamedTuple

from . import schema

SZD = schema.SZD                                  # {"BTC":5,"ETH":4,"SOL":2,"HYPE":2}
MAJORS = set(schema.MAJORS)
DUST_USD = Decimal("100")                         # $ notional floor to OPEN / for a qualifying reduction
GAP_MS = 30 * 60 * 1000                           # 30-min same-dir add-extension window
DEDUP_MS = 8 * 60 * 60 * 1000                     # 8h earliest-wins episode dedup (pass 2)
ZERO_HASH = "0x" + "0" * 64

# transition classes
INCREASE, REDUCE, CLOSE, FLIP = "INCREASE", "REDUCE", "CLOSE", "FLIP"


def ticks(dec_str: str, coin: str) -> int:
    """Exact position in integer ticks. Quantizes archive float-noise to the true protocol value."""
    q = Decimal(10) ** SZD[coin]
    return int((Decimal(dec_str) * q).to_integral_value(rounding="ROUND_HALF_UP"))


def signed_fill_ticks(side: str, sz_str: str, coin: str) -> int:
    t = ticks(sz_str, coin)
    return t if side == "B" else -t


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


class Transition(NamedTuple):
    cls: str
    q_before: int          # ticks
    q_after: int           # ticks
    close_qty: int         # ticks closed by this fill (REDUCE/CLOSE = |signed|; FLIP = |q_before|)
    residual_qty: int      # ticks of the newly-opened leg (FLIP only, else 0)
    residual_dir: int      # sign of the residual leg (FLIP only, else 0)


def classify(q_before: int, signed_fill: int) -> Transition:
    """RESTORE §3 exact-decimal transition. `dir` is reconciliation-only; arithmetic is authoritative."""
    q_after = q_before + signed_fill
    sb, sf = _sign(q_before), _sign(signed_fill)
    if q_before == 0 or sf == sb:
        return Transition(INCREASE, q_before, q_after, 0, 0, 0)
    sa = _sign(q_after)
    if sa == sb and abs(q_after) < abs(q_before):
        return Transition(REDUCE, q_before, q_after, abs(signed_fill), 0, 0)
    if q_after == 0:
        return Transition(CLOSE, q_before, q_after, abs(signed_fill), 0, 0)
    # sign flipped, nonzero residual
    return Transition(FLIP, q_before, q_after, abs(q_before), abs(q_after), sa)


# ---- flag predicates (RESTORE §5b) — a flagged fill updates the ledger but may not OPEN an episode ----
def is_zhash(hash_str: str) -> bool:
    return hash_str == ZERO_HASH


def is_liq_origin(liq_user: str | None, wallet: str) -> bool:
    return liq_user is not None and liq_user.lower() == wallet.lower()


def is_vault(dir_str: str | None) -> bool:
    return dir_str == "Net Child Vaults"


def opener_flagged(fill: dict) -> bool:
    """True ⇒ this fill may not open/extend a qualifying signal episode (still updates the ledger)."""
    return (is_zhash(fill["hash"])
            or is_liq_origin(fill.get("liq_user"), fill["wallet"])
            or is_vault(fill.get("dir")))


def notional_usd(sz_str: str, px_str: str) -> Decimal:
    return abs(Decimal(sz_str)) * Decimal(px_str)
