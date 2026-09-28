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
