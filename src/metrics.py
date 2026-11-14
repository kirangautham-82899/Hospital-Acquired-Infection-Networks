"""Shared forecast-scoring utilities. Used by P8 (real-data validation);
the flattened-long-DataFrame convention matches src/forecast.py's
flatten_records output, so downstream phases (P9+) can reuse this without
re-deriving their own aggregation logic.
"""
import itertools

import numpy as np
import pandas as pd
from scipy import stats

import config


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


# ---------------------------------------------------------------------------
# Uncertainty helpers (added after the Nov 14 review)
# ---------------------------------------------------------------------------

def paired_mean_ci(diff, level=None):
    """Mean of paired per-replicate differences with a t-based confidence
    interval and a two-sided one-sample t-test p-value (H0: mean = 0).
    Pairing comes from common random numbers: replicate i of both arms
    used the same seeds, so diff_i removes shared simulation noise."""
    level = config.CI_LEVEL if level is None else level
    diff = np.asarray(diff, dtype=float)
    n = len(diff)
    mean = float(diff.mean())
    sd = float(diff.std(ddof=1)) if n > 1 else 0.0
    se = sd / np.sqrt(n) if n > 0 else np.nan
    if se == 0:
        return {"mean": mean, "ci_low": mean, "ci_high": mean, "p_value": 0.0 if mean != 0 else 1.0, "n": n}
    tcrit = stats.t.ppf(0.5 + level / 2.0, df=n - 1)
    p = float(2 * stats.t.sf(abs(mean / se), df=n - 1))
    return {"mean": mean, "ci_low": mean - tcrit * se, "ci_high": mean + tcrit * se, "p_value": p, "n": n}


def spearman_exact(x, y):
    """Spearman rho with an EXACT two-sided permutation p-value (all n!
    orderings of y; 720 for n=6). scipy's default p-value uses a
    t-approximation that is unreliable at n=6."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    rho = stats.spearmanr(x, y).statistic
    perms = [stats.spearmanr(x, y[list(p)]).statistic for p in itertools.permutations(range(len(y)))]
    perms = np.asarray(perms)
    p = float(np.mean(np.abs(perms) >= abs(rho) - 1e-12))
    return float(rho), p


def block_bootstrap_rmse_diff(df_model, df_base, n_boot=None, level=None, seed=None, block_col="start_week"):
    """Paired comparison of two forecasters' RMSE on the SAME scored cells.
    df_model / df_base: long forecast rows (start_week, landing_week, ward,
    pred, actual) for one period and horizon. Resamples whole forecast
    start weeks with replacement (cells from one start week share
    errors, so they are not independent). Returns the observed RMSE
    difference (model - base; negative = model better), its bootstrap
    percentile CI, and the share of resamples where the model is NOT
    better (a one-sided bootstrap p-value for "model beats base")."""
    n_boot = config.P8_BOOTSTRAP_N if n_boot is None else n_boot
    level = config.CI_LEVEL if level is None else level
    seed = config.SEED if seed is None else seed
    key = [block_col, "landing_week", "ward"]
    m = df_model.set_index(key)
    b = df_base.set_index(key)
    common = m.index.intersection(b.index)
    m, b = m.loc[common], b.loc[common]
    se_m = ((m["pred"] - m["actual"]) ** 2).to_numpy()
    se_b = ((b["pred"] - b["actual"]) ** 2).to_numpy()
    blocks = common.get_level_values(block_col).to_numpy()
    uniq = np.unique(blocks)
    idx_by_block = [np.flatnonzero(blocks == u) for u in uniq]

    observed = float(np.sqrt(se_m.mean()) - np.sqrt(se_b.mean()))
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, len(uniq), size=len(uniq))
        rows = np.concatenate([idx_by_block[k] for k in pick])
        diffs[i] = np.sqrt(se_m[rows].mean()) - np.sqrt(se_b[rows].mean())
    alpha = 1.0 - level
    return {
        "n_cells": int(len(common)), "n_blocks": int(len(uniq)), "rmse_diff": observed,
        "ci_low": float(np.quantile(diffs, alpha / 2)), "ci_high": float(np.quantile(diffs, 1 - alpha / 2)),
        "p_not_better": float(np.mean(diffs >= 0)),
    }


def binomial_noise_floor(prevalence, n_tested):
    """Root-mean-square binomial sampling standard error of observed
    weekly prevalence, sqrt(mean(p(1-p)/n)): how uncertain each observed
    weekly value is as an estimate of the ward's prevalence. NOT a strict
    lower bound on forecast RMSE here: consecutive weeks mostly re-swab
    the same people, so sampling errors are strongly correlated week to
    week (persistence can score below this value). It is the yardstick
    for whether a difference between two models' RMSEs is practically
    meaningful."""
    p = np.asarray(prevalence, dtype=float)
    n = np.asarray(n_tested, dtype=float)
    return float(np.sqrt(np.mean(p * (1 - p) / n)))
