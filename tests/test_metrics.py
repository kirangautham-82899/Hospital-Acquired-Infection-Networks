"""Tests for src/metrics.py: RMSE/MAE aggregation (overall + per-ward)
from a long-format forecast DataFrame, and the skill-vs-persistence
score."""
import numpy as np
import pandas as pd

from src.metrics import add_skill_vs_persistence, compute_metrics_from_long


def _toy_df():
    return pd.DataFrame(
        [
            {"model": "modelA", "period": "holdout", "h": 1, "ward": "X", "pred": 0.5, "actual": 0.6},
            {"model": "modelA", "period": "holdout", "h": 1, "ward": "Y", "pred": 0.2, "actual": 0.2},
            {"model": "persistence", "period": "holdout", "h": 1, "ward": "X", "pred": 0.4, "actual": 0.6},
            {"model": "persistence", "period": "holdout", "h": 1, "ward": "Y", "pred": 0.3, "actual": 0.2},
        ]
    )


def test_compute_metrics_overall_matches_hand_calculation():
    df = _toy_df()
    metrics = compute_metrics_from_long(df, group_by=["period", "h"])
    row = metrics[(metrics["model"] == "modelA") & (metrics["ward"] == "overall")].iloc[0]
    pred, actual = np.array([0.5, 0.2]), np.array([0.6, 0.2])
    expected_rmse = np.sqrt(np.mean((pred - actual) ** 2))
    assert abs(row["rmse"] - expected_rmse) < 1e-12
    assert row["n"] == 2


def test_compute_metrics_per_ward_rows_present():
    df = _toy_df()
    metrics = compute_metrics_from_long(df, group_by=["period", "h"])
    wards = set(metrics[metrics["model"] == "modelA"]["ward"])
    assert wards == {"overall", "X", "Y"}
    x_row = metrics[(metrics["model"] == "modelA") & (metrics["ward"] == "X")].iloc[0]
    assert abs(x_row["rmse"] - 0.1) < 1e-12


def test_compute_metrics_clipped_matches_unclipped_when_in_range():
    df = _toy_df()
    metrics = compute_metrics_from_long(df, group_by=["period", "h"])
    assert np.allclose(metrics["rmse"], metrics["rmse_clipped"])  # all values already in [0,1]


def test_skill_vs_persistence_formula():
    df = _toy_df()
    metrics = compute_metrics_from_long(df, group_by=["period", "h"])
    scored = add_skill_vs_persistence(metrics, group_by=["period", "h"])
    a_overall = scored[(scored["model"] == "modelA") & (scored["ward"] == "overall")].iloc[0]
    p_overall = scored[(scored["model"] == "persistence") & (scored["ward"] == "overall")].iloc[0]
    expected = 1.0 - a_overall["rmse"] / p_overall["rmse"]
    assert abs(a_overall["skill_vs_persistence"] - expected) < 1e-12
    # persistence vs itself should have skill exactly 0
    assert abs(p_overall["skill_vs_persistence"] - 0.0) < 1e-12


def test_skill_vs_persistence_nan_when_baseline_missing():
    df = pd.DataFrame(
        [{"model": "modelA", "period": "holdout", "h": 1, "ward": "X", "pred": 0.5, "actual": 0.6}]
    )
    metrics = compute_metrics_from_long(df, group_by=["period", "h"])
    scored = add_skill_vs_persistence(metrics, group_by=["period", "h"])
    assert scored["skill_vs_persistence"].isna().all()
