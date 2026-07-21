"""Tests for pm-ralf-spy: formatters, CLI parsing, and a full integration
path connecting a real RalfSpyClient to a real RalfGateway over TCP.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Generator

import pytest

from edumatcher.ralf_gateway.config import RalfGatewayConfig
from edumatcher.ralf_gateway.gateway import RalfGateway
from edumatcher.ralf_gateway.protocol import RalfFrame
from edumatcher.ralf_spy import cli as ralf_spy_cli
from edumatcher.ralf_spy.client import (
    RalfSpyClient,
    RalfSpyConnectionError,
    RalfSpyOptions,
)
from edumatcher.ralf_spy.formatters import format_human, format_json


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ---------------------------------------------------------------------------
# Formatter unit tests (no network involved)
# ---------------------------------------------------------------------------


def test_format_human_stream_event() -> None:
    frame = RalfFrame(
        msg_type="EXEC",
        fields={
            "CH": "CLEARING",
            "SYM": "AAPL",
            "SEQ": "4",
            "TS": "x",
            "PX": "150.1",
            "QTY": "200",
        },
    )
    line = format_human(frame)
    assert "EXEC" in line
    assert "CLEARING" in line
    assert "AAPL" in line
    assert "#4" in line
    assert "PX=150.1" in line
    assert "QTY=200" in line
    # Envelope fields must not be duplicated in the trailing payload dump.
    assert "TS=x" not in line
    assert "CH=CLEARING" not in line


def test_format_human_session_message_welcome() -> None:
    frame = RalfFrame(
        msg_type="WELCOME",
        fields={"PROTO": "RALF1", "GW": "ralf-gwy01", "ROLE": "AUDIT"},
    )
    line = format_human(frame)
    assert "WELCOME" in line
    assert "GW=ralf-gwy01" in line
    assert "ROLE=AUDIT" in line


def test_format_human_exit_message() -> None:
    frame = RalfFrame(msg_type="EXIT", fields={"REASON": "idle_timeout", "TS": "x"})
    line = format_human(frame)
    assert "EXIT" in line
    assert "REASON=idle_timeout" in line


def test_format_human_err_highlights_code() -> None:
    frame = RalfFrame(
        msg_type="ERR", fields={"CODE": "ENTITLEMENT_DENIED", "DETAIL": "nope"}
    )
    line = format_human(frame)
    assert "ERR" in line
    assert "ENTITLEMENT_DENIED" in line
    assert "DETAIL=nope" in line


def test_format_human_raw_line_appended() -> None:
    frame = RalfFrame(msg_type="PONG", fields={})
    line = format_human(frame, raw_line="PONG")
    assert "PONG" in line
    assert line.count("PONG") >= 2


def test_format_json_lifts_envelope_and_keeps_fields() -> None:
    frame = RalfFrame(
        msg_type="EXEC",
        fields={
            "CH": "AUDIT",
            "SYM": "AAPL",
            "SEQ": "9",
            "TS": "2026-07-20T10:00:00.000Z",
            "PX": "150.25",
        },
    )
    out = format_json(frame, recv_ts=1234.5)
    record = json.loads(out)
    assert record["ch"] == "AUDIT"
    assert record["sym"] == "AAPL"
    assert record["seq"] == 9  # coerced to int
    assert record["msg_type"] == "EXEC"
    assert record["fields"]["PX"] == "150.25"
    assert record["recv_ts"] == 1234.5


def test_format_json_non_integer_seq_kept_as_none() -> None:
    frame = RalfFrame(msg_type="HB", fields={"TS": "x"})
    out = format_json(frame, recv_ts=0.0)
    record = json.loads(out)
    assert record["seq"] is None
    assert record["ch"] is None


# ---------------------------------------------------------------------------
# CLI argument parsing (no network involved)
# ---------------------------------------------------------------------------


def test_cli_parser_defaults() -> None:
    parser = ralf_spy_cli._build_parser()
    args = parser.parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 5580
    assert args.role == "AUDIT"
    assert args.channels == "*"
    assert args.symbols == "*"
    assert args.lastseq == 0
    assert args.format == "human"
    assert args.count == 0
    assert args.ping_interval == 60.0


def test_cli_parser_ping_interval_override() -> None:
    parser = ralf_spy_cli._build_parser()
    args = parser.parse_args(["--ping-interval", "5"])
    assert args.ping_interval == 5.0


def test_cli_parser_version(capsys: pytest.CaptureFixture[str]) -> None:
    parser = ralf_spy_cli._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])
    out = capsys.readouterr().out
    assert "pm-ralf-spy" in out


def test_cli_parser_rejects_bad_role() -> None:
    parser = ralf_spy_cli._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--role", "NOT_A_ROLE"])


def test_entitled_channels_audit_gets_everything() -> None:
    assert ralf_spy_cli._entitled_channels("AUDIT") == [
        "CLEARING",
        "DROP_COPY",
        "AUDIT",
    ]


def test_entitled_channels_clearing_gets_only_itself() -> None:
    assert ralf_spy_cli._entitled_channels("CLEARING") == ["CLEARING"]


def test_resolve_channels_wildcard_uses_role_entitlement() -> None:
    assert ralf_spy_cli._resolve_channels("DROP_COPY", "*") == ["DROP_COPY"]
    assert ralf_spy_cli._resolve_channels("AUDIT", "*") == [
        "CLEARING",
        "DROP_COPY",
        "AUDIT",
    ]


def test_resolve_channels_explicit_list_ignores_role() -> None:
    channels = ralf_spy_cli._resolve_channels("AUDIT", "clearing,drop_copy")
    assert channels == ["CLEARING", "DROP_COPY"]


# ---------------------------------------------------------------------------
# Full integration: real RalfGateway thread + real RalfSpyClient socket
# ---------------------------------------------------------------------------


@pytest.fixture()
def running_gateway() -> Generator[RalfGateway, None, None]:
    cfg = RalfGatewayConfig(
        bind_address="127.0.0.1",
        port=_free_port(),
        engine_pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        heartbeat_interval_sec=60,  # keep heartbeats out of the way of assertions
        idle_timeout_sec=30,
        replay_retention_sec=3600,
    )
    gw = RalfGateway(cfg)
    thread = threading.Thread(target=gw.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2.0
    while gw._server is None and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        yield gw
    finally:
        gw.stop()
        thread.join(timeout=2.0)


def test_handshake_receives_welcome_with_role(running_gateway: RalfGateway) -> None:
    options = RalfSpyOptions(
        host="127.0.0.1",
        port=running_gateway.config.port,
        client_name="spy-test",
        role="AUDIT",
    )
    client = RalfSpyClient(options)
    try:
        client.connect()
        welcome = client.handshake()
        assert welcome.msg_type == "WELCOME"
        assert welcome.fields["ROLE"] == "AUDIT"
        assert welcome.fields["GW"] == running_gateway.config.name
    finally:
        client.close()


def test_handshake_rejects_disallowed_role() -> None:
    # Construct a gateway with a restricted allowed_roles set so a client
    # requesting a role outside it gets ENTITLEMENT_DENIED at HELLO time.
    restricted_cfg = RalfGatewayConfig(
        bind_address="127.0.0.1",
        port=_free_port(),
        engine_pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        heartbeat_interval_sec=60,
        allowed_roles=("CLEARING",),
    )
    gw2 = RalfGateway(restricted_cfg)
    thread = threading.Thread(target=gw2.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2.0
    while gw2._server is None and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        options2 = RalfSpyOptions(
            host="127.0.0.1", port=restricted_cfg.port, role="AUDIT"
        )
        client2 = RalfSpyClient(options2)
        client2.connect()
        with pytest.raises(RalfSpyConnectionError):
            client2.handshake()
        client2.close()
    finally:
        gw2.stop()
        thread.join(timeout=2.0)


def test_subscribe_clearing_receives_snap(running_gateway: RalfGateway) -> None:
    options = RalfSpyOptions(
        host="127.0.0.1", port=running_gateway.config.port, role="CLEARING"
    )
    client = RalfSpyClient(options)
    received: list[RalfFrame] = []
    try:
        client.connect()
        client.handshake()
        client.subscribe(["CLEARING"], ["AAPL"])
        client.run(lambda frame, raw, ts: received.append(frame), max_frames=1)
    finally:
        client.close()

    assert len(received) == 1
    frame = received[0]
    assert frame.msg_type == "SNAP"
    assert frame.fields["CH"] == "CLEARING"
    assert frame.fields["SYM"] == "AAPL"


def test_subscribe_wrong_channel_for_role_rejected(
    running_gateway: RalfGateway,
) -> None:
    options = RalfSpyOptions(
        host="127.0.0.1", port=running_gateway.config.port, role="CLEARING"
    )
    client = RalfSpyClient(options)
    received: list[RalfFrame] = []
    try:
        client.connect()
        client.handshake()
        client.subscribe(["DROP_COPY"], ["AAPL"])
        client.run(lambda frame, raw, ts: received.append(frame), max_frames=1)
    finally:
        client.close()

    assert len(received) == 1
    assert received[0].msg_type == "ERR"
    assert received[0].fields["CODE"] == "ENTITLEMENT_DENIED"


def test_audit_role_can_subscribe_any_channel(running_gateway: RalfGateway) -> None:
    options = RalfSpyOptions(
        host="127.0.0.1", port=running_gateway.config.port, role="AUDIT"
    )
    client = RalfSpyClient(options)
    received: list[RalfFrame] = []
    try:
        client.connect()
        client.handshake()
        client.subscribe(["DROP_COPY"], ["*"])
        client.run(lambda frame, raw, ts: received.append(frame), max_frames=1)
    finally:
        client.close()

    assert len(received) == 1
    assert received[0].msg_type == "SNAP"
    assert received[0].fields["CH"] == "DROP_COPY"


def test_live_exec_event_flows_to_client(running_gateway: RalfGateway) -> None:
    options = RalfSpyOptions(
        host="127.0.0.1", port=running_gateway.config.port, role="AUDIT"
    )
    client = RalfSpyClient(options)
    received: list[RalfFrame] = []
    try:
        client.connect()
        client.handshake()
        client.subscribe(["AUDIT"], ["AAPL"])

        def _emit_after_delay() -> None:
            time.sleep(0.05)
            running_gateway._emit_event(
                "EXEC",
                {
                    "SYM": "AAPL",
                    "TS": "2026-07-20T10:00:00.000Z",
                    "PX": "150.25",
                    "QTY": "300",
                    "SIDE": "BUY",
                },
                channel="AUDIT",
                symbol="AAPL",
            )

        t = threading.Thread(target=_emit_after_delay, daemon=True)
        t.start()
        # subscribe() itself triggers a SNAP first; the live EXEC follows.
        client.run(lambda frame, raw, ts: received.append(frame), max_frames=2)
        t.join(timeout=2.0)
    finally:
        client.close()

    assert len(received) == 2
    assert received[0].msg_type == "SNAP"
    frame = received[1]
    assert frame.msg_type == "EXEC"
    assert frame.fields["PX"] == "150.25"
    assert frame.fields["SIDE"] == "BUY"


def test_connect_refused_raises_connection_error() -> None:
    options = RalfSpyOptions(host="127.0.0.1", port=_free_port())
    client = RalfSpyClient(options)
    with pytest.raises(RalfSpyConnectionError):
        client.connect()
        client.handshake()


def test_ping_thread_sends_ping_and_gateway_replies_pong(
    running_gateway: RalfGateway,
) -> None:
    """A ralf-spy client with a short --ping-interval should send PING on
    its own (with no other outbound traffic after SUB) and get PONG back
    from the gateway -- the mechanism that keeps an otherwise-silent spy
    client from being dropped by idle_timeout_sec."""
    options = RalfSpyOptions(
        host="127.0.0.1",
        port=running_gateway.config.port,
        ping_interval_sec=0.05,
    )
    client = RalfSpyClient(options)
    received: list[RalfFrame] = []
    try:
        client.connect()
        client.handshake()

        t = threading.Thread(
            target=lambda: client.run(
                lambda frame, raw, ts: received.append(frame), max_frames=0
            ),
            daemon=True,
        )
        t.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not any(
            f.msg_type == "PONG" for f in received
        ):
            time.sleep(0.02)
    finally:
        client.close()

    assert any(frame.msg_type == "PONG" for frame in received)


def test_ping_disabled_when_interval_zero(running_gateway: RalfGateway) -> None:
    options = RalfSpyOptions(
        host="127.0.0.1",
        port=running_gateway.config.port,
        ping_interval_sec=0,
    )
    client = RalfSpyClient(options)
    try:
        client.connect()
        client.handshake()
        client._start_ping_thread()
        assert client._ping_thread is None
    finally:
        client.close()


def test_two_independent_clients_different_roles(running_gateway: RalfGateway) -> None:
    """Confirms the 'multiple terminals' use case: two separate
    RalfSpyClient connections against the same gateway, each with a
    different role/channel, do not interfere with one another."""
    port = running_gateway.config.port
    client_a = RalfSpyClient(
        RalfSpyOptions(host="127.0.0.1", port=port, role="CLEARING")
    )
    client_b = RalfSpyClient(
        RalfSpyOptions(host="127.0.0.1", port=port, role="DROP_COPY")
    )
    received_a: list[RalfFrame] = []
    received_b: list[RalfFrame] = []
    try:
        client_a.connect()
        client_a.handshake()
        client_a.subscribe(["CLEARING"], ["*"])

        client_b.connect()
        client_b.handshake()
        client_b.subscribe(["DROP_COPY"], ["*"])

        client_a.run(lambda f, r, t: received_a.append(f), max_frames=1)
        client_b.run(lambda f, r, t: received_b.append(f), max_frames=1)
    finally:
        client_a.close()
        client_b.close()

    assert received_a[0].fields["CH"] == "CLEARING"
    assert received_b[0].fields["CH"] == "DROP_COPY"


# ---------------------------------------------------------------------------
# _SpySession.on_frame -- HB/PONG suppression (--show-heartbeats)
# ---------------------------------------------------------------------------


def _make_session(*, show_heartbeats: bool) -> ralf_spy_cli._SpySession:
    import argparse

    args = argparse.Namespace(
        no_color=True,
        format="json",
        raw=False,
        show_heartbeats=show_heartbeats,
    )
    return ralf_spy_cli._SpySession(args)


def test_on_frame_hides_pong_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    """PONG (the gateway's reply to our own keep-alive PING) is noise by
    default, same as HB -- both are suppressed unless --show-heartbeats."""
    session = _make_session(show_heartbeats=False)
    session.on_frame(RalfFrame(msg_type="PONG", fields={}), "PONG", 0.0)

    out = capsys.readouterr().out
    assert out == ""
    assert session.count == 0


def test_on_frame_hides_hb_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    session = _make_session(show_heartbeats=False)
    session.on_frame(RalfFrame(msg_type="HB", fields={}), "HB", 0.0)

    out = capsys.readouterr().out
    assert out == ""
    assert session.count == 0


def test_on_frame_shows_pong_with_show_heartbeats(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _make_session(show_heartbeats=True)
    session.on_frame(RalfFrame(msg_type="PONG", fields={}), "PONG", 0.0)

    out = capsys.readouterr().out
    assert '"msg_type": "PONG"' in out
    assert session.count == 1


def test_on_frame_does_not_suppress_data_frames(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Only HB/PONG are suppressed -- ordinary stream data always prints."""
    session = _make_session(show_heartbeats=False)
    session.on_frame(
        RalfFrame(msg_type="DROP_COPY", fields={"CH": "DROP_COPY", "SYM": "AAPL"}),
        "DROP_COPY|...",
        0.0,
    )

    out = capsys.readouterr().out
    assert '"msg_type": "DROP_COPY"' in out
    assert session.count == 1
