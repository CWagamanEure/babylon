"""
xsec_book_eval — OFFLINE evaluator for the forward xsec-book paper follower (docs/XSEC_BOOK_PAPER_PREREG.md).

Reads the follower's forward log (data/follow/xsec_book_live/xsec_book_log.jsonl = per-hour {signal S_a, mids}),
reconstructs the FROZEN decile long-short book (rank S_a, top/bottom 10%, hold-band 15%, reb=4h), marks the
DEPLOYABLE raw long-short return from the logged mids (a dollar-neutral alt book self-neutralizes BTC/ETH beta to
first order — this is the actual PnL you'd earn), and charges the pre-registered cost scenarios (taker certain-fill
+ maker earn-spread × adverse-selection haircut) using the frozen per-alt impact half-spread. Reports net-per-HOUR,
day-block CI, per-block (week) breakdown, turnover, and live-gross-vs-offline decay. Nothing here runs live.

    .venv/bin/python -m research.studies.wallet_flow.xsec_book_eval [--log PATH] [--reb 4]
"""
from __future__ import annotations
import argparse, json
from collections import deque
from pathlib import Path
import numpy as np

COHORT = Path("data/derived/xsec_book/cohort.json")
LOG = Path("data/follow/xsec_book_live/xsec_book_log.jsonl")
TAKER_FEE = 2.4; MAKER_FEE = 1.0
SCEN = [("taker_top_smallclip", 1.0, TAKER_FEE, "small"), ("taker_top_impact", 1.0, TAKER_FEE, "impact"),
        ("maker_earn_a0", 1.0, MAKER_FEE, "earn"), ("maker_earn_a30", 0.7, MAKER_FEE, "earn"),
        ("maker_earn_a50", 0.5, MAKER_FEE, "earn")]


def _dayblock_ci(vals, hrs_ms, n=2000, seed=7):
    if len(vals) < 8: return (float("nan"), float("nan"))
    days = (np.array(hrs_ms) // 86_400_000).astype(np.int64); ud = np.unique(days)
    loc = {d: np.nonzero(days == d)[0] for d in ud}; rng = np.random.default_rng(seed); st = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        st.append(np.array(vals)[np.concatenate([loc[ud[p]] for p in pick])].mean())
    s = np.array(st); return (float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5)))


ALPHA_DENOISE = 0.90        # FROZEN light-EMA gain (swarm 2026-07-10: net-optimal α≈0.87–0.90, OOS-robust; level space)


def smooth_signals(recs: list[dict], alpha: float) -> dict[int, dict[str, float]]:
    """Strictly-causal per-alt level-EMA of the logged hourly signal: m_t = α·S_t + (1−α)·m_{t−1}, belief carried across
    gaps, emitted only for coins active THIS hour (same booking universe as raw). alpha=1.0 ⇒ passthrough (raw signal)."""
    if alpha >= 1.0:
        return {r["hour_ms"]: dict(r["signal"]) for r in recs}
    state: dict[str, float] = {}
    out: dict[int, dict[str, float]] = {}
    for r in sorted(recs, key=lambda x: x["hour_ms"]):        # hour order = causal
        cur = {}
        for c, v in r["signal"].items():
            state[c] = alpha * float(v) + (1.0 - alpha) * state.get(c, float(v))
            cur[c] = state[c]
        out[r["hour_ms"]] = cur
    return out


def _book(sig: dict, mids: dict, hours: list, hs: dict, hs_def: float, q1: float, q2: float, reb: int,
          phase: int = 0) -> dict:
    """Reconstruct the FROZEN decile long-short book from a (possibly smoothed) per-hour signal → per-step raw components.
    `phase` selects the rebalance grid offset (0..reb-1); deployment can't choose the phase, so callers phase-AVERAGE."""
    held_long, held_short = set(), set()
    steps = {"hr": [], "gross": [], "ntrade": [], "hstraded": [], "turn": []}
    for i in range(phase, len(hours) - reb, reb):
        h = hours[i]; hf = hours[i + reb]
        S = sig.get(h, {})
        names = [c for c in S if c in mids[h] and c in mids.get(hf, {})]
        if len(names) < 4:
            continue
        sc = np.array([S[c] for c in names]); order = np.argsort(sc)
        k1 = max(1, int(round(q1 * len(names)))); k2 = max(k1, int(round(q2 * len(names))))
        nm = np.array(names)
        top_e, top_h = set(nm[order[-k1:]]), set(nm[order[-k2:]])
        bot_e, bot_h = set(nm[order[:k1]]), set(nm[order[:k2]])
        new_long = {c for c in held_long if c in top_h}
        for c in nm[order[::-1]]:
            if len(new_long) >= k1: break
            if c in top_e: new_long.add(c)
        new_short = {c for c in held_short if c in bot_h}
        for c in nm[order]:
            if len(new_short) >= k1: break
            if c in bot_e: new_short.add(c)
        K = max(1, min(len(new_long), len(new_short)))
        rl = [np.log(mids[hf][c] / mids[h][c]) for c in new_long if mids[h].get(c)]
        rs = [np.log(mids[hf][c] / mids[h][c]) for c in new_short if mids[h].get(c)]
        if not rl or not rs:
            held_long, held_short = new_long, new_short; continue
        gross = (np.mean(rl) - np.mean(rs)) * 1e4
        traded = (new_long ^ held_long) | (new_short ^ held_short)
        steps["hr"].append(h); steps["gross"].append(gross)
        steps["ntrade"].append(len(traded) / K)
        steps["hstraded"].append(sum(hs.get(c, hs_def) for c in traded) / K)
        steps["turn"].append(len(traded) / (2 * K))
        held_long, held_short = new_long, new_short
    return steps


def _report(steps: dict, reb: int, tag: str) -> None:
    g = np.array(steps["gross"]); nt = np.array(steps["ntrade"]); hst = np.array(steps["hstraded"]); hr = steps["hr"]
    if len(g) < 8:
        print(f"  [{tag}] only {len(g)} rebalances — extend."); return
    print(f"  [{tag}] {len(g)} rebalances  gross {(g/reb).mean():+.3f}bp/hr  turn {np.mean(steps['turn']):.2f}")
    for lab, mult, fee, mode in SCEN:
        if mode == "small":
            cost = nt * fee + np.minimum(hst, nt * 1.0)
        elif mode == "impact":
            cost = nt * fee + hst
        else:
            cost = nt * fee - hst
        net = (g * mult - cost) / reb
        lo, hi = _dayblock_ci(net, hr)
        print(f"    {lab:20s} net {net.mean():+.3f}/hr CI[{lo:+.3f},{hi:+.3f}]")


def run(log_path: Path, reb: int):
    cfg = json.loads(COHORT.read_text())
    hs = {c: float(v) for c, v in cfg["impact_halfspread_bp"].items()}
    hs_def = float(np.median(list(hs.values())))
    q1, q2 = cfg["book"]["q1"], cfg["book"]["q2"]
    if not log_path.exists():
        print(f"no log yet at {log_path} — follower has not produced forward records."); return
    recs = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    recs = [r for r in recs if r["hour_ms"] >= cfg["as_of_hour_ms"]]        # OOS only
    recs.sort(key=lambda r: r["hour_ms"])
    print(f"[eval] {len(recs)} OOS hourly records; cohort {cfg['cohort_sha']} reb={reb}")
    if len(recs) < reb + 8:
        print(f"[eval] insufficient data (need ≥{reb+8} hours; min-window verdict = 3 months / 60 active days)."); return
    mids = {r["hour_ms"]: {c: float(v) for c, v in r["mids"].items()} for r in recs}
    hours = [r["hour_ms"] for r in recs]
    cons_by_hour = {r["hour_ms"]: {c: float(v) for c, v in r.get("consensus", {}).items()} for r in recs}
    has_cons = any(cons_by_hour.get(h) for h in hours)

    def apply_consensus(sig):        # rank by S_a·cons_a (unanimous cells up-weighted, contested down-weighted)
        return {h: {c: v * cons_by_hour.get(h, {}).get(c, 1.0) for c, v in s.items()} for h, s in sig.items()}
    # PRE-REGISTERED, PHASE-AVERAGED config matrix (denoise-swarm 2026-07-10 corrected the reb4-phase0 over-carry:
    # deployment can't pick the rebalance phase, so every config is booked at ALL reb offsets and the per-step series
    # pooled). (label, reb, q2, alpha):
    #   base reb4        = the original frozen book (RAW vs DENOISED α=0.90 overlay — the denoise is a small ~+4-8% tilt)
    #   reb2 maker       = the swarm's biggest, phase-ROBUST maker lever (+5.4/hr offline vs honest phase-avg reb4 +3.2)
    #                      ⚠ maker-ONLY (reb2 taker is negative) and MORE dependent on the passive-fill rate (2× rebalances
    #                      → more earned-spread) — the forward MAKER leg is exactly what resolves that.
    #   taker-hyst q0.30 = the wider-hold-band TAKER candidate (regime-gated offline; pooled here as the deployable-shape floor)
    #   consensus arms rank by S_a·cons_a (directional-consensus R input; adaptive-filter swarm: beats fixed α on the
    #   maker leg +0.46bp OOS 3/4 folds, passes matched-DoF null P=0.016 — suggestive, hurts taker, forward-only verdict).
    #   (tag, reb, q2, alpha, consensus):
    configs = [("base reb4 RAW",        4, q2,   1.0,           False),
               ("base reb4 DENOISE",    4, q2,   ALPHA_DENOISE, False),
               ("reb2 maker RAW",       2, q2,   1.0,           False),
               ("reb2 maker DENOISE",   2, q2,   ALPHA_DENOISE, False),
               ("taker-hyst reb4 q0.30", 4, 0.30, ALPHA_DENOISE, False),
               ("base reb4 CONSENSUS",  4, q2,   1.0,           True),
               ("reb2 maker CONSENSUS", 2, q2,   1.0,           True)]
    for tag, r, q2c, alpha, use_cons in configs:
        if use_cons and not has_cons:
            print(f"  [{tag} (phase-avg)] no consensus field in log yet (pre-consensus-epoch records) — skipping.")
            continue
        sig = smooth_signals(recs, alpha)
        if use_cons:
            sig = apply_consensus(sig)
        pooled = {"hr": [], "gross": [], "ntrade": [], "hstraded": [], "turn": []}
        for ph in range(r):                                   # PHASE-AVERAGE: pool all reb offsets
            st = _book(sig, mids, hours, hs, hs_def, q1, q2c, r, phase=ph)
            for k in pooled: pooled[k].extend(st[k])
        _report(pooled, r, f"{tag} (phase-avg)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(LOG)); ap.add_argument("--reb", type=int, default=4)
    a = ap.parse_args(); run(Path(a.log), a.reb)


if __name__ == "__main__":
    main()
