"""Matched-placebo walk-forward for the two cohort arms (COPY_COHORT_ARCH §5, §7).

Folds T ∈ {202602…202606}: formation < T, evaluate the single forward month T. Per fold, freeze
the top-K=100 cohort on formation-only scores (selectors.build_formation), evaluate forward, and
compare to B=100 stratified-matched random cohorts. Inference:
 - **Load-bearing cross-unit test** = one-sided wallet-level sign test on cohort wallets' forward
   mean y (n≈100 per fold; direction pre-registered positive).
 - **Pooled magnitude CI** = two-way (wallet × ISO-week) CGM on all cohort episodes across folds.
 - **Arm p for BH** = one-sided cluster sign-flip p of the pooled cohort mean at the frozen
   wallet_week level, +1/(B+1) corrected.

Pre-registration refinement (documented; fold into ARCH §5 note): the two-way CGM CI centers on the
EPISODE-weighted cohort mean (so point estimate and CI are mutually consistent and G_week≈22 pooled);
the ECONOMIC headline (§5.3 wallet-equal-weight mean) and the wallet sign test are reported
alongside and are immune to episode-weighting. The ≥3-forward-episode floor applies to the wallet
statistic and the sign test; the episode-level CGM uses all cohort episodes.

    python -m research.studies.copy_cohort.walkforward run
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.stats import (sign_test, sign_flip_pvalue, twoway_cluster_ci, bh_fdr, inv_norm)
from . import selectors

_INV_A = inv_norm(0.975)      # z_{1-α/2}, α=0.05
_INV_B = inv_norm(0.80)       # z_power, 80%

OUT_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort"
REPORT_JSON = OUT_DIR / "walkforward_report.json"
FOLDS = (202602, 202603, 202604, 202605, 202606)
B_PLACEBO = 100
K = selectors.K_COHORT
MIN_FWD = selectors.MIN_FWD_EP
SEED = 20260712
N_FLIP = 10_000
STRATUM_MIN_MULT = 3          # collapse a stratum if pool_count < 3× the draws it must supply
OVERLAP_ABORT = 0.25          # >25% mean placebo↔real overlap ⇒ stratification too fine → fallback


def _stratum(feat: dict, keys=("act_q", "not_q", "coin", "long_h")) -> tuple:
    return tuple(feat[k] for k in keys)


def _draw_matched_placebos(pool: np.ndarray, features: dict, cohort: np.ndarray,
                           rng: np.random.Generator, b: int = B_PLACEBO,
                           keys=("act_q", "not_q", "coin", "long_h")) -> tuple[list, float, dict]:
    """B random cohorts stratified to the real cohort's per-stratum counts; collapse thin strata;
    return (placebo cohorts, mean overlap with real cohort, diagnostics)."""
    pool_strat = {w: _stratum(features[w], keys) for w in pool.tolist()}
    by_stratum: dict = {}
    for w, s in pool_strat.items():
        by_stratum.setdefault(s, []).append(w)
    need = {}
    for w in cohort.tolist():
        s = pool_strat[w]
        need[s] = need.get(s, 0) + 1

    # collapse: merge a stratum whose pool supply < STRATUM_MIN_MULT × need into the pooled "rest"
    collapsed_need, collapsed_pool, n_collapsed = {}, {}, 0
    rest_need, rest_pool = 0, []
    for s, cnt in need.items():
        supply = len(by_stratum.get(s, []))
        if supply >= STRATUM_MIN_MULT * cnt and supply > cnt:
            collapsed_need[s] = cnt
            collapsed_pool[s] = by_stratum[s]
        else:
            rest_need += cnt
            n_collapsed += 1
    # the "rest" pool = all pool wallets not claimed by a kept stratum
    kept = set().union(*[set(v) for v in collapsed_pool.values()]) if collapsed_pool else set()
    rest_pool = [w for w in pool.tolist() if w not in kept]

    cohort_set = set(cohort.tolist())
    placebos, overlaps = [], []
    for _ in range(b):
        pick = []
        for s, cnt in collapsed_need.items():
            avail = collapsed_pool[s]
            pick.extend(rng.choice(avail, size=cnt, replace=False).tolist())
        if rest_need > 0:
            take = min(rest_need, len(rest_pool))
            pick.extend(rng.choice(rest_pool, size=take, replace=False).tolist())
        pick = np.array(pick[:K])
        placebos.append(pick)
        overlaps.append(len(cohort_set & set(pick.tolist())) / max(len(pick), 1))
    diag = {"n_strata_kept": len(collapsed_need), "n_strata_collapsed": n_collapsed,
            "rest_need": rest_need, "kept_need": int(sum(collapsed_need.values()))}
    return placebos, float(np.mean(overlaps)), diag


def _cohort_wallet_means(frame, cohort: np.ndarray) -> dict:
    """{wallet: forward mean y} for cohort wallets with ≥ MIN_FWD forward episodes."""
    return {w: frame.wallet_mean[w] for w in cohort.tolist()
            if frame.wallet_n.get(w, 0) >= MIN_FWD}


def _wallet_equal_mean(frame, cohort: np.ndarray) -> tuple[float, np.ndarray]:
    """§5.3 economic statistic: equal-weight-over-wallets mean of wallet-mean y, wallets with
    ≥ MIN_FWD forward episodes. Returns (mean, per-wallet means used)."""
    ms = np.array(list(_cohort_wallet_means(frame, cohort).values()))
    return (float(ms.mean()) if ms.size else float("nan")), ms


def _cohort_episodes(frame, cohort: np.ndarray):
    """All forward episodes of cohort wallets → (y, wallet, week) for the episode-level CGM."""
    mask = np.isin(frame.ep_wallet, cohort)
    return frame.ep_y[mask], frame.ep_wallet[mask], frame.ep_week[mask]


def run() -> dict:
    con = selectors.connect()
    rng = np.random.default_rng(SEED)
    report: dict = {"config": {"folds": FOLDS, "K": K, "B_placebo": B_PLACEBO,
                               "min_fwd_ep": MIN_FWD, "seed": SEED,
                               "frozen_cluster": selectors.FROZEN_CLUSTER,
                               "stratum_keys": ["act_q", "not_q", "coin", "long_h"]},
                    "folds_detail": {}, "arms": {}}
    # accumulate pooled episode-level arrays per arm
    pooled = {"A": {"y": [], "w": [], "wk": []}, "B": {"y": [], "w": [], "wk": []}}
    fold_beats = {"A": [], "B": []}          # per-fold: cohort economic mean − placebo median
    fold_signp = {"A": [], "B": []}
    # per-wallet forward means keyed by wallet across folds — the pooled sign test collapses each
    # distinct wallet to ONE unit (a persistent wallet's 5 fold-echoes are NOT independent; audit F2)
    wallet_fwd = {"A": {}, "B": {}}

    for T in FOLDS:
        y0, m0 = divmod(T, 100)
        cutoff_month = (y0 - 1) * 100 + 12 if m0 == 1 else T - 1
        panel = selectors.build_formation(con, cutoff_month)
        frame = selectors.build_forward(con, T, panel.pool)
        fd = {"cutoff_month": cutoff_month, "pool_size": int(panel.pool.size),
              "score_a_meta": panel.score_a_meta, "score_b_meta": panel.score_b_meta, "arms": {}}
        for arm, score in (("A", panel.score_a), ("B", panel.score_b)):
            if not score:
                fd["arms"][arm] = {"skip": "no scores"}
                continue
            cohort = selectors.top_k(score, panel.pool, K)
            econ_mean, wmeans = _wallet_equal_mean(frame, cohort)
            # matched placebos
            placebos, overlap, sdiag = _draw_matched_placebos(panel.pool, panel.features, cohort, rng)
            if overlap > OVERLAP_ABORT:       # fallback: activity×notional only (arch §5.4)
                placebos, overlap, sdiag = _draw_matched_placebos(
                    panel.pool, panel.features, cohort, rng, keys=("act_q", "not_q"))
                sdiag["fallback"] = "act_q,not_q (overlap>abort)"
            pl_means = np.array([_wallet_equal_mean(frame, p)[0] for p in placebos])
            pl_means = pl_means[~np.isnan(pl_means)]     # drop degenerate placebos (audit F5)
            pl_median = float(np.median(pl_means)) if pl_means.size else float("nan")
            p_placebo = (int(np.sum(pl_means >= econ_mean)) + 1) / (pl_means.size + 1)
            # wallet-level one-sided sign test (direction pre-registered +)
            st = sign_test(wmeans)
            sign_p_one = _one_sided_sign_p(wmeans)
            fd["arms"][arm] = {
                "cohort_econ_mean_bp": econ_mean, "n_cohort_wallets_ge3fwd": int(wmeans.size),
                "placebo_median_bp": pl_median, "beats_placebo": bool(econ_mean > pl_median),
                "p_placebo_one_sided": p_placebo, "mean_placebo_overlap": overlap,
                "sign_frac_pos": st.frac_pos, "sign_p_one_sided": sign_p_one,
                "stratum_diag": sdiag}
            fold_beats[arm].append(econ_mean > pl_median)
            fold_signp[arm].append(sign_p_one)
            ey, ew, ewk = _cohort_episodes(frame, cohort)
            pooled[arm]["y"].append(ey); pooled[arm]["w"].append(ew); pooled[arm]["wk"].append(ewk)
            for wid, m in _cohort_wallet_means(frame, cohort).items():
                wallet_fwd[arm].setdefault(wid, []).append(m)
        report["folds_detail"][str(T)] = fd

    # pooled per-arm inference
    arm_pvals = {}
    for arm in ("A", "B"):
        if not pooled[arm]["y"]:
            report["arms"][arm] = {"skip": "no folds scored"}
            continue
        y = np.concatenate(pooled[arm]["y"])
        w = np.concatenate(pooled[arm]["w"])
        wk = np.concatenate(pooled[arm]["wk"])
        ci = twoway_cluster_ci(y, w, wk)          # episode-weighted mean, wallet × ISO-week
        we_ci = _wallet_equal_bootstrap_ci(y, w, wk, SEED + 7)   # frozen economic estimand CI
        # ONE unit per distinct wallet (avg its per-fold forward means) — folds are not independent
        per_wallet = np.array([float(np.mean(v)) for v in wallet_fwd[arm].values()])
        pooled_sign = sign_test(per_wallet)
        pooled_sign_p1 = _one_sided_sign_p(per_wallet)
        arm_p = _cluster_flip_one_sided(y, np.char.add(w.astype(str),
                                        np.char.add("|", wk.astype(str))), SEED + 1)
        arm_pvals[arm] = arm_p
        hw = (ci.hi - ci.lo) / 2.0
        z_a = _INV_A; z_b = _INV_B
        report["arms"][arm] = {
            "pooled_episode_mean_bp": float(y.mean()), "n_episodes": int(y.size),
            "twoway_ci_lo": ci.lo, "twoway_ci_hi": ci.hi, "twoway_se": ci.se,
            "twoway_df": ci.df, "twoway_floored": ci.floored, "ci_excludes_zero_positive": bool(ci.lo > 0),
            "realized_halfwidth_bp": hw, "realized_mde_bp": hw * (z_a + z_b) / z_a,   # §7 RED gate input
            "wallet_equal_ci": we_ci,   # CI on the FROZEN economic estimand (adjudicates steelman/prosecutor)
            "pooled_wallet_equal_mean_bp": float(per_wallet.mean()) if per_wallet.size else float("nan"),
            "n_distinct_cohort_wallets": int(per_wallet.size), "pooled_sign_frac_pos": pooled_sign.frac_pos,
            "pooled_sign_p_one_sided": pooled_sign_p1,
            "folds_beat_placebo": int(sum(fold_beats[arm])), "n_folds": len(fold_beats[arm]),
            "arm_flip_p_one_sided": arm_p,
            "arm_p_NOTE": "wallet_week flip — blind to cross-wallet week shocks; the two-way CI is the "
                          "binding significance gate (audit F2)",
            "CAVEAT": "folds share an overlapping wallet pool — folds are NOT independent draws"}

    # BH across the (≤2) arms
    if arm_pvals:
        names = list(arm_pvals)
        rej, q = bh_fdr([arm_pvals[a] for a in names])
        report["bh"] = {names[i]: {"p": arm_pvals[names[i]], "q": float(q[i]),
                                   "reject": bool(rej[i])} for i in range(len(names))}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str))
    print(f"walkforward done -> {REPORT_JSON}")
    return report


def _wallet_equal_bootstrap_ci(y: np.ndarray, w: np.ndarray, wk: np.ndarray, seed: int,
                               n_boot: int = 5000, level: float = 0.95) -> dict:
    """CI on the FROZEN economic estimand — the wallet-equal mean (mean over distinct wallets of each
    wallet's mean y) — the quantity the episode-weighted two-way CI does NOT target (audit F3 /
    prosecutor). Reported two ways; the binding CI is the WIDER: (a) resample wallets (within-wallet
    dependence), (b) resample ISO-week blocks and recompute the wallet-equal mean (cross-wallet week
    shocks — the dependence the prosecutor flagged the sign test ignores)."""
    rng = np.random.default_rng(seed)
    uw, w_inv = np.unique(w, return_inverse=True)
    uk, k_inv = np.unique(wk, return_inverse=True)
    ep_by_w = [np.where(w_inv == i)[0] for i in range(uw.size)]
    ep_by_k = [np.where(k_inv == i)[0] for i in range(uk.size)]

    def wallet_equal(rows: np.ndarray) -> float:
        wi = w_inv[rows]
        order = np.argsort(wi, kind="stable")
        wi_s, y_s = wi[order], y[rows][order]
        uniq, start = np.unique(wi_s, return_index=True)
        sums = np.add.reduceat(y_s, start)
        cnts = np.diff(np.r_[start, wi_s.size])
        return float((sums / cnts).mean())

    point = wallet_equal(np.arange(y.size))
    a = (1 - level) / 2
    # AUDIT FIX 2026-07-17 (multiplicity-preserving wallet resample): the old code
    # concatenated duplicate wallet picks and re-grouped by wallet id, so duplicates
    # collapsed to one cluster and the bootstrap variance was understated. The wallet-equal
    # mean under a resample with multiplicities m is the m-weighted mean of the per-wallet
    # means (ksweep weighted pattern). NOTE: code fixed 2026-07-17 but NOT re-run; the
    # 07-12 walkforward_report.json numbers carry a ledger correction note instead.
    pw_mean = np.array([float(np.mean(y[rows])) for rows in ep_by_w])
    boots_w = np.empty(n_boot)
    for b in range(n_boot):
        m = np.bincount(rng.integers(0, uw.size, size=uw.size), minlength=uw.size).astype(float)
        boots_w[b] = float(m @ pw_mean) / uw.size
    boots_k = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, uk.size, size=uk.size)
        boots_k[b] = wallet_equal(np.concatenate([ep_by_k[i] for i in pick]))
    lo_w, hi_w = float(np.quantile(boots_w, a)), float(np.quantile(boots_w, 1 - a))
    lo_k, hi_k = float(np.quantile(boots_k, a)), float(np.quantile(boots_k, 1 - a))
    lo, hi = min(lo_w, lo_k), max(hi_w, hi_k)      # binding = wider (conservative two-way)
    return {"point_bp": point, "ci_lo": lo, "ci_hi": hi, "excludes_zero_positive": bool(lo > 0),
            "wallet_only": [lo_w, hi_w], "week_block": [lo_k, hi_k],
            "binding": "week_block" if (hi_k - lo_k) >= (hi_w - lo_w) else "wallet_only"}


def _one_sided_sign_p(x: np.ndarray) -> float:
    """One-sided (H1: median > 0) exact binomial sign test p-value; excludes exact zeros."""
    from math import comb
    x = np.asarray(x, dtype=float)
    x = x[x != 0.0]
    n = x.size
    if n == 0:
        return float("nan")
    k = int((x > 0).sum())
    return float(sum(comb(n, i) for i in range(k, n + 1)) / (2 ** n))


def _cluster_flip_one_sided(y: np.ndarray, cluster_id: np.ndarray, seed: int,
                            n_perm: int = N_FLIP) -> float:
    """One-sided (H1: mean > 0) cluster sign-flip p of the pooled mean, +1/(n_perm+1) corrected."""
    obs, _, null = sign_flip_pvalue(y, stat=np.mean, n_perm=n_perm, seed=seed, cluster_id=cluster_id)
    return float((np.sum(null >= obs) + 1) / (n_perm + 1))


if __name__ == "__main__":
    run()
