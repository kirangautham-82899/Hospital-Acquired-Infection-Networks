"""P5: the train/val/test split by trajectory, defined ONCE here.

70/15/15, stratified by scenario (endemic vs outbreak) so both splits keep
the same mix, fixed seed for reproducibility. P6 and every later phase
that touches the training trajectories must load the saved split
(data/processed/trajectory_split.csv) rather than re-deriving their own.
"""
import numpy as np
import pandas as pd

import config

TRAIN_FRAC = 0.70
VAL_FRAC = 0.15
TEST_FRAC = 0.15  # implied as the remainder; kept explicit for readability


def make_split(metadata, seed=None):
    """metadata: trajectory metadata (must have 'trajectory' and
    'scenario' columns, e.g. p4_trajectories_metadata.csv). Returns a
    DataFrame [trajectory, scenario, split] with split in
    {'train', 'val', 'test'}, computed independently within each scenario
    so the overall 70/15/15 ratio holds for endemic and outbreak alike."""
    seed = config.SEED if seed is None else seed
    rng = np.random.default_rng(seed)

    rows = []
    for scenario, group in metadata.groupby("scenario"):
        ids = group["trajectory"].to_numpy().copy()
        rng.shuffle(ids)
        n = len(ids)
        n_train = int(round(n * TRAIN_FRAC))
        n_val = int(round(n * VAL_FRAC))
        n_test = n - n_train - n_val  # remainder, so counts always sum to n regardless of rounding

        assignment = (
            [("train", tid) for tid in ids[:n_train]]
            + [("val", tid) for tid in ids[n_train : n_train + n_val]]
            + [("test", tid) for tid in ids[n_train + n_val :]]
        )
        for split, tid in assignment:
            rows.append({"trajectory": int(tid), "scenario": scenario, "split": split})

    return pd.DataFrame(rows).sort_values("trajectory").reset_index(drop=True)
