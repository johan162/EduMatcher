"""Position and order queries answer about any configured gateway
(For-Later L030, L028; WP-FL06).

L030: the engine answered an empty list when the gateway asked about was not
connected, so an ADMIN saw a logged-off trader with resting GTC orders and a
position as flat with no orders; an id no participant has looked the same.
The replies now carry the data for any configured gateway and a ``status``:
``OK``, ``NOT_CONNECTED`` or ``UNKNOWN_GATEWAY``.

L028 (verified not a defect): every configured symbol has a book from
start-up, so a book request for one without orders is answered.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.order import TIF, OrderType, Side
from tests.engine_harness import connect, make_engine, msgs, order_payload


def setup(monkeypatch: Any, tmp_path: Any) -> Any:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._handle_new_order(order_payload(Side.SELL, OrderType.LIMIT, 5, "GW02", price=100.0))  # fmt: skip
    engine._handle_new_order(order_payload(Side.BUY, OrderType.LIMIT, 5, "GW01", price=100.0))  # fmt: skip
    engine._handle_new_order(order_payload(Side.BUY, OrderType.LIMIT, 7, "GW01", price=99.0, tif=TIF.GTC))  # fmt: skip
    return engine, pub


def ask(engine: Any, pub: Any, gw: str) -> tuple[dict[str, Any], dict[str, Any]]:
    engine._handle_position_request({"gateway_id": gw})
    engine._handle_orders_request({"gateway_id": gw})
    return (
        msgs(pub, f"system.position_snapshot.{gw}")[-1],
        msgs(pub, f"order.orders.{gw}")[-1],
    )


def test_a_logged_off_gateway_is_answered_with_its_orders_and_positions(
    monkeypatch, tmp_path
) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    engine._handle_gateway_disconnect({"gateway_id": "GW01"})

    positions, orders = ask(engine, pub, "GW01")

    assert positions["status"] == "NOT_CONNECTED"
    assert [(p["symbol"], p["net_qty"]) for p in positions["positions"]] == [("AAPL", 5)]  # fmt: skip
    assert orders["status"] == "NOT_CONNECTED"
    assert [o["remaining_qty"] for o in orders["orders"]] == [7]


def test_a_connected_gateway_is_ok(monkeypatch, tmp_path) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    positions, orders = ask(engine, pub, "GW01")
    assert positions["status"] == orders["status"] == "OK"
    assert len(orders["orders"]) == 1


def test_a_connected_flat_gateway_is_ok_and_empty(monkeypatch, tmp_path) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    positions, orders = ask(engine, pub, "GW03")
    assert (positions["status"], positions["positions"]) == ("OK", [])
    assert (orders["status"], orders["orders"]) == ("OK", [])


def test_an_id_no_participant_has_is_unknown(monkeypatch, tmp_path) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    positions, orders = ask(engine, pub, "NOPE")
    assert (positions["status"], positions["positions"]) == ("UNKNOWN_GATEWAY", [])
    assert (orders["status"], orders["orders"]) == ("UNKNOWN_GATEWAY", [])
    assert "NOPE" not in engine._sessions


def test_l028_a_configured_symbol_without_orders_is_answered_after_startup(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    engine._load_config()
    engine._handle_book_snapshot_request({"symbol": "MSFT"})
    (book,) = msgs(pub, "book.MSFT")
    assert book["bids"] == [] and book["asks"] == []
