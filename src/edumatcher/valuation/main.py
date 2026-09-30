"""pm-valuation — find the IPO price of a fictive company (design §21)."""

from __future__ import annotations

import argparse
import sys
from importlib.resources import files
from pathlib import Path

from edumatcher.valuation.fields import Level
from edumatcher.valuation.pipeline import CannotValue, run
from edumatcher.valuation.presets import load_presets
from edumatcher.valuation.report.build import build_report, listing_args
from edumatcher.valuation.report.render_md import render_markdown
from edumatcher.valuation.report.render_rich import print_report
from edumatcher.valuation.resolve import InvalidAnswers, resolve
from edumatcher.valuation.scenario_io import dump, load

#: The classroom cases shipped with the tool (``--case NAME``).
CASES = files("edumatcher.valuation").joinpath("cases")


def case_names() -> list[str]:
    return sorted(
        p.name.removesuffix(".yaml")
        for p in CASES.iterdir()
        if p.name.endswith(".yaml")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-valuation",
        description=(
            "Interview the student about a fictive company, value it with a "
            "two-stage DCF, and simulate the IPO that prices it."
        ),
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-valuation")
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--load", type=Path, help="Scenario file to start from")
    start.add_argument(
        "--case", choices=case_names(), help="Classroom case to start from"
    )
    parser.add_argument(
        "--no-tui", action="store_true", help="Print the report instead of interviewing"
    )
    parser.add_argument(
        "--level",
        choices=[level.name.lower() for level in Level],
        help="Interview detail: beginner (default), intermediate, advanced "
        "or expert; F3 changes it",
    )
    parser.add_argument(
        "--market",
        choices=("se", "us"),
        help="Where the company lists: se, Sweden (default), or us; "
        "overrides the scenario's",
    )
    parser.add_argument(
        "--mode",
        choices=("deterministic", "montecarlo", "both"),
        help="Scenarios, Monte Carlo, or both (default: the scenario's, else both)",
    )
    parser.add_argument("--draws", type=int, help="Monte Carlo draws")
    parser.add_argument("--seed", type=int, help="Monte Carlo seed")
    parser.add_argument("--save", type=Path, help="Write the scenario to this file")
    parser.add_argument(
        "--with-defaults",
        action="store_true",
        help="With --save: write every value, commented with its source",
    )
    parser.add_argument("--export", type=Path, help="Write the report as Markdown")
    parser.add_argument(
        "--pdf", type=Path, help="Write the report as a printable PDF (also p)"
    )
    parser.add_argument(
        "--paper", choices=("a4", "letter"), default="a4", help="PDF page size"
    )
    parser.add_argument("--presets", type=Path, help="Alternative presets file")
    parser.add_argument(
        "--list",
        action="store_true",
        help="With --no-tui: list the priced IPO with pm-new-symbol",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="With --list: the engine YAML pm-new-symbol edits",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.level is not None and args.no_tui:
        parser.error("--level chooses interview fields; it has no effect with --no-tui")
    if args.with_defaults and args.save is None:
        parser.error("--with-defaults needs --save")
    if args.list and not args.no_tui:
        parser.error("--list needs --no-tui")
    if args.config is not None and not args.list:
        parser.error("--config needs --list")
    try:
        presets = load_presets(args.presets)
        if args.load is not None:
            answers = load(args.load.read_text("utf-8"))
        elif args.case is not None:
            answers = load(CASES.joinpath(f"{args.case}.yaml").read_text("utf-8"))
        else:
            answers = {}
    except (OSError, ValueError) as exc:
        parser.exit(1, f"[ERROR] {exc}\n")
    for key, value in (
        ("company.market", args.market),
        ("simulation.mode", args.mode),
        ("simulation.draws", args.draws),
        ("simulation.seed", args.seed),
    ):
        if value is not None:
            answers[key] = value

    if not args.no_tui:
        from edumatcher.valuation.tui.app import interview

        level = Level[(args.level or "beginner").upper()]
        interview(answers, presets, level=level, save=args.save,
                  export=args.export, pdf=args.pdf, paper=args.paper)  # fmt: skip
        return

    try:
        result = run(answers, presets)
    except InvalidAnswers as exc:
        parser.exit(1, "".join(f"[ERROR] {m}\n" for _, m in exc.problems))
    except CannotValue as exc:
        parser.exit(1, f"[ERROR] {exc}\n")
    report = build_report(result, presets)
    print_report(report)
    if args.export is not None:
        args.export.write_text(render_markdown(report), encoding="utf-8")
    if args.pdf is not None:
        from edumatcher.valuation.report.render_pdf import write_pdf

        write_pdf(result, report, args.pdf, args.paper)
    if args.save is not None:
        resolved = resolve(answers, presets) if args.with_defaults else None
        args.save.write_text(dump(answers, resolved), encoding="utf-8")
    if args.list:
        listing = result.pricing.listing
        if listing is None:
            parser.exit(1, "[ERROR] the IPO is postponed: there is nothing to list\n")
        from edumatcher.new_symbol.main import main as new_symbol

        argv = listing_args(result.resolved["company.ticker"], listing)
        if args.config is not None:
            argv += ["--config", str(args.config)]
        new_symbol(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
