"""P7 orchestrator: eigendecompose each fitted EDMD operator (D1/D2/D3
from P6), filter spurious/trivial modes, map the remaining modes to ward
space in original prevalence units, and identify the dominant
ward-relevant mode per dictionary as a first-pass "which wards matter
most for persistent dynamics" signal -- feeding into P9's proper
superspreader validation against the simulated intervention ground truth.

Writes:
  results/tables/p7_modes_<dict>.csv               (every mode, full detail)
  results/tables/p7_dominant_mode_ward_ranking.csv  (cross-dictionary comparison)
  results/figures/p7_eigenvalue_spectrum_<dict>.png (complex plane, unit circle)
  results/figures/p7_dominant_mode_wards_<dict>.png (ward bar chart)
"""
import numpy as np
import pandas as pd

import config
from src.eigen import dominant_ward_relevant_mode, eigendecompose, mode_table, mode_ward_patterns, null_space_rank_cutoff


def load_p6_model(name):
    d = np.load(config.RESULTS_MODELS_DIR / f"p6_edmd_{name}.npz", allow_pickle=True)
    return {
        "K": d["K"], "scale_": d["scaler_scale"], "C": d["C"],
        "feature_names": list(d["feature_names"]), "groups": list(d["groups"]),
        "best_lambda": float(d["best_lambda"]),
    }


def analyze_dictionary(name):
    model = load_p6_model(name)
    K, C, scale_, groups = model["K"], model["C"], model["scale_"], model["groups"]

    eigvals, eigvecs = eigendecompose(K)
    rank_cutoff = null_space_rank_cutoff(K)
    ward_patterns = mode_ward_patterns(eigvecs, C, scale_)
    df = mode_table(eigvals, ward_patterns, rank_cutoff, groups)
    df.insert(0, "dictionary", name)

    dominant_idx = dominant_ward_relevant_mode(df)
    return df, dominant_idx, model


def _spectrum_plot(name, df, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5, 5))
    theta = np.linspace(0, 2 * np.pi, 200)
    ax.plot(np.cos(theta), np.sin(theta), "k--", linewidth=1, label="unit circle")

    for label, mask, color in [
        ("ward-relevant", ~df["spurious_null_space"] & ~df["zero_ward_pattern"], "steelblue"),
        ("zero ward pattern", df["zero_ward_pattern"], "gray"),
        ("spurious (null space)", df["spurious_null_space"], "lightcoral"),
    ]:
        sub = df[mask]
        if len(sub):
            ax.scatter(sub["eigenvalue_real"], sub["eigenvalue_imag"], s=30, alpha=0.7, label=label, color=color)

    ax.set_xlabel("Re(lambda)")
    ax.set_ylabel("Im(lambda)")
    ax.set_title(f"{name}: eigenvalue spectrum")
    ax.set_aspect("equal")
    ax.legend(fontsize=7, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _dominant_ward_plot(name, df, dominant_idx, groups, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if dominant_idx is None:
        return
    row = df[df["mode"] == dominant_idx].iloc[0]
    shares = [row[f"share_{g}"] for g in groups]

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(groups, shares, color="steelblue")
    ax.set_ylabel("ward share of dominant mode")
    lam = complex(row["eigenvalue_real"], row["eigenvalue_imag"])
    ax.set_title(f"{name}: dominant ward-relevant mode (lambda={lam:.4f}, |lambda|={row['magnitude']:.4f})")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def build():
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    print("P7 EIGENMODE BUILD SUMMARY")
    print("=" * 60)

    ranking_rows = []
    for name in config.EDMD_DICTIONARIES:
        df, dominant_idx, model = analyze_dictionary(name)
        df.to_csv(config.RESULTS_TABLES_DIR / f"p7_modes_{name}.csv", index=False)

        n_spurious = int(df["spurious_null_space"].sum())
        n_zero_pattern = int(df["zero_ward_pattern"].sum())
        print(f"\n[{name}] {len(df)} modes total: {n_spurious} spurious (null space), "
              f"{n_zero_pattern} with a zero ward pattern (invisible through the readout)")

        _spectrum_plot(name, df, config.RESULTS_FIGURES_DIR / f"p7_eigenvalue_spectrum_{name}.png")

        if dominant_idx is None:
            print("  no ward-relevant mode found (all modes spurious or trivial)")
            continue

        row = df[df["mode"] == dominant_idx].iloc[0]
        lam = complex(row["eigenvalue_real"], row["eigenvalue_imag"])
        print(f"  dominant ward-relevant mode: index={dominant_idx}, lambda={lam:.5f}, "
              f"|lambda|={row['magnitude']:.5f}, period={row['period_weeks']:.2f} weeks "
              f"({'oscillatory' if row['conjugate_partner'] >= 0 else 'non-oscillatory'})")

        shares = {g: row[f"share_{g}"] for g in model["groups"]}
        ranked = sorted(shares.items(), key=lambda kv: -kv[1])
        print(f"  ward shares (descending): {ranked}")

        _dominant_ward_plot(
            name, df, dominant_idx, model["groups"],
            config.RESULTS_FIGURES_DIR / f"p7_dominant_mode_wards_{name}.png",
        )

        for ward, share in shares.items():
            ranking_rows.append(
                {"dictionary": name, "mode": dominant_idx, "eigenvalue_magnitude": row["magnitude"], "ward": ward, "share": share}
            )

    ranking_df = pd.DataFrame(ranking_rows)
    ranking_df.to_csv(config.RESULTS_TABLES_DIR / "p7_dominant_mode_ward_ranking.csv", index=False)

    print("\nCross-dictionary agreement on top ward (by dominant-mode share):")
    for name in config.EDMD_DICTIONARIES:
        sub = ranking_df[ranking_df["dictionary"] == name]
        if sub.empty:
            continue
        top = sub.loc[sub["share"].idxmax()]
        print(f"  {name}: {top['ward']} (share={top['share']:.3f})")

    return ranking_df


if __name__ == "__main__":
    build()
