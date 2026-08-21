"""Adaptive panel flow.

The layout problem
------------------
Panels have very different natural widths (the ports table wants ~80 columns,
the circuit-breaker table ~34), one panel -- API keys -- has a hard content
width it must never fall below, and one panel -- symbols -- is arbitrarily
tall.  Laid out naively you either strand half the terminal beside a tall
table, or squeeze a wide table until it lies.

Four mechanisms solve it
------------------------
1.  **Width ranges, not widths.**  A panel declares ``min_w`` (below this it
    is illegible), ``nat_w`` (comfortable), ``max_w`` (beyond this it is
    stretched whitespace) and ``wprio`` (who is fed first when width is
    scarce).  A panel that reports a single width can only be placed or not
    placed; a range is what makes rearrangement possible at all.

2.  **Shelf packing with lookahead.**  Panels are emitted in *band* order -- a
    logical grouping -- and a row is filled while the next panel's ``min_w``
    still fits beside the ones already there *at their natural widths*.
    Packing on natural rather than minimum widths is what stops three panels
    being crammed into 80 columns and all three being unreadable.  When the
    next panel does not fit but a later, narrower one would, the packer
    reaches forward a few slots -- preferring the same band -- so a hole is
    filled without reordering the document.

3.  **Width distribution.**  Everyone starts at ``min_w``, is raised to
    ``nat_w`` in ``wprio`` order, and the remainder goes to the growers up to
    ``max_w``.  A row always consumes the full terminal width.

4.  **Vertical gap fill.**  Two panels side by side are almost never the same
    height, and the short one leaves a column of dead space -- the classic
    "huge table with nothing beside it" failure.  After widths are known the
    shorter cells pull *later* panels up into themselves and stack them, as
    long as the panel fits the cell's width and its remaining vertical gap.
    Cells end up roughly level and the gutter disappears.

``hard_break`` panels (a long symbol list) own their row, get every column,
and reflow internally into as many sub-tables as fit -- so the biggest table
in the file is precisely the one that can never strand space.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rich.console import Console, Group, RenderableType

#: Columns between two panels on the same row.
GAP = 2
#: More than three panels abreast stops being scannable whatever the width.
MAX_PER_ROW = 3
#: How far forward shelf packing may reach for a companion panel.
LOOKAHEAD = 4
#: Only reach across a band boundary when at least this much width is idle;
#: below it, preserving the logical grouping is worth the whitespace.
BORROW_SLACK = 30
#: How far forward gap fill may reach.
FILL_LOOKAHEAD = 6
#: Gaps shorter than this are not worth disturbing the reading order for.
MIN_GAP_TO_FILL = 4
#: A filler may overshoot the gap by this much; rows are not a hard grid.
FILL_TOLERANCE = 3


@dataclass
class Panel:
    """A placeable unit: a title, a width range and a build function."""

    key: str
    min_w: int
    nat_w: int
    build: Callable[[int], RenderableType]
    band: str = "misc"
    max_w: int = 0
    wprio: int = 2
    grow: bool = False
    hard_break: bool = False
    optional: bool = True

    def __post_init__(self) -> None:
        if not self.max_w:
            self.max_w = int(self.nat_w * 1.4)


#: A cell is a vertical stack of panels sharing one column width.
Cell = tuple[list[Panel], int]
Row = list[Cell]


def measure(console: Console, renderable: RenderableType, width: int) -> int:
    """Rendered height in lines of ``renderable`` at ``width``."""
    options = console.options.update(width=width, height=None)
    return len(console.render_lines(renderable, options, pad=False))


def render_cell(cell: list[Panel], width: int) -> RenderableType:
    if len(cell) == 1:
        return cell[0].build(width)
    return Group(*[panel.build(width) for panel in cell])


def total_height(console: Console, rows: list[Row]) -> int:
    return sum(
        max(measure(console, render_cell(cell, width), width) for cell, width in row)
        for row in rows
    )


# ---------------------------------------------------------------------------
def flow(console: Console, panels: list[Panel], width: int) -> list[Row]:
    """Pack ``panels`` into rows of cells that exactly fill ``width``."""
    remaining = list(panels)
    rows: list[Row] = []

    while remaining:
        head = remaining.pop(0)
        if head.hard_break:
            rows.append([([head], width)])
            continue

        row = _shelve(head, remaining, width)
        widths = _distribute(row, width)
        rows.append(_gap_fill(console, row, widths, remaining))

    return rows


def _shelve(head: Panel, remaining: list[Panel], width: int) -> list[Panel]:
    """Choose the panels that share ``head``'s row."""
    row = [head]
    while len(row) < MAX_PER_ROW:
        used = sum(min(p.nat_w, width) for p in row) + GAP * len(row)
        free = width - used
        if free <= 0:
            break

        candidates = remaining[:LOOKAHEAD]
        same_band = [
            c
            for c in candidates
            if not c.hard_break and c.min_w <= free and c.band == head.band
        ]
        other_band = [
            c
            for c in candidates
            if not c.hard_break
            and c.min_w <= free
            and c.band != head.band
            and free >= BORROW_SLACK
        ]
        pick = same_band or other_band
        if not pick:
            break
        row.append(pick[0])
        remaining.remove(pick[0])
    return row


def _distribute(row: list[Panel], width: int) -> list[int]:
    """Split ``width`` across ``row``, feeding high-priority panels first."""
    budget = width - GAP * (len(row) - 1)
    got = {panel.key: min(panel.min_w, budget) for panel in row}

    for panel in sorted(row, key=lambda p: p.wprio):  # raise to natural
        spare = budget - sum(got.values())
        if spare <= 0:
            break
        got[panel.key] += min(spare, max(0, panel.nat_w - got[panel.key]))

    for _ in range(2):  # then the growers
        spare = budget - sum(got.values())
        if spare <= 0:
            break
        targets = [p for p in row if p.grow and got[p.key] < p.max_w] or [
            p for p in row if got[p.key] < p.max_w
        ]
        if not targets:
            break
        for i, panel in enumerate(targets):
            share = spare // len(targets) + (1 if i < spare % len(targets) else 0)
            got[panel.key] += min(share, panel.max_w - got[panel.key])

    residual = budget - sum(got.values())  # never a ragged edge
    if residual > 0:
        got[row[-1].key] += residual
    return [got[panel.key] for panel in row]


def _gap_fill(
    console: Console, row: list[Panel], widths: list[int], remaining: list[Panel]
) -> Row:
    """Stack later panels into cells that are shorter than their neighbours."""
    cells: list[list[Panel]] = [[panel] for panel in row]
    heights = [
        measure(console, panel.build(width), width) for panel, width in zip(row, widths)
    ]
    target = max(heights)

    progress = True
    while progress:
        progress = False
        target = max(target, max(heights))
        for i, height in enumerate(heights):
            gap = target - height - 1  # -1 for the panel's own top rule
            if gap < MIN_GAP_TO_FILL:
                continue
            for candidate in remaining[:FILL_LOOKAHEAD]:
                if candidate.hard_break or candidate.min_w > widths[i]:
                    continue
                extra = measure(console, candidate.build(widths[i]), widths[i])
                if extra <= gap + FILL_TOLERANCE:
                    cells[i].append(candidate)
                    heights[i] += extra
                    remaining.remove(candidate)
                    progress = True
                    break

    return list(zip(cells, widths))


def fit_to_height(
    console: Console, panels: list[Panel], width: int, avail: int
) -> tuple[list[Row], list[str]]:
    """Drop optional panels from the end until the render fits ``avail`` lines.

    Only used at the default density: ``-m``/``-a`` are an explicit statement
    that scrolling is acceptable.
    """
    dropped: list[str] = []
    working = list(panels)
    while True:
        rows = flow(console, working, width)
        if total_height(console, rows) <= avail:
            return rows, dropped
        victims = [panel for panel in working if panel.optional]
        if not victims:
            return rows, dropped
        working.remove(victims[-1])
        dropped.append(victims[-1].key)
