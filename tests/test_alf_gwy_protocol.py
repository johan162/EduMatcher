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
