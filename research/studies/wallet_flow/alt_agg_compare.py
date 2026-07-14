"""alt_agg_compare — is there a strictly better aggregator of the SAME informed cohort's alt fills than the
settled breadth tilt (#long-#short)/#active?  Reconstructs candidate aggregators from alt_flow (month-batched,
RAM-safe) using the IDENTICAL walk-forward cohort-selection + embargo as alt_timing_dashboard_data.py (so the
baseline reproduced here should match ic.json's H1 OOS IC=+0.0045, z_vs_random=+0.07), then evaluates:
  (a) wallet-QUALITY-weighted vote   (weight = wallet's own train-score rank within the voting group)
  (b) DISPERSION/agreement gate      (keep hour only if majority-agreement >= its fold median)
  (c) tilt ACCELERATION              (hour-over-hour change in raw tilt, vs level)
  (d) per-coin breadth, CROSS-SECTIONAL (coin,hour) IC vs one basket-level scalar IC
  (e) maker-vs-taker split of the cohort's own flow (crossed) as two separate signals
Each gets its own OOS informed IC + a placebo z from the SAME walk-forward random-cohort null used for the
settled signal (apples-to-apples with the z=0.07 baseline).

    .venv/bin/python -m research.studies.wallet_flow.alt_agg_compare
"""
from __future__ import annotations
import functools, warnings, json, time
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

Wb, MINOBS = 720, 240
N_PLACEBO_OOS = 60          # scalar (basket-level) variants — matches dashboard baseline exactly
N_PLACEBO_XS = 30           # cross-sectional variant — heavier per-draw cost, fewer draws (noted as caveat)
SEED = 20260711
MINH = 20
MIN_RECENT_H = 40
RECENT_MONTHS = (202605, 202606)
HOUR = 3600000
OUT = Path("data/derived/alt_timing/agg_compare")
COH = Path("data/derived/alt_timing/cohort.json")


def _spear(a, b): return A._spear(a, b)


def _prev(m):
    y, mo = divmod(m, 100); mo -= 1
    return (y - 1) * 100 + 12 if mo == 0 else y * 100 + mo


def _rand_mask(rng, npool, nsel):
    mm = np.zeros(npool, bool); mm[rng.choice(npool, min(nsel, npool), replace=False)] = True; return mm


def _ann_t(ic, n): return float(ic * np.sqrt(n)) if n > 0 else float("nan")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(COH.read_text())
    cohort = list(cfg["cohort"]); basket = list(cfg["basket"]); cohort_sha = cfg["cohort_sha"]
    print(f"cohort {cohort_sha}: {len(cohort)} wallets, basket {basket}")

    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_aggcmp'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False); coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins); A.build_cohort_tables(con, coins)
    hours, ci, N = panel["hours"], panel["ci"], panel["N"]; hmin = int(hours[0]); hh = hours.astype(np.int64)
    fr = panel["fr"]                                    # [N,C] per-coin H1-forward neutral residual (majors=NaN)
    _log(f"panel+cohort tables ready: {N} hours, {len(coins)} coins")

    # ---- hourly mid lattice -> BTC/ETH-neutral ALT INDEX (the IC target, matches dashboard's fwd_idx_h1) ----
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbe AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d = con.execute("SELECT coin,h,mid FROM hbe").fetchnumpy()
    ca = np.asarray(d["coin"], dtype=object); ha = d["h"].astype(np.int64); C = len(coins)
    Lp = np.full((N, C), np.nan); rr = ((ha - hmin) // 3600000).astype(int); cc = np.array([ci[str(x)] for x in ca])
    ok = (rr >= 0) & (rr < N); Lp[rr[ok], cc[ok]] = np.log(d["mid"].astype(float)[ok]); R = np.diff(Lp, axis=0, prepend=np.nan)
    btc, eth = R[:, ci["BTC"]], R[:, ci["ETH"]]; eth_o = eth - rolling_beta(eth, btc, Wb, MINOBS) * btc

    def neutral(cols):
        s = np.nanmean(R[:, [ci[c] for c in cols]], axis=1)
        s = s - rolling_beta(s, btc, Wb, MINOBS) * btc
        return s - rolling_beta(s, eth_o, Wb, MINOBS) * eth_o
    idx = neutral(alts); cs = np.where(np.isfinite(idx), idx, 0.0)
    fwd1 = np.array([cs[h + 1] if h < N - 1 else np.nan for h in range(N)])   # H1 fwd (matches dashboard fwH[1])
    _log("targets built")

    # ---- eligible pool (placebo universe) ----
    inlist = "('" + "','".join(alts) + "')"; rm = ",".join(str(m) for m in RECENT_MONTHS)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE elig AS SELECT wallet FROM alt_flow
        WHERE month IN ({rm}) AND coin IN {inlist}
        GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""")

    months = [int(r[0]) for r in con.execute("SELECT DISTINCT mth FROM awb ORDER BY mth").fetchall()]
    TESTM = months[4:]                                  # IDENTICAL fold set to the dashboard's honest OOS window
    print(f"OOS folds (same as dashboard): {TESTM}")
    NSEL_OOS = min(len(cohort), 1500)

    # accumulators — scalar (basket-level) series, one value per hour
    base_tilt = np.full(N, np.nan)                       # (baseline) breadth tilt, reproduced here for a parity check
    wq_tilt = np.full(N, np.nan)                          # (a) quality-weighted vote
    gated_tilt = np.full(N, np.nan)                       # (b) tilt, but NaN'd out on low-agreement hours
    agree = np.full(N, np.nan)                            # (b) agreement series itself
    maker_tilt = np.full(N, np.nan); taker_tilt = np.full(N, np.nan)   # (e)
    rnd_base = np.full((N_PLACEBO_OOS, N), np.nan)
    rnd_wq = np.full((N_PLACEBO_OOS, N), np.nan)
    rnd_gated = np.full((N_PLACEBO_OOS, N), np.nan)
    rnd_maker = np.full((N_PLACEBO_OOS, N), np.nan); rnd_taker = np.full((N_PLACEBO_OOS, N), np.nan)

    # cross-sectional (d) accumulators — lists of (coin_idx, hour_idx, breadth) rows, concatenated across folds
    xs_ci, xs_hi, xs_val = [], [], []
    xs_rnd = [[] for _ in range(N_PLACEBO_XS)]            # each entry: list of (coin_idx,hour_idx,breadth)

    # per-fold z bookkeeping (to compare mean-of-per-fold-z vs pooled-z statistics — resolves the WF_FOLDS gap)
    fold_report = []

    rng = np.random.default_rng(SEED)
    for m in TESTM:
        ms_cut = int(con.execute(f"SELECT min(h) FROM awb WHERE mth={m}").fetchone()[0])
        emb = ms_cut - HOUR
        fmask = np.isfinite(fwd1) & (hh < emb)
        con.register("fsrc", {"hms": hh[fmask].astype(np.int64), "fwd": fwd1[fmask].astype(float)})
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
            print(f"  fold {m}: SKIP (elig {len(wal_e)} < {NSEL_OOS})"); continue
        order = np.argsort(-sc_e); cohort_idx = order[:NSEL_OOS]
        cohort_m = set(wal_e[cohort_idx])
        # rank-percentile weight WITHIN the informed cohort (nonneg, sums to informative variation): highest
        # train-score wallet -> weight 1.0, lowest cohort member -> weight ~1/NSEL. Applied identically to any
        # same-size group we score this way (so the placebo draws get the SAME weighting recipe, not a free pass).
        con.register("elig_arr", {"wallet": wal_e.astype(object)})
        fr_q = con.execute(f"""SELECT wb.wallet, wb.coin, wb.h, sign(wb.flow) s FROM awb wb JOIN elig_arr e USING(wallet)
            WHERE wb.mth={m} AND wb.flow<>0 AND wb.coin NOT IN ('BTC','ETH')""").fetchnumpy()
        mt_q = con.execute(f"""SELECT wallet, coin, (bucket-bucket%3600000) h, crossed, sum(flow_signed) f
            FROM alt_flow WHERE month={m} AND coin IN {inlist} AND wallet IN (SELECT wallet FROM elig_arr)
            GROUP BY wallet, coin, h, crossed""").fetchnumpy()
        con.unregister("elig_arr")

        fw_ = np.asarray([str(x) for x in fr_q["wallet"]], dtype=object)
        fco = np.asarray([str(x) for x in fr_q["coin"]], dtype=object)
        fh = ((fr_q["h"].astype(np.int64) - hmin) // 3600000).astype(int); fs = fr_q["s"].astype(np.int64)
        uwm, wcm = np.unique(fw_, return_inverse=True)
        kk = (fh >= 0) & (fh < N); fh, fs, wcm, fco = fh[kk], fs[kk], wcm[kk], fco[kk]
        fcidx = np.array([ci[c] for c in fco])
        wal_e_idx = {w: i for i, w in enumerate(wal_e)}   # map to score_e for weighting
        score_by_uwm = np.array([sc_e[wal_e_idx[w]] if w in wal_e_idx else np.nan for w in uwm])

        def rankpct(mask):                                # nonneg weight per wallet-in-group, 1/n .. 1.0
            idxs = np.nonzero(mask)[0]; s = score_by_uwm[idxs]
            r = np.argsort(np.argsort(s)).astype(float) + 1.0
            w = np.full(len(mask), np.nan); w[idxs] = r / len(idxs); return w

        def basic_tilt(mask):
            sel = mask[wcm]
            npo = np.bincount(fh[sel & (fs > 0)], minlength=N).astype(float)
            nne = np.bincount(fh[sel & (fs < 0)], minlength=N).astype(float)
            den = npo + nne; return np.where(den > 0, (npo - nne) / den, np.nan), den

        def weighted_tilt(mask, wt):
            sel = mask[wcm]; w = wt[wcm][sel]; s = fs[sel]; h_ = fh[sel]
            wpos = np.bincount(h_, weights=np.where(s > 0, w, 0.0), minlength=N)
            wneg = np.bincount(h_, weights=np.where(s < 0, w, 0.0), minlength=N)
            wden = np.bincount(h_, weights=w, minlength=N)
            return np.where(wden > 0, (wpos - wneg) / wden, np.nan)

        def gate_by_agreement(t, den_arr, npo, nne):
            agr = np.where(den_arr > 0, np.maximum(npo, nne) / den_arr, np.nan)
            th = np.nanmedian(agr[np.isfinite(agr)]) if np.isfinite(agr).any() else np.nan
            g = np.where(np.isfinite(agr) & (agr >= th), t, np.nan)
            return g, agr

        def coin_breadth(mask):                          # per (coin,h) breadth for a wallet mask -> lists
            sel = mask[wcm]; h_ = fh[sel]; c_ = fcidx[sel]; s_ = fs[sel]
            key = h_.astype(np.int64) * C + c_.astype(np.int64)
            uk, inv = np.unique(key, return_inverse=True)
            npo = np.bincount(inv, weights=(s_ > 0).astype(float))
            nne = np.bincount(inv, weights=(s_ < 0).astype(float))
            den = npo + nne; br = np.where(den > 0, (npo - nne) / den, np.nan)
            ok_ = np.isfinite(br)
            return (uk[ok_] // C).astype(int), (uk[ok_] % C).astype(int), br[ok_]   # h_idx, c_idx, breadth

        # ---- maker/taker rows ----
        mw = np.asarray([str(x) for x in mt_q["wallet"]], dtype=object)
        mco = np.asarray([str(x) for x in mt_q["coin"]], dtype=object)
        mh = ((mt_q["h"].astype(np.int64) - hmin) // 3600000).astype(int)
        mcr = np.asarray(mt_q["crossed"], dtype=bool); mf = mt_q["f"].astype(float)
        mk_ = (mh >= 0) & (mh < N); mw, mco, mh, mcr, mf = mw[mk_], mco[mk_], mh[mk_], mcr[mk_], mf[mk_]
        uwm2, wcm2 = np.unique(mw, return_inverse=True)

        def mt_tilt(mask, want_crossed):
            sel = mask[wcm2] & (mcr == want_crossed) & (mf != 0)
            npo = np.bincount(mh[sel & (mf > 0)], minlength=N).astype(float)
            nne = np.bincount(mh[sel & (mf < 0)], minlength=N).astype(float)
            den = npo + nne; return np.where(den > 0, (npo - nne) / den, np.nan)

        # ---- informed cohort ----
        cm = np.array([w in cohort_m for w in uwm])
        bt, den_bt = basic_tilt(cm); npo_c = np.bincount(fh[cm[wcm] & (fs > 0)], minlength=N).astype(float)
        nne_c = np.bincount(fh[cm[wcm] & (fs < 0)], minlength=N).astype(float)
        wt = rankpct(cm); wq = weighted_tilt(cm, wt)
        gt, ag = gate_by_agreement(bt, den_bt, npo_c, nne_c)
        cm2 = np.array([w in cohort_m for w in uwm2])
        mk_t = mt_tilt(cm2, False); tk_t = mt_tilt(cm2, True)   # crossed=false -> maker, true -> taker
        h_i, c_i, br_i = coin_breadth(cm)

        mh_ = np.isfinite(bt)
        base_tilt[mh_] = bt[mh_]; wq_tilt[mh_] = wq[mh_]
        gmh = np.isfinite(gt); gated_tilt[gmh] = gt[gmh]; agree[mh_] = ag[mh_]
        mkmh = np.isfinite(mk_t); maker_tilt[mkmh] = mk_t[mkmh]
        tkmh = np.isfinite(tk_t); taker_tilt[tkmh] = tk_t[tkmh]
        xs_ci.append(c_i); xs_hi.append(h_i); xs_val.append(br_i)

        n_j = min(N_PLACEBO_OOS, max(1, len(wal_e) - 1))
        for j in range(N_PLACEBO_OOS):
            rmask_full = _rand_mask(rng, len(wal_e), NSEL_OOS)
            rmask = np.zeros(len(uwm), bool)
            wal_e_sel = set(wal_e[rmask_full])
            rmask = np.array([w in wal_e_sel for w in uwm])
            rbt, rden = basic_tilt(rmask); rbt_mh = np.isfinite(rbt); rnd_base[j, rbt_mh] = rbt[rbt_mh]
            rnpo = np.bincount(fh[rmask[wcm] & (fs > 0)], minlength=N).astype(float)
            rnne = np.bincount(fh[rmask[wcm] & (fs < 0)], minlength=N).astype(float)
            rwt = rankpct(rmask); rwq = weighted_tilt(rmask, rwt)
            rgt, _ = gate_by_agreement(rbt, rden, rnpo, rnne)
            rmh = np.isfinite(rwq); rnd_wq[j, rmh] = rwq[rmh]
            rgmh = np.isfinite(rgt); rnd_gated[j, rgmh] = rgt[rgmh]
            rmask2 = np.array([w in wal_e_sel for w in uwm2])
            rmk = mt_tilt(rmask2, False); rtk = mt_tilt(rmask2, True)
            rmkmh = np.isfinite(rmk); rnd_maker[j, rmkmh] = rmk[rmkmh]
            rtkmh = np.isfinite(rtk); rnd_taker[j, rtkmh] = rtk[rtkmh]
            if j < N_PLACEBO_XS:
                rh_, rc_, rbr_ = coin_breadth(rmask)
                xs_rnd[j].append(np.stack([rh_.astype(np.int64), rc_.astype(np.int64), rbr_]))

        # per-fold z (mean-of-per-fold-z statistic, matching the WF_FOLDS/alt_mt_recency reporting convention)
        fic = _spear(bt, fwd1)
        fdraws = np.array([_spear(basic_tilt(np.array([w in set(wal_e[_rand_mask(rng, len(wal_e), NSEL_OOS)]) for w in uwm]))[0], fwd1) for _ in range(20)])
        fz = (fic - np.nanmean(fdraws)) / np.nanstd(fdraws) if np.nanstd(fdraws) > 0 else float("nan")
        fold_report.append({"month": m, "n_elig": len(wal_e), "n_cohort_hrs": int(mh_.sum()), "ic": float(fic), "z": float(fz)})
        print(f"  fold {m}: elig {len(wal_e):,} cohort {len(cohort_m)} hrs {int(mh_.sum())}  fold-IC {fic:+.4f} fold-z {fz:+.2f}")

    # ================= pooled OOS metrics =================
    def pooled(sig, rnd, tgt=fwd1):
        m = np.isfinite(sig) & np.isfinite(tgt)
        n = int(m.sum())
        ic = _spear(sig, tgt)
        draws = np.array([_spear(rnd[j], tgt) for j in range(rnd.shape[0])])
        mu, sdv = float(np.nanmean(draws)), float(np.nanstd(draws))
        z = (ic - mu) / sdv if sdv > 0 else float("nan")
        return {"ic": float(ic), "n_eff": n, "placebo_mean": mu, "placebo_std": sdv,
                "z_vs_random": float(z), "t_vs_zero": _ann_t(ic, n)}

    results = {}
    results["baseline_breadth_tilt"] = pooled(base_tilt, rnd_base)
    results["a_quality_weighted_vote"] = pooled(wq_tilt, rnd_wq)
    results["b_agreement_gated_tilt"] = pooled(gated_tilt, rnd_gated)
    # (c) acceleration — hour-over-hour change in the BASELINE tilt level (own null: random-cohort tilt's own diff)
    accel = np.diff(base_tilt, prepend=np.nan)
    rnd_accel = np.diff(rnd_base, axis=1, prepend=np.nan)
    results["c_tilt_acceleration"] = pooled(accel, rnd_accel)
    results["e_maker_only_tilt"] = pooled(maker_tilt, rnd_maker)
    results["e_taker_only_tilt"] = pooled(taker_tilt, rnd_taker)

    # (d) cross-sectional per-coin breadth — pool (coin,hour) rows across all folds
    if xs_hi:
        H_ = np.concatenate(xs_hi); Ci_ = np.concatenate(xs_ci); V_ = np.concatenate(xs_val)
        tgt_xs = fr[H_, Ci_]
        okxs = np.isfinite(V_) & np.isfinite(tgt_xs)
        xs_ic = _spear(V_[okxs], tgt_xs[okxs]); n_xs = int(okxs.sum())
        xs_draws = []
        for j in range(N_PLACEBO_XS):
            if not xs_rnd[j]: continue
            parts = xs_rnd[j]
            RH = np.concatenate([p[0].astype(int) for p in parts]); RC = np.concatenate([p[1].astype(int) for p in parts])
            RV = np.concatenate([p[2] for p in parts])
            rt = fr[RH, RC]; rok = np.isfinite(RV) & np.isfinite(rt)
            if rok.sum() > 100: xs_draws.append(_spear(RV[rok], rt[rok]))
        xs_draws = np.array(xs_draws)
        mu, sdv = float(np.nanmean(xs_draws)), float(np.nanstd(xs_draws))
        z = (xs_ic - mu) / sdv if sdv > 0 else float("nan")
        results["d_cross_sectional_percoin_breadth"] = {"ic": float(xs_ic), "n_eff": n_xs, "placebo_mean": mu,
                                                          "placebo_std": sdv, "z_vs_random": float(z),
                                                          "t_vs_zero": _ann_t(xs_ic, n_xs),
                                                          "n_placebo_draws": len(xs_draws)}
    print("\n=================== POOLED OOS RESULTS (same 7-month walk-forward window as dashboard) ===================")
    for k, v in results.items():
        print(f"  {k:35s} IC {v['ic']:+.4f}  n_eff {v['n_eff']:6d}  z_vs_random {v['z_vs_random']:+.2f}  t_vs_zero {v['t_vs_zero']:+.2f}")

    print("\n=================== per-fold z (mean-of-fold-z statistic, baseline tilt only) ===================")
    for f in fold_report:
        print(f"  {f['month']}: IC {f['ic']:+.4f} z {f['z']:+.2f}  (elig {f['n_elig']}, hrs {f['n_cohort_hrs']})")
    zs = np.array([f["z"] for f in fold_report])
    print(f"  mean fold-z = {zs.mean():+.2f}  ({int((zs>0).sum())}/{len(zs)} positive folds)")
    print(f"  [4-fold subset matching WF_FOLDS test months 202603-202606]:")
    sub = [f for f in fold_report if f["month"] in (202603, 202604, 202605, 202606)]
    if sub:
        subz = np.array([f["z"] for f in sub])
        print(f"    per-fold z: " + " ".join(f"{f['z']:+.1f}" for f in sub) + f"  mean {subz.mean():+.2f}")

    out = {"results": results, "fold_report": fold_report, "test_months": TESTM,
           "n_placebo_scalar": N_PLACEBO_OOS, "n_placebo_xs": N_PLACEBO_XS, "seed": SEED}
    (OUT / "agg_compare.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote {OUT}/agg_compare.json")


if __name__ == "__main__":
    main()
