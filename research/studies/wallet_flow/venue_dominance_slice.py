"""venue_dominance_slice — does the alt-timing tilt signal concentrate on HL-led vs Binance-led coins?

Reuses the EXACT walk-forward OOS design of alt_timing_dashboard_data.py (same folds, same cohort
selection, same embargo) but tracks tilt AND forward residual PER COIN (not pooled into one index),
so we can bucket the per-coin OOS IC by venue dominance (out/coin_venue_cg via markout_study) and test
an HL-dominance-WEIGHTED basket vs the deployed equal-weight-7.

Single a-priori bucket split: median hl_share_vs_binance over the 45-name alt universe (no threshold search).
RAM-safe: duckdb does the heavy aggregation server-side; month-batched cohort tables reused from cache.

    .venv/bin/python -m research.studies.wallet_flow.venue_dominance_slice
"""
from __future__ import annotations
import functools, warnings, json
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
Wb, MINOBS = 720, 240
S_HEAD = 1
N_PLACEBO_OOS = 40                   # per-coin placebo draws (lighter than dashboard's 60; still gives an SE)
FEES = {"maker": 0.0, "toptier": 2.4, "base": 4.5}
SEED = 20260711
HOUR = 3600000
MINH = 20
COH = Path("data/derived/alt_timing/cohort.json")
VENUE = Path("markout_study/out/coin_venue_cg.parquet")
OUT = Path("data/derived/alt_timing/venue_slice")


def _ann_sharpe(x):
    x = x[np.isfinite(x)]
    if len(x) < 10 or x.std() == 0: return float("nan")
    return float(x.mean() / x.std() * np.sqrt(24 * 365))


def _prev(m):
    y, mo = divmod(m, 100); mo -= 1
    return (y - 1) * 100 + 12 if mo == 0 else y * 100 + mo


def _rand_mask(rng, npool, nsel):
    mm = np.zeros(npool, bool); mm[rng.choice(npool, min(nsel, npool), replace=False)] = True; return mm


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(COH.read_text())
    cohort = list(cfg["cohort"]); basket = list(cfg["basket"]); cohort_sha = cfg["cohort_sha"]
    alt_universe = list(cfg["alt_universe"])
    print(f"cohort {cohort_sha}: {len(cohort)} wallets, basket {basket}, alt universe {len(alt_universe)}")

    vt = pq.read_table(VENUE, columns=["coin", "hl_share_vs_binance", "hl_share_vs_majors", "on_binance"])
    v_coin = vt.column("coin").to_pylist()
    v_hlb = vt.column("hl_share_vs_binance").to_pylist()
    v_hlm = vt.column("hl_share_vs_majors").to_pylist()
    venue = {c: (hb, hm) for c, hb, hm in zip(v_coin, v_hlb, v_hlm)}
    missing = [c for c in alt_universe if c not in venue]
    print(f"venue table matched {len(alt_universe) - len(missing)}/{len(alt_universe)} alts; missing {missing}")
    hlshare = {c: float(venue[c][0]) for c in alt_universe if c in venue}
    hlshare_maj = {c: float(venue[c][1]) for c in alt_universe if c in venue}
    med = float(np.median(list(hlshare.values())))
    hl_dom = {c: (hlshare[c] >= med) for c in hlshare}
    print(f"median hl_share_vs_binance over {len(hlshare)} alts = {med:.4f}")
    print("HL-dominant (>=median):", sorted([c for c in hl_dom if hl_dom[c]]))
    print("Binance-dominant (<median):", sorted([c for c in hl_dom if not hl_dom[c]]))

    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_venue'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    assert set(alts) == set(alt_universe), "alt universe mismatch vs frozen cohort.json — formation params drifted"
    coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins); A.build_cohort_tables(con, coins)
    hours, ci, N = panel["hours"], panel["ci"], panel["N"]; hmin = int(hours[0]); hh = hours.astype(np.int64)
    fr = panel["fr"]                     # [N,C] H1-forward factor-neutral residual, per coin (already h+1 shifted)

    # ---- BTC/ETH-neutral index/basket returns (mirror dashboard, needed for the book test + rotation lagmom) ----
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbe AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d = con.execute("SELECT coin,h,mid FROM hbe").fetchnumpy()
    ca = np.asarray(d["coin"], dtype=object); ha = d["h"].astype(np.int64); C = len(coins)
    Lp = np.full((N, C), np.nan); rr = ((ha - hmin) // 3600000).astype(int); cc = np.array([ci[str(x)] for x in ca])
    ok = (rr >= 0) & (rr < N); Lp[rr[ok], cc[ok]] = np.log(d["mid"].astype(float)[ok]); R = np.diff(Lp, axis=0, prepend=np.nan)
    btc, eth = R[:, ci["BTC"]], R[:, ci["ETH"]]; eth_o = eth - rolling_beta(eth, btc, Wb, MINOBS) * btc

    def neutral_w(cols, w):
        W = np.asarray(w); W = W / W.sum()
        s = np.nansum(R[:, [ci[c] for c in cols]] * W[None, :], axis=1)
        valid = np.isfinite(R[:, [ci[c] for c in cols]]).astype(float) @ W
        s = np.where(valid > 0.5, s, np.nan)          # require most weight present (mirrors nanmean semantics)
        s = s - rolling_beta(s, btc, Wb, MINOBS) * btc
        return s - rolling_beta(s, eth_o, Wb, MINOBS) * eth_o

    idx = neutral_w(alts, np.ones(len(alts)))
    cs = np.where(np.isfinite(idx), idx, 0.0)
    lagmom = np.array([cs[max(0, h - 24):h].sum() if h > 0 else np.nan for h in range(N)])

    bkt_eq = neutral_w(basket, np.ones(len(basket)))
    bkt_eq_next = np.array([bkt_eq[h + 1] if h < N - 1 else np.nan for h in range(N)])
    hl_w = np.array([hlshare.get(c, np.nan) for c in basket])
    print(f"basket hl_share_vs_binance weights: {dict(zip(basket, np.round(hl_w, 4)))}")
    bkt_hlw = neutral_w(basket, hl_w)
    bkt_hlw_next = np.array([bkt_hlw[h + 1] if h < N - 1 else np.nan for h in range(N)])

    fwH1 = np.full(N, np.nan)
    fwH1[:] = np.nan
    # index-level H1 forward return used ONLY for wallet scoring (identical to dashboard's fwH[1])
    fwH1[:-1] = cs[1:]

    # ---- eligible recency pool (placebo universe), identical gate to dashboard ----
    RECENT_MONTHS = (202605, 202606); MIN_RECENT_H = 40
    inlist = "('" + "','".join(alts) + "')"; rm = ",".join(str(m) for m in RECENT_MONTHS)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE elig AS SELECT wallet FROM alt_flow
        WHERE month IN ({rm}) AND coin IN {inlist}
        GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""")

    months = [int(r[0]) for r in con.execute("SELECT DISTINCT mth FROM awb ORDER BY mth").fetchall()]
    TESTM = months[4:]
    print(f"OOS folds (identical to dashboard): {TESTM}")
    NSEL_OOS = min(len(cohort), 1500)
    Cn = len(alts); acoi = {c: i for i, c in enumerate(alts)}
    oos_tilt_c = np.full((N, Cn), np.nan)             # per-coin OOS informed tilt
    rnd_tilt_c = np.full((N_PLACEBO_OOS, N, Cn), np.nan)  # per-coin OOS placebo tilt (RAM: 40*N*45 floats)
    rng = np.random.default_rng(SEED)

    for m in TESTM:
        ms_cut = int(con.execute(f"SELECT min(h) FROM awb WHERE mth={m}").fetchone()[0])
        emb = ms_cut - HOUR
        fmask = np.isfinite(fwH1) & (hh < emb)
        con.register("fsrc", {"hms": hh[fmask].astype(np.int64), "fwd": fwH1[fmask].astype(float)})
        con.execute("CREATE OR REPLACE TEMP TABLE ftab AS SELECT * FROM fsrc"); con.unregister("fsrc")
        sc = con.execute(f"""WITH wh AS (SELECT wallet,h,sum(flow) nf FROM awb
                WHERE mth<{m} AND coin NOT IN ('BTC','ETH') GROUP BY wallet,h)
            SELECT wh.wallet, avg(sign(wh.nf)*f.fwd) score FROM wh JOIN ftab f ON wh.h=f.hms
            WHERE wh.nf<>0 GROUP BY wh.wallet HAVING count(*)>={MINH}""").fetchnumpy()
        wal_m = np.asarray([str(x) for x in sc["wallet"]], dtype=object); score_m = sc["score"].astype(float)
        r1, r2 = _prev(_prev(m)), _prev(m)
        act = con.execute(f"""SELECT wallet FROM alt_flow WHERE month IN ({r1},{r2}) AND coin IN {inlist}
            GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""").fetchall()
        active = set(str(x[0]) for x in act)
        elig = np.array([w in active for w in wal_m]); wal_e = wal_m[elig]; sc_e = score_m[elig]
        if len(wal_e) < NSEL_OOS:
            print(f"  fold {m}: skipped (elig {len(wal_e)} < {NSEL_OOS})"); continue
        cohort_m = set(wal_e[np.argsort(-sc_e)[:NSEL_OOS]])
        con.register("elig_arr", {"wallet": wal_e.astype(object)})
        frr = con.execute(f"""SELECT wb.wallet, wb.coin, wb.h, sign(wb.flow) s FROM awb wb JOIN elig_arr e USING(wallet)
            WHERE wb.mth={m} AND wb.flow<>0 AND wb.coin NOT IN ('BTC','ETH')""").fetchnumpy(); con.unregister("elig_arr")
        fw_ = np.asarray([str(x) for x in frr["wallet"]], dtype=object)
        fco = np.asarray([str(x) for x in frr["coin"]], dtype=object)
        fh = ((frr["h"].astype(np.int64) - hmin) // 3600000).astype(int); fs = frr["s"].astype(np.int64)
        uwm, wcm = np.unique(fw_, return_inverse=True)
        keep_co = np.array([c in acoi for c in fco])
        kk = (fh >= 0) & (fh < N) & keep_co
        fh, fs, wcm, fco = fh[kk], fs[kk], wcm[kk], fco[kk]
        fcc = np.array([acoi[c] for c in fco])

        def fold_tilt_percoin(wmask):
            sel = wmask[wcm]
            npo = np.zeros((N, Cn)); nne = np.zeros((N, Cn))
            np.add.at(npo, (fh[sel & (fs > 0)], fcc[sel & (fs > 0)]), 1.0)
            np.add.at(nne, (fh[sel & (fs < 0)], fcc[sel & (fs < 0)]), 1.0)
            den = npo + nne
            return np.where(den > 0, (npo - nne) / den, np.nan)

        cm = np.array([w in cohort_m for w in uwm])
        ft = fold_tilt_percoin(cm)
        mh = np.isfinite(ft)
        oos_tilt_c[mh] = ft[mh]
        for j in range(N_PLACEBO_OOS):
            rt = fold_tilt_percoin(_rand_mask(rng, len(uwm), NSEL_OOS))
            rmh = np.isfinite(rt)
            rnd_tilt_c[j][rmh] = rt[rmh]
        print(f"    fold {m}: elig {len(wal_e):,}, cohort {len(cohort_m)}, coin-hours filled {int(mh.sum())}")

    tm_any = np.isfinite(oos_tilt_c).any(axis=1)
    print(f"OOS hours with >=1 coin tilt: {int(tm_any.sum())} / {N}")

    # ================= PER-COIN OOS IC =================
    rows = []
    for c in alts:
        j = acoi[c]
        t = oos_tilt_c[:, j]; y = fr[:, j]
        m = np.isfinite(t) & np.isfinite(y)
        n_eff = int(m.sum())
        ic = float(A._spear(t, y))
        draws = np.array([A._spear(rnd_tilt_c[k, :, j], y) for k in range(N_PLACEBO_OOS)])
        draws = draws[np.isfinite(draws)]
        mu, sd = (float(np.nanmean(draws)), float(np.nanstd(draws))) if len(draws) else (np.nan, np.nan)
        z = float((ic - mu) / sd) if sd and sd > 0 else float("nan")
        t_zero = float(ic * np.sqrt(n_eff)) if n_eff > 0 else float("nan")
        rows.append(dict(coin=c, n_eff=n_eff, ic=ic, placebo_mean=mu, placebo_std=sd, z_vs_random=z,
                          t_vs_zero=t_zero, hl_share_vs_binance=hlshare.get(c, float("nan")),
                          hl_share_vs_majors=hlshare_maj.get(c, float("nan")), hl_dominant=hl_dom.get(c)))
    rows.sort(key=lambda r: -r["hl_share_vs_binance"])
    print("\n=== per-coin OOS IC, sorted by hl_share_vs_binance (desc) ===")
    hdr = f"{'coin':10s} {'n_eff':>7s} {'ic':>9s} {'plc_mu':>9s} {'plc_sd':>8s} {'z_rand':>8s} {'t_zero':>8s} {'hl_vs_bn':>9s} {'hl_vs_maj':>9s} {'dom':>5s}"
    print(hdr)
    for r in rows:
        print(f"{r['coin']:10s} {r['n_eff']:7d} {r['ic']:+9.4f} {r['placebo_mean']:+9.4f} {r['placebo_std']:8.4f} "
              f"{r['z_vs_random']:+8.2f} {r['t_vs_zero']:+8.2f} {r['hl_share_vs_binance']:9.4f} "
              f"{r['hl_share_vs_majors']:9.4f} {str(r['hl_dominant']):>5s}")

    hlB = [r for r in rows if r["hl_dominant"] is True]
    biB = [r for r in rows if r["hl_dominant"] is False]

    def bucket_stats(rr, label):
        ics = np.array([r["ic"] for r in rr]); zs = np.array([r["z_vs_random"] for r in rr])
        n_eff_tot = int(sum(r["n_eff"] for r in rr))
        mean_ic = float(np.nanmean(ics)); se_ic = float(np.nanstd(ics, ddof=1) / np.sqrt(len(ics)))
        mean_z = float(np.nanmean(zs))
        print(f"  {label}: n_coins={len(rr)}, mean IC={mean_ic:+.4f} (coin-level SE={se_ic:.4f}), "
              f"mean z_vs_random={mean_z:+.2f}, total coin-hours={n_eff_tot:,}")
        return dict(label=label, n_coins=len(rr), mean_ic=mean_ic, se_ic=se_ic, mean_z_vs_random=mean_z,
                    n_eff_hours_total=n_eff_tot, coins=[r["coin"] for r in rr])

    print("\n=== bucket comparison (median split on hl_share_vs_binance, one a-priori split) ===")
    hl_stats = bucket_stats(hlB, "HL-dominant (>=median)")
    bi_stats = bucket_stats(biB, "Binance-dominant (<median)")
    diff = hl_stats["mean_ic"] - bi_stats["mean_ic"]
    se_diff = float(np.sqrt(hl_stats["se_ic"] ** 2 + bi_stats["se_ic"] ** 2))
    t_diff = diff / se_diff if se_diff > 0 else float("nan")

    def mannwhitney_p(a, b):                     # normal-approx two-sided Mann-Whitney U (no scipy in .venv)
        a, b = np.asarray(a, float), np.asarray(b, float)
        n1, n2 = len(a), len(b)
        allv = np.concatenate([a, b]); order = np.argsort(allv, kind="mergesort")
        ranks = np.empty(len(allv)); ranks[order] = np.arange(1, len(allv) + 1)
        # average ties
        uniq, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
        rsum = np.zeros(len(uniq)); np.add.at(rsum, inv, ranks)
        avgrank = (rsum / cnt)[inv]
        R1 = avgrank[:n1].sum()
        U1 = R1 - n1 * (n1 + 1) / 2.0
        mu = n1 * n2 / 2.0
        tie_term = np.sum(cnt ** 3 - cnt) / (12.0 * (n1 + n2) * (n1 + n2 - 1)) if (n1 + n2) > 1 else 0.0
        sigma = np.sqrt(n1 * n2 / 12.0 * ((n1 + n2 + 1) - tie_term * ((n1 + n2) / max(n1 * n2, 1))))
        if sigma == 0: return float("nan")
        z = (U1 - mu) / sigma
        from math import erf, sqrt
        p = 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))
        return float(p)

    mw_p = mannwhitney_p([r["ic"] for r in hlB], [r["ic"] for r in biB])
    print(f"\nDIFF (HL-dom minus Binance-dom) mean IC = {diff:+.4f}, SE(diff)={se_diff:.4f}, t={t_diff:+.2f}, "
          f"Mann-Whitney (normal-approx) p={mw_p:.3f} (n={len(hlB)} vs {len(biB)}, coin-level test, LOW power at N=45)")
    # spearman of coin-level IC vs continuous hl_share (secondary/robustness — not the headline split)
    rho_cont = float(A._spear(np.array([r["hl_share_vs_binance"] for r in rows]), np.array([r["ic"] for r in rows])))
    print(f"[robustness, secondary] Spearman(coin OOS-IC, hl_share_vs_binance) across the 45 alts = {rho_cont:+.4f}")

    # ================= BOOK: HL-weighted basket vs equal-weight-7 =================
    def possm(t, S):
        sm = np.array([np.nanmean(t[max(0, h - S + 1):h + 1]) if np.isfinite(t[max(0, h - S + 1):h + 1]).any()
                       else np.nan for h in range(N)])
        return np.where(np.isfinite(sm), np.sign(sm), 0.0)

    hsbp = float(np.mean(list(cfg.get("basket_half_spread_bp", {"x": 1.8}).values()))) / 2.0

    def book_of(pos, bkt_next):
        gross = pos * bkt_next; dpos = np.abs(np.diff(pos, prepend=0.0)); out = {"gross": gross}
        for name, fee in FEES.items():
            out[name] = gross - dpos * (hsbp + fee) / 1e4
        out["turnover"] = float(np.nanmean(dpos)); return out

    # aggregate OOS tilt over the 7 basket coins ONLY (drives the position; mirrors "which alts vote")
    basket_idx = [acoi[c] for c in basket]
    bt_num = np.nansum(np.where(np.isfinite(oos_tilt_c[:, basket_idx]), oos_tilt_c[:, basket_idx], np.nan), axis=1)
    bt_cnt = np.sum(np.isfinite(oos_tilt_c[:, basket_idx]), axis=1)
    basket_tilt = np.where(bt_cnt > 0, np.nanmean(oos_tilt_c[:, basket_idx], axis=1), np.nan)
    pos_eq = possm(basket_tilt, S_HEAD)
    tm = np.isfinite(basket_tilt)

    bk_eq = book_of(pos_eq, bkt_eq_next)
    bk_hlw = book_of(pos_eq, bkt_hlw_next)     # SAME position (from same tilt), only the TARGET basket return is HL-weighted

    print("\n=== book test: equal-weight-7 vs HL-dominance-weighted-7 (same OOS position, different target return) ===")
    for lbl, bk in [("equal-weight-7", bk_eq), ("HL-share-weighted-7", bk_hlw)]:
        g = _ann_sharpe(bk["gross"][tm])
        nets = {n: _ann_sharpe(bk[n][tm]) for n in FEES}
        print(f"  {lbl}: gross Sharpe {g:+.2f} | net maker {nets['maker']:+.2f} | net toptier {nets['toptier']:+.2f} "
              f"| net base {nets['base']:+.2f} | turnover/hr {bk['turnover']:.3f} | n_test_hours {int(tm.sum())}")

    # ---- day-block bootstrap CI on the SHARPE DIFFERENCE (hlw - eq), gross and net@toptier — is the
    # apparent improvement real or 7-asset noise? (CLAUDE.md: point estimate needs a CI, not just a single number)
    days_all = (hh // 86400000).astype(np.int64)
    idx_tm = np.nonzero(tm)[0]
    ud = np.unique(days_all[idx_tm])
    day_to_rows = {dday: idx_tm[days_all[idx_tm] == dday] for dday in ud}
    rngb = np.random.default_rng(SEED + 1)
    NBOOT = 1000
    diffs_gross, diffs_top = [], []
    for _ in range(NBOOT):
        pick = rngb.integers(0, len(ud), size=len(ud))
        sel = np.concatenate([day_to_rows[ud[p]] for p in pick])
        sg_eq = _ann_sharpe(bk_eq["gross"][sel]); sg_hl = _ann_sharpe(bk_hlw["gross"][sel])
        st_eq = _ann_sharpe(bk_eq["toptier"][sel]); st_hl = _ann_sharpe(bk_hlw["toptier"][sel])
        if np.isfinite(sg_eq) and np.isfinite(sg_hl): diffs_gross.append(sg_hl - sg_eq)
        if np.isfinite(st_eq) and np.isfinite(st_hl): diffs_top.append(st_hl - st_eq)
    dg = np.array(diffs_gross); dt = np.array(diffs_top)
    ci_g = np.percentile(dg, [2.5, 97.5]) if len(dg) > 10 else (np.nan, np.nan)
    ci_t = np.percentile(dt, [2.5, 97.5]) if len(dt) > 10 else (np.nan, np.nan)
    print(f"\n  [day-block bootstrap, N={NBOOT}] Sharpe DIFF (HL-weighted minus equal-weight):")
    print(f"    gross:      point {_ann_sharpe(bk_hlw['gross'][tm]) - _ann_sharpe(bk_eq['gross'][tm]):+.2f}  "
          f"95% CI [{ci_g[0]:+.2f}, {ci_g[1]:+.2f}]")
    print(f"    net toptier: point {_ann_sharpe(bk_hlw['toptier'][tm]) - _ann_sharpe(bk_eq['toptier'][tm]):+.2f}  "
          f"95% CI [{ci_t[0]:+.2f}, {ci_t[1]:+.2f}]")

    # ---- BH-FDR on the 43 finite per-coin z_vs_random (two-sided normal approx) — multiplicity check on the
    # standout individual coins (MON/PENGU/CC/ENA/TRUMP etc.) before treating any as a real per-coin edge.
    from math import erf, sqrt as msqrt
    zvals = [(r["coin"], r["z_vs_random"]) for r in rows if np.isfinite(r["z_vs_random"])]
    pvals = [(c, 2 * (1 - 0.5 * (1 + erf(abs(z) / msqrt(2))))) for c, z in zvals]
    pvals.sort(key=lambda x: x[1])
    M = len(pvals); Q = 0.10
    surviving = []
    for i, (c, p) in enumerate(pvals, start=1):
        if p <= (i / M) * Q: surviving.append((c, p))
    print(f"\n  [multiplicity] BH-FDR q={Q} over {M} per-coin z_vs_random tests: {len(surviving)} survive: {surviving}")

    # also: does per-coin position sizing help — position each basket coin on ITS OWN tilt (not the pooled one),
    # weighted by hl_share, vs equal weight (a second, clearly-labelled variant; avoid conflating with the headline)
    pos_c = np.array([possm(oos_tilt_c[:, acoi[c]], S_HEAD) for c in basket]).T   # [N,7]
    ret_c = R[:, [ci[c] for c in basket]]
    ret_c_next = np.vstack([ret_c[1:], np.full((1, len(basket)), np.nan)])
    gross_eqw_perCoin = np.nanmean(pos_c * ret_c_next, axis=1)
    w_hl = hl_w / np.nansum(hl_w)
    gross_hlw_perCoin = np.nansum(np.where(np.isfinite(pos_c * ret_c_next), pos_c * ret_c_next, 0) * w_hl[None, :], axis=1)
    tm2 = np.isfinite(gross_eqw_perCoin) & (np.abs(gross_eqw_perCoin) + np.abs(gross_hlw_perCoin) > 0)
    print(f"\n[secondary variant] per-coin-timed basket (each name sized on its OWN oos tilt, NOT neutralized, "
          f"raw returns — directional check only): eqw gross Sharpe {_ann_sharpe(gross_eqw_perCoin[tm2]):+.2f} | "
          f"hl-weighted gross Sharpe {_ann_sharpe(gross_hlw_perCoin[tm2]):+.2f}")

    import pyarrow as pa
    cols = {k: [r[k] for r in rows] for k in rows[0]}
    cols["hl_dominant"] = [bool(v) if v is not None else None for v in cols["hl_dominant"]]
    pq.write_table(pa.table(cols), OUT / "per_coin_ic.parquet")
    summary = dict(median_hl_share_vs_binance=med, bucket_hl=hl_stats, bucket_binance=bi_stats,
                   diff_mean_ic=diff, se_diff=se_diff, t_diff=t_diff, mannwhitney_p=mw_p,
                   spearman_ic_vs_hlshare_continuous=rho_cont,
                   book={"equal_weight_7": {"gross_sharpe": _ann_sharpe(bk_eq["gross"][tm]),
                                             **{f"net_{n}": _ann_sharpe(bk_eq[n][tm]) for n in FEES},
                                             "turnover": bk_eq["turnover"], "n_test_hours": int(tm.sum())},
                         "hl_weighted_7": {"gross_sharpe": _ann_sharpe(bk_hlw["gross"][tm]),
                                           **{f"net_{n}": _ann_sharpe(bk_hlw[n][tm]) for n in FEES},
                                           "turnover": bk_hlw["turnover"], "n_test_hours": int(tm.sum())}},
                   basket_hl_weights=dict(zip(basket, hl_w.tolist())),
                   test_months=TESTM, n_placebo=N_PLACEBO_OOS)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print(f"\nwrote {OUT}/per_coin_ic.parquet, {OUT}/summary.json")


if __name__ == "__main__":
    main()
