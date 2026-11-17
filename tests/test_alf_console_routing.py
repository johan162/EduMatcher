"""pm-alf-console handles only its own gateway's events (review WP-ACN01, H1).

A ZeroMQ SUBSCRIBE is a byte prefix and gateway-scoped topics have no
terminator, so a ``TRADER1`` console's subscription to ``order.fill.TRADER1``
also receives ``order.fill.TRADER10``. Those events must be neither printed
nor booked into ``POS`` and ``ORDERS``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest

from edumatcher.models.generated.index import (
    TOPIC_INDEX_UPDATE,
    topic_index_error,
    topic_index_history,
)
from edumatcher.models.generated.order import (
    topic_order_ack,
    topic_order_amended,
    topic_order_cancelled,
    topic_order_expired,
    topic_orders,
)
from edumatcher.models.generated.quote import (
    topic_quote_ack,
    topic_quote_cancel_ack,
    topic_quote_status,
)
from edumatcher.models.generated.risk import topic_kill_switch_ack
from edumatcher.models.generated.structure import (
    topic_combo_ack,
    topic_combo_cancel_ack,
    topic_combo_status,
    topic_oco_ack,
    topic_oco_cancel_ack,
    topic_oco_cancelled,
)
from edumatcher.models.generated.system import (
    topic_quote_bootstrap,
    topic_session_status,
    topic_symbols,
)
from edumatcher.models.message import make_fill_msg
from tests.alf_console_harness import console_harness  # noqa: F401
from tests.test_alf_console_quote_ack import _make_gateway

_ORDER = {"symbol": "AAPL", "side": "BUY", "quantity": 100, "order_type": "LIMIT"}


def _fill(gateway_id: str, order_id: str) -> list[bytes]:
    return make_fill_msg(gateway_id, order_id, 100, 150.0, 0, "FILLED", order=_ORDER)


# ---------------------------------------------------------------------------
# 1 + 3: real PUB/SUB, engine builder
# ---------------------------------------------------------------------------


def test_fill_for_a_gateway_id_with_this_one_as_prefix_is_ignored(
    console_harness: Any,  # noqa: F811
) -> None:
    h = console_harness("TRADER1")
    h.gw.order_cache["known"] = {"id": "known", "status": "NEW"}

    h.pub.send_multipart(_fill("TRADER10", "ord-of-trader10"))
    h.sync()

    assert h.gw._positions == {}
    assert set(h.gw.order_cache) == {"known"}
    assert not [line for line in h.lines if "FILL" in line]


def test_own_fill_is_printed_and_booked(
    console_harness: Any,  # noqa: F811
) -> None:
    h = console_harness("TRADER1")

    h.pub.send_multipart(_fill("TRADER1", "ord-own"))
    h.sync()

    assert h.gw._positions["AAPL"]["net_qty"] == 100
    assert [line for line in h.lines if "FILL" in line and "ord-own" in line]


# ---------------------------------------------------------------------------
# 2: every other gateway-scoped family, _handle_event direct
# ---------------------------------------------------------------------------

_OTHER = "TRADER10"

_FOREIGN_EVENTS: list[tuple[Callable[[str], str], dict[str, Any]]] = [
    (
        topic_order_ack,
        {"order_id": "o1", "accepted": True, "symbol": "AAPL", "qty": 10},
    ),
    (topic_order_cancelled, {"order_id": "o1"}),
    (topic_order_amended, {"order_id": "o1", "price": 1.0, "qty": 5}),
    (topic_order_expired, {"order_id": "o1"}),
    (
        topic_orders,
        {"orders": [{"id": "o2", "symbol": "AAPL", "side": "BUY", "quantity": 5}]},
    ),
    (topic_combo_ack, {"combo_id": "c1", "accepted": True}),
    (topic_combo_status, {"combo_id": "c1", "status": "FAILED"}),
    (topic_oco_ack, {"oco_id": "x1", "accepted": True}),
    (topic_oco_cancelled, {"oco_id": "x1", "cancelled_order_id": "o1"}),
    (topic_quote_ack, {"quote_id": "q1", "accepted": True, "bid_order_id": "b"}),
    (topic_quote_status, {"quote_id": "q1", "status": "CANCELLED"}),
    (topic_combo_cancel_ack, {"combo_id": "c1", "accepted": True}),
    (topic_oco_cancel_ack, {"oco_id": "x1", "accepted": True}),
    (topic_quote_cancel_ack, {"symbol": "AAPL", "accepted": True}),
    (topic_kill_switch_ack, {"accepted": True, "cancelled_orders": 3}),
    (topic_symbols, {"symbols": [{"symbol": "MSFT"}]}),
    (topic_quote_bootstrap, {"quotes": []}),
    (topic_session_status, {"state": "CLOSED"}),
    (topic_index_history, {"records": []}),
    (topic_index_error, {"reason": "nope"}),
]


@pytest.mark.parametrize(
    ("topic_fn", "payload"),
    _FOREIGN_EVENTS,
    ids=[fn.__name__ for fn, _ in _FOREIGN_EVENTS],
)
def test_other_gateways_event_is_neither_printed_nor_cached(
    topic_fn: Callable[[str], str], payload: dict[str, Any]
) -> None:
    gw, _push = _make_gateway("TRADER1")
    gw.order_cache["o1"] = {"id": "o1", "status": "NEW", "tif": "DAY"}
    gw._known_symbols.append("AAPL")
    before = {k: dict(v) for k, v in gw.order_cache.items()}

    with (
        patch("edumatcher.alf_console.main.console.print") as mock_print,
        patch("edumatcher.alf_console.main.print_symbols_table") as mock_symbols,
        patch("edumatcher.alf_console.main.print_session_status") as mock_session,
        patch("edumatcher.alf_console.main.print_quote_bootstrap") as mock_qboot,
        patch("edumatcher.alf_console.main.print_index_history") as mock_history,
    ):
        gw._handle_event(topic_fn(_OTHER), payload)

    for mock in (mock_print, mock_symbols, mock_session, mock_qboot, mock_history):
        mock.assert_not_called()
    assert gw.order_cache == before
    assert gw.quote_leg_cache == {}
    assert gw._known_symbols == ["AAPL"]


# ---------------------------------------------------------------------------
# 4: broadcast topics still reach every console, unchanged
# ---------------------------------------------------------------------------


def test_trade_executed_still_updates_last_price() -> None:
    gw, _push = _make_gateway("TRADER1")
    gw._handle_event("trade.executed", {"symbol": "AAPL", "price": 151.25})
    assert gw._last_prices == {"AAPL": 151.25}


def test_index_update_still_cached() -> None:
    gw, _push = _make_gateway("TRADER1")
    gw._handle_event(TOPIC_INDEX_UPDATE, {"index_id": "edx", "level": 1000.0})
    assert gw._last_index_update == {"index_id": "edx", "level": 1000.0}
    assert gw._default_index_id == "EDX"
