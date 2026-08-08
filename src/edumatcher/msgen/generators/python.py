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

import re
import textwrap

from typing import Any

from edumatcher.msgen.spec import Family, Field, Message

#: Coerce-then-render, applied to a raw read out of the bus payload. Matches
#: ``md_gateway/normaliser.py``: ``_as_decimal`` is ``str(raw)`` and
#: ``_as_int_text`` is ``str(int(raw))``. An enum renders uppercase,
#: reproducing ``normalise_trade``'s ``str(...).upper()`` — idempotent for any
#: declared value, since B.3 requires enum names to be SCREAMING_SNAKE.
#: The value is coerced to its declared type first, so the projection and the
#: typed binding always agree (design section B.13).
_TEXT_RENDER = {
    "string": "str({expr})",
    "int": "str(int({expr}))",
    "ticks": "str(int({expr}))",
    "float": "str(float({expr}))",
    "bool": "str(bool({expr}))",
    "enum": "str({expr}).upper()",
}

#: Reading a text field back into the typed value.
_TEXT_READ = {
    "string": "str({expr})",
    "int": "int({expr})",
    "ticks": "int({expr})",
    "float": "float({expr})",
    "bool": "bool({expr})",
    "enum": "str({expr})",
}

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


def _coerce_arg(f: Field) -> str:
    """Coerce a keyword argument in the hot-path builder.

    A nullable field keeps ``None``: coercing it would turn "not set" into the
    string ``"None"`` or raise on ``float(None)``.
    """
    call = f"{_COERCE[f.type]}({f.name})"
    return f"None if {f.name} is None else {call}" if f.nullable else call


def _payload_fields(message: Message) -> list[Field]:
    """Fields the bus payload carries.

    A topic parameter is excluded when the message's bus projection excludes
    it: `order.ack.{gateway_id}` names the gateway in the topic, and the
    hand-written builder never repeated it in the body.
    """
    for enc in message.encoding.values():
        if enc.include is not None:
            keep = set(enc.include)
            return [f for f in message.fields if f.name in keep]
    params = set(message.topic_params)
    return [f for f in message.fields if f.name not in params]


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
    base = _base_annotation(f)
    return f"{base} | None" if f.nullable else base


def _base_annotation(f: Field) -> str:
    """The annotation before nullability is applied."""
    if f.type != "enum":
        return _ANNOTATION[f.type]
    assert f.values is not None
    if f.has_parse_default and f.parse_default not in f.values:
        return "str"
    return "Literal[" + ", ".join(_pystr(v) for v in f.values) + "]"


def _narrow(f: Field, expr: str) -> str:
    """Wrap a coerced value in ``cast`` when the field is annotated ``Literal``.

    ``from_dict`` coerces with ``str()`` and does not validate, so a type
    checker cannot know the result is one of the declared values — and it might
    not be, which is exactly the point of the coercion/validation split.

    ``cast`` is the honest way to say so: it is a no-op at runtime, it keeps the
    ``Literal`` on the dataclass where it does catch a bad constructor call, and
    it confines the "we have not checked yet" admission to the one function
    whose job is not to check. A field whose ``parse_default`` is outside its
    values is annotated ``str`` instead and needs no cast (see ``_annotation``).
    """
    base = _base_annotation(f)
    if f.type == "enum" and base.startswith("Literal") and not f.nullable:
        return f"cast({base}, {expr})"
    return expr


def _split_top_level(text: str) -> tuple[str, str]:
    """Split ``text`` at its first comma outside any bracket."""
    depth = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            return text[:index], text[index + 1 :].lstrip()
    raise ValueError(f"no top-level comma in {text!r}")


def _kwarg_lines(indent: str, name: str, expr: str) -> list[str]:
    """Emit ``name=expr,`` the way black would, wrapping a long ``cast``.

    Only ``cast`` needs this: it is the one generated expression that can be
    long enough to wrap, and black has two forms for it depending on whether the
    arguments fit on one continuation line.
    """
    single = f"{indent}{name}={expr},"
    if len(single) <= LINE_LENGTH:
        return [single]
    if not expr.startswith("cast("):
        # Black wraps any other over-long argument in parentheses on its own
        # line. The nullable read (`None if ... else ...`) is the case that
        # reaches here.
        return [f"{indent}{name}=(", f"{indent}    {expr}", f"{indent}),"]
    # Split on the comma separating cast's two arguments, not on one inside
    # ``Literal["A", "B"]`` — which a naive split(", ", 1) hits first.
    annotation, inner = _split_top_level(expr[len("cast(") : -1])
    joined = f"{indent}    {annotation}, {inner}"
    if len(joined) <= LINE_LENGTH:
        return [f"{indent}{name}=cast(", joined, f"{indent}),"]
    return [
        f"{indent}{name}=cast(",
        f"{indent}    {annotation},",
        f"{indent}    {inner},",
        f"{indent}),",
    ]


def _read_expr(f: Field, in_topic_only: bool = False) -> str:
    """Return the ``from_dict`` read expression for one field.

    Precedence is normative (design section B.7.1): ``parse_default`` first,
    then a ``default`` on an optional field, then a strict subscript that
    raises ``KeyError`` exactly as the hand-written payloads do.
    """
    coerce = _COERCE[f.type]
    key = _pystr(f.name)
    if in_topic_only:
        # Carried by the topic, not the body. `parse_*` fills it in from the
        # matched topic; `from_dict` on a bare payload cannot know it, and an
        # empty string is a visibly-missing value rather than a plausible one.
        return (
            f'{coerce}(p.get({key}, ""))'
            if f.type in ("string", "enum")
            else (f"{coerce}(p.get({key}, 0))")
        )
    if f.nullable:
        # None must survive the read: coercing it would turn "absent" into
        # "None" (str(None) == "None"), which is a value, not an absence.
        return f"None if p.get({key}) is None else {coerce}(p[{key}])"
    if f.has_parse_default:
        return _narrow(f, f"{coerce}(p.get({key}, {_pyval(f.parse_default)}))")
    if not f.required:
        return _narrow(f, f"{coerce}(p.get({key}, {_pyval(f.default)}))")
    return _narrow(f, f"{coerce}(p[{key}])")


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
    const = _const_name(message)
    params = message.topic_params

    out: list[str] = []
    if message.topic is None:
        # An external-only message (BALF's execution_report) has no bus
        # endpoint, so there is no topic constant to emit (design section B.6).
        pass
    elif params:
        out.append(f"TOPIC_{const} = {_pystr(message.topic)}")
        prefix = message.topic[: message.topic.index("{")]
        regex = _topic_regex(message.topic, params)
        out.append(f"PREFIX_{const} = {_pystr(prefix)}")
        out.append(f"_{const}_RE = re.compile({_pystr(regex)})")
    else:
        out.append(f"TOPIC_{const} = {_pystr(message.topic)}")
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


def _field_checks(message: Message, f: Field, indent: str) -> list[str]:
    """Every declared rule for one field, at ``indent``."""
    out: list[str] = []

    def check(cond: str, msg: str) -> None:
        out.append(f"{indent}if {cond}:")
        out.extend(_call(f"{indent}    ", "raise MessageValidationError", msg))

    me = f"self.{f.name}"
    v = f.validate
    if True:  # keeps the original block indentation
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

    return out


def _validate_body(message: Message) -> list[str]:
    """Return the body of ``validate()``, in spec declaration order.

    A nullable field's rules are guarded by a ``is not None`` test: ``None``
    means "not set", not "set to an invalid value", so applying ``gt: 0`` to it
    would reject every message that legitimately omits the field.
    """
    out: list[str] = []
    for f in message.fields:
        if f.nullable:
            checks = _field_checks(message, f, "            ")
            if checks:
                out.append(f"        if self.{f.name} is not None:")
                out += checks
            continue
        out += _field_checks(message, f, "        ")
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
            line += " = None" if f.omit_when_none else f" = {_pyval(f.default)}"
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
    carried = {f.name for f in _payload_fields(message)}
    for f in message.fields:
        out += _kwarg_lines(
            "            ", f.name, _read_expr(f, f.name not in carried)
        )
    out.append("        )")

    out += ["", "    def to_dict(self) -> dict[str, Any]:"]
    out += _docstring(
        "        ",
        "Return the bus payload, in the spec's declared field order.",
        [],
    )
    fields = _payload_fields(message)
    always = [f for f in fields if not f.omit_when_none]
    omitted = [f for f in fields if f.omit_when_none]
    if not omitted:
        out.append("        return {")
        out += [f"            {_pystr(f.name)}: self.{f.name}," for f in always]
        out.append("        }")
        return out

    out.append("        payload: dict[str, Any] = {")
    out += [f"            {_pystr(f.name)}: self.{f.name}," for f in always]
    out.append("        }")
    for f in omitted:
        out.append(f"        if self.{f.name} is not None:")
        out.append(f"            payload[{_pystr(f.name)}] = self.{f.name}")
    out.append("        return payload")
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
    payload_fields = _payload_fields(message)
    always = [f for f in payload_fields if not f.omit_when_none]
    omitted = [f for f in payload_fields if f.omit_when_none]

    if not omitted:
        out += ["    return [", f"        {topic_expr},", "        _msg.dumps("]
        out.append("            {")
        for f in always:
            out.append(f"                {_pystr(f.name)}: {_coerce_arg(f)},")
        out += ["            }", "        ),", "    ]"]
        return out

    out.append("    payload: dict[str, Any] = {")
    for f in always:
        out.append(f"        {_pystr(f.name)}: {_coerce_arg(f)},")
    out.append("    }")
    for f in omitted:
        out.append(f"    if {f.name} is not None:")
        out.append(f"        payload[{_pystr(f.name)}] = {_COERCE[f.type]}({f.name})")
    out += [
        "    return [",
        f"        {topic_expr},",
        "        _msg.dumps(payload),",
        "    ]",
    ]
    return out


def _text_projection_blocks(message: Message) -> list[list[str]]:
    """Emit ``project_*_<transport>`` and ``parse_*_<transport>``.

    The projection carries **only** the included payload fields. Envelope keys
    (``CH``/``SYM``/``SEQ``/``TS``) are the gateway's, not the projection's —
    the two gateways inject them in different positions, so a projection that
    tried to own them could not serve both (design section B.13).
    """
    cls = _class_name(message)
    blocks: list[list[str]] = []

    for transport in sorted(message.text_encoding):
        enc = message.text_encoding[transport]
        const = f"MSGTYPE_{_const_name(message)}_{transport.upper()}"
        blocks.append([f"{const} = {_pystr(enc.msg_type)}"])

        body = [
            f"def project_{message.name}_{transport}(",
            "    payload: Mapping[str, Any],",
            ") -> dict[str, str]:",
        ]
        body += _docstring(
            "    ",
            f"Project a bus payload onto the {transport.upper()} "
            f"{enc.msg_type} field map.",
            [
                "Reads **only** the fields this transport carries, so a caller "
                "needs nothing the projection does not use. That is what makes "
                "this a projection rather than a rename of the whole message: "
                "a gateway feeding this transport should not have to hold "
                "fields the transport drops (design section 4.6).",
                "Values are coerced to their declared types first, so this and "
                "the typed binding never disagree. "
                + (
                    "The gateway supplies "
                    + ", ".join(enc.gateway_injected)
                    + " in its own envelope; they are not payload keys."
                    if enc.gateway_injected
                    else "There are no gateway-injected keys."
                ),
            ],
        )
        body.append("    return {")
        for name in enc.include:
            spec_field = message.field_by_name(name)
            raw = _payload_read(spec_field)
            rendered = _TEXT_RENDER[spec_field.type].format(expr=raw)
            for key in enc.keys[name]:
                body.append(f"        {_pystr(key)}: {rendered},")
        body.append("    }")
        blocks.append(body)

        reader = [
            f"def parse_{message.name}_{transport}(",
            "    fields: Mapping[str, str],",
            f') -> "{cls}":',
        ]
        reader += _docstring(
            "    ",
            f"Rebuild this message from a {transport.upper()} payload field map.",
            [
                "Only the projected fields can be recovered; anything this "
                "transport does not carry takes its declared default. Coerces "
                "without validating, like ``from_dict`` (design section 5.1.1).",
            ],
        )
        reader.append(f"    return {cls}(")
        for spec_field in message.fields:
            if spec_field.name in enc.include:
                key = enc.keys[spec_field.name][0]
                expr = _narrow(
                    spec_field,
                    _TEXT_READ[spec_field.type].format(expr=f"fields[{_pystr(key)}]"),
                )
            elif spec_field.has_parse_default:
                expr = _narrow(spec_field, _pyval(spec_field.parse_default))
            elif not spec_field.required:
                expr = _narrow(spec_field, _pyval(spec_field.default))
            else:
                expr = _narrow(spec_field, _absent_placeholder(spec_field))
            reader += _kwarg_lines("        ", spec_field.name, expr)
        reader.append("    )")
        blocks.append(reader)

    return blocks


_CHAR_ARRAY_RE = re.compile(r"char\[(\d+)\]")

#: ``repr`` token -> struct format code (little-endian; see design section B.10).
_STRUCT_CODE = {
    "u8": "B",
    "i8": "b",
    "u16": "H",
    "i16": "h",
    "u32": "I",
    "i32": "i",
    "u64": "Q",
    "i64": "q",
    "f32": "f",
    "f64": "d",
}


def _binary_blocks(message: Message) -> list[list[str]]:
    """Emit ``serialise_*_<transport>`` and ``parse_*_<transport>`` for a frame.

    One ``struct`` format string per message, built from the layout in offset
    order, so packing and unpacking are a single call rather than a field loop.
    The 8-byte header is prepended here: it is implicit in the spec and the
    generator owns it (design section B.13).
    """
    cls = _class_name(message)
    const = _const_name(message)
    blocks: list[list[str]] = []

    for transport in sorted(message.binary_encoding):
        enc = message.binary_encoding[transport]
        prefix = f"{const}_{transport.upper()}"
        placed = sorted(enc.layout, key=lambda e: e.offset)

        fmt = "<"
        names: list[str] = []
        for entry in placed:
            if entry.is_reserved:
                fmt += f"{entry.size}x"
                continue
            assert entry.repr is not None and entry.field is not None
            match = _CHAR_ARRAY_RE.fullmatch(entry.repr)
            fmt += f"{match.group(1)}s" if match else _STRUCT_CODE[entry.repr]
            names.append(entry.field)

        consts = [
            f"MSGTYPE_{prefix} = {enc.msg_type:#04x}",
            f"FRAME_SIZE_{prefix} = {enc.frame_size}",
            f"_{prefix}_FMT = {_pystr(fmt)}",
            f"_{prefix}_STRUCT = _struct.Struct(_{prefix}_FMT)",
        ]
        if enc.price_scale is not None:
            consts.append(f"PRICE_SCALE_{prefix} = {enc.price_scale}")
        for entry in placed:
            if entry.enum_map:
                assert entry.field is not None
                pairs = ", ".join(
                    f"{_pystr(k)}: {v}" for k, v in entry.enum_map.items()
                )
                name = f"_{prefix}_{entry.field.upper()}"
                consts.append(f"{name}_TO_WIRE = {{{pairs}}}")
                comprehension = f"v: k for k, v in {name}_TO_WIRE.items()"
                single = f"{name}_FROM_WIRE = {{{comprehension}}}"
                if len(single) <= LINE_LENGTH:
                    consts.append(single)
                else:
                    consts += [
                        f"{name}_FROM_WIRE = {{",
                        f"    {comprehension}",
                        "}",
                    ]
        blocks.append(consts)

        blocks.append(_binary_serialise(message, transport, enc, prefix, placed))
        blocks.append(_binary_parse(message, cls, transport, enc, prefix, names))

    return blocks


def _binary_pack_expr(entry: Any, prefix: str) -> str:
    """Value expression fed to ``struct.pack`` for one laid-out field."""
    assert entry.field is not None
    raw = f"payload[{_pystr(entry.field)}]"
    if entry.enum_map:
        return f"_{prefix}_{entry.field.upper()}_TO_WIRE[str({raw})]"
    match = _CHAR_ARRAY_RE.fullmatch(entry.repr or "")
    if match:
        return f"str({raw}).encode()"
    if entry.scale:
        return f"round(float({raw}) * {entry.scale})"
    if entry.repr in ("f32", "f64"):
        return f"float({raw})"
    return f"int({raw})"


def _binary_serialise(
    message: Message, transport: str, enc: Any, prefix: str, placed: list[Any]
) -> list[str]:
    out = [
        f"def serialise_{message.name}_{transport}(",
        "    payload: Mapping[str, Any],",
        "    *,",
        "    seq_no: int,",
        "    flags: int = 0,",
        ") -> bytes:",
    ]
    out += _docstring(
        "    ",
        f"Serialise a payload into one {transport.upper()} frame.",
        [
            f"Returns exactly FRAME_SIZE_{prefix} bytes: the fixed "
            "8-byte header followed by the body laid out in the spec. The "
            "header is the generator's, not the spec's — it must not be "
            "declared in `layout` (design section B.13).",
            "Reads only the laid-out fields, and coerces each to its declared "
            "type, so this and the typed binding never disagree.",
        ],
    )
    out.append("    return _msg_header(")
    out.append(f"        MSGTYPE_{prefix}, seq_no, flags")
    out.append(f"    ) + _{prefix}_STRUCT.pack(")
    for entry in placed:
        if not entry.is_reserved:
            out.append(f"        {_binary_pack_expr(entry, prefix)},")
    out.append("    )")
    return out


def _binary_parse(
    message: Message, cls: str, transport: str, enc: Any, prefix: str, names: list[str]
) -> list[str]:
    out = [
        f'def parse_{message.name}_{transport}(frame: bytes) -> "{cls}":',
    ]
    out += _docstring(
        "    ",
        f"Parse one {transport.upper()} frame into this message.",
        [
            "Validates the header (magic, version, msg_type) and the frame "
            "length, because a wrong-length frame is not this message and "
            "reading it as one would silently produce nonsense. Field values "
            "are coerced but their declared rules are not checked — call "
            "``validate()`` for that (design section 5.1.1).",
            "Raises MessageValidationError on a header or length mismatch.",
        ],
    )
    out.append(f"    _check_frame(frame, MSGTYPE_{prefix}, FRAME_SIZE_{prefix})")
    single = f"    ({', '.join(names)},) = _{prefix}_STRUCT.unpack_from(frame, 8)"
    if len(single) <= LINE_LENGTH:
        out.append(single)
    else:
        out.append("    (")
        out += [f"        {name}," for name in names]
        out.append(f"    ) = _{prefix}_STRUCT.unpack_from(frame, 8)")
    out.append(f"    return {cls}(")
    by_offset = {e.field: e for e in enc.layout if not e.is_reserved}
    for f in message.fields:
        entry = by_offset[f.name]
        expr = f.name
        if entry.enum_map:
            # An unmapped wire byte yields "" rather than an exception: parse
            # coerces, validate() rejects (design section 5.1.1).
            expr = _narrow(f, f'_{prefix}_{f.name.upper()}_FROM_WIRE.get({f.name}, "")')
        elif _CHAR_ARRAY_RE.fullmatch(entry.repr or ""):
            expr = f'{f.name}.split(b"\\x00")[0].decode()'
        elif entry.scale:
            expr = f"{f.name} / {entry.scale}"
        out += _kwarg_lines("        ", f.name, expr)
    out.append("    )")
    return out


def _payload_read(f: Field) -> str:
    """Read one field out of a bus payload mapping, uncoerced.

    Same precedence as ``from_dict`` (design section B.7.1): ``parse_default``,
    then an optional field's ``default``, then a strict subscript. Keeping the
    two identical is what makes ``project_*(payload)`` and
    ``project_*(obj.to_dict())`` interchangeable.
    """
    key = _pystr(f.name)
    if f.has_parse_default:
        return f"payload.get({key}, {_pyval(f.parse_default)})"
    if not f.required:
        return f"payload.get({key}, {_pyval(f.default)})"
    return f"payload[{key}]"


def _absent_placeholder(f: Field) -> str:
    """Value for a required field this transport does not carry.

    A text projection is a genuine subset (design section 4.6): CALF's TRADE
    print carries no ``id`` or ``symbol``. Rebuilding a full message from one
    therefore cannot recover them, and inventing a plausible-looking value would
    be worse than an obviously empty one.
    """
    if f.type in ("int", "ticks"):
        return "0"
    if f.type == "float":
        return "0.0"
    if f.type == "bool":
        return "False"
    return '""'


def _parse_body(message: Message, cls: str) -> list[str]:
    """Body of ``parse_*``: decode, recover topic parameters, build, validate.

    A topic parameter is carried by the topic rather than the payload, so it
    has to be read back out of the topic — otherwise ``parse_order_ack`` would
    return a message whose ``gateway_id`` is empty, which is exactly the sort
    of quietly-wrong value this generator exists to prevent.
    """
    params = message.topic_params
    if not params:
        # Underscore-prefixed: with no topic parameters the topic is not read,
        # and pyright's reportUnusedVariable is right to say so.
        return [
            "    _topic, payload = _msg.decode(frames)",
            f"    obj = {cls}.from_dict(payload)",
            "    obj.validate()",
            "    return obj",
        ]

    out = ["    topic, payload = _msg.decode(frames)"]
    const = _const_name(message)
    out.append(f"    matched = match_{message.name}(topic)")
    out.append("    if matched is None:")
    out.extend(
        _call(
            "        ",
            "raise MessageValidationError",
            f'f"topic {{topic!r}} is not {{TOPIC_{const}!r}}"',
        )
    )
    if len(params) == 1:
        out.append(f"    payload = {{**payload, {_pystr(params[0])}: matched}}")
    else:
        out.append("    payload = {**payload, **matched}")
    return out + [
        f"    obj = {cls}.from_dict(payload)",
        "    obj.validate()",
        "    return obj",
    ]


def _function_blocks(message: Message) -> list[list[str]]:
    """Every module-level function for one message, as separate blocks.

    A message with no bus transport gets only ``describe_*``: ``make_*`` and
    ``parse_*`` build and read bus frames, which an external-only message never
    has (design section B.6).
    """
    cls = _class_name(message)
    const = _const_name(message)
    params = message.topic_params
    blocks: list[list[str]] = []

    if message.topic is None:
        return [
            [f"def describe_{message.name}() -> tuple[dict[str, Any], ...]:"]
            + _docstring(
                "    ",
                "Return field metadata, for spy tools and runtime pretty-printing.",
                [],
            )
            + [f"    return _{const}_FIELDS"]
        ]

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
        + _parse_body(message, cls)
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

    needs_binary = any(m.binary_encoding for m in messages)
    needs_bus = any(m.topic is not None for m in messages)

    imports = ["from __future__ import annotations", ""]
    if needs_re:
        imports.append("import re")
    if needs_binary:
        imports.append("import struct as _struct")
    imports.append("from dataclasses import dataclass")
    typing_names = ["Any"]
    if needs_literal:
        typing_names.append("Literal")
    typing_names.append("Mapping")
    if needs_literal:
        typing_names.append("cast")
    imports.append(f"from typing import {', '.join(typing_names)}")
    imports.append("")
    if needs_bus:
        imports.append("from edumatcher.models import message as _msg")
    runtime_names = ["MessageValidationError"]
    if needs_binary:
        runtime_names = [
            "MessageValidationError",
            "balf_header as _msg_header",
            "check_balf_frame as _check_frame",
        ]
    if len(runtime_names) == 1:
        imports.append(
            "from edumatcher.models.generated._runtime import MessageValidationError"
        )
    else:
        imports.append("from edumatcher.models.generated._runtime import (")
        imports += [f"    {name}," for name in runtime_names]
        imports.append(")")

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
        constants = _constant_block(message)
        if constants:
            blocks.append(constants)
        blocks.append(_describe_block(message))
        blocks.append(_class_block(message))
        blocks.extend(_function_blocks(message))
        blocks.extend(_text_projection_blocks(message))
        blocks.extend(_binary_blocks(message))

    # Only bus messages have a topic; an external-only family's registry is
    # legitimately empty (design section B.6).
    topics = [f"TOPIC_{_const_name(m)}" for m in messages if m.topic is not None]
    literal = _tuple_literal(topics) if topics else "()"
    single = f"FAMILY_TOPICS: tuple[str, ...] = {literal}"
    if len(single) <= LINE_LENGTH:
        blocks.append([single])
    else:
        blocks.append(
            ["FAMILY_TOPICS: tuple[str, ...] = ("]
            + [f"    {name}," for name in topics]
            + [")"]
        )

    return "\n\n\n".join("\n".join(b) for b in blocks) + "\n"
