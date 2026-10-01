"""Report → rich renderables, for the terminal and the TUI's report viewer."""

from __future__ import annotations

import re

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.markup import escape
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table as RichTable
from rich.text import Text

from edumatcher.valuation.report.build import (
    Block,
    Bullets,
    Paragraph,
    Report,
    Section,
    Table,
)

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_VERDICT_STYLE = {"PROCEED": "bold green", "POSTPONE": "bold red"}

#: Printed reports are this wide on any terminal, so every copy reads the same.
REPORT_WIDTH = 100


def _markup(text: str) -> Text:
    """Plain text with the builder's only markup, **bold**, made bold."""
    return Text.from_markup(_BOLD.sub(r"[bold]\1[/bold]", escape(text)))


def _rich_table(block: Table, columns: list[int]) -> RichTable:
    table = RichTable(
        box=box.SIMPLE_HEAD, pad_edge=False, show_header=any(block.headers)
    )
    for i in columns:
        table.add_column(
            block.headers[i], justify="right" if block.align[i] == "r" else "left"
        )
    for row in block.rows:
        table.add_row(*(row[i] for i in columns))
    return table


class _FittedTable:
    """A table split into column groups, each repeating the first column, when
    it cannot fit the width without cutting cells short (the ten-year tables
    in an 80-column terminal)."""

    def __init__(self, block: Table) -> None:
        self.block = block

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        def fits(columns: list[int]) -> bool:
            # Rendered, not measured: rich's column shrinking can cut a header
            # word even when the measured minimum fits.
            lines = console.render_lines(_rich_table(self.block, columns), options)
            return not any("…" in seg.text for line in lines for seg in line)

        groups, current = [], [0]
        for i in range(1, len(self.block.headers)):
            if len(current) == 1 or fits([*current, i]):
                current.append(i)
            else:
                groups.append(current)
                current = [0, i]
        groups.append(current)
        for n, columns in enumerate(groups):
            if n:
                yield Text("")
            yield _rich_table(self.block, columns)


def _block(block: Block) -> RenderableType:
    if isinstance(block, Table):
        return _FittedTable(block)
    if isinstance(block, Paragraph):
        return _markup(block.text)
    if isinstance(block, Bullets):
        return Group(*(Text("• ").append_text(_markup(item)) for item in block.items))
    return Panel(Text(block.text), box=box.ROUNDED, expand=False)


def render_section(section: Section) -> RenderableType:
    title = Text(section.title, style="bold cyan")
    body = [Padding(_block(b), (0, 0, 1, 2), expand=False) for b in section.blocks]
    return Group(title, *body)


def render_report(report: Report) -> RenderableType:
    style = _VERDICT_STYLE.get(report.verdict, "bold yellow")
    head = Text(report.title, style="bold").append(f"  {report.verdict}", style=style)
    return Group(head, Text(""), *(render_section(s) for s in report.sections))


def print_report(report: Report, console: Console | None = None) -> None:
    (console or Console(width=REPORT_WIDTH)).print(render_report(report))
