"""Phase 6.1b: the quote family, and the price unit that was left behind.

Three of the four messages were byte-identical. The fourth, ``quote.new``,
carried display money on a bus where design section 15.2 had made integer
ticks the rule — because that phase converted three inbound paths by name
(``order.new``, ``order.combo``, ``order.oco``) and quotes were not among
them.

Nothing was mispriced. All four producers agreed on display money and the
engine always converted, so there was none of the int-versus-float ambiguity
15.2 removed. What was wrong was the *rule*: its test file states "engine-
inbound prices are ticks, everywhere, with no exceptions", and a developer
who believed it would send ``bid_price: 150`` meaning ticks and have it read
as $150. Section 25.2.
"""

from __future__ import annotations

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import quote as G
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.models.price import to_ticks


class TestTheThreeUnchangedWires:
    def test_quote_cancel(self) -> None:
        assert M.make_quote_cancel_msg("GW1", "ACME") == G.make_quote_cancel(
            gateway_id="GW1", symbol="ACME"
        )

    def test_quote_ack(self) -> None:
        assert M.make_quote_ack_msg(
            "GW1", "Q1", True, bid_order_id="b", ask_order_id="a"
        ) == G.make_quote_ack(
            gateway_id="GW1",
            quote_id="Q1",
            accepted=True,
            reason="",
            bid_order_id="b",
            ask_order_id="a",
        )

    def test_quote_status(self) -> None:
        assert M.make_quote_status_msg(
            "GW1", "Q1", "CANCELLED", "kill switch"
        ) == G.make_quote_status(
            gateway_id="GW1", quote_id="Q1", status="CANCELLED", reason="kill switch"
        )


class TestQuotePricesAreTicksNow:
    def test_the_wire_carries_integers(self) -> None:
        _topic, payload = M.decode(
            G.make_quote_new(
                gateway_id="GW1",
                symbol="AAPL",
                bid_price=to_ticks(99.50, "AAPL"),
                bid_qty=10,
                ask_price=to_ticks(100.50, "AAPL"),
                ask_qty=10,
                tif="DAY",
                quote_id="",
            )
        )
        assert isinstance(payload["bid_price"], int)
        assert payload["bid_price"] == 9950
        assert payload["ask_price"] == 10050

    def test_a_zero_price_is_rejected(self) -> None:
        with pytest.raises(MessageValidationError, match="bid_price"):
            G.make_quote_new(
                gateway_id="GW1",
                symbol="AAPL",
                bid_price=0,
                bid_qty=10,
                ask_price=10050,
                ask_qty=10,
            )

    def test_a_non_positive_quantity_is_rejected(self) -> None:
        with pytest.raises(MessageValidationError, match="qty"):
            G.make_quote_new(
                gateway_id="GW1",
                symbol="AAPL",
                bid_price=9950,
                bid_qty=0,
                ask_price=10050,
                ask_qty=10,
            )

    def test_every_producer_converts(self) -> None:
        """Four gateways, one boundary each — the rule 15.2 set.

        Checked as source rather than behaviour because three of the four need
        a live socket to exercise; what matters is that none of them hands a
        raw display float to the builder.
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src/edumatcher"
        for rel in (
            "api_gateway/translate.py",
            "alf_console/main.py",
            "alf_gwy/gateway.py",
            "mm_bot/bot.py",
        ):
            source = (root / rel).read_text(encoding="utf-8")
            # to_ticks_exact is the checking variant the client-facing edges
            # moved to; alf_gwy wraps it in its own _ticks helper so an
            # off-grid price becomes a REJECT_CODE rather than a rounded one.
            # Either spelling satisfies the rule this test enforces: no raw
            # display float reaches the builder.
            assert (
                "to_ticks(" in source
                or "to_ticks_exact(" in source
                or "self._ticks(" in source
            ), rel
            assert '"bid_price": bid_price,' not in source, rel
            assert '"bid_price": bid,' not in source, rel

    def test_the_engine_no_longer_converts(self) -> None:
        import inspect

        from edumatcher.engine.main import Engine

        source = inspect.getsource(Engine._handle_quote_new)
        # The *call* is gone; the word survives in the docstring that explains
        # why, which is why this looks for the call rather than the name.
        assert "to_ticks(" not in source
        assert "must be integer ticks, not display money" in source

    def test_a_bool_is_not_an_integer_price(self) -> None:
        """``isinstance(True, int)`` is True in Python, so the guard says so.

        Not reachable from any producer, but the OCO guard this mirrors has
        the same hole and it costs one clause to close.
        """
        import inspect

        from edumatcher.engine.main import Engine

        source = inspect.getsource(Engine._handle_quote_new)
        assert "isinstance(value, bool)" in source


class TestPresence:
    def test_an_unset_quote_id_is_absent(self) -> None:
        """The hand-written builders omitted the key rather than sending ""."""
        _topic, payload = M.decode(
            G.make_quote_new(
                gateway_id="GW1",
                symbol="AAPL",
                bid_price=9950,
                bid_qty=10,
                ask_price=10050,
                ask_qty=10,
            )
        )
        assert "quote_id" not in payload

    def test_tif_defaults_to_day(self) -> None:
        _topic, payload = M.decode(
            G.make_quote_new(
                gateway_id="GW1",
                symbol="AAPL",
                bid_price=9950,
                bid_qty=10,
                ask_price=10050,
                ask_qty=10,
            )
        )
        assert payload["tif"] == "DAY"

    def test_the_ack_order_ids_are_always_emitted(self) -> None:
        _topic, payload = M.decode(M.make_quote_ack_msg("GW1", "Q1", False, "closed"))
        assert payload["bid_order_id"] == ""
        assert payload["ask_order_id"] == ""

    def test_the_acks_do_not_repeat_the_gateway_in_the_body(self) -> None:
        for frames in (
            M.make_quote_ack_msg("GW1", "Q1", True),
            M.make_quote_status_msg("GW1", "Q1", "ACTIVE"),
        ):
            assert "gateway_id" not in M.decode(frames)[1]


class TestTheEnumsMirrorTheEngine:
    def test_quote_status_matches_quote_state(self) -> None:
        """A state the engine can publish and the spec rejects is a landmine."""
        from typing import get_args

        from edumatcher.models.quote import QuoteState

        assert set(get_args(G.QuoteStatusStatus)) == {s.value for s in QuoteState}

    def test_tif_matches_the_order_enum(self) -> None:
        """A quote's legs are ordinary orders once they rest."""
        from typing import get_args

        from edumatcher.models.order import TIF

        assert set(get_args(G.QuoteNewTif)) == {t.value for t in TIF}


class TestTheTopicsAreDeclared:
    def test_four_topics(self) -> None:
        assert len(G.FAMILY_TOPICS) == 4

    def test_the_submissions_are_plain(self) -> None:
        assert G.TOPIC_QUOTE_NEW == "quote.new"
        assert G.TOPIC_QUOTE_CANCEL == "quote.cancel"

    def test_the_events_are_addressed(self) -> None:
        assert G.topic_quote_ack("GW1") == "quote.ack.GW1"
        assert G.match_quote_status("quote.status.GW1") == "GW1"
        assert G.match_quote_status("quote.ack.GW1") is None
