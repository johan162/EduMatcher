from __future__ import annotations

import pytest

from edumatcher.md_gateway.protocol import (
    CalfProtocolError,
    build_line,
    iso_utc,
    parse_line,
)


def test_parse_line_ok() -> None:
    frame = parse_line("HELLO|CLIENT=bot01|PROTO=CALF1")
    assert frame.msg_type == "HELLO"
    assert frame.fields["CLIENT"] == "bot01"


def test_parse_line_rejects_empty() -> None:
    with pytest.raises(CalfProtocolError):
        parse_line("\n")


def test_parse_line_rejects_bad_msgtype() -> None:
    with pytest.raises(CalfProtocolError):
        parse_line("hello|A=B")


def test_parse_line_rejects_missing_equals() -> None:
    with pytest.raises(CalfProtocolError):
        parse_line("HELLO|CLIENT")


def test_build_line_roundtrip() -> None:
    raw = build_line("SUB", {"CH": "TOP", "SYM": "AAPL"})
    frame = parse_line(raw.decode("utf-8"))
    assert frame.msg_type == "SUB"
    assert frame.fields == {"CH": "TOP", "SYM": "AAPL"}


def test_build_line_rejects_pipe_value() -> None:
    with pytest.raises(CalfProtocolError):
        build_line("SUB", {"CH": "TOP|TRADE"})


def test_iso_utc_suffix() -> None:
    out = iso_utc(0.0)
    assert out.endswith("Z")
    assert "1970-01-01T00:00:00" in out
