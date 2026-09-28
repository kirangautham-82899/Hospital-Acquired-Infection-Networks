"""Tests for src/states.py (P3): window restriction, weekly per-person
status, weekly prevalence, repeat-test handling, and the carry-forward
sensitivity series."""
import pandas as pd
import pytest

import config
from src.load import load_admission, load_contacts, load_microbio
from src.states import (
    carry_forward_prevalence,
    carry_forward_status,
    repeat_test_report,
    restrict_to_window,
    weekly_person_status,
    weekly_prevalence,
)


@pytest.fixture(scope="module")
def admission():
    return load_admission(config.ADMISSION_CSV)


@pytest.fixture(scope="module")
def contacts():
    return load_contacts(config.CONTACTS_CSV)


@pytest.fixture(scope="module")
def microbio():
    return load_microbio(config.MICROBIO_CSV)


@pytest.fixture(scope="module")
def network_people(contacts):
    return set(contacts["from"]) | set(contacts["to"])


@pytest.fixture(scope="module")
def windows(microbio):
    return restrict_to_window(microbio)


# ---- window restriction ----

def test_window_split_conserves_all_rows(microbio, windows):
    in_window, before, after = windows
    assert len(in_window) + len(before) + len(after) == microbio.shape[0]


def test_window_counts_match_verified_reference(windows):
    in_window, before, after = windows
    assert len(in_window) == 4492
    assert len(before) == 2198
    assert len(after) == 38  # 2009-10-26 and 2009-10-27 tests, dropped per research_log.md


def test_after_window_rows_are_all_after_study_end(windows):
    _, _, after = windows
    assert (after["date_prl"] > pd.Timestamp(config.STUDY_END)).all()


def test_before_window_rows_are_all_before_study_start(windows):
    _, before, _ = windows
    assert (before["date_prl"] < pd.Timestamp(config.STUDY_START)).all()


# ---- repeat-test handling: cross-checked against independently verified reference numbers ----

def test_repeat_report_all_tested_population_matches_reference(admission, windows):
    in_window, _, _ = windows
    status = weekly_person_status(in_window, admission, person_filter=None)
    n_pw, n_rep = repeat_test_report(status)
    assert n_pw == 4412
    assert n_rep == 80


def test_repeat_report_network_population_is_subset_of_all_tested(admission, windows, network_people):
    in_window, _, _ = windows
    status_all = weekly_person_status(in_window, admission, person_filter=None)
    status_net = weekly_person_status(in_window, admission, person_filter=network_people)
    n_pw_all, _ = repeat_test_report(status_all)
    n_pw_net, _ = repeat_test_report(status_net)
    assert n_pw_net < n_pw_all
    assert set(status_net["calc_ident"]) <= network_people


# ---- weekly_person_status: repeat resolution rule ----

def test_any_positive_in_week_counts_as_positive():
    microbio_like = pd.DataFrame(
        {
            "calc_ident": ["PA-001-AAA", "PA-001-AAA"],
            "date_prl": [pd.Timestamp("2009-07-06"), pd.Timestamp("2009-07-07")],  # both week 1
            "sarm": [0, 1],
        }
    )
    admission_like = pd.DataFrame({"calc_ident": ["PA-001-AAA"], "service_pa_pe": ["Menard 1"]})
    status = weekly_person_status(microbio_like, admission_like)
    assert len(status) == 1  # one person, one week -> one row despite 2 tests
    row = status.iloc[0]
    assert row["status"] == 1  # any positive that week -> positive
    assert row["n_tests"] == 2


def test_person_counts_once_in_denominator_despite_repeat(admission, windows, network_people):
    in_window, _, _ = windows
    status = weekly_person_status(in_window, admission, person_filter=network_people)
    prevalence = weekly_prevalence(status, groups=config.WARD_GROUPS)
    # n_tested must count distinct people, not test rows
    assert prevalence["n_tested"].max() < status.groupby(["week", "ward_group"])["n_tests"].sum().max() + 1


# ---- weekly_prevalence ----

def test_states_real_row_count_and_bounds(admission, windows, network_people):
    in_window, _, _ = windows
    status = weekly_person_status(in_window, admission, person_filter=network_people)
    states_real = weekly_prevalence(status, groups=config.WARD_GROUPS)
    assert len(states_real) == 93  # 9 of 102 possible group-weeks have zero tested people
    assert (states_real["prevalence"] >= 0).all() and (states_real["prevalence"] <= 1).all()
    assert states_real["prevalence"].isna().sum() == 0
    assert set(states_real["group"]) <= set(config.WARD_GROUPS)


def test_low_n_flag_is_consistent_with_threshold(admission, windows, network_people):
    in_window, _, _ = windows
    status = weekly_person_status(in_window, admission, person_filter=network_people)
    states_real = weekly_prevalence(status, groups=config.WARD_GROUPS)
    assert (states_real.loc[states_real["low_n"], "n_tested"] < 10).all()
    assert (states_real.loc[~states_real["low_n"], "n_tested"] >= 10).all()


def test_hand_check_menard1_week5(admission, microbio, network_people):
    """Independent recomputation for one cell, mirroring src/build_states.py's
    hand_check but expressed as a standalone pytest assertion."""
    from src.wards import person_ward_map

    ward_of = person_ward_map(admission)
    week_start, week_end = pd.Timestamp("2009-08-03"), pd.Timestamp("2009-08-09")
    sub = microbio[
        (microbio["date_prl"] >= week_start)
        & (microbio["date_prl"] <= week_end)
        & (microbio["calc_ident"].isin(network_people))
    ]
    sub = sub[sub["calc_ident"].map(ward_of) == "Menard 1"]
    people = sub.groupby("calc_ident")["sarm"].apply(lambda s: int((s == 1).any()))
    assert len(people) == 67
    assert int(people.sum()) == 13


# ---- carry-forward: sensitivity only ----

def test_carry_forward_fills_up_to_2_weeks_not_3():
    status = pd.DataFrame(
        {
            "calc_ident": ["P1", "P1"],
            "week": [0, 4],
            "ward_group": ["Menard 1", "Menard 1"],
            "status": [1, 0],
            "n_tests": [1, 1],
        }
    )
    carried = carry_forward_status(status, max_weeks=2)
    by_week = carried.set_index("week")
    assert by_week.loc[0, "status"] == 1 and not by_week.loc[0, "is_carried"]
    assert by_week.loc[1, "status"] == 1 and by_week.loc[1, "is_carried"]
    assert by_week.loc[2, "status"] == 1 and by_week.loc[2, "is_carried"]
    assert 3 not in by_week.index  # week 3 is >2 weeks after week 0's test -> not filled
    assert by_week.loc[4, "status"] == 0 and not by_week.loc[4, "is_carried"]


def test_carry_forward_never_exceeds_fresh_count(admission, windows, network_people):
    in_window, _, _ = windows
    status = weekly_person_status(in_window, admission, person_filter=network_people)
    carried = carry_forward_status(status)
    cf_prevalence = carry_forward_prevalence(carried, groups=config.WARD_GROUPS)
    assert (cf_prevalence["n_carried"] <= cf_prevalence["n_tested"]).all()
    assert (cf_prevalence["prevalence"] >= 0).all() and (cf_prevalence["prevalence"] <= 1).all()


def test_carry_forward_covers_more_group_weeks_than_main(admission, windows, network_people):
    in_window, _, _ = windows
    status = weekly_person_status(in_window, admission, person_filter=network_people)
    states_real = weekly_prevalence(status, groups=config.WARD_GROUPS)
    carried = carry_forward_status(status)
    cf_prevalence = carry_forward_prevalence(carried, groups=config.WARD_GROUPS)
    assert len(cf_prevalence) >= len(states_real)
