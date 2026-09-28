# Research Log

Sep 28: chose I-Bird dataset, contact network (no transfer records), ward-level state with 6 groups.

Sep 28: P0 setup done (venv, folders, git init, requirements.txt). P1 data audit
done (src/load.py, src/audit.py, tests/). All 19 "first inspection" reference
numbers in CLAUDE.md verified exactly against the raw CSVs, no adjustments
needed: 795/124,924/6,728 rows, 452/343 PA/PE in admission, 589 (329/260) people
in mat.day.csv, 206 admission people with zero contacts, 7 missing contact days
(Jul 21-23, Aug 28-29, Sep 18-19, all missing days come in clusters of 2-3
consecutive days, not scattered), length range 60-86400s (mean 3886s), sarm
1,118/5,610, 295 people MRSA-positive at least once, date_prl == date_prl_posix
for all rows, 9 admission service_pa_pe values all map cleanly onto the 6 locked
ward groups (0 unmapped).

Unexpected/worth noting (not blockers, no CLAUDE.md decision affected):
- microbio.csv: germe has 4,161/6,728 missing (only filled for some tests, not
  strictly tied to sarm=1 count of 1,118 - about 2,567 rows have a germe value,
  so it's also recorded for some non-MRSA results). age has 145/6,728 missing.
- Weekly test coverage per ward never reaches 100% in any week (peaks around
  45-65%), consistent with roughly-weekly-not-exactly-weekly testing per person
  plus partial-week edge effects at the start/end of the date range - confirms
  decision #6 (no imputation in main run) is the right default, imputation
  sensitivity run will matter.
- Contact reciprocity (row has same-day reverse partner) is 99.88%, matching
  the ~99.9% reference; the ~0.12% without a reverse row is small enough to not
  need special handling yet.
- mat.day.csv's 124,924 rows cover 110 of 117 days Jul 1-Oct 25; microbio's own
  test date range (May 4-Oct 27) is wider than the contact window, so ward-level
  test coverage before Jul 1 / after Oct 25 reflects a period with no contact
  data - relevant when we pick the real weekly-prevalence window in P3.

Confirmed in P1, ready to check off in CLAUDE.md's "RE-VERIFY in P1" note.

Sep 28: P2 contact network + ward matrix W done. Key decisions/conventions
(not previously specified, so recording them here per the correction on this
phase):

- Ward mapping moved to a shared src/wards.py (used by src/audit.py, P1's
  audit, and src/network.py, P2's build) instead of living only in audit.py.
- Found that reciprocal contact rows (A->B and B->A, same day) do NOT always
  agree on 'length': ~17% of pairs disagree (median gap ~90s, up to 48,840s
  at the extreme), consistent with independent per-person sensor reads
  rather than data corruption. 144 rows (~0.1%) have no reverse partner at
  all.
- Person-level deduped edge list (one row per unordered pair per day, used
  for the network/graphs/centrality): when both directions exist, average
  their length; when only one exists, use it as-is. Saved as the single
  master file data/processed/edges_master.csv (62,534 rows; 19,974 unique
  pairs overall, matching the P1 reference number). No per-day or per-week
  networkx graphs are persisted -- they're built on demand from this file.
- Ward contact matrix W: sums the RAW bidirectional rows as given (no
  dedup) -- W[i,j] = total contact-seconds people in ward i spent with
  people in ward j (each person's own exposure). This makes the diagonal
  ~2x the undirected within-ward total (exactly 2x except for the 144
  unreciprocated rows, verified: ratio 1.998-2.000 across wards). Sum of
  all W entries == sum of contacts['length'] exactly (485,444,550 seconds),
  confirming no double-counting or loss. Row-normalized W has all rows
  summing to exactly 1.0.
- W is NOT used inside the P4 SIS simulator (that runs on the person-level
  daily edges). W feeds the D3 EDMD dictionary and the network-exposure
  baseline only.
- Both a staff-inclusive population ("all", 589 nodes, 6 ward groups) and a
  patients-only population ("patients_only", 329 nodes, 5 real wards,
  decision #3's sensitivity run) were built in full: network, W (raw +
  normalized), weekly W, node metrics (degree/strength/centrality),
  within-vs-between-ward share, and plots.
- Within-ward share of total contact-seconds: 90.3% (all population), 94.0%
  (patients-only) -- confirms decision #3's premise that pooling
  patients+staff per ward is a reasonable state definition, since most
  contact really does stay inside a ward.
- Weekly bins: week 0 = the 7-day window starting at STUDY_START
  (2009-07-01); 117 days -> 17 weekly bins (last bin partial, 5 days).
  [SUPERSEDED Sep 28, see correction below.]
- OPEN QUESTION for the user (Sep 28, partially answered below): decision
  numbering in CLAUDE.md (as pasted into this project) doesn't match what
  was referenced as "Part A" -- e.g. D3 (contact-weighted dictionary) is
  decision #11 here, but was called out as decision #13 in Part A, with #11
  said to be about simulation scenarios. CLAUDE.md's decision *content* was
  used as-is (unchanged) since that's what's in this repo; if Part A is
  authoritative for numbering, let us know and we'll renumber CLAUDE.md to
  match.

Sep 28: CORRECTION to P2's weekly binning, found while starting P3.
assign_week() anchored week 0 at STUDY_START (2009-07-01, a Wednesday), but
microbio swabs run Monday-Thursday. Wed-anchored (Wed-Tue) bins therefore
cut each ward's weekly screening round in half. Verified empirically on the
Jul1-Oct25 window: Wed-anchored bins put 655 of 3,812 person-weeks (17.2%)
into more than one bin, vs 80 of 4,412 (1.8%) with Monday-anchored bins.

Fix: src/network.py's assign_week() now anchors week 0 at the Monday
on/before STUDY_START, i.e. week 0 = Mon 2009-06-29 to Sun 2009-07-05
(contacts only run Jul1-Jul5 within it, 5 of 7 days -- the short/partial
bin moved from the end to the start). Week 16 = Mon 2009-10-19 to Sun
2009-10-25, a full week, matching the contact window's last day exactly.
Still 17 bins (0-16). Rebuilt P2's weekly graphs and weekly W with this
fix (src/build_network.py re-run); all 51 tests still pass since none of
them hardcoded a specific bin boundary, only structural properties (bin
count, conservation).

Partial answer to the decision-numbering question above: told that in
Part A, node definition = #3, patients-only sensitivity = #5, no-imputation
= #8 (vs #2/#3/#6 in this repo's CLAUDE.md). Still don't have the full Part
A numbering, so CLAUDE.md is not being renumbered yet -- continuing to
follow decision *content*, cross-checked against Part A's descriptions
where given.

Sep 28: P3 real weekly prevalence done (src/states.py, src/build_states.py).
Decisions locked:

- Population: MAIN series = people tested in-window AND present in the
  589-person contact network (581 of 666 in-window-tested people qualify;
  85 tested people are absent from the network and excluded). CHECK series
  = all 666 tested people, unrestricted, to show how much the restriction
  matters. Verified: max |prevalence diff| between MAIN and CHECK across
  all group-weeks = 0.056, mean = 0.014 -- small, as expected, confirming
  the restriction doesn't meaningfully distort the series.
- Repeat tests within a week (80 of 4,412 person-weeks for the CHECK
  population, 72 of 4,028 for MAIN, both ~1.8%, reproducing the numbers
  given): a person counts positive that week if ANY test that week was
  sarm=1, and counts once in the denominator regardless of test count.
  Verified with an independent hand-check against raw microbio.csv for two
  cells (week 5/Menard 1: 67 tested, 13 positive; week 10/Sorrel 2: 45
  tested, 10 positive) -- both matched exactly.
- Window: tests in [2009-07-01, 2009-10-25] (4,492 rows) go into the main/
  check/patients-only series. Tests on 2009-10-26/27 (38 rows) fall outside
  the contact window and are dropped (noted here, not silently discarded).
  Tests before 2009-07-01 (2,198 rows, back to 2009-05-04) are kept
  separately in data/processed/states_pre_window_raw_tests.csv for context,
  plus a per-person last-known-status table
  (states_pre_window_last_status.csv, 511 people) as a candidate P4
  starting state -- neither is used for calibration.
- Group-weeks with fewer than 10 tested people are flagged (low_n=True),
  not dropped: 4 of 93 non-empty group-weeks in the MAIN series. A further
  9 of the 102 possible (17 weeks x 6 groups) combinations have ZERO tested
  people and are absent from states_real.csv entirely (not synthesized as
  0% prevalence) -- see p3_zero_tested_group_weeks.csv.
- Carry-forward (states_real_carry_forward_SENSITIVITY_ONLY.csv): fills an
  untested week with a person's last known status (positive OR negative,
  not just "assume negative"), up to 2 weeks back, within the in-window
  table only (does not reach into the pre-window file). Verified on a
  synthetic 2-test case that week 3 (3 weeks after a week-0 test, with no
  other test until week 4) is correctly left unfilled, not carried a 3rd
  week. n_carried <= n_tested holds for every row (checked). This is a
  robustness check only -- never a validation target for P4/P6 onward.
- Files: canonical copies of every series live in data/processed/ (P4's
  input); human-facing copies of the reporting tables (states_real,
  patients_only, check-vs-main diff, low_n flags, zero-tested list,
  hand-check) live in results/tables/p3_*.csv. Figure:
  results/figures/p3_prevalence_trajectory.png (main vs carry-forward per
  ward, low_n cells marked).
- 14 new tests in tests/test_states.py, all passing alongside the existing
  51 (65 total).

Sep 28: P4 SIS simulation + calibration done (src/simulate.py,
src/calibrate_sim.py, src/trajectories.py, src/build_simulation.py).
Decisions locked (per correction: plan numbers SIS=#9, calibration=#10,
scenarios=#11, splits=#14, seeds=#18 -- still following content, not
renumbering CLAUDE.md without the full Part A list):

- Mechanism: daily individual-level SIS on the 589-person contact network
  (patients-only deferred to experiment E6 -- population is a parameter
  everywhere in src/simulate.py/calibrate_sim.py/trajectories.py, defaulting
  to "all"). P(S->I from contacts that day) = 1-exp(-beta*H_i(t)), H_i(t) =
  that day's contact-hours with currently-infected neighbors (the per-
  neighbor-independent-trial assumption collapses cleanly to this single
  exponential in the SUM of hours, verified analytically: a 2-person
  hand-built network with H=2h, beta=0.05 gave empirical P(infect)=0.0952
  over 20,000 replicates vs analytic 1-exp(-0.1)=0.0952). Importation
  epsilon and contact transmission combine as independent events:
  P(S->I)=1-(1-P_transmit)(1-epsilon). Decolonization P(I->S)=gamma,
  independent per person per day.
- Comparing like with like (calibration objective): real prevalence only
  reflects tested people, so the objective reads each tested person's
  SIMULATED status on their REAL test date and aggregates with the exact
  same rule P3 uses (any positive that week = positive, person counted
  once) -- see src/calibrate_sim.py's simulated_weekly_prevalence. Loss =
  n_tested(real)-weighted mean squared error, calibration weeks (0-11)
  only, P3's low_n-flagged group-weeks excluded.
- Two DIFFERENT initial-condition schemes, as instructed:
  - Calibration runs: each person's last pre-window status if known
    (states_pre_window_last_status.csv from P3); people with no pre-window
    test draw Bernoulli(their group's pre-window prevalence) -- never
    default susceptible.
  - Training runs: endemic starts draw an INDEPENDENT Uniform(0.5,1.5)
    multiplier PER GROUP PER TRAJECTORY (not one shared multiplier per
    trajectory -- chosen to maximize coverage of the joint 6-ward state
    space, since a single shared multiplier would only move every ward up
    or down together) applied to that group's baseline real prevalence
    (mean of states_real over the calibration weeks, excluding low_n),
    capped at 1; each person in the group then drawn independently
    Bernoulli at that probability. Outbreak starts: everyone susceptible
    except 1-3 seeded cases in ONE randomly chosen ward, seed ward varied
    per trajectory. Split exactly 150/150 of 300. beta and gamma
    independently drawn Uniform(0.5x, 2x) of their calibrated values PER
    TRAJECTORY; epsilon held fixed at its calibrated value (decision
    content names only beta/gamma as varied). Every trajectory tagged:
    scenario, seed_ward, n_seeds, beta, gamma, epsilon, ic_seed,
    param_seed, dyn_seed.
- Training-data weekly convention (DIFFERENT from the calibration
  objective, on purpose -- locked so P6 uses the same one): mean daily
  prevalence over a Monday-anchored week's calendar days, across ALL
  people in the group (the simulator knows everyone, unlike real testing).
- Grid: beta 8 log-spaced pts in [1e-3,5e-2]/contact-hour, gamma 8 in
  [0.005,0.1]/day, epsilon 5 in [1e-4,5e-3]/day (320 points), 20 replicates
  per point with COMMON RANDOM NUMBERS (same (ic_seed,dyn_seed) pairs, from
  SeedSequence.spawn, reused at every grid point) -- a grid point's
  simulated prevalence is the mean, per (week,group) cell, of that cell's
  prevalence across the 20 replicates. Full run took ~2.7 min (320*20=6400
  simulated 117-day trajectories).
- Split: calibrated on weeks 0-11, held out weeks 12-16 (simulator still
  runs all 117 days regardless). Held-out loss (sanity check only, never
  used to pick the point): 0.00919 vs calibration loss 0.00516 -- same
  order of magnitude, no sign of gross overfitting to the calibration
  window.
- RESULT / LIMITATION TO REPORT: the best point (beta=6.82e-4/hr,
  gamma=1.67e-3/day, epsilon=7.07e-4/day) was on the low edge of BOTH beta
  and gamma initially. Auto-widened once (3x extension in the hugged
  direction, same point density) per instructions -- beta resolved off the
  edge, but gamma is STILL at the low edge of the widened grid. This
  reflects a genuine ridge/identifiability issue, not a bug: with gamma
  this low (mean carriage ~600 days, implausible for MRSA biologically),
  the simulated ward trajectories stay nearly flat near their initial
  condition for the whole 17-week window (visually confirmed in
  p4_calibration_fit.png) -- and because the real weekly series is noisy
  with no strong trend, a near-static model is hard for weighted MSE to
  beat. 16 of 320 grid points are within 10% of the best loss, confirming
  the expected ridge (beta/gamma partly trade off). Full grid saved to
  p4_calibration_grid.csv; not chasing the edge further by construction --
  flagging this as an open modeling question for the user (e.g. whether to
  add a biologically-motivated prior/bound on gamma, or accept that with
  only ~12 noisy weekly snapshots per ward, beta/gamma are only weakly
  identified from this objective alone).
- Files: data/processed/states_sim.npz (states: [300,17,6] float array in
  config.WARD_GROUPS order, no NaNs, values in [0, 0.65], plus per-
  trajectory metadata arrays); results/tables/p4_calibration_grid.csv,
  p4_calibrated_params.csv, p4_trajectories_metadata.csv;
  results/figures/p4_calibration_fit.png (real calib/holdout vs simulated,
  per ward).
- Verification beyond the plan's two checks, all implemented as pytest
  (tests/test_simulate.py): beta=epsilon=0 -> colonized count provably
  non-increasing (deterministic given the mechanism, not just usually
  true) and decays to 0 within 117 days; gamma=epsilon=0 -> non-decreasing;
  S+I=N by construction (bool array, checked explicitly); same seed ->
  bit-identical history; a zero-contact-days scenario shows no transmission
  to an isolated person while decolonization still applies; a 2-person
  hand-built network's empirical infection probability over 20,000
  replicates matched the analytic 1-exp(-beta*H) within 5 standard errors.
- 32 new tests across tests/test_simulate.py, test_calibrate_sim.py,
  test_trajectories.py (all passing alongside the existing 65, 97 total).
  Two real bugs were caught by writing these tests (not left unfixed):
  calibration_loss relied on pandas' merge-suffix behavior to name the
  weight column, which broke if sim_prevalence lacked its own n_tested
  column -- fixed to rename explicitly before merging, weight always taken
  from states_real. (The other two initial test failures were bugs in the
  TESTS' own assumptions, not the source: SeedSequence.spawn() children
  share the same .entropy as their root, so distinctness has to be checked
  via what the seeds generate, not .entropy; and simulation_day_list()
  starts on a Wednesday, so its first 7 entries span parts of two
  Monday-anchored weeks, not one.)

Sep 28: P5 observables done (src/observables.py, src/trajectory_split.py,
src/real_state_fill.py, src/build_observables.py). Decisions locked (plan
numbers per the last correction: SIS=#9, calibration=#10, scenarios=#11,
splits=#14, seeds=#18 -- content followed, CLAUDE.md still not renumbered):

- "Identity included in the dictionary" clarified: it means the raw state
  x itself is a feature (so a predicted lifted state can be read back down
  to x by selection), NOT the constant function -- already true by
  construction for D1/D2/D3 (verified by test_all_dictionaries_include_
  the_raw_state_x). The constant 1 is a SEPARATE, newly logged decision:
  prepended to all three dictionaries, because the simulator's importation
  epsilon makes the dynamics affine and a K with no offset term can't
  represent that; D1+constant is also the natural "linear EDMD" ablation
  baseline for P8. Feature counts for n=6, verified exactly by
  tests/test_observables.py: D1=7 (1+x), D2=28 (1+x+x^2+15 cross terms),
  D3=25 (1+x+x^2+Wx+x-elementwise-times-Wx). D3's cross term is confirmed
  elementwise (n features), not a dot product (which would collapse to a
  single scalar) -- explicit test.
- Gap-filling utility (src/real_state_fill.py) built and tested now, per
  instructions, but NOT applied to the real series in this phase -- K is
  never fit on real data. fill_state_vector prefers a genuine states_real
  value (even if low_n-flagged -- still a real estimate) over the P3
  carry-forward value, and returns NaN only if neither exists; a separate,
  STRICTER observed_for_scoring_mask (n_tested >= 10) is for P8's accuracy
  scoring only -- confirmed these two masks disagree exactly on low_n
  cells (explicit test). Both will be applied to the real series starting
  in P8.
- No scaling inside the dictionaries (features have very different natural
  scales -- x^2 is tiny next to x). P6 will fit and save a StandardScaler
  on the training split only.
- W: the row-normalized OVERALL W from P2 (p2_ward_matrix_W_all.csv),
  confirmed identical row/column group order to config.WARD_GROUPS and to
  states_sim.npz's own group order (explicit assert in
  src/build_observables.py, would raise loudly if it ever drifted).
  LIMITATION (logged per instructions): W is time-invariant, built from
  the WHOLE contact period, including the weeks later used as P4's
  held-out weeks. It contains no MRSA outcome information (it's built
  purely from contact seconds), so this doesn't leak calibration targets,
  but it does mean D3's network structure isn't blind to the holdout
  period's contact patterns -- acceptable per instructions, flagged for
  the report.
- feature_names saved per dictionary (results/tables/p5_feature_names_D*.csv)
  for P7/P9 eigenmode interpretation.
- Train/val/test split defined ONCE here (src/trajectory_split.py):
  70/15/15 by trajectory, stratified independently within each scenario
  (endemic/outbreak) so both keep the ratio, fixed seed (config.SEED).
  Real counts: 105/22/23 per scenario (150 each), verified exactly by
  test_split_on_real_trajectory_metadata_matches_expected_counts. Saved to
  data/processed/trajectory_split.csv -- P6 onward must load this file,
  not re-derive a split.
- Code confirmed dimension-agnostic: n=5 (patients-only, deferred to E6)
  produces the expected 21/21-feature D2/D3 dictionaries with no code
  changes (explicit test).
- CONDITIONING FINDING, worth flagging prominently for P6: on the training
  split's stacked source snapshots (3,360 = 105 train trajectories x 16
  transitions, both scenarios), condition numbers are D1=35.5, D2=976.9,
  D3=9.4e16 (numerically singular -- 4 exact machine-epsilon-zero singular
  values, plus 2 more that are much smaller than the rest). Root cause
  diagnosed, not just observed: Wx = x @ W.T is a LINEAR function of x, so
  for ANY W, including both x and Wx as separate linear features is
  structurally rank-deficient (rank([x, Wx]) <= rank(x) = 6, regardless of
  how much data you have) -- only the nonlinear terms (x^2, x*(Wx)) can
  contribute genuinely new rank. And because P2 found W strongly diagonal-
  dominant (~90% within-ward contact), x*(Wx) is itself nearly
  proportional to x^2 elementwise (empirical corr(x_i, (Wx)_i) ranges
  0.80-0.9997 across the 6 wards), so even the nonlinear terms are close
  to collinear. This is a property of the LOCKED D3 definition combined
  with the real network structure, not a bug -- not deviating from the
  spec, but this means ridge regularization in P6 is not an optional nice-
  to-have for D3, it is essential just to get a well-posed solve. Full
  numbers in results/tables/p5_lifted_matrix_conditioning.csv.
- 25 new tests (tests/test_observables.py, test_trajectory_split.py,
  test_real_state_fill.py), all passing alongside the existing 97 (112
  total).

Sep 28: P6 EDMD fit done (src/edmd.py, src/build_edmd.py). This is the
"first review" milestone phase per CLAUDE.md's Phases list. Plan numbers
per the latest correction: SIS=#9, calibration=#10, scenarios=#11,
splits=#14, seeds=#18 -- content followed throughout, CLAUDE.md still not
renumbered (no full Part A numbering in hand yet).

MAJOR FINDING, verified both analytically and empirically before building
anything on top of it: D3 adds NO new function space beyond D2. Proof: for
a fixed W, (Wx)_i = sum_j W_ij x_j is a LINEAR function of x, so it is
already in D1's span; since P2's W is invertible (checked: all 6
eigenvalues nonzero, smallest 0.443), Wx spans EXACTLY the same subspace
as x -- 0 new rank. x_i*(Wx)_i = sum_j W_ij x_i x_j is a fixed linear
combination of D2's existing x_i^2 and cross terms -- also no new rank
beyond D2. So D3's 25 raw features have effective rank <= 1+6+6+6=19 (the
Wx block, 6 of them, is exactly redundant given x). This was CONFIRMED
empirically: the fitted K for D3 has rank(K)=19 of 25 on the real
training data (test_d3_fitted_rank_matches_theoretical_prediction_on_real_
data), exactly matching the theoretical ceiling, while D1 (rank 7 of 7)
and D2 (rank 28 of 28) are both full rank. Consequence for language used
throughout this project from now on: D3 should be described as "tests
whether a contact-structured prior helps generalization" -- NEVER "D3
injects network information", since it structurally cannot add
information beyond D2. A genuinely network-aware dictionary would need the
WEEK-SPECIFIC contact matrix W_t (since W_t x_t is then not a function of
x_t alone) -- noted as optional future work, not part of the locked plan.
FLAG FOR P7: D3's K will have near-zero eigenvalues from this null space
-- filter them before eigenmode interpretation.

P6 plan fixes, all implemented:
1. Standardization: only the non-constant features are centered/scaled
   (ConstantAwareScaler); the constant feature (index 0 in every
   dictionary) is kept exactly 1 and excluded from the ridge penalty.
   Fitted on the TRAINING split only (test_scaler_fitted_on_train_only).
   Confirmed the shift-invariance property mathematically and by test
   (test_shifted_target_shifts_only_constant_column): shifting every
   target by a constant vector c changes ONLY K's constant column (by
   exactly c), leaving every other (penalized) coefficient bit-identical
   -- this is only true if the constant is genuinely unpenalized, so it's
   a strong correctness check on the implementation, not just the design.
2. Snapshot pairs are built strictly within each trajectory
   (build_pairs_within_trajectory) -- week 16 of one trajectory is never
   paired with week 0 of the next. Verified with a synthetic array where
   each trajectory's values encode their own id, so any cross-trajectory
   contamination would be immediately detectable (it wasn't).
3. Solver: ridge via lstsq on the augmented system [X; sqrt(lambda)*P]
   (P = diag(0, 1, ..., 1), zero at the constant's position), never an
   explicit (X'X + lambda I)^-1 -- important given D3's near-singular X.
   Verified against the closed-form ridge solution
   (X'X+D)^-1 X'Y on synthetic data (test_ridge_fit_matches_closed_form_
   solution) and via exact recovery of a known noiseless linear system
   (D1) and a known noiseless quadratic map (D2).
4. Lambda selection: grid = 20 log-spaced points, 1e-6 to 1e3, per
   dictionary. Selected on the VALIDATION split (P5's saved
   trajectory_split.csv), scoring the mean RMSE over forecast horizons
   1-4 (K, K^2, K^3, K^4 applied to phi(x_t), rolled forward from every
   valid t in each validation trajectory, not just t=0) IN ORIGINAL
   PREVALENCE UNITS via the readout C and the scaler's inverse transform
   -- never on the raw lifted vector. Auto-widens once (3x extension) if
   the best point lands on a grid edge, same pattern as P4. Test split
   touched exactly once, after lambda and K were fixed from train+val.
   Selected lambda: D1=4.28, D2=1.44, D3=1.44 (none landed on an edge).
   NOTE: the validation curve is remarkably FLAT across ~6 orders of
   magnitude (1e-6 to ~1) before rising sharply past lambda~10 (see
   p6_lambda_curve_D3.png) -- regularization strength barely matters
   across a huge range, consistent with P4's finding that the calibrated
   dynamics are simple/near-static and only weakly identified by the
   available data.
5. Reporting (results/tables/p6_metrics_D*.csv): RMSE and MAE, train/val/
   test, overall and per-ward, h=1-4, split by scenario (endemic/
   outbreak), raw and clipped-to-[0,1], with skill score vs persistence
   (1 - RMSE_model/RMSE_persistence). Spectral radius and count of
   eigenvalues outside the unit circle per dictionary
   (p6_spectral_summary.csv). Lambda curves and a 1-step predicted-vs-
   actual scatter per dictionary in results/figures/.
6. HONEST RESULT, as anticipated: D1, D2, and D3 perform almost
   identically (test h=1 RMSE: D1=0.00748, D2=0.00758, D3=0.00747), all
   beating persistence by a modest ~12-13% at h=1, growing to ~25-27% by
   h=4 (skill score improves with horizon since persistence degrades
   faster than the fitted models). training_mean is a much worse baseline
   (skill as low as -12.5) since each trajectory sits near its own,
   trajectory-specific level rather than a shared global mean. D3 edges
   out D2 very slightly at every horizon despite having strictly less
   effective capacity (rank 19 vs 28) -- a small, concrete instance of the
   "fewer effective parameters can generalize marginally better"
   mechanism named in the D3 finding above, though the margin is small
   enough not to over-claim. D2 does not meaningfully beat D1 (the linear-
   EDMD ablation) -- reported as-is, not chased.
7. K was NOT applied to real data in this phase (deferred to P8).

Numbers behind the spectral diagnostics: D1 spectral radius=1.0000 (1
eigenvalue "outside" the unit circle by the strict > check, but it is
exactly the trivial constant->constant mode -- K's row 0 is
[1, 0, 0, 0, 0, 0, 0] to ~1e-16, and its eigenvalue is 1.0+0j to floating-
point precision, not a genuine instability). D2 spectral radius=1.0138, 5
eigenvalues outside the unit circle (mix of the trivial mode and possibly-
real mild instabilities -- worth a closer look in P7's eigenmode work, not
resolved here). D3 spectral radius=1.0004, 3 outside (fewer than D2,
consistent with D3's restricted/regularized structure).

Bug caught by writing tests, fixed in source: lambda_selection_criterion
hardcoded config.N_WEEKS instead of deriving n_weeks from the features
array's own shape. Real data always has exactly 17 weeks, so the
orchestrator's actual run was unaffected, but this was a latent
correctness bug (an implicit, unchecked coupling to a global constant)
that a synthetic-shape test caught immediately. Fixed to use
features.shape[1]; re-ran the full P6 build afterward and confirmed
bit-identical results on the real data (as expected, since the fix only
changes behavior for non-17-week inputs).

16 new tests (tests/test_edmd.py, test_build_edmd.py) including all 7
tests required by this phase (D1 exact linear recovery, D2 exact
quadratic recovery, closed-form ridge agreement, selector correctness,
train-only scaler, no cross-trajectory pairs, unpenalized-constant shift
invariance), plus the D3 rank confirmation on real data. 128 tests total,
all passing.

Sep 28: P7 eigenmodes done (src/eigen.py, src/build_eigen.py). CLAUDE.md
doesn't lock specific decisions for this phase beyond the phase name, so
judgment calls were made and are logged here (asked to proceed on my own
judgment for the open questions raised before starting).

Design choices:
- D3's null-space filter uses rank(K) (from P6, already verified) as the
  cutoff: keep the top rank(K) eigenvalues by magnitude, flag the rest
  spurious. Checked empirically before trusting this, not assumed: D3's
  eigenvalue magnitudes have a ~2.5 x 10^12 gap between the 19th and 20th
  largest (0.0026 vs 1.0e-15) -- completely unambiguous, not a fuzzy
  threshold call. D1 and D2 (full rank) have nothing filtered.
- Eigenvector un-scaling: K was fit in P6's SCALED space. Ward-space mode
  shapes need the eigenvector mapped back to original prevalence units
  via the SAME similarity transform relationship P5/P6 anticipated.
  Derived it carefully (K_z = D^-1 K_orig D with D=diag(scale), so
  K_z v=lambda v implies K_orig(D v)=lambda(D v)) and verified against a
  synthetic similarity-transform case before trusting it on real data.
- Mode ward "share" = |mode_ward_pattern_i| / sum(|mode_ward_pattern|)
  across wards (sums to 1, easy to read as a relative risk-contribution,
  and directly comparable to P9's eventual risk-score work).
- Complex-conjugate pairs are kept as separate rows (both ARE distinct
  eigenvalues/eigenvectors of a real K) but cross-referenced via a
  conjugate_partner column, so a reader doesn't double-count one
  oscillatory phenomenon as two unrelated modes.
- Dominant mode = the largest-magnitude mode that survives both filters
  (not spurious, not a zero ward pattern) -- for D1/D2/D3 on the real
  data this is simply the single largest-magnitude eigenvalue, since
  nothing gets filtered by the zero-ward-pattern check (see correction
  below).

TWO BUGS CAUGHT BY TESTS BEFORE THIS WAS TRUSTED, one of them a real
mathematical reasoning error on my part, not just a coding slip:
1. Eigenvector un-scaling direction. First draft divided by scale_
   (v / scale_); the correct relationship (re-derived and checked against
   a synthetic K_orig / K_scaled pair before accepting it) is MULTIPLY
   (v * scale_). This is not a nitpick -- dividing vs multiplying by
   scale factors that are all within an order of magnitude of each other
   can look "plausible" without an obvious red flag, so this would have
   silently produced wrong ward-mode interpretations without the test
   catching it.
2. Reasoning error about a "trivial constant-feature mode". Original
   assumption: since every dictionary's constant feature makes K's row 0
   exactly [1,0,...,0] (verified in P6), the constant basis direction e_0
   would be an eigenvector with a ward-space pattern of exactly 0 (since
   readout C never selects it), so every dictionary should show exactly
   one "trivial" mode to filter. Built a filter for this and it found
   ZERO such modes on the real D1/D2/D3 data -- investigated rather than
   forcing the filter to "work": row 0 = [1,0,...,0] makes e_0 a LEFT
   eigenvector of K (e_0^T K = e_0^T, confirmed exactly), which is a
   completely different thing from a RIGHT eigenvector (K v = lambda v,
   what mode decomposition x(t) = C sum v_i lambda_i^t b_i actually
   uses). K's COLUMN 0 (the intercept for every output) is nonzero almost
   everywhere (checked directly on the real D1 model), so e_0 is not
   close to any right eigenvector. CORRECTED CONCLUSION: the
   eigenvalue-closest-to-1 mode is NOT a trivial artifact to discard --
   it is the system's genuine steady-state/equilibrium ward pattern, and
   its content is real information. Renamed the (still useful as a
   general defensive check, just not tied to the constant specifically)
   column from trivial_constant_mode to zero_ward_pattern to stop the
   code from asserting something false about what it measures.

RESULT, reported honestly including a disagreement I didn't try to paper
over: the dominant (near-|lambda|=1, most persistent) mode's top ward
differs between dictionaries. D1 (linear only): Menard 1 dominates
(share=0.452), lambda=1.00000 exactly. D2 and D3 agree with each other:
Sorrel 1 dominates (share=0.418 and 0.415), lambda=1.0138 (D2, notably
>1 -- technically slowly growing, not an exact fixed point) and
lambda=1.00035+0.00091j (D3, complex but with an enormous ~6901-week
period, i.e. non-oscillatory on any timescale this data could show).
Plausible explanation, not confirmed: D2/D3's nonlinear (quadratic) terms
change the fitted dynamics' equilibrium structure relative to D1's plain
linear/VAR(1)-type model, and D2/D3 agreeing with each other while D1
differs suggests the nonlinear dictionaries may be capturing something
more consistent -- but this is exactly the kind of claim P9's proper
validation against the simulated intervention ground truth (cut a ward's
contacts 50%, measure the person-days drop) needs to check, not something
to assert from eigenmodes alone. D3's 6 spurious null-space eigenvalues
sit near the origin, cleanly separated from the 19 ward-relevant ones
clustered near the unit circle (visually confirmed in
p7_eigenvalue_spectrum_D3.png).

Files: results/tables/p7_modes_D*.csv (every mode, full detail),
p7_dominant_mode_ward_ranking.csv (cross-dictionary comparison);
results/figures/p7_eigenvalue_spectrum_D*.png (complex plane, unit circle,
modes colored by filter status), p7_dominant_mode_wards_D*.png (ward bar
chart for the dominant mode).

12 new tests (tests/test_eigen.py) -- including the two that caught the
bugs above -- all passing alongside the existing 128 (140 total).

Sep 28: P8 forecasting, validation, baselines done (src/baselines.py,
src/forecast.py, src/metrics.py, src/build_p8.py). CLAUDE.md doesn't lock
specific decisions for this phase beyond the phase name and the decision
#13-content baseline list (persistence, historical mean, network-exposure
linear model, ward-level SIS model, linear EDMD ablation), so several
judgment calls were made (asked to proceed on my own judgment) and are
logged here.

Design choices:
- This is the FIRST time K (fit purely on simulated data, P6) is applied
  to real data anywhere in this project -- deliberately deferred until
  now. Real starting states are built via P5's real_state_fill (real
  value preferred, carry-forward fallback up to 2 weeks, never defaults
  to susceptible); forecasts are scored ONLY against genuinely-observed
  cells (P5's observed_for_scoring_mask, n_tested >= 10) -- carry-forward
  values are valid inputs, never valid targets.
- Forecast protocol: rolling-origin within the single real 17-week
  series (every usable starting week, horizons 1-4, same convention as
  P6), not a single fixed origin -- needed for enough data points given
  how sparse real data is. Every forecast is tagged by which PERIOD its
  LANDING week falls in: 'calibration' (weeks 0-11) or 'holdout' (weeks
  12-16, config.HOLDOUT_WEEKS, already defined in P4/P6). K itself is
  out-of-sample for real data in BOTH periods (never fit on real data at
  all); the two new baselines below ARE fit on the calibration period, so
  'holdout' is the one period that is a fair, never-touched test for
  every model alike -- matches decision #13's real-data time split intent
  applied to the pieces of this pipeline that DO get fit on real data.
- Network-exposure linear model (new): x_{t+1,i} ~= a + b*x_{t,i} +
  c*(Wx_t)_i, ONE shared 3-parameter model pooled across all (week, ward)
  pairs rather than a separate model per ward -- real data has only ~11
  usable consecutive-week pairs across the calibration weeks, nowhere
  near enough to fit 6 separate per-ward models. Fit via the SAME
  ridge_fit solver as P6/P7 (unpenalized constant, lstsq-based) with a
  fixed lambda=1.0, not grid-searched -- a full lambda search on ~62
  training rows would be fitting noise, which is exactly why the Koopman
  operator itself is never fit on real data at all (P4-P6).
- Ward-level SIS model (new): mean-field/compartmental SIS directly on
  the 6-dim weekly prevalence vector (distinct from P4's individual-level
  daily simulator): x_{t+1,i}-x_{t,i} = beta*(1-x_{t,i})*(Wx_t)_i -
  gamma*x_{t,i}. Linear in (beta, gamma) given x, so fit by plain least
  squares (2 parameters, ~62 training rows -- comfortably determined, no
  regularization needed). Verified exact parameter recovery on noiseless
  synthetic data before trusting it on real data.
- Both new baselines' fitting pairs are restricted to the calibration
  weeks, with the regression TARGET further restricted to genuinely-
  observed cells (n_tested>=10) -- fitting against a carry-forward-
  derived pseudo-target would be circular (carry-forward just repeats old
  information, it isn't new signal about dynamics).
- Linear EDMD ablation = D1 itself, reused as-is (fit on simulated
  trajectories in P6, not refit here) -- decision #13 literally names
  this as one of the baselines to compare the richer dictionaries
  against, so D1 plays double duty: a primary EDMD result AND one of the
  5 named baselines.
- Historical mean baseline: per-ward mean of REAL observed (not filled)
  prevalence over the calibration weeks only.

BUG CAUGHT BY TESTING, a wiring/argument-order mistake, not a math error:
forecast_baseline_iteratively (src/build_p8.py) called
predict_fn(*predict_args, current) where predict_args=(coef, W), which
put the STATIC W matrix into predict_network_exposure's `x` parameter
slot and the per-step STATE VECTOR into its `W` slot -- silently
computing nonsense (a full 6-element array landed in a single-ward 'pred'
cell) rather than raising an error immediately. First noticed as a
np.clip crash three steps downstream in src/metrics.py (a symptom, not
the cause) -- traced back to the actual call site rather than patched at
the crash site. Fixed by making forecast_baseline_iteratively take
coef_args and W as explicit, separately-named parameters instead of
splatting a mixed tuple positionally. Added
tests/test_build_p8.py specifically exercising this wiring end to end
(not just the underlying predict_* functions in isolation, which had
already passed their own unit tests and gave no signal that the caller
was misusing them) -- this is the kind of bug that passes every unit test
on the pieces individually and only shows up when they're wired together,
so the wiring itself needed its own test.

RESULT, reported honestly, an "honest, possibly weak" outcome very much
in the spirit CLAUDE.md anticipated for the simulated-trajectory
comparisons: on the HOLDOUT period (weeks 12-16, the one fair test for
every model), D1/D2/D3 are statistically indistinguishable from
persistence at h=1 (RMSE 0.0465-0.0466 vs persistence's 0.0464, skill
scores -0.001 to -0.006 -- i.e. essentially a wash, consistent with P6's
finding that D1/D2/D3 barely differ from each other). At h=3-4,
historical_mean becomes the best performer by a clear margin (skill
~0.20 vs persistence, RMSE flat at 0.0692 regardless of horizon since it
always predicts the same fixed vector) -- a real, well-known and
defensible forecasting phenomenon: naive/climatology-average methods
often beat both persistence and fitted dynamics at longer horizons for
noisy, mean-reverting series, because the further out you forecast the
closer the true system tends to sit to its long-run average anyway.
network_exposure is the weakest model at nearly every horizon in both
periods (visually confirmed in p8_rmse_by_horizon.png). Plausible
explanation for EDMD's lack of edge over persistence on real data, not
confirmed: K was fit PURELY on simulated trajectories, and P4 already
found the simulator's calibrated dynamics sit on a weak/ambiguous ridge
(near-static, only weakly identified by the noisy ~16-week real series
that calibrated it in the first place) -- it is plausible this
simulation-trained K simply doesn't carry a strong edge onto the real,
sparse, noisy 16-week series it was never fit on. This is exactly the
kind of sim-to-real transfer gap the project's known limitations section
already flags ("about 16 real weekly snapshots only"), now made concrete
with numbers rather than left as a caveat.

Files: results/tables/p8_baseline_params.csv (fitted network-exposure/
ward-SIS coefficients), p8_forecast_records_long.csv (every scored
(model, start, landing, h, ward) row), p8_metrics.csv (full model x
period x h x ward table, raw+clipped, skill vs persistence),
p8_metrics_summary.csv (holdout period, overall-ward quick-read view);
results/figures/p8_rmse_by_horizon.png (calibration vs holdout, all
models), p8_predicted_vs_actual_holdout.png (h=1, all models).

19 new tests (tests/test_baselines.py, test_forecast.py, test_metrics.py,
test_build_p8.py) -- including exact-recovery checks for both new
baselines on noiseless synthetic data, an end-to-end integration check
applying the real fitted D1 model to real P3 data, and the two wiring
tests that caught the argument-order bug above. 159 tests total, all
passing.

Sep 28: P9 superspreader ward risk score vs centrality done
(src/intervention.py, src/risk.py, src/build_p9.py). This is the phase
that actually tests the project's central premise ("identify
superspreader-ward eigenmodes for targeted infection-control
intervention"), so the result below is reported in full rather than
summarized away.

Design choices:
- "Cut a ward's contacts by 50%" = scale EVERY edge touching that ward
  (either endpoint), not just within-ward edges -- a real intervention
  (cohorting, restricted movement) reduces a ward's overall activity,
  including its contact with other wards, not just internal contact.
- Ground truth uses the SAME calibrated (beta, gamma, epsilon) and
  calibration initial condition as P4 (never re-calibrated), with common
  random numbers (same 100 replicate seed pairs) for baseline and every
  intervention -- a paired, variance-reduced comparison, same technique
  as P4's grid search and P6's lambda selection.
- Risk score candidates: the P7 Koopman dominant-mode ward shares (one
  per dictionary), plus three ward-level centrality measures computed
  directly from P2's raw ward contact matrix (never previously computed
  at ward granularity, only person-level in P2): degree/strength
  (row sum -- a ward's total contact-seconds exposure), eigenvector
  centrality, and betweenness centrality (both on the symmetrized W,
  since raw W is directed).
- Compared via ranks (1=highest) across all 6 wards AND Spearman
  correlation against the ground truth, with an explicit caveat
  (CLAUDE.md's own known limitation: "Only 6 groups, so rank statistics
  are weak") printed alongside every correlation number, not just
  mentioned once.

TEST DESIGN CORRECTION, caught before trusting the experiment: the first
version of the bridge-topology correctness test seeded the initial
infection INSIDE one of the three compared wards (a bridge B between
leaf wards A and C) and expected cutting B to show the biggest effect.
It failed -- cutting A (the SEED's own ward) showed a bigger drop than
cutting the bridge B. Investigated rather than weakened the assertion:
this is a real, sensible effect (cutting the source ward's contacts
throttles the epidemic at its most sensitive, earliest stage, which
compounds over the following weeks -- a bigger effect than a downstream
topological bridge for a single-seed start), just not what the test was
trying to isolate. Redesigned with a 4th ward D (the seed source,
excluded from the compared groups) connected only through the bridge B,
so all three compared wards are equally "downstream" of the seed and
only their topological role differs -- this version correctly confirmed
B (bridge) > A, C (leaves).

MAIN RESULT, the actual point of this phase: on the real network (100
replicates per ward, common random numbers), the ground-truth drop in
colonized person-days ranks Menard 1 > Sorrel 1 > Menard 2 > Sorrel 2 >
Sorrel 0 > Other (p9_ground_truth_bar.png). Comparing candidates via
Spearman rho against this ranking:
    degree_centrality        0.943  (p=0.0048)
    eigenvector_centrality   0.714  (p=0.111)
    koopman_D2                0.543  (p=0.266)
    koopman_D3                0.429  (p=0.397)
    betweenness_centrality    0.309  (p=0.552)
    koopman_D1                 0.257  (p=0.623)
SIMPLE DEGREE CENTRALITY -- literally just each ward's row sum in the
already-computed P2 ward contact matrix, no Koopman machinery required --
predicts the simulated ground truth far better than any of the three
Koopman eigenmode risk scores, and is the only candidate whose
correlation survives even a rough Bonferroni correction for testing 6
candidates (0.05/6=0.0083; degree_centrality's p=0.0048 clears that,
nothing else does). None of the three Koopman scores reach conventional
significance. This is an honest negative-ish result for the project's
central premise and is reported as such, not reframed. One nuance worth
keeping in mind rather than either dismissing or over-crediting D1:
koopman_D1 correctly picks Menard 1 as the #1 ward (matching P7's finding
that D1's dominant mode was Menard-1-dominated, while D2/D3's was Sorrel-
1-dominated -- P7 flagged this disagreement for exactly this validation
step) but scrambles the ordering of the remaining 5 wards badly enough
that its OVERALL rank correlation (0.257) is the worst of the three
Koopman variants -- getting the top pick right is not the same as good
rank agreement throughout, and both facts are true simultaneously.
Caveat carried from CLAUDE.md's own known limitations and repeated here
deliberately: n=6 wards is a very small sample for any rank statistic:
the reported correlations and p-values should be read as descriptive,
not confirmatory, findings. The per-replicate variability in the ground-
truth experiment is also substantial (visible in p9_ground_truth_bar.png's
error bars, which show per-replicate std, not the tighter standard error
of the 100-replicate mean -- the means themselves, which is what's
actually compared/correlated, are considerably more precise than the raw
per-replicate spread suggests, but the underlying stochastic simulation
noise is real and should not be understated either).

Files: results/tables/p9_ground_truth_intervention.csv,
p9_ward_scores.csv (raw), p9_ward_ranks.csv,
p9_spearman_vs_ground_truth.csv; results/figures/p9_ground_truth_bar.png,
p9_rank_heatmap.png (visually confirms the same pattern: ground_truth,
degree_centrality, and eigenvector_centrality columns look similar; the
three koopman columns look comparatively scrambled).

12 new tests (tests/test_intervention.py, test_risk.py), including the
corrected bridge-topology experiment-correctness test and hand-checkable
centrality tests (star graph for eigenvector, path graph for
betweenness). 167 tests total, all passing.
