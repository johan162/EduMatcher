"""Interactive symbol picker for ``pm-viewer``.

A small popup over the live book: type to narrow the list, arrow keys to
move, Enter to switch symbol, Esc to go back. The state machine is kept
free of Rich and of ZMQ so the selection behaviour can be exercised
directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

#: Rows of the symbol list shown at once. The list scrolls within this window.
DEFAULT_VISIBLE_ROWS = 12

_FILTER_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")


@dataclass
class SymbolPicker:
    """Which symbols are on offer, what has been typed, and what is selected.

    Starts empty and ``loading``: the viewer asks the engine for the symbol
    list when the picker opens and calls :meth:`set_symbols` when the reply
    arrives, so the popup appears immediately rather than after a round trip.
    """

    symbols: list[str] = field(default_factory=list)
    query: str = ""
    index: int = 0
    loading: bool = True

    def set_symbols(self, symbols: list[str]) -> None:
        self.symbols = sorted({s.strip().upper() for s in symbols if s.strip()})
        self.loading = False
        self._clamp()

    @property
    def matches(self) -> list[str]:
        # Prefix, not substring: typing "A" should offer the symbols that
        # start with A, not every symbol containing one.
        if not self.query:
            return self.symbols
        return [s for s in self.symbols if s.startswith(self.query)]

    @property
    def selection(self) -> str | None:
        matches = self.matches
        return matches[self.index] if matches else None

    def move(self, delta: int) -> None:
        self.index += delta
        self._clamp()

    def type_char(self, char: str) -> bool:
        """Append *char* to the filter. Returns False if it is not filterable."""
        upper = char.upper()
        if upper not in _FILTER_CHARS:
            return False
        self.query += upper
        self.index = 0
        return True

    def backspace(self) -> None:
        self.query = self.query[:-1]
        self.index = 0

    def window(self, visible_rows: int) -> tuple[list[str], int, bool, bool]:
        """The visible slice, the selected row within it, and scroll markers."""
        matches = self.matches
        if len(matches) <= visible_rows:
            return matches, self.index, False, False
        # Keep the selection centred until it runs into either end of the list.
        start = min(
            max(0, self.index - visible_rows // 2),
            len(matches) - visible_rows,
        )
        end = start + visible_rows
        return matches[start:end], self.index - start, start > 0, end < len(matches)

    def _clamp(self) -> None:
        count = len(self.matches)
        self.index = 0 if count == 0 else max(0, min(self.index, count - 1))


def render_picker(
    picker: SymbolPicker,
    *,
    current: str,
    visible_rows: int = DEFAULT_VISIBLE_ROWS,
) -> RenderableType:
    """The popup body: filter line, symbol list, and key hints."""
    rows, selected, more_above, more_below = picker.window(visible_rows)

    listing = Table.grid(padding=(0, 1))
    listing.add_column(width=1, no_wrap=True)
    listing.add_column(no_wrap=True)

    if picker.loading:
        listing.add_row("", Text("loading symbols…", style="grey58"))
    elif not rows:
        listing.add_row("", Text("no match", style="yellow"))
    else:
        if more_above:
            listing.add_row("", Text("↑ more", style="grey42"))
        for offset, symbol in enumerate(rows):
            marker = "›" if offset == selected else ""
            style = "bold black on cyan" if offset == selected else "white"
            if symbol == current and offset != selected:
                style = "cyan"
            listing.add_row(Text(marker, style="cyan"), Text(symbol, style=style))
        if more_below:
            listing.add_row("", Text("↓ more", style="grey42"))

    filter_line = Text.assemble(
        ("Filter ", "grey58"),
        (picker.query or "", "bold white"),
        ("▏", "cyan"),
    )
    hints = Text("↑/↓ move  •  Enter select  •  Esc cancel", style="grey58")

    return Panel(
        Group(filter_line, Text(""), listing),
        title=Text(" Select symbol ", style="bold white on blue"),
        title_align="left",
        subtitle=hints,
        subtitle_align="right",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 2),
        width=48,
    )
