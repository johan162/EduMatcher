"""Phase 6.1a: the four multi-leg structure events.

``order.combo`` and ``order.oco`` were specified in 5.1c/5.1d; what became of
them was not. These four events are published on ``combo.*`` and ``oco.*``
topic roots, so they are a family of their own rather than part of ``order`` —
a family file is named after its topic root, which is what FAMILY_TOPICS and
the literal scanner key on.

The find here is the third of a shape this project keeps turning up: a field
one side believes in that the other cannot supply. ``combo.status`` carried a
``details`` mapping with exactly one key, ever, which both consumers unwrapped
on arrival.
"""

from __future__ import annotations

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import structure as G
from edumatcher.models.generated._runtime import MessageValidationError


class TestTheWireIsUnchangedExceptWhereItIsNot:
    def test_combo_ack(self) -> None:
        assert M.make_combo_ack_msg("GW1", "C1", True) == G.make_combo_ack(
            gateway_id="GW1", combo_id="C1", accepted=True, reason=""
        )

    def test_combo_status_without_a_reason(self) -> None:
        assert M.make_combo_status_msg("GW1", "C1", "MATCHED") == G.make_combo_status(
            gateway_id="GW1", combo_id="C1", status="MATCHED", reason=""
        )

    def test_oco_ack(self) -> None:
        assert M.make_oco_ack_msg(
            "GW1", "O1", True, order_id_1="a", order_id_2="b"
        ) == G.make_oco_ack(
            gateway_id="GW1",
            oco_id="O1",
            accepted=True,
            reason="",
            order_id_1="a",
            order_id_2="b",
        )

    def test_oco_cancelled(self) -> None:
        assert M.make_oco_cancelled_msg(
            "GW1", "O1", "a", "sibling filled"
        ) == G.make_oco_cancelled(
            gateway_id="GW1",
            oco_id="O1",
            cancelled_order_id="a",
            reason="sibling filled",
        )


class TestTheMapThatWasOneField:
    """``details: {"reason": ...}`` became ``reason``.

    Design section 15.4 excludes maps on the grounds that a spec appearing to
    need one is describing a message that should have been simpler — usually a
    list of records (section 19.2's ``log.notify`` levels). This is the
    thinnest instance the project has found: not a list of anything, just one
    scalar wrapped in a dict.

    Both consumers proved it. ``alf_console`` did
    ``details.get("reason", "") if details else ""``; ``alf_gwy`` did
    ``if isinstance(details, dict): reason = details.get("reason", "")``. Six
    lines between them to recover one string.
    """

    def test_a_reason_is_a_top_level_string_now(self) -> None:
        _topic, payload = M.decode(
            M.make_combo_status_msg("GW1", "C1", "FAILED", reason="leg expired")
        )
        assert payload["reason"] == "leg expired"
        assert "details" not in payload

    def test_an_absent_reason_omits_the_key(self) -> None:
        """What ``details={"reason": r} if r else None`` did, as a regime."""
        _topic, payload = M.decode(M.make_combo_status_msg("GW1", "C1", "MATCHED"))
        assert "reason" not in payload

    def test_the_producer_passes_a_reason_not_a_mapping(self) -> None:
        import inspect

        from edumatcher.engine.main import Engine

        source = inspect.getsource(Engine._cascade_cancel_combo)
        assert 'details={"reason"' not in source
        assert "reason=reason," in source

    def test_neither_consumer_unwraps_a_mapping_any_more(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src/edumatcher"
        for rel in ("alf_console/main.py", "alf_gwy/gateway.py"):
            source = (root / rel).read_text(encoding="utf-8")
            assert 'payload.get("details"' not in source, rel

    def test_the_idl_still_has_no_map(self) -> None:
        """The exclusion holds because no wire needed one — section 15.4."""
        from edumatcher.msgen.spec import SCALAR_TYPES

        assert "map" not in SCALAR_TYPES
        assert "dict" not in SCALAR_TYPES


class TestPresence:
    def test_the_oco_order_ids_are_always_emitted(self) -> None:
        """ "" on rejection: the builder put them in the base payload."""
        _topic, payload = M.decode(M.make_oco_ack_msg("GW1", "O1", False, "no room"))
        assert payload["order_id_1"] == ""
        assert payload["order_id_2"] == ""

    def test_the_acks_do_not_repeat_the_gateway_in_the_body(self) -> None:
        for frames in (
            M.make_combo_ack_msg("GW1", "C1", True),
            M.make_combo_status_msg("GW1", "C1", "MATCHED"),
            M.make_oco_ack_msg("GW1", "O1", True),
            M.make_oco_cancelled_msg("GW1", "O1", "a"),
        ):
            assert "gateway_id" not in M.decode(frames)[1]

    def test_an_unknown_combo_status_is_rejected(self) -> None:
        with pytest.raises(MessageValidationError, match="status"):
            G.ComboStatus.from_dict(
                {"combo_id": "C1", "status": "SORT_OF_MATCHED"}
            ).validate()

    def test_the_status_enum_matches_the_engine(self) -> None:
        """A status the engine can publish and the spec rejects is a landmine."""
        from typing import get_args

        from edumatcher.models.combo import ComboStatus as EngineStatus

        assert set(get_args(G.ComboStatusStatus)) == {s.value for s in EngineStatus}


class TestTheTopicsAreDeclared:
    def test_four_topics(self) -> None:
        assert len(G.FAMILY_TOPICS) == 4

    def test_the_prefixes_subscribers_use(self) -> None:
        assert G.PREFIX_COMBO_ACK == "combo.ack."
        assert G.PREFIX_COMBO_STATUS == "combo.status."
        assert G.PREFIX_OCO_ACK == "oco.ack."
        assert G.PREFIX_OCO_CANCELLED == "oco.cancelled."

    def test_a_combo_ack_prefix_does_not_match_a_status(self) -> None:
        assert G.match_combo_ack("combo.status.GW1") is None
        assert G.match_combo_ack("combo.ack.GW1") == "GW1"

    def test_the_submissions_live_in_the_order_family(self) -> None:
        """Two roots, two families — which is why this is not order.yaml.

        The registry a family exposes has to be the topics it owns, or a
        router built from FAMILY_TOPICS subscribes to things the family does
        not publish.
        """
        from edumatcher.models.generated import order as gen_order

        assert "order.combo" in gen_order.FAMILY_TOPICS
        assert "order.oco" in gen_order.FAMILY_TOPICS
        assert not any(t.startswith("combo.") for t in gen_order.FAMILY_TOPICS)
        assert not any(t.startswith("oco.") for t in gen_order.FAMILY_TOPICS)
