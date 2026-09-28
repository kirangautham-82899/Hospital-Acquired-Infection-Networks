"""Run the full P1-P11 pipeline in order. Each phase's orchestrator reads
the previous phases' saved outputs from data/processed/ and results/, so
they must run in this order. See README.md for running phases
individually, and CLAUDE.md / research_log.md for what each phase does.

Does not include P0 (one-time environment setup) or P12 (this report/
slides/cleanup phase, which is not a data-producing step).
"""
import time

PHASES = [
    ("P1 data audit", "src.audit", "build_report"),  # named build_report, not build, elsewhere
    ("P2 contact network + ward matrix W", "src.build_network"),
    ("P3 real weekly prevalence", "src.build_states"),
    ("P4 SIS simulation + calibration", "src.build_simulation"),
    ("P5 observables", "src.build_observables"),
    ("P6 EDMD fit", "src.build_edmd"),
    ("P7 eigenmodes", "src.build_eigen"),
    ("P8 forecasting, validation, baselines", "src.build_p8"),
    ("P9 superspreader ward risk score vs centrality", "src.build_p9"),
    ("P10 intervention simulation", "src.build_p10"),
    ("P11 robustness experiments E1-E8", "src.build_p11"),
]


def main():
    import importlib

    for entry in PHASES:
        label, module_name = entry[0], entry[1]
        entry_point = entry[2] if len(entry) > 2 else "build"
        print("\n" + "=" * 70)
        print(f"RUNNING {label} ({module_name}.{entry_point}())")
        print("=" * 70)
        t0 = time.time()
        module = importlib.import_module(module_name)
        getattr(module, entry_point)()
        print(f"\n[{label} done in {time.time() - t0:.1f}s]")

    print("\n" + "=" * 70)
    print("FULL PIPELINE COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
