"""Project-wide constants. No magic numbers outside this file."""
from pathlib import Path

SEED = 42

ROOT_DIR = Path(__file__).resolve().parent
DATA_RAW_DIR = ROOT_DIR / "data" / "raw"
DATA_PROCESSED_DIR = ROOT_DIR / "data" / "processed"
RESULTS_FIGURES_DIR = ROOT_DIR / "results" / "figures"
RESULTS_TABLES_DIR = ROOT_DIR / "results" / "tables"
RESULTS_MODELS_DIR = ROOT_DIR / "results" / "models"

ADMISSION_CSV = DATA_RAW_DIR / "admission.csv"
CONTACTS_CSV = DATA_RAW_DIR / "mat.day.csv"
MICROBIO_CSV = DATA_RAW_DIR / "microbio.csv"

# Nominal study window for the contact data (see research_log.md).
STUDY_START = "2009-07-01"
STUDY_END = "2009-10-25"

WARD_GROUPS = ["Menard 1", "Menard 2", "Sorrel 0", "Sorrel 1", "Sorrel 2", "Other"]
OTHER_SERVICES = ["Autre", "Garde de nuit", "Kine", "Ergo"]
