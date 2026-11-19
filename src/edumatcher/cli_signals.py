"""An interactive console logs out when its terminal goes away.

Python's default action for SIGHUP (the terminal window was closed) and
SIGTERM (``kill``) ends the process at once, without the ``finally`` that
sends ``system.gateway_disconnect``. The engine then kept the participant ID
connected, and its orders resting, until the console's heartbeats ran out.
While :func:`logout_on_hangup` is active both signals call *request_exit*
instead, which ends the prompt loop the same way EXIT does.
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from types import FrameType

#: SIGHUP does not exist on Windows.
_SIGNALS = tuple(
    sig for sig in (getattr(signal, "SIGHUP", None), signal.SIGTERM) if sig is not None
)


@contextmanager
def logout_on_hangup(request_exit: Callable[[], None]) -> Generator[None, None, None]:
    """Route SIGHUP and SIGTERM to *request_exit* until the block ends.

    A no-op off the main thread, where Python does not allow signal handlers.
    The previous handlers come back on exit.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handler(_signum: int, _frame: FrameType | None) -> None:
        request_exit()

    previous = {sig: signal.getsignal(sig) for sig in _SIGNALS}
    for sig in _SIGNALS:
        signal.signal(sig, _handler)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
