from __future__ import annotations

import json

import numpy as np
import pytest

from research.studies.copy_cohort.efron_bot500_visuals import (
    SPEC,
    WATERMARK,
    empirical_survival_abs,
    month_ms,
    qq_points,
    sha256,
    validate_existing_generation,
    wallet_contributions,
)


def test_month_bounds_are_exact_utc_month() -> None:
    start, end = month_ms(202512)
    assert end > start
    assert (end - start) // 86_400_000 == 31


def test_empirical_survival_is_monotone() -> None:
    x, survival = empirical_survival_abs(np.array([-3.0, 1.0, 2.0, 4.0]))
    assert np.all(np.diff(x) >= 0)
    assert np.all(np.diff(survival) <= 0)
    assert survival[0] == 1.0


def test_qq_points_are_sorted_and_standardized() -> None:
    q, y = qq_points(np.arange(1.0, 101.0))
    assert np.all(np.diff(q) > 0)
    assert np.all(np.diff(y) > 0)
    assert abs(y.mean()) < 1e-12
    assert np.isclose(y.std(ddof=1), 1.0)


def test_wallet_contributions_sum_to_arm_mean_delta() -> None:
    a = {
        "wallet": np.array(["a", "a", "b"]),
        "net_bp": np.array([10.0, 20.0, -5.0]),
    }
    b = {
        "wallet": np.array(["a", "c"]),
        "net_bp": np.array([4.0, 8.0]),
    }
    result = wallet_contributions(a, b)
    expected = a["net_bp"].mean() - b["net_bp"].mean()
    assert np.isclose(result["delta"].sum(), expected)


def test_existing_generation_requires_every_bound_output(tmp_path) -> None:
    digest = "a" * 64
    names = [
        "01_executive_overview.png",
        "02_returns_and_tails.png",
        "03_formation_cohort.png",
        "04_efron_assumptions.png",
        "05_roster_dynamics.png",
        "06_capacity_missingness.png",
        "07_wallet_dependence.png",
        "diagnostic_atlas.pdf",
        "index.html",
    ]
    for name in names:
        payload = (
            ("data:image/png;base64," * 7 + digest + WATERMARK).encode()
            if name == "index.html"
            else f"bytes-{name}".encode()
        )
        (tmp_path / name).write_bytes(payload)
    outputs = [
        {"path": name, "size": (tmp_path / name).stat().st_size, "sha256": sha256(tmp_path / name)}
        for name in names
    ]
    manifest = {
        "status": "BURNED_POSTHOC_VISUAL_DIAGNOSTIC_ATLAS",
        "generation_digest": digest,
        "watermark": WATERMARK,
        "consensus": "excluded",
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
        "visual_spec_sha256": sha256(SPEC),
        "visual_code_sha256": sha256(SPEC.with_name("efron_bot500_visuals.py")),
        "inputs": [{"path": "bound", "size": 1, "sha256": "b" * 64}],
        "outputs": outputs,
    }
    (tmp_path / "visual_manifest.json").write_text(json.dumps(manifest))
    validate_existing_generation(tmp_path, digest, manifest["inputs"])

    (tmp_path / "03_formation_cohort.png").write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="output integrity"):
        validate_existing_generation(tmp_path, digest, manifest["inputs"])

    (tmp_path / "03_formation_cohort.png").write_bytes(b"bytes-03_formation_cohort.png")
    (tmp_path / "stale_unbound_page.png").write_bytes(b"stale")
    with pytest.raises(RuntimeError, match="unbound files"):
        validate_existing_generation(tmp_path, digest, manifest["inputs"])
