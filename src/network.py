"""P2: person-level contact network and the ward-to-ward contact matrix W.

Two separate representations, by design (see research_log.md for the full
rationale):

  - The person-level network is built from a DEDUPED edge list: one row per
    unordered pair per day. mat.day.csv records each day's contact from
    both sides, and the two sides' measured 'length' disagree for about
    17% of pairs (median gap ~90s) -- consistent with independent
    per-person sensor reads, not data corruption. When both directions
    exist, we average them; when only one exists (~0.1% of pairs), we use
    it as-is.
  - The ward contact matrix W sums the RAW bidirectional rows as given (no
    dedup): W[i, j] is the total contact-seconds that people in ward i
    spent with people in ward j -- i.e. each person's own exposure. This
    makes the diagonal equal to twice the undirected within-ward total,
    since every within-ward pair contributes once from each side.

W is NOT a diffusion operator inside the P4 SIS simulator, which runs
directly on the person-level daily contact edges. W feeds the D3 EDMD
dictionary and the network-exposure baseline.
"""
import networkx as nx
import numpy as np
import pandas as pd

import config
from src.wards import person_prefix, person_ward_map


def dedupe_daily_edges(contacts):
    """Collapse mat.day.csv's both-direction rows into one row per
    unordered pair per day. Canonical order is (u, v) = sorted(from, to).
    When both directions exist for a (day, pair), their 'length' values
    are averaged; when only one direction exists, that value is used
    as-is. Returns columns [day, u, v, seconds]."""
    df = contacts[["from", "to", "day", "length"]].copy()
    swap = df["from"] > df["to"]
    df["u"] = df["from"].where(~swap, df["to"])
    df["v"] = df["to"].where(~swap, df["from"])
    grouped = df.groupby(["day", "u", "v"], as_index=False)["length"].mean()
    grouped = grouped.rename(columns={"length": "seconds"})
    return grouped[["day", "u", "v", "seconds"]].sort_values(["day", "u", "v"]).reset_index(drop=True)


def build_master_edge_list(contacts, save_path=None):
    """Build the deduped, staff-inclusive master edge list and optionally
    save it to save_path (data/processed/, never data/raw/). Downstream
    functions filter this by day range and/or population as needed, so
    only this one file is persisted -- not 110 separate daily graphs."""
    edges = dedupe_daily_edges(contacts)
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        edges.to_csv(save_path, index=False)
    return edges


def filter_people(admission, include_staff=True):
    """Return the set of calc_ident allowed under this population filter:
    all admission people if include_staff, else only the PA (patients-only
    sensitivity run, decision #3)."""
    if include_staff:
        return set(admission["calc_ident"])
    prefix = person_prefix(admission["calc_ident"])
    return set(admission.loc[prefix == "PA", "calc_ident"])


def filter_edges(edges, admission, include_staff=True):
    """Drop edges touching a person outside the population filter."""
    if include_staff:
        return edges
    allowed = filter_people(admission, include_staff=False)
    return edges[edges["u"].isin(allowed) & edges["v"].isin(allowed)]


def monday_on_or_before(date):
    """Return the Monday on or before the given date."""
    date = pd.Timestamp(date)
    return date - pd.Timedelta(days=date.weekday())


def assign_week(day_series, anchor=None):
    """Map each day to a 0-indexed week number using Monday-anchored
    weekly bins. Week 0 is the Monday-Sunday week containing/preceding
    `anchor` (defaults to config.STUDY_START, 2009-07-01, a Wednesday).

    This is Monday-anchored rather than anchored at STUDY_START itself
    because microbio's swabs run Monday-Thursday: bins starting on a
    Wednesday cut each ward's weekly screening round across two bins.
    Verified on the Jul1-Oct25 window: Wed-anchored bins put 655 of 3,812
    person-weeks (17.2%) into >1 bin per screening round, vs 80 of 4,412
    (1.8%) with Monday-anchored bins. See research_log.md."""
    monday_anchor = monday_on_or_before(anchor or config.STUDY_START)
    return ((day_series - monday_anchor).dt.days // 7).astype(int)


def build_graph(edges, nodes=None):
    """Build an undirected networkx.Graph with edge weight 'seconds' =
    summed seconds across all rows in edges (already day/population
    filtered by the caller). If nodes is given, every one of those nodes
    is added first, so a node with no edges in this slice still appears
    (degree 0) instead of being silently dropped."""
    g = nx.Graph()
    if nodes is not None:
        g.add_nodes_from(nodes)
    for u, v, seconds in zip(edges["u"], edges["v"], edges["seconds"]):
        if g.has_edge(u, v):
            g[u][v]["seconds"] += seconds
        else:
            g.add_edge(u, v, seconds=seconds)
    return g


def weekly_graphs(edges, nodes=None, study_start=None):
    """Return {week_number: nx.Graph}, one graph per 7-day bin, built on
    demand from the (already filtered) deduped edge list."""
    edges = edges.copy()
    edges["week"] = assign_week(edges["day"], study_start)
    return {w: build_graph(sub, nodes=nodes) for w, sub in edges.groupby("week")}


def ward_contact_matrix(raw_contacts, admission, include_staff=True):
    """Sum RAW (bidirectional, non-deduped) contact seconds into a ward x
    ward matrix. W_raw[i, j] = total seconds that people in ward i spent
    in contact with people in ward j (each person's own exposure, so the
    diagonal is twice the undirected within-ward total). If include_staff
    is False, restricts to PA-PA contacts over the 5 real wards."""
    ward_of = person_ward_map(admission)
    df = raw_contacts[["from", "to", "length"]].copy()
    df["ward_from"] = df["from"].map(ward_of)
    df["ward_to"] = df["to"].map(ward_of)

    groups = config.WARD_GROUPS if include_staff else [g for g in config.WARD_GROUPS if g != "Other"]
    if not include_staff:
        df = df[(df["ward_from"] != "Other") & (df["ward_to"] != "Other")]

    mat = df.groupby(["ward_from", "ward_to"])["length"].sum().unstack(fill_value=0)
    mat = mat.reindex(index=groups, columns=groups, fill_value=0)
    return mat


def row_normalize(matrix):
    """Row-normalize a matrix so each row sums to 1 (rows that sum to 0
    are left as all-0 rather than producing NaN)."""
    row_sums = matrix.sum(axis=1)
    normalized = matrix.div(row_sums.replace(0, np.nan), axis=0)
    return normalized.fillna(0.0)


def weekly_ward_contact_matrices(raw_contacts, admission, include_staff=True, study_start=None):
    """Same as ward_contact_matrix but one matrix per 7-day week bin.
    Returns {week_number: DataFrame}."""
    df = raw_contacts.copy()
    df["week"] = assign_week(df["day"], study_start)
    groups = config.WARD_GROUPS if include_staff else [g for g in config.WARD_GROUPS if g != "Other"]
    out = {}
    for w, sub in df.groupby("week"):
        out[w] = ward_contact_matrix(sub, admission, include_staff=include_staff)
        out[w] = out[w].reindex(index=groups, columns=groups, fill_value=0)
    return out


def weekly_ward_matrices_long(weekly_matrices):
    """Flatten {week: DataFrame} ward matrices into one long-format table
    (week, ward_from, ward_to, seconds) for a single CSV save instead of
    one file per week."""
    frames = []
    for week, mat in weekly_matrices.items():
        long = mat.stack().reset_index()
        long.columns = ["ward_from", "ward_to", "seconds"]
        long.insert(0, "week", week)
        frames.append(long)
    return pd.concat(frames, ignore_index=True)


def node_metrics(graph, ward_of):
    """Per-node table: degree (# distinct contact partners), strength
    (summed contact-seconds), degree_centrality, betweenness_centrality
    (unweighted, by hop count), and eigenvector_centrality (weighted by
    seconds). ward_of maps calc_ident -> ward_group."""
    degree = dict(graph.degree())
    strength = dict(graph.degree(weight="seconds"))
    degree_centrality = nx.degree_centrality(graph)
    betweenness = nx.betweenness_centrality(graph)
    try:
        eigenvector = nx.eigenvector_centrality_numpy(graph, weight="seconds")
    except Exception:
        eigenvector = {n: np.nan for n in graph.nodes()}

    rows = [
        {
            "calc_ident": n,
            "ward_group": ward_of.get(n, "UNMAPPED"),
            "degree": degree[n],
            "strength_seconds": strength[n],
            "degree_centrality": degree_centrality[n],
            "betweenness_centrality": betweenness[n],
            "eigenvector_centrality": eigenvector[n],
        }
        for n in graph.nodes()
    ]
    return pd.DataFrame(rows)


def within_between_ward_share(edges, admission):
    """Using the deduped person-level edge list, compute what share of
    total contact-seconds (and of unique pair-days) is within the same
    ward vs between different wards. Expected to be high within-ward,
    since most contact happens among people who share a ward."""
    ward_of = person_ward_map(admission)
    df = edges.copy()
    df["ward_u"] = df["u"].map(ward_of)
    df["ward_v"] = df["v"].map(ward_of)
    within = df["ward_u"] == df["ward_v"]
    total_seconds = df["seconds"].sum()

    return pd.DataFrame(
        [
            {
                "measure": "seconds",
                "within_ward": df.loc[within, "seconds"].sum(),
                "between_ward": df.loc[~within, "seconds"].sum(),
                "within_ward_share": df.loc[within, "seconds"].sum() / total_seconds,
            },
            {
                "measure": "pair_days",
                "within_ward": int(within.sum()),
                "between_ward": int((~within).sum()),
                "within_ward_share": float(within.mean()),
            },
        ]
    )
