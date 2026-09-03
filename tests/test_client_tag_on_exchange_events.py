"""An exchange-initiated lifecycle event carries the order's ``client_tag``.

``client_tag`` is the whole point of G1: a client correlates a lifecycle event
back to the order it submitted without matching on arrival order. That worked
for events the client asked for, and silently did not for the ones the
exchange decided on its own — an OCO sibling cancel, a combo cascade, a quote
replacement, a DAY expiry at the close. Those are precisely the events a
client cannot predict, so they are the ones where correlation matters most.

The cause was not carelessness at seven call sites. ``make_ack_msg`` read the
tag off its ``order`` argument; ``make_cancelled_msg`` and ``make_expired_msg``
took the same argument, used it only for group ids, and left ``client_tag`` at
its ``None`` default — with nothing in either signature to say they differed.
The first class of test below pins the shared behaviour so the three builders
cannot drift apart again; the second proves it reaches the wire on the paths
that were broken.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.generated.order import (
    topic_order_cancelled,
    topic_order_expired,
)
from edumatcher.models.message import (
    make_ack_msg,
    make_cancelled_msg,
    make_expired_msg,
)
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import connect, make_engine, msgs, order_payload

_ORDER = {
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "DAY",
    "quantity": 10,
    "client_tag": "CT-FROM-ORDER",
    "oco_group_id": "OCO-9",
}


def _payload(frames: list[bytes]) -> dict[str, Any]:
    from edumatcher.models.message import decode

    return decode(frames)[1]


def _builders() -> list[tuple[str, Any]]:
    """The three builders that take an ``order`` and an optional tag."""
    return [
        ("cancelled", lambda **kw: make_cancelled_msg("GW1", "O1", **kw)),
        ("expired", lambda **kw: make_expired_msg("GW1", "O1", **kw)),
        ("ack", lambda **kw: make_ack_msg("GW1", "O1", False, "no", **kw)),
    ]


class TestBuildersAgree:
    """Whichever builder you reach for, ``order=`` means the same thing."""

    @pytest.mark.parametrize(
        "name,build", _builders(), ids=lambda v: getattr(v, "__name__", str(v))
    )
    def test_tag_comes_from_the_order(self, name: str, build: Any) -> None:
        assert _payload(build(order=_ORDER))["client_tag"] == "CT-FROM-ORDER"

    @pytest.mark.parametrize(
        "name,build", _builders(), ids=lambda v: getattr(v, "__name__", str(v))
    )
    def test_an_explicit_tag_wins(self, name: str, build: Any) -> None:
        """A caller that knows better than the order dict stays in charge —
        the engine's cancel handler passes the resting order's tag while the
        payload it was handed is the *request*, not the order."""
        payload = build(client_tag="CT-EXPLICIT", order=_ORDER)
        assert _payload(payload)["client_tag"] == "CT-EXPLICIT"

    @pytest.mark.parametrize(
        "name,build", _builders(), ids=lambda v: getattr(v, "__name__", str(v))
    )
    def test_no_order_and_no_tag_stays_absent(self, name: str, build: Any) -> None:
        """omit_when_none: an untagged order must not grow a null field."""
        assert "client_tag" not in _payload(build())

    @pytest.mark.parametrize(
        "name,build", _builders(), ids=lambda v: getattr(v, "__name__", str(v))
    )
    def test_an_untagged_order_stays_absent(self, name: str, build: Any) -> None:
        untagged = {k: v for k, v in _ORDER.items() if k != "client_tag"}
        assert "client_tag" not in _payload(build(order=untagged))

    def test_group_ids_still_travel(self) -> None:
        """Guard against 'fixing' the tag by replacing the order argument."""
        for _name, build in _builders():
            assert _payload(build(order=_ORDER))["oco_group_id"] == "OCO-9"


class TestExchangeInitiatedEventsOnTheWire:
    """The paths that were dropping it, driven through the engine."""

    def test_oco_sibling_cancel_carries_the_tag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """Cancelling one OCO leg cascades to its sibling. The client asked for
        one cancel and receives two; without a tag on the second it cannot tell
        which of its orders the exchange took away."""
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        engine._handle_oco_order(
            {
                "oco_id": "OCO001",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "quantity": 100,
                "tif": "DAY",
                "client_tag": "CT-OCO",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 9500},
                "leg2": {"side": "BUY", "order_type": "STOP", "stop_price": 10500},
            }
        )
        engine._handle_oco_cancel({"oco_id": "OCO001", "gateway_id": "GW01"})

        cancels = msgs(pub, topic_order_cancelled("GW01"))
        assert cancels, "OCO cancel produced no order.cancelled"
        assert all(c.get("client_tag") == "CT-OCO" for c in cancels), cancels

    def test_day_expiry_at_the_close_carries_the_tag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """The one make_expired_msg call site, and the least predictable event
        of all: it fires hours after the client last touched the order."""
        engine, pub = make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        connect(engine, "GW01")
        # Sessions start CLOSED; walk to CONTINUOUS so the order is accepted.
        engine._handle_session_transition({"to_state": "PRE_OPEN"})
        engine._handle_session_transition({"to_state": "CONTINUOUS"})

        resting = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=95.00)
        resting["client_tag"] = "CT-DAY"
        engine._handle_new_order(resting)
        engine._handle_session_transition({"to_state": "CLOSED"})

        expired = msgs(pub, topic_order_expired("GW01"))
        assert expired, "DAY order was not expired at the close"
        assert all(e.get("client_tag") == "CT-DAY" for e in expired), expired
