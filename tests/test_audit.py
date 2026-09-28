"""Tests for src/audit.py: the derived numbers reported by the P1 audit,
checked against the reference numbers recorded in CLAUDE.md."""
import config
from src.load import load_admission, load_contacts, load_microbio
from src.audit import (
    id_overlap_report,
    missing_contact_days_report,
    people_counts_report,
    reciprocity_report,
    reference_number_checks,
)
from src.wards import map_to_ward_group


def _load_all():
    return (
        load_admission(config.ADMISSION_CSV),
        load_contacts(config.CONTACTS_CSV),
        load_microbio(config.MICROBIO_CSV),
    )


def test_people_counts_match_reference():
    admission, contacts, microbio = _load_all()
    counts, statut_mismatches, contact_people = people_counts_report(admission, contacts, microbio)
    counts = counts.set_index("file")
    assert counts.loc["admission.csv", ["n_people", "n_PA", "n_PE"]].tolist() == [795, 452, 343]
    assert counts.loc["mat.day.csv", ["n_people", "n_PA", "n_PE"]].tolist() == [589, 329, 260]
    assert statut_mismatches == 0


def test_no_contact_people_count_is_206():
    admission, contacts, microbio = _load_all()
    _, _, contact_people = people_counts_report(admission, contacts, microbio)
    overlap_summary, no_contact_ids = id_overlap_report(admission, contact_people, microbio)
    assert len(no_contact_ids) == 206
    row = overlap_summary.set_index("check")
    assert row.loc["contact people not in admission.csv", "count"] == 0
    assert row.loc["microbio people not in admission.csv", "count"] == 0


def test_missing_contact_days_count_is_7():
    _, contacts, _ = _load_all()
    missing_days_df, n_full_range, n_present = missing_contact_days_report(
        contacts, config.STUDY_START, config.STUDY_END
    )
    assert n_full_range == 117
    assert n_present == 110
    assert len(missing_days_df) == 7


def test_reciprocity_is_near_one():
    _, contacts, _ = _load_all()
    frac = reciprocity_report(contacts)
    assert 0.99 < frac <= 1.0


def test_ward_group_mapping_covers_all_service_values():
    admission, _, _ = _load_all()
    mapped = map_to_ward_group(admission["service_pa_pe"])
    assert (mapped != "UNMAPPED").all()
    assert set(mapped.unique()) == set(config.WARD_GROUPS)


def test_all_reference_numbers_match():
    admission, contacts, microbio = _load_all()
    checks = reference_number_checks(admission, contacts, microbio)
    mismatches = checks[~checks["match"]]
    assert mismatches.empty, f"Reference number mismatches:\n{mismatches.to_string(index=False)}"
