"""Data helpers for the results app (app/app.py).

Read-only: every function here loads files that the pipeline already
saved under results/ (tables and fitted EDMD models) and reshapes them
for display. Nothing is re-simulated or re-fitted, and nothing is written.
The one computation is the what-if forecast, which rolls a saved K
forward exactly as src/forecast.py does for real data.
"""
import numpy as np
import pandas as pd

import config
from src.forecast import load_edmd_model
from src.observables import apply_dictionary

TABLES = config.RESULTS_TABLES_DIR

# Plain-language names for the intervention strategies shown in the app.
STRATEGY_LABELS = {
    "none": "Do nothing",
    "random": "Ward(s) picked at random",
    "whole_hospital": "Spread the cut over the whole hospital",
    "degree_targeted": "Ward(s) with the most contact time",
    f"koopman_targeted_{config.APP_MODEL}": "Ward(s) picked by the Koopman model",
}


def demo_html():
    """The animated demo page (app/demo/) as ONE self-contained HTML string.

    st.components.v1.html renders a page inside an iframe that cannot load the
    page's sibling files, so the stylesheet, the data file and the script are
    inlined. The body gets the 'embed' class, which hides the page footer.
    Run `python -m src.demo_data` first so demo_data.js is current."""
    d = config.DEMO_DIR
    html = (d / "index.html").read_text(encoding="utf-8")
    parts = {
        '<link rel="stylesheet" href="styles.css">': "<style>" + (d / "styles.css").read_text(encoding="utf-8") + "</style>",
        '<script src="demo_data.js"></script>': "<script>" + config.DEMO_DATA_JS.read_text(encoding="utf-8") + "</script>",
        '<script src="demo.js"></script>': "<script>" + (d / "demo.js").read_text(encoding="utf-8") + "</script>",
        "<body>": '<body class="embed">',
    }
    for tag, inline in parts.items():
        assert html.count(tag) == 1, f"demo index.html changed: expected one {tag!r}"
        html = html.replace(tag, inline)
    return html


def load_states_real():
    """Weekly MRSA prevalence per group (P3 main run), one row per week and group."""
    return pd.read_csv(TABLES / "p3_states_real.csv")


def load_w():
    """Row-normalized ward contact matrix W (P2), rows and columns in config.WARD_GROUPS order."""
    w = pd.read_csv(TABLES / "p2_ward_matrix_W_all.csv", index_col=0)
    assert list(w.index) == config.WARD_GROUPS and list(w.columns) == config.WARD_GROUPS
    return w


def hospital_summary():
    """Headline counts for the first tab: people in the contact network, groups, weeks."""
    nodes = pd.read_csv(TABLES / "p2_node_metrics_all.csv")
    states = load_states_real()
    return {
        "people": int(nodes["calc_ident"].nunique()),
        "patients": int(nodes["calc_ident"].str.startswith("PA").sum()),
        "staff": int(nodes["calc_ident"].str.startswith("PE").sum()),
        "groups": len(config.WARD_GROUPS),
        "weeks": int(states["week"].nunique()),
    }


def within_ward_share(w):
    """Share of each group's contact time spent inside its own group (the diagonal of W)."""
    return pd.Series(np.diag(w.to_numpy()), index=w.index)


def usual_state(states_real):
    """Each group's average prevalence over the calibration weeks, in config.WARD_GROUPS order.
    This is the 'normal' hospital the what-if outbreak is added on top of."""
    calib = states_real[states_real["week"].isin(config.CALIBRATION_WEEKS)]
    return calib.groupby("group")["prevalence"].mean().reindex(config.WARD_GROUPS).to_numpy()


def koopman_rollout(model, x0, horizon, W):
    """Roll the saved Koopman operator K forward from state x0 for `horizon` weeks.
    Lift x0 with the model's dictionary, scale it, multiply by K once per week,
    and read the group prevalences back out. Returns an array [horizon+1, n_groups]
    whose first row is x0. Same steps as src/forecast.py edmd_forecast_real."""
    groups = model["groups"]
    idx = [model["feature_names"].index(f"x_{g}") for g in groups]
    phi, _ = apply_dictionary(model["name"], np.asarray(x0, float)[None, :], groups, W)
    current = model["scaler"].transform(phi)[0]
    out = [np.asarray(x0, float)]
    for _ in range(horizon):
        current = current @ model["K"].T
        out.append(model["scaler"].inverse_transform_indices(current[idx], idx))
    return np.array(out)


def load_app_model():
    """Load the saved EDMD model used by the app (config.APP_MODEL) and tag it with its name."""
    model = load_edmd_model(config.APP_MODEL)
    model["name"] = config.APP_MODEL
    assert model["groups"] == config.WARD_GROUPS
    return model


def what_if_outbreak(ward, model, states_real, W, bump=None, horizon=None):
    """Forecast an outbreak in one ward. Start from the usual state, add `bump` to the
    chosen ward, and roll K forward. Also roll forward the usual state with no outbreak,
    so the app can show the extra MRSA the outbreak causes in every group.
    Returns a long DataFrame (week, group, with_outbreak, without_outbreak, extra)."""
    bump = config.APP_OUTBREAK_BUMP if bump is None else bump
    horizon = config.APP_HORIZON_WEEKS if horizon is None else horizon
    base = usual_state(states_real)
    seeded = base.copy()
    i = config.WARD_GROUPS.index(ward)
    seeded[i] = min(1.0, seeded[i] + bump)
    with_ob = np.clip(koopman_rollout(model, seeded, horizon, W.to_numpy()), 0, 1)
    without_ob = np.clip(koopman_rollout(model, base, horizon, W.to_numpy()), 0, 1)
    rows = []
    for t in range(horizon + 1):
        for j, g in enumerate(config.WARD_GROUPS):
            rows.append({"week": t, "group": g, "with_outbreak": with_ob[t, j],
                         "without_outbreak": without_ob[t, j], "extra": with_ob[t, j] - without_ob[t, j]})
    return pd.DataFrame(rows)


def what_if_sentence(df, ward):
    """One plain-English sentence describing the what-if forecast's final week."""
    last = df[df["week"] == df["week"].max()].set_index("group")
    own = last.loc[ward]
    others = last.drop(index=ward)
    top = others["extra"].idxmax()
    weeks = int(df["week"].max())
    first = (
        f"After {weeks} weeks, about {own.with_outbreak:.0%} of people in {ward} carry MRSA, "
        f"against {own.without_outbreak:.0%} with no outbreak. "
    )
    gain_pp = others["extra"].max() * 100
    if gain_pp < 0.5:
        return first + "The outbreak stays in its own ward: no other group goes up by even half a percentage point."
    return first + (
        f"The outbreak mostly stays in {ward}. The group it spreads to most is {top}, "
        f"which goes up by {gain_pp:.1f} percentage points."
    )


def forecast_vs_actual(model_name=None, h=1):
    """One-week-ahead forecasts on the real data (P8), for the model and for persistence
    ('next week = this week'), with the real value. Long DataFrame by landing week and ward."""
    model_name = config.APP_MODEL if model_name is None else model_name
    rec = pd.read_csv(TABLES / "p8_forecast_records_long.csv")
    rec = rec[(rec["h"] == h) & rec["model"].isin([model_name, "persistence"])]
    wide = rec.pivot_table(index=["landing_week", "ward", "period"], columns="model", values="pred").reset_index()
    actual = rec.drop_duplicates(["landing_week", "ward"])[["landing_week", "ward", "actual"]]
    return wide.merge(actual, on=["landing_week", "ward"]).rename(columns={model_name: "koopman"})


def holdout_rmse(h=1):
    """Hold-out RMSE (all wards pooled) for the app model and persistence at horizon h (P8)."""
    m = pd.read_csv(TABLES / "p8_metrics_summary.csv")
    m = m[(m["period"] == "holdout") & (m["ward"] == "overall") & (m["h"] == h)].set_index("model")
    return {"koopman": float(m.loc[config.APP_MODEL, "rmse"]), "persistence": float(m.loc["persistence", "rmse"])}


def intervention_options(k, reduction):
    """P10 results for one (k wards, contact reduction) setting, restricted to the
    strategies in STRATEGY_LABELS, with plain-language names. Sorted best first."""
    d = pd.read_csv(TABLES / "p10_intervention_results.csv")
    keep = d["strategy"].isin(STRATEGY_LABELS) & (
        ((d["k"] == k) & np.isclose(d["R"], reduction)) | (d["strategy"] == "none")
    )
    d = d[keep].copy()
    if "whole_hospital" in set(d["strategy"]):
        # whole_hospital rows use the same equal budget (k * R) under each k; keep the matching one
        budget = k * reduction
        d = d[(d["strategy"] != "whole_hospital") | np.isclose(d["budget"], budget)]
    d["label"] = d["strategy"].map(STRATEGY_LABELS)
    d["targeted_wards"] = d["targeted_wards"].fillna("").str.replace(",", ", ")
    return d.sort_values("drop_mean", ascending=False).reset_index(drop=True)


def ward_ranking():
    """Per-ward 'MRSA days prevented' when that ward's contacts are halved (P9 ground truth),
    next to the Koopman score and contact count. Sorted by prevented days."""
    s = pd.read_csv(TABLES / "p9_ward_scores.csv")
    s = s[["ward", "ground_truth_drop", f"koopman_{config.APP_MODEL}", "degree_centrality"]]
    return s.sort_values("ground_truth_drop", ascending=False).reset_index(drop=True)


def ranking_agreement():
    """Spearman rho between each ranking method and the 50%-cut ground truth (P9)."""
    s = pd.read_csv(TABLES / "p9_spearman_vs_ground_truth.csv")
    s = s[s["ground_truth"] == "pct50"].set_index("candidate")["spearman_rho"]
    return {"koopman": float(s[f"koopman_{config.APP_MODEL}"]), "contacts": float(s["degree_centrality"])}
