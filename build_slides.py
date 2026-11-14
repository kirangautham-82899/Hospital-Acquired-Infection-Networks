"""Builds P30_slides.pptx from the project's saved results. A one-off
report-generation script (not part of the src/ analysis pipeline) --
mirrors REPORT.md's structure and numbers, both drawn from the same
verified results/tables/*.csv and research_log.md sources.
"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

TITLE_COLOR = RGBColor(0x1B, 0x3A, 0x5C)
ACCENT_COLOR = RGBColor(0xC0, 0x39, 0x2B)
TEXT_COLOR = RGBColor(0x22, 0x22, 0x22)

FIG = "results/figures"


def add_title_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(0.7), Inches(1.6), Inches(12), Inches(2.2))
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(["P30: Koopman/EDMD Forecasting of MRSA Spread", "on a Hospital Contact Network"]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.size = Pt(34)
        p.font.bold = True
        p.font.color.rgb = TITLE_COLOR

    sub = slide.shapes.add_textbox(Inches(0.7), Inches(3.9), Inches(12), Inches(1.5))
    tf2 = sub.text_frame
    tf2.word_wrap = True
    for text, size in [
        ("Kiran Gautham", 20),
        ("CMDS Course Project · M.Tech Data Science · Amrita Vishwa Vidyapeetham", 18),
        ("Topic P30 · First review: October 6, 2026 · Revised November 14, 2026", 16),
    ]:
        p = tf2.add_paragraph() if tf2.paragraphs[0].text else tf2.paragraphs[0]
        p.text = text
        p.font.size = Pt(size)
        p.font.color.rgb = TEXT_COLOR
    return slide


def add_section_slide(prs, title):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = TITLE_COLOR
    box = slide.shapes.add_textbox(Inches(0.7), Inches(3.0), Inches(12), Inches(2))
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(title.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.size = Pt(32)
        p.font.bold = True
        p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    return slide


def add_bullet_slide(prs, title, bullets, note=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.35), Inches(12.3), Inches(0.9))
    tp = title_box.text_frame.paragraphs[0]
    tp.text = title
    tp.font.size = Pt(26)
    tp.font.bold = True
    tp.font.color.rgb = TITLE_COLOR

    body = slide.shapes.add_textbox(Inches(0.6), Inches(1.3), Inches(12.1), Inches(5.6))
    tf = body.text_frame
    tf.word_wrap = True
    first = True
    for item in bullets:
        if isinstance(item, tuple):
            text, level = item
        else:
            text, level = item, 0
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.text = ("• " if level == 0 else "   - ") + text
        p.font.size = Pt(20 if level == 0 else 17)
        p.font.color.rgb = ACCENT_COLOR if level == 0 and text.isupper() else TEXT_COLOR
        p.space_after = Pt(10)
    if note:
        note_box = slide.shapes.add_textbox(Inches(0.6), Inches(6.9), Inches(12.1), Inches(0.5))
        p = note_box.text_frame.paragraphs[0]
        p.text = note
        p.font.size = Pt(12)
        p.font.italic = True
        p.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    return slide


def add_image_slide(prs, title, image_path, caption=None, bullets=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.35), Inches(12.3), Inches(0.8))
    tp = title_box.text_frame.paragraphs[0]
    tp.text = title
    tp.font.size = Pt(26)
    tp.font.bold = True
    tp.font.color.rgb = TITLE_COLOR

    left_width = Inches(7.6) if bullets else Inches(11.5)
    pic = slide.shapes.add_picture(image_path, Inches(0.6), Inches(1.25), width=left_width)
    # cap height so it never overflows the slide
    max_h = Inches(5.6)
    if pic.height > max_h:
        ratio = max_h / pic.height
        pic.height = max_h
        pic.width = Emu(int(pic.width * ratio))

    if bullets:
        body = slide.shapes.add_textbox(Inches(8.5), Inches(1.4), Inches(4.3), Inches(5.4))
        tf = body.text_frame
        tf.word_wrap = True
        first = True
        for text in bullets:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.text = "• " + text
            p.font.size = Pt(15)
            p.font.color.rgb = TEXT_COLOR
            p.space_after = Pt(8)

    if caption:
        cap_box = slide.shapes.add_textbox(Inches(0.6), Inches(7.0), Inches(11.5), Inches(0.4))
        p = cap_box.text_frame.paragraphs[0]
        p.text = caption
        p.font.size = Pt(12)
        p.font.italic = True
        p.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    return slide


def add_table_slide(prs, title, headers, rows, note=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.35), Inches(12.3), Inches(0.8))
    tp = title_box.text_frame.paragraphs[0]
    tp.text = title
    tp.font.size = Pt(26)
    tp.font.bold = True
    tp.font.color.rgb = TITLE_COLOR

    n_rows, n_cols = len(rows) + 1, len(headers)
    table_shape = slide.shapes.add_table(n_rows, n_cols, Inches(0.6), Inches(1.4), Inches(12.1), Inches(0.5 * n_rows))
    table = table_shape.table
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        cell.text_frame.paragraphs[0].font.bold = True
        cell.text_frame.paragraphs[0].font.size = Pt(15)
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            cell = table.cell(i, j)
            cell.text = str(val)
            cell.text_frame.paragraphs[0].font.size = Pt(14)

    if note:
        note_box = slide.shapes.add_textbox(Inches(0.6), Inches(1.5 + 0.5 * n_rows), Inches(12.1), Inches(1.0))
        p = note_box.text_frame.paragraphs[0]
        p.text = note
        p.font.size = Pt(14)
        p.font.italic = True
        p.font.color.rgb = TEXT_COLOR
    return slide


def build():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    add_title_slide(prs)

    add_bullet_slide(
        prs, "Motivation",
        [
            "Hospital-acquired MRSA spreads through person-to-person contact",
            "Infection-control resources (isolation, cohorting, screening) are finite",
            "Which ward, if any, is disproportionately responsible for spread?",
            "Would intervening there actually help more than a blanket or random policy?",
        ],
    )

    add_bullet_slide(
        prs, "Research Questions",
        [
            "RQ1: Does lifting ward-level MRSA prevalence into a Koopman/EDMD",
            ("framework forecast better than simple baselines?", 1),
            "RQ2: Do Koopman-based ward scores identify “superspreader”",
            ("wards better than plain network centrality?", 1),
            "Answered against SIMULATED GROUND TRUTHS and real holdout data, not in-sample fit",
        ],
    )

    add_bullet_slide(
        prs, "Data: the I-Bird Hospital Contact Network",
        [
            "200-bed long-term/rehabilitation hospital, Berck-sur-Mer, France, 2009",
            "Obadia et al. 2015 (PLOS Comput Biol); Duval et al. 2018 (Sci Rep)",
            "admission.csv: 795 people (452 patients, 343 staff), 6 ward groups",
            "mat.day.csv: 124,924 contact records, 589 people, 19,974 unique pairs",
            "microbio.csv: 6,728 MRSA swabs, 295 people MRSA-positive at least once",
            "P1 data audit: all 19 reference numbers independently re-verified exactly",
        ],
    )

    add_image_slide(
        prs, "The Contact Network, Colored by Ward",
        f"{FIG}/p2_network_by_ward_all.png",
        bullets=[
            "Clear within-ward clustering",
            "“Other” (staff, brown) bridges wards",
            "90.3% of contact-seconds are within-ward",
            "Ward contact matrix W built from raw bidirectional contact records",
        ],
        caption="Figure: 589-person contact network, node color = ward group.",
    )

    add_bullet_slide(
        prs, "Pipeline Overview",
        [
            "P1 Data audit  →  P2 Contact network + ward matrix W",
            "P3 Real weekly prevalence  →  P4 Individual-level SIS simulation + calibration",
            "P5 EDMD dictionaries (D1/D2/D3)  →  P6 Ridge-regularized EDMD fit",
            "P7 Eigenmodes + Koopman influence  →  P8 Real-data forecasting validation",
            "P9 Superspreader score vs. centrality  →  P10 Intervention simulation",
            "P11 Robustness experiments E1–E9 (E9: rerun P4–P10 along the calibration ridge)",
            "197 automated tests; every decision and the Nov 14 review fixes logged",
        ],
    )

    add_image_slide(
        prs, "SIS Simulation & Calibration (P4)",
        f"{FIG}/p4_profile_loss.png",
        bullets=[
            "Daily SIS on 589 people: P(transmit) = 1 − exp(−β·contact hours)",
            "500-point grid, calibration weeks 0–11 only",
            "Best: β=7.9×10⁻⁴/hr, γ=2.2×10⁻⁴/day, ε=2.7×10⁻⁴/day (interior)",
            "FINDING: γ is bounded only from above — every γ from 10⁻⁴ to "
            "2×10⁻³/day is within 5% of the best loss",
            "So the simulator has almost no decolonization: simulated "
            "prevalence drifts up, real prevalence fell in weeks 13–16",
        ],
        caption="Figure: profile loss per parameter (flat = weakly identified).",
    )

    add_bullet_slide(
        prs, "Three EDMD Dictionaries (P5)",
        [
            "D1 (linear): [1, x] — 7 features",
            "D2 (degree-2 polynomial): [1, x, x², cross terms] — 28 features",
            "D3 (contact-weighted): [1, x, x², Wx, x⊙(Wx)] — 25 features",
            "D3 is the one dictionary meant to inject network structure",
        ],
    )

    add_bullet_slide(
        prs, "Major Finding: D3 Adds No Function Space Beyond D2",
        [
            "PROVEN ANALYTICALLY, before building anything on top of it:",
            ("Wx is a linear function of x → spans exactly the same subspace as x", 1),
            ("x·(Wx) is a fixed linear combination of D2's own square/cross terms", 1),
            ("→ D3's effective rank ceiling: 19 of its 25 raw features", 1),
            "CONFIRMED EMPIRICALLY: fitted D3 operator has rank(K) = 19 exactly",
            "D1 (rank 7/7) and D2 (rank 28/28) are both full rank",
            "Consequence: D3 tests whether a contact-structured PRIOR helps —",
            ("it structurally cannot add network information beyond D2", 1),
        ],
    )

    add_bullet_slide(
        prs, "EDMD Fit Results (P6)",
        [
            "Ridge regression, written from scratch in NumPy (no external Koopman library)",
            "Constant feature excluded from scaling AND the ridge penalty",
            "λ selected on validation split, mean RMSE over horizons 1–4",
            "On simulated test trajectories D1, D2, D3 are almost identical:",
            ("h=1 RMSE 0.00519 / 0.00522 / 0.00516 vs persistence 0.00611", 1),
            ("15% better than persistence at h=1, 26–28% at h=4", 1),
            "Spectral radius slightly above 1 for all three (1.014–1.022):",
            ("the operators learned the simulator's slow upward drift", 1),
        ],
    )

    add_image_slide(
        prs, "Eigenmodes and Koopman Influence (P7)",
        f"{FIG}/p7_eigenvalue_spectrum_D3.png",
        bullets=[
            "Dominant-mode top ward: D1 Menard 1, D2 Sorrel 2, D3 Menard 1",
            "A mode's ward shares show WHERE the persistent pattern sits, "
            "not which ward DRIVES spread",
            "Added after review: influence score = extra colonized "
            "person-weeks K predicts after seeding 3 people in a ward",
            "Influence puts the two Menard wards on top for all three dictionaries",
        ],
        caption="Figure: D3's eigenvalue spectrum — real modes (blue) vs. spurious null-space modes (red).",
    )

    add_table_slide(
        prs, "Real-Data Forecasting (P8): RMSE Minus Persistence",
        ["Model", "h=1", "h=3", "h=4"],
        [
            ["D1", "+0.0006 [−0.0005, +0.0014]", "+0.0033 [+0.0005, +0.0049]", "+0.0053 [+0.0007, +0.0079]"],
            ["D2", "+0.0005 [−0.0005, +0.0014]", "+0.0029 [+0.0000, +0.0048]", "+0.0044 [−0.0004, +0.0068]"],
            ["D3", "+0.0008 [−0.0004, +0.0018]", "+0.0037 [+0.0009, +0.0054]", "+0.0058 [+0.0003, +0.0088]"],
            ["historical mean", "+0.0228 [+0.0110, +0.0384]", "−0.0173 [−0.0427, +0.0078]", "−0.0176 [−0.0402, +0.0037]"],
        ],
        note="Main calibration point; block-bootstrap 95% CIs from only 5 start weeks (rough). Positive = worse.\n"
             "Across all 9 calibration points (E9): tied at h=1 everywhere; at h=3–4 tied or worse except 2 of 54 cases.",
    )

    add_section_slide(prs, "The Central Question:\nKoopman Scores vs. Simple Centrality")

    add_image_slide(
        prs, "Two Simulated Ground Truths (P9)",
        f"{FIG}/p9_ground_truth_bar.png",
        bullets=[
            "A: cut each ward's contacts 50% (locked design)",
            "Caveat: A removes more hours from busy wards, so it rewards "
            "contact volume (= degree) by construction",
            "B (added): remove the SAME 2,884 contact-hours from every ward (400 replicates)",
            "Under B Sorrel 1 is clearly first, Sorrel 2 last; the middle four partly overlap",
        ],
        caption="Figure: drop in colonized person-days, 100 paired replicates, 95% CIs.",
    )

    add_table_slide(
        prs, "Ward Scores vs. Ground Truth: Spearman ρ (exact p)",
        ["Candidate", "vs A (50% cut)", "vs B (equal hours)"],
        [
            ["degree centrality", "0.943 (p=0.017)", "0.200 (p=0.71)"],
            ["Koopman D3 mode share", "0.829 (p=0.058)", "0.600 (p=0.24)"],
            ["Koopman D3 influence", "0.771 (p=0.10)", "−0.257 (p=0.66)"],
            ["eigenvector centrality", "0.714 (p=0.14)", "0.314 (p=0.56)"],
            ["betweenness centrality", "0.309 (p=0.53)", "0.802 (p=0.10, ties)"],
            ["Koopman D2 mode share", "−0.371 (p=0.50)", "−0.086 (p=0.92)"],
        ],
        note="Degree is significant vs A (largely by construction) at all 9 calibration points; Koopman swings −0.77..0.94.\n"
             "Under B no candidate ranks the wards reliably at any calibration point (n=6).",
    )

    add_image_slide(
        prs, "Intervention Simulation (P10)",
        f"{FIG}/p10_drop_vs_budget.png",
        bullets=[
            "Equal budget = k × reduction; 200 paired replicates, 95% CIs",
            "Degree-targeted beats random AND whole-hospital at every budget "
            "and every calibration point",
            "Koopman D2 mode-share targeting is WORSE than random",
            "Koopman beats degree in 2 of 108 comparisons across all "
            "calibration points (E9); loses 51, ties 55",
            "Best strategy prevents < 5% of colonized person-days",
        ],
        caption="Figure: drop vs. budget, one panel per k, 95% paired CIs. Degree and influence D1/D3 pick the same wards, so their lines overlap.",
    )

    add_table_slide(
        prs, "Robustness: Experiments E1–E9 (P11)",
        ["#", "Probes", "Result"],
        [
            ["E1", "Seed sensitivity (ground truth A)", "ρ=0.943"],
            ["E2", "λ sensitivity (0.1×/10×)", "max ratio dev. 1.6%"],
            ["E3", "Replicate count (30/300)", "ρ=1.000"],
            ["E4", "Calibration ridge point (γ=2.2×10⁻³)", "ρ=1.000"],
            ["E5", "W's time window", "ρ=1.000"],
            ["E6", "Patients-only population", "ρ=1.000"],
            ["E7", "Missing-data handling", "ρ=0.50 (3 near-tied models)"],
            ["E8", "D3 structural redundancy", "ratio 0.999, dominant ward DIFFERS"],
            ["E9", "Whole pipeline at 9 calibration points", "see next slides"],
        ],
        note="Ground truth A's ranking is very stable (driven by Menard 1's contact volume).\n"
             "Koopman eigenmode ward shares are fragile (E8).",
    )

    add_image_slide(
        prs, "E9: What Holds Across the Calibration Ridge",
        f"{FIG}/p11_e9_ridge_sensitivity.png",
        caption="Rerun of P4–P10 at all 9 points on the γ, β, ε profiles within 5% of the best calibration loss.",
    )

    add_table_slide(
        prs, "E9 Summary: Robust vs. Fragile Conclusions",
        ["Claim", "Range over 5 points", "Holds everywhere?"],
        [
            ["EDMD ≈ persistence at h=1", "−0.0003 .. +0.0011", "yes"],
            ["EDMD vs persistence at h=3–4", "−0.0023 .. +0.0092", "no (worse 26, better 2 of 54)"],
            ["ρ(degree, ground truth A)", "0.886 .. 0.943 (all p<0.05)", "yes"],
            ["ρ(Koopman D3 mode, A)", "−0.771 .. 0.943", "no"],
            ["Degree beats random / whole-hospital", "36 of 36", "yes"],
            ["Koopman beats degree", "2 of 108", "never reliably"],
        ],
    )

    add_bullet_slide(
        prs, "Discussion",
        [
            "The EDMD machinery is sound (exact recovery tests, proven D3 redundancy)",
            "Forecasting: no gain on real data — the closed, no-turnover simulator "
            "drifts up while real prevalence fell; EDMD inherits that drift",
            "Ranking: ground truth A mostly measures contact volume; under "
            "equal hours nothing ranks reliably with 6 wards",
            "Koopman scores depend on an unidentified decolonization rate "
            "(E9: they swing −0.77..0.94; degree stays significant)",
            "Practical: concentrate contact reduction on the busiest wards — "
            "beats random/whole-hospital, but the gain is small (< 5%)",
        ],
    )

    add_bullet_slide(
        prs, "Limitations",
        [
            "About 16 real weekly snapshots — decolonization rate not identified",
            "Closed population (no admission/discharge dates): cannot reproduce decline",
            "Ground truths and Koopman scores share the same simulator",
            "Only 6 ward groups — weak rank statistics; many P10 comparisons",
            "Time-invariant K vs. a time-varying contact network; no transfer records",
        ],
    )

    add_bullet_slide(
        prs, "Conclusion & Future Work",
        [
            "Complete, tested pipeline: real network → calibrated SIS → EDMD → "
            "eigenmodes/influence → validated against simulated ground truths",
            "Koopman/EDMD does not beat persistence on real data, and no Koopman "
            "score beats contact volume at finding high-impact wards",
            "Review fixes made two earlier claims weaker and are reported openly",
            "FUTURE WORK:",
            ("Simulator with patient admission/discharge (turnover)", 1),
            ("Week-specific network dictionary W_t", 1),
            ("Larger / multi-site dataset to identify the decolonization rate", 1),
        ],
    )

    add_bullet_slide(
        prs, "References",
        [
            "Obadia, T., Silhol, R., Opatowski, L., Temime, L., Legrand, J., "
            "Thiébaut, A.C.M., et al. (2015). Detailed Contact Data and the "
            "Dissemination of Staphylococcus aureus in Hospitals. "
            "PLOS Computational Biology, 11(3):e1004170.",
            "Duval, A., Obadia, T., Martinet, L., Boëlle, P.Y., Fleury, E., "
            "Guillemot, D., et al. (2018). Measuring dynamic social contacts "
            "in a rehabilitation hospital: effect of wards, patient and staff "
            "characteristics. Scientific Reports, 8:1686.",
        ],
    )

    prs.save("P30_slides.pptx")
    print(f"Saved P30_slides.pptx with {len(prs.slides)} slides")


if __name__ == "__main__":
    build()
