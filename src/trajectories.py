"""P4 training-trajectory generation: simulate endemic-start and
outbreak-start SIS trajectories, centered on the calibrated
(beta, gamma, epsilon), for P5 (observables) and P6 (EDMD fit) to consume.

Weekly state convention for this dataset (locked decision, see
research_log.md -- deliberately DIFFERENT from src/calibrate_sim.py's "at
test date" convention used for the calibration objective): the state for
week w is the MEAN DAILY prevalence over that week's calendar days, across
ALL people in the group. The simulator knows everyone's status every day,
unlike the real (tested-only) data, so there's no reason to subsample it
the way the calibration objective has to.

Two initial-condition schemes (locked decisions):
  - Endemic starts: each ward group's colonization probability = that
    group's baseline real prevalence (mean over the calibration weeks,
    excluding low_n weeks) times an independent Uniform(0.5, 1.5)
    multiplier, capped at 1. The multiplier is drawn independently per
    group per trajectory, to maximize coverage of the joint ward-state
    space (a single shared multiplier per trajectory would only move all
    wards up/down together). Each person in a group is then an
    independent Bernoulli draw at that group's probability.
  - Outbreak starts: everyone susceptible except 1-3 seeded cases in ONE
    randomly chosen ward (the seed ward is varied across trajectories).

beta and gamma are independently varied 0.5x-2x around their calibrated
values per trajectory (epsilon is held fixed at its calibrated value --
decision #9's content only names beta/gamma as varied). Every trajectory
is tagged with its scenario, seed_ward, beta, gamma, epsilon, and seeds.
"""
import numpy as np
import pandas as pd

import config
from src.network import assign_week
from src.simulate import simulate_sis
from src.wards import person_ward_map


def group_baseline_prevalence(states_real, groups):
    """Each group's baseline real prevalence for endemic starts: mean of
    states_real's prevalence over the calibration weeks, excluding
    low_n-flagged group-weeks. Falls back to the overall calibration-week
    mean for any group with no qualifying rows."""
    calib = states_real[states_real["week"].isin(config.CALIBRATION_WEEKS) & (~states_real["low_n"])]
    per_group = calib.groupby("group")["prevalence"].mean()
    overall = calib["prevalence"].mean()
    return per_group.reindex(groups).fillna(overall)


def endemic_initial_state(people, index, ward_of, baseline_prevalence, rng):
    """Randomized endemic start (see module docstring). Returns (state,
    {group: probability_used})."""
    lo, hi = config.ENDEMIC_PREVALENCE_MULTIPLIER_RANGE
    group_prob = {}
    for group, baseline in baseline_prevalence.items():
        multiplier = rng.uniform(lo, hi)
        group_prob[group] = min(1.0, float(baseline) * multiplier)

    state = np.zeros(len(people), dtype=bool)
    draws = rng.random(len(people))
    for p in people:
        prob = group_prob.get(ward_of.get(p), 0.0)
        state[index[p]] = draws[index[p]] < prob
    return state, group_prob


def outbreak_initial_state(people, index, ward_of, rng):
    """Outbreak start (see module docstring). Returns (state, seed_ward,
    n_seeds)."""
    groups_present = sorted({ward_of[p] for p in people if p in ward_of})
    seed_ward = rng.choice(groups_present)
    ward_people = [p for p in people if ward_of.get(p) == seed_ward]

    lo, hi = config.OUTBREAK_SEED_RANGE
    n_seeds = min(int(rng.integers(lo, hi + 1)), len(ward_people))
    seeded = rng.choice(ward_people, size=n_seeds, replace=False)

    state = np.zeros(len(people), dtype=bool)
    for p in seeded:
        state[index[p]] = True
    return state, str(seed_ward), n_seeds


def person_group_array(people, ward_of):
    return np.array([ward_of.get(p, "UNMAPPED") for p in people])


def weekly_mean_prevalence_all_people(history, day_list, group_arr, groups):
    """Training-data weekly aggregation (see module docstring): mean over
    each week's days of the fraction of ALL people in the group who are
    colonized that day. Returns an [N_WEEKS, len(groups)] array."""
    weeks = assign_week(pd.Series(day_list)).to_numpy()
    out = np.full((config.N_WEEKS, len(groups)), np.nan)
    for gi, g in enumerate(groups):
        mask = group_arr == g
        if not mask.any():
            continue
        daily_prev = history[:, mask].mean(axis=1)
        df = pd.DataFrame({"week": weeks, "prevalence": daily_prev})
        weekly = df.groupby("week")["prevalence"].mean()
        out[weekly.index.to_numpy(), gi] = weekly.to_numpy()
    return out


def generate_trajectories(n_trajectories, people, index, day_list, edge_arrays_by_day, admission,
                           calibrated_params, states_real, groups=None, base_seed=None):
    """Generate n_trajectories SIS trajectories, split 50/50 endemic/
    outbreak. Returns (states, metadata): states has shape
    [n_trajectories, config.N_WEEKS, len(groups)]; metadata is a DataFrame
    with one row per trajectory."""
    groups = config.WARD_GROUPS if groups is None else groups
    base_seed = config.SEED if base_seed is None else base_seed
    ward_of = person_ward_map(admission)
    group_arr = person_group_array(people, ward_of)
    baseline = group_baseline_prevalence(states_real, groups)

    beta0 = calibrated_params["beta"]
    gamma0 = calibrated_params["gamma"]
    epsilon0 = calibrated_params["epsilon"]
    lo, hi = config.TRAJECTORY_PARAM_MULTIPLIER_RANGE

    n_endemic = n_trajectories // 2
    n_outbreak = n_trajectories - n_endemic
    scenarios = ["endemic"] * n_endemic + ["outbreak"] * n_outbreak

    master_rng = np.random.default_rng(base_seed)
    seed_table = master_rng.integers(0, 2**31 - 1, size=(n_trajectories, 3))

    states = np.full((n_trajectories, config.N_WEEKS, len(groups)), np.nan)
    meta_rows = []

    for i, scenario in enumerate(scenarios):
        ic_seed, param_seed, dyn_seed = (int(s) for s in seed_table[i])
        param_rng = np.random.default_rng(param_seed)
        ic_rng = np.random.default_rng(ic_seed)

        beta = beta0 * param_rng.uniform(lo, hi)
        gamma = gamma0 * param_rng.uniform(lo, hi)
        epsilon = epsilon0

        if scenario == "endemic":
            initial, group_prob = endemic_initial_state(people, index, ward_of, baseline, ic_rng)
            seed_ward, n_seeds = None, None
        else:
            initial, seed_ward, n_seeds = outbreak_initial_state(people, index, ward_of, ic_rng)

        history = simulate_sis(initial, day_list, edge_arrays_by_day, beta, gamma, epsilon, seed=dyn_seed)
        states[i] = weekly_mean_prevalence_all_people(history, day_list, group_arr, groups)

        meta_rows.append(
            {
                "trajectory": i, "scenario": scenario, "seed_ward": seed_ward, "n_seeds": n_seeds,
                "beta": beta, "gamma": gamma, "epsilon": epsilon,
                "ic_seed": ic_seed, "param_seed": param_seed, "dyn_seed": dyn_seed,
            }
        )

    metadata = pd.DataFrame(meta_rows)
    return states, metadata
