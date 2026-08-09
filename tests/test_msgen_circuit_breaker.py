"""Phase 6.1c: the circuit_breaker family, and a fork that was a regime.

``circuit_breaker.halt`` has three producers and ``circuit_breaker.resume``
has four, and in each case they disagreed about which keys the payload
carries. Neither is a real fork: the disagreement is entirely about how a
producer spells "unset", and ``md_gateway/normaliser.py`` — the only
structural reader — reaches every one of the contested keys through
``payload.get``. Presence regimes 3 and 4 describe both shapes at once.

Section 26.2 is why the corridor triple stayed flat rather than becoming the
nullable record section 20.1 would suggest.
"""

from __future__ import annotations

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import circuit_breaker as G
from edumatcher.models.generated._runtime import MessageValidationError


def _payload(frames: list[bytes]) -> dict:
    return M.decode(frames)[1]


class TestTheHaltFork:
    """One rule, two producer shapes, no byte change on either."""

    def test_the_price_triggered_halt_carries_the_corridor(self) -> None:
        p = _payload(
            G.make_circuit_breaker_halt(
                symbol="AAPL",
                trigger_price=90.0,
                reference_price=100.0,
                resume_at_ns=123,
                halt_source="CB",
                level="L1",
                corridor_low=95.0,
                corridor_high=105.0,
                expansion=0,
            )
        )
        assert p["corridor_low"] == 95.0
        assert p["corridor_high"] == 105.0
        assert p["expansion"] == 0

    def test_an_admin_halt_carries_no_corridor_keys_at_all(self) -> None:
        """Not ``null`` — absent, which is what the two ADMIN paths sent."""
        p = _payload(
            G.make_circuit_breaker_halt(
                symbol="AAPL",
                trigger_price=None,
                reference_price=None,
                resume_at_ns=None,
                halt_source="ADMIN",
                level="ADMIN_ALL",
            )
        )
        assert "corridor_low" not in p
        assert "corridor_high" not in p
        assert "expansion" not in p

    def test_the_prices_stay_null_rather_than_vanishing(self) -> None:
        """Regime 2, deliberately: all three producers emit these keys.

        The contrast with the corridor triple is the whole point of 26.2 —
        two groups on one message, two regimes, because the producers agree
        about one pair and disagree about the other.
        """
        p = _payload(
            G.make_circuit_breaker_halt(
                symbol="AAPL",
                trigger_price=None,
                reference_price=None,
                resume_at_ns=None,
                halt_source="ADMIN",
                level="ADMIN_SYMBOL",
            )
        )
        assert p["trigger_price"] is None
        assert p["reference_price"] is None
        assert p["resume_at_ns"] is None

    def test_expansion_zero_is_not_mistaken_for_absent(self) -> None:
        """``omit_when_none`` keys on ``None``, not on falsy — 16.1's reason."""
        p = _payload(
            G.make_circuit_breaker_halt(
                symbol="AAPL", halt_source="CB", level="L1", expansion=0
            )
        )
        assert p["expansion"] == 0


class TestTheResumeFork:
    def test_an_ordinary_resume_is_two_keys(self) -> None:
        """Three of the four producers send exactly this."""
        assert _payload(
            G.make_circuit_breaker_resume(symbol="AAPL", halt_source="CB")
        ) == {"symbol": "AAPL", "halt_source": "CB"}

    def test_the_backstop_resume_carries_three_more(self) -> None:
        p = _payload(
            G.make_circuit_breaker_resume(
                symbol="AAPL",
                halt_source="CB",
                reason="CLOSING_BACKSTOP",
                clamped=True,
                print_price=110.0,
            )
        )
        assert p["reason"] == "CLOSING_BACKSTOP"
        assert p["clamped"] is True
        assert p["print_price"] == 110.0

    def test_clamped_false_is_emitted_and_clamped_unset_is_not(self) -> None:
        """A backstop that did not clamp is a different statement from a
        resume where no price was imposed at all, and the wire keeps them
        distinct."""
        emitted = _payload(
            G.make_circuit_breaker_resume(
                symbol="AAPL",
                halt_source="CB",
                reason="CLOSING_BACKSTOP",
                clamped=False,
                print_price=110.0,
            )
        )
        assert emitted["clamped"] is False
        assert "clamped" not in _payload(
            G.make_circuit_breaker_resume(symbol="AAPL", halt_source="CB")
        )

    def test_a_backstop_with_nothing_to_print_omits_the_price(self) -> None:
        """Reachable: ``print_price`` is None when no interest crosses."""
        p = _payload(
            G.make_circuit_breaker_resume(
                symbol="AAPL",
                halt_source="CB",
                reason="CLOSING_BACKSTOP",
                clamped=False,
                print_price=None,
            )
        )
        assert "print_price" not in p


class TestExtendIsTheOneWithoutAFork:
    def test_the_corridor_is_required_here(self) -> None:
        """The only producer has just asserted the corridor exists.

        A ``KeyError`` out of ``from_dict`` rather than a
        ``MessageValidationError``: a missing *required* key never reaches
        ``validate()``, which is the coercion/validation split the IDL draws
        on purpose. The contrast with ``circuit_breaker.halt``, where the same
        three fields omit freely, is 26.2.
        """
        with pytest.raises(KeyError, match="corridor_low"):
            G.make_circuit_breaker_extend(
                symbol="AAPL",
                indicative_price=122.0,
                indicative_qty=500,
                resume_at_ns=9,
                corridor_high=120.0,
                expansion=1,
            )

    def test_a_balanced_book_omits_the_imbalance_side(self) -> None:
        p = _payload(
            G.make_circuit_breaker_extend(
                symbol="AAPL",
                indicative_price=122.0,
                indicative_qty=500,
                imbalance_side=None,
                resume_at_ns=9,
                corridor_low=80.0,
                corridor_high=120.0,
                expansion=1,
            )
        )
        assert "imbalance_side" not in p


class TestTheSymbolIsInTheBodyAsWellAsTheTopic:
    """26.4: ``include: all`` would have dropped it from all three.

    Every consumer reads it from the body — ``alf_gwy`` broadcasts
    ``payload["symbol"]`` — so losing it would have been silent and total.
    """

    @pytest.mark.parametrize(
        "frames",
        [
            G.make_circuit_breaker_halt(symbol="AAPL", halt_source="CB", level="L1"),
            G.make_circuit_breaker_resume(symbol="AAPL", halt_source="CB"),
            G.make_circuit_breaker_extend(
                symbol="AAPL",
                indicative_price=1.0,
                indicative_qty=1,
                resume_at_ns=1,
                corridor_low=1.0,
                corridor_high=2.0,
                expansion=1,
            ),
        ],
    )
    def test_symbol_is_carried_in_the_payload(self, frames: list[bytes]) -> None:
        assert _payload(frames)["symbol"] == "AAPL"


class TestTheBoundsTheAuditAdded:
    def test_a_level_name_longer_than_the_spec_is_rejected(self) -> None:
        with pytest.raises(MessageValidationError, match="level"):
            G.make_circuit_breaker_halt(
                symbol="AAPL", halt_source="ADMIN", level="L" * 33
            )

    def test_a_config_level_name_is_bounded_where_it_is_declared(self) -> None:
        """26.5: bounded at config load, so the error names the config line
        rather than raising inside a generated builder at halt time."""
        from edumatcher.engine import config_loader

        assert config_loader._MAX_CB_LEVEL_NAME == 32

    def test_the_engine_clamps_an_inbound_level_name(self) -> None:
        """26.5: an unknown level is quoted verbatim into a symbol_halt_ack
        whose ``reason`` the risk spec bounds at 512. Unclamped, that raises
        inside the ack builder and the caller gets no answer at all."""
        import inspect

        from edumatcher.engine.main import Engine

        source = inspect.getsource(Engine._handle_symbol_halt)
        assert "_MAX_WIRE_CB_LEVEL_LEN" in source


class TestTheTopicsAreDeclared:
    def test_three_topics(self) -> None:
        assert len(G.FAMILY_TOPICS) == 3

    def test_they_are_symbol_addressed(self) -> None:
        assert G.topic_circuit_breaker_halt("AAPL") == "circuit_breaker.halt.AAPL"
        assert G.match_circuit_breaker_resume("circuit_breaker.resume.AAPL") == "AAPL"
        assert G.match_circuit_breaker_resume("circuit_breaker.halt.AAPL") is None

    def test_the_family_owns_no_auction_topic(self) -> None:
        """24.4: a family advertises only the topics it owns. A reopening
        auction is how a halt ends, which is exactly why the temptation to
        fold the two families together needed answering."""
        assert not any(t.startswith("auction.") for t in G.FAMILY_TOPICS)


class TestTheEnumMirrorsTheEngine:
    def test_halt_source_is_the_two_values_the_engine_sets(self) -> None:
        from typing import get_args

        assert set(get_args(G.CircuitBreakerHaltHaltSource)) == {"CB", "ADMIN"}
