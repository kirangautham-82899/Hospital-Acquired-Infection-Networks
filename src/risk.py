"""P9: ward-level 'risk score' candidates compared against the simulated
superspreader ground truth (src/intervention.py) -- the Koopman/eigenmode
score from P7, and simple network-centrality baselines computed on the
ward-level contact graph (P2's raw ward contact matrix W).

CAUTION carried through every comparison downstream: there are only 6
wards. CLAUDE.md's own known limitations already flag this ("Only 6
groups, so rank statistics are weak") -- any rank correlation computed
against the ground truth in src/build_p9.py has very low statistical
power at n=6 and should be read as descriptive, not as a significance
test.
"""
import numpy as np
import networkx as nx
import pandas as pd

import config


def load_koopman_risk_scores(dict_name, groups):
    """Ward shares of the dominant ward-relevant mode from P7
    (p7_dominant_mode_ward_ranking.csv), for one dictionary, reindexed to
    `groups` order."""
    df = pd.read_csv(config.RESULTS_TABLES_DIR / "p7_dominant_mode_ward_ranking.csv")
    sub = df[df["dictionary"] == dict_name].set_index("ward")["share"]
    return sub.reindex(groups)


def ward_degree_centrality(W_raw, groups):
    """Row sum of the raw ward contact matrix: total contact-seconds
    exposure for each ward's own people -- a simple 'activity level'
    centrality, already directly available from P2 (no new computation
    needed beyond summing)."""
    return pd.Series(np.asarray(W_raw).sum(axis=1), index=groups)


def _symmetrized_graph(W_raw, groups):
    sym = (np.asarray(W_raw) + np.asarray(W_raw).T) / 2.0
    graph = nx.from_numpy_array(sym)
    return nx.relabel_nodes(graph, {i: name for i, name in enumerate(groups)})


def ward_eigenvector_centrality(W_raw, groups):
    """Eigenvector centrality on the SYMMETRIZED ward contact graph
    ((W+W.T)/2, since the raw W is directed/asymmetric by construction --
    see P2's research_log.md entry)."""
    g = _symmetrized_graph(W_raw, groups)
    centrality = nx.eigenvector_centrality_numpy(g, weight="weight")
    return pd.Series(centrality).reindex(groups)


def ward_betweenness_centrality(W_raw, groups):
    """Betweenness centrality on the symmetrized ward contact graph,
    using 1/weight as edge distance (heavier contact = 'closer'). With
    only 6 densely-connected nodes this is expected to be weakly
    informative (many pairs are directly connected, leaving little room
    for a node to sit 'between' others) -- see module docstring."""
    g = _symmetrized_graph(W_raw, groups)
    for _, _, d in g.edges(data=True):
        d["distance"] = 1.0 / d["weight"] if d["weight"] > 0 else np.inf
    centrality = nx.betweenness_centrality(g, weight="distance")
    return pd.Series(centrality).reindex(groups)
