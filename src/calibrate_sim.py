"""P4 calibration: fit (beta, gamma, epsilon) against P3's real weekly
prevalence series (states_real.csv).

Comparing like with like (locked decision, see research_log.md): the real
series only reflects people who were actually tested that week, while the
simulator knows everyone's status every day. So the calibration objective
reads each tested person's SIMULATED status on their REAL test date and
aggregates it with the exact same rule P3 used for the real data ("any
positive test that week counts as positive, person counts once in the
denominator") -- not a full-population daily mean (that convention is used
only for the training-trajectory dataset, see src/trajectories.py).

The loss is the n_tested-weighted mean squared error between real and
simulated weekly ward prevalence, over the calibration weeks only (0-11),
excluding group-weeks P3 flagged low_n (fewer than 10 tested people).

Grid search uses COMMON RANDOM NUMBERS: the same N_CALIBRATION_REPLICATES
seeds (for both the initial-condition draw and the daily dynamics) are
reused at every grid point, so differences in loss reflect the parameters,
not sampling noise. Each grid point's simulated prevalence is the mean, at
each (week, group) cell, of that cell's prevalence across the replicates.
"""
import numpy as np
import pandas as pd

import config
from src.network import assign_week
from src.simulate import simulate_sis
from src.wards import person_ward_map


def calibration_initial_state(people, index, pre_window_last_status, admission, seed):
    """Initial state for calibration runs: each person's last known
    pre-window status if they have one. For people with no pre-window
    test, draw Bernoulli(their group's pre-window prevalence) -- never
    default to susceptible, which would bias prevalence downward (locked
    decision, research_log.md)."""
    ward_of = person_ward_map(admission)
    last_status = dict(zip(pre_window_last_status["calc_ident"], pre_window_last_status["last_status"]))

    has_status = pre_window_last_status.copy()
    has_status["ward_group"] = has_status["calc_ident"].map(ward_of)
    group_prevalence = has_status.groupby("ward_group")["last_status"].mean()
    overall_prevalence = has_status["last_status"].mean()

    rng = np.random.default_rng(seed)
    state = np.zeros(len(people), dtype=bool)
    for p in people:
        if p in last_status:
            state[index[p]] = bool(last_status[p])
        else:
            group = ward_of.get(p, None)
            prevalence = group_prevalence.get(group, overall_prevalence)
            state[index[p]] = rng.random() < prevalence
    return state


def simulated_status_at_test_dates(microbio_in_window, population, day_list, history, index):
    """One row per real test event on a person in `population`, with the
    simulated status (0/1) looked up from `history` on that test's
    calendar day. Multiple same-person tests in a week each get their own
    simulated status, so the 'any positive that week' rule can be applied
    identically to how P3 applies it to the real sarm results."""
    day_to_t = {d: t for t, d in enumerate(day_list)}
    df = microbio_in_window[microbio_in_window["calc_ident"].isin(population)].copy()
    df = df[df["date_prl"].isin(day_to_t)]
    t_idx = df["date_prl"].map(day_to_t).to_numpy()
    p_idx = df["calc_ident"].map(index).to_numpy()
    df["sim_status"] = history[t_idx, p_idx].astype(int)
    return df


def simulated_weekly_prevalence(sim_status_rows, admission, groups):
    """Aggregate simulated per-test-event status into (week, group,
    n_tested, n_positive, prevalence), using the same 'any positive that
    week counts positive, person counts once' rule as
    src.states.weekly_prevalence."""
    df = sim_status_rows.copy()
    df["week"] = assign_week(df["date_prl"])
    ward_of = person_ward_map(admission)
    df["ward_group"] = df["calc_ident"].map(ward_of)

    per_person_week = (
        df.groupby(["calc_ident", "week", "ward_group"])["sim_status"].max().reset_index()
    )
    agg = (
        per_person_week.groupby(["week", "ward_group"])
        .agg(n_tested=("calc_ident", "nunique"), n_positive=("sim_status", "sum"))
        .reset_index()
        .rename(columns={"ward_group": "group"})
    )
    agg["prevalence"] = agg["n_positive"] / agg["n_tested"]
    agg = agg[agg["group"].isin(groups)]
    return agg.sort_values(["week", "group"]).reset_index(drop=True)


def calibration_loss(states_real, sim_prevalence, weeks):
    """n_tested(real)-weighted mean squared error between real and
    simulated weekly ward prevalence, restricted to `weeks`, excluding
    P3's low_n-flagged group-weeks. Returns (loss, merged_table). Uses
    states_real's own n_tested as the weight regardless of whether
    sim_prevalence also has an n_tested column (explicit rename before
    merge, rather than relying on pandas' merge-suffix behavior)."""
    real = states_real[states_real["week"].isin(weeks) & (~states_real["low_n"])]
    real = real.rename(columns={"prevalence": "prevalence_real"})
    sim = sim_prevalence[["week", "group", "prevalence"]].rename(columns={"prevalence": "prevalence_sim"})
    merged = real.merge(sim, on=["week", "group"], how="inner")
    if merged.empty:
        return np.nan, merged
    sq_err = (merged["prevalence_real"] - merged["prevalence_sim"]) ** 2
    weight = merged["n_tested"]
    loss = float((weight * sq_err).sum() / weight.sum())
    return loss, merged


def run_one_replicate(beta, gamma, epsilon, ic_seed, dyn_seed, people, index, day_list, edge_arrays_by_day,
                       pre_window_last_status, admission, microbio_in_window, groups):
    """Run one calibration replicate end to end: build the initial state,
    simulate, and return this replicate's simulated weekly prevalence."""
    initial = calibration_initial_state(people, index, pre_window_last_status, admission, seed=ic_seed)
    history = simulate_sis(initial, day_list, edge_arrays_by_day, beta, gamma, epsilon, seed=dyn_seed)
    status_rows = simulated_status_at_test_dates(microbio_in_window, set(people), day_list, history, index)
    return simulated_weekly_prevalence(status_rows, admission, groups)


def replicate_seed_pairs(n_replicates, base_seed=None):
    """Spawn n_replicates independent (ic_seed, dyn_seed) SeedSequence pairs
    from one base seed. The SAME pairs are reused at every grid point
    (common random numbers), so grid points differ only in their
    parameters, not their random draws."""
    base_seed = config.SEED if base_seed is None else base_seed
    ss = np.random.SeedSequence(base_seed)
    replicate_seeds = ss.spawn(n_replicates)
    return [tuple(rep.spawn(2)) for rep in replicate_seeds]


def evaluate_grid_point(beta, gamma, epsilon, seed_pairs, people, index, day_list, edge_arrays_by_day,
                         pre_window_last_status, admission, microbio_in_window, groups, states_real, weeks):
    """Run all replicates for one (beta, gamma, epsilon), average their
    simulated prevalence per (week, group) cell, then score against
    states_real over `weeks`. Returns (loss, avg_sim_prevalence)."""
    replicate_tables = []
    for ic_seed, dyn_seed in seed_pairs:
        sim_prev = run_one_replicate(
            beta, gamma, epsilon, ic_seed, dyn_seed, people, index, day_list, edge_arrays_by_day,
            pre_window_last_status, admission, microbio_in_window, groups,
        )
        replicate_tables.append(sim_prev)

    combined = pd.concat(replicate_tables, ignore_index=True)
    avg = (
        combined.groupby(["week", "group"])
        .agg(prevalence=("prevalence", "mean"), n_tested=("n_tested", "first"))
        .reset_index()
    )
    loss, _ = calibration_loss(states_real, avg, weeks)
    return loss, avg


def grid_search(people, index, day_list, edge_arrays_by_day, pre_window_last_status, admission,
                 microbio_in_window, groups, states_real, weeks=None, beta_grid=None, gamma_grid=None,
                 epsilon_grid=None, n_replicates=None):
    """Evaluate every (beta, gamma, epsilon) combination in the grid with
    common random numbers, returning the full loss table sorted by loss."""
    weeks = config.CALIBRATION_WEEKS if weeks is None else weeks
    beta_grid = config.BETA_GRID if beta_grid is None else beta_grid
    gamma_grid = config.GAMMA_GRID if gamma_grid is None else gamma_grid
    epsilon_grid = config.EPSILON_GRID if epsilon_grid is None else epsilon_grid
    n_replicates = config.N_CALIBRATION_REPLICATES if n_replicates is None else n_replicates

    seed_pairs = replicate_seed_pairs(n_replicates)

    rows = []
    for beta in beta_grid:
        for gamma in gamma_grid:
            for epsilon in epsilon_grid:
                loss, _ = evaluate_grid_point(
                    beta, gamma, epsilon, seed_pairs, people, index, day_list, edge_arrays_by_day,
                    pre_window_last_status, admission, microbio_in_window, groups, states_real, weeks,
                )
                rows.append({"beta": beta, "gamma": gamma, "epsilon": epsilon, "loss": loss})

    table = pd.DataFrame(rows).sort_values("loss").reset_index(drop=True)
    return table


def is_on_edge(best_row, beta_grid, gamma_grid, epsilon_grid):
    """Return which of beta/gamma/epsilon sit at the min or max of their
    grid (a sign the grid should be widened in that direction)."""
    edges = {}
    for name, grid in [("beta", beta_grid), ("gamma", gamma_grid), ("epsilon", epsilon_grid)]:
        value = best_row[name]
        if np.isclose(value, min(grid)):
            edges[name] = "low"
        elif np.isclose(value, max(grid)):
            edges[name] = "high"
    return edges
