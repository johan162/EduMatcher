"""Engine-inbound prices are ticks, everywhere, with no exceptions.

Until this change the *unit* of a price depended on its *runtime type*:
``to_ticks`` returned an ``int`` argument unchanged, on the convention that "an
integer is already ticks". Three inbound paths then disagreed about which side
of that convention they were on — ``order.new`` and ``order.combo`` sent ticks
and the engine defensively re-converted anything that looked like a float,
while ``order.oco`` sent display money and the engine always converted.

That is unrepresentable in a schema, and it made a display price of exactly
``150`` indistinguishable from ``150`` ticks — a 100x mispricing on a
two-decimal instrument, silent in both directions.

The rule now: **converting is the submitting gateway's job, and the wire
carries integer ticks.** These tests are what stops a display float creeping
back onto it.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.price import to_ticks


class TestToTicksIsTotal:
    """The passthrough that made the ambiguity expressible is gone."""

    def test_an_integer_is_a_display_price_like_any_other(self) -> None:
        """``to_ticks(150, "AAPL")`` is $150.00, not 150 ticks.

        This is the assertion that used to be false. It is the whole reason the
        int/float convention could not survive contact with a schema.
        """
        assert to_ticks(150, "AAPL") == 15000

    def test_a_float_converts_the_same_way(self) -> None:
        assert to_ticks(150.0, "AAPL") == 15000

    def test_the_two_agree(self) -> None:
        """No caller should be able to tell 150 from 150.0."""
        assert to_ticks(150, "AAPL") == to_ticks(150.0, "AAPL")


def _leg_prices(payload: dict[str, Any]) -> list[Any]:
    """Every price-bearing value in an OCO payload's two legs."""
    return [
        leg[key]
        for leg in (payload["leg1"], payload["leg2"])
        for key in ("price", "stop_price", "trail_offset")
        if key in leg
    ]


class TestGatewaysEmitTicks:
    """The producers, driven for real rather than inspected.

    ``order.oco`` is the path that changed: all three of its gateways used to
    put display money on the wire.
    """

    def test_api_gateway_oco_legs_are_ticks(self) -> None:
        from edumatcher.api_gateway.schemas import OcoLegRequest, OcoRequest
        from edumatcher.api_gateway.translate import build_oco_payload
        from edumatcher.models.order import OrderType, Side, TIF

        request = OcoRequest(
            oco_id="X1",
            symbol="AAPL",
            quantity=10,
            tif=TIF.DAY,
            leg1=OcoLegRequest(side=Side.BUY, order_type=OrderType.LIMIT, price=95.5),
            leg2=OcoLegRequest(
                side=Side.SELL, order_type=OrderType.LIMIT, price=130.25
            ),
        )
        payload = build_oco_payload(request, "GW1")

        assert payload["leg1"]["price"] == 9550
        assert payload["leg2"]["price"] == 13025
        assert all(isinstance(v, int) for v in _leg_prices(payload))

    def test_api_gateway_combo_legs_are_ticks(self) -> None:
        """Combo already converted; this pins it so it stays that way."""
        from edumatcher.api_gateway.schemas import ComboLegRequest, ComboRequest
        from edumatcher.api_gateway.translate import build_combo_payload
        from edumatcher.models.order import OrderType, Side, TIF

        leg = ComboLegRequest(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=95.5,
        )
        other = ComboLegRequest(
            symbol="MSFT",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=130.25,
        )
        payload = build_combo_payload(
            ComboRequest(combo_id="C1", tif=TIF.DAY, legs=[leg, other]), "GW1"
        )
        prices = [each["price"] for each in payload["legs"]]
        assert prices == [9550, 13025]
        assert all(isinstance(p, int) for p in prices)

    def test_api_gateway_new_order_price_is_ticks(self) -> None:
        from edumatcher.api_gateway.schemas import OrderRequest
        from edumatcher.api_gateway.translate import build_order
        from edumatcher.models.order import OrderType, Side, TIF

        order = build_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=10,
                tif=TIF.DAY,
                price=95.5,
            ),
            "GW1",
        )
        assert order.to_dict()["price"] == 9550
        assert isinstance(order.to_dict()["price"], int)


class TestTheEngineRejectsDisplayMoney:
    """The trust boundary, driven through the real handler.

    Truncating silently is the failure this whole change exists to remove: a
    leg priced 95.0 would rest at 95 ticks — 95 cents — and cross everything on
    the book. Rejecting the leg is the loud alternative.
    """

    @pytest.mark.parametrize("key", ["price", "stop_price", "trail_offset"])
    def test_a_display_float_leg_is_rejected(
        self, key: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from edumatcher.models.message import decode
        from tests.test_engine_handlers import _connect, _make_engine

        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_oco_order(
            {
                "oco_id": "OCO-FLOAT",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", key: 95.0},
                "leg2": {"side": "SELL", "order_type": "LIMIT", "price": 10500},
            }
        )
        _topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "leg" in msg["reason"].lower()

    def test_an_integer_leg_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """The same payload in ticks goes through, so the guard is specific."""
        from edumatcher.models.message import decode
        from tests.test_engine_handlers import _connect, _make_engine

        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_oco_order(
            {
                "oco_id": "OCO-TICKS",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 9500},
                "leg2": {"side": "SELL", "order_type": "LIMIT", "price": 10500},
            }
        )
        _topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is True


class TestNoDisplayFloatsLingerInTestPayloads:
    """The sweep that came with this change, pinned.

    29 OCO and combo leg payloads across eight test modules carried display
    floats. They passed only because the engine converted them, so removing
    that conversion is exactly what surfaced them. A new one would now rest at
    1/100th of its intended price, which is easy to miss in a test that only
    asserts "a fill happened".
    """

    def test_no_leg_payload_in_the_suite_uses_a_float_price(self) -> None:
        import re
        from pathlib import Path

        pattern = re.compile(r'"(?:price|stop_price|trail_offset)":\s*\d+\.\d+')
        offenders = []
        for path in sorted(Path(__file__).resolve().parent.glob("test_*.py")):
            if path.name == Path(__file__).name:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                is_leg = '"leg1"' in line or '"leg2"' in line
                is_leg = is_leg or ('"side"' in line and '"order_type"' in line)
                if is_leg and pattern.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        assert offenders == [], "display money on an engine-inbound leg:\n" + "\n".join(
            offenders
        )
