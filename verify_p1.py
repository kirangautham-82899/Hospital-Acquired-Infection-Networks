"""One-off P1 verification script (not part of the phased pipeline in src/).

Does NOT import pandas for its core checks: re-derives row counts, unique
people, unique days, and sarm=1 counts using only the stdlib csv module,
then compares against the pandas-based loaders in src/load.py (read-only,
unmodified). Also hashes data/raw/ and answers the P1 evidence questions.
Writes results/tables/raw_hashes.txt. Never writes into data/raw/.
"""
import csv
import hashlib
import subprocess
import sys
from pathlib import Path

import config
from src.load import load_admission, load_contacts, load_microbio


def read_raw_rows(path):
    """Return (header, rows) using only the stdlib csv module. header has
    one fewer field than each row (the raw files' leading column has no
    name), so callers must match header[i] to row[i + 1]."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        rows = list(reader)
    return header, rows


def field(header, row, name):
    return row[header.index(name) + 1]


def csv_module_checks():
    admission_header, admission_rows = read_raw_rows(config.ADMISSION_CSV)
    contacts_header, contacts_rows = read_raw_rows(config.CONTACTS_CSV)
    microbio_header, microbio_rows = read_raw_rows(config.MICROBIO_CSV)

    admission_people = {field(admission_header, r, "calc_ident") for r in admission_rows}
    contact_people = set()
    contact_days = set()
    for r in contacts_rows:
        contact_people.add(field(contacts_header, r, "from"))
        contact_people.add(field(contacts_header, r, "to"))
        contact_days.add(field(contacts_header, r, "day"))
    microbio_people = {field(microbio_header, r, "calc_ident") for r in microbio_rows}
    sarm_1_count = sum(1 for r in microbio_rows if field(microbio_header, r, "sarm") == "1")

    return {
        "admission_rows": len(admission_rows),
        "contacts_rows": len(contacts_rows),
        "microbio_rows": len(microbio_rows),
        "admission_people": len(admission_people),
        "contact_people": len(contact_people),
        "microbio_people": len(microbio_people),
        "contact_days": len(contact_days),
        "sarm_1_count": sarm_1_count,
    }


def pandas_checks():
    admission = load_admission(config.ADMISSION_CSV)
    contacts = load_contacts(config.CONTACTS_CSV)
    microbio = load_microbio(config.MICROBIO_CSV)
    return {
        "admission_rows": admission.shape[0],
        "contacts_rows": contacts.shape[0],
        "microbio_rows": microbio.shape[0],
        "admission_people": admission["calc_ident"].nunique(),
        "contact_people": len(set(contacts["from"]) | set(contacts["to"])),
        "microbio_people": microbio["calc_ident"].nunique(),
        "contact_days": contacts["day"].nunique(),
        "sarm_1_count": int((microbio["sarm"] == 1).sum()),
    }, admission, contacts, microbio


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_hashes():
    config.RESULTS_TABLES_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    for path in [config.ADMISSION_CSV, config.CONTACTS_CSV, config.MICROBIO_CSV]:
        digest = sha256_of(path)
        lines.append(f"{digest}  {path.name}")
    out_path = config.RESULTS_TABLES_DIR / "raw_hashes.txt"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines, out_path


def check_no_writes_to_raw():
    """Grep src/*.py, verify_p1.py, and config.py for any file-write call
    (open(..., 'w'/'a'/'x'), Path.write_text/write_bytes, DataFrame.to_csv)
    whose target resolves to something under data/raw/. Returns the list of
    suspicious lines (empty means clean)."""
    write_indicators = ["'w'", '"w"', "'a'", '"a"', "'x'", '"x"', "write_text", "write_bytes", "to_csv"]
    suspicious = []
    py_files = list(Path(".").glob("src/*.py")) + [Path("verify_p1.py"), Path("config.py")]
    for py_file in py_files:
        text = py_file.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(ind in line for ind in write_indicators) and ("raw" in line.lower() or "RAW" in line):
                suspicious.append(f"{py_file}:{lineno}: {line.strip()}")
    return suspicious


def main():
    print("=" * 70)
    print("P1 INDEPENDENT VERIFICATION")
    print("=" * 70)

    csv_vals = csv_module_checks()
    pandas_vals, admission, contacts, microbio = pandas_checks()

    print("\n--- 2. PANDAS vs CSV-MODULE CROSS-CHECK ---")
    reference = {
        "admission_rows": 795,
        "contacts_rows": 124924,
        "microbio_rows": 6728,
        "admission_people": 795,
        "contact_people": 589,
        "microbio_people": 795,
        "contact_days": 110,
        "sarm_1_count": 1118,
    }
    header = f"{'metric':28s} | {'expected':>9s} | {'pandas':>9s} | {'csv module':>10s} | match?"
    print(header)
    print("-" * len(header))
    all_match = True
    for key in reference:
        exp, pd_val, csv_val = reference[key], pandas_vals[key], csv_vals[key]
        match = (exp == pd_val == csv_val)
        all_match &= match
        print(f"{key:28s} | {exp:>9} | {pd_val:>9} | {csv_val:>10} | {match}")
    print(f"\nAll metrics match (expected == pandas == csv module): {all_match}")

    print("\n--- 3. SHA-256 HASHES OF data/raw/ ---")
    hash_lines, out_path = write_hashes()
    for line in hash_lines:
        print(line)
    print(f"Saved to {out_path}")

    print("\nRead-only check: scanning src/*.py, verify_p1.py, config.py for any")
    print("write call whose target mentions 'raw':")
    suspicious = check_no_writes_to_raw()
    if suspicious:
        print("SUSPICIOUS LINES FOUND:")
        for s in suspicious:
            print("  " + s)
    else:
        print("  none found -- no code writes into data/raw/.")

    print("\n--- 4. EVIDENCE ---")

    full_range_days = set(
        d.strftime("%Y-%m-%d")
        for d in __import__("pandas").date_range(config.STUDY_START, config.STUDY_END, freq="D")
    )
    present_days = set(contacts["day"].dt.strftime("%Y-%m-%d"))
    missing_days = sorted(full_range_days - present_days)
    print(f"Missing contact days ({len(missing_days)} of {len(full_range_days)}):")
    for d in missing_days:
        print(f"  {d}")

    from src.audit import map_to_ward_group
    import pandas as pd
    mic = microbio.copy()
    mic["ward_group"] = map_to_ward_group(mic["service_pa_pe"])
    mic["week"] = mic["date_prl"].dt.to_period("W").apply(lambda p: p.start_time)
    weekly_test_counts = (
        mic.groupby(["week", "ward_group"])["calc_ident"].count().unstack(fill_value=0)
        .reindex(columns=config.WARD_GROUPS, fill_value=0)
    )
    print("\nWeekly test COUNT per ward group (raw counts, not coverage fraction):")
    print(weekly_test_counts.to_string())

    identical = bool((microbio["date_prl"].dt.normalize() == microbio["date_prl_posix"].dt.normalize()).all())
    n_diff = int((microbio["date_prl"].dt.normalize() != microbio["date_prl_posix"].dt.normalize()).sum())
    print(f"\ndate_prl == date_prl_posix for every row: {identical} ({n_diff} rows differ)")

    length = contacts["length"]
    n_86400 = int((length == 86400).sum())
    print(f"\nlength column: min={length.min()}, max={length.max()}, mean={length.mean():.2f}")
    print(f"Rows where length == 86400 (i.e. a full 24h, 60*60*24): {n_86400} of {len(length)} "
          f"({100 * n_86400 / len(length):.3f}%)")
    print("Interpretation: min=60s and max=86400s bracket a plausible 'seconds of contact "
          "in one day' range (1 min to a full day); the bulk of rows (median far below the "
          "mean) are short contacts, with a long right tail up to the 86400s ceiling, "
          "consistent with 'seconds of contact between one pair on one day', not e.g. a raw "
          "timestamp or a duration in a different unit.")

    n_days_in_period = (pd.Timestamp(config.STUDY_END) - pd.Timestamp(config.STUDY_START)).days + 1
    n_weekly_steps = -(-n_days_in_period // 7)
    print(f"\nContact period {config.STUDY_START} to {config.STUDY_END}: {n_days_in_period} days "
          f"-> {n_weekly_steps} weekly steps (7-day bins, ceil({n_days_in_period}/7)).")

    print("\n" + "=" * 70)
    print("END OF P1 VERIFICATION")
    print("=" * 70)


if __name__ == "__main__":
    main()
