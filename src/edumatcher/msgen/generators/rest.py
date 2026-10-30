"""Emit Pydantic models of the JSON bodies, for the REST gateway's contract.

``pm-api-gwy`` forwards many engine replies to clients as they are. These
models are what it declares (and validates) them as, so the OpenAPI document
and the bus payload come from one spec and cannot drift apart.

They model the *body*, which differs from the Python binding's dataclass in two
ways that matter to a client:

* topic-only fields (``gateway_id`` of ``system.session_status.{gateway_id}``)
  are not in the body, so they are not in the model;
* a field ``to_dict`` leaves out when it is empty (``omit_when_none`` /
  ``omit_when_empty``) is optional with a ``None`` default, every other field is
  required. Serialised with ``exclude_unset``, an absent field stays absent
  rather than turning into ``null``.

Descriptions are attribute docstrings (``use_attribute_docstrings``) rather
than ``Field(description=...)``: a docstring wraps, a string argument would
leave lines black cannot shorten. Formatting follows the same rules as the
Python emitter, whose helpers this reuses, so the output is black-clean without
running black.
"""

from __future__ import annotations

from edumatcher.msgen.generators.python import (
    _alias_name,  # pyright: ignore[reportPrivateUsage]
    _as_message,  # pyright: ignore[reportPrivateUsage]
    _class_name,  # pyright: ignore[reportPrivateUsage]
    _docstring,  # pyright: ignore[reportPrivateUsage]
    _literal_literal,  # pyright: ignore[reportPrivateUsage]
    _payload_fields,  # pyright: ignore[reportPrivateUsage]
    _pystr,  # pyright: ignore[reportPrivateUsage]
    _pyval,  # pyright: ignore[reportPrivateUsage]
    _uses_literal,  # pyright: ignore[reportPrivateUsage]
    _wrap,  # pyright: ignore[reportPrivateUsage]
)
from edumatcher.msgen.spec import Family, Field, Message

_ANNOTATION = {
    "string": "str",
    "int": "int",
    "ticks": "int",
    "float": "float",
    "bool": "bool",
}


def _omitted(f: Field) -> bool:
    """Whether ``to_dict`` can leave this field out of the payload."""
    return f.omit_when_none or f.omit_when_empty


def _base(message: Message, f: Field) -> str:
    if f.type == "nested":
        assert f.ref is not None
        return f.ref
    if f.type == "list":
        if f.item is not None:
            return f"list[{_ANNOTATION[f.item]}]"
        assert f.ref is not None
        return f"list[{f.ref}]"
    if f.type == "enum":
        return _alias_name(message, f) if _uses_literal(f) else "str"
    return _ANNOTATION[f.type]


def _constraints(f: Field) -> list[str]:
    """``Field(...)`` keyword arguments for the declared validation rules."""
    v = f.validate
    out: list[str] = []
    for name in ("gt", "ge", "lt", "le"):
        bound = getattr(v, name)
        if bound is not None:
            out.append(f"{name}={_pyval(bound)}")
    lo = v.min_items if f.type == "list" else v.min_len
    hi = v.max_items if f.type == "list" else v.max_len
    if lo is not None:
        out.append(f"min_length={lo}")
    if hi is not None:
        out.append(f"max_length={hi}")
    if v.pattern is not None:
        out.append(f"pattern={_pystr(v.pattern)}")
    return out


def _field_lines(message: Message, f: Field) -> list[str]:
    annotation = _base(message, f)
    if f.nullable or _omitted(f):
        annotation += " | None"
    args = _constraints(f)
    if _omitted(f):
        args.insert(0, "default=None")
    if args:
        line = f"{f.name}: {annotation} = Field({', '.join(args)})"
    else:
        line = f"{f.name}: {annotation}"
    out = _wrap("    ", line)
    doc = " ".join(f.doc.split())
    if f.unit and f.unit != "dimensionless":
        doc = f"{doc} Unit: {f.unit}.".strip()
    if doc:
        out += _docstring("    ", doc, [])
    return out


def _class_lines(message: Message, fields: list[Field]) -> list[str]:
    cls = _class_name(message)
    summary = str(message.doc.get("motivation", "")).strip() or f"The {cls} body."
    out = [f"class {cls}(BaseModel):"]
    out += _docstring("    ", summary, [])
    out.append("")
    out.append("    model_config = ConfigDict(use_attribute_docstrings=True)")
    if fields:
        out.append("")
    for f in fields:
        out += _field_lines(message, f)
    return out


def render_family(family: Family, spec_path: str) -> str:
    """Return the module of body models for one family."""
    nested = [(_as_message(n), list(n.fields)) for n in family.types]
    messages = [(m, _payload_fields(m)) for m in family.messages]
    scoped = nested + messages
    needs_literal = any(_uses_literal(f) for _, fs in scoped for f in fs)
    needs_field = any(_constraints(f) or _omitted(f) for _, fs in scoped for f in fs)

    out = [
        f"# GENERATED FROM {spec_path} - DO NOT EDIT",
        "#",
        "# Regenerate with:  poetry run pm-msgen generate",
    ]
    out += _docstring(
        "",
        f"REST body models for the ``{family.family}`` message family.",
        [
            f"Family version {family.version}. Derived from ``{spec_path}`` by "
            "the rest emitter; edit the spec, not this file.",
        ],
    )
    out += ["", "from __future__ import annotations", ""]
    if needs_literal:
        out += ["from typing import Literal", ""]
    names = "BaseModel, ConfigDict, Field" if needs_field else "BaseModel, ConfigDict"
    out.append(f"from pydantic import {names}")

    aliases: list[str] = []
    for message, fields in scoped:
        for f in fields:
            if _uses_literal(f):
                aliases += _wrap(
                    "", f"{_alias_name(message, f)} = {_literal_literal(f)}"
                )
    if aliases:
        out += ["", *aliases]

    for message, fields in scoped:
        out += ["", "", *_class_lines(message, fields)]
    out.append("")
    return "\n".join(out)


def render_init(families: list[Family], spec_glob: str) -> str:
    """The package marker, so ``models.generated.rest`` imports as a package."""
    out = [
        f"# GENERATED FROM {spec_glob} - DO NOT EDIT",
        "#",
        "# Regenerate with:  poetry run pm-msgen generate",
    ]
    out += _docstring(
        "",
        "REST body models, one module per message family.",
        [", ".join(f"``{f.family}``" for f in families) + "."],
    )
    out.append("")
    return "\n".join(out)
