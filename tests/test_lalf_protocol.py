from __future__ import annotations

import pytest

from edumatcher.logclient.protocol import (
    FrameReader,
    LalfProtocolError,
    build_header_line,
    build_log_frame,
    parse_header_line,
    payload_len,
    validate_log_fields,
)


def test_parse_header_line_ok() -> None:
    msg_type, fields = parse_header_line(
        "HELLO|CLIENT=pm-api-gwy|PID=123|HOST=x|PROTO=LALF1"
    )
    assert msg_type == "HELLO"
    assert fields["CLIENT"] == "pm-api-gwy"
    assert fields["PID"] == "123"


def test_parse_header_line_rejects_empty() -> None:
    with pytest.raises(LalfProtocolError):
        parse_header_line("")


def test_parse_header_line_rejects_bad_msgtype() -> None:
    with pytest.raises(LalfProtocolError):
        parse_header_line("hello|A=B")


def test_parse_header_line_rejects_missing_equals() -> None:
    with pytest.raises(LalfProtocolError):
        parse_header_line("HELLO|CLIENT")


def test_build_header_line_roundtrip() -> None:
    raw = build_header_line("HB", {"TS": "2026-07-28T00:00:00.000Z"})
    msg_type, fields = parse_header_line(raw.decode("utf-8").rstrip("\n"))
    assert msg_type == "HB"
    assert fields == {"TS": "2026-07-28T00:00:00.000Z"}


def test_build_header_line_rejects_pipe_value() -> None:
    with pytest.raises(LalfProtocolError):
        build_header_line("HB", {"TS": "a|b"})


def test_build_header_line_rejects_newline_value() -> None:
    with pytest.raises(LalfProtocolError):
        build_header_line("HB", {"TS": "a\nb"})


# ---------------------------------------------------------------------------
# LOG frame: header + LEN-prefixed payload — the core reason LALF exists
# ---------------------------------------------------------------------------


def test_build_log_frame_roundtrip_via_frame_reader() -> None:
    frame_bytes = build_log_frame(
        seq=1,
        ts="2026-07-28T14:32:07.511Z",
        level="WARNING",
        logger="edumatcher.md_gateway.gateway",
        message="slow client detected on channel DEPTH, symbol AAPL, dropping",
    )
    reader = FrameReader()
    reader.feed(frame_bytes)
    frame = reader.next_frame()
    assert frame is not None
    assert frame.msg_type == "LOG"
    assert frame.fields["SEQ"] == "1"
    assert frame.fields["LEVEL"] == "WARNING"
    assert (
        frame.payload == b"slow client detected on channel DEPTH, symbol AAPL, dropping"
    )
    assert reader.next_frame() is None


def test_log_frame_payload_may_contain_pipes_and_newlines_and_unicode() -> None:
    """The whole reason LALF exists (§5.2): CALF's grammar cannot carry this."""
    message = "line1|weird\nline2 ünïcödé 日本語\nTraceback: ConnectionResetError"
    frame_bytes = build_log_frame(
        seq=2, ts="x", level="ERROR", logger="y.z", message=message, has_exception=True
    )
    reader = FrameReader()
    reader.feed(frame_bytes)
    frame = reader.next_frame()
    assert frame is not None
    assert frame.payload is not None
    assert frame.payload.decode("utf-8") == message
    assert frame.fields["EXC"] == "1"


def test_frame_reader_handles_partial_reads_byte_by_byte() -> None:
    message = "a" * 500 + "\n" + "b" * 500  # payload spans many small chunks
    frame_bytes = build_log_frame(
        seq=3, ts="x", level="INFO", logger="y", message=message
    )

    reader = FrameReader()
    got = None
    for i in range(0, len(frame_bytes), 13):
        reader.feed(frame_bytes[i : i + 13])
        got = reader.next_frame()
        if got is not None:
            break
    assert got is not None
    assert got.payload is not None
    assert got.payload.decode("utf-8") == message


def test_frame_reader_handles_multiple_frames_in_one_feed() -> None:
    two = build_header_line("HB", {"TS": "x"}) + build_header_line("PING")
    reader = FrameReader()
    reader.feed(two)
    f1 = reader.next_frame()
    f2 = reader.next_frame()
    f3 = reader.next_frame()
    assert f1 is not None and f1.msg_type == "HB"
    assert f2 is not None and f2.msg_type == "PING"
    assert f3 is None


def test_build_log_frame_rejects_invalid_level() -> None:
    with pytest.raises(LalfProtocolError):
        build_log_frame(seq=1, ts="x", level="TRACE", logger="y", message="z")


def test_build_log_frame_truncates_oversized_payload_without_splitting_codepoint() -> (
    None
):
    message = "é" * 100  # each char is 2 bytes in utf-8 => 200 bytes total
    frame_bytes = build_log_frame(
        seq=1, ts="x", level="INFO", logger="y", message=message, max_message_bytes=101
    )
    header_line, payload = frame_bytes.split(b"\n", 1)
    _, fields = parse_header_line(header_line.decode())
    n = payload_len(fields)
    assert n is not None
    assert len(payload) == n
    assert n <= 101
    # must decode cleanly — truncation never splits a multi-byte codepoint
    payload.decode("utf-8")


def test_validate_log_fields_missing_field() -> None:
    assert (
        validate_log_fields({"SEQ": "1", "TS": "x", "LEVEL": "INFO"}) == "MISSING_FIELD"
    )


def test_validate_log_fields_invalid_level() -> None:
    fields = {"SEQ": "1", "TS": "x", "LEVEL": "TRACE", "LOGGER": "y", "LEN": "0"}
    assert validate_log_fields(fields) == "INVALID_LEVEL"


def test_validate_log_fields_ok() -> None:
    fields = {"SEQ": "1", "TS": "x", "LEVEL": "INFO", "LOGGER": "y", "LEN": "0"}
    assert validate_log_fields(fields) is None


def test_frame_reader_rejects_oversized_header_line() -> None:
    reader = FrameReader(max_header_line_bytes=32)
    with pytest.raises(LalfProtocolError):
        reader.feed(b"HB|TS=" + b"x" * 100 + b"\n")
        reader.next_frame()
