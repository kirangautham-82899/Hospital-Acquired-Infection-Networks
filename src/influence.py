"""Koopman INFLUENCE score per ward (added after the Nov 14 review).

Why this exists: the original P7/P9 "Koopman score" was each ward's share
of the slowest mode's RIGHT eigenvector. That vector is the shape of the
fitted operator's most persistent pattern (with the first calibration, D1's
was the lambda = 1 equilibrium). It answers "where does MRSA settle?", not "which ward drives
spread?", so it was never a fair superspreader score.

The influence score asks the second question directly, using only the
fitted operator K (no simulator, no contact data):

  1. Start from a baseline ward state x_base (real mean prevalence over
     the calibration weeks) and roll K forward `horizon` weeks.
  2. Add the same NUMBER of extra colonized people (n_seed) to ward j
     (prevalence + n_seed / N_j) and roll forward again.
  3. influence_total_j = sum over weeks and wards of the difference,
     converted to people (x N_i): extra colonized person-weeks that K
     predicts from seeding ward j. influence_spillover_j is the same sum
     over the OTHER wards only.

Seeding a fixed number of people (not a fixed prevalence step) keeps big
and small wards comparable. The rollout is the same lifted-space
iteration P8 uses for forecasting (z <- K z, read x off the readout).
"""
import numpy as np
import pandas as pd

import config
from src.observables import d3_contact_weighted, DICTIONARIES


def lift(model, dict_name, x, groups, W=None):
    """Dictionary features of one ward state x, scaled with the model's
    own (training-split) scaler. D3 needs the ward matrix W."""
    if dict_name == "D3":
        phi, _ = d3_contact_weighted(np.asarray(x, dtype=float), groups, W)
    else:
        phi, _ = DICTIONARIES[dict_name](np.asarray(x, dtype=float), groups)
    return model["scaler"].transform(np.asarray(phi)[None, :])[0]


def koopman_rollout(model, dict_name, x0, groups, horizon, W=None):
    """Predicted ward prevalence for weeks 1..horizon from start x0:
    array [horizon, n_groups] in original prevalence units."""
    feature_names = model["feature_names"]
    idx = [feature_names.index(f"x_{g}") for g in groups]
    z = lift(model, dict_name, x0, groups, W)
    out = np.empty((horizon, len(groups)))
    for h in range(horizon):
        z = z @ model["K"].T
        out[h] = model["scaler"].inverse_transform_indices(z[idx], idx)
    return out


def koopman_influence_scores(model, dict_name, x_base, ward_sizes, groups, n_seed=None, horizon=None, W=None):
    """Per-ward influence of seeding n_seed extra colonized people, as
    predicted by the fitted operator. Returns a DataFrame [ward,
    seed_prevalence_step, influence_total, influence_spillover]
    (person-weeks over `horizon` weeks)."""
    n_seed = config.KOOPMAN_INFLUENCE_N_SEED if n_seed is None else n_seed
    horizon = config.KOOPMAN_INFLUENCE_HORIZON if horizon is None else horizon
    x_base = np.asarray(x_base, dtype=float)
    sizes = np.asarray(ward_sizes, dtype=float)

    base = koopman_rollout(model, dict_name, x_base, groups, horizon, W)
    rows = []
    for j, ward in enumerate(groups):
        x = x_base.copy()
        step = min(n_seed / sizes[j], 1.0 - x[j])
        x[j] += step
        pert = koopman_rollout(model, dict_name, x, groups, horizon, W)
        excess_people = (pert - base) * sizes[None, :]
        others = [i for i in range(len(groups)) if i != j]
        rows.append({
            "ward": ward, "seed_prevalence_step": step,
            "influence_total": float(excess_people.sum()),
            "influence_spillover": float(excess_people[:, others].sum()),
        })
    return pd.DataFrame(rows)


def ward_sizes_in_network(admission, network_people, groups):
    """Number of contact-network people in each ward group."""
    from src.wards import person_ward_map

    ward_of = person_ward_map(admission)
    counts = pd.Series([ward_of.get(p) for p in network_people]).value_counts()
    return counts.reindex(groups).fillna(0).astype(int).to_numpy()
