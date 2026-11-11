"""CG4: the release-1.0 clearing contract, as a browser client will consume it.

The routes are registered under ``/api/v1/clearing``, read-only, each with a
response model and its authorization answers documented; the role matrix is
enforced by the server; the two money units (clearing ticks, EOD minor units)
are separate and recognisable from field names alone; every list is bounded;
the existing ``/positions`` enrichment is unchanged; and the user/operator
documentation names every route and configuration key the code serves.
"""

from __future__ import annotations

import re
from contextlib import closing
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from edumatcher.api_gateway import contract
from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.main import create_app
from edumatcher.api_gateway.responses import PositionRow
from edumatcher.api_gateway.routers import clearing as clearing_router
from edumatcher.clearing.query import (
    open_readonly_connection,
    query_period_realized_pnl,
)
from tests.api_gateway_harness import call
from tests.clearing_api_fixture import (
    ADMIN_KEY,
    DAY1,
    DAY2,
    MM_KEY,
    READ_ONLY_KEY,
    SILENT_HEALTH_ADDR,
    TRADER_KEY,
    Venue,
    build_venue,
    make_clearing_app,
)

ROOT = Path(__file__).resolve().parents[1]
BOOKS = ROOT / "docs" / "books"
PREFIX = "/api/v1/clearing"

#: route -> expected answer per role: 200, or the 403 code.
MATRIX: dict[str, dict[str, int | str]] = {
    "/summary": {"ADMIN": 200, "TRADER": "ROLE_DENIED", "MM": "ROLE_DENIED"},
    "/participants": {"ADMIN": 200, "TRADER": "ROLE_DENIED", "MM": "ROLE_DENIED"},
    "/participants/{gateway_id}": {"ADMIN": 200, "TRADER": 200, "MM": "SCOPE_DENIED"},
    "/positions": {"ADMIN": 200, "TRADER": 200, "MM": 200},
    "/exposure": {"ADMIN": 200, "TRADER": 200, "MM": 200},
    "/trades": {"ADMIN": 200, "TRADER": 200, "MM": 200},
    "/daily": {"ADMIN": 200, "TRADER": 200, "MM": 200},
    "/close-snapshots": {"ADMIN": 200, "TRADER": 200, "MM": 200},
    "/symbols": {"ADMIN": 200, "TRADER": "ROLE_DENIED", "MM": "ROLE_DENIED"},
    "/session-events": {"ADMIN": 200, "TRADER": "ROLE_DENIED", "MM": "ROLE_DENIED"},
    "/gateway-sessions": {"ADMIN": 200, "TRADER": 200, "MM": 200},
    "/reconciliation": {"ADMIN": 200, "TRADER": "ROLE_DENIED", "MM": "ROLE_DENIED"},
    "/health": {"ADMIN": 200, "TRADER": "ROLE_DENIED", "MM": "ROLE_DENIED"},
    "/settlements": {"ADMIN": 200, "TRADER": 200, "MM": 200},
    "/balances": {"ADMIN": 200, "TRADER": 200, "MM": 200},
}
_KEYS = {"ADMIN": ADMIN_KEY, "TRADER": TRADER_KEY, "MM": MM_KEY}
#: Concrete requests for the templated / range-requiring routes.
_REQUEST = {
    "/participants/{gateway_id}": "/participants/TRADER01",
    "/reconciliation": f"/reconciliation?from={DAY1}&to={DAY2}",
}
#: Lists whose size grows with time or venue size: each needs a bounded limit.
_LISTS = {
    "/participants",
    "/positions",
    "/exposure",
    "/trades",
    "/daily",
    "/close-snapshots",
    "/symbols",
    "/session-events",
    "/gateway-sessions",
    "/reconciliation",
    "/settlements",
}
_UNSUPPORTED = ("margin", "equity", "collateral", "buying_power", "open_interest")


@cache
def _document() -> dict[str, Any]:
    return create_app(ApiGatewayConfig()).openapi()


def _clearing_paths() -> dict[str, dict[str, Any]]:
    return {
        path[len(PREFIX) :]: item
        for path, item in _document()["paths"].items()
        if path.startswith(PREFIX)
    }


def _schema(ref: str) -> dict[str, Any]:
    schema: dict[str, Any] = _document()["components"]["schemas"][ref.split("/")[-1]]
    return schema


def _clearing_schemas() -> dict[str, dict[str, Any]]:
    """Every component schema reachable from a clearing 200 response."""
    found: dict[str, dict[str, Any]] = {}

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.split("/")[-1]
                if name not in found:
                    found[name] = _schema(ref)
                    _walk(found[name])
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    for item in _clearing_paths().values():
        _walk(item["get"]["responses"]["200"])
    return found


@pytest.fixture(scope="module")
def venue(tmp_path_factory: pytest.TempPathFactory) -> Venue:
    return build_venue(tmp_path_factory.mktemp("venue"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _silent_clearing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clearing_router, "_HEALTH_ADDR", SILENT_HEALTH_ADDR)
    monkeypatch.setattr(clearing_router, "_HEALTH_TIMEOUT_MS", 50)


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def test_exactly_the_release_routes_are_registered_and_read_only() -> None:
    paths = _clearing_paths()
    assert set(paths) == set(MATRIX)
    for path, item in paths.items():
        assert set(item) == {"get"}, path
        assert item["get"]["tags"] == ["clearing"], path


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_no_clearing_route_accepts_a_write(venue: Venue, method: str) -> None:
    app = make_clearing_app(venue)
    for route in MATRIX:
        path = PREFIX + _REQUEST.get(route, route).split("?")[0]
        status, headers, body = await call(
            app, method, path, authorization=f"Bearer {ADMIN_KEY}"
        )
        assert status == 405, (method, path)
        assert body["error"]["code"] == "METHOD_NOT_ALLOWED"
        assert headers["allow"] == "GET"


def test_each_route_has_a_model_and_documents_its_authorization() -> None:
    for path, item in _clearing_paths().items():
        responses = item["get"]["responses"]
        schema = responses["200"]["content"]["application/json"]["schema"]
        assert "$ref" in schema, path
        assert "401" in responses, path
        refusals = set(responses["403"]["content"]["application/json"]["examples"])
        assert "READ_ONLY" in refusals, path
        expected = {v for v in MATRIX[path].values() if isinstance(v, str)}
        assert expected <= refusals, path
        assert responses["503"] or path == "/health"
        assert item["get"]["description"], path


def test_the_committed_contract_has_the_clearing_routes() -> None:
    import json

    committed = json.loads(contract.OUTPUT.read_text(encoding="utf-8"))
    assert {p for p in committed["paths"] if p.startswith(PREFIX)} == {
        PREFIX + p for p in MATRIX
    }


# ---------------------------------------------------------------------------
# role matrix, through the whole app
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("route", sorted(MATRIX))
async def test_the_role_matrix_is_enforced(venue: Venue, route: str) -> None:
    app = make_clearing_app(venue)
    path = PREFIX + _REQUEST.get(route, route)
    for role, expected in MATRIX[route].items():
        status, _, body = await call(
            app, "GET", path, authorization=f"Bearer {_KEYS[role]}"
        )
        if expected == 200:
            assert status == 200, (route, role, body)
        else:
            assert (status, body["error"]["code"]) == (403, expected), (route, role)
    status, _, body = await call(
        app, "GET", path, authorization=f"Bearer {READ_ONLY_KEY}"
    )
    assert (status, body["error"]["code"]) == (403, "READ_ONLY"), route
    status, _, body = await call(app, "GET", path, authorization=None)
    assert (status, body["error"]["code"]) == (401, "AUTH"), route


# ---------------------------------------------------------------------------
# units, bounds, unsupported claims
# ---------------------------------------------------------------------------


def test_tick_values_have_their_precision_and_display_twin() -> None:
    for name, schema in _clearing_schemas().items():
        props = set(schema.get("properties", {}))
        for prop in props:
            if prop.endswith("_ticks"):
                assert "tick_decimals" in props, (name, prop)
                assert prop[: -len("_ticks")] in props, (name, prop)


def test_minor_units_are_a_separate_unit_with_a_decimal_twin() -> None:
    minor_schemas = 0
    for name, schema in _clearing_schemas().items():
        props = schema.get("properties", {})
        minors = [p for p in props if p.endswith("_minor")]
        if not minors:
            continue
        minor_schemas += 1
        assert "tick_decimals" not in props, name
        assert not any(p.endswith("_ticks") for p in props), name
        for prop in minors:
            assert props[prop]["type"] == "integer", (name, prop)
            twin = props[prop[: -len("_minor")]]
            assert twin["type"] == "string", (name, prop)
    assert minor_schemas == 2  # settlement rows and balance rows


def test_no_schema_claims_an_unsupported_measure() -> None:
    for name, schema in _clearing_schemas().items():
        for prop in schema.get("properties", {}):
            assert not any(word in prop for word in _UNSUPPORTED), (name, prop)


def test_every_list_is_bounded() -> None:
    for path, item in _clearing_paths().items():
        params = {p["name"]: p for p in item["get"].get("parameters", [])}
        if path not in _LISTS:
            assert "limit" not in params, path
            continue
        limit = params["limit"]["schema"]
        assert limit["maximum"] == 5000 and limit["minimum"] == 1, path
        assert 1 <= limit["default"] <= 1000, path


def test_the_reconciliation_range_is_required() -> None:
    params = {
        p["name"]: p for p in _clearing_paths()["/reconciliation"]["get"]["parameters"]
    }
    assert params["from"]["required"] and params["to"]["required"]


def test_the_limits_users_must_know_are_in_the_contract() -> None:
    tags = {t["name"]: t["description"] for t in _document()["tags"]}
    for phrase in ("flush", "retention", "minor units", "SCOPE_DENIED"):
        assert phrase in tags["clearing"], phrase
    describe = {
        p: " ".join(i["get"]["description"].split())
        for p, i in _clearing_paths().items()
    }
    assert "retention" in describe["/trades"]
    assert "observed" in describe["/session-events"]
    assert "not a verified complete history" in describe["/reconciliation"]
    assert "not margin" in describe["/settlements"]
    assert "derived" in describe["/balances"]
    assert "does not prove" in describe["/health"]


# ---------------------------------------------------------------------------
# /positions is unchanged
# ---------------------------------------------------------------------------


def test_the_positions_row_is_unchanged() -> None:
    assert list(PositionRow.model_fields) == [
        "symbol",
        "net_qty",
        "avg_cost",
        "last_price",
        "market_value",
        "unrealized_pnl",
        "realized_pnl_session",
        "realized_pnl_mtd",
        "realized_pnl_ytd",
    ]


def test_the_positions_enrichment_reads_a_real_ledger(venue: Venue) -> None:
    """The query `/positions` uses, against a ledger pm-clearing wrote."""
    now = datetime.fromisoformat(f"{DAY2}T20:00:00+00:00").astimezone(timezone.utc)
    with closing(open_readonly_connection(venue.clearing_db)) as conn:
        periods = query_period_realized_pnl(conn, gateway_id="TRADER01", now=now)
    assert periods["AAPL"].session == pytest.approx(26.6667, abs=1e-4)
    assert periods["EURUSD"].session == pytest.approx(-0.6)
    assert periods["EURUSD"].ytd == pytest.approx(-0.6)


# ---------------------------------------------------------------------------
# documentation agrees with the code
# ---------------------------------------------------------------------------


def _read(*parts: str) -> str:
    return (BOOKS.joinpath(*parts)).read_text(encoding="utf-8")


def test_the_operator_guide_names_every_clearing_route() -> None:
    text = _read("operator-guide", "part-5-gateways", "050-api-gateway.md")
    for path in MATRIX:
        assert f"/clearing{path}" in text, path


def test_the_participant_guide_names_the_self_service_routes() -> None:
    text = _read(
        "participant-guide", "part-5-positions-and-results", "010-positions-and-pnl.md"
    )
    for route, roles in MATRIX.items():
        if roles["TRADER"] == 200:
            assert f"/clearing{route}" in text, route
    assert "SCOPE_DENIED" in text


@pytest.mark.parametrize(
    "parts",
    [
        ("reference-manual", "part-3-configuration", "030-formal-specification.md"),
        (
            "reference-manual",
            "part-3-configuration",
            "010-schema-and-process-blocks.md",
        ),
        ("operator-guide", "part-2-configure", "005-the-configuration-file.md"),
        ("operator-guide", "part-5-gateways", "050-api-gateway.md"),
    ],
)
def test_the_eod_db_key_is_documented(parts: tuple[str, ...]) -> None:
    assert re.search(r"`?eod_db`?", _read(*parts)), parts
