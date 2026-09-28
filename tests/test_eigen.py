"""Tests for src/eigen.py (P7): eigendecomposition, the similarity-
transform un-scaling of eigenvectors, null-space/trivial-mode filtering,
conjugate-pair detection, and an integration check against P6's real D3
model (rank cutoff should land exactly at 19, matching the empirically
confirmed ~10^12 magnitude gap)."""
import numpy as np
import pytest

import config
from src.eigen import (
    dominant_ward_relevant_mode,
    eigendecompose,
    find_conjugate_pairs,
    mode_table,
    mode_ward_patterns,
    null_space_rank_cutoff,
    trivial_mode_mask,
    unscale_eigenvector,
)


def test_eigendecompose_satisfies_eigenvalue_equation_and_is_sorted():
    rng = np.random.default_rng(0)
    K = rng.normal(size=(6, 6))
    eigvals, eigvecs = eigendecompose(K)
    for i in range(6):
        assert np.allclose(K @ eigvecs[:, i], eigvals[i] * eigvecs[:, i], atol=1e-8)
    mags = np.abs(eigvals)
    assert (np.diff(mags) <= 1e-12).all()  # non-increasing


def test_unscale_eigenvector_similarity_transform_property():
    """Build K_orig, define a scaling D=diag(scale) with x ~= D z (i.e.
    z = D^-1 x, matching ConstantAwareScaler's z=(x-mean)/scale), form
    K_scaled = D^-1 K_orig D (the operator that acts on z), and confirm
    that unscaling a K_scaled eigenvector by MULTIPLYING by scale_
    recovers an eigenvector of K_orig with the SAME eigenvalue."""
    rng = np.random.default_rng(1)
    n = 5
    K_orig = rng.normal(size=(n, n)) * 0.3
    scale = rng.uniform(0.5, 3.0, size=n)
    D = np.diag(scale)
    K_scaled = np.linalg.inv(D) @ K_orig @ D

    eigvals_scaled, eigvecs_scaled = eigendecompose(K_scaled)
    eigvals_orig, eigvecs_orig = eigendecompose(K_orig)

    for i in range(n):
        u = unscale_eigenvector(eigvecs_scaled[:, i], scale)
        # u should be an eigenvector of K_orig with the matching eigenvalue
        assert np.allclose(K_orig @ u, eigvals_scaled[i] * u, atol=1e-6)

    assert np.allclose(sorted(eigvals_scaled, key=lambda z: abs(z)), sorted(eigvals_orig, key=lambda z: abs(z)))


def test_mode_ward_patterns_matches_manual_computation():
    C = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])  # selects features 1,2 (skips constant at 0)
    eigvecs = np.array([[1.0, 0.0], [2.0, 1.0], [3.0, -1.0]])
    scale_ = np.array([1.0, 2.0, 3.0])
    patterns = mode_ward_patterns(eigvecs, C, scale_)
    manual = C @ (eigvecs * scale_[:, None])
    assert np.allclose(patterns, manual)
    assert patterns.shape == (2, 2)


def test_null_space_rank_cutoff_on_low_rank_matrix():
    rng = np.random.default_rng(2)
    A = rng.normal(size=(10, 4))
    K = A @ A.T  # rank <= 4, 10x10
    cutoff = null_space_rank_cutoff(K)
    assert cutoff == 4


def test_trivial_mode_mask_detects_zero_pattern():
    patterns = np.array([[1.0, 0.0, 0.5], [1.0, 1e-12, 0.5]])
    mask = trivial_mode_mask(patterns, rel_tol=1e-6)
    assert mask.tolist() == [False, True, False]


def test_find_conjugate_pairs_on_rotation_matrix():
    theta = 0.7
    K = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    eigvals, _ = eigendecompose(K)
    assert abs(eigvals[0].imag) > 1e-6  # complex
    partner = find_conjugate_pairs(eigvals)
    assert partner[0] == 1 and partner[1] == 0
    assert np.isclose(eigvals[0], np.conj(eigvals[1]))


def test_mode_table_shares_sum_to_one_for_nontrivial_modes():
    eigvals = np.array([0.9 + 0j, 0.5 + 0j])
    ward_patterns = np.array([[0.6, 0.1], [0.3, 0.2], [0.1, 0.7]])  # 3 wards, 2 modes
    df = mode_table(eigvals, ward_patterns, rank_cutoff=2, group_names=["A", "B", "C"])
    for _, row in df.iterrows():
        total_share = row["share_A"] + row["share_B"] + row["share_C"]
        assert abs(total_share - 1.0) < 1e-9


def test_mode_table_period_for_known_rotation():
    theta = np.pi / 4  # eigenvalue e^{i*pi/4} -> period = 2*pi/(pi/4) = 8
    eigvals = np.array([np.exp(1j * theta), np.exp(-1j * theta)])
    ward_patterns = np.ones((2, 2))
    df = mode_table(eigvals, ward_patterns, rank_cutoff=2, group_names=["A", "B"])
    assert np.isclose(df.iloc[0]["period_weeks"], 8.0)


def test_dominant_ward_relevant_mode_skips_spurious_and_trivial():
    eigvals = np.array([1.0 + 0j, 0.95 + 0j, 1e-15 + 0j])
    # mode 0: trivial (zero ward pattern), mode 1: real, mode 2: spurious (beyond rank cutoff=2)
    ward_patterns = np.array([[0.0, 0.7, 5.0], [0.0, 0.3, 5.0]])
    df = mode_table(eigvals, ward_patterns, rank_cutoff=2, group_names=["A", "B"])
    dominant = dominant_ward_relevant_mode(df)
    assert dominant == 1


def test_dominant_mode_none_when_everything_filtered():
    eigvals = np.array([1.0 + 0j])
    ward_patterns = np.array([[0.0], [0.0]])
    df = mode_table(eigvals, ward_patterns, rank_cutoff=1, group_names=["A", "B"])
    assert dominant_ward_relevant_mode(df) is None


# ---- integration: real P6 D3 model ----

def test_d3_real_model_rank_cutoff_matches_empirical_gap():
    d = np.load(config.RESULTS_MODELS_DIR / "p6_edmd_D3.npz", allow_pickle=True)
    K = d["K"]
    cutoff = null_space_rank_cutoff(K)
    assert cutoff == 19  # matches P6's reported rank(K) exactly

    eigvals, eigvecs = eigendecompose(K)
    mags = np.abs(eigvals)
    # confirm the huge gap lands exactly at the cutoff boundary
    assert mags[cutoff - 1] / mags[cutoff] > 1e9


def test_d1_real_model_has_no_spurious_modes():
    d = np.load(config.RESULTS_MODELS_DIR / "p6_edmd_D1.npz", allow_pickle=True)
    K = d["K"]
    assert null_space_rank_cutoff(K) == K.shape[0]  # full rank -> nothing filtered
