"""E9 (added after the second review, Nov 14): propagate the calibration
ridge through the whole downstream pipeline.

Why: P4 shows the decolonization rate gamma is identified only from
above (every grid gamma up to ~2e-3/day fits within
CALIBRATION_NEAR_OPTIMAL_TOL of the best loss). P5-P10 were built on ONE
point of that ridge, and comparing the first and second runs showed some
conclusions move with the point. E9 makes this explicit instead of
anecdotal.

For every grid value of gamma, beta and epsilon (config.E9_RIDGE_AXES)
inside the near-optimal set, take the other two parameters that minimise
the calibration loss at that value (the profile point); the union of these
points is rerun, with the same seeds as the main pipeline:
  P4  training trajectories              (src.trajectories)
  P5  dictionaries + split                (src.build_observables, src.trajectory_split)
  P6  EDMD fit with lambda selection      (src.build_edmd.build_for_dictionary)
  P7  dominant-mode shares + influence    (src.eigen, src.influence)
  P8  real holdout RMSE vs persistence    (src.forecast, src.metrics block bootstrap)
  P9  both ground truths + Spearman       (src.intervention, src.metrics.spearman_exact)
  P10 two budget cells, paired CIs        (src.intervention, src.metrics.paired_mean_ci)
Nothing here writes to the main P4-P10 outputs; results go to
results/tables/p11_e9_*.csv only.
"""
import numpy as np
import pandas as pd

import config
from src.baselines import build_real_weekly_states
from src.build_edmd import build_for_dictionary
from src.build_observables import apply_all_dictionaries, load_w
from src.eigen import dominant_ward_relevant_mode, eigendecompose, mode_table, mode_ward_patterns, null_space_rank_cutoff
from src.forecast import edmd_forecast_real, flatten_records, persistence_forecast_real
from src.influence import koopman_influence_scores, ward_sizes_in_network
from src.intervention import (
    equal_hours_scales,
    run_person_days_random_wards,
    run_person_days_replicates,
    scale_multiple_ward_edges,
    superspreader_experiment,
    ward_touching_seconds,
)
from src.metrics import block_bootstrap_rmse_diff, paired_mean_ci, spearman_exact
from src.risk import top_k_wards, ward_degree_centrality, ward_eigenvector_centrality
from src.simulate import daily_edge_arrays
from src.trajectories import generate_trajectories
from src.trajectory_split import make_split

RANDOM_WARD_SEED_BASE = 20261001  # same as src/build_p10.py, so 'random' draws match P10


def ridge_points(grid_table, tol=None, axes=None):
    """Near-optimal profile points. For each parameter in `axes` and each
    of its grid values whose best loss is within `tol` of the overall
    best, take the (beta, gamma, epsilon) row with the lowest loss at that
    value. Returns the UNION over axes (a point found on several profiles
    appears once), with an 'axes' column naming the profiles it lies on.
    Sorted by (gamma, beta, epsilon)."""
    tol = config.CALIBRATION_NEAR_OPTIMAL_TOL if tol is None else tol
    axes = config.E9_RIDGE_AXES if axes is None else axes
    best = grid_table["loss"].min()
    found = {}
    for axis in axes:
        idx = grid_table.groupby(axis)["loss"].idxmin()
        prof = grid_table.loc[idx]
        for i, row in prof[prof["loss"] <= best * (1.0 + tol)].iterrows():
            found.setdefault(i, []).append(axis)
    out = grid_table.loc[list(found)].copy()
    out["axes"] = ["+".join(found[i]) for i in out.index]
    return out.sort_values(["gamma", "beta", "epsilon"]).reset_index(drop=True)


def _fit_models(states, metadata, groups, W):
    """P5 + P6 on one set of trajectories. Returns {dict_name: result}
    where result is build_for_dictionary's output."""
    lifted = apply_all_dictionaries(states, groups, W)
    split_df = make_split(metadata)
    traj_scenario_map = dict(zip(metadata["trajectory"], metadata["scenario"]))
    trajectory_ids = metadata["trajectory"].to_numpy()
    sim = {"trajectory": trajectory_ids}
    for name, (features, names) in lifted.items():
        sim[f"{name}_features"] = features
        sim[f"{name}_feature_names"] = np.array(names)
    return {
        name: build_for_dictionary(name, sim, split_df, traj_scenario_map, trajectory_ids, groups)
        for name in config.EDMD_DICTIONARIES
    }


def _mode_share(result, groups):
    """Dominant ward-relevant mode's ward shares (same rule as P7)."""
    K = result["K"]
    eigvals, eigvecs = eigendecompose(K)
    patterns = mode_ward_patterns(eigvecs, result["C"], result["scaler"].scale_)
    df = mode_table(eigvals, patterns, null_space_rank_cutoff(K), groups)
    row = df[df["mode"] == dominant_ward_relevant_mode(df)].iloc[0]
    return pd.Series({g: row[f"share_{g}"] for g in groups})


def _forecast_rows(models, groups, W, states_real, states_cf):
    """P8 holdout: RMSE minus persistence (block bootstrap) per model and h."""
    weekly = build_real_weekly_states(states_real, states_cf, groups, weeks=range(config.N_WEEKS))
    records = persistence_forecast_real(weekly, states_real, groups, config.EDMD_MAX_HORIZON)
    for name, res in models.items():
        model = {"K": res["K"], "scaler": res["scaler"], "feature_names": res["feature_names"]}
        records += edmd_forecast_real(model, weekly, states_real, groups, config.EDMD_MAX_HORIZON, name, W=W)
    long_df = flatten_records(records, groups)
    hold = long_df[long_df["period"] == "holdout"]
    rows = []
    for h, g in hold.groupby("h"):
        base = g[g["model"] == "persistence"]
        for name in models:
            r = block_bootstrap_rmse_diff(g[g["model"] == name], base)
            rows.append({"h": h, "model": name, "rmse_diff": r["rmse_diff"], "ci_low": r["ci_low"],
                         "ci_high": r["ci_high"]})
    return rows


def run_point(point, setup, n_gt_replicates=None, n_int_replicates=None, n_eq_replicates=None):
    """Rerun P4 trajectories -> P10 subset at one (beta, gamma, epsilon).
    Returns a dict of DataFrames: params, forecast, ranking, interventions."""
    n_gt = config.ROBUSTNESS_N_REPLICATES if n_gt_replicates is None else n_gt_replicates
    n_eq = config.P9_EQUAL_HOURS_N_REPLICATES if n_eq_replicates is None else n_eq_replicates
    n_int = config.INTERVENTION_N_REPLICATES if n_int_replicates is None else n_int_replicates
    beta, gamma, epsilon = float(point["beta"]), float(point["gamma"]), float(point["epsilon"])
    groups = setup["groups"]
    tag = {"gamma": gamma, "beta": beta, "epsilon": epsilon, "axes": point.get("axes", "")}

    # ---- P4 trajectories (same seeds as the main run) + P5/P6 ----
    states, metadata = generate_trajectories(
        config.N_TRAINING_TRAJECTORIES, setup["people"], setup["index"], setup["day_list"],
        setup["edge_arrays"], setup["admission"], {"beta": beta, "gamma": gamma, "epsilon": epsilon},
        setup["states_real"], groups=groups,
    )
    models = _fit_models(states, metadata, groups, setup["W"])
    params = [{**tag, "loss": float(point["loss"]), "dictionary": n,
               "spectral_radius": float(np.max(np.abs(r["eigvals"]))), "best_lambda": r["best_lambda"],
               "sim_test_skill_h1": _sim_skill(r, 1), "sim_test_skill_h4": _sim_skill(r, 4)}
              for n, r in models.items()]

    # ---- P8 ----
    forecast = [{**tag, **row} for row in _forecast_rows(models, groups, setup["W"], setup["states_real"],
                                                         setup["states_cf"])]

    # ---- P7 scores ----
    scores = {"degree_centrality": setup["degree"], "eigenvector_centrality": setup["eigenvector"]}
    for name, res in models.items():
        scores[f"koopman_{name}"] = _mode_share(res, groups)
        model = {"K": res["K"], "scaler": res["scaler"], "feature_names": res["feature_names"]}
        inf = koopman_influence_scores(model, name, setup["x_base"], setup["sizes"], groups, W=setup["W"])
        scores[f"koopman_influence_{name}"] = inf.set_index("ward")["influence_total"].reindex(groups)

    # ---- P9 ground truths ----
    common = (setup["people"], setup["index"], setup["day_list"], setup["edges"], setup["admission"],
              beta, gamma, epsilon, setup["pre_window_last_status"], groups)
    gt_a, _ = superspreader_experiment(*common, n_replicates=n_gt, cut_fraction=0.5)
    gt_b, _ = superspreader_experiment(*common, n_replicates=n_eq, ward_scales=setup["eq_scales"])
    gts = {"pct50": gt_a.set_index("ward")["drop_person_days_mean"].reindex(groups),
           "equal_hours": gt_b.set_index("ward")["drop_person_days_mean"].reindex(groups)}
    ranking = []
    for gt_name, gt in gts.items():
        for cand, sc in scores.items():
            rho, p = spearman_exact(gt.to_numpy(), sc.reindex(groups).to_numpy())
            ranking.append({**tag, "ground_truth": gt_name, "candidate": cand, "spearman_rho": rho,
                            "p_value_exact": p, "top_ward": sc.idxmax()})

    # ---- P10 subset ----
    interventions = _intervention_cells(setup, beta, gamma, epsilon, scores, n_int, tag)

    return {"params": pd.DataFrame(params), "forecast": pd.DataFrame(forecast),
            "ranking": pd.DataFrame(ranking), "interventions": pd.DataFrame(interventions)}


def _sim_skill(result, h):
    m = result["metrics"]
    row = m[(m["split"] == "test") & (m["ward"] == "overall") & (m["scenario"] == "overall")
            & (m["h"] == h) & (m["model"].str.startswith("edmd_"))]
    return float(row["skill_vs_persistence"].iloc[0])


def _intervention_cells(setup, beta, gamma, epsilon, scores, n_rep, tag):
    """For each (k, R) in config.E9_INTERVENTION_CELLS: paired advantage of
    every targeted strategy over random and whole-hospital, and of every
    Koopman strategy over degree-targeted."""
    from src.calibrate_sim import replicate_seed_pairs

    groups = setup["groups"]
    seed_pairs = replicate_seed_pairs(n_rep)
    sim_args = (beta, gamma, epsilon, setup["pre_window_last_status"], setup["admission"], seed_pairs)

    def run(wards, scale):
        edges = scale_multiple_ward_edges(setup["edges"], setup["admission"], wards, scale=scale)
        return run_person_days_replicates(setup["people"], setup["index"], setup["day_list"],
                                          daily_edge_arrays(edges, setup["index"]), *sim_args)

    rows = []
    for k, R in config.E9_INTERVENTION_CELLS:
        whole = run(groups, 1.0 - k * R / len(groups))
        rand, _ = run_person_days_random_wards(
            setup["people"], setup["index"], setup["day_list"], setup["edges"], setup["admission"], groups, k,
            1.0 - R, beta, gamma, epsilon, setup["pre_window_last_status"], seed_pairs, RANDOM_WARD_SEED_BASE)
        cache = {}
        totals = {}
        for cand in ["degree_centrality"] + [c for c in scores if c.startswith("koopman")]:
            wards = top_k_wards(scores[cand], k)
            key = tuple(sorted(wards))
            if key not in cache:
                cache[key] = run(wards, 1.0 - R)
            totals[cand] = (wards, cache[key])
        for cand, (wards, tot) in totals.items():
            refs = {"random": rand, "whole_hospital": whole}
            if cand != "degree_centrality":
                refs["degree_centrality"] = totals["degree_centrality"][1]
            for ref_name, ref in refs.items():
                ci = paired_mean_ci(ref - tot)
                rows.append({**tag, "k": k, "R": R, "strategy": cand, "wards": ",".join(wards),
                             "reference": ref_name, "advantage_mean": ci["mean"], "ci_low": ci["ci_low"],
                             "ci_high": ci["ci_high"],
                             "verdict": "better" if ci["ci_low"] > 0 else ("worse" if ci["ci_high"] < 0
                                                                          else "not distinguishable")})
    return rows


def build_setup(common_setup):
    """Add what E9 needs on top of src.robustness.build_common_setup()."""
    from src.build_simulation import load_p4_inputs

    s = dict(common_setup)
    groups = s["groups"]
    p4 = load_p4_inputs("all")
    assert p4["people"] == s["people"], "P4 and P9 person orderings differ"
    s["edge_arrays"] = p4["edge_arrays_by_day"]
    s["states_real"] = pd.read_csv(config.RESULTS_TABLES_DIR / "p3_states_real.csv")
    s["states_cf"] = pd.read_csv(config.DATA_PROCESSED_DIR / "states_real_carry_forward_SENSITIVITY_ONLY.csv")
    s["W"], _ = load_w("all")
    W_raw = pd.read_csv(config.RESULTS_TABLES_DIR / "p2_ward_matrix_raw_all.csv", index_col=0).loc[groups, groups]
    s["degree"] = ward_degree_centrality(W_raw.to_numpy(), groups)
    s["eigenvector"] = ward_eigenvector_centrality(W_raw.to_numpy(), groups)
    calib = s["states_real"][s["states_real"]["week"].isin(config.CALIBRATION_WEEKS)]
    s["x_base"] = calib.groupby("group")["prevalence"].mean().reindex(groups).to_numpy()
    s["sizes"] = ward_sizes_in_network(s["admission"], set(s["people"]), groups)
    touching = ward_touching_seconds(s["edges"], s["admission"], groups)
    s["eq_scales"] = equal_hours_scales(touching, config.P9_EQUAL_HOURS_FRACTION_OF_MIN)
    return s


def e9_calibration_ridge(common_setup):
    """Run every ridge point. Returns (points, {table_name: DataFrame})."""
    grid = pd.read_csv(config.RESULTS_TABLES_DIR / "p4_calibration_grid.csv")
    points = ridge_points(grid)
    setup = build_setup(common_setup)
    parts = {"params": [], "forecast": [], "ranking": [], "interventions": []}
    for _, point in points.iterrows():
        print(f"  ridge point gamma={point['gamma']:.3g} beta={point['beta']:.3g} "
              f"epsilon={point['epsilon']:.3g} loss={point['loss']:.5f} (profile: {point['axes']})", flush=True)
        out = run_point(point, setup)
        for key in parts:
            parts[key].append(out[key])
    return points, {k: pd.concat(v, ignore_index=True) for k, v in parts.items()}
