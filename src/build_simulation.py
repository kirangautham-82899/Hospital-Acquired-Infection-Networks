"""P4 orchestrator: calibrate (beta, gamma, epsilon) against P3's real
weekly prevalence, then generate the training-trajectory dataset.

Writes:
  results/tables/p4_calibration_grid.csv       (full loss table, every grid point)
  results/tables/p4_calibrated_params.csv      (best point + holdout sanity check)
  results/figures/p4_calibration_fit.png       (sim vs real, calibration/holdout marked)
  data/processed/states_sim.npz                (training trajectories: states + metadata)
  results/tables/p4_trajectories_metadata.csv  (human-readable copy of the metadata)

Population is a parameter (config.DEFAULT_SIMULATION_POPULATION = "all");
the patients-only variant is deferred to experiment E6, not run here.
"""
import numpy as np
import pandas as pd

import config
from src.calibrate_sim import evaluate_grid_point, grid_search, is_on_edge, replicate_seed_pairs
from src.load import load_admission, load_contacts, load_microbio
from src.network import filter_edges, filter_people
from src.simulate import build_person_index, daily_edge_arrays, simulation_day_list
from src.states import restrict_to_window
from src.trajectories import generate_trajectories


def load_p4_inputs(population="all"):
    admission = load_admission(config.ADMISSION_CSV)
    contacts = load_contacts(config.CONTACTS_CSV)
    microbio = load_microbio(config.MICROBIO_CSV)
    edges = pd.read_csv(config.DATA_PROCESSED_DIR / "edges_master.csv", parse_dates=["day"])
    pre_window_last_status = pd.read_csv(config.DATA_PROCESSED_DIR / "states_pre_window_last_status.csv")
    states_real = pd.read_csv(config.RESULTS_TABLES_DIR / "p3_states_real.csv")

    include_staff = population == "all"
    groups = config.WARD_GROUPS if include_staff else [g for g in config.WARD_GROUPS if g != "Other"]

    edges = filter_edges(edges, admission, include_staff=include_staff)
    network_people = set(contacts["from"]) | set(contacts["to"])
    pop_people = filter_people(admission, include_staff=include_staff)
    people_set = network_people if include_staff else (network_people & pop_people)

    people, index = build_person_index(people_set)
    day_list = simulation_day_list()
    edge_arrays_by_day = daily_edge_arrays(edges, index)

    in_window, before_window, after_window = restrict_to_window(microbio)

    return {
        "admission": admission, "microbio_in_window": in_window,
        "pre_window_last_status": pre_window_last_status, "states_real": states_real,
        "people": people, "index": index, "day_list": day_list,
        "edge_arrays_by_day": edge_arrays_by_day, "groups": groups,
    }


def widen_grid_if_needed(table, beta_grid, gamma_grid, epsilon_grid, ctx, max_rounds=1):
    """If the best grid point sits on an edge, widen that axis (extend the
    range 3x in the hugged direction, same point density) and rerun the
    full grid search once. Returns (table, beta_grid, gamma_grid, epsilon_grid, widened: bool)."""
    best = table.iloc[0]
    edges = is_on_edge(best, beta_grid, gamma_grid, epsilon_grid)
    if not edges or max_rounds <= 0:
        return table, beta_grid, gamma_grid, epsilon_grid, False

    print(f"Best grid point is on an edge: {edges}. Widening and re-running once.")
    new_grids = {"beta": list(beta_grid), "gamma": list(gamma_grid), "epsilon": list(epsilon_grid)}
    for name, direction in edges.items():
        grid = np.array(new_grids[name])
        n = len(grid)
        if direction == "low":
            new_min, new_max = grid.min() / 3.0, grid.max()
        else:
            new_min, new_max = grid.min(), grid.max() * 3.0
        new_grids[name] = list(np.geomspace(new_min, new_max, n))

    widened_table = grid_search(
        ctx["people"], ctx["index"], ctx["day_list"], ctx["edge_arrays_by_day"],
        ctx["pre_window_last_status"], ctx["admission"], ctx["microbio_in_window"], ctx["groups"],
        ctx["states_real"], beta_grid=new_grids["beta"], gamma_grid=new_grids["gamma"],
        epsilon_grid=new_grids["epsilon"],
    )
    return widened_table, new_grids["beta"], new_grids["gamma"], new_grids["epsilon"], True


def build(population=None, n_trajectories=None):
    population = config.DEFAULT_SIMULATION_POPULATION if population is None else population
    n_trajectories = config.N_TRAINING_TRAJECTORIES if n_trajectories is None else n_trajectories

    config.DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    ctx = load_p4_inputs(population)
    print("P4 SIMULATION BUILD SUMMARY")
    print("=" * 60)
    print(f"Population: {population}, n_people={len(ctx['people'])}, groups={ctx['groups']}")

    table = grid_search(
        ctx["people"], ctx["index"], ctx["day_list"], ctx["edge_arrays_by_day"],
        ctx["pre_window_last_status"], ctx["admission"], ctx["microbio_in_window"], ctx["groups"],
        ctx["states_real"],
    )
    table, beta_grid, gamma_grid, epsilon_grid, widened = widen_grid_if_needed(
        table, config.BETA_GRID, config.GAMMA_GRID, config.EPSILON_GRID, ctx
    )
    table.to_csv(config.RESULTS_TABLES_DIR / "p4_calibration_grid.csv", index=False)

    best = table.iloc[0]
    remaining_edges = is_on_edge(best, beta_grid, gamma_grid, epsilon_grid)
    print(f"\nBest calibration point: beta={best['beta']:.5g}, gamma={best['gamma']:.5g}, "
          f"epsilon={best['epsilon']:.5g}, loss={best['loss']:.5g}")
    if remaining_edges:
        print(f"WARNING: best point still on an edge after widening: {remaining_edges}. "
              f"Report this as a limitation -- see research_log.md.")
    print(f"Loss ridge check: {int((table['loss'] < best['loss'] * 1.1).sum())} of {len(table)} grid points "
          f"are within 10% of the best loss (expect a ridge, not a single sharp minimum).")

    # Held-out sanity check (never used to pick the point)
    seed_pairs = replicate_seed_pairs(config.N_CALIBRATION_REPLICATES)
    holdout_loss, holdout_merged = evaluate_grid_point(
        best["beta"], best["gamma"], best["epsilon"], seed_pairs, ctx["people"], ctx["index"],
        ctx["day_list"], ctx["edge_arrays_by_day"], ctx["pre_window_last_status"], ctx["admission"],
        ctx["microbio_in_window"], ctx["groups"], ctx["states_real"], config.HOLDOUT_WEEKS,
    )
    from src.calibrate_sim import calibration_loss
    holdout_score, _ = calibration_loss(ctx["states_real"], holdout_merged, config.HOLDOUT_WEEKS)
    print(f"Held-out loss (weeks {config.HOLDOUT_WEEKS[0]}-{config.HOLDOUT_WEEKS[-1]}, sanity check only): "
          f"{holdout_score:.5g}")

    params_out = pd.DataFrame(
        [
            {
                "beta": best["beta"], "gamma": best["gamma"], "epsilon": best["epsilon"],
                "calibration_loss": best["loss"], "holdout_loss": holdout_score,
                "grid_widened": widened, "still_on_edge": bool(remaining_edges),
            }
        ]
    )
    params_out.to_csv(config.RESULTS_TABLES_DIR / "p4_calibrated_params.csv", index=False)

    _fit_plot(ctx, best, seed_pairs)

    # ---- Training trajectories ----
    calibrated_params = {"beta": best["beta"], "gamma": best["gamma"], "epsilon": best["epsilon"]}
    states, metadata = generate_trajectories(
        n_trajectories, ctx["people"], ctx["index"], ctx["day_list"], ctx["edge_arrays_by_day"],
        ctx["admission"], calibrated_params, ctx["states_real"], groups=ctx["groups"],
    )
    np.savez(
        config.DATA_PROCESSED_DIR / "states_sim.npz",
        states=states,
        groups=np.array(ctx["groups"]),
        trajectory=metadata["trajectory"].to_numpy(),
        scenario=metadata["scenario"].to_numpy(),
        seed_ward=metadata["seed_ward"].astype(str).to_numpy(),
        n_seeds=metadata["n_seeds"].fillna(-1).to_numpy(),
        beta=metadata["beta"].to_numpy(),
        gamma=metadata["gamma"].to_numpy(),
        epsilon=metadata["epsilon"].to_numpy(),
        ic_seed=metadata["ic_seed"].to_numpy(),
        param_seed=metadata["param_seed"].to_numpy(),
        dyn_seed=metadata["dyn_seed"].to_numpy(),
    )
    metadata.to_csv(config.RESULTS_TABLES_DIR / "p4_trajectories_metadata.csv", index=False)
    print(f"\nGenerated {len(metadata)} trajectories: "
          f"{(metadata['scenario'] == 'endemic').sum()} endemic, "
          f"{(metadata['scenario'] == 'outbreak').sum()} outbreak.")
    print(f"states_sim.npz shape: {states.shape} [trajectory, week, group]")

    return {"table": table, "best": best, "states": states, "metadata": metadata}


def _fit_plot(ctx, best, seed_pairs):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.calibrate_sim import evaluate_grid_point

    all_weeks = sorted(config.CALIBRATION_WEEKS + config.HOLDOUT_WEEKS)
    _, sim_all = evaluate_grid_point(
        best["beta"], best["gamma"], best["epsilon"], seed_pairs, ctx["people"], ctx["index"],
        ctx["day_list"], ctx["edge_arrays_by_day"], ctx["pre_window_last_status"], ctx["admission"],
        ctx["microbio_in_window"], ctx["groups"], ctx["states_real"], all_weeks,
    )

    n_groups = len(ctx["groups"])
    fig, axes = plt.subplots(2, (n_groups + 1) // 2, figsize=(14, 7), sharex=True, sharey=True)
    axes = np.atleast_1d(axes).flatten()
    for ax, group in zip(axes, ctx["groups"]):
        real = ctx["states_real"][ctx["states_real"]["group"] == group]
        sim = sim_all[sim_all["group"] == group]
        real_calib = real[real["week"].isin(config.CALIBRATION_WEEKS)]
        real_holdout = real[real["week"].isin(config.HOLDOUT_WEEKS)]
        ax.plot(real_calib["week"], real_calib["prevalence"], "o-", color="steelblue", label="real (calib)")
        ax.plot(real_holdout["week"], real_holdout["prevalence"], "o--", color="darkorange", label="real (holdout)")
        ax.plot(sim["week"], sim["prevalence"], "x-", color="black", alpha=0.6, label="simulated (calibrated)")
        ax.axvline(config.CALIBRATION_WEEKS[-1] + 0.5, color="gray", linestyle=":", linewidth=1)
        ax.set_title(group)
        ax.set_ylim(0, 1)
    axes[0].legend(fontsize=7, loc="upper right")
    fig.supxlabel("week (0 = Mon 2009-06-29); dotted line = calibration/holdout split")
    fig.supylabel("MRSA prevalence")
    fig.suptitle(f"Calibration fit: beta={best['beta']:.4g}, gamma={best['gamma']:.4g}, epsilon={best['epsilon']:.4g}")
    fig.tight_layout()
    fig.savefig(config.RESULTS_FIGURES_DIR / "p4_calibration_fit.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    build()
