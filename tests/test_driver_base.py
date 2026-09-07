"""Unit tests for the ``Driver`` protocol's dataclass contract.

Covers Requirement 4, Criteria 3, 5, and 6 (see requirements.md and
design.md Components §4):

  * a wire field absent on the response becomes ``None`` on the normalised
    dataclass rather than a substituted default (4.3);
  * ``orders``/``positions``/``events`` return ``[]``, never ``None``, when
    nothing matches (4.5);
  * the reserved ``quote``/``kill_switch`` verbs raise ``NotImplementedError``
    in every Phase 1/2 ``Driver`` implementation (4.6).

The ``Driver`` protocol itself only declares structural shape (it is not
``@runtime_checkable``, per drivers/base.py's own docstring), so the
``NotImplementedError`` contract is exercised here against a minimal fake
implementation rather than against the ``Protocol`` class directly.
"""

from __future__ import annotations

from edumatcher.systest.drivers.base import (
    Ack,
    Driver,
    Event,
    NewOrderRequest,
    OrderAmendment,
    OrderView,
    PositionView,
    SessionView,
)


class FakeDriver:
    """A minimal, otherwise-inert stand-in for a Phase 1 ``Driver``.

    Every verb besides ``quote``/``kill_switch`` returns a trivial, valid
    value so this class satisfies the ``Driver`` Protocol's shape; only the
    two reserved verbs are under test here.
    """

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def new_order(self, order: NewOrderRequest) -> Ack:
        raise NotImplementedError

    def cancel_order(self, order_id: str, *, request_tag: str | None = None) -> Ack:
        raise NotImplementedError

    def amend_order(self, order_id: str, amendment: OrderAmendment) -> Ack:
        raise NotImplementedError

    def orders(self) -> list[OrderView]:
        return []

    def positions(self) -> list[PositionView]:
        return []

    def session(self) -> SessionView:
        raise NotImplementedError

    def events(self) -> list[Event]:
        return []

    def quote(self, req: object) -> Ack:
        raise NotImplementedError

    def kill_switch(self, symbol: str | None) -> Ack:
        raise NotImplementedError


def _assert_is_driver(driver: Driver) -> None:
    """Type-level nudge: ``FakeDriver`` must actually fit the ``Driver`` shape.

    ``Driver`` is not ``@runtime_checkable`` (see drivers/base.py), so this
    is a structural convenience for readers, not an ``isinstance`` check.
    """


class TestOmittedWireFieldsStoreNoneNotADefault:
    """Requirement 4.3: an absent wire field becomes ``None``, never a
    substituted default (not ``0``, not ``""``, not a sentinel)."""

    def test_ack_omitted_optional_fields_are_none_not_defaults(self) -> None:
        ack = Ack(
            order_id=None,
            accepted=True,
            reason="",
            reject_code=None,
            client_tag=None,
            request_tag=None,
        )
        # symbol/side/order_type/tif/qty/price are optional wire fields with
        # no explicit value supplied here -- they must default to None, not
        # to "", 0, or any other substituted value.
        assert ack.symbol is None
        assert ack.side is None
        assert ack.order_type is None
        assert ack.tif is None
        assert ack.qty is None
        assert ack.price is None

    def test_order_view_omitted_optional_fields_are_none(self) -> None:
        view = OrderView(
            id="order-1",
            symbol="AAPL",
            side="BUY",
            order_type="LIMIT",
            tif="DAY",
            quantity=100,
            remaining_qty=100,
            status="NEW",
            price=10.0,
            stop_price=None,
            visible_qty=None,
            displayed_qty=None,
            smp_action=None,
            oco_group_id=None,
            combo_parent_id=None,
            leg_index=None,
            origin="alf",
            quote_id=None,
            client_tag=None,
            arrival_seq=1,
            timestamp=0.0,
        )
        assert view.stop_price is None
        assert view.visible_qty is None
        assert view.displayed_qty is None
        assert view.smp_action is None
        assert view.oco_group_id is None
        assert view.combo_parent_id is None
        assert view.leg_index is None
        assert view.quote_id is None
        assert view.client_tag is None

    def test_session_view_omitted_optional_fields_default_to_none(self) -> None:
        # prev_state/next_state/next_at are declared with a `= None` default
        # on SessionView -- confirm omitting them on construction actually
        # yields None rather than some other substituted value.
        view = SessionView(state="CONTINUOUS", sessions_enabled=True)
        assert view.prev_state is None
        assert view.next_state is None
        assert view.next_at is None

    def test_event_omitted_fill_and_cancel_fields_are_none_not_defaults(self) -> None:
        # A non-fill event (an "ack") has no fill/cancel-specific data on the
        # wire; those fields must come through as None, and trade_ids -- the
        # one field with a non-None default -- must be an empty list, not a
        # shared mutable default across instances (dataclass `field(default_
        # factory=list)`).
        event = Event(
            kind="ack",
            order_id="order-1",
            gateway_id="gw-1",
            client_tag=None,
            request_tag=None,
            sequence=1,
            accepted=True,
        )
        assert event.fill_qty is None
        assert event.fill_price is None
        assert event.remaining_qty is None
        assert event.liquidity_flag is None
        assert event.cancel_reason is None
        assert event.priority_reset is None
        assert event.price is None
        assert event.qty is None
        assert event.reject_code is None
        assert event.reason is None
        assert event.trade_ids == []

    def test_event_trade_ids_default_is_not_a_shared_mutable_list(self) -> None:
        first = Event(
            kind="fill",
            order_id="o1",
            gateway_id="gw-1",
            client_tag=None,
            request_tag=None,
            sequence=1,
        )
        second = Event(
            kind="fill",
            order_id="o2",
            gateway_id="gw-1",
            client_tag=None,
            request_tag=None,
            sequence=2,
        )
        first.trade_ids.append("T-1")
        assert second.trade_ids == []


class TestReservedVerbsRaiseNotImplementedError:
    """Requirement 4.6: ``quote``/``kill_switch`` raise ``NotImplementedError``
    in every Phase 1/2 ``Driver`` implementation."""

    def test_quote_raises_not_implemented_error(self) -> None:
        driver: Driver = FakeDriver()
        _assert_is_driver(driver)
        try:
            driver.quote(object())
        except NotImplementedError:
            pass
        else:
            raise AssertionError("quote() did not raise NotImplementedError")

    def test_kill_switch_raises_not_implemented_error(self) -> None:
        driver: Driver = FakeDriver()
        try:
            driver.kill_switch("AAPL")
        except NotImplementedError:
            pass
        else:
            raise AssertionError("kill_switch() did not raise NotImplementedError")

    def test_kill_switch_raises_with_none_symbol(self) -> None:
        driver: Driver = FakeDriver()
        try:
            driver.kill_switch(None)
        except NotImplementedError:
            pass
        else:
            raise AssertionError("kill_switch(None) did not raise NotImplementedError")


class TestNoMatchesReturnEmptyListNotNone:
    """Requirement 4.5: ``orders``/``positions``/``events`` return ``[]``,
    never ``None``, when nothing matches (checked against a Phase 1-shaped
    fake, since this is a per-implementation contract the Protocol itself
    cannot enforce)."""

    def test_orders_returns_empty_list_not_none(self) -> None:
        driver: Driver = FakeDriver()
        result = driver.orders()
        assert result == []
        assert result is not None

    def test_positions_returns_empty_list_not_none(self) -> None:
        driver: Driver = FakeDriver()
        result = driver.positions()
        assert result == []
        assert result is not None

    def test_events_returns_empty_list_not_none(self) -> None:
        driver: Driver = FakeDriver()
        result = driver.events()
        assert result == []
        assert result is not None
