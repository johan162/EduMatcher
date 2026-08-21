"""The entire palette, glyph set and box style, in one place.

Ordinary values use ``"default"`` rather than an explicit white so that the
coloured items carry the emphasis and the result works on both light and dark
terminal backgrounds.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich import box

# --- semantic styles -------------------------------------------------------
S_BORDER = "grey42"
S_BORDER_HOT = "cyan"
S_TITLE = "bold cyan"
S_TITLE_HOT = "bold bright_yellow"
S_LABEL = "grey62"
S_VALUE = "default"
S_PORT = "bold bright_yellow"
S_PROC = "bright_green"
S_KEY = "bold bright_magenta"
S_ON = "bright_green"
S_OFF = "grey50"
S_WARN = "bright_yellow"
S_BAD = "bold bright_red"
S_DEFAULTED = "grey50 italic"
S_SYMBOL = "bold bright_white"
S_RULE = "bold white"

ROLE_STYLE: dict[str, str] = {
    "TRADER": "bright_blue",
    "MARKET_MAKER": "bright_magenta",
    "ADMIN": "bright_red",
    "READ-ONLY": "grey62",
}

#: Origin of a listener's port -> (label, style).  A defaulted or fixed port
#: is rendered greyed so it reads as "not from this file" at a glance.
ORIGIN_STYLE: dict[str, tuple[str, str]] = {
    "fixed": ("fixed", S_DEFAULTED),
    "env": ("env", S_WARN),
    "default": ("default", S_DEFAULTED),
    "configured": ("set", S_ON),
}


@dataclass
class Theme:
    """Mutable per-run drawing choices (Unicode vs ASCII)."""

    panel_box: box.Box = box.ROUNDED
    table_box: box.Box = box.SIMPLE_HEAD
    on_glyph: str = "●"
    off_glyph: str = "○"
    bar_start: str = "├"
    bar_mid: str = "┼"
    bar_fill: str = "─"
    bar_end: str = "┤"
    default_marker: str = "◂default"

    def to_ascii(self) -> None:
        """Switch to pure ASCII for non-UTF-8 terminals or ``--ascii``."""
        self.panel_box = box.ASCII
        self.table_box = box.HORIZONTALS
        self.on_glyph, self.off_glyph = "+", "-"
        self.bar_start, self.bar_mid = "|", "+"
        self.bar_fill, self.bar_end = "-", "|"
        self.default_marker = "<default"


#: Module-level singleton; ``cli`` flips it to ASCII when required.  A single
#: shared object keeps every panel builder free of theme plumbing.
THEME = Theme()
