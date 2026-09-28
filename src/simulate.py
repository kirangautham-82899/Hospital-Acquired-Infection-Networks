"""P4 core: the daily individual-level SIS simulator.

Runs on the deduped person-level contact edges from P2
(data/processed/edges_master.csv), one day at a time, over the full
117-day contact window (2009-07-01 to 2009-10-25). Weekly aggregation
(for comparing against P3's real series, or for the training-trajectory
dataset) is a separate step layered on top -- see src/calibrate_sim.py and
src/trajectories.py.

Mechanism (decision content matching "SIS" in the locked plan, whatever
its number is in Part A vs this repo's CLAUDE.md):
  - Each person is S (susceptible) or I (colonized), tracked as a bool
    array over the whole population.
  - Per day, per susceptible person i: contact-driven transmission hazard
    is beta * (total contact-hours that day with currently-infected
    neighbors). Because per-neighbor transmission events are treated as
    independent Bernoulli(1 - exp(-beta*hours_j)) trials, the probability
    of NOT being infected by any infected neighbor collapses to a single
    exponential in the SUM of hours with infected neighbors:
        P(transmission that day) = 1 - exp(-beta * H_i(t))
    where H_i(t) = sum of contact-hours that day with neighbors who are
    currently infected.
  - Independently, a small daily importation probability epsilon can also
    colonize a susceptible person (models reintroduction from outside the
    tracked network -- new admissions, staff households, environment).
    The two mechanisms are combined as independent events:
        P(S -> I that day) = 1 - (1 - P(transmission)) * (1 - epsilon)
  - Each infected person independently decolonizes with daily probability
    gamma: P(I -> S that day) = gamma.
  - All transitions for a day are computed from that day's state
    (synchronous update), then applied simultaneously.

A day with zero rows in the edge list (7 such days, see P1) simply has
H_i(t) = 0 for everyone -- no transmission that day, but decolonization
and importation still apply as normal.
"""
import numpy as np
import pandas as pd

import config


def build_person_index(people):
    """Return (sorted_people_list, {calc_ident: index}) for a population.
    Sorting makes the index assignment deterministic/reproducible."""
    sorted_people = sorted(people)
    index = {p: i for i, p in enumerate(sorted_people)}
    return sorted_people, index


def daily_edge_arrays(edges, index):
    """edges: DataFrame[day, u, v, seconds], already population-filtered
    by the caller (see src/network.py's filter_edges). Returns
    {day: (u_idx, v_idx, hours)} numpy arrays for fast per-day vectorized
    lookups. A day with no rows in `edges` is simply absent from the
    returned dict (treated as zero contacts by simulate_sis)."""
    out = {}
    for day, sub in edges.groupby("day"):
        u_idx = sub["u"].map(index).to_numpy()
        v_idx = sub["v"].map(index).to_numpy()
        hours = sub["seconds"].to_numpy() / 3600.0
        out[day] = (u_idx, v_idx, hours)
    return out


def simulation_day_list(start=None, end=None):
    """The full list of calendar days the simulator steps over (all 117
    days, regardless of the calibration/holdout week split)."""
    return list(pd.date_range(start or config.STUDY_START, end or config.STUDY_END, freq="D"))


def simulate_sis(initial_state, day_list, edge_arrays_by_day, beta, gamma, epsilon, seed):
    """Run the daily SIS simulation.

    initial_state: bool array [n_people], status at the start of day_list[0].
    day_list: the calendar days to simulate (see simulation_day_list()).
    edge_arrays_by_day: {day: (u_idx, v_idx, hours)} from daily_edge_arrays().
    seed: int or np.random.SeedSequence -- same seed gives identical output.

    Returns history: bool array [n_days, n_people]. history[t] is the
    state at the START of day_list[t] (i.e. what a test on that calendar
    day would find) -- the state that day's transmission dynamics act on
    to produce history[t+1].
    """
    rng = np.random.default_rng(seed)
    n_people = len(initial_state)
    n_days = len(day_list)
    history = np.zeros((n_days, n_people), dtype=bool)
    state = np.asarray(initial_state, dtype=bool).copy()

    for t, day in enumerate(day_list):
        history[t] = state

        hours_to_infected = np.zeros(n_people)
        edges_today = edge_arrays_by_day.get(day)
        if edges_today is not None:
            u_idx, v_idx, hours = edges_today
            v_infected = state[v_idx]
            np.add.at(hours_to_infected, u_idx[v_infected], hours[v_infected])
            u_infected = state[u_idx]
            np.add.at(hours_to_infected, v_idx[u_infected], hours[u_infected])

        p_transmit = 1.0 - np.exp(-beta * hours_to_infected)
        p_new_colonized = 1.0 - (1.0 - p_transmit) * (1.0 - epsilon)

        susceptible = ~state
        colonize_draws = rng.random(n_people)
        newly_colonized = susceptible & (colonize_draws < p_new_colonized)

        recover_draws = rng.random(n_people)
        newly_recovered = state & (recover_draws < gamma)

        state = state.copy()
        state[newly_colonized] = True
        state[newly_recovered] = False

    return history
