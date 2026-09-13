"""The Fact layer: units, clocks and topics (task AR-1.3).

The price tests are what they are because of a wire change: every message
carrying a tick price now carries the ``tick_decimals`` those ticks are at, and
the field names say ``_ticks``. What used to be a five-rung resolution ladder
fed by a pre-pass over the whole log is a dict lookup, so what is left to test
is that the lookup is used, that display prices are passed through untouched,
and that a message which somehow arrives without its declared scale is
reported rather than guessed at.
"""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any

import pytest

from edumatcher.audit.query import AuditEntry, iter_entries
from edumatcher.audit.replay.anomalies import TICK_SCALE_UNKNOWN, UNKNOWN_TOPIC
from edumatcher.audit.replay.facts import (
    CLOCK_CLIENT,
    CLOCK_ENGINE,
    normalise,
    to_fact,
)

_TS = "2026-09-08T09:31:02.118+00:00"


def entry(
    topic: str, payload: dict[str, Any], meta: dict[str, str] | None = None
) -> AuditEntry:
    return AuditEntry(_TS, topic, payload, meta or {}, file="audit.log", line_no=1)


def fact(topic: str, payload: dict[str, Any]) -> Any:
    return to_fact(entry(topic, payload), 0)


def log_line(topic: str, payload: dict[str, Any], meta: str = "") -> str:
    section = f" [{meta}]" if meta else ""
    return f"[{_TS}] [{topic}]{section} {json.dumps(payload)}"


# ---------------------------------------------------------------------------
# Prices (design section 5.3.1)
# ---------------------------------------------------------------------------


class TestTickConversion:
    def test_the_scale_comes_off_the_message(self) -> None:
        """The whole point of the wire change: no lookup, no window, no ladder."""
        f = fact(
            "order.new",
            {"symbol": "AAPL", "tick_decimals": 2, "price_ticks": 7569},
        )
        assert f.prices["price_ticks"].display == pytest.approx(75.69)
        assert f.prices["price_ticks"].render() == "75.69"

    def test_a_four_decimal_symbol_is_not_scaled_by_a_hundred(self) -> None:
        f = fact(
            "order.new",
            {"symbol": "EURUSD", "tick_decimals": 4, "price_ticks": 10875},
        )
        assert f.prices["price_ticks"].display == pytest.approx(1.0875)

    def test_every_tick_field_on_the_message_is_converted(self) -> None:
        f = fact(
            "order.new",
            {
                "symbol": "AAPL",
                "tick_decimals": 2,
                "price_ticks": 7569,
                "stop_price_ticks": 7500,
                "trail_offset_ticks": 25,
            },
        )
        assert set(f.prices) == {
            "price_ticks",
            "stop_price_ticks",
            "trail_offset_ticks",
        }
        assert f.prices["trail_offset_ticks"].display == pytest.approx(0.25)

    def test_a_message_needs_no_help_from_its_neighbours(self) -> None:
        """A single order.new, alone, with nothing else in the window.

        This is the case the pre-pass existed for: before the scale travelled
        with the price, reading a window that did not happen to contain a book
        snapshot for the symbol meant refusing every price in it.
        """
        f = fact(
            "quote.new",
            {
                "gateway_id": "MM01",
                "symbol": "AAPL",
                "tick_decimals": 2,
                "bid_price_ticks": 9950,
                "ask_price_ticks": 10050,
            },
        )
        assert f.prices["bid_price_ticks"].display == pytest.approx(99.50)
        assert f.prices["ask_price_ticks"].display == pytest.approx(100.50)
        assert f.anomalies == ()

    def test_a_display_price_is_passed_through_untouched(self) -> None:
        f = fact(
            "trade.executed",
            {"symbol": "AAPL", "price": 74.80, "quantity": 150, "tick_decimals": 2},
        )
        assert f.prices["price"].display == pytest.approx(74.80)
        assert f.prices["price"].provenance() == "already display money"

    def test_provenance_says_the_scale_was_declared(self) -> None:
        f = fact(
            "order.new",
            {"symbol": "AAPL", "tick_decimals": 2, "price_ticks": 7569},
        )
        assert f.prices["price_ticks"].provenance() == "ticks->display, tick_decimals=2"

    def test_a_missing_price_field_produces_no_price(self) -> None:
        """A MARKET order has no limit, and none is invented for it."""
        f = fact("order.new", {"symbol": "AAPL", "tick_decimals": 2, "quantity": 200})
        assert f.prices == {}
        assert f.anomalies == ()

    def test_a_null_price_produces_no_price(self) -> None:
        f = fact(
            "order.new",
            {"symbol": "AAPL", "tick_decimals": 2, "price_ticks": None},
        )
        assert f.prices == {}


class TestAMessageMissingItsScale:
    """The spec makes `tick_decimals` required wherever a tick price appears,
    so this is a malformed message rather than a gap in the reader. It is still
    reported and still not guessed at: the tool is what someone reaches for
    when the system is already misbehaving."""

    def test_the_price_is_left_in_ticks_and_reported(self) -> None:
        f = fact("order.new", {"symbol": "AAPL", "price_ticks": 7569})
        price = f.prices["price_ticks"]
        assert price.display is None
        assert price.resolved is False
        assert price.raw == 7569
        assert price.render() == "7569 ticks"
        assert [a.code for a in f.anomalies] == [TICK_SCALE_UNKNOWN]

    def test_it_never_defaults_to_two_decimals(self) -> None:
        """The regression this refusal exists to prevent: 7569 for 75.69."""
        f = fact("order.new", {"symbol": "AAPL", "price_ticks": 7569})
        assert f.prices["price_ticks"].display is None

    def test_a_non_integer_scale_is_not_trusted(self) -> None:
        f = fact(
            "order.new",
            {"symbol": "AAPL", "tick_decimals": "2", "price_ticks": 7569},
        )
        assert f.prices["price_ticks"].display is None


# ---------------------------------------------------------------------------
# Clocks (design section 5.3.2)
# ---------------------------------------------------------------------------


class TestClocks:
    def test_receipt_is_parsed_to_aware_utc(self) -> None:
        f = fact("order.new", {"symbol": "AAPL"})
        assert f.receipt_ts.tzinfo is not None
        assert f.receipt_ts.astimezone(timezone.utc).hour == 9
        assert f.receipt_raw == _TS

    def test_order_new_timestamp_is_the_client_clock(self) -> None:
        """It is explicitly not what the book uses for priority."""
        f = fact("order.new", {"symbol": "AAPL", "ts_ns": 1757323862118000000})
        assert f.times["ts_ns"].clock == CLOCK_CLIENT

    def test_trade_ts_ns_is_the_engine_clock(self) -> None:
        f = fact("trade.executed", {"symbol": "AAPL", "ts_ns": 1757323862122334567})
        assert f.times["ts_ns"].clock == CLOCK_ENGINE

    def test_the_two_clocks_are_never_merged(self) -> None:
        """Same unit, different clocks: normalising the unit does not make them
        comparable, and nothing in a Fact pretends otherwise."""
        client = fact("order.new", {"symbol": "AAPL", "ts_ns": 1_000_000_000_000})
        engine = fact("trade.executed", {"symbol": "AAPL", "ts_ns": 1_000_000_000_000})
        assert client.times["ts_ns"].clock == CLOCK_CLIENT
        assert engine.times["ts_ns"].clock == CLOCK_ENGINE
        # Same field name, same unit, same value -- and still not the same
        # reading. Only the topic tells them apart.
        assert client.times["ts_ns"].when == engine.times["ts_ns"].when

    def test_nanos_are_converted_not_truncated(self) -> None:
        f = fact(
            "trade.executed", {"symbol": "AAPL", "ts_ns": 1_757_323_862_122_334_567}
        )
        when = f.times["ts_ns"].when
        assert when.year == 2025 or when.year == 2026
        assert when.microsecond == 122334

    def test_an_absurd_epoch_value_drops_the_field_not_the_line(self) -> None:
        f = fact("trade.executed", {"symbol": "AAPL", "ts_ns": 10**30, "price": 1.0})
        assert "ts_ns" not in f.times
        assert f.kind == "trade.executed"


# ---------------------------------------------------------------------------
# Topic resolution and robustness
# ---------------------------------------------------------------------------


class TestTopicAndEnvelope:
    def test_a_wildcard_topic_is_split(self) -> None:
        f = fact("order.ack.TRADER01", {"order_id": "abc", "accepted": True})
        assert (f.kind, f.actor) == ("order.ack", "TRADER01")

    def test_an_unknown_topic_is_reported_not_guessed(self) -> None:
        f = fact("wibble.frotz", {"anything": 1})
        assert f.known is False
        assert [a.code for a in f.anomalies] == [UNKNOWN_TOPIC]
        assert f.prices == {}

    def test_the_envelope_rides_through(self) -> None:
        f = to_fact(
            entry(
                "trade.executed",
                {"symbol": "AAPL"},
                {"seq": "12", "msg": "01AAA", "cause": "01BBB", "chain": "01CCC"},
            ),
            0,
        )
        assert f.msg_id == "01AAA"
        assert f.causation_id == "01BBB"
        assert f.correlation_id == "01CCC"
        assert f.topic_seq == 12
        assert f.has_envelope is True

    def test_a_declared_origin_is_not_a_missing_envelope(self) -> None:
        """Envelope present, no cause: the publisher stated nothing caused it."""
        f = to_fact(
            entry("trade.executed", {"symbol": "AAPL"}, {"msg": "01AAA"}),
            0,
        )
        assert f.has_envelope is True
        assert f.causation_id is None

    def test_source_coordinates_render_for_show_source(self) -> None:
        f = fact("order.new", {"symbol": "AAPL"})
        assert f.source == "audit.log:1"

    def test_the_payload_is_kept_verbatim(self) -> None:
        """A Fact removes ambiguity; it does not remove information."""
        payload = {"symbol": "AAPL", "price": 7569, "status": "NEW"}
        f = fact("order.new", dict(payload))
        assert f.payload == payload


class TestNormaliseStream:
    def test_ordinals_number_the_stream_not_the_file(self, tmp_path: Path) -> None:
        first = tmp_path / "audit.log.1"
        second = tmp_path / "audit.log"
        first.write_text(log_line("order.new", {"id": "A"}) + "\n", encoding="utf-8")
        second.write_text(log_line("order.new", {"id": "B"}) + "\n", encoding="utf-8")
        facts = list(normalise(iter_entries([first, second])))
        assert [f.ordinal for f in facts] == [0, 1]
        assert [f.line_no for f in facts] == [1, 1]

    def test_one_line_is_enough_to_resolve_its_own_prices(self, tmp_path: Path) -> None:
        """A window holding a single order and nothing else.

        This is the case that used to need a pre-pass over the entire log: the
        scale lived on `book`/`trade.executed`/reference data, and a window not
        containing one for this symbol refused every price in it. The scale now
        travels with the price, so the line is self-sufficient.
        """
        log = tmp_path / "audit.log"
        log.write_text(
            log_line(
                "order.new",
                {"symbol": "AAPL", "tick_decimals": 2, "price_ticks": 7569},
            )
            + "\n",
            encoding="utf-8",
        )
        facts = list(normalise(iter_entries([log])))
        assert len(facts) == 1
        assert facts[0].prices["price_ticks"].display == pytest.approx(75.69)
        assert facts[0].anomalies == ()
