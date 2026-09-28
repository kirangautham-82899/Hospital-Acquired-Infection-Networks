"""Asserts every number listed under 'Reference numbers from a first
inspection' in CLAUDE.md against the loaded raw data. These are read-only
checks against src/load.py (not modified here). Per instructions, if a
number does not match, this file is NOT edited to make it pass -- the
mismatch must be reported instead.
"""
import pandas as pd
import pytest

import config
from src.audit import map_to_ward_group, person_prefix
from src.load import load_admission, load_contacts, load_microbio


@pytest.fixture(scope="module")
def admission():
    return load_admission(config.ADMISSION_CSV)


@pytest.fixture(scope="module")
def contacts():
    return load_contacts(config.CONTACTS_CSV)


@pytest.fixture(scope="module")
def microbio():
    return load_microbio(config.MICROBIO_CSV)


# ---- admission.csv: "795 rows; 452 PA, 343 PE; 9 distinct service values;
# no person appears twice (no transfer information)." ----

def test_admission_row_count(admission):
    assert admission.shape[0] == 795


def test_admission_pa_pe_counts(admission):
    prefix = person_prefix(admission["calc_ident"])
    assert (prefix == "PA").sum() == 452
    assert (prefix == "PE").sum() == 343


def test_admission_distinct_service_values(admission):
    assert admission["service_pa_pe"].nunique() == 9


def test_admission_no_person_appears_twice(admission):
    assert admission["calc_ident"].duplicated().sum() == 0


# ---- mat.day.csv: "124,924 rows; 110 distinct days between 2009-07-01 and
# 2009-10-25 (span is 117 days, so 7 days missing); 589 distinct people
# (329 PA, 260 PE); 19,974 unique undirected pairs; about 99.9% of rows have
# a reverse row on the same day; length min 60, max 86400, mean about 3886."
# ----

def test_contacts_row_count(contacts):
    assert contacts.shape[0] == 124924


def test_contacts_distinct_days_and_missing_days(contacts):
    full_range = pd.date_range(config.STUDY_START, config.STUDY_END, freq="D")
    assert len(full_range) == 117
    n_present = contacts["day"].nunique()
    assert n_present == 110
    assert (len(full_range) - n_present) == 7


def test_contacts_distinct_people_and_pa_pe(contacts):
    people = pd.Index(pd.concat([contacts["from"], contacts["to"]]).unique())
    assert len(people) == 589
    prefix = person_prefix(pd.Series(people))
    assert (prefix == "PA").sum() == 329
    assert (prefix == "PE").sum() == 260


def test_contacts_unique_undirected_pairs(contacts):
    pairs = {frozenset((a, b)) for a, b in zip(contacts["from"], contacts["to"])}
    assert len(pairs) == 19974


def test_contacts_reciprocity_about_99_9_percent(contacts):
    pairs = set(zip(contacts["from"], contacts["to"], contacts["day"]))
    has_reverse = [
        (t, f, d) in pairs for f, t, d in zip(contacts["from"], contacts["to"], contacts["day"])
    ]
    frac = sum(has_reverse) / len(has_reverse)
    assert 0.995 <= frac <= 1.0, f"reciprocity {frac:.4f} not within 'about 99.9%'"


def test_contacts_length_stats(contacts):
    length = contacts["length"]
    assert length.min() == 60
    assert length.max() == 86400
    assert 3886 - 5 <= length.mean() <= 3886 + 5


# ---- microbio.csv: "6,728 rows; 795 people; 3,369 PA rows and 3,359 PE
# rows; sarm=1 in 1,118 rows and sarm=0 in 5,610 rows; dates 2009-05-04 to
# 2009-10-27; 295 people MRSA-positive at least once; tests fall on Mon-Thu,
# about weekly." ----

def test_microbio_row_count(microbio):
    assert microbio.shape[0] == 6728


def test_microbio_people_count(microbio):
    assert microbio["calc_ident"].nunique() == 795


def test_microbio_pa_pe_row_counts(microbio):
    assert (microbio["statut"] == "PA").sum() == 3369
    assert (microbio["statut"] == "PE").sum() == 3359


def test_microbio_sarm_counts(microbio):
    assert (microbio["sarm"] == 1).sum() == 1118
    assert (microbio["sarm"] == 0).sum() == 5610


def test_microbio_date_range(microbio):
    assert microbio["date_prl"].min() == pd.Timestamp("2009-05-04")
    assert microbio["date_prl"].max() == pd.Timestamp("2009-10-27")


def test_microbio_mrsa_positive_people_count(microbio):
    assert microbio.loc[microbio["sarm"] == 1, "calc_ident"].nunique() == 295


def test_microbio_tests_fall_on_mon_thu(microbio):
    weekdays = set(microbio["date_prl"].dt.day_name().unique())
    assert weekdays <= {"Monday", "Tuesday", "Wednesday", "Thursday"}, (
        f"tests occur on unexpected weekdays: {weekdays - {'Monday', 'Tuesday', 'Wednesday', 'Thursday'}}"
    )


# ---- "206 people are in admission.csv but have no contacts; every contact
# person is in admission.csv; every microbio person is in admission.csv." ----

def test_206_people_have_no_contacts(admission, contacts):
    admission_ids = set(admission["calc_ident"])
    contact_ids = set(contacts["from"]) | set(contacts["to"])
    assert len(admission_ids - contact_ids) == 206


def test_every_contact_person_in_admission(admission, contacts):
    admission_ids = set(admission["calc_ident"])
    contact_ids = set(contacts["from"]) | set(contacts["to"])
    assert contact_ids <= admission_ids


def test_every_microbio_person_in_admission(admission, microbio):
    admission_ids = set(admission["calc_ident"])
    microbio_ids = set(microbio["calc_ident"].unique())
    assert microbio_ids <= admission_ids


# ---- Bonus: 6-group mapping used throughout CLAUDE.md's locked decisions
# should account for all 9 admission service values with none left over. ----

def test_service_values_map_onto_6_groups_cleanly(admission):
    mapped = map_to_ward_group(admission["service_pa_pe"])
    assert (mapped != "UNMAPPED").all()
    assert set(mapped.unique()) == set(config.WARD_GROUPS)
