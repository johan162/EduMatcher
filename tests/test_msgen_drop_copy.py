"""Phase 6.1d: the drop_copy family, and the map adoption could not tolerate.

``DropCopyPublisher.publish`` took ``payload: dict[str, Any]`` and splatted it
into the message. One caller, one event type, the same five keys every time —
and routed through a generated builder, an undeclared key would have been
dropped in silence. The signature is typed now; section 27.2.

The two messages carry identical bodies and cannot share a ``types:`` record,
because a ``nested`` field is an object on the wire and both readers reach
``seq`` and ``order_id`` at the top level. ``test_the_two_bodies_agree`` is
what keeps the duplicated field lists from drifting; section 27.4.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import drop_copy as G
from edumatcher.models.generated._runtime import MessageValidationError

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src/edumatcher"


def _fill(**overrides: object) -> dict:
    base = {
        "seq": 42,
        "timestamp": 1700000000000000000,
        "gateway_id": "TRADER01",
        "event_type": "order.fill",
        "order_id": "ord-001",
        "trade_ids": ["000001-000000042"],
        "symbol": "MSFT",
        "fill_qty": 100,
        "fill_price": 420.0,
        "liquidity_flag": "MAKER",
    }
    base.update(overrides)
    return base


def _payload(frames: list[bytes]) -> dict:
    return M.decode(frames)[1]


class TestTheTwoBodiesAgree:
    """The duplication the IDL forces, pinned so it cannot drift."""

    def test_the_field_sets_are_identical(self) -> None:
        event = set(G.DropCopyEvent.__dataclass_fields__)
        replay = set(G.DropCopyReplay.__dataclass_fields__) - {"recipient_id"}
        assert event == replay

    def test_the_payloads_are_byte_identical(self) -> None:
        """A replayed fill is the same fill: same seq, same timestamp. Only
        the topic differs, and it names the recipient rather than the
        gateway."""
        fill = _fill()
        live = G.make_drop_copy_event(**fill)
        replayed = G.make_drop_copy_replay(recipient_id="RISK1", **fill)
        assert live[1] == replayed[1]
        assert live[0] == b"drop_copy.event.TRADER01"
        assert replayed[0] == b"drop_copy.replay.RISK1"

    def test_the_recipient_is_not_in_the_body(self) -> None:
        """It identifies who asked, not what happened."""
        p = _payload(G.make_drop_copy_replay(recipient_id="RISK1", **_fill()))
        assert "recipient_id" not in p

    def test_the_gateway_is_in_the_body_of_both(self) -> None:
        """26.4: it is the topic parameter on the live event, so `include:
        all` would have dropped it — and then a replayed fill would not say
        whose it was, because that topic names the recipient instead."""
        assert _payload(G.make_drop_copy_event(**_fill()))["gateway_id"] == "TRADER01"
        assert (
            _payload(G.make_drop_copy_replay(recipient_id="R", **_fill()))["gateway_id"]
            == "TRADER01"
        )


class TestThePublisherIsTyped:
    def test_publish_fill_emits_the_generated_frames(self) -> None:
        from edumatcher.engine.drop_copy import DropCopyMessage

        msg = DropCopyMessage(**_fill())
        assert G.make_drop_copy_event(**_fill()) == G.make_drop_copy_event(
            seq=msg.seq,
            timestamp=msg.timestamp,
            gateway_id=msg.gateway_id,
            event_type=msg.event_type,
            order_id=msg.order_id,
            trade_ids=msg.trade_ids,
            symbol=msg.symbol,
            fill_qty=msg.fill_qty,
            fill_price=msg.fill_price,
            liquidity_flag=msg.liquidity_flag,
        )

    def test_the_generic_signature_is_gone(self) -> None:
        """Not cosmetic: a generic `**payload` over a generated builder drops
        undeclared keys with no error, which is the failure the generator
        exists to remove. Section 27.2."""
        from edumatcher.engine.drop_copy import DropCopyPublisher

        assert not hasattr(DropCopyPublisher, "publish")
        assert hasattr(DropCopyPublisher, "publish_fill")

    def test_the_buffered_message_holds_named_fields(self) -> None:
        from edumatcher.engine.drop_copy import DropCopyMessage

        assert "payload" not in DropCopyMessage.__dataclass_fields__
        assert "liquidity_flag" in DropCopyMessage.__dataclass_fields__

    def test_the_only_engine_call_site_passes_every_field(self) -> None:
        """A missing keyword would be a TypeError at runtime rather than a
        key quietly absent from the wire — which is the whole gain."""
        tree = ast.parse((_SRC / "engine/main.py").read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) == "publish_fill"
        ]
        assert len(calls) == 1
        passed = {kw.arg for kw in calls[0].keywords}
        assert passed == {
            "gateway_id",
            "order_id",
            "trade_ids",
            "symbol",
            "fill_qty",
            "fill_price",
            "liquidity_flag",
        }


class TestTheEnums:
    def test_event_type_has_one_value(self) -> None:
        """A second event type is a spec change with a regenerated binding,
        not a new dict key no reader knows about."""
        from typing import get_args

        assert get_args(G.DropCopyEventEventType) == ("order.fill",)

    def test_liquidity_flag_is_maker_or_taker(self) -> None:
        from typing import get_args

        assert set(get_args(G.DropCopyEventLiquidityFlag)) == {"MAKER", "TAKER"}

    def test_a_third_liquidity_value_is_rejected(self) -> None:
        with pytest.raises(MessageValidationError, match="liquidity_flag"):
            G.make_drop_copy_event(**_fill(liquidity_flag="BOTH"))


class TestTheReadersStillSeeWhatTheySaw:
    def test_the_six_keys_alf_gwy_and_dc_gateway_project(self) -> None:
        """Both relays read exactly these by name, at the top level."""
        p = _payload(G.make_drop_copy_event(**_fill()))
        for key in (
            "seq",
            "order_id",
            "trade_ids",
            "symbol",
            "fill_qty",
            "fill_price",
            "liquidity_flag",
        ):
            assert key in p, key


class TestValidation:
    def test_a_zero_fill_is_rejected(self) -> None:
        with pytest.raises(MessageValidationError, match="fill_qty"):
            G.make_drop_copy_event(**_fill(fill_qty=0))

    def test_seq_starts_above_zero(self) -> None:
        """0 means "no events yet", so it is not a legal sequence number."""
        with pytest.raises(MessageValidationError, match="seq"):
            G.make_drop_copy_event(**_fill(seq=0))

    def test_trade_ids_must_not_be_empty(self) -> None:
        with pytest.raises(MessageValidationError, match="trade_ids"):
            G.make_drop_copy_event(**_fill(trade_ids=[]))

    def test_the_price_is_display_money(self) -> None:
        """Not ticks — `_publish_trade` converts once and hands the same float
        to the position ledger and to here."""
        assert G.describe_drop_copy_event()  # the table exists
        units = {row["name"]: row.get("unit") for row in G.describe_drop_copy_event()}
        assert units["fill_price"] == "display_price"


class TestTheTopicsAreDeclared:
    def test_two_topics(self) -> None:
        assert len(G.FAMILY_TOPICS) == 2

    def test_they_are_differently_addressed(self) -> None:
        assert G.topic_drop_copy_event("TRADER01") == "drop_copy.event.TRADER01"
        assert G.topic_drop_copy_replay("RISK1") == "drop_copy.replay.RISK1"

    def test_there_is_no_replay_request(self) -> None:
        """The module docstring described one for a long time. Replay is
        in-process only and reachable by no protocol. Section 27.3."""
        assert not any("replay_request" in t for t in G.FAMILY_TOPICS)
