"""Tests for src/simulate.py (P4 core): the mechanistic invariants that
must hold regardless of calibration, plus a known-analytic-probability
check on a tiny hand-built network."""
import numpy as np
import pandas as pd
import pytest

from src.simulate import build_person_index, daily_edge_arrays, simulate_sis, simulation_day_list


def _toy_population(n=20):
    people = [f"P{i:03d}" for i in range(n)]
    return build_person_index(people)


def _chain_edges(people, index, days, hours=1.0):
    """A ring/chain network: person i contacts person i+1 (mod n) every day."""
    rows = []
    n = len(people)
    for day in days:
        for i in range(n):
            u, v = people[i], people[(i + 1) % n]
            rows.append({"day": day, "u": u, "v": v, "seconds": hours * 3600.0})
    edges = pd.DataFrame(rows)
    return daily_edge_arrays(edges, index)


def test_beta_zero_epsilon_zero_colonized_never_rises_and_decays_to_zero():
    people, index = _toy_population(50)
    days = simulation_day_list()
    edge_arrays = _chain_edges(people, index, days)

    rng = np.random.default_rng(0)
    initial = rng.random(len(people)) < 0.4  # some colonized, some not

    history = simulate_sis(initial, days, edge_arrays, beta=0.0, gamma=0.3, epsilon=0.0, seed=123)
    counts = history.sum(axis=1)

    assert (np.diff(counts) <= 0).all(), "with beta=epsilon=0, colonized count must never rise"
    assert counts[-1] == 0, "with gamma=0.3 over 117 days, colonized count should decay to 0"


def test_gamma_zero_epsilon_zero_colonized_never_falls():
    people, index = _toy_population(50)
    days = simulation_day_list()
    edge_arrays = _chain_edges(people, index, days, hours=5.0)

    rng = np.random.default_rng(1)
    initial = rng.random(len(people)) < 0.1

    history = simulate_sis(initial, days, edge_arrays, beta=0.05, gamma=0.0, epsilon=0.0, seed=456)
    counts = history.sum(axis=1)

    assert (np.diff(counts) >= 0).all(), "with gamma=epsilon=0, colonized count must never fall"


def test_s_plus_i_equals_n_every_day():
    people, index = _toy_population(30)
    days = simulation_day_list()
    edge_arrays = _chain_edges(people, index, days)

    initial = np.zeros(len(people), dtype=bool)
    initial[:5] = True
    history = simulate_sis(initial, days, edge_arrays, beta=0.02, gamma=0.05, epsilon=0.001, seed=7)

    # each entry is bool -> S+I=N is true by construction (every person is
    # exactly one of S/I), but check explicitly that history has no other
    # values and the right shape every day.
    assert history.dtype == bool
    assert history.shape == (len(days), len(people))
    assert ((history.sum(axis=1) + (~history).sum(axis=1)) == len(people)).all()


def test_same_seed_gives_identical_output():
    people, index = _toy_population(40)
    days = simulation_day_list()
    edge_arrays = _chain_edges(people, index, days)
    rng = np.random.default_rng(2)
    initial = rng.random(len(people)) < 0.3

    h1 = simulate_sis(initial, days, edge_arrays, beta=0.01, gamma=0.02, epsilon=0.0005, seed=999)
    h2 = simulate_sis(initial, days, edge_arrays, beta=0.01, gamma=0.02, epsilon=0.0005, seed=999)
    assert np.array_equal(h1, h2)

    h3 = simulate_sis(initial, days, edge_arrays, beta=0.01, gamma=0.02, epsilon=0.0005, seed=1000)
    assert not np.array_equal(h1, h3), "different seed should (almost certainly) differ"


def test_zero_contact_day_has_no_transmission_but_decolonization_applies():
    people, index = _toy_population(10)
    days = simulation_day_list()[:5]
    edge_arrays = {}  # no contacts on any of these days

    initial = np.zeros(len(people), dtype=bool)
    initial[0] = True  # one colonized person, isolated (no contacts at all)

    # very high beta should not matter since there are no edges
    history = simulate_sis(initial, days, edge_arrays, beta=100.0, gamma=1.0, epsilon=0.0, seed=5)
    # nobody else can ever become colonized (no contacts, no importation)
    assert not history[:, 1:].any()
    # the seeded person decolonizes on day 2 (gamma=1.0 -> certain recovery each day)
    assert history[0, 0] == True
    assert history[1, 0] == False


def test_known_analytic_transmission_probability_two_person_network():
    """A->B contact of H=2 hours/day, A infected, B susceptible, epsilon=0,
    single day. Empirical P(B infected) over many replicates should match
    the analytic 1 - exp(-beta*H) within a tight Monte Carlo tolerance."""
    people, index = build_person_index(["A", "B"])
    hours = 2.0

    beta = 0.05
    analytic_p = 1 - np.exp(-beta * hours)
    initial = np.array([True, False])  # A infected, B susceptible

    # history[0] is always the initial state (pre-transition), so the
    # transmission outcome shows up as history[1] -- simulate 2 days and
    # read B's status on the second one.
    n_trials = 20000
    outcomes2 = np.zeros(n_trials, dtype=bool)
    two_days = simulation_day_list()[:2]
    edges2 = pd.DataFrame(
        [{"day": two_days[0], "u": "A", "v": "B", "seconds": hours * 3600.0}]
    )
    edge_arrays2 = daily_edge_arrays(edges2, index)
    for i in range(n_trials):
        history = simulate_sis(initial, two_days, edge_arrays2, beta=beta, gamma=0.0, epsilon=0.0, seed=i)
        outcomes2[i] = history[1, 1]

    empirical_p = outcomes2.mean()
    se = np.sqrt(analytic_p * (1 - analytic_p) / n_trials)
    assert abs(empirical_p - analytic_p) < 5 * se, (
        f"empirical {empirical_p:.4f} vs analytic {analytic_p:.4f}, tolerance {5*se:.4f}"
    )
