"""Tests for src/edmd.py (P6): the mandatory checks (exact recovery on
noiseless synthetic systems, agreement with closed-form ridge, the
selector, scaler train-only fitting, no cross-trajectory pairs, and the
unpenalized-constant shift property), plus supporting unit tests."""
import numpy as np
import pandas as pd
import pytest

from src.edmd import (
    ConstantAwareScaler,
    build_pairs_within_trajectory,
    compute_metrics_table,
    eigenvalues_outside_unit_circle,
    forecast_horizons,
    gather_rolling_starts,
    ridge_fit,
    selector_matrix,
    spectral_radius,
)
from src.observables import d1_linear, d2_poly2


# ---- 1. Exact recovery of a known linear system x'=Ax+b with D1, lambda->0 ----

def test_d1_exact_recovery_of_linear_system_noiseless():
    rng = np.random.default_rng(0)
    n = 4
    A = rng.uniform(-0.3, 0.3, size=(n, n))
    b = rng.uniform(-0.1, 0.1, size=n)

    n_samples = 500
    X_raw = rng.uniform(0, 1, size=(n_samples, n))
    Y_raw = X_raw @ A.T + b  # noiseless

    group_names = [f"g{i}" for i in range(n)]
    Phi_X, _ = d1_linear(X_raw, group_names)
    Phi_Y, _ = d1_linear(Y_raw, group_names)

    K = ridge_fit(Phi_X, Phi_Y, lam=1e-10)

    assert np.allclose(K[0], [1.0] + [0.0] * n, atol=1e-6)  # const -> const exactly
    recovered_b = K[1:, 0]
    recovered_A = K[1:, 1:]
    assert np.allclose(recovered_b, b, atol=1e-5)
    assert np.allclose(recovered_A, A, atol=1e-5)

    # and predictions on held-out points match exactly
    X_test = rng.uniform(0, 1, size=(50, n))
    Phi_test, _ = d1_linear(X_test, group_names)
    pred = Phi_test @ K.T
    true_next = X_test @ A.T + b
    assert np.allclose(pred[:, 1:], true_next, atol=1e-5)  # D1's layout is [1, x...]


# ---- 2. Exact recovery of a known quadratic map with D2 ----

def test_d2_exact_recovery_of_quadratic_map_noiseless():
    rng = np.random.default_rng(1)
    n = 3
    group_names = [f"g{i}" for i in range(n)]

    n_samples = 400
    X_raw = rng.uniform(-1, 1, size=(n_samples, n))
    Phi_X, names = d2_poly2(X_raw, group_names)
    n_features = Phi_X.shape[1]

    true_coefs = rng.uniform(-0.2, 0.2, size=n_features)  # true map for output g0 only, as a scalar test
    y0 = Phi_X @ true_coefs  # exact quadratic map: y0 = true_coefs . phi(x)

    K = ridge_fit(Phi_X, y0[:, None], lam=1e-10)
    assert np.allclose(K[0], true_coefs, atol=1e-4)

    X_test = rng.uniform(-1, 1, size=(30, n))
    Phi_test, _ = d2_poly2(X_test, group_names)
    pred = (Phi_test @ K.T).ravel()
    true_y0 = Phi_test @ true_coefs
    assert np.allclose(pred, true_y0, atol=1e-4)


# ---- 3. Agreement with a closed-form ridge solution on synthetic data ----

def test_ridge_fit_matches_closed_form_solution():
    rng = np.random.default_rng(2)
    n_samples, n_features, n_out = 200, 10, 6
    X = rng.normal(size=(n_samples, n_features))
    Y = rng.normal(size=(n_samples, n_out))
    lam = 0.5
    const_index = 0

    K = ridge_fit(X, Y, lam=lam, const_index=const_index)

    penalty_diag = np.ones(n_features)
    penalty_diag[const_index] = 0.0
    D = lam * np.diag(penalty_diag)
    K_closed_T = np.linalg.solve(X.T @ X + D, X.T @ Y)  # closed form: K.T = (X'X + D)^-1 X'Y
    K_closed = K_closed_T.T

    assert np.allclose(K, K_closed, atol=1e-8)


# ---- 4. Selector C returns x exactly from phi(x) ----

def test_selector_returns_x_exactly():
    group_names = ["Menard 1", "Sorrel 0", "Other"]
    x = np.array([0.1, 0.4, 0.7])
    features, names = d2_poly2(x, group_names)
    C = selector_matrix(names, group_names)
    assert np.allclose(C @ features, x)


# ---- 5. Scaler is fitted on train only ----

def test_scaler_fitted_on_train_only():
    rng = np.random.default_rng(3)
    X_train = rng.normal(loc=5.0, scale=2.0, size=(100, 4))
    X_val = rng.normal(loc=50.0, scale=20.0, size=(20, 4))  # very different distribution

    scaler = ConstantAwareScaler(const_index=0)
    scaler.fit(X_train)

    manual_mean = X_train.mean(axis=0)
    manual_mean[0] = 0.0
    manual_std = X_train.std(axis=0)
    manual_std[0] = 1.0

    assert np.allclose(scaler.mean_, manual_mean)
    assert np.allclose(scaler.scale_, manual_std)
    # explicitly NOT influenced by X_val
    assert not np.allclose(scaler.mean_[1:], X_val.mean(axis=0)[1:], atol=1.0)


def test_scaler_constant_column_untouched():
    X = np.column_stack([np.ones(50), np.random.default_rng(4).normal(size=(50, 3))])
    scaler = ConstantAwareScaler(const_index=0)
    scaled = scaler.fit_transform(X)
    assert np.all(scaled[:, 0] == 1.0)
    restored = scaler.inverse_transform(scaled)
    assert np.allclose(restored, X)


# ---- 6. Pairs never cross a trajectory boundary ----

def test_pairs_never_cross_trajectory_boundary():
    n_traj, n_weeks, n_features = 5, 6, 2
    # each trajectory's values are its own id * 100 + week, so any
    # cross-trajectory pairing would be immediately detectable
    features = np.zeros((n_traj, n_weeks, n_features))
    for tid in range(n_traj):
        for t in range(n_weeks):
            features[tid, t, :] = tid * 100 + t

    trajectory_ids = np.arange(n_traj)
    split_df = pd.DataFrame({"trajectory": trajectory_ids, "split": ["train"] * n_traj})

    X, Y, traj_id_per_pair = build_pairs_within_trajectory(features, trajectory_ids, split_df, "train")

    assert len(X) == n_traj * (n_weeks - 1)
    # for every pair, X and Y must belong to the SAME trajectory (same
    # hundreds digit) and Y must be exactly X's next week
    x_traj = X[:, 0] // 100
    y_traj = Y[:, 0] // 100
    assert np.array_equal(x_traj, y_traj)
    assert np.array_equal(x_traj, traj_id_per_pair)
    assert np.allclose(Y - X, 1.0)  # each pair steps exactly one week forward


def test_gather_rolling_starts_respects_horizon_and_split():
    n_traj, n_weeks = 3, 17
    trajectory_ids = np.array([0, 1, 2])
    split_df = pd.DataFrame({"trajectory": [0, 1, 2], "split": ["train", "val", "train"]})
    rows, t_starts = gather_rolling_starts(trajectory_ids, split_df, "train", max_h=4, n_weeks=n_weeks)
    assert set(rows.tolist()) == {0, 2}  # only train trajectories (rows 0 and 2)
    assert t_starts.max() == n_weeks - 1 - 4  # last valid start given horizon 4
    assert t_starts.min() == 0


# ---- 7. The constant is not penalized: a shifted target shifts only the constant ----

def test_shifted_target_shifts_only_constant_column():
    rng = np.random.default_rng(5)
    n_samples, n_features, n_out = 300, 8, 8
    X = rng.normal(size=(n_samples, n_features))
    X[:, 0] = 1.0  # constant feature
    Y = rng.normal(size=(n_samples, n_out))
    lam = 2.0

    K = ridge_fit(X, Y, lam=lam, const_index=0)

    c = rng.normal(size=n_out)
    Y_shifted = Y + c  # shift every output by the same constant vector
    K_shifted = ridge_fit(X, Y_shifted, lam=lam, const_index=0)

    assert np.allclose(K_shifted[:, 1:], K[:, 1:], atol=1e-8)  # non-constant columns unchanged
    assert np.allclose(K_shifted[:, 0], K[:, 0] + c, atol=1e-8)  # constant column absorbs the shift


# ---- supporting tests ----

def test_forecast_horizons_matches_repeated_matmul():
    rng = np.random.default_rng(6)
    K = rng.normal(size=(5, 5)) * 0.1
    phi0 = rng.normal(size=(10, 5))
    preds = forecast_horizons(K, phi0, max_h=3)

    manual_h1 = phi0 @ K.T
    manual_h2 = manual_h1 @ K.T
    manual_h3 = manual_h2 @ K.T
    assert np.allclose(preds[1], manual_h1)
    assert np.allclose(preds[2], manual_h2)
    assert np.allclose(preds[3], manual_h3)


def test_spectral_radius_and_eigenvalues_outside_unit_circle():
    K = np.diag([0.5, 0.9, 1.2, -1.5])
    assert abs(spectral_radius(K) - 1.5) < 1e-10
    eigvals, outside = eigenvalues_outside_unit_circle(K)
    assert len(outside) == 2  # 1.2 and -1.5


def test_compute_metrics_table_basic_correctness():
    pred = np.array([[0.5, 0.5], [0.5, 0.5]])
    actual = np.array([[0.6, 0.4], [0.7, 0.3]])
    traj_id = np.array([0, 1])
    results = [{"h": 1, "pred": pred, "actual": actual, "traj_id": traj_id}]
    traj_scenario_map = {0: "endemic", 1: "outbreak"}
    table = compute_metrics_table(results, traj_scenario_map, ["A", "B"], model_name="test")

    overall_row = table[(table["ward"] == "overall") & (table["scenario"] == "overall")].iloc[0]
    manual_rmse = np.sqrt(np.mean((pred - actual) ** 2))
    assert abs(overall_row["rmse"] - manual_rmse) < 1e-10

    endemic_row = table[(table["ward"] == "overall") & (table["scenario"] == "endemic")].iloc[0]
    assert endemic_row["n"] == 1
