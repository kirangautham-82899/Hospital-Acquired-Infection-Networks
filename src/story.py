"""Find a real, possible spread chain for the step-by-step demo story.

A chain is three people who carried the SAME MRSA strain, linked by sensor
contacts in the right time order:

    A (patient, already positive)  --contact-->  B (staff, swab negative, then positive)
    B (now positive)               --contact-->  C (another patient, negative, then positive)

Cross-ward chains are preferred, but none exist in this data (staff work
almost only in their own ward), so the chain found is within one ward.
Only MRSA strain types count (strain codes starting "1."; "2." = MSSA).

This is a route CONSISTENT with the data, not proof of transmission: B or C
could have caught the strain from someone else, or from a contact the
sensors missed. The demo says so. Read-only on data/raw/.
"""
import pandas as pd

import config


def swab_timelines(microbio):
    """One sorted swab list per person: date, sarm (0/1) and strain."""
    m = microbio[["calc_ident", "date_prl", "sarm", "strain"]].copy()
    m["strain"] = m["strain"].astype(str)
    return {pid: g.sort_values("date_prl").reset_index(drop=True) for pid, g in m.groupby("calc_ident")}


def acquisitions(timelines):
    """Every negative -> positive switch between two consecutive swabs.
    Returns rows: person, last negative date, first positive date, strain."""
    rows = []
    for pid, t in timelines.items():
        for i in range(1, len(t)):
            if t.loc[i - 1, "sarm"] == 0 and t.loc[i, "sarm"] == 1:
                rows.append({"person": pid, "neg_date": t.loc[i - 1, "date_prl"],
                             "pos_date": t.loc[i, "date_prl"], "strain": t.loc[i, "strain"]})
    return pd.DataFrame(rows)


def positive_on(timeline, day, strain):
    """True if this person's most recent swab on or before `day` was MRSA of `strain`."""
    before = timeline[timeline["date_prl"] <= day]
    return (not before.empty) and before.iloc[-1]["sarm"] == 1 and before.iloc[-1]["strain"] == strain


def daily_contacts(contacts):
    """Contacts as (person, other, day, seconds), one row per direction."""
    return contacts.rename(columns={"from": "person", "to": "other", "length": "seconds"})[["person", "other", "day", "seconds"]]


def find_chains(admission, contacts, microbio):
    """All A -> B -> C chains (patient -> staff -> patient on another ward,
    same MRSA strain, contacts in time order). Sorted so the chain with the
    most contact time on its weaker link comes first."""
    ward = admission.set_index("calc_ident")["service_pa_pe"].to_dict()
    tl = swab_timelines(microbio)
    acq = acquisitions(tl)
    acq = acq[acq["strain"].str.startswith(config.STORY_MRSA_STRAIN_PREFIX)]
    con = daily_contacts(contacts)
    by_person = {p: g for p, g in con.groupby("person")}
    chains = []
    staff_acq = acq[acq["person"].str.startswith("PE")]
    pat_acq = acq[acq["person"].str.startswith("PA")].set_index("person")
    for _, b in staff_acq.iterrows():
        if b["person"] not in by_person:
            continue
        cb = by_person[b["person"]]
        # link 1: contact with a patient A who was already carrying the strain, between B's two swabs
        l1 = cb[(cb["day"] > b["neg_date"]) & (cb["day"] <= b["pos_date"]) & cb["other"].str.startswith("PA")]
        l1 = l1[[positive_on(tl[a], d, b["strain"]) if a in tl else False for a, d in zip(l1["other"], l1["day"])]]
        if l1.empty:
            continue
        # link 2: after B is positive, contact with a patient C (other ward than A) who then acquires the strain
        l2 = cb[(cb["day"] >= b["pos_date"]) & cb["other"].isin(pat_acq.index)]
        for c_id, g2 in l2.groupby("other"):
            for _, ca in pat_acq.loc[[c_id]].iterrows():
                if ca["strain"] != b["strain"]:
                    continue
                g = g2[(g2["day"] > ca["neg_date"]) & (g2["day"] <= ca["pos_date"])]
                g = g[[positive_on(tl[b["person"]], d, b["strain"]) for d in g["day"]]]
                if g.empty:
                    continue
                for a_id, g1 in l1.groupby("other"):
                    if a_id == c_id:
                        continue
                    chains.append({
                        "A": a_id, "B": b["person"], "C": c_id, "strain": b["strain"],
                        "ward_A": ward.get(a_id), "ward_B": ward.get(b["person"]), "ward_C": ward.get(c_id),
                        "B_neg": b["neg_date"], "B_pos": b["pos_date"], "C_neg": ca["neg_date"], "C_pos": ca["pos_date"],
                        "AB_first_day": g1["day"].min(), "AB_seconds": float(g1["seconds"].sum()), "AB_days": int(g1["day"].nunique()),
                        "BC_first_day": g["day"].min(), "BC_seconds": float(g["seconds"].sum()), "BC_days": int(g["day"].nunique()),
                    })
    out = pd.DataFrame(chains)
    if out.empty:
        return out
    out["weak_link_seconds"] = out[["AB_seconds", "BC_seconds"]].min(axis=1)
    out["cross_ward"] = out["ward_A"] != out["ward_C"]
    return out.sort_values(["cross_ward", "weak_link_seconds", "A", "B", "C"],
                           ascending=[False, False, True, True, True]).reset_index(drop=True)


def story_events(chain, contacts, microbio):
    """Anonymised event list for one chain: every swab of A, B and C in the
    story window, and every qualifying contact day (A-B between B's negative
    and positive swab; B-C between C's negative and positive swab). People
    are only 'A', 'B', 'C' here: no identifiers leave this function."""
    label = {chain["A"]: "A", chain["B"]: "B", chain["C"]: "C"}
    start = chain["AB_first_day"] - pd.Timedelta(days=config.STORY_WINDOW_PAD_DAYS)
    end = chain["C_pos"] + pd.Timedelta(days=config.STORY_WINDOW_PAD_DAYS)
    rows = []
    sw = microbio[microbio["calc_ident"].isin(label) & microbio["date_prl"].between(start, end)]
    for _, r in sw.sort_values("date_prl").iterrows():
        rows.append({"who": label[r["calc_ident"]], "event": "swab", "date": r["date_prl"].date().isoformat(),
                     "mrsa": int(r["sarm"]), "strain": str(r["strain"]) if r["sarm"] == 1 else "", "minutes": ""})
    con = daily_contacts(contacts)

    def pair(x, y, lo, hi, tag):
        g = con[(con["person"] == x) & (con["other"] == y) & (con["day"] > lo) & (con["day"] <= hi)]
        for _, r in g.sort_values("day").iterrows():
            rows.append({"who": tag, "event": "contact", "date": r["day"].date().isoformat(),
                         "mrsa": "", "strain": "", "minutes": round(r["seconds"] / 60.0, 1)})

    pair(chain["B"], chain["A"], chain["B_neg"], chain["B_pos"], "AB")
    pair(chain["B"], chain["C"], chain["C_neg"], chain["C_pos"], "BC")
    return pd.DataFrame(rows).sort_values(["date", "event"]).reset_index(drop=True)


def story_summary(chain, chains, microbio):
    """One row of context: ward, strain, how common the strain is among
    MRSA-positive swabs (a common strain makes the route weaker evidence),
    and how many chains / cross-ward chains the search found."""
    pos = microbio[microbio["sarm"] == 1]
    return pd.DataFrame([{
        "ward": chain["ward_B"], "strain": chain["strain"],
        "strain_share_of_mrsa_swabs": float((pos["strain"].astype(str) == chain["strain"]).mean()),
        "n_chains_found": int(len(chains)), "n_cross_ward_chains": int(chains["cross_ward"].sum()),
    }])


def build_story(save=True):
    """Find chains, keep the top one, save the anonymised events and summary
    to results/tables/ and return them."""
    from src.load import load_all
    a, c, m = load_all(config.ADMISSION_CSV, config.CONTACTS_CSV, config.MICROBIO_CSV)
    chains = find_chains(a, c, m)
    assert not chains.empty, "no chain found"
    top = chains.iloc[0]
    events, summary = story_events(top, c, m), story_summary(top, chains, m)
    if save:
        events.to_csv(config.RESULTS_TABLES_DIR / "story_chain_events.csv", index=False)
        summary.to_csv(config.RESULTS_TABLES_DIR / "story_chain_summary.csv", index=False)
    return events, summary


if __name__ == "__main__":
    ev, su = build_story()
    print(su.to_string(index=False))
    print(ev.to_string(index=False))
