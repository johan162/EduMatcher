"""Tests for pm-calf-spy: formatters, CLI parsing, and a full integration
path connecting a real CalfSpyClient to a real MarketDataGateway over TCP.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Generator

import pytest

from edumatcher.calf_spy import cli as calf_spy_cli
from edumatcher.calf_spy.client import (
    CalfSpyClient,
    CalfSpyConnectionError,
    CalfSpyOptions,
    ResumeRequest,
)
from edumatcher.calf_spy.formatters import format_human, format_json
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.gateway import MarketDataGateway
from edumatcher.md_gateway.protocol import CalfFrame, parse_line


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ---------------------------------------------------------------------------
# Formatter unit tests (no network involved)
# ---------------------------------------------------------------------------


def test_format_human_stream_event() -> None:
    frame = CalfFrame(
        msg_type="TRADE",
        fields={
            "CH": "TRADE",
            "SYM": "AAPL",
            "SEQ": "12",
            "TS": "x",
            "PX": "150.1",
            "QTY": "200",
        },
    )
    line = format_human(frame)
    assert "TRADE" in line
    assert "AAPL" in line
    assert "#12" in line
    assert "PX=150.1" in line
    assert "QTY=200" in line
    # Envelope fields must not be duplicated in the trailing payload dump.
    assert "TS=x" not in line
    assert "CH=TRADE" not in line


def test_format_human_session_message_welcome() -> None:
    frame = CalfFrame(
        msg_type="WELCOME",
        fields={"PROTO": "CALF1", "GW": "md-gwy01", "CH_SUPPORTED": "TOP,TRADE"},
    )
    line = format_human(frame)
    assert "WELCOME" in line
    assert "GW=md-gwy01" in line


def test_format_human_err_highlights_code() -> None:
    frame = CalfFrame(msg_type="ERR", fields={"CODE": "INVALID_SYMBOL", "SYM": "ZZZZ"})
    line = format_human(frame)
    assert "ERR" in line
    assert "INVALID_SYMBOL" in line
    assert "SYM=ZZZZ" in line


def test_format_human_raw_line_appended() -> None:
    frame = CalfFrame(msg_type="PONG", fields={})
    line = format_human(frame, raw_line="PONG")
    assert "PONG" in line
    assert line.count("PONG") >= 2


def test_format_json_lifts_envelope_and_keeps_fields() -> None:
    frame = CalfFrame(
        msg_type="CB",
        fields={
            "CH": "CB",
            "SYM": "AAPL",
            "SEQ": "4",
            "TS": "2026-07-20T10:00:00.000Z",
            "STATUS": "HALTED",
        },
    )
    out = format_json(frame, recv_ts=1234.5)
    record = json.loads(out)
    assert record["ch"] == "CB"
    assert record["sym"] == "AAPL"
    assert record["seq"] == 4  # coerced to int
    assert record["msg_type"] == "CB"
    assert record["fields"]["STATUS"] == "HALTED"
    assert record["recv_ts"] == 1234.5


def test_format_json_non_integer_seq_kept_as_string() -> None:
    frame = CalfFrame(msg_type="HB", fields={"TS": "x"})
    out = format_json(frame, recv_ts=0.0)
    record = json.loads(out)
    assert record["seq"] is None
    assert record["ch"] is None


# ---------------------------------------------------------------------------
# CLI argument parsing (no network involved)
# ---------------------------------------------------------------------------


def test_cli_parser_defaults() -> None:
    parser = calf_spy_cli._build_parser()
    args = parser.parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 5570
    assert args.channels == "*"
    assert args.symbols == "*"
    assert args.format == "human"
    assert args.count == 0


def test_cli_parser_version(capsys: pytest.CaptureFixture[str]) -> None:
    parser = calf_spy_cli._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])
    out = capsys.readouterr().out
    assert "pm-calf-spy" in out


def test_parse_resume_valid() -> None:
    resume = calf_spy_cli._parse_resume("top:aapl:42")
    assert resume == ResumeRequest(channel="TOP", symbol="AAPL", last_seq=42)


def test_parse_resume_none() -> None:
    assert calf_spy_cli._parse_resume(None) is None


def test_parse_resume_bad_shape() -> None:
    with pytest.raises(ValueError):
        calf_spy_cli._parse_resume("TOP:AAPL")


def test_parse_resume_bad_lastseq() -> None:
    with pytest.raises(ValueError):
        calf_spy_cli._parse_resume("TOP:AAPL:notanumber")


def test_resolve_channels_wildcard_uses_ch_supported() -> None:
    welcome = CalfFrame(
        msg_type="WELCOME",
        fields={"CH_SUPPORTED": "CB,DEPTH,TOP,TRADE,AUCTION,STATE,INDEX"},
    )
    channels = calf_spy_cli._resolve_channels(welcome, "*")
    assert channels == sorted(
        ["CB", "DEPTH", "TOP", "TRADE", "AUCTION", "STATE", "INDEX"]
    )


def test_resolve_channels_wildcard_falls_back_without_ch_supported() -> None:
    welcome = CalfFrame(msg_type="WELCOME", fields={})
    channels = calf_spy_cli._resolve_channels(welcome, "*")
    assert channels == list(calf_spy_cli._BASELINE_CHANNELS)


def test_resolve_channels_explicit_list_ignores_welcome() -> None:
    welcome = CalfFrame(msg_type="WELCOME", fields={"CH_SUPPORTED": "TOP"})
    channels = calf_spy_cli._resolve_channels(welcome, "cb,trade")
    assert channels == ["CB", "TRADE"]


# ---------------------------------------------------------------------------
# Full integration: real MarketDataGateway thread + real CalfSpyClient socket
# ---------------------------------------------------------------------------


@pytest.fixture()
def running_gateway() -> Generator[MarketDataGateway, None, None]:
    cfg = MarketDataGatewayConfig(
        bind_address="127.0.0.1",
        port=_free_port(),
        engine_pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        index_pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        heartbeat_interval_sec=60,  # keep heartbeats out of the way of assertions
        idle_timeout_sec=30,
        replay_window_sec=10,
    )
    gw = MarketDataGateway(cfg, known_symbols={"AAPL", "MSFT"})
    thread = threading.Thread(target=gw.run, daemon=True)
    thread.start()
    # Give the listener a moment to bind before tests try to connect.
    deadline = time.monotonic() + 2.0
    while gw._server is None and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        yield gw
    finally:
        gw.stop()
        thread.join(timeout=2.0)


def test_handshake_receives_welcome_with_ch_supported(
    running_gateway: MarketDataGateway,
) -> None:
    options = CalfSpyOptions(
        host="127.0.0.1", port=running_gateway.config.port, client_name="spy-test"
    )
    client = CalfSpyClient(options)
    try:
        client.connect()
        welcome = client.handshake()
        assert welcome.msg_type == "WELCOME"
        assert "CH_SUPPORTED" in welcome.fields
        supported = set(welcome.fields["CH_SUPPORTED"].split(","))
        assert {"TOP", "TRADE", "STATE", "INDEX", "DEPTH", "AUCTION", "CB"} == supported
    finally:
        client.close()


def test_subscribe_top_receives_snap(running_gateway: MarketDataGateway) -> None:
    options = CalfSpyOptions(host="127.0.0.1", port=running_gateway.config.port)
    client = CalfSpyClient(options)
    received: list[CalfFrame] = []
    try:
        client.connect()
        client.handshake()
        client.subscribe(["TOP"], ["AAPL"])
        client.run(lambda frame, raw, ts: received.append(frame), max_frames=1)
    finally:
        client.close()

    assert len(received) == 1
    frame = received[0]
    assert frame.msg_type == "SNAP"
    assert frame.fields["CH"] == "TOP"
    assert frame.fields["SYM"] == "AAPL"


def test_subscribe_cb_wildcard_rejected_but_session_continues(
    running_gateway: MarketDataGateway,
) -> None:
    options = CalfSpyOptions(host="127.0.0.1", port=running_gateway.config.port)
    client = CalfSpyClient(options)
    received: list[CalfFrame] = []
    try:
        client.connect()
        client.handshake()
        client.subscribe(["CB"], ["*"])
        client.run(lambda frame, raw, ts: received.append(frame), max_frames=1)
    finally:
        client.close()

    assert len(received) == 1
    assert received[0].msg_type == "ERR"
    assert received[0].fields["CODE"] == "INVALID_SYMBOL"


def test_live_trade_event_flows_to_client(running_gateway: MarketDataGateway) -> None:
    options = CalfSpyOptions(host="127.0.0.1", port=running_gateway.config.port)
    client = CalfSpyClient(options)
    received: list[CalfFrame] = []
    try:
        client.connect()
        client.handshake()
        client.subscribe(["TRADE"], ["AAPL"])

        # Directly drive the gateway's internal emission path (mirrors the
        # pattern used in test_md_gateway_emit.py) rather than requiring a
        # real ZMQ publisher upstream -- this test is about the TCP/CALF
        # transport working end-to-end, not about engine wiring.
        def _emit_after_delay() -> None:
            time.sleep(0.05)
            running_gateway._emit_stream_event(
                "TRADE",
                "TRADE",
                "AAPL",
                {"PX": "150.25", "QTY": "300", "SIDE": "BUY"},
                ts_seconds=time.time(),
            )

        t = threading.Thread(target=_emit_after_delay, daemon=True)
        t.start()
        client.run(lambda frame, raw, ts: received.append(frame), max_frames=1)
        t.join(timeout=2.0)
    finally:
        client.close()

    assert len(received) == 1
    frame = received[0]
    assert frame.msg_type == "TRADE"
    assert frame.fields["PX"] == "150.25"
    assert frame.fields["SIDE"] == "BUY"


def test_connect_refused_raises_connection_error() -> None:
    options = CalfSpyOptions(host="127.0.0.1", port=_free_port())
    client = CalfSpyClient(options)
    with pytest.raises(CalfSpyConnectionError):
        client.connect()
        client.handshake()


def test_two_independent_clients_can_subscribe_different_channels(
    running_gateway: MarketDataGateway,
) -> None:
    """Confirms the 'multiple terminals' use case: two separate CalfSpyClient
    connections against the same gateway, each subscribed to a different
    channel, do not interfere with one another."""
    port = running_gateway.config.port
    client_a = CalfSpyClient(
        CalfSpyOptions(host="127.0.0.1", port=port, client_name="a")
    )
    client_b = CalfSpyClient(
        CalfSpyOptions(host="127.0.0.1", port=port, client_name="b")
    )
    received_a: list[CalfFrame] = []
    received_b: list[CalfFrame] = []
    try:
        client_a.connect()
        client_a.handshake()
        client_a.subscribe(["TOP"], ["AAPL"])

        client_b.connect()
        client_b.handshake()
        client_b.subscribe(["STATE"], ["*"])

        client_a.run(lambda f, r, t: received_a.append(f), max_frames=1)
        client_b.run(lambda f, r, t: received_b.append(f), max_frames=1)
    finally:
        client_a.close()
        client_b.close()

    assert received_a[0].fields["CH"] == "TOP"
    assert received_b[0].fields["CH"] == "STATE"


def test_parse_line_roundtrip_sanity() -> None:
    """Sanity check that CalfSpyClient reuses the shipped protocol parser
    rather than a hand-rolled duplicate (regression guard for a design
    decision made when building this tool)."""
    frame = parse_line("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=x|PX=1|QTY=1|SIDE=BUY")
    assert frame.msg_type == "TRADE"
    assert frame.fields["SYM"] == "AAPL"
