"""Tests for src/app_data.py (results app helpers). They read the saved
results/ files, so they check the app shows what the pipeline produced."""
import csv

import numpy as np
import pandas as pd
import pytest

import config
from src import app_data as ad


@pytest.fixture(scope="module")
def ctx():
    return {"states": ad.load_states_real(), "W": ad.load_w(), "model": ad.load_app_model()}


def test_w_rows_sum_to_one(ctx):
    assert np.allclose(ctx["W"].to_numpy().sum(axis=1), 1.0)


def test_hospital_summary_counts():
    s = ad.hospital_summary()
    assert s["people"] == s["patients"] + s["staff"]
    assert s["groups"] == 6


def test_rollout_matches_p8_saved_forecast(ctx):
    """Independent check: the app's rollout from a real week must reproduce the
    one-week-ahead D3 forecast that P8 saved to p8_forecast_records_long.csv."""
    rec = pd.read_csv(config.RESULTS_TABLES_DIR / "p8_forecast_records_long.csv")
    rec = rec[(rec["model"] == config.APP_MODEL) & (rec["h"] == 1)]
    start = int(rec["start_week"].min())
    saved = rec[rec["start_week"] == start].set_index("ward")["pred"].reindex(config.WARD_GROUPS).to_numpy()
    # P8 started from the filled real state; rebuild it the same way
    from src.real_state_fill import fill_state_vector
    cf = pd.read_csv(config.DATA_PROCESSED_DIR / "states_real_carry_forward_SENSITIVITY_ONLY.csv")
    x0, _ = fill_state_vector(start, ctx["states"], cf, config.WARD_GROUPS)
    out = ad.koopman_rollout(ctx["model"], x0, 1, ctx["W"].to_numpy())
    assert np.allclose(out[1], saved, atol=1e-9)


def test_rollout_first_row_is_start(ctx):
    x0 = ad.usual_state(ctx["states"])
    out = ad.koopman_rollout(ctx["model"], x0, 3, ctx["W"].to_numpy())
    assert out.shape == (4, 6)
    assert np.allclose(out[0], x0)


def test_usual_state_by_csv_module(ctx):
    """Second method: average calibration-week prevalence with the csv module."""
    sums, counts = {}, {}
    with open(config.RESULTS_TABLES_DIR / "p3_states_real.csv", newline="") as f:
        for row in csv.DictReader(f):
            if int(row["week"]) in config.CALIBRATION_WEEKS:
                sums[row["group"]] = sums.get(row["group"], 0.0) + float(row["prevalence"])
                counts[row["group"]] = counts.get(row["group"], 0) + 1
    expected = np.array([sums[g] / counts[g] for g in config.WARD_GROUPS])
    assert np.allclose(ad.usual_state(ctx["states"]), expected)


@pytest.mark.parametrize("ward", config.APP_REAL_WARDS)
def test_what_if_outbreak(ctx, ward):
    df = ad.what_if_outbreak(ward, ctx["model"], ctx["states"], ctx["W"])
    assert len(df) == (config.APP_HORIZON_WEEKS + 1) * 6
    assert df[["with_outbreak", "without_outbreak"]].stack().between(0, 1).all()
    w0 = df[(df["week"] == 0) & (df["group"] == ward)].iloc[0]
    assert w0["extra"] == pytest.approx(config.APP_OUTBREAK_BUMP)
    others0 = df[(df["week"] == 0) & (df["group"] != ward)]
    assert np.allclose(others0["extra"], 0)
    sentence = ad.what_if_sentence(df, ward)
    assert ward in sentence and "nan" not in sentence.lower()


def test_forecast_vs_actual_columns():
    f = ad.forecast_vs_actual()
    assert {"landing_week", "ward", "koopman", "persistence", "actual"} <= set(f.columns)
    assert f[["koopman", "persistence", "actual"]].notna().all().all()


@pytest.mark.parametrize("k", config.INTERVENTION_K_VALUES)
@pytest.mark.parametrize("r", config.INTERVENTION_REDUCTIONS)
def test_intervention_options(k, r):
    o = ad.intervention_options(k, r)
    assert set(o["strategy"]) == set(ad.STRATEGY_LABELS)  # one row per strategy, none missing or duplicated
    assert o["drop_mean"].is_monotonic_decreasing
    budgets = o.loc[o["strategy"] != "none", "budget"]
    assert np.allclose(budgets, k * r)  # equal budget across strategies


def test_ranking_agreement_matches_table():
    a = ad.ranking_agreement()
    assert 0 <= a["koopman"] <= 1 and 0 <= a["contacts"] <= 1
