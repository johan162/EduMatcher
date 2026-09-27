"""Non-blocking single-keypress input for ``pm-viewer``.

The viewer's main loop is a single ``zmq.Poller`` over the book subscription,
so keyboard input has to be pollable too rather than blocking on ``input()``.
:class:`KeyReader` puts the terminal in cbreak mode (keys arrive without
Enter, Ctrl-C still raises ``KeyboardInterrupt``) and exposes a file
descriptor the same poller can watch.

Keys are reported as single characters, or as one of the names ``UP``,
``DOWN``, ``LEFT``, ``RIGHT``, ``ENTER``, ``BACKSPACE``, ``ESC``, ``F1``.
"""

from __future__ import annotations

import os
import sys
from types import TracebackType
from typing import Any, Protocol

if sys.platform == "win32":  # pragma: no cover - POSIX terminals only
    _SUPPORTED = False
else:
    import termios
    import tty

    _SUPPORTED = True


class TerminalStream(Protocol):
    """The whole of what :class:`KeyReader` needs from its input stream."""

    def isatty(self) -> bool: ...

    def fileno(self) -> int: ...


# Terminals disagree about F1: xterm in application mode sends SS3 `\x1bOP`,
# the Linux console sends `\x1b[[A`, and the VT220 form is `\x1b[11~`. All
# three are accepted so the hint in the footer is true wherever it is read.
_ESCAPE_SEQUENCES: tuple[tuple[str, str], ...] = (
    ("[11~", "F1"),
    ("[[A", "F1"),
    ("OP", "F1"),
    ("[A", "UP"),
    ("OA", "UP"),
    ("[B", "DOWN"),
    ("OB", "DOWN"),
    ("[C", "RIGHT"),
    ("OC", "RIGHT"),
    ("[D", "LEFT"),
    ("OD", "LEFT"),
)


def _match_escape(rest: str) -> tuple[str, int]:
    """Resolve the bytes following an ESC into a key name and a consume count.

    An unrecognised control sequence returns an empty name so its bytes are
    swallowed whole rather than landing in a text field one character at a
    time.
    """
    for sequence, name in _ESCAPE_SEQUENCES:
        if rest.startswith(sequence):
            return name, len(sequence)
    if rest[:1] in ("[", "O"):
        for index, char in enumerate(rest):
            if index and "@" <= char <= "~":
                return "", index + 1
        return "", len(rest)
    return "ESC", 0


def parse_keys(data: str) -> list[str]:
    """Split one read of terminal input into individual key names."""
    keys: list[str] = []
    index = 0
    while index < len(data):
        char = data[index]
        if char == "\x1b":
            name, consumed = _match_escape(data[index + 1 :])
            if name:
                keys.append(name)
            index += 1 + consumed
            continue
        if char in ("\r", "\n"):
            keys.append("ENTER")
        elif char in ("\x7f", "\b"):
            keys.append("BACKSPACE")
        else:
            keys.append(char)
        index += 1
    return keys


class KeyReader:
    """Context manager putting stdin in cbreak mode for the duration.

    When the stream is not a TTY (piped input, a test harness, a service
    manager) :attr:`available` is ``False`` and every method is a no-op, so
    the caller can register it unconditionally and simply never see a key.
    """

    def __init__(self, stream: TerminalStream | None = None) -> None:
        self._stream: TerminalStream = stream if stream is not None else sys.stdin
        self._fd = -1
        self._saved: Any | None = None

    @property
    def available(self) -> bool:
        if not _SUPPORTED:
            return False  # pragma: no cover - POSIX terminals only
        try:
            return self._stream.isatty() and self._stream.fileno() >= 0
        except (OSError, ValueError):
            return False

    def fileno(self) -> int:
        return self._fd

    def __enter__(self) -> "KeyReader":
        if self.available:
            fd = self._stream.fileno()
            try:
                self._saved = termios.tcgetattr(fd)
                tty.setcbreak(fd)
            except (termios.error, OSError):
                self._saved = None
                return self
            self._fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._saved is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            except (termios.error, OSError):
                # The terminal went away (SIGHUP, closed tty). There is
                # nothing left to restore, and failing here would replace the
                # real exit reason with a cleanup traceback.
                pass
            self._saved = None
        self._fd = -1

    def read_keys(self) -> list[str]:
        """Drain whatever is buffered. Only call when the fd is readable."""
        if self._fd < 0:
            return []
        try:
            data = os.read(self._fd, 1024)
        except OSError:
            return []
        return parse_keys(data.decode("utf-8", "replace"))
