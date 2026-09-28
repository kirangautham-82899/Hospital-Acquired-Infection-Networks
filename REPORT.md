# P30: Koopman/EDMD Forecasting of MRSA Spread on a Hospital Contact Network

**Technical Report**
CMDS Course Project, M.Tech Data Science, Amrita Vishwa Vidyapeetham
Topic P30 · First review: October 6, 2026

---

## Abstract

Hospital-acquired MRSA transmission is driven by who contacts whom, but most
forecasting and intervention-planning tools either ignore network structure
entirely or use it only descriptively. This project builds a full pipeline —
from a real hospital contact network through an individual-level stochastic
epidemic simulator to a data-driven Koopman/EDMD forecasting model — and asks
two concrete questions: (1) does lifting ward-level MRSA prevalence into a
Koopman-operator framework forecast outbreak trajectories better than simple
baselines, and (2) do the resulting Koopman eigenmodes identify
"superspreader" wards better than plain network centrality? Using the I-Bird
hospital contact-network dataset (589 people, 124,924 contact records, 6,728
MRSA swabs, Berck-sur-Mer, France, 2009), we build three EDMD dictionaries of
increasing richness (linear, degree-2 polynomial, and a contact-weighted
variant), fit ridge-regularized Koopman operators on 300 simulated outbreak
trajectories, and validate everything against both simulated and real data.
The honest answer to both questions is **no, not for this dataset**: on real
data, all three EDMD variants are statistically indistinguishable from a
naive persistence forecast, and a one-line network centrality score predicts
a simulated superspreader-ward ground truth far better (Spearman ρ = 0.94)
than any Koopman eigenmode score (ρ = 0.26–0.54). We report this negative
result in full rather than reframing it, trace it to concrete, verifiable
causes (a weakly-identified calibration ridge, a proven structural redundancy
in the network-weighted dictionary, and a real 16-week data budget), and show
via eight robustness experiments that these conclusions are stable across
every modeling choice we could reasonably vary. Targeting *some* score —
almost any of them — still beats not targeting at all by a wide margin, which
remains a useful, practically actionable finding independent of which
specific score is used.

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
operator's eigenmodes as the system's characteristic spatial-temporal
patterns. A mode with a large, persistent eigenvalue and heavy weight on one
ward would be a natural, principled "superspreader ward" signal — in
particular, a *contact-network-weighted* dictionary might let the Koopman
operator directly encode which wards drive which other wards.

This project builds that full pipeline end to end on a real hospital contact
network, and — critically — does not stop at fitting the model. It asks
whether the resulting eigenmode-based ward ranking is *actually better* than
the obvious, nearly-free alternative (a ward's raw contact volume), using a
**simulated ground-truth experiment** (cutting a ward's contacts and
measuring the actual epidemiological effect) as the arbiter, not just
in-sample model fit.

**Roadmap.** Section 2 describes the data and its audit. Section 3 covers
methods: the contact network (§3.1), real weekly MRSA prevalence (§3.2), an
individual-level SIS simulator calibrated to the real data (§3.3), the three
EDMD dictionaries (§3.4), the ridge-regularized EDMD fit (§3.5), and
eigenmode analysis (§3.6). Section 4 presents results: forecasting
validation on real data (§4.1), the superspreader risk-score comparison
(§4.2) — the phase that actually answers this project's central question —
intervention simulation (§4.3), and eight robustness experiments (§4.4).
Section 5 discusses what these results mean; Section 6 states limitations;
Section 7 concludes.

Every number in this report is pulled directly from the project's saved
`results/tables/*.csv` outputs and `research_log.md`, which records each
phase's verified numbers, design decisions, and any bugs caught along the
way (several are discussed explicitly below, since fixing them changed
concrete conclusions).

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
probability γ.

**Calibration.** Fit via a 320-point grid search (β × γ × ε) with 20
replicates per point (common random numbers), scoring against the real
weekly prevalence series on the calibration weeks (0–11) only, comparing
each *tested* person's *simulated* status on their *real* test date — not a
full-population average — for a fair like-with-like comparison.

**A significant finding, reported rather than hidden.** The best-fit point
(β=6.82×10⁻⁴/hr, γ=1.67×10⁻³/day, ε=7.07×10⁻⁴/day) sat on the edge of the
search grid; after one automatic 3× widening, γ *remained* on the widened
grid's edge. This reflects a genuine identifiability problem, not a bug:
with γ this low (mean carriage ≈600 days — biologically implausible for
MRSA), the simulated trajectories stay nearly flat for the entire 17-week
window, and because the real weekly series is itself noisy with no strong
trend, a near-static model is difficult for a weighted-least-squares
objective to beat. 16 of 320 grid points scored within 10% of the best
loss, confirming a genuine ridge (β and γ partly trade off) rather than a
single sharp optimum. This ridge is the root cause behind several "honest,
weak" results later in this report (§4.1, §4.2) and is revisited explicitly
in the robustness experiments (§4.4, E4).

**Training trajectories.** 300 simulated 17-week trajectories were
generated for EDMD fitting (§3.5): 150 *endemic* starts (each ward's
initial prevalence drawn from a randomized multiplier on its real baseline,
independently per ward per trajectory, to cover the joint 6-ward state
space rather than only near one operating point) and 150 *outbreak* starts
(1–3 seeded cases in one randomly chosen ward). β and γ are independently
varied 0.5×–2× around their calibrated values per trajectory; ε is held
fixed.

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
snapshot matrix's condition number is 35.5 for D1, 976.9 for D2, and
**9.4×10¹⁶ for D3 — numerically singular**. This was diagnosed, not just
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
nonlinear block). This was confirmed exactly: the fitted operator for D3 has
`rank(K) = 19` of 25, precisely matching the theoretical prediction, while
D1 (rank 7 of 7) and D2 (rank 28 of 28) are both full rank. **Consequence for
interpretation, used consistently from this point on: D3 should be
described as testing whether a contact-structured *prior* helps
generalization — never as "injecting network information," since it
structurally cannot add information beyond D2.** A genuinely network-aware
dictionary would need the *week-specific* contact matrix `W_t` (since
`W_t·x_t` would then not be a function of `x_t` alone) — noted here as future
work, outside the project's locked scope.

**λ selection.** A 20-point log-spaced grid (10⁻⁶ to 10³) per dictionary,
selected on the validation split by the mean RMSE over forecast horizons
1–4 (`K`, `K²`, `K³`, `K⁴` applied to `φ(x_t)`, in original prevalence units
via the readout, never on the raw lifted vector). Selected λ: D1=4.28,
D2=1.44, D3=1.44, none on a grid edge. The validation curve is remarkably
**flat across roughly six orders of magnitude** before rising sharply past
λ≈10 — regularization strength barely matters here, consistent with the
calibration ridge finding in §3.3: the underlying dynamics are simple and
only weakly identified by the available data.

**Honest simulated-trajectory result.** D1, D2, and D3 perform almost
identically on held-out simulated trajectories (test h=1 RMSE: 0.00748,
0.00758, 0.00747 respectively), all beating a persistence baseline by a
modest 12–13% at h=1, growing to 25–27% by h=4. D3 edges out D2 very
slightly at every horizon *despite having strictly less effective capacity*
(rank 19 vs. 28) — a small, concrete instance of "fewer effective
parameters can generalize marginally better," though the margin is too
small to lean on. D2 does not meaningfully beat D1.

### 3.6 Eigenmode Analysis (P7)

Each fitted `K`'s eigenvalues and eigenvectors are computed, mapped back to
ward space via the readout and correctly *un-scaled* to original prevalence
units (a similarity-transform relationship: `K_z = D⁻¹ K_orig D` for
`D = diag(scale)`, so a scaled-space eigenvector must be *multiplied*, not
divided, by the scale vector to recover the original-space eigenvector —
the first implementation had this backwards and was caught by a synthetic
test before it reached any real conclusion). D3's 6 spurious null-space
eigenvalues (from the proven rank deficiency in §3.5) are filtered using
the already-established rank cutoff, validated against a clean ~10¹²-fold
gap in eigenvalue magnitude between the 19th and 20th largest — an
unambiguous cutoff, not a judgment call.

**Dominant-mode disagreement, flagged for later validation.** The
most-persistent (|λ| closest to 1) ward-relevant mode's dominant ward
differs by dictionary: **D1 says Menard 1** (45.2% share of the mode's
magnitude concentrated there, λ=1.00000 exactly); **D2 and D3 agree with
each other: Sorrel 1** (λ=1.0138 and 1.00035+0.00091j respectively). This
disagreement is explicitly *not* resolved from eigenmodes alone — it is
carried forward as the central question for §4.2's validation against
simulated ground truth.

---

## 4. Results

### 4.1 Forecasting Validation on Real Data (P8)

This is the first point in the project where the EDMD operators (fit purely
on simulated trajectories) touch real data at all. Real starting states are
built by preferring genuine test observations and falling back to the P3
carry-forward series for gaps; forecasts are scored only against
genuinely-observed cells. Two additional baselines were built for this
comparison: a pooled 3-parameter network-exposure linear model and a
2-parameter mean-field ward-level SIS model (both verified via exact
parameter recovery on noiseless synthetic data before use), plus persistence
and historical-mean.

**Result.** On the holdout period (weeks 12–16, the one period untouched by
any model's fitting), **D1/D2/D3 are statistically indistinguishable from
persistence at h=1** (RMSE 0.0464–0.0466 vs. persistence's 0.0464 — skill
scores of −0.001 to −0.006). At longer horizons (h=3–4), the
historical-mean baseline overtakes everything (skill ≈0.20 vs. persistence)
— a well-known, defensible phenomenon: naive climatology beats both
persistence and fitted dynamics at longer horizons for noisy, mean-reverting
series. The network-exposure model is the weakest at nearly every horizon.
A plausible (not confirmed) explanation for EDMD's lack of edge: K was fit
purely on simulated trajectories sitting on §3.3's weakly-identified
calibration ridge, so it may simply not transfer a strong advantage onto the
real, sparse, 16-week series it never touched during fitting.

### 4.2 Superspreader Ward Risk Score vs. Centrality (P9)

**This is the phase that actually answers the project's central question**,
and its result is reported in full.

**Ground truth**, measured in simulation: for each ward, cut *all* contact
edges touching that ward (within- and between-ward) by 50%, using the same
calibrated (β, γ, ε) and initial condition as §3.3, with common random
numbers across 100 replicates for a paired comparison. The resulting
ranking of drop in colonized person-days: **Menard 1 > Sorrel 1 > Menard 2 >
Sorrel 2 > Sorrel 0 > Other.**

**Candidates compared against this ranking** (Spearman ρ, n=6 wards):

| Candidate | ρ | p |
|---|---|---|
| **degree_centrality** | **0.943** | **0.0048** |
| eigenvector_centrality | 0.714 | 0.111 |
| koopman_D2 | 0.543 | 0.266 |
| koopman_D3 | 0.429 | 0.397 |
| betweenness_centrality | 0.309 | 0.552 |
| koopman_D1 | 0.257 | 0.623 |

**Simple degree centrality — each ward's raw row-sum in a table already
computed in §3.1, requiring no Koopman machinery at all — predicts the
ground truth far better than any of the three Koopman eigenmode scores**,
and is the only candidate whose correlation survives even a rough
Bonferroni correction for testing 6 candidates (0.05/6 = 0.0083). None of
the Koopman scores reach conventional significance. This is an honest,
not-reframed negative result for the project's central premise.

One nuance kept rather than smoothed over: **koopman_D1 correctly picks
Menard 1 as the #1 ward** (matching §3.6's finding that D1's dominant mode
is Menard-1-dominated), but scrambles the ordering of the remaining 5 wards
badly enough that its *overall* rank correlation (0.257) is the *worst* of
the three Koopman variants — getting the top pick right and having good
overall rank agreement are different properties, and both are true
simultaneously here. n=6 wards gives inherently weak rank statistics (a
known limitation, §6); these correlations should be read descriptively.

### 4.3 Intervention Simulation (P10)

Extends §4.2 into an actual decision-comparison: five strategies (none,
random, whole-hospital, degree-targeted, and Koopman-targeted — reported as
three separate variants, one per dictionary, since §3.6/§4.2 already found
they disagree) compared under an **equal-budget** framework
(`budget = k × R` for `k` targeted wards each reduced by fraction `R`,
whole-hospital scaled to `budget/6` per ward so it is not trivially favored
by spending more total resource), 200 replicates with common random numbers
across ~7,200 simulated runs.

**Headline result:** every targeted strategy clearly and consistently beats
both untargeted strategies (random, whole-hospital) at every matching
budget — targeting of *any* kind is worth far more than spreading effort
thin or picking blindly, regardless of which specific score does the
targeting.

**Which score wins is nuanced, and reported in full.** At k=1, degree-
targeted and koopman_D1 tie exactly (both pick Menard 1). At **k=2, the
ranking flips**: koopman_D2/D3 (picking {Sorrel 1, Menard 1} — the true
top-2 ground-truth wards) slightly but consistently *outperforms*
degree-targeted (picking {Menard 1, Menard 2} — degree centrality's own
top-2, which swaps the true #2 and #3 wards) at every reduction level (e.g.
R=75%: drop 412.6 vs. 398.3 person-days). This shows that a higher overall
Spearman correlation (§4.2: degree 0.943 vs. koopman_D2/D3 0.543/0.429)
does not guarantee the better choice on every specific targeting decision —
degree centrality's one rank error (swapping wards #2 and #3) happened to
matter directly for the k=2 case.

### 4.4 Robustness Experiments E1–E8 (P11)

Eight experiments, each perturbing one axis of the modeling pipeline and
reporting a Spearman ρ (rank-based) or RMSE ratio (magnitude-based) against
the corresponding baseline result:

| # | Experiment | What it probes | Result |
|---|---|---|---|
| E1 | Seed sensitivity | A different global seed for the §4.2 ground truth | ρ=0.943 |
| E2 | λ sensitivity | Refit at 0.1×/10× the selected λ, re-score on real holdout | max \|ratio−1\|=0.033 |
| E3 | Replicate-count convergence | 30 / 300 replicates vs. the standard 100 | ρ=1.000 (both) |
| E4 | Calibration ridge-point | A different point on §3.3's loss ridge | ρ=1.000 |
| E5 | W's time window | W from calibration weeks only vs. the whole period | ρ=1.000 |
| E6 | Patients-only population | 329-person, 5-ward population (the locked sensitivity run) | ρ≈1.000 |
| E7 | Missing-data handling | Carry-forward series as ground truth vs. no-imputation | ρ=1.000 (model ranking) |
| E8 | D3 structural redundancy | Drop the provably-redundant Wx block (19 vs. 25 features) | ratio=0.998, same dominant ward |

**Every conclusion drawn in §§4.1–4.3 is stable** across seed choice,
replicate count, calibration point, network time-window, population
definition, missing-data handling, and λ choice. This uniformity is not
treated as suspicious: each check varies a genuinely different axis, and
the underlying reasons are independently explicable — the ward ranking is
driven by a large, stable structural feature of the real contact data
(Menard 1's outsized contact volume), not a fragile model artifact, and
E8's near-zero effect is *expected* because D3's redundancy (§3.5) is a
proven algebraic fact, not an empirical coincidence that could have gone
the other way. (One numerical coincidence — E1's ρ matching §4.2's
degree_centrality correlation to 15 decimal places — was investigated
rather than left unexplained: both correspond to exactly one adjacent-rank
swap out of 6 wards, the smallest possible non-zero perturbation, which two
otherwise-unconnected comparisons independently landed on; see
`research_log.md` for the full derivation.)

---

## 5. Discussion

Three findings define this project's contribution:

1. **The Koopman/EDMD machinery works, and was built and verified
   rigorously** — exact recovery on synthetic linear and quadratic systems,
   closed-form ridge agreement, a numerically stable solver, and a
   consistent train/val/test discipline throughout. The engineering is
   sound.

2. **On this dataset, it does not outperform much simpler alternatives**,
   and we report this plainly rather than reframing a negative result as a
   qualified success. Three concrete, verifiable reasons converge on why:
   (a) the SIS calibration (§3.3) sits on a wide, weakly-identified ridge
   because the real prevalence series has only ~16 usable weekly snapshots,
   so the simulated training trajectories may not encode a strongly
   generalizable signal; (b) the contact-weighted dictionary D3 — the one
   dictionary meant to be "network-aware" — is *provably* no richer than
   the plain polynomial dictionary D2, so it cannot outperform D2 on
   principle, only potentially generalize marginally better; and (c) a
   ward's raw contact *volume* turns out to be a strong, nearly-free
   predictor of its epidemiological importance, which is itself a
   substantive, useful finding, just not the one the Koopman framework was
   built to surface.

3. **Targeting still matters enormously**, independent of which score does
   the targeting (§4.3) — a practically actionable conclusion for
   infection control that survives every robustness check (§4.4), even
   though the *specific* ranking method's advantage is much less clear-cut
   (§4.2).

A natural question is whether a genuinely time-varying, network-aware
dictionary (using the week-specific contact matrix `W_t` rather than the
time-invariant `W`, noted in §3.5) would change the picture — this was
identified as a concrete, well-motivated direction for future work, not
attempted here since it falls outside the locked project scope.

---

## 6. Limitations

Carried forward from the project's locked plan, and confirmed as materially
relevant by the results above rather than boilerplate:

- **About 16 real weekly snapshots only.** This is the root cause behind
  §3.3's calibration ridge and, very plausibly, §4.1's weak sim-to-real
  transfer.
- **Time-invariant K vs. a time-varying contact network.** D3 uses one
  fixed W for the whole period; §4.4 (E5) confirmed this specific choice
  doesn't change the degree-centrality ranking, but a genuinely
  time-varying `W_t` dictionary (§5) was never built.
- **Only 6 ward groups, so rank statistics are weak.** Directly
  responsible for §4.2's low statistical power and for the E1/degree-
  centrality coincidence investigated in §4.4.
- **No admission/discharge dates, single hospital, single 4-month window,
  no transfer records.** Limits how far any finding here — positive or
  negative — should be expected to generalize beyond this specific
  dataset.

---

## 7. Conclusion

This project built a complete, rigorously-tested pipeline from a real
hospital contact network to a Koopman/EDMD forecasting and superspreader-
targeting system, and used that pipeline honestly to test its own central
hypothesis. The answer, for this dataset, is that a network-aware Koopman
eigenmode score does not beat simple degree centrality at identifying
high-impact wards, and EDMD forecasts do not clearly beat persistence on
real data — but the reasons why are traceable to specific, well-understood
causes (a weak calibration ridge, a proven dictionary redundancy, limited
real data) rather than implementation error, and the broader practical
conclusion — that *some* form of targeted intervention is worth far more
than untargeted effort — holds robustly regardless. Future work should
prioritize a genuinely time-varying network-weighted dictionary and a
larger or multi-site real dataset to give the calibration and validation
steps more to work with.

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
phase-by-phase engineering log — every verified number, locked decision,
and bug caught during development — is in [research_log.md](research_log.md).

## Appendix B: Software Summary

- **31 modules** in `src/`, one per pipeline concern plus one orchestrator
  per phase (`build_network.py`, `build_states.py`, `build_simulation.py`,
  `build_observables.py`, `build_edmd.py`, `build_eigen.py`, `build_p8.py`
  through `build_p11.py`).
- **179 tests** in `tests/`, all passing — including exact-recovery checks
  against known closed-form solutions, hand-built synthetic networks with
  analytically-predictable outcomes, and integration checks against the
  real fitted models.
- **Every parameter and file path** lives in `config.py`; no hidden magic
  numbers elsewhere in the codebase.
- At least **six bugs were caught by this project's own testing and review
  discipline** before they could affect a reported conclusion (a merge-
  suffix dependency in the SIS calibration loss, a seed-entropy
  misunderstanding, an eigenvector un-scaling direction reversed, a
  mathematically-incorrect "trivial mode" assumption, a wiring argument-
  order mistake, and a variable-shadowing bug in a graph-symmetrization
  helper) — each is documented in `research_log.md` at the point it was
  found, including what specifically caught it and why the fix mattered.
