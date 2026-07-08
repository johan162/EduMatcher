"""Output formatters for pm-audit-cli: table, JSON, and CSV.

All three renderers accept the same ``rows`` / ``columns`` interface so the
query layer can stay format-agnostic.
"""

from __future__ import annotations

import csv
import json
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def stringify(value: Any) -> str:
    """Convert any cell value to a display-safe string."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


# ---------------------------------------------------------------------------
# Table renderer
# ---------------------------------------------------------------------------


def render_table(
    rows: list[dict[str, Any]],
    columns: list[str],
    no_header: bool = False,
) -> None:
    """Print *rows* as a plain-text aligned table to stdout.

    When *rows* is empty a ``No matching events found.`` message is printed
    and the function returns.
    """
    if not rows:
        print("No matching events found.")
        return

    widths: list[int] = []
    for col in columns:
        content_w = max((len(stringify(row.get(col))) for row in rows), default=0)
        widths.append(max(len(col), content_w))

    def _line(values: list[str]) -> str:
        return " | ".join(v.ljust(w) for v, w in zip(values, widths, strict=True))

    if not no_header:
        print(_line(columns))
        print("-+-".join("-" * w for w in widths))

    for row in rows:
        print(_line([stringify(row.get(col)) for col in columns]))


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------


def render_json(
    rows: list[dict[str, Any]],
    columns: list[str],
) -> None:
    """Print *rows* as a JSON array to stdout.

    When *rows* is empty prints ``[]``.
    """
    projected = [{col: row.get(col) for col in columns} for row in rows]
    print(json.dumps(projected, indent=2))


# ---------------------------------------------------------------------------
# CSV renderer
# ---------------------------------------------------------------------------


def render_csv(
    rows: list[dict[str, Any]],
    columns: list[str],
    no_header: bool = False,
) -> None:
    """Print *rows* as CSV to stdout.

    When *rows* is empty and *no_header* is False, the header row is still
    printed.  When *no_header* is True nothing is printed for empty results.
    """
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=columns,
        extrasaction="ignore",
        lineterminator="\n",
    )
    if not no_header:
        writer.writeheader()
    for row in rows:
        writer.writerow({col: stringify(row.get(col)) for col in columns})


# ---------------------------------------------------------------------------
# Unified dispatch
# ---------------------------------------------------------------------------


def render(
    rows: list[dict[str, Any]],
    columns: list[str],
    fmt: str,
    no_header: bool = False,
) -> None:
    """Dispatch to the appropriate renderer based on *fmt*.

    Accepted values for *fmt*: ``"table"``, ``"json"``, ``"csv"``.
    """
    if fmt == "json":
        render_json(rows, columns)
    elif fmt == "csv":
        render_csv(rows, columns, no_header=no_header)
    else:
        render_table(rows, columns, no_header=no_header)


# ---------------------------------------------------------------------------
# Stats display
# ---------------------------------------------------------------------------


def render_stats(stats: dict[str, Any], verbose: bool = False) -> None:
    """Print the ``stats`` command output in the design-specified format."""

    def _fmt_bytes(n: int) -> str:
        if n >= 1_073_741_824:
            return f"{n / 1_073_741_824:.1f} GB"
        if n >= 1_048_576:
            return f"{n / 1_048_576:.1f} MB"
        if n >= 1_024:
            return f"{n / 1_024:.1f} KB"
        return f"{n} B"

    total_bytes: int = stats.get("total_bytes", 0)
    comp_bytes: int = stats.get("compressed_bytes", 0)
    uncompressed = total_bytes - comp_bytes

    size_str = _fmt_bytes(uncompressed)
    if comp_bytes:
        size_str += f" (compressed: {_fmt_bytes(comp_bytes)})"

    print("Audit Log Statistics")
    print("━" * 50)
    print(f"  Total events:       {stats.get('total_events', 0):,}")
    print(f"  Total size:         {size_str}")
    print(f"  Log files:          {stats.get('file_count', 0)}")
    print(f"  Oldest event:       {stats.get('oldest_event') or 'n/a'}")
    print(f"  Newest event:       {stats.get('newest_event') or 'n/a'}")
    print(f"  Topics seen:        {stats.get('topic_count', 0):,}")
    print(f"  Gateways seen:      {stats.get('gateway_count', 0):,}")

    if verbose:
        files: list[dict[str, Any]] = stats.get("files", [])
        if files:
            print()
            print("  Per-file breakdown:")
            for f in files:
                print(
                    f"    {f['file']}  "
                    f"{f['events']:,} events  "
                    f"{_fmt_bytes(int(f['size_bytes']))}"
                )
