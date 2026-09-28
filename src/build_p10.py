"""P10 orchestrator: compare intervention STRATEGIES (decision content --
see research_log.md for the Part A numbering caveat) under an
equal-budget framework: none, random, whole-hospital, degree-targeted,
and Koopman-targeted (one variant per dictionary, D1/D2/D3, since P9
found they disagree on which ward matters most -- reporting all three
rather than picking one). k=1 or 2 targeted wards, per-ward reductions
25/50/75%, 200 replicates with COMMON RANDOM NUMBERS shared across every
strategy and config for a paired, variance-reduced comparison, all using
P4's calibrated (beta, gamma, epsilon) and calibration initial condition
(never re-calibrated).

Equal budget (locked definition): budget(k, R) = k * R. The whole-
hospital strategy, to be compared fairly against a k-ward targeted
strategy at reduction R, applies budget/6 to ALL 6 wards -- otherwise
"cut everyone by R%" would trivially beat "cut k wards by R%" just by
spending more total resource, which would not be a meaningful comparison
of TARGETING quality. Some (k, R) cells share a budget (e.g. k=1,R=50%
and k=2,R=25% both give budget=0.5) -- whole-hospital is computed once
per DISTINCT budget and reused across every grid cell with that budget.

Writes:
  results/tables/p10_intervention_results.csv   (every strategy x k x R row)
  results/tables/p10_best_strategy_per_budget.csv
  results/figures/p10_drop_vs_budget.png
"""
import numpy as np
import pandas as pd

import config
from src.intervention import (
    run_person_days_random_wards,
    run_person_days_replicates,
    scale_multiple_ward_edges,
)
from src.load import load_admission, load_contacts
from src.network import build_master_edge_list
from src.risk import load_koopman_risk_scores, top_k_wards, ward_degree_centrality
from src.simulate import build_person_index, daily_edge_arrays, simulation_day_list
from src.calibrate_sim import replicate_seed_pairs

RANDOM_WARD_SEED_BASE = 20261001  # separate root from the ic/dyn seed stream -- see ward_choice_rngs


def build_grid():
    return [
        {"k": k, "R": R, "budget": round(k * R, 6)}
        for k in config.INTERVENTION_K_VALUES
        for R in config.INTERVENTION_REDUCTIONS
    ]


def build(n_replicates=None):
    n_replicates = config.INTERVENTION_N_REPLICATES if n_replicates is None else n_replicates
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

    print("P10 INTERVENTION SIMULATION")
    print("=" * 60)
    print(f"Using P4 calibrated params: beta={beta:.5g}, gamma={gamma:.5g}, epsilon={epsilon:.5g}")
    print(f"{n_replicates} replicates, common random numbers across every strategy/config")

    seed_pairs = replicate_seed_pairs(n_replicates)

    # ---- risk-score candidates for targeting ----
    W_raw = pd.read_csv(config.RESULTS_TABLES_DIR / "p2_ward_matrix_raw_all.csv", index_col=0)
    assert list(W_raw.index) == groups
    degree_scores = ward_degree_centrality(W_raw.to_numpy(), groups)
    koopman_scores = {name: load_koopman_risk_scores(name, groups) for name in config.EDMD_DICTIONARIES}

    # ---- none (baseline) ----
    none_edge_arrays = daily_edge_arrays(edges, index)
    none_totals = run_person_days_replicates(
        people, index, day_list, none_edge_arrays, beta, gamma, epsilon, pre_window_last_status, admission, seed_pairs
    )
    print(f"\n[none] mean person-days: {none_totals.mean():.2f}")

    grid = build_grid()
    distinct_budgets = sorted({cell["budget"] for cell in grid})

    # ---- whole_hospital, once per distinct budget ----
    whole_hospital_totals = {}
    for budget in distinct_budgets:
        per_ward_reduction = budget / len(groups)
        scaled_edges = scale_multiple_ward_edges(edges, admission, groups, scale=1.0 - per_ward_reduction)
        edge_arrays = daily_edge_arrays(scaled_edges, index)
        whole_hospital_totals[budget] = run_person_days_replicates(
            people, index, day_list, edge_arrays, beta, gamma, epsilon, pre_window_last_status, admission, seed_pairs
        )
        print(f"[whole_hospital] budget={budget:.3g} (per-ward reduction={per_ward_reduction:.3g}): "
              f"mean person-days: {whole_hospital_totals[budget].mean():.2f}")

    rows = [
        {
            "strategy": "none", "k": 0, "R": 0.0, "budget": 0.0, "targeted_wards": "",
            "mean_person_days": none_totals.mean(), "drop_mean": 0.0, "drop_std": 0.0, "drop_fraction_mean": 0.0,
        }
    ]

    def add_row(strategy, k, R, budget, targeted_wards, totals):
        drop = none_totals - totals
        drop_fraction = np.divide(drop, none_totals, out=np.full_like(drop, np.nan), where=none_totals != 0)
        rows.append(
            {
                "strategy": strategy, "k": k, "R": R, "budget": budget,
                "targeted_wards": ",".join(targeted_wards) if targeted_wards else "",
                "mean_person_days": totals.mean(), "drop_mean": drop.mean(), "drop_std": drop.std(ddof=1),
                "drop_fraction_mean": float(np.nanmean(drop_fraction)),
            }
        )

    for cell in grid:
        k, R, budget = cell["k"], cell["R"], cell["budget"]
        print(f"\n--- k={k}, R={R} (budget={budget:.3g}) ---")

        add_row("whole_hospital", k, R, budget, [], whole_hospital_totals[budget])

        degree_wards = top_k_wards(degree_scores, k)
        scaled = scale_multiple_ward_edges(edges, admission, degree_wards, scale=1.0 - R)
        totals = run_person_days_replicates(
            people, index, day_list, daily_edge_arrays(scaled, index), beta, gamma, epsilon,
            pre_window_last_status, admission, seed_pairs,
        )
        add_row("degree_targeted", k, R, budget, degree_wards, totals)
        print(f"  degree_targeted {degree_wards}: drop={none_totals.mean() - totals.mean():.2f}")

        for name in config.EDMD_DICTIONARIES:
            koop_wards = top_k_wards(koopman_scores[name], k)
            scaled = scale_multiple_ward_edges(edges, admission, koop_wards, scale=1.0 - R)
            totals = run_person_days_replicates(
                people, index, day_list, daily_edge_arrays(scaled, index), beta, gamma, epsilon,
                pre_window_last_status, admission, seed_pairs,
            )
            add_row(f"koopman_targeted_{name}", k, R, budget, koop_wards, totals)
            print(f"  koopman_targeted_{name} {koop_wards}: drop={none_totals.mean() - totals.mean():.2f}")

        random_totals, _ = run_person_days_random_wards(
            people, index, day_list, edges, admission, groups, k, 1.0 - R,
            beta, gamma, epsilon, pre_window_last_status, seed_pairs, RANDOM_WARD_SEED_BASE,
        )
        add_row("random", k, R, budget, [], random_totals)
        print(f"  random: drop={none_totals.mean() - random_totals.mean():.2f}")

    results = pd.DataFrame(rows)
    results.to_csv(config.RESULTS_TABLES_DIR / "p10_intervention_results.csv", index=False)

    best_per_budget = (
        results[results["strategy"] != "none"]
        .sort_values("drop_mean", ascending=False)
        .groupby("budget", as_index=False)
        .first()
        .sort_values("budget")
    )
    best_per_budget.to_csv(config.RESULTS_TABLES_DIR / "p10_best_strategy_per_budget.csv", index=False)

    print("\nBest strategy per budget level:")
    print(best_per_budget[["budget", "strategy", "targeted_wards", "drop_mean", "drop_fraction_mean"]].to_string(index=False))

    _plot(results)
    return results


def _plot(results):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    strategies = [s for s in results["strategy"].unique() if s != "none"]
    for strategy in strategies:
        sub = results[results["strategy"] == strategy].sort_values("budget")
        ax.errorbar(sub["budget"], sub["drop_mean"], yerr=sub["drop_std"] / np.sqrt(config.INTERVENTION_N_REPLICATES),
                     marker="o", label=strategy, capsize=3)
    ax.set_xlabel("budget (k x reduction fraction)")
    ax.set_ylabel("drop in colonized person-days vs no intervention\n(mean +/- standard error)")
    ax.set_title("P10: intervention strategy comparison, equal budget")
    ax.legend(fontsize=7, loc="upper left")
    fig.tight_layout()
    fig.savefig(config.RESULTS_FIGURES_DIR / "p10_drop_vs_budget.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    build()
