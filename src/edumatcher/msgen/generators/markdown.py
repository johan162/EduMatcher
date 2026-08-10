"""The message reference, rendered from the spec.

Phase 6.2, and the reason the generator was built. Section 1 named three
surfaces that drift — publisher, subscriber, documentation — and the first two
have been generated since 5.1. This is the third. Four phases running, every
family's adoption turned up documentation believing in something the wire does
not carry (sections 26.6, 27.3, 27.6, 28.3), and each time the note was "this
is the argument for 6.2 generating the reference rather than maintaining it".

What this module deliberately does **not** render is anything the spec cannot
state. The narrative half of the page — how a bus works, what the transports
are, the CALF protocol — lives in ``270-preamble.md`` and is copied through
verbatim. Generating prose from a spec that has no field for it is how a
documentation generator starts inventing things, which is the failure this one
exists to remove rather than relocate.
"""

from __future__ import annotations

from edumatcher.msgen.spec import Family, Field, Message, NestedType

_BANNER = """<!--
  GENERATED FILE - DO NOT EDIT.

  The reference sections below are rendered from spec/messages/*.yaml by
  `pm-msgen generate`. Edit the spec, not this file; `pm-msgen check` fails in
  CI when the two disagree.

  The narrative sections come from docs/user-guide/270-preamble.md, which IS
  hand-written and is the right place for anything the spec cannot state.
-->
"""


def _escape(text: str) -> str:
    """Make a doc string safe inside a markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def _presence(f: Field) -> str:
    """One phrase per presence regime — the four of design section B.7.0."""
    if f.required:
        return "required"
    if f.omit_when_none:
        return "omitted when unset"
    if f.omit_when_empty:
        return "omitted when empty"
    if f.nullable:
        return "`null` when unset"
    # Regime 1: always present, carrying `default` when the producer omits it.
    # The `or f.default == ""` this used to also test was dead — `""` is not
    # `None`, so the first half already covers a declared empty-string default,
    # which is the commonest one in the tree.
    if f.default is not None:
        return f"defaults to `{f.default!r}`"
    return "optional"


def _type_of(f: Field) -> str:
    if f.type == "nested":
        return f"[`{f.ref}`](#{str(f.ref).lower()})"
    if f.type == "list":
        inner = f"[`{f.ref}`](#{str(f.ref).lower()})" if f.ref else f"`{f.item}`"
        return f"list of {inner}"
    if f.type == "enum" and f.values:
        return "enum: " + ", ".join(f"`{v}`" for v in f.values)
    return f"`{f.type}`"


def _rules(f: Field) -> str:
    v = f.validate
    parts = [
        f"{name} {value}"
        for name, value in (
            ("gt", v.gt),
            ("ge", v.ge),
            ("lt", v.lt),
            ("le", v.le),
            ("max_len", v.max_len),
            ("min_len", v.min_len),
            ("min_items", v.min_items),
            ("max_items", v.max_items),
        )
        if value is not None
    ]
    if v.pattern:
        parts.append(f"pattern `{v.pattern}`")
    if f.unit:
        parts.append(f"unit `{f.unit}`")
    return ", ".join(parts) or "—"


def _field_table(fields: tuple[Field, ...]) -> list[str]:
    out = [
        "| Field | Type | Presence | Rules | Description |",
        "|---|---|---|---|---|",
    ]
    for f in fields:
        out.append(
            f"| `{f.name}` | {_type_of(f)} | {_presence(f)} | {_rules(f)} "
            f"| {_escape(f.doc)} |"
        )
    return out


def _record(t: NestedType) -> list[str]:
    out = [f"#### `{t.name}`", ""]
    if t.doc:
        out += [_escape(t.doc), ""]
    out += _field_table(t.fields) + [""]
    return out


def _message(m: Message) -> list[str]:
    doc = m.doc or {}
    # A message with no topic never touches the bus — the BALF-only frame of
    # design section B.4. It is named by its spec name instead.
    heading = f"`{m.topic}`" if m.topic else f"`{m.name}` (no bus topic)"
    out = [f"### {heading}", ""]

    published_by = ", ".join(f"`{p}`" for p in doc.get("published_by", ()))
    transports = ", ".join(f"`{t}`" for t in m.transport)
    out += [f"**Published by:** {published_by}", ""]
    out += [f"**Transport:** {transports}", ""]
    if doc.get("since"):
        out += [f"**Since:** {doc['since']}", ""]

    out += [_escape(doc.get("motivation", "")), ""]

    if m.fields:
        out += _field_table(m.fields) + [""]
    else:
        out += ["*No payload fields.*", ""]

    if doc.get("example_note"):
        out += ["!!! note", ""]
        for line in _escape(doc["example_note"]).split(". "):
            if line.strip():
                out += [f"    {line.strip().rstrip('.')}.", ""]

    see = doc.get("see_also") or ()
    if see:
        out += ["**See also:** " + ", ".join(f"`{s}`" for s in see), ""]
    return out


def _summary(families: list[Family]) -> list[str]:
    out = [
        "## Topic index",
        "",
        "Every topic in the system, and which process puts it on the wire.",
        "",
        "| Topic | Family | Published by |",
        "|---|---|---|",
    ]
    rows = [
        (
            m.topic or f"{m.name} (no bus topic)",
            f.family,
            ", ".join(f"`{p}`" for p in (m.doc or {}).get("published_by", ())),
        )
        for f in families
        for m in f.messages
    ]
    for topic, family, who in sorted(rows):
        out.append(f"| `{topic}` | `{family}` | {who} |")
    out.append("")
    return out


def render_reference(families: list[Family], preamble: str) -> str:
    """Render the whole page: banner, hand-written preamble, generated body.

    The preamble is passed through **byte for byte**. An earlier draft
    normalised blank-line runs across the whole page, which quietly reformatted
    the hand-written half every time the generator ran — a documentation
    generator editing the prose a human owns, which is a smaller version of
    exactly what this tool exists to stop. Only the body it produces is
    normalised.
    """
    body: list[str] = list(_summary(families))
    for family in sorted(families, key=lambda f: f.family):
        body += [f"## Family `{family.family}`", ""]
        if family.types:
            body += ["### Record types", ""]
            for t in family.types:
                body += _record(t)
        for m in family.messages:
            body += _message(m)

    # Collapse the blank-line runs the section joins produce, so the output is
    # stable regardless of which optional blocks a given message has.
    text = "\n".join(body)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return _BANNER + "\n" + preamble.rstrip("\n") + "\n\n" + text.rstrip("\n") + "\n"
