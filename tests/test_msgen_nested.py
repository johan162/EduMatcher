"""``nested``: a record type declared once and embedded by name.

The first IDL construct beyond scalars. ``order.oco`` is what motivated it and
what proves it: two ``OcoLeg`` records, one message, one generated dataclass.

The design decisions being pinned here are as much about what ``nested`` does
*not* do as what it does — no recursion, no external transports, no hot-path
builder. Each is a place where half-supporting the construct would have put a
wrong answer in a committed binding rather than an error in a spec file.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import order as G
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.msgen.spec import SpecError, load_family, load_transports

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPO_ROOT / "spec"


def _payload() -> dict[str, object]:
    return {
        "oco_id": "X1",
        "gateway_id": "GW1",
        "symbol": "AAPL",
        "quantity": 10,
        "tif": "DAY",
        "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 9500},
        "leg2": {"side": "SELL", "order_type": "STOP", "stop_price": 10500},
    }


class TestTheRecordRoundTrips:
    def test_from_dict_builds_the_nested_dataclass(self) -> None:
        oco = G.OrderOco.from_dict(_payload())
        assert isinstance(oco.leg1, G.OcoLeg)
        assert oco.leg1.side == "BUY"
        assert oco.leg1.price == 9500

    def test_to_dict_reproduces_the_payload_exactly(self) -> None:
        """Byte-identity, which is every family adoption's acceptance bar."""
        assert G.OrderOco.from_dict(_payload()).to_dict() == _payload()

    def test_a_leg_omits_the_prices_it_does_not_have(self) -> None:
        """``omit_when_none`` applies inside a record, as it does outside."""
        leg = G.OrderOco.from_dict(_payload()).leg1.to_dict()
        assert leg == {"side": "BUY", "order_type": "LIMIT", "price": 9500}
        assert "stop_price" not in leg
        assert "trail_offset" not in leg

    def test_the_bus_frames_match_the_hand_written_builder(self) -> None:
        assert M.make_oco_order_msg(_payload()) == G.make_order_oco(**_payload())


class TestValidationReachesIntoTheRecord:
    """Rules declared on a record's fields apply wherever it is embedded.

    Declaring them once is the point: ``OcoLeg`` is used twice by this message
    alone, and a rule enforced per-embedding would be a rule that can differ
    per-embedding.
    """

    def test_a_bad_leg_enum_is_rejected(self) -> None:
        payload = _payload()
        payload["leg1"] = {"side": "SIDEWAYS", "order_type": "LIMIT"}
        with pytest.raises(MessageValidationError, match="side"):
            G.OrderOco.from_dict(payload).validate()

    def test_a_good_payload_validates(self) -> None:
        G.OrderOco.from_dict(_payload()).validate()

    def test_the_record_validates_standalone_too(self) -> None:
        with pytest.raises(MessageValidationError):
            G.OcoLeg.from_dict({"side": "NOPE", "order_type": "LIMIT"}).validate()

    def test_from_dict_still_does_not_validate(self) -> None:
        """The coercion/validation split (5.1.1) holds through a record.

        Read back through ``to_dict`` rather than off the attribute: the
        attribute is annotated ``Literal["BUY", "SELL"]``, and a type checker is
        right that it can never equal "SIDEWAYS". At runtime it does, which is
        the whole point of the split — ``cast`` in ``from_dict`` is where that
        admission lives (design section 5.1.1).
        """
        payload = _payload()
        payload["leg1"] = {"side": "SIDEWAYS", "order_type": "LIMIT"}
        assert G.OrderOco.from_dict(payload).leg1.to_dict()["side"] == "SIDEWAYS"


class TestOneDefinitionNotTwo:
    def test_both_legs_are_the_same_class(self) -> None:
        oco = G.OrderOco.from_dict(_payload())
        assert type(oco.leg1) is type(oco.leg2)

    def test_the_dataclass_is_emitted_once(self) -> None:
        source = (REPO_ROOT / "src/edumatcher/models/generated/order.py").read_text(
            encoding="utf-8"
        )
        assert source.count("class OcoLeg:") == 1

    def test_it_is_defined_before_the_message_that_embeds_it(self) -> None:
        source = (REPO_ROOT / "src/edumatcher/models/generated/order.py").read_text(
            encoding="utf-8"
        )
        assert source.index("class OcoLeg:") < source.index("class OrderOco:")


class TestWhatNestedDeliberatelyDoesNot:
    """Each of these is an error in a spec file rather than a wrong binding."""

    def _family(self, tmp_path: Path, body: str) -> None:
        transports = load_transports(SPEC_ROOT / "transports.yaml")
        path = tmp_path / "fake.yaml"
        path.write_text(body, encoding="utf-8")
        load_family(path, transports)

    def test_a_record_may_contain_a_record(self, tmp_path: Path) -> None:
        """5.2d narrowed this: what breaks the generators is a cycle, not depth.

        ``log.status`` carries a subscription, which carries its own filter.
        Forbidding depth was a rule broader than its reason, so the loader now
        rejects reference cycles and emits types in dependency order.
        """
        if True:
            self._family(
                tmp_path,
                """
family: fake
version: 1
types:
  Inner:
    fields: [{ name: a, type: string }]
  Outer:
    fields: [{ name: b, type: nested, ref: Inner }]
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: { motivation: "fixture", published_by: [engine], since: "1.0" }
    fields: [{ name: x, type: nested, ref: Outer }]
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
            )

    def test_an_unknown_ref_is_caught(self, tmp_path: Path) -> None:
        with pytest.raises(SpecError, match="unknown type"):
            self._family(
                tmp_path,
                """
family: fake
version: 1
types:
  Leg:
    fields: [{ name: a, type: string }]
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: { motivation: "fixture", published_by: [engine], since: "1.0" }
    fields: [{ name: x, type: nested, ref: Legg }]
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
            )

    def test_a_type_may_not_shadow_a_message_class(self, tmp_path: Path) -> None:
        """A record and a message emit classes into the same module.

        6.1e wrote a ``SessionSchedule`` type beside a ``session_schedule``
        message, so ``class SessionSchedule`` was defined twice and the second
        silently shadowed the first — the nested field resolved to the message
        class at runtime. Every existing check passed on that spec: ``lint``,
        ``pm-msgen check`` and black. Design section 28.4.
        """
        with pytest.raises(SpecError, match="both generate 'class Thing'"):
            self._family(
                tmp_path,
                """
family: fake
version: 1
types:
  Thing:
    fields: [{ name: a, type: string }]
messages:
  - name: thing
    topic: "m.t"
    transport: [engine_pub]
    doc: { motivation: "fixture", published_by: [engine], since: "1.0" }
    fields: [{ name: x, type: nested, ref: Thing }]
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
            )

    def test_the_shadowing_guard_allows_an_unrelated_type(self, tmp_path: Path) -> None:
        """The guard keys on the emitted class name, not on resemblance.

        Section 23.1: a check that has never disagreed has not been tested, and
        a check that disagrees with everything is no better. ``ThingDetail``
        beside ``thing`` is the shape every family in the tree already has.
        """
        self._family(
            tmp_path,
            """
family: fake
version: 1
types:
  ThingDetail:
    fields: [{ name: a, type: string }]
messages:
  - name: thing
    topic: "m.t"
    transport: [engine_pub]
    doc: { motivation: "fixture", published_by: [engine], since: "1.0" }
    fields: [{ name: x, type: nested, ref: ThingDetail }]
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
        )

    def test_a_nested_field_needs_a_ref(self, tmp_path: Path) -> None:
        with pytest.raises(SpecError, match="requires 'ref: <TypeName>'"):
            self._family(
                tmp_path,
                """
family: fake
version: 1
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: { motivation: "fixture", published_by: [engine], since: "1.0" }
    fields: [{ name: x, type: nested }]
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
            )

    def test_an_unreferenced_type_is_an_error(self, tmp_path: Path) -> None:
        """A type nothing embeds generates a class nothing constructs."""
        with pytest.raises(SpecError, match="never referenced"):
            self._family(
                tmp_path,
                """
family: fake
version: 1
types:
  Leg:
    fields: [{ name: a, type: string }]
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: { motivation: "fixture", published_by: [engine], since: "1.0" }
    fields: [{ name: x, type: string }]
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
            )


class TestNoHotPathBuilderForARecord:
    """``make_*_unchecked`` is a dict-literal builder; a record has no literal.

    Neither combo nor OCO is a measured hot path (design section 14), so the
    honest move is to omit the builder rather than emit a slow one under a name
    that promises speed.
    """

    def test_order_oco_has_no_unchecked_constructor(self) -> None:
        assert not hasattr(G, "make_order_oco_unchecked")

    def test_a_flat_message_in_the_same_family_still_has_one(self) -> None:
        """The omission is per-message, not per-family."""
        assert hasattr(G, "make_order_oco_cancel_unchecked")


class TestTheRealFamilyStillGenerates:
    def test_the_spec_and_the_committed_binding_agree(self) -> None:
        """``pm-msgen check`` in miniature: nested must be deterministic too."""
        from edumatcher.msgen.generators.python import render_family

        transports = load_transports(SPEC_ROOT / "transports.yaml")
        family = load_family(SPEC_ROOT / "messages" / "order.yaml", transports)
        rendered = render_family(family, "spec/messages/order.yaml")
        committed = (REPO_ROOT / "src/edumatcher/models/generated/order.py").read_text(
            encoding="utf-8"
        )
        assert rendered == committed

    def test_generating_twice_gives_the_same_bytes(self) -> None:
        from edumatcher.msgen.generators.python import render_family

        transports = load_transports(SPEC_ROOT / "transports.yaml")
        family = load_family(SPEC_ROOT / "messages" / "order.yaml", transports)
        first = render_family(family, "spec/messages/order.yaml")
        second = render_family(family, "spec/messages/order.yaml")
        assert first == second


class TestListOfRecords:
    """``list[T]``: what ``order.combo`` needed, and the last of design §15.

    Three separate obstacles stood in front of this message, and every one of
    them turned out to be the wire being wrong rather than the IDL being short
    — leg prices whose unit lived in their runtime type, engine state riding on
    a client submission, and only then the missing construct.
    """

    def _combo_payload(self) -> dict[str, object]:
        return {
            "combo_id": "C1",
            "gateway_id": "GW1",
            "combo_type": "AON",
            "tif": "DAY",
            "legs": [
                {
                    "symbol": "AAPL",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "quantity": 10,
                    "price": 9500,
                    "stop_price": None,
                    "smp_action": None,
                },
                {
                    "symbol": "MSFT",
                    "side": "SELL",
                    "order_type": "LIMIT",
                    "quantity": 10,
                    "price": 13000,
                    "stop_price": None,
                    "smp_action": None,
                },
            ],
        }

    def test_it_round_trips(self) -> None:
        combo = G.OrderCombo.from_dict(self._combo_payload())
        assert [leg.symbol for leg in combo.legs] == ["AAPL", "MSFT"]
        assert combo.to_dict() == self._combo_payload()

    def test_the_items_are_the_declared_record(self) -> None:
        combo = G.OrderCombo.from_dict(self._combo_payload())
        assert all(isinstance(leg, G.ComboLeg) for leg in combo.legs)

    def test_it_matches_the_hand_written_submission(self) -> None:
        """Byte-identity against ``ComboOrder.to_submission_dict()``."""
        from edumatcher.models.combo import ComboLeg as ModelLeg
        from edumatcher.models.combo import ComboOrder, ComboType
        from edumatcher.models.order import OrderType, Side, TIF

        combo = ComboOrder.create(
            combo_id="C1",
            gateway_id="GW1",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ModelLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=9500,
                ),
                ModelLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=13000,
                ),
            ],
        )
        assert M.make_combo_order_msg(combo.to_submission_dict()) == (
            G.make_order_combo(**combo.to_submission_dict())
        )

    @pytest.mark.parametrize(
        "count, ok", [(1, False), (2, True), (10, True), (11, False)]
    )
    def test_the_bounds_are_enforced(self, count: int, ok: bool) -> None:
        """``min_items``/``max_items`` were pydantic-only before this.

        ``ComboRequest`` declared ``min_length=2, max_length=10``, so the rule
        held for api_gateway and for nobody else — the ALF console and gateway
        could submit a one-legged combo. Declaring it in the spec is what makes
        it a property of the message rather than of one producer.
        """
        payload = self._combo_payload()
        leg = cast(list[dict[str, object]], payload["legs"])[0]
        payload["legs"] = [dict(leg) for _ in range(count)]

        if ok:
            G.OrderCombo.from_dict(payload).validate()
        else:
            with pytest.raises(MessageValidationError, match="item"):
                G.OrderCombo.from_dict(payload).validate()

    def test_a_bad_leg_is_caught_wherever_it_sits(self) -> None:
        """Validation walks every item, not just the first."""
        payload = self._combo_payload()
        cast(list[dict[str, object]], payload["legs"])[1]["quantity"] = 0
        with pytest.raises(MessageValidationError, match="quantity"):
            G.OrderCombo.from_dict(payload).validate()

    def test_no_unchecked_builder_for_a_list_message(self) -> None:
        assert not hasattr(G, "make_order_combo_unchecked")


class TestTheRestrictionsActuallyRestrict:
    """Found in Phase 5.1e's review, not by the build.

    The JSON-transport-only rule was written, documented and believed for a
    whole phase before anything checked it. It read ``message.encoding``, which
    holds the *bus* encoding only — CALF and BALF live in ``text_encoding`` and
    ``binary_encoding`` — so the condition was always false and the guard never
    fired. A restriction nothing tests is a comment.
    """

    def _family(self, tmp_path: Path, body: str) -> None:
        transports = load_transports(SPEC_ROOT / "transports.yaml")
        path = tmp_path / "fake.yaml"
        path.write_text(body, encoding="utf-8")
        load_family(path, transports)

    def test_a_record_on_a_text_transport_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SpecError, match="record field on"):
            self._family(
                tmp_path,
                """
family: fake
version: 1
types:
  Leg:
    fields: [{ name: a, type: string }]
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub, calf]
    doc: { motivation: "fixture", published_by: [engine], since: "1.0" }
    fields: [{ name: legs, type: list, ref: Leg }]
    encoding:
      engine_pub: { frames: [topic, json_payload], include: all }
      calf: { msg_type: X, include: [legs], keys: { legs: L } }
""",
            )

    def test_a_list_may_not_be_nullable(self, tmp_path: Path) -> None:
        """An empty list already says "nothing"; null would be a second way.

        Left unchecked this generated a ``to_dict`` that iterates ``None``.
        """
        with pytest.raises(SpecError, match="may not be nullable"):
            self._family(
                tmp_path,
                """
family: fake
version: 1
types:
  Leg:
    fields: [{ name: a, type: string }]
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: { motivation: "fixture", published_by: [engine], since: "1.0" }
    fields:
      - { name: legs, type: list, ref: Leg, required: false, nullable: true }
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
            )

    def test_a_list_of_records_may_live_inside_a_record(self, tmp_path: Path) -> None:
        """Also narrowed in 5.2d, for the same reason."""
        if True:
            self._family(
                tmp_path,
                """
family: fake
version: 1
types:
  Inner:
    fields: [{ name: a, type: string }]
  Outer:
    fields: [{ name: b, type: list, ref: Inner }]
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: { motivation: "fixture", published_by: [engine], since: "1.0" }
    fields: [{ name: x, type: nested, ref: Outer }]
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
            )

    def test_a_type_may_not_reference_itself(self, tmp_path: Path) -> None:
        """The recursion the non-recursive generators would not survive.

        Still rejected after 5.2d — only the reason moved from "depth" to
        "cycle", and the message says so.
        """
        with pytest.raises(SpecError, match="cycle"):
            self._family(
                tmp_path,
                """
family: fake
version: 1
types:
  Node:
    fields: [{ name: child, type: nested, ref: Node }]
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: { motivation: "fixture", published_by: [engine], since: "1.0" }
    fields: [{ name: x, type: nested, ref: Node }]
    encoding: { engine_pub: { frames: [topic, json_payload], include: all } }
""",
            )
