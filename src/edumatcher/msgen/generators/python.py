"""Emit the Python binding for one family.

Hand-rolled string assembly, no templating engine (design section 12.5). The
output must be:

* **deterministic** — a byte-for-byte pure function of the spec, so
  ``pm-msgen check`` is a reliable gate rather than a flaky one (section B.17).
  Nothing here reads the clock, the filesystem layout or a set's iteration
  order; every loop walks spec declaration order.
* **black-clean** — the generated file is committed and reviewed like any
  other, and ``make format`` runs over it. Emission therefore already follows
  black's style: double quotes, two blank lines around top-level definitions,
  and a call exploded across lines only when the single-line form would exceed
  the configured 88 columns. ``black`` is deliberately **not** invoked at
  generation time: that would make the output depend on the installed black
  version and reintroduce risk R9 (flaky ``check``).
"""

from __future__ import annotations

import textwrap

from edumatcher.msgen.spec import Family, Field, Message

#: Configured black/flake8 line length. Emission targets this directly.
LINE_LENGTH = 88

#: Coercion callable applied by ``from_dict`` for each spec type. This is the
#: whole of the design's "same str()/int()/float() coercion" requirement
#: (section 5.1.1); it must match the hand-written payloads field-for-field.
_COERCE = {
    "string": "str",
    "int": "int",
    "ticks": "int",
    "float": "float",
    "bool": "bool",
    "enum": "str",
}

#: Python annotation per spec type, for non-enum fields.
_ANNOTATION = {
    "string": "str",
    "int": "int",
    "ticks": "int",
    "float": "float",
    "bool": "bool",
}


def _pystr(value: str) -> str:
    """Return ``value`` as a double-quoted Python string literal."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _pyval(value: object) -> str:
    """Return a Python literal for a spec scalar."""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return _pystr(value)
    return repr(value)


def _tuple_literal(items: list[str]) -> str:
    """Return a tuple literal black will leave on one line.

    A trailing comma is emitted only for the one-element case, where it is
    syntactically required. Adding it elsewhere would be a "magic trailing
    comma" and black would explode the tuple across lines.
    """
    if len(items) == 1:
        return f"({items[0]},)"
    return "(" + ", ".join(items) + ")"


def _docstring(indent: str, summary: str, body: list[str]) -> list[str]:
    """Return a wrapped docstring, hard-wrapped to the configured width.

    A one-line summary with no body closes on the same line, which is what
    black does and therefore what the generated file must already look like.
    """
    width = LINE_LENGTH - len(indent)
    wrapped = textwrap.wrap(" ".join(summary.split()), width=width - 6) or [""]
    if len(wrapped) == 1 and not body:
        return [f'{indent}"""{wrapped[0]}"""']
    out = [f'{indent}"""{wrapped[0]}']
    out += [f"{indent}{line}" for line in wrapped[1:]]
    for para in body:
        out.append("")
        out += [
            f"{indent}{line}"
            for line in textwrap.wrap(" ".join(para.split()), width=width)
        ]
    out.append(f'{indent}"""')
    return out


def _call(indent: str, head: str, arg: str) -> list[str]:
    """Emit ``head(arg)`` the way black would: one line, or exploded.

    Black collapses a call onto one line when it fits within the line length
    and explodes it otherwise. Reproducing that rule here is what keeps the
    generated file black-clean without running black.
    """
    single = f"{indent}{head}({arg})"
    if len(single) <= LINE_LENGTH:
        return [single]
    return [f"{indent}{head}(", f"{indent}    {arg}", f"{indent})"]


def _class_name(message: Message) -> str:
    return "".join(part.title() for part in message.name.split("_"))


def _const_name(message: Message) -> str:
    return message.name.upper()


def _values_const(message: Message, f: Field) -> str:
    return f"_{_const_name(message)}_{f.name.upper()}_VALUES"


def _pattern_const(message: Message, f: Field) -> str:
    return f"_{_const_name(message)}_{f.name.upper()}_RE"


def _annotation(f: Field) -> str:
    """Return the Python annotation for a field.

    An enum normally becomes a ``Literal`` of its declared values. It does
    **not** when the field declares a ``parse_default`` outside those values:
    ``from_dict`` can then legitimately produce a value the ``Literal``
    forbids (design section B.7.1), and annotating it anyway would make the
    type a lie that every call site has to silence with a ``type: ignore``.
    Narrowing is ``validate()``'s job, not the annotation's.
    """
    if f.type != "enum":
        return _ANNOTATION[f.type]
    assert f.values is not None
    if f.has_parse_default and f.parse_default not in f.values:
        return "str"
    return "Literal[" + ", ".join(_pystr(v) for v in f.values) + "]"


def _read_expr(f: Field) -> str:
    """Return the ``from_dict`` read expression for one field.

    Precedence is normative (design section B.7.1): ``parse_default`` first,
    then a ``default`` on an optional field, then a strict subscript that
    raises ``KeyError`` exactly as the hand-written payloads do.
    """
    coerce = _COERCE[f.type]
    key = _pystr(f.name)
    if f.has_parse_default:
        return f"{coerce}(p.get({key}, {_pyval(f.parse_default)}))"
    if not f.required:
        return f"{coerce}(p.get({key}, {_pyval(f.default)}))"
    return f"{coerce}(p[{key}])"


def _topic_regex(topic: str, params: tuple[str, ...]) -> str:
    """Build the ``match_*`` regex source for a parameterised topic.

    ``[^.]+`` and not ``.+``: topic segments are dot-delimited, so a greedy
    ``.+`` would swallow a trailing ``.suffix`` and match a topic that is not
    this one (design section A.4).
    """
    out = ""
    rest = topic
    for param in params:
        head, rest = rest.split("{" + param + "}", 1)
        out += head.replace(".", r"\.")
        out += f"(?P<{param}>[^.]+)"
    return out + rest.replace(".", r"\.")


def _constant_block(message: Message) -> list[str]:
    """Module-level constants for one message: topic, patterns, enum values."""
    assert message.topic is not None
    const = _const_name(message)
    params = message.topic_params

    out = [f"TOPIC_{const} = {_pystr(message.topic)}"]
    if params:
        prefix = message.topic[: message.topic.index("{")]
        regex = _topic_regex(message.topic, params)
        out.append(f"PREFIX_{const} = {_pystr(prefix)}")
        out.append(f"_{const}_RE = re.compile({_pystr(regex)})")
    else:
        # Pre-encoded once at import, matching the engine's own _TRADE_TOPIC
        # optimisation (docs-design/perf-notes.md, "Engine / publication").
        # A parameterised topic cannot be pre-encoded; it is built per call.
        out.append(f"_TOPIC_{const}_BYTES = {_pystr(message.topic)}.encode()")

    for f in message.fields:
        if f.validate.pattern is not None:
            out.append(
                f"{_pattern_const(message, f)} = "
                f"re.compile({_pystr(f.validate.pattern)})"
            )
        if f.type == "enum":
            assert f.values is not None
            literals = [_pystr(v) for v in f.values]
            out.append(f"{_values_const(message, f)} = {_tuple_literal(literals)}")
    return out


def _describe_block(message: Message) -> list[str]:
    """A static field-metadata table, for spy tools and runtime introspection."""
    out = [f"_{_const_name(message)}_FIELDS: tuple[dict[str, Any], ...] = ("]
    for f in message.fields:
        constraints: list[str] = []
        v = f.validate
        for key in ("gt", "ge", "lt", "le", "min_len", "max_len", "max_items"):
            val = getattr(v, key)
            if val is not None:
                constraints.append(f"{_pystr(key)}: {val!r}")
        if v.pattern is not None:
            constraints.append(f"{_pystr('pattern')}: {_pystr(v.pattern)}")
        items = [
            f"{_pystr('name')}: {_pystr(f.name)}",
            f"{_pystr('type')}: {_pystr(f.type)}",
            f"{_pystr('unit')}: {_pyval(f.unit) if f.unit else 'None'}",
            f"{_pystr('required')}: {f.required!r}",
            f"{_pystr('doc')}: {_pystr(' '.join(f.doc.split()))}",
        ]
        if f.values:
            items.append(f"{_pystr('values')}: {_values_const(message, f)}")
        if constraints:
            items.append(f"{_pystr('constraints')}: {{{', '.join(constraints)}}}")
        out.append("    {")
        out += [f"        {item}," for item in items]
        out.append("    },")
    out.append(")")
    return out


def _validate_body(message: Message) -> list[str]:
    """Return the body of ``validate()``, in spec declaration order."""
    out: list[str] = []

    def check(cond: str, msg: str) -> None:
        out.append(f"        if {cond}:")
        out.extend(_call("            ", "raise MessageValidationError", msg))

    for f in message.fields:
        me = f"self.{f.name}"
        v = f.validate
        if f.type == "enum":
            const = _values_const(message, f)
            check(
                f"{me} not in {const}",
                f'f"{f.name}: {{{me}!r}} is not one of {{{const}!r}}"',
            )
        for key, op, text in (
            ("gt", "<=", ">"),
            ("ge", "<", ">="),
            ("lt", ">=", "<"),
            ("le", ">", "<="),
        ):
            bound = getattr(v, key)
            if bound is not None:
                check(
                    f"{me} {op} {bound!r}",
                    f'f"{f.name}: {{{me}!r}} must be {text} {bound!r}"',
                )
        if v.min_len is not None:
            check(
                f"len({me}) < {v.min_len!r}",
                f'f"{f.name}: length {{len({me})}} is below min_len {v.min_len!r}"',
            )
        if v.max_len is not None:
            check(
                f"len({me}) > {v.max_len!r}",
                f'f"{f.name}: length {{len({me})}} exceeds max_len {v.max_len!r}"',
            )
        if v.pattern is not None:
            rx = _pattern_const(message, f)
            # The pattern is interpolated from the compiled object rather than
            # inlined as a literal: a spec pattern may contain quotes or braces,
            # either of which would break an f-string that embedded it directly.
            check(
                f"not {rx}.fullmatch({me})",
                f'f"{f.name}: {{{me}!r}} does not match {{{rx}.pattern!r}}"',
            )

    return out or ["        return None"]


def _class_block(message: Message) -> list[str]:
    cls = _class_name(message)
    out = ["@dataclass(frozen=True, slots=True)", f"class {cls}:"]

    note = str(message.doc.get("example_note", "")).strip()
    out += _docstring(
        "    ",
        str(message.doc.get("motivation", "")),
        [note] if note else [],
    )
    out.append("")

    ordered = [f for f in message.fields if f.required]
    ordered += [f for f in message.fields if not f.required]
    for f in ordered:
        line = f"    {f.name}: {_annotation(f)}"
        if not f.required:
            line += f" = {_pyval(f.default)}"
        out.append(line + (f"  # unit: {f.unit}" if f.unit else ""))

    out += ["", "    def validate(self) -> None:"]
    out += _docstring(
        "        ",
        "Raise MessageValidationError if any declared rule fails.",
        [
            "The only strictness gate: ``from_dict`` coerces but never "
            "validates, so a reader of historical data can opt out of the "
            "rules by calling ``from_dict`` alone (design section 5.1.1).",
        ],
    )
    out += _validate_body(message)

    out += [
        "",
        "    @classmethod",
        f'    def from_dict(cls, p: Mapping[str, Any]) -> "{cls}":',
    ]
    out += _docstring(
        "        ",
        "Coerce a payload mapping into this message. Does NOT validate.",
        [
            "Mirrors the hand-written payload's coercion exactly, including its "
            "lenient fallbacks, so it is a drop-in replacement for readers of "
            "already-published data (design section 5.1.1).",
        ],
    )
    out.append("        return cls(")
    out += [f"            {f.name}={_read_expr(f)}," for f in message.fields]
    out.append("        )")

    out += ["", "    def to_dict(self) -> dict[str, Any]:"]
    out += _docstring(
        "        ",
        "Return the bus payload, in the spec's declared field order.",
        [],
    )
    out.append("        return {")
    out += [f"            {_pystr(f.name)}: self.{f.name}," for f in message.fields]
    out.append("        }")
    return out


def _encode_return(message: Message) -> str:
    params = message.topic_params
    if not params:
        return f"    return _msg.encode(TOPIC_{_const_name(message)}, obj.to_dict())"
    args = ", ".join(f"obj.{p}" for p in params)
    return f"    return _msg.encode(topic_{message.name}({args}), obj.to_dict())"


def _unchecked_block(message: Message) -> list[str]:
    """Emit the hot-path constructor.

    Deliberately does **not** route through ``from_dict``/dataclass/``to_dict``
    the way ``make_*`` does. Measured on the ``trade`` family, that route costs
    4.03 us/call against 0.96 for the hand-written dict literal it replaces —
    a +3.1 us regression on a path where ``docs-design/perf-notes.md`` records
    optimisations worth 0.2-1.0 us each. A constructor whose stated purpose is
    "measured hot paths only" cannot be four times slower than the code it
    replaces.

    So this emits the dict literal directly, with explicit keyword-only
    parameters and a pre-encoded topic. Coercion is kept inline: dropping it
    saves a further 0.34 us but makes ``make_*_unchecked(price=100)`` put an
    int on the wire where ``make_*`` puts a float, and mypy does not catch it
    because int is promotable to float. That is the silent-divergence class
    this whole tool exists to remove, so the 0.34 us is paid.

    Net: 1.47 us/call, +0.50 us against the hand-written literal, and the field
    list now lives only in the spec (design section 8, Phase 2).
    """
    const = _const_name(message)
    params = message.topic_params

    required = [f for f in message.fields if f.required]
    optional = [f for f in message.fields if not f.required]
    sig = [f"    {f.name}: {_annotation(f)}," for f in required]
    sig += [f"    {f.name}: {_annotation(f)} = {_pyval(f.default)}," for f in optional]

    if params:
        topic_expr = f"topic_{message.name}({', '.join(params)}).encode()"
    else:
        topic_expr = f"_TOPIC_{const}_BYTES"

    out = (
        [f"def make_{message.name}_unchecked(", "    *,"] + sig + [") -> list[bytes]:"]
    )
    out += _docstring(
        "    ",
        f"Identical frames to ``make_{message.name}``, without ``validate()``.",
        [
            "For measured hot paths only; every other caller should use the "
            "validating constructor. Builds the payload directly rather than "
            "via the dataclass, which is what makes it cheap enough to be worth "
            "having — see the generator's _unchecked_block docstring for the "
            "measurements.",
            "Coerces exactly as ``make_*`` does, so for any input the two emit "
            "byte-identical frames.",
        ],
    )
    out += ["    return [", f"        {topic_expr},", "        _msg.dumps("]
    out.append("            {")
    for f in message.fields:
        out.append(f"                {_pystr(f.name)}: {_COERCE[f.type]}({f.name}),")
    out += ["            }", "        ),", "    ]"]
    return out


def _function_blocks(message: Message) -> list[list[str]]:
    """Every module-level function for one message, as separate blocks."""
    cls = _class_name(message)
    const = _const_name(message)
    params = message.topic_params
    blocks: list[list[str]] = []

    if not params:
        blocks.append(
            [f"def is_{message.name}(topic: str) -> bool:"]
            + _docstring("    ", "True when ``topic`` is this message's topic.", [])
            + [f"    return topic == TOPIC_{const}"]
        )
    else:
        args = ", ".join(f"{p}: str" for p in params)
        blocks.append(
            [f"def topic_{message.name}({args}) -> str:"]
            + _docstring(
                "    ", "Build this message's topic without a string literal.", []
            )
            + [f"    return f{_pystr(message.topic or '')}"]
        )
        if len(params) == 1:
            blocks.append(
                [f"def match_{message.name}(topic: str) -> str | None:"]
                + _docstring(
                    "    ",
                    f"Return ``{params[0]}`` when ``topic`` matches, else None.",
                    [],
                )
                + [
                    f"    m = _{const}_RE.fullmatch(topic)",
                    f"    return m.group({_pystr(params[0])}) if m else None",
                ]
            )
        else:
            blocks.append(
                [f"def match_{message.name}(topic: str) -> dict[str, str] | None:"]
                + _docstring(
                    "    ",
                    "Return the topic parameters when ``topic`` matches, else None.",
                    [],
                )
                + [
                    f"    m = _{const}_RE.fullmatch(topic)",
                    "    return m.groupdict() if m else None",
                ]
            )

    blocks.append(
        [f"def make_{message.name}(**kw: Any) -> list[bytes]:"]
        + _docstring(
            "    ",
            "Coerce, validate, and return the TWO bus frames [topic, payload].",
            [
                "The per-topic sequence third frame is NOT added here; it is "
                "appended by SequencedPublisher.send_multipart() at publish time "
                "(edumatcher/messaging/bus.py).",
                "Routes through ``from_dict`` rather than the dataclass "
                "constructor, so a caller passing ``price=100`` puts a float on "
                "the wire rather than an int (design section 5.1.1).",
            ],
        )
        + [
            f"    obj = {cls}.from_dict(kw)",
            "    obj.validate()",
            _encode_return(message),
        ]
    )

    blocks.append(_unchecked_block(message))

    blocks.append(
        [f'def parse_{message.name}(frames: list[bytes]) -> "{cls}":']
        + _docstring(
            "    ",
            "Decode bus frames into a validated message.",
            [
                "Raises MessageValidationError if the payload breaks a declared "
                "rule. Call ``from_dict`` on a decoded payload instead to read "
                "without validating.",
            ],
        )
        + [
            "    _topic, payload = _msg.decode(frames)",
            f"    obj = {cls}.from_dict(payload)",
            "    obj.validate()",
            "    return obj",
        ]
    )

    blocks.append(
        [f"def describe_{message.name}() -> tuple[dict[str, Any], ...]:"]
        + _docstring(
            "    ",
            "Return field metadata, for spy tools and runtime pretty-printing.",
            [],
        )
        + [f"    return _{const}_FIELDS"]
    )
    return blocks


def render_family(family: Family, spec_path: str) -> str:
    """Return the complete generated module source for one family.

    ``spec_path`` is a repo-relative label such as ``spec/messages/trade.yaml``.
    It must not be an absolute path: the banner is part of the output that
    ``pm-msgen check`` diffs, so it has to be identical on every machine.
    """
    messages = family.messages
    needs_re = any(
        f.validate.pattern is not None for m in messages for f in m.fields
    ) or any(m.topic_params for m in messages)
    needs_literal = any(
        f.type == "enum" and _annotation(f).startswith("Literal")
        for m in messages
        for f in m.fields
    )

    header: list[str] = [
        f"# GENERATED FROM {spec_path} - DO NOT EDIT",
        "#",
        "# Regenerate with:  poetry run pm-msgen generate",
    ]
    header += _docstring(
        "",
        f"Generated bindings for the ``{family.family}`` message family.",
        [
            f"Family version {family.version}. Every symbol here is derived from "
            f"``{spec_path}``; edit the spec, not this file.",
            "``pm-msgen check`` fails the build if this file and the spec "
            "disagree. See docs/developer/06-msgen.md.",
        ],
    )

    imports = ["from __future__ import annotations", ""]
    if needs_re:
        imports.append("import re")
    imports.append("from dataclasses import dataclass")
    typing_names = ["Any"] + (["Literal"] if needs_literal else []) + ["Mapping"]
    imports += [
        f"from typing import {', '.join(typing_names)}",
        "",
        "from edumatcher.models import message as _msg",
        "from edumatcher.models.generated._runtime import MessageValidationError",
    ]

    # Black wants exactly one blank line after the import block, so the module
    # preamble and the family constants are one emitted block.
    blocks: list[list[str]] = [
        header
        + [""]
        + imports
        + [
            "",
            f"FAMILY = {_pystr(family.family)}",
            f"FAMILY_VERSION = {family.version}",
        ]
    ]

    for message in messages:
        blocks.append(_constant_block(message))
        blocks.append(_describe_block(message))
        blocks.append(_class_block(message))
        blocks.extend(_function_blocks(message))

    topics = [f"TOPIC_{_const_name(m)}" for m in messages]
    blocks.append([f"FAMILY_TOPICS: tuple[str, ...] = {_tuple_literal(topics)}"])

    return "\n\n\n".join("\n".join(b) for b in blocks) + "\n"
