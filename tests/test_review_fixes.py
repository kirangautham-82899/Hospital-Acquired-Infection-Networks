"""Tests for the fixes made after the Nov 14 review: calibration grid
widening and profile loss (P4), the Koopman influence score (P7), the
equal-hours ground truth (P9), and the uncertainty helpers used in P8/P10.
Each test checks against a hand-computable answer, not just "it runs"."""
import itertools

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src.calibrate_sim import near_optimal_interval, profile_loss, widened_grid
from src.edmd import ConstantAwareScaler
from src.influence import koopman_influence_scores, koopman_rollout, ward_sizes_in_network
from src.intervention import equal_hours_scales, scale_ward_edges, ward_touching_seconds
from src.metrics import binomial_noise_floor, block_bootstrap_rmse_diff, paired_mean_ci, spearman_exact

GROUPS3 = ["A", "B", "C"]


# ------------------------------------------------------------- P4 ----

def test_widened_grid_extends_one_side_and_keeps_length():
    grid = list(np.geomspace(1e-3, 1e-1, 5))
    low = widened_grid(grid, "low", factor=3.0)
    high = widened_grid(grid, "high", factor=3.0)
    assert len(low) == len(high) == 5
    assert low[0] == pytest.approx(1e-3 / 3) and low[-1] == pytest.approx(1e-1)
    assert high[0] == pytest.approx(1e-3) and high[-1] == pytest.approx(3e-1)
    with pytest.raises(ValueError):
        widened_grid(grid, "sideways")


def test_profile_loss_is_min_over_other_params():
    table = pd.DataFrame({
        "beta": [1, 1, 2, 2], "gamma": [10, 20, 10, 20], "epsilon": [0, 0, 0, 0],
        "loss": [5.0, 3.0, 4.0, 6.0],
    })
    prof = profile_loss(table, "gamma")
    assert prof["gamma"].tolist() == [10, 20]
    assert prof["profile_loss"].tolist() == [4.0, 3.0]  # min over beta at each gamma


def test_near_optimal_interval_hand_computed():
    table = pd.DataFrame({"gamma": [1.0, 2.0, 3.0, 4.0], "loss": [1.00, 1.04, 1.20, 1.03]})
    assert near_optimal_interval(table, "gamma", tol=0.05) == (1.0, 4.0)
    assert near_optimal_interval(table, "gamma", tol=0.035) == (1.0, 4.0)
    assert near_optimal_interval(table, "gamma", tol=0.01) == (1.0, 1.0)


# ------------------------------------------------------------- P7 ----

def _identity_scaled_d1_model(K):
    """A D1 'fitted model' whose scaler is the identity, so the lifted
    state is exactly [1, x] and K acts on it directly."""
    n = K.shape[0]
    scaler = ConstantAwareScaler()
    scaler.mean_ = np.zeros(n)
    scaler.scale_ = np.ones(n)
    names = ["1"] + [f"x_{g}" for g in GROUPS3]
    return {"K": K, "scaler": scaler, "feature_names": names}


def test_rollout_identity_operator_keeps_state_constant():
    model = _identity_scaled_d1_model(np.eye(4))
    x0 = np.array([0.1, 0.2, 0.3])
    out = koopman_rollout(model, "D1", x0, GROUPS3, horizon=5)
    assert out.shape == (5, 3)
    assert np.allclose(out, x0)


def test_influence_identity_operator_equals_seed_times_horizon():
    """With K = I a seeded case simply persists: total influence =
    n_seed people x horizon weeks, spillover = 0, for every ward."""
    model = _identity_scaled_d1_model(np.eye(4))
    df = koopman_influence_scores(model, "D1", np.array([0.1, 0.2, 0.3]), [50, 100, 200], GROUPS3,
                                  n_seed=2, horizon=4)
    assert np.allclose(df["influence_total"], 2 * 4)
    assert np.allclose(df["influence_spillover"], 0.0)
    assert np.allclose(df["seed_prevalence_step"], [2 / 50, 2 / 100, 2 / 200])


def test_influence_detects_ward_that_feeds_others():
    """x_B(t+1) = x_B(t) + 0.5 x_A(t): seeding A spills into B, seeding B
    or C does not spill anywhere. Hand-computed for horizon 2 with equal
    ward sizes N=100 and n_seed=1 (step 0.01):
      seed A: x_A stays +0.01; x_B gets +0.005 at h=1, +0.010 at h=2
      -> spillover = (0.005 + 0.010) * 100 = 1.5 people-weeks."""
    K = np.eye(4)
    K[2, 1] = 0.5  # row = output x_B, column = input x_A (index 0 is the constant)
    model = _identity_scaled_d1_model(K)
    df = koopman_influence_scores(model, "D1", np.zeros(3), [100, 100, 100], GROUPS3, n_seed=1, horizon=2)
    spill = df.set_index("ward")["influence_spillover"]
    assert spill["A"] == pytest.approx(1.5)
    assert spill["B"] == pytest.approx(0.0)
    assert spill["C"] == pytest.approx(0.0)
    assert df.set_index("ward")["influence_total"]["A"] == pytest.approx(1 * 2 + 1.5)


def test_ward_sizes_in_network_counts_people():
    admission = pd.DataFrame({"calc_ident": ["p1", "p2", "p3", "p4"],
                              "service_pa_pe": ["Menard 1", "Menard 1", "Kine", "Sorrel 0"]})
    sizes = ward_sizes_in_network(admission, {"p1", "p2", "p3"}, ["Menard 1", "Sorrel 0", "Other"])
    assert sizes.tolist() == [2, 0, 1]


# ------------------------------------------------------------- P9 ----

def _three_ward_edges():
    admission = pd.DataFrame({"calc_ident": ["a1", "a2", "b1", "c1"],
                              "service_pa_pe": ["Menard 1", "Menard 1", "Menard 2", "Sorrel 0"]})
    edges = pd.DataFrame({
        "day": pd.to_datetime(["2009-07-01"] * 3),
        "u": ["a1", "a1", "b1"], "v": ["a2", "b1", "c1"], "seconds": [1000.0, 400.0, 200.0],
    })
    return admission, edges


def test_ward_touching_seconds_counts_each_edge_once_per_ward():
    admission, edges = _three_ward_edges()
    t = ward_touching_seconds(edges, admission, ["Menard 1", "Menard 2", "Sorrel 0"])
    assert t["Menard 1"] == 1400.0  # a1-a2 (once) + a1-b1
    assert t["Menard 2"] == 600.0   # a1-b1 + b1-c1
    assert t["Sorrel 0"] == 200.0   # b1-c1


def test_equal_hours_scales_remove_the_same_seconds_from_every_ward():
    admission, edges = _three_ward_edges()
    groups = ["Menard 1", "Menard 2", "Sorrel 0"]
    touching = ward_touching_seconds(edges, admission, groups)
    scales = equal_hours_scales(touching, fraction_of_min=0.5)
    removed = []
    for ward in groups:
        after = scale_ward_edges(edges, admission, ward, scale=scales[ward])
        removed.append(edges["seconds"].sum() - after["seconds"].sum())
    assert np.allclose(removed, 100.0)  # 0.5 x smallest volume (200 s)
    assert scales["Sorrel 0"] == pytest.approx(0.5)


# --------------------------------------------------------- P8 / P10 ----

def test_paired_mean_ci_matches_scipy_ttest():
    rng = np.random.default_rng(0)
    diff = rng.normal(1.0, 2.0, size=50)
    res = paired_mean_ci(diff, level=0.95)
    t = stats.ttest_1samp(diff, 0.0)
    se = diff.std(ddof=1) / np.sqrt(50)
    half = stats.t.ppf(0.975, 49) * se
    assert res["mean"] == pytest.approx(diff.mean())
    assert res["ci_low"] == pytest.approx(diff.mean() - half)
    assert res["ci_high"] == pytest.approx(diff.mean() + half)
    assert res["p_value"] == pytest.approx(t.pvalue)


def test_spearman_exact_perfect_and_hand_counted():
    rho, p = spearman_exact([1, 2, 3, 4, 5, 6], [10, 20, 30, 40, 50, 60])
    assert rho == pytest.approx(1.0)
    assert p == pytest.approx(2 / 720)  # only the identity and full reversal reach |rho| = 1
    # brute-force check of a non-trivial case
    x, y = [1, 2, 3, 4, 5, 6], [2, 1, 3, 4, 6, 5]
    rho, p = spearman_exact(x, y)
    all_rho = [stats.spearmanr(x, np.array(y)[list(q)]).statistic for q in itertools.permutations(range(6))]
    assert p == pytest.approx(np.mean(np.abs(all_rho) >= abs(rho) - 1e-12))


def test_block_bootstrap_identical_models_gives_zero_difference():
    df = pd.DataFrame({"start_week": [1, 1, 2, 2, 3], "landing_week": [2, 2, 3, 3, 4],
                       "ward": ["A", "B", "A", "B", "A"], "pred": [.1, .2, .3, .2, .1],
                       "actual": [.2, .2, .1, .3, .1]})
    res = block_bootstrap_rmse_diff(df, df.copy(), n_boot=200, seed=1)
    assert res["rmse_diff"] == 0.0 and res["ci_low"] == 0.0 and res["ci_high"] == 0.0
    assert res["n_blocks"] == 3 and res["n_cells"] == 5


def test_block_bootstrap_detects_a_uniformly_better_model():
    base = pd.DataFrame({"start_week": np.repeat(np.arange(8), 3), "landing_week": np.repeat(np.arange(8), 3) + 1,
                         "ward": list("ABC") * 8, "actual": 0.2, "pred": 0.4})
    better = base.copy()
    better["pred"] = 0.25
    res = block_bootstrap_rmse_diff(better, base, n_boot=500, seed=2)
    assert res["rmse_diff"] == pytest.approx(0.05 - 0.2)
    assert res["ci_high"] < 0 and res["p_not_better"] == 0.0


def test_binomial_noise_floor_hand_computed():
    assert binomial_noise_floor([0.5, 0.5], [25, 25]) == pytest.approx(0.1)
    assert binomial_noise_floor([0.2, 0.5], [16, 100]) == pytest.approx(np.sqrt((0.01 + 0.0025) / 2))


def test_p10_pairwise_comparisons_sign_and_verdict():
    from src.build_p10 import pairwise_comparisons

    base = np.array([100.0, 110.0, 90.0, 105.0, 95.0])
    per_rep = {
        ("degree_targeted", 1, 0.5): base,
        ("koopman_x", 1, 0.5): base - 10.0,   # always 10 fewer person-days -> better
        ("worse_x", 1, 0.5): base + 1.0,      # always 1 more -> worse
    }
    grid = [{"k": 1, "R": 0.5, "budget": 0.5}]
    out = pairwise_comparisons(per_rep, grid, references=("degree_targeted",)).set_index("strategy")
    assert out.loc["koopman_x", "advantage_mean"] == pytest.approx(10.0)
    assert out.loc["koopman_x", "verdict"] == "better"
    assert out.loc["worse_x", "advantage_mean"] == pytest.approx(-1.0)
    assert out.loc["worse_x", "verdict"] == "worse"
