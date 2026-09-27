"""Tests for pm-dc-spy: formatters, CLI parsing, and a full integration path
connecting a real DcSpyClient to a real DropCopyPublisher over ZMQ.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from collections.abc import Generator
from unittest.mock import Mock

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
from tests.conftest import free_port

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
        "trade_ids": ["000001-000000042"],
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
    parser = dc_spy_cli.build_parser()
    args = parser.parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 5557
    assert args.gateway is None
    assert args.replay_of is None
    assert args.format == "human"
    assert args.count == 0


def test_cli_parser_gateway_override() -> None:
    parser = dc_spy_cli.build_parser()
    args = parser.parse_args(["--gateway", "trader01"])
    assert args.gateway == "trader01"


def test_cli_parser_version(capsys: pytest.CaptureFixture[str]) -> None:
    parser = dc_spy_cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])
    out = capsys.readouterr().out
    assert "pm-dc-spy" in out


@pytest.mark.parametrize(
    "arguments, expected",
    [
        ({"log_level": "ERROR", "verbose": 2, "quiet": False}, logging.ERROR),
        ({"log_level": None, "verbose": 2, "quiet": False}, logging.DEBUG),
        ({"log_level": None, "verbose": 1, "quiet": False}, logging.INFO),
        ({"log_level": None, "verbose": 0, "quiet": True}, logging.WARNING),
        ({"log_level": None, "verbose": 0, "quiet": False}, logging.WARNING),
    ],
)
def test_logging_precedence_matches_operator_intent(
    arguments: dict[str, object],
    expected: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace(
        **arguments,
        log_target="file",
        log_file="spy.log",
        log_failover_timeout=None,
    )
    client_config = argparse.Namespace(
        connect_timeout_sec=1.5,
        failover_timeout_sec=30.0,
        failover_dir="fallback",
    )
    server_config = argparse.Namespace(port=5600)
    handler = logging.NullHandler()
    resolve = Mock(return_value=handler)
    basic_config = Mock()
    monkeypatch.setattr(
        dc_spy_cli, "load_default_log_client_config", lambda: client_config
    )
    monkeypatch.setattr(
        dc_spy_cli, "load_default_log_server_config", lambda: server_config
    )
    monkeypatch.setattr(dc_spy_cli, "resolve_host_default", lambda: "log-host")
    monkeypatch.setattr(dc_spy_cli, "resolve_handler", resolve)
    monkeypatch.setattr(logging, "basicConfig", basic_config)

    assert dc_spy_cli._configure_logging(args) == expected
    basic_config.assert_called_once_with(
        level=expected, format=dc_spy_cli._LOG_FORMAT, handlers=[handler]
    )
    assert resolve.call_args.kwargs["host"] == "log-host"
    assert resolve.call_args.kwargs["port"] == 5600
    assert resolve.call_args.kwargs["failover_timeout_sec"] == 30.0


def test_explicit_failover_timeout_reaches_log_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace(
        log_level=None,
        verbose=0,
        quiet=False,
        log_target=None,
        log_file=None,
        log_failover_timeout=4.5,
    )
    monkeypatch.setattr(
        dc_spy_cli,
        "load_default_log_client_config",
        lambda: argparse.Namespace(
            connect_timeout_sec=1.0,
            failover_timeout_sec=30.0,
            failover_dir="fallback",
        ),
    )
    monkeypatch.setattr(
        dc_spy_cli,
        "load_default_log_server_config",
        lambda: argparse.Namespace(port=5600),
    )
    monkeypatch.setattr(dc_spy_cli, "resolve_host_default", lambda: "localhost")
    resolve = Mock(return_value=logging.NullHandler())
    monkeypatch.setattr(dc_spy_cli, "resolve_handler", resolve)
    monkeypatch.setattr(logging, "basicConfig", Mock())

    dc_spy_cli._configure_logging(args)

    assert resolve.call_args.kwargs["failover_timeout_sec"] == 4.5


@pytest.mark.parametrize(
    "isatty, no_color, expected",
    [(True, False, True), (True, True, False), (False, False, False)],
)
def test_session_enables_color_only_for_an_opted_in_terminal(
    isatty: bool,
    no_color: bool,
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = Mock()
    console_factory = Mock(return_value=console)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: isatty)
    monkeypatch.setattr(dc_spy_cli, "Console", console_factory)

    dc_spy_cli._SpySession(
        argparse.Namespace(no_color=no_color, format="human", raw=False)
    )

    console_factory.assert_called_once_with(
        highlight=False, no_color=not expected, force_terminal=expected
    )


def test_session_human_mode_honors_raw_and_counts_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = dc_spy_cli._SpySession(
        argparse.Namespace(no_color=True, format="human", raw=True)
    )
    formatted = Mock(return_value="rendered fill")
    monkeypatch.setattr(dc_spy_cli, "format_human", formatted)
    session.console.print = Mock()

    session.on_message("drop_copy.event.TRADER01", {"seq": 1}, 12.0)

    formatted.assert_called_once_with("drop_copy.event.TRADER01", {"seq": 1}, raw=True)
    session.console.print.assert_called_once_with("rendered fill")
    assert session.count == 1


def test_session_json_mode_emits_one_complete_record_and_ignores_raw(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    session = dc_spy_cli._SpySession(
        argparse.Namespace(no_color=True, format="json", raw=True)
    )
    monkeypatch.setattr(dc_spy_cli, "format_json", lambda *args, **kwargs: '{"seq": 1}')

    session.on_message("drop_copy.event.TRADER01", {"seq": 1}, 12.0)

    assert capsys.readouterr().out == '{"seq": 1}\n'
    assert session.count == 1


class _FakeSpyClient:
    instances: list["_FakeSpyClient"] = []
    connect_error: Exception | None = None
    run_error: BaseException | None = None

    def __init__(self, options: DcSpyOptions) -> None:
        self.options = options
        self.connected = False
        self.closed = False
        self.max_messages: int | None = None
        self.__class__.instances.append(self)

    def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    def run(self, callback: object, *, max_messages: int) -> None:
        self.max_messages = max_messages
        if self.run_error is not None:
            raise self.run_error

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_cli_client(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSpyClient]:
    _FakeSpyClient.instances = []
    _FakeSpyClient.connect_error = None
    _FakeSpyClient.run_error = None
    monkeypatch.setattr(dc_spy_cli, "DcSpyClient", _FakeSpyClient)
    monkeypatch.setattr(dc_spy_cli, "_configure_logging", lambda args: logging.WARNING)
    return _FakeSpyClient


def test_main_normalizes_filters_and_passes_count(
    fake_cli_client: type[_FakeSpyClient],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pm-dc-spy",
            "--gateway",
            " trader01 ",
            "--replay-of",
            " RISK01 ",
            "--count",
            "7",
            "--no-color",
        ],
    )

    dc_spy_cli.main()

    client = fake_cli_client.instances[0]
    assert client.options == DcSpyOptions(
        host="127.0.0.1",
        port=5557,
        gateway="TRADER01",
        replay_of="RISK01",
    )
    assert client.connected and client.closed
    assert client.max_messages == 7
    output = " ".join(capsys.readouterr().out.split())
    assert "drop_copy.event.TRADER01" in output
    assert "drop_copy.replay.RISK01" in output


def test_main_all_gateway_banner_does_not_claim_a_single_subscription(
    fake_cli_client: type[_FakeSpyClient],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-dc-spy", "--count", "1", "--no-color"])

    dc_spy_cli.main()

    output = " ".join(capsys.readouterr().out.split())
    assert "drop_copy.event.*" in output
    assert "all gateways" in output


def test_main_reports_connect_failure_as_cli_error(
    fake_cli_client: type[_FakeSpyClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_cli_client.connect_error = DcSpyConnectionError("feed unavailable")
    monkeypatch.setattr(sys, "argv", ["pm-dc-spy", "--no-color"])

    with pytest.raises(SystemExit, match="1"):
        dc_spy_cli.main()


@pytest.mark.parametrize(
    "failure, exits",
    [(DcSpyConnectionError("socket read failed"), True), (KeyboardInterrupt(), False)],
)
def test_main_always_closes_after_receive_loop_stops(
    failure: BaseException,
    exits: bool,
    fake_cli_client: type[_FakeSpyClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cli_client.run_error = failure
    monkeypatch.setattr(sys, "argv", ["pm-dc-spy", "--no-color"])

    if exits:
        with pytest.raises(SystemExit, match="1"):
            dc_spy_cli.main()
    else:
        dc_spy_cli.main()

    assert fake_cli_client.instances[0].closed is True


def test_json_mode_keeps_stdout_valid_json_lines(
    fake_cli_client: type[_FakeSpyClient],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def emit_record(
        self: _FakeSpyClient, callback: object, *, max_messages: int
    ) -> None:
        self.max_messages = max_messages
        callback("drop_copy.event.TRADER01", _fill_payload(), 1234.5)  # type: ignore[operator]

    monkeypatch.setattr(_FakeSpyClient, "run", emit_record)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-dc-spy", "--format", "json", "--count", "1", "--no-color"],
    )

    dc_spy_cli.main()

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(records) == 1
    assert records[0]["gateway_id"] == "TRADER01"


# ---------------------------------------------------------------------------
# Full integration: real DropCopyPublisher + real DcSpyClient over ZMQ
# ---------------------------------------------------------------------------


@pytest.fixture()
def publisher() -> Generator[tuple[DropCopyPublisher, int], None, None]:
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    port = free_port()
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
        pub.publish_fill(
            "TRADER01",
            order_id="ord-1",
            trade_ids=["000001-000000001"],
            symbol="AAPL",
            fill_qty=100,
            fill_price=150.25,
            liquidity_flag="MAKER",
        )

    t = threading.Thread(target=publish_after_subscribe)
    t.start()
    try:
        client.run(
            lambda topic, payload, ts: received.append((topic, payload)), max_messages=1
        )
    finally:
        t.join(timeout=2)
        client.close()

    assert len(received) == 1
    topic, payload = received[0]
    assert topic == "drop_copy.event.TRADER01"
    assert payload["gateway_id"] == "TRADER01"
    assert payload["trade_ids"] == ["000001-000000001"]
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
        pub.publish_fill(
            "TRADER02",
            order_id="ord-2",
            trade_ids=["000001-000000002"],
            symbol="MSFT",
            fill_qty=10,
            fill_price=1.0,
            liquidity_flag="TAKER",
        )
        pub.publish_fill(
            "TRADER01",
            order_id="ord-1",
            trade_ids=["000001-000000001"],
            symbol="AAPL",
            fill_qty=100,
            fill_price=150.25,
            liquidity_flag="MAKER",
        )

    t = threading.Thread(target=publish_both)
    t.start()
    try:
        client.run(
            lambda topic, payload, ts: received.append((topic, payload)), max_messages=1
        )
    finally:
        t.join(timeout=2)
        client.close()

    assert len(received) == 1
    assert received[0][1]["gateway_id"] == "TRADER01"


def test_integration_replay_topic_received_when_requested(
    publisher: tuple[DropCopyPublisher, int],
) -> None:
    pub, port = publisher
    opts = DcSpyOptions(
        host="127.0.0.1", port=port, gateway="NOBODY", replay_of="MY_RISK_SYS"
    )
    client = DcSpyClient(opts)
    client.connect()

    received: list[tuple[str, dict]] = []

    def publish_and_replay() -> None:
        time.sleep(0.2)
        pub.publish_fill(
            "TRADER01",
            order_id="ord-1",
            trade_ids=["000001-000000001"],
            symbol="AAPL",
            fill_qty=100,
            fill_price=150.25,
            liquidity_flag="MAKER",
        )
        pub.replay("MY_RISK_SYS", from_seq=1)

    t = threading.Thread(target=publish_and_replay)
    t.start()
    try:
        client.run(
            lambda topic, payload, ts: received.append((topic, payload)), max_messages=1
        )
    finally:
        t.join(timeout=2)
        client.close()

    assert len(received) == 1
    topic, payload = received[0]
    assert topic == "drop_copy.replay.MY_RISK_SYS"
    assert is_replay(topic)
