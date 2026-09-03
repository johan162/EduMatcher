from __future__ import annotations

import inspect
import json
import socket
import time
from collections.abc import Iterator, Mapping
from typing import Any, cast

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError
from starlette.requests import Request

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway, ClientSession
from edumatcher.alf_gwy.protocol import parse_alf_line
from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.main import create_app
from edumatcher.api_gateway.routers import orders
from edumatcher.api_gateway.schemas import OrderRequest
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


async def _rest_validation_reject_code(body: dict[str, object]) -> str:
    try:
        OrderRequest.model_validate(body)
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
    result = handler(_request(), TickViolation(off_grid, "AAPL"))
    response = await result if inspect.isawaitable(result) else result
    content = cast(dict[str, Any], json.loads(bytes(response.body).decode("utf-8")))
    rest_code = str(cast(dict[str, Any], content["error"])["reject_code"])

    assert alf_code == rest_code == "TICK_VIOLATION"
