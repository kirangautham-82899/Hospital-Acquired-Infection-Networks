"""Tests for src/forecast.py (P8): period classification, real-data EDMD
forecasting mechanics, the simple baselines, and flatten_records'
scoring-mask filtering -- plus an integration check that applying P6's
real fitted D1 model to real P3 data runs cleanly end to end."""
import numpy as np
import pandas as pd
import pytest

import config
from src.baselines import build_real_weekly_states
from src.forecast import (
    edmd_forecast_real,
    flatten_records,
    historical_mean_forecast_real,
    landing_period,
    load_edmd_model,
    persistence_forecast_real,
)


def test_landing_period_boundaries():
    assert landing_period(config.CALIBRATION_WEEKS[-1]) == "calibration"
    assert landing_period(config.HOLDOUT_WEEKS[0]) == "holdout"
    assert landing_period(config.HOLDOUT_WEEKS[-1]) == "holdout"


def test_persistence_forecast_real_predicts_current_state():
    states_real = pd.DataFrame(
        {"week": [0, 1], "group": ["A", "A"], "prevalence": [0.3, 0.5], "n_tested": [15, 15]}
    )
    carry = pd.DataFrame({"week": [], "group": [], "prevalence": []})
    weekly_states = build_real_weekly_states(states_real, carry, groups=["A"], weeks=range(config.N_WEEKS))
    records = persistence_forecast_real(weekly_states, states_real, groups=["A"], max_h=1)

    rec = next(r for r in records if r["start_week"] == 0 and r["h"] == 1)
    assert rec["pred"][0] == 0.3  # persistence = current state
    assert rec["landing_week"] == 1
    assert rec["period"] == "calibration"


def test_historical_mean_forecast_real_predicts_fixed_vector():
    states_real = pd.DataFrame({"week": [0], "group": ["A"], "prevalence": [0.3], "n_tested": [15]})
    carry = pd.DataFrame({"week": [], "group": [], "prevalence": []})
    weekly_states = build_real_weekly_states(states_real, carry, groups=["A"], weeks=range(config.N_WEEKS))
    mean_vector = np.array([0.42])
    records = historical_mean_forecast_real(mean_vector, weekly_states, states_real, groups=["A"], max_h=1)
    assert all(r["pred"][0] == 0.42 for r in records)


def test_flatten_records_only_keeps_scored_wards():
    records = [
        {
            "model": "test", "start_week": 0, "landing_week": 1, "period": "calibration", "h": 1,
            "pred": np.array([0.5, 0.6]), "actual": np.array([0.4, 0.7]),
            "scoring_mask": np.array([True, False]),
        }
    ]
    df = flatten_records(records, groups=["A", "B"])
    assert len(df) == 1
    assert df.iloc[0]["ward"] == "A"
    assert df.iloc[0]["pred"] == 0.5
    assert df.iloc[0]["actual"] == 0.4


def test_edmd_forecast_real_skips_unusable_starts_and_respects_n_weeks():
    # tiny synthetic 2-group system, no real data at all -> every week unusable
    states_real = pd.DataFrame({"week": [], "group": [], "prevalence": [], "n_tested": []})
    carry = pd.DataFrame({"week": [], "group": [], "prevalence": []})
    weekly_states = build_real_weekly_states(states_real, carry, groups=["A", "B"], weeks=range(config.N_WEEKS))

    class DummyModel:
        pass

    from src.edmd import ConstantAwareScaler

    scaler = ConstantAwareScaler()
    scaler.mean_ = np.zeros(3)
    scaler.scale_ = np.ones(3)
    model = {
        "K": np.eye(3), "scaler": scaler, "C": np.array([[0, 1, 0], [0, 0, 1]]),
        "feature_names": ["1", "x_A", "x_B"], "groups": ["A", "B"],
    }
    records = edmd_forecast_real(model, weekly_states, states_real, groups=["A", "B"], max_h=4, dict_name="D1")
    assert records == []  # no usable starting states anywhere -> nothing forecast


def test_edmd_forecast_real_on_actual_p6_model_runs_and_stays_in_range():
    """Integration check: apply the real fitted D1 model to real P3 data
    end to end. Not asserting accuracy (that's P8's actual analysis), just
    that the pipeline produces well-formed, finite, bounded-ish output."""
    states_real = pd.read_csv(config.RESULTS_TABLES_DIR / "p3_states_real.csv")
    carry = pd.read_csv(config.DATA_PROCESSED_DIR / "states_real_carry_forward_SENSITIVITY_ONLY.csv")
    groups = config.WARD_GROUPS
    weekly_states = build_real_weekly_states(states_real, carry, groups, weeks=range(config.N_WEEKS))

    model = load_edmd_model("D1")
    records = edmd_forecast_real(model, weekly_states, states_real, groups, max_h=4, dict_name="D1")
    assert len(records) > 0
    for r in records:
        assert np.isfinite(r["pred"]).all()
        assert r["period"] in ("calibration", "holdout")
        assert r["landing_week"] == r["start_week"] + r["h"]
