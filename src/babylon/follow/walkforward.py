"""Walk-forward evaluation of follow-wallet skill.

The prerequisite for copy-trading to work is **persistence**: wallets that look
skilled on a TRAIN window must stay skilled on a disjoint FOLLOW window. If skill
is just noise, the train-top-quintile is no better than random on the follow
window and copying is pointless. This module ranks on train, measures the same
wallets on follow, and reports whether train-skill predicts follow-skill — the
honest out-of-sample test (the CSV ranking, derived in-sample, is only a sanity
cross-check, never the selector).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from babylon.follow.skill import rank_wallets


@dataclass(frozen=True, slots=True)
class Persistence:
    n_wallets: int  # had enough positions in BOTH windows
    rank_corr: float  # Spearman(train median bps, follow median bps)
    top_follow_median: float  # follow-window median skill of the TRAIN top quintile
    rest_follow_median: float  # follow-window median skill of everyone else
    top_follow_positive_frac: float  # fraction of train-top-quintile with >0 follow skill
    csv_overlap: float | None  # |train-top ∩ csv-top| / |train-top|, if CSV given


def evaluate(
    fills_dir: Path,
    train: tuple[int, int],
    follow: tuple[int, int],
    *,
    min_positions: int = 20,
    csv_top: set[str] | None = None,
) -> Persistence:
    train_rank = rank_wallets(fills_dir, *train, min_positions=min_positions)
    follow_rank = rank_wallets(fills_dir, *follow, min_positions=min_positions)
    if train_rank.is_empty() or follow_rank.is_empty():
        return Persistence(0, 0.0, 0.0, 0.0, 0.0, None)

    j = train_rank.select(["wallet", "median_bps", "top_quintile"]).join(
        follow_rank.select(["wallet", "median_bps"]).rename({"median_bps": "follow_bps"}),
        on="wallet", how="inner",
    )
    if j.height < 5:
        return Persistence(j.height, 0.0, 0.0, 0.0, 0.0, None)

    tr = j["median_bps"].to_numpy()
    fo = j["follow_bps"].to_numpy()
    rank_corr = float(np.corrcoef(_rankdata(tr), _rankdata(fo))[0, 1])

    top = j.filter(pl.col("top_quintile"))
    rest = j.filter(~pl.col("top_quintile"))
    top_fo = top["follow_bps"].to_numpy()
    overlap = None
    if csv_top is not None:
        train_top_set = set(top["wallet"].to_list())
        overlap = len(train_top_set & csv_top) / max(1, len(train_top_set))
    return Persistence(
        n_wallets=j.height,
        rank_corr=rank_corr,
        top_follow_median=float(np.median(top_fo)) if top_fo.size else 0.0,
        rest_follow_median=float(np.median(rest["follow_bps"].to_numpy())) if rest.height else 0.0,
        top_follow_positive_frac=float(np.mean(top_fo > 0)) if top_fo.size else 0.0,
        csv_overlap=overlap,
    )


def _rankdata(a: np.ndarray) -> np.ndarray:
    order = a.argsort()
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(a.size, dtype=np.float64)
    return ranks


def csv_top_quintile(csv_path: Path) -> set[str]:
    df = pl.read_csv(csv_path)
    return set(df.filter(pl.col("top_quintile"))["w"].to_list())
