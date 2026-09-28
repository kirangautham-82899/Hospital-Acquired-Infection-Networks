# P30: Koopman/EDMD forecasting of MRSA spread on a hospital contact network

## Project
CMDS course project (M.Tech Data Science, Amrita Vishwa Vidyapeetham), topic P30,
team of two. Sir's brief: lift ward-level colonization-state observables from a
dynamic patient-contact graph into a Koopman-operator framework via EDMD, forecast
outbreak trajectories, and identify superspreader-ward eigenmodes for targeted
infection-control intervention.
First review: Oct 6, 2026. Python only, run locally (no Colab).

## Data (data/raw/, READ-ONLY: never modify, never overwrite)
Source: I-Bird study, 200-bed long-term/rehabilitation hospital, Berck-sur-Mer,
France, 2009. Cite Obadia et al. 2015 (PLOS Comput Biol 11(3):e1004170) and
Duval et al. 2018 (Sci Rep 8:1686). Vanhems 2013 is background only, NOT the
data source. Dataset license is unverified: never push data/ to a public repo.

Files use ';' as separator. GOTCHA: each file has an unnamed leading row-number
column (header has one fewer field than the data rows). Always load with
index_col=0 and assert that columns did not shift.
- admission.csv: calc_ident, service_pa_pe (person -> ward/group). PA = patient,
  PE = staff.
- mat.day.csv: from, to, day, length. Contact edges, stored in BOTH directions.
  `length` is probably contact seconds per pair per day (to be confirmed in P1).
- microbio.csv: calc_ident, statut, date_prl, date_prl_posix, ndem, same, sa,
  sasm, sarm, germe, service_pa_pe, age, sexe, strain. One nasal swab per row.
  sarm=1 means MRSA positive; sasm = methicillin-susceptible (MSSA); sa = either.

Groups: 5 real wards (Menard 1, Menard 2, Sorrel 0, Sorrel 1, Sorrel 2) plus
"Other" = the staff-only groups (Autre, Garde de nuit, Kine, Ergo). 6 groups total.

### Reference numbers from a first inspection (RE-VERIFY in P1, do not trust)
- admission.csv: 795 rows; 452 PA, 343 PE; 9 distinct service values;
  no person appears twice (no transfer information).
- mat.day.csv: 124,924 rows; 110 distinct days between 2009-07-01 and 2009-10-25
  (span is 117 days, so 7 days missing); 589 distinct people (329 PA, 260 PE);
  19,974 unique undirected pairs; about 99.9% of rows have a reverse row on the
  same day; length min 60, max 86400, mean about 3886.
- microbio.csv: 6,728 rows; 795 people; 3,369 PA rows and 3,359 PE rows; sarm=1
  in 1,118 rows and sarm=0 in 5,610 rows; dates 2009-05-04 to 2009-10-27;
  295 people MRSA-positive at least once; tests fall on Mon-Thu, about weekly.
- 206 people are in admission.csv but have no contacts; every contact person is
  in admission.csv; every microbio person is in admission.csv.

## Locked decisions (log any change in research_log.md)
1. Contact network only (no transfer records). Transfers = future work.
2. Nodes = the 589 people in mat.day.csv. Keep one row per pair per day.
   Edge weight = contact seconds.
3. State vector = weekly MRSA prevalence in each of the 6 groups (patients and
   staff of a ward pooled). Sensitivity run: patients only, 5 wards.
4. Colonized means sarm=1. MSSA counts as not colonized.
5. Weekly time step for EDMD and validation. The simulation runs daily and is
   aggregated to weeks.
6. Missing tests: main run = prevalence over people tested that week, no
   imputation. Sensitivity run = carry the last result forward up to 2 weeks.
7. Dynamics: individual-level SIS. Daily P(transmit i->j) = 1 - exp(-beta * contact
   hours). Daily decolonization prob gamma. Small importation rate epsilon.
8. Calibrate (beta, gamma, epsilon) by grid search on the first ~70% of weeks.
9. Simulate endemic starts (real prevalence) AND outbreak starts (1-3 seeded
   cases in one ward). At least 300 training trajectories, beta and gamma varied
   0.5x to 2x around calibrated values.
10. EDMD written by us in numpy, ridge-regularized, identity included in the
    dictionary. No Koopman library until our own version works.
11. Dictionaries: D1 linear; D2 degree-2 polynomial; D3 contact-weighted (state,
    squares, W x, x * (W x), W = row-normalized ward contact matrix).
12. Splits: simulation split by trajectory 70/15/15; real data split by time
    (calibrate on first ~70% of weeks, test on the rest).
13. Baselines: persistence, historical mean, network-exposure linear model,
    ward-level SIS model, linear EDMD (ablation).
14. Superspreader ground truth (measured in simulation): cut one ward's contacts
    by 50% and record the drop in colonized person-days.
15. Interventions (equal budget): none, random, whole-hospital, degree-targeted,
    Koopman-targeted. k = 1 and 2 wards; reductions 25/50/75%; 200+ seeds with
    common random numbers.
16. Reproducibility: SEED in config.py, one config.py, Git, requirements.txt.

## Phases
P0 setup | P1 data audit | P2 contact network + ward matrix W | P3 real weekly
prevalence | P4 SIS simulation + calibration | P5 observables | P6 EDMD fit
(first review ends here) | P7 eigenmodes | P8 forecasting, validation, baselines
| P9 superspreader ward risk score vs centrality | P10 intervention simulation
| P11 robustness experiments E1-E8 | P12 report, slides, cleanup.

## Folder layout
data/raw/ data/processed/ | src/ (load, network, states, simulate, calibrate,
observables, edmd, eigen, forecast, baselines, risk, intervention, metrics) |
tests/ | notebooks/ | results/{figures,tables,models}/ | config.py | CLAUDE.md |
research_log.md | README.md | requirements.txt

## Working rules
1. Do ONE phase per instruction and stop. Do not build ahead.
2. After writing code, explain each function briefly in plain language.
3. Put reusable code in src/ as functions; notebooks are only for exploration.
4. Never modify data/raw/. Save derived data to data/processed/.
5. Save every plot to results/figures/ and every table to results/tables/.
6. Fix random seeds. No hidden magic numbers: parameters go in config.py.
7. Say clearly when something is an assumption rather than a verified fact.

## Verification protocol (end of EVERY phase)
- Write pytest tests in tests/ for the phase and run them; show the real output.
- Cross-check at least two numbers by a second, independent method
  (for example the csv module vs pandas, or a hand calculation).
- Print a table: metric | expected | computed | match?
- Never claim a check passed without running it. Report mismatches, do not
  hide them or edit the tests to pass.

## Known limitations (state them in the report)
About 16 real weekly snapshots only. Time-invariant K vs a time-varying contact
network. Only 6 groups, so rank statistics are weak. No admission/discharge
dates. Single hospital, single 4-month window. No transfer records.
