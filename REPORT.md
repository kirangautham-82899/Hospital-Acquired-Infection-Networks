# P30: Koopman/EDMD Forecasting of MRSA Spread on a Hospital Contact Network

**Technical Report**
Kiran Gautham
CMDS Course Project, M.Tech Data Science, Amrita Vishwa Vidyapeetham
Topic P30 · First review: October 6, 2026 · Revised after internal review: November 14, 2026

---

## Abstract

Hospital-acquired MRSA transmission is driven by who contacts whom. This
project builds a full pipeline, from a real hospital contact network through
an individual-level stochastic epidemic simulator to a data-driven
Koopman/EDMD model, and asks two questions: (1) does lifting ward-level MRSA
prevalence into a Koopman-operator framework forecast better than simple
baselines, and (2) do Koopman-based ward scores identify "superspreader"
wards better than plain network centrality? We use the I-Bird hospital
dataset (589 people, 124,924 contact records, 6,728 MRSA swabs,
Berck-sur-Mer, France, 2009), three EDMD dictionaries (linear, degree-2
polynomial, contact-weighted), and ridge-regularized operators fitted on 210
simulated training trajectories (of 300 generated).

The answer to both questions is **no, not for this dataset**. The SIS
calibration is weakly identified: the data bound the decolonization rate
only from above (γ ≲ 2×10⁻³/day), and β and ε only within factors of 4–7.
We therefore rerun the whole downstream pipeline at all nine near-optimal
calibration points along the γ, β and ε profiles (experiment E9) and say,
for each headline claim, whether it holds at every point. On real holdout
weeks no EDMD variant beats a persistence forecast one week ahead at any
point; at 3–4 weeks EDMD is usually tied or slightly worse, and better in
only 2 of 54 model × point × horizon cases. All differences (at most 0.0092
RMSE) are small next to the 0.057 sampling error of a weekly ward
prevalence. For ward ranking, degree centrality matches the main simulated
ground truth (cut each ward's contacts by 50%) at every calibration point
(Spearman ρ = 0.94 at eight points and 0.89 at one, exact p < 0.05 at
all), but that ground truth largely rewards contact volume by construction.
A Koopman score equals degree at one of nine points and otherwise falls
below it, swinging between −0.77 and 0.94. Under a second ground truth that
removes the *same* number of contact-hours from every ward, no candidate
ranks the wards reliably at any point. Targeting wards by contact volume beats random and
whole-hospital allocation in every comparison at every calibration point
(paired 95% CIs exclude zero), but even the best strategy prevents under 5%
of colonized person-days in this model.

---

## 1. Introduction

Methicillin-resistant *Staphylococcus aureus* (MRSA) spreads through hospitals
via person-to-person contact, and infection-control resources (isolation,
cohorting, targeted screening) are finite. A natural question for a hospital
epidemiologist is: **which ward, if any, is disproportionately responsible
for spread, and would intervening there actually help more than a
blanket or random policy?**

The Koopman operator framework offers an appealing answer in principle:
lift a nonlinear epidemic's state into a richer observable space, fit a
*linear* operator (via Extended Dynamic Mode Decomposition, EDMD) that
approximately advances that lifted state one time step, and read off the
operator's eigenmodes and responses as the system's characteristic
patterns. A contact-network-weighted dictionary might let the operator
encode which wards drive which other wards.

This project builds that pipeline end to end on a real hospital contact
network and does not stop at fitting the model. It asks whether a
Koopman-based ward ranking is *actually better* than the obvious,
nearly-free alternative (a ward's raw contact volume), using **simulated
ground-truth experiments** (cutting a ward's contacts and measuring the
epidemiological effect) as the arbiter.

**Roadmap.** Section 2 describes the data and its audit. Section 3 covers
methods: the contact network (§3.1), real weekly prevalence (§3.2), the
calibrated SIS simulator (§3.3), the EDMD dictionaries (§3.4), the EDMD fit
(§3.5), and eigenmode and influence analysis (§3.6). Section 4 presents
results: real-data forecasting (§4.1), the superspreader comparison (§4.2),
intervention simulation (§4.3), and robustness experiments (§4.4).
Section 5 discusses, Section 6 states limitations, Section 7 concludes.

**Revision note (November 14, 2026).** An internal review of the first
version found six problems: the calibration optimum sat on the edge of its
search grid; the main superspreader ground truth was close to circular for
degree centrality; the Koopman ward score measured the equilibrium pattern
rather than influence; intervention differences were reported without
uncertainty; "statistically indistinguishable" was claimed without a test;
and unstable eigenvalues were not reported. All six are fixed in this
version (details in §3.3, §3.6, §4.1–4.3 and `research_log.md`). Fixing the
calibration changed several downstream numbers; where a conclusion changed,
this report says so. A second review pass found that the main results still
rested on one arbitrary point of an unidentified calibration ridge, and that
"measurably worse than persistence" leaned on a 5-block bootstrap.
Experiment E9 (§4.4) now reruns P4–P10 at every near-optimal calibration
point, and every headline claim states whether it holds across all of them. A third pass extended E9 from the γ profile to
the β and ε profiles (nine points in all) and strengthened the equal-hours
ground truth, which had too little signal to rank anything.

Every number below is read from the saved `results/tables/*.csv` outputs of
a full pipeline run (`python run_all.py`).

---

## 2. Data

**Source.** The I-Bird study: a 200-bed long-term/rehabilitation hospital in
Berck-sur-Mer, France, 2009 (Obadia et al. 2015, *PLOS Computational
Biology* 11(3):e1004170; Duval et al. 2018, *Scientific Reports* 8:1686).
Three files: `admission.csv` (person → ward), `mat.day.csv` (daily contact
edges, RFID-sensor-derived, stored in both directions), `microbio.csv` (nasal
swab MRSA test results). The dataset's license is unverified, so the raw
files are excluded from this repository.

**Audit (P1).** Every one of the 19 "first inspection" reference numbers in
the project plan was independently re-verified against the raw CSVs, with
zero adjustments needed:

| File | Rows | Key facts |
|---|---|---|
| `admission.csv` | 795 | 452 patients (PA), 343 staff (PE); 9 distinct service values, all mapping cleanly to 6 ward groups |
| `mat.day.csv` | 124,924 | 589 distinct people (329 PA, 260 PE); 19,974 unique undirected pairs; 110 of 117 days present (7 missing: Jul 21–23, Aug 28–29, Sep 18–19); contact length 60–86,400s (mean 3,886s); 99.9% row-level reciprocity |
| `microbio.csv` | 6,728 | 795 people tested; sarm=1 (MRSA+) in 1,118 rows, sarm=0 in 5,610; 295 people MRSA-positive at least once; `date_prl` == `date_prl_posix` for every row |

206 admission people have zero contact records (excluded from the network by
construction). All cross-checks (pandas vs. the stdlib `csv` module, SHA-256
hashes of the raw files) confirmed the loaders are reading the data
correctly and never modifying `data/raw/`.

---

## 3. Methods

### 3.1 Contact Network Construction (P2)

**Nodes and edges.** The 589 people appearing in `mat.day.csv` are the
network's nodes. Each day's contact is recorded from both sides; **these
disagree ~17% of the time** (median gap ~90 seconds, consistent with
independent per-device sensor reads rather than data corruption). The
person-level deduplicated edge list averages both directions when both
exist and uses the single value when only one does, producing a master
edge list of 62,534 (day, pair) rows.

**Ward contact matrix W.** Deliberately built differently from the
person-level network: W sums the *raw, non-deduplicated* bidirectional rows,
so `W[i,j]` represents the total contact-seconds people in ward *i* spent
with people in ward *j* — each person's own exposure. This makes the
diagonal approximately twice the undirected within-ward total (verified
ratio 1.998–2.000 across wards, the ~0.1% deviation coming from the ~144
rows with no reciprocal partner). Row-normalized W is used throughout for
the network-weighted EDMD dictionary; the raw version, summed per ward,
gives a simple **degree/strength centrality** that turns out to matter a
great deal in §4.2. Within-ward contact accounts for 90.3% of total
contact-seconds (94.0% in the patients-only population), confirming that
pooling patients and staff per ward is a reasonable state definition.

**A methodological correction with real consequences.** The first version
of the weekly binning anchored week 0 at the study start date (2009-07-01,
a *Wednesday*). Since MRSA swabs are taken Monday–Thursday, this cut each
ward's weekly screening round across two bins: 655 of 3,812 person-weeks
(17.2%) fell into more than one bin. Anchoring weeks at the preceding
**Monday** instead reduced this to 80 of 4,412 (1.8%). All downstream weekly
aggregation (P3 onward) uses Monday-anchored bins; the 117-day contact
window spans 17 such weeks (weeks 0–16, week 0 = Mon 2009-06-29–Sun
2009-07-05, containing 5 days of contact data; week 16 ends exactly on the
study's last day).

### 3.2 Real Weekly Prevalence (P3)

The **state vector** is weekly MRSA prevalence in each of 6 ward groups (5
real wards + "Other" for staff-only service categories), built only from
people who are *both* tested that week *and* present in the 589-person
contact network (581 of 666 in-window-tested people qualify — the
difference from using all 666 changes prevalence estimates by at most 0.056
across all group-weeks, confirming the restriction is not materially
distorting). A person counts as positive for a week if *any* test that week
was positive, and counts once in the denominator regardless of test count
(verified against an independent hand-recomputation from the raw CSV for
two spot-checked cells, exact match both times).

Group-weeks with fewer than 10 tested people are flagged, not dropped (4 of
93 non-empty group-weeks); 9 of the 102 possible (17 weeks × 6 groups)
combinations have zero tested people and are correctly absent rather than
synthesized as 0% prevalence. A carry-forward sensitivity series (fills a
gap with a person's last known status, up to 2 weeks) is built and clearly
labeled a robustness check only — never a validation target, until reused
explicitly for that purpose in §4.4 (E7).

### 3.3 SIS Simulation & Calibration (P4)

**Mechanism.** A daily, individual-level susceptible–infected (SIS) process
on the 589-person contact network. For each susceptible person, the daily
transmission probability from contacts is `1 − exp(−β·H(t))`, where `H(t)`
is that day's total contact-hours with currently-colonized neighbors (this
exponential-in-the-sum form was verified analytically: a hand-built 2-person
network with known contact hours gave an empirical infection probability
matching the closed-form prediction over 20,000 Monte Carlo replicates).
Colonization can also arise independently via a small daily importation
probability ε (representing reintroduction from outside the tracked
network), and each colonized person independently decolonizes with daily
probability γ. The population is closed: nobody is admitted or discharged.

**Calibration.** A 500-point grid search (10 β × 10 γ × 5 ε, β and γ each
spanning three orders of magnitude) with 20 replicates per point (common
random numbers), scored against the real weekly prevalence on the
calibration weeks (0–11) only. Each *tested* person's *simulated* status is
read on their *real* test date, so the comparison is like with like. If the
best point lands on a grid edge, that axis is widened 3× and the search
rerun, up to 3 times.

**Result: the best point is interior, but the decolonization rate is
only bounded from above.** The best point is β = 7.9×10⁻⁴ per contact-hour,
γ = 2.2×10⁻⁴/day, ε = 2.7×10⁻⁴/day (calibration loss 0.00497; holdout loss
0.00890, never used for selection). No widening was needed. The *profile
loss* (best loss over the other two parameters, for each value of one
parameter; `p4_profile_loss.png`) shows how well each parameter is pinned
down:

| Parameter | Best | Values within 5% of the best loss | Spread |
|---|---|---|---|
| β (per contact-hour) | 7.9×10⁻⁴ | 2.0×10⁻⁴ – 7.9×10⁻⁴ | 4× |
| γ (per day) | 2.2×10⁻⁴ | 1.0×10⁻⁴ (grid minimum) – 2.2×10⁻³ | ≥ 22× |
| ε (per day) | 2.7×10⁻⁴ | 1.0×10⁻⁴ (grid minimum) – 7.1×10⁻⁴ | ≥ 7× |

The γ profile is flat from the smallest value tried up to about
2×10⁻³/day and rises steeply above it. **The data therefore say only that
decolonization is slow on the 17-week scale (γ ≲ 2×10⁻³/day, mean carriage
of at least about 460 days); they cannot say how slow.** The chosen point
corresponds to almost no decolonization within the window. Long MRSA
carriage is commonly reported in long-term care settings, so this is not
in itself implausible, but the specific value is not identified. (The first
version of this report quoted γ = 1.67×10⁻³ as "the" fit and called it
implausible; that point lies inside the near-optimal set above, and the
first grid simply stopped too early.)

**Consequence for everything downstream.** With almost no decolonization
in a closed population, simulated prevalence can only drift upward:
endemic training trajectories rise on average from 0.194 to 0.248 over 16
weeks. The real series does the opposite in the holdout weeks (pooled
prevalence 0.155–0.193 in weeks 9–12, 0.116–0.125 in weeks 13–16). This
sim-to-real mismatch drives the forecasting result in §4.1.

**Training trajectories.** 300 simulated 17-week trajectories: 150
*endemic* starts (each ward's initial prevalence drawn from a randomized
multiplier on its real baseline, independently per ward per trajectory) and
150 *outbreak* starts (1–3 seeded cases in one randomly chosen ward). β and
γ are independently varied 0.5×–2× around their calibrated values per
trajectory; ε is held fixed. Trajectories are split 70/15/15 (210 train / 44 validation / 46 test; the split is by whole trajectory).

### 3.4 Observables / Koopman Dictionaries (P5)

Three dictionaries lift the raw 6-dimensional state `x` (ward prevalence)
into a higher-dimensional observable space for EDMD:

| Dictionary | Definition | Features (n=6) |
|---|---|---|
| **D1** (linear) | `[1, x]` | 7 |
| **D2** (degree-2 polynomial) | `[1, x, x², x_i·x_j (i<j)]` | 28 |
| **D3** (contact-weighted) | `[1, x, x², Wx, x⊙(Wx)]` | 25 |

The constant `1` is included in every dictionary (a decision made explicitly
here, distinct from "the raw state is a dictionary feature," which was
already true by construction): the simulator's importation term ε makes the
dynamics affine, and an operator with no offset term cannot represent that.
D1 with the constant is also the natural "linear EDMD" ablation baseline
used later (§4.1).

**A conditioning finding that foreshadows a major result.** The training
snapshot matrix's condition number is 40.5 for D1, 1,244 for D2, and
**8.8×10¹⁶ for D3 — numerically singular**. This was diagnosed, not just
observed, and the diagnosis is confirmed rigorously in §3.5.

### 3.5 EDMD Fit (P6)

Ridge-regularized EDMD, implemented from scratch in NumPy (no external
Koopman library, per the project's locked constraints): fit `K` such that
`φ(x_{t+1}) ≈ K φ(x_t)`, using training-split trajectory pairs only, with a
constant-aware scaler (every non-constant feature is standardized; the
constant is left as exactly 1 and excluded from the ridge penalty — a
property confirmed by a synthetic test showing that shifting every training
target by a constant vector changes *only* the operator's constant column,
bit-for-bit) and a numerically stable `lstsq`-based solve on an augmented
system (never an explicit matrix inverse, which would be dangerous given
D3's near-singularity).

**Major finding: D3 adds no function space beyond D2.** This was proven
analytically before any code was written on top of it, then confirmed
empirically. For a fixed, invertible ward contact matrix W (confirmed
invertible: all 6 eigenvalues nonzero, smallest 0.443), `Wx` is a purely
linear function of `x`, so it spans exactly the same subspace as `x` — zero
new rank. `x_i·(Wx)_i` is a fixed linear combination of D2's own square and
cross terms. **D3's 25 raw features therefore have an effective rank ceiling
of 19** (1 constant + 6 linear + 6 square + 6 from the one genuinely new
nonlinear block). The fitted D3 operator has `rank(K) = 19` of 25, exactly
as predicted (training snapshot matrix condition number 8.8×10¹⁶ for D3 vs
40.5 for D1 and 1,244 for D2), while D1 (7 of 7) and D2 (28 of 28) are full
rank. **D3 therefore tests whether a contact-structured *prior* helps, not
whether network information is injected; it structurally cannot add
information beyond D2.** A genuinely network-aware dictionary would need the
*week-specific* contact matrix `W_t` — future work.

**λ selection.** A 20-point log-spaced grid (10⁻⁶ to 10³) per dictionary,
selected on the validation split by mean RMSE over horizons 1–4 (in
original prevalence units). Selected λ: D1 = 0.16, D2 = 0.48, D3 = 0.48,
none on a grid edge. The validation curve is flat from 10⁻⁶ to about 1 and
rises past about 10: regularization strength barely matters here.

**Simulated-trajectory result.** On the 46 held-out test trajectories, D1,
D2 and D3 perform almost identically (h=1 RMSE 0.00519, 0.00522, 0.00516 vs
persistence 0.00611), beating persistence by 15% at h=1 and 26–28% at h=4.
D2 does not beat D1; D3 is marginally best at every horizon.

**Stability (reported after review).** Every operator has eigenvalues
outside the unit circle: spectral radius 1.0144 for D1, 1.0218 for D2 and
1.0156 for D3. Counting eigenvalues of magnitude ≥ 1 gives 6 of 7 (D1), 13
of 28 (D2) and 8 of 25 (D3); each count includes one eigenvalue of exactly 1
that comes from the constant feature (K row 0 is exactly [1, 0, …, 0]). The
rest are slightly above 1 and reflect the slow upward drift of the
simulated training data (§3.3). Iterated far beyond the training horizon, these
operators grow without bound (for example 1.0218¹⁶ ≈ 1.41 over 16 weeks);
within the 1–4-week horizons used here the growth is mild but measurable
(§4.1).

### 3.6 Eigenmode and Influence Analysis (P7)

Each fitted `K`'s eigenvalues and eigenvectors are computed, mapped back to
ward space via the readout and correctly *un-scaled* to original prevalence
units (a similarity transform: `K_z = D⁻¹ K_orig D` for `D = diag(scale)`,
so a scaled-space eigenvector must be *multiplied* by the scale vector — the
first implementation divided, and a synthetic test caught it). D3's 6
spurious null-space eigenvalues (from the proven rank deficiency) are
filtered using the rank cutoff, validated against a clean ~10¹²-fold gap in
eigenvalue magnitude between the 19th and 20th largest.

**Dominant-mode ward shares.** The largest-magnitude ward-relevant mode's
ward shares are: D1 λ = 1.0144, Menard 1 (56.6%); D2 λ = 1.0218, Sorrel 2
(33.8%); D3 λ = 1.0156 ± 0.031i (period about 200 weeks), Menard 1 (59.5%).
**What this score measures (corrected after review):** a right eigenvector
of the slowest mode describes the spatial *shape* of the most persistent
pattern (where the long-run drift or equilibrium sits), not which ward
*drives* spread. It was the project's original "Koopman superspreader
score" and is kept for comparison, but it was never a direct measure of
influence.

**Koopman influence score (added after review, `src/influence.py`).** To ask
the influence question with the operator alone: start from the real
calibration-weeks mean state, add 3 extra colonized people to ward *j*
(prevalence step 3/N_j, so large and small wards are seeded equally),
roll K forward 16 weeks, and sum the predicted extra colonized
person-weeks over all wards (total) and over the other wards only
(spillover). A seeded case that simply persisted would give 3 × 16 = 48.

| Ward | D1 total | D2 total | D3 total |
|---|---|---|---|
| Menard 1 | **56.8** | 55.6 | **57.6** |
| Menard 2 | 54.0 | **56.7** | 53.3 |
| Sorrel 0 | 47.9 | 44.6 | 44.9 |
| Sorrel 1 | 47.6 | 44.7 | 45.7 |
| Sorrel 2 | 49.2 | 48.6 | 48.2 |
| Other | 50.9 | 41.3 | 45.4 |

Spillover is small (−5.5 to +6.5 person-weeks) and sometimes negative,
which no transmission process can produce; the negative values are an
artefact of the fitted quadratic terms and a reminder that these operators
extrapolate poorly away from the training data. All three dictionaries put
the two Menard wards on top.

---

## 4. Results

### 4.1 Forecasting Validation on Real Data (P8)

This is the first point where the EDMD operators (fit purely on simulated
trajectories) touch real data. Real starting states prefer genuine test
observations and fall back to the P3 carry-forward series for gaps;
forecasts are scored only against genuinely-observed cells (n_tested ≥ 10).
Baselines: persistence, historical mean, a pooled 3-parameter
network-exposure linear model and a 2-parameter mean-field ward-level SIS
model (both verified by exact parameter recovery on noiseless synthetic
data).

**Testing the differences (added after review).** Each model's RMSE is
compared with persistence's on the same scored cells by a paired block
bootstrap (10,000 resamples of whole forecast-start weeks, since cells from
one start week share errors). Only 5 start weeks feed each holdout horizon,
so these intervals are rough. As a yardstick, the RMS binomial sampling SE
of an observed weekly ward prevalence in the holdout is 0.057.

Holdout weeks 12–16, RMSE difference vs persistence (positive = worse than
persistence), with 95% bootstrap CI:

| Model | h=1 | h=3 | h=4 |
|---|---|---|---|
| D1 | +0.0006 [−0.0005, +0.0014] | **+0.0033 [+0.0005, +0.0049]** | **+0.0053 [+0.0007, +0.0079]** |
| D2 | +0.0005 [−0.0005, +0.0014] | **+0.0029 [+0.0000, +0.0048]** | +0.0044 [−0.0004, +0.0068] |
| D3 | +0.0008 [−0.0004, +0.0018] | **+0.0037 [+0.0009, +0.0054]** | **+0.0058 [+0.0003, +0.0088]** |
| ward-level SIS | +0.0010 [−0.0066, +0.0050] | −0.0118 [−0.0299, +0.0054] | −0.0023 [−0.0188, +0.0213] |
| historical mean | **+0.0228 [+0.0110, +0.0384]** | −0.0173 [−0.0427, +0.0078] | −0.0176 [−0.0402, +0.0037] |

(Persistence RMSE: 0.0464 at h=1, 0.0865 at h=3, 0.0868 at h=4.)

**Result at the main calibration point.** At h=1 the EDMD forecasts cannot
be told apart from persistence (differences under 0.001, about 1/60 of the
sampling SE). At h=3–4 they are slightly worse, and for D1 and D3 the CIs
exclude zero. This is a small effect resting on weak evidence: the largest
gap (0.0058) is about a tenth of the sampling SE, and percentile bootstrap
intervals built from only 5 clusters tend to be too narrow. The direction is
explained by the sim-to-real mismatch from §3.3: at this point the operators
learned the simulator's slow upward drift, while real prevalence fell in the
holdout. The historical mean is the best model at h=3–4 by point estimate
(skill ≈ 0.20 vs persistence), but its advantage is not significant with 5
start weeks.

**Across the calibration ridge (E9, §4.4).** Rerunning P4–P8 at all nine
near-optimal calibration points:

| Horizon | EDMD RMSE − persistence (27 model × point cases) | CI excludes 0: worse / better |
|---|---|---|
| h=1 | −0.0003 to +0.0011 | 0 / 0 |
| h=2 | −0.0021 to +0.0016 | 0 / 2 |
| h=3 | −0.0023 to +0.0055 | 13 / 2 |
| h=4 | −0.0011 to +0.0092 | 13 / 0 |

The long-horizon gap is positive wherever decolonization is slowest (the
six points with γ ≤ 2.2×10⁻⁴, where the operators grow fastest), near zero at
γ = 10⁻³, and slightly negative only for D2 (h=2, two points) and D2/D3 (h=3)
at γ = 2.2×10⁻³. **The statement that holds at every point is: EDMD
forecasts are practically indistinguishable from persistence one week
ahead, and are not reliably better at any horizon.** Whether they are
slightly worse depends on parameters the data cannot pin down.

### 4.2 Superspreader Ward Risk Score vs. Centrality (P9)

**Two ground truths**, both measured in the simulator with the calibrated
parameters, 100 replicates and common random numbers (95% paired CIs in
`p9_ground_truth_bar.png`):

- **A — 50% cut (locked decision 14).** Cut *all* contacts touching one ward
  by 50% and record the drop in colonized person-days. Ranking: Menard 1
  (241, CI 208–275) > Sorrel 1 (131) > Menard 2 (112) > Sorrel 2 (55) >
  Sorrel 0 (43) > Other (27). **Caveat found in review:** a 50% cut removes
  more contact-hours from a high-volume ward (Menard 1 touches 30,730
  contact-hours; Other touches 3,204), and in this simulator infection risk
  rises with contact-hours. Degree centrality, which *is* contact volume, is
  therefore expected to match ground truth A largely by construction.
- **B — equal contact-hours (added after review).** Remove the *same*
  2,884 contact-hours from each ward (90% of the smallest ward's volume:
  Other keeps 10% of its contacts, Menard 1 loses 9%), with 400 replicates.
  This asks which ward's contact-hours matter most *per hour*, which no
  score answers by construction. Drops (95% CI): Sorrel 1 69.6 (61.6–77.5),
  Sorrel 0 51.3 (44.2–58.3), Menard 2 49.4 (43.0–55.8), Menard 1 42.6
  (35.2–50.1), Other 39.4 (33.6–45.2), Sorrel 2 33.1 (27.7–38.5). Sorrel 1
  is clearly first and Sorrel 2 last; the middle four partly overlap. (A
  first version removed only half as much, 1,602 hours, with 100
  replicates; its drops of 20–44 person-days overlapped almost entirely and
  had too little signal to rank anything.)

**Spearman ρ vs each ground truth** (n = 6 wards; p-values are *exact*
permutation p-values over all 720 orderings, replacing scipy's
t-approximation, which is unreliable at n = 6):

| Candidate | ρ vs A | p | ρ vs B | p |
|---|---|---|---|---|
| degree centrality | **0.943** | **0.017** | 0.200 | 0.71 |
| Koopman D3 mode share | 0.829 | 0.058 | 0.600 | 0.24 |
| Koopman D3 influence | 0.771 | 0.10 | −0.257 | 0.66 |
| eigenvector centrality | 0.714 | 0.14 | 0.314 | 0.56 |
| Koopman D2 influence | 0.714 | 0.14 | −0.029 | 1.00 |
| Koopman D1 mode share | 0.600 | 0.24 | −0.314 | 0.56 |
| betweenness centrality | 0.309 | 0.53 | 0.802 | 0.10 |
| Koopman D1 influence | 0.257 | 0.66 | −0.486 | 0.36 |
| Koopman D2 mode share | −0.371 | 0.50 | −0.086 | 0.92 |

**Reading.** (1) Against A, degree centrality is best (one adjacent swap
from a perfect ranking), and it is the only candidate whose exact p is
below 0.05; but because of the construction caveat this mostly confirms
that "volume" drives ground truth A. (2) Against B, *no* candidate ranks
the wards reliably. The highest ρ is betweenness centrality (0.80,
p = 0.10), but that score is 0 for three of the six wards, so the ranking
rests on ties; degree (0.20) does no better than chance, which confirms that
B removes the volume effect. (3) The Koopman scores do not beat degree on A
and are not better than chance on B; the new influence score does not
change this. (4) Across all nine near-optimal calibration points (E9),
degree's ρ against A is 0.943 at eight points and 0.886 at the lowest-β
point (exact p < 0.05 at all nine), while the Koopman scores move a lot:
mode share D3 from −0.77 to 0.94 (equal to degree at one point, below it at
the other eight), influence D3 from 0.09 to 0.83, and their top ward changes
between points. Against B, the only correlations with exact p < 0.05 at any
point are *negative* (influence D3, ρ = −0.89 at the lowest-β point): no
candidate ranks the wards reliably in the right direction anywhere.

### 4.3 Intervention Simulation (P10)

Strategies compared under an **equal budget** (`budget = k × R` for k
targeted wards each reduced by fraction R; whole-hospital spreads
`budget/6` over all 6 wards): none, random, whole-hospital,
degree-targeted, Koopman mode-share-targeted (D1/D2/D3) and Koopman
influence-targeted (D1/D2/D3). k = 1, 2; R = 25/50/75%; 200 replicates with
common random numbers. **Added after review:** a 95% paired CI for every
strategy's drop, and paired comparisons of every strategy against
degree-targeted, random and whole-hospital in every (k, R) cell
(`p10_pairwise_comparisons.csv`). Baseline burden: 10,659 colonized
person-days.

**Findings.**

1. **Targeting by contact volume beats untargeted allocation.**
   Degree-targeted beats both random and whole-hospital in all 6 cells
   (all CIs exclude zero); for example at k=2, R=75% it prevents 489
   person-days (CI 456–521) vs 285 for random and 286 for whole-hospital.
   It also beats both in all 36 E9 comparisons (two cells × nine
   calibration points × two references).
2. **Not every score helps.** Koopman D2 mode-share targeting (Sorrel 2,
   then Sorrel 2 + Sorrel 0) is *worse* than both random and whole-hospital
   in all 6 cells. The first version's claim that "almost any" score beats
   untargeted allocation is withdrawn.
3. **Koopman vs degree.** The D1/D3 influence scores pick exactly the same
   wards as degree in every cell (Menard 1; Menard 1 + Menard 2). Koopman
   D3 mode-share picks Menard 1 + Sorrel 1 at k=2: it ties degree at
   R = 25% (+1.2, CI −12.2 to +14.6) and 50% (+7.0, CI −12.4 to +26.4) and
   beats it at R = 75% (+30.9 person-days, CI +6.9 to +54.9, p = 0.012).
   That single significant cell is one of 48 comparisons against degree.
   It also does not survive E9: across the nine calibration points,
   Koopman-targeted strategies beat degree in 2 of 108 comparisons (this
   cell at two points), lose in 51 and tie in 55. The Koopman D3 influence
   score usually picks the same wards as degree (16 ties, 2 losses). No
   Koopman choice beats degree reliably.
4. **Random vs whole-hospital** cannot be told apart in any cell.
5. **Effect sizes are small.** The best strategy prevents 4.9% of colonized
   person-days (Koopman D3, k=2, R=75%); degree-targeted 4.5%. With almost
   no decolonization (§3.3), people colonized at the start stay colonized,
   so contact cuts can only prevent new acquisitions. The first version's
   phrase "targeting matters enormously" overstated this.

### 4.4 Robustness Experiments E1–E9 (P11)

Each experiment perturbs one axis and reports a Spearman ρ (rank-based) or
RMSE ratio (magnitude-based) against the corresponding baseline result.
E1–E6 test ground truth A or degree centrality, not the Koopman scores.

| # | Experiment | What it probes | Result |
|---|---|---|---|
| E1 | Seed sensitivity | A different global seed for ground truth A | ρ = 0.943 |
| E2 | λ sensitivity | Refit at 0.1×/10× the selected λ, re-score real holdout | max \|ratio − 1\| = 0.016 |
| E3 | Replicate-count convergence | 30 / 300 replicates vs the standard 100 | ρ = 1.000 (both) |
| E4 | Calibration ridge point | Ground truth A at γ = 2.2×10⁻³ (other end of the ridge) | ρ = 1.000 |
| E5 | W's time window | W from calibration weeks only vs the whole period | ρ = 1.000 |
| E6 | Patients-only population | 329-person, 5-ward population (locked sensitivity run) | ρ = 1.000 |
| E7 | Missing-data handling | Carry-forward vs no-imputation scoring, D1/D2/D3 ranking | ρ = 0.50 |
| E8 | D3 structural redundancy | Drop the provably redundant Wx block (19 vs 25 features) | RMSE ratio 0.999, dominant ward **differs** (Menard 1 → Sorrel 2) |
| E9 | Calibration ridge, full pipeline | Rerun P4–P10 at all 9 near-optimal points on the γ, β and ε profiles | see below |

**Reading.** Ground truth A's ward ranking is very stable (E1, E3–E6): it is
driven by Menard 1's large contact volume, a fixed feature of the data. E7's
ρ = 0.50 ranks three models whose holdout RMSEs differ by under 0.0003, so
it reflects ties, not instability. E8 shows that removing a block that adds
no function space leaves forecasts unchanged but changes the dominant
mode's top ward: **the eigenmode ward shares are fragile** even when the
forecasts are not. The E1 value equals degree's ρ against A by coincidence:
both are one adjacent-rank swap out of 6, the smallest non-zero
perturbation (derivation in `research_log.md`).

**E9: the whole pipeline across the near-optimal calibration points
(`src/ridge_sensitivity.py`).** For each of γ, β and ε, and each of its grid
values whose profile loss is within 5% of the best, E9 takes the
loss-minimizing values of the other two parameters. The union is nine
points: five along γ (1.0×10⁻⁴ to 2.2×10⁻³/day), two more along β (2.0×10⁻⁴
and 4.0×10⁻⁴ per contact-hour) and two more along ε (1.0×10⁻⁴ and 7.1×10⁻⁴
per day at β = 4.0×10⁻⁴ or the main β). At each point E9 regenerates the 300
training trajectories with the main pipeline's seeds, refits D1–D3 with λ
selection, recomputes mode shares and influence scores, reruns the
real-data forecast test, both ground truths (A: 100 replicates, B: 400) and
two P10 cells (k=1, R=50% and k=2, R=75%; 200 replicates). At the main point
E9 reproduces the main pipeline's numbers exactly, an end-to-end check of
the rerun.

| Quantity | Range over the 9 points | Holds at every point? |
|---|---|---|
| EDMD spectral radius | 1.000 – 1.027 (slower decolonization → larger) | — |
| EDMD vs persistence, h=1 | −0.0003 to +0.0011, never significant | yes: no difference |
| EDMD vs persistence, h=3–4 | −0.0023 to +0.0092; worse in 26, better in 2 of 54 | no: depends on the point |
| ρ(degree, ground truth A) | 0.886 – 0.943, exact p < 0.05 at all | yes |
| ρ(Koopman D3 mode share, A) | −0.771 – 0.943 | no |
| ρ(Koopman D3 influence, A) | 0.086 – 0.829 | no |
| ρ(any candidate, ground truth B) | −0.886 – 0.829; only significant values are negative | yes: none reliable |
| Degree-targeted vs random / whole-hospital | better in 36 of 36 | yes |
| Koopman-targeted vs degree-targeted | better 2, worse 51, tied 55 of 108 | yes: never reliably better |

Figure `p11_e9_ridge_sensitivity.png` plots the forecast gap and the
Spearman values at each point.

---

## 5. Discussion

1. **The machinery is sound.** EDMD recovers known linear and quadratic
   systems exactly, agrees with the closed-form ridge solution, uses a
   stable solver and a clean train/validation/test split; the D3
   redundancy is proven and confirmed.

2. **Forecasting: no gain on real data, and the reason is the simulator,
   not the operator.** EDMD beats persistence on simulated test
   trajectories (15–28% at the main point; 5–22% at h=1 across the E9
   points) but not on real data, at any calibration point. The calibrated simulator is a closed population with
   little or no decolonization; it drifts upward, while the real holdout
   declined. Any model trained on it inherits that drift, and how much
   depends on γ, which the data cannot pin down. A simulator with
   admissions and discharges would be needed to represent decline.

3. **Superspreader ranking: the main ground truth mostly measures volume.**
   Degree centrality "wins" ground truth A largely by construction. Under
   an equal-hours ground truth nothing, Koopman or centrality, ranks
   reliably, and with 6 wards there is little power to tell candidates
   apart. The honest conclusion is not "centrality beats Koopman" but
   "neither approach demonstrates superspreader detection beyond contact
   volume on this dataset."

4. **Koopman scores depend on poorly identified parameters.** Across the
   nine near-optimal calibration points (E9) the Koopman scores'
   correlation with ground truth A ranges from −0.77 to 0.94 and their top
   ward changes, and E8 shows mode shares are fragile even at a fixed
   point. Degree centrality needs no simulator and is significant against
   ground truth A at every point. Scores derived from the simulator cannot be more reliable than
   the simulator's calibration.

5. **Practical message.** Concentrating a fixed contact-reduction budget on
   the highest-volume wards beats spreading it evenly or choosing wards at
   random, with paired CIs excluding zero at every budget and every
   calibration point. The absolute gain in this model is small (under 5% of
   colonized person-days).

A time-varying network-aware dictionary (week-specific `W_t`) and a
simulator with patient turnover are the two most promising extensions.

---

## 6. Limitations

- **About 16 real weekly snapshots.** The decolonization rate is identified
  only from above; β and ε are each identified within a factor of 4–7. E9
  reruns the pipeline at all nine near-optimal points and shows which
  conclusions survive this; the Koopman scores and the long-horizon
  forecast gap do not. The near-optimal set itself depends on a chosen 5%
  tolerance, 20 calibration replicates and a 10-point grid.
- **Few forecast start weeks.** Each holdout horizon has only 5 start weeks,
  so the block-bootstrap CIs in §4.1 are rough and likely too narrow.
- **Closed population.** No admission or discharge dates, so the simulator
  cannot reproduce declining prevalence. This is the main reason for the
  sim-to-real forecasting gap.
- **Ground truth from the same simulator.** Both ground truths and the
  Koopman scores come from the same calibrated simulator, so they share its
  calibration uncertainty; there is no real-world intervention outcome.
- **Only 6 ward groups.** Rank statistics have little power (exact p-values
  are reported); many P10 comparisons were made, so isolated significant
  cells should be read with that in mind.
- **Time-invariant K vs a time-varying contact network.** D3 uses one fixed
  W; E5 shows this does not change degree ranking, but a `W_t` dictionary
  was not built.
- **Single hospital, single 4-month window, no transfer records.**

---

## 7. Conclusion

This project built a complete, tested pipeline from a real hospital contact
network to a Koopman/EDMD forecasting and ward-targeting system, and used it
to test its own central hypothesis. For this dataset, Koopman/EDMD forecasts
do not beat persistence on real data, and no Koopman-based score identifies
high-impact wards better than contact volume; both statements hold at every
near-optimal calibration point (E9). A review of the first
version showed that earlier conclusions were stronger than the evidence:
the decolonization rate is not identified, and the main ground truth largely
rewards contact volume by construction. Both are now fixed and reported,
and every headline claim was rechecked at all nine near-optimal
calibration points.
What holds up is that, in this model, targeting the highest-contact wards
beats untargeted allocation at every budget and every calibration point,
although the absolute effect is small. Future work should add
patient turnover to the simulator, build a week-specific network dictionary,
and use a larger or multi-site dataset.

---

## References

- Obadia, T., Silhol, R., Opatowski, L., Temime, L., Legrand, J., Thiébaut,
  A.C.M., et al. (2015). Detailed Contact Data and the Dissemination of
  *Staphylococcus aureus* in Hospitals. *PLOS Computational Biology*,
  11(3):e1004170.
- Duval, A., Obadia, T., Martinet, L., Boëlle, P.Y., Fleury, E., Guillemot,
  D., et al. (2018). Measuring dynamic social contacts in a rehabilitation
  hospital: effect of wards, patient and staff characteristics. *Scientific
  Reports*, 8:1686.

---

## Appendix A: Reproducibility

See [README.md](README.md) for setup and `python run_all.py` to reproduce
every table and figure referenced above from the raw data. The full
phase-by-phase engineering log, including the November 14 review fixes, is
in [research_log.md](research_log.md).

## Appendix B: Software Summary

- **32 modules** in `src/`, one per pipeline concern plus one orchestrator
  per phase.
- **197 tests** in `tests/`, all passing, including exact-recovery checks
  against closed-form solutions, hand-built synthetic networks with known
  outcomes, hand-computed checks of every review fix (profile loss, Koopman
  influence on a known operator, equal-hours cuts, paired CIs vs scipy,
  exact Spearman p by brute force, block bootstrap), and integration checks
  against the real fitted models.
- **Every parameter and file path** lives in `config.py`.
- **Bugs caught by the project's own tests and review** are documented in
  `research_log.md` where they were found: a merge-suffix dependency in the
  calibration loss, a seed-entropy misunderstanding, a reversed eigenvector
  un-scaling, an incorrect "trivial mode" assumption, a wiring argument-order
  mistake, a variable-shadowing bug in graph symmetrization, and (Nov 14
  review) a calibration grid that stopped at its edge.
