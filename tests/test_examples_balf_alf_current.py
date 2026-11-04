"""The BALF and ALF example clients stay in step with the gateways.

The examples are what customers copy, so they are held to what the production
code sends: the BALF parser decodes frames built by the gateway's own codec and
serialisers, and the ALF client renders the events and errors the gateway
documents (a cancel the exchange decided, a quote cancel, a lost session).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from edumatcher.balf_gwy import codec, protocol
from edumatcher.models.generated.order import (
    serialise_execution_report_balf,
    serialise_stop_triggered_balf,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs" / "examples"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def balf() -> ModuleType:
    return _load("balf_parser_example", EXAMPLES / "balf" / "balf_parser.py")


def _body(frame: bytes) -> bytes:
    return frame[codec.HEADER_SIZE :]


class TestBalfExampleAgainstTheGateway:
    def test_the_example_self_test_passes(self, balf: ModuleType) -> None:
        balf._self_test()

    def test_constants_are_the_gateways(self, balf: ModuleType) -> None:
        assert balf.LOGON_REJECT_NOT_CONFIGURED == codec.LOGON_REJECT_NOT_CONFIGURED
        assert balf.LOGON_REJECT_ALREADY_CONNECTED == codec.LOGON_REJECT_ALREADY_CONNECTED  # fmt: skip
        assert balf.LOGON_REJECT_PROTO_MISMATCH == codec.LOGON_REJECT_PROTO_MISMATCH
        assert balf.LOGON_REJECT_OTHER == codec.LOGON_REJECT_OTHER
        assert balf.CANCEL_REASON_CLIENT == codec.CANCEL_REASON_CLIENT
        assert balf.CANCEL_REASON_SYSTEM == codec.CANCEL_REASON_SYSTEM
        assert balf.STATUS_NAMES == {
            codec.STATUS_PARTIAL: "PARTIAL",
            codec.STATUS_FILLED: "FILLED",
        }
        assert balf.SIDE_NAMES == {codec.SIDE_BUY: "BUY", codec.SIDE_SELL: "SELL"}
        for code, name in balf.ORDER_REJECT_NAMES.items():
            assert getattr(protocol, f"RC_{name}") == code

    def test_every_gateway_reject_code_is_named(self, balf: ModuleType) -> None:
        gateway_codes = {
            v for k, v in vars(protocol).items() if k.startswith("RC_") and isinstance(v, int)  # fmt: skip
        }
        assert gateway_codes == set(balf.ORDER_REJECT_NAMES)

    def test_symbols_unavailable_is_the_text_the_gateway_sends(
        self, balf: ModuleType
    ) -> None:
        source = (ROOT / "src/edumatcher/balf_gwy/gateway.py").read_text()
        assert f'msg="{balf.LOGON_MSG_SYMBOLS_UNAVAILABLE}"' in source
        frame = codec.build_logon_ack(
            "TRADER01",
            accepted=False,
            reject_code=codec.LOGON_REJECT_OTHER,
            msg="SYMBOLS_UNAVAILABLE",
        )
        hdr, body = balf.split_frame(frame)
        ack = balf.parse_logon_ack(body)
        assert not ack["accepted"]
        assert ack["message"] == "SYMBOLS_UNAVAILABLE"
        assert "reconnect" in balf.describe_logon_ack(ack)

    def test_order_ack_names_the_reject(self, balf: ModuleType) -> None:
        frame = codec.build_order_ack(
            client_order_id=5,
            balf_order_id=0,
            seq_no=1,
            accepted=False,
            reject_code=protocol.RC_SYMBOL_NOT_CONFIGURED,
            reason="unknown symbol XYZ",
        )
        _, body = balf.split_frame(frame)
        ack = balf.parse_order_ack(body)
        assert ack["reject_name"] == "SYMBOL_NOT_CONFIGURED"
        assert ack["reason"] == "unknown symbol XYZ"

    def test_cancel_ack(self, balf: ModuleType) -> None:
        frame = codec.build_cancel_ack(
            client_order_id=7,
            balf_order_id=42,
            seq_no=2,
            accepted=True,
            cancel_reason=codec.CANCEL_REASON_SYSTEM,
        )
        _, body = balf.split_frame(frame)
        assert balf.parse_cancel_ack(body) == {
            "client_order_id": 7,
            "order_id": 42,
            "accepted": True,
            "cancel_reason": 255,
            "by_exchange": True,
        }

    def test_amend_ack(self, balf: ModuleType) -> None:
        frame = codec.build_amend_ack(
            client_order_id=7,
            balf_order_id=42,
            seq_no=3,
            accepted=True,
            new_price=codec.encode_price(150.25),
            new_quantity=80,
            remaining_qty=60,
            priority_reset=True,
        )
        _, body = balf.split_frame(frame)
        assert balf.parse_amend_ack(body) == {
            "client_order_id": 7,
            "order_id": 42,
            "new_price": 150.25,
            "new_quantity": 80,
            "remaining_qty": 60,
            "accepted": True,
            "priority_reset": True,
        }

    def test_stop_triggered(self, balf: ModuleType) -> None:
        frame = serialise_stop_triggered_balf(
            {
                "client_order_id": 7,
                "order_id": 42,
                "stop_price": 148.0,
                "trigger_price": 147.9,
                "symbol": "AAPL",
                "order_type": "STOP_LIMIT",
                "becomes": "LIMIT",
            },
            seq_no=4,
        )
        _, body = balf.split_frame(frame)
        assert balf.parse_stop_triggered(body) == {
            "client_order_id": 7,
            "order_id": 42,
            "stop_price": 148.0,
            "trigger_price": 147.9,
            "symbol": "AAPL",
            "order_type": "STOP_LIMIT",
            "becomes": "LIMIT",
        }

    def test_execution_report_names_side_and_status(self, balf: ModuleType) -> None:
        frame = serialise_execution_report_balf(
            {
                "client_order_id": 9,
                "order_id": 3,
                "fill_price": 99.5,
                "fill_qty": 10,
                "remaining_qty": 5,
                "timestamp_ns": 1,
                "symbol": "MSFT",
                "side": "SELL",
                "tick_decimals": 2,
                "status": "PARTIAL",
            },
            seq_no=5,
        )
        _, body = balf.split_frame(frame)
        report = balf.parse_execution_report(body)
        assert (report["side"], report["status"]) == ("SELL", "PARTIAL")

    def test_logout_is_a_bare_header(self, balf: ModuleType) -> None:
        hdr, body = balf.split_frame(codec.build_logout(6))
        assert hdr.msg_type == balf.MSG_LOGOUT and body == b""

    @pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler")
    def test_c_example_builds_and_runs(self, tmp_path: Path) -> None:
        exe = tmp_path / "balf_parser"
        gen = EXAMPLES / "generated"
        subprocess.run(
            ["cc", "-std=c11", "-Wall", "-Wextra", "-pedantic", "-Werror", "-O2",
             f"-I{gen}", str(EXAMPLES / "balf" / "balf_parser.c"),
             str(gen / "edumatcher_order.c"), str(gen / "edumatcher_msg.c"),
             "-o", str(exe)],
            check=True,
        )  # fmt: skip
        out = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
        assert "balf_parser.c self-test: OK" in out.stdout
        assert "SYMBOLS_UNAVAILABLE" in out.stdout
        assert "CANCEL_ACK" in out.stdout and "by=exchange" in out.stdout
        assert "AMEND_ACK" in out.stdout
        assert "STOP_TRIGGERED order_id=42 AAPL TRAILING_STOP" in out.stdout


@pytest.fixture(scope="module")
def alf_client_module() -> Iterator[ModuleType]:
    directory = str(EXAMPLES / "alf" / "python")
    sys.path.insert(0, directory)
    try:
        yield _load("alf_client_example", EXAMPLES / "alf" / "python" / "alf_client.py")
    finally:
        sys.path.remove(directory)
        sys.modules.pop("alf_parser", None)


class _Printed:
    """An AlfClient with its printing captured and no terminal behind it."""

    def __init__(self, module: ModuleType) -> None:
        self.client = object.__new__(module.AlfClient)
        self.client._orders = {}
        self.client._positions = {}
        self.lines: list[str] = []
        self.client._pr = self.lines.append
        self.parse = sys.modules["alf_parser"].parse_alf_line

    def send(self, line: str) -> str:
        self.lines.clear()
        self.client._handle(self.parse(line))
        return "\n".join(self.lines)


@pytest.fixture
def alf(alf_client_module: ModuleType) -> _Printed:
    return _Printed(alf_client_module)


class TestAlfPythonClient:
    def test_an_exchange_cancel_shows_why(self, alf: _Printed) -> None:
        out = alf.send(
            "CANCELLED|ORDER_ID=ORD-1|TAG=T1|CANCEL_REASON=SELF_MATCH_PREVENTED"
        )
        assert "reason=SELF_MATCH_PREVENTED" in out and "tag=T1" in out

    def test_my_own_cancel_has_no_reason(self, alf: _Printed) -> None:
        out = alf.send("CANCELLED|ORDER_ID=ORD-1|RTAG=R1")
        assert "reason=" not in out and "rtag=R1" in out

    def test_a_quote_cancel_is_not_shown_as_a_new_quote(self, alf: _Printed) -> None:
        out = alf.send("QUOTE_ACK|QUOTE_ID=Q1|SYM=AAPL|ACCEPTED=TRUE|REASON=|BID_ID=|ASK_ID=")  # fmt: skip
        assert "QUOTE CXL" in out and "bid=" not in out

    def test_a_new_quote_still_shows_its_legs(self, alf: _Printed) -> None:
        out = alf.send("QUOTE_ACK|QUOTE_ID=Q1|SYM=AAPL|ACCEPTED=TRUE|BID_ID=B1|ASK_ID=A1")  # fmt: skip
        assert "QUOTE ACK" in out and "bid=B1 ask=A1" in out

    @pytest.mark.parametrize(
        ("code", "hint"),
        [
            ("SESSION_LOST", "log on again"),
            ("SYMBOLS_NOT_READY", "retry shortly"),
            ("ENGINE_UNAVAILABLE", "retry shortly"),
            ("RATE_LIMITED", "slow down"),
        ],
    )
    def test_session_errors_say_what_to_do(
        self, alf: _Printed, code: str, hint: str
    ) -> None:
        out = alf.send(f"ERR|CODE={code}|DETAIL=whatever")
        assert f"[{code}]" in out and hint in out

    def test_every_session_ending_error_the_gateway_sends_has_a_hint(
        self, alf_client_module: ModuleType
    ) -> None:
        documented: dict[str, Any] = alf_client_module._ERR_HINTS
        for code in ("SESSION_LOST", "SYMBOLS_NOT_READY", "ENGINE_UNAVAILABLE"):
            assert code in documented
            assert f'"{code}"' in (ROOT / "src/edumatcher/alf_gwy/gateway.py").read_text()  # fmt: skip
