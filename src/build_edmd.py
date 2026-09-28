"""P6 orchestrator: fit ridge-regularized EDMD (D1/D2/D3), select lambda
per dictionary on the validation split (mean RMSE over forecast horizons
1-4, in original prevalence units via the readout C), and report
train/val/test metrics, baselines, skill scores, and spectral diagnostics.

K is fit on TRAINING trajectories only; the test split is touched exactly
once, at the very end, for final reporting. Real data is NOT forecast
here -- that is P8.

Writes:
  results/models/p6_edmd_<dict>.npz          (K, scaler mean_/scale_, C, lambda, feature_names)
  results/tables/p6_lambda_selection_<dict>.csv
  results/tables/p6_metrics_<dict>.csv        (train/val/test x h1-4 x ward x scenario, model + baselines + skill)
  results/tables/p6_spectral_<dict>.csv
  results/tables/p6_effective_rank.csv
  results/figures/p6_lambda_curve_<dict>.png
  results/figures/p6_predicted_vs_actual_<dict>.png
"""
import numpy as np
import pandas as pd

import config
from src.edmd import (
    ConstantAwareScaler,
    build_pairs_within_trajectory,
    compute_metrics_table,
    eigenvalues_outside_unit_circle,
    evaluate_forecast,
    persistence_forecast,
    ridge_fit,
    selector_matrix,
    spectral_radius,
    training_mean_forecast,
)


def load_p6_inputs():
    sim = np.load(config.DATA_PROCESSED_DIR / "observables_sim.npz", allow_pickle=True)
    split_df = pd.read_csv(config.DATA_PROCESSED_DIR / "trajectory_split.csv")
    metadata = pd.read_csv(config.RESULTS_TABLES_DIR / "p4_trajectories_metadata.csv")
    traj_scenario_map = dict(zip(metadata["trajectory"], metadata["scenario"]))
    trajectory_ids = sim["trajectory"]
    groups = list(sim["groups"])
    return sim, split_df, traj_scenario_map, trajectory_ids, groups


def lambda_selection_criterion(K, scaler, group_indices, features, trajectory_ids, split_df):
    """Mean RMSE over horizons 1..EDMD_MAX_HORIZON on the VALIDATION
    split, overall (all wards, all trajectories) -- the single scalar used
    to pick lambda. n_weeks is taken from `features` itself, not
    config.N_WEEKS, so this works correctly on any array shape (e.g. in
    tests with a small synthetic number of weeks), not just the real
    17-week trajectories."""
    results = evaluate_forecast(
        K, scaler, group_indices, features, trajectory_ids, split_df, "val",
        config.EDMD_MAX_HORIZON, features.shape[1],
    )
    horizon_rmses = []
    for r in results:
        rmse = np.sqrt(np.mean((r["pred"] - r["actual"]) ** 2))
        horizon_rmses.append(rmse)
    return float(np.mean(horizon_rmses))


def select_lambda(X_train_s, Y_train_s, scaler, group_indices, features, trajectory_ids, split_df,
                   lambda_grid, max_rounds=1):
    """Evaluate every lambda in lambda_grid, widen the grid once (3x
    extension in the hugged direction) if the best value sits on an edge,
    per the same pattern used in P4."""
    grid = list(lambda_grid)
    for round_i in range(max_rounds + 1):
        rows = []
        for lam in grid:
            K = ridge_fit(X_train_s, Y_train_s, lam)
            criterion = lambda_selection_criterion(K, scaler, group_indices, features, trajectory_ids, split_df)
            rows.append({"lambda": lam, "val_rmse_h1_4": criterion})
        table = pd.DataFrame(rows).sort_values("val_rmse_h1_4").reset_index(drop=True)
        best_lam = table.iloc[0]["lambda"]

        if round_i >= max_rounds:
            break
        if np.isclose(best_lam, min(grid)):
            grid = list(np.geomspace(min(grid) / 3.0, max(grid), len(grid)))
        elif np.isclose(best_lam, max(grid)):
            grid = list(np.geomspace(min(grid), max(grid) * 3.0, len(grid)))
        else:
            break
    return table, best_lam


def build_for_dictionary(name, sim, split_df, traj_scenario_map, trajectory_ids, groups):
    features = sim[f"{name}_features"]
    feature_names = list(sim[f"{name}_feature_names"])
    n_weeks = features.shape[1]

    X_train, Y_train, _ = build_pairs_within_trajectory(features, trajectory_ids, split_df, "train")
    scaler = ConstantAwareScaler().fit(X_train)
    X_train_s = scaler.transform(X_train)
    Y_train_s = scaler.transform(Y_train)

    C = selector_matrix(feature_names, groups)
    group_indices = [feature_names.index(f"x_{g}") for g in groups]

    lambda_table, best_lambda = select_lambda(
        X_train_s, Y_train_s, scaler, group_indices, features, trajectory_ids, split_df, config.EDMD_LAMBDA_GRID
    )
    K = ridge_fit(X_train_s, Y_train_s, best_lambda)

    # ---- metrics on train/val/test, model + baselines ----
    train_mean_vector = features[:, :, group_indices][
        np.isin(trajectory_ids, split_df.loc[split_df["split"] == "train", "trajectory"])
    ].reshape(-1, len(groups)).mean(axis=0)

    metrics_tables = []
    for split_name in ["train", "val", "test"]:
        model_results = evaluate_forecast(
            K, scaler, group_indices, features, trajectory_ids, split_df, split_name,
            config.EDMD_MAX_HORIZON, n_weeks,
        )
        persist_results = persistence_forecast(
            features, trajectory_ids, split_df, split_name, group_indices, config.EDMD_MAX_HORIZON, n_weeks
        )
        mean_results = training_mean_forecast(
            train_mean_vector, features, trajectory_ids, split_df, split_name, group_indices,
            config.EDMD_MAX_HORIZON, n_weeks,
        )
        model_table = compute_metrics_table(model_results, traj_scenario_map, groups, f"edmd_{name}")
        persist_table = compute_metrics_table(persist_results, traj_scenario_map, groups, "persistence")
        mean_table = compute_metrics_table(mean_results, traj_scenario_map, groups, "training_mean")

        combined = pd.concat([model_table, persist_table, mean_table], ignore_index=True)
        combined.insert(0, "split", split_name)
        metrics_tables.append(combined)

    metrics = pd.concat(metrics_tables, ignore_index=True)

    persist_lookup = metrics[metrics["model"] == "persistence"].set_index(["split", "h", "ward", "scenario"])["rmse"]

    def skill(row):
        key = (row["split"], row["h"], row["ward"], row["scenario"])
        persist_rmse = persist_lookup.get(key, np.nan)
        if not persist_rmse or persist_rmse == 0:
            return np.nan
        return 1.0 - row["rmse"] / persist_rmse

    metrics["skill_vs_persistence"] = metrics.apply(skill, axis=1)

    # ---- spectral diagnostics ----
    eigvals, outside = eigenvalues_outside_unit_circle(K)
    spectral = pd.DataFrame(
        [{"dictionary": name, "spectral_radius": spectral_radius(K), "n_eigenvalues_outside_unit_circle": len(outside),
          "n_eigenvalues_total": len(eigvals), "best_lambda": best_lambda}]
    )

    return {
        "K": K, "scaler": scaler, "C": C, "feature_names": feature_names, "group_indices": group_indices,
        "best_lambda": best_lambda, "lambda_table": lambda_table, "metrics": metrics, "spectral": spectral,
        "eigvals": eigvals, "features": features, "trajectory_ids": trajectory_ids,
    }


def _lambda_curve_plot(name, lambda_table, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    sorted_table = lambda_table.sort_values("lambda")
    ax.plot(sorted_table["lambda"], sorted_table["val_rmse_h1_4"], "o-")
    ax.set_xscale("log")
    ax.set_xlabel("lambda")
    ax.set_ylabel("validation mean RMSE (h=1-4)")
    ax.set_title(f"{name}: lambda selection")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _predicted_vs_actual_plot(name, result, groups, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    K, scaler, group_indices = result["K"], result["scaler"], result["group_indices"]
    features, trajectory_ids = result["features"], result["trajectory_ids"]
    split_df = pd.read_csv(config.DATA_PROCESSED_DIR / "trajectory_split.csv")

    test_results = evaluate_forecast(
        K, scaler, group_indices, features, trajectory_ids, split_df, "test", 1, features.shape[1]
    )
    pred = test_results[0]["pred"]
    actual = test_results[0]["actual"]

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(actual.ravel(), pred.ravel(), s=8, alpha=0.4)
    lims = [0, max(actual.max(), pred.max(), 1.0)]
    ax.plot(lims, lims, "k--", linewidth=1)
    ax.set_xlabel("actual prevalence (test, h=1)")
    ax.set_ylabel("predicted prevalence (test, h=1)")
    ax.set_title(f"{name}: predicted vs actual (1-step, test)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def build():
    config.RESULTS_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    sim, split_df, traj_scenario_map, trajectory_ids, groups = load_p6_inputs()

    print("P6 EDMD BUILD SUMMARY")
    print("=" * 60)

    rank_rows = []
    spectral_rows = []
    for name in config.EDMD_DICTIONARIES:
        print(f"\n[{name}]")
        result = build_for_dictionary(name, sim, split_df, traj_scenario_map, trajectory_ids, groups)

        result["lambda_table"].to_csv(config.RESULTS_TABLES_DIR / f"p6_lambda_selection_{name}.csv", index=False)
        result["metrics"].to_csv(config.RESULTS_TABLES_DIR / f"p6_metrics_{name}.csv", index=False)
        result["spectral"].to_csv(config.RESULTS_TABLES_DIR / f"p6_spectral_{name}.csv", index=False)
        spectral_rows.append(result["spectral"].iloc[0].to_dict())

        rank = int(np.linalg.matrix_rank(result["K"]))
        rank_rows.append({"dictionary": name, "n_features": len(result["feature_names"]), "rank_of_K": rank})

        np.savez(
            config.RESULTS_MODELS_DIR / f"p6_edmd_{name}.npz",
            K=result["K"], scaler_mean=result["scaler"].mean_, scaler_scale=result["scaler"].scale_,
            C=result["C"], feature_names=np.array(result["feature_names"]), best_lambda=result["best_lambda"],
            groups=np.array(groups),
        )

        _lambda_curve_plot(name, result["lambda_table"], config.RESULTS_FIGURES_DIR / f"p6_lambda_curve_{name}.png")
        _predicted_vs_actual_plot(
            name, result, groups, config.RESULTS_FIGURES_DIR / f"p6_predicted_vs_actual_{name}.png"
        )

        test_overall = result["metrics"][
            (result["metrics"]["split"] == "test") & (result["metrics"]["ward"] == "overall")
            & (result["metrics"]["scenario"] == "overall") & (result["metrics"]["h"] == 1)
        ]
        print(f"  best lambda={result['best_lambda']:.4g}, spectral radius={result['spectral'].iloc[0]['spectral_radius']:.4f}, "
              f"eigenvalues outside unit circle={result['spectral'].iloc[0]['n_eigenvalues_outside_unit_circle']}")
        print(f"  rank(K)={rank} of {len(result['feature_names'])} features")
        print("  test set, h=1, overall RMSE by model:")
        print(test_overall[["model", "rmse", "rmse_clipped", "skill_vs_persistence"]].to_string(index=False))

    pd.DataFrame(rank_rows).to_csv(config.RESULTS_TABLES_DIR / "p6_effective_rank.csv", index=False)
    pd.DataFrame(spectral_rows).to_csv(config.RESULTS_TABLES_DIR / "p6_spectral_summary.csv", index=False)

    print("\nEffective rank per dictionary:")
    print(pd.DataFrame(rank_rows).to_string(index=False))


if __name__ == "__main__":
    build()
