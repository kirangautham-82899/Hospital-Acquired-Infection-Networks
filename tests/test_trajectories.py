"""Tests for src/trajectories.py (P4): baseline prevalence, endemic/
outbreak initial conditions, the full-population weekly-mean aggregation,
and end-to-end trajectory generation."""
import numpy as np
import pandas as pd
import pytest

import config
from src.simulate import build_person_index, simulation_day_list
from src.trajectories import (
    endemic_initial_state,
    generate_trajectories,
    group_baseline_prevalence,
    outbreak_initial_state,
    person_group_array,
    weekly_mean_prevalence_all_people,
)


def test_group_baseline_prevalence_excludes_low_n_and_holdout_weeks():
    states_real = pd.DataFrame(
        [
            {"week": 0, "group": "A", "prevalence": 0.2, "low_n": False},
            {"week": 1, "group": "A", "prevalence": 0.4, "low_n": False},
            {"week": 0, "group": "B", "prevalence": 0.9, "low_n": True},  # excluded (low_n)
            {"week": 13, "group": "A", "prevalence": 0.99, "low_n": False},  # excluded (holdout week)
        ]
    )
    baseline = group_baseline_prevalence(states_real, groups=["A", "B"])
    assert abs(baseline["A"] - 0.3) < 1e-9  # mean(0.2, 0.4), week 13 excluded
    assert baseline["B"] == baseline["A"]  # B has no qualifying rows -> falls back to overall mean


def test_endemic_initial_state_respects_cap_and_targets_probability():
    people, index = build_person_index([f"P{i:03d}" for i in range(500)])
    ward_of = {p: "A" for p in people}
    baseline = {"A": 0.9}  # with a 1.5x multiplier this would exceed 1 -> must cap
    rng = np.random.default_rng(0)
    state, group_prob = endemic_initial_state(people, index, ward_of, baseline, rng)
    assert group_prob["A"] <= 1.0
    # empirical colonized fraction should roughly track the (capped) probability used
    assert abs(state.mean() - group_prob["A"]) < 0.08


def test_outbreak_initial_state_seeds_1_to_3_in_one_ward():
    people, index = build_person_index([f"P{i:03d}" for i in range(60)])
    ward_of = {p: ("A" if i < 30 else "B") for i, p in enumerate(people)}
    rng = np.random.default_rng(3)
    state, seed_ward, n_seeds = outbreak_initial_state(people, index, ward_of, rng)
    assert 1 <= n_seeds <= 3
    assert state.sum() == n_seeds
    seeded_people = [p for p in people if state[index[p]]]
    assert all(ward_of[p] == seed_ward for p in seeded_people)


def test_outbreak_seed_ward_varies_across_calls():
    people, index = build_person_index([f"P{i:03d}" for i in range(60)])
    ward_of = {p: ["A", "B", "C"][i % 3] for i, p in enumerate(people)}
    wards_seen = set()
    for seed in range(20):
        rng = np.random.default_rng(seed)
        _, seed_ward, _ = outbreak_initial_state(people, index, ward_of, rng)
        wards_seen.add(seed_ward)
    assert len(wards_seen) > 1  # should not always pick the same ward


def test_weekly_mean_prevalence_matches_hand_calculation():
    """simulation_day_list() starts 2009-07-01 (a Wednesday), and week 0 is
    Monday-anchored (Jun29-Jul5), so only the FIRST 5 entries of
    simulation_day_list() (Jul1-Jul5) fall in week 0 -- day 6 onward is
    already week 1. Use exactly those 5 days for a clean single-week
    hand-check."""
    people, index = build_person_index(["P1", "P2"])
    day_list = simulation_day_list()[:5]  # 2009-07-01 .. 2009-07-05, all of week 0's overlap
    history = np.zeros((5, 2), dtype=bool)
    history[:, 0] = [True, True, False, False, False]  # P1 colonized 2/5 days
    history[:, 1] = [False] * 5  # P2 never colonized
    group_arr = person_group_array(people, {"P1": "A", "P2": "A"})

    out = weekly_mean_prevalence_all_people(history, day_list, group_arr, groups=["A"])
    daily_prev = history.mean(axis=1)  # per-day mean over the 2 people
    expected_week0 = daily_prev.mean()
    assert abs(out[0, 0] - expected_week0) < 1e-9


@pytest.fixture(scope="module")
def small_sim_inputs():
    from src.load import load_admission, load_contacts
    from src.network import build_master_edge_list
    from src.simulate import daily_edge_arrays

    admission = load_admission(config.ADMISSION_CSV)
    contacts = load_contacts(config.CONTACTS_CSV)
    edges = build_master_edge_list(contacts)
    people_set = set(contacts["from"]) | set(contacts["to"])
    people, index = build_person_index(people_set)
    day_list = simulation_day_list()
    edge_arrays = daily_edge_arrays(edges, index)

    states_real = pd.DataFrame(
        [
            {"week": w, "group": g, "prevalence": 0.2, "n_tested": 50, "low_n": False}
            for w in config.CALIBRATION_WEEKS
            for g in config.WARD_GROUPS
        ]
    )
    return admission, people, index, day_list, edge_arrays, states_real


def test_generate_trajectories_shape_and_scenario_split(small_sim_inputs):
    admission, people, index, day_list, edge_arrays, states_real = small_sim_inputs
    calibrated = {"beta": 0.01, "gamma": 0.02, "epsilon": 0.001}
    states, metadata = generate_trajectories(
        10, people, index, day_list, edge_arrays, admission, calibrated, states_real, base_seed=1
    )
    assert states.shape == (10, config.N_WEEKS, len(config.WARD_GROUPS))
    assert (metadata["scenario"] == "endemic").sum() == 5
    assert (metadata["scenario"] == "outbreak").sum() == 5
    assert not np.isnan(states).any()


def test_generate_trajectories_params_within_multiplier_range(small_sim_inputs):
    admission, people, index, day_list, edge_arrays, states_real = small_sim_inputs
    calibrated = {"beta": 0.01, "gamma": 0.02, "epsilon": 0.001}
    _, metadata = generate_trajectories(
        20, people, index, day_list, edge_arrays, admission, calibrated, states_real, base_seed=2
    )
    lo, hi = config.TRAJECTORY_PARAM_MULTIPLIER_RANGE
    assert (metadata["beta"] >= calibrated["beta"] * lo - 1e-12).all()
    assert (metadata["beta"] <= calibrated["beta"] * hi + 1e-12).all()
    assert (metadata["gamma"] >= calibrated["gamma"] * lo - 1e-12).all()
    assert (metadata["gamma"] <= calibrated["gamma"] * hi + 1e-12).all()
    assert (metadata["epsilon"] == calibrated["epsilon"]).all()  # epsilon held fixed, not varied


def test_generate_trajectories_reproducible_with_same_base_seed(small_sim_inputs):
    admission, people, index, day_list, edge_arrays, states_real = small_sim_inputs
    calibrated = {"beta": 0.01, "gamma": 0.02, "epsilon": 0.001}
    states1, meta1 = generate_trajectories(
        6, people, index, day_list, edge_arrays, admission, calibrated, states_real, base_seed=99
    )
    states2, meta2 = generate_trajectories(
        6, people, index, day_list, edge_arrays, admission, calibrated, states_real, base_seed=99
    )
    assert np.array_equal(states1, states2, equal_nan=True)
    pd.testing.assert_frame_equal(meta1, meta2)


def test_outbreak_trajectories_start_lower_than_endemic_on_average(small_sim_inputs):
    """Sanity check on the two scenario types: outbreak starts (1-3 seeded
    people) should have much lower week-0 prevalence than endemic starts
    (drawn near the ~0.2 baseline used in states_real fixture)."""
    admission, people, index, day_list, edge_arrays, states_real = small_sim_inputs
    calibrated = {"beta": 0.01, "gamma": 0.02, "epsilon": 0.001}
    states, metadata = generate_trajectories(
        40, people, index, day_list, edge_arrays, admission, calibrated, states_real, base_seed=3
    )
    week0_mean = states[:, 0, :].mean(axis=1)  # mean across groups, per trajectory
    endemic_mask = (metadata["scenario"] == "endemic").to_numpy()
    assert week0_mean[endemic_mask].mean() > week0_mean[~endemic_mask].mean()
