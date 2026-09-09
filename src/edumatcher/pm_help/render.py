"""Rendering for ``pm-help``/``pm-man``: the command table and man pages.

Two output styles, selected with ``--format``:

``table`` (default)
    Rich UTF-8 box-drawing tables, coloured on a terminal.
``text``
    Plain aligned columns with no box-drawing characters and no colour --
    friendly to pipes (``| grep``), redirects, and non-UTF-8 terminals.
"""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from edumatcher.pm_help.registry import (
    COMMON_LOG_OPTIONS,
    COMMON_VERSION_OPTION,
    CommandInfo,
    Option,
    commands_by_category,
)

TableFormat = str  # "table" | "text"


def make_console(
    *, output_format: TableFormat, no_color: bool, width: int | None = None
) -> Console:
    """Build a :class:`~rich.console.Console` matching ``pm-config-show``'s
    conventions: colour belongs on a terminal, not in a redirect."""
    return Console(
        width=width,
        no_color=no_color or output_format == "text",
        force_terminal=not no_color,
        highlight=False,
        soft_wrap=False,
    )


def _box_for(output_format: TableFormat) -> box.Box | None:
    return box.ROUNDED if output_format == "table" else None


def _effective_options(cmd: CommandInfo) -> tuple[Option, ...]:
    opts = cmd.options
    if cmd.has_common_log_options:
        opts = opts + COMMON_LOG_OPTIONS
    if cmd.has_version_option:
        opts = opts + (COMMON_VERSION_OPTION,)
    return opts


# ---------------------------------------------------------------------------
# Mode A: the full command index
# ---------------------------------------------------------------------------


def render_command_index(
    console: Console,
    *,
    output_format: TableFormat,
    verbose: bool,
) -> None:
    """Print one table per category, each row a command and its one-sentence summary."""
    style_box = _box_for(output_format)
    use_color = output_format == "table"

    for category, cmds in commands_by_category():
        table = Table(
            box=style_box,
            show_header=True,
            header_style="bold cyan" if use_color else None,
            title=category,
            title_style="bold" if use_color else None,
            title_justify="left",
            expand=False,
            pad_edge=False,
        )
        table.add_column(
            "Command", style="bold green" if use_color else None, no_wrap=True
        )
        table.add_column("Summary", overflow="fold")
        for cmd in cmds:
            name_cell = cmd.name
            if cmd.aliases:
                name_cell = f"{cmd.name} ({', '.join(cmd.aliases)})"
            table.add_row(name_cell, cmd.summary)
            if verbose:
                extra = _verbose_index_line(cmd)
                if extra:
                    table.add_row("", extra)
        console.print(table)
        console.print()


def _verbose_index_line(cmd: CommandInfo) -> str:
    parts: list[str] = []
    if cmd.examples:
        parts.append(f"e.g. {cmd.examples[0]}")
    elif cmd.ports:
        parts.append(cmd.ports)
    if cmd.related:
        parts.append(f"related: {', '.join(cmd.related)}")
    return "  |  ".join(parts)


# ---------------------------------------------------------------------------
# Mode B: a single command's man page
# ---------------------------------------------------------------------------


def _heading(console: Console, text: str, *, use_color: bool) -> None:
    console.print()
    console.print(Text(text.upper(), style="bold cyan" if use_color else "bold"))


def _options_table(options: tuple[Option, ...], *, output_format: TableFormat) -> Table:
    style_box = _box_for(output_format)
    use_color = output_format == "table"
    table = Table(
        box=style_box,
        show_header=True,
        header_style="bold" if use_color else None,
        pad_edge=False,
    )
    table.add_column("Flag", style="green" if use_color else None, no_wrap=True)
    table.add_column("Default", no_wrap=True)
    table.add_column("Description", overflow="fold")
    for opt in options:
        table.add_row(opt.flags, opt.default, opt.help)
    return table


def render_man_page(
    console: Console,
    cmd: CommandInfo,
    *,
    output_format: TableFormat,
) -> None:
    use_color = output_format == "table"
    style_box = _box_for(output_format)

    title = f"{cmd.name} -- {cmd.title}" if cmd.title else cmd.name
    console.print(Text(title, style="bold" if use_color else ""))
    if cmd.aliases:
        console.print(f"Aliases: {', '.join(cmd.aliases)}")

    _heading(console, "NAME", use_color=use_color)
    console.print(f"{cmd.name} - {cmd.summary}")

    _heading(console, "SYNOPSIS", use_color=use_color)
    for line in cmd.synopsis:
        console.print(f"  {line}")

    if cmd.description:
        _heading(console, "DESCRIPTION", use_color=use_color)
        for para in cmd.description:
            console.print(para)
            console.print()

    options = _effective_options(cmd)
    if options:
        _heading(console, "OPTIONS", use_color=use_color)
        # Group options that carry an explicit `group`; keep ungrouped ones
        # (the common majority) in one table so the page doesn't fragment
        # for the ~30 commands that have no groups at all.
        groups: dict[str, list[Option]] = {}
        order: list[str] = []
        for opt in options:
            key = opt.group or ""
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(opt)
        for key in order:
            if key:
                console.print(Text(key, style="bold" if use_color else ""))
            console.print(
                _options_table(tuple(groups[key]), output_format=output_format)
            )

    if cmd.subcommands:
        _heading(console, "SUBCOMMANDS", use_color=use_color)
        table = Table(
            box=style_box,
            show_header=True,
            header_style="bold" if use_color else None,
            pad_edge=False,
        )
        table.add_column(
            "Subcommand", style="green" if use_color else None, no_wrap=True
        )
        table.add_column("Aliases", no_wrap=True)
        table.add_column("Args", no_wrap=True)
        table.add_column("Purpose", overflow="fold")
        for sub in cmd.subcommands:
            table.add_row(sub.name, ", ".join(sub.aliases), sub.args, sub.purpose)
        console.print(table)

    if cmd.ports:
        _heading(console, "PORTS", use_color=use_color)
        console.print(cmd.ports)

    if cmd.messages:
        _heading(console, "MESSAGE BUS", use_color=use_color)
        for line in cmd.messages:
            console.print(f"- {line}")

    if cmd.related:
        _heading(console, "RELATED COMMANDS", use_color=use_color)
        console.print(", ".join(cmd.related))

    if cmd.examples:
        _heading(console, "EXAMPLES", use_color=use_color)
        for ex in cmd.examples:
            console.print(f"  $ {ex}")

    if cmd.notes:
        _heading(console, "NOTES", use_color=use_color)
        for note in cmd.notes:
            console.print(f"- {note}")

    if cmd.doc_anchor or cmd.doc_page:
        _heading(console, "SEE ALSO", use_color=use_color)
        if cmd.doc_anchor:
            console.print(f"docs/user-guide/170-processes.md#{cmd.doc_anchor}")
        if cmd.doc_page:
            console.print(f"docs/user-guide/{cmd.doc_page}")
        console.print("Run `pm-help` with no arguments for the full command index.")
