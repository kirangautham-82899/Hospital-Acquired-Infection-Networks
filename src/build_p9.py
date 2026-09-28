"""P9 orchestrator: run the superspreader ward intervention experiment
(ground truth, src/intervention.py), compute centrality and Koopman-
eigenmode risk-score candidates (src/risk.py), and compare them via ranks
and Spearman correlation -- heavily caveated given only 6 wards
(CLAUDE.md's own known limitation: "Only 6 groups, so rank statistics are
weak").

Writes:
  results/tables/p9_ground_truth_intervention.csv
  results/tables/p9_ward_scores.csv       (raw scores: ground truth, centrality x3, koopman x3)
  results/tables/p9_ward_ranks.csv        (1 = highest / most central / biggest drop)
  results/tables/p9_spearman_vs_ground_truth.csv
  results/figures/p9_ground_truth_bar.png
  results/figures/p9_rank_heatmap.png
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import config
from src.intervention import superspreader_experiment
from src.load import load_admission, load_contacts
from src.network import build_master_edge_list
from src.risk import (
    load_koopman_risk_scores,
    ward_betweenness_centrality,
    ward_degree_centrality,
    ward_eigenvector_centrality,
)
from src.simulate import build_person_index, simulation_day_list


def build(n_replicates=100):
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    admission = load_admission(config.ADMISSION_CSV)
    contacts = load_contacts(config.CONTACTS_CSV)
    edges = build_master_edge_list(contacts)
    people_set = set(contacts["from"]) | set(contacts["to"])
    people, index = build_person_index(people_set)
    day_list = simulation_day_list()
    groups = config.WARD_GROUPS

    pre_window_last_status = pd.read_csv(config.DATA_PROCESSED_DIR / "states_pre_window_last_status.csv")
    calibrated = pd.read_csv(config.RESULTS_TABLES_DIR / "p4_calibrated_params.csv").iloc[0]
    beta, gamma, epsilon = float(calibrated["beta"]), float(calibrated["gamma"]), float(calibrated["epsilon"])

    print("P9 SUPERSPREADER WARD RISK SCORE VS CENTRALITY")
    print("=" * 60)
    print(f"Using P4 calibrated params: beta={beta:.5g}, gamma={gamma:.5g}, epsilon={epsilon:.5g}")
    print(f"Ground-truth experiment: {n_replicates} replicates per ward, 50% contact cut (all edges touching "
          f"the ward), common random numbers vs a shared baseline")

    ground_truth, per_replicate = superspreader_experiment(
        people, index, day_list, edges, admission, beta, gamma, epsilon,
        pre_window_last_status, groups, n_replicates=n_replicates, cut_fraction=0.5,
    )
    ground_truth.to_csv(config.RESULTS_TABLES_DIR / "p9_ground_truth_intervention.csv", index=False)
    print("\nGround truth (drop in colonized person-days when a ward's contacts are cut 50%, "
          "descending):")
    print(
        ground_truth[["ward", "drop_person_days_mean", "drop_fraction_mean"]]
        .sort_values("drop_person_days_mean", ascending=False)
        .to_string(index=False)
    )

    # ---- risk score candidates ----
    W_raw = pd.read_csv(config.RESULTS_TABLES_DIR / "p2_ward_matrix_raw_all.csv", index_col=0)
    assert list(W_raw.index) == groups
    W_raw = W_raw.to_numpy()

    scores = pd.DataFrame({"ward": groups})
    scores["ground_truth_drop"] = ground_truth.set_index("ward").loc[groups, "drop_person_days_mean"].to_numpy()
    scores["degree_centrality"] = ward_degree_centrality(W_raw, groups).to_numpy()
    scores["eigenvector_centrality"] = ward_eigenvector_centrality(W_raw, groups).to_numpy()
    scores["betweenness_centrality"] = ward_betweenness_centrality(W_raw, groups).to_numpy()
    for name in config.EDMD_DICTIONARIES:
        scores[f"koopman_{name}"] = load_koopman_risk_scores(name, groups).to_numpy()
    scores.to_csv(config.RESULTS_TABLES_DIR / "p9_ward_scores.csv", index=False)

    rank_cols = [c for c in scores.columns if c != "ward"]
    ranks = scores.copy()
    for c in rank_cols:
        ranks[c] = scores[c].rank(ascending=False).astype(int)
    ranks.to_csv(config.RESULTS_TABLES_DIR / "p9_ward_ranks.csv", index=False)

    print("\nWard ranks (1 = highest / most central / biggest drop):")
    print(ranks.to_string(index=False))

    corr_rows = []
    for c in rank_cols:
        if c == "ground_truth_drop":
            continue
        rho, pval = spearmanr(scores["ground_truth_drop"], scores[c])
        corr_rows.append({"candidate": c, "spearman_rho": rho, "p_value": pval})
    corr_df = pd.DataFrame(corr_rows).sort_values("spearman_rho", ascending=False)
    corr_df.to_csv(config.RESULTS_TABLES_DIR / "p9_spearman_vs_ground_truth.csv", index=False)

    print(f"\nSpearman rank correlation vs ground truth (n={len(groups)} wards -- CAUTION: with only 6")
    print("items, rank statistics are weak per CLAUDE.md's own known limitations; these correlations")
    print("and p-values are descriptive only, not meaningfully significant at this sample size):")
    print(corr_df.to_string(index=False))

    _plots(ground_truth, ranks, groups)
    return {"ground_truth": ground_truth, "scores": scores, "ranks": ranks, "corr": corr_df}


def _plots(ground_truth, ranks, groups):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gt_sorted = ground_truth.sort_values("drop_person_days_mean", ascending=False)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(gt_sorted["ward"], gt_sorted["drop_person_days_mean"],
           yerr=gt_sorted["drop_person_days_std"], capsize=4, color="steelblue")
    ax.set_ylabel("drop in colonized person-days\n(50% contact cut vs baseline)")
    ax.set_title("P9: simulated superspreader ground truth")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(config.RESULTS_FIGURES_DIR / "p9_ground_truth_bar.png", dpi=150)
    plt.close(fig)

    rank_matrix = ranks.set_index("ward")
    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(rank_matrix.to_numpy(), cmap="RdYlGn_r", vmin=1, vmax=len(groups))
    ax.set_xticks(range(len(rank_matrix.columns)))
    ax.set_xticklabels(rank_matrix.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(rank_matrix.index)))
    ax.set_yticklabels(rank_matrix.index)
    for i in range(rank_matrix.shape[0]):
        for j in range(rank_matrix.shape[1]):
            ax.text(j, i, int(rank_matrix.iloc[i, j]), ha="center", va="center", fontsize=8)
    ax.set_title("P9: ward ranks (1 = highest) across candidates")
    fig.colorbar(im, ax=ax, label="rank")
    fig.tight_layout()
    fig.savefig(config.RESULTS_FIGURES_DIR / "p9_rank_heatmap.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    build()
