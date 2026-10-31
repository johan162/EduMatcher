from __future__ import annotations

import inspect
import json
import socket
import time
from collections.abc import Iterator, Mapping
from typing import Any, cast

import pytest
from fastapi import Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from starlette.requests import Request

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway, ClientSession
from edumatcher.alf_gwy.protocol import parse_alf_line
from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.main import create_app
from edumatcher.api_gateway.routers import orders
from edumatcher.api_gateway.schemas import ComboRequest, OcoRequest, OrderRequest
from edumatcher.api_gateway.sessions import Session
from edumatcher.models.order import OrderType, Side
from edumatcher.models.price import (
    TickViolation,
    clear_tick_registry,
    register_tick_decimals,
)


class _FakePush:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []
        self.closed = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)


class _FakeSub:
    def setsockopt(self, op: int, value: bytes) -> None:
        _ = (op, value)


@pytest.fixture(autouse=True)
def _symbols_loaded() -> Iterator[None]:
    """Stand in for the engine's symbols snapshot.

    The order routes now refuse a symbol whose tick precision has not arrived
    yet: converting a price before it does would apply the two-decimal default
    to an instrument that may not have two decimals. A live gateway registers
    these when it authenticates; these tests call the route functions directly,
    so they register them here.
    """
    clear_tick_registry()
    register_tick_decimals("AAPL", 2)
    register_tick_decimals("MSFT", 2)
    yield
    clear_tick_registry()


@pytest.fixture()
def alf_gateway(monkeypatch: pytest.MonkeyPatch) -> AlfGateway:
    fake_push = _FakePush()
    fake_sub = _FakeSub()
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_pusher", lambda _addr: fake_push
    )
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_subscriber",
        lambda _addr, *_topics: fake_sub,
    )
    gateway = AlfGateway(
        AlfGatewayConfig(
            bind_address="127.0.0.1",
            port=5565,
            max_commands_per_second=100,
            gateway_roles=(("TRADER01", "TRADER"),),
        )
    )
    gateway._push = fake_push
    gateway._sub = fake_sub
    gateway._symbols_snapshot_loaded = True
    gateway._known_symbols = {"AAPL"}
    return gateway


def _session() -> tuple[ClientSession, socket.socket]:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    session = ClientSession(sock=left, addr=("local", 0))
    session.authenticated = True
    session.gateway_id = "TRADER01"
    session.role = "TRADER"
    session.rate_tokens = 100.0
    session.rate_updated = time.monotonic()
    return session, right


def _alf_err_reject_code(gateway: AlfGateway, line: str) -> str:
    session, peer = _session()
    try:
        gateway._handle_client_line(session, line)
        assert session.out_queue, "ALF command did not produce an ERR"
        frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
        assert frame.command == "ERR"
        return frame.fields["REJECT_CODE"]
    finally:
        peer.close()
        session.close()


def _alf_err_detail(gateway: AlfGateway, line: str) -> str:
    session, peer = _session()
    try:
        gateway._handle_client_line(session, line)
        frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
        return frame.fields["DETAIL"]
    finally:
        peer.close()
        session.close()


def _alf_ack_reject_code(gateway: AlfGateway, payload: dict[str, object]) -> str:
    session, peer = _session()
    try:
        gateway._clients[session.sock.fileno()] = session
        gateway._active_gateway_sessions["TRADER01"] = session.sock.fileno()
        gateway._route_gateway_scoped_event("order.ack.TRADER01", payload)
        assert session.out_queue, "ALF rejected ACK was not routed to the client"
        frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
        assert frame.command == "ACK"
        assert frame.fields["ACCEPTED"] == "FALSE"
        return frame.fields["REJECT_CODE"]
    finally:
        gateway._clients.pop(session.sock.fileno(), None)
        gateway._active_gateway_sessions.pop("TRADER01", None)
        peer.close()
        session.close()


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/orders",
            "query_string": b"",
            "headers": [],
        }
    )


async def _rest_validation_reject_code(
    body: dict[str, object], model: type[BaseModel] = OrderRequest
) -> str:
    try:
        model.model_validate(body)
    except PydanticValidationError as exc:
        errors = cast(list[dict[str, object]], exc.errors())
    else:  # pragma: no cover - defensive; every caller passes an invalid body
        raise AssertionError("REST body did not fail validation")

    app = create_app(ApiGatewayConfig(swagger_enabled=False))
    handler = app.exception_handlers[RequestValidationError]
    result = handler(_request(), RequestValidationError(errors, body=body))
    response = await result if inspect.isawaitable(result) else result
    content = cast(dict[str, Any], json.loads(bytes(response.body).decode("utf-8")))
    error = cast(dict[str, Any], content["error"])
    return str(error["reject_code"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("alf_line", "rest_body", "expected"),
    [
        (
            "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=10|TAG=CT-MISSING",
            {
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": 10,
                "client_tag": "CT-MISSING",
            },
            "MISSING_FIELD",
        ),
        (
            "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=0|PRICE=100|TAG=CT-QTY",
            {
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": 0,
                "price": 100.0,
                "client_tag": "CT-QTY",
            },
            "INVALID_VALUE",
        ),
        (
            "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=10|PRICE=100|RTAG=REQ-NEW",
            {
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": 10,
                "price": 100.0,
                "request_tag": "REQ-NEW",
            },
            "UNSUPPORTED_FIELD",
        ),
    ],
)
async def test_alf_and_rest_request_shape_reject_codes_match(
    alf_gateway: AlfGateway,
    alf_line: str,
    rest_body: dict[str, object],
    expected: str,
) -> None:
    assert _alf_err_reject_code(alf_gateway, alf_line) == expected
    assert await _rest_validation_reject_code(rest_body) == expected


class _RejectedOrderEngine:
    def __init__(self, reject_code: str, reason: str) -> None:
        self.reject_code = reject_code
        self.reason = reason
        self.cache = type("Cache", (), {"orders": {}})()

    def get_caches(self, gateway_id: str) -> object:
        _ = gateway_id
        return self.cache

    def send_new_order(self, order: object) -> None:
        _ = order

    async def await_event(
        self, topic: str, match: Mapping[str, str] | None, timeout: float
    ) -> dict[str, Any]:
        _ = (topic, timeout)
        return {
            "order_id": match.get("order_id", "") if match else "",
            "accepted": False,
            "reason": self.reason,
            "reject_code": self.reject_code,
            "client_tag": "CT-BUSINESS",
        }


def _request_with_engine(engine: object) -> Any:
    return type(
        "Request",
        (),
        {
            "app": type(
                "App",
                (),
                {
                    "state": type(
                        "State",
                        (),
                        {
                            "engine": engine,
                            "config": ApiGatewayConfig(),
                            "rate_limiter": type(
                                "Limiter", (), {"allow": lambda self, key: True}
                            )(),
                        },
                    )()
                },
            )()
        },
    )()


@pytest.mark.anyio
async def test_alf_and_rest_business_rule_reject_codes_match(
    alf_gateway: AlfGateway,
) -> None:
    shared_reject = {
        "order_id": "ORD1",
        "accepted": False,
        "reason": "Symbol not configured: MSFT",
        "reject_code": "UNKNOWN_SYMBOL",
        "client_tag": "CT-BUSINESS",
    }
    alf_reject_code = _alf_ack_reject_code(alf_gateway, shared_reject)

    rest_engine = _RejectedOrderEngine(
        reject_code=str(shared_reject["reject_code"]),
        reason=str(shared_reject["reason"]),
    )
    rest_response = await orders.submit_order(
        OrderRequest(
            symbol="MSFT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=100.0,
            client_tag="CT-BUSINESS",
        ),
        _request_with_engine(rest_engine),
        Response(),
        Session(api_key="key", gateway_id="TRADER01", description="test"),
        wait="ack",
    )

    assert rest_response.accepted is False
    assert rest_response.reject_code == alf_reject_code
    assert rest_response.event is not None
    assert rest_response.event["reject_code"] == alf_reject_code


@pytest.mark.anyio
async def test_alf_and_rest_agree_on_tick_violation(
    alf_gateway: AlfGateway,
) -> None:
    """The one reject code neither gateway can delegate to the engine.

    Every other shared code is produced by the engine and merely relayed, so
    the two transports agree for free. Tick validation is different: the bus
    carries integer ticks and every integer is a valid tick, so the engine
    structurally cannot check this — each edge does it independently, and this
    is the only thing keeping their answers the same.
    """
    off_grid = 100.005  # not a multiple of AAPL's 0.01 tick

    session, peer = _session()
    try:
        alf_gateway._handle_client_line(
            session,
            f"NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=10|PRICE={off_grid}|TAG=CT-TICK",
        )
        assert session.out_queue, "ALF did not answer an off-grid price"
        frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
        assert frame.command == "ERR"
        alf_code = frame.fields["REJECT_CODE"]
        # The correlation tag survives, so the client can tell which order
        # was refused — the point of G1, exercised on a new reject path.
        assert frame.fields["TAG"] == "CT-TICK"
    finally:
        peer.close()
        session.close()

    app = create_app(ApiGatewayConfig(swagger_enabled=False))
    handler = app.exception_handlers[TickViolation]
    result = handler(_request(), TickViolation(off_grid, "AAPL", 2))
    response = await result if inspect.isawaitable(result) else result
    content = cast(dict[str, Any], json.loads(bytes(response.body).decode("utf-8")))
    rest_code = str(cast(dict[str, Any], content["error"])["reject_code"])

    assert alf_code == rest_code == "TICK_VIOLATION"


# --- WP-API16: one per-type field rule on every transport ---------------------

_ORDER = {"symbol": "AAPL", "side": "BUY", "quantity": 10}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("alf_line", "rest_body", "expected"),
    [
        # A field the type does not use: ALF used to drop it silently.
        (
            "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=10|PRICE=100|TRAIL=0.5",
            {**_ORDER, "order_type": "LIMIT", "price": 100.0, "trail_offset": 0.5},
            "UNSUPPORTED_FIELD",
        ),
        (
            "NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=10|PRICE=100",
            {**_ORDER, "order_type": "MARKET", "price": 100.0},
            "UNSUPPORTED_FIELD",
        ),
        (
            "NEW|SYM=AAPL|SIDE=BUY|TYPE=ICEBERG|QTY=10|PRICE=100|VISIBLE=2|STOP=95",
            {
                **_ORDER,
                "order_type": "ICEBERG",
                "price": 100.0,
                "visible_qty": 2,
                "stop_price": 95.0,
            },
            "UNSUPPORTED_FIELD",
        ),
        (
            "NEW|SYM=AAPL|SIDE=BUY|TYPE=STOP_LIMIT|QTY=10|STOP=95",
            {**_ORDER, "order_type": "STOP_LIMIT", "stop_price": 95.0},
            "MISSING_FIELD",
        ),
    ],
)
async def test_single_orders_follow_one_type_rule(
    alf_gateway: AlfGateway,
    alf_line: str,
    rest_body: dict[str, object],
    expected: str,
) -> None:
    assert _alf_err_reject_code(alf_gateway, alf_line) == expected
    assert await _rest_validation_reject_code(rest_body) == expected


_OCO = {"oco_id": "O1", "symbol": "AAPL", "quantity": 10}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("alf_legs", "rest_legs", "expected"),
    # REST bodies carry display prices (D8); the gateway converts to ticks.
    [
        # ALF used to forward these to the engine unchecked.
        (
            "LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=95",
            (
                {"side": "SELL", "order_type": "LIMIT"},
                {
                    "side": "SELL",
                    "order_type": "STOP",
                    "stop_price": 95.0,
                },
            ),
            "MISSING_FIELD",
        ),
        (
            "LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=105|LEG1_STOP=99"
            "|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=95",
            (
                {
                    "side": "SELL",
                    "order_type": "LIMIT",
                    "price": 105.0,
                    "stop_price": 99.0,
                },
                {
                    "side": "SELL",
                    "order_type": "STOP",
                    "stop_price": 95.0,
                },
            ),
            "UNSUPPORTED_FIELD",
        ),
        (
            "LEG1_SIDE=SELL|LEG1_TYPE=ICEBERG|LEG1_PRICE=105"
            "|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=95",
            (
                {
                    "side": "SELL",
                    "order_type": "ICEBERG",
                    "price": 105.0,
                },
                {
                    "side": "SELL",
                    "order_type": "STOP",
                    "stop_price": 95.0,
                },
            ),
            "INVALID_VALUE",
        ),
    ],
)
async def test_oco_legs_follow_one_type_rule(
    alf_gateway: AlfGateway,
    alf_legs: str,
    rest_legs: tuple[dict[str, object], dict[str, object]],
    expected: str,
) -> None:
    line = f"NEW|TYPE=OCO|OCO_ID=O1|SYM=AAPL|QTY=10|{alf_legs}"
    assert _alf_err_reject_code(alf_gateway, line) == expected
    # The verdict is on the leg, not an unrelated missing field.
    assert "LEG1_" in _alf_err_detail(
        alf_gateway, line
    ) or "OCO leg" in _alf_err_detail(alf_gateway, line)
    body = {**_OCO, "leg1": rest_legs[0], "leg2": rest_legs[1]}
    assert await _rest_validation_reject_code(body, OcoRequest) == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("alf_leg0", "rest_leg0", "expected"),
    [
        # STOP_LIMIT without a price: ALF and the engine used to accept it.
        (
            "LEG0.TYPE=STOP_LIMIT|LEG0.STOP=95",
            {"order_type": "STOP_LIMIT", "stop_price": 95.0},
            "MISSING_FIELD",
        ),
        (
            "LEG0.TYPE=LIMIT|LEG0.PRICE=100|LEG0.STOP=95",
            {"order_type": "LIMIT", "price": 100.0, "stop_price": 95.0},
            "UNSUPPORTED_FIELD",
        ),
        (
            "LEG0.TYPE=TRAILING_STOP",
            {"order_type": "TRAILING_STOP"},
            "INVALID_VALUE",
        ),
    ],
)
async def test_combo_legs_follow_one_type_rule(
    alf_gateway: AlfGateway,
    alf_leg0: str,
    rest_leg0: dict[str, object],
    expected: str,
) -> None:
    alf_gateway._known_symbols = {"AAPL", "MSFT"}
    line = (
        "NEW|TYPE=COMBO|COMBO_ID=C1|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=10|"
        f"{alf_leg0}|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=5|LEG1.PRICE=410"
    )
    assert _alf_err_reject_code(alf_gateway, line) == expected
    detail = _alf_err_detail(alf_gateway, line)
    assert "LEG0." in detail or "combo leg" in detail
    body: dict[str, object] = {
        "combo_id": "C1",
        "legs": [
            {"symbol": "AAPL", "side": "BUY", "quantity": 10, **rest_leg0},
            {"symbol": "MSFT", "side": "SELL", "quantity": 5, "price": 410.0},
        ],
    }
    assert await _rest_validation_reject_code(body, ComboRequest) == expected


def test_shared_conditions_map_to_one_reject_code() -> None:
    """The reject-code half of WP-API16: REST and ALF name their errors
    differently (RATE_LIMIT vs RATE_LIMITED), but a condition both report must
    carry the same reject_code."""
    from edumatcher.alf_gwy.protocol import _reject_code_for_error
    from edumatcher.api_gateway.errors import ERROR_CODES

    same_condition = {
        # REST code: ALF code
        "VALIDATION": "INVALID_VALUE",
        "READ_ONLY": "ROLE_DENIED",
        "ROLE_DENIED": "ROLE_DENIED",
        "RATE_LIMIT": "RATE_LIMITED",
        "SYMBOLS_NOT_READY": "SYMBOLS_NOT_READY",
        "ENGINE_UNAVAILABLE": "ENGINE_UNAVAILABLE",
        "INTERNAL_ERROR": "INTERNAL_ERROR",
        "AUTH": "AUTH_REQUIRED",
    }
    for rest_code, alf_code in same_condition.items():
        assert ERROR_CODES[rest_code].reject_code == _reject_code_for_error(alf_code), (
            rest_code,
            alf_code,
        )
