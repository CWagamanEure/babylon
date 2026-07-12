"""Paper follower for the ALT-COMPLEX-TIMING signal (research FINDINGS Result 9). PAPER ONLY — no signing/capital.

Each hour it polls the frozen recency-gated TIMING cohort's alt fills (top-N live wallets), computes the aggregate breadth tilt
(#net-long − #net-short)/(#active) over the alt universe, keeps an 8-hour smooth → sign position, and APPENDS a
log record (tilt, position, and the basket + BTC/ETH mids) for OFFLINE evaluation per
docs/ALT_TIMING_PAPER_PREREG.md. The follower is deliberately dumb — it only records signal + prices; the
neutralized-basket PnL / net Sharpe is computed offline (where the logic is tested), so nothing fragile runs live.

Cohort/basket/config are frozen in data/derived/alt_timing/cohort.json (export_timing_cohort.py; monthly refresh).

v2 A/B (docs/ALT_TIMING_V2_MAKER_PREREG.md, Result 9b): a MAKER-ONLY tilt (same cohort/basket, but built from
only each wallet's crossed=false passive fills) is computed and logged EACH hour as `maker_tilt`/`maker_n_active`
ALONGSIDE the unchanged v1 signal — a prospective, pre-registered A/B, never a retroactive swap. v1 is unchanged.
Any hour after that file's as_of is a genuine forward out-of-sample record.

    python -m babylon.follow.alt_timing_main --self-test    # offline: cohort load + tilt logic on synthetic fills
    python -m babylon.follow.alt_timing_main --dry-run       # ON THE DROPLET: one real poll cycle, print, exit
    python -m babylon.follow.alt_timing_main                 # run the hourly loop
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import deque
from pathlib import Path

HOUR_MS = 3_600_000
SMOOTH = 8
SETTLE_MS = 90_000            # wait this long after an hour closes before polling (let fills settle)
THROTTLE_S = 1.0             # ~1/sec ≈ HL weight budget (60 calls/min); 1500 wallets → ~25min/sweep, shares budget w/ basket
COHORT_PATH = Path("data/derived/alt_timing/cohort.json")


def hour_floor(ms: int) -> int:
    return ms - ms % HOUR_MS


def compute_tilt(fills_by_wallet: dict[str, list[dict]], alts: set[str],
                 maker_only: bool = False) -> tuple[float | None, int]:
    """Aggregate breadth tilt for one hour: over each cohort wallet's NET direction per alt coin, count
    net-buys vs net-sells across all (wallet, coin) pairs. tilt = (buys − sells)/(buys + sells).

    maker_only=True restricts to each wallet's PASSIVE (crossed=False) fills — the pre-registered v2 signal
    (research FINDINGS Result 9b: maker-side positioning carries the informed tilt; the taker fills where they
    crossed the spread dilute it, lifting honest full-window OOS IC ~4.5x in-sample). Default False = the
    deployed v1 signal, byte-identical to before; v2 is LOGGED alongside for a prospective A/B, never a swap."""
    n_buy = n_sell = 0
    for fills in fills_by_wallet.values():
        net: dict[str, float] = {}
        for f in fills:
            if maker_only and bool(f.get("crossed", False)):
                continue                                   # skip aggressor/taker fills for the v2 signal
            c = str(f["coin"])
            if c not in alts:
                continue
            sz = float(f["sz"])
            net[c] = net.get(c, 0.0) + (sz if str(f["side"]) == "B" else -sz)
        for v in net.values():
            if v > 0:
                n_buy += 1
            elif v < 0:
                n_sell += 1
    tot = n_buy + n_sell
    return ((n_buy - n_sell) / tot if tot > 0 else None), tot


def smoothed_position(buf: deque[tuple[int, float | None]]) -> tuple[float | None, float]:
    vals = [t for _, t in buf if t is not None]
    if not vals:
        return None, 0.0
    sm = sum(vals) / len(vals)
    return sm, (1.0 if sm > 0 else (-1.0 if sm < 0 else 0.0))


def _bucket_hours(fills: list[dict], alts: set[str], hours: list[int]) -> dict[int, dict[str, float]]:
    """Bucket one wallet's fills into per-hour net-per-coin (for warm-up backfill)."""
    per_hour: dict[int, dict[str, float]] = {h: {} for h in hours}
    for f in fills:
        c = str(f["coin"])
        if c not in alts:
            continue
        h = hour_floor(int(f["time"]))
        if h not in per_hour:
            continue
        sz = float(f["sz"])
        per_hour[h][c] = per_hour[h].get(c, 0.0) + (sz if str(f["side"]) == "B" else -sz)
    return per_hour


async def _poll(info, wallets: list[str], start_ms: int, end_ms: int, throttle: float) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for w in wallets:
        try:
            out[w] = await info.user_fills_by_time(w, start_ms, end_ms)
        except Exception:
            out[w] = []
        if throttle > 0:
            await asyncio.sleep(throttle)
    return out


class AltTimingFollower:
    def __init__(self, cohort_path: Path, state_dir: Path, throttle: float = THROTTLE_S):
        cfg = json.loads(cohort_path.read_text())
        self.wallets: list[str] = list(cfg["cohort"])
        self.alts: set[str] = set(cfg["alt_universe"])
        self.basket: list[str] = list(cfg["basket"])
        self.hedge: list[str] = list(cfg["hedge"])
        self.cohort_sha: str = cfg.get("cohort_sha", "?")
        self.as_of: int = int(cfg.get("as_of_hour_ms", 0))
        self.throttle = throttle
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = state_dir / "alt_timing_log.jsonl"
        self.ckpt_path = state_dir / "checkpoint.json"
        self.buf: deque[tuple[int, float | None]] = deque(maxlen=SMOOTH)
        self.last_hour = 0
        self._load_ckpt()

    def _load_ckpt(self):
        if self.ckpt_path.exists():
            c = json.loads(self.ckpt_path.read_text())
            self.buf = deque([(int(h), t) for h, t in c.get("buf", [])], maxlen=SMOOTH)
            self.last_hour = int(c.get("last_hour", 0))

    def _save_ckpt(self):
        tmp = self.ckpt_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"buf": list(self.buf), "last_hour": self.last_hour,
                                   "cohort_sha": self.cohort_sha}))
        tmp.replace(self.ckpt_path)

    async def warmup(self, info):
        """Seed the 8-hour buffer from a single [now-8h, now] poll per wallet (1 call each)."""
        now = int(time.time() * 1000)
        cur = hour_floor(now)
        hours = [cur - i * HOUR_MS for i in range(SMOOTH, 0, -1)]      # last 8 closed hours
        raw = await _poll(info, self.wallets, hours[0], cur, self.throttle)
        per_wallet_hours = {w: _bucket_hours(fs, self.alts, hours) for w, fs in raw.items()}
        for h in hours:
            n_buy = n_sell = 0
            for w in self.wallets:
                for v in per_wallet_hours[w].get(h, {}).values():
                    if v > 0:
                        n_buy += 1
                    elif v < 0:
                        n_sell += 1
            tot = n_buy + n_sell
            self.buf.append((h, (n_buy - n_sell) / tot if tot > 0 else None))
        self.last_hour = cur - HOUR_MS
        self._save_ckpt()

    async def process_hour(self, info, h_start: int) -> dict:
        """Poll [h_start, h_start+1h], compute that hour's tilt, update buffer, log with current mids."""
        raw = await _poll(info, self.wallets, h_start, h_start + HOUR_MS, self.throttle)
        tilt, n_active = compute_tilt(raw, self.alts)
        maker_tilt, maker_n = compute_tilt(raw, self.alts, maker_only=True)   # v2 pre-registered A/B (Result 9b)
        self.buf.append((h_start, tilt))
        sm, pos = smoothed_position(self.buf)
        mids = await info.all_mids()
        want = set(self.basket) | set(self.hedge)
        mid_snap = {c: str(v) for c, v in mids.mids.items() if c in want}
        rec = {"hour_ms": h_start, "tilt": tilt, "n_active": n_active,
               "maker_tilt": maker_tilt, "maker_n_active": maker_n,   # v2 (logged only; offline eval smooths+books)
               "smoothed": sm, "position": pos, "mids": mid_snap,
               "cohort_sha": self.cohort_sha, "logged_ms": int(time.time() * 1000)}
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        self.last_hour = h_start
        self._save_ckpt()
        return rec

    async def run(self, info):
        if not self.buf:
            print(f"[warmup] seeding {SMOOTH}h buffer from cohort {self.cohort_sha} ({len(self.wallets)} wallets)…",
                  flush=True)
            await self.warmup(info)
            print(f"[warmup] buffer={[round(t,3) if t is not None else None for _,t in self.buf]}", flush=True)
        while True:
            now = int(time.time() * 1000)
            h_to_process = hour_floor(now) - HOUR_MS          # the most recently CLOSED hour
            if h_to_process <= self.last_hour:
                target = hour_floor(now) + HOUR_MS + SETTLE_MS   # next hour close + settle
                await asyncio.sleep(max(1.0, (target - now) / 1000))
                continue
            rec = await self.process_hour(info, h_to_process)
            sm_s = f"{rec['smoothed']:.3f}" if rec["smoothed"] is not None else "None"
            print(f"[{time.strftime('%Y-%m-%d %H:%MZ', time.gmtime(h_to_process/1000))}] "
                  f"tilt={rec['tilt']} n={rec['n_active']} smooth={sm_s} pos={rec['position']:+.0f} "
                  f"| v2 maker_tilt={rec['maker_tilt']} maker_n={rec['maker_n_active']}", flush=True)


def _self_test():
    """Offline: verify cohort loads + tilt logic on synthetic fills (Mac can't reach the HL API)."""
    assert COHORT_PATH.exists(), f"missing {COHORT_PATH}"
    cfg = json.loads(COHORT_PATH.read_text())
    alts = set(cfg["alt_universe"])
    a, b = cfg["alt_universe"][0], cfg["alt_universe"][1]
    fills = {
        "w1": [{"coin": a, "sz": "10", "side": "B", "crossed": False, "time": 1},   # maker buy +10
               {"coin": a, "sz": "3", "side": "A", "crossed": True, "time": 2}],     # taker sell -3 → combined net +7 buy
        "w2": [{"coin": a, "sz": "5", "side": "A", "crossed": True, "time": 1}],      # taker sell -5 → combined sell; maker-only: excluded
        "w3": [{"coin": b, "sz": "1", "side": "B", "crossed": False, "time": 1},      # maker buy
               {"coin": "NOTANALT", "sz": "9", "side": "B", "crossed": False, "time": 1}],  # non-alt ignored
    }
    tilt, n = compute_tilt(fills, alts)
    assert n == 3, n                     # (w1,a)+, (w2,a)-, (w3,b)+
    assert abs(tilt - (2 - 1) / 3) < 1e-9, tilt
    mtilt, mn = compute_tilt(fills, alts, maker_only=True)   # v2: w2 is taker-only → excluded; w1-a (+10) & w3-b both maker buys
    assert mn == 2, mn
    assert abs(mtilt - 1.0) < 1e-9, mtilt
    buf = deque([(0, 1.0), (1, -1.0), (2, None), (3, 0.5)], maxlen=SMOOTH)
    sm, pos = smoothed_position(buf)
    assert abs(sm - (1.0 - 1.0 + 0.5) / 3) < 1e-9 and pos == 1.0, (sm, pos)
    print(f"SELF-TEST OK — cohort {cfg.get('cohort_sha')}, {len(cfg['cohort'])} wallets, "
          f"basket {cfg['basket']}, tilt={tilt:.3f} n={n}, smoothed={sm:.3f} pos={pos:+.0f}")


async def _amain(dry_run: bool, state_dir: Path):
    from babylon.config import Network
    from babylon.exchange.constants import endpoints_for
    from babylon.exchange.rest import InfoClient
    rest = endpoints_for(Network.MAINNET).rest
    f = AltTimingFollower(COHORT_PATH, state_dir)
    print(f"cohort {f.cohort_sha}: {len(f.wallets)} wallets, basket {f.basket}, as_of {f.as_of}", flush=True)
    async with InfoClient(rest) as info:
        if dry_run:
            print("[dry-run] warm-up + one closed-hour poll, then exit…", flush=True)
            await f.warmup(info)
            h = hour_floor(int(time.time() * 1000)) - HOUR_MS
            rec = await f.process_hour(info, h)
            print("[dry-run] record:", json.dumps(rec)[:400], flush=True)
        else:
            await f.run(info)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--state-dir", default="data/follow/alt_timing_live")
    a = ap.parse_args()
    if a.self_test:
        _self_test()
        return
    asyncio.run(_amain(a.dry_run, Path(a.state_dir)))


if __name__ == "__main__":
    main()
