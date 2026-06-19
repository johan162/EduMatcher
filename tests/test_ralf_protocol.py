from __future__ import annotations

import pytest

from edumatcher.ralf_gateway.protocol import (
    RalfProtocolError,
    build_line,
    iso_utc,
    parse_line,
)


def test_parse_line_ok() -> None:
    frame = parse_line("HELLO|CLIENT=x|PROTO=RALF1|ROLE=CLEARING")
    assert frame.msg_type == "HELLO"
    assert frame.fields["CLIENT"] == "x"
    assert frame.fields["PROTO"] == "RALF1"


def test_parse_line_rejects_empty() -> None:
    with pytest.raises(RalfProtocolError):
        parse_line("\n")


def test_parse_line_rejects_bad_msgtype() -> None:
    with pytest.raises(RalfProtocolError):
        parse_line("hello|A=B")


def test_parse_line_rejects_missing_equals() -> None:
    with pytest.raises(RalfProtocolError):
        parse_line("HELLO|CLIENT")


def test_build_line_roundtrip() -> None:
    raw = build_line("SUB", {"CH": "CLEARING", "SYM": "*"})
    frame = parse_line(raw.decode("utf-8"))
    assert frame.msg_type == "SUB"
    assert frame.fields == {"CH": "CLEARING", "SYM": "*"}


def test_build_line_rejects_bad_msgtype() -> None:
    with pytest.raises(RalfProtocolError):
        build_line("bad", {})


def test_build_line_rejects_pipe_in_value() -> None:
    with pytest.raises(RalfProtocolError):
        build_line("EXEC", {"CH": "CLEAR|ING"})


def test_iso_utc_has_z_suffix() -> None:
    text = iso_utc(0.0)
    assert text.endswith("Z")
    assert "1970-01-01T00:00:00" in text
