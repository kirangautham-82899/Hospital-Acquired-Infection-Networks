"""Shared forecast-scoring utilities. Used by P8 (real-data validation);
the flattened-long-DataFrame convention matches src/forecast.py's
flatten_records output, so downstream phases (P9+) can reuse this without
re-deriving their own aggregation logic.
"""
import numpy as np
import pandas as pd


def compute_metrics_from_long(df, group_by, model_col="model"):
    """df: long-format rows with columns [model, ..., ward, pred, actual]
    (e.g. src/forecast.py's flatten_records output). group_by: the list
    of columns to aggregate within (e.g. ['period', 'h']) -- 'ward' is
    handled specially: an 'overall' row (all wards pooled) is always
    produced in addition to one row per individual ward.

    Returns a long metrics table: model, <group_by columns>, ward
    ('overall' or a specific ward), n, rmse, mae, rmse_clipped,
    mae_clipped.
    """
    rows = []
    for keys, group in df.groupby([model_col] + list(group_by)):
        keys = keys if isinstance(keys, tuple) else (keys,)
        key_dict = dict(zip([model_col] + list(group_by), keys))

        for ward_filter in ["overall"] + sorted(group["ward"].unique().tolist()):
            sub = group if ward_filter == "overall" else group[group["ward"] == ward_filter]
            if sub.empty:
                continue
            pred, actual = sub["pred"].to_numpy(), sub["actual"].to_numpy()
            pred_clipped = np.clip(pred, 0.0, 1.0)
            row = dict(key_dict)
            row["ward"] = ward_filter
            row["n"] = len(sub)
            row["rmse"] = float(np.sqrt(np.mean((pred - actual) ** 2)))
            row["mae"] = float(np.mean(np.abs(pred - actual)))
            row["rmse_clipped"] = float(np.sqrt(np.mean((pred_clipped - actual) ** 2)))
            row["mae_clipped"] = float(np.mean(np.abs(pred_clipped - actual)))
            rows.append(row)
    return pd.DataFrame(rows)


def add_skill_vs_persistence(metrics, group_by, model_col="model", baseline_name="persistence"):
    """Append a skill_vs_persistence column: 1 - rmse_model / rmse_persistence,
    matched on every group_by key + ward. NaN where the persistence row
    doesn't exist or has rmse 0."""
    key_cols = list(group_by) + ["ward"]
    persist = metrics[metrics[model_col] == baseline_name].set_index(key_cols)["rmse"]

    def skill(row):
        key = tuple(row[c] for c in key_cols)
        persist_rmse = persist.get(key, np.nan)
        if not persist_rmse or persist_rmse == 0:
            return np.nan
        return 1.0 - row["rmse"] / persist_rmse

    out = metrics.copy()
    out["skill_vs_persistence"] = out.apply(skill, axis=1)
    return out
