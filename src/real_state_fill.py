"""P5 utility, used starting in P8: build a complete state vector from
P3's real weekly prevalence series, filling any missing group-week with
the carry-forward value (up to 2 weeks), for use as a starting point when
forecasting from real data. Built and tested here; NOT applied to the
full real series in this phase -- K is never fitted on real data (only
~16 noisy weeks), so gap handling only matters for P8's initial
conditions and scoring.

Two distinct masks matter downstream:
  - `observed` (from fill_state_vector): True only where a genuine
    states_real row was used, not a carry-forward fill. Filled values are
    valid INPUTS for a starting state, never valid prediction targets.
  - the SCORING mask (observed_for_scoring_mask, n_tested >= 10) is a
    separate, stricter concept for deciding which (week, group) cells
    count toward P8's accuracy metrics.
"""
import numpy as np


def fill_state_vector(week, states_real, states_carry_forward, groups):
    """Build a complete state vector for `week`, one entry per group in
    `groups` order. Preference per group: (1) states_real's value for
    (week, group) if that row exists at all (even if flagged low_n -- it
    is still a genuine test-derived estimate, just noisy); (2)
    states_carry_forward's value if states_real has nothing; (3) NaN if
    neither is available.

    Returns (state [len(groups)] float, with NaN where unavailable;
    observed [len(groups)] bool, True only where states_real (not
    carry-forward) supplied the value)."""
    real_lookup = {(w, g): p for w, g, p in zip(states_real["week"], states_real["group"], states_real["prevalence"])}
    carry_lookup = {
        (w, g): p
        for w, g, p in zip(
            states_carry_forward["week"], states_carry_forward["group"], states_carry_forward["prevalence"]
        )
    }

    state = np.full(len(groups), np.nan)
    observed = np.zeros(len(groups), dtype=bool)
    for i, group in enumerate(groups):
        key = (week, group)
        if key in real_lookup:
            state[i] = real_lookup[key]
            observed[i] = True
        elif key in carry_lookup:
            state[i] = carry_lookup[key]
    return state, observed


def state_is_usable_as_starting_point(state):
    """A week is only usable as a forecast starting point if every group
    ended up with SOME value (real or carried forward) -- no NaN left."""
    return not np.isnan(state).any()


def observed_for_scoring_mask(week, states_real, groups, min_n_tested=10):
    """Which (week, group) entries are eligible to count toward P8's
    accuracy metrics: a genuine states_real row with n_tested >=
    min_n_tested (P3's own low_n threshold). Stricter than
    fill_state_vector's `observed` mask, which accepts any real row
    regardless of sample size -- scoring should not reward or penalize a
    forecast against a handful-of-people estimate."""
    lookup = {(w, g): n for w, g, n in zip(states_real["week"], states_real["group"], states_real["n_tested"])}
    mask = np.zeros(len(groups), dtype=bool)
    for i, group in enumerate(groups):
        n_tested = lookup.get((week, group))
        if n_tested is not None and n_tested >= min_n_tested:
            mask[i] = True
    return mask
