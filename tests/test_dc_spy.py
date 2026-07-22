"""Tests for pm-dc-spy: formatters, CLI parsing, and a full integration path
connecting a real DcSpyClient to a real DropCopyPublisher over ZMQ.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Generator

import pytest
import zmq

from edumatcher.dc_spy import cli as dc_spy_cli
from edumatcher.dc_spy.client import (
    DcSpyClient,
    DcSpyConnectionError,
    DcSpyOptions,
)
from edumatcher.dc_spy.formatters import format_human, format_json, is_replay
from edumatcher.engine.drop_copy import DropCopyPublisher


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ---------------------------------------------------------------------------
# Formatter unit tests (no network involved)
# ---------------------------------------------------------------------------


def _fill_payload(**overrides: object) -> dict:
    payload = {
        "seq": 42,
        "timestamp": 1700000000000000000,
        "gateway_id": "TRADER01",
        "event_type": "order.fill",
        "order_id": "ord-001",
        "symbol": "MSFT",
        "fill_qty": 100,
        "fill_price": 420.0,
        "liquidity_flag": "MAKER",
    }
    payload.update(overrides)
    return payload


def test_format_human_fill_event() -> None:
    line = format_human("drop_copy.event.TRADER01", _fill_payload())
    assert "FILL" in line
    assert "TRADER01" in line
    assert "MSFT" in line
    assert "#42" in line
    assert "100@420.0" in line
    assert "MAKER" in line
    assert "order_id=ord-001" in line
    # Envelope fields must not be duplicated in the trailing payload dump.
    assert "seq=42" not in line
    assert "gateway_id=TRADER01" not in line


def test_format_human_replay_event_tagged() -> None:
    line = format_human("drop_copy.replay.MY_RISK_SYS", _fill_payload())
    assert "REPLAY" in line
    assert "FILL" not in line.replace("REPLAY", "")  # no stray "FILL" substring


def test_format_human_raw_appends_topic_and_json() -> None:
    payload = _fill_payload()
    line = format_human("drop_copy.event.TRADER01", payload, raw=True)
    assert "drop_copy.event.TRADER01|" in line
    assert '"order_id": "ord-001"' in line


def test_format_json_lifts_topic_and_replay_flag() -> None:
    out = format_json("drop_copy.event.TRADER01", _fill_payload(), recv_ts=1234.5)
    record = json.loads(out)
    assert record["topic"] == "drop_copy.event.TRADER01"
    assert record["replay"] is False
    assert record["seq"] == 42
    assert record["gateway_id"] == "TRADER01"
    assert record["fill_qty"] == 100
    assert record["recv_ts"] == 1234.5


def test_format_json_replay_flag_true_for_replay_topic() -> None:
    out = format_json("drop_copy.replay.MY_RISK_SYS", _fill_payload(), recv_ts=0.0)
    record = json.loads(out)
    assert record["replay"] is True


def test_is_replay() -> None:
    assert is_replay("drop_copy.replay.MY_RISK_SYS") is True
    assert is_replay("drop_copy.event.TRADER01") is False


# ---------------------------------------------------------------------------
# DcSpyOptions topic derivation
# ---------------------------------------------------------------------------


def test_options_event_topic_all_gateways() -> None:
    opts = DcSpyOptions()
    assert opts.event_topic == "drop_copy.event."
    assert opts.replay_topic is None


def test_options_event_topic_single_gateway() -> None:
    opts = DcSpyOptions(gateway="TRADER01")
    assert opts.event_topic == "drop_copy.event.TRADER01"


def test_options_replay_topic() -> None:
    opts = DcSpyOptions(replay_of="MY_RISK_SYS")
    assert opts.replay_topic == "drop_copy.replay.MY_RISK_SYS"


def test_options_addr() -> None:
    opts = DcSpyOptions(host="10.0.0.1", port=15557)
    assert opts.addr == "tcp://10.0.0.1:15557"


# ---------------------------------------------------------------------------
# CLI argument parsing (no network involved)
# ---------------------------------------------------------------------------


def test_cli_parser_defaults() -> None:
    parser = dc_spy_cli._build_parser()
    args = parser.parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 5557
    assert args.gateway is None
    assert args.replay_of is None
    assert args.format == "human"
    assert args.count == 0


def test_cli_parser_gateway_override() -> None:
    parser = dc_spy_cli._build_parser()
    args = parser.parse_args(["--gateway", "trader01"])
    assert args.gateway == "trader01"


def test_cli_parser_version(capsys: pytest.CaptureFixture[str]) -> None:
    parser = dc_spy_cli._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])
    out = capsys.readouterr().out
    assert "pm-dc-spy" in out


def test_cli_connect_error_bad_endpoint() -> None:
    # An invalid host string is rejected by zmq at connect() time.
    opts = DcSpyOptions(host="not a host", port=5557)
    client = DcSpyClient(opts)
    with pytest.raises(DcSpyConnectionError):
        client.connect()


# ---------------------------------------------------------------------------
# Full integration: real DropCopyPublisher + real DcSpyClient over ZMQ
# ---------------------------------------------------------------------------


@pytest.fixture()
def publisher() -> Generator[tuple[DropCopyPublisher, int], None, None]:
    ctx = zmq.Context.instance()
    port = _free_port()
    pub = DropCopyPublisher(ctx, addr=f"tcp://127.0.0.1:{port}")
    # Give the PUB socket a brief moment to finish binding before any
    # subscriber connects (avoids the classic PUB/SUB slow-joiner race).
    time.sleep(0.05)
    yield pub, port
    pub.close()


def test_integration_receives_published_fill(
    publisher: tuple[DropCopyPublisher, int],
) -> None:
    pub, port = publisher
    opts = DcSpyOptions(host="127.0.0.1", port=port)
    client = DcSpyClient(opts)
    client.connect()

    received: list[tuple[str, dict]] = []

    def publish_after_subscribe() -> None:
        time.sleep(0.2)  # let the SUB socket's subscription propagate
        pub.publish("TRADER01", "order.fill", {"symbol": "AAPL", "fill_qty": 100})

    t = threading.Thread(target=publish_after_subscribe)
    t.start()
    try:
        client.run(lambda topic, payload, ts: received.append((topic, payload)), max_messages=1)
    finally:
        t.join(timeout=2)
        client.close()

    assert len(received) == 1
    topic, payload = received[0]
    assert topic == "drop_copy.event.TRADER01"
    assert payload["gateway_id"] == "TRADER01"
    assert payload["symbol"] == "AAPL"
    assert payload["seq"] >= 1


def test_integration_gateway_filter_excludes_other_gateways(
    publisher: tuple[DropCopyPublisher, int],
) -> None:
    pub, port = publisher
    opts = DcSpyOptions(host="127.0.0.1", port=port, gateway="TRADER01")
    client = DcSpyClient(opts)
    client.connect()

    received: list[tuple[str, dict]] = []

    def publish_both() -> None:
        time.sleep(0.2)
        pub.publish("TRADER02", "order.fill", {"symbol": "MSFT", "fill_qty": 10})
        pub.publish("TRADER01", "order.fill", {"symbol": "AAPL", "fill_qty": 100})

    t = threading.Thread(target=publish_both)
    t.start()
    try:
        client.run(lambda topic, payload, ts: received.append((topic, payload)), max_messages=1)
    finally:
        t.join(timeout=2)
        client.close()

    assert len(received) == 1
    assert received[0][1]["gateway_id"] == "TRADER01"


def test_integration_replay_topic_received_when_requested(
    publisher: tuple[DropCopyPublisher, int],
) -> None:
    pub, port = publisher
    opts = DcSpyOptions(host="127.0.0.1", port=port, gateway="NOBODY", replay_of="MY_RISK_SYS")
    client = DcSpyClient(opts)
    client.connect()

    received: list[tuple[str, dict]] = []

    def publish_and_replay() -> None:
        time.sleep(0.2)
        pub.publish("TRADER01", "order.fill", {"symbol": "AAPL", "fill_qty": 100})
        pub.replay("MY_RISK_SYS", from_seq=1)

    t = threading.Thread(target=publish_and_replay)
    t.start()
    try:
        client.run(lambda topic, payload, ts: received.append((topic, payload)), max_messages=1)
    finally:
        t.join(timeout=2)
        client.close()

    assert len(received) == 1
    topic, payload = received[0]
    assert topic == "drop_copy.replay.MY_RISK_SYS"
    assert is_replay(topic)
