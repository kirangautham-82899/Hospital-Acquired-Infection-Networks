"""P11: robustness experiments E1-E8.

CLAUDE.md names this phase "robustness experiments E1-E8" but does not
define what E1-E8 are (unlike P1-P10, which had explicit locked
decisions). Designed here to directly probe the soft spots this project
has already flagged in its own research_log.md and CLAUDE.md's known
limitations section, rather than invented from nothing -- each
experiment below cites exactly which prior finding it is stress-testing.
Every experiment reports a Spearman rho (or equivalent stability metric)
between a baseline result and a perturbed re-run, so "how robust is this"
has one consistent, comparable answer format throughout.

E1 seed sensitivity            -- P9's ground truth used one base seed
E2 lambda sensitivity          -- P6 found a remarkably FLAT lambda curve
E3 replicate-count sensitivity -- P9/P10 used 100/200 replicates
E4 calibration ridge-point     -- P4 found gamma sits on a wide loss ridge
E5 W time-window               -- P5 flagged W spans the holdout period
E6 patients-only population    -- decision #3's sensitivity run, deferred
                                   at every phase since P2
E7 missing-data handling       -- decision #6's carry-forward sensitivity
                                   run, built in P3, unused until now
E8 D3 structural redundancy    -- P6/P7 proved D3 subseteq span(D2)
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import config
from src.edmd import ConstantAwareScaler, ridge_fit, selector_matrix
from src.forecast import edmd_forecast_real, flatten_records
from src.intervention import superspreader_experiment
from src.load import load_admission, load_contacts
from src.metrics import compute_metrics_from_long
from src.network import assign_week, build_master_edge_list, ward_contact_matrix
from src.risk import ward_degree_centrality
from src.simulate import build_person_index, simulation_day_list
from src.wards import person_ward_map


def rank_stability(baseline_scores, alt_scores, groups):
    """Spearman rho (and p-value) between two ward-indexed score Series
    over the same groups -- the standard stability metric used
    throughout this module."""
    b = baseline_scores.reindex(groups).to_numpy(dtype=float)
    a = alt_scores.reindex(groups).to_numpy(dtype=float)
    rho, pval = spearmanr(b, a)
    return float(rho), float(pval)


def build_common_setup():
    """Shared inputs reused by most experiments below: the full
    population/network/edges (mirrors P9/P10's setup exactly, so results
    are directly comparable to the saved P9/P10 baselines)."""
    admission = load_admission(config.ADMISSION_CSV)
    contacts = load_contacts(config.CONTACTS_CSV)
    edges = build_master_edge_list(contacts)
    people_set = set(contacts["from"]) | set(contacts["to"])
    people, index = build_person_index(people_set)
    day_list = simulation_day_list()
    pre_window_last_status = pd.read_csv(config.DATA_PROCESSED_DIR / "states_pre_window_last_status.csv")
    calibrated = pd.read_csv(config.RESULTS_TABLES_DIR / "p4_calibrated_params.csv").iloc[0]
    return {
        "admission": admission, "contacts": contacts, "edges": edges,
        "people": people, "index": index, "day_list": day_list,
        "pre_window_last_status": pre_window_last_status,
        "beta": float(calibrated["beta"]), "gamma": float(calibrated["gamma"]),
        "epsilon": float(calibrated["epsilon"]), "groups": config.WARD_GROUPS,
    }


# ---------------------------------------------------------------- E1 ----

def e1_seed_sensitivity(setup):
    """Rerun P9's ground-truth experiment with a different global seed
    (config.ROBUSTNESS_ALT_SEED instead of P9's default config.SEED).
    Tests whether the ward ranking that P9/P10's conclusions rest on is
    an artifact of one particular seed."""
    original = pd.read_csv(config.RESULTS_TABLES_DIR / "p9_ground_truth_intervention.csv").set_index("ward")[
        "drop_person_days_mean"
    ]
    alt, _ = superspreader_experiment(
        setup["people"], setup["index"], setup["day_list"], setup["edges"], setup["admission"],
        setup["beta"], setup["gamma"], setup["epsilon"], setup["pre_window_last_status"], setup["groups"],
        n_replicates=config.ROBUSTNESS_N_REPLICATES, base_seed=config.ROBUSTNESS_ALT_SEED,
    )
    alt_scores = alt.set_index("ward")["drop_person_days_mean"]
    rho, pval = rank_stability(original, alt_scores, setup["groups"])
    return {"experiment": "E1_seed_sensitivity", "rho_vs_baseline": rho, "p_value": pval,
            "note": f"alt_seed={config.ROBUSTNESS_ALT_SEED}, n_replicates={config.ROBUSTNESS_N_REPLICATES}"}


# ---------------------------------------------------------------- E2 ----

def e2_lambda_sensitivity(dict_name, multiplier):
    """Refit K for one dictionary at lambda = (P6-selected lambda) *
    multiplier, using the SAME training pairs and scaler as P6 (only
    lambda differs), then re-run P8's real-data holdout forecast and
    compare h=1 overall RMSE to P6's selected-lambda result. Tests P6's
    finding that the lambda-selection curve was remarkably flat (see
    p6_lambda_curve_D3.png) -- does forecast quality on REAL data (not
    just the validation criterion lambda was selected on) actually stay
    stable across orders of magnitude of lambda?"""
    sim = np.load(config.DATA_PROCESSED_DIR / "observables_sim.npz", allow_pickle=True)
    split_df = pd.read_csv(config.DATA_PROCESSED_DIR / "trajectory_split.csv")
    trajectory_ids = sim["trajectory"]
    groups = list(sim["groups"])
    features = sim[f"{dict_name}_features"]

    from src.edmd import build_pairs_within_trajectory

    X_train, Y_train, _ = build_pairs_within_trajectory(features, trajectory_ids, split_df, "train")

    model_npz = np.load(config.RESULTS_MODELS_DIR / f"p6_edmd_{dict_name}.npz", allow_pickle=True)
    scaler = ConstantAwareScaler()
    scaler.mean_ = model_npz["scaler_mean"]
    scaler.scale_ = model_npz["scaler_scale"]
    selected_lambda = float(model_npz["best_lambda"])
    feature_names = list(model_npz["feature_names"])
    C = model_npz["C"]

    alt_lambda = selected_lambda * multiplier
    K_alt = ridge_fit(scaler.transform(X_train), scaler.transform(Y_train), alt_lambda)

    W = pd.read_csv(config.RESULTS_TABLES_DIR / "p2_ward_matrix_W_all.csv", index_col=0).to_numpy()
    states_real = pd.read_csv(config.RESULTS_TABLES_DIR / "p3_states_real.csv")
    states_cf = pd.read_csv(config.DATA_PROCESSED_DIR / "states_real_carry_forward_SENSITIVITY_ONLY.csv")
    from src.baselines import build_real_weekly_states

    weekly_states = build_real_weekly_states(states_real, states_cf, groups, weeks=range(config.N_WEEKS))
    model_alt = {"K": K_alt, "scaler": scaler, "C": C, "feature_names": feature_names, "groups": groups}
    records = edmd_forecast_real(model_alt, weekly_states, states_real, groups, config.EDMD_MAX_HORIZON, dict_name, W=W)
    long_df = flatten_records(records, groups)
    metrics = compute_metrics_from_long(long_df, group_by=["period", "h"])

    row = metrics[
        (metrics["model"] == dict_name) & (metrics["period"] == "holdout")
        & (metrics["h"] == 1) & (metrics["ward"] == "overall")
    ]
    alt_rmse = float(row["rmse"].iloc[0]) if len(row) else np.nan

    p8_metrics = pd.read_csv(config.RESULTS_TABLES_DIR / "p8_metrics.csv")
    base_row = p8_metrics[
        (p8_metrics["model"] == dict_name) & (p8_metrics["period"] == "holdout")
        & (p8_metrics["h"] == 1) & (p8_metrics["ward"] == "overall")
    ]
    base_rmse = float(base_row["rmse"].iloc[0])

    return {
        "experiment": "E2_lambda_sensitivity", "dictionary": dict_name, "multiplier": multiplier,
        "selected_lambda": selected_lambda, "alt_lambda": alt_lambda,
        "baseline_holdout_rmse_h1": base_rmse, "alt_holdout_rmse_h1": alt_rmse,
        "rmse_ratio": alt_rmse / base_rmse if base_rmse else np.nan,
    }


# ---------------------------------------------------------------- E3 ----

def e3_replicate_count_sensitivity(setup, n_replicates):
    """Rerun P9's ground-truth experiment with a different replicate
    count (config.ROBUSTNESS_REPLICATE_COUNTS: 30 and 300, vs P9's
    standard 100), using the SAME default base seed as P9's original run.
    Because numpy's SeedSequence.spawn(n) assigns spawn keys 0..n-1
    deterministically, a 30-replicate run here is an exact PREFIX of the
    original 100, and 300 extends it with 200 more -- so this is a
    Monte-Carlo CONVERGENCE check (does a smaller/larger sample of the
    SAME stream already agree with the full one), not an independent-
    reseeding check (that is what E1 tests, with a genuinely different
    base seed). Both are useful and answer different questions."""
    original = pd.read_csv(config.RESULTS_TABLES_DIR / "p9_ground_truth_intervention.csv").set_index("ward")[
        "drop_person_days_mean"
    ]
    alt, _ = superspreader_experiment(
        setup["people"], setup["index"], setup["day_list"], setup["edges"], setup["admission"],
        setup["beta"], setup["gamma"], setup["epsilon"], setup["pre_window_last_status"], setup["groups"],
        n_replicates=n_replicates,
    )
    alt_scores = alt.set_index("ward")["drop_person_days_mean"]
    rho, pval = rank_stability(original, alt_scores, setup["groups"])
    return {"experiment": "E3_replicate_count_sensitivity", "n_replicates": n_replicates,
            "rho_vs_baseline": rho, "p_value": pval}


# ---------------------------------------------------------------- E4 ----

def e4_calibration_ridge_point(setup):
    """P4 found the best-fit (beta, gamma) sits on a wide, flat loss
    ridge (16 of 320 grid points within 10% of the best loss; gamma still
    on the widened grid's edge). Pick a DIFFERENT point on that ridge
    (largest gamma among the near-best points, to get a meaningfully
    different point, not a numerically nearby duplicate) and rerun P9's
    ground-truth experiment there. Tests whether P9/P10's conclusions
    depend on the specific calibrated point or hold across the ridge."""
    grid = pd.read_csv(config.RESULTS_TABLES_DIR / "p4_calibration_grid.csv")
    best_loss = grid["loss"].min()
    near_best = grid[grid["loss"] < best_loss * 1.1]
    alt_point = near_best.sort_values("gamma", ascending=False).iloc[0]

    original = pd.read_csv(config.RESULTS_TABLES_DIR / "p9_ground_truth_intervention.csv").set_index("ward")[
        "drop_person_days_mean"
    ]
    alt, _ = superspreader_experiment(
        setup["people"], setup["index"], setup["day_list"], setup["edges"], setup["admission"],
        float(alt_point["beta"]), float(alt_point["gamma"]), float(alt_point["epsilon"]),
        setup["pre_window_last_status"], setup["groups"], n_replicates=config.ROBUSTNESS_N_REPLICATES,
    )
    alt_scores = alt.set_index("ward")["drop_person_days_mean"]
    rho, pval = rank_stability(original, alt_scores, setup["groups"])
    return {
        "experiment": "E4_calibration_ridge_point", "alt_beta": float(alt_point["beta"]),
        "alt_gamma": float(alt_point["gamma"]), "alt_epsilon": float(alt_point["epsilon"]),
        "alt_loss": float(alt_point["loss"]), "rho_vs_baseline": rho, "p_value": pval,
    }


# ---------------------------------------------------------------- E5 ----

def e5_w_time_window_sensitivity(setup):
    """P5 flagged that W (used in D3 and the degree-centrality risk
    score) is built from the WHOLE contact period, including the weeks
    later used as P4/P6's holdout -- acceptable since W carries no
    outcome information, but flagged as a limitation. Recompute W using
    ONLY the calibration-period weeks (0-11) and compare the resulting
    degree-centrality ward ranking to the original (whole-period) one."""
    contacts = setup["contacts"]
    week = assign_week(contacts["day"])
    calib_contacts = contacts[week.isin(config.CALIBRATION_WEEKS)]

    w_full = pd.read_csv(config.RESULTS_TABLES_DIR / "p2_ward_matrix_raw_all.csv", index_col=0)
    original_degree = ward_degree_centrality(w_full.to_numpy(), setup["groups"])

    w_calib = ward_contact_matrix(calib_contacts, setup["admission"], include_staff=True)
    alt_degree = ward_degree_centrality(w_calib.reindex(index=setup["groups"], columns=setup["groups"]).to_numpy(), setup["groups"])

    rho, pval = rank_stability(original_degree, alt_degree, setup["groups"])
    return {"experiment": "E5_W_time_window_sensitivity", "rho_vs_baseline": rho, "p_value": pval,
            "note": "degree centrality, whole-period W vs calibration-weeks-only W"}


# ---------------------------------------------------------------- E6 ----

def e6_patients_only_population(setup):
    """The patients-only sensitivity run (decision #3), deferred at every
    phase since P2. Rerun P9's ground-truth experiment restricted to the
    329-person, 5-ward patients-only population, and compare the ward
    ranking for the 5 SHARED wards (all but 'Other', which doesn't exist
    in a patients-only population) to the original 6-ward ranking
    restricted to those same 5 wards."""
    from src.network import filter_edges, filter_people

    patients_groups = [g for g in setup["groups"] if g != "Other"]
    pop_people = filter_people(setup["admission"], include_staff=False)
    network_people = set(setup["contacts"]["from"]) | set(setup["contacts"]["to"])
    people_subset = network_people & pop_people
    people, index = build_person_index(people_subset)
    edges = filter_edges(setup["edges"], setup["admission"], include_staff=False)

    original = pd.read_csv(config.RESULTS_TABLES_DIR / "p9_ground_truth_intervention.csv").set_index("ward")[
        "drop_person_days_mean"
    ]
    alt, _ = superspreader_experiment(
        people, index, setup["day_list"], edges, setup["admission"],
        setup["beta"], setup["gamma"], setup["epsilon"], setup["pre_window_last_status"], patients_groups,
        n_replicates=config.ROBUSTNESS_N_REPLICATES,
    )
    alt_scores = alt.set_index("ward")["drop_person_days_mean"]
    rho, pval = rank_stability(original, alt_scores, patients_groups)
    return {"experiment": "E6_patients_only_population", "n_people": len(people_subset),
            "rho_vs_baseline_5_shared_wards": rho, "p_value": pval}


# ---------------------------------------------------------------- E7 ----

def e7_missing_data_handling(setup):
    """Decision #6's carry-forward sensitivity run (built in P3, unused
    for scoring until now, by design -- see states.py's module
    docstring). Recompute P8's holdout model ranking using the
    carry-forward-filled series AS IF it were the ground truth (scoring
    every carry-forward cell, not gated by P3's n_tested>=10 mask) and
    compare the resulting model order to P8's original no-imputation
    ranking."""
    states_cf = pd.read_csv(config.DATA_PROCESSED_DIR / "states_real_carry_forward_SENSITIVITY_ONLY.csv")
    groups = setup["groups"]

    rows = []
    for name in config.EDMD_DICTIONARIES:
        model_npz = np.load(config.RESULTS_MODELS_DIR / f"p6_edmd_{name}.npz", allow_pickle=True)
        scaler = ConstantAwareScaler()
        scaler.mean_ = model_npz["scaler_mean"]
        scaler.scale_ = model_npz["scaler_scale"]
        model = {
            "K": model_npz["K"], "scaler": scaler, "C": model_npz["C"],
            "feature_names": list(model_npz["feature_names"]), "groups": list(model_npz["groups"]),
        }
        W = pd.read_csv(config.RESULTS_TABLES_DIR / "p2_ward_matrix_W_all.csv", index_col=0).to_numpy()

        # treat carry-forward as the "real" series for both filling AND scoring
        cf_as_real = states_cf.rename(columns={"prevalence": "prevalence"}).copy()
        cf_as_real["n_tested"] = 999  # always "observed enough" -- this IS the point of the check
        from src.baselines import build_real_weekly_states

        weekly_states = build_real_weekly_states(cf_as_real, states_cf, groups, weeks=range(config.N_WEEKS))
        records = edmd_forecast_real(model, weekly_states, cf_as_real, groups, config.EDMD_MAX_HORIZON, name, W=W)
        long_df = flatten_records(records, groups)
        metrics = compute_metrics_from_long(long_df, group_by=["period", "h"])
        row = metrics[
            (metrics["model"] == name) & (metrics["period"] == "holdout")
            & (metrics["h"] == 1) & (metrics["ward"] == "overall")
        ]
        rows.append({"model": name, "carry_forward_scored_rmse": float(row["rmse"].iloc[0]) if len(row) else np.nan})

    alt_ranking = pd.DataFrame(rows).sort_values("carry_forward_scored_rmse")

    p8_metrics = pd.read_csv(config.RESULTS_TABLES_DIR / "p8_metrics.csv")
    base = p8_metrics[
        (p8_metrics["model"].isin(config.EDMD_DICTIONARIES)) & (p8_metrics["period"] == "holdout")
        & (p8_metrics["h"] == 1) & (p8_metrics["ward"] == "overall")
    ][["model", "rmse"]].rename(columns={"rmse": "no_imputation_rmse"})

    comparison = alt_ranking.merge(base, on="model")
    rho, pval = spearmanr(comparison["carry_forward_scored_rmse"], comparison["no_imputation_rmse"])
    return {"experiment": "E7_missing_data_handling", "rho_model_ranking_agreement": float(rho),
            "p_value": float(pval)}, comparison


# ---------------------------------------------------------------- E8 ----

def _d3_reduced_features(states, group_names, W):
    """D3 with the provably-redundant Wx block dropped (P6/P7 proved
    Wx contributes ZERO rank beyond x, since W is invertible): [1, x, x^2,
    x*(Wx)] instead of D3's full [1, x, x^2, Wx, x*(Wx)]."""
    X = np.asarray(states, dtype=float)
    n = X.shape[-1]
    ones = np.ones(X.shape[:-1] + (1,))
    squares = X**2
    Wx = X @ W.T
    cross = X * Wx
    features = np.concatenate([ones, X, squares, cross], axis=-1)
    names = (
        ["1"] + [f"x_{g}" for g in group_names] + [f"x_{g}^2" for g in group_names]
        + [f"x_{g}*(Wx)_{g}" for g in group_names]
    )
    return features, names


def e8_d3_structural_redundancy(setup):
    """P6/P7 proved D3's raw 25 features have effective rank <= 19 (Wx
    contributes zero rank beyond x). Build 'D3_reduced' with that
    redundant Wx block dropped (19 features instead of 25), refit EDMD
    the same way P6 did (same train/val/test split, own lambda grid), and
    compare its real-data holdout RMSE and dominant-mode ward ranking to
    the full D3's. If the theory is right, dropping a block that
    contributes no independent information should barely change
    anything."""
    from src.build_edmd import lambda_selection_criterion, select_lambda
    from src.edmd import build_pairs_within_trajectory
    from src.eigen import dominant_ward_relevant_mode, eigendecompose, mode_table, mode_ward_patterns, null_space_rank_cutoff

    sim = np.load(config.DATA_PROCESSED_DIR / "states_sim.npz", allow_pickle=True)
    states = sim["states"]
    groups = list(sim["groups"])
    trajectory_ids = sim["trajectory"]
    split_df = pd.read_csv(config.DATA_PROCESSED_DIR / "trajectory_split.csv")
    W = pd.read_csv(config.RESULTS_TABLES_DIR / "p2_ward_matrix_W_all.csv", index_col=0).to_numpy()

    features, feature_names = _d3_reduced_features(states, groups, W)

    X_train, Y_train, _ = build_pairs_within_trajectory(features, trajectory_ids, split_df, "train")
    scaler = ConstantAwareScaler().fit(X_train)
    X_train_s, Y_train_s = scaler.transform(X_train), scaler.transform(Y_train)
    group_indices = [feature_names.index(f"x_{g}") for g in groups]

    lambda_table, best_lambda = select_lambda(
        X_train_s, Y_train_s, scaler, group_indices, features, trajectory_ids, split_df, config.EDMD_LAMBDA_GRID
    )
    K = ridge_fit(X_train_s, Y_train_s, best_lambda)
    rank = int(np.linalg.matrix_rank(K))

    C = selector_matrix(feature_names, groups)
    states_real = pd.read_csv(config.RESULTS_TABLES_DIR / "p3_states_real.csv")
    states_cf = pd.read_csv(config.DATA_PROCESSED_DIR / "states_real_carry_forward_SENSITIVITY_ONLY.csv")
    from src.baselines import build_real_weekly_states

    weekly_states = build_real_weekly_states(states_real, states_cf, groups, weeks=range(config.N_WEEKS))
    # D3_reduced isn't one of src.observables' DICTIONARIES, so build phi ourselves
    # here (via _d3_reduced_features) rather than using edmd_forecast_real's dict_name dispatch.
    records = []
    for t in range(config.N_WEEKS):
        x_t, _ = weekly_states[t]
        from src.real_state_fill import observed_for_scoring_mask, state_is_usable_as_starting_point
        from src.forecast import landing_period

        if not state_is_usable_as_starting_point(x_t):
            continue
        phi, _ = _d3_reduced_features(x_t, groups, W)
        current = scaler.transform(phi[None, :])[0]
        for h in range(1, config.EDMD_MAX_HORIZON + 1):
            landing = t + h
            if landing >= config.N_WEEKS:
                break
            current = current @ K.T
            pred_scaled = current[group_indices]
            pred_raw = scaler.inverse_transform_indices(pred_scaled, group_indices)
            actual_raw, _ = weekly_states[landing]
            mask = observed_for_scoring_mask(landing, states_real, groups, min_n_tested=10)
            records.append(
                {"model": "D3_reduced", "start_week": t, "landing_week": landing,
                 "period": landing_period(landing), "h": h, "pred": pred_raw, "actual": actual_raw, "scoring_mask": mask}
            )
    long_df = flatten_records(records, groups)
    metrics = compute_metrics_from_long(long_df, group_by=["period", "h"])
    row = metrics[(metrics["period"] == "holdout") & (metrics["h"] == 1) & (metrics["ward"] == "overall")]
    reduced_rmse = float(row["rmse"].iloc[0]) if len(row) else np.nan

    eigvals, eigvecs = eigendecompose(K)
    rank_cutoff = null_space_rank_cutoff(K)
    ward_patterns = mode_ward_patterns(eigvecs, C, scaler.scale_)
    mode_df = mode_table(eigvals, ward_patterns, rank_cutoff, groups)
    dominant_idx = dominant_ward_relevant_mode(mode_df)
    dominant_ward = None
    if dominant_idx is not None:
        row_m = mode_df[mode_df["mode"] == dominant_idx].iloc[0]
        shares = {g: row_m[f"share_{g}"] for g in groups}
        dominant_ward = max(shares, key=shares.get)

    d3_metrics = pd.read_csv(config.RESULTS_TABLES_DIR / "p8_metrics.csv")
    d3_row = d3_metrics[
        (d3_metrics["model"] == "D3") & (d3_metrics["period"] == "holdout")
        & (d3_metrics["h"] == 1) & (d3_metrics["ward"] == "overall")
    ]
    d3_rmse = float(d3_row["rmse"].iloc[0])
    d3_dominant = pd.read_csv(config.RESULTS_TABLES_DIR / "p7_dominant_mode_ward_ranking.csv")
    d3_dominant_ward = d3_dominant[d3_dominant["dictionary"] == "D3"].sort_values("share", ascending=False).iloc[0]["ward"]

    return {
        "experiment": "E8_D3_structural_redundancy",
        "d3_full_n_features": 25, "d3_reduced_n_features": len(feature_names),
        "d3_full_rank_K": 19, "d3_reduced_rank_K": rank,
        "d3_full_holdout_rmse_h1": d3_rmse, "d3_reduced_holdout_rmse_h1": reduced_rmse,
        "rmse_ratio": reduced_rmse / d3_rmse if d3_rmse else np.nan,
        "d3_full_dominant_ward": d3_dominant_ward, "d3_reduced_dominant_ward": dominant_ward,
        "dominant_ward_matches": dominant_ward == d3_dominant_ward,
    }
