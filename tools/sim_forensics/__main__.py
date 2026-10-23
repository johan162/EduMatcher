"""Command line: ``PYTHONPATH=tools python -m sim_forensics``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sim_forensics import checks  # noqa: F401  (registers the checks)
from sim_forensics import report
from sim_forensics.dataset import Dataset
from sim_forensics.registry import REGISTRY, run_checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sim_forensics",
        description="Check a finished simulation run's records against each other.",
    )
    parser.add_argument("--data", type=Path, help="Run's data dir (sim stopped)")
    parser.add_argument(
        "--out", type=Path, help="Directory for report.md/findings.json"
    )
    parser.add_argument(
        "--check", action="append", metavar="ID", help="Run only these checks"
    )
    parser.add_argument(
        "--samples", type=int, default=10, metavar="N", help="Samples kept per check"
    )
    parser.add_argument("--list", action="store_true", help="List checks and exit")
    args = parser.parse_args(argv)

    if args.list:
        for c in REGISTRY.values():
            print(f"{c.id:5} {c.oracle:13} {c.title}")
        return 0
    if args.data is None or args.out is None:
        parser.error("--data and --out are required")
    if not args.data.is_dir():
        parser.error(f"--data {args.data} is not a directory")
    unknown = sorted(set(args.check or ()) - REGISTRY.keys())
    if unknown:
        parser.error(f"unknown check id(s): {', '.join(unknown)}")

    selected = [
        REGISTRY[i] for i in sorted(REGISTRY) if not args.check or i in args.check
    ]
    with Dataset.open(args.data.expanduser()) as ds:
        results = run_checks(ds, selected, args.samples)
        report.write(ds, results, args.out.expanduser())
    for r in results:
        print(f"{r.check.id:5} {r.status:8} {r.violations:>8}  {r.check.title}")
    print(f"report: {args.out / 'report.md'}")
    return 1 if any(r.status in ("FAIL", "ERROR") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
