"""P5: dictionary / observable-lifting functions for EDMD (P6).

Three dictionaries (decision content -- see research_log.md for the
numbering caveats vs Part A):
  D1  linear
  D2  full degree-2 polynomial (constant, linear, squares, all cross terms)
  D3  contact-weighted (state, squares, W x, x elementwise* (W x))

"Identity included in the dictionary" means the raw state x itself is one
of the features in every dictionary, so a predicted lifted state can be
read back down to a state by selecting those entries -- already true by
construction here (D1 is x, D2 contains x, D3 starts with x).

The constant function 1 is a SEPARATE, newly logged decision (not implied
by "identity"): it is prepended to all three dictionaries, because the
simulator's importation epsilon makes the dynamics affine, and a K with
no offset term can't represent that. See research_log.md.

No scaling is done here -- features have very different natural scales
(x^2 is tiny next to x), so P6 fits and saves a StandardScaler on the
training split only, not here.

Dimension-agnostic: works for n=6 (all, default) or n=5 (patients-only,
deferred to experiment E6) -- callers pass group_names explicitly rather
than anything being hardcoded to 6.
"""
import numpy as np


def d1_linear(X, group_names):
    """D1 = [1, x_1, ..., x_n]. X: array with shape [..., n] (any number
    of leading batch dimensions, e.g. [n_trajectories, n_weeks, n]).
    Returns (features [..., 1+n], feature_names)."""
    X = np.asarray(X, dtype=float)
    ones = np.ones(X.shape[:-1] + (1,))
    features = np.concatenate([ones, X], axis=-1)
    names = ["1"] + [f"x_{g}" for g in group_names]
    return features, names


def d2_poly2(X, group_names):
    """D2 = [1, x_i, x_i^2, x_i*x_j for i<j] -- the full degree-2
    polynomial basis (constant + linear + all quadratic terms, including
    cross terms between different groups)."""
    X = np.asarray(X, dtype=float)
    n = X.shape[-1]
    ones = np.ones(X.shape[:-1] + (1,))
    squares = X**2

    cross_terms, cross_names = [], []
    for i in range(n):
        for j in range(i + 1, n):
            cross_terms.append(X[..., i] * X[..., j])
            cross_names.append(f"x_{group_names[i]}*x_{group_names[j]}")
    cross = np.stack(cross_terms, axis=-1) if cross_terms else np.zeros(X.shape[:-1] + (0,))

    features = np.concatenate([ones, X, squares, cross], axis=-1)
    names = (
        ["1"]
        + [f"x_{g}" for g in group_names]
        + [f"x_{g}^2" for g in group_names]
        + cross_names
    )
    return features, names


def d3_contact_weighted(X, group_names, W):
    """D3 = [1, x, x^2, Wx, x elementwise* Wx]. W must be an [n, n]
    row-normalized matrix whose row/column order matches group_names /
    X's last axis exactly -- callers must verify this alignment (see
    src/build_observables.py). x*(Wx) is the ELEMENTWISE product (n
    features), not a dot product (which would collapse to one scalar)."""
    X = np.asarray(X, dtype=float)
    n = X.shape[-1]
    W = np.asarray(W, dtype=float)
    assert W.shape == (n, n), f"W shape {W.shape} does not match state dimension {n}"

    ones = np.ones(X.shape[:-1] + (1,))
    squares = X**2
    Wx = X @ W.T  # (Wx)_i = sum_j W[i, j] * x_j, vectorized over leading batch dims
    cross = X * Wx  # elementwise, NOT a dot product

    features = np.concatenate([ones, X, squares, Wx, cross], axis=-1)
    names = (
        ["1"]
        + [f"x_{g}" for g in group_names]
        + [f"x_{g}^2" for g in group_names]
        + [f"(Wx)_{g}" for g in group_names]
        + [f"x_{g}*(Wx)_{g}" for g in group_names]
    )
    return features, names


DICTIONARIES = {"D1": d1_linear, "D2": d2_poly2, "D3": d3_contact_weighted}


def apply_dictionary(name, X, group_names, W=None):
    """Dispatch to the named dictionary ('D1', 'D2', 'D3'). W is required
    (and only used) for D3."""
    if name == "D3":
        return d3_contact_weighted(X, group_names, W)
    return DICTIONARIES[name](X, group_names)
