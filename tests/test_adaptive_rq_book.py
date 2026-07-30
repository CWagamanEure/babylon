from __future__ import annotations

import copy

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research.studies.copy_cohort import adaptive_rq_book as b
from research.studies.copy_cohort.adaptive_rq_filter import ARMS, PROFILE_ID


def valid_gate() -> dict[str, object]:
    return {
        "profile_id": PROFILE_ID,
        "architecture": b.ARCH.name,
        "architecture_sha256": b._file_sha256(b.ARCH),
        "code_sha256": b._code_sha256(
            b.Path(b.__file__).with_name("adaptive_rq_filter.py")
        ),
        "conditional_book_action": "RUN_DIRECTION_INDEPENDENT",
        "primary_resolution_capable": True,
        "score_files_sha256": {str(fold): "hash" for fold in b.FOLDS},
        "config": {
            "arms": list(ARMS),
            "contrasts": {key: list(value) for key, value in b.CONTRASTS.items()},
            "profile_id": PROFILE_ID,
            "primary": b.PRIMARY,
            "n_boot": b.N_BOOT,
            "care_bp_day": 5.0,
            "min_active_base": 200,
            "min_formation_pool": 30,
            "min_arm_coin": 30,
            "min_fold_coverage": 0.90,
        },
        "results": {b.PRIMARY: {"resolution_capable": True}},
    }


def test_factor_gate_accepts_only_exact_powered_lineage() -> None:
    report = valid_gate()
    b.validate_factor_gate(report)
    for key, value in (
        ("primary_resolution_capable", False),
        ("conditional_book_action", "STOP"),
        ("profile_id", "wrong"),
        ("architecture_sha256", "wrong"),
        ("code_sha256", "wrong"),
    ):
        bad = copy.deepcopy(report)
        bad[key] = value
        with pytest.raises(RuntimeError):
            b.validate_factor_gate(bad)


def test_roster_masks_ineligible_and_breaks_ties_by_wallet(tmp_path) -> None:
    wallets = np.array([f"w{i:02d}" for i in range(32)][::-1])
    scores = np.ones(32)
    eligible = np.ones(32, dtype=bool)
    eligible[wallets == "w00"] = False
    path = tmp_path / "scores.parquet"
    pq.write_table(
        pa.table(
            {
                "wallet": wallets,
                "score__EW60": scores,
                "eligible__EW60": eligible,
            }
        ),
        path,
    )
    roster = b.roster_from_score(path, "EW60")
    assert roster == [f"w{i:02d}" for i in range(1, 31)]


def test_shock_arms_are_only_blowup_and_all() -> None:
    assert b.SHOCK_ARMS == {"KF60_BLOWUP", "KF60_ALL"}
    assert not ({"EW60", "KF60_BASE", "KF60_R_VOL", "KF60_Q_SLOW"} & b.SHOCK_ARMS)


def test_frozen_book_rejects_bootstrap_override() -> None:
    with pytest.raises(RuntimeError, match="n_boot=10000"):
        b.run(n_boot=99)


def test_contrast_concentration_uses_wallet_mean_contributions() -> None:
    a = {
        "wallet": np.array(["w1", "w1", "w2"]),
        "net_bp": np.array([9.0, 3.0, 6.0]),
    }
    c = {
        "wallet": np.array(["w1", "w3"]),
        "net_bp": np.array([2.0, 4.0]),
    }
    result = {"delta_bp": float(a["net_bp"].mean() - c["net_bp"].mean())}
    b.add_contrast_concentration(result, a, c)
    concentration = result["contrast_concentration"]
    assert concentration["n_contributing_wallets"] == 3
    assert concentration["top5_wallet_abs_contribution_share"] == pytest.approx(1.0)
