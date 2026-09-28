"""Tests for src/build_p8.py's forecast_baseline_iteratively -- this is
the function whose argument order originally didn't match
predict_network_exposure/predict_ward_sis's actual signatures (coef_args
were spliced in after `current` instead of before `W`), silently putting
a 6-element state array into a scalar 'pred' slot. Caught only once this
test exercised the wiring end to end, not just the underlying predict_*
functions in isolation."""
import numpy as np
import pandas as pd
import pytest

import config
from src.baselines import build_real_weekly_states, predict_network_exposure, predict_ward_sis
from src.build_p8 import forecast_baseline_iteratively


def test_forecast_baseline_iteratively_passes_arguments_in_correct_order():
    groups = ["A", "B"]
    W = np.array([[0.8, 0.2], [0.3, 0.7]])
    states_real = pd.DataFrame(
        {"week": [0, 0], "group": ["A", "B"], "prevalence": [0.3, 0.4], "n_tested": [15, 15]}
    )
    carry = pd.DataFrame({"week": [], "group": [], "prevalence": []})
    weekly_states = build_real_weekly_states(states_real, carry, groups, weeks=range(config.N_WEEKS))

    coef = np.array([0.05, 0.5, 0.2])
    records = forecast_baseline_iteratively(
        predict_network_exposure, weekly_states, states_real, groups, max_h=1,
        model_name="network_exposure", coef_args=(coef,), W=W,
    )
    assert len(records) == 1
    rec = records[0]
    # pred must be a per-ward vector of length len(groups), matching what
    # predict_network_exposure(coef, x, W) actually returns -- NOT some
    # other shape from a misrouted argument.
    assert rec["pred"].shape == (2,)

    x0 = np.array([0.3, 0.4])
    expected = predict_network_exposure(coef, x0, W)
    assert np.allclose(rec["pred"], expected)


def test_forecast_baseline_iteratively_ward_sis_argument_order():
    groups = ["A", "B"]
    W = np.array([[0.8, 0.2], [0.3, 0.7]])
    states_real = pd.DataFrame(
        {"week": [0, 0], "group": ["A", "B"], "prevalence": [0.3, 0.4], "n_tested": [15, 15]}
    )
    carry = pd.DataFrame({"week": [], "group": [], "prevalence": []})
    weekly_states = build_real_weekly_states(states_real, carry, groups, weeks=range(config.N_WEEKS))

    beta, gamma = 0.4, 0.1
    records = forecast_baseline_iteratively(
        predict_ward_sis, weekly_states, states_real, groups, max_h=1,
        model_name="ward_sis", coef_args=(beta, gamma), W=W,
    )
    assert len(records) == 1
    x0 = np.array([0.3, 0.4])
    expected = predict_ward_sis(beta, gamma, x0, W)
    assert np.allclose(records[0]["pred"], expected)
