"""Phase 6.1c: the auction family, and the falsy sentinel that left the wire.

``imbalance_side`` was ``"BUY"``, ``"SELL"`` or ``""``. It is an enum of the
two real values that omits when unset, which is the same statement to every
reader — all three go through ``str(payload.get(k, "")).upper()`` and skip on
falsy — and says on the wire what the engine's own dataclass comment says.

Section 26.3 records the option that would have broken: a nullable enum, where
``str(None).upper()`` is ``"NONE"`` and the CALF projection would have emitted
``IMB=NONE`` for a balanced book.
"""

from __future__ import annotations

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import auction as G
from edumatcher.models.generated._runtime import MessageValidationError


def _payload(frames: list[bytes]) -> dict:
    return M.decode(frames)[1]


class TestTheBuildersDelegate:
    def test_indicative(self) -> None:
        assert M.make_auction_indicative_msg(
            "AAPL", "OPENING_AUCTION", 150.0, 1000, "BUY", 200
        ) == G.make_auction_indicative(
            symbol="AAPL",
            phase="OPENING_AUCTION",
            eq_price=150.0,
            eq_qty=1000,
            imbalance_side="BUY",
            imbalance_qty=200,
        )

    def test_result(self) -> None:
        assert M.make_auction_result_msg(
            "AAPL", 150.0, 1000, 5, "SELL", 200, "SCHEDULED"
        ) == G.make_auction_result(
            symbol="AAPL",
            eq_price=150.0,
            eq_qty=1000,
            trades_count=5,
            imbalance_side="SELL",
            imbalance_qty=200,
            reason="SCHEDULED",
        )


class TestTheImbalanceSentinel:
    def test_the_empty_string_becomes_an_absent_key(self) -> None:
        """``AuctionResult.imbalance_side`` is "" when balanced, and the
        builder translates that at the boundary rather than on the wire."""
        p = _payload(M.make_auction_result_msg("AAPL", None, 0, 0, "", 0, "REOPEN"))
        assert "imbalance_side" not in p

    def test_a_real_side_survives(self) -> None:
        p = _payload(
            M.make_auction_indicative_msg("AAPL", "CLOSING_AUCTION", 9.0, 1, "BUY", 3)
        )
        assert p["imbalance_side"] == "BUY"

    def test_a_third_value_is_rejected(self) -> None:
        with pytest.raises(MessageValidationError, match="imbalance_side"):
            G.make_auction_result(
                symbol="AAPL",
                eq_price=None,
                eq_qty=0,
                trades_count=0,
                imbalance_side="NONE",
                imbalance_qty=0,
                reason="REOPEN",
            )

    def test_the_normalisers_read_absence_as_balanced(self) -> None:
        """The reason the omission is safe, checked rather than assumed.

        A nullable enum would have put ``null`` here instead, and every one of
        these does ``str(...).upper()`` on what it gets — which is ``"NONE"``
        for ``None``, and truthy. Section 26.3.
        """
        from edumatcher.md_gateway.normaliser import EngineNormaliser

        n = EngineNormaliser()
        _sym, fields = n.normalise_auction_result({"symbol": "AAPL", "eq_qty": 0})
        assert "IMBSIDE" not in fields
        _sym, fields = n.normalise_auction_indicative({"symbol": "AAPL", "eq_qty": 0})
        assert "IMB" not in fields


class TestPresence:
    def test_a_non_crossing_book_sends_a_null_price_not_an_absent_one(self) -> None:
        """Regime 2: "nothing would trade yet" is a reading, not a silence.

        The contrast with ``imbalance_side`` on the same message is deliberate
        — a balanced book has no side to name, but it does have a price that
        is knowably absent.
        """
        p = _payload(
            M.make_auction_indicative_msg("AAPL", "OPENING_AUCTION", None, 0, "", 0)
        )
        assert p["eq_price"] is None
        assert p["eq_qty"] == 0

    def test_zero_quantities_are_emitted(self) -> None:
        p = _payload(M.make_auction_result_msg("AAPL", None, 0, 0, "", 0, "SCHEDULED"))
        assert p["eq_qty"] == 0
        assert p["trades_count"] == 0
        assert p["imbalance_qty"] == 0

    def test_symbol_is_carried_in_the_body(self) -> None:
        """26.4: ``normalise_auction_result`` takes the symbol from the
        payload, not from the topic, so ``include: all`` would have broken it
        silently."""
        for frames in (
            M.make_auction_result_msg("AAPL", 1.0, 1, 1, "", 0, "REOPEN"),
            M.make_auction_indicative_msg("AAPL", "OPENING_AUCTION", 1.0, 1, "", 0),
        ):
            assert _payload(frames)["symbol"] == "AAPL"


class TestTheFourthReason:
    def test_backstop_is_a_declared_value(self) -> None:
        """26.6: ``_run_uncross`` is called with BACKSTOP from the closing
        backstop, and three documents listed only the other three."""
        from typing import get_args

        assert set(get_args(G.AuctionResultReason)) == {
            "SCHEDULED",
            "REOPEN",
            "RECOVERY",
            "BACKSTOP",
        }

    def test_every_reason_the_engine_passes_is_declared(self) -> None:
        """Enumerated from the source rather than from the docstring, which
        is how the fourth one went unrecorded in the first place."""
        import inspect
        import re
        from typing import get_args

        from edumatcher.engine.main import Engine

        source = inspect.getsource(Engine)
        used = set(re.findall(r'_run_uncross\([^)]*reason="([A-Z_]+)"', source))
        assert used == set(get_args(G.AuctionResultReason))


class TestThePhaseEnum:
    def test_it_is_the_two_states_is_auction_phase_admits(self) -> None:
        from typing import get_args

        from edumatcher.models.session import SessionState, is_auction_phase

        assert set(get_args(G.AuctionIndicativePhase)) == {
            s.value for s in SessionState if is_auction_phase(s)
        }


class TestTheTopicsAreDeclared:
    def test_two_topics(self) -> None:
        assert len(G.FAMILY_TOPICS) == 2

    def test_they_are_symbol_addressed(self) -> None:
        assert G.topic_auction_result("AAPL") == "auction.result.AAPL"
        assert G.match_auction_indicative("auction.indicative.AAPL") == "AAPL"
        assert G.match_auction_indicative("auction.result.AAPL") is None

    def test_the_family_owns_no_circuit_breaker_topic(self) -> None:
        assert not any(t.startswith("circuit_breaker.") for t in G.FAMILY_TOPICS)
