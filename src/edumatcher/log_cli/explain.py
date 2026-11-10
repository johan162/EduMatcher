"""``pm-log-cli`` output for the log ledger: ``explain``, ``--explain``, ``ledger``.

The ledger itself lives in :mod:`edumatcher.log_ledger`
(docs-design/EduMatcher-Log-Ledger.md §4).
"""

from __future__ import annotations

import json
import textwrap
from collections import defaultdict
from typing import Any

from edumatcher.log_ledger import CheckReport, LedgerEntry
from edumatcher.log_ledger.scan import LEDGER_LEVELS

_WIDTH = 100


def entry_for(
    row: dict[str, Any], ledger: dict[str, LedgerEntry]
) -> LedgerEntry | None:
    tpl = row.get("tpl")
    return ledger.get(tpl) if tpl else None


def with_explain(
    rows: list[dict[str, Any]], ledger: dict[str, LedgerEntry]
) -> list[dict[str, Any]]:
    """Rows for JSON output, each WARNING+ row with an entry gets ``explain``."""
    out = []
    for row in rows:
        entry = entry_for(row, ledger)
        out.append(row if entry is None else {**row, "explain": _explain_dict(entry)})
    return out


def _explain_dict(entry: LedgerEntry) -> dict[str, Any]:
    return {"explanation": entry.explanation, "actions": list(entry.actions)}


def explanation_lines(entry: LedgerEntry, indent: str = "  ") -> list[str]:
    """The explanation and numbered actions, wrapped for a terminal."""
    lines = textwrap.wrap(
        entry.explanation, _WIDTH, initial_indent=indent, subsequent_indent=indent
    )
    for i, action in enumerate(entry.actions, 1):
        lines += textwrap.wrap(
            action,
            _WIDTH,
            initial_indent=f"{indent}{i}. ",
            subsequent_indent=f"{indent}   ",
        )
    return lines


def print_explain(
    row: dict[str, Any], ledger: dict[str, LedgerEntry], fmt: str
) -> None:
    """``pm-log-cli explain SEQ``."""
    entry = entry_for(row, ledger)
    if fmt == "json":
        print(
            json.dumps(
                {**row, "explain": None if entry is None else _explain_dict(entry)}
            )
        )
        return
    print(
        f"seq {row['seq']}  {row['client_ts']}  {row['level']}  "
        f"{row['process']}  {row['logger']}"
    )
    for line in str(row["message"]).splitlines() or [""]:
        print(f"  {line}")
    print()
    if row["level"] not in LEDGER_LEVELS:
        print(
            f"The ledger explains WARNING and above only; this row is {row['level']}."
        )
        return
    if entry is None:
        print(f"No ledger entry for this message (tpl={row.get('tpl') or 'none'}).")
        return
    _print_explanation_and_actions(entry)


def _print_explanation_and_actions(entry: LedgerEntry) -> None:
    print("Explanation:")
    print(
        textwrap.fill(
            entry.explanation, _WIDTH, initial_indent="  ", subsequent_indent="  "
        )
    )
    print()
    print("Actions:")
    for i, action in enumerate(entry.actions, 1):
        print(
            textwrap.fill(
                action, _WIDTH, initial_indent=f"  {i}. ", subsequent_indent="     "
            )
        )


def print_ledger_list(entries: list[LedgerEntry], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps([e.to_dict() for e in entries]))
        return
    if not entries:
        print("No ledger entries match.")
        return
    width = max(len(e.logger) for e in entries)
    print(f"{'tpl':<12} | {'level':<8} | {'logger':<{width}} | template")
    print(f"{'-' * 12}-+-{'-' * 8}-+-{'-' * width}-+-{'-' * 8}")
    for e in entries:
        print(f"{e.tpl:<12} | {e.level:<8} | {e.logger:<{width}} | {e.template}")


def print_ledger_entry(entry: LedgerEntry, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(entry.to_dict()))
        return
    print(f"tpl:      {entry.tpl}")
    print(f"level:    {entry.level}")
    print(f"logger:   {entry.logger}")
    print(f"template: {entry.template}")
    print(f"file:     {entry.source}")
    print()
    _print_explanation_and_actions(entry)


def export_json(ledger: dict[str, LedgerEntry]) -> str:
    """What the log-GUI bridge loads: ``{tpl: entry}``."""
    return json.dumps(
        {
            tpl: {k: v for k, v in e.to_dict().items() if k != "tpl"}
            for tpl, e in sorted(ledger.items())
        }
    )


def print_check(report: CheckReport, packages: list[str] | None, fmt: str) -> None:
    """``pm-log-cli ledger check``; ``packages`` narrows the missing list."""
    missing = [s for s in report.missing if not packages or s.package in packages]
    if fmt == "json":
        print(
            json.dumps(
                {
                    "ok": _ok(report, missing),
                    "missing": [
                        {
                            "where": s.where,
                            "logger": s.logger,
                            "level": s.level,
                            "template": s.template,
                        }
                        for s in missing
                    ],
                    "stale": [e.to_dict() for e in report.stale],
                    "level_mismatch": [
                        {**e.to_dict(), "expected_level": lv}
                        for e, lv in report.level_mismatch
                    ],
                    "problems": [
                        {"where": s.where, "problem": s.problem}
                        for s in report.problems
                    ],
                    "generic": [
                        {"where": s.where, "template": s.template}
                        for s in report.generic
                    ],
                }
            )
        )
        return
    for s in report.problems:
        print(f"PROBLEM  {s.where}: {s.problem}")
    for e in report.stale:
        print(f"STALE    {e.source}: no call site logs {e.logger}: {e.template!r}")
    for e, level in report.level_mismatch:
        print(
            f"LEVEL    {e.source}: {e.template!r} is {e.level}, the code logs {level}"
        )
    by_package: dict[str, list[Any]] = defaultdict(list)
    for s in missing:
        by_package[s.package].append(s)
    for package in sorted(by_package):
        print(f"MISSING  {package}: {len(by_package[package])} call site(s)")
        for s in by_package[package]:
            print(f"  {s.where}  {s.level}  {s.logger}: {s.template!r}")
    for s in report.generic:
        print(f"GENERIC  {s.where}: template {s.template!r} has no fixed text")
    print(
        "ledger check: OK"
        if _ok(report, missing)
        else f"ledger check: FAILED ({len(missing)} missing, {len(report.stale)} stale, "
        f"{len(report.level_mismatch)} level, {len(report.problems)} problem)"
    )


def _ok(report: CheckReport, missing: list[Any]) -> bool:
    return not (missing or report.stale or report.level_mismatch or report.problems)
