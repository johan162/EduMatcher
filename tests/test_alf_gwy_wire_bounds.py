"""The ALF gateway enforces everything ``OrderNew.validate()`` would have.

``_handle_new_single`` builds its bus frame with ``make_order_new_unchecked``
because the validating builder costs 5.0 µs an order and 4.6 µs of that is a
dataclass round trip with no safety value
(``docs-design/EduMatcher-Perf-Analysis.md`` §7). The remaining 355 ns *is* a
safety trade, and it is only an acceptable one while every rule the generated
``validate()`` declares is enforced somewhere earlier.

"Somewhere earlier" is one of three places, and this module pins which:

* **per order, in the gateway** — the client-supplied fields;
* **once, at startup or handshake** — the config-derived fields, which a
  client cannot influence and which have no business being re-checked 45 000
  times a second;
* **structurally** — fields the gateway does not take from the client at all,
  because ``Order.create`` sets them.

The test that matters most is :func:`test_every_validate_rule_is_accounted_for`.
It reads the rules out of the generated source, so a *new* rule added to the
spec fails here until someone decides which of the three columns it belongs in.
Without that, this file would silently stop covering the thing it exists for.
"""

from __future__ import annotations

import inspect
import re
import socket
import time
from typing import Any

import pytest

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import (
    _MAX_GATEWAY_ID_LEN,
    _MAX_SYMBOL_LEN,
    AlfGateway,
    ClientSession,
)
from edumatcher.alf_gwy.protocol import parse_alf_line
from edumatcher.models.generated import order as G
from edumatcher.models.message import make_order_new_msg, make_order_new_unchecked_msg
from edumatcher.models.price import register_tick_decimals


class _FakePush:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)


class _FakeSub:
    def setsockopt(self, op: int, value: bytes) -> None:
        _ = (op, value)


@pytest.fixture()
def gateway(monkeypatch: pytest.MonkeyPatch) -> AlfGateway:
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_pusher", lambda _addr: _FakePush()
    )
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_subscriber", lambda _addr, *_t: _FakeSub()
    )
    gw = AlfGateway(
        AlfGatewayConfig(
            bind_address="127.0.0.1",
            port=5567,
            max_commands_per_second=10**6,
            gateway_roles=(("TRADER01", "TRADER"),),
        )
    )
    gw._push = _FakePush()
    gw._sub = _FakeSub()
    register_tick_decimals("AAPL", 2)
    gw._symbols_snapshot_loaded = True
    gw._known_symbols.add("AAPL")
    return gw


def _session() -> tuple[ClientSession, socket.socket]:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    session = ClientSession(sock=left, addr=("local", 0))
    session.authenticated = True
    session.gateway_id = "TRADER01"
    session.role = "TRADER"
    session.rate_tokens = 1e6
    session.rate_updated = time.monotonic()
    return session, right


def _reject_code(gateway: AlfGateway, line: str) -> str | None:
    """Submit *line* and return the ERR code, or None if it was accepted."""
    session, peer = _session()
    try:
        gateway._clients[session.sock.fileno()] = session
        gateway._handle_client_line(session, line)
        if not session.out_queue:
            return None
        frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
        return frame.fields.get("CODE") if frame.command == "ERR" else None
    finally:
        peer.close()
        session.close()


_GOOD = "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TAG=ORDER-001"


class TestClientSuppliedFieldsAreRejectedPerOrder:
    """The fields a client controls. Each must never reach the bus unchecked."""

    @pytest.mark.parametrize(
        "line,rule",
        [
            ("NEW|SYM=AAPL|SIDE=SIDEWAYS|TYPE=LIMIT|QTY=1|PRICE=1.00", "side"),
            ("NEW|SYM=AAPL|SIDE=BUY|TYPE=NOPE|QTY=1|PRICE=1.00", "order_type"),
            ("NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=1.00|TIF=FOREVER", "tif"),
            ("NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=0|PRICE=1.00", "quantity > 0"),
            ("NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=-5|PRICE=1.00", "quantity > 0"),
            ("NEW|SYM=NOSUCH|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=1.00", "symbol"),
            (
                "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=1.00|SMP=SOMETIMES",
                "smp_action",
            ),
            (
                "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=1.00|TAG=" + "T" * 65,
                "client_tag max_len 64",
            ),
        ],
    )
    def test_violation_is_refused_before_the_bus(
        self, gateway: AlfGateway, line: str, rule: str
    ) -> None:
        push = gateway._push
        assert isinstance(push, _FakePush)
        assert _reject_code(gateway, line) is not None, f"{rule} reached the bus"
        assert not push.sent, f"{rule} was published"

    def test_the_control_order_is_accepted(self, gateway: AlfGateway) -> None:
        """Guard against the parametrised cases passing for the wrong reason."""
        push = gateway._push
        assert isinstance(push, _FakePush)
        assert _reject_code(gateway, _GOOD) is None
        assert len(push.sent) == 1


class TestConfigDerivedFieldsAreBoundedOnce:
    """Fields a client cannot influence, checked off the per-order path."""

    def test_an_oversized_gateway_id_is_refused_at_hello(
        self, gateway: AlfGateway
    ) -> None:
        session, peer = _session()
        session.authenticated = False
        session.gateway_id = None
        try:
            gateway._clients[session.sock.fileno()] = session
            gateway._handle_client_line(
                session,
                f"HELLO|CLIENT=x|PROTO=ALF1|GW={'G' * (_MAX_GATEWAY_ID_LEN + 1)}",
            )
            assert session.out_queue, "over-long gateway id was accepted"
            frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
            assert frame.command == "ERR"
            assert session.gateway_id is None
        finally:
            peer.close()
            session.close()

    def test_an_oversized_symbol_never_becomes_tradable(
        self, gateway: AlfGateway
    ) -> None:
        """The engine is the only source of symbols, so this is a config error;
        it is dropped when the snapshot lands rather than per order."""
        session, peer = _session()
        try:
            gateway._clients[session.sock.fileno()] = session
            gateway._active_gateway_sessions["TRADER01"] = session.sock.fileno()
            gateway._known_symbols.clear()
            gateway._handle_symbols_response(
                "TRADER01",
                {
                    "symbols": [
                        {"symbol": "OK", "tick_decimals": 2},
                        {"symbol": "S" * (_MAX_SYMBOL_LEN + 1), "tick_decimals": 2},
                    ]
                },
            )
            assert "OK" in gateway._known_symbols
            assert "S" * (_MAX_SYMBOL_LEN + 1) not in gateway._known_symbols
        finally:
            peer.close()
            session.close()


class TestStructurallySafeFields:
    """Fields ``Order.create`` sets, which the client never supplies."""

    def test_generated_order_id_is_inside_the_wire_limit(self) -> None:
        from edumatcher.models.ids import new_order_id

        assert len(new_order_id()) <= 64

    def test_status_origin_and_remaining_qty_come_from_order_create(
        self, gateway: AlfGateway
    ) -> None:
        from edumatcher.models.message import decode

        push = gateway._push
        assert isinstance(push, _FakePush)
        assert _reject_code(gateway, _GOOD) is None
        _topic, payload = decode(push.sent[0])
        assert payload["status"] == "NEW"
        assert payload["origin"] == "ORDER"
        assert payload["remaining_qty"] == payload["quantity"] == 100
        assert payload["timestamp"] > 0


class TestTheTwoBuildersStillAgree:
    """The switch is only safe while the frames are identical."""

    @pytest.mark.parametrize(
        "extra",
        [
            {},
            {"price": 15000, "client_tag": "T-1"},
            {"smp_action": "CANCEL_BOTH"},
            {"oco_group_id": "OCO-1", "leg_index": 0, "combo_parent_id": "CMB-1"},
            {"visible_qty": 10, "displayed_qty": 10},
        ],
    )
    def test_byte_identical_frames(self, extra: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "id": "a" * 32,
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "tif": "DAY",
            "quantity": 100,
            "remaining_qty": 100,
            "gateway_id": "TRADER01",
            "timestamp": 1,
            "status": "NEW",
            **extra,
        }
        assert make_order_new_unchecked_msg(payload) == make_order_new_msg(payload)


def test_every_validate_rule_is_accounted_for() -> None:
    """A new rule in the spec must be classified, not silently uncovered.

    This reads the generated ``validate()`` and requires every field it
    constrains to appear in one of the three buckets above. It is deliberately
    a source-level check: the point is to fail when the *spec* grows a rule
    that nothing in the gateway enforces, which no behavioural test can notice.
    """
    constrained = set(
        re.findall(r"self\.(\w+)(?:\s|\)|\.)", inspect.getsource(G.OrderNew.validate))
    )

    checked_per_order = {
        "side",
        "order_type",
        "tif",
        "quantity",
        "smp_action",
        "symbol",
        "client_tag",
    }
    bounded_once = {"gateway_id"}
    set_by_order_create = {
        "id",
        "remaining_qty",
        "timestamp",
        "status",
        "origin",
        # Always None on the single-order path; the OCO and combo handlers
        # build their own messages through the validating builder.
        "oco_group_id",
        "combo_parent_id",
        "quote_id",
    }

    accounted = checked_per_order | bounded_once | set_by_order_create
    unaccounted = constrained - accounted
    assert not unaccounted, (
        "order_new gained validation rules the ALF gateway does not enforce: "
        f"{sorted(unaccounted)}. Either enforce them in _handle_new_single, "
        "bound them once at startup, or revert that path to the validating "
        "builder make_order_new_msg."
    )
