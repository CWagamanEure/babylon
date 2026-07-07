"""Validate a restored month against the recorded RESTORE_PLAN oracle (protocol-semantic checks).

Reproduces the numbers in RESTORE_PLAN_v1.md §"MONTH GATE RESULT" from the tape in data/raw/fills:
total retained major fills, per-coin split, zero-hash fraction, liquidation touching/forced-origin
counts, and the exact-decimal transition classification (INCREASE/REDUCE/CLOSE/FLIP).

Transition uses each fill's OWN startPosition (RESTORE §3 — per-fill, no cross-fill ordering needed):
    signed = +sz if side=='B' else -sz;  q_before = startPosition;  q_after = q_before + signed
    all quantized to szDecimals[coin] as exact integer ticks (no epsilon).

    python -m research.data.validate 202508
"""
from __future__ import annotations

import sys
from collections import Counter
from decimal import Decimal

import pyarrow.dataset as ds

from . import schema

_QUANT = {c: Decimal(10) ** d for c, d in schema.SZD.items()}


def _ticks(dec_str: str, coin: str) -> int:
    return int((Decimal(dec_str) * _QUANT[coin]).to_integral_value(rounding="ROUND_HALF_UP"))


def _classify(coin: str, side: str, sz: str, start_position: str) -> str:
    qb = _ticks(start_position, coin)
    sgn = 1 if side == "B" else -1
    signed = sgn * _ticks(sz, coin)
    qa = qb + signed
    sb = (qb > 0) - (qb < 0)
    sf = (signed > 0) - (signed < 0)
    if qb == 0 or sf == sb:
        return "INCREASE"
    sa = (qa > 0) - (qa < 0)
    if sa == sb and abs(qa) < abs(qb):
        return "REDUCE"
    if qa == 0:
        return "CLOSE"
    return "FLIP"


ZERO_HASH = "0x" + "0" * 64


def validate_month(month: str, base: str = "data/raw/fills") -> dict:
    dset = ds.dataset(f"{base}/month={month}", format="parquet", partitioning="hive")
    cols = ["coin", "side", "sz", "start_position", "hash", "liq_user", "wallet"]
    trans: Counter = Counter()
    coins: Counter = Counter()
    total = zhash = liq_touch = liq_origin = 0
    for batch in dset.to_batches(columns=cols, batch_size=200_000):
        d = batch.to_pydict()
        n = len(d["coin"])
        total += n
        for i in range(n):
            c = d["coin"][i]
            coins[c] += 1
            trans[_classify(c, d["side"][i], d["sz"][i], d["start_position"][i])] += 1
            if d["hash"][i] == ZERO_HASH:
                zhash += 1
            lu = d["liq_user"][i]
            if lu is not None:
                liq_touch += 1
                if lu.lower() == d["wallet"][i].lower():
                    liq_origin += 1
        sys.stderr.write(f"\r  scanned {total:,} fills...")
        sys.stderr.flush()
    sys.stderr.write("\n")
    res = {"month": month, "total_major_fills": total, "coins": dict(coins),
           "transitions": dict(trans), "zhash": zhash,
           "zhash_pct": round(100 * zhash / total, 2) if total else 0,
           "liq_touching": liq_touch, "liq_forced_origin": liq_origin}
    print("=== MONTH", month, "VALIDATION ===")
    for k, v in res.items():
        print(f"  {k}: {v}")
    print("\n  Oracle (RESTORE_PLAN 2025-08): total 87,899,062 | "
          "INCREASE 45.33M REDUCE 39.55M CLOSE 1.71M FLIP 1.30M | zhash 18.2% | "
          "liq touch 605,310 forced 302,655")
    return res


if __name__ == "__main__":
    validate_month(sys.argv[1])
