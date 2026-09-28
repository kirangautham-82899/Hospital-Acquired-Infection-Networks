"""P11 orchestrator: run robustness experiments E1-E8 (see
src/robustness.py's module docstring for what each one probes and why)
and assemble a single summary table.

Writes:
  results/tables/p11_summary.csv           (one row per experiment, rho/ratio vs baseline)
  results/tables/p11_e2_lambda_detail.csv
  results/tables/p11_e7_model_ranking_detail.csv
  results/tables/p11_e8_detail.csv
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


def build():
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)

    print("P11 ROBUSTNESS EXPERIMENTS E1-E8")
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

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(config.RESULTS_TABLES_DIR / "p11_summary.csv", index=False)

    print("\n" + "=" * 60)
    print("P11 SUMMARY")
    print(summary[["experiment", "description", "stability_metric", "value"]].to_string(index=False))

    return summary


if __name__ == "__main__":
    build()
