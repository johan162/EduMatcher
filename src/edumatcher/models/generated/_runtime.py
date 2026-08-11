"""Shared runtime support for generated message bindings.

Hand-written and committed - this is the one file under ``generated/`` that is
NOT generated, so it carries no ``DO NOT EDIT`` banner. Every generated family
module imports from here rather than declaring its own error type, which is
what lets a caller write one ``except`` clause for all of them.
"""

from __future__ import annotations

import struct

#: The fixed BALF frame header: magic, version, msg_type, flags, seq_no u32 LE.
#: Implicit in every binary layout — the spec must not declare it, and the
#: generated serialiser writes it (design section B.13).
BALF_HEADER_FMT = "<BBBBI"
BALF_HEADER_SIZE = 8

#: A single **protocol-wide** version byte shared by every binary message, not
#: a per-family number. A family version bump does not change it; changing it
#: is a deliberate protocol-wide decision (design risk R7).
BALF_MAGIC = 0xBA
BALF_VERSION = 0x01

_HEADER = struct.Struct(BALF_HEADER_FMT)


class MessageValidationError(ValueError):
    """A message failed a validation rule declared in its specification.

    Subclasses ``ValueError`` deliberately. The tree already has three
    unrelated validation errors - ``CalfParseError``,
    ``alf_gwy.protocol.ValidationError`` and
    ``balf_gwy.protocol.BalfValidationError`` - none of which fits a generated
    binding, and existing call sites that guard with ``except ValueError``
    keep working unchanged.

    Raised only by a generated ``validate()`` (and therefore by ``make_*`` and
    ``parse_*``, which call it). ``from_dict`` never raises this: it coerces
    without validating, so a reader of historical data can opt out of the
    rules. See section 5.1.1 of
    ``docs-design/EduMatcher-Message-Generator.md``.

    Binary frame parsers also raise it for a bad header or a wrong frame
    length, which are structural failures rather than field-rule ones.
    """


def balf_header(msg_type: int, seq_no: int, flags: int = 0) -> bytes:
    """Return the 8-byte BALF header for one frame."""
    return _HEADER.pack(BALF_MAGIC, BALF_VERSION, msg_type, flags, seq_no)


def check_balf_frame(frame: bytes, msg_type: int, frame_size: int) -> None:
    """Raise unless ``frame`` is a well-formed frame of exactly this type.

    Length is checked as well as magic and type because BALF frames are fixed
    size per ``msg_type``: a frame of the wrong length is not this message, and
    unpacking it anyway would read adjacent bytes as field values and produce a
    plausible-looking result. That failure — no error, just wrong — is the one
    this whole generator exists to remove.
    """
    if len(frame) < BALF_HEADER_SIZE:
        raise MessageValidationError(
            f"frame is {len(frame)} bytes, shorter than the "
            f"{BALF_HEADER_SIZE}-byte header"
        )
    magic, version, actual_type, _flags, _seq = _HEADER.unpack_from(frame, 0)
    if magic != BALF_MAGIC:
        raise MessageValidationError(
            f"bad BALF magic 0x{magic:02X} (expected 0x{BALF_MAGIC:02X})"
        )
    if version != BALF_VERSION:
        raise MessageValidationError(
            f"unsupported BALF version 0x{version:02X} "
            f"(expected 0x{BALF_VERSION:02X})"
        )
    if actual_type != msg_type:
        raise MessageValidationError(
            f"msg_type 0x{actual_type:02X} is not 0x{msg_type:02X}"
        )
    if len(frame) != frame_size:
        raise MessageValidationError(
            f"msg_type 0x{msg_type:02X} frames are {frame_size} bytes; got "
            f"{len(frame)}"
        )


def balf_seq_no(frame: bytes) -> int:
    """Return the per-session sequence number from a frame header."""
    return int(_HEADER.unpack_from(frame, 0)[4])
