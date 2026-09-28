"""P5 orchestrator: apply the D1/D2/D3 dictionaries to all 300 simulated
trajectories, define and save the train/val/test split, and report the
conditioning of each dictionary's lifted training matrix (early warning
for P6's ridge regression).

Writes:
  data/processed/trajectory_split.csv        (70/15/15 by trajectory, stratified by scenario)
  data/processed/observables_sim.npz         (D1/D2/D3 lifted features for all 300 trajectories)
  results/tables/p5_trajectory_split.csv     (reporting copy)
  results/tables/p5_feature_names_*.csv      (one per dictionary)
  results/tables/p5_lifted_matrix_conditioning.csv

Real-data gap filling (src/real_state_fill.py) is built and tested in this
phase but NOT applied here -- see its module docstring and
research_log.md: K is never fit on real data, so it's only needed
starting in P8.
"""
import numpy as np
import pandas as pd

import config
from src.observables import DICTIONARIES, d3_contact_weighted
from src.trajectory_split import make_split


def load_w(population="all"):
    tag = "all" if population == "all" else "patients_only"
    w = pd.read_csv(config.RESULTS_TABLES_DIR / f"p2_ward_matrix_W_{tag}.csv", index_col=0)
    groups = config.WARD_GROUPS if population == "all" else [g for g in config.WARD_GROUPS if g != "Other"]
    assert list(w.index) == groups, f"W row order {list(w.index)} != state group order {groups}"
    assert list(w.columns) == groups, f"W column order {list(w.columns)} != state group order {groups}"
    return w.to_numpy(), groups


def apply_all_dictionaries(states, group_names, W):
    """states: [n_trajectories, n_weeks, n_groups]. Returns
    {name: (features [n_trajectories, n_weeks, n_features], feature_names)}."""
    out = {}
    for name, fn in DICTIONARIES.items():
        if name == "D3":
            out[name] = d3_contact_weighted(states, group_names, W)
        else:
            out[name] = fn(states, group_names)
    return out


def lifted_training_matrix(features, split_df, scenario_agnostic=True):
    """Stack phi(x_t) for t = 0..N_WEEKS-2 (the EDMD 'source' snapshots)
    across only the trajectories tagged 'train' in split_df. Returns a 2D
    [n_train_trajectories * (N_WEEKS-1), n_features] matrix."""
    train_ids = split_df.loc[split_df["split"] == "train", "trajectory"].to_numpy()
    source = features[train_ids, :-1, :]  # drop the last week (no "next" state to pair with)
    return source.reshape(-1, source.shape[-1])


def build(population=None):
    population = config.DEFAULT_SIMULATION_POPULATION if population is None else population
    config.DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)

    sim = np.load(config.DATA_PROCESSED_DIR / "states_sim.npz", allow_pickle=True)
    states = sim["states"]
    groups_in_sim = list(sim["groups"])
    metadata = pd.read_csv(config.RESULTS_TABLES_DIR / "p4_trajectories_metadata.csv")

    W, groups_w = load_w(population)
    assert groups_w == groups_in_sim, (
        f"W's group order {groups_w} does not match states_sim.npz's group order {groups_in_sim}"
    )

    print("P5 OBSERVABLES BUILD SUMMARY")
    print("=" * 60)
    print(f"states shape: {states.shape} [trajectory, week, group], groups={groups_in_sim}")

    split_df = make_split(metadata)
    split_df.to_csv(config.DATA_PROCESSED_DIR / "trajectory_split.csv", index=False)
    split_df.to_csv(config.RESULTS_TABLES_DIR / "p5_trajectory_split.csv", index=False)
    counts = split_df.groupby(["scenario", "split"]).size().unstack(fill_value=0)
    print("\nTrain/val/test split (by scenario):")
    print(counts.to_string())

    lifted = apply_all_dictionaries(states, groups_in_sim, W)

    npz_payload = {"trajectory": metadata["trajectory"].to_numpy(), "groups": np.array(groups_in_sim)}
    conditioning_rows = []
    for name, (features, feature_names) in lifted.items():
        npz_payload[f"{name}_features"] = features
        npz_payload[f"{name}_feature_names"] = np.array(feature_names)
        pd.DataFrame({"feature_name": feature_names}).to_csv(
            config.RESULTS_TABLES_DIR / f"p5_feature_names_{name}.csv", index=False
        )

        train_matrix = lifted_training_matrix(features, split_df)
        cond = np.linalg.cond(train_matrix)
        conditioning_rows.append(
            {
                "dictionary": name, "n_features": len(feature_names),
                "n_train_snapshots": train_matrix.shape[0], "condition_number": cond,
            }
        )
        print(f"\n[{name}] {len(feature_names)} features: {feature_names}")
        print(f"  training snapshot matrix: {train_matrix.shape}, condition number = {cond:.4g}")

    np.savez(config.DATA_PROCESSED_DIR / "observables_sim.npz", **npz_payload)

    conditioning_df = pd.DataFrame(conditioning_rows)
    conditioning_df.to_csv(config.RESULTS_TABLES_DIR / "p5_lifted_matrix_conditioning.csv", index=False)

    return {"split": split_df, "lifted": lifted, "conditioning": conditioning_df}


if __name__ == "__main__":
    build()
