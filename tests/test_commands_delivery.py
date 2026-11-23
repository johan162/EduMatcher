"""ExchangeCommandClient over real sockets: replies arrive, connects authenticate.

The engine is a stand-in thread that binds the real ``make_puller`` and
``make_publisher`` on free ports and answers with the engine's own builders,
so every frame carries the real publisher trailer. It can flood the PUB
socket with ``book.<SYM>`` snapshots the way a busy market does, which is what
fills an idle client's SUB queue (Admin commands review 2026-11, H1).
"""

from __future__ import annotations

import queue
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from edumatcher.commands import CommandTimeoutError, ExchangeCommandClient
from edumatcher.engine.order_book import OrderBook
from edumatcher.messaging.bus import make_publisher, make_puller
from edumatcher.models.message import (
    decode,
    make_book_msg,
    make_circuit_breaker_halt_all_ack_msg,
    make_gateway_auth_msg,
    make_session_status_msg,
    make_volume_msg,
)

GW = "GW_ADMIN"
_STANDIN = Path(__file__).with_name("commands_standin_engine.py")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _StandInEngine:
    """Answers connect, session-state, volume, halt-all and book requests."""

    def __init__(self, pub_delay: float = 0.0, pub_addr: str | None = None) -> None:
        self._pub_delay = pub_delay
        self.pull_addr = f"tcp://127.0.0.1:{_free_port()}"
        self.pub_addr = pub_addr or f"tcp://127.0.0.1:{_free_port()}"
        self.received: list[str] = []
        self.volume_qty = 222
        self.accept = True
        self._actions: queue.Queue[Callable[[Any], None]] = queue.Queue()
        self._stop = threading.Event()
        self._ready = threading.Event()
        snap = OrderBook("S000").snapshot()
        snap["bids"] = [{"price": 100.0 - i, "qty": 100, "count": 1} for i in range(10)]
        snap["asks"] = [{"price": 101.0 + i, "qty": 100, "count": 1} for i in range(10)]
        self._snap = snap
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def _run(self) -> None:
        pull = make_puller(self.pull_addr)
        self._ready.set()
        # A late PUB socket: requests queue on PULL meanwhile, and the first
        # replies go out before any subscriber has had time to (re)connect.
        time.sleep(self._pub_delay)
        pub = make_publisher(self.pub_addr)
        try:
            while not self._stop.is_set():
                while not self._actions.empty():
                    self._actions.get()(pub)
                if not pull.poll(10):
                    continue
                topic, p = decode(pull.recv_multipart())
                self.received.append(topic)
                gw = str(p.get("gateway_id", "")).upper()
                if topic == "system.gateway_connect":
                    pub.send_multipart(
                        make_gateway_auth_msg(
                            gw,
                            self.accept,
                            "" if self.accept else "Gateway already connected",
                        )
                    )
                elif topic == "system.session_state_request":
                    pub.send_multipart(
                        make_session_status_msg(gw, "CONTINUOUS", "", False)
                    )
                elif topic == "system.volume_request":
                    pub.send_multipart(make_volume_msg(gw, [], self.volume_qty, 0.0, 0))
                elif topic == "risk.circuit_breaker_halt_all":
                    pub.send_multipart(
                        make_circuit_breaker_halt_all_ack_msg(
                            gw, True, halted_symbols=1, halted_symbol_ids=["S000"]
                        )
                    )
                elif topic == "book.snapshot_request":
                    pub.send_multipart(make_book_msg("S000", self._snap))
        finally:
            pull.close(linger=0)
            pub.close(linger=0)

    def run_on_engine(self, action: Callable[[Any], None]) -> None:
        """Run *action(pub)* on the engine thread and wait for it."""
        done = threading.Event()

        def _wrapped(pub: Any) -> None:
            action(pub)
            done.set()

        self._actions.put(_wrapped)
        assert done.wait(10)

    def flood(self, n: int) -> None:
        """Publish *n* book snapshots while the client is not reading."""

        def _burst(pub: Any) -> None:
            for _ in range(n):
                pub.send_multipart(make_book_msg("S000", self._snap))

        self.run_on_engine(_burst)
        time.sleep(0.2)  # let the I/O threads fill the pipes

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(5)


@pytest.fixture
def engine() -> Iterator[_StandInEngine]:
    eng = _StandInEngine()
    yield eng
    eng.stop()


def _client(engine: _StandInEngine) -> ExchangeCommandClient:
    return ExchangeCommandClient(
        GW,
        push_addr=engine.pull_addr,
        pub_addr=engine.pub_addr,
        index_pull_addr=f"tcp://127.0.0.1:{_free_port()}",
        index_pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        timeout_ms=3000,
    )


@pytest.fixture
def client(engine: _StandInEngine) -> Iterator[ExchangeCommandClient]:
    c = _client(engine)
    assert c.connect()["accepted"] is True
    yield c
    c.close()


# ---------------------------------------------------------------------------
# WP-ADM01 — a reply is never lost to the market-data backlog
# ---------------------------------------------------------------------------


@pytest.fixture
def streaming_engine() -> Iterator[tuple[str, str]]:
    """A stand-in engine *process* streaming 3 000 book snapshots a second."""
    pull_addr = f"tcp://127.0.0.1:{_free_port()}"
    pub_addr = f"tcp://127.0.0.1:{_free_port()}"
    proc = subprocess.Popen(
        [sys.executable, str(_STANDIN), pull_addr, pub_addr, "3000"],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        yield pull_addr, pub_addr
    finally:
        proc.kill()
        proc.wait(5)
        if proc.stdout is not None:
            proc.stdout.close()


def test_replies_arrive_after_idling_on_a_busy_market(
    streaming_engine: tuple[str, str],
) -> None:
    pull_addr, pub_addr = streaming_engine
    c = ExchangeCommandClient(
        GW,
        push_addr=pull_addr,
        pub_addr=pub_addr,
        index_pull_addr=f"tcp://127.0.0.1:{_free_port()}",
        index_pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        timeout_ms=3000,
    )
    try:
        assert c.connect()["accepted"] is True
        time.sleep(2.5)  # ~7 500 snapshots: the SUB queue overflows
        assert c.volume()["total_qty"] == 222
        time.sleep(2.5)
        # A mutating command: executed by the engine, so its ack must arrive.
        assert c.halt_all()["accepted"] is True
    finally:
        c.close()


def test_a_late_reply_queued_while_idle_is_not_taken_for_the_next_one(
    engine: _StandInEngine, client: ExchangeCommandClient
) -> None:
    engine.run_on_engine(
        lambda pub: pub.send_multipart(make_volume_msg(GW, [], 111, 0.0, 0))
    )
    time.sleep(0.2)
    assert client.volume()["total_qty"] == 222


def test_book_still_answers_after_a_flood(
    engine: _StandInEngine, client: ExchangeCommandClient
) -> None:
    engine.flood(6000)
    assert client.book_depth("S000")["symbol"] == "S000"


def test_no_engine_still_times_out() -> None:
    c = ExchangeCommandClient(
        GW,
        push_addr=f"tcp://127.0.0.1:{_free_port()}",
        pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        index_pull_addr=f"tcp://127.0.0.1:{_free_port()}",
        index_pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        timeout_ms=300,
    )
    try:
        with pytest.raises(CommandTimeoutError):
            c.connect()
    finally:
        c.close()


# ---------------------------------------------------------------------------
# WP-ADM02 — a connect never misses its own auth reply
# ---------------------------------------------------------------------------


def test_connect_waits_until_replies_can_arrive(tmp_path: Path) -> None:
    """The engine answers the connect before this client's SUB socket is
    connected: the auth reply is lost, the engine holds the ID, and the real
    engine refused every later connect for three minutes."""
    # An ipc endpoint, not a free TCP port: the port would be unreserved for
    # the 0.3 s before the late bind, long enough for another xdist worker
    # to take it in a full run.
    eng = _StandInEngine(pub_delay=0.3, pub_addr=f"ipc://{tmp_path / 'pub'}")
    c = _client(eng)
    try:
        assert c.connect()["accepted"] is True
    finally:
        c.close()
        eng.stop()
    assert eng.received.count("system.gateway_connect") == 1


def test_connect_proves_the_reply_path_before_connecting(
    engine: _StandInEngine,
) -> None:
    c = _client(engine)
    try:
        assert c.connect()["accepted"] is True
    finally:
        c.close()
    first_connect = engine.received.index("system.gateway_connect")
    assert "system.session_state_request" in engine.received[:first_connect]
    assert engine.received.count("system.gateway_connect") == 1


def test_a_refused_connect_sends_no_disconnect(engine: _StandInEngine) -> None:
    engine.accept = False
    c = _client(engine)
    try:
        result = c.connect()
    finally:
        c.close()
    time.sleep(0.1)
    assert result["accepted"] is False
    assert "system.gateway_disconnect" not in engine.received
