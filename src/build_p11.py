"""P11 orchestrator: run robustness experiments E1-E9 (see
src/robustness.py's module docstring for what each one probes and why)
and assemble a single summary table.

Writes:
  results/tables/p11_summary.csv           (one row per experiment, rho/ratio vs baseline)
  results/tables/p11_e2_lambda_detail.csv
  results/tables/p11_e7_model_ranking_detail.csv
  results/tables/p11_e8_detail.csv
  results/tables/p11_e9_ridge_points.csv     (E9: every near-optimal calibration point, src/ridge_sensitivity.py)
  results/tables/p11_e9_models.csv           (E9: lambda, spectral radius, sim-test skill per point x dictionary)
  results/tables/p11_e9_forecast.csv         (E9: real holdout RMSE minus persistence, block-bootstrap CI)
  results/tables/p11_e9_ranking.csv          (E9: Spearman of every score vs both ground truths)
  results/tables/p11_e9_interventions.csv    (E9: paired advantages in two P10 cells)
  results/figures/p11_e9_ridge_sensitivity.png
"""
import pandas as pd

import config
from src.robustness import (
    build_common_setup,
    e1_seed_sensitivity,
    e2_lambda_sensitivity,
    e3_replicate_count_sensitivity,
    e4_calibration_ridge_point,
    e5_w_time_window_sensitivity,
    e6_patients_only_population,
    e7_missing_data_handling,
    e8_d3_structural_redundancy,
)
from src.ridge_sensitivity import e9_calibration_ridge


def build():
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)

    print("P11 ROBUSTNESS EXPERIMENTS E1-E9")
    print("=" * 60)

    setup = build_common_setup()
    summary_rows = []

    print("\n[E1] seed sensitivity...")
    e1 = e1_seed_sensitivity(setup)
    print(f"  {e1}")
    summary_rows.append({"experiment": "E1", "description": "seed sensitivity (P9 ground truth)",
                          "stability_metric": "rho", "value": e1["rho_vs_baseline"], "detail": e1["note"]})

    print("\n[E2] lambda sensitivity...")
    e2_rows = []
    for name in config.EDMD_DICTIONARIES:
        for mult in config.ROBUSTNESS_LAMBDA_MULTIPLIERS:
            r = e2_lambda_sensitivity(name, mult)
            print(f"  {name} x{mult}: rmse_ratio={r['rmse_ratio']:.4f}")
            e2_rows.append(r)
    e2_df = pd.DataFrame(e2_rows)
    e2_df.to_csv(config.RESULTS_TABLES_DIR / "p11_e2_lambda_detail.csv", index=False)
    summary_rows.append({"experiment": "E2", "description": "lambda sensitivity (P8 holdout RMSE, h=1)",
                          "stability_metric": "max |rmse_ratio - 1|", "value": (e2_df["rmse_ratio"] - 1).abs().max(),
                          "detail": "see p11_e2_lambda_detail.csv"})

    print("\n[E3] replicate-count sensitivity...")
    for n in config.ROBUSTNESS_REPLICATE_COUNTS:
        e3 = e3_replicate_count_sensitivity(setup, n)
        print(f"  n_replicates={n}: {e3}")
        summary_rows.append({"experiment": "E3", "description": f"replicate-count sensitivity (n={n})",
                              "stability_metric": "rho", "value": e3["rho_vs_baseline"], "detail": f"n_replicates={n}"})

    print("\n[E4] calibration ridge-point sensitivity...")
    e4 = e4_calibration_ridge_point(setup)
    print(f"  {e4}")
    summary_rows.append(
        {"experiment": "E4", "description": "calibration ridge-point sensitivity (P9 ground truth)",
         "stability_metric": "rho", "value": e4["rho_vs_baseline"],
         "detail": f"alt beta={e4['alt_beta']:.4g}, gamma={e4['alt_gamma']:.4g}, loss={e4['alt_loss']:.4g}"}
    )

    print("\n[E5] W time-window sensitivity...")
    e5 = e5_w_time_window_sensitivity(setup)
    print(f"  {e5}")
    summary_rows.append({"experiment": "E5", "description": "W time-window sensitivity (degree centrality)",
                          "stability_metric": "rho", "value": e5["rho_vs_baseline"], "detail": e5["note"]})

    print("\n[E6] patients-only population...")
    e6 = e6_patients_only_population(setup)
    print(f"  {e6}")
    summary_rows.append(
        {"experiment": "E6", "description": "patients-only population (P9 ground truth, 5 shared wards)",
         "stability_metric": "rho", "value": e6["rho_vs_baseline_5_shared_wards"], "detail": f"n_people={e6['n_people']}"}
    )

    print("\n[E7] missing-data handling (carry-forward vs no-imputation)...")
    e7, e7_detail = e7_missing_data_handling(setup)
    print(f"  {e7}")
    e7_detail.to_csv(config.RESULTS_TABLES_DIR / "p11_e7_model_ranking_detail.csv", index=False)
    summary_rows.append(
        {"experiment": "E7", "description": "missing-data handling (P8 model ranking agreement)",
         "stability_metric": "rho", "value": e7["rho_model_ranking_agreement"], "detail": "see p11_e7_model_ranking_detail.csv"}
    )

    print("\n[E8] D3 structural redundancy (drop the provably-redundant Wx block)...")
    e8 = e8_d3_structural_redundancy(setup)
    print(f"  {e8}")
    pd.DataFrame([e8]).to_csv(config.RESULTS_TABLES_DIR / "p11_e8_detail.csv", index=False)
    summary_rows.append(
        {"experiment": "E8", "description": "D3 structural redundancy (holdout RMSE ratio, reduced/full)",
         "stability_metric": "rmse_ratio", "value": e8["rmse_ratio"],
         "detail": f"dominant ward {'MATCHES' if e8['dominant_ward_matches'] else 'DIFFERS'}: "
                    f"full={e8['d3_full_dominant_ward']}, reduced={e8['d3_reduced_dominant_ward']}"}
    )

    print("\n[E9] calibration ridge: rerun P4-P10 at every near-optimal gamma...")
    points, e9 = e9_calibration_ridge(setup)
    points.to_csv(config.RESULTS_TABLES_DIR / "p11_e9_ridge_points.csv", index=False)
    e9["params"].to_csv(config.RESULTS_TABLES_DIR / "p11_e9_models.csv", index=False)
    e9["forecast"].to_csv(config.RESULTS_TABLES_DIR / "p11_e9_forecast.csv", index=False)
    e9["ranking"].to_csv(config.RESULTS_TABLES_DIR / "p11_e9_ranking.csv", index=False)
    e9["interventions"].to_csv(config.RESULTS_TABLES_DIR / "p11_e9_interventions.csv", index=False)
    summary_rows.extend(e9_summary_rows(points, e9))
    _e9_plot(e9)

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(config.RESULTS_TABLES_DIR / "p11_summary.csv", index=False)

    print("\n" + "=" * 60)
    print("P11 SUMMARY")
    print(summary[["experiment", "description", "stability_metric", "value"]].to_string(index=False))

    return summary


def e9_summary_rows(points, e9):
    """One summary row per E9 question, each giving the range over ridge
    points (min..max) so the reader sees how much the answer moves."""
    rows = []
    span = (f"{len(points)} points; gamma {points['gamma'].min():.3g}..{points['gamma'].max():.3g}, "
            f"beta {points['beta'].min():.3g}..{points['beta'].max():.3g}, "
            f"epsilon {points['epsilon'].min():.3g}..{points['epsilon'].max():.3g}")
    m = e9["params"]
    rows.append({"experiment": "E9", "description": "ridge: EDMD spectral radius (all dictionaries)",
                 "stability_metric": "min..max", "value": m["spectral_radius"].max(),
                 "detail": f"{m['spectral_radius'].min():.4f}..{m['spectral_radius'].max():.4f}; {span}"})
    f = e9["forecast"]
    for h in sorted(f["h"].unique()):
        sub = f[f["h"] == h]
        n_worse = int((sub["ci_low"] > 0).sum())
        n_better = int((sub["ci_high"] < 0).sum())
        rows.append({"experiment": "E9", "description": f"ridge: real holdout RMSE - persistence, h={h}",
                     "stability_metric": "max", "value": sub["rmse_diff"].max(),
                     "detail": f"{sub['rmse_diff'].min():+.4f}..{sub['rmse_diff'].max():+.4f}; "
                               f"CI excludes 0 worse in {n_worse}, better in {n_better} of {len(sub)}"})
    r = e9["ranking"]
    for gt in ["pct50", "equal_hours"]:
        for cand in ["degree_centrality", "koopman_D3", "koopman_influence_D3"]:
            sub = r[(r["ground_truth"] == gt) & (r["candidate"] == cand)]
            rows.append({"experiment": "E9", "description": f"ridge: Spearman {cand} vs {gt}",
                         "stability_metric": "min", "value": sub["spearman_rho"].min(),
                         "detail": f"{sub['spearman_rho'].min():.3f}..{sub['spearman_rho'].max():.3f}"})
    iv = e9["interventions"]
    deg = iv[(iv["strategy"] == "degree_centrality") & iv["reference"].isin(["random", "whole_hospital"])]
    rows.append({"experiment": "E9", "description": "ridge: degree-targeted vs random/whole-hospital",
                 "stability_metric": "share better", "value": float((deg["verdict"] == "better").mean()),
                 "detail": f"{int((deg['verdict'] == 'better').sum())} of {len(deg)} comparisons better"})
    kd = iv[iv["reference"] == "degree_centrality"]
    rows.append({"experiment": "E9", "description": "ridge: Koopman-targeted vs degree-targeted",
                 "stability_metric": "share better", "value": float((kd["verdict"] == "better").mean()),
                 "detail": f"better {int((kd['verdict'] == 'better').sum())}, worse "
                           f"{int((kd['verdict'] == 'worse').sum())}, tied {int((kd['verdict'] == 'not distinguishable').sum())}"
                           f" of {len(kd)}"})
    return rows


def _e9_plot(e9):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Points differ in gamma, beta or epsilon, so the x axis is the point
    # itself (sorted by gamma, then beta, then epsilon), labelled with its
    # parameters. Lines join points only as a visual aid.
    keys = ["gamma", "beta", "epsilon"]
    pts = e9["params"][keys].drop_duplicates().sort_values(keys).reset_index(drop=True)
    pos = {tuple(r): i for i, r in enumerate(pts.itertuples(index=False))}
    labels = [f"g {r.gamma:.1e}\nb {r.beta:.1e}\ne {r.epsilon:.1e}" for r in pts.itertuples(index=False)]

    def xs(df):
        return [pos[tuple(r)] for r in df[keys].itertuples(index=False)]

    fig, axes = plt.subplots(3, 1, figsize=(12, 13))
    f = e9["forecast"]
    for name, g in f[f["h"] == 4].groupby("model"):
        g = g.sort_values(keys)
        axes[0].errorbar(xs(g), g["rmse_diff"], yerr=[g["rmse_diff"] - g["ci_low"], g["ci_high"] - g["rmse_diff"]],
                         marker="o", capsize=3, label=name)
    axes[0].axhline(0, color="gray", linestyle=":")
    axes[0].set_title("real holdout RMSE - persistence, h=4 (> 0 = worse than persistence)", fontsize=10)
    axes[0].legend(fontsize=8)
    r = e9["ranking"]
    for ax, gt in zip(axes[1:], ["pct50", "equal_hours"]):
        for cand in ["degree_centrality", "eigenvector_centrality", "koopman_D1", "koopman_D2", "koopman_D3",
                     "koopman_influence_D3"]:
            g = r[(r["ground_truth"] == gt) & (r["candidate"] == cand)].sort_values(keys)
            ax.plot(xs(g), g["spearman_rho"], marker="o", label=cand)
        ax.axhline(0, color="gray", linestyle=":")
        ax.set_ylim(-1.05, 1.05)
        ax.set_title(f"Spearman rho vs ground truth {'A (50% cut)' if gt == 'pct50' else 'B (equal hours)'}",
                     fontsize=10)
        ax.legend(fontsize=8, loc="lower left", ncol=3)
    for ax in axes:
        ax.set_xticks(range(len(pts)))
        ax.set_xticklabels(labels, fontsize=7)
    axes[-1].set_xlabel("near-optimal calibration point (g = gamma/day, b = beta/contact-hour, e = epsilon/day)")
    fig.suptitle("E9: how results move across the near-optimal calibration points (loss within 5% of the best)")
    fig.tight_layout()
    fig.savefig(config.RESULTS_FIGURES_DIR / "p11_e9_ridge_sensitivity.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    build()
