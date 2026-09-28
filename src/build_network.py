"""P2 orchestrator: build the person-level contact network and the ward
contact matrix W, for both the full population and the patients-only (no
staff, decision #3 sensitivity run) population.

Writes:
  data/processed/edges_master.csv        (deduped, staff-inclusive, master)
  results/tables/p2_*.csv
  results/figures/p2_*.png

Never modifies data/raw/. See research_log.md for the W convention (sums
raw bidirectional rows, diagonal = 2x undirected within-ward total) and why
it differs from the deduped person-level edge list.
"""
import config
from src.load import load_admission, load_contacts
from src.network import (
    build_graph,
    build_master_edge_list,
    filter_edges,
    filter_people,
    node_metrics,
    row_normalize,
    ward_contact_matrix,
    weekly_ward_contact_matrices,
    weekly_ward_matrices_long,
    within_between_ward_share,
)
from src.network_plots import plot_degree_distribution, plot_network_by_ward, plot_ward_heatmap
from src.wards import person_ward_map


def build_population_artifacts(admission, contacts, edges, include_staff, tag):
    """Build and save all per-population P2 artifacts (network + W +
    metrics + plots). tag is a short filename suffix, e.g. 'all' or
    'patients_only'. Returns a dict of headline numbers for the summary."""
    pop_edges = filter_edges(edges, admission, include_staff=include_staff)
    pop_people = filter_people(admission, include_staff=include_staff)
    all_contact_people = set(edges["u"]) | set(edges["v"])
    nodes = all_contact_people if include_staff else (all_contact_people & pop_people)

    ward_of = person_ward_map(admission)
    graph = build_graph(pop_edges, nodes=nodes)

    metrics = node_metrics(graph, ward_of)
    metrics.to_csv(config.RESULTS_TABLES_DIR / f"p2_node_metrics_{tag}.csv", index=False)
    plot_degree_distribution(metrics, config.RESULTS_FIGURES_DIR / f"p2_degree_distribution_{tag}.png")
    plot_network_by_ward(graph, ward_of, config.RESULTS_FIGURES_DIR / f"p2_network_by_ward_{tag}.png")

    raw_contacts_pop = contacts[
        contacts["from"].isin(pop_people) & contacts["to"].isin(pop_people)
    ]
    w_raw = ward_contact_matrix(raw_contacts_pop, admission, include_staff=include_staff)
    w_norm = row_normalize(w_raw)
    w_raw.to_csv(config.RESULTS_TABLES_DIR / f"p2_ward_matrix_raw_{tag}.csv")
    w_norm.to_csv(config.RESULTS_TABLES_DIR / f"p2_ward_matrix_W_{tag}.csv")
    plot_ward_heatmap(w_raw, f"Ward contact seconds (raw, {tag})",
                       config.RESULTS_FIGURES_DIR / f"p2_ward_heatmap_raw_{tag}.png")
    plot_ward_heatmap(w_norm, f"Ward contact matrix W (row-normalized, {tag})",
                       config.RESULTS_FIGURES_DIR / f"p2_ward_heatmap_W_{tag}.png")

    weekly = weekly_ward_contact_matrices(raw_contacts_pop, admission, include_staff=include_staff)
    weekly_long = weekly_ward_matrices_long(weekly)
    weekly_long.to_csv(config.RESULTS_TABLES_DIR / f"p2_weekly_ward_matrix_raw_{tag}.csv", index=False)

    share = within_between_ward_share(pop_edges, admission)
    share.to_csv(config.RESULTS_TABLES_DIR / f"p2_within_between_ward_share_{tag}.csv", index=False)

    return {
        "tag": tag,
        "n_nodes": graph.number_of_nodes(),
        "n_edges": graph.number_of_edges(),
        "w_raw_diag_sum": float(w_raw.values.trace()),
        "w_row_sums": w_norm.sum(axis=1).round(6).tolist(),
        "within_ward_share_seconds": float(share.loc[share["measure"] == "seconds", "within_ward_share"].iloc[0]),
        "n_weeks": weekly_long["week"].nunique(),
    }


def build():
    config.DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    admission = load_admission(config.ADMISSION_CSV)
    contacts = load_contacts(config.CONTACTS_CSV)

    edges = build_master_edge_list(contacts, save_path=config.DATA_PROCESSED_DIR / "edges_master.csv")

    summary = {}
    summary["all"] = build_population_artifacts(admission, contacts, edges, include_staff=True, tag="all")
    summary["patients_only"] = build_population_artifacts(
        admission, contacts, edges, include_staff=False, tag="patients_only"
    )

    print("P2 NETWORK BUILD SUMMARY")
    print("=" * 60)
    print(f"Master edge list: {len(edges)} deduped (day, pair) rows, "
          f"{edges[['u', 'v']].drop_duplicates().shape[0]} unique pairs overall")
    for tag, s in summary.items():
        print(f"\n[{tag}]")
        print(f"  nodes={s['n_nodes']}  edges={s['n_edges']}  weeks={s['n_weeks']}")
        print(f"  within-ward share of contact-seconds: {s['within_ward_share_seconds']:.4f}")
        print(f"  W row sums (should all be ~1.0): {s['w_row_sums']}")
    return summary


if __name__ == "__main__":
    build()
