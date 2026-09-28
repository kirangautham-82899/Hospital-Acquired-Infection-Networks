"""P9/P10: ward contact-reduction interventions, simulated (decision
content -- see research_log.md for the Part A numbering caveat).

P9's superspreader_experiment: for each ward, cut ALL of that ward's
contacts (any edge touching a person who belongs to that ward, both
within-ward and between-ward -- see scale_ward_edges below for why
"all", not just within-ward) by 50% for the entire 117-day simulated
period, and record the drop in colonized person-days relative to a
no-intervention baseline.

P10's multi-ward experiments (scale_multiple_ward_edges, used by
src/build_p10.py) generalize this to cutting a SET of k wards
simultaneously by a chosen reduction fraction, for comparing intervention
STRATEGIES (random / whole-hospital / degree-targeted / Koopman-targeted)
under an equal-budget framework.

Both use the SAME calibrated (beta, gamma, epsilon) and calibration
initial condition as P4/P6 (never re-calibrated here), with COMMON RANDOM
NUMBERS (the same replicate seed pairs for baseline and every
intervention) for a paired, variance-reduced comparison -- same technique
as P4's grid search and P6's lambda selection.

"Cut a ward's contacts" is interpreted as scaling EVERY edge touching
that ward (either endpoint), not just within-ward edges: a real
intervention like cohorting staff or restricting movement reduces a
ward's overall contact activity, including its contact with other wards,
not just contact among people already confined to it.
"""
import numpy as np
import pandas as pd

from src.calibrate_sim import calibration_initial_state, replicate_seed_pairs
from src.simulate import daily_edge_arrays, simulate_sis
from src.wards import person_ward_map


def scale_ward_edges(edges, admission, ward, scale=0.5):
    """Return a copy of `edges` (columns day, u, v, seconds) with the
    seconds of any row touching a person in `ward` (u's ward == ward OR
    v's ward == ward) multiplied by `scale`. A within-ward edge (both
    endpoints in `ward`) is still scaled exactly once, not twice. A
    single-ward special case of scale_multiple_ward_edges."""
    return scale_multiple_ward_edges(edges, admission, [ward], scale)


def scale_multiple_ward_edges(edges, admission, wards, scale):
    """Generalizes scale_ward_edges to a SET of wards: any row touching a
    person in ANY of `wards` is scaled by `scale`, exactly once even if
    it touches two targeted wards (or two people in the same targeted
    ward). Passing all 6 wards implements a uniform whole-hospital
    reduction (every edge touches some targeted ward, so every edge is
    scaled)."""
    ward_of = person_ward_map(admission)
    wards = set(wards)
    out = edges.copy()
    touches = out["u"].map(ward_of).isin(wards) | out["v"].map(ward_of).isin(wards)
    out.loc[touches, "seconds"] = out.loc[touches, "seconds"] * scale
    return out


def colonized_person_days(history):
    """Sum over all simulated days and all people of the colonized
    indicator -- the total burden measure the intervention is scored
    against."""
    return float(history.sum())


def ward_choice_rngs(n_replicates, base_seed):
    """n_replicates independent RNGs for ward-selection randomness
    (P10's 'random' strategy), deterministically derived from base_seed
    but from a SEPARATE SeedSequence root than any ic_seed/dyn_seed
    stream (see replicate_seed_pairs), so ward choice never disturbs the
    common-random-numbers pairing those carry across every strategy."""
    seeds = np.random.SeedSequence(base_seed).spawn(n_replicates)
    return [np.random.default_rng(s) for s in seeds]


def run_person_days_random_wards(people, index, day_list, edges, admission, groups, k, scale,
                                  beta, gamma, epsilon, pre_window_last_status, seed_pairs,
                                  ward_seed_base):
    """Like run_person_days_replicates, but for the 'random' intervention
    strategy: each replicate independently draws a random k-ward subset
    (from ward_choice_rngs, kept separate from ic_seed/dyn_seed), scales
    those wards' edges by `scale`, and simulates. Averages over BOTH
    ward-choice randomness and simulation stochasticity -- the expected
    outcome of 'pick k wards uniformly at random', not one fixed pick.
    Only builds edge arrays once per DISTINCT ward subset actually drawn
    (at most C(len(groups), k) of them, not once per replicate) --
    C(6,1)=6 or C(6,2)=15 in this project, far fewer than 200 replicates.
    Returns (totals array, list of the k-ward list chosen per
    replicate)."""
    ward_rngs = ward_choice_rngs(len(seed_pairs), ward_seed_base)

    totals = np.empty(len(seed_pairs))
    chosen_per_replicate = []
    edge_arrays_cache = {}
    for i, ((ic_seed, dyn_seed), ward_rng) in enumerate(zip(seed_pairs, ward_rngs)):
        chosen = tuple(sorted(ward_rng.choice(groups, size=k, replace=False).tolist()))
        chosen_per_replicate.append(list(chosen))
        if chosen not in edge_arrays_cache:
            scaled_edges = scale_multiple_ward_edges(edges, admission, list(chosen), scale=scale)
            edge_arrays_cache[chosen] = daily_edge_arrays(scaled_edges, index)
        initial = calibration_initial_state(people, index, pre_window_last_status, admission, seed=ic_seed)
        history = simulate_sis(initial, day_list, edge_arrays_cache[chosen], beta, gamma, epsilon, seed=dyn_seed)
        totals[i] = colonized_person_days(history)
    return totals, chosen_per_replicate


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
