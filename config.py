"""Project-wide constants. No magic numbers outside this file."""
from pathlib import Path

import numpy as np

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

# --- P4: SIS simulation + calibration ---
N_WEEKS = 17  # weeks 0-16, Monday-anchored (src/network.py assign_week)
CALIBRATION_WEEKS = list(range(0, 12))  # weeks 0-11
HOLDOUT_WEEKS = list(range(12, 17))  # weeks 12-16, sanity check only, never tuned on

# Starting grid, widened after review (Nov 14): the first grid (beta from
# 1e-3, gamma from 5e-3, one widening round) left gamma on its lower edge,
# so the reported "optimum" was only a grid boundary. The grid now spans
# 3 orders of magnitude in beta and gamma, and widening repeats (up to
# CALIBRATION_MAX_WIDEN_ROUNDS) until the best point is interior.
BETA_GRID = list(np.geomspace(1e-4, 5e-2, 10))  # per contact-hour
GAMMA_GRID = list(np.geomspace(1e-4, 0.1, 10))  # per day
EPSILON_GRID = list(np.geomspace(1e-4, 5e-3, 5))  # per day
N_CALIBRATION_REPLICATES = 20  # same seeds at every grid point (common random numbers)
CALIBRATION_MAX_WIDEN_ROUNDS = 3  # repeat 3x widening of an edge axis at most this many times
CALIBRATION_WIDEN_FACTOR = 3.0
# Near-optimal set: grid points whose loss is within this fraction of the
# best loss. Used to report an identifiability interval per parameter
# (profile loss), instead of a single point estimate on a flat ridge.
CALIBRATION_NEAR_OPTIMAL_TOL = 0.05

N_TRAINING_TRAJECTORIES = 300
TRAJECTORY_SCENARIOS = ["endemic", "outbreak"]  # split 50/50
OUTBREAK_SEED_RANGE = (1, 3)  # 1-3 seeded cases in one ward
TRAJECTORY_PARAM_MULTIPLIER_RANGE = (0.5, 2.0)  # beta, gamma varied around calibrated values
ENDEMIC_PREVALENCE_MULTIPLIER_RANGE = (0.5, 1.5)  # applied to each group's real prevalence

DEFAULT_SIMULATION_POPULATION = "all"  # "all" (589, 6 groups) or "patients_only" (329, 5 wards; deferred to E6)

# --- P6: EDMD fit ---
EDMD_LAMBDA_GRID = list(np.geomspace(1e-6, 1e3, 20))
EDMD_MAX_HORIZON = 4  # lambda selected on mean RMSE over h=1..4, not just h=1
EDMD_DICTIONARIES = ["D1", "D2", "D3"]

# --- P7 add-on (Nov 14 review): Koopman influence score, src/influence.py ---
KOOPMAN_INFLUENCE_N_SEED = 3  # extra colonized people seeded in one ward (matches OUTBREAK_SEED_RANGE max)
KOOPMAN_INFLUENCE_HORIZON = N_WEEKS - 1  # weeks rolled forward (16, the length of the real window)

# --- P8 add-on (Nov 14 review): forecast significance ---
CI_LEVEL = 0.95
P8_BOOTSTRAP_N = 10000  # block bootstrap resamples (blocks = forecast start weeks)

# --- P9 add-on (Nov 14 review): non-circular ground truth ---
# The locked ground truth (decision 14) cuts each ward's contacts by 50%,
# so a ward with more contact-hours loses more hours; degree centrality
# then matches it almost by construction. The second ground truth removes
# the SAME number of contact-hours from every ward: this fraction of the
# smallest ward's touching contact volume.
P9_EQUAL_HOURS_FRACTION_OF_MIN = 0.5

# --- P10: intervention simulation ---
INTERVENTION_K_VALUES = [1, 2]  # number of targeted wards
INTERVENTION_REDUCTIONS = [0.25, 0.50, 0.75]  # per-targeted-ward contact reduction
INTERVENTION_N_REPLICATES = 200  # common random numbers across every strategy/config
INTERVENTION_TARGETED_STRATEGIES = ["random", "degree_targeted"] + [
    f"koopman_targeted_{d}" for d in EDMD_DICTIONARIES  # dominant-mode share (original P7 score)
] + [f"koopman_influence_targeted_{d}" for d in EDMD_DICTIONARIES]  # influence score (Nov 14 review)

# --- P11: robustness experiments E1-E8 ---
# CLAUDE.md names this phase "robustness experiments E1-E8" without
# defining them -- unlike P1-P10's locked decisions. Designed here to
# directly probe the soft spots this project has already flagged in its
# own research_log.md / CLAUDE.md's known limitations, logged in full.
ROBUSTNESS_N_REPLICATES = 100  # standard replicate count for E1, E4, E5, E6 (matches P9)
ROBUSTNESS_ALT_SEED = 20261225  # E1: a different global seed
ROBUSTNESS_REPLICATE_COUNTS = [30, 300]  # E3: vs P9's standard 100
ROBUSTNESS_LAMBDA_MULTIPLIERS = [0.1, 10.0]  # E2: vs each dictionary's P6-selected lambda
# E9 (second review, Nov 14): rerun P4-P10 at every near-optimal gamma on
# the calibration ridge (src/ridge_sensitivity.py). P10 is rerun only for
# these (k, R) cells to keep the cost down: the smallest-k mid cut and the
# largest budget.
E9_INTERVENTION_CELLS = [(1, 0.50), (2, 0.75)]
