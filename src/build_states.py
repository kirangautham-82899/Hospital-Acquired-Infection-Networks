"""P3 orchestrator: build the real weekly MRSA prevalence state series.

Writes:
  data/processed/states_real.csv                         (MAIN series, used for calibration)
  data/processed/states_real_check_all_tested.csv         (CHECK series, all 666 tested people)
  data/processed/states_real_patients_only.csv            (5-ward sensitivity population)
  data/processed/states_real_carry_forward_SENSITIVITY_ONLY.csv
  data/processed/states_pre_window_raw_tests.csv          (May 4 - Jun 28, context only)
  data/processed/states_pre_window_last_status.csv        (candidate starting state for P4)
  results/tables/p3_*.csv                                 (reporting copies + diagnostics)
  results/figures/p3_prevalence_trajectory.png

Never modifies data/raw/.
"""
import numpy as np
import pandas as pd

import config
from src.load import load_admission, load_contacts, load_microbio
from src.network import filter_people
from src.states import (
    MIN_TESTED_FLAG,
    carry_forward_prevalence,
    carry_forward_status,
    last_status_before_window,
    repeat_test_report,
    restrict_to_window,
    weekly_person_status,
    weekly_prevalence,
)


def hand_check(microbio, admission, network_people, checks):
    """Independently recompute prevalence for a few (week, group) cells
    straight from raw microbio.csv (own date filter + own groupby, not
    calling src.states), to cross-check the pipeline output."""
    from src.wards import person_ward_map

    ward_of = person_ward_map(admission)
    rows = []
    for week, group in checks:
        week_start = pd.Timestamp(config.STUDY_START) - pd.Timedelta(
            days=pd.Timestamp(config.STUDY_START).weekday()
        ) + pd.Timedelta(weeks=week)
        week_end = week_start + pd.Timedelta(days=6)
        sub = microbio[
            (microbio["date_prl"] >= week_start)
            & (microbio["date_prl"] <= week_end)
            & (microbio["calc_ident"].isin(network_people))
        ].copy()
        sub = sub[sub["calc_ident"].map(ward_of) == group]
        people = sub.groupby("calc_ident")["sarm"].apply(lambda s: int((s == 1).any()))
        n_tested = len(people)
        n_positive = int(people.sum())
        prevalence = n_positive / n_tested if n_tested else np.nan
        rows.append(
            {
                "week": week, "group": group,
                "week_start": week_start.date(), "week_end": week_end.date(),
                "hand_n_tested": n_tested, "hand_n_positive": n_positive,
                "hand_prevalence": prevalence,
            }
        )
    return pd.DataFrame(rows)


def build():
    config.DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    admission = load_admission(config.ADMISSION_CSV)
    contacts = load_contacts(config.CONTACTS_CSV)
    microbio = load_microbio(config.MICROBIO_CSV)

    network_people = set(contacts["from"]) | set(contacts["to"])
    patients_only_network_people = filter_people(admission, include_staff=False) & network_people

    in_window, before_window, after_window = restrict_to_window(microbio)

    print("P3 STATE BUILD SUMMARY")
    print("=" * 60)
    print(f"Tests in window (2009-07-01 to 2009-10-25): {len(in_window)}")
    print(f"Tests dropped, after window (2009-10-26/27): {len(after_window)}")
    print(f"Tests kept as pre-window context (before 2009-07-01): {len(before_window)}")

    # ---- MAIN series: network-restricted, 6 groups ----
    person_status_main = weekly_person_status(in_window, admission, person_filter=network_people)
    states_real = weekly_prevalence(person_status_main, groups=config.WARD_GROUPS)
    n_pw, n_repeats = repeat_test_report(person_status_main)
    print(f"\n[MAIN, network-restricted] person-weeks: {n_pw}, with repeat tests: {n_repeats} "
          f"({100 * n_repeats / n_pw:.1f}%)")

    states_real.to_csv(config.DATA_PROCESSED_DIR / "states_real.csv", index=False)
    states_real.to_csv(config.RESULTS_TABLES_DIR / "p3_states_real.csv", index=False)

    low_n = states_real[states_real["low_n"]]
    low_n.to_csv(config.RESULTS_TABLES_DIR / "p3_low_n_flagged.csv", index=False)
    print(f"Group-weeks flagged low_n (< {MIN_TESTED_FLAG} tested): {len(low_n)} of {len(states_real)}")

    import itertools
    all_combos = set(itertools.product(range(17), config.WARD_GROUPS))
    present = set(zip(states_real["week"], states_real["group"]))
    missing = pd.DataFrame(sorted(all_combos - present), columns=["week", "group"])
    missing.to_csv(config.RESULTS_TABLES_DIR / "p3_zero_tested_group_weeks.csv", index=False)
    print(f"Group-weeks with ZERO tested people (absent from states_real entirely): {len(missing)} "
          f"of {17 * len(config.WARD_GROUPS)} possible")

    # ---- CHECK series: all tested people, 6 groups ----
    person_status_check = weekly_person_status(in_window, admission, person_filter=None)
    states_check = weekly_prevalence(person_status_check, groups=config.WARD_GROUPS)
    states_check.to_csv(config.DATA_PROCESSED_DIR / "states_real_check_all_tested.csv", index=False)

    merged = states_real.merge(states_check, on=["week", "group"], suffixes=("_main", "_check"))
    merged["abs_diff"] = (merged["prevalence_main"] - merged["prevalence_check"]).abs()
    merged.to_csv(config.RESULTS_TABLES_DIR / "p3_states_check_vs_main_diff.csv", index=False)
    print(f"\n[CHECK vs MAIN] max |prevalence diff|: {merged['abs_diff'].max():.4f}, "
          f"mean: {merged['abs_diff'].mean():.4f}")

    # ---- Patients-only series: network-restricted, 5 wards ----
    person_status_patients = weekly_person_status(
        in_window, admission, person_filter=patients_only_network_people
    )
    patient_groups = [g for g in config.WARD_GROUPS if g != "Other"]
    states_patients_only = weekly_prevalence(person_status_patients, groups=patient_groups)
    states_patients_only.to_csv(config.DATA_PROCESSED_DIR / "states_real_patients_only.csv", index=False)
    states_patients_only.to_csv(config.RESULTS_TABLES_DIR / "p3_states_real_patients_only.csv", index=False)

    # ---- Carry-forward sensitivity (MAIN population, 6 groups) ----
    carried = carry_forward_status(person_status_main)
    states_carry_forward = carry_forward_prevalence(carried, groups=config.WARD_GROUPS)
    states_carry_forward.to_csv(
        config.DATA_PROCESSED_DIR / "states_real_carry_forward_SENSITIVITY_ONLY.csv", index=False
    )
    print(f"\n[CARRY-FORWARD, sensitivity only] rows: {len(states_carry_forward)}, "
          f"mean n_carried/week-group: {states_carry_forward['n_carried'].mean():.2f}")

    # ---- Pre-window context ----
    before_window.to_csv(config.DATA_PROCESSED_DIR / "states_pre_window_raw_tests.csv", index=False)
    pre_window_status = last_status_before_window(before_window, admission)
    pre_window_status.to_csv(config.DATA_PROCESSED_DIR / "states_pre_window_last_status.csv", index=False)
    print(f"\nPre-window tests kept for context: {len(before_window)} rows, "
          f"{pre_window_status['calc_ident'].nunique()} distinct people with a last-known status")

    # ---- Hand-check two group-weeks against the raw CSV ----
    checks = [(5, "Menard 1"), (10, "Sorrel 2")]
    hand = hand_check(microbio, admission, network_people, checks)
    pipeline_vals = states_real.set_index(["week", "group"])
    hand["pipeline_n_tested"] = [pipeline_vals.loc[(w, g), "n_tested"] for w, g in zip(hand["week"], hand["group"])]
    hand["pipeline_prevalence"] = [
        pipeline_vals.loc[(w, g), "prevalence"] for w, g in zip(hand["week"], hand["group"])
    ]
    hand["match"] = (hand["hand_n_tested"] == hand["pipeline_n_tested"]) & (
        (hand["hand_prevalence"] - hand["pipeline_prevalence"]).abs() < 1e-9
    )
    hand.to_csv(config.RESULTS_TABLES_DIR / "p3_hand_check.csv", index=False)
    print("\nHand-check (independent recomputation from raw microbio.csv):")
    print(hand.to_string(index=False))
    assert hand["match"].all(), "hand-check mismatch -- see p3_hand_check.csv"

    _plot_trajectory(states_real, states_carry_forward)

    return {
        "states_real": states_real,
        "states_check": states_check,
        "states_patients_only": states_patients_only,
        "states_carry_forward": states_carry_forward,
    }


def _plot_trajectory(states_real, states_carry_forward):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 3, figsize=(14, 7), sharex=True, sharey=True)
    for ax, group in zip(axes.flat, config.WARD_GROUPS):
        main = states_real[states_real["group"] == group]
        cf = states_carry_forward[states_carry_forward["group"] == group]
        ax.plot(main["week"], main["prevalence"], "o-", label="main (no imputation)", color="steelblue")
        ax.plot(cf["week"], cf["prevalence"], "--", label="carry-forward (sensitivity only)", color="indianred", alpha=0.7)
        low = main[main["low_n"]]
        ax.scatter(low["week"], low["prevalence"], marker="x", color="black", zorder=5, label="low_n < 10")
        ax.set_title(group)
        ax.set_ylim(0, 1)
    axes[0, 0].legend(fontsize=7, loc="upper right")
    fig.supxlabel("week (0 = Mon 2009-06-29)")
    fig.supylabel("MRSA prevalence")
    fig.suptitle("Real weekly MRSA prevalence by ward group")
    fig.tight_layout()
    fig.savefig(config.RESULTS_FIGURES_DIR / "p3_prevalence_trajectory.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    build()
