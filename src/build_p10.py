"""P10 orchestrator: compare intervention STRATEGIES (decision content --
see research_log.md for the Part A numbering caveat) under an
equal-budget framework: none, random, whole-hospital, degree-targeted,
and Koopman-targeted (one variant per dictionary, D1/D2/D3, since P9
found they disagree on which ward matters most -- reporting all three
rather than picking one). Two Koopman scores are targeted: the original
dominant-mode ward share (koopman_targeted_*) and, after the Nov 14
review, the seeded-perturbation influence score (koopman_influence_
targeted_*, src/influence.py). k=1 or 2 targeted wards, per-ward reductions
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
  results/tables/p10_per_replicate.csv          (every replicate's colonized person-days)
  results/tables/p10_pairwise_comparisons.csv   (paired CIs vs degree / random / whole-hospital)
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
from src.metrics import paired_mean_ci
from src.risk import load_koopman_influence_scores, load_koopman_risk_scores, top_k_wards, ward_degree_centrality
from src.simulate import build_person_index, daily_edge_arrays, simulation_day_list
from src.calibrate_sim import replicate_seed_pairs

RANDOM_WARD_SEED_BASE = 20261001  # separate root from the ic/dyn seed stream -- see ward_choice_rngs


def build_grid():
    return [
        {"k": k, "R": R, "budget": round(k * R, 6)}
        for k in config.INTERVENTION_K_VALUES
        for R in config.INTERVENTION_REDUCTIONS
    ]


def pairwise_comparisons(per_replicate, grid, references=("degree_targeted", "random", "whole_hospital")):
    """For every (k, R) cell, compare every strategy against each
    reference strategy using the PAIRED per-replicate difference in
    colonized person-days (common random numbers make replicate i of
    both arms share seeds). advantage = person_days(reference) -
    person_days(strategy), so positive means the strategy prevented more
    colonized person-days than the reference. Returns mean, 95% CI and
    paired t-test p-value per comparison."""
    out = []
    for cell in grid:
        k, R = cell["k"], cell["R"]
        strategies = [s for (s, kk, RR) in per_replicate if kk == k and RR == R]
        for ref in references:
            if (ref, k, R) not in per_replicate:
                continue
            for s in strategies:
                if s == ref:
                    continue
                adv = per_replicate[(ref, k, R)] - per_replicate[(s, k, R)]
                ci = paired_mean_ci(adv)
                out.append({
                    "k": k, "R": R, "budget": cell["budget"], "strategy": s, "reference": ref,
                    "advantage_mean": ci["mean"], "ci_low": ci["ci_low"], "ci_high": ci["ci_high"],
                    "p_value": ci["p_value"],
                    "verdict": "better" if ci["ci_low"] > 0 else ("worse" if ci["ci_high"] < 0 else "not distinguishable"),
                })
    return pd.DataFrame(out)


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
    koopman_scores = {}
    for name in config.EDMD_DICTIONARIES:
        koopman_scores[f"koopman_targeted_{name}"] = load_koopman_risk_scores(name, groups)
    for name in config.EDMD_DICTIONARIES:
        koopman_scores[f"koopman_influence_targeted_{name}"] = load_koopman_influence_scores(name, groups)

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

    per_replicate = {("none", 0, 0.0): none_totals}

    def add_row(strategy, k, R, budget, targeted_wards, totals):
        drop = none_totals - totals
        drop_fraction = np.divide(drop, none_totals, out=np.full_like(drop, np.nan), where=none_totals != 0)
        ci = paired_mean_ci(drop)
        per_replicate[(strategy, k, R)] = totals
        rows.append(
            {
                "strategy": strategy, "k": k, "R": R, "budget": budget,
                "targeted_wards": ",".join(targeted_wards) if targeted_wards else "",
                "mean_person_days": totals.mean(), "drop_mean": drop.mean(), "drop_std": drop.std(ddof=1),
                "drop_ci_low": ci["ci_low"], "drop_ci_high": ci["ci_high"],
                "drop_fraction_mean": float(np.nanmean(drop_fraction)),
            }
        )

    for cell in grid:
        k, R, budget = cell["k"], cell["R"], cell["budget"]
        print(f"\n--- k={k}, R={R} (budget={budget:.3g}) ---")

        add_row("whole_hospital", k, R, budget, [], whole_hospital_totals[budget])

        totals_cache = {}
        degree_wards = top_k_wards(degree_scores, k)
        scaled = scale_multiple_ward_edges(edges, admission, degree_wards, scale=1.0 - R)
        totals = run_person_days_replicates(
            people, index, day_list, daily_edge_arrays(scaled, index), beta, gamma, epsilon,
            pre_window_last_status, admission, seed_pairs,
        )
        totals_cache[tuple(sorted(degree_wards))] = totals
        add_row("degree_targeted", k, R, budget, degree_wards, totals)
        print(f"  degree_targeted {degree_wards}: drop={none_totals.mean() - totals.mean():.2f}")

        for strategy, score in koopman_scores.items():
            koop_wards = top_k_wards(score, k)
            key = tuple(sorted(koop_wards))
            if key not in totals_cache:  # same ward set + R gives identical CRN totals
                scaled = scale_multiple_ward_edges(edges, admission, koop_wards, scale=1.0 - R)
                totals_cache[key] = run_person_days_replicates(
                    people, index, day_list, daily_edge_arrays(scaled, index), beta, gamma, epsilon,
                    pre_window_last_status, admission, seed_pairs,
                )
            totals = totals_cache[key]
            add_row(strategy, k, R, budget, koop_wards, totals)
            print(f"  {strategy} {koop_wards}: drop={none_totals.mean() - totals.mean():.2f}")

        random_totals, _ = run_person_days_random_wards(
            people, index, day_list, edges, admission, groups, k, 1.0 - R,
            beta, gamma, epsilon, pre_window_last_status, seed_pairs, RANDOM_WARD_SEED_BASE,
        )
        add_row("random", k, R, budget, [], random_totals)
        print(f"  random: drop={none_totals.mean() - random_totals.mean():.2f}")

    results = pd.DataFrame(rows)
    results.to_csv(config.RESULTS_TABLES_DIR / "p10_intervention_results.csv", index=False)

    per_rep_df = pd.DataFrame(
        [
            {"strategy": s, "k": k, "R": R, "replicate": i, "person_days": float(v)}
            for (s, k, R), arr in per_replicate.items()
            for i, v in enumerate(arr)
        ]
    )
    per_rep_df.to_csv(config.RESULTS_TABLES_DIR / "p10_per_replicate.csv", index=False)

    pairwise = pairwise_comparisons(per_replicate, grid)
    pairwise.to_csv(config.RESULTS_TABLES_DIR / "p10_pairwise_comparisons.csv", index=False)
    print("\nPaired comparisons (drop of strategy A minus drop of strategy B; positive = A better):")
    print(pairwise.to_string(index=False))

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

    # One panel per k, so k=1 and k=2 cells that share a budget are never
    # joined by one line. Strategies that target identical wards overlap.
    ks = config.INTERVENTION_K_VALUES
    fig, axes = plt.subplots(1, len(ks), figsize=(13, 5), sharey=True)
    strategies = [s for s in results["strategy"].unique() if s != "none"]
    for ax, k in zip(np.atleast_1d(axes), ks):
        for strategy in strategies:
            sub = results[(results["strategy"] == strategy) & (results["k"] == k)].sort_values("budget")
            err = [sub["drop_mean"] - sub["drop_ci_low"], sub["drop_ci_high"] - sub["drop_mean"]]
            ax.errorbar(sub["budget"], sub["drop_mean"], yerr=err, marker="o", label=strategy, capsize=3)
        ax.set_title(f"k = {k} targeted ward{'s' if k > 1 else ''}")
        ax.set_xlabel("budget (k x reduction fraction)")
    np.atleast_1d(axes)[0].set_ylabel("drop in colonized person-days vs no intervention\n(mean, 95% paired CI)")
    np.atleast_1d(axes)[0].legend(fontsize=7, loc="upper left")
    fig.suptitle("P10: intervention strategy comparison, equal budget")
    fig.tight_layout()
    fig.savefig(config.RESULTS_FIGURES_DIR / "p10_drop_vs_budget.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    build()
