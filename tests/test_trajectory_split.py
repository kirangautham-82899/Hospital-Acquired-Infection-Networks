"""Tests for src/trajectory_split.py (P5): 70/15/15 split, stratified by
scenario, reproducible, covering every trajectory exactly once."""
import pandas as pd

import config
from src.trajectory_split import make_split


def _synthetic_metadata(n_endemic=100, n_outbreak=100):
    rows = [{"trajectory": i, "scenario": "endemic"} for i in range(n_endemic)]
    rows += [{"trajectory": i, "scenario": "outbreak"} for i in range(n_endemic, n_endemic + n_outbreak)]
    return pd.DataFrame(rows)


def test_split_covers_every_trajectory_exactly_once():
    metadata = _synthetic_metadata()
    split = make_split(metadata, seed=1)
    assert sorted(split["trajectory"]) == sorted(metadata["trajectory"])
    assert split["trajectory"].duplicated().sum() == 0


def test_split_proportions_approximately_70_15_15_per_scenario():
    metadata = _synthetic_metadata(n_endemic=100, n_outbreak=100)
    split = make_split(metadata, seed=1)
    for scenario in ["endemic", "outbreak"]:
        counts = split[split["scenario"] == scenario]["split"].value_counts()
        assert counts["train"] == 70
        assert counts["val"] == 15
        assert counts["test"] == 15


def test_split_reproducible_with_same_seed():
    metadata = _synthetic_metadata()
    s1 = make_split(metadata, seed=42)
    s2 = make_split(metadata, seed=42)
    pd.testing.assert_frame_equal(s1, s2)


def test_split_differs_with_different_seed():
    metadata = _synthetic_metadata()
    s1 = make_split(metadata, seed=1)
    s2 = make_split(metadata, seed=2)
    assert not s1["split"].equals(s2["split"])


def test_split_on_real_trajectory_metadata_matches_expected_counts():
    metadata = pd.read_csv(config.RESULTS_TABLES_DIR / "p4_trajectories_metadata.csv")
    split = make_split(metadata)
    assert len(split) == len(metadata)
    for scenario in ["endemic", "outbreak"]:
        counts = split[split["scenario"] == scenario]["split"].value_counts()
        # 150 per scenario -> round(150*0.7)=105, round(150*0.15)=22, remainder=23
        assert counts["train"] == 105
        assert counts["val"] == 22
        assert counts["test"] == 23
