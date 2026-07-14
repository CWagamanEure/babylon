"""Causal dollar-sized follower book for copy_cohort Arm B v2.

Architecture: ARM_B_BOOK_ARCH.md. This is intentionally post-hoc. MCMC random-path ranks are
descriptive, never finite-sample p-values.

    python -m research.studies.copy_cohort.arm_b_book
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from research.data.markout import HORIZONS, REPO_ROOT
from research.lib.cv import as_of_cutoff_ms
from research.lib.stats import inv_norm, t_ppf
from . import selectors

FOLDS = (202602, 202603, 202604, 202605, 202606)
K = selectors.K_COHORT
QS = (0.50, 0.75)
PRIMARY_Q = 0.50
RT_COST_BP = 2.6
N_PATHS = 1_000
N_CHAINS = 4
BURN_PROPOSALS = 50_000
DISPERSE_PROPOSALS = 100_000
THIN_PROPOSALS = 5_000
BALANCE_TV_MAX = 0.05
SEED = 20260713
DAY_MS = 86_400_000
H_MS = HORIZONS[selectors.H]
BASE_GLOB = selectors.BASE_GLOB
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "arm_b_book_report.json"
EQ_OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "arm_b_book_equity.json"
AXES = ("act_q", "not_q", "coin", "long_h")


def _month_bounds(test_month: int) -> tuple[int, int]:
    y, m = divmod(test_month, 100)
    prev = (y - 1) * 100 + 12 if m == 1 else test_month - 1
    return as_of_cutoff_ms(prev), as_of_cutoff_ms(test_month)


MONTH_LO = np.array([_month_bounds(t)[0] for t in FOLDS], dtype=np.int64)
MONTH_HI = np.array([_month_bounds(t)[1] for t in FOLDS], dtype=np.int64)
CAL_DAY_LO = int(MONTH_LO[0] // DAY_MS)
CAL_DAY_HI = int((MONTH_HI[-1] + H_MS - 1) // DAY_MS) + 1


def _month_idx(open_ts: np.ndarray) -> np.ndarray:
    idx = np.searchsorted(MONTH_HI, open_ts, side="right")
    clip = np.clip(idx, 0, len(FOLDS) - 1)
    good = (idx < len(FOLDS)) & (open_ts >= MONTH_LO[clip])
    return np.where(good, idx, -1)


def _expanding_clips(ep: dict, qs: tuple[float, ...] = QS) -> dict[float, np.ndarray]:
    """Exact strict-prior NumPy-linear quantiles via per-group Fenwick order statistics.

    All rows at the current timestamp are queried before any are inserted, so same-timestamp
    entries cannot size one another. O(N log group-size), unlike the inherited O(N²) prefix sort.
    """
    wallet = ep["wallet"].astype(str)
    coin = ep["coin"].astype(str)
    ts = np.asarray(ep["ts"], dtype=np.int64)
    notl = np.asarray(ep["notl"], dtype=float)
    out = {q: np.full(notl.size, np.nan) for q in qs}
    key = np.char.add(wallet, np.char.add("|", coin))
    _, starts = np.unique(key, return_index=True)
    starts = np.sort(starts)
    bounds = list(starts) + [notl.size]

    def add(tree: np.ndarray, pos: int) -> None:
        i = pos + 1
        while i < tree.size:
            tree[i] += 1; i += i & -i

    def kth(tree: np.ndarray, k: int) -> int:
        """Zero-based coordinate index of one-based order statistic k."""
        idx = 0; bit = 1 << ((tree.size - 1).bit_length() - 1)
        while bit:
            nxt = idx + bit
            if nxt < tree.size and tree[nxt] < k:
                idx = nxt; k -= int(tree[nxt])
            bit >>= 1
        return idx

    for gi in range(len(starts)):
        a, b = bounds[gi], bounds[gi + 1]
        coords, pos = np.unique(notl[a:b], return_inverse=True)
        tree = np.zeros(coords.size + 1, dtype=np.int64)
        nprev = 0; j = a
        while j < b:
            z = j + 1
            while z < b and ts[z] == ts[j]:
                z += 1
            if nprev:
                for q in qs:
                    h = (nprev - 1) * q; lo = int(np.floor(h)); hi = int(np.ceil(h)); frac = h - lo
                    vlo = coords[kth(tree, lo + 1)]; vhi = coords[kth(tree, hi + 1)]
                    out[q][j:z] = vlo + frac * (vhi - vlo)
            for p in pos[j - a:z - a]:
                add(tree, int(p))
            nprev += z - j; j = z
    return out


def _weighted_twoway_ci(ret_bp: np.ndarray, clip: np.ndarray, wallet: np.ndarray,
                        week: np.ndarray, level: float = 0.95) -> dict:
    """Ratio-estimator CI: wallet + week - wallet×week CR1 score-sandwich."""
    r = np.asarray(ret_bp, dtype=float)
    w = np.asarray(clip, dtype=float)
    if r.size == 0 or not np.isfinite(w.sum()) or w.sum() <= 0:
        return {"point_bp": None, "ci_lo": None, "ci_hi": None, "n": int(r.size)}
    mu = float(np.sum(w * r) / np.sum(w))
    psi = w * (r - mu) / np.sum(w)
    wa = np.asarray(wallet).astype(str)
    wk = np.asarray(week).astype(str)
    inter = np.char.add(wa, np.char.add("|", wk))

    def cr1(cid: np.ndarray) -> tuple[float, int]:
        _, inv = np.unique(cid, return_inverse=True)
        g = int(inv.max()) + 1
        sums = np.bincount(inv, weights=psi)
        corr = g / (g - 1) if g > 1 else 1.0
        return float(corr * np.sum(sums * sums)), g

    va, ga = cr1(wa); vb, gb = cr1(wk); vab, gab = cr1(inter)
    v = va + vb - vab
    floored = v <= 0
    if floored:
        v = max(va, vb)
    df = min(ga, gb) - 1
    if df < 4:
        return {"point_bp": mu, "ci_lo": None, "ci_hi": None, "se": float(np.sqrt(v)),
                "df": df, "floored": floored, "n": int(r.size)}
    tc = t_ppf(1 - (1 - level) / 2, df)
    se = float(np.sqrt(v))
    return {"point_bp": mu, "ci_lo": mu - tc * se, "ci_hi": mu + tc * se,
            "se": se, "df": df, "floored": floored, "n": int(r.size),
            "components": {"wallet": va, "week": vb, "wallet_week": vab,
                           "G_wallet": ga, "G_week": gb, "G_wallet_week": gab}}


def _ci_invariants() -> dict:
    r = np.array([-2.0, 3.0, 9.0, 1.0])
    w = np.array([1.0, 2.0, 4.0, 3.0])
    wallet = np.array(["a", "a", "b", "c"])
    week = np.array([1, 2, 1, 2])
    p = _weighted_twoway_ci(r, w, wallet, week)["point_bp"]
    shift = _weighted_twoway_ci(r + 5, w, wallet, week)["point_bp"]
    scale = _weighted_twoway_ci(r, w * 17, wallet, week)["point_bp"]
    dup = _weighted_twoway_ci(np.r_[r, r], np.r_[w, w], np.r_[wallet, wallet],
                              np.r_[week, week])["point_bp"]
    eq = _weighted_twoway_ci(r, np.ones_like(w), wallet, week)["point_bp"]
    checks = {"uniform_shift_5bp": abs((shift - p) - 5) < 1e-10,
              "global_clip_scale": abs(scale - p) < 1e-10,
              "all_row_duplication": abs(dup - p) < 1e-10,
              "equal_clip_point_is_mean": abs(eq - r.mean()) < 1e-10}
    if not all(checks.values()):
        raise AssertionError(f"weighted CI invariant failure: {checks}")
    return checks


@dataclass
class Selection:
    panels: list
    cohorts: list[set[str]]
    legacy_cohorts: list[set[str]]


def _selection() -> Selection:
    con = selectors.connect()
    panels, cohorts, legacy = [], [], []
    for t in FOLDS:
        y, m = divmod(t, 100)
        cutoff = (y - 1) * 100 + 12 if m == 1 else t - 1
        p = selectors.build_formation(con, cutoff, arm_b_apply_f0=True)
        c = selectors.top_k(p.score_b, p.pool, K)
        panels.append(p); cohorts.append(set(map(str, c.tolist())))
        old = selectors.build_formation(con, cutoff, arm_b_apply_f0=False)
        lc = selectors.top_k(old.score_b, old.pool, K)
        legacy.append(set(map(str, lc.tolist())))
        print(f"selection {t}: pool={p.pool.size} v2={len(c)} legacy={len(lc)} "
              f"overlap={len(cohorts[-1] & legacy[-1])}", flush=True)
    return Selection(panels, cohorts, legacy)


def _trajectory_arrays(sel: Selection) -> dict:
    sources = sorted(set().union(*sel.cohorts))
    patterns = np.array([[w in sel.cohorts[f] for f in range(len(FOLDS))] for w in sources], dtype=bool)
    candidates = sorted(set().union(*[set(map(str, p.pool.tolist())) for p in sel.panels]))
    cidx = {w: i for i, w in enumerate(candidates)}
    identity = np.array([cidx[w] for w in sources], dtype=int)
    elig = np.zeros((len(FOLDS), len(candidates)), dtype=bool)
    raw_feat = [[[None for _ in candidates] for _ in AXES] for _ in FOLDS]
    for f, p in enumerate(sel.panels):
        for w in map(str, p.pool.tolist()):
            j = cidx[w]; elig[f, j] = True
            feat = p.features[w]
            for a, name in enumerate(AXES):
                raw_feat[f][a][j] = feat[name]
    feat = np.full((len(FOLDS), len(AXES), len(candidates)), -1, dtype=int)
    ncat = []
    for a in range(len(AXES)):
        vals = sorted({raw_feat[f][a][j] for f in range(len(FOLDS)) for j in range(len(candidates))
                       if raw_feat[f][a][j] is not None}, key=str)
        code = {v: i for i, v in enumerate(vals)}; ncat.append(len(vals))
        for f in range(len(FOLDS)):
            for j, v in enumerate(raw_feat[f][a]):
                if v is not None:
                    feat[f, a, j] = code[v]
    assert np.all([elig[patterns[s], identity[s]].all() for s in range(len(sources))])
    return {"sources": sources, "patterns": patterns, "candidates": candidates,
            "identity": identity, "eligible": elig, "feature": feat, "ncat": ncat}


def _initial_balance(x: dict, assignment: np.ndarray):
    patterns, feat, ncat = x["patterns"], x["feature"], x["ncat"]
    target = [[np.zeros(ncat[a], dtype=int) for a in range(len(AXES))] for _ in FOLDS]
    for s, c in enumerate(assignment):
        for f in np.flatnonzero(patterns[s]):
            for a in range(len(AXES)):
                target[f][a][feat[f, a, c]] += 1
    counts = [[v.copy() for v in row] for row in target]
    l1 = np.zeros((len(FOLDS), len(AXES)), dtype=int)
    return target, counts, l1


def _try_move(x: dict, assignment: np.ndarray, owner: np.ndarray, target, counts, l1,
              s: int, cand: int) -> bool:
    patterns, elig, feat = x["patterns"], x["eligible"], x["feature"]
    t = int(owner[cand])
    if t == s:
        return False
    old = int(assignment[s])
    changes = [(s, old, cand)]
    if t >= 0:
        changes.append((t, cand, old))
    for slot, _, new in changes:
        if not elig[patterns[slot], new].all():
            return False
    delta: dict[tuple[int, int, int], int] = {}
    for slot, before, after in changes:
        for f in np.flatnonzero(patterns[slot]):
            for a in range(len(AXES)):
                b, n = int(feat[f, a, before]), int(feat[f, a, after])
                if b != n:
                    delta[(f, a, b)] = delta.get((f, a, b), 0) - 1
                    delta[(f, a, n)] = delta.get((f, a, n), 0) + 1
    new_l1 = l1.copy()
    by_fa: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for (f, a, cat), d in delta.items():
        by_fa.setdefault((f, a), []).append((cat, d))
    for (f, a), ds in by_fa.items():
        z = int(l1[f, a])
        for cat, d in ds:
            z += abs(int(counts[f][a][cat] + d - target[f][a][cat])) \
                 - abs(int(counts[f][a][cat] - target[f][a][cat]))
        new_l1[f, a] = z
        if z / (2 * K) > BALANCE_TV_MAX + 1e-12:
            return False
    owner[old] = t if t >= 0 else -1
    owner[cand] = s
    assignment[s] = cand
    if t >= 0:
        assignment[t] = old
    for (f, a, cat), d in delta.items():
        counts[f][a][cat] += d
    l1[:] = new_l1
    return True


def _sample_paths(x: dict) -> tuple[list[np.ndarray], list[int], dict]:
    per_chain = N_PATHS // N_CHAINS
    assert per_chain * N_CHAINS == N_PATHS
    all_states, chain_ids, chain_diag = [], [], []
    dispersed = []
    for ch in range(N_CHAINS):
        rng = np.random.default_rng(SEED + 1000 + ch)
        assn = x["identity"].copy()
        owner = np.full(len(x["candidates"]), -1, dtype=int); owner[assn] = np.arange(assn.size)
        target, counts, l1 = _initial_balance(x, assn)
        accepted = proposals = 0
        # Independently seeded warm-start construction. These moves are not sampled; they exist to
        # put the four recorded chains in dispersed feasible regions before the common burn-in.
        for _ in range(DISPERSE_PROPOSALS):
            s = int(rng.integers(0, assn.size)); c = int(rng.integers(0, owner.size))
            _try_move(x, assn, owner, target, counts, l1, s, c)
        dispersed.append(assn.copy())
        n_total = BURN_PROPOSALS + per_chain * THIN_PROPOSALS
        for step in range(n_total):
            proposals += 1
            s = int(rng.integers(0, assn.size)); c = int(rng.integers(0, owner.size))
            accepted += int(_try_move(x, assn, owner, target, counts, l1, s, c))
            if step >= BURN_PROPOSALS and (step - BURN_PROPOSALS + 1) % THIN_PROPOSALS == 0:
                all_states.append(assn.copy()); chain_ids.append(ch)
        chain_diag.append({"chain": ch, "proposals": proposals, "accepted": accepted,
                           "acceptance": accepted / proposals,
                           "final_max_tv": float(l1.max() / (2 * K)),
                           "dispersed_start_distance_from_identity":
                               _path_distance(x, dispersed[-1], x["identity"])})
    unique = len({_canonical_path(x, a) for a in all_states})
    pair_dist = [_path_distance(x, dispersed[i], dispersed[j]) for i in range(N_CHAINS)
                 for j in range(i + 1, N_CHAINS)]
    return all_states, chain_ids, {"chains": chain_diag, "unique_states": unique,
                                   "unique_fraction": unique / len(all_states),
                                   "dispersed_start_pairwise_distance_min": min(pair_dist),
                                   "dispersed_start_pairwise_distance_median": float(np.median(pair_dist))}


def _canonical_path(x: dict, assignment: np.ndarray) -> tuple:
    """Economic state, quotienting out labels of slots with identical trajectories."""
    return tuple(tuple(sorted(int(assignment[s]) for s in np.flatnonzero(x["patterns"][:, f])))
                 for f in range(len(FOLDS)))


def _path_distance(x: dict, left: np.ndarray, right: np.ndarray) -> float:
    """Mean per-fold membership replacement fraction (0=same book, 1=disjoint books)."""
    a, b = _canonical_path(x, left), _canonical_path(x, right)
    return float(np.mean([1 - len(set(a[f]) & set(b[f])) / K for f in range(len(FOLDS))]))


def _pull_episodes(wallets: list[str]) -> dict:
    con = selectors.connect()
    con.register("u_src", {"wallet": np.asarray(wallets, dtype=str)})
    con.execute("CREATE OR REPLACE TEMP TABLE u AS SELECT DISTINCT wallet FROM u_src")
    con.unregister("u_src")
    d = con.execute(f"""
      SELECT b.wallet, b.coin, b.entry_bar_ts AS ts, b.open_ts,
             b.initial_notional_usd AS notl, b.raw_markout_4h AS mk,
             b.is_liquidation_close
      FROM read_parquet('{BASE_GLOB}', hive_partitioning=false) b
      JOIN u ON b.wallet = u.wallet
      WHERE b.crossed_open AND NOT b.opener_flagged AND NOT b.entry_after_close
        AND b.entry_lag_s <= {selectors.ENTRY_LAG_MAX_S}
        AND b.initial_notional_usd > 0
      ORDER BY b.wallet, b.coin, b.entry_bar_ts""").fetchnumpy()
    d["wallet"] = d["wallet"].astype(str); d["coin"] = d["coin"].astype(str)
    d["mk"] = np.asarray(np.ma.filled(d["mk"], np.nan), dtype=float)
    return d


def _row_index(ep: dict, midx: np.ndarray) -> dict:
    out: dict[tuple[int, str], list[int]] = {}
    for i in np.flatnonzero(midx >= 0):
        out.setdefault((int(midx[i]), str(ep["wallet"][i])), []).append(int(i))
    return {k: np.asarray(v, dtype=int) for k, v in out.items()}


def _rows_for_membership(index: dict, membership: list[set[str]]) -> np.ndarray:
    parts = [index[(f, w)] for f, ws in enumerate(membership) for w in ws if (f, w) in index]
    return np.concatenate(parts) if parts else np.array([], dtype=int)


def _peak_exposure(entry: np.ndarray, exit_: np.ndarray, clip: np.ndarray) -> float:
    if clip.size == 0:
        return 0.0
    t = np.r_[entry, exit_]; d = np.r_[clip, -clip]
    order = np.argsort(t, kind="stable"); t, d = t[order], d[order]
    _, start = np.unique(t, return_index=True)
    delta = np.add.reduceat(d, start)
    return float(np.maximum(np.cumsum(delta), 0).max(initial=0.0))


def _book(ep: dict, clip: np.ndarray, index: dict, membership: list[set[str]],
          want_equity: bool = False) -> dict:
    rows = _rows_for_membership(index, membership)
    sizeable = rows[np.isfinite(clip[rows])]
    evaluable = sizeable[np.isfinite(ep["mk"][sizeable])]
    attempted_turnover = float(clip[sizeable].sum()) if sizeable.size else 0.0
    peak = _peak_exposure(ep["ts"][sizeable], ep["ts"][sizeable] + H_MS,
                          clip[sizeable]) if sizeable.size else 0.0
    out = {"n_attempted_entries": int(rows.size), "n_sizeable_attempted": int(sizeable.size),
           "n_unsizeable": int(rows.size - sizeable.size), "n_evaluable": int(evaluable.size),
           "n_censored_4h": int(sizeable.size - evaluable.size),
           "evaluable_fraction_of_sizeable": float(evaluable.size / sizeable.size) if sizeable.size else None,
           "attempted_turnover_usd": attempted_turnover, "peak_concurrent_gross_usd": peak,
           "attempted_roundtrip_cost_usd": attempted_turnover * RT_COST_BP / 1e4}
    if evaluable.size == 0:
        out.update({"net_usd": 0.0, "dollar_wtd_net_bp": None, "daily_sharpe": None})
        return out
    f = evaluable; cl = clip[f]; ret = np.asarray(ep["mk"][f], float); net_bp = ret - RT_COST_BP
    net = cl * net_bp / 1e4; gross = cl * ret / 1e4
    exit_ts = np.asarray(ep["ts"][f], np.int64) + H_MS
    exit_day = exit_ts // DAY_MS
    daily = np.zeros(CAL_DAY_HI - CAL_DAY_LO)
    np.add.at(daily, exit_day - CAL_DAY_LO, net)
    sd = float(daily.std(ddof=1)) if daily.size > 1 else 0.0
    sharpe = float(daily.mean() / sd * np.sqrt(365)) if sd > 0 else 0.0
    ux, inv = np.unique(exit_ts, return_inverse=True)
    closed = np.bincount(inv, weights=net); eq = np.cumsum(closed)
    eq0 = np.r_[0.0, eq]; peak_eq = np.maximum.accumulate(eq0)
    maxdd = float((peak_eq - eq0).max())
    wallet = ep["wallet"][f].astype(str)
    week = ((exit_day + 3) // 7).astype(str)
    ci = _weighted_twoway_ci(net_bp, cl, wallet, week)
    uw, wi = np.unique(wallet, return_inverse=True)
    wnet = np.bincount(wi, weights=net); wclip = np.bincount(wi, weights=cl)
    wpositive = np.bincount(wi, weights=np.maximum(net, 0.0))
    uwk, ki = np.unique(week, return_inverse=True)
    knet = np.bincount(ki, weights=net); kclip = np.bincount(ki, weights=cl)
    total_pos = float(net[net > 0].sum())
    loo_w = (net.sum() - wnet) / np.maximum(cl.sum() - wclip, 1e-30) * 1e4
    loo_k = (net.sum() - knet) / np.maximum(cl.sum() - kclip, 1e-30) * 1e4
    out.update({"n_wallets": int(uw.size), "evaluable_turnover_usd": float(cl.sum()),
                "gross_usd": float(gross.sum()), "net_usd": float(net.sum()),
                "dollar_wtd_gross_bp": float(gross.sum() / cl.sum() * 1e4),
                "dollar_wtd_net_bp": float(net.sum() / cl.sum() * 1e4),
                "equal_wtd_net_bp": float(net_bp.mean()), "win_rate": float((net > 0).mean()),
                "daily_sharpe": sharpe, "closed_trade_max_dd_usd": maxdd,
                "median_clip_usd": float(np.median(cl)),
                "net_return_on_peak_gross_bp": float(net.sum() / peak * 1e4) if peak else None,
                "top_trade_share_positive_pnl": float(net.max(initial=0) / total_pos) if total_pos else None,
                "top_wallet_share_positive_pnl": float(wpositive.max(initial=0) / total_pos) if total_pos else None,
                "wallet_frac_net_positive": float((wnet > 0).mean()),
                "week_frac_net_positive": float((knet > 0).mean()),
                "leave_one_wallet_net_bp_min": float(loo_w.min(initial=np.inf)),
                "leave_one_wallet_net_bp_max": float(loo_w.max(initial=-np.inf)),
                "leave_one_week_net_bp_min": float(loo_k.min(initial=np.inf)),
                "leave_one_week_net_bp_max": float(loo_k.max(initial=-np.inf)),
                "absolute_weighted_ci": ci})
    if want_equity:
        out["_equity"] = {"exit_ts": ux.tolist(), "closed_trade_equity_usd": eq.tolist(),
                          "calendar_daily_net_usd": daily.tolist(), "calendar_day_lo": CAL_DAY_LO}
    return out


def _membership_from_assignment(x: dict, assignment: np.ndarray) -> list[set[str]]:
    out = [set() for _ in FOLDS]
    for s, c in enumerate(assignment):
        w = x["candidates"][int(c)]
        for f in np.flatnonzero(x["patterns"][s]):
            out[f].add(w)
    if not all(len(v) == K for v in out):
        raise AssertionError(f"trajectory assignment broke K: {[len(v) for v in out]}")
    return out


def _one_fold(membership: list[set[str]], fold: int) -> list[set[str]]:
    return [set(v) if i == fold else set() for i, v in enumerate(membership)]


def _ess(x: np.ndarray) -> float:
    z = np.asarray(x, float); n = z.size
    if n < 3 or z.std() == 0:
        return float(n)
    z = z - z.mean(); denom = float(np.dot(z, z)); s = 0.0
    for lag in range(1, min(n // 2, 50)):
        rho = float(np.dot(z[:-lag], z[lag:]) / denom)
        if rho <= 0:
            break
        s += rho
    return float(n / (1 + 2 * s))


def _random_diagnostics(values: np.ndarray, chain_ids: list[int], real: float) -> dict:
    ids = np.asarray(chain_ids)
    ess_ret = sum(_ess(values[ids == c]) for c in range(N_CHAINS))
    tail = (values >= real).astype(float)
    ess_tail = sum(_ess(tail[ids == c]) for c in range(N_CHAINS))
    means = [float(values[ids == c].mean()) for c in range(N_CHAINS)]
    pooled_sd = float(values.std(ddof=1))
    spread = max(means) - min(means)
    return {"return_ess": ess_ret, "tail_indicator_ess": ess_tail,
            "chain_means": means, "chain_mean_spread_in_pooled_sd": spread / pooled_sd if pooled_sd else 0.0}


def run() -> dict:
    invariants = _ci_invariants()
    sel = _selection()
    x = _trajectory_arrays(sel)
    states, chain_ids, sampler = _sample_paths(x)
    overlap = np.array([[len(_membership_from_assignment(x, a)[f] & sel.cohorts[f]) / K
                         for f in range(len(FOLDS))] for a in states])
    sampler["real_wallet_overlap_median_by_fold"] = np.median(overlap, axis=0).tolist()
    sampler["real_wallet_overlap_p90_by_fold"] = np.quantile(overlap, 0.90, axis=0).tolist()
    print(f"trajectory paths: {len(states)} unique={sampler['unique_states']} ",
          f"acceptance={[round(c['acceptance'], 3) for c in sampler['chains']]}", flush=True)
    ep = _pull_episodes(x["candidates"])
    midx = _month_idx(np.asarray(ep["open_ts"], np.int64)); index = _row_index(ep, midx)
    print(f"episodes: {len(ep['wallet']):,}; test attempted rows={(midx >= 0).sum():,}", flush=True)
    real_mem = sel.cohorts
    random_mem = [_membership_from_assignment(x, a) for a in states]
    report = {"config": {"folds": FOLDS, "K": K, "qs": QS, "primary_q": PRIMARY_Q,
                         "round_trip_cost_bp": RT_COST_BP, "n_paths": N_PATHS,
                         "mcmc_rank_status": "DESCRIPTIVE_NOT_PVALUE", "seed": SEED,
                         "calendar_days": [CAL_DAY_LO, CAL_DAY_HI], "sharpe_annualizer": 365},
              "architecture": "ARM_B_BOOK_ARCH.md", "ci_invariants": invariants,
              "selection": {"v2_distinct_wallets": len(set().union(*sel.cohorts)),
                            "no_f0_corrected_pool_distinct_wallets": len(set().union(*sel.legacy_cohorts)),
                            "v2_vs_legacy_overlap_by_fold": [len(a & b) for a, b in zip(sel.cohorts, sel.legacy_cohorts)]},
              "sampler": sampler, "by_q": {}}
    equity = {}
    clips = _expanding_clips(ep)
    for q in QS:
        clip = clips[q]
        real = _book(ep, clip, index, real_mem, want_equity=True)
        equity[f"q{int(q*100)}"] = real.pop("_equity", {})
        legacy = _book(ep, clip, index, sel.legacy_cohorts)
        rb = [_book(ep, clip, index, m) for m in random_mem]
        rret = np.array([z["dollar_wtd_net_bp"] for z in rb], float)
        rnet = np.array([z["net_usd"] for z in rb], float)
        rsh = np.array([z["daily_sharpe"] for z in rb], float)
        point = float(real["dollar_wtd_net_bp"])
        rank = float((1 + np.sum(rret >= point)) / (len(rret) + 1))
        qlo, qhi = np.quantile(rret, [0.025, 0.975])
        sd0 = float(rret.std(ddof=1))
        mde = float(np.quantile(rret, 0.95) - np.quantile(rret, 0.20))
        mde_normal_diag = float((inv_norm(0.95) + inv_norm(0.80)) * sd0)
        injected_rank = float((1 + np.sum(rret >= point + 5.0)) / (len(rret) + 1))
        diag = _random_diagnostics(rret, chain_ids, point)
        valid_band = (min(c["acceptance"] for c in sampler["chains"]) >= 0.01
                      and sampler["unique_fraction"] >= 0.9 and diag["return_ess"] >= 400
                      and sd0 > 0
                      and diag["chain_mean_spread_in_pooled_sd"] <= 0.25
                      and min(c["dispersed_start_distance_from_identity"] for c in sampler["chains"]) >= 0.25
                      and sampler["dispersed_start_pairwise_distance_min"] >= 0.25)
        fold_detail = {}
        for f, t in enumerate(FOLDS):
            rf = _book(ep, clip, index, _one_fold(real_mem, f))
            rr = [_book(ep, clip, index, _one_fold(m, f))["dollar_wtd_net_bp"] for m in random_mem]
            rr = np.asarray(rr, dtype=float)
            fold_detail[str(t)] = {"real_net_bp": rf["dollar_wtd_net_bp"],
                                   "random_median_net_bp": float(np.median(rr)),
                                   "real_minus_random_median_bp": float(rf["dollar_wtd_net_bp"] - np.median(rr)),
                                   "beats_random_median": bool(rf["dollar_wtd_net_bp"] > np.median(rr)),
                                   "n_evaluable": rf["n_evaluable"]}
        rwallet = np.asarray([z["wallet_frac_net_positive"] for z in rb], dtype=float)
        rweek = np.asarray([z["week_frac_net_positive"] for z in rb], dtype=float)
        report["by_q"][f"q{int(q*100)}"] = {
            "real_v2": real, "no_f0_sensitivity_on_corrected_pool": legacy,
            "random_return_median_bp": float(np.median(rret)),
            "random_return_p90_bp": float(np.quantile(rret, 0.90)),
            "real_minus_random_median_bp": point - float(np.median(rret)),
            "descriptive_contrast_band_bp": [point - float(qhi), point - float(qlo)],
            "descriptive_rank_return": rank, "rank_NOTE": "ordinary MCMC rank; NOT a p-value",
            "null_sd_bp": sd0, "empirical_null_mde_80pct_one_sided_bp": mde,
            "normal_mde_diagnostic_bp": mde_normal_diag,
            "plus5bp_on_top_of_observed_rank": injected_rank,
            "plus5bp_NOTE": "adds 5bp atop observed enrichment; NOT standalone +5bp power",
            "random_net_usd_median": float(np.median(rnet)),
            "descriptive_rank_net_usd": float((1 + np.sum(rnet >= real["net_usd"])) / (len(rnet) + 1)),
            "random_sharpe_median": float(np.median(rsh)),
            "descriptive_rank_sharpe": float((1 + np.sum(rsh >= real["daily_sharpe"])) / (len(rsh) + 1)),
            "random_diagnostics": diag, "random_band_interpretable": bool(valid_band),
            "random_attempted_turnover_median_usd": float(np.median([z["attempted_turnover_usd"] for z in rb])),
            "random_evaluable_fraction_median": float(np.median([z["evaluable_fraction_of_sizeable"] for z in rb])),
            "descriptive_rank_wallet_breadth": float((1 + np.sum(rwallet >= real["wallet_frac_net_positive"])) / (len(rwallet) + 1)),
            "descriptive_rank_week_breadth": float((1 + np.sum(rweek >= real["week_frac_net_positive"])) / (len(rweek) + 1)),
            "fold_detail": fold_detail,
            "folds_beat_random_median": int(sum(z["beats_random_median"] for z in fold_detail.values()))}
        print(f"q{int(q*100)} v2: {point:+.2f}bp net=${real['net_usd']:,.0f} "
              f"Sharpe={real['daily_sharpe']:.2f} n={real['n_evaluable']} | "
              f"random med={np.median(rret):+.2f} rank={rank:.3f} MDE={mde:.1f}bp", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    EQ_OUT.write_text(json.dumps(equity, default=str))
    print(f"-> {OUT}")
    return report


if __name__ == "__main__":
    run()
