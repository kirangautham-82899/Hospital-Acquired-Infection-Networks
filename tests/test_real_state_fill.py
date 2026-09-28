"""Tests for src/real_state_fill.py (P5, applied starting P8): building a
complete state vector for a real week by preferring states_real, falling
back to carry-forward, and the two distinct masks (observed vs scoring-
eligible)."""
import numpy as np
import pandas as pd

import config
from src.real_state_fill import (
    fill_state_vector,
    observed_for_scoring_mask,
    state_is_usable_as_starting_point,
)


def test_fill_prefers_real_over_carry_forward():
    states_real = pd.DataFrame({"week": [0], "group": ["A"], "prevalence": [0.3], "n_tested": [20]})
    carry = pd.DataFrame({"week": [0], "group": ["A"], "prevalence": [0.9]})
    state, observed = fill_state_vector(0, states_real, carry, groups=["A"])
    assert state[0] == 0.3
    assert observed[0] == True


def test_fill_falls_back_to_carry_forward_when_real_missing():
    states_real = pd.DataFrame({"week": [], "group": [], "prevalence": [], "n_tested": []})
    carry = pd.DataFrame({"week": [0], "group": ["A"], "prevalence": [0.7]})
    state, observed = fill_state_vector(0, states_real, carry, groups=["A"])
    assert state[0] == 0.7
    assert observed[0] == False  # filled, not genuinely observed


def test_fill_uses_real_even_if_low_n_flagged():
    """A low_n real value is still a genuine test-derived estimate -- it
    should still be preferred over carry-forward for building the state
    vector (low_n only matters for the SEPARATE scoring mask)."""
    states_real = pd.DataFrame({"week": [0], "group": ["A"], "prevalence": [0.5], "n_tested": [2]})
    carry = pd.DataFrame({"week": [0], "group": ["A"], "prevalence": [0.1]})
    state, observed = fill_state_vector(0, states_real, carry, groups=["A"])
    assert state[0] == 0.5
    assert observed[0] == True


def test_fill_leaves_nan_when_neither_available():
    states_real = pd.DataFrame({"week": [], "group": [], "prevalence": [], "n_tested": []})
    carry = pd.DataFrame({"week": [], "group": [], "prevalence": []})
    state, observed = fill_state_vector(5, states_real, carry, groups=["A", "B"])
    assert np.isnan(state).all()
    assert not observed.any()
    assert not state_is_usable_as_starting_point(state)


def test_state_usable_only_when_fully_filled():
    assert state_is_usable_as_starting_point(np.array([0.1, 0.2, 0.3]))
    assert not state_is_usable_as_starting_point(np.array([0.1, np.nan, 0.3]))


def test_scoring_mask_respects_min_n_tested_threshold():
    states_real = pd.DataFrame(
        {"week": [0, 0], "group": ["A", "B"], "prevalence": [0.3, 0.4], "n_tested": [15, 3]}
    )
    mask = observed_for_scoring_mask(0, states_real, groups=["A", "B", "C"], min_n_tested=10)
    assert mask.tolist() == [True, False, False]  # A: n=15 ok, B: n=3 too low, C: missing entirely


def test_scoring_mask_is_stricter_than_fill_observed_mask():
    """A low_n real value counts as 'observed' for filling a starting
    state but NOT for scoring -- the two masks must disagree in exactly
    this case."""
    states_real = pd.DataFrame({"week": [0], "group": ["A"], "prevalence": [0.5], "n_tested": [2]})
    carry = pd.DataFrame({"week": [], "group": [], "prevalence": []})
    _, observed = fill_state_vector(0, states_real, carry, groups=["A"])
    scoring = observed_for_scoring_mask(0, states_real, groups=["A"], min_n_tested=10)
    assert observed[0] == True
    assert scoring[0] == False


def test_integration_on_real_p3_zero_tested_group_week():
    """Pick a real (week, group) that P3 flagged as having ZERO tested
    people (absent from states_real entirely) and confirm it either gets
    filled from carry-forward or correctly stays NaN."""
    states_real = pd.read_csv(config.RESULTS_TABLES_DIR / "p3_states_real.csv")
    carry = pd.read_csv(config.DATA_PROCESSED_DIR / "states_real_carry_forward_SENSITIVITY_ONLY.csv")
    zero_tested = pd.read_csv(config.RESULTS_TABLES_DIR / "p3_zero_tested_group_weeks.csv")
    assert len(zero_tested) > 0

    week, group = zero_tested.iloc[0]["week"], zero_tested.iloc[0]["group"]
    state, observed = fill_state_vector(int(week), states_real, carry, groups=config.WARD_GROUPS)
    idx = config.WARD_GROUPS.index(group)
    assert observed[idx] == False  # by construction this cell has zero real tests
    # either carry-forward filled it (not NaN) or it's genuinely unfillable (NaN) -- both are valid,
    # just confirm the function didn't silently invent an "observed" real value
