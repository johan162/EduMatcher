"""``ComboOrder`` serialises for three different jobs, and they are now three.

One ``to_dict()`` was serving all of them:

===================  =======================================================
submission           what a gateway sends as ``order.combo``
event                what the engine put on ``combo.ack``
persistence          what ``save_gtc_combos`` writes

The submission inherited the other two's fields as a result — ``id``,
``status``, ``child_order_ids``, ``leg_fill_qty``, ``leg_statuses``. A client
fills in none of them: the lists and maps are always empty and the status is
always PENDING. They were noise that only the engine could populate.

Beyond the tidiness, this is what unblocks the message generator. The two
``leg_*`` maps are integer-keyed dictionaries, which the IDL has no way to
describe; removing them from the wire means ``order.combo`` needs only
``nested`` and ``list[T]`` — ordinary, additive features — rather than a map
construct invented to accommodate a shape nothing wanted (design section 15.4).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from edumatcher.models.combo import ComboLeg, ComboOrder, ComboStatus, ComboType
from edumatcher.models.order import OrderType, Side, TIF

_LEGS = [
    ComboLeg(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=9500,
    ),
    ComboLeg(
        symbol="MSFT",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=13000,
    ),
]


def _combo() -> ComboOrder:
    return ComboOrder.create(
        combo_id="C1",
        gateway_id="GW1",
        combo_type=ComboType.AON,
        tif=TIF.DAY,
        legs=list(_LEGS),
    )


class TestTheSubmissionShape:
    def test_it_carries_only_what_a_client_can_say(self) -> None:
        assert set(_combo().to_submission_dict()) == {
            "combo_id",
            "gateway_id",
            "combo_type",
            "tif",
            "legs",
        }

    @pytest.mark.parametrize(
        "field",
        ["id", "status", "child_order_ids", "leg_fill_qty", "leg_statuses"],
    )
    def test_engine_owned_state_is_absent(self, field: str) -> None:
        assert field not in _combo().to_submission_dict()

    def test_the_legs_survive_intact(self) -> None:
        """Dropping state must not drop the part that carries the order."""
        legs = _combo().to_submission_dict()["legs"]
        assert [leg["symbol"] for leg in legs] == ["AAPL", "MSFT"]
        assert [leg["price"] for leg in legs] == [9500, 13000]


class TestNoMapsReachTheWire:
    """The property that unblocks the IDL, asserted rather than assumed."""

    def _has_mapping(self, value: Any) -> bool:
        if isinstance(value, dict):
            return True
        if isinstance(value, list):
            return any(self._has_mapping(item) for item in value)
        return False

    def test_no_submission_field_is_a_map(self) -> None:
        payload = _combo().to_submission_dict()
        offenders = [k for k, v in payload.items() if self._has_mapping(v)]
        assert offenders == ["legs"], "legs is a list of records, not a map"

    def test_a_leg_is_flat(self) -> None:
        """``nested`` is enough; no leg field is itself a container."""
        leg = _combo().to_submission_dict()["legs"][0]
        assert not any(self._has_mapping(v) for v in leg.values())

    def test_the_combo_ack_is_three_scalars(self) -> None:
        from edumatcher.models.message import decode, make_combo_ack_msg

        _topic, payload = decode(make_combo_ack_msg("GW1", "C1", True, "ok"))
        assert not any(self._has_mapping(v) for v in payload.values())


class TestTheEngineOwnsTheIdentity:
    def test_from_submission_mints_id_timestamp_and_status(self) -> None:
        built = ComboOrder.from_submission_dict(_combo().to_submission_dict())
        assert built.id
        assert built.timestamp > 0
        assert built.status is ComboStatus.PENDING

    def test_a_client_supplied_id_is_ignored(self) -> None:
        """A submitter that could name its own internal id could collide."""
        payload = _combo().to_submission_dict()
        payload["id"] = "attacker-chosen"
        assert ComboOrder.from_submission_dict(payload).id != "attacker-chosen"

    def test_two_submissions_of_the_same_payload_get_distinct_ids(self) -> None:
        payload = _combo().to_submission_dict()
        first = ComboOrder.from_submission_dict(payload)
        second = ComboOrder.from_submission_dict(payload)
        assert first.id != second.id


class TestPersistenceKeepsTheFullState:
    """``to_dict``/``from_dict`` are now persistence's alone, and unchanged."""

    def test_the_state_round_trips(self) -> None:
        combo = _combo()
        combo.child_order_ids = ["o1", "o2"]
        combo.leg_fill_qty = {0: 5}
        combo.leg_statuses = {0: "PARTIAL"}

        restored = ComboOrder.from_dict(json.loads(json.dumps(combo.to_dict())))

        assert restored.id == combo.id
        assert restored.child_order_ids == ["o1", "o2"]
        assert restored.leg_fill_qty == {0: 5}
        assert restored.leg_statuses == {0: "PARTIAL"}

    def test_the_two_shapes_are_different(self) -> None:
        combo = _combo()
        assert set(combo.to_dict()) > set(combo.to_submission_dict())


class TestEveryProducerSendsTheSameShape:
    """Three gateways build this payload; they must not drift apart."""

    def test_api_gateway_matches_the_submission_shape(self) -> None:
        from edumatcher.api_gateway.schemas import ComboLegRequest, ComboRequest
        from edumatcher.api_gateway.translate import build_combo_payload

        payload = build_combo_payload(
            ComboRequest(
                combo_id="C1",
                tif=TIF.DAY,
                legs=[
                    ComboLegRequest(
                        symbol="AAPL",
                        side=Side.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=10,
                        price=95.0,
                    ),
                    ComboLegRequest(
                        symbol="MSFT",
                        side=Side.SELL,
                        order_type=OrderType.LIMIT,
                        quantity=10,
                        price=130.0,
                    ),
                ],
            ),
            "GW1",
        )
        assert set(payload) == set(_combo().to_submission_dict())

    def test_the_engine_accepts_what_the_gateway_sends(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """End to end: the submission shape is what the handler reads."""
        from edumatcher.models.message import decode
        from tests.test_engine_handlers import _connect, _make_engine

        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        _connect(engine)
        combo = ComboOrder.create(
            combo_id="C-E2E",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=list(_LEGS),
        )
        engine._handle_combo_order(combo.to_submission_dict())

        acks = [
            decode(frame)[1]
            for frame in pub_sock.sent
            if decode(frame)[0].startswith("combo.ack.")
        ]
        assert acks and acks[-1]["accepted"] is True
