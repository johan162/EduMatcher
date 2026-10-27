"""pm-compdb-cli: the company database.

Build the database of the simulated market's companies, look companies up,
list them with the columns, filters and order you choose, and add, change or
remove companies.

Usage examples:
  pm-compdb-cli init
  pm-compdb-cli show AAPL
  pm-compdb-cli list -c symbol,name,pe_ratio -w sector=TECH -w "pe_ratio<25" --sort pe_ratio
  pm-compdb-cli list -w "founder_story~garage" -c symbol,name,founders
  pm-compdb-cli --format csv list -c all > companies.csv
  pm-compdb-cli add ACME name="Acme Rockets" sector=INDUSTRIALS industry=Machinery
  pm-compdb-cli update ACME ceo_name="Wile E. Coyote" ceo_since=2024
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import textwrap
from contextlib import closing
from pathlib import Path
from typing import Any

from edumatcher.compdb.store import (
    COLUMNS,
    COMPANIES_DB,
    FIELDS,
    CompanyError,
    build,
    connect,
    delete,
    get,
    insert,
    load_seed,
    parse_filter,
    query,
    read_companies,
    update,
)

DEFAULT_COLUMNS = "symbol,name,sector,industry,market_cap_musd,pe_ratio"
MAX_CELL = 60  # table cells longer than this are cut short


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def _render(
    rows: list[dict[str, Any]], columns: list[str], fmt: str, no_header: bool
) -> None:
    if fmt == "json":
        print(json.dumps(rows, indent=2))
        return
    if fmt == "csv":
        writer = csv.writer(sys.stdout, lineterminator="\n")
        if not no_header:
            writer.writerow(columns)
        writer.writerows([_cell(row[c]) for c in columns] for row in rows)
        return
    if not rows:
        print("No companies found.")
        return
    cells = [
        [textwrap.shorten(_cell(row[c]), MAX_CELL, placeholder="...") for c in columns]
        for row in rows
    ]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]
    numeric = [COLUMNS[c].kind != "TEXT" for c in columns]

    def line(values: list[str]) -> str:
        return " | ".join(
            v.rjust(w) if num else v.ljust(w)
            for v, w, num in zip(values, widths, numeric, strict=True)
        ).rstrip()

    if not no_header:
        print(line(columns))
        print("-+-".join("-" * w for w in widths))
    for r in cells:
        print(line(r))


def _show(company: dict[str, Any]) -> None:
    width = max(len(c) for c in COLUMNS)
    for name in COLUMNS:
        text = _cell(company[name])
        lines = textwrap.wrap(text, 78 - width - 2) or [""]
        print(f"{name:<{width}}  {lines[0]}")
        for more in lines[1:]:
            print(f"{'':<{width}}  {more}")


def _assignments(items: list[str]) -> dict[str, str]:
    changes: dict[str, str] = {}
    for item in items:
        name, sep, value = item.partition("=")
        if not sep:
            raise CompanyError(
                f"{item!r}: use FIELD=VALUE (see: pm-compdb-cli columns)"
            )
        changes[name.strip()] = value
    return changes


def _columns_arg(text: str) -> list[str]:
    if text == "all":
        return list(COLUMNS)
    return [c.strip() for c in text.split(",") if c.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-compdb-cli",
        description="The company database of the simulated market.",
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-compdb-cli")
    parser.add_argument(
        "--db",
        type=Path,
        default=COMPANIES_DB,
        help=f"Database file (default: {COMPANIES_DB})",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json", "csv"),
        default="table",
        help="Output format of show and list (default: table)",
    )
    parser.add_argument(
        "--no-header", action="store_true", help="Leave out the table/CSV header"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Build the database of the bundled companies")
    init.add_argument("--force", action="store_true", help="Replace an existing one")
    sub.add_parser("columns", help="List the columns, with what each one holds")
    show = sub.add_parser("show", help="Everything about one or more companies")
    show.add_argument("symbols", nargs="+", metavar="SYMBOL")
    lst = sub.add_parser("list", help="List companies")
    lst.add_argument(
        "-c",
        "--columns",
        type=_columns_arg,
        default=_columns_arg(DEFAULT_COLUMNS),
        help=f"Comma-separated columns, or 'all' (default: {DEFAULT_COLUMNS})",
    )
    lst.add_argument(
        "-w",
        "--where",
        action="append",
        default=[],
        metavar="FILTER",
        help="COLUMN OP VALUE, OP one of = != < <= > >= ~ (contains); "
        "repeat to narrow further",
    )
    lst.add_argument("-s", "--sort", default="symbol", help="Column to sort by")
    lst.add_argument("--desc", action="store_true", help="Sort largest first")
    lst.add_argument("-n", "--limit", type=int, help="Show at most N companies")
    add = sub.add_parser("add", help="Add a company")
    add.add_argument("symbol", metavar="SYMBOL")
    add.add_argument(
        "fields",
        nargs="+",
        metavar="FIELD=VALUE",
        help="name, sector and industry are required",
    )
    imp = sub.add_parser("import", help="Add the companies of YAML files")
    imp.add_argument(
        "files", nargs="+", type=Path, metavar="FILE", help="Mapping of SYMBOL: fields"
    )
    upd = sub.add_parser("update", help="Change a company's fields")
    upd.add_argument("symbol", metavar="SYMBOL")
    upd.add_argument("fields", nargs="+", metavar="FIELD=VALUE", help="Empty: clear")
    rm = sub.add_parser("delete", help="Remove a company")
    rm.add_argument("symbol", metavar="SYMBOL")
    return parser


def run(args: argparse.Namespace) -> None:
    if args.command == "init":
        records = load_seed()
        build(args.db, records, force=args.force)
        print(f"{len(records)} companies written to {args.db}")
        return
    if args.command == "columns":
        derived = {c.name for c in COLUMNS.values()} - {c.name for c in FIELDS}
        for c in COLUMNS.values():
            note = " (derived)" if c.name in derived else ""
            print(f"{c.name:<22} {c.kind:<8} {c.description}{note}")
        return
    with closing(connect(args.db)) as conn:
        if args.command == "show":
            companies = []
            for symbol in args.symbols:
                company = get(conn, symbol)
                if company is None:
                    raise CompanyError(f"{symbol.upper()} is not in the database")
                companies.append(company)
            if args.format == "table":
                for i, company in enumerate(companies):
                    if i:
                        print()
                    _show(company)
            else:
                _render(companies, list(COLUMNS), args.format, args.no_header)
        elif args.command == "list":
            if args.limit is not None and args.limit < 1:
                raise CompanyError("--limit must be at least 1")
            filters = [parse_filter(f) for f in args.where]
            rows = query(conn, args.columns, filters, args.sort, args.desc, args.limit)
            _render(rows, args.columns, args.format, args.no_header)
        elif args.command == "import":
            records = read_companies(args.files)
            with conn:
                for rec in records:
                    insert(conn, rec)
            print(f"{len(records)} companies added")
        else:
            with conn:
                if args.command == "add":
                    insert(conn, {**_assignments(args.fields), "symbol": args.symbol})
                elif args.command == "update":
                    update(conn, args.symbol, _assignments(args.fields))
                else:
                    delete(conn, args.symbol)
            print(f"{args.symbol.upper()} {args.command}d")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except CompanyError as exc:
        print(f"pm-compdb-cli: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
