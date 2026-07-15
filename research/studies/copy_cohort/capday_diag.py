"""Step 1 — contribution diagnostics for the capday 8h q50 book (why does the CI include zero?).

Decides the fork the user posed: BROAD weakness (most wallets ~0 → selection signal must improve) vs
CONCENTRATED blowups (most wallets mildly +, a few destroy it → fragility filter worth pursuing).

Computes, on the SAME leakage-clean 8h q50 evaluable book as capday_book.py (PRIMARY cell):
  - per-wallet OOS 8h contribution (net_usd, net_bp, n, clip)
  - the wallet distribution (median vs mean, fraction net-positive)
  - leave-one-wallet-out and remove-worst-k portfolio net_bp
  - worst 1/5/10% wallet contributions; share of losses from the worst 5
  - loss clustering by coin, by rebalance month (fold), and crash-beta vs the field(coin,week) market proxy

    python -m research.studies.copy_cohort.capday_diag
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from .base import open_base
from . import capday_book as cb

HORIZON = "8h"
Q = 0.50
RT = cb.RT_COST_BP
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_diag_report.json"


def _book_entries():
    """Reconstruct the per-entry 8h q50 cohort book: wallet, coin, iso-week, fold, clip, net_bp, net_usd,
    plus the field(coin,week) mean 8h markout (a market/beta proxy for crash-beta)."""
    con = _connect()
    sel = cb._selection()
    ep = cb._pull_episodes(con, sorted(set().union(*sel.cohorts)))
    midx = cb._month_idx(np.asarray(ep["open_ts"], np.int64))
    index = cb._row_index(ep, midx)
    clips = cb._expanding_clips({"wallet": ep["wallet"], "coin": ep["coin"], "ts": ep["ts"], "notl": ep["notl"]})
    clip = clips[Q]
    rows = cb._rows_for_membership(index, sel.cohorts)
    sz = rows[np.isfinite(clip[rows])]
    mk = ep[cb.MK_COL[HORIZON]]
    f = sz[np.isfinite(mk[sz])]
    # field(coin, iso-week) mean 8h markout over ALL opening-taker in-test episodes = market/beta proxy
    g = open_base(con)
    fr = con.execute(f"""
      SELECT coin, strftime(make_timestamp(entry_bar_ts*1000),'%G%V') AS wk, avg(raw_markout_8h) AS fmk
      FROM read_parquet('{g}')
      WHERE crossed_open AND NOT opener_flagged AND NOT entry_after_close AND entry_lag_s<=90
            AND raw_markout_8h IS NOT NULL
      GROUP BY coin, wk""").fetchnumpy()
    field = {(c, w): v for c, w, v in zip(fr["coin"].astype(str), fr["wk"].astype(str), fr["fmk"])}
    import datetime
    wk = np.array([datetime.datetime.fromtimestamp(int(t) / 1000, datetime.UTC).strftime('%G%V')
                   for t in ep["ts"][f]])
    coin = ep["coin"][f].astype(str)
    wallet = ep["wallet"][f].astype(str)
    fold = midx[f]
    cl = clip[f].astype(float)
    net_bp = np.asarray(mk[f], float) - RT
    net_usd = cl * net_bp / 1e4
    fieldmk = np.array([field.get((coin[j], wk[j]), 0.0) for j in range(f.size)])
    return dict(wallet=wallet, coin=coin, wk=wk, fold=fold, clip=cl, net_bp=net_bp,
                net_usd=net_usd, field_bp=fieldmk)


def run():
    e = _book_entries()
    wallet, net_usd, net_bp, cl = e["wallet"], e["net_usd"], e["net_bp"], e["clip"]
    tot_usd = float(net_usd.sum()); tot_clip = float(cl.sum())
    book_bp = tot_usd / tot_clip * 1e4
    n = wallet.size

    # ---- per-wallet aggregation
    uw, inv = np.unique(wallet, return_inverse=True)
    w_usd = np.bincount(inv, weights=net_usd)
    w_clip = np.bincount(inv, weights=cl)
    w_n = np.bincount(inv)
    w_bp = np.where(w_clip > 0, w_usd / np.maximum(w_clip, 1e-30) * 1e4, 0.0)  # $-wtd per-wallet net bp
    order = np.argsort(w_usd)                                                   # ascending: worst first
    G = uw.size

    # ---- distribution: broad vs concentrated
    frac_pos = float((w_usd > 0).mean())
    median_w_bp = float(np.median(w_bp)); mean_w_bp = float(w_bp.mean())
    # equal-wallet mean (unweighted per-wallet net_bp) already known ~ -7; report both

    # ---- remove-worst-k: does dropping a few wallets transform the book?
    def book_excl(mask):
        c = cl[mask].sum()
        return (net_usd[mask].sum() / c * 1e4) if c > 0 else None
    worst_wallets = uw[order]
    remove_k = {}
    for k in (0, 1, 2, 3, 5, 10):
        drop = set(worst_wallets[:k].tolist())
        m = ~np.isin(wallet, list(drop)) if k else np.ones(n, bool)
        remove_k[k] = {"book_net_bp": book_excl(m), "dropped_wallets": worst_wallets[:k].tolist(),
                       "dropped_net_usd": float(w_usd[order][:k].sum())}

    # ---- worst 1/5/10% of wallets by net_usd; share of losses from worst 5
    def pct_share(p):
        kk = max(1, int(np.ceil(G * p)))
        return {"n_wallets": kk, "net_usd": float(w_usd[order][:kk].sum()),
                "share_of_total_book_usd": float(w_usd[order][:kk].sum() / tot_usd) if tot_usd else None}
    gross_loss = float(-w_usd[w_usd < 0].sum())
    worst5_loss = float(-w_usd[order][:5][w_usd[order][:5] < 0].sum())
    losers = int((w_usd < 0).sum())

    # ---- loss clustering by coin and by fold (ENTRY-level: denom = entry-level gross loss, so shares sum to 1)
    entry_gross_loss = float(-net_usd[net_usd < 0].sum())
    def cluster(keyarr):
        uk, ki = np.unique(keyarr, return_inverse=True)
        k_usd = np.bincount(ki, weights=net_usd)
        out = {}
        for j, k in enumerate(uk):
            neg = float(-net_usd[(ki == j) & (net_usd < 0)].sum())
            out[str(k)] = {"net_usd": float(k_usd[j]), "loss_usd": neg,
                           "share_of_entry_gross_loss": float(neg / entry_gross_loss) if entry_gross_loss else None,
                           "n": int((ki == j).sum())}
        return out
    by_coin = cluster(e["coin"]); by_fold = cluster(e["fold"].astype(str))

    # ---- crash beta: does the book lose when the field(coin,week) is down? (entry-level regression)
    fb = e["field_bp"]
    if np.std(fb) > 0:
        beta = float(np.polyfit(fb, net_bp, 1)[0])           # net_bp ~ a + beta*field_bp
        corr = float(np.corrcoef(fb, net_bp)[0, 1])
        # book net_bp in field-down vs field-up entries
        dn = net_bp[fb < 0]; up = net_bp[fb >= 0]
        crash = {"entry_beta_to_field": beta, "entry_corr_to_field": corr,
                 "mean_net_bp_field_down": float(dn.mean()) if dn.size else None,
                 "mean_net_bp_field_up": float(up.mean()) if up.size else None,
                 "n_field_down": int(dn.size), "n_field_up": int(up.size)}
    else:
        crash = {}

    # ---- verdict heuristic: CONCENTRATED iff the typical wallet is + but a few carry most of the loss AND
    # removing the worst handful materially lifts the book (NECESSARY for fragility filtering to be worth it —
    # sufficiency requires the blowups to be EX-ANTE predictable, which Step 3 must test OOS).
    lift5 = (remove_k[5]["book_net_bp"] - book_bp) if remove_k[5]["book_net_bp"] is not None else 0.0
    concentrated = (median_w_bp > 2.0 and (worst5_loss / gross_loss if gross_loss else 0) > 0.5 and lift5 > 10)
    thin_median = median_w_bp < 5.0                       # per-wallet edge is weak even if concentrated
    verdict = ("CONCENTRATED_BLOWUPS" if concentrated else
               "BROAD_WEAKNESS" if abs(median_w_bp) < 2.0 else "MIXED") \
        + (" + THIN_MEDIAN_EDGE (median wallet only +%.1fbp → selection rework ALSO warranted)" % median_w_bp
           if thin_median else "")

    rep = {
        "horizon": HORIZON, "q": Q, "n_entries": int(n), "n_wallets": int(G),
        "book_dollar_wtd_net_bp": book_bp, "book_net_usd": tot_usd,
        "distribution": {"frac_wallets_net_positive": frac_pos,
                         "median_wallet_net_bp": median_w_bp, "mean_wallet_net_bp": mean_w_bp,
                         "wallet_net_bp_q10_q25_q75_q90": [float(np.quantile(w_bp, x)) for x in (.1, .25, .75, .9)],
                         "n_losers": losers, "n_winners": int((w_usd > 0).sum())},
        "remove_worst_k_book_net_bp": {str(k): remove_k[k]["book_net_bp"] for k in remove_k},
        "worst_pct": {"1pct": pct_share(0.01), "5pct": pct_share(0.05), "10pct": pct_share(0.10)},
        "worst5_share_of_gross_loss": float(worst5_loss / gross_loss) if gross_loss else None,
        "gross_loss_usd": gross_loss,
        "loss_cluster_by_coin": by_coin, "loss_cluster_by_fold": by_fold,
        "crash_beta": crash,
        "VERDICT": verdict,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))

    print(f"\n=== capday 8h q50 book contribution diagnostics (n={n} entries, {G} wallets) ===")
    print(f"book $-wtd net = {book_bp:+.2f}bp   net$ = {tot_usd:+,.0f}")
    print(f"\nDISTRIBUTION (broad-vs-concentrated):")
    print(f"  frac wallets net-positive : {frac_pos:.2f}   ({rep['distribution']['n_winners']} win / {losers} lose)")
    print(f"  wallet net_bp  median {median_w_bp:+.1f}   mean {mean_w_bp:+.1f}")
    print(f"  wallet net_bp  q10/q25/q75/q90: {[round(x,1) for x in rep['distribution']['wallet_net_bp_q10_q25_q75_q90']]}")
    print(f"\nREMOVE-WORST-k book net bp: " + "  ".join(f"k={k}:{(remove_k[k]['book_net_bp'] or 0):+.1f}" for k in remove_k))
    print(f"worst-5 wallets = {rep['worst5_share_of_gross_loss']:.2f} of gross loss; "
          f"worst-10% wallets net$ {rep['worst_pct']['10pct']['net_usd']:+,.0f} "
          f"({rep['worst_pct']['10pct']['share_of_total_book_usd']})")
    print(f"\nLOSS CLUSTER by coin: " + "  ".join(f"{k}:{v['share_of_entry_gross_loss'] and round(v['share_of_entry_gross_loss'],2)}" for k,v in by_coin.items()))
    print(f"LOSS CLUSTER by fold: " + "  ".join(f"{k}:{v['share_of_entry_gross_loss'] and round(v['share_of_entry_gross_loss'],2)}" for k,v in by_fold.items()))
    if crash:
        print(f"\nCRASH BETA to field: beta {crash['entry_beta_to_field']:+.2f} corr {crash['entry_corr_to_field']:+.2f}  "
              f"net_bp field-down {crash['mean_net_bp_field_down']:+.1f} (n{crash['n_field_down']}) vs up {crash['mean_net_bp_field_up']:+.1f} (n{crash['n_field_up']})")
    print(f"\n>>> VERDICT: {verdict}")
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
