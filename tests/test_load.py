"""Tests for src/load.py: shapes, columns, and an independent (csv-module)
row-count cross-check against the pandas loaders."""
import csv

import config
from src.load import load_admission, load_contacts, load_microbio


def _csv_module_row_count(path):
    """Count data rows using the stdlib csv module, independent of pandas,
    as a second method to cross-check pandas' row counts against."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        next(reader)  # header
        return sum(1 for _ in reader)


def test_admission_shape_and_columns():
    df = load_admission(config.ADMISSION_CSV)
    assert df.shape == (795, 2)
    assert list(df.columns) == ["calc_ident", "service_pa_pe"]


def test_contacts_shape_and_columns():
    df = load_contacts(config.CONTACTS_CSV)
    assert df.shape == (124924, 4)
    assert list(df.columns) == ["from", "to", "day", "length"]


def test_microbio_shape_and_columns():
    df = load_microbio(config.MICROBIO_CSV)
    assert df.shape == (6728, 14)
    assert "sarm" in df.columns


def test_row_counts_match_csv_module():
    """Independent cross-check: pandas row count must equal a plain csv
    module row count for each raw file."""
    assert load_admission(config.ADMISSION_CSV).shape[0] == _csv_module_row_count(config.ADMISSION_CSV)
    assert load_contacts(config.CONTACTS_CSV).shape[0] == _csv_module_row_count(config.CONTACTS_CSV)
    assert load_microbio(config.MICROBIO_CSV).shape[0] == _csv_module_row_count(config.MICROBIO_CSV)


def test_date_prl_posix_matches_date_prl():
    df = load_microbio(config.MICROBIO_CSV)
    assert (df["date_prl"].dt.normalize() == df["date_prl_posix"].dt.normalize()).all()


def test_no_missing_values_in_key_columns():
    admission = load_admission(config.ADMISSION_CSV)
    contacts = load_contacts(config.CONTACTS_CSV)
    microbio = load_microbio(config.MICROBIO_CSV)
    assert admission[["calc_ident", "service_pa_pe"]].isna().sum().sum() == 0
    assert contacts[["from", "to", "day", "length"]].isna().sum().sum() == 0
    assert microbio[["calc_ident", "sarm"]].isna().sum().sum() == 0
