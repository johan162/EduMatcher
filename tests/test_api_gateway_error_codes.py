"""WP-API14: each operation's documented error codes are exactly what it can raise.

The contract (``spec/rest/openapi.json``) lists per operation the ``error.code``
values a client must handle. Too many and clients write dead branches (every
route used to claim ``ENGINE_TIMEOUT``); too few and they meet codes nobody
told them about (``STATS_DB``, ``READ_ONLY``, ``ENGINE_UNAVAILABLE`` were
missing on most routes). Both directions are checked against what the code
can raise, found by ``tests/api_gateway_error_scan.py``.
"""

from __future__ import annotations

import ast
from typing import Any

import pytest
from fastapi.routing import APIRoute

from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.errors import ERROR_CODES
from edumatcher.api_gateway.main import create_app
from edumatcher.api_gateway.routers import admin, bootstrap, history, orders, reference
from tests.api_gateway_error_scan import ROOT, route_codes

_ROUTERS = (orders, reference, history, admin, bootstrap)


def _operations() -> list[tuple[str, str, Any, dict[str, Any]]]:
    document = create_app(ApiGatewayConfig()).openapi()
    found = []
    for module in _ROUTERS:
        for route in module.router.routes:
            if not isinstance(route, APIRoute) or not route.include_in_schema:
                continue
            for method in sorted(route.methods or ()):
                operation = document["paths"][route.path][method.lower()]
                found.append((method, route.path, route.endpoint, operation))
    return found


def _declared(operation: dict[str, Any]) -> set[str]:
    codes = set()
    for status_code, response in operation["responses"].items():
        if status_code.startswith("2"):
            continue
        for example in response["content"]["application/json"]["examples"].values():
            codes.add(example["value"]["error"]["code"])
    return codes


_OPERATIONS = _operations()


@pytest.mark.parametrize(
    ("method", "path", "endpoint", "operation"),
    _OPERATIONS,
    ids=[f"{m} {p}" for m, p, _, _ in _OPERATIONS],
)
def test_declared_codes_are_exactly_the_reachable_ones(
    method: str, path: str, endpoint: Any, operation: dict[str, Any]
) -> None:
    takes_input = bool(operation.get("parameters") or operation.get("requestBody"))
    reachable = route_codes(endpoint.__module__, endpoint.__name__, takes_input)
    declared = _declared(operation)
    assert declared == reachable, (
        f"{method} {path}: declared but unreachable {sorted(declared - reachable)}, "
        f"reachable but undeclared {sorted(reachable - declared)}"
    )


def test_each_error_status_is_the_registrys() -> None:
    for method, path, _, operation in _OPERATIONS:
        for status_code, response in operation["responses"].items():
            if status_code.startswith("2"):
                continue
            for example in response["content"]["application/json"]["examples"].values():
                code = example["value"]["error"]["code"]
                assert ERROR_CODES[code].status == int(status_code), (method, path)


def test_the_scan_sees_what_it_must() -> None:
    """Controls: an empty or over-eager scan would pass the equality test
    against equally wrong declarations, so pin a few known facts."""
    by_route = {(m, p): _declared(o) for m, p, _, o in _OPERATIONS}
    assert "STATS_DB" in by_route[("GET", "/api/v1/history/trades")]
    assert "REPLACE_REJECTED" in by_route[("POST", "/api/v1/orders/{order_id}/replace")]
    assert "ROLE_DENIED" in by_route[("GET", "/api/v1/admin/gateways")]
    # DELETE /oco never waits for the engine, so it cannot time out.
    assert "ENGINE_TIMEOUT" not in by_route[("DELETE", "/api/v1/oco/{oco_id}")]
    # Open to any key.
    assert "READ_ONLY" not in by_route[("GET", "/api/v1/session")]


def test_every_code_the_package_raises_is_registered() -> None:
    """A new ``{"code": "X"}`` anywhere in the gateway must be added to the
    registry, or the scan (which only knows registered codes) cannot see it."""
    unregistered = []
    for path in sorted(ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "code"
                    and isinstance(value, ast.Constant)
                    and value.value not in ERROR_CODES
                ):
                    unregistered.append(f"{path.name}: {value.value!r}")
    assert unregistered == []
