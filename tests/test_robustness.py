"""Tests for src/robustness.py (P11): the shared rank_stability metric,
the D3_reduced feature construction, and integration checks against real
saved P9/P4/P2 outputs for each experiment's core mechanics."""
import numpy as np
import pandas as pd
import pytest

import config
from src.robustness import _d3_reduced_features, rank_stability


def test_rank_stability_perfect_agreement():
    a = pd.Series([1, 2, 3, 4], index=["A", "B", "C", "D"])
    b = pd.Series([10, 20, 30, 40], index=["A", "B", "C", "D"])  # same order, different scale
    rho, pval = rank_stability(a, b, ["A", "B", "C", "D"])
    assert abs(rho - 1.0) < 1e-9


def test_rank_stability_perfect_disagreement():
    a = pd.Series([1, 2, 3, 4], index=["A", "B", "C", "D"])
    b = pd.Series([4, 3, 2, 1], index=["A", "B", "C", "D"])  # exactly reversed
    rho, pval = rank_stability(a, b, ["A", "B", "C", "D"])
    assert abs(rho - (-1.0)) < 1e-9


def test_rank_stability_handles_reordered_index():
    a = pd.Series([1, 2, 3], index=["A", "B", "C"])
    b = pd.Series([30, 10, 20], index=["C", "A", "B"])  # different index order, same underlying values
    rho, pval = rank_stability(a, b, ["A", "B", "C"])
    assert abs(rho - 1.0) < 1e-9  # A:1<->10, B:2<->20, C:3<->30 -- perfectly monotonic once aligned


def test_d3_reduced_features_matches_full_d3_minus_wx_block():
    from src.observables import d3_contact_weighted

    rng = np.random.default_rng(0)
    W = rng.uniform(0.05, 0.3, size=(4, 4))
    W = W / W.sum(axis=1, keepdims=True)
    x = rng.uniform(0, 1, size=4)
    groups = ["a", "b", "c", "d"]

    full_features, full_names = d3_contact_weighted(x, groups, W)
    reduced_features, reduced_names = _d3_reduced_features(x, groups, W)

    assert len(reduced_names) == len(full_names) - 4  # dropped exactly the 4 Wx entries
    assert not any(name.startswith("(Wx)_") for name in reduced_names)
    # every reduced feature should have an EXACT match among the full D3 features
    full_by_name = dict(zip(full_names, full_features))
    for name, value in zip(reduced_names, reduced_features):
        assert abs(full_by_name[name] - value) < 1e-12


def test_d3_reduced_features_batched_matches_per_sample():
    rng = np.random.default_rng(1)
    W = rng.uniform(0.05, 0.3, size=(3, 3))
    W = W / W.sum(axis=1, keepdims=True)
    X = rng.uniform(0, 1, size=(2, 5, 3))
    groups = ["a", "b", "c"]

    batched, names = _d3_reduced_features(X, groups, W)
    for i in range(2):
        for t in range(5):
            single, _ = _d3_reduced_features(X[i, t], groups, W)
            assert np.allclose(batched[i, t], single)


# ---- integration checks against real saved outputs ----

def test_e5_calibration_week_contacts_are_a_subset():
    """Sanity check the raw ingredient E5 depends on: restricting
    contacts to the calibration weeks should strictly reduce row count
    and total contact-seconds relative to the whole period."""
    from src.load import load_admission, load_contacts
    from src.network import assign_week, build_master_edge_list, ward_contact_matrix

    admission = load_admission(config.ADMISSION_CSV)
    contacts = load_contacts(config.CONTACTS_CSV)
    week = assign_week(contacts["day"])
    calib_contacts = contacts[week.isin(config.CALIBRATION_WEEKS)]

    assert 0 < len(calib_contacts) < len(contacts)
    w_calib = ward_contact_matrix(calib_contacts, admission, include_staff=True)
    w_full = pd.read_csv(config.RESULTS_TABLES_DIR / "p2_ward_matrix_raw_all.csv", index_col=0)
    assert w_calib.reindex(index=config.WARD_GROUPS, columns=config.WARD_GROUPS).to_numpy().sum() < w_full.to_numpy().sum()


def test_e4_ridge_point_is_within_10_percent_of_best_and_differs_from_it():
    grid = pd.read_csv(config.RESULTS_TABLES_DIR / "p4_calibration_grid.csv")
    best_loss = grid["loss"].min()
    near_best = grid[grid["loss"] < best_loss * 1.1]
    assert len(near_best) > 1  # there really is a ridge, not a single point
    alt_point = near_best.sort_values("gamma", ascending=False).iloc[0]
    best_point = grid.sort_values("loss").iloc[0]
    assert alt_point["loss"] < best_loss * 1.1
    assert alt_point["gamma"] != best_point["gamma"]  # genuinely a different point on the ridge
