"""pm-alf-console tells the engine it is alive, so a killed console frees its
participant ID instead of locking it."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import zmq
from edumatcher.models.message import decode


def _make_gateway(gw_id: str = "GW01"):
    from edumatcher.alf_console.main import Gateway

    with (
        patch("edumatcher.alf_console.main.make_pusher", return_value=MagicMock()),
        patch("edumatcher.alf_console.main.make_subscriber", return_value=MagicMock()),
    ):
        return Gateway(gw_id)


def test_heartbeat_loop_sends_beat_on_its_own_socket_then_stops() -> None:
    gw = _make_gateway()
    own_push = MagicMock()
    gw._heartbeat_stop.set()

    with patch("edumatcher.alf_console.main.make_pusher", return_value=own_push):
        gw._heartbeat_loop()

    topic, payload = decode(own_push.send_multipart.call_args.args[0])
    assert topic == "system.gateway_heartbeat"
    assert payload == {"gateway_id": "GW01", "interval_sec": 60}
    own_push.close.assert_called_once()


def test_send_logs_out_when_engine_connection_is_lost() -> None:
    gw = _make_gateway()
    gw.push_sock.send_multipart.side_effect = zmq.Again()

    with patch("edumatcher.alf_console.main.console.print") as print_message:
        sent = gw._send(gw.push_sock, [])

    assert sent is False
    assert gw._running is False
    print_message.assert_called_once()
    assert "Engine connection was lost" in str(print_message.call_args.args)


def test_heartbeat_logs_out_after_engine_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _make_gateway()
    own_push = MagicMock()
    own_push.send_multipart.side_effect = [None, zmq.Again()]
    monkeypatch.setattr(gw._heartbeat_stop, "wait", lambda _timeout: False)

    with (
        patch("edumatcher.alf_console.main.make_pusher", return_value=own_push),
        patch("edumatcher.alf_console.main.console.print") as print_message,
    ):
        gw._heartbeat_loop()

    assert gw._running is False
    print_message.assert_called_once()
    assert "Engine connection was lost" in str(print_message.call_args.args)
    own_push.close.assert_called_once()


def test_engine_disconnect_interrupts_an_idle_prompt() -> None:
    gw = _make_gateway()
    session = MagicMock()
    session.app.loop.is_running.return_value = True
    gw._prompt_session = session

    with patch("edumatcher.alf_console.main.console.print"):
        gw._engine_connection_lost()

    assert gw._running is False
    schedule_exit = session.app.loop.call_soon_threadsafe.call_args.args[0]
    schedule_exit()
    session.app.exit.assert_called_once_with(exception=KeyboardInterrupt)


def test_engine_peer_disconnect_logs_out_alf_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _make_gateway()
    context: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    engine_pub = context.socket(zmq.PUB)
    port = engine_pub.bind_to_random_port("tcp://127.0.0.1")
    gateway_sub = context.socket(zmq.SUB)
    gateway_sub.setsockopt(zmq.SUBSCRIBE, b"")
    gateway_sub.connect(f"tcp://127.0.0.1:{port}")
    gw.sub_sock = gateway_sub
    gw._index_sub_sock = context.socket(zmq.SUB)
    gw._dc_sub_sock = context.socket(zmq.SUB)
    received = threading.Event()
    monkeypatch.setattr(gw, "_handle_event", lambda _topic, _payload: received.set())
    listener = threading.Thread(target=gw._listen, daemon=True)
    try:
        with patch("edumatcher.alf_console.main.console.print") as print_message:
            listener.start()
            deadline = time.monotonic() + 5.0
            while not received.is_set():
                engine_pub.send_multipart([b"test", b"{}"])
                assert time.monotonic() < deadline
                received.wait(0.02)

            engine_pub.close(linger=0)
            listener.join(timeout=5.0)

        assert not listener.is_alive()
        assert gw._running is False
        assert "Engine connection was lost" in str(print_message.call_args.args)
    finally:
        gw._running = False
        listener.join(timeout=5.0)
        gateway_sub.close(linger=0)
        gw._index_sub_sock.close(linger=0)
        gw._dc_sub_sock.close(linger=0)
        engine_pub.close(linger=0)
