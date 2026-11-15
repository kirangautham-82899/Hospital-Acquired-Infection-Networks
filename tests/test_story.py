"""Tests for src/story.py: the step-by-step demo chain must (1) satisfy every
rule it claims, checked from the saved events with plain csv, (2) match the
raw swab file read a second way, and (3) carry no personal identifiers."""
import csv

import pytest

import config
from src import story

EVENTS = config.RESULTS_TABLES_DIR / "story_chain_events.csv"


@pytest.fixture(scope="module")
def ev():
    with open(EVENTS, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _sw(ev, who):
    return [e for e in ev if e["who"] == who and e["event"] == "swab"]


def _ct(ev, tag):
    return [e for e in ev if e["who"] == tag and e["event"] == "contact"]


def test_no_identifiers(ev):
    assert {e["who"] for e in ev} <= {"A", "B", "C", "AB", "BC"}
    with open(EVENTS, encoding="utf-8") as fh:
        text = fh.read()
    assert "PA-" not in text and "PE-" not in text


def test_chain_rules_hold(ev):
    ab, bc = _ct(ev, "AB"), _ct(ev, "BC")
    b_pos = next(e for e in _sw(ev, "B") if e["mrsa"] == "1")
    b_neg = [e for e in _sw(ev, "B") if e["mrsa"] == "0" and e["date"] < b_pos["date"]]
    c_pos = next(e for e in _sw(ev, "C") if e["mrsa"] == "1")
    c_neg = [e for e in _sw(ev, "C") if e["mrsa"] == "0" and e["date"] < c_pos["date"]]
    strain = b_pos["strain"]
    assert strain.startswith(config.STORY_MRSA_STRAIN_PREFIX) and c_pos["strain"] == strain
    # A carried the strain before the first A-B contact
    a_before = [e for e in _sw(ev, "A") if e["date"] <= ab[0]["date"]]
    assert a_before and a_before[-1]["mrsa"] == "1" and a_before[-1]["strain"] == strain
    # B: negative, then contact with A, then positive
    assert b_neg and b_neg[-1]["date"] < ab[0]["date"] and ab[-1]["date"] <= b_pos["date"]
    # C: negative, then contact with B, then positive; B still positive by then
    assert c_neg and c_neg[-1]["date"] < bc[0]["date"] and bc[-1]["date"] <= c_pos["date"]
    b_last = [e for e in _sw(ev, "B") if e["date"] <= bc[0]["date"]][-1]
    assert b_last["mrsa"] == "1" and b_last["strain"] == strain


def test_minutes_hand_check(ev):
    """Hand sum of the exported contact minutes (2.5 + 40 + 18; 18 + 85)."""
    assert sum(float(e["minutes"]) for e in _ct(ev, "AB")) == pytest.approx(60.5)
    assert sum(float(e["minutes"]) for e in _ct(ev, "BC")) == pytest.approx(103.0)


def test_swabs_match_raw_file_read_with_csv_module(ev):
    """Second method: re-find the three people by matching the exported swab
    sequences against microbio.csv read with the csv module, not pandas."""
    by_person = {}
    with open(config.MICROBIO_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh, delimiter=";"))
    header = rows[0]
    idx = {k: header.index(k) + 1 for k in ("calc_ident", "date_prl", "sarm")}  # +1: unnamed row-number column
    for r in rows[1:]:
        by_person.setdefault(r[idx["calc_ident"]], set()).add((r[idx["date_prl"]].strip('"'), r[idx["sarm"]]))
    for who in ("A", "B", "C"):
        want = {(e["date"], e["mrsa"]) for e in _sw(ev, who)}
        matches = [p for p, s in by_person.items() if want <= s]
        assert len(matches) >= 1, f"{who}: no person in microbio.csv has these swabs"


def test_acquisitions_detects_switch():
    import pandas as pd
    t = {"X": pd.DataFrame({"date_prl": pd.to_datetime(["2009-07-01", "2009-07-08", "2009-07-15"]),
                            "sarm": [0, 1, 1], "strain": ["0", "1.2.1", "1.2.1"]})}
    acq = story.acquisitions(t)
    assert len(acq) == 1 and acq.iloc[0]["strain"] == "1.2.1"
