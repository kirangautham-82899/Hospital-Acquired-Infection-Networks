"""P6: ridge-regularized EDMD, written in numpy (no external Koopman
library -- decision content, see research_log.md for numbering caveats).
Fits K such that phi(x_{t+1}) ~= K phi(x_t) for each dictionary (D1/D2/D3
from P5), using only TRAINING-split trajectories (data/processed/
trajectory_split.csv from P5 -- never re-derived here).

D3 caveat, confirmed analytically (see research_log.md): for a fixed,
invertible W, every D3 feature is an exact linear combination of D2's
features -- Wx is linear in x, so it adds zero new rank beyond x (W is
invertible here, verified: all 6 eigenvalues nonzero); x*(Wx) is a fixed
linear combination of D2's existing square/cross terms. D3 therefore sits
entirely inside D2's span (effective rank <= 19 of its 25 raw columns) --
it is NOT a source of new expressiveness. Language throughout this
project should say D3 "tests whether a contact-structured prior helps
generalization", never "D3 injects network information".

Constant-feature convention: every dictionary's feature 0 is the constant
1 (src/observables.py). It is never centered/scaled, and never penalized
by the ridge regularizer (an intercept-like term should be free).
"""
import numpy as np
import pandas as pd

CONST_INDEX = 0


# ---------------------------------------------------------------- pairs ----

def build_pairs_within_trajectory(features, trajectory_ids, split_df, split_name):
    """Build one-step (X, Y) snapshot pairs from a lifted
    [n_rows, n_weeks, n_features] array, restricted to the trajectories
    tagged `split_name` in split_df. NEVER pairs across a trajectory
    boundary: week 16 of one trajectory is never paired with week 0 of
    another -- pairs are built independently per trajectory, then
    concatenated.

    trajectory_ids[row_i] is the trajectory id that features[row_i]
    belongs to. Returns X [n_pairs, n_features], Y [n_pairs, n_features],
    traj_id_per_pair [n_pairs] (which trajectory each pair came from, for
    later per-scenario breakdowns and for testing the no-crossing
    property).
    """
    keep_ids = set(split_df.loc[split_df["split"] == split_name, "trajectory"].tolist())
    Xs, Ys, tids = [], [], []
    for row_i, tid in enumerate(trajectory_ids):
        if tid not in keep_ids:
            continue
        traj = features[row_i]  # [n_weeks, n_features]
        Xs.append(traj[:-1])
        Ys.append(traj[1:])
        tids.extend([tid] * (traj.shape[0] - 1))
    X = np.concatenate(Xs, axis=0)
    Y = np.concatenate(Ys, axis=0)
    return X, Y, np.array(tids)


def gather_rolling_starts(trajectory_ids, split_df, split_name, max_h, n_weeks):
    """Return (row_indices, t_starts) for every valid (trajectory-row, t)
    combination in the given split, where t ranges so t+max_h stays
    within [0, n_weeks-1]. Used for multi-horizon forecast evaluation."""
    keep_ids = set(split_df.loc[split_df["split"] == split_name, "trajectory"].tolist())
    rows = [i for i, tid in enumerate(trajectory_ids) if tid in keep_ids]
    t_max_start = n_weeks - 1 - max_h
    row_list, t_list = [], []
    for row_i in rows:
        for t in range(0, t_max_start + 1):
            row_list.append(row_i)
            t_list.append(t)
    return np.array(row_list), np.array(t_list)


# --------------------------------------------------------------- scaler ----

class ConstantAwareScaler:
    """Standardizes every feature EXCEPT the one at const_index, which is
    left exactly as 1 (never centered/scaled). Fit on training data only;
    mean_/scale_ are stored so predictions can be un-scaled back to
    original units later (P7 needs this to interpret eigenvectors)."""

    def __init__(self, const_index=CONST_INDEX):
        self.const_index = const_index
        self.mean_ = None
        self.scale_ = None

    def fit(self, X):
        X = np.asarray(X, dtype=float)
        mean = X.mean(axis=0)
        scale = X.std(axis=0)
        mean[self.const_index] = 0.0
        scale[self.const_index] = 1.0
        scale[scale < 1e-12] = 1.0  # guard against a zero-variance non-constant feature
        self.mean_, self.scale_ = mean, scale
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=float)
        out = (X - self.mean_) / self.scale_
        out[..., self.const_index] = 1.0
        return out

    def fit_transform(self, X):
        return self.fit(X).transform(X)

    def inverse_transform(self, X):
        X = np.asarray(X, dtype=float)
        out = X * self.scale_ + self.mean_
        out[..., self.const_index] = 1.0
        return out

    def inverse_transform_indices(self, X_subset, indices):
        """Un-scale only specific feature columns (e.g. the x_<group>
        block selected by the readout C), given their SCALED values."""
        return X_subset * self.scale_[indices] + self.mean_[indices]


# ------------------------------------------------------------ ridge fit ----

def ridge_fit(X, Y, lam, const_index=CONST_INDEX):
    """Ridge-regularized K such that Y ~= X @ K.T (equivalently, for a
    single sample as a column vector, y ~= K @ x). Solved via lstsq on the
    augmented system (never forms an explicit (X^T X + lambda I)^-1,
    which would be numerically dangerous given D3's near-singularity).
    The feature at const_index is NOT penalized."""
    n_features = X.shape[1]
    penalty_diag = np.ones(n_features)
    penalty_diag[const_index] = 0.0
    P = np.sqrt(lam) * np.diag(penalty_diag)

    X_aug = np.vstack([X, P])
    Y_aug = np.vstack([Y, np.zeros((n_features, Y.shape[1]))])

    K_T, *_ = np.linalg.lstsq(X_aug, Y_aug, rcond=None)
    return K_T.T


# ------------------------------------------------------------- readout ----

def selector_matrix(feature_names, group_names):
    """C [len(group_names), len(feature_names)]: 0/1 matrix such that
    C @ phi(x) == x exactly (every dictionary includes x_<group> as a
    literal feature -- 'identity included')."""
    C = np.zeros((len(group_names), len(feature_names)))
    for i, g in enumerate(group_names):
        j = feature_names.index(f"x_{g}")
        C[i, j] = 1.0
    return C


# ------------------------------------------------------------ forecasts ----

def forecast_horizons(K, phi_x0_batch, max_h):
    """Given a batch of starting lifted states [n_samples, n_features]
    (already in K's operating space -- i.e. scaled), return
    {h: predictions [n_samples, n_features]} for h=1..max_h, via repeated
    application of K."""
    preds = {}
    current = phi_x0_batch
    for h in range(1, max_h + 1):
        current = current @ K.T
        preds[h] = current
    return preds


def apply_k_power(K, phi_x, h):
    """K^h @ phi_x for a single lifted state vector (1D). Mainly for
    testing / eigen-analysis; forecast_horizons is the vectorized
    workhorse used for evaluation."""
    out = np.asarray(phi_x, dtype=float)
    for _ in range(h):
        out = K @ out
    return out


# --------------------------------------------------------- spectral info ----

def spectral_radius(K):
    return float(np.max(np.abs(np.linalg.eigvals(K))))


def eigenvalues_outside_unit_circle(K):
    eigvals = np.linalg.eigvals(K)
    return eigvals, eigvals[np.abs(eigvals) > 1.0]


# ------------------------------------------------------ forecast scoring ----

def evaluate_forecast(K, scaler, group_indices, features, trajectory_ids, split_df, split_name, max_h, n_weeks):
    """Roll K forward from every valid (trajectory, t) start in the given
    split, for h=1..max_h. Returns a list of dicts (one per h):
    {h, pred [n,g] raw state units, actual [n,g] raw state units,
    traj_id [n]}. Error is scored in ORIGINAL PREVALENCE units via the
    readout (group_indices = selector C's column positions), not on the
    raw lifted vector, per research_log.md."""
    rows, t_starts = gather_rolling_starts(trajectory_ids, split_df, split_name, max_h, n_weeks)
    phi_x0_raw = features[rows, t_starts, :]
    phi_x0_scaled = scaler.transform(phi_x0_raw)

    results = []
    current_scaled = phi_x0_scaled
    for h in range(1, max_h + 1):
        current_scaled = current_scaled @ K.T
        pred_scaled = current_scaled[:, group_indices]
        pred_raw = scaler.inverse_transform_indices(pred_scaled, group_indices)
        actual_raw = features[rows, t_starts + h, :][:, group_indices]
        results.append({"h": h, "pred": pred_raw, "actual": actual_raw, "traj_id": trajectory_ids[rows]})
    return results


def persistence_forecast(features, trajectory_ids, split_df, split_name, group_indices, max_h, n_weeks):
    """Baseline: predict x_{t+h} = x_t for all h."""
    rows, t_starts = gather_rolling_starts(trajectory_ids, split_df, split_name, max_h, n_weeks)
    x0 = features[rows, t_starts, :][:, group_indices]
    results = []
    for h in range(1, max_h + 1):
        actual = features[rows, t_starts + h, :][:, group_indices]
        results.append({"h": h, "pred": x0, "actual": actual, "traj_id": trajectory_ids[rows]})
    return results


def training_mean_forecast(train_mean_vector, features, trajectory_ids, split_df, split_name, group_indices, max_h, n_weeks):
    """Baseline: predict the training split's overall mean prevalence per
    group, regardless of t or h."""
    rows, t_starts = gather_rolling_starts(trajectory_ids, split_df, split_name, max_h, n_weeks)
    pred = np.tile(train_mean_vector, (len(rows), 1))
    results = []
    for h in range(1, max_h + 1):
        actual = features[rows, t_starts + h, :][:, group_indices]
        results.append({"h": h, "pred": pred, "actual": actual, "traj_id": trajectory_ids[rows]})
    return results


def compute_metrics_table(results, traj_scenario_map, group_names, model_name):
    """results: list of {h, pred[n,g], actual[n,g], traj_id[n]} (one
    entry per horizon). Returns a long DataFrame: model, h, ward,
    scenario, n, rmse, mae, rmse_clipped, mae_clipped -- ward is either a
    group name or 'overall'; scenario is 'endemic', 'outbreak', or
    'overall'."""
    rows_out = []
    for r in results:
        h, pred, actual, traj_id = r["h"], r["pred"], r["actual"], r["traj_id"]
        scenario = np.array([traj_scenario_map[t] for t in traj_id])
        pred_clipped = np.clip(pred, 0.0, 1.0)

        for scen_filter in ["overall", "endemic", "outbreak"]:
            mask = np.ones(len(traj_id), dtype=bool) if scen_filter == "overall" else (scenario == scen_filter)
            if not mask.any():
                continue
            targets = list(enumerate(group_names)) + [(None, "overall")]
            for gi, ward_name in targets:
                if ward_name == "overall":
                    p, a, pc = pred[mask], actual[mask], pred_clipped[mask]
                else:
                    p, a, pc = pred[mask, gi : gi + 1], actual[mask, gi : gi + 1], pred_clipped[mask, gi : gi + 1]
                rmse = float(np.sqrt(np.mean((p - a) ** 2)))
                mae = float(np.mean(np.abs(p - a)))
                rmse_c = float(np.sqrt(np.mean((pc - a) ** 2)))
                mae_c = float(np.mean(np.abs(pc - a)))
                rows_out.append(
                    {
                        "model": model_name, "h": h, "ward": ward_name, "scenario": scen_filter,
                        "n": int(mask.sum()), "rmse": rmse, "mae": mae,
                        "rmse_clipped": rmse_c, "mae_clipped": mae_c,
                    }
                )
    return pd.DataFrame(rows_out)
