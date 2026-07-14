"""Gate-A v1.0 — module 1: exact-decimal ledger -> qualifying signal episodes (opens).
EPISODE_SPEC + RESTORE §3/§5b + ruling-A (R1 dust-wins, R3 self-cross anomaly) + quarantine (correction 4).
Input: fills for ONE (wallet, coin), each dict {ts, side, sz, px, start_position, dir, hash, liq_user,
wallet, tid}, sorted by (ts, event_index). Output: (episodes=[(open_ts, dir)], quarantine_reason|None).
No epsilon anywhere — exact integer-tick arithmetic. Flagged fills update the ledger but never open/extend.
"""
from __future__ import annotations
from decimal import Decimal
from .common import (ticks, signed_ticks, notional, pos_notional, dsign, is_flagged, DUST, GAP_MS)

INCREASE, REDUCE, CLOSE, FLIP = "INCREASE", "REDUCE", "CLOSE", "FLIP"


def classify(qb: int, sf: int) -> str:
    qa = qb + sf
    if qb == 0 or dsign(sf) == dsign(qb):
        return INCREASE
    if dsign(qa) == dsign(qb) and abs(qa) < abs(qb):
        return REDUCE
    if qa == 0:
        return CLOSE
    return FLIP


def _quarantine(fills, coin: str, missing_hours: bool) -> str | None:
    if missing_hours:
        return "missing_hourly_object"
    seen_tid = set()
    for f in fills:
        if f.get("start_position") is None:
            return "missing_startpos"
        if f["tid"] in seen_tid:                      # R3: same wallet, same tid twice = self-cross anomaly
            return "self_cross_anomaly"
        seen_tid.add(f["tid"])
    # chain consistency (exact): start_position[k+1] == start_position[k] + signed_fill[k]
    for k in range(len(fills) - 1):
        qa = ticks(fills[k]["start_position"], coin) + signed_ticks(fills[k]["side"], fills[k]["sz"], coin)
        if ticks(fills[k + 1]["start_position"], coin) != qa:
            return "chain_break"
    return None


def build_episodes(fills: list[dict], coin: str, missing_hours: bool = False):
    """Returns ([(open_ts, dir)], quarantine_reason|None). A nonzero first start_position is NOT
    quarantined — it is exactly classifiable (correction 4)."""
    q = _quarantine(fills, coin, missing_hours)
    if q is not None:
        return [], q

    episodes: list[tuple[int, int]] = []
    has_open = False
    cdir = 0
    clast = 0
    cpeak = Decimal(0)

    for f in fills:
        qb = ticks(f["start_position"], coin)
        sf = signed_ticks(f["side"], f["sz"], coin)
        qa = qb + sf
        cls = classify(qb, sf)
        flagged = is_flagged(f)
        ts = f["ts"]

        if cls == INCREASE:
            if flagged:
                if has_open:                                  # ledger grows; no open/extend of a qualifying episode
                    cpeak = max(cpeak, pos_notional(qa, coin, f["px"]))
                continue
            n = notional(f["sz"], f["px"])
            if n < DUST:                                      # dust increase never opens
                if has_open:
                    cpeak = max(cpeak, pos_notional(qa, coin, f["px"])); clast = ts
                continue
            d = dsign(sf)
            if has_open and cdir == d and (ts - clast) <= GAP_MS:
                clast = ts; cpeak = max(cpeak, pos_notional(qa, coin, f["px"]))   # same-dir add within gap: extend
            else:
                episodes.append((ts, d))                       # OPEN a new qualifying episode
                has_open = True; cdir = d; clast = ts; cpeak = pos_notional(qa, coin, f["px"])

        elif cls == REDUCE:
            floor = max(DUST, Decimal("0.10") * cpeak) if has_open else DUST
            if notional(f["sz"], f["px"]) >= floor:            # flagged or not: a real reduction terminates
                has_open = False

        elif cls == CLOSE:
            has_open = False

        else:  # FLIP: terminate prior; residual opens only if >= dust AND unflagged (R1 dust wins)
            has_open = False
            resid = pos_notional(qa, coin, f["px"])
            if resid >= DUST and not flagged:
                episodes.append((ts, dsign(qa)))
                has_open = True; cdir = dsign(qa); clast = ts; cpeak = resid

    return episodes, None
