"""P8 orchestrator: forecast real data with D1/D2/D3 (first time K
touches real data), fit and forecast the two new baselines (network-
exposure, ward-SIS) plus persistence and historical mean, and produce the
full model-comparison report.

Writes:
  results/tables/p8_baseline_params.csv     (fitted network-exposure/ward-SIS coefficients)
  results/tables/p8_metrics.csv             (every model x period x h x ward, raw+clipped, skill)
  results/tables/p8_metrics_summary.csv     (overall-ward, holdout-period summary for quick reading)
  results/figures/p8_rmse_by_horizon.png
  results/figures/p8_predicted_vs_actual_holdout.png

Real data is used ONLY for: (a) building starting states for K (never for
fitting K), (b) fitting the two new baselines on calibration weeks, and
(c) scoring everyone on genuinely-observed cells. See research_log.md.
"""
import numpy as np
import pandas as pd

import config
from src.baselines import (
    build_real_weekly_states,
    build_training_pairs,
    fit_network_exposure_model,
    fit_ward_sis_model,
    predict_network_exposure,
    predict_ward_sis,
)
from src.forecast import (
    edmd_forecast_real,
    flatten_records,
    historical_mean_forecast_real,
    load_edmd_model,
    persistence_forecast_real,
)
from src.metrics import add_skill_vs_persistence, compute_metrics_from_long


def load_w_all():
    w = pd.read_csv(config.RESULTS_TABLES_DIR / "p2_ward_matrix_W_all.csv", index_col=0)
    assert list(w.index) == config.WARD_GROUPS
    return w.to_numpy()


def forecast_baseline_iteratively(predict_fn, weekly_states, states_real, groups, max_h, model_name, coef_args, W):
    """Roll a one-step baseline predict function (network-exposure or
    ward-SIS) forward h=1..max_h from every usable real starting week.
    predict_fn's signature must be predict_fn(*coef_args, x, W) -- matching
    predict_network_exposure(coef, x, W) and predict_ward_sis(beta, gamma,
    x, W) (coef_args = (coef,) or (beta, gamma) respectively)."""
    from src.real_state_fill import state_is_usable_as_starting_point
    from src.forecast import landing_period
    from src.real_state_fill import observed_for_scoring_mask

    records = []
    for t in range(config.N_WEEKS):
        x_t, _ = weekly_states[t]
        if not state_is_usable_as_starting_point(x_t):
            continue
        current = x_t.copy()
        for h in range(1, max_h + 1):
            landing = t + h
            if landing >= config.N_WEEKS:
                break
            current = predict_fn(*coef_args, current, W)
            actual_raw, _ = weekly_states[landing]
            mask = observed_for_scoring_mask(landing, states_real, groups, min_n_tested=10)
            records.append(
                {
                    "model": model_name, "start_week": t, "landing_week": landing,
                    "period": landing_period(landing), "h": h,
                    "pred": current.copy(), "actual": actual_raw, "scoring_mask": mask,
                }
            )
    return records


def build():
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    groups = config.WARD_GROUPS
    states_real = pd.read_csv(config.RESULTS_TABLES_DIR / "p3_states_real.csv")
    states_cf = pd.read_csv(config.DATA_PROCESSED_DIR / "states_real_carry_forward_SENSITIVITY_ONLY.csv")
    W = load_w_all()

    weekly_states = build_real_weekly_states(states_real, states_cf, groups, weeks=range(config.N_WEEKS))

    print("P8 FORECASTING, VALIDATION, BASELINES")
    print("=" * 60)
    n_usable = sum(1 for w in weekly_states if not np.isnan(weekly_states[w][0]).any())
    print(f"Usable (fully filled) starting states: {n_usable} of {config.N_WEEKS} weeks")

    # ---- fit the two new baselines on calibration weeks only ----
    train_pairs = build_training_pairs(weekly_states, states_real, groups, config.CALIBRATION_WEEKS[:-1])
    print(f"Training pairs for network-exposure / ward-SIS (calibration weeks, observed targets only): {len(train_pairs)}")

    ne_coef = fit_network_exposure_model(train_pairs, W)
    sis_beta, sis_gamma = fit_ward_sis_model(train_pairs, W)
    print(f"network_exposure coefficients [a, b, c]: {ne_coef}")
    print(f"ward_sis (beta, gamma): ({sis_beta:.5g}, {sis_gamma:.5g})")

    pd.DataFrame(
        [
            {"model": "network_exposure", "param": "a", "value": ne_coef[0]},
            {"model": "network_exposure", "param": "b", "value": ne_coef[1]},
            {"model": "network_exposure", "param": "c", "value": ne_coef[2]},
            {"model": "ward_sis", "param": "beta", "value": sis_beta},
            {"model": "ward_sis", "param": "gamma", "value": sis_gamma},
        ]
    ).to_csv(config.RESULTS_TABLES_DIR / "p8_baseline_params.csv", index=False)

    # ---- historical mean baseline: real observed mean over calibration weeks ----
    calib_real = states_real[states_real["week"].isin(config.CALIBRATION_WEEKS)]
    mean_vector = calib_real.groupby("group")["prevalence"].mean().reindex(groups).to_numpy()

    # ---- forecast every model ----
    all_records = []
    for name in config.EDMD_DICTIONARIES:
        model = load_edmd_model(name)
        all_records += edmd_forecast_real(
            model, weekly_states, states_real, groups, config.EDMD_MAX_HORIZON, name, W=W
        )
    all_records += persistence_forecast_real(weekly_states, states_real, groups, config.EDMD_MAX_HORIZON)
    all_records += historical_mean_forecast_real(
        mean_vector, weekly_states, states_real, groups, config.EDMD_MAX_HORIZON
    )
    all_records += forecast_baseline_iteratively(
        predict_network_exposure, weekly_states, states_real, groups, config.EDMD_MAX_HORIZON,
        "network_exposure", (ne_coef,), W,
    )
    all_records += forecast_baseline_iteratively(
        predict_ward_sis, weekly_states, states_real, groups, config.EDMD_MAX_HORIZON,
        "ward_sis", (sis_beta, sis_gamma), W,
    )

    long_df = flatten_records(all_records, groups)
    long_df.to_csv(config.RESULTS_TABLES_DIR / "p8_forecast_records_long.csv", index=False)
    print(f"\nTotal scored (model, start, landing, h, ward) rows: {len(long_df)}")

    metrics = compute_metrics_from_long(long_df, group_by=["period", "h"])
    metrics = add_skill_vs_persistence(metrics, group_by=["period", "h"])
    metrics.to_csv(config.RESULTS_TABLES_DIR / "p8_metrics.csv", index=False)

    summary = metrics[
        (metrics["ward"] == "overall") & (metrics["period"] == "holdout")
    ].sort_values(["h", "rmse"])
    summary.to_csv(config.RESULTS_TABLES_DIR / "p8_metrics_summary.csv", index=False)

    print("\nHOLDOUT period, overall (all wards), by horizon:")
    print(summary[["model", "h", "n", "rmse", "rmse_clipped", "skill_vs_persistence"]].to_string(index=False))

    _rmse_by_horizon_plot(metrics)
    _predicted_vs_actual_plot(long_df)

    return {"metrics": metrics, "long_df": long_df, "ne_coef": ne_coef, "sis_params": (sis_beta, sis_gamma)}


def _rmse_by_horizon_plot(metrics):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, period in zip(axes, ["calibration", "holdout"]):
        sub = metrics[(metrics["ward"] == "overall") & (metrics["period"] == period)]
        for model, g in sub.groupby("model"):
            g = g.sort_values("h")
            ax.plot(g["h"], g["rmse"], "o-", label=model)
        ax.set_title(f"{period} period")
        ax.set_xlabel("forecast horizon (weeks)")
        ax.set_xticks(range(1, config.EDMD_MAX_HORIZON + 1))
    axes[0].set_ylabel("RMSE (overall, all wards)")
    axes[1].legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    fig.suptitle("P8: real-data forecast RMSE by horizon")
    fig.tight_layout()
    fig.savefig(config.RESULTS_FIGURES_DIR / "p8_rmse_by_horizon.png", dpi=150)
    plt.close(fig)


def _predicted_vs_actual_plot(long_df):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sub = long_df[(long_df["period"] == "holdout") & (long_df["h"] == 1)]
    models = sorted(sub["model"].unique())
    fig, axes = plt.subplots(2, (len(models) + 1) // 2, figsize=(14, 7), sharex=True, sharey=True)
    axes = np.atleast_1d(axes).flatten()
    for ax, model in zip(axes, models):
        m = sub[sub["model"] == model]
        ax.scatter(m["actual"], m["pred"], s=15, alpha=0.6)
        ax.plot([0, 1], [0, 1], "k--", linewidth=1)
        ax.set_title(model, fontsize=9)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
    fig.supxlabel("actual prevalence")
    fig.supylabel("predicted prevalence")
    fig.suptitle("P8: holdout period, h=1, predicted vs actual")
    fig.tight_layout()
    fig.savefig(config.RESULTS_FIGURES_DIR / "p8_predicted_vs_actual_holdout.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    build()
