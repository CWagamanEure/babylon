"""Stage 0 — dependence calibration on the burn-in slice (COPY_COHORT_ARCH §2).

Burn-in = 202508–202510 ONLY. This stage picks the frozen (observation unit, SE-cluster level) pair
empirically and validates the two-way CI's coverage. It is CALIBRATION, not effect selection: the
decisional diagnostics (flip-null rejection rates, Moulton variance ratios) are effect-blind; no
selector/horizon/filter choice is made from Stage-0 effect sizes.

Population = the episode-level filters of the ARCH §3 primary population (F0 entry freshness,
taker-opener, non-flagged, non-liq-close, non-inherited, window censor `entry_bar_ts + 4h < C0`)
— NOT the wallet-level eligibility filters (F1's 30-episode floor, F2–F6, the 20%-flagged rule);
calibration wants breadth. The calibration wallet floor MIN_EP_CAL=10 is a registered parameter
(ARCH §2), with a mandatory ≥30-episode (F1-level) sensitivity population: the adopted level must
calibrate on BOTH. Outcome y = raw_markout_4h − dir_sign·μ_4h(coin, ISO-week of the entry tick),
μ from the fwd_returns primitive censored at C0 (mu_fold.register_mu). All CLUSTERING keys (day,
week) are anchored on open_ts — one time base, so day ⊂ week nesting is guaranteed; the entry-tick
ISO week is used ONLY for the μ join (post-code-audit fix: mixed anchors broke nestedness for
episodes whose entry tick crosses midnight Sunday).

Diagnostics (ARCH §2, audit-fixed non-circular construction):
 1. Moulton variance ratios per candidate cluster level (SE-inflation vs iid).
 2. Pooled sign-flip calibration: null = wallet-level flips (coarsest; preserves ALL within-wallet
    dependence), test = pooled mean with CR0 clustering at each finer candidate (episode /
    wallet-coin-day / wallet-week), t critical at G−1 df. The SAME seed (hence the identical sign
    matrix) is used for every candidate level — a paired comparison. FROZEN adoption rule: coarsest
    candidate below wallet whose Wilson 95% CI on the rejection rate is inside [0.03, 0.07] at
    α=0.05 on BOTH calibration populations (≥10 and ≥30 episodes); none → fall back to wallet-week
    cluster bootstrap and report the miscalibration.
    (Wallet flips scramble cross-wallet time dependence — that axis is handled structurally by the
    two-way CGM CI in §5.5, validated by diagnostic 4, not by this calibration. coin_week appears
    in the Moulton table only: it is not wallet-nested, so it cannot enter the flip ladder.)
 3. Supporting per-wallet adjacent-rung calibration (flip wallet-week → test wallet-coin-day;
    flip wallet-coin-day → test iid) and descriptives (lag/gap/overlap autocorrelation, coin-hour
    and coin-week ICC of y before/after μ-subtraction). Wrapped: a supporting-diagnostic failure
    cannot destroy the decisional report.
 4. Two-way CGM CI coverage simulation (audit S1 deliverable), incl. the rejected wider-of-two rule
    and a heavy-tailed cluster-size variant.

    python -m research.studies.copy_cohort.stage0_dependence build   # materialize the y panel
    python -m research.studies.copy_cohort.stage0_dependence run     # diagnostics + report
    python -m research.studies.copy_cohort.stage0_dependence all
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np

from research.data.markout import (_connect, HORIZONS, EP_GLOB, REPO_ROOT,
                                   MARKOUT_SCHEMA_VERSION)
from research.data.mu_baseline import MU_SCHEMA_VERSION
from research.lib.cv import as_of_cutoff_ms
from research.lib.stats import _cluster_sandwich_var_of_mean, t_ppf, twoway_cluster_ci
from . import mu_fold

MK_GLOB = str(REPO_ROOT / "data" / "derived" / "episodes_markout" / "coin=*/part-b*.parquet")
OUT_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort"
Y_PATH = OUT_DIR / "stage0_y.parquet"
META_PATH = OUT_DIR / "_STAGE0_META.json"
REPORT_JSON = OUT_DIR / "stage0_report.json"
REPORT_MD = OUT_DIR / "stage0_report.md"

BURN_MONTHS = (202508, 202509, 202510)
START_MS = int(datetime(2025, 8, 1, tzinfo=timezone.utc).timestamp() * 1000)
C0 = as_of_cutoff_ms(202510)                     # first ms of 2025-11 — burn-in cutoff
H = "4h"
H_MS = HORIZONS[H]
SEED = 20260712
N_PERM = 10_000                                  # MC half-width at rate .05 ≈ 0.0043 ≤ 0.005 (ARCH §2)
MIN_EP_CAL = 10                                  # registered calibration floor (ARCH §2)
MIN_EP_SENS = 30                                 # F1-level sensitivity population (ARCH §2)
FLIP_CHUNK = 100                                 # part of the frozen draw stream (chunking alters draws)
BAND = (0.03, 0.07)
ALPHA_Z = 1.959963984540054
ENTRY_LAG_MAX_S = 90                             # F0 (mirrors features_markout P0 freshness)
N_SIM_COVERAGE = 4_000


def _code_commit() -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=10)
        return out.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# build: materialize the burn-in y panel (deterministic: threads=1, total-order COPY)
# ---------------------------------------------------------------------------
def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = _connect()
    con.execute("PRAGMA threads=1")              # determinism: μ AVG + COPY order are contractual
    mu_fold.register_mu(con, cutoff_ms=C0, horizons=(H,), start_ms=START_MS)
    wk = "strftime(make_timestamp(mk.entry_bar_ts*1000), '%G%V')"
    base = f"""
      WITH mk AS (
        SELECT wallet, coin, open_ts, entry_bar_ts, dir_sign, raw_markout_{H},
               opener_block, opener_event_index
        FROM read_parquet('{MK_GLOB}', hive_partitioning=false)
        WHERE open_ts >= {START_MS} AND open_ts < {C0}
          AND NOT entry_after_close AND entry_lag_s <= {ENTRY_LAG_MAX_S}
          AND raw_markout_{H} IS NOT NULL
          AND entry_bar_ts + {H_MS} < {C0}
      ),
      ep AS (
        -- predicate on open_ts, NEVER the finalize-month partition key (episodes_build contract);
        -- join key unique only under NOT inherited_basis (both sides enforce it)
        SELECT wallet, coin, opener_block, opener_event_index
        FROM read_parquet('{EP_GLOB}', hive_partitioning=true)
        WHERE open_ts >= {START_MS} AND open_ts < {C0}
          AND NOT inherited_basis AND crossed_open
          AND NOT opener_flagged AND NOT is_liquidation_close
      ),
      joined AS (
        SELECT mk.* FROM mk JOIN ep USING (wallet, coin, opener_block, opener_event_index)
      )"""
    tmp = Y_PATH.with_suffix(".parquet.tmp")
    con.execute(f"""COPY ({base}
      SELECT j.wallet, j.coin, j.open_ts, j.entry_bar_ts, j.dir_sign,
             j.opener_block, j.opener_event_index,
             strftime(make_timestamp(j.entry_bar_ts*1000), '%G%V') AS iso_week_entry,
             j.raw_markout_{H} AS raw,
             j.raw_markout_{H} - j.dir_sign * mu.mu_{H} AS y
      FROM joined j
      JOIN mu ON mu.coin = j.coin
             AND mu.iso_week = strftime(make_timestamp(j.entry_bar_ts*1000), '%G%V')
      WHERE mu.mu_{H} IS NOT NULL
      ORDER BY j.wallet, j.coin, j.open_ts, j.opener_block, j.opener_event_index
    ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)""")
    import os
    os.replace(tmp, Y_PATH)
    n_joined = con.execute(base + " SELECT count(*) FROM joined").fetchone()[0]
    n, w = con.execute(f"SELECT count(*), count(DISTINCT wallet) "
                       f"FROM read_parquet('{Y_PATH}')").fetchone()
    META_PATH.write_text(json.dumps({
        "code_commit": _code_commit(),
        "markout_schema_version": MARKOUT_SCHEMA_VERSION,
        "mu_schema_version": MU_SCHEMA_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_rows": n, "n_wallets": w, "n_joined_pre_mu": n_joined,
        "mu_join_dropped": n_joined - n}, indent=2))
    print(f"stage0 build: {n:,} scoreable episodes ({n_joined - n} dropped by μ join), "
          f"{w:,} wallets -> {Y_PATH}", flush=True)


# ---------------------------------------------------------------------------
# load: factorized integer cluster ids (0-based); ALL clustering keys anchored on open_ts
# ---------------------------------------------------------------------------
def load() -> dict[str, np.ndarray]:
    con = _connect()
    wko = "strftime(make_timestamp(open_ts*1000), '%G%V')"
    d = con.execute(f"""
      SELECT y, raw, open_ts, entry_bar_ts, dir_sign,
             dense_rank() OVER (ORDER BY wallet) - 1                          AS w_id,
             dense_rank() OVER (ORDER BY wallet, coin) - 1                    AS wc_id,
             dense_rank() OVER (ORDER BY wallet, coin, open_ts // 86400000)-1 AS wcd_id,
             dense_rank() OVER (ORDER BY wallet, {wko}) - 1                   AS ww_id,
             dense_rank() OVER (ORDER BY coin, {wko}) - 1                     AS cw_id,
             dense_rank() OVER (ORDER BY coin, open_ts // 3600000) - 1        AS ch_id
      FROM read_parquet('{Y_PATH}')
      ORDER BY wallet, coin, open_ts, opener_block, opener_event_index""").fetchnumpy()
    return {k: np.ascontiguousarray(v) for k, v in d.items()}


def _wilson(k: int, n: int, z: float = ALPHA_Z) -> tuple[float, float]:
    p = k / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    hw = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return float(ctr - hw), float(ctr + hw)


def _assert_nested(inner: np.ndarray, outer: np.ndarray, name: str) -> None:
    """Every inner cluster must map to exactly one outer cluster (nestedness for the flip algebra)."""
    lo = np.full(int(inner.max()) + 1, np.iinfo(np.int64).max)
    hi = np.full(int(inner.max()) + 1, -1)
    np.minimum.at(lo, inner, outer)
    np.maximum.at(hi, inner, outer)
    used = hi >= 0
    if not np.array_equal(lo[used], hi[used]):
        raise AssertionError(f"cluster level {name} is not nested in the flip level")


# ---------------------------------------------------------------------------
# diagnostic 1: Moulton variance ratios
# ---------------------------------------------------------------------------
def moulton_table(y: np.ndarray, levels: dict[str, np.ndarray]) -> dict:
    vi, _ = _cluster_sandwich_var_of_mean(y, np.arange(y.size))
    out = {}
    for name, cid in levels.items():
        v, g = _cluster_sandwich_var_of_mean(y, cid)
        out[name] = {"n_clusters": g, "se_inflation_vs_iid": float(np.sqrt(v / vi))}
    return out


# ---------------------------------------------------------------------------
# diagnostic 2: pooled flip calibration (decisional)
# ---------------------------------------------------------------------------
def flip_calibration(y: np.ndarray, w_id: np.ndarray, lvl_id: np.ndarray,
                     n_perm: int, seed: int, chunk: int = FLIP_CHUNK) -> dict:
    """Rejection rate of the pooled-mean CR0-clustered t-test (t critical at G−1 df) under
    wallet-level sign flips. Fully vectorized via per-cluster sums: flipping wallet w rescales every
    nested cluster sum S_c by s_w, so ȳ^r and the CR0 variance are dot products against per-wallet
    aggregates. NOTE: the draw stream depends on (seed, chunk, n_wallets); chunk is frozen."""
    _, w_inv = np.unique(w_id, return_inverse=True)
    _, l_inv = np.unique(lvl_id, return_inverse=True)
    _assert_nested(l_inv, w_inv, "test-level-vs-wallet")
    n = y.size
    s_c = np.bincount(l_inv, weights=y)                     # cluster sums
    n_c = np.bincount(l_inv).astype(float)
    w_of_c = np.full(s_c.size, -1, dtype=np.int64)
    w_of_c[l_inv] = w_inv
    n_wallets = int(w_inv.max()) + 1
    a_const = float((s_c ** 2).sum())
    cn_const = float((n_c ** 2).sum())
    u = np.bincount(w_of_c, weights=s_c, minlength=n_wallets)          # Σ_c∈w S_c
    v = np.bincount(w_of_c, weights=s_c * n_c, minlength=n_wallets)    # Σ_c∈w S_c·n_c
    tcrit = t_ppf(0.975, int(s_c.size) - 1) if s_c.size < 10_000 else ALPHA_Z
    rng = np.random.default_rng(seed)
    rej = 0
    done = 0
    while done < n_perm:
        m = min(chunk, n_perm - done)
        signs = (rng.integers(0, 2, size=(m, n_wallets), dtype=np.int8) * 2 - 1).astype(np.float64)
        ybar = (signs @ u) / n
        b = signs @ v
        var = (a_const - 2.0 * ybar * b + ybar * ybar * cn_const) / (n * n)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(var > 0, ybar / np.sqrt(var), np.inf)   # var≤0 → reject (conservative)
        rej += int((np.abs(t) > tcrit).sum())
        done += m
    lo, hi = _wilson(rej, n_perm)
    return {"n_clusters": int(s_c.size), "reject_rate": rej / n_perm,
            "wilson_lo": lo, "wilson_hi": hi,
            "calibrated": bool(BAND[0] <= lo and hi <= BAND[1])}


# ---------------------------------------------------------------------------
# diagnostic 3a: per-wallet adjacent rungs (supporting)
# ---------------------------------------------------------------------------
def perwallet_rung(y: np.ndarray, w_id: np.ndarray, flip_id: np.ndarray, test_id: np.ndarray,
                   seed: int, n_perm: int = 500, max_wallets: int = 1_500,
                   min_test_clusters: int = 8, min_flip_blocks: int = 2) -> dict:
    """Per-wallet test (mean/CR0-SE at `test_id` level, t critical at G−1) under within-wallet flips
    at `flip_id` level (test level nested in flip level). Mean rejection rate over sampled wallets.
    Wallets whose clusters violate nesting are skipped and counted (not fatal)."""
    rng = np.random.default_rng(seed)
    order = np.lexsort((test_id, w_id))
    yw, ww, fw, tw = y[order], w_id[order], flip_id[order], test_id[order]
    starts = np.flatnonzero(np.r_[True, ww[1:] != ww[:-1]])
    bounds = np.r_[starts, ww.size]
    idx_all = np.arange(starts.size)
    rng.shuffle(idx_all)
    rates, used, skipped_nesting = [], 0, 0
    for wi in idx_all:
        lo, hi = bounds[wi], bounds[wi + 1]
        yv, fv, tv = yw[lo:hi], fw[lo:hi], tw[lo:hi]
        _, t_inv = np.unique(tv, return_inverse=True)
        _, f_inv = np.unique(fv, return_inverse=True)
        n_t, n_f = int(t_inv.max()) + 1, int(f_inv.max()) + 1
        if n_t < min_test_clusters or n_f < min_flip_blocks:
            continue
        try:
            _assert_nested(t_inv, f_inv, "rung")
        except AssertionError:
            skipped_nesting += 1
            continue
        n = yv.size
        s_c = np.bincount(t_inv, weights=yv)
        n_c = np.bincount(t_inv).astype(float)
        f_of_c = np.full(n_t, -1, dtype=np.int64)
        f_of_c[t_inv] = f_inv
        a_const = float((s_c ** 2).sum())
        cn_const = float((n_c ** 2).sum())
        u = np.bincount(f_of_c, weights=s_c, minlength=n_f)
        v = np.bincount(f_of_c, weights=s_c * n_c, minlength=n_f)
        signs = (rng.integers(0, 2, size=(n_perm, n_f), dtype=np.int8) * 2 - 1).astype(np.float64)
        ybar = (signs @ u) / n
        b = signs @ v
        var = (a_const - 2.0 * ybar * b + ybar * ybar * cn_const) / (n * n)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(var > 0, ybar / np.sqrt(var), np.inf)
        # small-G: t critical at G−1 df, else CR0+z over-rejects (~0.09 at G=12 on calibrated data)
        rates.append(float((np.abs(t) > t_ppf(0.975, n_t - 1)).mean()))
        used += 1
        if used >= max_wallets:
            break
    r = float(np.mean(rates)) if rates else float("nan")
    se = float(np.std(rates, ddof=1) / np.sqrt(len(rates))) if len(rates) > 1 else float("nan")
    return {"n_wallets_used": used, "mean_reject_rate": r, "se_over_wallets": se,
            "skipped_nonnested": skipped_nesting}


# ---------------------------------------------------------------------------
# diagnostic 3b: descriptives (reported, not decisional)
# ---------------------------------------------------------------------------
def _pair_corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 30:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def descriptives(d: dict[str, np.ndarray]) -> dict:
    y, raw = d["y"], d["raw"]
    out: dict = {}
    # consecutive-episode structure within (wallet, coin), ordered by open_ts (entry_bar_ts breaks
    # same-ms ties deterministically — same-block reopens share open_ts)
    order = np.lexsort((d["entry_bar_ts"], d["open_ts"], d["wc_id"]))
    yo, wco = y[order], d["wc_id"][order]
    ot, eb = d["open_ts"][order], d["entry_bar_ts"][order]
    for k in (1, 2, 3):
        same = wco[k:] == wco[:-k]
        out[f"autocorr_lag{k}"] = _pair_corr(yo[:-k][same], yo[k:][same])
    same1 = wco[1:] == wco[:-1]
    gap_h = (ot[1:] - ot[:-1]) / 3_600_000.0
    prev_y, next_y = yo[:-1][same1], yo[1:][same1]
    g = gap_h[same1]
    for name, m in (("lt_1h", g < 1), ("1_4h", (g >= 1) & (g < 4)),
                    ("4_24h", (g >= 4) & (g < 24)), ("ge_24h", g >= 24)):
        out[f"corr_gap_{name}"] = _pair_corr(prev_y[m], next_y[m])
    overlap = (ot[1:] < eb[:-1] + H_MS)[same1]
    out["corr_overlapping_windows"] = _pair_corr(prev_y[overlap], next_y[overlap])
    out["corr_nonoverlapping"] = _pair_corr(prev_y[~overlap], next_y[~overlap])
    out["frac_pairs_overlapping"] = float(overlap.mean())

    # cross-wallet ICC within (coin, hour) and (coin, week), before vs after μ-subtraction
    def icc(vals: np.ndarray, gid: np.ndarray) -> float:
        _, inv = np.unique(gid, return_inverse=True)
        cnt = np.bincount(inv).astype(float)
        keep = cnt[inv] >= 2
        vals, inv = vals[keep], inv[keep]
        _, inv = np.unique(inv, return_inverse=True)
        cnt = np.bincount(inv).astype(float)
        G, N = cnt.size, vals.size
        gm = np.bincount(inv, weights=vals) / cnt
        grand = vals.mean()
        ssb = float((cnt * (gm - grand) ** 2).sum())
        ssw = float(((vals - gm[inv]) ** 2).sum())
        msb, msw = ssb / (G - 1), ssw / (N - G)
        n0 = (N - float((cnt ** 2).sum()) / N) / (G - 1)
        return float((msb - msw) / (msb + (n0 - 1) * msw))
    for gname, gid in (("coin_hour", d["ch_id"]), ("coin_week", d["cw_id"])):
        out[f"icc_{gname}_raw"] = icc(raw, gid)
        out[f"icc_{gname}_timing_resid"] = icc(y, gid)
    return out


# ---------------------------------------------------------------------------
# diagnostic 4: two-way CI coverage simulation (audit S1 deliverable)
# ---------------------------------------------------------------------------
def coverage_sim(n_sim: int = N_SIM_COVERAGE, n_wallets: int = 100, n_weeks: int = 22,
                 lam: float = 3.0, heavy_tail: bool = False, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    hits = {"twoway_cgm": 0, "wallet_only": 0, "week_only": 0, "wider_of_two": 0, "iid": 0}
    floored = 0
    for _ in range(n_sim):
        if heavy_tail:
            rate = np.exp(rng.normal(0.0, 1.0, size=(n_wallets, n_weeks)))
            rate *= lam / rate.mean()
            n_wt = rng.poisson(rate)
        else:
            n_wt = rng.poisson(lam, size=(n_wallets, n_weeks))
        w_id = np.repeat(np.repeat(np.arange(n_wallets), n_weeks), n_wt.ravel())
        t_id = np.repeat(np.tile(np.arange(n_weeks), n_wallets), n_wt.ravel())
        n = w_id.size
        yv = rng.normal(size=n_wallets)[w_id] + rng.normal(size=n_weeks)[t_id] + rng.normal(size=n)
        ci = twoway_cluster_ci(yv, w_id, t_id)
        floored += int(ci.floored)
        hits["twoway_cgm"] += int(ci.lo <= 0.0 <= ci.hi)
        m = float(yv.mean())
        ones = {}
        for key, cid in (("wallet_only", w_id), ("week_only", t_id)):
            v, gg = _cluster_sandwich_var_of_mean(yv, cid)
            hw = t_ppf(0.975, gg - 1) * np.sqrt(v)
            ones[key] = hw
            hits[key] += int(abs(m) <= hw)
        hits["wider_of_two"] += int(abs(m) <= max(ones.values()))
        vi, _ = _cluster_sandwich_var_of_mean(yv, np.arange(n))
        hits["iid"] += int(abs(m) <= ALPHA_Z * np.sqrt(vi))
    return {"n_sim": n_sim, "dims": f"{n_wallets}w x {n_weeks}t, lam={lam}, heavy={heavy_tail}",
            "coverage": {k: v / n_sim for k, v in hits.items()},
            "frac_floored": floored / n_sim}


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
def run() -> dict:
    t0 = time.time()
    meta = json.loads(META_PATH.read_text()) if META_PATH.exists() else {}
    if meta.get("markout_schema_version") not in (None, MARKOUT_SCHEMA_VERSION):
        raise RuntimeError("stage0_y.parquet built under a different markout schema — rebuild")
    if meta.get("mu_schema_version") not in (None, MU_SCHEMA_VERSION):
        raise RuntimeError("stage0_y.parquet built under a different mu schema — rebuild")
    d = load()
    y = d["y"]
    n = y.size
    n_wallets = int(d["w_id"].max()) + 1
    print(f"stage0 run: {n:,} episodes, {n_wallets:,} wallets  (load {time.time()-t0:.0f}s)", flush=True)

    report: dict = {
        "config": {"burn_months": BURN_MONTHS, "cutoff_ms": C0, "horizon": H, "seed": SEED,
                   "n_perm": N_PERM, "flip_chunk": FLIP_CHUNK,
                   "min_ep_calibration": MIN_EP_CAL, "min_ep_sensitivity": MIN_EP_SENS,
                   "band": BAND, "paired_flip_draws": True,
                   "code_commit": _code_commit(),
                   "panel_meta": {k: meta.get(k) for k in
                                  ("code_commit", "markout_schema_version", "mu_schema_version",
                                   "n_rows")},
                   "clustering_time_anchor": "open_ts (entry-tick week used only for the mu join)",
                   "population": "episode-level ARCH-3 filters (taker-opener, non-flagged, "
                                 f"non-liq-close, F0 entry-fresh, entry+{H} < C0); wallet-level "
                                 "eligibility filters intentionally NOT applied"},
        "dims": {"n_episodes": n, "n_wallets": n_wallets,
                 "y_mean_bp": float(y.mean()), "y_sd_bp": float(y.std(ddof=1)),
                 "NOTE": "y_mean is descriptive only — Stage 0 makes no effect-level decision"},
    }

    levels_all = {"episode": np.arange(n), "wallet_coin_day": d["wcd_id"],
                  "wallet_week": d["ww_id"], "coin_week": d["cw_id"], "wallet": d["w_id"]}
    report["moulton"] = moulton_table(y, levels_all)
    print("  moulton done", flush=True)

    cnt = np.bincount(d["w_id"], minlength=n_wallets)
    flip_blocks = {}
    for pop_name, floor in (("cal_ge10", MIN_EP_CAL), ("sens_ge30", MIN_EP_SENS)):
        keep = cnt[d["w_id"]] >= floor
        yc = y[keep]
        pop = {"floor": floor, "n_episodes": int(keep.sum()),
               "n_wallets": int((cnt >= floor).sum()), "levels": {}}
        for name, cid in (("episode", np.arange(n)[keep]),
                          ("wallet_coin_day", d["wcd_id"][keep]),
                          ("wallet_week", d["ww_id"][keep])):
            # SAME seed for every level and population size differs only via n_wallets → the sign
            # matrix is identical across levels within a population: a paired comparison.
            res = flip_calibration(yc, d["w_id"][keep], cid, N_PERM, SEED)
            pop["levels"][name] = res
            print(f"  flip[{pop_name}/{name}]: reject={res['reject_rate']:.4f} "
                  f"CI=({res['wilson_lo']:.4f},{res['wilson_hi']:.4f}) "
                  f"calibrated={res['calibrated']}", flush=True)
        flip_blocks[pop_name] = pop
    report["flip_calibration"] = flip_blocks

    # FROZEN adoption rule (ARCH §2): coarsest calibrating candidate below wallet, on BOTH populations
    adopted = None
    for name in ("wallet_week", "wallet_coin_day", "episode"):
        if (flip_blocks["cal_ge10"]["levels"][name]["calibrated"]
                and flip_blocks["sens_ge30"]["levels"][name]["calibrated"]):
            adopted = name
            break
    report["adoption"] = {
        "rule": "coarsest candidate below wallet with Wilson CI within band on BOTH populations",
        "adopted_cluster_level": adopted,
        "fallback": None if adopted else "wallet_week cluster bootstrap (miscalibration reported)",
        "observation_unit": "episode",
    }
    print(f"  ADOPTED: {adopted or 'NONE -> fallback'}", flush=True)

    # supporting diagnostics: failures are recorded, never fatal to the decisional report
    keep10 = cnt[d["w_id"]] >= MIN_EP_CAL
    for key, fn in (
        ("perwallet_rungs", lambda: {
            "flip_ww_test_wcd": perwallet_rung(y[keep10], d["w_id"][keep10], d["ww_id"][keep10],
                                               d["wcd_id"][keep10], SEED + 10),
            "flip_wcd_test_iid": perwallet_rung(y[keep10], d["w_id"][keep10], d["wcd_id"][keep10],
                                                np.arange(int(keep10.sum())), SEED + 11)}),
        ("descriptives", lambda: descriptives(d)),
        ("coverage_sim_forward_dims", lambda: coverage_sim(seed=SEED + 20)),
        ("coverage_sim_perfold_dims", lambda: coverage_sim(n_weeks=5, seed=SEED + 21)),
        ("coverage_sim_heavytail", lambda: coverage_sim(heavy_tail=True, seed=SEED + 22)),
    ):
        try:
            report[key] = fn()
        except Exception as e:                            # noqa: BLE001 — supporting diag only
            report[key] = {"ERROR": f"{type(e).__name__}: {e}"}
        print(f"  {key} done", flush=True)

    report["runtime_s"] = round(time.time() - t0, 1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str))
    REPORT_MD.write_text(_render_md(report))
    print(f"stage0 run done {report['runtime_s']}s -> {REPORT_JSON}", flush=True)
    return report


def _render_md(r: dict) -> str:
    L = ["# Stage 0 — dependence calibration report", "",
         f"Config: `{r['config']}`", "",
         f"Dims: {r['dims']['n_episodes']:,} episodes / {r['dims']['n_wallets']:,} wallets; "
         f"y sd = {r['dims']['y_sd_bp']:.1f} bp", "",
         "## Moulton SE-inflation vs iid", "",
         "| level | clusters | SE inflation |", "|---|---|---|"]
    for k, v in r["moulton"].items():
        L.append(f"| {k} | {v['n_clusters']:,} | {v['se_inflation_vs_iid']:.3f} |")
    L += ["", "## Pooled flip calibration (wallet-level flips; decisional)", ""]
    for pop_name, pop in r["flip_calibration"].items():
        L += [f"### population {pop_name} (floor {pop['floor']}): "
              f"{pop['n_episodes']:,} eps / {pop['n_wallets']:,} wallets", "",
              "| test cluster level | clusters | reject rate | Wilson 95% | calibrated |",
              "|---|---|---|---|---|"]
        for k, v in pop["levels"].items():
            L.append(f"| {k} | {v['n_clusters']:,} | {v['reject_rate']:.4f} | "
                     f"({v['wilson_lo']:.4f}, {v['wilson_hi']:.4f}) | {v['calibrated']} |")
        L.append("")
    a = r["adoption"]
    L += [f"**ADOPTED (frozen rule):** unit = `{a['observation_unit']}`, "
          f"cluster = `{a['adopted_cluster_level']}`"
          + (f" — FALLBACK: {a['fallback']}" if not a["adopted_cluster_level"] else ""), "",
          "## Per-wallet rungs (supporting)", "", f"`{r.get('perwallet_rungs')}`", "",
          "## Descriptives", "", f"`{r.get('descriptives')}`", "",
          "## Two-way CI coverage (nominal 95%)", "",
          f"forward dims: `{r.get('coverage_sim_forward_dims')}`", "",
          f"per-fold dims: `{r.get('coverage_sim_perfold_dims')}`", "",
          f"heavy-tail: `{r.get('coverage_sim_heavytail')}`", ""]
    return "\n".join(L)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("build", "all"):
        build()
    if cmd in ("run", "all"):
        run()
