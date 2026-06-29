"""Per-wallet fractional-Kelly consensus weights.

Each followed wallet contributes to the per-coin consensus in proportion to its
edge — but sized as FRACTIONAL Kelly on the wallet's per-ROUND-TRIP return
distribution (NOT per-tick: per-tick Kelly mathematically floors to 0 or pins at
max on a per-round-trip copy edge — the units bug the investigation found). The
edge here is marginal and uncertain, so we use quarter-Kelly with SNR shrinkage
(full Kelly over-bets an uncertain edge) and a hard per-wallet cap. Weights are
frozen at selection (the experiment requires frozen sizing); the biweekly re-rank
is the only legal update.
"""

from __future__ import annotations

import numpy as np


def _kelly_proportional(returns: np.ndarray, fractional: float) -> float:
    """SNR-shrunk fractional-Kelly proportional weight for one wallet's round-trip
    return series (in any consistent unit). 0 if no positive edge."""
    a = np.asarray(returns, dtype=np.float64)
    if a.size < 2:
        return 0.0
    mu = float(a.mean())
    var = float(a.var())
    if var <= 0.0 or mu <= 0.0:
        return 0.0  # no demonstrated positive edge → no weight
    snr = a.size * mu * mu / var
    shrink = snr / (1.0 + snr)              # → 0 when the edge is unreliable
    return fractional * shrink * (mu / var)  # f* ≈ μ/σ² for small edges


def _cap_normalize(raw: dict[str, float], max_frac: float) -> dict[str, float]:
    """Normalize to Σ=1 with every weight ≤ max_frac (water-fill: cap the wallets that
    exceed max_frac, redistribute the freed mass to the rest, repeat)."""
    if len(raw) * max_frac < 1.0 - 1e-9:
        # cap infeasible (too few wallets to sum to 1 under it) → equal weight
        return {w: 1.0 / len(raw) for w in raw}
    capped: dict[str, float] = {}
    free = dict(raw)
    fixed_total = 0.0
    while free:
        scale = (1.0 - fixed_total) / sum(free.values())
        over = [w for w in free if free[w] * scale > max_frac]
        if not over:
            for w, v in free.items():
                capped[w] = v * scale
            break
        for w in over:
            capped[w] = max_frac
            fixed_total += max_frac
            del free[w]
    tot = sum(capped.values())
    return {w: v / tot for w, v in capped.items()} if tot > 0 else {}


def kelly_weights(
    returns_by_wallet: dict[str, np.ndarray], *,
    fractional: float = 0.25, max_frac: float = 0.05,
) -> dict[str, float]:
    """Frozen per-wallet consensus weights (Σ=1), each ≤ max_frac. Wallets with no
    positive demonstrated edge get zero weight (and are dropped from the roster)."""
    raw = {w: f for w, r in returns_by_wallet.items()
           if (f := _kelly_proportional(r, fractional)) > 0.0}
    if not raw:
        return {}
    return _cap_normalize(raw, max_frac)
