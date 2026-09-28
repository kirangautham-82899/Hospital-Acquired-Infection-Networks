"""P9: the superspreader ward ground-truth experiment (decision content
-- see research_log.md for the Part A numbering caveat). Ground truth is
MEASURED IN SIMULATION: for each ward, cut ALL of that ward's contacts
(any edge touching a person who belongs to that ward, both within-ward
and between-ward -- see scale_ward_edges below for why "all", not just
within-ward) by 50% for the entire 117-day simulated period, and record
the drop in colonized person-days relative to a no-intervention baseline.
Uses the SAME calibrated (beta, gamma, epsilon) and calibration initial
condition as P4/P6 (never re-calibrated here), with COMMON RANDOM NUMBERS
(the same replicate seed pairs for baseline and every intervention) for a
paired, variance-reduced comparison -- same technique as P4's grid search
and P6's lambda selection.

"Cut a ward's contacts" is interpreted as scaling EVERY edge touching
that ward (either endpoint), not just within-ward edges: a real
intervention like cohorting staff or restricting movement reduces a
ward's overall contact activity, including its contact with other wards,
not just contact among people already confined to it.
"""
import numpy as np
import pandas as pd

import config
from src.calibrate_sim import calibration_initial_state, replicate_seed_pairs
from src.simulate import daily_edge_arrays, simulate_sis
from src.wards import person_ward_map


def scale_ward_edges(edges, admission, ward, scale=0.5):
    """Return a copy of `edges` (columns day, u, v, seconds) with the
    seconds of any row touching a person in `ward` (u's ward == ward OR
    v's ward == ward) multiplied by `scale`. A within-ward edge (both
    endpoints in `ward`) is still scaled exactly once, not twice."""
    ward_of = person_ward_map(admission)
    out = edges.copy()
    touches = out["u"].map(ward_of).eq(ward) | out["v"].map(ward_of).eq(ward)
    out.loc[touches, "seconds"] = out.loc[touches, "seconds"] * scale
    return out


def colonized_person_days(history):
    """Sum over all simulated days and all people of the colonized
    indicator -- the total burden measure the intervention is scored
    against."""
    return float(history.sum())


def run_person_days_replicates(people, index, day_list, edge_arrays_by_day, beta, gamma, epsilon,
                                pre_window_last_status, admission, seed_pairs):
    """Run one replicate per (ic_seed, dyn_seed) pair in seed_pairs,
    returning the array of per-replicate colonized person-days."""
    totals = np.empty(len(seed_pairs))
    for i, (ic_seed, dyn_seed) in enumerate(seed_pairs):
        initial = calibration_initial_state(people, index, pre_window_last_status, admission, seed=ic_seed)
        history = simulate_sis(initial, day_list, edge_arrays_by_day, beta, gamma, epsilon, seed=dyn_seed)
        totals[i] = colonized_person_days(history)
    return totals


def superspreader_experiment(people, index, day_list, edges, admission, beta, gamma, epsilon,
                              pre_window_last_status, groups, n_replicates=100, cut_fraction=0.5, base_seed=None):
    """For each ward in `groups`: run n_replicates baseline and
    intervention (that ward's contacts cut by cut_fraction) simulations
    with COMMON RANDOM NUMBERS. Returns (summary DataFrame, per-replicate
    dict {'baseline': array, ward: array, ...}) so callers can also check
    the paired per-replicate drop distribution, not just its mean."""
    seed_pairs = replicate_seed_pairs(n_replicates, base_seed=base_seed)

    baseline_edge_arrays = daily_edge_arrays(edges, index)
    baseline_totals = run_person_days_replicates(
        people, index, day_list, baseline_edge_arrays, beta, gamma, epsilon,
        pre_window_last_status, admission, seed_pairs,
    )

    rows = []
    per_replicate = {"baseline": baseline_totals}
    for ward in groups:
        scaled_edges = scale_ward_edges(edges, admission, ward, scale=1.0 - cut_fraction)
        scaled_edge_arrays = daily_edge_arrays(scaled_edges, index)
        intervention_totals = run_person_days_replicates(
            people, index, day_list, scaled_edge_arrays, beta, gamma, epsilon,
            pre_window_last_status, admission, seed_pairs,
        )
        per_replicate[ward] = intervention_totals

        drop = baseline_totals - intervention_totals  # paired, per replicate
        drop_fraction = np.divide(
            drop, baseline_totals, out=np.full_like(drop, np.nan), where=baseline_totals != 0
        )
        rows.append(
            {
                "ward": ward,
                "baseline_mean_person_days": baseline_totals.mean(),
                "intervention_mean_person_days": intervention_totals.mean(),
                "drop_person_days_mean": drop.mean(),
                "drop_person_days_std": drop.std(ddof=1),
                "drop_fraction_mean": float(np.nanmean(drop_fraction)),
            }
        )

    return pd.DataFrame(rows), per_replicate
