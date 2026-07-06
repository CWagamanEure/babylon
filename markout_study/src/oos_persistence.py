"""
OOS Persistence Test (PERSISTENCE_ARCHITECTURE.md v2, post-audit).

Baseline: does ranking takers by a naive metric on a PAST window select wallets whose deployable
edge persists on a FUTURE window? Purged walk-forward + a persistent-random-score permutation
JOINT null (dependent-split-safe) + positive/negative controls + MDE.

Reuses mkcommon verbatim: markout_ret (audited post-fill pricing), winsor_cap/apply_winsor, and
the EXACT stage-2 per-metric definitions (sharpe = winsor-mean/RAW-std; vw = Σmkusd/Σnotl;
avg = winsor-mean; cum = winsor Σmkusd). Everything recomputed on the per-split PURGED slice —
never reads markout_stats.parquet.

Outputs (out/):
  persistence_splits.parquet   : per (coin,metric,horizon,split) cohort + diagnostics
  persistence_verdict.parquet  : per (coin,metric,horizon) joint-null S, p, verdict, BH-FDR
  persistence_controls.parquet : positive / negative / MDE power checks
"""
import sys
from glob import glob
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import (MAJORS, H_LABELS, H_MS, COST_BPS,
                      markout_ret, winsor_cap, apply_winsor, _load_bars, BAR_MS, T0)

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = sorted(glob(str(ROOT / "out/entries/part_*.parquet")))
OUT = ROOT / "out"

# --- config (ARCHITECTURE §3/§4/§9) ---
PH = ["4h", "24h", "168h"]                       # pre-registered horizons
PH_IDX = [H_LABELS.index(l) for l in PH]         # -> columns of markout_ret output
PH_MS = {l: int(H_MS[H_LABELS.index(l)]) for l in PH}
BUCKET_MS = 30 * 86_400_000                       # ~30-day bucket
FIRST_TEST = 4                                    # test buckets w4..wLast (>=4 train buckets)
FLOOR_TR = 30                                     # min PURGED-train entries to be rankable
FLOOR_TE = 10                                     # min test entries for Spearman (diagnostic only)
K = 50                                            # primary cohort size (top-100 also reported)
R_PERM = 1000                                     # joint-null permutations
R_CTRL = 300                                      # permutations inside controls (calibration)
METRICS = ["vw_edge", "avg_edge", "sharpe", "hit_rate", "cum_pnl"]
PRIMARY = ("vw_edge", "24h")
SEED = 12345
# NOTE: cluster-aware CI (doc §4) is descoped by design — the headline is a NULL (nothing beats
# random selection), and co-trade clustering only INFLATES significance, so it cannot rescue a
# null; it would only matter if a cell DID persist. Register if any cell persists.


def priced_close_ms(t):
    """Realized close time of _next_bar_close_vec(lk, t): close of the first bar starting
    strictly AFTER t, i.e. (floor(t/BAR)+2)*BAR. Used by the embargo (confirm-item-1)."""
    return (t // BAR_MS + 2) * BAR_MS


def wallet_agg(inv, W, r_w, r_raw, notl):
    """Per-wallet aggregates over a set of entries (all already finite & sliced by caller).
    inv: wallet codes 0..W-1; r_w winsorized ret; r_raw raw ret; notl notional. Mirrors
    markout_stats.wallet_stats exactly. Returns dict of length-W arrays."""
    cnt = np.bincount(inv, minlength=W)
    sum_notl = np.bincount(inv, weights=notl, minlength=W)
    sum_mkusd = np.bincount(inv, weights=r_w * notl, minlength=W)     # winsorized $
    sum_w = np.bincount(inv, weights=r_w, minlength=W)
    sum_r = np.bincount(inv, weights=r_raw, minlength=W)
    sum_r2 = np.bincount(inv, weights=r_raw * r_raw, minlength=W)
    hits = np.bincount(inv, weights=(r_raw > 0).astype(float), minlength=W)
    c = cnt.astype(np.float64)
    cpos = np.maximum(c, 1.0)
    mean_w = sum_w / cpos * 1e4                                       # winsorized mean (bps)
    with np.errstate(invalid="ignore", divide="ignore"):
        vw = np.where(sum_notl > 0, sum_mkusd / np.where(sum_notl > 0, sum_notl, 1.0) * 1e4, np.nan)
        std_raw = np.sqrt(np.maximum(sum_r2 - sum_r ** 2 / cpos, 0.0) / np.maximum(c - 1, 1.0)) * 1e4
        sharpe = np.where((c > 0) & (std_raw > 0), mean_w / np.where(std_raw > 0, std_raw, 1.0), np.nan)
        hit = np.where(c > 0, hits / cpos, np.nan) * 1e4              # scale so ranking uses same units; monotone in hits/c
    return dict(cnt=cnt, sum_notl=sum_notl, sum_mkusd=sum_mkusd, sum_w=sum_w,
                vw_edge=vw, avg_edge=mean_w, sharpe=sharpe, hit_rate=hit, cum_pnl=sum_mkusd)


def rank_desc(values, codes, elig):
    """Descending-metric, ascending-wallet-id tie-break; return eligible codes sorted best-first.
    Ineligible or non-finite metric dropped."""
    m = elig & np.isfinite(values)
    idx = np.nonzero(m)[0]
    order = np.lexsort((codes[idx], -values[idx]))   # primary -value asc (=value desc), tie code asc
    return idx[order]


def cohort_vw(pick, sum_mkusd, sum_notl):
    """Active-only volume-weighted deployable edge (bps) over a pick list. Silent picks have
    sum_notl==0 -> excluded from denom automatically (copy-sim semantics)."""
    num = sum_mkusd[pick].sum(); den = sum_notl[pick].sum()
    return (num / den * 1e4) if den > 0 else np.nan, num, den


def build_coin(coin, lk):
    """Load a coin's entries, compute raw markout once for the 3 horizons, frozen full caps,
    buckets, wallet codes. Returns a context dict or None."""
    df = (pl.scan_parquet(ENTRIES).filter(pl.col("coin") == coin)
          .select("wallet", "b_ts", "dir", "entry_px", "notl").collect())
    if df.height == 0:
        return None
    wallet = df["wallet"].to_numpy(); b_ts = df["b_ts"].to_numpy()
    d = df["dir"].to_numpy(); entry_px = df["entry_px"].to_numpy(); notl = df["notl"].to_numpy()
    uniq, inv = np.unique(wallet, return_inverse=True)
    inv = inv.astype(np.int64)
    ret_all = markout_ret(lk, b_ts, d, entry_px)          # (n,12) raw, ONCE
    ret_raw = ret_all[:, PH_IDX].copy()                   # (n,3)
    del ret_all
    codes = np.arange(uniq.size, dtype=np.int64)
    cap_full = [winsor_cap(ret_raw[:, j]) for j in range(len(PH))]   # frozen full-sample caps (test outcome)
    bucket = ((b_ts - T0) // BUCKET_MS).astype(np.int64)
    return dict(coin=coin, uniq=uniq, inv=inv, W=uniq.size, codes=codes,
                b_ts=b_ts, notl=notl, ret_raw=ret_raw, cap_full=cap_full, bucket=bucket,
                n_buckets=int(bucket.max()) + 1)


def split_tables(ctx, ret_raw=None):
    """For every (horizon, split) build eligible-wallet tables: train metric values + test
    contributions. ret_raw override lets controls inject/permute. Returns
    tab[hi][t] = dict(elig(codes), metrics{m:arr[W]}, te_mkusd[W], te_notl[W], te_cnt[W],
                      te_sumw[W]) with arrays indexed by global wallet code."""
    if ret_raw is None:
        ret_raw = ctx["ret_raw"]
    W, inv, notl, b_ts, bucket = ctx["W"], ctx["inv"], ctx["notl"], ctx["b_ts"], ctx["bucket"]
    tab = {}
    for hi, hl in enumerate(PH):
        h_ms = PH_MS[hl]; cap_te = ctx["cap_full"][hi]
        pexit = priced_close_ms(b_ts + h_ms)
        col_raw = ret_raw[:, hi]
        fin = np.isfinite(col_raw)
        per_t = {}
        for t in range(FIRST_TEST, ctx["n_buckets"]):
            test_start = T0 + t * BUCKET_MS
            # --- TRAIN (purged): before test start AND priced exit closes before test start ---
            adm = fin & (b_ts < test_start) & (pexit <= test_start)
            if not adm.any():
                continue
            cap_tr = winsor_cap(col_raw[adm])
            r_w_tr = apply_winsor(col_raw, cap_tr)
            tr = wallet_agg(inv[adm], W, r_w_tr[adm], col_raw[adm], notl[adm])
            elig_mask = tr["cnt"] >= FLOOR_TR
            elig = np.nonzero(elig_mask)[0]
            if elig.size < K:                       # thin-split guard (confirm-newissue): skip
                continue
            # --- TEST: entries in bucket t, frozen full-sample cap ---
            tmask = fin & (bucket == t)
            r_w_te = apply_winsor(col_raw, cap_te)
            te = wallet_agg(inv[tmask], W, r_w_te[tmask], col_raw[tmask], notl[tmask])
            per_t[t] = dict(elig=elig,
                            metrics={m: tr[m] for m in METRICS},
                            te_mkusd=te["sum_mkusd"], te_notl=te["sum_notl"],
                            te_cnt=te["cnt"], te_sumw=te["sum_w"])
        tab[hi] = per_t
    return tab


def real_S(tab_h, codes, metric, k=K):
    """Turnover-weighted top-k cohort vw edge across all splits for one metric+horizon."""
    num = den = 0.0
    for t, s in tab_h.items():
        vals = s["metrics"][metric]
        order = rank_desc(vals, codes, np.isin(codes, s["elig"]))  # elig-restricted rank
        pick = order[:k]
        _, n, dsum = cohort_vw(pick, s["te_mkusd"], s["te_notl"])
        num += n; den += dsum
    return (num / den * 1e4) if den > 0 else np.nan


def joint_null(tab_h, codes, W, k=K, R=R_PERM, seed=SEED):
    """Persistent-random-score permutation null: one score/wallet carried across all splits.
    Metric-agnostic -> shared by all metrics at this horizon. Returns S_null array (R,)."""
    rng = np.random.default_rng(seed)
    # precompute per-split eligible index once
    splits = [(s["elig"], s["te_mkusd"], s["te_notl"]) for s in tab_h.values()]
    out = np.empty(R)
    for r in range(R):
        score = rng.random(W)                         # one persistent score per wallet
        num = den = 0.0
        for elig, mk, no in splits:
            # rank eligible by score desc, tie-break code asc (lexsort)
            order = elig[np.lexsort((elig, -score[elig]))]
            pick = order[:k]
            num += mk[pick].sum(); den += no[pick].sum()
        out[r] = (num / den * 1e4) if den > 0 else np.nan
    return out


def spearman_diag(tab_h, codes, metric):
    """Diagnostic (never verdict): rank-corr(train metric, test vw edge) over wallets with
    >=FLOOR_TE test entries, pooled across splits; + split-half reliability + disattenuated."""
    xs, ys = [], []
    for s in tab_h.values():
        elig = s["elig"]
        te_cnt = s["te_cnt"][elig]
        keep = te_cnt >= FLOOR_TE
        if keep.sum() < 5:
            continue
        w = elig[keep]
        x = s["metrics"][metric][w]
        with np.errstate(invalid="ignore", divide="ignore"):
            y = np.where(s["te_notl"][w] > 0, s["te_mkusd"][w] / np.where(s["te_notl"][w] > 0, s["te_notl"][w], 1) * 1e4, np.nan)
        good = np.isfinite(x) & np.isfinite(y)
        xs.append(x[good]); ys.append(y[good])
    if not xs:
        return None
    X = np.concatenate(xs); Y = np.concatenate(ys)
    if X.size < 10:
        return None
    rho = _spearman(X, Y)
    return dict(spearman=float(rho), n_both=int(X.size))


def _spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    ra = ra - ra.mean(); rb = rb - rb.mean()
    denom = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / denom) if denom > 0 else np.nan


def decile_slope(tab_h, codes, metric):
    """Slope of decile-mean test vw edge on decile rank (1..10), pooled across splits."""
    dec_num = np.zeros(10); dec_den = np.zeros(10)
    for s in tab_h.items() if False else tab_h.values():
        vals = s["metrics"][metric]
        order = rank_desc(vals, codes, np.isin(codes, s["elig"]))
        if order.size < 10:
            continue
        # decile 10 = best (top rank). split order into 10 by count.
        grp = (np.arange(order.size) * 10 // order.size)      # 0=best..9=worst
        for g in range(10):
            pick = order[grp == g]
            dec_num[9 - g] += s["te_mkusd"][pick].sum()       # index 9 = best -> decile 10
            dec_den[9 - g] += s["te_notl"][pick].sum()
    with np.errstate(invalid="ignore", divide="ignore"):
        edge = np.where(dec_den > 0, dec_num / np.where(dec_den > 0, dec_den, 1) * 1e4, np.nan)
    x = np.arange(1, 11); good = np.isfinite(edge)
    if good.sum() < 3:
        return None
    xg = x[good] - x[good].mean(); yg = edge[good] - edge[good].mean()
    slope = float((xg * yg).sum() / (xg ** 2).sum()) if (xg ** 2).sum() > 0 else np.nan
    return dict(decile_slope=slope, dec10=float(edge[9]) if good[9] else None,
                dec1=float(edge[0]) if good[0] else None)


def bh_fdr(pvals, q=0.05):
    """Benjamini-Hochberg: return boolean reject array for secondary-grid multiplicity."""
    p = np.asarray(pvals, float); n = p.size
    order = np.argsort(p); ranked = p[order]
    thresh = (np.arange(1, n + 1) / n) * q
    passed = ranked <= thresh
    kmax = np.nonzero(passed)[0].max() + 1 if passed.any() else 0
    rej = np.zeros(n, bool)
    if kmax:
        rej[order[:kmax]] = True
    return rej


# ------------------------------------------------------------------ main analysis
def analyse(ctx, tab, seed=SEED):
    """Produce per-(metric,horizon,split) rows + per-(metric,horizon) verdict rows for one coin."""
    coin, codes, W = ctx["coin"], ctx["codes"], ctx["W"]
    split_rows, verdict_rows = [], []
    for hi, hl in enumerate(PH):
        tab_h = tab[hi]
        if not tab_h:
            continue
        s_null = joint_null(tab_h, codes, W, seed=seed)
        s_null = s_null[np.isfinite(s_null)]
        for metric in METRICS:
            S = real_S(tab_h, codes, metric)
            # (1+Σ)/(1+R) so a Monte-Carlo p is never exactly 0 [code-audit m2]
            p = float((1 + (s_null >= S).sum()) / (1 + s_null.size)) if (np.isfinite(S) and s_null.size) else np.nan
            sp = spearman_diag(tab_h, codes, metric)
            dc = decile_slope(tab_h, codes, metric)
            verdict_rows.append(dict(
                coin=coin, metric=metric, horizon=hl, n_splits=len(tab_h),
                S_bps=None if not np.isfinite(S) else float(S),
                null_mean_bps=float(np.mean(s_null)) if s_null.size else None,
                null_p95_bps=float(np.percentile(s_null, 95)) if s_null.size else None,
                joint_p=None if np.isnan(p) else p,
                persists=bool(np.isfinite(S) and S > 0 and p < 0.05),
                is_primary=(metric, hl) == PRIMARY,
                spearman=None if sp is None else sp["spearman"],
                n_both=None if sp is None else sp["n_both"],
                decile_slope=None if dc is None else dc["decile_slope"]))
            # per-split cohort detail
            for t, s in tab_h.items():
                order = rank_desc(s["metrics"][metric], codes, np.isin(codes, s["elig"]))
                pick = order[:K]
                vw, num, den = cohort_vw(pick, s["te_mkusd"], s["te_notl"])
                n_active = int((s["te_cnt"][pick] > 0).sum())
                ew0 = float(np.where(s["te_cnt"][pick] > 0, s["te_sumw"][pick] / np.maximum(s["te_cnt"][pick], 1) * 1e4, 0.0).mean())
                vw100, _, _ = cohort_vw(order[:100], s["te_mkusd"], s["te_notl"])   # robustness [code-audit m5]
                split_rows.append(dict(
                    coin=coin, metric=metric, horizon=hl, test_bucket=int(t),
                    pool=int(s["elig"].size), cohort_vw_bps=None if np.isnan(vw) else float(vw),
                    cohort_vw100_bps=None if np.isnan(vw100) else float(vw100),
                    cohort_ew0_bps=ew0, n_active=n_active, turnover=float(den),
                    net_bps=None if np.isnan(vw) else float(vw - COST_BPS[coin])))
    return split_rows, verdict_rows


# ------------------------------------------------------------------ controls (§6)
def _inject(ctx, n_inj, delta_bps, rng):
    """Positive control: add +delta (bps, pre-winsor) to a RANKABLE wallet subset's markout in
    ALL entries (both windows) -> persistently informed. Injecting only into wallets with
    >=FLOOR_TR total entries gives the ranking its best shot (a fair power test — the MDE is the
    smallest edge detectable for wallets that CAN be ranked, not diluted by never-eligible dust).
    Returns modified ret_raw + injected set."""
    W = ctx["W"]
    cnt = np.bincount(ctx["inv"], minlength=W)
    rankable = np.nonzero(cnt >= FLOOR_TR)[0]
    inj = rng.choice(rankable, size=min(n_inj, rankable.size), replace=False)
    is_inj = np.zeros(W, bool); is_inj[inj] = True
    ent_inj = is_inj[ctx["inv"]]
    ret = ctx["ret_raw"].copy()
    ret[ent_inj, :] += delta_bps / 1e4
    return ret, inj


def run_controls(ctx):
    rows = []
    coin = ctx["coin"]; codes = ctx["codes"]; W = ctx["W"]
    pm, ph = PRIMARY
    hi = PH.index(ph)
    # --- negative control: permute wallet labels (structure-preserving) ---
    rng = np.random.default_rng(SEED + 1)
    fp = 0; ntot = 0
    for s in range(20):
        # structure-preserving: shuffle the per-ENTRY wallet assignment (keeps price paths,
        # times, and the per-wallet count multiset; breaks train-identity <-> test-edge link).
        # NB relabeling codes bijectively (perm[inv]) would be INERT — same partition. [code-audit MAJOR]
        inv_perm = rng.permutation(ctx["inv"])
        ctx2 = dict(ctx); ctx2["inv"] = inv_perm
        tab = split_tables(ctx2)
        if not tab.get(hi):
            continue
        s_null = joint_null(tab[hi], codes, W, R=R_CTRL, seed=SEED + 100 + s)
        s_null = s_null[np.isfinite(s_null)]
        S = real_S(tab[hi], codes, pm)
        if np.isfinite(S) and s_null.size:
            ntot += 1
            if S > 0 and (s_null >= S).mean() < 0.05:
                fp += 1
    rows.append(dict(coin=coin, control="negative", horizon=ph, metric=pm,
                     trials=ntot, detections=fp, rate=fp / ntot if ntot else None,
                     note="permuted wallet labels; rate should ~= 0.05"))
    # --- positive control + MDE: sweep delta, detection rate over seeds ---
    grid = [40, 80, 160, 320, 640, 1280]
    n_inj = 100                                    # inject into 100 rankable wallets (~2x cohort)
    mde = None
    for delta in grid:
        det = 0; rec = []; ntot = 0
        for s in range(12):
            rng = np.random.default_rng(SEED + 7 + s)
            ret_inj, inj = _inject(ctx, n_inj, delta, rng)
            ctx2 = dict(ctx); ctx2["ret_raw"] = ret_inj
            tab = split_tables(ctx2)
            if not tab.get(hi):
                continue
            s_null = joint_null(tab[hi], codes, W, R=R_CTRL, seed=SEED + 200 + s)
            s_null = s_null[np.isfinite(s_null)]
            S = real_S(tab[hi], codes, pm)
            if np.isfinite(S) and s_null.size:
                ntot += 1; rec.append(S)
                if S > 0 and (s_null >= S).mean() < 0.05:
                    det += 1
        rate = det / ntot if ntot else 0.0
        rows.append(dict(coin=coin, control="positive", horizon=ph, metric=pm,
                         delta_bps=delta, trials=ntot, detections=det, rate=rate,
                         recovered_bps=float(np.mean(rec)) if rec else None,
                         note="injected +delta both windows"))
        if mde is None and rate >= 0.8:
            mde = delta
    rows.append(dict(coin=coin, control="MDE", horizon=ph, metric=pm, delta_bps=mde,
                     note="smallest injected delta detected at >=80% power (primary cell); "
                          "null result => true persistence below this bound, NOT unmeasurable"))
    return rows


def main(controls_coin="BTC", smoke=False):
    assert ENTRIES, "run build_entries.py first"
    lk = _load_bars()
    coins = ["BTC"] if smoke else MAJORS
    split_rows, verdict_rows, ctrl_rows = [], [], []
    for coin in coins:
        if lk.get(coin) is None:
            print(f"{coin}: no bars", flush=True); continue
        ctx = build_coin(coin, lk[coin])
        if ctx is None:
            print(f"{coin}: no entries", flush=True); continue
        tab = split_tables(ctx)
        sr, vr = analyse(ctx, tab)
        split_rows += sr; verdict_rows += vr
        print(f"{coin}: {ctx['W']:,} wallets, {ctx['n_buckets']} buckets, "
              f"{sum(len(tab[hi]) for hi in tab)} (horizon,split) cells", flush=True)
        if coin == controls_coin:
            ctrl_rows += run_controls(ctx)
            print(f"{coin}: controls done", flush=True)

    vdf = pl.DataFrame(verdict_rows)
    # BH-FDR over SECONDARY cells only (primary is pre-registered/protected)
    sec = vdf.filter(~pl.col("is_primary") & pl.col("joint_p").is_not_null())
    if sec.height:
        rej = bh_fdr(sec["joint_p"].to_numpy())
        Sarr = sec["S_bps"].fill_null(float("nan")).to_numpy()
        # persistence REQUIRES S>0 too — a negative-edge cell can beat a negative-centered
        # null on p alone; BH rejection must be AND-ed with deployability. [code-audit M1]
        fdr_map = {(r["coin"], r["metric"], r["horizon"]): bool(x) and (s > 0)
                   for r, x, s in zip(sec.iter_rows(named=True), rej, Sarr)}
    else:
        fdr_map = {}
    vdf = vdf.with_columns(pl.struct(["coin", "metric", "horizon", "is_primary", "persists"]).map_elements(
        lambda r: bool(r["persists"]) if r["is_primary"] else fdr_map.get((r["coin"], r["metric"], r["horizon"]), False),
        return_dtype=pl.Boolean).alias("persists_fdr"))

    pl.DataFrame(split_rows).write_parquet(OUT / "persistence_splits.parquet")
    vdf.write_parquet(OUT / "persistence_verdict.parquet")
    if ctrl_rows:
        pl.DataFrame(ctrl_rows).write_parquet(OUT / "persistence_controls.parquet")
    print(f"DONE -> persistence_splits / persistence_verdict / persistence_controls in {OUT}", flush=True)


if __name__ == "__main__":
    main(smoke="--smoke" in sys.argv)
