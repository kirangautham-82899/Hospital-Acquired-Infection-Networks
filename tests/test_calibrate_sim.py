"""Tests for src/calibrate_sim.py (P4): initial conditions, the
'at-test-date' aggregation that mirrors P3 exactly, the weighted loss, and
the common-random-numbers seeding scheme."""
import numpy as np
import pandas as pd
import pytest

from src.calibrate_sim import (
    calibration_initial_state,
    calibration_loss,
    is_on_edge,
    replicate_seed_pairs,
    simulated_status_at_test_dates,
    simulated_weekly_prevalence,
)
from src.simulate import build_person_index, simulation_day_list


def test_calibration_initial_state_uses_known_status_exactly():
    people, index = build_person_index(["PA-001", "PA-002", "PA-003"])
    admission = pd.DataFrame(
        {"calc_ident": ["PA-001", "PA-002", "PA-003"], "service_pa_pe": ["Menard 1"] * 3}
    )
    pre_window = pd.DataFrame({"calc_ident": ["PA-001", "PA-002"], "last_status": [1, 0]})
    state = calibration_initial_state(people, index, pre_window, admission, seed=0)
    assert state[index["PA-001"]] == True
    assert state[index["PA-002"]] == False


def test_calibration_initial_state_unknown_person_draws_from_group_prevalence():
    people, index = build_person_index([f"PA-{i:03d}" for i in range(200)])
    admission = pd.DataFrame({"calc_ident": people, "service_pa_pe": ["Menard 1"] * 200})
    # 100 people with known status (80% positive), 100 unknown
    known = people[:100]
    pre_window = pd.DataFrame({"calc_ident": known, "last_status": [1] * 80 + [0] * 20})
    state = calibration_initial_state(people, index, pre_window, admission, seed=1)
    unknown_idx = [index[p] for p in people[100:]]
    empirical_rate = state[unknown_idx].mean()
    assert abs(empirical_rate - 0.8) < 0.15  # loose statistical tolerance


def test_calibration_initial_state_reproducible_with_same_seed():
    people, index = build_person_index([f"PA-{i:03d}" for i in range(50)])
    admission = pd.DataFrame({"calc_ident": people, "service_pa_pe": ["Menard 1"] * 50})
    pre_window = pd.DataFrame({"calc_ident": people[:10], "last_status": [1] * 5 + [0] * 5})
    s1 = calibration_initial_state(people, index, pre_window, admission, seed=42)
    s2 = calibration_initial_state(people, index, pre_window, admission, seed=42)
    assert np.array_equal(s1, s2)


def test_simulated_status_and_weekly_prevalence_any_positive_rule():
    people, index = build_person_index(["PA-001", "PA-002"])
    day_list = simulation_day_list()[:14]  # 2 weeks
    n_days, n_people = len(day_list), len(people)
    history = np.zeros((n_days, n_people), dtype=bool)
    # PA-001: negative on day0, positive on day1 (both in week 0) -> "any positive" -> week0 positive
    history[1, index["PA-001"]] = True
    # PA-002: never colonized
    microbio = pd.DataFrame(
        {
            "calc_ident": ["PA-001", "PA-001", "PA-002"],
            "date_prl": [day_list[0], day_list[1], day_list[0]],
        }
    )
    admission = pd.DataFrame({"calc_ident": ["PA-001", "PA-002"], "service_pa_pe": ["Menard 1", "Menard 1"]})

    rows = simulated_status_at_test_dates(microbio, set(people), day_list, history, index)
    assert len(rows) == 3
    weekly = simulated_weekly_prevalence(rows, admission, groups=["Menard 1"])
    week0 = weekly[weekly["week"] == 0].iloc[0]
    assert week0["n_tested"] == 2
    assert week0["n_positive"] == 1  # PA-001 positive (any test that week), PA-002 negative
    assert week0["prevalence"] == 0.5


def test_calibration_loss_excludes_low_n_and_weights_by_n_tested():
    states_real = pd.DataFrame(
        [
            {"week": 0, "group": "A", "prevalence": 0.5, "n_tested": 20, "low_n": False},
            {"week": 0, "group": "B", "prevalence": 0.8, "n_tested": 5, "low_n": True},  # excluded
            {"week": 1, "group": "A", "prevalence": 0.3, "n_tested": 10, "low_n": False},
        ]
    )
    sim_prevalence = pd.DataFrame(
        [
            {"week": 0, "group": "A", "prevalence": 0.4},  # err 0.1, weight 20
            {"week": 0, "group": "B", "prevalence": 0.0},  # excluded (low_n)
            {"week": 1, "group": "A", "prevalence": 0.3},  # err 0.0, weight 10
        ]
    )
    loss, merged = calibration_loss(states_real, sim_prevalence, weeks=[0, 1])
    assert len(merged) == 2  # the low_n row must not appear
    expected = (20 * 0.1**2 + 10 * 0.0**2) / (20 + 10)
    assert abs(loss - expected) < 1e-12


def test_replicate_seed_pairs_reproducible_and_distinct():
    """SeedSequence.entropy is shared by all children spawned from one
    root (it identifies the root, not the child), so distinctness has to
    be checked by what the seeds actually produce, not by .entropy."""
    pairs_a = replicate_seed_pairs(5, base_seed=123)
    pairs_b = replicate_seed_pairs(5, base_seed=123)
    assert len(pairs_a) == 5

    draws_a = [np.random.default_rng(ic).random() for ic, _ in pairs_a]
    draws_b = [np.random.default_rng(ic).random() for ic, _ in pairs_b]
    assert draws_a == draws_b  # same base_seed -> identical seed pairs -> identical draws
    assert len(set(draws_a)) == 5  # different replicate indices -> distinct streams

    dyn_draws_a = [np.random.default_rng(dyn).random() for _, dyn in pairs_a]
    assert len(set(dyn_draws_a)) == 5
    assert draws_a != dyn_draws_a  # ic and dyn streams within a replicate must differ too


def test_is_on_edge_detects_min_and_max():
    grid = [1, 2, 4, 8]
    best_low = {"beta": 1, "gamma": 4, "epsilon": 2}
    edges = is_on_edge(best_low, grid, grid, grid)
    assert edges["beta"] == "low"
    assert "gamma" not in edges

    best_high = {"beta": 8, "gamma": 8, "epsilon": 4}
    edges2 = is_on_edge(best_high, grid, grid, grid)
    assert edges2["beta"] == "high" and edges2["gamma"] == "high"
    assert "epsilon" not in edges2
