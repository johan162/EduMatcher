from __future__ import annotations

import select
import signal
import socket
import threading
import time
from collections.abc import Generator
from types import SimpleNamespace

import pytest

import edumatcher.md_gateway.gateway as gateway_mod
from edumatcher.md_gateway.client_session import ClientSession
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.gateway import MarketDataGateway, _extract_ts
from edumatcher.md_gateway.protocol import parse_line


class _FakeSubscriber:
    def __init__(self, events: list[tuple[str, dict[str, object]]]) -> None:
        self._events = list(events)

    def poll(self, timeout: int = 0) -> bool:
        _ = timeout
        return bool(self._events)

    def recv_multipart(self) -> tuple[str, dict[str, object]]:
        return self._events.pop(0)

    def close(self) -> None:
        return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def unit_gateway() -> Generator[MarketDataGateway, None, None]:
    cfg = MarketDataGatewayConfig(
        bind_address="127.0.0.1",
        port=_free_port(),
        engine_pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        heartbeat_interval_sec=1,
        idle_timeout_sec=1,
        replay_window_sec=5,
        max_client_queue=2,
    )
    gw = MarketDataGateway(cfg, known_symbols={"AAPL", "MSFT"})
    try:
        yield gw
    finally:
        gw.close()


def _make_session() -> tuple[ClientSession, socket.socket]:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    return ClientSession(sock=left, addr=("local", 0)), right


def test_run_single_iteration_main_thread(
    unit_gateway: MarketDataGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(threading, "current_thread", lambda: SimpleNamespace())
    monkeypatch.setattr(threading, "main_thread", lambda: SimpleNamespace())
    monkeypatch.setattr(signal, "signal", lambda *_: None)
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    def _accept_once() -> None:
        unit_gateway.stop()

    monkeypatch.setattr(unit_gateway, "_accept_new_clients", _accept_once)
    monkeypatch.setattr(unit_gateway, "_read_client_data", lambda: None)
    monkeypatch.setattr(unit_gateway, "_poll_engine_events", lambda: None)
    monkeypatch.setattr(unit_gateway, "_send_heartbeats_if_due", lambda: None)
    monkeypatch.setattr(unit_gateway, "_flush_client_writes", lambda: None)
    monkeypatch.setattr(unit_gateway, "_drop_idle_clients", lambda: None)

    unit_gateway.run()
    assert unit_gateway._server is None


def test_accept_new_clients(unit_gateway: MarketDataGateway) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", _free_port()))
    server.listen(5)
    server.setblocking(False)
    unit_gateway._server = server

    client = socket.create_connection(server.getsockname())
    client.setblocking(False)
    select.select([server], [], [], 2.0)
    unit_gateway._accept_new_clients()
    assert len(unit_gateway._clients) >= 1

    client.close()
    server.close()


def test_read_client_data_disconnect_on_eof(unit_gateway: MarketDataGateway) -> None:
    session, peer = _make_session()
    unit_gateway._clients[session.sock.fileno()] = session
    peer.close()
    unit_gateway._read_client_data()
    assert session.sock.fileno() not in unit_gateway._clients


def test_read_client_data_oversize_line(unit_gateway: MarketDataGateway) -> None:
    session, peer = _make_session()
    unit_gateway._clients[session.sock.fileno()] = session
    session.in_buffer.extend(b"X" * 4090)
    peer.sendall(b"Y" * 20)
    unit_gateway._read_client_data()
    assert session.closing is True
    frame = parse_line(session.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "BAD_MESSAGE"
    peer.close()


def test_drain_lines_overlong_with_newline(unit_gateway: MarketDataGateway) -> None:
    session, peer = _make_session()
    session.in_buffer.extend((b"X" * 5000) + b"\n")
    unit_gateway._drain_lines(session)
    assert session.closing is True
    peer.close()


def test_flush_client_writes_and_disconnect(unit_gateway: MarketDataGateway) -> None:
    session, peer = _make_session()
    session.out_queue.append(b"PONG\n")
    session.closing = True
    unit_gateway._clients[session.sock.fileno()] = session
    unit_gateway._flush_client_writes()
    assert session.sock.fileno() not in unit_gateway._clients
    peer.close()


def test_poll_engine_events_all_topics(
    unit_gateway: MarketDataGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeSubscriber(
        [
            (
                "book.aapl",
                {
                    "bids": [{"price": 100.1, "qty": 10}],
                    "asks": [{"price": 100.2, "qty": 11}],
                    "timestamp": 1.0,
                },
            ),
            (
                "trade.executed",
                {
                    "symbol": "AAPL",
                    "price": 100.2,
                    "quantity": 3,
                    "aggressor_side": "BUY",
                    "timestamp": 2.0,
                },
            ),
            (
                "session.state",
                {"state": "CONTINUOUS", "prev_state": "PRE_OPEN", "timestamp": 3.0},
            ),
            ("circuit_breaker.halt.aapl", {"timestamp": 4.0}),
            ("circuit_breaker.resume.aapl", {"timestamp": 5.0}),
        ]
    )
    unit_gateway._sub_sock = fake
    monkeypatch.setattr(gateway_mod, "decode", lambda payload: payload)

    seen: list[tuple[str, str, str]] = []

    def _capture(
        msg_type: str,
        ch: str,
        sym: str,
        payload_fields: dict[str, str],
        ts_seconds: float,
    ) -> None:
        _ = (payload_fields, ts_seconds)
        seen.append((msg_type, ch, sym))

    monkeypatch.setattr(unit_gateway, "_emit_stream_event", _capture)
    unit_gateway._poll_engine_events()

    assert ("MD", "TOP", "AAPL") in seen
    assert ("TRADE", "TRADE", "AAPL") in seen
    assert ("STATE", "STATE", "*") in seen
    assert ("STATE", "STATE", "AAPL") in seen


def test_drop_idle_clients(unit_gateway: MarketDataGateway) -> None:
    auth_session, auth_peer = _make_session()
    auth_session.authenticated = True
    auth_session.last_activity = time.monotonic() - 10

    new_session, new_peer = _make_session()
    new_session.authenticated = False
    new_session.last_activity = time.monotonic() - 10

    unit_gateway._clients[auth_session.sock.fileno()] = auth_session
    unit_gateway._clients[new_session.sock.fileno()] = new_session

    unit_gateway._drop_idle_clients()
    assert not unit_gateway._clients

    auth_peer.close()
    new_peer.close()


def test_extract_ts_fallback_and_parse_csv(unit_gateway: MarketDataGateway) -> None:
    assert _extract_ts({"timestamp": "2.5"}) == 2.5
    assert isinstance(_extract_ts({"timestamp": object()}), float)
    assert isinstance(_extract_ts({}), float)
    assert unit_gateway._parse_csv_upper(" aapl, msft ") == ["AAPL", "MSFT"]
