from __future__ import annotations

import socket
import sqlite3
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq


def free_ports(count: int) -> list[int]:
    """*count* distinct free TCP ports, allocated **simultaneously**.

    The obvious helper -- bind to port 0, read the number, close, repeat --
    cannot promise distinct ports. Once the socket is closed the kernel may
    hand the same ephemeral port to the very next call, and measured on a
    Linux dev box that happens about once in three thousand four-port
    allocations. macOS allocates differently and effectively never does,
    which is why this was a Linux-only failure.

    When it does happen the symptom is baffling rather than obvious: two
    services in one fixture are handed the same port, the first to bind wins,
    the second dies with EADDRINUSE *despite* SO_REUSEADDR -- the port is
    actively listening, not in TIME_WAIT -- and a client connecting to it
    reaches the wrong service and hangs waiting for a reply that will never
    come.

    Holding every socket open until all *count* have been bound makes a
    duplicate impossible: the kernel cannot allocate a port it has already
    given out. The window between closing them and the caller binding is
    still a race against the rest of the machine, but that one is inherent to
    asking for a port before you need it, and it is not the one that bites.
    """
    sockets = [socket.socket(socket.AF_INET, socket.SOCK_STREAM) for _ in range(count)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [int(sock.getsockname()[1]) for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def free_port() -> int:
    """One free TCP port. Safe on its own; use :func:`free_ports` for several."""
    return free_ports(1)[0]


#: The replay fixtures, anchored to this file rather than to the working
#: directory. A ``Path("tests/fixtures/replay")`` resolves against the cwd, so
#: running pytest from anywhere but the repo root made every glob over it
#: return nothing -- and a parametrize over an empty list is zero test cases,
#: which pytest reports as success. Sixteen tests silently ceased to exist.
REPLAY_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "replay"


def replay_logs() -> list[Path]:
    """Every replay fixture log, and never an empty list.

    The assertion is the point. Returning nothing is the failure mode that
    hides itself, so it is turned into a loud one here rather than left to be
    noticed by whoever wonders why the suite got faster.
    """
    logs = sorted(REPLAY_FIXTURES.glob("*.log"))
    assert logs, f"no replay fixtures under {REPLAY_FIXTURES}"
    return logs


def wait_for_listener(host: str, port: int, timeout: float = 5.0) -> None:
    """Block until *port* actually accepts a connection.

    The only true readiness signal for a server started on a thread. Two
    weaker ones are in use around the suite and both fail the same way on a
    loaded machine:

    * a fixed ``time.sleep(0.15)``, which is a guess about how long a thread
      takes to schedule;
    * polling a gateway's ``_server`` attribute, which every gateway assigns
      *before* it calls ``bind()`` and ``listen()`` -- so the wait ends while
      the port is still refusing connections.

    Both pass on an idle Mac and fail on a busy Linux box, which is exactly
    the class of flake that gets written off as infrastructure.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.02)
    raise AssertionError(f"nothing started listening on {host}:{port} in {timeout}s")


_OPEN_DATABASES: list[sqlite3.Connection] = []


def opened(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Register a connection to be closed when the test ends.

    A test that opens an index and reads from it across several statements
    reads better without a ``with`` around the whole body, but a connection
    nobody closes is still a leak -- and since Python 3.14 sqlite3 says so,
    with a ``ResourceWarning`` attributed to whichever unrelated line the
    collector happened to be running. Wrapping the open at the call site
    keeps the closing explicit and deterministic.
    """
    _OPEN_DATABASES.append(conn)
    return conn


@pytest.fixture(autouse=True)
def _close_registered_databases() -> Generator[None, None, None]:
    yield
    while _OPEN_DATABASES:
        _OPEN_DATABASES.pop().close()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help=(
            "Rewrite tests/fixtures/replay/*.expected.*.txt from current output. "
            "Read the diff before committing it."
        ),
    )


@pytest.fixture
def update_goldens(request: pytest.FixtureRequest) -> bool:
    """True when the run was asked to regenerate golden files."""
    return bool(request.config.getoption("--update-goldens"))


@pytest.fixture(autouse=True)
def _configure_trade_id_run() -> Generator[None, None, None]:
    reset_trade_ids_for_tests()
    set_run_seq(0)
    yield
    reset_trade_ids_for_tests()


def make_order(
    *,
    symbol: str = "AAPL",
    side: Side,
    order_type: OrderType,
    qty: int,
    gateway_id: str,
    tif: TIF = TIF.DAY,
    price: int | None = None,
    stop_price: int | None = None,
    visible_qty: int | None = None,
) -> Order:
    return Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price_ticks=price,
        stop_price_ticks=stop_price,
        visible_qty=visible_qty,
    )
