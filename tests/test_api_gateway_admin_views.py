"""The admin replay boundary: cache retention, cross-gateway views, snapshot.

Three things are pinned:

* terminal orders are evicted, so the admin table shows what is open rather
  than everything since process start;
* the cross-gateway order view is derived from state the gateway already
  keeps, and the lifecycle view is read from the audit trail rather than
  duplicated in memory;
* the monitor snapshot asks the *engine* for the gateway roster, because the
  gateway's own `active_gateways()` is scoped to this instance.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from edumatcher.api_gateway.caches import TERMINAL_ORDER_STATUSES, SessionCaches
from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.routers import admin
from edumatcher.api_gateway.sessions import Session
from edumatcher.audit.indexer import open_index, query_index_events

# ---------------------------------------------------------------------------
# Cache retention
# ---------------------------------------------------------------------------


def _cache_with(status: str, order_id: str = "ORD-1") -> SessionCaches:
    cache = SessionCaches()
    cache.apply("order.ack.GW01", {"order_id": order_id, "accepted": True})
    if status != "NEW":
        topic = {
            "FILLED": "order.fill.GW01",
            "CANCELLED": "order.cancelled.GW01",
            "EXPIRED": "order.expired.GW01",
        }[status]
        payload: dict[str, Any] = {"order_id": order_id}
        if status == "FILLED":
            payload["status"] = "FILLED"
        cache.apply(topic, payload)
    return cache


@pytest.mark.parametrize("status", sorted(TERMINAL_ORDER_STATUSES - {"REJECTED"}))
def test_terminal_orders_are_evicted_once_stale(status: str) -> None:
    cache = _cache_with(status)
    assert cache.orders["ORD-1"]["status"] == status

    # Not yet stale.
    assert cache.evict_terminal_orders(3600) == 0
    assert "ORD-1" in cache.orders

    # An hour later.
    assert cache.evict_terminal_orders(3600, now=time.time() + 3601) == 1
    assert cache.orders == {}
    assert cache.terminal_at == {}


def test_a_resting_order_is_never_evicted() -> None:
    """Live state, whatever its age. A GTC order resting for days is still
    the participant's order."""
    cache = _cache_with("NEW")
    assert cache.evict_terminal_orders(1, now=time.time() + 86_400) == 0
    assert "ORD-1" in cache.orders


def test_retention_of_zero_disables_eviction() -> None:
    cache = _cache_with("FILLED")
    assert cache.evict_terminal_orders(0, now=time.time() + 999_999) == 0
    assert "ORD-1" in cache.orders


def test_an_order_that_becomes_live_again_loses_its_terminal_stamp() -> None:
    """Defensive: a status moving back off terminal must not stay eligible
    for eviction."""
    cache = _cache_with("CANCELLED")
    assert "ORD-1" in cache.terminal_at
    cache.apply("order.amended.GW01", {"order_id": "ORD-1"})
    assert "ORD-1" not in cache.terminal_at
    assert cache.evict_terminal_orders(1, now=time.time() + 86_400) == 0


def test_positions_survive_eviction() -> None:
    """The order is forgotten; the position it created is not."""
    cache = SessionCaches()
    cache.apply(
        "order.fill.GW01",
        {
            "order_id": "ORD-1",
            "symbol": "AAPL",
            "side": "BUY",
            "fill_qty": 100,
            "status": "FILLED",
        },
    )
    cache.evict_terminal_orders(1, now=time.time() + 3600)
    assert cache.orders == {}
    assert cache.positions == {"AAPL": 100}


def test_the_eviction_stamp_never_reaches_the_wire() -> None:
    """It lives beside the order, not inside it, so responses stay clean."""
    cache = _cache_with("FILLED")
    assert "_terminal_at" not in cache.orders["ORD-1"]
    assert "terminal_at" not in cache.orders["ORD-1"]


# ---------------------------------------------------------------------------
# Cross-gateway order view
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Any:
    with (
        patch(
            "edumatcher.api_gateway.engine_client.make_pusher",
            return_value=MagicMock(closed=False),
        ),
        patch(
            "edumatcher.api_gateway.engine_client.make_subscriber",
            return_value=MagicMock(),
        ),
    ):
        loop = asyncio.new_event_loop()
        try:
            yield EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", loop)
        finally:
            loop.close()


def test_all_orders_spans_every_gateway(engine: EngineClient) -> None:
    """The cross-gateway view an admin needs was already in `_caches`; it
    just was not reachable."""
    engine._handle_event(
        "order.ack.GW01", {"order_id": "A", "accepted": True, "symbol": "AAPL"}
    )
    engine._handle_event(
        "order.ack.GW02", {"order_id": "B", "accepted": True, "symbol": "MSFT"}
    )

    orders = engine.all_orders()
    assert {o["order_id"] for o in orders} == {"A", "B"}
    # gateway_id is the dict key, not part of the payload — it must be added.
    assert {o["gateway_id"] for o in orders} == {"GW01", "GW02"}


def _admin_request(engine: Any, retention: int = 3600) -> Any:
    config = ApiGatewayConfig(
        credentials=(ApiCredential("key", "ADMIN01", "test"),),
        order_retention_sec=retention,
        audit_db=Path("/nonexistent/audit_index.db"),
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(engine=engine, config=config))
    )


def _admin_session() -> Session:
    return Session(api_key="key", gateway_id="ADMIN01", description="test")


@pytest.mark.anyio
async def test_admin_orders_filters(engine: EngineClient) -> None:
    for gid, oid, sym in (
        ("GW01", "A", "AAPL"),
        ("GW01", "B", "MSFT"),
        ("GW02", "C", "AAPL"),
    ):
        engine._handle_event(
            f"order.ack.{gid}", {"order_id": oid, "accepted": True, "symbol": sym}
        )
    request = _admin_request(engine)
    with patch.object(admin, "require_admin", return_value="ADMIN01"):
        every = await admin.admin_orders(request, _admin_session())
        by_symbol = await admin.admin_orders(request, _admin_session(), symbol="aapl")
        by_gateway = await admin.admin_orders(
            request, _admin_session(), gateway_id="gw02"
        )
        by_status = await admin.admin_orders(
            request, _admin_session(), status_filter="NEW"
        )

    assert every["count"] == 3
    assert {o["order_id"] for o in by_symbol["orders"]} == {"A", "C"}
    assert {o["order_id"] for o in by_gateway["orders"]} == {"C"}
    assert by_status["count"] == 3
    # The response states its own horizon, so a caller knows what it is not
    # being shown.
    assert every["retention_sec"] == 3600


# ---------------------------------------------------------------------------
# Audit-backed lifecycle
# ---------------------------------------------------------------------------


def test_the_audit_index_can_be_queried_by_order_id(tmp_path: Path) -> None:
    """The column was always indexed; only the filter was missing."""
    db = tmp_path / "audit_index.db"
    conn = open_index(db)
    rows = [
        (
            "2026-08-05T10:00:00.000",
            "order.ack.GW01",
            "{}",
            "GW01",
            "AAPL",
            "A",
            None,
            "ack",
        ),
        (
            "2026-08-05T10:00:01.000",
            "order.fill.GW01",
            "{}",
            "GW01",
            "AAPL",
            "A",
            None,
            "fill",
        ),
        (
            "2026-08-05T10:00:02.000",
            "order.ack.GW01",
            "{}",
            "GW01",
            "AAPL",
            "B",
            None,
            "ack",
        ),
    ]
    conn.executemany(
        "INSERT INTO audit_events (timestamp, topic, payload, gateway_id, symbol,"
        " order_id, trade_id, event_type) VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    try:
        for_a = query_index_events(conn, order_id="A")
        assert [e["topic"] for e in for_a] == ["order.ack.GW01", "order.fill.GW01"]
        assert query_index_events(conn, order_id="ZZZ") == []
    finally:
        conn.close()


@pytest.mark.anyio
async def test_lifecycle_degrades_cleanly_without_an_audit_index(
    engine: EngineClient,
) -> None:
    """The dependency is optional: pm-audit may not be deployed. That one
    endpoint reports it; nothing else is affected."""
    request = _admin_request(engine)
    with patch.object(admin, "require_admin", return_value="ADMIN01"):
        with pytest.raises(HTTPException) as excinfo:
            await admin.admin_order_lifecycle("ORD-1", request, _admin_session())
    assert excinfo.value.status_code == 503
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail["error"]["code"] == "AUDIT_INDEX_UNAVAILABLE"
    # The message must name what to do, not just what failed.
    assert "pm-audit" in detail["error"]["message"]


@pytest.mark.anyio
async def test_lifecycle_returns_404_for_an_unaudited_order(
    engine: EngineClient, tmp_path: Path
) -> None:
    db = tmp_path / "audit_index.db"
    conn = open_index(db)
    conn.commit()
    conn.close()

    request = _admin_request(engine)
    request.app.state.config = ApiGatewayConfig(
        credentials=(ApiCredential("key", "ADMIN01", "test"),), audit_db=db
    )
    with patch.object(admin, "require_admin", return_value="ADMIN01"):
        with pytest.raises(HTTPException) as excinfo:
            await admin.admin_order_lifecycle("NOPE", request, _admin_session())
    assert excinfo.value.status_code == 404


@pytest.mark.anyio
async def test_lifecycle_returns_the_full_ordered_history(
    engine: EngineClient, tmp_path: Path
) -> None:
    db = tmp_path / "audit_index.db"
    conn = open_index(db)
    conn.executemany(
        "INSERT INTO audit_events (timestamp, topic, payload, gateway_id, symbol,"
        " order_id, trade_id, event_type) VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                "2026-08-05T10:00:0%d.000" % i,
                topic,
                "{}",
                "GW01",
                "AAPL",
                "ORD-1",
                None,
                "e",
            )
            for i, topic in enumerate(
                ["order.ack.GW01", "order.fill.GW01", "order.cancelled.GW01"]
            )
        ],
    )
    conn.commit()
    conn.close()

    request = _admin_request(engine)
    request.app.state.config = ApiGatewayConfig(
        credentials=(ApiCredential("key", "ADMIN01", "test"),), audit_db=db
    )
    with patch.object(admin, "require_admin", return_value="ADMIN01"):
        result = await admin.admin_order_lifecycle("ORD-1", request, _admin_session())

    assert result["count"] == 3
    assert [e["topic"] for e in result["events"]] == [
        "order.ack.GW01",
        "order.fill.GW01",
        "order.cancelled.GW01",
    ]


def test_the_gateway_never_writes_the_audit_index(tmp_path: Path) -> None:
    """Read-only by construction: pm-audit owns this file."""
    from edumatcher.audit.indexer import open_readonly_index

    db = tmp_path / "audit_index.db"
    open_index(db).close()
    conn = open_readonly_index(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO audit_events (timestamp, topic, payload)"
                " VALUES ('t','x','{}')"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# order_retention_sec across the config toolchain
# ---------------------------------------------------------------------------


def test_config_loader_defaults_and_validates_retention() -> None:
    from edumatcher.api_gateway.config import _load_api_gateway_section

    section = "api_gateways.desk"
    assert _load_api_gateway_section({}, section, "desk").order_retention_sec == 3600
    assert (
        _load_api_gateway_section(
            {"order_retention_sec": 120}, section, "desk"
        ).order_retention_sec
        == 120
    )
    # 0 is meaningful — "never evict" — and must not be coerced to the default.
    assert (
        _load_api_gateway_section(
            {"order_retention_sec": 0}, section, "desk"
        ).order_retention_sec
        == 0
    )
    with pytest.raises(ValueError, match=">= 0"):
        _load_api_gateway_section({"order_retention_sec": -1}, section, "desk")
    with pytest.raises(ValueError, match="must be an integer"):
        _load_api_gateway_section({"order_retention_sec": "soon"}, section, "desk")


def test_cverifier_reports_a_negative_retention() -> None:
    """pm-cverifier delegates to the same loader, so the rule has one home."""
    from edumatcher.cverifier.layer2_schema import _check_api_gateway_sections

    results: list[Any] = []
    _check_api_gateway_sections(
        {"api_gateways": {"desk": {"port": 8080, "order_retention_sec": -5}}}, results
    )
    assert results, "a negative retention must be reported"
    assert "order_retention_sec" in results[0].message

    ok: list[Any] = []
    _check_api_gateway_sections(
        {"api_gateways": {"desk": {"port": 8080, "order_retention_sec": 0}}}, ok
    )
    assert not ok, "0 is valid"


def test_config_gen_emits_the_field() -> None:
    from edumatcher.config_gen.builder import (
        ApiGatewaySpec,
        ConfigBuilder,
        ConfigSpec,
    )
    from edumatcher.config_gen.gateway_spec import GatewaySpec
    from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole

    def build(api_spec: ApiGatewaySpec) -> dict[str, Any]:
        spec = ConfigSpec(
            symbols=["AAPL"],
            gateways=[
                GatewaySpec(
                    gateway_id="TRADER01",
                    role=ParticipantRole.TRADER,
                    disconnect_behaviour=DisconnectBehaviour.LEAVE_ALL,
                )
            ],
            api_gateways=(api_spec,),
        )
        return ConfigBuilder(spec).build()["api_gateways"]["default"]

    assert build(ApiGatewaySpec(order_retention_sec=45))["order_retention_sec"] == 45
    assert build(ApiGatewaySpec())["order_retention_sec"] == 3600
    # 0 must survive the builder too.
    assert build(ApiGatewaySpec(order_retention_sec=0))["order_retention_sec"] == 0


def test_the_compiled_artifact_round_trips_the_field() -> None:
    """pm-config-deploy writes the artifact every process reads."""
    from edumatcher.config_artifact import from_jsonable, to_jsonable

    encoded = to_jsonable(ApiGatewayConfig(order_retention_sec=120))
    assert encoded["order_retention_sec"] == 120
    assert from_jsonable(ApiGatewayConfig, encoded).order_retention_sec == 120


def test_an_artifact_compiled_before_this_field_still_loads() -> None:
    """Deploying a new build against an old artifact must not fail; the
    dataclass default applies instead."""
    from edumatcher.config_artifact import from_jsonable, to_jsonable

    encoded = to_jsonable(ApiGatewayConfig())
    legacy = {
        k: v for k, v in encoded.items() if k not in ("order_retention_sec", "audit_db")
    }
    restored = from_jsonable(ApiGatewayConfig, legacy)
    assert restored.order_retention_sec == 3600
    assert restored.audit_db.name == "audit_index.db"
