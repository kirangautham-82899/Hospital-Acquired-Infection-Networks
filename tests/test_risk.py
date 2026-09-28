"""Tests for src/risk.py (P9): ward centrality measures against
hand-checkable small graphs (star, path), and an integration check that
the Koopman risk score loader matches P7's real saved output."""
import numpy as np
import pandas as pd
import pytest

import config
from src.risk import (
    load_koopman_risk_scores,
    top_k_wards,
    ward_betweenness_centrality,
    ward_degree_centrality,
    ward_eigenvector_centrality,
)


def test_ward_degree_centrality_matches_row_sum():
    W = np.array([[1.0, 2.0, 3.0], [0.5, 1.5, 0.0], [4.0, 0.0, 1.0]])
    groups = ["A", "B", "C"]
    out = ward_degree_centrality(W, groups)
    assert np.allclose(out.values, [6.0, 2.0, 5.0])
    assert list(out.index) == groups


def test_eigenvector_centrality_highest_at_star_hub():
    # star graph: node 0 (hub) connected to 1,2,3; no other edges
    n = 4
    W = np.zeros((n, n))
    for i in range(1, n):
        W[0, i] = W[i, 0] = 1.0
    groups = ["hub", "leaf1", "leaf2", "leaf3"]
    out = ward_eigenvector_centrality(W, groups)
    assert out["hub"] > out["leaf1"]
    assert out["hub"] > out["leaf2"]
    assert out["hub"] > out["leaf3"]
    # leaves should all be equal by symmetry
    assert abs(out["leaf1"] - out["leaf2"]) < 1e-9


def test_betweenness_centrality_highest_at_path_middle():
    # path graph: A-B-C (no direct A-C edge) -> B sits between every pair
    W = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 1.0], [0.0, 1.0, 0.0]])
    groups = ["A", "B", "C"]
    out = ward_betweenness_centrality(W, groups)
    assert out["B"] > out["A"]
    assert out["B"] > out["C"]
    assert out["A"] == out["C"] == 0.0  # endpoints of a 3-node path have 0 betweenness


def test_load_koopman_risk_scores_matches_real_p7_output():
    real = pd.read_csv(config.RESULTS_TABLES_DIR / "p7_dominant_mode_ward_ranking.csv")
    for dict_name in config.EDMD_DICTIONARIES:
        scores = load_koopman_risk_scores(dict_name, config.WARD_GROUPS)
        assert abs(scores.sum() - 1.0) < 1e-9  # shares sum to 1
        expected = real[real["dictionary"] == dict_name].set_index("ward")["share"]
        for g in config.WARD_GROUPS:
            assert abs(scores[g] - expected[g]) < 1e-12


def test_top_k_wards_picks_highest_scores():
    score = pd.Series([0.5, 0.1, 0.3, 0.9], index=["A", "B", "C", "D"])
    assert top_k_wards(score, 1) == ["D"]
    assert top_k_wards(score, 2) == ["D", "A"]
    assert top_k_wards(score, 4) == ["D", "A", "C", "B"]
