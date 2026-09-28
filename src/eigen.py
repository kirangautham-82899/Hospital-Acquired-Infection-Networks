"""P7: eigendecomposition of the fitted EDMD operators (P6), mapped back
to ward space via the readout C and un-scaled to original prevalence
units, to see which wards dominate the most persistent dynamical modes.

Filtering:
  - D3's K is rank-deficient (confirmed in P6: rank 19 of 25, from the
    proven structural redundancy of Wx/x*(Wx) given x -- see
    src/observables.py's D3 caveat). Empirically the eigenvalue spectrum
    has a ~10^12 gap between the 19th and 20th largest magnitude, so
    "keep the top rank(K) eigenvalues, flag the rest spurious" is
    unambiguous, not a judgment call with a fuzzy threshold. D1 and D2
    are full rank, so this filter is a no-op for them.
  - trivial_mode_mask is a general defensive check for a mode whose
    ward-space pattern is ~0 (would be invisible through the readout C).
    CORRECTED REASONING, logged honestly in research_log.md: an earlier
    version of this module assumed the constant feature always produces
    exactly one such trivial mode, reasoning that K's row 0 = [1,0,...,0]
    (verified in P6) makes the readout-excluded constant direction e_0 an
    eigenvector. That's wrong: row 0 = [1,0,...,0] makes e_0 a LEFT
    eigenvector of K (e_0^T K = e_0^T, eigenvalue 1), not a right one --
    K's COLUMN 0 (the intercept for every output) is generally nonzero
    almost everywhere, so e_0 is generally NOT close to any RIGHT
    eigenvector, which is what mode decomposition (K v = lambda v) uses.
    Empirically, zero modes trigger this check across D1/D2/D3 on the
    real data. The eigenvalue closest to 1 is NOT a trivial artifact --
    it is the system's genuine steady-state / equilibrium mode (the ward
    pattern that neither grows nor decays), and its ward-space content is
    real, interpretable information.

Eigenvector un-scaling: K was fit in SCALED space (P6's
ConstantAwareScaler; z = (phi(x) - mean) / scale on non-constant
features, identity on the constant). Writing D = diag(scale) (so
x ~= D z, ignoring the mean/offset, which is a homogeneous/linear
relationship for eigenvector purposes), the scaled-space operator is
K_z = D^-1 K_orig D, so K_orig = D K_z D^-1. If K_z v = lambda v, then
K_orig (D v) = D K_z D^-1 (D v) = D K_z v = lambda (D v): u = D v =
v * scale (element-wise MULTIPLY, not divide -- verified against a
synthetic similarity-transform case in tests/test_eigen.py; standardized-
space directions scale UP by the standard deviation to reach original
units, matching intuition). Ward-space mode shapes are C @ (v * scale_).
"""
import numpy as np
import pandas as pd


def eigendecompose(K):
    """Right eigenvalues/eigenvectors of K, sorted by descending
    magnitude (eigvecs columns correspond to eigvals entries)."""
    eigvals, eigvecs = np.linalg.eig(K)
    order = np.argsort(-np.abs(eigvals))
    return eigvals[order], eigvecs[:, order]


def unscale_eigenvector(v, scale_):
    """u = v * scale_ (element-wise): map a right eigenvector from K's
    scaled operating space back to original-units space (see module
    docstring for the similarity-transform derivation -- this is a
    multiply, not a divide)."""
    return v * scale_


def mode_ward_patterns(eigvecs, C, scale_):
    """Ward-space mode shape (complex) in ORIGINAL prevalence units for
    every eigenvector (column): C @ (v * scale_). Returns
    [n_groups, n_modes] complex."""
    unscaled = eigvecs * scale_[:, None]
    return C @ unscaled


def null_space_rank_cutoff(K, tol=None):
    """Number of eigenvalues to treat as genuine dynamical modes:
    rank(K). The remaining (n_features - rank) smallest-magnitude
    eigenvalues (eigvals/eigvecs must be magnitude-sorted, as
    eigendecompose() returns them) are spurious null-space artifacts."""
    return int(np.linalg.matrix_rank(K, tol=tol))


def trivial_mode_mask(ward_patterns, rel_tol=1e-6):
    """True for any mode whose ward-space pattern has near-zero norm
    relative to the largest mode's norm -- i.e. a mode that would be
    invisible through the readout C. A general defensive check, NOT
    specific to the constant feature (see module docstring for why that
    original assumption was wrong); empirically triggers on 0 of the real
    D1/D2/D3 modes. L1 norm, robust to a single outlier entry."""
    norms = np.abs(ward_patterns).sum(axis=0)
    if norms.max() == 0:
        return np.ones(len(norms), dtype=bool)  # every mode's ward pattern is exactly zero -> all trivial
    return norms < rel_tol * norms.max()


def find_conjugate_pairs(eigvals, atol=1e-8):
    """For each eigenvalue with nonzero imaginary part, the index of its
    complex-conjugate partner among the other eigenvalues (-1 if real or
    no partner found). A real matrix's complex eigenvalues always occur
    in conjugate pairs, corresponding to one real oscillatory mode."""
    partner = np.full(len(eigvals), -1)
    for i, li in enumerate(eigvals):
        if abs(li.imag) < atol or partner[i] != -1:
            continue
        for j in range(i + 1, len(eigvals)):
            if partner[j] != -1:
                continue
            lj = eigvals[j]
            if abs(li.real - lj.real) < atol and abs(li.imag + lj.imag) < atol:
                partner[i], partner[j] = j, i
                break
    return partner


def mode_table(eigvals, ward_patterns, rank_cutoff, group_names):
    """One row per mode: eigenvalue (real/imag/magnitude/angle/period),
    whether it's beyond the rank cutoff (spurious_null_space), whether
    its ward pattern is ~0 / invisible through the readout
    (zero_ward_pattern -- see trivial_mode_mask; NOT specific to the
    constant feature, empirically 0 of the real modes), its conjugate
    partner (if any), and its normalized ward shares (magnitude of each
    ward's entry / sum of magnitudes across wards)."""
    n_modes = len(eigvals)
    trivial = trivial_mode_mask(ward_patterns)
    partner = find_conjugate_pairs(eigvals)

    rows = []
    for i in range(n_modes):
        lam = eigvals[i]
        magnitude = abs(lam)
        angle = np.angle(lam)
        period = (2 * np.pi / abs(angle)) if abs(angle) > 1e-9 else np.inf

        pattern = ward_patterns[:, i]
        mags = np.abs(pattern)
        shares = mags / mags.sum() if mags.sum() > 0 else np.zeros_like(mags)

        row = {
            "mode": i, "eigenvalue_real": lam.real, "eigenvalue_imag": lam.imag,
            "magnitude": magnitude, "angle_rad": angle, "period_weeks": period,
            "conjugate_partner": int(partner[i]),
            "spurious_null_space": i >= rank_cutoff,
            "zero_ward_pattern": bool(trivial[i]),
        }
        for g, share in zip(group_names, shares):
            row[f"share_{g}"] = share
        rows.append(row)
    return pd.DataFrame(rows)


def dominant_ward_relevant_mode(mode_df):
    """Index of the first (largest-magnitude, since mode_df is built from
    magnitude-sorted eigvals) mode that is NEITHER spurious (D3's null
    space) NOR invisible through the readout (zero_ward_pattern) -- the
    most persistent mode that actually says something about ward
    dynamics. For D1/D2/D3 on the real data this is simply the
    largest-magnitude mode (no modes are filtered by either check).
    Returns None if every mode is filtered."""
    candidates = mode_df[~mode_df["spurious_null_space"] & ~mode_df["zero_ward_pattern"]]
    if candidates.empty:
        return None
    return int(candidates.iloc[0]["mode"])
