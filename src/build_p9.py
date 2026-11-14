"""P9 orchestrator: run the superspreader ward intervention experiment
(ground truth, src/intervention.py), compute centrality and Koopman-
eigenmode risk-score candidates (src/risk.py), and compare them via ranks
and Spearman correlation -- heavily caveated given only 6 wards
(CLAUDE.md's own known limitation: "Only 6 groups, so rank statistics are
weak").

Two ground truths (second added after the Nov 14 review):
  - "pct50" (locked decision 14): cut each ward's contacts by 50%. A
    high-volume ward loses more contact-hours, so degree centrality is
    expected to match this ranking largely by construction.
  - "equal_hours": remove the SAME number of contact-hours from each ward
    (config.P9_EQUAL_HOURS_FRACTION_OF_MIN of the smallest ward's volume,
    config.P9_EQUAL_HOURS_N_REPLICATES replicates).
    This asks which ward's contact-hours matter most per hour, which
    degree does not answer by construction.

Writes:
  results/tables/p9_ground_truth_intervention.csv
  results/tables/p9_ground_truth_equal_hours.csv
  results/tables/p9_ward_scores.csv       (raw scores: ground truth, centrality x3, koopman x3)
  results/tables/p9_ward_ranks.csv        (1 = highest / most central / biggest drop)
  results/tables/p9_spearman_vs_ground_truth.csv
  results/figures/p9_ground_truth_bar.png
  results/figures/p9_rank_heatmap.png
"""
import pandas as pd
import config
from src.intervention import equal_hours_scales, superspreader_experiment, ward_touching_seconds
from src.metrics import spearman_exact
from src.load import load_admission, load_contacts
from src.network import build_master_edge_list
from src.risk import (
    load_koopman_influence_scores,
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
    print("\nGround truth A (pct50: drop in colonized person-days when a ward's contacts are cut 50%):")
    print(
        ground_truth[["ward", "drop_person_days_mean", "drop_ci_low", "drop_ci_high", "drop_fraction_mean"]]
        .sort_values("drop_person_days_mean", ascending=False)
        .to_string(index=False)
    )

    touching = ward_touching_seconds(edges, admission, groups)
    scales = equal_hours_scales(touching, config.P9_EQUAL_HOURS_FRACTION_OF_MIN)
    removed_hours = config.P9_EQUAL_HOURS_FRACTION_OF_MIN * touching.min() / 3600.0
    gt_eq, _ = superspreader_experiment(
        people, index, day_list, edges, admission, beta, gamma, epsilon,
        pre_window_last_status, groups, n_replicates=config.P9_EQUAL_HOURS_N_REPLICATES, ward_scales=scales,
    )
    gt_eq.insert(1, "touching_contact_hours", touching.loc[groups].to_numpy() / 3600.0)
    gt_eq.insert(2, "removed_contact_hours", removed_hours)
    gt_eq.to_csv(config.RESULTS_TABLES_DIR / "p9_ground_truth_equal_hours.csv", index=False)
    print(f"\nGround truth B (equal_hours: remove {removed_hours:.0f} contact-hours from each ward):")
    print(
        gt_eq[["ward", "edge_scale", "drop_person_days_mean", "drop_ci_low", "drop_ci_high"]]
        .sort_values("drop_person_days_mean", ascending=False)
        .to_string(index=False)
    )

    # ---- risk score candidates ----
    W_raw = pd.read_csv(config.RESULTS_TABLES_DIR / "p2_ward_matrix_raw_all.csv", index_col=0)
    assert list(W_raw.index) == groups
    W_raw = W_raw.to_numpy()

    scores = pd.DataFrame({"ward": groups})
    scores["ground_truth_drop"] = ground_truth.set_index("ward").loc[groups, "drop_person_days_mean"].to_numpy()
    scores["ground_truth_equal_hours_drop"] = gt_eq.set_index("ward").loc[groups, "drop_person_days_mean"].to_numpy()
    scores["degree_centrality"] = ward_degree_centrality(W_raw, groups).to_numpy()
    scores["eigenvector_centrality"] = ward_eigenvector_centrality(W_raw, groups).to_numpy()
    scores["betweenness_centrality"] = ward_betweenness_centrality(W_raw, groups).to_numpy()
    for name in config.EDMD_DICTIONARIES:
        scores[f"koopman_{name}"] = load_koopman_risk_scores(name, groups).to_numpy()
    for name in config.EDMD_DICTIONARIES:
        scores[f"koopman_influence_{name}"] = load_koopman_influence_scores(name, groups).to_numpy()
    scores.to_csv(config.RESULTS_TABLES_DIR / "p9_ward_scores.csv", index=False)

    rank_cols = [c for c in scores.columns if c != "ward"]
    ranks = scores.copy()
    for c in rank_cols:
        ranks[c] = scores[c].rank(ascending=False).astype(int)
    ranks.to_csv(config.RESULTS_TABLES_DIR / "p9_ward_ranks.csv", index=False)

    print("\nWard ranks (1 = highest / most central / biggest drop):")
    print(ranks.to_string(index=False))

    gt_cols = {"pct50": "ground_truth_drop", "equal_hours": "ground_truth_equal_hours_drop"}
    corr_rows = []
    for gt_name, gt_col in gt_cols.items():
        for c in rank_cols:
            if c in gt_cols.values():
                continue
            rho, pval = spearman_exact(scores[gt_col], scores[c])
            corr_rows.append({"ground_truth": gt_name, "candidate": c, "spearman_rho": rho, "p_value_exact": pval})
    corr_df = pd.DataFrame(corr_rows).sort_values(["ground_truth", "spearman_rho"], ascending=[False, False])
    corr_df.to_csv(config.RESULTS_TABLES_DIR / "p9_spearman_vs_ground_truth.csv", index=False)

    print(f"\nSpearman rank correlation vs each ground truth (n={len(groups)} wards; exact permutation")
    print("p-values over all 720 orderings -- still weak evidence at n=6, read descriptively):")
    print(corr_df.to_string(index=False))

    _plots(ground_truth, gt_eq, ranks, groups)
    return {"ground_truth": ground_truth, "scores": scores, "ranks": ranks, "corr": corr_df}


def _plots(ground_truth, gt_eq, ranks, groups):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, gt, label in [
        (axes[0], ground_truth, "A: 50% cut of each ward's contacts"),
        (axes[1], gt_eq, "B: same contact-hours removed from each ward"),
    ]:
        g = gt.sort_values("drop_person_days_mean", ascending=False)
        err = [g["drop_person_days_mean"] - g["drop_ci_low"], g["drop_ci_high"] - g["drop_person_days_mean"]]
        ax.bar(g["ward"], g["drop_person_days_mean"], yerr=err, capsize=4, color="steelblue")
        ax.set_title(label, fontsize=10)
        ax.tick_params(axis="x", rotation=30)
    axes[0].set_ylabel("drop in colonized person-days vs baseline\n(mean, 95% paired CI)")
    fig.suptitle("P9: simulated superspreader ground truths")
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
