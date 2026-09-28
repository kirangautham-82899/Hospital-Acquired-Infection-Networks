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
- OPEN QUESTION for the user: decision numbering in CLAUDE.md (as pasted
  into this project) doesn't match what was referenced as "Part A" -- e.g.
  D3 (contact-weighted dictionary) is decision #11 here, but was called out
  as decision #13 in Part A, with #11 said to be about simulation scenarios.
  CLAUDE.md's decision *content* was used as-is (unchanged) since that's
  what's in this repo; if Part A is authoritative for numbering, let us know
  and we'll renumber CLAUDE.md to match.
