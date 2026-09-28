"""P1 data audit: load the three raw CSVs and report on their shape, quality,
and coverage. Writes results/tables/p1_dataset_report.txt plus a few
supporting CSVs. Never modifies data/raw/.
"""
import numpy as np
import pandas as pd

import config
from src.load import load_admission, load_contacts, load_microbio
from src.wards import map_to_ward_group, person_prefix


def shapes_report(admission, contacts, microbio):
    """Return a small DataFrame with the row/column count of each raw
    table, so the first thing the report shows is 'did everything load'."""
    return pd.DataFrame(
        [
            {"file": "admission.csv", "rows": admission.shape[0], "cols": admission.shape[1]},
            {"file": "mat.day.csv", "rows": contacts.shape[0], "cols": contacts.shape[1]},
            {"file": "microbio.csv", "rows": microbio.shape[0], "cols": microbio.shape[1]},
        ]
    )


def missing_values_report(df, name):
    """Return a DataFrame of the missing-value count per column of df, so
    gaps in the raw data are visible instead of silently propagating."""
    counts = df.isna().sum()
    out = counts.reset_index()
    out.columns = ["column", "n_missing"]
    out.insert(0, "file", name)
    return out


def duplicates_report(admission, contacts, microbio):
    """Count exact full-row duplicates in each table, plus duplicate
    (from, to, day) contact pairs, which would mean the same pair was
    logged twice for one day."""
    contact_key_dupes = contacts.duplicated(subset=["from", "to", "day"]).sum()
    return pd.DataFrame(
        [
            {"file": "admission.csv", "check": "full-row duplicates", "count": int(admission.duplicated().sum())},
            {"file": "mat.day.csv", "check": "full-row duplicates", "count": int(contacts.duplicated().sum())},
            {"file": "mat.day.csv", "check": "duplicate (from,to,day) pairs", "count": int(contact_key_dupes)},
            {"file": "microbio.csv", "check": "full-row duplicates", "count": int(microbio.duplicated().sum())},
        ]
    )


def reciprocity_report(contacts):
    """For each (from, to, day) contact row, check whether the reverse
    (to, from, day) row also exists. Returns the fraction of rows that
    have a same-day reverse partner, which is expected to be close to 1.0
    since contacts are meant to be stored in both directions."""
    pairs = set(zip(contacts["from"], contacts["to"], contacts["day"]))
    reverse_exists = [
        (t, f, d) in pairs for f, t, d in zip(contacts["from"], contacts["to"], contacts["day"])
    ]
    frac = float(np.mean(reverse_exists))
    return frac


def date_ranges_report(contacts, microbio):
    """Return the min/max date for the contact days and for the microbio
    swab dates."""
    return pd.DataFrame(
        [
            {"file": "mat.day.csv", "column": "day", "min": contacts["day"].min(), "max": contacts["day"].max()},
            {"file": "microbio.csv", "column": "date_prl", "min": microbio["date_prl"].min(), "max": microbio["date_prl"].max()},
        ]
    )


def people_counts_report(admission, contacts, microbio):
    """Count people per file, split by PA (patient) / PE (staff), using
    the calc_ident prefix for admission and contacts, and the 'statut'
    column for microbio (cross-checked against its own calc_ident prefix)."""
    rows = []

    adm_prefix = person_prefix(admission["calc_ident"])
    rows.append({"file": "admission.csv", "n_people": admission["calc_ident"].nunique(),
                 "n_PA": int((adm_prefix == "PA").sum()), "n_PE": int((adm_prefix == "PE").sum())})

    contact_people = pd.Index(pd.concat([contacts["from"], contacts["to"]]).unique())
    contact_prefix = person_prefix(pd.Series(contact_people))
    rows.append({"file": "mat.day.csv", "n_people": len(contact_people),
                 "n_PA": int((contact_prefix == "PA").sum()), "n_PE": int((contact_prefix == "PE").sum())})

    mic_people = microbio["calc_ident"].unique()
    mic_by_statut = microbio.drop_duplicates("calc_ident")["statut"].value_counts()
    rows.append({"file": "microbio.csv", "n_people": len(mic_people),
                 "n_PA": int(mic_by_statut.get("PA", 0)), "n_PE": int(mic_by_statut.get("PE", 0))})

    mic_prefix_check = person_prefix(microbio.drop_duplicates("calc_ident")["calc_ident"])
    statut_vs_prefix_mismatches = int(
        (mic_prefix_check.values != microbio.drop_duplicates("calc_ident")["statut"].values).sum()
    )

    return pd.DataFrame(rows), statut_vs_prefix_mismatches, contact_people


def id_overlap_report(admission, contact_people, microbio):
    """Check ID overlap between files: how many contact people and microbio
    people are missing from admission.csv (should be 0 for a clean linkage),
    and how many admission people have zero contacts (the '206 people'
    question)."""
    admission_ids = set(admission["calc_ident"])
    contact_ids = set(contact_people)
    microbio_ids = set(microbio["calc_ident"].unique())

    contacts_not_in_admission = contact_ids - admission_ids
    microbio_not_in_admission = microbio_ids - admission_ids
    admission_with_no_contacts = admission_ids - contact_ids

    summary = pd.DataFrame(
        [
            {"check": "contact people not in admission.csv", "count": len(contacts_not_in_admission)},
            {"check": "microbio people not in admission.csv", "count": len(microbio_not_in_admission)},
            {"check": "admission people with zero contacts", "count": len(admission_with_no_contacts)},
        ]
    )
    return summary, sorted(admission_with_no_contacts)


def missing_contact_days_report(contacts, start, end):
    """Return the list of calendar days in [start, end] that never appear
    in mat.day.csv's 'day' column."""
    full_range = pd.date_range(start=start, end=end, freq="D")
    present_days = set(contacts["day"].unique())
    missing = [d for d in full_range if d not in present_days]
    return pd.DataFrame({"missing_day": missing}), len(full_range), len(present_days)


def contact_length_stats_report(contacts):
    """Return summary statistics (min/max/mean/median/std) of the contact
    'length' column, in seconds."""
    length = contacts["length"]
    return pd.DataFrame(
        [
            {
                "min": length.min(), "max": length.max(), "mean": length.mean(),
                "median": length.median(), "std": length.std(), "n": length.shape[0],
            }
        ]
    )


def weekly_test_coverage_report(admission, microbio):
    """For each ISO week in microbio's date range and each of the 6 locked
    ward groups, compute the fraction of that ward group's people (per
    admission.csv) who were tested that week."""
    admission = admission.copy()
    admission["ward_group"] = map_to_ward_group(admission["service_pa_pe"])
    ward_sizes = admission.groupby("ward_group")["calc_ident"].nunique()

    mic = microbio.copy()
    mic["ward_group"] = map_to_ward_group(mic["service_pa_pe"])
    mic["week"] = mic["date_prl"].dt.to_period("W").apply(lambda p: p.start_time)

    tested_per_week_ward = (
        mic.drop_duplicates(["calc_ident", "week"])
        .groupby(["week", "ward_group"])["calc_ident"]
        .nunique()
        .unstack(fill_value=0)
    )

    coverage = tested_per_week_ward.divide(ward_sizes, axis=1)
    coverage = coverage.reindex(columns=config.WARD_GROUPS)
    return coverage.round(3), ward_sizes


def reference_number_checks(admission, contacts, microbio):
    """Cross-check the 'first inspection' reference numbers recorded in
    CLAUDE.md against numbers computed here, so drift is caught explicitly
    rather than left implicit in the sections above."""
    adm_prefix = person_prefix(admission["calc_ident"])
    contact_people = pd.Index(pd.concat([contacts["from"], contacts["to"]]).unique())
    contact_prefix = person_prefix(pd.Series(contact_people))
    mapped = map_to_ward_group(admission["service_pa_pe"])

    checks = [
        ("admission.csv rows", 795, admission.shape[0]),
        ("admission.csv PA", 452, int((adm_prefix == "PA").sum())),
        ("admission.csv PE", 343, int((adm_prefix == "PE").sum())),
        ("admission.csv distinct service values", 9, admission["service_pa_pe"].nunique()),
        ("mat.day.csv rows", 124924, contacts.shape[0]),
        ("mat.day.csv distinct people", 589, len(contact_people)),
        ("mat.day.csv PA", 329, int((contact_prefix == "PA").sum())),
        ("mat.day.csv PE", 260, int((contact_prefix == "PE").sum())),
        ("mat.day.csv length min", 60, int(contacts["length"].min())),
        ("mat.day.csv length max", 86400, int(contacts["length"].max())),
        ("microbio.csv rows", 6728, microbio.shape[0]),
        ("microbio.csv people", 795, microbio["calc_ident"].nunique()),
        ("microbio.csv PA rows", 3369, int((microbio["statut"] == "PA").sum())),
        ("microbio.csv PE rows", 3359, int((microbio["statut"] == "PE").sum())),
        ("microbio.csv sarm=1 rows", 1118, int((microbio["sarm"] == 1).sum())),
        ("microbio.csv sarm=0 rows", 5610, int((microbio["sarm"] == 0).sum())),
        ("people MRSA-positive at least once", 295, microbio.loc[microbio["sarm"] == 1, "calc_ident"].nunique()),
        ("admission people with no contacts", 206, len(set(admission["calc_ident"]) - set(contact_people))),
        ("ward-group-unmapped admission people", 0, int((mapped == "UNMAPPED").sum())),
    ]
    df = pd.DataFrame(checks, columns=["metric", "expected", "computed"])
    df["match"] = df["expected"] == df["computed"]
    return df


def date_prl_posix_identical_report(microbio):
    """Check whether date_prl and date_prl_posix are identical once both
    are parsed as dates, and count how many rows differ if not."""
    diff_mask = microbio["date_prl"].dt.normalize() != microbio["date_prl_posix"].dt.normalize()
    return bool((~diff_mask).all()), int(diff_mask.sum())


def build_report():
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)

    admission, contacts, microbio = load_admission(config.ADMISSION_CSV), \
        load_contacts(config.CONTACTS_CSV), load_microbio(config.MICROBIO_CSV)

    lines = []

    def emit(text=""):
        lines.append(text)

    emit("P1 DATA AUDIT REPORT")
    emit("=" * 60)
    emit()

    emit("1. SHAPES")
    shapes = shapes_report(admission, contacts, microbio)
    emit(shapes.to_string(index=False))
    emit()

    emit("2. MISSING VALUES")
    for df, name in [(admission, "admission.csv"), (contacts, "mat.day.csv"), (microbio, "microbio.csv")]:
        mv = missing_values_report(df, name)
        emit(mv.to_string(index=False))
    emit()

    emit("3. DUPLICATES")
    dupes = duplicates_report(admission, contacts, microbio)
    emit(dupes.to_string(index=False))
    recip_frac = reciprocity_report(contacts)
    emit(f"mat.day.csv: fraction of rows with a same-day reverse (to,from,day) partner = {recip_frac:.4f}")
    emit()

    emit("4. DATE RANGES")
    dr = date_ranges_report(contacts, microbio)
    emit(dr.to_string(index=False))
    emit()

    emit("5. PEOPLE PER FILE")
    people_counts, statut_mismatches, contact_people = people_counts_report(admission, contacts, microbio)
    emit(people_counts.to_string(index=False))
    emit(f"microbio.csv: rows where 'statut' disagrees with calc_ident prefix = {statut_mismatches}")
    emit()

    emit("6. ID OVERLAP BETWEEN FILES")
    overlap_summary, no_contact_ids = id_overlap_report(admission, contact_people, microbio)
    emit(overlap_summary.to_string(index=False))
    emit()

    emit("7. MISSING CONTACT DAYS")
    missing_days_df, n_full_range, n_present = missing_contact_days_report(
        contacts, config.STUDY_START, config.STUDY_END
    )
    emit(f"Study window {config.STUDY_START} to {config.STUDY_END}: "
         f"{n_full_range} calendar days, {n_present} distinct days present in mat.day.csv, "
         f"{len(missing_days_df)} missing.")
    if len(missing_days_df):
        emit("Missing days:")
        emit(missing_days_df["missing_day"].dt.strftime("%Y-%m-%d").to_string(index=False))
    emit()

    emit("8. WEEKLY TEST COVERAGE PER WARD GROUP")
    coverage, ward_sizes = weekly_test_coverage_report(admission, microbio)
    emit("Ward group sizes (admission.csv):")
    emit(ward_sizes.reindex(config.WARD_GROUPS).to_string())
    emit("Coverage = distinct people tested that week / ward group size:")
    emit(coverage.to_string())
    emit()

    emit("9. PEOPLE WITH NO CONTACTS")
    emit(f"admission.csv people with zero rows in mat.day.csv: {len(no_contact_ids)}")
    emit()

    emit("10. CONTACT-LENGTH STATISTICS (seconds)")
    length_stats = contact_length_stats_report(contacts)
    emit(length_stats.to_string(index=False))
    emit()

    emit("11. date_prl vs date_prl_posix")
    identical, n_diff = date_prl_posix_identical_report(microbio)
    emit(f"Identical for all rows (as dates): {identical} (rows differing: {n_diff})")
    emit()

    emit("12. REFERENCE NUMBER CROSS-CHECK (vs CLAUDE.md 'first inspection' numbers)")
    ref_checks = reference_number_checks(admission, contacts, microbio)
    emit(ref_checks.to_string(index=False))
    emit(f"All reference numbers match: {bool(ref_checks['match'].all())}")
    emit()

    report_text = "\n".join(str(l) for l in lines)
    (config.RESULTS_TABLES_DIR / "p1_dataset_report.txt").write_text(report_text, encoding="utf-8")

    missing_days_df.to_csv(config.RESULTS_TABLES_DIR / "p1_missing_contact_days.csv", index=False)
    coverage.to_csv(config.RESULTS_TABLES_DIR / "p1_weekly_test_coverage.csv")
    length_stats.to_csv(config.RESULTS_TABLES_DIR / "p1_contact_length_stats.csv", index=False)
    pd.DataFrame({"calc_ident": no_contact_ids}).to_csv(
        config.RESULTS_TABLES_DIR / "p1_people_no_contacts.csv", index=False
    )
    ref_checks.to_csv(config.RESULTS_TABLES_DIR / "p1_reference_number_checks.csv", index=False)

    print(report_text)
    return report_text


if __name__ == "__main__":
    build_report()
