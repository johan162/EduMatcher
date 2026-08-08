"""Parsed-spec data model and strict YAML loader.

This is the generator's own contract: the typed shape every generator consumes.
It is hand-written, never generated.

The loader is deliberately **strict**. An unknown key raises rather than being
ignored, because ``requird: true`` silently disabling a field is precisely the
failure class this whole tool exists to remove (design section A.2, B.18 rule
15).

Phase 1 implements the subset of Appendix B the ``trade`` family needs: bus
encodings, scalar and enum fields, the full ``validate`` vocabulary. Text and
binary encodings, nested types, invariants and deprecation are Phases 4-6 and
are rejected with a clear message rather than silently accepted.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class SpecError(ValueError):
    """A spec file is malformed or violates a static semantic rule.

    Subclasses ``ValueError`` so a caller that already guards a load with
    ``except ValueError`` keeps working.
    """


# --------------------------------------------------------------------------
# Closed vocabularies (design sections B.9, B.11, B.12, B.4)
# --------------------------------------------------------------------------

#: Scalar types Phase 1 can generate. ``nested`` and ``list[T]`` are Appendix
#: B constructs that no Phase 1 spec uses; they are rejected explicitly rather
#: than half-supported.
SCALAR_TYPES = ("string", "int", "float", "bool", "enum", "ticks")

#: Complete enumeration from design section B.11.
UNITS = (
    "display_price",
    "ticks",
    "shares",
    "epoch_seconds",
    "epoch_nanos",
    "percent",
    "dimensionless",
    "money",
)

#: Numeric types for which lint requires a declared ``unit`` (B.18 rule 13).
NUMERIC_TYPES = ("int", "float", "ticks")

#: ZeroMQ / external-protocol patterns (design section B.4).
PATTERNS = ("PUB", "SUB", "PUSH", "PULL", "TCP")

#: Reserved external line/binary protocol names (design section B.4).
EXTERNAL_TRANSPORTS = ("calf", "balf", "ralf")

#: External protocols carrying key=value text lines. Generated in Phase 4a.
TEXT_TRANSPORTS = ("calf", "ralf")

#: External protocols carrying fixed binary frames. Phase 4b.
BINARY_TRANSPORTS = ("balf",)

#: Tokens allowed in a bus ``frames`` list (design section B.13).
FRAME_TOKENS = ("topic", "json_payload")


@dataclass(frozen=True)
class Validate:
    """The ``validate:`` block. Complete vocabulary, design section B.12."""

    gt: float | None = None
    ge: float | None = None
    lt: float | None = None
    le: float | None = None
    max_len: int | None = None
    min_len: int | None = None
    max_items: int | None = None
    pattern: str | None = None


@dataclass(frozen=True)
class Field:
    """One field of a message (design section B.7)."""

    name: str
    type: str
    required: bool = True
    default: Any = None
    #: Lenient fallback used by ``from_dict`` only; need not be a legal value.
    #: See design section B.7.1 for why this is distinct from ``default``.
    parse_default: Any = None
    unit: str | None = None
    doc: str = ""
    values: tuple[str, ...] | None = None
    item: str | None = None
    validate: Validate = field(default_factory=Validate)
    deprecated_since: str | None = None
    removed_after: str | None = None
    #: True when ``parse_default:`` was present, so the generator can tell a
    #: declared ``parse_default: ""`` from an absent one (both are falsy).
    has_parse_default: bool = False


@dataclass(frozen=True)
class BusEncoding:
    """A bus (ZeroMQ) projection (design section B.13)."""

    transport: str
    frames: tuple[str, ...] = ("topic", "json_payload")
    include: tuple[str, ...] | None = None  # None means "all"


@dataclass(frozen=True)
class TextEncoding:
    """A CALF/RALF line projection (design section B.13).

    ``keys`` maps each included field to one or more wire keys; a field may
    feed several (RALF's ``id: [EXEC_ID, MATCH_ID]``).

    ``gateway_injected`` is **documentation only**. The generated projection
    never emits these keys — the gateway supplies them in its own envelope, and
    the two gateways do so in different positions, so their order here carries
    no meaning (design section B.13, corrected in 1.8.0).
    """

    transport: str
    msg_type: str
    include: tuple[str, ...]
    keys: dict[str, tuple[str, ...]]
    gateway_injected: tuple[str, ...] = ()


@dataclass(frozen=True)
class Message:
    """One message within a family (design section B.6)."""

    name: str
    topic: str | None
    transport: tuple[str, ...]
    fields: tuple[Field, ...]
    doc: dict[str, Any] = field(default_factory=dict)
    encoding: dict[str, BusEncoding] = field(default_factory=dict)
    text_encoding: dict[str, TextEncoding] = field(default_factory=dict)

    @property
    def topic_params(self) -> tuple[str, ...]:
        """The ``{param}`` names in ``topic``, in order of appearance."""
        return tuple(_topic_params(self.topic)) if self.topic else ()

    def field_by_name(self, name: str) -> Field:
        """Return the declared field called ``name``."""
        for candidate in self.fields:
            if candidate.name == name:
                return candidate
        raise KeyError(name)


@dataclass(frozen=True)
class Family:
    """One family file (design section B.5)."""

    family: str
    version: int
    messages: tuple[Message, ...]


@dataclass(frozen=True)
class Transport:
    """One transport registry entry (design section B.4)."""

    name: str
    pattern: str
    address_config_key: str
    subscriber_pattern: str | None = None

    @property
    def is_bus(self) -> bool:
        """True for ZeroMQ transports, False for external line/binary ones."""
        return self.pattern != "TCP"


_FIELD_KEYS = {f.name for f in dataclasses.fields(Field)} - {"has_parse_default"}
_VALIDATE_KEYS = {f.name for f in dataclasses.fields(Validate)}
_MESSAGE_KEYS = {
    "name",
    "topic",
    "transport",
    "doc",
    "fields",
    "nested_types",
    "encoding",
    "invariants",
}
_DOC_KEYS = {"motivation", "since", "see_also", "example_note"}
_BUS_ENCODING_KEYS = {"frames", "include"}
_TEXT_ENCODING_KEYS = {"msg_type", "include", "keys", "gateway_injected"}

#: design section B.3: a CALF/RALF wire key and MSGTYPE are SCREAMING_SNAKE.
_KEY_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
_MSG_TYPE_TEXT = re.compile(r"[A-Z][A-Z0-9_]*")
_TRANSPORT_KEYS = {"pattern", "subscriber_pattern", "address_config_key"}

_UNSUPPORTED_MESSAGE_KEYS = {
    "nested_types": "nested types are Phase 4",
    "invariants": "invariant expressions are Phase 4",
}


def _topic_params(topic: str) -> list[str]:
    """Return the ``{param}`` names in a topic pattern, in order."""
    params: list[str] = []
    rest = topic
    while "{" in rest:
        start = rest.index("{")
        if "}" not in rest[start:]:
            raise SpecError(f"topic {topic!r}: unbalanced '{{'")
        end = rest.index("}", start)
        params.append(rest[start + 1 : end])
        rest = rest[end + 1 :]
    return params


def _require_mapping(raw: Any, what: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SpecError(f"{what}: expected a mapping, got {type(raw).__name__}")
    return raw


def _reject_unknown(raw: dict[str, Any], allowed: set[str], what: str) -> None:
    """Raise on any key outside ``allowed``, suggesting a near match.

    The suggestion is what turns "unknown key" into an actionable message; the
    threshold of 2 edits matches design section 7.5.5.
    """
    unknown = sorted(set(raw) - allowed)
    if not unknown:
        return
    parts = []
    for key in unknown:
        near = _nearest(key, allowed)
        parts.append(f"{key!r}" + (f" (did you mean {near!r}?)" if near else ""))
    raise SpecError(f"{what}: unknown key(s) {', '.join(parts)}")


def _nearest(word: str, candidates: set[str]) -> str | None:
    """Return the closest candidate within edit distance 2, or None."""
    best: tuple[int, str] | None = None
    for cand in sorted(candidates):
        dist = _levenshtein(word, cand)
        if dist <= 2 and (best is None or dist < best[0]):
            best = (dist, cand)
    return best[1] if best else None


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _load_validate(raw: Any, what: str) -> Validate:
    if raw is None:
        return Validate()
    block = _require_mapping(raw, f"{what}: validate")
    _reject_unknown(block, _VALIDATE_KEYS, f"{what}: validate")
    return Validate(**block)


def _load_field(raw: Any, what: str) -> Field:
    block = _require_mapping(raw, what)
    if "name" not in block:
        raise SpecError(f"{what}: missing required key 'name'")
    name = block["name"]
    where = f"{what} ({name!r})"
    _reject_unknown(block, _FIELD_KEYS, where)
    if "type" not in block:
        raise SpecError(f"{where}: missing required key 'type'")

    ftype = block["type"]
    if ftype not in SCALAR_TYPES:
        near = _nearest(str(ftype), set(SCALAR_TYPES))
        hint = f" (did you mean {near!r}?)" if near else ""
        raise SpecError(
            f"{where}: type {ftype!r} is not one of {list(SCALAR_TYPES)}{hint}. "
            "list[T] and nested are Appendix B constructs not yet generated."
        )

    values = block.get("values")
    if ftype == "enum":
        if not values:
            raise SpecError(f"{where}: an enum field requires a non-empty 'values'")
        if not isinstance(values, list):
            raise SpecError(f"{where}: 'values' must be a list")
    elif values is not None:
        raise SpecError(f"{where}: 'values' is only meaningful for type: enum")

    unit = block.get("unit")
    if unit is not None and unit not in UNITS:
        near = _nearest(str(unit), set(UNITS))
        hint = f" (did you mean {near!r}?)" if near else ""
        raise SpecError(f"{where}: unit {unit!r} is not one of {list(UNITS)}{hint}")
    if unit is None and ftype in NUMERIC_TYPES:
        raise SpecError(
            f"{where}: a numeric field requires a declared 'unit' "
            f"(one of {list(UNITS)})"
        )

    if block.get("deprecated_since") and not block.get("doc"):
        raise SpecError(f"{where}: a deprecated field requires a non-empty 'doc'")

    # An optional field with no default would have to generate as `X | None`,
    # and every rule in validate() would then need a None guard. No Phase 1
    # spec needs that, so require the default rather than generate the
    # Optional machinery speculatively.
    if not block.get("required", True) and "default" not in block:
        raise SpecError(
            f"{where}: a field with 'required: false' must declare a 'default'"
        )

    return Field(
        name=name,
        type=ftype,
        required=block.get("required", True),
        default=block.get("default"),
        parse_default=block.get("parse_default"),
        unit=unit,
        doc=block.get("doc", ""),
        values=tuple(values) if values else None,
        item=block.get("item"),
        validate=_load_validate(block.get("validate"), where),
        deprecated_since=block.get("deprecated_since"),
        removed_after=block.get("removed_after"),
        has_parse_default="parse_default" in block,
    )


def _load_bus_encoding(
    transport: str, raw: Any, field_names: list[str], what: str
) -> BusEncoding:
    block = _require_mapping(raw, what)
    _reject_unknown(block, _BUS_ENCODING_KEYS, what)

    frames = block.get("frames", list(FRAME_TOKENS))
    if not isinstance(frames, list) or not frames:
        raise SpecError(f"{what}: 'frames' must be a non-empty list")
    for token in frames:
        if token not in FRAME_TOKENS:
            raise SpecError(
                f"{what}: frame token {token!r} is not one of {list(FRAME_TOKENS)}. "
                "The per-topic sequence frame is added by SequencedPublisher at "
                "publish time and must not be declared."
            )

    include = block.get("include", "all")
    if include == "all":
        resolved: tuple[str, ...] | None = None
    elif isinstance(include, list):
        for name in include:
            if name not in field_names:
                near = _nearest(str(name), set(field_names))
                hint = f" (did you mean {near!r}?)" if near else ""
                raise SpecError(
                    f"{what}: include names undeclared field {name!r}{hint}"
                )
        resolved = tuple(include)
    else:
        raise SpecError(f"{what}: 'include' must be 'all' or a list of field names")

    return BusEncoding(transport=transport, frames=tuple(frames), include=resolved)


def _load_text_encoding(
    transport: str, raw: Any, fields: tuple[Field, ...], what: str
) -> TextEncoding:
    """Load a CALF/RALF encoding block and enforce B.18 rules 4, 6 and 8."""
    block = _require_mapping(raw, what)
    _reject_unknown(block, _TEXT_ENCODING_KEYS, what)

    msg_type = block.get("msg_type")
    if not msg_type or not isinstance(msg_type, str):
        raise SpecError(f"{what}: 'msg_type' is required for a text encoding")
    if not _MSG_TYPE_TEXT.fullmatch(msg_type):
        raise SpecError(
            f"{what}: msg_type {msg_type!r} must be SCREAMING_SNAKE "
            "(design section B.3)"
        )

    field_names = [f.name for f in fields]
    include = block.get("include", "all")
    if include == "all":
        resolved = tuple(field_names)
    elif isinstance(include, list):
        for name in include:
            if name not in field_names:
                near = _nearest(str(name), set(field_names))
                hint = f" (did you mean {near!r}?)" if near else ""
                raise SpecError(
                    f"{what}: include names undeclared field {name!r}{hint}"
                )
        resolved = tuple(include)
    else:
        raise SpecError(f"{what}: 'include' must be 'all' or a list of field names")

    injected = block.get("gateway_injected") or []
    if not isinstance(injected, list):
        raise SpecError(f"{what}: 'gateway_injected' must be a list of key names")
    for key in injected:
        if not isinstance(key, str) or not _KEY_NAME.fullmatch(key):
            raise SpecError(
                f"{what}: gateway_injected key {key!r} must be SCREAMING_SNAKE"
            )

    raw_keys = _require_mapping(block.get("keys") or {}, f"{what}: keys")
    # B.18 rule 6: keys covers exactly the included fields, no more, no fewer.
    missing = [name for name in resolved if name not in raw_keys]
    if missing:
        raise SpecError(
            f"{what}: 'keys' has no wire name for included field(s) {missing}"
        )
    extra = [name for name in raw_keys if name not in resolved]
    if extra:
        raise SpecError(f"{what}: 'keys' names field(s) {extra} that 'include' omits")

    keys: dict[str, tuple[str, ...]] = {}
    seen: dict[str, str] = {}
    for name in resolved:
        target = raw_keys[name]
        wire = (target,) if isinstance(target, str) else tuple(target)
        if not wire:
            raise SpecError(f"{what}: field {name!r} maps to an empty key list")
        for key in wire:
            if not isinstance(key, str) or not _KEY_NAME.fullmatch(key):
                raise SpecError(f"{what}: wire key {key!r} must be SCREAMING_SNAKE")
            if key in seen:
                raise SpecError(
                    f"{what}: wire key {key!r} is produced by both "
                    f"{seen[key]!r} and {name!r}"
                )
            # B.18 rule 6: an injected key must not collide with a payload key,
            # or the gateway envelope and the projection would fight over it.
            if key in injected:
                raise SpecError(
                    f"{what}: wire key {key!r} for field {name!r} collides with a "
                    "gateway_injected key"
                )
            seen[key] = name
        keys[name] = wire

    # B.18 rule 8: a string reaching an external transport needs max_len, since
    # the C binding must size a fixed buffer for it.
    by_name = {f.name: f for f in fields}
    for name in resolved:
        spec_field = by_name[name]
        if spec_field.type == "string" and spec_field.validate.max_len is None:
            raise SpecError(
                f"{what}: field {name!r} is a string reaching transport "
                f"{transport!r} and needs validate.max_len so the C binding can "
                "size its buffer"
            )

    return TextEncoding(
        transport=transport,
        msg_type=msg_type,
        include=resolved,
        keys=keys,
        gateway_injected=tuple(injected),
    )


def _load_message(raw: Any, transports: dict[str, Transport], what: str) -> Message:
    block = _require_mapping(raw, what)
    if "name" not in block:
        raise SpecError(f"{what}: missing required key 'name'")
    name = block["name"]
    where = f"{what} ({name!r})"
    _reject_unknown(block, _MESSAGE_KEYS, where)

    for key, reason in _UNSUPPORTED_MESSAGE_KEYS.items():
        if key in block:
            raise SpecError(f"{where}: {key!r} is not supported yet - {reason}")

    raw_fields = block.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise SpecError(f"{where}: 'fields' is required and must be non-empty")
    fields = tuple(
        _load_field(f, f"{where}.fields[{i}]") for i, f in enumerate(raw_fields)
    )
    field_names = [f.name for f in fields]
    dupes = sorted({n for n in field_names if field_names.count(n) > 1})
    if dupes:
        raise SpecError(f"{where}: duplicate field name(s) {dupes}")

    raw_transport = block.get("transport")
    if not isinstance(raw_transport, list) or not raw_transport:
        raise SpecError(f"{where}: 'transport' is required and must be non-empty")
    for tname in raw_transport:
        if tname in BINARY_TRANSPORTS:
            raise SpecError(
                f"{where}: transport {tname!r} is a binary protocol; its layout "
                "is not generated yet (Phase 4b)."
            )
        if tname in TEXT_TRANSPORTS:
            continue
        if tname not in transports:
            near = _nearest(str(tname), set(transports))
            hint = f" (did you mean {near!r}?)" if near else ""
            raise SpecError(
                f"{where}: transport {tname!r} is absent from "
                f"spec/transports.yaml{hint}"
            )

    bus_transports = [t for t in raw_transport if t not in TEXT_TRANSPORTS]
    topic = block.get("topic")
    if topic is None:
        raise SpecError(f"{where}: 'topic' is required for a bus message")
    if not bus_transports:
        raise SpecError(
            f"{where}: a message with no bus transport must omit 'topic' "
            "(design section B.6) - text-only messages are Phase 4b"
        )
    if not isinstance(topic, str) or not topic:
        raise SpecError(f"{where}: 'topic' must be a non-empty string")
    for param in _topic_params(topic):
        if param not in field_names:
            near = _nearest(param, set(field_names))
            hint = f" (did you mean {near!r}?)" if near else ""
            raise SpecError(
                f"{where}: topic parameter {{{param}}} is not a field of "
                f"this message{hint}"
            )

    doc = block.get("doc") or {}
    doc = _require_mapping(doc, f"{where}.doc")
    _reject_unknown(doc, _DOC_KEYS, f"{where}.doc")
    if not doc.get("motivation"):
        raise SpecError(f"{where}: doc.motivation is required")

    raw_encoding = block.get("encoding") or {}
    raw_encoding = _require_mapping(raw_encoding, f"{where}.encoding")
    for tname in raw_encoding:
        if tname not in raw_transport:
            raise SpecError(
                f"{where}.encoding: {tname!r} is not listed in this message's "
                "'transport'"
            )
    # A text transport's block is REQUIRED: `keys` and `msg_type` have no
    # defensible default, since nothing can infer a wire key name (B.6).
    for tname in raw_transport:
        if tname in TEXT_TRANSPORTS and tname not in raw_encoding:
            raise SpecError(
                f"{where}: transport {tname!r} requires an 'encoding.{tname}' "
                "block declaring msg_type and keys"
            )

    encoding = {
        tname: _load_bus_encoding(
            tname,
            raw_encoding.get(tname, {}),
            field_names,
            f"{where}.encoding.{tname}",
        )
        for tname in bus_transports
    }
    text_encoding = {
        tname: _load_text_encoding(
            tname,
            raw_encoding[tname],
            fields,
            f"{where}.encoding.{tname}",
        )
        for tname in raw_transport
        if tname in TEXT_TRANSPORTS
    }

    # B.18 rule 5: every required field must reach the authoritative bus
    # projection. With one bus transport in Phase 1 this is unambiguous.
    for enc in encoding.values():
        if enc.include is None:
            continue
        missing = [f.name for f in fields if f.required and f.name not in enc.include]
        if missing:
            raise SpecError(
                f"{where}.encoding.{enc.transport}: required field(s) {missing} "
                "are absent from the bus projection's 'include'"
            )

    return Message(
        name=name,
        topic=topic,
        transport=tuple(raw_transport),
        fields=fields,
        doc=dict(doc),
        encoding=encoding,
        text_encoding=text_encoding,
    )


def load_transports(path: Path) -> dict[str, Transport]:
    """Load and validate ``spec/transports.yaml`` (design section B.4)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    root = _require_mapping(raw, str(path))
    _reject_unknown(root, {"transports"}, str(path))
    entries = _require_mapping(root.get("transports") or {}, f"{path}: transports")

    result: dict[str, Transport] = {}
    for name in sorted(entries):
        where = f"{path}: transports.{name}"
        block = _require_mapping(entries[name], where)
        _reject_unknown(block, _TRANSPORT_KEYS, where)
        pattern = block.get("pattern")
        if pattern not in PATTERNS:
            raise SpecError(f"{where}: pattern {pattern!r} is not one of {PATTERNS}")
        sub = block.get("subscriber_pattern")
        if sub is not None and sub not in PATTERNS:
            raise SpecError(
                f"{where}: subscriber_pattern {sub!r} is not one of {PATTERNS}"
            )
        key = block.get("address_config_key")
        if not key:
            raise SpecError(f"{where}: 'address_config_key' is required")
        if "://" in str(key):
            raise SpecError(
                f"{where}: address_config_key {key!r} looks like a literal "
                "address; it must be a symbolic config key"
            )
        result[name] = Transport(
            name=name,
            pattern=pattern,
            address_config_key=str(key),
            subscriber_pattern=sub,
        )
    return result


def load_family(path: Path, transports: dict[str, Transport]) -> Family:
    """Load and validate one ``spec/messages/<family>.yaml`` file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    root = _require_mapping(raw, str(path))
    _reject_unknown(root, {"family", "version", "messages"}, str(path))

    name = root.get("family")
    if not name:
        raise SpecError(f"{path}: 'family' is required")
    if name != path.stem:
        raise SpecError(
            f"{path}: family {name!r} must equal the filename stem {path.stem!r}"
        )
    version = root.get("version")
    if not isinstance(version, int):
        raise SpecError(f"{path}: 'version' is required and must be an integer")

    raw_messages = root.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise SpecError(f"{path}: 'messages' is required and must be non-empty")
    messages = tuple(
        _load_message(m, transports, f"{path}: messages[{i}]")
        for i, m in enumerate(raw_messages)
    )
    names = [m.name for m in messages]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise SpecError(f"{path}: duplicate message name(s) {dupes}")
    return Family(family=name, version=version, messages=messages)


def load_all(spec_root: Path) -> tuple[dict[str, Transport], list[Family]]:
    """Load the transport registry and every family under ``spec_root``.

    ``spec_root`` is the directory holding ``transports.yaml`` and a
    ``messages/`` subdirectory. Families are returned sorted by name so
    downstream generation is order-independent (design section B.17).
    """
    transports = load_transports(spec_root / "transports.yaml")
    families = [
        load_family(p, transports)
        for p in sorted((spec_root / "messages").glob("*.yaml"))
    ]

    seen: dict[str, str] = {}
    for fam in families:
        for msg in fam.messages:
            if msg.topic is None:
                continue
            if msg.topic in seen:
                raise SpecError(
                    f"topic {msg.topic!r} is declared in both {seen[msg.topic]!r} "
                    f"and {fam.family!r} (B.18 rule 14)"
                )
            seen[msg.topic] = fam.family

    # C has one flat namespace. Generated symbols are named after the message
    # (edu_<message>_calf_parse), not the family, so two families sharing a
    # message name would emit colliding externs the moment a client included
    # both headers. Catch it in the spec rather than in someone's linker.
    seen_names: dict[str, str] = {}
    for fam in families:
        for msg in fam.messages:
            if msg.name in seen_names:
                raise SpecError(
                    f"message name {msg.name!r} is declared in both "
                    f"{seen_names[msg.name]!r} and {fam.family!r}; generated C "
                    "symbols are message-scoped and would collide"
                )
            seen_names[msg.name] = fam.family
    return transports, families
