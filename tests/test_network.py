"""Tests for src/network.py (P2): the deduped person-level edge list, the
raw/row-normalized ward contact matrix W, weekly aggregation, and node
metrics. Two populations are checked: 'all' (staff-inclusive) and
'patients_only' (decision #3 sensitivity run).
"""
import hashlib

import pandas as pd
import pytest

import config
from src.load import load_admission, load_contacts
from src.network import (
    assign_week,
    build_graph,
    dedupe_daily_edges,
    filter_edges,
    filter_people,
    node_metrics,
    row_normalize,
    ward_contact_matrix,
    weekly_ward_contact_matrices,
    within_between_ward_share,
)
from src.wards import person_ward_map


@pytest.fixture(scope="module")
def admission():
    return load_admission(config.ADMISSION_CSV)


@pytest.fixture(scope="module")
def contacts():
    return load_contacts(config.CONTACTS_CSV)


@pytest.fixture(scope="module")
def edges(contacts):
    return dedupe_daily_edges(contacts)


# ---- data/raw/ must stay untouched by any of this ----

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def test_raw_files_unchanged_by_network_build():
    saved = {}
    for line in (config.RESULTS_TABLES_DIR / "raw_hashes.txt").read_text().splitlines():
        digest, name = line.split()
        saved[name] = digest
    assert _sha256(config.ADMISSION_CSV) == saved["admission.csv"]
    assert _sha256(config.CONTACTS_CSV) == saved["mat.day.csv"]
    assert _sha256(config.MICROBIO_CSV) == saved["microbio.csv"]


# ---- dedupe_daily_edges: unit tests on synthetic rows + integration on real data ----

def test_dedupe_averages_mismatched_reciprocal_rows():
    raw = pd.DataFrame(
        {
            "from": ["A", "B"],
            "to": ["B", "A"],
            "day": [pd.Timestamp("2009-07-01")] * 2,
            "length": [100, 200],
        }
    )
    out = dedupe_daily_edges(raw)
    assert len(out) == 1
    assert out.iloc[0]["u"] == "A" and out.iloc[0]["v"] == "B"
    assert out.iloc[0]["seconds"] == 150.0


def test_dedupe_keeps_unreciprocated_row_as_is():
    raw = pd.DataFrame({"from": ["A"], "to": ["B"], "day": [pd.Timestamp("2009-07-01")], "length": [77]})
    out = dedupe_daily_edges(raw)
    assert len(out) == 1
    assert out.iloc[0]["seconds"] == 77


def test_dedupe_no_duplicate_day_pair_rows(edges):
    assert edges.duplicated(subset=["day", "u", "v"]).sum() == 0


def test_dedupe_unique_pair_count_is_19974(edges):
    assert edges[["u", "v"]].drop_duplicates().shape[0] == 19974


def test_dedupe_row_count_between_half_and_original(edges, contacts):
    # 99.9% reciprocity => close to half of 124924, but not exactly, because
    # of the ~144 rows with no reverse partner.
    assert len(edges) == 62534
    assert len(edges) < contacts.shape[0]


# ---- population filters ----

def test_filter_people_patients_only_matches_reference(admission):
    all_people = filter_people(admission, include_staff=True)
    pa_only = filter_people(admission, include_staff=False)
    assert len(all_people) == 795
    assert len(pa_only) == 452


def test_filter_edges_patients_only_drops_any_staff_edge(admission, edges):
    pa_only_edges = filter_edges(edges, admission, include_staff=False)
    allowed = filter_people(admission, include_staff=False)
    assert set(pa_only_edges["u"]) <= allowed
    assert set(pa_only_edges["v"]) <= allowed


# ---- graph construction ----

def test_full_population_graph_has_589_nodes(admission, contacts, edges):
    all_contact_people = set(edges["u"]) | set(edges["v"])
    graph = build_graph(edges, nodes=all_contact_people)
    assert graph.number_of_nodes() == 589
    assert graph.number_of_edges() == 19974


def test_patients_only_graph_has_329_nodes(admission, contacts, edges):
    pop_edges = filter_edges(edges, admission, include_staff=False)
    pop_people = filter_people(admission, include_staff=False)
    all_contact_people = set(edges["u"]) | set(edges["v"])
    nodes = all_contact_people & pop_people
    graph = build_graph(pop_edges, nodes=nodes)
    assert graph.number_of_nodes() == 329


# ---- ward contact matrix W ----

def test_ward_matrix_raw_conserves_total_seconds(admission, contacts):
    w_raw = ward_contact_matrix(contacts, admission, include_staff=True)
    assert float(w_raw.values.sum()) == float(contacts["length"].sum())


def test_ward_matrix_row_normalized_rows_sum_to_1(admission, contacts):
    w_raw = ward_contact_matrix(contacts, admission, include_staff=True)
    w_norm = row_normalize(w_raw)
    row_sums = w_norm.sum(axis=1)
    assert (abs(row_sums - 1.0) < 1e-9).all()


def test_ward_matrix_diagonal_is_about_twice_undirected_within_ward(admission, contacts, edges):
    """W's diagonal sums BOTH directions of every within-ward pair, so it
    should be close to (but not exactly, because of ~144 unreciprocated
    rows) twice the deduped/undirected within-ward total."""
    w_raw = ward_contact_matrix(contacts, admission, include_staff=True)
    ward_of = person_ward_map(admission)
    e = edges.copy()
    e["ward_u"] = e["u"].map(ward_of)
    e["ward_v"] = e["v"].map(ward_of)
    undirected_within = e[e["ward_u"] == e["ward_v"]].groupby("ward_u")["seconds"].sum()

    diag = pd.Series(w_raw.values.diagonal(), index=w_raw.index)
    ratio = diag / undirected_within.reindex(diag.index)
    assert (ratio > 1.99).all() and (ratio <= 2.0001).all()


def test_ward_matrix_patients_only_has_5_wards(admission, contacts):
    pop_people = filter_people(admission, include_staff=False)
    raw_contacts_pop = contacts[contacts["from"].isin(pop_people) & contacts["to"].isin(pop_people)]
    w_raw = ward_contact_matrix(raw_contacts_pop, admission, include_staff=False)
    assert w_raw.shape == (5, 5)
    assert "Other" not in w_raw.index


# ---- weekly aggregation ----

def test_weekly_ward_matrices_sum_to_overall(admission, contacts):
    w_raw_overall = ward_contact_matrix(contacts, admission, include_staff=True)
    weekly = weekly_ward_contact_matrices(contacts, admission, include_staff=True)
    assert len(weekly) == 17
    summed = sum(weekly.values())
    pd.testing.assert_frame_equal(
        summed.sort_index(axis=0).sort_index(axis=1),
        w_raw_overall.sort_index(axis=0).sort_index(axis=1),
        check_dtype=False,
    )


def test_assign_week_range_is_0_to_16(contacts):
    weeks = assign_week(contacts["day"])
    assert weeks.min() == 0
    assert weeks.max() == 16


# ---- within/between ward share ----

def test_within_ward_share_is_high(admission, edges):
    share = within_between_ward_share(edges, admission)
    seconds_row = share.loc[share["measure"] == "seconds"].iloc[0]
    assert seconds_row["within_ward_share"] > 0.5
    assert abs(seconds_row["within_ward"] + seconds_row["between_ward"] - edges["seconds"].sum()) < 1e-6


# ---- node metrics ----

def test_node_metrics_bounds(admission, edges):
    ward_of = person_ward_map(admission)
    all_contact_people = set(edges["u"]) | set(edges["v"])
    graph = build_graph(edges, nodes=all_contact_people)
    metrics = node_metrics(graph, ward_of)
    assert len(metrics) == 589
    assert (metrics["degree"] >= 1).all()  # every node in mat.day.csv has >=1 contact overall
    assert (metrics["degree_centrality"] >= 0).all() and (metrics["degree_centrality"] <= 1).all()
    assert (metrics["betweenness_centrality"] >= 0).all() and (metrics["betweenness_centrality"] <= 1).all()
    assert metrics["ward_group"].isin(config.WARD_GROUPS).all()
