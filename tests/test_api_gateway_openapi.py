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
    assert len(operations) > 50  # the exact set: test_api_gateway_layout.py
    for method, path, op in operations:
        where = f"{method} {path}"
        assert op.get("summary") and op["summary"] != op["operationId"], where
        _, response = _success(op)
        for value in _example_values(response):
            assert isinstance(value, dict) and value, where
            assert "additionalProp1" not in value, where


def test_every_endpoint_documents_the_error_envelope(spec: dict[str, Any]) -> None:
    """Which codes each operation lists is test_api_gateway_error_codes's job;
    here: every error response is the envelope, and the two universal ones
    (an unknown key, a gateway bug) are on every operation."""
    for method, path, op in _operations(spec):
        for status_code, response in op["responses"].items():
            if status_code.startswith("2") or status_code == "422":
                continue
            content = response["content"]["application/json"]
            assert content["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }, f"{method} {path} {status_code}"
        for status_code, code in (("401", "AUTH"), ("500", "INTERNAL_ERROR")):
            examples = op["responses"][status_code]["content"]["application/json"]
            assert code in examples["examples"], f"{method} {path} lacks {code}"


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
    op = spec["paths"]["/api/v1/admin/orders/{order_id}/audit"]["get"]
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
        "SymbolHaltRequest",
        "AdminNoteRequest",
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
        (system_msgs.QuoteBootstrap, docs.QUOTE_BOOTSTRAP),
        (system_msgs.QuoteLegs, docs.QUOTE_LEGS),
        (system_msgs.RiskState, docs.ADMIN_RISK_STATE),
        (system_msgs.Gateways, docs.ADMIN_GATEWAYS),
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


def test_every_success_example_is_exactly_its_response_model() -> None:
    """WP-API04: a documented example must be a reply the route can send.

    Each 2xx example is validated against the operation's response model and
    serialised back the way the route serialises (``exclude_unset``); the
    result must equal the example -- nothing missing, nothing dropped.
    """
    from fastapi.routing import APIRoute

    from edumatcher.api_gateway.routers import (
        admin,
        bootstrap,
        history,
        orders,
        reference,
    )

    failures: list[str] = []
    for module in (orders, reference, history, admin, bootstrap):
        for route in module.router.routes:
            if not isinstance(route, APIRoute) or route.response_model is None:
                continue
            where = f"{sorted(route.methods or ())} {route.path}"
            for code, response in (route.responses or {}).items():
                if not str(code).startswith("2"):
                    continue
                media = response.get("content", {}).get("application/json", {})
                values = [media["example"]] if "example" in media else []
                values += [e["value"] for e in media.get("examples", {}).values()]
                for value in values:
                    try:
                        dumped = route.response_model.model_validate(value).model_dump(
                            mode="json", exclude_unset=True
                        )
                    except Exception as exc:  # noqa: BLE001 - reported below
                        failures.append(f"{where}: {str(exc).splitlines()[0]}")
                        continue
                    if dumped != value:
                        failures.append(f"{where}: example has undeclared fields")
    assert failures == [], "\n".join(failures)


def test_every_parameter_is_described(spec: dict[str, Any]) -> None:
    """S4: a generated SDK turns these into doc comments; none may be blank."""
    missing = [
        f"{method} {path} {param['name']}"
        for method, path, op in _operations(spec)
        for param in op.get("parameters", [])
        if not (param.get("description") or param.get("schema", {}).get("description"))
    ]
    assert missing == []


def test_descriptions_carry_no_internal_references(spec: dict[str, Any]) -> None:
    """DOC3: review ids, private names and transport internals stay in code
    comments, not in what a client reads."""
    import re

    internal = re.compile(
        r"\bAR-\d|_caches|_gateway_positions|SessionCaches|\bZMQ\b|design section"
    )
    leaks = [
        f"{method} {path}: {sorted(set(internal.findall(op.get('description', ''))))}"
        for method, path, op in _operations(spec)
        if internal.search(op.get("description", ""))
    ]
    assert leaks == []
