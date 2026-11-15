"""Week-to-week MRSA transitions per ward, for the demo's spreading scene.

Same people and same weekly rule as the P3 main series (src/build_states.py):
the 589 people in the contact network, one status per person-week, positive
if any swab that week was sarm=1. Each person tested in a week is then put in
exactly one class by comparing with their previous swab result:

    new       positive now, negative at their previous swab   (acquired MRSA)
    still     positive now, positive at their previous swab
    first     positive now, no earlier swab at all            (arrived carrying,
                                                               or first tested)
    cleared   negative now, positive at their previous swab
    negative  negative now, negative before or never tested

"Previous swab" is the person's latest earlier tested week in the window, or
their last swab before the window if that is all there is. Only counts per
ward-week are saved: no identifiers leave this module.

Assumption (stated in the demo): a new positive between two swabs means the
person acquired MRSA in between; it may also be a missed earlier positive.
"""
import pandas as pd

import config
from src.load import load_admission, load_contacts, load_microbio
from src.states import last_status_before_window, restrict_to_window, weekly_person_status

CLASSES = ["new", "still", "first", "cleared", "negative"]


def classify(person_status, before):
    """Add a 'kind' column (one of CLASSES) to the person-week table."""
    ps = person_status.sort_values(["calc_ident", "week"]).copy()
    ps["prev"] = ps.groupby("calc_ident")["status"].shift(1)
    pre = before.set_index("calc_ident")["last_status"]
    first_rows = ps["prev"].isna()
    ps.loc[first_rows, "prev"] = ps.loc[first_rows, "calc_ident"].map(pre)

    def kind(r):
        if r["status"] == 1:
            if pd.isna(r["prev"]):
                return "first"
            return "still" if r["prev"] == 1 else "new"
        return "cleared" if r["prev"] == 1 else "negative"

    ps["kind"] = ps.apply(kind, axis=1)
    return ps


def weekly_transitions(person_status, before):
    """Counts per (week, group) of each class, plus tested and positive."""
    ps = classify(person_status, before)
    counts = (ps.groupby(["week", "ward_group", "kind"]).size().unstack("kind", fill_value=0)
              .reindex(columns=CLASSES, fill_value=0).reset_index().rename(columns={"ward_group": "group"}))
    counts["tested"] = counts[CLASSES].sum(axis=1)
    counts["positive"] = counts[["new", "still", "first"]].sum(axis=1)
    return counts.sort_values(["week", "group"]).reset_index(drop=True)


def build(save=True):
    admission = load_admission(config.ADMISSION_CSV)
    contacts = load_contacts(config.CONTACTS_CSV)
    microbio = load_microbio(config.MICROBIO_CSV)
    network_people = set(contacts["from"]) | set(contacts["to"])
    in_window, before_window, _ = restrict_to_window(microbio)
    status = weekly_person_status(in_window, admission, person_filter=network_people)
    before = last_status_before_window(before_window[before_window["calc_ident"].isin(network_people)], admission)
    out = weekly_transitions(status, before)
    if save:
        out.to_csv(config.RESULTS_TABLES_DIR / "demo_weekly_transitions.csv", index=False)
    return out


if __name__ == "__main__":
    t = build()
    print(t.groupby("week")[CLASSES + ["tested", "positive"]].sum().to_string())
    print("totals:", t[CLASSES].sum().to_dict())
