"""Split a ``pm-mm-bot`` command line into per-symbol scopes.

``argparse`` has no way to express "this flag belongs to the ``--symbol``
that preceded it", so the raw argv is split here *before* argparse sees it:

    pm-mm-bot --qty 500 --symbol AAPL --gap 0.10 --symbol MSFT --gap 0.20

becomes a global scope (``--qty 500``) plus one scope per ``--symbol``. The
only token that opens a new scope is ``--symbol`` itself, so no table of
flag arities is needed — everything else is copied verbatim into whichever
scope is currently open and handed to argparse untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


class ScopeError(ValueError):
    """The command line could not be split into symbol scopes."""


@dataclass(frozen=True)
class ArgvScopes:
    """One command line, split by ``--symbol``.

    ``symbol_argv`` preserves command-line order and never contains the
    ``--symbol``/``--symbol=`` tokens themselves.
    """

    global_argv: list[str] = field(default_factory=list)
    symbol_argv: list[tuple[str, list[str]]] = field(default_factory=list)

    @property
    def symbols(self) -> list[str]:
        return [sym for sym, _ in self.symbol_argv]


_FLAG = "--symbol"
_FLAG_EQ = "--symbol="


def split_argv_scopes(argv: Sequence[str]) -> ArgvScopes:
    """Split ``argv`` on ``--symbol`` boundaries.

    The input is never mutated. Raises ``ScopeError`` for a ``--symbol``
    with no name after it, or for the same symbol named twice (merging two
    scopes for one symbol is exactly the kind of surprise a long command
    line should not spring on its author).
    """
    global_argv: list[str] = []
    scopes: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    seen: set[str] = set()
    passthrough = False

    index = 0
    total = len(argv)
    while index < total:
        token = argv[index]

        if not passthrough and token == "--":
            # Everything after a bare "--" is positional/verbatim and must not
            # be mistaken for a scope boundary.
            passthrough = True
        elif not passthrough and (token == _FLAG or token.startswith(_FLAG_EQ)):
            if token == _FLAG:
                if index + 1 >= total:
                    raise ScopeError("--symbol requires a symbol name")
                raw = argv[index + 1]
                index += 2
            else:
                raw = token[len(_FLAG_EQ) :]
                index += 1
            name = raw.strip().upper()
            if not name or name.startswith("-"):
                raise ScopeError("--symbol requires a symbol name")
            if name in seen:
                raise ScopeError(f"--symbol {name} given more than once")
            seen.add(name)
            current = []
            scopes.append((name, current))
            continue

        (global_argv if current is None else current).append(token)
        index += 1

    return ArgvScopes(global_argv=global_argv, symbol_argv=scopes)
