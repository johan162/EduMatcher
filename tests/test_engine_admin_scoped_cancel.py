"""WP-API07: the admin kill switch scoped to one symbol, or to quotes only.

``risk.kill_switch_gateway`` gained an optional ``symbol`` and ``quotes_only``
so an ADMIN can pull one participant's exposure on one instrument, or just
its quote, through the admin message. The alternative, sending the
participant's own ``risk.kill_switch`` / ``quote.cancel`` on its behalf, put
the target's name on the audit trail instead of the admin's and failed
whenever the target was disconnected.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.order import OrderType, Side
from tests.engine_harness import connect, make_engine, msgs, order_payload, submit_quote

ADMIN = "ADM01"
MM = "MM01"


def _engine(monkeypatch: Any, tmp_path: Any) -> tuple[Any, Any]:
    engine, pub_sock = make_engine(
        monkeypatch,
        tmp_path,
        symbols=("AAPL", "MSFT"),
        gateways=(ADMIN, MM),
        mm_gateways=(MM,),
        admin_gateways=(ADMIN,),
    )
    connect(engine, ADMIN, MM)
    # MM: a quote and a resting order on AAPL, a resting order on MSFT.
    submit_quote(engine, MM, bid_price=99.0, ask_price=101.0, symbol="AAPL")
    engine._handle_new_order(
        order_payload(
            gateway_id=MM, symbol="AAPL", side=Side.BUY,
            order_type=OrderType.LIMIT, price=95.0, qty=10,
        )
    )  # fmt: skip
    engine._handle_new_order(
        order_payload(
            gateway_id=MM, symbol="MSFT", side=Side.BUY,
            order_type=OrderType.LIMIT, price=95.0, qty=10,
        )
    )  # fmt: skip
    pub_sock.sent.clear()
    return engine, pub_sock


def _ack(pub_sock: Any) -> dict[str, Any]:
    (ack,) = msgs(pub_sock, f"risk.kill_switch_gateway_ack.{ADMIN}")
    return ack


def _resting(engine: Any, symbol: str) -> list[Any]:
    return list(engine.books[symbol].orders_for_gateway(MM))


def test_a_symbol_scoped_kill_switch_leaves_other_symbols(monkeypatch, tmp_path):
    engine, pub_sock = _engine(monkeypatch, tmp_path)
    engine._handle_kill_switch_gateway(
        {"gateway_id": ADMIN, "target_gateway_id": MM, "symbol": "AAPL", "command_id": "c1"}
    )  # fmt: skip
    ack = _ack(pub_sock)
    assert ack["accepted"] is True and ack["symbol"] == "AAPL"
    assert (ack["cancelled_orders"], ack["cancelled_quotes"]) == (1, 2)
    assert _resting(engine, "AAPL") == []
    assert len(_resting(engine, "MSFT")) == 1


def test_quotes_only_pulls_the_quote_and_keeps_orders(monkeypatch, tmp_path):
    engine, pub_sock = _engine(monkeypatch, tmp_path)
    engine._handle_kill_switch_gateway(
        {"gateway_id": ADMIN, "target_gateway_id": MM, "symbol": "AAPL", "quotes_only": True}
    )  # fmt: skip
    ack = _ack(pub_sock)
    assert ack["accepted"] is True
    assert (ack["cancelled_orders"], ack["cancelled_quotes"]) == (0, 2)
    remaining = _resting(engine, "AAPL")
    assert len(remaining) == 1 and remaining[0].price_ticks == 9500


def test_it_acts_on_a_disconnected_target(monkeypatch, tmp_path):
    """Pulling a disconnected participant's resting orders is exactly when an
    operator needs this; only the ADMIN caller must be connected."""
    engine, pub_sock = _engine(monkeypatch, tmp_path)
    engine._connected_fix_gateways.discard(MM)
    session = engine._sessions.get(MM)
    if session is not None:
        session.connected = False
    engine._handle_kill_switch_gateway(
        {"gateway_id": ADMIN, "target_gateway_id": MM, "symbol": "MSFT"}
    )
    ack = _ack(pub_sock)
    assert ack["accepted"] is True and ack["cancelled_orders"] == 1


def test_the_audit_names_the_admin(monkeypatch, tmp_path):
    engine, pub_sock = _engine(monkeypatch, tmp_path)
    engine._handle_kill_switch_gateway(
        {"gateway_id": ADMIN, "target_gateway_id": MM, "symbol": "AAPL", "quotes_only": True}
    )  # fmt: skip
    (action,) = [
        m
        for m in msgs(pub_sock, f"admin.action.{ADMIN}")
        if m.get("action") == "kill_switch.gateway"
    ]
    assert action["initiator_gateway_id"] == ADMIN
    assert action["scope"]["target_gateway_id"] == MM
    assert (
        action["scope"]["symbol"] == "AAPL" and action["scope"]["quotes_only"] is True
    )
