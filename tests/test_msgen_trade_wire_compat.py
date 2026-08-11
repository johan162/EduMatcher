"""Wire compatibility for the generated ``trade`` binding (Phases 1 and 2).

Phase 1 proved the generated binding matched the hand-written one (design
section A.5). Phase 2 wired it in: ``make_trade_msg`` delegates to
``make_trade_executed``, ``engine/main.py::_publish_trade`` calls
``make_trade_executed_unchecked``, and ``pm-stats`` uses the generated topic
constant. These tests are what make that adoption reviewable.

Two comparisons of deliberately different strength (design section 8, Phase 2):

* ``make_trade_msg`` vs ``make_trade_executed`` — **byte-identical**. Both
  derive from a ``to_dict()`` over the same fields, so there is no excuse for a
  difference. Likewise ``make_*`` vs ``make_*_unchecked`` (design section 8.2).
* the engine's **pre-Phase-2** inline dict vs what it publishes now —
  **equal key sets and equal parsed values**, not equal bytes. The old literal
  emitted ``tick_decimals`` between ``price`` and ``quantity``; the spec emits
  it last. Nothing on the wire can tell: JSON objects are unordered and every
  consumer reads with ``.get``. Asserting byte-identity there would be stronger
  than the system's actual contract, and would have blocked this change for no
  reason.

One behaviour change is deliberate and tested here: ``make_trade_msg`` now
**validates**. It previously published a zero price, or a payload with no
``aggressor_side``, without complaint. Reading such data back still works —
that is what ``from_dict`` is for — but a producer may no longer create it.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.feed_schema import TradeExecutedPayload
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.models.generated.trade import (
    TOPIC_TRADE_EXECUTED,
    TradeExecuted,
    make_trade_executed,
    make_trade_executed_unchecked,
    parse_trade_executed,
)
from edumatcher.models.message import decode, make_trade_msg

_SAMPLE: dict[str, Any] = {
    "id": "42",
    "symbol": "ACME",
    "buy_order_id": "b-1",
    "sell_order_id": "s-1",
    "buy_gateway_id": "GW1",
    "sell_gateway_id": "GW2",
    "price": 101.5,
    "quantity": 300,
    "aggressor_side": "BUY",
    "timestamp": 1_700_000_000.0,
    "tick_decimals": 2,
}


def _engine_inline_payload(**over: Any) -> dict[str, Any]:
    """Reproduce ``engine/main.py::_publish_trade``'s dict, key order included.

    Kept as a literal rather than imported: the point of the test is to notice
    when the engine's hand-written shape and the spec diverge, and importing
    from the engine would make the two move together silently.
    """
    payload = {
        "id": "42",
        "symbol": "ACME",
        "buy_order_id": "b-1",
        "sell_order_id": "s-1",
        "buy_gateway_id": "GW1",
        "sell_gateway_id": "GW2",
        "price": 101.5,
        "tick_decimals": 2,
        "quantity": 300,
        "aggressor_side": "BUY",
        "timestamp": 1_700_000_000.0,
    }
    payload.update(over)
    return payload


class TestByteIdenticalToHandWrittenFactory:
    """Strong claim: same bytes, because both go through ``to_dict()``."""

    def test_to_dict_matches_including_key_order(self) -> None:
        hand = TradeExecutedPayload.from_dict(_SAMPLE).to_dict()
        generated = TradeExecuted.from_dict(_SAMPLE).to_dict()
        assert generated == hand
        assert list(generated) == list(hand)

    def test_frames_are_byte_identical(self) -> None:
        assert make_trade_executed(**_SAMPLE) == make_trade_msg(_SAMPLE)

    def test_unchecked_frames_are_byte_identical_too(self) -> None:
        assert make_trade_executed_unchecked(**_SAMPLE) == make_trade_msg(_SAMPLE)

    @pytest.mark.parametrize(
        "override",
        [
            {"aggressor_side": "SELL"},
            {"aggressor_side": "AUCTION"},
            {"tick_decimals": 0},
            {"tick_decimals": 8},
            {"price": 0.01},
            {"quantity": 1},
            {"symbol": "A.B_C1"},
            {"id": "999999"},
        ],
    )
    def test_frames_match_across_the_value_space(
        self, override: dict[str, Any]
    ) -> None:
        payload = {**_SAMPLE, **override}
        assert make_trade_executed(**payload) == make_trade_msg(payload)

    def test_topic_frame_is_the_documented_topic(self) -> None:
        frames = make_trade_executed(**_SAMPLE)
        assert frames[0] == TOPIC_TRADE_EXECUTED.encode()

    def test_exactly_two_frames(self) -> None:
        """The sequence third frame belongs to SequencedPublisher, not make_*."""
        assert len(make_trade_executed(**_SAMPLE)) == 2


class TestEquivalentToTheEngineHotPath:
    """Weaker claim, deliberately: same keys and values, order not asserted."""

    def test_key_sets_match(self) -> None:
        generated = TradeExecuted.from_dict(_SAMPLE).to_dict()
        assert set(generated) == set(_engine_inline_payload())

    def test_parsed_values_match(self) -> None:
        generated = TradeExecuted.from_dict(_SAMPLE).to_dict()
        assert generated == _engine_inline_payload()

    def test_the_engine_payload_survives_the_generated_parser(self) -> None:
        """A Phase 2 prerequisite: what the engine publishes today must parse."""
        from edumatcher.models.message import encode

        frames = encode(TOPIC_TRADE_EXECUTED, _engine_inline_payload())
        assert (
            parse_trade_executed(frames).to_dict()
            == TradeExecuted.from_dict(_SAMPLE).to_dict()
        )

    def test_key_order_differs_as_documented(self) -> None:
        """Pins design section 12.3, so the divergence cannot be forgotten.

        ``_engine_inline_payload`` is the shape the engine emitted *before*
        Phase 2. Adoption changed the published key order to the spec's, which
        no consumer can observe: JSON objects are unordered and every reader
        uses ``.get``. This test records that the change happened and was
        intentional.
        """
        generated = list(TradeExecuted.from_dict(_SAMPLE).to_dict())
        engine = list(_engine_inline_payload())
        assert generated != engine
        assert generated[-1] == "tick_decimals"
        assert engine.index("tick_decimals") == engine.index("price") + 1

    def test_unchecked_reproduces_the_pre_phase2_engine_payload(self) -> None:
        """What the engine publishes now must equal what it published before."""
        frames = make_trade_executed_unchecked(**_SAMPLE)
        _topic, payload = decode(frames)
        assert payload == _engine_inline_payload()
        assert frames[0] == TOPIC_TRADE_EXECUTED.encode()


class TestNoDuplicateDescriptionSurvivesUnguarded:
    """``feed_schema.TradeExecutedPayload`` is now a duplicate of the spec.

    Phase 2 made the spec authoritative for the engine, ``make_trade_msg`` and
    pm-stats, but ``feed_schema.TradeExecutedPayload`` is still hand-written and
    still used by ``clearing/main.py::_trade_from_payload``. Two typed
    descriptions of one message is precisely the §1 problem, so until one of
    them is removed (a Phase 5 candidate — see design open question 2) this test
    is what stops them drifting.

    Folding it into an alias of the generated class is the obvious fix and is
    deliberately *not* done here: ``feed_schema`` is imported by
    ``models/message.py``, which the generated module imports, so the alias
    would create an import cycle whose safety depends on statement order within
    ``feed_schema.py``. That is worth doing carefully, not incidentally.
    """

    def test_fields_are_identical(self) -> None:
        import dataclasses

        hand = [
            (f.name, f.type, f.default)
            for f in dataclasses.fields(TradeExecutedPayload)
        ]
        generated = [
            (f.name, f.type, f.default) for f in dataclasses.fields(TradeExecuted)
        ]
        assert hand == generated

    def test_clearing_still_reads_trades_the_same_way(self) -> None:
        """Clearing coerces without validating, which is correct (section 5.1.1).

        It must keep working on payloads the spec would reject, because it
        ingests published history.
        """
        from edumatcher.models.feed_schema import TradeExecutedPayload as Hand

        archived = {k: v for k, v in _SAMPLE.items() if k != "aggressor_side"}
        assert Hand.from_dict(archived).to_dict() == (
            TradeExecuted.from_dict(archived).to_dict()
        )


class TestUncheckedMatchesChecked:
    """Design 8.2: the two constructors must never disagree on the wire."""

    def test_identical_frames_for_the_sample(self) -> None:
        assert make_trade_executed_unchecked(**_SAMPLE) == make_trade_executed(
            **_SAMPLE
        )

    @pytest.mark.parametrize(
        "override",
        [
            {"price": 100},
            {"price": 100.0},
            {"quantity": 7},
            {"tick_decimals": 0},
            {"aggressor_side": "AUCTION"},
            {"timestamp": 1_700_000_000},
            {"id": "1"},
        ],
    )
    def test_identical_frames_across_the_value_space(
        self, override: dict[str, Any]
    ) -> None:
        payload = {**_SAMPLE, **override}
        assert make_trade_executed_unchecked(**payload) == make_trade_executed(
            **payload
        )

    def test_int_price_is_coerced_by_both(self) -> None:
        """The 0.34 us design 8.2 pays for.

        Without inline coercion the unchecked constructor would emit ``100``
        where the validating one emits ``100.0``, and mypy would not catch it
        because int is promotable to float.
        """
        _topic, checked = decode(make_trade_executed(**{**_SAMPLE, "price": 100}))
        _topic2, unchecked = decode(
            make_trade_executed_unchecked(**{**_SAMPLE, "price": 100})
        )
        assert checked["price"] == unchecked["price"] == 100.0
        assert isinstance(unchecked["price"], float)

    def test_unchecked_does_not_validate(self) -> None:
        """It is the hot path's opt-out; that is the whole reason it exists."""
        frames = make_trade_executed_unchecked(**{**_SAMPLE, "quantity": 0})
        _topic, payload = decode(frames)
        assert payload["quantity"] == 0

    def test_topic_is_pre_encoded_once(self) -> None:
        """Matches the engine's own _TRADE_TOPIC optimisation."""
        from edumatcher.models.generated import trade as generated

        first = make_trade_executed_unchecked(**_SAMPLE)[0]
        assert first is generated._TOPIC_TRADE_EXECUTED_BYTES


class TestCoercionMatchesTheHandWrittenPayload:
    """Section 5.1.1: ``from_dict`` coerces, and does so identically."""

    @pytest.mark.parametrize(
        "override",
        [
            {"price": 101},
            {"quantity": "300"},
            {"id": 42},
            {"timestamp": 1_700_000_000},
            {"tick_decimals": "2"},
            {"symbol": "ACME"},
        ],
    )
    def test_loose_input_coerces_the_same_way(self, override: dict[str, Any]) -> None:
        payload = {**_SAMPLE, **override}
        hand = TradeExecutedPayload.from_dict(payload).to_dict()
        generated = TradeExecuted.from_dict(payload).to_dict()
        assert generated == hand
        assert [type(v) for v in generated.values()] == [type(v) for v in hand.values()]

    def test_make_coerces_rather_than_putting_an_int_on_the_wire(self) -> None:
        """The A.3 defect: ``Cls(**kw)`` would emit ``"price": 100``."""
        frames = make_trade_executed(**{**_SAMPLE, "price": 100})
        _topic, payload = decode(frames)
        assert payload["price"] == 100.0
        assert isinstance(payload["price"], float)

    def test_tick_decimals_defaults_to_two_when_absent(self) -> None:
        payload = {k: v for k, v in _SAMPLE.items() if k != "tick_decimals"}
        assert TradeExecuted.from_dict(payload).tick_decimals == 2
        assert TradeExecutedPayload.from_dict(payload).tick_decimals == 2

    def test_a_missing_required_key_raises_keyerror_like_the_hand_written_one(
        self,
    ) -> None:
        payload = {k: v for k, v in _SAMPLE.items() if k != "price"}
        with pytest.raises(KeyError):
            TradeExecuted.from_dict(payload)
        with pytest.raises(KeyError):
            TradeExecutedPayload.from_dict(payload)


class TestArchiveTolerance:
    """The reason ``aggressor_side`` needs ``parse_default`` (section B.7.1)."""

    def test_a_payload_without_aggressor_side_still_parses(self) -> None:
        archived = {k: v for k, v in _SAMPLE.items() if k != "aggressor_side"}
        assert TradeExecuted.from_dict(archived).aggressor_side == ""
        assert TradeExecutedPayload.from_dict(archived).aggressor_side == ""

    def test_but_it_fails_validate(self) -> None:
        """Which is what makes the empty-string population countable."""
        archived = {k: v for k, v in _SAMPLE.items() if k != "aggressor_side"}
        with pytest.raises(MessageValidationError, match="aggressor_side"):
            TradeExecuted.from_dict(archived).validate()

    def test_and_a_producer_cannot_publish_one(self) -> None:
        archived = {k: v for k, v in _SAMPLE.items() if k != "aggressor_side"}
        with pytest.raises(MessageValidationError):
            make_trade_executed(**archived)


class TestValidateRejectsOutOfRange:
    @pytest.mark.parametrize(
        "override",
        [
            {"price": 0},
            {"price": -1.0},
            {"quantity": 0},
            {"quantity": -5},
            {"tick_decimals": -1},
            {"tick_decimals": 9},
            {"aggressor_side": "X"},
            {"aggressor_side": "buy"},
            {"id": "abc"},
            {"id": "4" * 65},
            {"symbol": "acme"},
            {"symbol": "A" * 17},
            {"buy_gateway_id": "G" * 33},
            {"sell_order_id": "s" * 65},
        ],
    )
    def test_rejects(self, override: dict[str, Any]) -> None:
        obj = TradeExecuted.from_dict({**_SAMPLE, **override})
        with pytest.raises(MessageValidationError):
            obj.validate()

    def test_accepts_the_sample(self) -> None:
        TradeExecuted.from_dict(_SAMPLE).validate()

    @pytest.mark.parametrize("side", ["BUY", "SELL", "AUCTION"])
    def test_accepts_every_declared_enum_value(self, side: str) -> None:
        TradeExecuted.from_dict({**_SAMPLE, "aggressor_side": side}).validate()

    def test_error_names_the_offending_field(self) -> None:
        obj = TradeExecuted.from_dict({**_SAMPLE, "price": 0})
        with pytest.raises(MessageValidationError, match="price"):
            obj.validate()


class TestRoundTrip:
    """Capstone assertions 1-3, at Phase 1 (bus-only) scale."""

    def test_make_then_parse_returns_the_original(self) -> None:
        frames = make_trade_executed(**_SAMPLE)
        assert parse_trade_executed(frames) == TradeExecuted.from_dict(_SAMPLE)

    def test_to_dict_then_from_dict_is_identity(self) -> None:
        obj = TradeExecuted.from_dict(_SAMPLE)
        assert TradeExecuted.from_dict(obj.to_dict()) == obj

    def test_parse_validates(self) -> None:
        from edumatcher.models.message import encode

        frames = encode(TOPIC_TRADE_EXECUTED, {**_SAMPLE, "quantity": 0})
        with pytest.raises(MessageValidationError):
            parse_trade_executed(frames)

    def test_parse_ignores_a_sequence_third_frame(self) -> None:
        """SequencedPublisher appends one; decode() reads only two."""
        frames = make_trade_executed(**_SAMPLE)
        assert parse_trade_executed(frames + [b"17"]) == TradeExecuted.from_dict(
            _SAMPLE
        )


class TestPhase2Adoption:
    """Phase 2 wires the binding in. These pin what adoption did and did not change."""

    def test_make_trade_msg_delegates_to_the_generated_constructor(self) -> None:
        assert make_trade_msg(_SAMPLE) == make_trade_executed(**_SAMPLE)

    def test_make_trade_msg_output_is_unchanged_by_adoption(self) -> None:
        """The bytes are what the hand-written payload produced before Phase 2."""
        topic, payload = decode(make_trade_msg(_SAMPLE))
        assert topic == "trade.executed"
        assert payload == TradeExecutedPayload.from_dict(_SAMPLE).to_dict()

    def test_make_trade_msg_now_validates(self) -> None:
        """Deliberate behaviour change: producers are held to the contract.

        Before Phase 2 this published a zero-price trade without complaint.
        """
        with pytest.raises(MessageValidationError):
            make_trade_msg({**_SAMPLE, "price": 0})

    def test_make_trade_msg_rejects_a_missing_aggressor_side(self) -> None:
        """Also deliberate: publishing "" was never intended (design 12.1).

        Reading it back still works — that is what ``from_dict`` is for — but a
        producer may no longer put it on the wire.
        """
        archived = {k: v for k, v in _SAMPLE.items() if k != "aggressor_side"}
        with pytest.raises(MessageValidationError):
            make_trade_msg(archived)
        assert TradeExecuted.from_dict(archived).aggressor_side == ""

    def test_validation_failure_is_still_a_value_error(self) -> None:
        """Callers guarding with `except ValueError` keep working."""
        with pytest.raises(ValueError):
            make_trade_msg({**_SAMPLE, "quantity": 0})

    def test_the_engine_imports_the_unchecked_constructor(self) -> None:
        from edumatcher.models.generated import trade as generated

        source = _read_src("edumatcher/engine/main.py")
        assert "make_trade_executed_unchecked" in source
        assert hasattr(generated, "make_trade_executed_unchecked")

    def test_the_engine_no_longer_hand_writes_the_payload(self) -> None:
        """The point of Phase 2: the field list lives in the spec, not here."""
        source = _read_src("edumatcher/engine/main.py")
        assert '"buy_gateway_id": trade.buy_gateway_id' not in source
        assert '_TRADE_TOPIC = b"trade.executed"' not in source

    def test_pm_stats_uses_the_generated_topic_constant(self) -> None:
        """Design 8.1: the constant is adopted, the tolerant handler is not."""
        from edumatcher.stats.main import TRADE_STREAM

        assert TRADE_STREAM == TOPIC_TRADE_EXECUTED
        source = _read_src("edumatcher/stats/main.py")
        assert 'topic.startswith("trade.executed")' not in source

    def test_no_trade_executed_literal_remains_in_adopted_modules(self) -> None:
        """Design 1.2: adoption is measured by literals removed."""
        for module in (
            "edumatcher/engine/main.py",
            "edumatcher/stats/main.py",
            "edumatcher/models/message.py",
        ):
            source = _read_src(module)
            code = "\n".join(
                line
                for line in source.splitlines()
                if not line.lstrip().startswith("#")
            )
            assert '"trade.executed"' not in code, module
            assert 'b"trade.executed"' not in code, module


def _read_src(relative: str) -> str:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src"
    return (root / relative).read_text(encoding="utf-8")
