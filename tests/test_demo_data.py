"""Tests for src/demo_data.py (animated demo page). Each check compares the
exported numbers with the saved results tables read a second way (the csv
module), so the page cannot show a number the pipeline did not produce."""
import csv
import json

import pytest

import config
from src import demo_data as dd

TABLES = config.RESULTS_TABLES_DIR


def _rows(name):
    with open(TABLES / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def data():
    return dd.build_demo_data()


def test_people_total_is_589(data):
    total = sum(p["patients"] + p["staff"] for p in data["people"].values())
    assert total == 589
    assert data["people"]["Other"]["patients"] == 0  # staff-only group


def test_weekly_prevalence_matches_p3_csv(data):
    rows = _rows("p3_states_real.csv")
    assert len(data["weeks"]) == config.N_WEEKS
    for r in rows:
        got = data["weeks"][int(r["week"])]["groups"][r["group"]]
        assert got["tested"] == int(r["n_tested"]) and got["positive"] == int(r["n_positive"])
        assert got["p"] == pytest.approx(float(r["prevalence"]), abs=1e-6)
    # every group-week absent from the csv must be exported as "not tested" (None)
    present = {(int(r["week"]), r["group"]) for r in rows}
    missing = [(w["week"], g) for w in data["weeks"] for g, v in w["groups"].items() if v is None]
    assert len(present) + len(missing) == config.N_WEEKS * len(config.WARD_GROUPS)


def test_week0_starts_on_monday_29_jun_2009(data):
    assert data["weeks"][0]["monday"] == "29 Jun 2009"


def test_within_ward_share_hand_check(data):
    """Independent: 90.3% of contact seconds are within-ward (p2 share table)."""
    share = float(_rows("p2_within_between_ward_share_all.csv")[0]["within_ward_share"])
    inside = sum(data["contacts"]["inside_hours"].values())
    between = 2 * sum(l["hours"] for l in data["contacts"]["links"])
    # Not exact: the raw matrix counts both directions of each contact, and
    # ~0.1% of contact rows have no reverse row (P1), so the two routes
    # differ by ~2e-5 (0.903316 vs 0.903337). The page shows a whole percent.
    assert inside / (inside + between) == pytest.approx(share, abs=1e-4)


def test_superspreader_and_intervention_match_tables(data):
    gt = {r["ward"]: float(r["drop_person_days_mean"]) for r in _rows("p9_ground_truth_intervention.csv")}
    for w in data["superspreader"]["wards"]:
        assert w["drop"] == pytest.approx(gt[w["ward"]])
    p10 = [r for r in _rows("p10_intervention_results.csv") if r["strategy"] in config.DEMO_STRATEGIES]
    assert len(p10) == len(data["interventions"]["rows"])
    best = next(r for r in data["interventions"]["rows"]
                if r["strategy"] == f"koopman_targeted_{config.APP_MODEL}" and r["k"] == 2 and r["R"] == 0.75)
    assert best["targeted_wards"] == "Menard 1,Sorrel 1" and best["drop_mean"] == pytest.approx(519.595)


def test_forecast_points_match_p8(data):
    rows = [r for r in _rows("p8_forecast_records_long.csv")
            if r["period"] == "holdout" and r["h"] == "1" and r["model"] in config.DEMO_FORECAST_MODELS]
    assert len(rows) == len(data["forecast"]["points"])


def test_written_js_is_valid(tmp_path):
    out = tmp_path / "demo_data.js"
    dd.write_demo_data(out)
    text = out.read_text(encoding="utf-8")
    body = text.split("window.DEMO_DATA = ", 1)[1].rstrip().rstrip(";")
    assert json.loads(body)["groups"] == config.WARD_GROUPS


def test_demo_html_is_self_contained():
    """The Streamlit iframe cannot load sibling files, so demo_html() must inline
    the stylesheet, the data and the script (only the web font stays external)."""
    from src.app_data import demo_html
    html = demo_html()
    assert 'href="styles.css"' not in html and 'src="demo.js"' not in html and 'src="demo_data.js"' not in html
    assert "window.DEMO_DATA = " in html and '<body class="embed">' in html
    assert html.count("<script>") == 3  # start-scene settings, data, script


def test_transitions_add_up_to_p3(data):
    """Second method for the spreading scene: per ward-week, the transition
    classes must add up to P3's tested and positive counts."""
    for r in _rows("p3_states_real.csv"):
        t = data["transitions"][r["week"]][r["group"]]
        assert sum(t[k] for k in ["new", "still", "first", "cleared", "negative"]) == t["tested"] == int(r["n_tested"])
        assert t["new"] + t["still"] + t["first"] == int(r["n_positive"])


def test_transitions_hand_check(data):
    """Hospital-wide totals over all weeks (printed by `python -m src.transitions`)."""
    tot = {k: sum(g[k] for wk in data["transitions"].values() for g in wk.values()) for k in ["new", "cleared"]}
    assert tot == {"new": 229, "cleared": 233}
