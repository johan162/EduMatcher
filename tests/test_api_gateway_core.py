from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.main import create_app
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.schemas import OrderRequest, QuoteRequest
from edumatcher.api_gateway.translate import build_order, build_quote_payload
from edumatcher.models.order import OrderType
from edumatcher.stats.query import query_order_events, query_order_lifecycle


def test_swagger_can_be_disabled() -> None:
    app = create_app(ApiGatewayConfig(swagger_enabled=False))
    assert app.docs_url is None
    assert app.openapi_url is None


def test_order_request_validation_requires_limit_price() -> None:
    with pytest.raises(ValueError, match="requires price"):
        OrderRequest(symbol="aapl", side="BUY", order_type="LIMIT", quantity=10)


def test_build_order_converts_display_price_to_ticks() -> None:
    request = OrderRequest(
        symbol="AAPL",
        side="BUY",
        order_type="LIMIT",
        quantity=10,
        price=150.25,
    )
    order = build_order(request, "GW01")
    assert order.symbol == "AAPL"
    assert order.order_type == OrderType.LIMIT
    assert order.price == 15025
    assert order.gateway_id == "GW01"


def test_quote_payload_uses_wire_values() -> None:
    request = QuoteRequest(
        symbol="aapl",
        bid_price=150.0,
        bid_qty=100,
        ask_price=150.1,
        ask_qty=100,
    )
    payload = build_quote_payload(request, "GW01")
    assert payload["symbol"] == "AAPL"
    assert payload["tif"] == "DAY"


def test_rate_limiter_exhausts_burst() -> None:
    limiter = RateLimiter(writes_per_second=1, burst=2)
    assert limiter.allow("key") is True
    assert limiter.allow("key") is True
    assert limiter.allow("key") is False


def test_query_order_history(tmp_path: Path) -> None:
    db_path = tmp_path / "stats.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
CREATE TABLE order_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    order_id TEXT NOT NULL,
    gateway_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT,
    order_type TEXT,
    tif TEXT,
    price REAL,
    quantity INTEGER,
    remaining_qty INTEGER,
    status TEXT,
    fill_price REAL,
    fill_qty INTEGER,
    trade_id TEXT,
    reason TEXT,
    client_order_id TEXT,
    combo_parent_id TEXT,
    oco_group_id TEXT,
    priority_reset INTEGER
);
INSERT INTO order_events
    (ts, event_type, order_id, gateway_id, symbol, side, order_type, tif)
VALUES
    ('2026-06-24T10:00:00', 'ACK', 'ORD1', 'GW01', 'AAPL', 'BUY', 'LIMIT', 'DAY'),
    ('2026-06-24T10:00:01', 'FILL', 'ORD1', 'GW01', 'AAPL', 'BUY', 'LIMIT', 'DAY'),
    ('2026-06-24T10:00:02', 'ACK', 'ORD2', 'GW02', 'MSFT', 'BUY', 'LIMIT', 'DAY');
""")
    events = query_order_events(
        conn,
        gateway_id="GW01",
        symbol="AAPL",
        event_type=None,
        date_value="2026-06-24",
        from_ts=None,
        to_ts=None,
        limit=10,
    )
    lifecycle = query_order_lifecycle(conn, gateway_id="GW01", order_id="ORD1")
    assert [event["event_type"] for event in events] == ["ACK", "FILL"]
    assert len(lifecycle) == 2
    conn.close()
