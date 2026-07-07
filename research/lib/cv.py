"""Walk-forward cross-validation over month blocks — the anti-leakage splitter.

Every study that ranks/selects on one period and evaluates on the next uses THIS, so the walk-forward
discipline (train strictly before test; no future data) is identical across studies. This is the exact
guard the earlier markout study lacked (whole-window eligibility leak).

Pure stdlib.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator, Sequence

# The tape's month universe (integer YYYYMM). Keep in sync with the ingested range.
MONTHS = [202508, 202509, 202510, 202511, 202512,
          202601, 202602, 202603, 202604, 202605, 202606]


@dataclass(frozen=True)
class Split:
    train: tuple[int, ...]     # month blocks used to fit / rank / select
    test: int                  # the single held-out next month
    index: int


def walkforward_splits(months: Sequence[int] = MONTHS, min_train: int = 1,
                       mode: str = "expanding", train_window: int | None = None
                       ) -> Iterator[Split]:
    """Yield (train_months, test_month) splits where train is STRICTLY before test.

    mode="expanding": train grows to include all months up to test-1 (needs `min_train`).
    mode="rolling":   train is the last `train_window` months before test (needs `train_window`).
    """
    m = list(months)
    if mode == "rolling":
        if not train_window:
            raise ValueError("rolling mode needs train_window")
        for i in range(train_window, len(m)):
            yield Split(tuple(m[i - train_window:i]), m[i], i - train_window)
    elif mode == "expanding":
        for i in range(min_train, len(m)):
            yield Split(tuple(m[:i]), m[i], i - min_train)
    else:
        raise ValueError(f"unknown mode {mode!r} (expanding|rolling)")


def as_of_cutoff_ms(month: int) -> int:
    """First instant of the NEXT month, 00:00:00.000Z, as epoch ms — the leakage cutoff for `month`.
    (Matches WALLET_FEATURES_SPEC P12: membership is close_ts ≤ cutoff.)
    """
    from datetime import datetime, timezone
    y, mo = divmod(month, 100)
    ny, nmo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return int(datetime(ny, nmo, 1, tzinfo=timezone.utc).timestamp() * 1000)
