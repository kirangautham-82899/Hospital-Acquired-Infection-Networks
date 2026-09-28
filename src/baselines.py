"""P8: two real-data baselines named in the locked plan's baseline list
(content -- see research_log.md for the numbering caveat vs Part A) that
don't exist yet: a network-exposure linear model and a ward-level
(mean-field) SIS model. Both are fit on REAL data, restricted to the
calibration weeks (config.CALIBRATION_WEEKS) -- unlike the EDMD
dictionaries (D1/D2/D3), which are fit only on the 300 simulated
trajectories and never touch real data during fitting at all.

Fitting protocol, shared by both: build (x_t, x_{t+1}) pairs across the
calibration weeks, where x_t is a COMPLETE state (P5's real_state_fill:
real value preferred, carry-forward fallback, never defaulting to 0/
susceptible) and the regression TARGET is restricted to genuinely-
observed cells (P5's observed_for_scoring_mask, n_tested >= 10) -- never
fitting against a carry-forward-derived pseudo-observation, which would
just be circular (carry-forward repeats old information, it isn't new
signal to learn dynamics from).

Unlike P6's EDMD fit (300 trajectories x 16 transitions = 4,800+ training
pairs, a proper train/val/test split, and a 20-point lambda grid search),
these baselines have only ~11 real consecutive-week pairs to fit on. A
full grid search here would be fitting noise, not signal -- this scarcity
is exactly why the Koopman operator itself is never fit on real data at
all (P4-P6). A small FIXED ridge penalty is used for the network-exposure
model for numerical stability, not tuned; the ward-SIS model has only 2
parameters and is fit by plain least squares.
"""
import numpy as np

import config
from src.edmd import ridge_fit
from src.real_state_fill import fill_state_vector, observed_for_scoring_mask, state_is_usable_as_starting_point

REAL_BASELINE_RIDGE = 1.0  # fixed, not grid-searched -- see module docstring


def build_real_weekly_states(states_real, states_carry_forward, groups, weeks=None):
    """{week: (state [n_groups] with NaN where unfillable, observed
    [n_groups] bool)} for every week in `weeks` (default: all of
    config.N_WEEKS), via P5's fill_state_vector."""
    weeks = range(config.N_WEEKS) if weeks is None else weeks
    return {w: fill_state_vector(w, states_real, states_carry_forward, groups) for w in weeks}


def build_training_pairs(weekly_states, states_real, groups, weeks, min_n_tested=10):
    """One row per (week, ward) target that is genuinely observed at
    week+1, for week in `weeks`; skipped if week's own state isn't fully
    usable. Returns a list of {week, ward_idx, x, x_next} dicts."""
    rows = []
    for w in weeks:
        if w + 1 not in weekly_states:
            continue
        x, _ = weekly_states[w]
        if not state_is_usable_as_starting_point(x):
            continue
        mask = observed_for_scoring_mask(w + 1, states_real, groups, min_n_tested)
        x_next, _ = weekly_states[w + 1]
        for gi, ok in enumerate(mask):
            if ok:
                rows.append({"week": w, "ward_idx": gi, "x": x, "x_next": x_next[gi]})
    return rows


# ---------------------------------------------------- network-exposure ----

def fit_network_exposure_model(pairs, W, lam=REAL_BASELINE_RIDGE):
    """x_{t+1,i} ~= a + b*x_{t,i} + c*(Wx_t)_i, one shared 3-parameter
    model pooled across all (week, ward) training pairs. Returns
    [a, b, c]."""
    X_rows, y_rows = [], []
    for p in pairs:
        x, i = p["x"], p["ward_idx"]
        wx_i = float(W[i] @ x)
        X_rows.append([1.0, x[i], wx_i])
        y_rows.append(p["x_next"])
    X, y = np.array(X_rows), np.array(y_rows)
    coef = ridge_fit(X, y[:, None], lam=lam, const_index=0).ravel()
    return coef


def predict_network_exposure(coef, x, W):
    """Vectorized one-step prediction for every ward: a + b*x + c*(Wx)."""
    a, b, c = coef
    return a + b * x + c * (W @ x)


# --------------------------------------------------------- ward-level SIS ----

def fit_ward_sis_model(pairs, W):
    """Mean-field ward-level SIS update:
    x_{t+1,i} - x_{t,i} = beta*(1-x_{t,i})*(Wx_t)_i - gamma*x_{t,i}.
    Linear in (beta, gamma) given x, fit by plain least squares (2
    parameters, ~dozens of training pairs -- no regularization needed).
    Returns (beta, gamma)."""
    X_rows, y_rows = [], []
    for p in pairs:
        x, i = p["x"], p["ward_idx"]
        wx_i = float(W[i] @ x)
        X_rows.append([(1 - x[i]) * wx_i, -x[i]])
        y_rows.append(p["x_next"] - x[i])
    X, y = np.array(X_rows), np.array(y_rows)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    beta, gamma = coef
    return float(beta), float(gamma)


def predict_ward_sis(beta, gamma, x, W):
    """Vectorized one-step prediction for every ward."""
    Wx = W @ x
    return x + beta * (1 - x) * Wx - gamma * x
