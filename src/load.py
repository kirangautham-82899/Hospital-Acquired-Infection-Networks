"""Loaders for the three raw I-Bird CSVs in data/raw/.

Each file has an unnamed leading row-number column (the header row has one
fewer field than the data rows), so all three are read with index_col=0.
The raw files are never modified.
"""
import pandas as pd

ADMISSION_COLUMNS = ["calc_ident", "service_pa_pe"]
CONTACTS_COLUMNS = ["from", "to", "day", "length"]
MICROBIO_COLUMNS = [
    "calc_ident", "statut", "date_prl", "date_prl_posix", "ndem", "same",
    "sa", "sasm", "sarm", "germe", "service_pa_pe", "age", "sexe", "strain",
]


def _read_semicolon_csv(path):
    """Read one of the raw files with ';' as separator and the leading
    unnamed column as the index."""
    return pd.read_csv(path, sep=";", index_col=0)


def load_admission(path):
    """Load admission.csv: one row per person, with their calc_ident (e.g.
    'PA-001-LAM') and their ward/group (service_pa_pe). Asserts the columns
    have not shifted before returning."""
    df = _read_semicolon_csv(path)
    assert list(df.columns) == ADMISSION_COLUMNS, (
        f"admission.csv columns shifted: {list(df.columns)}"
    )
    return df


def load_contacts(path):
    """Load mat.day.csv: one row per (from, to, day) contact, with the
    contact length in seconds. Parses 'day' to a real datetime and asserts
    the columns have not shifted before returning."""
    df = _read_semicolon_csv(path)
    assert list(df.columns) == CONTACTS_COLUMNS, (
        f"mat.day.csv columns shifted: {list(df.columns)}"
    )
    df["day"] = pd.to_datetime(df["day"])
    return df


def load_microbio(path):
    """Load microbio.csv: one row per nasal swab test, with the MRSA/MSSA
    result flags (sa, sasm, sarm) and both date columns parsed to real
    datetimes. Asserts the columns have not shifted before returning."""
    df = _read_semicolon_csv(path)
    assert list(df.columns) == MICROBIO_COLUMNS, (
        f"microbio.csv columns shifted: {list(df.columns)}"
    )
    df["date_prl"] = pd.to_datetime(df["date_prl"])
    df["date_prl_posix"] = pd.to_datetime(df["date_prl_posix"])
    return df


def load_all(admission_path, contacts_path, microbio_path):
    """Convenience wrapper: load all three files and return them as a
    (admission, contacts, microbio) tuple of DataFrames."""
    admission = load_admission(admission_path)
    contacts = load_contacts(contacts_path)
    microbio = load_microbio(microbio_path)
    return admission, contacts, microbio
