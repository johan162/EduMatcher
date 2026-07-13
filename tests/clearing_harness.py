"""
Contract-test harness for the clearing module.

Fidelity principles (see docs-design/EduMatcher-Review-Clearing.md §8):

1. **Payloads are produced by the engine's own code** — a real `Engine`
   (via tests/engine_harness.make_engine) processes real order flow and we
   capture the exact frames its publisher emitted.  No hand-built payloads:
   the historic failure mode was tests that encoded clearing's *expectation*
   of the contract instead of the engine's *actual* output.

2. **Delivery uses the real transport and the real clearing process** — a
   genuine ZMQ PUB socket (shared Context, inproc) feeds a genuine
   `ClearingProcess.run()` on its own thread, so clearing's own
   subscription list, decode, dispatch, buffering, locking, and flush
   pipeline are all under test.  Tests therefore stay policy-neutral: a fix
   that changes *which* topic carries some information goes green without
   test edits, as long as the information flows.

Readiness protocol: ZMQ SUB subscriptions propagate asynchronously, so the
harness publishes a side-effect-free probe (`system.gateway_connect` with
gateway_id "PROBE!") until clearing observes it, before any test traffic.

Not a test module (no test_ prefix) — pytest will not collect it.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import zmq

from edumatcher.clearing.main import ClearingProcess
from edumatcher.models.message import decode, encode

# Probe gateway id — excluded from all assertions.
PROBE_GW = "PROBE!"

# Generous: under pytest-xdist a fully loaded machine can starve the
# clearing thread for several seconds without anything being wrong.
_DEADLINE = 15.0

# Captured at import time so the harness keeps REAL pacing even if some
# test fixture patches time.sleep globally.
_SLEEP = time.sleep
_MONO = time.monotonic


def wait_until(
    cond: Callable[[], bool], *, what: str, deadline: float = _DEADLINE
) -> None:
    end = _MONO() + deadline
    while _MONO() < end:
        if cond():
            return
        _SLEEP(0.02)
    raise AssertionError(f"harness timeout waiting for: {what}")


@dataclass
class ClearingUnderTest:
    """A live ClearingProcess fed through a real ZMQ PUB socket."""

    process: ClearingProcess
    db_path: Path
    _pub: zmq.Socket  # type: ignore[type-arg]
    _thread: threading.Thread
    _sent_trades: int = 0
    _extra_conns: list[sqlite3.Connection] = field(default_factory=list)

    # -- publishing ----------------------------------------------------
    def publish_frames(self, frames_list: Iterable[list[bytes]]) -> None:
        """Publish raw multipart frames exactly as captured from the engine."""
        for frames in frames_list:
            topic, _ = decode(frames)
            if topic == "trade.executed":
                self._sent_trades += 1
            self._pub.send_multipart(frames)

    def publish_engine_output(
        self,
        engine_pub_sent: list[list[bytes]],
        *,
        topics: tuple[str, ...] | None = None,
    ) -> None:
        """Forward everything a (fake-socketed) engine published.

        The real SUB socket filters by clearing's own subscriptions, so
        forwarding the full stream is faithful; ``topics`` can narrow the
        stream to model selective delivery (e.g. transport gaps).
        """
        for frames in engine_pub_sent:
            topic, _ = decode(frames)
            if topics is not None and not any(topic.startswith(t) for t in topics):
                continue
            if topic == "trade.executed":
                self._sent_trades += 1
            self._pub.send_multipart(frames)

    # -- synchronization -----------------------------------------------
    def wait_ingested(self, n_trades: int | None = None) -> None:
        target = self._sent_trades if n_trades is None else n_trades
        wait_until(
            lambda: self.process._trade_count >= target,
            what=f"clearing to ingest {target} trade(s) "
            f"(saw {self.process._trade_count})",
        )

    def flush(self) -> None:
        self.process.flush_now()

    def fence(self) -> None:
        """Guarantee every previously published frame has been processed.

        ZMQ preserves per-connection ordering, so once a fresh probe (sent
        AFTER the test traffic) is observed by clearing, everything sent
        before it has been dispatched too.  Probe gateway ids all start with
        PROBE_GW — exclude them when asserting on gateway_sessions.
        """
        tag = f"{PROBE_GW}{uuid.uuid4().hex[:8].upper()}"

        def _seen() -> bool:
            self._pub.send_multipart(
                encode("system.gateway_connect", {"gateway_id": tag})
            )
            _SLEEP(0.03)
            return tag in self.process._gw_connect_ts

        wait_until(_seen, what="ordering fence probe")

    # -- DB access -------------------------------------------------------
    def db(self) -> sqlite3.Connection:
        """Read-only connection usable while the process is still running (WAL)."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        self._extra_conns.append(conn)
        return conn

    # -- teardown --------------------------------------------------------
    def stop(self) -> None:
        self.process.stop()
        self._thread.join(timeout=_DEADLINE)
        self._pub.close(linger=0)
        for conn in self._extra_conns:
            try:
                conn.close()
            except Exception:
                pass


def start_clearing(
    db_path: Path,
    *,
    flush_size: int = 100,
    flush_interval_sec: float = 60.0,  # timer effectively off; tests flush explicitly
) -> ClearingUnderTest:
    """Bind a PUB socket and run a real ClearingProcess against it."""
    addr = f"inproc://clearing-test-{uuid.uuid4().hex}"
    ctx = zmq.Context.instance()  # same context the bus module uses
    pub = ctx.socket(zmq.PUB)
    pub.bind(addr)

    process = ClearingProcess(
        pub_addr=addr,
        db_path=db_path,
        flush_size=flush_size,
        flush_interval_sec=flush_interval_sec,
        print_every=0,  # keep test output clean
    )
    thread = threading.Thread(
        target=process.run, daemon=True, name="clearing-under-test"
    )
    thread.start()

    cut = ClearingUnderTest(process=process, db_path=db_path, _pub=pub, _thread=thread)

    # Readiness: probe until the SUB is provably receiving.
    def _probed() -> bool:
        pub.send_multipart(encode("system.gateway_connect", {"gateway_id": PROBE_GW}))
        _SLEEP(0.03)
        return PROBE_GW in process._gw_connect_ts

    try:
        wait_until(_probed, what="clearing SUB socket to start receiving")
    except AssertionError:
        # Don't leak the running thread, its writer DB connection, or the
        # PUB socket when readiness fails — stop() drives run()'s finally
        # block, which closes both.
        cut.stop()
        raise
    return cut


# ---------------------------------------------------------------------------
# Engine-side frame capture helpers
# ---------------------------------------------------------------------------


def engine_frames(
    engine_pub_sent: list[list[bytes]], topic_prefix: str
) -> list[list[bytes]]:
    """Frames from a captured engine stream whose topic starts with *prefix*."""
    out = []
    for frames in engine_pub_sent:
        topic, _ = decode(frames)
        if topic.startswith(topic_prefix):
            out.append(frames)
    return out


def decoded(engine_pub_sent: list[list[bytes]], topic: str) -> list[dict[str, Any]]:
    return [decode(f)[1] for f in engine_pub_sent if decode(f)[0] == topic]
