from __future__ import annotations

import pytest

from edumatcher.dc_gateway.protocol import (
    DcProtocolError,
    build_line,
    iso_utc,
    parse_line,
)


def test_parse_line_basic() -> None:
    frame = parse_line("HELLO|CLIENT=test|PROTO=DC1|ID=TRADER01")
    assert frame.msg_type == "HELLO"
    assert frame.fields == {"CLIENT": "test", "PROTO": "DC1", "ID": "TRADER01"}


def test_parse_line_no_fields() -> None:
    frame = parse_line("PING")
    assert frame.msg_type == "PING"
    assert frame.fields == {}


def test_parse_line_strips_crlf() -> None:
    frame = parse_line("PING\r\n")
    assert frame.msg_type == "PING"


def test_parse_line_empty_raises() -> None:
    with pytest.raises(DcProtocolError):
        parse_line("")


def test_parse_line_bad_msgtype_raises() -> None:
    with pytest.raises(DcProtocolError):
        parse_line("bad-type|X=1")


def test_parse_line_missing_equals_raises() -> None:
    with pytest.raises(DcProtocolError):
        parse_line("HELLO|NOEQUALS")


def test_parse_line_empty_key_raises() -> None:
    with pytest.raises(DcProtocolError):
        parse_line("HELLO|=value")


def test_build_line_roundtrip() -> None:
    raw = build_line("WELCOME", {"PROTO": "DC1", "GW": "dc-gwy01"})
    assert raw == b"WELCOME|PROTO=DC1|GW=dc-gwy01\n"
    frame = parse_line(raw.decode("utf-8"))
    assert frame.msg_type == "WELCOME"
    assert frame.fields["GW"] == "dc-gwy01"


def test_build_line_no_fields() -> None:
    raw = build_line("PONG")
    assert raw == b"PONG\n"


def test_build_line_bad_msgtype_raises() -> None:
    with pytest.raises(DcProtocolError):
        build_line("bad type")


def test_build_line_pipe_in_value_raises() -> None:
    with pytest.raises(DcProtocolError):
        build_line("ERR", {"DETAIL": "a|b"})


def test_build_line_empty_key_raises() -> None:
    with pytest.raises(DcProtocolError):
        build_line("ERR", {"": "value"})


def test_iso_utc_format() -> None:
    formatted = iso_utc(1700000000.123)
    assert formatted.endswith("Z")
    assert "T" in formatted
