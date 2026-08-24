from __future__ import annotations

import threading
from typing import Any, Literal
from unittest.mock import patch

import pytest
import zmq

from edumatcher.orders.main import OrderMonitor


class _FakeSub:
    def __init__(self) -> None:
        self.closed = False

    def recv_multipart(self) -> list[bytes]:
        return [b"topic", b"payload"]

    def close(self) -> None:
        self.closed = True


class _PollerOneEventThenStop:
    def __init__(self, monitor: OrderMonitor, sub: Any) -> None:
        self._monitor = monitor
        self._sub = sub
        self._count = 0

    def register(self, _sock: Any, _mask: int) -> None:
        return None

    def poll(self, timeout: int) -> list[tuple[Any, int]]:
        _ = timeout
        self._count += 1
        if self._count == 1:
            return [(self._sub, zmq.POLLIN)]
        self._monitor._running = False
        return []


class _InlineThread:
    def __init__(self, target: Any, daemon: bool = False) -> None:
        _ = daemon
        self._target = target

    def start(self) -> None:
        self._target()

    def join(self, timeout: float | None = None) -> None:
        _ = timeout
        return None


class _FakeLive:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    def __enter__(self) -> "_FakeLive":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        _ = (exc_type, exc, tb)
        return False

    def update(self, _table: Any) -> None:
        return None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_receive_tracks_fill_even_without_prior_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intent: if monitor starts late and misses an ack, fill events must still
    produce a visible row with gateway/status/remaining.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    with (
        patch(
            "edumatcher.orders.main.zmq.Poller",
            return_value=_PollerOneEventThenStop(monitor, fake_sub),
        ),
        patch(
            "edumatcher.orders.main.decode",
            return_value=(
                "order.fill.GW77",
                {
                    "order_id": "ORD-LATE",
                    "remaining_qty": 3,
                    "status": "PARTIAL",
                    "symbol": "AAPL",
                },
            ),
        ),
    ):
        monitor._receive()

    with monitor._lock:
        row = monitor._orders["ORD-LATE"]
        assert row["gateway_id"] == "GW77"
        assert row["status"] == "PARTIAL"
        assert row["remaining"] == 3


def test_subscribes_to_order_and_quote_status_topics() -> None:
    """Intent: pm-orders must see every per-order lifecycle event plus
    quote.status — without quote.status, a quote-driven order.cancelled row
    (order.cancelled's wire schema carries no symbol/side/price, see
    spec/messages/order.yaml) has no way to explain itself in the same view.

    Deliberately NOT the bare "order." prefix: that catch-all also matches
    query REPLIES living under the order.* namespace — order.orders.{gw}
    (pm-admin's ORDERS command) and order.price_level_orders(_request).{gw}
    (the LEVEL command) — neither of which carries an order_id, so each hit
    used to render a row with an empty ID and every other column "?".
    """
    fake_sub = _FakeSub()
    with patch(
        "edumatcher.orders.main.make_subscriber", return_value=fake_sub
    ) as make_sub:
        OrderMonitor(gw_filter=None)

    args, _kwargs = make_sub.call_args
    topics = args[1:]
    assert "order." not in topics
    for prefix in (
        "order.ack.",
        "order.fill.",
        "order.cancelled.",
        "order.expired.",
        "order.amended.",
        "quote.status.",
    ):
        assert prefix in topics
    # And explicitly NOT the query-reply prefixes that leaked in under the
    # old bare "order." subscription.
    assert "order.orders." not in topics
    assert "order.price_level_orders." not in topics
    assert "order.price_level_orders_request" not in topics


def test_accepted_ack_seeds_remaining_from_qty() -> None:
    """Intent: a freshly accepted, unfilled order has a well-known remaining
    quantity — its full quantity — and must not show "?" until the first
    fill touches it.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "order.ack.GW01",
        {
            "gateway_id": "GW01",
            "order_id": "sell-170",
            "accepted": True,
            "symbol": "AAPL",
            "side": "SELL",
            "order_type": "LIMIT",
            "tif": "DAY",
            "qty": 170,
            "price": 150.0,
        },
    )

    with monitor._lock:
        assert monitor._orders["sell-170"]["remaining"] == 170


def test_rejected_ack_does_not_seed_remaining() -> None:
    """Intent: a rejected order never rests, so it shouldn't display a
    remaining quantity as though it were live on the book.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "order.ack.GW01",
        {
            "gateway_id": "GW01",
            "order_id": "rejected-1",
            "accepted": False,
            "reason": "Symbol not configured",
            "qty": 100,
        },
    )

    with monitor._lock:
        assert "remaining" not in monitor._orders["rejected-1"]


def test_fill_after_ack_overrides_seeded_remaining() -> None:
    """Intent: the ack-time seed of remaining=qty must not linger once a
    real fill reports the true remaining quantity.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "order.ack.GW01",
        {
            "gateway_id": "GW01",
            "order_id": "partial-1",
            "accepted": True,
            "symbol": "AAPL",
            "side": "SELL",
            "qty": 170,
            "price": 150.0,
        },
    )
    monitor._handle(
        "order.fill.GW01",
        {
            "order_id": "partial-1",
            "remaining_qty": 70,
            "status": "PARTIAL",
            "fill_price": 150.0,
        },
    )

    with monitor._lock:
        assert monitor._orders["partial-1"]["remaining"] == 70


def test_cancelled_sibling_leg_backfills_symbol_and_side_from_fill() -> None:
    """Intent: a market order crossing a resting MM quote fills one leg and
    cancels the other. If the cancelled leg's own ack was never seen (e.g.
    it was a seeded quote leg resting since before pm-orders started), its
    order.cancelled row (which carries only order_id/quote_id — see
    spec/messages/order.yaml) must still show the correct symbol and the
    inferred opposite side, using what the FILLED leg's own event revealed
    about the shared quote_id, instead of "?" everywhere but ID/Time/Status.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    # The filled BID leg: monitor DOES see this one, since it's a live fill.
    monitor._handle(
        "order.fill.MM01",
        {
            "order_id": "bid-leg-filled",
            "gateway_id": "MM01",
            "symbol": "AAPL",
            "side": "BUY",
            "quote_id": "SEED-MM01-AAPL-1",
            "remaining_qty": 0,
            "status": "FILLED",
            "fill_price": 149.50,
        },
    )
    # The sibling ASK leg: monitor never saw its ack (seeded before startup).
    monitor._handle(
        "order.cancelled.MM01",
        {
            "gateway_id": "MM01",
            "order_id": "ask-leg-cancelled",
            "quote_id": "SEED-MM01-AAPL-1",
        },
    )

    with monitor._lock:
        row = monitor._orders["ask-leg-cancelled"]
        assert row["symbol"] == "AAPL"
        assert row["side"] == "SELL"
        assert row["status"] == "CANCELLED"


def test_cancelled_leg_with_unknown_quote_falls_back_gracefully() -> None:
    """Intent: when NO event for the quote's other leg was ever seen either,
    there's genuinely nothing to backfill from — must not crash, and the
    row still renders (as "?" for the unknowable fields), same as before
    this backfill existed.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "order.cancelled.MM01",
        {"gateway_id": "MM01", "order_id": "orphan-leg", "quote_id": "NEVER-SEEN"},
    )

    with monitor._lock:
        row = monitor._orders["orphan-leg"]
        assert "symbol" not in row
        assert "side" not in row
        assert row["status"] == "CANCELLED"

    # Rendering must not raise even with symbol/side absent.
    from edumatcher.orders.main import _build_rows_table

    _build_rows_table(list(monitor._history))


def test_non_quote_cancel_is_unaffected_by_backfill() -> None:
    """Intent: an ordinary (non-quote) order's cancellation must behave
    exactly as before — no quote_id means no lookup, no side effects.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "order.ack.GW01",
        {
            "gateway_id": "GW01",
            "order_id": "plain-order",
            "accepted": True,
            "symbol": "MSFT",
            "side": "BUY",
            "qty": 50,
            "price": 300.0,
        },
    )
    monitor._handle(
        "order.cancelled.GW01",
        {"gateway_id": "GW01", "order_id": "plain-order"},
    )

    with monitor._lock:
        row = monitor._orders["plain-order"]
        assert row["symbol"] == "MSFT"
        assert row["side"] == "BUY"
        assert row["status"] == "CANCELLED"
        assert "quote_id" not in row


def test_amended_updates_remaining_without_touching_status() -> None:
    """Intent: order.amended carries no symbol/side/order_type/tif (same
    minimal shape as order.cancelled) and must not clobber a status set by
    an earlier ack/fill — it only ever refreshes remaining/price/qty.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "order.ack.GW01",
        {
            "gateway_id": "GW01",
            "order_id": "ORD-AMEND",
            "accepted": True,
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "tif": "DAY",
            "qty": 100,
            "price": 150.0,
        },
    )
    monitor._handle(
        "order.amended.GW01",
        {
            "gateway_id": "GW01",
            "order_id": "ORD-AMEND",
            "qty": 80,
            "remaining_qty": 80,
            "priority_reset": True,
            "price": 149.0,
        },
    )

    with monitor._lock:
        row = monitor._orders["ORD-AMEND"]
        assert row["status"] == "NEW"  # unchanged by the amendment
        assert row["remaining"] == 80
        assert row["symbol"] == "AAPL"  # still present from the earlier ack


def test_quote_status_appends_standalone_row_not_onto_orders_dict() -> None:
    """Intent: quote.status has no order_id, so it must not create or
    mutate an entry in self._orders — it's a standalone history row.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "quote.status.MM01",
        {
            "gateway_id": "MM01",
            "quote_id": "SEED-MM01-AAPL-1",
            "status": "INACTIVE_ASK_FILLED",
            "reason": "",
        },
    )

    with monitor._lock:
        assert monitor._orders == {}
        assert len(monitor._history) == 1
        row = monitor._history[-1]
        assert row["kind"] == "quote"
        assert row["gateway_id"] == "MM01"
        assert row["quote_id"] == "SEED-MM01-AAPL-1"
        assert row["status"] == "INACTIVE_ASK_FILLED"


def test_quote_status_gateway_id_falls_back_to_topic() -> None:
    """Intent: same defensive fallback order.* handling already has —
    derive gateway_id from the topic if the payload ever omits it.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "quote.status.MM01",
        {"quote_id": "SEED-MM01-AAPL-1", "status": "ACTIVE"},
    )

    with monitor._lock:
        row = monitor._history[-1]
        assert row["gateway_id"] == "MM01"


def test_quote_status_respects_gateway_filter() -> None:
    """Intent: --gateway filtering must apply to quote.status rows the same
    way it already applies to order.* rows.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter="GW01")

    monitor._handle(
        "quote.status.MM01",
        {"gateway_id": "MM01", "quote_id": "Q1", "status": "ACTIVE"},
    )
    with monitor._lock:
        assert len(monitor._history) == 0

    monitor._handle(
        "quote.status.GW01",
        {"gateway_id": "GW01", "quote_id": "Q2", "status": "ACTIVE"},
    )
    with monitor._lock:
        assert len(monitor._history) == 1


def test_quote_status_backfills_symbol_from_quote_meta() -> None:
    """Intent: a quote.status row (e.g. INACTIVE_ASK_FILLED) has no symbol
    on the wire — pm-orders must fill it in from whichever leg's ack/fill
    already revealed the symbol, the same _quote_meta store order.cancelled
    backfill already relies on.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    # The hit leg's fill teaches _quote_meta the symbol for this quote_id.
    monitor._handle(
        "order.fill.MM01",
        {
            "gateway_id": "MM01",
            "order_id": "hit-leg",
            "quote_id": "Q-AAPL-1",
            "symbol": "AAPL",
            "side": "SELL",
            "status": "FILLED",
        },
    )
    # Engine then publishes the quote's own status transition, still with
    # no symbol on the wire.
    monitor._handle(
        "quote.status.MM01",
        {
            "gateway_id": "MM01",
            "quote_id": "Q-AAPL-1",
            "status": "INACTIVE_ASK_FILLED",
        },
    )

    with monitor._lock:
        quote_rows = [r for r in monitor._history if r.get("kind") == "quote"]
        assert len(quote_rows) == 1
        assert quote_rows[0]["symbol"] == "AAPL"


def test_quote_status_symbol_falls_back_gracefully_when_unknown() -> None:
    """Intent: if no leg of this quote has ever been observed, there's
    nothing to backfill from — the row should carry symbol=None rather
    than raise, and rendering must still succeed.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "quote.status.MM01",
        {
            "gateway_id": "MM01",
            "quote_id": "NEVER-SEEN",
            "status": "INACTIVE_BID_FILLED",
        },
    )

    with monitor._lock:
        row = monitor._history[-1]
        assert row["symbol"] is None

    from edumatcher.orders.main import _build_rows_table

    _build_rows_table(list(monitor._history))


def test_build_rows_table_translates_quote_status_text() -> None:
    """Intent: the raw wire enum (INACTIVE_BID_FILLED / INACTIVE_ASK_FILLED)
    names the side that TRADED, not the side that was cancelled, and reads
    plausibly either way to someone unfamiliar with that convention —
    _build_rows_table must render the spelled-out _QUOTE_STATUS_TEXT instead
    of the raw enum value.
    """
    from edumatcher.orders.main import _QUOTE_STATUS_TEXT, _build_rows_table

    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "quote.status.MM01",
        {
            "gateway_id": "MM01",
            "quote_id": "Q1",
            "status": "INACTIVE_ASK_FILLED",
        },
    )

    with monitor._lock:
        table = _build_rows_table(list(monitor._history))

    rendered = [str(cell) for cell in table.columns[-1]._cells]
    assert _QUOTE_STATUS_TEXT["INACTIVE_ASK_FILLED"] in rendered[0]
    assert "INACTIVE_ASK_FILLED" not in rendered[0]


def test_build_rows_table_shows_inactivated_side_for_quote_fill() -> None:
    """Intent: INACTIVE_BID_FILLED means the BID traded, so the leg that
    went inactive (the one an operator needs to re-quote) is the ASK —
    SELL. The Side column must show the cancelled side, not the side that
    traded.
    """
    from edumatcher.orders.main import _build_rows_table

    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "quote.status.MM01",
        {
            "gateway_id": "MM01",
            "quote_id": "Q1",
            "status": "INACTIVE_BID_FILLED",
        },
    )

    with monitor._lock:
        table = _build_rows_table(list(monitor._history))

    rendered_side = str(table.columns[4]._cells[0])
    assert rendered_side == "SELL"


def test_build_rows_table_shows_inactivated_side_for_quote_ask_fill() -> None:
    """Intent: the mirror case — INACTIVE_ASK_FILLED means the ASK traded,
    so the cancelled leg (shown in Side) is the BID — BUY.
    """
    from edumatcher.orders.main import _build_rows_table

    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "quote.status.MM01",
        {
            "gateway_id": "MM01",
            "quote_id": "Q1",
            "status": "INACTIVE_ASK_FILLED",
        },
    )

    with monitor._lock:
        table = _build_rows_table(list(monitor._history))

    rendered_side = str(table.columns[4]._cells[0])
    assert rendered_side == "BUY"


def test_build_rows_table_quote_side_blank_for_active_and_cancelled() -> None:
    """Intent: ACTIVE and explicit CANCELLED apply to the whole quote (both
    legs), so there's no single side to show — the Side cell must stay
    blank rather than guessing.
    """
    from edumatcher.orders.main import _build_rows_table

    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "quote.status.MM01",
        {"gateway_id": "MM01", "quote_id": "Q1", "status": "ACTIVE"},
    )
    monitor._handle(
        "quote.status.MM01",
        {"gateway_id": "MM01", "quote_id": "Q1", "status": "CANCELLED"},
    )

    with monitor._lock:
        table = _build_rows_table(list(monitor._history))

    side_cells = [str(c) for c in table.columns[4]._cells]
    assert side_cells == ["", ""]


def test_build_rows_table_appends_reason_to_translated_status() -> None:
    """Intent: an explicit CANCELLED transition can carry a reason (unlike
    the *_FILLED transitions, which never do — see
    Engine._on_quote_leg_filled's 3-arg make_quote_status_msg call). When
    present, the reason must still ride alongside the translated text.
    """
    from edumatcher.orders.main import _build_rows_table

    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    monitor._handle(
        "quote.status.MM01",
        {
            "gateway_id": "MM01",
            "quote_id": "Q1",
            "status": "CANCELLED",
            "reason": "replaced",
        },
    )

    with monitor._lock:
        table = _build_rows_table(list(monitor._history))

    rendered = [str(cell) for cell in table.columns[-1]._cells]
    assert rendered[0] == "CANCELLED (replaced)"


def test_run_closes_subscriber_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Intent: run loop should always close subscriber resources when exiting."""
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter="GW01")

    def _receive_once_then_stop() -> None:
        monitor._running = False

    with (
        patch("edumatcher.orders.main.threading.Thread", _InlineThread),
        patch("edumatcher.orders.main.Live", _FakeLive),
        patch.object(threading, "Event"),
        patch.object(monitor, "_receive", side_effect=_receive_once_then_stop),
        patch("edumatcher.orders.main.signal.signal", lambda *_a, **_k: None),
        patch("edumatcher.orders.main.time.sleep", lambda *_a, **_k: None),
    ):
        monitor.run()

    assert fake_sub.closed is True
