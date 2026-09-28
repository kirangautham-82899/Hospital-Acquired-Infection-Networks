"""Tests for src/baselines.py (P8): real-week state building, training
pair construction (usability + scoring-mask restrictions), and exact
parameter recovery for both new baselines on noiseless synthetic data."""
import numpy as np
import pandas as pd
import pytest

from src.baselines import (
    build_real_weekly_states,
    build_training_pairs,
    fit_network_exposure_model,
    fit_ward_sis_model,
    predict_network_exposure,
    predict_ward_sis,
)


def test_build_real_weekly_states_prefers_real_over_carry_forward():
    states_real = pd.DataFrame({"week": [0], "group": ["A"], "prevalence": [0.4], "n_tested": [12]})
    carry = pd.DataFrame({"week": [0, 1], "group": ["A", "A"], "prevalence": [0.9, 0.5]})
    out = build_real_weekly_states(states_real, carry, groups=["A"], weeks=[0, 1])
    assert out[0][0][0] == 0.4  # real preferred
    assert out[1][0][0] == 0.5  # carry-forward fallback


def test_build_training_pairs_skips_unusable_start_and_unobserved_target():
    states_real = pd.DataFrame(
        {"week": [1], "group": ["A"], "prevalence": [0.3], "n_tested": [15]}
    )  # only week 1 (the target) has an observed value; week 0 unobserved anywhere
    carry = pd.DataFrame({"week": [], "group": [], "prevalence": []})
    weekly_states = build_real_weekly_states(states_real, carry, groups=["A"], weeks=[0, 1, 2])
    # week 0's state is unusable (NaN, nothing in real or carry-forward) -> pair (0,1) must be skipped
    pairs = build_training_pairs(weekly_states, states_real, groups=["A"], weeks=[0, 1])
    assert pairs == []


def test_build_training_pairs_respects_min_n_tested():
    states_real = pd.DataFrame(
        {"week": [0, 1], "group": ["A", "A"], "prevalence": [0.2, 0.5], "n_tested": [15, 3]}
    )
    carry = pd.DataFrame({"week": [], "group": [], "prevalence": []})
    weekly_states = build_real_weekly_states(states_real, carry, groups=["A"], weeks=[0, 1])
    pairs = build_training_pairs(weekly_states, states_real, groups=["A"], weeks=[0], min_n_tested=10)
    assert pairs == []  # week 1's n_tested=3 < 10, target not observed enough


def test_build_training_pairs_basic_correctness():
    states_real = pd.DataFrame(
        {"week": [0, 1], "group": ["A", "A"], "prevalence": [0.2, 0.5], "n_tested": [15, 20]}
    )
    carry = pd.DataFrame({"week": [], "group": [], "prevalence": []})
    weekly_states = build_real_weekly_states(states_real, carry, groups=["A"], weeks=[0, 1])
    pairs = build_training_pairs(weekly_states, states_real, groups=["A"], weeks=[0], min_n_tested=10)
    assert len(pairs) == 1
    assert pairs[0]["ward_idx"] == 0
    assert pairs[0]["x"][0] == 0.2
    assert pairs[0]["x_next"] == 0.5


def test_network_exposure_exact_recovery_noiseless():
    rng = np.random.default_rng(0)
    n = 4
    W = rng.uniform(0.05, 0.3, size=(n, n))
    W = W / W.sum(axis=1, keepdims=True)
    a_true, b_true, c_true = 0.02, 0.6, 0.25

    pairs = []
    for _ in range(200):
        x = rng.uniform(0, 1, size=n)
        for i in range(n):
            wx_i = W[i] @ x
            x_next_i = a_true + b_true * x[i] + c_true * wx_i
            pairs.append({"x": x, "ward_idx": i, "x_next": x_next_i})

    coef = fit_network_exposure_model(pairs, W, lam=1e-8)
    assert np.allclose(coef, [a_true, b_true, c_true], atol=1e-4)

    x_test = rng.uniform(0, 1, size=n)
    pred = predict_network_exposure(coef, x_test, W)
    manual = np.array([a_true + b_true * x_test[i] + c_true * (W[i] @ x_test) for i in range(n)])
    assert np.allclose(pred, manual, atol=1e-4)


def test_ward_sis_exact_recovery_noiseless():
    rng = np.random.default_rng(1)
    n = 3
    W = rng.uniform(0.05, 0.3, size=(n, n))
    W = W / W.sum(axis=1, keepdims=True)
    beta_true, gamma_true = 0.4, 0.15

    pairs = []
    for _ in range(150):
        x = rng.uniform(0, 1, size=n)
        for i in range(n):
            wx_i = W[i] @ x
            x_next_i = x[i] + beta_true * (1 - x[i]) * wx_i - gamma_true * x[i]
            pairs.append({"x": x, "ward_idx": i, "x_next": x_next_i})

    beta, gamma = fit_ward_sis_model(pairs, W)
    assert abs(beta - beta_true) < 1e-6
    assert abs(gamma - gamma_true) < 1e-6

    x_test = rng.uniform(0, 1, size=n)
    pred = predict_ward_sis(beta, gamma, x_test, W)
    manual = x_test + beta_true * (1 - x_test) * (W @ x_test) - gamma_true * x_test
    assert np.allclose(pred, manual, atol=1e-6)
