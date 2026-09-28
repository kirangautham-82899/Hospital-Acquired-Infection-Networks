"""Tests for src/intervention.py (P9): edge-scaling correctness,
reproducibility, and a DESIGNED synthetic network (a bridge ward between
two otherwise-disconnected wards) where the correct ranking is known in
advance -- not just "the experiment runs without crashing"."""
import numpy as np
import pandas as pd
import pytest

from src.intervention import (
    colonized_person_days,
    scale_multiple_ward_edges,
    scale_ward_edges,
    superspreader_experiment,
)
from src.simulate import build_person_index, simulation_day_list


def test_scale_ward_edges_scales_only_touching_rows():
    admission = pd.DataFrame(
        {"calc_ident": ["P1", "P2", "P3"], "service_pa_pe": ["Menard 1", "Menard 1", "Sorrel 0"]}
    )
    edges = pd.DataFrame(
        {
            "day": pd.to_datetime(["2009-07-01", "2009-07-01", "2009-07-01"]),
            "u": ["P1", "P1", "P3"], "v": ["P2", "P3", "P3"], "seconds": [100.0, 200.0, 50.0],
        }
    )
    out = scale_ward_edges(edges, admission, "Menard 1", scale=0.5)
    assert out.iloc[0]["seconds"] == 50.0  # P1-P2, both Menard 1 -> scaled once, not twice
    assert out.iloc[1]["seconds"] == 100.0  # P1-P3, P1 touches Menard 1 -> scaled
    assert out.iloc[2]["seconds"] == 50.0  # P3-P3 row, neither in Menard 1 -> untouched


def test_colonized_person_days_is_a_plain_sum():
    history = np.array([[True, False, True], [False, False, True]])
    assert colonized_person_days(history) == 3.0


def test_scale_multiple_ward_edges_scales_once_even_if_both_wards_targeted():
    admission = pd.DataFrame(
        {
            "calc_ident": ["P1", "P2", "P3", "P4"],
            "service_pa_pe": ["Menard 1", "Menard 1", "Sorrel 0", "Other"],
        }
    )
    edges = pd.DataFrame(
        {
            "day": pd.to_datetime(["2009-07-01"] * 4),
            "u": ["P1", "P1", "P2", "P4"], "v": ["P2", "P3", "P3", "P4"],
            "seconds": [100.0, 100.0, 100.0, 100.0],
        }
    )
    out = scale_multiple_ward_edges(edges, admission, ["Menard 1", "Sorrel 0"], scale=0.5)
    assert out.iloc[0]["seconds"] == 50.0  # P1-P2: both targeted -> scaled once, not twice
    assert out.iloc[1]["seconds"] == 50.0  # P1-P3: P1 targeted -> scaled
    assert out.iloc[2]["seconds"] == 50.0  # P2-P3: both targeted -> scaled
    assert out.iloc[3]["seconds"] == 100.0  # P4-P4: neither ward targeted -> untouched


def test_scale_multiple_ward_edges_with_all_wards_matches_uniform_scale():
    admission = pd.DataFrame({"calc_ident": ["P1", "P2"], "service_pa_pe": ["Menard 1", "Sorrel 0"]})
    edges = pd.DataFrame(
        {"day": pd.to_datetime(["2009-07-01"]), "u": ["P1"], "v": ["P2"], "seconds": [200.0]}
    )
    out = scale_multiple_ward_edges(edges, admission, ["Menard 1", "Sorrel 0"], scale=0.25)
    assert out.iloc[0]["seconds"] == 50.0  # every edge touches a targeted ward -> uniformly scaled


def test_scale_ward_edges_is_the_single_ward_special_case():
    admission = pd.DataFrame({"calc_ident": ["P1", "P2"], "service_pa_pe": ["Menard 1", "Sorrel 0"]})
    edges = pd.DataFrame(
        {"day": pd.to_datetime(["2009-07-01"]), "u": ["P1"], "v": ["P2"], "seconds": [200.0]}
    )
    single = scale_ward_edges(edges, admission, "Menard 1", scale=0.4)
    multi = scale_multiple_ward_edges(edges, admission, ["Menard 1"], scale=0.4)
    pd.testing.assert_frame_equal(single, multi)


def _bridge_topology():
    """4 wards: D is the seed source, connected ONLY to B (the hub); B
    also connects to leaf wards A and C, which never contact D or each
    other directly. Seeding colonization in D (outside the compared
    groups) isolates the pure topological effect: cutting B blocks BOTH
    of D's paths to A and C, while cutting A (or C) only blocks one leaf,
    leaving the other fully reachable via D->B->C (or D->B->A). This
    avoids the confound of cutting the SEED's own ward, which throttles
    the epidemic at its most sensitive early stage regardless of
    topology (discovered empirically: an earlier version of this test
    seeded inside one of the compared wards and found THAT effect
    dominates bridge position -- a real, interesting finding in its own
    right, but not what this test is trying to isolate)."""
    people_d = [f"D{i}" for i in range(6)]
    people_a = [f"A{i}" for i in range(6)]
    people_b = [f"B{i}" for i in range(6)]
    people_c = [f"C{i}" for i in range(6)]
    admission = pd.DataFrame(
        {
            "calc_ident": people_d + people_a + people_b + people_c,
            "service_pa_pe": ["Other"] * 6 + ["Menard 1"] * 6 + ["Menard 2"] * 6 + ["Sorrel 0"] * 6,
        }
    )
    day_list = simulation_day_list()
    rows = []
    for day in day_list:
        for grp in (people_d, people_a, people_b, people_c):
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    rows.append({"day": day, "u": grp[i], "v": grp[j], "seconds": 3600.0})
        for i in range(6):
            rows.append({"day": day, "u": people_d[i], "v": people_b[i], "seconds": 1800.0})  # D-B
            rows.append({"day": day, "u": people_b[i], "v": people_a[i], "seconds": 1800.0})  # B-A
            rows.append({"day": day, "u": people_b[i], "v": people_c[i], "seconds": 1800.0})  # B-C
    edges = pd.DataFrame(rows)
    return admission, edges, day_list, people_d + people_a + people_b + people_c


def test_bridge_ward_has_largest_drop_when_cut():
    admission, edges, day_list, people_list = _bridge_topology()
    people, index = build_person_index(people_list)

    # deterministic seed: exactly one colonized person in ward D (the
    # source, NOT one of the compared groups), everyone else explicitly
    # susceptible, epsilon=0 -- so the ONLY way infection reaches A or C
    # is via B, isolating the pure bridge-topology effect.
    seed_person = people_list[0]
    pre_window_last_status = pd.DataFrame(
        {"calc_ident": people_list, "last_status": [1 if p == seed_person else 0 for p in people_list]}
    )
    groups = ["Menard 1", "Menard 2", "Sorrel 0"]  # A, B, C (D/"Other" is the seed source, not compared)

    summary, per_replicate = superspreader_experiment(
        people, index, day_list, edges, admission,
        beta=0.02, gamma=0.02, epsilon=0.0,
        pre_window_last_status=pre_window_last_status,
        groups=groups, n_replicates=40, cut_fraction=0.5, base_seed=7,
    )
    drop_by_ward = summary.set_index("ward")["drop_person_days_mean"]
    assert drop_by_ward["Menard 2"] > drop_by_ward["Menard 1"]  # B (bridge) > A (leaf)
    assert drop_by_ward["Menard 2"] > drop_by_ward["Sorrel 0"]  # B (bridge) > C (leaf)


def test_superspreader_experiment_reproducible_with_same_seed():
    admission, edges, day_list, people_list = _bridge_topology()
    people, index = build_person_index(people_list)
    pre_window_last_status = pd.DataFrame({"calc_ident": [], "last_status": []})
    groups = ["Menard 1"]

    s1, _ = superspreader_experiment(
        people, index, day_list, edges, admission, 0.02, 0.02, 0.0005,
        pre_window_last_status, groups, n_replicates=10, base_seed=3,
    )
    s2, _ = superspreader_experiment(
        people, index, day_list, edges, admission, 0.02, 0.02, 0.0005,
        pre_window_last_status, groups, n_replicates=10, base_seed=3,
    )
    pd.testing.assert_frame_equal(s1, s2)


def test_run_person_days_random_wards_varies_choice_and_reproducible():
    from src.calibrate_sim import replicate_seed_pairs
    from src.intervention import run_person_days_random_wards

    admission, edges, day_list, people_list = _bridge_topology()
    people, index = build_person_index(people_list)
    pre_window_last_status = pd.DataFrame({"calc_ident": [], "last_status": []})
    groups = ["Menard 1", "Menard 2", "Sorrel 0"]

    seed_pairs = replicate_seed_pairs(20, base_seed=1)
    totals1, chosen1 = run_person_days_random_wards(
        people, index, day_list, edges, admission, groups, k=1, scale=0.5,
        beta=0.02, gamma=0.02, epsilon=0.0005, pre_window_last_status=pre_window_last_status,
        seed_pairs=seed_pairs, ward_seed_base=42,
    )
    assert len(set(tuple(c) for c in chosen1)) > 1  # not always the same ward across replicates
    assert all(len(c) == 1 and c[0] in groups for c in chosen1)

    totals2, chosen2 = run_person_days_random_wards(
        people, index, day_list, edges, admission, groups, k=1, scale=0.5,
        beta=0.02, gamma=0.02, epsilon=0.0005, pre_window_last_status=pre_window_last_status,
        seed_pairs=seed_pairs, ward_seed_base=42,
    )
    assert chosen1 == chosen2  # reproducible ward choice with same ward_seed_base
    assert np.array_equal(totals1, totals2)

    # a different ward_seed_base should (almost certainly) change the ward choices,
    # while leaving the simulation's own randomness (seed_pairs) untouched
    _, chosen3 = run_person_days_random_wards(
        people, index, day_list, edges, admission, groups, k=1, scale=0.5,
        beta=0.02, gamma=0.02, epsilon=0.0005, pre_window_last_status=pre_window_last_status,
        seed_pairs=seed_pairs, ward_seed_base=99,
    )
    assert chosen1 != chosen3
