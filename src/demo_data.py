"""Export saved P30 results for the animated demo page (app/demo/index.html).

Read-only on results/: nothing is simulated or fitted. Every number the
demo shows comes from a table the pipeline already wrote. The output is a
small JavaScript file (window.DEMO_DATA = {...}) so the page opens straight
from disk, with no server and no network.

Run from the project root:
    python -m src.demo_data
"""
import json
import math

import numpy as np
import pandas as pd

import config
from src.network import monday_on_or_before

TABLES = config.RESULTS_TABLES_DIR


def _clean(v):
    """Turn numpy / NaN values into plain JSON values (NaN -> None)."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(v) else round(float(v), 6)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def ward_people():
    """People in the contact network per group, split into patients (PA) and staff (PE)."""
    nodes = pd.read_csv(TABLES / "p2_node_metrics_all.csv")
    out = {}
    for g in config.WARD_GROUPS:
        ids = nodes.loc[nodes["ward_group"] == g, "calc_ident"]
        out[g] = {"patients": int(ids.str.startswith("PA").sum()), "staff": int(ids.str.startswith("PE").sum())}
    return out


def weekly_prevalence():
    """Real weekly prevalence (P3 main run) as {week: {group: {...} or None}}.
    None means nobody in that group was tested that week (no imputation)."""
    s = pd.read_csv(TABLES / "p3_states_real.csv")
    start = monday_on_or_before(config.STUDY_START)
    weeks = []
    for w in range(config.N_WEEKS):
        row = {"week": w, "monday": (start + pd.Timedelta(days=7 * w)).strftime("%d %b %Y"), "groups": {}}
        for g in config.WARD_GROUPS:
            r = s[(s["week"] == w) & (s["group"] == g)]
            row["groups"][g] = None if r.empty else {
                "p": _clean(r["prevalence"].iloc[0]), "tested": int(r["n_tested"].iloc[0]),
                "positive": int(r["n_positive"].iloc[0]), "low_n": bool(r["low_n"].iloc[0])}
        weeks.append(row)
    return weeks


def contact_hours():
    """Between-group contact hours (P2 raw matrix, seconds -> hours), symmetrized
    as the mean of both directions, plus each group's within-group share (diag of W)."""
    raw = pd.read_csv(TABLES / "p2_ward_matrix_raw_all.csv", index_col=0).loc[config.WARD_GROUPS, config.WARD_GROUPS]
    w = pd.read_csv(TABLES / "p2_ward_matrix_W_all.csv", index_col=0).loc[config.WARD_GROUPS, config.WARD_GROUPS]
    hours = raw.to_numpy() / 3600.0
    sym = (hours + hours.T) / 2.0
    links = []
    for i, a in enumerate(config.WARD_GROUPS):
        for j, b in enumerate(config.WARD_GROUPS):
            if j > i:
                links.append({"a": a, "b": b, "hours": _clean(sym[i, j])})
    within = {g: _clean(w.loc[g, g]) for g in config.WARD_GROUPS}
    inside_hours = {g: _clean(hours[i, i]) for i, g in enumerate(config.WARD_GROUPS)}
    return {"links": links, "within_share": within, "inside_hours": inside_hours}


def forecasts():
    """Holdout one-week-ahead forecasts (P8) for the demo models, and the
    overall holdout RMSE for h = 1..4."""
    rec = pd.read_csv(TABLES / "p8_forecast_records_long.csv")
    rec = rec[(rec["period"] == "holdout") & (rec["h"] == 1) & rec["model"].isin(config.DEMO_FORECAST_MODELS)]
    points = [{k: _clean(v) for k, v in r.items()} for r in
              rec[["model", "landing_week", "ward", "pred", "actual"]].to_dict("records")]
    summ = pd.read_csv(TABLES / "p8_metrics_summary.csv")
    summ = summ[(summ["period"] == "holdout") & (summ["ward"] == "overall") & summ["model"].isin(config.DEMO_FORECAST_MODELS)]
    rmse = [{"model": r["model"], "h": int(r["h"]), "rmse": _clean(r["rmse"])} for _, r in summ.iterrows()]
    return {"points": points, "rmse": rmse, "holdout_weeks": config.HOLDOUT_WEEKS}


def superspreader():
    """Per-ward ground truth (P9, 50% cut and equal-hours cut, with 95% CIs),
    the Koopman D3 dominant-mode share and contact hours, plus Spearman rows."""
    gt = pd.read_csv(TABLES / "p9_ground_truth_intervention.csv").set_index("ward")
    eq = pd.read_csv(TABLES / "p9_ground_truth_equal_hours.csv").set_index("ward")
    sc = pd.read_csv(TABLES / "p9_ward_scores.csv").set_index("ward")
    wards = []
    for g in config.WARD_GROUPS:
        wards.append({
            "ward": g,
            "drop": _clean(gt.loc[g, "drop_person_days_mean"]), "lo": _clean(gt.loc[g, "drop_ci_low"]),
            "hi": _clean(gt.loc[g, "drop_ci_high"]),
            "eq_drop": _clean(eq.loc[g, "drop_person_days_mean"]), "eq_lo": _clean(eq.loc[g, "drop_ci_low"]),
            "eq_hi": _clean(eq.loc[g, "drop_ci_high"]),
            "koopman": _clean(sc.loc[g, f"koopman_{config.APP_MODEL}"]),
            "contact_hours": _clean(sc.loc[g, "degree_centrality"] / 3600.0)})
    sp = pd.read_csv(TABLES / "p9_spearman_vs_ground_truth.csv")
    keep = ["degree_centrality", f"koopman_{config.APP_MODEL}", "betweenness_centrality"]
    sp = sp[sp["candidate"].isin(keep)]
    spearman = [{k: _clean(v) for k, v in r.items()} for r in sp.to_dict("records")]
    return {"wards": wards, "spearman": spearman, "baseline_person_days": _clean(gt["baseline_mean_person_days"].iloc[0])}


def interventions():
    """P10 results for the demo strategies, every (k, R) cell, plus the pairwise
    verdict of Koopman-targeted vs degree-targeted."""
    res = pd.read_csv(TABLES / "p10_intervention_results.csv")
    res = res[res["strategy"].isin(config.DEMO_STRATEGIES)]
    rows = [{k: _clean(v) for k, v in r.items()} for r in res.fillna({"targeted_wards": ""}).to_dict("records")]
    pw = pd.read_csv(TABLES / "p10_pairwise_comparisons.csv")
    pw = pw[(pw["strategy"] == f"koopman_targeted_{config.APP_MODEL}")]
    pair = [{k: _clean(v) for k, v in r.items()} for r in pw.to_dict("records")]
    return {"rows": rows, "pairwise": pair}


def story():
    """The anonymised A -> B -> C chain saved by src/story.py (people are
    only 'A', 'B', 'C'), plus its context row and the calibrated beta."""
    ev = pd.read_csv(TABLES / "story_chain_events.csv", dtype={"strain": str}).fillna("")
    su = pd.read_csv(TABLES / "story_chain_summary.csv").iloc[0]
    events = [{"who": r["who"], "event": r["event"], "date": r["date"],
               "mrsa": None if r["mrsa"] == "" else int(float(r["mrsa"])),
               "strain": r["strain"], "minutes": None if r["minutes"] == "" else float(r["minutes"])}
              for _, r in ev.iterrows()]
    return {"events": events, "ward": su["ward"], "strain": str(su["strain"]),
            "strain_share": _clean(su["strain_share_of_mrsa_swabs"]),
            "n_chains": int(su["n_chains_found"]), "n_cross_ward": int(su["n_cross_ward_chains"])}


def build_demo_data():
    """Collect everything the demo page needs into one dict."""
    params = pd.read_csv(TABLES / "p4_calibrated_params.csv").iloc[0]
    return {
        "groups": config.WARD_GROUPS,
        "people": ward_people(),
        "people_per_figure": config.DEMO_PEOPLE_PER_FIGURE,
        "weeks": weekly_prevalence(),
        "contacts": contact_hours(),
        "forecast": forecasts(),
        "superspreader": superspreader(),
        "interventions": interventions(),
        "model": config.APP_MODEL,
        "params": {k: _clean(params[k]) for k in ["beta", "gamma", "epsilon"]},
        "calibration_weeks": config.CALIBRATION_WEEKS,
        "story": story(),
    }


def write_demo_data(path=config.DEMO_DATA_JS):
    """Write window.DEMO_DATA = {...}; to app/demo/demo_data.js and return the dict."""
    data = build_demo_data()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// Generated by src/demo_data.py from results/tables. Do not edit by hand.\n"
                    "window.DEMO_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n", encoding="utf-8")
    return data


if __name__ == "__main__":
    d = write_demo_data()
    print(f"wrote {config.DEMO_DATA_JS} ({config.DEMO_DATA_JS.stat().st_size} bytes), "
          f"{len(d['weeks'])} weeks, {len(d['forecast']['points'])} forecast points, "
          f"{len(d['interventions']['rows'])} intervention rows")
