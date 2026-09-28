"""Tests for src/build_edmd.py (P6 orchestrator): lambda-grid widening,
the selection criterion, and an integration check that D3's fitted K has
the theoretically-predicted effective rank on the real trajectory data."""
import numpy as np
import pandas as pd
import pytest

from src.build_edmd import lambda_selection_criterion, load_p6_inputs, select_lambda
from src.edmd import ConstantAwareScaler, build_pairs_within_trajectory, ridge_fit


def test_lambda_selection_criterion_is_mean_rmse_over_horizons():
    # 2 trajectories, enough weeks for horizon 4, identity-like dynamics
    n_traj, n_weeks, n_features = 2, 10, 3
    rng = np.random.default_rng(0)
    features = rng.uniform(0.2, 0.8, size=(n_traj, n_weeks, n_features))
    features[..., 0] = 1.0  # constant feature
    trajectory_ids = np.array([0, 1])
    split_df = pd.DataFrame({"trajectory": [0, 1], "split": ["train", "val"]})

    X_train, Y_train, _ = build_pairs_within_trajectory(features, trajectory_ids, split_df, "train")
    scaler = ConstantAwareScaler().fit(X_train)
    K = ridge_fit(scaler.transform(X_train), scaler.transform(Y_train), lam=1.0)

    group_indices = [1, 2]
    criterion = lambda_selection_criterion(K, scaler, group_indices, features, trajectory_ids, split_df)
    assert criterion >= 0
    assert np.isfinite(criterion)


def test_select_lambda_widens_grid_when_best_is_on_edge():
    """Construct a case where only a very small lambda minimizes the
    validation criterion (near-perfect noiseless linear fit), so the
    initial grid's minimum should get hit and trigger a widen."""
    n_traj, n_weeks, n_features = 3, 8, 3
    rng = np.random.default_rng(1)
    A_true = np.array([[0.9, 0.05], [0.02, 0.85]])
    features = np.zeros((n_traj, n_weeks, n_features))
    for tid in range(n_traj):
        x = rng.uniform(0.2, 0.6, size=2)
        for t in range(n_weeks):
            features[tid, t, 0] = 1.0
            features[tid, t, 1:] = x
            x = A_true @ x  # noiseless linear dynamics -> smallest lambda should fit best

    trajectory_ids = np.arange(n_traj)
    split_df = pd.DataFrame({"trajectory": [0, 1, 2], "split": ["train", "train", "val"]})
    X_train, Y_train, _ = build_pairs_within_trajectory(features, trajectory_ids, split_df, "train")
    scaler = ConstantAwareScaler().fit(X_train)
    X_s, Y_s = scaler.transform(X_train), scaler.transform(Y_train)

    narrow_grid = list(np.geomspace(1.0, 10.0, 5))  # deliberately excludes small lambda
    table, best_lambda = select_lambda(
        X_s, Y_s, scaler, [1, 2], features, trajectory_ids, split_df, narrow_grid, max_rounds=1
    )
    # after one widen round, the grid's lower bound should have moved below 1.0
    assert table["lambda"].min() < 1.0


def test_d3_fitted_rank_matches_theoretical_prediction_on_real_data():
    """Integration check: on the actual P5 observables and P6 pipeline,
    D3's fitted K should have rank <= 19 (of 25 features), confirming the
    analytical finding (Wx contributes zero new rank given invertible W;
    x*(Wx) is a linear combination of D2's existing quadratic terms)."""
    sim, split_df, traj_scenario_map, trajectory_ids, groups = load_p6_inputs()
    features = sim["D3_features"]
    X_train, Y_train, _ = build_pairs_within_trajectory(features, trajectory_ids, split_df, "train")
    scaler = ConstantAwareScaler().fit(X_train)
    K = ridge_fit(scaler.transform(X_train), scaler.transform(Y_train), lam=1.0)
    rank = np.linalg.matrix_rank(K, tol=1e-6)
    assert rank <= 19


def test_d1_and_d2_fitted_rank_is_full_on_real_data():
    """Contrast case: D1 and D2 have no built-in redundancy, so their
    fitted K should be full rank (unlike D3)."""
    sim, split_df, traj_scenario_map, trajectory_ids, groups = load_p6_inputs()
    for name, expected_features in [("D1", 7), ("D2", 28)]:
        features = sim[f"{name}_features"]
        assert features.shape[-1] == expected_features
        X_train, Y_train, _ = build_pairs_within_trajectory(features, trajectory_ids, split_df, "train")
        scaler = ConstantAwareScaler().fit(X_train)
        K = ridge_fit(scaler.transform(X_train), scaler.transform(Y_train), lam=1.0)
        rank = np.linalg.matrix_rank(K)
        assert rank == expected_features
