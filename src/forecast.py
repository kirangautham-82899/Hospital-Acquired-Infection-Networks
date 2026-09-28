"""P8: forecast REAL data with the EDMD operators fitted in P6 (D1/D2/D3)
-- the first time K touches real data anywhere in this project, per
research_log.md ("Don't apply K to real data yet. Real-data forecasting
is P8."). Also houses the two simplest baselines (persistence, historical
mean) evaluated the same way.

Real starting states are built via P5's real_state_fill (real value
preferred, carry-forward fallback up to 2 weeks, never defaulting to
susceptible). Forecasts are ONLY SCORED against genuinely-observed real
values (P5's observed_for_scoring_mask, n_tested >= 10); a scoring_mask
travels with every forecast record so aggregation can drop the rest.

Every forecast is tagged by which PERIOD its landing week falls in:
'calibration' (config.CALIBRATION_WEEKS) or 'holdout'
(config.HOLDOUT_WEEKS). K was fit purely on simulated data, so it is
out-of-sample for real data in BOTH periods; the two new baselines in
src/baselines.py are fit on the calibration period specifically, so
'holdout' is the one period that is a fair, never-touched test for every
model alike.
"""
import numpy as np

import config
from src.edmd import ConstantAwareScaler
from src.observables import DICTIONARIES, d3_contact_weighted
from src.real_state_fill import observed_for_scoring_mask, state_is_usable_as_starting_point


def load_edmd_model(name):
    d = np.load(config.RESULTS_MODELS_DIR / f"p6_edmd_{name}.npz", allow_pickle=True)
    scaler = ConstantAwareScaler()
    scaler.mean_ = d["scaler_mean"]
    scaler.scale_ = d["scaler_scale"]
    return {
        "K": d["K"], "scaler": scaler, "C": d["C"],
        "feature_names": list(d["feature_names"]), "groups": list(d["groups"]),
    }


def landing_period(landing_week):
    if landing_week in config.CALIBRATION_WEEKS:
        return "calibration"
    if landing_week in config.HOLDOUT_WEEKS:
        return "holdout"
    return "out_of_range"


def edmd_forecast_real(model, weekly_states, states_real, groups, max_h, dict_name, W=None):
    """Roll the fitted K forward from every usable real starting week,
    for h=1..max_h. Returns a list of records: {model, start_week,
    landing_week, period, h, pred [n_groups] raw units, actual [n_groups]
    raw units (filled), scoring_mask [n_groups] bool}."""
    K, scaler, C, feature_names = model["K"], model["scaler"], model["C"], model["feature_names"]
    group_indices = [feature_names.index(f"x_{g}") for g in groups]
    dict_fn = DICTIONARIES[dict_name]

    records = []
    for t in range(config.N_WEEKS):
        x_t, _ = weekly_states[t]
        if not state_is_usable_as_starting_point(x_t):
            continue
        if dict_name == "D3":
            phi, _ = d3_contact_weighted(x_t, groups, W)
        else:
            phi, _ = dict_fn(x_t, groups)
        current = scaler.transform(phi[None, :])[0]

        for h in range(1, max_h + 1):
            landing = t + h
            if landing >= config.N_WEEKS:
                break
            current = current @ K.T
            pred_scaled = current[group_indices]
            pred_raw = scaler.inverse_transform_indices(pred_scaled, group_indices)
            actual_raw, _ = weekly_states[landing]
            mask = observed_for_scoring_mask(landing, states_real, groups, min_n_tested=10)
            records.append(
                {
                    "model": dict_name, "start_week": t, "landing_week": landing,
                    "period": landing_period(landing), "h": h,
                    "pred": pred_raw, "actual": actual_raw, "scoring_mask": mask,
                }
            )
    return records


def persistence_forecast_real(weekly_states, states_real, groups, max_h):
    records = []
    for t in range(config.N_WEEKS):
        x_t, _ = weekly_states[t]
        if not state_is_usable_as_starting_point(x_t):
            continue
        for h in range(1, max_h + 1):
            landing = t + h
            if landing >= config.N_WEEKS:
                break
            actual_raw, _ = weekly_states[landing]
            mask = observed_for_scoring_mask(landing, states_real, groups, min_n_tested=10)
            records.append(
                {
                    "model": "persistence", "start_week": t, "landing_week": landing,
                    "period": landing_period(landing), "h": h,
                    "pred": x_t.copy(), "actual": actual_raw, "scoring_mask": mask,
                }
            )
    return records


def historical_mean_forecast_real(mean_vector, weekly_states, states_real, groups, max_h):
    records = []
    for t in range(config.N_WEEKS):
        x_t, _ = weekly_states[t]
        if not state_is_usable_as_starting_point(x_t):
            continue
        for h in range(1, max_h + 1):
            landing = t + h
            if landing >= config.N_WEEKS:
                break
            actual_raw, _ = weekly_states[landing]
            mask = observed_for_scoring_mask(landing, states_real, groups, min_n_tested=10)
            records.append(
                {
                    "model": "historical_mean", "start_week": t, "landing_week": landing,
                    "period": landing_period(landing), "h": h,
                    "pred": mean_vector.copy(), "actual": actual_raw, "scoring_mask": mask,
                }
            )
    return records


def flatten_records(records, groups):
    """Long-format rows, one per (record, ward) where the ward is
    genuinely observed at the landing week (scoring_mask True). Filled
    (carry-forward) actual values never appear here -- only real
    observations count as scoring targets."""
    import pandas as pd

    rows = []
    for r in records:
        for gi, g in enumerate(groups):
            if not r["scoring_mask"][gi]:
                continue
            rows.append(
                {
                    "model": r["model"], "start_week": r["start_week"], "landing_week": r["landing_week"],
                    "period": r["period"], "h": r["h"], "ward": g,
                    "pred": r["pred"][gi], "actual": r["actual"][gi],
                }
            )
    return pd.DataFrame(rows)
