"""Fresh-wallet alt validation — registered H1/H2 (Arm C + scale) and Arm T/P comparisons.

Per ALT_UNIVERSE_PREREG.md (+addendum), on cohorts from alt_select.py:
- Forward book: cohort wallets' TEST-month flat taker opens (lake open_entries), ALT coins only,
  8h gross dir-signed markout on the LOCAL asset_ctx mid lattice (backward-ASOF, ≤90s both ends).
- FRESH = wallet not in frozen_alt_universe.json's 133 distinct_wallets.
- Registered inference = ROBUST SPEC: winsor at p95 |mk| within stratum, wallet-folds ≥3 evaluable
  entries, wallet-equal; paired wallet-cluster bootstrap (4000, seed 20260716); wallet-collapsed sign
  test; median-difference permutation. Raw estimates reported alongside, never headline.

    python -m research.studies.copy_cohort.alt_fresh_validate
"""
from __future__ import annotations

import glob
import json
import sys

import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.stats import sign_test
from . import lake

COHORTS = REPO_ROOT / "data" / "derived" / "copy_cohort" / "alt_universe_cohorts.json"
FROZEN = REPO_ROOT / "data" / "derived" / "copy_cohort" / "frozen_alt_universe.json"
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "alt_fresh_validation_report.json"
CTX_DIR = REPO_ROOT / "data" / "raw" / "asset_ctx"
MAJORS = ("BTC", "ETH", "SOL", "HYPE")
H8_MS = 28_800_000
STALE_MS = 90_000
N_BOOT = 4000
SEED = 20260716
COST_SENS = (20.0, 50.0, 100.0)
GATES = {"min_large_entries": 40, "min_folds": 3, "min_large_wallets": 5}


def _ctx_parts(month: int) -> list[str]:
    y, mm = divmod(month, 100)
    nxt = (y + 1) * 100 + 1 if mm == 12 else month + 1
    parts = glob.glob(str(CTX_DIR / f"month={month}" / "day=*" / "ctx.parquet"))
    parts += [p for p in glob.glob(str(CTX_DIR / f"month={nxt}" / "day=*" / "ctx.parquet"))
              if int(p.split("day=")[1][:8]) <= nxt * 100 + 3]
    return parts


def _forward_entries(con, fold: int, wallets: list[str]):
    """Test-month alt flat-open entries of `wallets` with 8h markout (returns numpy dict)."""
    ctx = _ctx_parts(fold)
    if not ctx:
        return None
    ctx_list = ",".join(f"'{p}'" for p in ctx)
    majors = ",".join(f"'{m}'" for m in MAJORS)
    con.execute("CREATE OR REPLACE TEMP TABLE cw AS SELECT * FROM (SELECT UNNEST(?) AS wallet)",
                [sorted(wallets)])
    return con.execute(f"""
        WITH ent AS (
          SELECT o.wallet, o.coin, o.ts, o.dir_sign, CAST(o.notl AS DOUBLE) AS notl
          FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN cw USING (wallet)
          WHERE o.coin NOT IN ({majors})
        ),
        ctx AS (SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL),
        p0 AS (SELECT e.*, c.mid_px AS px0, c.ts AS px0_ts
               FROM ent e ASOF LEFT JOIN ctx c ON e.coin = c.coin AND e.ts >= c.ts),
        p8 AS (SELECT p0.*, c.mid_px AS px8, c.ts AS px8_ts
               FROM p0 ASOF LEFT JOIN ctx c ON p0.coin = c.coin AND (p0.ts + {H8_MS}) >= c.ts)
        SELECT wallet, coin, ts, notl,
               CASE WHEN px0 IS NOT NULL AND px8 IS NOT NULL AND px0 > 0
                      AND (ts - px0_ts) <= {STALE_MS} AND ((ts + {H8_MS}) - px8_ts) <= {STALE_MS}
                    THEN dir_sign * (px8 - px0) / px0 * 1e4 END AS mk
        FROM p8""").fetchnumpy()


def _np(a, dtype=float):
    """fetchnumpy → plain ndarray; NULL-masked cells become NaN (never fill garbage).

    AUDIT FIX 2026-07-17: bare np.asarray on a duckdb masked column silently exposes the
    underlying fill values where the column was NULL; those can be finite and leak into
    the analysis. Same helper as construction_study._np."""
    a = np.ma.filled(a, np.nan) if np.ma.isMaskedArray(a) else a
    return np.asarray(a, dtype)


# ---------- registered robust-spec estimators ----------

def _robust_mask(mk, wallet, fold):
    """winsor p95 |mk| + wallet-folds with >=3 evaluable entries. Returns (mk_w, keep_mask)."""
    if mk.size == 0:
        return mk, np.zeros(0, bool)
    lim = np.percentile(np.abs(mk), 95)
    mk_w = np.clip(mk, -lim, lim)
    key = np.char.add(np.char.add(wallet.astype(str), "|"), fold.astype(str))
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    return mk_w, cnt[inv] >= 3


def _wallet_equal(mk, wallet, fold):
    if mk.size == 0:
        return None, np.zeros(0), np.zeros(0, dtype=object)
    key = np.char.add(np.char.add(wallet.astype(str), "|"), fold.astype(str))
    uk, inv = np.unique(key, return_inverse=True)
    wf = np.bincount(inv, weights=mk) / np.bincount(inv)
    wf_wal = np.array([k.split("|")[0] for k in uk], dtype=object)
    return float(wf.mean()), wf, wf_wal


def _pseudo_labels(pick, idx):
    """Per-draw pseudo-cluster wallet labels ('wallet#j') for a resample `pick` over `idx`.

    AUDIT FIX 2026-07-17 (multiplicity-preserving cluster bootstrap): the old code
    concatenated duplicate wallet picks but the statistic keys on wallet|fold with
    np.unique, so duplicate draws of the same wallet COLLAPSED into one cluster and the
    bootstrap variance was understated. Tagging each draw j as its own pseudo-cluster
    preserves multiplicity — equivalent to the weighted pattern verified in ksweep."""
    return np.concatenate([np.full(idx[x].size, f"{x}#{j}") for j, x in enumerate(pick)]) \
        if len(pick) else np.array([], dtype=str)


def _cluster_boot(mk, wallet, fold, rng):
    uw = np.unique(wallet)
    idx = {x: np.flatnonzero(wallet == x) for x in uw}
    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pick = rng.choice(uw, uw.size, replace=True)
        rows = np.concatenate([idx[x] for x in pick])
        stats[b] = _wallet_equal(mk[rows], _pseudo_labels(pick, idx), fold[rows])[0]
    stats = stats[np.isfinite(stats)]
    return {"ci": [float(np.quantile(stats, .025)), float(np.quantile(stats, .975))],
            "p_gt0": float((stats > 0).mean())}


def _paired_delta_boot(e_a, e_b, rng):
    """Paired wallet-cluster bootstrap of Δ = R(a) − R(b); wallets in both arms resampled once.

    AUDIT FIX 2026-07-17: pseudo-cluster tags preserve duplicate-pick multiplicity (see
    _pseudo_labels); the same pick (with the same tags) is applied to both arms — pairing kept."""
    uw = np.unique(np.concatenate([e_a["wallet"], e_b["wallet"]]))
    ia = {x: np.flatnonzero(e_a["wallet"] == x) for x in uw}
    ib = {x: np.flatnonzero(e_b["wallet"] == x) for x in uw}
    d = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pick = rng.choice(uw, uw.size, replace=True)
        ra = np.concatenate([ia[x] for x in pick]) if any(ia[x].size for x in pick) else np.array([], int)
        rb = np.concatenate([ib[x] for x in pick]) if any(ib[x].size for x in pick) else np.array([], int)
        la = _pseudo_labels(pick, ia) if ra.size else ra
        lb = _pseudo_labels(pick, ib) if rb.size else rb
        ma = _wallet_equal(e_a["mk"][ra], la, e_a["fold"][ra])[0] if ra.size else np.nan
        mb = _wallet_equal(e_b["mk"][rb], lb, e_b["fold"][rb])[0] if rb.size else np.nan
        d[b] = (ma - mb) if (ma is not None and mb is not None) else np.nan
    d = d[np.isfinite(d)]
    if d.size == 0:
        return None
    return {"delta_bp": float(d.mean()), "ci": [float(np.quantile(d, .025)), float(np.quantile(d, .975))],
            "p_gt0": float((d > 0).mean()), "n_boot_valid": int(d.size)}


def _median_perm(e_a, e_b, rng, n=10_000):
    """Median-difference permutation, WALLET-label permutation.

    AUDIT FIX 2026-07-17: the old test permuted individual ENTRIES between arms, ignoring
    wallet clustering (entries of one wallet are dependent) — anti-conservative. Now whole
    wallets are reassigned between arms (a wallet's entries move together); arm sizes are
    held at the observed wallet counts."""
    x_a, x_b = e_a["mk"], e_b["mk"]
    obs = np.median(x_a) - np.median(x_b)
    wal = np.concatenate([e_a["wallet"].astype(str), e_b["wallet"].astype(str)])
    mk = np.concatenate([x_a, x_b])
    uw, inv = np.unique(wal, return_inverse=True)
    na_w = min(int(np.unique(e_a["wallet"].astype(str)).size), uw.size - 1)
    hits = n_valid = 0
    for _ in range(n):
        in_a = np.zeros(uw.size, bool)
        in_a[rng.permutation(uw.size)[:na_w]] = True
        ma = in_a[inv]
        if not ma.any() or ma.all():
            continue
        n_valid += 1
        if np.median(mk[ma]) - np.median(mk[~ma]) >= obs:
            hits += 1
    return {"obs": float(obs), "p": (hits + 1) / (n_valid + 1), "unit": "wallet",
            "n_perm_valid": n_valid}


def _stratum(e, mask):
    return {k: e[k][mask] for k in ("mk", "wallet", "fold", "coin", "notl")}


def _full_inference(e, rng):
    """Robust-spec wallet-equal point + boot CI + sign + raw point for one entry set."""
    if e["mk"].size == 0:
        return {"n": 0}
    raw_pt, _, _ = _wallet_equal(e["mk"], e["wallet"], e["fold"])
    mk_w, keep = _robust_mask(e["mk"], e["wallet"], e["fold"])
    r = {k: e[k][keep] for k in e}
    r["mk"] = mk_w[keep]
    if r["mk"].size == 0:
        return {"n": int(e["mk"].size), "raw_point_bp": raw_pt, "robust": None}
    pt, wf, wf_wal = _wallet_equal(r["mk"], r["wallet"], r["fold"])
    # wallet-collapsed sign test
    uw = np.unique(wf_wal)
    wal_means = np.array([wf[wf_wal == x].mean() for x in uw])
    st = sign_test(wal_means)
    return {"n": int(e["mk"].size), "n_robust": int(r["mk"].size),
            "n_wf_robust": int(np.unique(np.char.add(r["wallet"].astype(str), r["fold"].astype(str))).size),
            "n_wallets": int(np.unique(e["wallet"]).size),
            "raw_point_bp": raw_pt, "robust_point_bp": pt,
            "boot": _cluster_boot(r["mk"], r["wallet"], r["fold"], rng),
            "sign_test": {"n_pos": int(st.n_pos), "n": int(st.n_effective), "p": float(st.p_value)},
            "robust_entries": r}


def run():
    cohorts = json.loads(COHORTS.read_text())
    old133 = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    con = lake.connect()

    # collect forward entries once per fold for the union of all arm members
    per_arm = {a: {k: [] for k in ("mk", "wallet", "fold", "coin", "notl", "large", "fresh")}
               for a in ("C", "T", "P")}
    for fold_s, f in sorted(cohorts["folds"].items()):
        fold = int(fold_s)
        union = sorted({w for a in f["arms"].values() for w in a["members"]})
        d = _forward_entries(con, fold, union)
        if d is None:
            print(f"  fold {fold}: no ctx, skipped", flush=True)
            continue
        w = d["wallet"].astype(str)
        mk_all = _np(d["mk"])
        ok = np.isfinite(mk_all)
        for arm, adef in f["arms"].items():
            mem = adef["members"]
            in_arm = np.array([x in mem for x in w]) & ok
            pa = per_arm[arm]
            pa["mk"].append(mk_all[in_arm])
            pa["wallet"].append(w[in_arm])
            pa["fold"].append(np.full(in_arm.sum(), fold))
            pa["coin"].append(d["coin"].astype(str)[in_arm])
            pa["notl"].append(_np(d["notl"])[in_arm])
            pa["large"].append(np.array([mem[x]["large"] is True for x in w[in_arm]]))
            pa["fresh"].append(np.array([x not in old133 for x in w[in_arm]]))
    arms = {}
    for a, pa in per_arm.items():
        arms[a] = {k: (np.concatenate(v) if v else np.array([])) for k, v in pa.items()}

    rng = np.random.default_rng(SEED)
    rep = {"config": {"n_boot": N_BOOT, "seed": SEED, "robust_spec": "winsor p95 |mk|, wf>=3",
                      "prereg": "ALT_UNIVERSE_PREREG.md (+addendum)", "gates": GATES,
                      "code_commit": lake.git_describe(),
                      "audit_2026_07_17": "multiplicity-preserving cluster boot; wallet-label "
                                          "median perm; masked->NaN markout guard"},
           "arms": {}}

    for a in ("C", "T", "P"):
        e = arms[a]
        fresh = _stratum(e, e["fresh"]) if e["mk"].size else e
        full = e
        ent = {"n_entries": int(e["mk"].size),
               "n_fresh_entries": int(e["fresh"].sum()) if e["mk"].size else 0,
               "overlap_with_old133": int(np.unique(e["wallet"][~e["fresh"]]).size) if e["mk"].size else 0}
        h1_fresh = _full_inference(fresh, rng)
        h1_fresh.pop("robust_entries", None)
        h1_full = _full_inference(full, rng)
        h1_full.pop("robust_entries", None)
        ent["H1_fresh"] = h1_fresh
        ent["H1_full"] = h1_full
        # H2 (scale) inside this arm, FRESH only — registered headline lives on Arm C
        if e["mk"].size:
            fl = e["fresh"] & e["large"]
            fs = e["fresh"] & ~e["large"]
            L, S = _stratum(e, fl), _stratum(e, fs)
            iL, iS = _full_inference(L, rng), _full_inference(S, rng)
            rl, rs = iL.pop("robust_entries", None), iS.pop("robust_entries", None)
            ent["H2_scale"] = {"large": iL, "small": iS}
            if rl is not None and rs is not None and rl["mk"].size and rs["mk"].size:
                ent["H2_scale"]["paired_delta"] = _paired_delta_boot(rl, rs, rng)
                ent["H2_scale"]["median_perm"] = _median_perm(rl, rs,
                                                              np.random.default_rng(SEED + 7))
            ent["coverage"] = {"n_fresh_large_entries": int(fl.sum()),
                               "n_folds": int(np.unique(e["fold"][e["fresh"]]).size) if e["fresh"].any() else 0,
                               "n_fresh_large_wallets": int(np.unique(e["wallet"][fl]).size),
                               "adequate": bool(fl.sum() >= GATES["min_large_entries"]
                                                and np.unique(e["fold"][e["fresh"]]).size >= GATES["min_folds"]
                                                and np.unique(e["wallet"][fl]).size >= GATES["min_large_wallets"])}
            # dose-response + cost sens (secondary)
            ent["notional_strata_fresh"] = {}
            for thr in (250.0, 1000.0):
                m = e["fresh"] & (e["notl"] >= thr)
                if m.sum() >= 5:
                    s = _full_inference(_stratum(e, m), rng); s.pop("robust_entries", None)
                    ent["notional_strata_fresh"][f">=${int(thr)}"] = {
                        "n": s["n"], "robust_point_bp": s.get("robust_point_bp")}
            ent["cost_sensitivity_fresh_robust"] = {
                f"{c:.0f}bp": (None if h1_fresh.get("robust_point_bp") is None
                               else h1_fresh["robust_point_bp"] - c) for c in COST_SENS}
        rep["arms"][a] = ent

    # registered arm-vs-arm deltas (T>C, P>C) on robust FRESH entries
    def robust_fresh(a):
        e = _stratum(arms[a], arms[a]["fresh"]) if arms[a]["mk"].size else None
        if e is None or e["mk"].size == 0:
            return None
        mk_w, keep = _robust_mask(e["mk"], e["wallet"], e["fold"])
        r = {k: e[k][keep] for k in e}; r["mk"] = mk_w[keep]
        return r if r["mk"].size else None

    rc = robust_fresh("C")
    for a in ("T", "P"):
        ra = robust_fresh(a)
        rep[f"H_{a}_gt_C_fresh_robust"] = (_paired_delta_boot(ra, rc, np.random.default_rng(SEED + ord(a)))
                                           if (ra is not None and rc is not None) else None)

    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print(f"\n=== ALT-UNIVERSE fresh-wallet validation (arms C/T/P) ===")
    for a in ("C", "T", "P"):
        r = rep["arms"][a]
        h = r.get("H1_fresh", {})
        b = h.get("boot") or {}
        print(f"arm {a}: fresh n={r.get('n_fresh_entries')} | H1 fresh robust "
              f"{_f(h.get('robust_point_bp'))}bp CI[{_f((b.get('ci') or [None, None])[0])},"
              f"{_f((b.get('ci') or [None, None])[1])}] P(>0)={_f(b.get('p_gt0'), 2)} "
              f"(raw {_f(h.get('raw_point_bp'))})")
        h2 = r.get("H2_scale", {})
        pd = h2.get("paired_delta")
        if pd:
            print(f"       H2 scale Δ={pd['delta_bp']:+.1f} CI[{pd['ci'][0]:+.1f},{pd['ci'][1]:+.1f}] "
                  f"P(Δ>0)={pd['p_gt0']:.2f} | median-perm p={h2.get('median_perm', {}).get('p')}")
    for a in ("T", "P"):
        d = rep.get(f"H_{a}_gt_C_fresh_robust")
        if d:
            print(f"arm {a} − arm C (fresh, robust): Δ={d['delta_bp']:+.1f} "
                  f"CI[{d['ci'][0]:+.1f},{d['ci'][1]:+.1f}] P(Δ>0)={d['p_gt0']:.2f}")
    print(f"-> {OUT}")
    return rep


def _f(x, nd=1):
    return "" if x is None else round(x, nd)


if __name__ == "__main__":
    run()
