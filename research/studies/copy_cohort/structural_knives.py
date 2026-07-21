"""STRUCTURAL COMPOSITE — final descriptive knives before the freeze (burned folds).

LOFO feature knives, N-sweep, long-only stacking, drop-202512 sensitivity, eligibility gates.
Everything from the existing sweep caches. DESCRIPTIVE — output feeds STRUCTURAL_TOPN_PREREG.md;
after that doc freezes, no further burned-fold looks.

    python -m research.studies.copy_cohort.structural_knives
"""
from __future__ import annotations

import json

import duckdb
import numpy as np

from .tape_capday_filter import CACHE, DERIVED, RT_COST_BP, _np
from .tape_metric_sweep import FOLDS, SWEEP_V, _fwd_book

OUT = DERIVED / "structural_knives_report.json"
FEATS = {"dd": ("f_max_dd_usd", -1), "act": ("f_trades_per_day", 1),
         "turn": ("f_turnover", 1), "clip": ("f_med_entry_notl", 1)}
NS = (20, 30, 50, 75, 100)
BOT_MAX_FILLS_DAY = 1000.0


def _pct(v):
    ok = np.isfinite(v)
    r = np.full(v.size, np.nan)
    r[ok] = np.argsort(np.argsort(v[ok])) / max(ok.sum() - 1, 1)
    return r


def _load():
    data = {}
    for f in FOLDS:
        lc = duckdb.connect()
        d = lc.execute(f"SELECT * FROM read_parquet("
                       f"'{(CACHE / f'sweep_feat_{f}_{SWEEP_V}.parquet').as_posix()}')").fetchnumpy()
        e = lc.execute(f"""SELECT wallet, ts, dir_sign, mk_8h FROM read_parquet(
            '{(CACHE / f'sweep_ent_{f}_{SWEEP_V}.parquet').as_posix()}')
            WHERE notional >= 250 AND mk_8h IS NOT NULL""").fetchnumpy()
        lc.close()
        data[f] = ({k: (v.astype(str) if k == "wallet" else _np(v)) for k, v in d.items()
                    if k in {"wallet", "metric_cap", "f_max_dd_usd", "f_trades_per_day",
                             "f_turnover", "f_med_entry_notl"}},
                   {"wallet": e["wallet"].astype(str), "ts": _np(e["ts"]),
                    "dir": _np(e["dir_sign"]), "mk8": _np(e["mk_8h"])})
    return data


def _book(data, feats, n_top, long_only=False, skip_folds=(), gate=True):
    ent = {"mk8": [], "wallet": [], "ts": []}
    per_fold = {}
    for f in FOLDS:
        if f in skip_folds:
            continue
        d, e = data[f]
        w = d["wallet"]
        elig = np.isfinite(d["metric_cap"])
        if gate:
            elig &= (d["metric_cap"] > 0) & (d["f_trades_per_day"] < BOT_MAX_FILLS_DAY)
        comp = np.nanmean(np.column_stack(
            [_pct(np.where(elig, d[FEATS[k][0]] * FEATS[k][1], np.nan)) for k in feats]), axis=1)
        order = np.argsort(-np.where(np.isfinite(comp), comp, -np.inf))
        top = set(w[order[:n_top]])
        m = np.array([x in top for x in e["wallet"]])
        if long_only:
            m &= e["dir"] > 0
        if not m.any():
            continue
        ent["mk8"].append(e["mk8"][m])
        ent["wallet"].append(e["wallet"][m])
        ent["ts"].append(e["ts"][m])
        uw, inv = np.unique(e["wallet"][m], return_inverse=True)
        per_fold[str(f)] = round(float((np.bincount(inv, weights=e["mk8"][m])
                                        / np.bincount(inv)).mean()), 2)
    cat = {k: np.concatenate(v) for k, v in ent.items()}
    b = _fwd_book(cat, np.ones(cat["mk8"].size, bool)) or {}
    signs = [v for v in per_fold.values()]
    b["per_fold_we"] = per_fold
    b["folds_gt0"] = f"{sum(1 for v in signs if v > 0)}/{len(signs)}"
    return b


def run():
    data = _load()
    rep = {"stamp": "DESCRIPTIVE knives, burned folds — final looks before STRUCTURAL_TOPN freeze",
           "gates": f"metric_cap>0, fills/day<{BOT_MAX_FILLS_DAY:.0f}, nd>=15", "variants": {}}

    def add(name, **kw):
        b = _book(data, **kw)
        rep["variants"][name] = b
        print(f"{name:>34}: n={b.get('n_entries', 0):>6,} nw={b.get('n_wallets', 0):>4} "
              f"we={b.get('wallet_equal_bp', float('nan')):+7.2f} net={b.get('net_bp', float('nan')):+6.2f} "
              f"SR={None if b.get('sharpe') is None else round(b['sharpe'], 2)} "
              f"{b.get('folds_gt0')}", flush=True)

    add("full4_N30", feats=tuple(FEATS), n_top=30)
    add("full4_N30_nogate", feats=tuple(FEATS), n_top=30, gate=False)
    for k in FEATS:
        add(f"lofo_drop_{k}_N30", feats=tuple(x for x in FEATS if x != k), n_top=30)
    add("trio_dd_act_clip_N30", feats=("dd", "act", "clip"), n_top=30)
    for n in NS:
        add(f"full4_N{n}", feats=tuple(FEATS), n_top=n)
    add("full4_N30_LONGONLY", feats=tuple(FEATS), n_top=30, long_only=True)
    add("trio_dd_act_clip_N30_LONGONLY", feats=("dd", "act", "clip"), n_top=30, long_only=True)
    add("full4_N50_LONGONLY", feats=tuple(FEATS), n_top=50, long_only=True)
    add("full4_N30_ex202512", feats=tuple(FEATS), n_top=30, skip_folds=(202512,))

    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
