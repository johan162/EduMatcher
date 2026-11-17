"""A pm-* CLI whose reader goes away ends quietly (For-Later L013).

Python ignores SIGPIPE, so ``pm-stats-cli daily | head`` gets a
``BrokenPipeError`` at the first write after ``head`` exits, or at the final
flush ("Exception ignored while flushing sys.stdout"). Resetting SIGPIPE
globally is not an option: the daemons write to sockets, where a closed peer
must be an error, not a signal that kills the process. So each CLI entry
point that prints to stdout is wrapped in :func:`pipe_safe` instead.
"""

from __future__ import annotations

import functools
import os
import sys
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")

#: The status of a CLI whose output was cut off, as Python's documentation
#: suggests for this case (a shell pipeline reports the last command's anyway).
EXIT_BROKEN_PIPE = 1


def _stdout_to_devnull() -> None:
    """Point stdout at /dev/null so the interpreter's final flush cannot fail."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())
    os.close(devnull)


def pipe_safe(main: Callable[P, T]) -> Callable[P, T]:
    """Run *main*; a closed stdout ends the process with status 1, quietly."""

    @functools.wraps(main)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            result = main(*args, **kwargs)
            sys.stdout.flush()
            return result
        except SystemExit:
            # argparse's --help and every explicit exit: flush what is left
            # first, so a closed pipe is not reported while exiting.
            try:
                sys.stdout.flush()
            except BrokenPipeError:
                _stdout_to_devnull()
            raise
        except BrokenPipeError:
            _stdout_to_devnull()
            raise SystemExit(EXIT_BROKEN_PIPE) from None

    return wrapper
