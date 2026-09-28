"""P3: real weekly MRSA prevalence per ward group, built from microbio.csv
tests inside the contact-network window (2009-07-01 to 2009-10-25),
Monday-anchored weekly bins (src/network.py's assign_week -- see
research_log.md for why Monday-anchoring, not STUDY_START-anchoring, is
required here).

Population decision (locked, see research_log.md): the MAIN series only
counts people who are both tested in-window AND present in the 589-person
contact network, because P4's simulator only runs on those 589 people --
calibrating it against a prevalence series drawn from a different
population (e.g. including people with no contact record at all) would not
be a fair target. A CHECK series using all people tested in-window
(including those absent from the network) is also produced, to quantify
how much this restriction matters.

Repeat tests within a week (rare once Monday-anchored: 80 of 4,412
person-weeks, 1.8%) are resolved as: a person counts as positive that week
if ANY of that week's tests is sarm=1, and counts once in the denominator
regardless of how many times they were tested that week.

Tests on 2009-10-26 and 2009-10-27 fall outside the contact window and are
dropped from every series (noted in research_log.md). Tests before the
window (2009-05-04 to 2009-06-28) are kept in a separate file for context/
starting-state use, not used for calibration.

Carry-forward status (carry_forward_status / carry_forward_prevalence) is a
SENSITIVITY CHECK ONLY: it smooths the series by filling untested weeks
with a person's last known result (positive or negative) for up to 2
weeks, which is not a real observation. Never treat it as a validation
target.
"""
import numpy as np
import pandas as pd

import config
from src.network import assign_week
from src.wards import person_ward_map

MIN_TESTED_FLAG = 10  # group-weeks with fewer tested people than this are flagged, not dropped
CARRY_FORWARD_MAX_WEEKS = 2


def restrict_to_window(microbio, start=None, end=None):
    """Return the microbio rows with date_prl inside [start, end]
    (defaults to config.STUDY_START/STUDY_END), plus the dropped
    out-of-window-on-the-right rows (tests after `end`, which matter
    separately from the very-early pre-window rows)."""
    start = pd.Timestamp(start or config.STUDY_START)
    end = pd.Timestamp(end or config.STUDY_END)
    in_window = microbio[(microbio["date_prl"] >= start) & (microbio["date_prl"] <= end)]
    after_window = microbio[microbio["date_prl"] > end]
    before_window = microbio[microbio["date_prl"] < start]
    return in_window, before_window, after_window


def weekly_person_status(microbio_in_window, admission, person_filter=None):
    """Collapse in-window microbio tests to one row per (calc_ident, week):
    status=1 if any test that week was sarm=1 else 0, n_tests = how many
    tests that person had that week (repeat-test diagnostic). person_filter,
    if given, is a set of calc_ident to keep (e.g. the 589-person network)."""
    df = microbio_in_window.copy()
    if person_filter is not None:
        df = df[df["calc_ident"].isin(person_filter)]
    df["week"] = assign_week(df["date_prl"])
    ward_of = person_ward_map(admission)
    df["ward_group"] = df["calc_ident"].map(ward_of)

    grouped = (
        df.groupby(["calc_ident", "week", "ward_group"])
        .agg(status=("sarm", lambda s: int((s == 1).any())), n_tests=("sarm", "size"))
        .reset_index()
    )
    return grouped


def repeat_test_report(person_status):
    """Return (n_person_weeks, n_with_repeats) from a weekly_person_status
    table."""
    return len(person_status), int((person_status["n_tests"] > 1).sum())


def weekly_prevalence(person_status, groups):
    """Aggregate a weekly_person_status table into one row per (week,
    group): n_tested, n_positive, prevalence, low_n (n_tested <
    MIN_TESTED_FLAG). Every (week, group) combination present in the data
    is included; group-weeks with zero tested people are NOT synthesized
    (no data is not the same as 0% prevalence)."""
    agg = (
        person_status.groupby(["week", "ward_group"])
        .agg(n_tested=("calc_ident", "nunique"), n_positive=("status", "sum"))
        .reset_index()
        .rename(columns={"ward_group": "group"})
    )
    agg["prevalence"] = agg["n_positive"] / agg["n_tested"]
    agg["low_n"] = agg["n_tested"] < MIN_TESTED_FLAG
    agg = agg[agg["group"].isin(groups)]
    return agg.sort_values(["week", "group"]).reset_index(drop=True)[
        ["week", "group", "prevalence", "n_tested", "n_positive", "low_n"]
    ]


def carry_forward_status(person_status, max_weeks=CARRY_FORWARD_MAX_WEEKS):
    """SENSITIVITY CHECK ONLY (see module docstring). For each person and
    each week from their first to last test, fill untested weeks with
    their most recent known status (positive or negative), up to
    max_weeks back. Returns (calc_ident, week, ward_group, status,
    is_carried)."""
    pivot = person_status.pivot(index="calc_ident", columns="week", values="status")
    all_weeks = range(int(person_status["week"].min()), int(person_status["week"].max()) + 1)
    pivot = pivot.reindex(columns=all_weeks)

    known_mask = pivot.notna()
    filled = pivot.ffill(axis=1, limit=max_weeks)
    carried_mask = filled.notna() & ~known_mask

    ward_of = person_status.drop_duplicates("calc_ident").set_index("calc_ident")["ward_group"]

    status_long = filled.stack().dropna().rename("status").reset_index()
    status_long.columns = ["calc_ident", "week", "status"]
    carried_long = carried_mask.stack().rename("is_carried").reset_index()
    carried_long.columns = ["calc_ident", "week", "is_carried"]

    out = status_long.merge(carried_long, on=["calc_ident", "week"])
    out["ward_group"] = out["calc_ident"].map(ward_of)
    return out.sort_values(["calc_ident", "week"]).reset_index(drop=True)


def carry_forward_prevalence(carried_status, groups):
    """SENSITIVITY CHECK ONLY (see module docstring). Same aggregation as
    weekly_prevalence but over the carry-forward-filled status table, plus
    an n_carried column reporting how many of that week's included people
    had their status carried forward rather than freshly tested."""
    agg = (
        carried_status.groupby(["week", "ward_group"])
        .agg(
            n_tested=("calc_ident", "nunique"),
            n_positive=("status", "sum"),
            n_carried=("is_carried", "sum"),
        )
        .reset_index()
        .rename(columns={"ward_group": "group"})
    )
    agg["prevalence"] = agg["n_positive"] / agg["n_tested"]
    agg["low_n"] = agg["n_tested"] < MIN_TESTED_FLAG
    agg = agg[agg["group"].isin(groups)]
    return agg.sort_values(["week", "group"]).reset_index(drop=True)[
        ["week", "group", "prevalence", "n_tested", "n_positive", "n_carried", "low_n"]
    ]


def last_status_before_window(microbio_before_window, admission, start=None):
    """For each person with a pre-window test, their most recent status
    (1/0) as of just before the window starts -- a candidate starting
    state for P4's simulation. Not used for calibration."""
    start = pd.Timestamp(start or config.STUDY_START)
    df = microbio_before_window[microbio_before_window["date_prl"] < start].copy()
    ward_of = person_ward_map(admission)
    df["ward_group"] = df["calc_ident"].map(ward_of)
    df = df.sort_values("date_prl")
    last = df.groupby("calc_ident").agg(
        last_status=("sarm", "last"),
        last_test_date=("date_prl", "last"),
        ward_group=("ward_group", "last"),
    ).reset_index()
    return last
