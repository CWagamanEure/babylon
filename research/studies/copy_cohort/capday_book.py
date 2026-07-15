"""Clean causal copy-book for the top-30 capped-PnL/active-day cohort — 8h / 24h / 48h / own-exit.

Architecture: CAPDAY_BOOK_ARCH.md (v1.1, post architecture-audit A1–A17). Supersedes the RETRACTED
`book.py` (F1 masked-array Sharpe fabrication, F2 liquidation lookahead, F3 non-executable entries) by
porting `arm_b_book.py`'s leakage-clean accounting onto the user's exact capday selector and adding the two
untested levers: longer horizons (24/48h) and the wallets' OWN exit.

PRIMARY horizon = 8h (the claim under test, A6). 24h/48h/own-exit are pre-registered SECONDARY LEADS: a
positive there needs fresh-data confirmation, never a headline CONFIRMED. MCMC random-path ranks are
DESCRIPTIVE, never finite-sample p-values.

    python -m research.studies.copy_cohort.capday_book
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from research.lib.cv import MONTHS, as_of_cutoff_ms
from research.lib.stats import t_ppf
from . import base as basemod
from .base import open_base, open_close_sidecar
from .capday_cohort import _pool_scores, _window_days
# reuse the K-independent, already-audited accounting primitives verbatim
from .arm_b_book import (_weighted_twoway_ci, _expanding_clips, _ci_invariants, _peak_exposure, _ess, AXES)

# ---- config (frozen) -------------------------------------------------------------------------
CAP = 100_000.0                                # the user's cap
K = 30                                          # top-30 cohort
FOLDS = tuple(MONTHS[3:])                        # test months (first 3 consumed by the formation window)
QS = (0.50, 0.75)
PRIMARY_Q = 0.50
PRIMARY_HORIZON = "8h"                           # A6: the single headline; others are secondary leads
RT_COST_BP = 2.6                                # 2 × 1.3bp taker round-trip
DAY_MS = 86_400_000
HORIZON_MS = {"8h": 28_800_000, "24h": 86_400_000, "48h": 172_800_000, "own": None}
HORIZONS = ("8h", "24h", "48h", "own")
MK_COL = {"8h": "mk_8h", "24h": "mk_24h", "48h": "mk_48h", "own": "mk_own"}
WIDE_CI_HORIZONS = {"48h", "own"}               # A4: report both entry- & exit-week clustering, use wider
CARE_ABOUT_BP = 5.0                             # follower-economics deployable margin
ENTRY_LAG_MAX_S = 90                            # F0 / F3

# MCMC longitudinal matched-random sampler (copied from arm_b_book with LOCAL K=30) -------------
N_PATHS = 1_000
N_CHAINS = 4
BURN_PROPOSALS = 50_000
DISPERSE_PROPOSALS = 100_000
THIN_PROPOSALS = 5_000
BALANCE_TV_MAX = 0.05
SEED = 20260714

OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_book_report.json"
EQ_OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_book_equity.json"


def _cutoff_of(T: int) -> int:
    """Formation cutoff = first instant of test month T (= as_of_cutoff_ms of the PRIOR month). Strictly
    pre-test: feature/selection data must satisfy open_ts < this (audit F1 fix — was as_of_cutoff_ms(T),
    which is the first instant of T+1 and leaked the whole test month into the balancing features)."""
    return as_of_cutoff_ms(MONTHS[MONTHS.index(T) - 1])


# ============================================================================================
# Selection (capday top-30) + per-fold formation feature panel for the matched-random sampler.
# ============================================================================================
@dataclass
class Panel:
    pool: np.ndarray                 # np.str_ array of eligible (nd≥MIN_ND) wallets
    features: dict                   # wallet -> {act_q, not_q, coin, long_h}


@dataclass
class Selection:
    panels: list
    cohorts: list                    # list[set[str]] the top-30 cohort per fold
    legacy_cohorts: list = field(default_factory=list)


def _capday_features(con, pool: np.ndarray, cutoff_ms: int) -> dict:
    """Formation features over PRE-CUTOFF base episodes (A9: open_ts < cutoff only) for pool wallets.
    Mirrors selectors.py:199 quantile-bucket construction so the sampler balances comparable strata."""
    g = open_base(con)
    con.register("pf_src", {"wallet": pool.astype(str)})
    con.execute("CREATE OR REPLACE TEMP TABLE pf AS SELECT DISTINCT wallet FROM pf_src")
    con.unregister("pf_src")
    feats = con.execute(f"""
      SELECT b.wallet,
             count(*)                                              AS n_ep,
             coalesce(median(b.initial_notional_usd), 0.0)         AS med_notional,
             avg(CASE WHEN b.dir_sign > 0 THEN 1.0 ELSE 0.0 END)   AS long_share,
             max_by(b.coin, b.coin_n)                              AS majority_coin
      FROM (SELECT *, count(*) OVER (PARTITION BY wallet, coin) AS coin_n
            FROM read_parquet('{g}') WHERE open_ts < {cutoff_ms}) b
      JOIN pf ON b.wallet = pf.wallet
      GROUP BY b.wallet""").fetchnumpy()
    # A9 runtime guard: no balancing feature may read a row at/after the formation cutoff.
    mx = con.execute(f"SELECT max(open_ts) FROM read_parquet('{g}') b JOIN pf ON b.wallet=pf.wallet "
                     f"WHERE b.open_ts < {cutoff_ms}").fetchone()[0]
    assert mx is None or mx < cutoff_ms, f"A9 leak: feature open_ts {mx} >= cutoff {cutoff_ms}"
    w = feats["wallet"].astype(str)
    if w.size == 0:
        return {}
    act_edges = np.quantile(feats["n_ep"], [0.2, 0.4, 0.6, 0.8])
    not_edges = np.quantile(feats["med_notional"], [0.2, 0.4, 0.6, 0.8])
    out = {}
    for i in range(w.size):
        out[w[i]] = {
            "act_q": int(np.searchsorted(act_edges, feats["n_ep"][i], side="right")),
            "not_q": int(np.searchsorted(not_edges, feats["med_notional"][i], side="right")),
            "coin": str(feats["majority_coin"][i]),
            "long_h": int(feats["long_share"][i] >= 0.5),
        }
    return out


def _selection() -> Selection:
    con = _connect()
    panels, cohorts = [], []
    for T in FOLDS:
        lo_day, hi_day = _window_days(T)
        ps = _pool_scores(con, lo_day, hi_day, CAP)          # {wallet, metric, nd}
        pool = ps["wallet"].astype(str); metric = np.asarray(ps["metric"], float)
        # A15: deterministic top-K by (metric DESC, wallet ASC)
        order = np.lexsort((pool, -metric))                  # primary -metric (=metric desc), tie wallet asc
        cohort = pool[order][:K]
        feats = _capday_features(con, pool, _cutoff_of(T))
        # keep only pool wallets that HAVE pre-cutoff features (needed by the sampler); cohort ⊂ pool
        pool_feat = np.array([w for w in pool if w in feats], dtype=str)
        panels.append(Panel(pool_feat, feats))
        cohorts.append(set(cohort.tolist()))
        miss = [w for w in cohort.tolist() if w not in feats]
        print(f"selection {T}: pool={pool.size} feat_pool={pool_feat.size} cohort={len(cohort)} "
              f"cohort_wo_feat={len(miss)}", flush=True)
    return Selection(panels, cohorts)


# ---- MCMC trajectory-preserving matched-random sampler (LOCAL K=30) --------------------------
def _trajectory_arrays(sel: Selection) -> dict:
    candidates = sorted(set().union(*[set(p.pool.tolist()) for p in sel.panels]))
    cidx = {w: i for i, w in enumerate(candidates)}
    # The trajectory sampler balances on formation features → it can only place cohort wallets that HAVE
    # a pre-cutoff feature panel. A few top-30 wallets (selected by raw-fills PnL) have no majors crossed-
    # open base history → no features → they're dropped from the RANDOM matching only (they contribute ~no
    # followable entries: no prior notionals ⇒ un-sizeable). The REAL book still uses the full cohort.
    pool_sets = [set(p.pool.tolist()) for p in sel.panels]
    cohorts_feat = [set(w for w in sel.cohorts[f] if w in pool_sets[f]) for f in range(len(FOLDS))]
    n_dropped = sum(len(sel.cohorts[f]) - len(cohorts_feat[f]) for f in range(len(FOLDS)))
    if n_dropped:
        print(f"trajectory: dropped {n_dropped} featureless cohort-fold memberships from random matching",
              flush=True)
    sources = sorted(set().union(*cohorts_feat))
    patterns = np.array([[w in cohorts_feat[f] for f in range(len(FOLDS))] for w in sources], dtype=bool)
    identity = np.array([cidx[w] for w in sources], dtype=int)
    elig = np.zeros((len(FOLDS), len(candidates)), dtype=bool)
    raw_feat = [[[None for _ in candidates] for _ in AXES] for _ in FOLDS]
    for f, p in enumerate(sel.panels):
        for w in p.pool.tolist():
            j = cidx[w]; elig[f, j] = True
            fe = p.features[w]
            for a, name in enumerate(AXES):
                raw_feat[f][a][j] = fe[name]
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
    kf = patterns.sum(axis=0).astype(int)              # F3: actual active-source count per fold (may be <K)
    return {"sources": sources, "patterns": patterns, "candidates": candidates,
            "identity": identity, "eligible": elig, "feature": feat, "ncat": ncat, "Kf": kf}


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


def _try_move(x, assignment, owner, target, counts, l1, s, cand) -> bool:
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
    delta: dict = {}
    for slot, before, after in changes:
        for f in np.flatnonzero(patterns[slot]):
            for a in range(len(AXES)):
                b, n = int(feat[f, a, before]), int(feat[f, a, after])
                if b != n:
                    delta[(f, a, b)] = delta.get((f, a, b), 0) - 1
                    delta[(f, a, n)] = delta.get((f, a, n), 0) + 1
    new_l1 = l1.copy()
    by_fa: dict = {}
    for (f, a, cat), d in delta.items():
        by_fa.setdefault((f, a), []).append((cat, d))
    kf = x["Kf"]
    for (f, a), ds in by_fa.items():
        z = int(l1[f, a])
        for cat, d in ds:
            z += abs(int(counts[f][a][cat] + d - target[f][a][cat])) \
                 - abs(int(counts[f][a][cat] - target[f][a][cat]))
        new_l1[f, a] = z
        if z / (2 * max(int(kf[f]), 1)) > BALANCE_TV_MAX + 1e-12:   # F3: per-fold normalizer
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


def _canonical_path(x, assignment) -> tuple:
    return tuple(tuple(sorted(int(assignment[s]) for s in np.flatnonzero(x["patterns"][:, f])))
                 for f in range(len(FOLDS)))


def _path_distance(x, left, right) -> float:
    a, b = _canonical_path(x, left), _canonical_path(x, right)
    return float(np.mean([1 - len(set(a[f]) & set(b[f])) / max(len(a[f]), 1) for f in range(len(FOLDS))]))


def _sample_paths(x):
    per_chain = N_PATHS // N_CHAINS
    all_states, chain_ids, chain_diag, dispersed = [], [], [], []
    for ch in range(N_CHAINS):
        rng = np.random.default_rng(SEED + 1000 + ch)
        assn = x["identity"].copy()
        owner = np.full(len(x["candidates"]), -1, dtype=int); owner[assn] = np.arange(assn.size)
        target, counts, l1 = _initial_balance(x, assn)
        accepted = proposals = 0
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
        kf = np.maximum(x["Kf"], 1)
        chain_diag.append({"chain": ch, "acceptance": accepted / proposals,
                           "final_max_tv": float((l1 / (2 * kf[:, None])).max()),
                           "dispersed_start_distance_from_identity":
                               _path_distance(x, dispersed[-1], x["identity"])})
    unique = len({_canonical_path(x, a) for a in all_states})
    pair = [_path_distance(x, dispersed[i], dispersed[j]) for i in range(N_CHAINS)
            for j in range(i + 1, N_CHAINS)]
    return all_states, chain_ids, {"chains": chain_diag, "unique_states": unique,
                                   "unique_fraction": unique / len(all_states),
                                   "dispersed_start_pairwise_distance_min": min(pair)}


def _membership_from_assignment(x, assignment) -> list:
    out = [set() for _ in FOLDS]
    for s, c in enumerate(assignment):
        w = x["candidates"][int(c)]
        for f in np.flatnonzero(x["patterns"][s]):
            out[f].add(w)
    return out


def _one_fold(membership, fold) -> list:
    return [set(v) if i == fold else set() for i, v in enumerate(membership)]


def _random_diagnostics(values: np.ndarray, chain_ids: list, real: float) -> dict:
    """F2: convergence/interpretability of the descriptive random band (ported from arm_b)."""
    ids = np.asarray(chain_ids)
    ess_ret = sum(_ess(values[ids == c]) for c in range(N_CHAINS))
    means = [float(values[ids == c].mean()) for c in range(N_CHAINS) if (ids == c).any()]
    pooled_sd = float(values.std(ddof=1)) if values.size > 1 else 0.0
    spread = (max(means) - min(means)) if means else 0.0
    return {"return_ess": ess_ret, "chain_means": means, "pooled_sd": pooled_sd,
            "chain_mean_spread_in_pooled_sd": spread / pooled_sd if pooled_sd else 0.0}


# ============================================================================================
# Episode pull (A11: from base directly, F0/F2/F3 guards) + own-exit sidecar join.
# ============================================================================================
def _pull_episodes(con, wallets: list[str]) -> dict:
    g = open_base(con); close_glob = open_close_sidecar()
    con.register("u_src", {"wallet": np.asarray(wallets, dtype=str)})
    con.execute("CREATE OR REPLACE TEMP TABLE u AS SELECT DISTINCT wallet FROM u_src")
    con.unregister("u_src")
    d = con.execute(f"""
      SELECT b.wallet, b.coin, b.entry_bar_ts AS ts, b.open_ts, b.close_ts, b.hold_minutes,
             b.initial_notional_usd AS notl,
             b.raw_markout_8h  AS mk_8h,
             b.raw_markout_24h AS mk_24h,
             b.raw_markout_48h AS mk_48h,
             cl.raw_markout_close AS mk_own, cl.close_bar_ts AS exit_own,
             b.is_liquidation_close
      FROM read_parquet('{g}') b
      JOIN u ON b.wallet = u.wallet
      LEFT JOIN read_parquet('{close_glob}', hive_partitioning=false) cl
        ON b.wallet = cl.wallet AND b.coin = cl.coin
           AND b.opener_block = cl.opener_block AND b.opener_event_index = cl.opener_event_index
      WHERE b.crossed_open AND NOT b.opener_flagged AND NOT b.entry_after_close
        AND b.entry_lag_s <= {ENTRY_LAG_MAX_S} AND b.initial_notional_usd > 0
      ORDER BY b.wallet, b.coin, b.entry_bar_ts""").fetchnumpy()
    d["wallet"] = d["wallet"].astype(str); d["coin"] = d["coin"].astype(str)
    for k in ("mk_8h", "mk_24h", "mk_48h", "mk_own", "exit_own", "hold_minutes", "close_ts"):
        d[k] = np.ma.filled(np.ma.asarray(d[k]).astype(float), np.nan)
    return d


MONTH_LO = np.array([as_of_cutoff_ms(MONTHS[MONTHS.index(T) - 1]) for T in FOLDS], dtype=np.int64)
MONTH_HI = np.array([as_of_cutoff_ms(T) for T in FOLDS], dtype=np.int64)


def _month_idx(open_ts: np.ndarray) -> np.ndarray:
    idx = np.searchsorted(MONTH_HI, open_ts, side="right")
    clip = np.clip(idx, 0, len(FOLDS) - 1)
    good = (idx < len(FOLDS)) & (open_ts >= MONTH_LO[clip])
    return np.where(good, idx, -1)


def _row_index(ep: dict, midx: np.ndarray) -> dict:
    out: dict = {}
    for i in np.flatnonzero(midx >= 0):
        out.setdefault((int(midx[i]), str(ep["wallet"][i])), []).append(int(i))
    return {k: np.asarray(v, dtype=int) for k, v in out.items()}


def _rows_for_membership(index: dict, membership: list) -> np.ndarray:
    parts = [index[(f, w)] for f, ws in enumerate(membership) for w in ws if (f, w) in index]
    return np.concatenate(parts) if parts else np.array([], dtype=int)


def _wallet_equal_ci(net_bp: np.ndarray, wallet: np.ndarray, level: float = 0.95) -> dict:
    """A2: the anti-over-carry CO-PRIMARY. Per-wallet mean net bp, then the point/CI is over WALLETS
    (each wallet one unit) → a few hyperactive wallets cannot manufacture the headline. Wallet-clustered
    (one level) t CI."""
    if net_bp.size == 0:
        return {"point_bp": None, "ci_lo": None, "ci_hi": None, "n_wallets": 0}
    uw, inv = np.unique(wallet.astype(str), return_inverse=True)
    wmean = np.bincount(inv, weights=net_bp) / np.bincount(inv)
    g = uw.size
    point = float(wmean.mean())
    if g < 5:
        return {"point_bp": point, "ci_lo": None, "ci_hi": None, "n_wallets": g}
    se = float(wmean.std(ddof=1) / np.sqrt(g))
    tc = t_ppf(1 - (1 - level) / 2, g - 1)
    return {"point_bp": point, "ci_lo": point - tc * se, "ci_hi": point + tc * se,
            "se": se, "n_wallets": g}


def _wallet_equal_invariants() -> dict:
    net = np.array([2.0, 4.0, 10.0, -2.0, 6.0])
    wal = np.array(["a", "a", "b", "c", "c"])
    p = _wallet_equal_ci(net, wal)["point_bp"]            # (3, 10, 2) mean = 5
    shift = _wallet_equal_ci(net + 5, wal)["point_bp"]
    checks = {"wallet_equal_point": abs(p - 5.0) < 1e-9, "uniform_shift_5": abs((shift - p) - 5) < 1e-9}
    if not all(checks.values()):
        raise AssertionError(f"wallet-equal CI invariant failure: {checks}")
    return checks


# ============================================================================================
# The book (horizon-aware, per-row exit_ts A8, own-exit censoring bracket A3, dual-week CI A4).
# ============================================================================================
def _exit_ts(ep: dict, rows: np.ndarray, horizon: str) -> np.ndarray:
    """Per-row exit timestamp (ms). Fixed horizon: entry + H. Own-exit: the matched close tick (A8)."""
    if horizon == "own":
        return np.asarray(ep["exit_own"][rows], dtype=float)     # NaN where censored (filtered upstream)
    return np.asarray(ep["ts"][rows], dtype=float) + HORIZON_MS[horizon]


def _book(ep, clip, index, membership, horizon, cal_lo, cal_hi, want_equity=False, light=False) -> dict:
    """light=True (random draws): compute only net/$wtd/sharpe/wallet-breadth — skip the expensive CI,
    wallet-equal, leave-one-out, concentration, own-exit bracket. Same numbers, far fewer ops."""
    mk_all = ep[MK_COL[horizon]]
    rows = _rows_for_membership(index, membership)
    sizeable = rows[np.isfinite(clip[rows])]
    evaluable = sizeable[np.isfinite(mk_all[sizeable])]
    n_days = int(cal_hi - cal_lo)
    attempted_turnover = float(clip[sizeable].sum()) if sizeable.size else 0.0
    out = {"n_attempted_entries": int(rows.size), "n_sizeable_attempted": int(sizeable.size),
           "n_unsizeable": int(rows.size - sizeable.size), "n_evaluable": int(evaluable.size),
           "n_censored": int(sizeable.size - evaluable.size),
           "evaluable_fraction_of_sizeable": float(evaluable.size / sizeable.size) if sizeable.size else None,
           "attempted_turnover_usd": attempted_turnover}
    if evaluable.size == 0:
        out.update({"net_usd": 0.0, "dollar_wtd_net_bp": None, "daily_sharpe": None,
                    "wallet_frac_net_positive": None})
        return out
    f = evaluable
    cl = clip[f]; ret = np.asarray(mk_all[f], float); net_bp = ret - RT_COST_BP
    net = cl * net_bp / 1e4; gross = cl * ret / 1e4
    exit_ts = _exit_ts(ep, f, horizon)
    exit_day = (exit_ts // DAY_MS).astype(np.int64)
    # Sharpe on a full UTC calendar with zero days, credited at exit (A8 per-row exit_ts)
    daily = np.zeros(n_days)
    np.add.at(daily, np.clip(exit_day - cal_lo, 0, n_days - 1), net)
    sd = float(daily.std(ddof=1)) if daily.size > 1 else 0.0
    sharpe = float(daily.mean() / sd * np.sqrt(365)) if sd > 0 else 0.0
    wallet = ep["wallet"][f].astype(str)
    if light:
        uw, wi = np.unique(wallet, return_inverse=True)
        wnet = np.bincount(wi, weights=net)
        wk = ((exit_day + 3) // 7).astype(str)
        _, ki = np.unique(wk, return_inverse=True)
        knet = np.bincount(ki, weights=net)
        out.update({"net_usd": float(net.sum()),
                    "dollar_wtd_net_bp": float(net.sum() / cl.sum() * 1e4) if cl.sum() else None,
                    "daily_sharpe": sharpe, "wallet_frac_net_positive": float((wnet > 0).mean()),
                    "week_frac_net_positive": float((knet > 0).mean())})   # F4
        return out
    peak = _peak_exposure(np.asarray(ep["ts"][f], float), exit_ts, cl)
    ux, inv = np.unique(exit_ts, return_inverse=True)
    eq = np.cumsum(np.bincount(inv, weights=net)); eq0 = np.r_[0.0, eq]
    maxdd = float((np.maximum.accumulate(eq0) - eq0).max())
    exit_week = ((exit_day + 3) // 7).astype(str)
    # A4: dollar-weighted two-way CI clustered on EXIT week; for long/own horizons also ENTRY week, use wider
    ci_exit = _weighted_twoway_ci(net_bp, cl, wallet, exit_week)
    ci = ci_exit
    if horizon in WIDE_CI_HORIZONS:
        entry_week = ((np.asarray(ep["ts"][f], np.int64) // DAY_MS + 3) // 7).astype(str)
        ci_entry = _weighted_twoway_ci(net_bp, cl, wallet, entry_week)
        # wider = lower ci_lo (more conservative for the CONFIRMED gate)
        lo_e = ci_exit.get("ci_lo"); lo_n = ci_entry.get("ci_lo")
        use_entry = (lo_e is None) or (lo_n is not None and lo_n < lo_e)
        ci = ci_entry if use_entry else ci_exit
        out["ci_exit_week"] = ci_exit; out["ci_entry_week"] = ci_entry
        out["ci_which_wider"] = "entry_week" if use_entry else "exit_week"
    # A2 co-primary: wallet-equal net bp with wallet-clustered CI
    weq = _wallet_equal_ci(net_bp, wallet)
    # concentration + breadth + leave-one-out
    uw, wi = np.unique(wallet, return_inverse=True)
    wnet = np.bincount(wi, weights=net); wclip = np.bincount(wi, weights=cl)
    wpos = np.bincount(wi, weights=np.maximum(net, 0.0))
    uwk, ki = np.unique(exit_week, return_inverse=True)
    knet = np.bincount(ki, weights=net); kclip = np.bincount(ki, weights=cl)
    total_pos = float(net[net > 0].sum())
    loo_w = (net.sum() - wnet) / np.maximum(cl.sum() - wclip, 1e-30) * 1e4
    loo_k = (net.sum() - knet) / np.maximum(cl.sum() - kclip, 1e-30) * 1e4
    out.update({"n_wallets": int(uw.size), "evaluable_turnover_usd": float(cl.sum()),
                "gross_usd": float(gross.sum()), "net_usd": float(net.sum()),
                "dollar_wtd_gross_bp": float(gross.sum() / cl.sum() * 1e4),
                "dollar_wtd_net_bp": float(net.sum() / cl.sum() * 1e4),
                "equal_wtd_net_bp_PER_EPISODE": float(net_bp.mean()),
                "wallet_equal_net_bp": weq,
                "win_rate": float((net > 0).mean()), "daily_sharpe": sharpe,
                "closed_trade_max_dd_usd": maxdd, "peak_concurrent_gross_usd": peak,
                "net_return_on_peak_gross_bp": float(net.sum() / peak * 1e4) if peak else None,
                "median_clip_usd": float(np.median(cl)),
                "top_trade_share_positive_pnl": float(net.max(initial=0) / total_pos) if total_pos else None,
                "top_wallet_share_positive_pnl": float(wpos.max(initial=0) / total_pos) if total_pos else None,
                "wallet_frac_net_positive": float((wnet > 0).mean()),
                "week_frac_net_positive": float((knet > 0).mean()),
                "leave_one_wallet_net_bp_min": float(loo_w.min(initial=np.inf)),
                "leave_one_wallet_net_bp_max": float(loo_w.max(initial=-np.inf)),
                "leave_one_week_net_bp_min": float(loo_k.min(initial=np.inf)),
                "leave_one_week_net_bp_max": float(loo_k.max(initial=-np.inf)),
                "absolute_weighted_ci": ci})
    # A3: own-exit is double-tail-truncated on hold length → report a censoring-bounded bracket +
    # hold-duration distributions so the headline is a conditional-on-close BOUND, not a length-selected mean.
    if horizon == "own":
        censored = sizeable[~np.isfinite(mk_all[sizeable])]
        cl_c = clip[censored]
        denom = cl.sum() + cl_c.sum()

        def _impute(v):   # dollar-wtd net bp if every censored trade realized net_bp=v
            return (net.sum() + float((cl_c * v).sum()) / 1e4) / denom * 1e4 if denom else None
        q25, q75 = float(np.quantile(net_bp, 0.25)), float(np.quantile(net_bp, 0.75))
        vmin, vmax = float(net_bp.min()), float(net_bp.max())
        hold_ev = ep["hold_minutes"][f]; hold_ev = hold_ev[np.isfinite(hold_ev)]
        hold_sz = ep["hold_minutes"][sizeable]; hold_sz = hold_sz[np.isfinite(hold_sz)]
        out["own_exit_censoring"] = {
            "censored_fraction_of_sizeable": float(censored.size / sizeable.size) if sizeable.size else None,
            "dollar_wtd_net_bp_IQR_sensitivity_q25q75": [_impute(q25), _impute(q75)],
            "dollar_wtd_net_bp_TRUE_bound_minmax": [_impute(vmin), _impute(vmax)],  # a real worst/best-case bound
            "bracket_NOTE": "IQR = plausible band (NOT a floor); minmax = the true bound over observed net_bp",
            "evaluable_hold_min_median": float(np.median(hold_ev)) if hold_ev.size else None,
            "evaluable_hold_min_p90": float(np.quantile(hold_ev, 0.9)) if hold_ev.size else None,
            "sizeable_hold_min_median": float(np.median(hold_sz)) if hold_sz.size else None,
            "n_open_at_data_end": int(np.isnan(ep["close_ts"][sizeable]).sum())}
    if want_equity:
        out["_equity"] = {"exit_ts": ux.tolist(), "closed_trade_equity_usd": eq.tolist()}
    return out


def _cal_bounds(ep: dict, midx: np.ndarray, horizon: str) -> tuple[int, int]:
    """Full-calendar day bounds spanning every test episode's entry..exit for THIS horizon (A8)."""
    m = np.flatnonzero(midx >= 0)
    entry_day = (np.asarray(ep["ts"][m], np.int64) // DAY_MS)
    ex = _exit_ts(ep, m, horizon)
    ex = ex[np.isfinite(ex)]
    lo = int(entry_day.min())
    hi = int((ex.max() // DAY_MS)) + 2 if ex.size else lo + 2
    return lo, hi


def run() -> dict:
    ci_inv = _ci_invariants(); weq_inv = _wallet_equal_invariants()
    con = _connect()
    sel = _selection()
    x = _trajectory_arrays(sel)
    states, chain_ids, sampler = _sample_paths(x)
    print(f"trajectory paths: {len(states)} unique={sampler['unique_states']} "
          f"acc={[round(c['acceptance'],3) for c in sampler['chains']]}", flush=True)
    random_mem = [_membership_from_assignment(x, a) for a in states]
    # Pull episodes ONLY for wallets actually used (real cohorts ∪ every sampled random path) — far
    # smaller than the full candidate universe, so the clip build stays tractable.
    used = set().union(*sel.cohorts)
    for m in random_mem:
        used |= set().union(*m)
    ep = _pull_episodes(con, sorted(used))
    midx = _month_idx(np.asarray(ep["open_ts"], np.int64)); index = _row_index(ep, midx)
    print(f"episodes: {len(ep['wallet']):,} for {len(used):,} used wallets; "
          f"test attempted rows={(midx>=0).sum():,}", flush=True)
    clips = _expanding_clips({"wallet": ep["wallet"], "coin": ep["coin"], "ts": ep["ts"], "notl": ep["notl"]})
    report = {"config": {"cap": CAP, "K": K, "folds": FOLDS, "qs": QS, "primary_q": PRIMARY_Q,
                         "primary_horizon": PRIMARY_HORIZON, "secondary_leads": [h for h in HORIZONS if h != PRIMARY_HORIZON],
                         "round_trip_cost_bp": RT_COST_BP, "care_about_bp": CARE_ABOUT_BP,
                         "n_paths": N_PATHS, "seed": SEED, "mcmc_rank_status": "DESCRIPTIVE_NOT_PVALUE",
                         "arch": "CAPDAY_BOOK_ARCH.md v1.1", "code_commit": basemod._git_commit()},
              "ci_invariants": ci_inv, "wallet_equal_invariants": weq_inv,
              "sampler": sampler, "by_horizon": {}}
    equity = {}
    for horizon in HORIZONS:
        cal_lo, cal_hi = _cal_bounds(ep, midx, horizon)
        hz = {}
        for q in QS:
            clip = clips[q]
            real = _book(ep, clip, index, sel.cohorts, horizon, cal_lo, cal_hi, want_equity=(q == PRIMARY_Q))
            if q == PRIMARY_Q:
                equity[horizon] = real.pop("_equity", {})
            rb = [_book(ep, clip, index, m, horizon, cal_lo, cal_hi, light=True) for m in random_mem]
            # F6: explicit None handling (0.0 is a legitimate value — never coerce it to nan)
            def _col(key):
                v = np.array([np.nan if z.get(key) is None else z.get(key) for z in rb], float)
                ids = np.asarray(chain_ids)[np.isfinite(v)]
                return v[np.isfinite(v)], ids
            rret, rret_ids = _col("dollar_wtd_net_bp")
            point = real.get("dollar_wtd_net_bp")
            rank = float((1 + np.sum(rret >= point)) / (rret.size + 1)) if (point is not None and rret.size) else None
            mde = float(np.quantile(rret, 0.95) - np.quantile(rret, 0.20)) if rret.size else None
            diag = _random_diagnostics(rret, rret_ids.tolist(), point) if rret.size else {}
            band_ok = bool(rret.size and diag.get("return_ess", 0) >= 400
                           and diag.get("chain_mean_spread_in_pooled_sd", 9) <= 0.25
                           and sampler["unique_fraction"] >= 0.9
                           and min(c["acceptance"] for c in sampler["chains"]) >= 0.01)
            # per-fold beats-random (primary q only, light random books — the headline breadth)
            fold_detail = {}
            if q == PRIMARY_Q:
                for fo, T in enumerate(FOLDS):
                    rf = _book(ep, clip, index, _one_fold(sel.cohorts, fo), horizon, cal_lo, cal_hi, light=True)
                    rr = np.array([np.nan if _book(ep, clip, index, _one_fold(mm, fo), horizon, cal_lo, cal_hi, light=True).get("dollar_wtd_net_bp") is None
                                   else _book(ep, clip, index, _one_fold(mm, fo), horizon, cal_lo, cal_hi, light=True).get("dollar_wtd_net_bp")
                                   for mm in random_mem], float)
                    rr = rr[np.isfinite(rr)]
                    rfp = rf.get("dollar_wtd_net_bp")
                    fold_detail[str(T)] = {"real_net_bp": rfp, "random_median_net_bp": float(np.median(rr)) if rr.size else None,
                                           "beats_random_median": bool(rfp is not None and rr.size and rfp > np.median(rr)),
                                           "n_evaluable": rf["n_evaluable"]}
            rwal, _ = _col("wallet_frac_net_positive"); rwk, _ = _col("week_frac_net_positive")
            role = "PRIMARY" if (horizon == PRIMARY_HORIZON and q == PRIMARY_Q) else \
                   ("SENSITIVITY" if q != PRIMARY_Q else "SECONDARY_LEAD")
            hz[f"q{int(q*100)}"] = {
                "role": role,                                            # F7: no silent promotion
                "cohort": real,
                "random_return_median_bp": float(np.median(rret)) if rret.size else None,
                "random_return_p90_bp": float(np.quantile(rret, 0.90)) if rret.size else None,
                "real_minus_random_median_bp": (point - float(np.median(rret))) if (point is not None and rret.size) else None,
                "descriptive_rank_return": rank, "rank_NOTE": "MCMC rank; NOT a p-value",
                "random_band_interpretable": band_ok, "random_diagnostics": diag,
                "empirical_null_mde_80pct_one_sided_bp": mde,
                "descriptive_rank_wallet_breadth": float((1 + np.sum(rwal >= (real.get("wallet_frac_net_positive") or 0))) / (rwal.size + 1)) if rwal.size else None,
                "descriptive_rank_week_breadth": float((1 + np.sum(rwk >= (real.get("week_frac_net_positive") or 0))) / (rwk.size + 1)) if rwk.size else None,
                "fold_detail": fold_detail,
                "folds_beat_random_median": int(sum(z["beats_random_median"] for z in fold_detail.values()))}
            wq = real.get("wallet_equal_net_bp", {})
            ci_a = real.get('absolute_weighted_ci', {})
            print(f"[{horizon} q{int(q*100)}] $wtd={point if point is None else round(point,2)}bp "
                  f"wallet_eq={wq.get('point_bp') if wq.get('point_bp') is None else round(wq['point_bp'],2)} "
                  f"CI=[{ci_a.get('ci_lo')},{ci_a.get('ci_hi')}] "
                  f"n={real['n_evaluable']} folds={hz[f'q{int(q*100)}']['folds_beat_random_median']}/{len(FOLDS) if q==PRIMARY_Q else 0} "
                  f"rank={rank} MDE={mde}", flush=True)
        report["by_horizon"][horizon] = hz
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    EQ_OUT.write_text(json.dumps(equity, default=str))
    print(f"-> {OUT}")
    return report


if __name__ == "__main__":
    run()
