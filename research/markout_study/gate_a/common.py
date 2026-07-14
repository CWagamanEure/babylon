"""Gate-A v1.0 shared constants + exact-decimal helpers. Frozen values only — no new DoF."""
from __future__ import annotations
from decimal import Decimal
import hashlib

# frozen szDecimals (GATE_A_FROZEN_CONFIG; sz-grain confirmed at 4.7M-row scale)
SZD = {"BTC": 5, "ETH": 4, "SOL": 2, "HYPE": 2}
MAJORS = ("BTC", "ETH", "SOL", "HYPE")
# frozen constant F1
GLOBAL_SEED = "6439d8b356ed63376290c04f7856ab238d15f86781bb362da3f97e2ed2805288"
ZERO_HASH = "0x" + "0" * 64
DUST = Decimal("100")            # $ notional floor for opening / reduction (max($100,10%*peak))
GAP_MS = 30 * 60 * 1000          # 30-min episode gap
H = {"h1": 3_600_000, "h2": 7_200_000, "h4": 14_400_000, "h8": 28_800_000}
BAR_MS = 300_000
J = 20                           # wallet-days per horizon for H_w
N_MIN = 100
MIN_WEEKS = 6


def ticks(dec_str: str, coin: str) -> int:
    """Exact position in integer ticks = round(value * 10^szDecimals). No epsilon.
    Quantizing cleans archive float-noise (e.g. '985263.5699999999' -> exact protocol value)."""
    q = Decimal(10) ** SZD[coin]
    return int((Decimal(dec_str) * q).to_integral_value(rounding="ROUND_HALF_UP"))


def signed_ticks(side: str, sz_str: str, coin: str) -> int:
    t = ticks(sz_str, coin)
    return t if side == "B" else -t


def notional(sz_str: str, px_str: str) -> Decimal:
    return abs(Decimal(sz_str)) * Decimal(px_str)


def pos_notional(pos_ticks: int, coin: str, px_str: str) -> Decimal:
    return (abs(Decimal(pos_ticks)) / (Decimal(10) ** SZD[coin])) * Decimal(px_str)


def dsign(x: int) -> int:
    return (x > 0) - (x < 0)


def boot_seed(wallet: str, cutoff_ms: int) -> int:
    """SCORE §6: int(sha256(GLOBAL_SEED ∥ w ∥ C)) mod 2**32."""
    h = hashlib.sha256(f"{GLOBAL_SEED}{wallet}{cutoff_ms}".encode()).hexdigest()
    return int(h, 16) % (2 ** 32)


# ---- fill-flag helpers (RESTORE §5b ruling-A) ----
def is_zhash(hash_str: str) -> bool:
    return hash_str == ZERO_HASH


def is_liq_origin(liq_user: str | None, wallet: str) -> bool:
    """Narrow ruling A: forced party only (lowercase-hex compare)."""
    return liq_user is not None and liq_user.lower() == wallet.lower()


def is_vault(dir_str: str) -> bool:
    return dir_str == "Net Child Vaults"


def is_flagged(fill: dict) -> bool:
    """Flagged fills update the ledger but may not OPEN/extend a qualifying episode."""
    return (is_zhash(fill["hash"])
            or is_liq_origin(fill.get("liq_user"), fill["wallet"])
            or is_vault(fill["dir"]))
