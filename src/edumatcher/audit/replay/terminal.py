"""How the terminal sees it: the clock and the colours.

Two display concerns several renderers share, and that neither the model nor
the prose has any business knowing about. ``--tz`` changes what a timestamp
looks like, never what it is; ``--no-color`` changes nothing about the words
at all.

**Colour is off unless stdout is a terminal.** A redirected stream gets plain
text without anyone asking, because escape codes in a file are noise the
reader has to strip back out -- and a report a script parses must not depend
on whether a human happened to be watching. ``NO_COLOR`` in the environment
turns it off too, which is the convention the rest of the tree follows
(``pm_help``, ``pm-config-show``).

**Colour never reaches the machine-readable formats.** NDJSON and JSON are
built from the beats' own fields rather than from a rendered line, and CSV is
data; the painting here happens only where a sentence is assembled for a
human. The same goes for ``--tz``: the object model keeps the timestamps the
trail recorded, because a display switch that moved them would make the two
formats disagree about what happened, which is the one thing section 11 is
for.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SupportsIsatty(Protocol):
    """All this asks of a stream, which is what it should say it asks.

    ``IO[Any]`` would be a promise about read, write, seek and a dozen other
    things none of which are consulted here -- and would make a two-line test
    double impossible to type.
    """

    def isatty(self) -> bool: ...  # pragma: no cover - a shape, not code


_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"


@dataclass(frozen=True, slots=True)
class Palette:
    """Wrapping in escape codes, or not, without the caller branching.

    Every method is the identity when colour is off, so a renderer reads
    ``palette.dim(clock)`` rather than ``dim(clock) if color else clock`` at
    thirty call sites -- and a site that forgets the branch cannot write
    escape codes into a file.
    """

    enabled: bool = False

    def _wrap(self, text: str, code: str) -> str:
        return f"{code}{text}{_RESET}" if self.enabled and text else text

    def bold(self, text: str) -> str:
        return self._wrap(text, _BOLD)

    def dim(self, text: str) -> str:
        return self._wrap(text, _DIM)

    def red(self, text: str) -> str:
        return self._wrap(text, _RED)

    def green(self, text: str) -> str:
        return self._wrap(text, _GREEN)

    def yellow(self, text: str) -> str:
        return self._wrap(text, _YELLOW)

    def cyan(self, text: str) -> str:
        return self._wrap(text, _CYAN)


#: What every renderer uses unless a live one is passed in. Sharing one
#: disabled instance keeps "no colour" the default everywhere, including in
#: the tests and in any caller that predates this module.
PLAIN = Palette()


def palette_for(
    no_color: bool = False,
    stream: SupportsIsatty | None = None,
    *,
    force: bool = False,
) -> Palette:
    """The palette this invocation should use.

    The tty check is a guess at what is on the other end of the pipe, and it
    is wrong in one common case: ``| less -R`` and ``| head`` end at a
    terminal the tool cannot see. So the guess is overridable in both
    directions, and an explicit ``force`` beats everything -- a flag the
    reader typed is a more specific instruction than an environment default
    they may not remember setting.

    Otherwise three ways to end up plain, and the last two need no flag: the
    caller asked, ``NO_COLOR`` is set, or stdout is not a terminal.
    """
    if force:
        return Palette(enabled=True)
    if no_color or os.environ.get("NO_COLOR"):
        return PLAIN
    stream = sys.stdout if stream is None else stream
    if stream is None:
        # Detached from a console entirely: pythonw, a service. Not a
        # terminal, which is the answer this needs.
        return PLAIN
    try:
        interactive = bool(stream.isatty())
    except (AttributeError, ValueError):
        # A closed or exotic stream is not a terminal, which is the answer
        # this needs; it is not a reason to fail a report.
        interactive = False
    return Palette(enabled=interactive)


def parse_tz(name: str) -> tzinfo:
    """``--tz``'s argument as a zone, or a message argparse can print."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {name!r}: {exc}") from exc


def clock(when: datetime, tz: tzinfo | None = None) -> str:
    """``09:31:02.122`` -- the time of day, in *tz* when one was asked for.

    Milliseconds because that is the resolution ``pm-audit`` records, and no
    date because every view that prints this is already bounded by a window
    the reader chose.
    """
    return (when.astimezone(tz) if tz else when).strftime("%H:%M:%S.%f")[:-3]


def moment(raw: str, tz: tzinfo | None = None) -> str:
    """An ISO timestamp as recorded, moved into *tz* when one was asked for.

    For the places that carry the trail's own string rather than a parsed
    time. A string that will not parse is returned untouched: this is a
    display helper, and refusing to print a timestamp because it is odd would
    lose the one thing the reader could have grepped for.
    """
    if tz is None:
        return raw
    try:
        return datetime.fromisoformat(raw).astimezone(tz).isoformat()
    except ValueError:
        return raw


__all__ = [
    "PLAIN",
    "Palette",
    "SupportsIsatty",
    "clock",
    "moment",
    "palette_for",
    "parse_tz",
]
