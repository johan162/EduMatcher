from __future__ import annotations

import pytest

from edumatcher.alf_gwy.protocol import (
    AlfProtocolError,
    ValidationError,
    build_line,
    parse_alf_line,
    safe_float,
    safe_int,
    validate_hello_fields,
)


def test_parse_alf_line_last_value_wins() -> None:
    frame = parse_alf_line("new|sym=aapl|qty=1|qty=2")
    assert frame.command == "NEW"
    assert frame.fields["QTY"] == "2"


def test_parse_alf_line_skips_segment_without_equals() -> None:
    frame = parse_alf_line("NEW|SYM=AAPL|BROKEN|QTY=1")
    assert frame.command == "NEW"
    assert frame.fields == {"SYM": "AAPL", "QTY": "1"}


def test_parse_alf_line_rejects_empty() -> None:
    with pytest.raises(AlfProtocolError):
        parse_alf_line("\n")


def test_build_line_roundtrip() -> None:
    raw = build_line("ACK", {"ORDER_ID": "abc", "ACCEPTED": "TRUE"})
    parsed = parse_alf_line(raw.decode("utf-8"))
    assert parsed.command == "ACK"
    assert parsed.fields["ORDER_ID"] == "ABC"


def test_safe_int_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        safe_int("9999999999999", "QTY")


@pytest.mark.parametrize(
    ("code", "reject_code"),
    [
        ("BAD_MESSAGE", "MALFORMED_MESSAGE"),
        ("MISSING_FIELD", "MISSING_FIELD"),
        ("SYMBOL_NOT_CONFIGURED", "UNKNOWN_SYMBOL"),
        ("SYMBOLS_NOT_READY", "SYMBOL_NOT_READY"),
        ("RATE_LIMITED", "RATE_LIMITED"),
        ("UNKNOWN_COMMAND", "UNSUPPORTED_FIELD"),
    ],
)
def test_validation_error_maps_to_reject_code(code: str, reject_code: str) -> None:
    assert ValidationError(code, "bad").reject_code == reject_code


@pytest.mark.parametrize("value", ["NAN", "INF", "-INF"])
def test_safe_float_rejects_non_finite(value: str) -> None:
    with pytest.raises(ValidationError):
        safe_float(value, "PRICE")


def test_validate_hello_fields_ok() -> None:
    client, proto, gateway_id = validate_hello_fields(
        {"CLIENT": "BOT", "PROTO": "ALF1", "ID": "TRADER01"}
    )
    assert client == "BOT"
    assert proto == "ALF1"
    assert gateway_id == "TRADER01"


def test_validate_hello_fields_missing_id() -> None:
    with pytest.raises(ValidationError):
        validate_hello_fields({"CLIENT": "BOT", "PROTO": "ALF1"})


# ---------------------------------------------------------------------------
# quote.ack -> ALF QUOTE_ACK carries SYM
# ---------------------------------------------------------------------------


class TestQuoteAckCarriesTheSymbol:
    """`quote.ack.{gateway_id}` is a per-gateway topic, so an ALF client that
    quotes several symbols cannot tell which instrument an ack is for unless
    the gateway passes the symbol through. Before `symbol` existed on the bus
    payload the gateway had nothing to pass, and every text client had to keep
    its own book of outstanding quotes and match by send order.
    """

    @staticmethod
    def _alf_fields(payload: dict[str, object]) -> dict[str, str]:
        """Mirror of the PREFIX_QUOTE_ACK branch in
        ``alf_gwy.gateway._route_gateway_scoped_event``."""
        return {
            "QUOTE_ID": str(payload.get("quote_id", "")),
            "SYM": str(payload.get("symbol", "")),
            "ACCEPTED": "TRUE" if bool(payload.get("accepted", False)) else "FALSE",
            "REASON": str(payload.get("reason", "")),
            "BID_ID": str(payload.get("bid_order_id", "")),
            "ASK_ID": str(payload.get("ask_order_id", "")),
        }

    def test_accepted_ack_reports_the_symbol(self) -> None:
        fields = self._alf_fields(
            {
                "quote_id": "Q1",
                "symbol": "AAPL",
                "accepted": True,
                "bid_order_id": "b1",
                "ask_order_id": "a1",
            }
        )
        assert fields["SYM"] == "AAPL"
        assert fields["ACCEPTED"] == "TRUE"

    def test_rejected_ack_still_reports_the_symbol(self) -> None:
        """A rejection is exactly when a client most needs to know which of its
        quotes failed."""
        fields = self._alf_fields(
            {
                "quote_id": "Q2",
                "symbol": "MSFT",
                "accepted": False,
                "reason": "Market is closed",
            }
        )
        assert fields["SYM"] == "MSFT"
        assert fields["REASON"] == "Market is closed"

    def test_symbol_is_empty_when_the_engine_never_knew_it(self) -> None:
        fields = self._alf_fields({"quote_id": "", "accepted": False, "reason": "bad"})
        assert fields["SYM"] == ""
