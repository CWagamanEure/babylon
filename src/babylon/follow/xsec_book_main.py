"""Paper follower for the CROSS-SECTIONAL alt-SELECTION book (research Result 10). PAPER ONLY — no signing/capital.

Each hour it polls the frozen top-1500 skill-weighted cohort's alt fills, computes the per-alt V-trail signal
    S_a = Σ_w W_w · q_trail_{w,a},   q_trail = sign(net_flow_{w,a}) − mean(sign over w's trailing-24h traded set)
(size-blind, breadth), and APPENDS a log record (the full S_a vector + live mids) for OFFLINE evaluation per
docs/XSEC_BOOK_PAPER_PREREG.md. The follower is deliberately dumb — it only records the signal + prices; the
decile long-short book, taker/maker PnL and net-per-hour are reconstructed OFFLINE (where the logic is tested),
so nothing fragile runs live. Cost uses the FROZEN per-alt impact half-spread in the cohort file (live mids are
logged for the PnL mark; per-coin L2 polling is skipped to stay within the HL weight budget).

Cohort/weights/universe frozen in data/derived/xsec_book/cohort.json (export_xsec_cohort.py; monthly refresh).
Any hour after that file's as_of_hour_ms is a genuine forward out-of-sample record.

    python -m babylon.follow.xsec_book_main --self-test   # offline: cohort load + V-trail signal on synthetic fills
    python -m babylon.follow.xsec_book_main --dry-run      # ON THE DROPLET: one real poll cycle, print, exit
    python -m babylon.follow.xsec_book_main                # run the hourly loop
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import deque
from pathlib import Path

HOUR_MS = 3_600_000
WIN_H = 24                     # V-trail trailing window (hours)
SETTLE_MS = 90_000
THROTTLE_S = 1.0              # ~1/sec ≈ HL weight budget; 1500 wallets → ~25min/sweep, shares budget w/ basket
COHORT_PATH = Path("data/derived/xsec_book/cohort.json")


def hour_floor(ms: int) -> int:
    return ms - ms % HOUR_MS


def _net_signs(fills: list[dict], alts: set[str]) -> dict[str, float]:
    """One wallet's net direction per alt this hour → {coin: +1/-1} (coins with zero net dropped)."""
    net: dict[str, float] = {}
    for f in fills:
        c = str(f["coin"])
        if c not in alts:
            continue
        sz = float(f["sz"])
        net[c] = net.get(c, 0.0) + (sz if str(f["side"]) == "B" else -sz)
    return {c: (1.0 if v > 0 else -1.0) for c, v in net.items() if v != 0}


def _evict(buf: deque, hour: int) -> None:
    while buf and buf[0][0] < hour - (WIN_H - 1) * HOUR_MS:      # keep hours [hour-23, hour]
        buf.popleft()


def compute_signal(cur_fills: dict[str, list[dict]], buffers: dict[str, deque],
                   weights: dict[str, float], alts: set[str], hour: int
                   ) -> tuple[dict[str, float], dict[str, float], int]:
    """Per-alt skill-weighted V-trail signal for the CURRENT hour. Updates each wallet's 24h sign buffer, then
    S_a = Σ_w W_w·(sign_{w,a} − trailing_mean_w). Only coins the wallet traded THIS hour contribute.
    Also returns per-alt DIRECTIONAL CONSENSUS cons_a = |Σ_w W_w·sign(q_{w,a})| / Σ_w W_w ∈ [0,1] — how unanimous the
    cohort is on that alt (adaptive-filter swarm 2026-07-10: consensus is a real R-driver; unanimous cells carry the IC,
    contested cells ≈ 0). Logged additively for the OFFLINE consensus-weighted A/B; does not affect S_a or the book."""
    S: dict[str, float] = {}
    num: dict[str, float] = {}      # Σ_w W_w·sign(q)   per alt
    den: dict[str, float] = {}      # Σ_w W_w           per alt
    n_pairs = 0
    for w, fills in cur_fills.items():
        cur = _net_signs(fills, alts)
        if not cur:
            continue
        buf = buffers.setdefault(w, deque())
        buf.append((hour, cur))
        _evict(buf, hour)
        trail = [s for _, sg in buf for s in sg.values()]        # all signs in the 24h window (incl current)
        if not trail:
            continue
        tmean = sum(trail) / len(trail)
        Ww = weights.get(w, 0.0)
        for c, sgn in cur.items():
            q = sgn - tmean
            S[c] = S.get(c, 0.0) + Ww * q
            num[c] = num.get(c, 0.0) + Ww * (1.0 if q > 0 else (-1.0 if q < 0 else 0.0))
            den[c] = den.get(c, 0.0) + Ww
            n_pairs += 1
    cons = {c: (abs(num[c]) / den[c] if den.get(c, 0.0) > 0 else 0.0) for c in S}
    return S, cons, n_pairs


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


class XsecBookFollower:
    def __init__(self, cohort_path: Path, state_dir: Path, throttle: float = THROTTLE_S):
        cfg = json.loads(cohort_path.read_text())
        self.weights: dict[str, float] = dict(cfg["cohort_weights"])
        self.wallets: list[str] = list(self.weights)
        self.alts: set[str] = set(cfg["universe"])
        self.cohort_sha: str = cfg.get("cohort_sha", "?")
        self.universe_sha: str = cfg.get("universe_sha", "?")
        self.as_of: int = int(cfg.get("as_of_hour_ms", 0))
        self.throttle = throttle
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = state_dir / "xsec_book_log.jsonl"
        self.ckpt_path = state_dir / "checkpoint.json"
        self.buffers: dict[str, deque] = {}
        self.last_hour = 0
        self._load_ckpt()

    def _load_ckpt(self):
        if self.ckpt_path.exists():
            c = json.loads(self.ckpt_path.read_text())
            self.last_hour = int(c.get("last_hour", 0))
            for w, entries in c.get("buffers", {}).items():
                self.buffers[w] = deque((int(h), {k: float(v) for k, v in sg.items()}) for h, sg in entries)

    def _save_ckpt(self):
        buf_ser = {w: [[h, sg] for h, sg in buf] for w, buf in self.buffers.items() if buf}
        tmp = self.ckpt_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"last_hour": self.last_hour, "cohort_sha": self.cohort_sha,
                                   "buffers": buf_ser}))
        tmp.replace(self.ckpt_path)

    async def warmup(self, info):
        """Seed each wallet's 24h sign buffer from a single [now-24h, now] poll per wallet."""
        now = int(time.time() * 1000)
        cur = hour_floor(now)
        hours = [cur - i * HOUR_MS for i in range(WIN_H, 0, -1)]     # last 24 closed hours, oldest→newest
        raw = await _poll(info, self.wallets, hours[0], cur, self.throttle)
        for w, fills in raw.items():
            per_hour: dict[int, list[dict]] = {}
            for f in fills:
                per_hour.setdefault(hour_floor(int(f["time"])), []).append(f)
            buf: deque = deque()
            for h in hours:
                sg = _net_signs(per_hour.get(h, []), self.alts)
                if sg:
                    buf.append((h, sg))
            _evict(buf, hours[-1])
            if buf:
                self.buffers[w] = buf
        self.last_hour = cur - HOUR_MS
        self._save_ckpt()

    async def process_hour(self, info, h_start: int) -> dict:
        raw = await _poll(info, self.wallets, h_start, h_start + HOUR_MS, self.throttle)
        S, cons, n_pairs = compute_signal(raw, self.buffers, self.weights, self.alts, h_start)
        mids = await info.all_mids()
        mid_snap = {c: str(v) for c, v in mids.mids.items() if c in self.alts}
        rec = {"hour_ms": h_start, "signal": {c: round(v, 6) for c, v in S.items()},
               "consensus": {c: round(v, 4) for c, v in cons.items()},
               "n_pairs": n_pairs, "n_alts_active": len(S), "mids": mid_snap,
               "cohort_sha": self.cohort_sha, "universe_sha": self.universe_sha,
               "logged_ms": int(time.time() * 1000)}
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        self.last_hour = h_start
        self._save_ckpt()
        return rec

    async def run(self, info):
        if not self.buffers:
            print(f"[warmup] seeding {WIN_H}h buffers from cohort {self.cohort_sha} ({len(self.wallets)} wallets)…",
                  flush=True)
            await self.warmup(info)
            print(f"[warmup] {sum(1 for b in self.buffers.values() if b)} wallets with history", flush=True)
        while True:
            now = int(time.time() * 1000)
            h_to_process = hour_floor(now) - HOUR_MS
            if h_to_process <= self.last_hour:
                target = hour_floor(now) + HOUR_MS + SETTLE_MS
                await asyncio.sleep(max(1.0, (target - now) / 1000))
                continue
            rec = await self.process_hour(info, h_to_process)
            print(f"[{time.strftime('%Y-%m-%d %H:%MZ', time.gmtime(h_to_process/1000))}] "
                  f"n_alts={rec['n_alts_active']} n_pairs={rec['n_pairs']} "
                  f"top={sorted(rec['signal'].items(), key=lambda x:-x[1])[:3]}", flush=True)


def _self_test():
    """Offline: verify cohort loads + V-trail signal logic on synthetic fills (Mac can't reach the HL API)."""
    assert COHORT_PATH.exists(), f"missing {COHORT_PATH} (run export_xsec_cohort.py)"
    cfg = json.loads(COHORT_PATH.read_text())
    alts = set(cfg["universe"]); a, b = cfg["universe"][0], cfg["universe"][1]
    W = {"w1": 2.0, "w2": 1.0}
    buffers: dict[str, deque] = {}
    # hour 0: w1 trades a (buy) + b (sell); trailing set = {+1,-1} → mean 0 → q = sign
    S0, cons0, n0 = compute_signal({"w1": [{"coin": a, "sz": "5", "side": "B", "time": 0},
                                           {"coin": b, "sz": "5", "side": "A", "time": 0}]}, buffers, W, alts, 0)
    assert abs(S0[a] - 2.0 * 1.0) < 1e-9 and abs(S0[b] - 2.0 * -1.0) < 1e-9, S0
    assert abs(cons0[a] - 1.0) < 1e-9 and abs(cons0[b] - 1.0) < 1e-9, cons0   # single wallet → unanimous
    # two wallets DISAGREE on a → consensus < 1: w1 (W2) buys a, w2 (W1) sells a; each trades a+b so tmean=0, q=±1
    buf2: dict[str, deque] = {}
    _S, _cons, _ = compute_signal({"w1": [{"coin": a, "sz": "5", "side": "B", "time": 0},
                                          {"coin": b, "sz": "5", "side": "A", "time": 0}],
                                   "w2": [{"coin": a, "sz": "5", "side": "A", "time": 0},
                                          {"coin": b, "sz": "5", "side": "B", "time": 0}]}, buf2, W, alts, 0)
    assert abs(_cons[a] - abs(2.0 - 1.0) / (2.0 + 1.0)) < 1e-9, _cons        # |+2-1|/3 = 1/3 (contested)
    # hour +1h: w1 buys a again; trailing set now {a:+1,b:-1 (h0), a:+1 (h1)} mean=(1-1+1)/3=1/3 → q=1-1/3=2/3
    h1 = HOUR_MS
    S1, _c1, _ = compute_signal({"w1": [{"coin": a, "sz": "3", "side": "B", "time": h1 + 1}]}, buffers, W, alts, h1)
    assert abs(S1[a] - 2.0 * (1.0 - 1.0 / 3.0)) < 1e-9, S1
    # eviction at h24: window is [h1, h24] (24h) → h0 drops out, h1 is the boundary and is kept
    h24 = 24 * HOUR_MS
    _ = compute_signal({"w1": [{"coin": a, "sz": "1", "side": "B", "time": h24 + 1}]}, buffers, W, alts, h24)
    assert list(buffers["w1"])[0][0] == h1, [h for h, _ in buffers["w1"]]   # h0 evicted, h1 kept (== h24-23h)
    print(f"SELF-TEST OK — cohort {cfg.get('cohort_sha')}, {len(cfg['cohort_weights'])} wallets, "
          f"{len(alts)} alts; S(h0)[a]={S0[a]:+.3f} S(h1)[a]={S1[a]:+.3f}")


async def _amain(dry_run: bool, state_dir: Path):
    from babylon.config import Network
    from babylon.exchange.constants import endpoints_for
    from babylon.exchange.rest import InfoClient
    rest = endpoints_for(Network.MAINNET).rest
    f = XsecBookFollower(COHORT_PATH, state_dir)
    print(f"cohort {f.cohort_sha}: {len(f.wallets)} wallets, {len(f.alts)} alts, as_of {f.as_of}", flush=True)
    async with InfoClient(rest) as info:
        if dry_run:
            print("[dry-run] warm-up + one closed-hour poll, then exit…", flush=True)
            await f.warmup(info)
            h = hour_floor(int(time.time() * 1000)) - HOUR_MS
            rec = await f.process_hour(info, h)
            print("[dry-run] record:", json.dumps(rec)[:500], flush=True)
        else:
            await f.run(info)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--state-dir", default="data/follow/xsec_book_live")
    a = ap.parse_args()
    if a.self_test:
        _self_test()
        return
    asyncio.run(_amain(a.dry_run, Path(a.state_dir)))


if __name__ == "__main__":
    main()
