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

#: Field types that embed a record declared under the family's ``types:``.
#: Both are generated for JSON bus payloads only (design section 15.5).
RECORD_TYPES = ("nested", "list")

#: External protocols carrying key=value text lines. Generated in Phase 4a.
TEXT_TRANSPORTS = ("calf", "ralf")

#: External protocols carrying fixed binary frames. Phase 4b.
BINARY_TRANSPORTS = ("balf",)

#: Tokens allowed in a bus ``frames`` list (design section B.13).
FRAME_TOKENS = ("topic", "json_payload")

#: The fixed BALF header: magic, version, msg_type, flags, seq_no u32 LE.
#: Implicit in every binary layout — the generator writes it, the spec must not
#: declare it (design section B.13).
HEADER_SIZE = 8

#: Width in bytes of each scalar ``repr`` (design section B.10). ``char[N]`` is
#: handled separately because its width is in the token.
REPR_SIZE = {
    "u8": 1,
    "i8": 1,
    "u16": 2,
    "i16": 2,
    "u32": 4,
    "i32": 4,
    "u64": 8,
    "i64": 8,
    "f32": 4,
    "f64": 8,
}

#: Spec types each ``repr`` may carry.
_REPR_TYPES = {
    "u8": ("int", "ticks", "bool", "enum"),
    "i8": ("int", "ticks"),
    "u16": ("int", "ticks", "enum"),
    "i16": ("int", "ticks"),
    "u32": ("int", "ticks"),
    "i32": ("int", "ticks"),
    "u64": ("int", "ticks"),
    "i64": ("int", "ticks", "float"),
    "f32": ("float",),
    "f64": ("float",),
}


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
    min_items: int | None = None
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
    #: The value may be ``None``. Affects the Python annotation only; the key
    #: is still always emitted (design section B.7.2).
    nullable: bool = False
    #: ``to_dict`` omits the key when the value is the empty string. A fourth
    #: presence regime alongside the three in B.7.0, and the one the codebase
    #: already used most: 27 hand-written builders drop a key with ``if x:``.
    #: Strings only — on a number it would silently drop a legitimate zero.
    omit_when_empty: bool = False
    #: Implies ``nullable``. ``to_dict`` **omits the key entirely** when the
    #: value is None, rather than emitting ``null``. Use where absence and null
    #: mean the same thing to every reader, which in this system is everywhere
    #: (design section B.7.2).
    omit_when_none: bool = False
    values: tuple[str, ...] | None = None
    #: For ``type: nested`` — the name of a family-level entry under ``types:``.
    ref: str | None = None
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
class LayoutEntry:
    """One placed field, or one explicit padding run, in a binary body."""

    offset: int
    size: int
    field: str | None = None
    repr: str | None = None
    scale: int | None = None
    enum_map: dict[str, int] | None = None

    @property
    def is_reserved(self) -> bool:
        return self.field is None


@dataclass(frozen=True)
class BinaryEncoding:
    """A BALF frame layout (design section B.13).

    ``frame_size`` is the total on the wire, header included. Offsets in
    ``layout`` are relative to the **body**, so byte 0 is the first byte after
    the 8-byte header. The header is implicit: the generator writes it and the
    spec must not declare it.
    """

    transport: str
    msg_type: int
    frame_size: int
    layout: tuple[LayoutEntry, ...]
    price_scale: int | None = None

    @property
    def body_size(self) -> int:
        return self.frame_size - HEADER_SIZE


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
    binary_encoding: dict[str, BinaryEncoding] = field(default_factory=dict)

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
class NestedType:
    """A record type declared once at family level and referenced by name.

    Nested types are declared under ``types:`` rather than inline so that a
    type used by more than one message generates a single definition. C needs a
    named struct regardless, and two inline copies would be free to drift.

    Its fields are scalars only: a nested type may not itself contain a
    ``nested`` field. Nothing in this system needs deeper structure, and the
    restriction keeps the generators non-recursive.
    """

    name: str
    fields: tuple[Field, ...]
    doc: str = ""


@dataclass(frozen=True)
class Family:
    """One family file (design section B.5)."""

    family: str
    version: int
    messages: tuple[Message, ...]
    types: tuple[NestedType, ...] = ()


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
_BINARY_ENCODING_KEYS = {"msg_type", "frame_size", "price_scale", "layout"}
_LAYOUT_KEYS = {"field", "repr", "offset", "scale", "enum_map"}
_CHAR_ARRAY = re.compile(r"char\[(\d+)\]")

#: design section B.3: a CALF/RALF wire key and MSGTYPE are SCREAMING_SNAKE.
_KEY_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
_MSG_TYPE_TEXT = re.compile(r"[A-Z][A-Z0-9_]*")

#: A family-level nested type name (design section B.7.3).
_TYPE_NAME = re.compile(r"[A-Z][A-Za-z0-9]*")
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
    rules = Validate(**block)

    # An unsatisfiable or meaningless list bound is worse than a wrong one: the
    # spec loads, the binding generates, and every message fails validate() at
    # runtime with no hint that the rule itself is the problem.
    for name in ("min_items", "max_items"):
        bound = getattr(rules, name)
        if bound is not None and bound < 0:
            raise SpecError(f"{what}: validate.{name} must not be negative")
    low, high = rules.min_items, rules.max_items
    if low is not None and high is not None and low > high:
        raise SpecError(
            f"{what}: validate.min_items {low} exceeds max_items {high}, so no "
            "list can satisfy both and every message would be rejected"
        )
    return rules


def _load_field(raw: Any, what: str, *, allow_nested: bool = True) -> Field:
    block = _require_mapping(raw, what)
    if "name" not in block:
        raise SpecError(f"{what}: missing required key 'name'")
    name = block["name"]
    where = f"{what} ({name!r})"
    _reject_unknown(block, _FIELD_KEYS, where)
    if "type" not in block:
        raise SpecError(f"{where}: missing required key 'type'")

    ftype = block["type"]
    # Inside a nested type, `list` is allowed but `nested` is not, and a list
    # there must be of scalars (checked below). The rule the restriction exists
    # for is "the generators stay non-recursive" — a list of strings is flat,
    # so it was never the thing being excluded.
    allowed = SCALAR_TYPES + (RECORD_TYPES if allow_nested else ("list",))
    if ftype not in allowed:
        near = _nearest(str(ftype), set(allowed))
        hint = f" (did you mean {near!r}?)" if near else ""
        detail = (
            ". A nested type's fields are scalars only - it may not contain "
            "another record, nor a list of them"
            if ftype in RECORD_TYPES
            else ""
        )
        raise SpecError(
            f"{where}: type {ftype!r} is not one of {list(allowed)}{hint}{detail}"
        )

    ref = block.get("ref")
    item = block.get("item")
    if ftype == "list" and item is not None:
        # A list of scalars: `item:` names the element type, where `ref:` names
        # a record. Exactly one of the two - they are different kinds of list.
        if ref is not None:
            raise SpecError(
                f"{where}: a list declares 'ref: <TypeName>' for records or "
                "'item: <scalar>' for scalars, not both"
            )
        if item not in SCALAR_TYPES:
            raise SpecError(
                f"{where}: list item type {item!r} is not one of "
                f"{list(SCALAR_TYPES)}. A list of records uses 'ref:' instead"
            )
        default = block.get("default")
        if default is not None and default != []:
            raise SpecError(
                f"{where}: the only default a list may declare is [], and it is "
                "the implied one. A non-empty default would be a value the "
                "producer never chose appearing on the wire as if it had"
            )
        if item in ("enum", "ticks"):
            raise SpecError(
                f"{where}: a list of {item!r} is not generated - an enum needs "
                "'values:' per element and a tick list has no use here. Declare "
                "a record with 'ref:' if the elements need rules"
            )
    elif ftype in RECORD_TYPES:
        if not allow_nested:
            raise SpecError(
                f"{where}: a nested type's fields are scalars only, or a list "
                "of scalars via 'item:'. A record inside a record - or a list "
                "of them - is what keeps the generators non-recursive"
            )
        if not ref:
            options = (
                "'ref: <TypeName>' for a list of records, or 'item: <scalar>' "
                "for a list of scalars"
                if ftype == "list"
                else "'ref: <TypeName>' naming an entry under 'types:'"
            )
            raise SpecError(f"{where}: a {ftype} field requires {options}")
        for key in ("values", "unit", "default", "parse_default"):
            if block.get(key) is not None:
                raise SpecError(
                    f"{where}: {key!r} is not meaningful on a {ftype} field - "
                    "declare it on the referenced type's own fields instead"
                )
    elif ref is not None:
        raise SpecError(f"{where}: 'ref' is only meaningful for {list(RECORD_TYPES)}")
    if item is not None and ftype != "list":
        raise SpecError(f"{where}: 'item' is only meaningful for type: list")
    if ftype == "list":
        # These apply to every list, records and scalars alike. They lived
        # inside the record branch until a scalar list slipped past them.
        if block.get("nullable") or block.get("omit_when_none"):
            raise SpecError(
                f"{where}: a list may not be nullable. An empty list is how a "
                "list says it has nothing; null would be a second way to say "
                "the same thing, and every reader would have to handle both. "
                "Use 'validate: {min_items: 0}' if none is legal"
            )
        scalar_rules = _require_mapping(block.get("validate") or {}, where)
        for rule in ("max_len", "min_len", "gt", "ge", "lt", "le", "pattern"):
            if scalar_rules.get(rule) is not None:
                raise SpecError(
                    f"{where}: validate.{rule} is a scalar rule and does "
                    "nothing on a list. Use min_items/max_items for the list, "
                    "or declare a record with 'ref:' if the elements need rules"
                )
    if ftype == "list" and ref is None and item is None:
        raise SpecError(
            f"{where}: a list needs 'ref: <TypeName>' for records or "
            "'item: <scalar>' for scalars"
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

    # `required: false` must say which of the two it means, because they are
    # different on the wire: a default is always emitted, an omitted field is
    # not. Leaving it implicit is how a spec ends up saying something its
    # author did not intend (design section B.7.2).
    nullable = bool(block.get("nullable", False))
    omit = bool(block.get("omit_when_none", False))
    if omit and not nullable:
        raise SpecError(
            f"{where}: 'omit_when_none' requires 'nullable: true' - a field that "
            "cannot be None can never be omitted"
        )
    if (
        not block.get("required", True)
        and "default" not in block
        and not nullable
        and not block.get("omit_when_empty", False)
    ):
        raise SpecError(
            f"{where}: a field with 'required: false' must say what happens when "
            "it is unset - 'default: X' (always emitted as X), 'nullable: true' "
            "(always emitted as null), or 'nullable: true, omit_when_none: true' "
            "(absent). The three differ on the wire"
        )
    empty = bool(block.get("omit_when_empty", False))
    if empty:
        if ftype != "string":
            raise SpecError(
                f"{where}: 'omit_when_empty' applies to strings only; this is "
                f"a {ftype!r} field. On a number it would silently drop a "
                "legitimate zero, and an enum's empty value is not a declared "
                "one"
            )
        if "default" in block:
            raise SpecError(
                f"{where}: 'omit_when_empty' and 'default' contradict each "
                "other - the empty string *is* the absence for this regime, so "
                "there is nothing for a default to supply. Declaring one would "
                "read back a value the field can never emit"
            )
        if omit or nullable:
            raise SpecError(
                f"{where}: 'omit_when_empty' and 'omit_when_none' are two "
                'different regimes - a field omits on "" or on null, not both'
            )
        if block.get("required", True):
            raise SpecError(
                f"{where}: 'omit_when_empty' means the field may be absent, so "
                "it must also declare 'required: false'"
            )
    if omit and block.get("required", True):
        raise SpecError(
            f"{where}: 'omit_when_none' means the field may be absent, so it "
            "must also declare 'required: false'"
        )

    return Field(
        name=name,
        type=ftype,
        required=block.get("required", True),
        default=block.get("default"),
        parse_default=block.get("parse_default"),
        unit=unit,
        doc=block.get("doc", ""),
        nullable=nullable or omit,
        omit_when_none=omit,
        omit_when_empty=empty,
        values=tuple(values) if values else None,
        ref=ref,
        item=item,
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


def _repr_size(token: str, what: str) -> int:
    """Return the byte width of a ``repr`` token (design section B.10)."""
    if token in REPR_SIZE:
        return REPR_SIZE[token]
    match = _CHAR_ARRAY.fullmatch(token)
    if match:
        return int(match.group(1))
    near = _nearest(token, set(REPR_SIZE))
    hint = f" (did you mean {near!r}?)" if near else ""
    raise SpecError(f"{what}: unknown repr {token!r}{hint}")


def _load_layout_entry(
    raw: Any, fields: tuple[Field, ...], price_scale: int | None, what: str
) -> LayoutEntry:
    block = _require_mapping(raw, what)

    if "reserved" in block:
        _reject_unknown(block, {"reserved", "offset"}, what)
        size = block["reserved"]
        offset = block.get("offset")
        if not isinstance(size, int) or size <= 0:
            raise SpecError(f"{what}: 'reserved' must be a positive byte count")
        if not isinstance(offset, int) or offset < 0:
            raise SpecError(f"{what}: a reserved run needs a non-negative 'offset'")
        return LayoutEntry(offset=offset, size=size)

    _reject_unknown(block, _LAYOUT_KEYS, what)
    name = block.get("field")
    if not name:
        raise SpecError(f"{what}: a layout entry needs 'field' or 'reserved'")
    by_name = {f.name: f for f in fields}
    if name not in by_name:
        near = _nearest(str(name), set(by_name))
        hint = f" (did you mean {near!r}?)" if near else ""
        raise SpecError(f"{what}: layout names undeclared field {name!r}{hint}")
    spec_field = by_name[name]

    token = block.get("repr")
    if not isinstance(token, str):
        raise SpecError(f"{what}: field {name!r} needs a 'repr'")
    size = _repr_size(token, what)
    offset = block.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise SpecError(f"{what}: field {name!r} needs a non-negative 'offset'")

    char_match = _CHAR_ARRAY.fullmatch(token)
    if char_match:
        if spec_field.type != "string":
            raise SpecError(
                f"{what}: {token} carries field {name!r}, which is "
                f"{spec_field.type!r}, not a string"
            )
        # B.18 rule 8/10: the buffer is the declared max_len, so the two must
        # agree or a legal value would not fit the frame the spec describes.
        if spec_field.validate.max_len != size:
            raise SpecError(
                f"{what}: {token} for field {name!r} must equal its "
                f"validate.max_len ({spec_field.validate.max_len!r})"
            )
    else:
        allowed = _REPR_TYPES[token]
        if spec_field.type not in allowed:
            raise SpecError(
                f"{what}: repr {token!r} cannot carry a {spec_field.type!r} field "
                f"({name!r}); it accepts {list(allowed)}"
            )

    raw_scale = block.get("scale")
    scale: int | None = None
    if raw_scale is not None:
        if raw_scale == "price_scale":
            if price_scale is None:
                raise SpecError(
                    f"{what}: field {name!r} uses 'scale: price_scale' but the "
                    "balf block declares no price_scale"
                )
            scale = price_scale
        elif isinstance(raw_scale, int) and raw_scale > 0:
            scale = raw_scale
        else:
            raise SpecError(
                f"{what}: 'scale' must be a positive integer or the token "
                "'price_scale'"
            )

    enum_map = block.get("enum_map")
    if spec_field.type == "enum":
        # B.18 rule 7: a binary enum needs a complete map. A missing name is a
        # value that cannot be encoded, discovered at runtime rather than here.
        if not isinstance(enum_map, dict) or not enum_map:
            raise SpecError(
                f"{what}: enum field {name!r} on a binary transport requires an "
                "'enum_map'"
            )
        assert spec_field.values is not None
        missing = [v for v in spec_field.values if v not in enum_map]
        if missing:
            raise SpecError(f"{what}: enum_map for {name!r} omits {missing}")
        extra = [v for v in enum_map if v not in spec_field.values]
        if extra:
            raise SpecError(
                f"{what}: enum_map for {name!r} names undeclared value(s) {extra}"
            )
        for value, code in enum_map.items():
            if not isinstance(code, int) or not 0 <= code < 256**size:
                raise SpecError(
                    f"{what}: enum_map[{value!r}] = {code!r} does not fit {token}"
                )
        enum_map = {v: int(enum_map[v]) for v in spec_field.values}
    elif enum_map is not None:
        raise SpecError(f"{what}: 'enum_map' is only meaningful for an enum field")

    return LayoutEntry(
        offset=offset,
        size=size,
        field=name,
        repr=token,
        scale=scale,
        enum_map=enum_map,
    )


def _load_binary_encoding(
    transport: str, raw: Any, fields: tuple[Field, ...], what: str
) -> BinaryEncoding:
    block = _require_mapping(raw, what)
    _reject_unknown(block, _BINARY_ENCODING_KEYS, what)

    msg_type = block.get("msg_type")
    if not isinstance(msg_type, int) or not 0 <= msg_type <= 0xFF:
        raise SpecError(f"{what}: 'msg_type' must be a byte in 0x00-0xFF")

    frame_size = block.get("frame_size")
    if not isinstance(frame_size, int) or frame_size < HEADER_SIZE:
        raise SpecError(
            f"{what}: 'frame_size' is required and must be at least the "
            f"{HEADER_SIZE}-byte header"
        )

    price_scale = block.get("price_scale")
    if price_scale is not None and (
        not isinstance(price_scale, int) or price_scale <= 0
    ):
        raise SpecError(f"{what}: 'price_scale' must be a positive integer")

    raw_layout = block.get("layout")
    if not isinstance(raw_layout, list) or not raw_layout:
        raise SpecError(f"{what}: 'layout' is required and must be non-empty")
    entries = tuple(
        _load_layout_entry(item, fields, price_scale, f"{what}.layout[{index}]")
        for index, item in enumerate(raw_layout)
    )

    body_size = frame_size - HEADER_SIZE
    # B.18 rule 10: every body byte is covered exactly once. Gaps must be
    # explicit `reserved` runs, so a hole is always a decision rather than an
    # oversight — this is the rule that would have caught the eight-byte drift
    # in docs/examples/balf/balf_parser.py.
    covered: dict[int, str] = {}
    for entry in entries:
        label = entry.field or f"reserved@{entry.offset}"
        end = entry.offset + entry.size
        if end > body_size:
            raise SpecError(
                f"{what}: {label} occupies bytes [{entry.offset}, {end}) which "
                f"overruns the {body_size}-byte body implied by frame_size "
                f"{frame_size}"
            )
        for byte in range(entry.offset, end):
            if byte in covered:
                raise SpecError(
                    f"{what}: byte {byte} is claimed by both {covered[byte]!r} "
                    f"and {label!r}"
                )
            covered[byte] = label
    uncovered = [byte for byte in range(body_size) if byte not in covered]
    if uncovered:
        raise SpecError(
            f"{what}: body byte(s) {_runs(uncovered)} are not covered by any "
            "layout entry; add an explicit 'reserved' run"
        )

    laid_out = [e.field for e in entries if e.field]
    missing = [f.name for f in fields if f.name not in laid_out]
    if missing:
        raise SpecError(f"{what}: field(s) {missing} have no layout entry")

    return BinaryEncoding(
        transport=transport,
        msg_type=msg_type,
        frame_size=frame_size,
        layout=entries,
        price_scale=price_scale,
    )


def _runs(values: list[int]) -> str:
    """Render a sorted int list as compact ranges, for readable diagnostics."""
    out: list[str] = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = value
    out.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(out)


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
        if tname in EXTERNAL_TRANSPORTS:
            continue
        if tname not in transports:
            near = _nearest(str(tname), set(transports))
            hint = f" (did you mean {near!r}?)" if near else ""
            raise SpecError(
                f"{where}: transport {tname!r} is absent from "
                f"spec/transports.yaml{hint}"
            )

    # B.6: `topic` is present iff the message lists at least one bus transport.
    # An external-only message (BALF's execution_report) never travels on the
    # bus, so giving it a topic would invent an endpoint nobody publishes to.
    bus_transports = [t for t in raw_transport if t not in EXTERNAL_TRANSPORTS]
    topic = block.get("topic")
    if bus_transports and topic is None:
        raise SpecError(f"{where}: 'topic' is required for a bus message")
    if not bus_transports and topic is not None:
        raise SpecError(
            f"{where}: a message with no bus transport must omit 'topic' "
            "(design section B.6)"
        )
    if topic is not None:
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
    # An external transport's block is REQUIRED: nothing can infer a wire key
    # name or a byte offset, so there is no defensible default (B.6).
    for tname in raw_transport:
        if tname in EXTERNAL_TRANSPORTS and tname not in raw_encoding:
            raise SpecError(
                f"{where}: transport {tname!r} requires an 'encoding.{tname}' "
                "block declaring its wire layout"
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
    binary_encoding = {
        tname: _load_binary_encoding(
            tname,
            raw_encoding[tname],
            fields,
            f"{where}.encoding.{tname}",
        )
        for tname in raw_transport
        if tname in BINARY_TRANSPORTS
    }

    # B.18 rule 5: every required field must reach the authoritative bus
    # projection. With one bus transport in Phase 1 this is unambiguous.
    for enc in encoding.values():
        if enc.include is None:
            continue
        # A topic parameter is carried BY the topic, so excluding it from the
        # payload loses nothing - `order.ack.{gateway_id}` already names the
        # gateway. Requiring it in both would force every ack to repeat it.
        params = set(_topic_params(topic)) if topic else set()
        missing = [
            f.name
            for f in fields
            if f.required and f.name not in enc.include and f.name not in params
        ]
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
        binary_encoding=binary_encoding,
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
    _reject_unknown(root, {"family", "version", "messages", "types"}, str(path))

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

    raw_types = root.get("types") or {}
    if not isinstance(raw_types, dict):
        raise SpecError(f"{path}: 'types' must be a mapping of name to fields")
    types: list[NestedType] = []
    for type_name, raw_type in raw_types.items():
        where = f"{path}: types[{type_name!r}]"
        if not _TYPE_NAME.fullmatch(str(type_name)):
            raise SpecError(f"{where}: a type name must be CamelCase")
        block = _require_mapping(raw_type, where)
        _reject_unknown(block, {"fields", "doc"}, where)
        raw_fields = block.get("fields")
        if not isinstance(raw_fields, list) or not raw_fields:
            raise SpecError(f"{where}: 'fields' is required and must be non-empty")
        types.append(
            NestedType(
                name=str(type_name),
                fields=tuple(
                    _load_field(f, f"{where}: fields[{i}]", allow_nested=False)
                    for i, f in enumerate(raw_fields)
                ),
                doc=block.get("doc", ""),
            )
        )

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

    declared = {t.name for t in types}
    for message in messages:
        for f in message.fields:
            if f.type not in RECORD_TYPES or f.ref is None:
                continue
            if f.ref not in declared:
                near = _nearest(str(f.ref), declared)
                hint = f" (did you mean {near!r}?)" if near else ""
                raise SpecError(
                    f"{path}: {message.name}.{f.name} references unknown type "
                    f"{f.ref!r}{hint}. Declare it under the family's 'types:'"
                )
        # `message.encoding` holds the bus encoding only; CALF and BALF live in
        # `text_encoding`/`binary_encoding`. Reading it here meant this guard
        # never fired. The declared transports are the reliable source.
        external = sorted(set(message.transport) & set(EXTERNAL_TRANSPORTS))
        if external and any(f.type in RECORD_TYPES for f in message.fields):
            raise SpecError(
                f"{path}: {message.name} carries a record field on {external}. "
                "Records and lists are generated for JSON bus payloads only - "
                "one inside a CALF key-value line or a fixed BALF frame is an "
                "unsolved layout question, and half-supporting it would put a "
                "wrong answer in a committed binding"
            )

    used = {
        f.ref
        for m in messages
        for f in m.fields
        if f.type in RECORD_TYPES and f.ref is not None
    }
    unused = sorted(declared - used)
    if unused:
        raise SpecError(
            f"{path}: type(s) {unused} are declared but never referenced. "
            "An unused type generates a class nothing constructs"
        )
    return Family(family=name, version=version, messages=messages, types=tuple(types))


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

    # B.18 rule 11: a binary msg_type is the only thing a receiver has to tell
    # frames apart, so two messages sharing one on the same transport would be
    # undecodable.
    seen_types: dict[tuple[str, int], str] = {}
    for fam in families:
        for msg in fam.messages:
            for transport, enc in sorted(msg.binary_encoding.items()):
                key = (transport, enc.msg_type)
                if key in seen_types:
                    raise SpecError(
                        f"{transport} msg_type 0x{enc.msg_type:02X} is declared by "
                        f"both {seen_types[key]!r} and {msg.name!r}"
                    )
                seen_types[key] = msg.name

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
