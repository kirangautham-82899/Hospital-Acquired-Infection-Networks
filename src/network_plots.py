"""Plotting helpers for the P2 contact network report. Kept separate from
src/network.py so that module stays pure data logic."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import seaborn as sns

import config


def plot_ward_heatmap(matrix, title, path):
    """Save a heatmap of a ward x ward matrix (raw seconds or row-
    normalized W) to path."""
    is_fraction = float(matrix.values.max()) <= 1.0001
    fig, ax = plt.subplots(figsize=(6, 5))
    sns.heatmap(matrix, annot=True, fmt=".2f" if is_fraction else ".0f", cmap="viridis", ax=ax)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_degree_distribution(node_metrics_df, path):
    """Save side-by-side histograms of node degree and node strength
    (total contact hours) to path."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].hist(node_metrics_df["degree"], bins=30, color="steelblue")
    axes[0].set_title("Degree distribution")
    axes[0].set_xlabel("degree (# distinct contact partners)")
    axes[0].set_ylabel("# people")

    axes[1].hist(node_metrics_df["strength_seconds"] / 3600.0, bins=30, color="indianred")
    axes[1].set_title("Strength distribution")
    axes[1].set_xlabel("strength (total contact hours)")
    axes[1].set_ylabel("# people")

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_network_by_ward(graph, ward_of, path, seed=None):
    """Save a spring-layout drawing of the contact network, node color =
    ward group, edge width/alpha faint (this graph is dense)."""
    seed = config.SEED if seed is None else seed
    pos = nx.spring_layout(graph, seed=seed, weight="seconds", k=0.25)

    palette = sns.color_palette("tab10", len(config.WARD_GROUPS))
    color_of_group = dict(zip(config.WARD_GROUPS, palette))
    node_colors = [color_of_group[ward_of.get(n, "Other")] for n in graph.nodes()]

    fig, ax = plt.subplots(figsize=(9, 9))
    nx.draw_networkx_edges(graph, pos, alpha=0.04, width=0.5, ax=ax)
    nx.draw_networkx_nodes(graph, pos, node_color=node_colors, node_size=25, ax=ax)

    handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=color_of_group[g], label=g, markersize=8)
        for g in config.WARD_GROUPS
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=8, title="Ward group")
    ax.set_title("Contact network colored by ward group")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
