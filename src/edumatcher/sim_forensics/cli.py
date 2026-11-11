"""Command line: ``pm-sim-forensics``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from edumatcher.cli_version import add_version_argument, package_version
from edumatcher.config import DATA_DIR
from edumatcher.sim_forensics import report

# Importing the package registers every check.
import edumatcher.sim_forensics.checks  # noqa: F401  # pyright: ignore[reportUnusedImport]
from edumatcher.sim_forensics.dataset import Dataset
from edumatcher.sim_forensics.registry import REGISTRY, Result, run_checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-sim-forensics",
        description="Check a finished simulation run's records against each other.",
    )
    add_version_argument(parser, "pm-sim-forensics")
    parser.add_argument(
        "--data",
        type=Path,
        default=DATA_DIR,
        help="Run's data dir, sim stopped (default: the data dir of this install)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DATA_DIR.parent / "forensics",
        help="Directory for report.md/findings.json (default: forensics/ beside the data dir)",
    )
    parser.add_argument(
        "--check", action="append", metavar="ID", help="Run only these checks"
    )
    parser.add_argument(
        "--samples", type=int, default=10, metavar="N", help="Samples kept per check"
    )
    parser.add_argument(
        "--slow",
        action="store_true",
        help="Also run the slow checks (E5-E7: several engine re-runs)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        metavar="N",
        help="Processes to run checks in, one module's checks together "
        "(default: one per CPU; 1 = in this process)",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="No progress output on stderr"
    )
    parser.add_argument("--list", action="store_true", help="List checks and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        for c in REGISTRY.values():
            print(f"{c.id:5} {c.oracle:13} {c.title}{'  (slow)' if c.slow else ''}")
        return 0
    if not args.data.is_dir():
        parser.error(f"--data {args.data} is not a directory")
    unknown = sorted(set(args.check or ()) - REGISTRY.keys())
    if unknown:
        parser.error(f"unknown check id(s): {', '.join(unknown)}")

    selected = [
        REGISTRY[i] for i in sorted(REGISTRY) if not args.check or i in args.check
    ]
    total = sum(1 for c in selected if args.slow or args.check or not c.slow)
    count = 0

    def progress(r: Result) -> None:
        nonlocal count
        count += 1
        print(
            f"[{count}/{total}] {r.check.id:5} {r.status:8} {r.seconds:6.1f}s  "
            f"{r.check.title}",
            file=sys.stderr,
            flush=True,
        )

    with Dataset.open(args.data.expanduser()) as ds:
        # A check named with --check runs even if slow.
        results = run_checks(
            ds,
            selected,
            args.samples,
            args.slow or bool(args.check),
            args.jobs or os.cpu_count() or 1,
            None if args.quiet else progress,
        )
        report.write(ds, results, args.out.expanduser(), package_version())
    for r in results:
        print(f"{r.check.id:5} {r.status:8} {r.violations:>8}  {r.check.title}")
    print(f"report: {args.out / 'report.md'}")
    return 1 if any(r.status in ("FAIL", "ERROR") for r in results) else 0
