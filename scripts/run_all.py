"""Rebuild every result from the committed inputs (offline): model, figures, README.md and docs/validation_report.md.

    python scripts/run_all.py            # full run, including the three equilibrium assignments
    python scripts/run_all.py --reuse-assignment   # keep results/link_flows.csv, redo everything else
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stm import pipeline  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reuse-assignment", action="store_true")
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args()
    pipeline.run(assign_scenarios=not a.reuse_assignment)
    if not a.no_figures:
        from stm import plots
        plots.make_all()
    from stm import report
    report.write_all()


if __name__ == "__main__":
    main()
