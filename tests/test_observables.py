"""Tests for src/observables.py (P5): exact feature construction for D1,
D2, D3 against hand-computed small cases, vectorization correctness, and
dimension-agnostic behavior (n=6 and n=5)."""
import numpy as np
import pytest

from src.observables import d1_linear, d2_poly2, d3_contact_weighted


def test_d1_linear_hand_check():
    X = np.array([0.2, 0.5, 0.1])
    features, names = d1_linear(X, ["a", "b", "c"])
    assert names == ["1", "x_a", "x_b", "x_c"]
    assert np.allclose(features, [1.0, 0.2, 0.5, 0.1])


def test_d1_linear_batched_shape():
    X = np.random.default_rng(0).random((5, 17, 6))
    features, names = d1_linear(X, list("abcdef"))
    assert features.shape == (5, 17, 7)
    assert len(names) == 7


def test_d2_poly2_hand_check_two_dims():
    X = np.array([2.0, 3.0])
    features, names = d2_poly2(X, ["a", "b"])
    # expected: [1, x_a, x_b, x_a^2, x_b^2, x_a*x_b] = [1, 2, 3, 4, 9, 6]
    assert names == ["1", "x_a", "x_b", "x_a^2", "x_b^2", "x_a*x_b"]
    assert np.allclose(features, [1.0, 2.0, 3.0, 4.0, 9.0, 6.0])


def test_d2_poly2_feature_count_for_six_groups():
    X = np.zeros(6)
    features, names = d2_poly2(X, list("abcdef"))
    # 1 (const) + 6 (linear) + 6 (squares) + 15 (cross, C(6,2)) = 28
    assert features.shape == (28,)
    assert len(names) == 28
    assert len(set(names)) == 28  # all distinct


def test_d2_poly2_cross_terms_are_correct_products():
    X = np.array([1.0, 2.0, 3.0])
    features, names = d2_poly2(X, ["a", "b", "c"])
    by_name = dict(zip(names, features))
    assert by_name["x_a*x_b"] == 2.0
    assert by_name["x_a*x_c"] == 3.0
    assert by_name["x_b*x_c"] == 6.0


def test_d3_contact_weighted_wx_matches_manual_matmul():
    W = np.array([[0.7, 0.3], [0.2, 0.8]])
    x = np.array([0.4, 0.6])
    features, names = d3_contact_weighted(x, ["a", "b"], W)
    manual_wx = W @ x  # (Wx)_i = sum_j W[i,j] x_j
    by_name = dict(zip(names, features))
    assert abs(by_name["(Wx)_a"] - manual_wx[0]) < 1e-12
    assert abs(by_name["(Wx)_b"] - manual_wx[1]) < 1e-12


def test_d3_cross_term_is_elementwise_not_dot_product():
    W = np.eye(3)  # Wx = x when W is identity
    x = np.array([2.0, 3.0, 5.0])
    features, names = d3_contact_weighted(x, ["a", "b", "c"], W)
    by_name = dict(zip(names, features))
    # with W=I, Wx=x, so x*(Wx) should equal x^2 elementwise, 3 separate values
    assert by_name["x_a*(Wx)_a"] == 4.0
    assert by_name["x_b*(Wx)_b"] == 9.0
    assert by_name["x_c*(Wx)_c"] == 25.0
    # exactly 3 cross-term features, not collapsed to 1 (a dot product would be a single scalar)
    cross_names = [n for n in names if "*(Wx)" in n]
    assert len(cross_names) == 3


def test_d3_feature_count_for_six_groups():
    W = np.eye(6)
    X = np.zeros(6)
    features, names = d3_contact_weighted(X, list("abcdef"), W)
    # 1 + 6 (x) + 6 (x^2) + 6 (Wx) + 6 (x*Wx) = 25
    assert features.shape == (25,)
    assert len(names) == 25


def test_d3_raises_on_shape_mismatch():
    W = np.eye(3)  # wrong size for a 6-dim state
    X = np.zeros(6)
    with pytest.raises(AssertionError):
        d3_contact_weighted(X, list("abcdef"), W)


def test_d3_batched_matches_per_sample_loop():
    rng = np.random.default_rng(1)
    W = rng.random((4, 4))
    W = W / W.sum(axis=1, keepdims=True)  # row-normalize like the real W
    X = rng.random((3, 5, 4))  # [trajectories, weeks, groups]

    batched_features, names = d3_contact_weighted(X, list("abcd"), W)
    for i in range(3):
        for t in range(5):
            single_features, _ = d3_contact_weighted(X[i, t], list("abcd"), W)
            assert np.allclose(batched_features[i, t], single_features)


def test_dictionaries_are_dimension_agnostic_n5():
    """Patients-only sensitivity run (E6) will use n=5 groups; nothing
    here should hardcode n=6."""
    W = np.eye(5)
    X = np.random.default_rng(2).random((5,))
    groups = ["Menard 1", "Menard 2", "Sorrel 0", "Sorrel 1", "Sorrel 2"]
    f1, n1 = d1_linear(X, groups)
    f2, n2 = d2_poly2(X, groups)
    f3, n3 = d3_contact_weighted(X, groups, W)
    assert f1.shape == (6,)  # 1 + 5
    assert f2.shape == (1 + 5 + 5 + 10,)  # 1 + 5 + 5 + C(5,2)=10 = 21
    assert f3.shape == (1 + 5 + 5 + 5 + 5,)  # 21


def test_all_dictionaries_include_the_raw_state_x():
    """'Identity included' -- x itself must be a readable-back subset of
    every dictionary's features."""
    X = np.array([0.1, 0.2, 0.3])
    names_groups = ["a", "b", "c"]
    for fn in (d1_linear, d2_poly2):
        features, names = fn(X, names_groups)
        for i, g in enumerate(names_groups):
            assert features[names.index(f"x_{g}")] == X[i]
    W = np.eye(3)
    features, names = d3_contact_weighted(X, names_groups, W)
    for i, g in enumerate(names_groups):
        assert features[names.index(f"x_{g}")] == X[i]
