"""The Swagger document: every endpoint carries a real, truthful example."""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.main import create_app
from edumatcher.models.generated import order as order_msgs
from edumatcher.models.generated import risk as risk_msgs
from edumatcher.models.generated import system as system_msgs

_METHODS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return create_app(ApiGatewayConfig(swagger_enabled=True)).openapi()


def _operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method.upper(), path, op)
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in _METHODS
    ]


def _success(op: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    codes = sorted(c for c in op["responses"] if c.startswith("2"))
    assert codes, "no 2xx response documented"
    return codes[0], op["responses"][codes[0]]


def _example_values(response: dict[str, Any]) -> list[Any]:
    media = response["content"]["application/json"]
    if "example" in media:
        return [media["example"]]
    return [e["value"] for e in media["examples"].values()]


def test_every_endpoint_has_a_summary_and_a_real_example(spec: dict[str, Any]) -> None:
    operations = _operations(spec)
    assert len(operations) > 60
    for method, path, op in operations:
        where = f"{method} {path}"
        assert op.get("summary") and op["summary"] != op["operationId"], where
        _, response = _success(op)
        for value in _example_values(response):
            assert isinstance(value, dict) and value, where
            assert "additionalProp1" not in value, where


def test_every_endpoint_documents_the_error_envelope(spec: dict[str, Any]) -> None:
    for method, path, op in _operations(spec):
        for code in ("400", "401", "403", "503"):
            assert code in op["responses"], f"{method} {path} lacks {code}"
        envelope = op["responses"]["401"]["content"]["application/json"]["example"]
        assert envelope["error"]["code"] == "AUTH"


def test_stock_fastapi_422_is_not_advertised(spec: dict[str, Any]) -> None:
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    for _, _, op in _operations(spec):
        response = op["responses"].get("422")
        if response is not None:
            assert "content" not in response


def test_auth_is_a_bearer_security_scheme_not_a_header_param(
    spec: dict[str, Any],
) -> None:
    """WP-API01 (S2): a security scheme gives Swagger its Authorize button and
    SDK generators a client-wide credential, where a required header
    parameter made every generated call take an `authorization` argument."""
    (name, scheme), *rest = spec["components"]["securitySchemes"].items()
    assert not rest
    assert (scheme["type"], scheme["scheme"]) == ("http", "bearer")
    assert "Bearer" in scheme["description"]
    for method, path, op in _operations(spec):
        assert op.get("security") == [{name: []}], f"{method} {path}"
        params = [p["name"].lower() for p in op.get("parameters", [])]
        assert "authorization" not in params, f"{method} {path}"


def test_list_orders_example_is_what_the_issue_asked_for(
    spec: dict[str, Any],
) -> None:
    op = spec["paths"]["/api/v1/orders"]["get"]
    (example,) = _example_values(_success(op)[1])
    assert example["orders"][0]["symbol"] == "AAPL"
    assert example["orders"][0]["status"] == "PARTIAL"


def test_order_lifecycle_example_preserves_wire_topics(spec: dict[str, Any]) -> None:
    op = spec["paths"]["/api/v1/admin/orders/{order_id}"]["get"]
    (example,) = _example_values(_success(op)[1])
    assert [event["topic"] for event in example["events"]] == [
        "order.ack.TRADER01",
        "order.fill.TRADER01",
    ]


def test_request_bodies_carry_examples(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    for name in (
        "OrderRequest",
        "AmendRequest",
        "OcoRequest",
        "ComboRequest",
        "QuoteRequest",
        "MassCancelRequest",
        "SessionTransitionRequest",
        "CircuitBreakerTriggerRequest",
        "KillSwitchGatewayRequest",
        "IndexRebalanceRequest",
    ):
        assert schemas[name].get("examples"), name
    body = spec["paths"]["/api/v1/orders"]["post"]["requestBody"]
    assert {"limit", "market", "iceberg"} <= set(
        body["content"]["application/json"]["examples"]
    )


# ---------------------------------------------------------------------------
# The examples must be what the engine really sends: round-trip them through
# the generated message classes, which validate field names, types and enums.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "payload"),
    [
        (system_msgs.Reference, docs.REFERENCE_BUNDLE),
        (system_msgs.Symbols, docs.SYMBOLS),
        (system_msgs.SessionStatus, docs.SESSION_STATUS),
        (system_msgs.HaltStatus, docs.HALT_STATUS),
        (system_msgs.HaltStatus, docs.ADMIN_HALTS),
        (system_msgs.QuoteBootstrap, docs.QUOTE_BOOTSTRAP),
        (system_msgs.QuoteLegs, docs.QUOTE_LEGS),
        (system_msgs.RiskState, docs.ADMIN_RISK_STATE),
        (system_msgs.Gateways, docs.ADMIN_GATEWAYS),
        (system_msgs.SessionSchedule, docs.ADMIN_SCHEDULE),
        (
            system_msgs.PositionSnapshot,
            {k: v for k, v in docs.ADMIN_POSITIONS.items() if k != "count"},
        ),
        (order_msgs.Orders, docs.ORDERS_LIST),
        (order_msgs.OrderAck, docs.ORDER_ACK_EVENT),
        (order_msgs.OrderAck, docs.ORDER_REJECT_EVENT),
        (order_msgs.OrderCancelled, docs.ORDER_CANCELLED_EVENT),
        (risk_msgs.KillSwitchAck, docs.MASS_CANCEL),
        (risk_msgs.SymbolHaltAck, docs.ADMIN_HALT_ACK),
        (risk_msgs.SymbolResumeAck, docs.ADMIN_RESUME_ACK),
        (risk_msgs.CancelSymbolAck, docs.ADMIN_KILL_SYMBOL),
        (risk_msgs.KillSwitchGatewayAck, docs.ADMIN_KILL_GATEWAY),
        (risk_msgs.KillSwitchGlobalAck, docs.ADMIN_KILL_GLOBAL),
    ],
)
def test_engine_reply_examples_match_the_wire_spec(
    message: Any, payload: dict[str, Any]
) -> None:
    parsed = message.from_dict(payload)
    parsed.validate()
    # Nothing in the example was silently dropped by the parser.
    assert set(payload) <= set(parsed.to_dict()) | {"gateway_id"}
