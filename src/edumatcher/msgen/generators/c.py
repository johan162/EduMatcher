"""Emit the C binding for one family's text (CALF/RALF) projections.

Phase 4a. Binary (BALF) layout generation is Phase 4b and lives elsewhere.

Design constraints this file implements:

* **A C struct mirrors the transport projection, not the bus payload**
  (section 5.2). C clients speak CALF; they never see the internal bus, so a
  public CALF trade yields a three-field struct rather than the eleven-field
  bus message.
* **Fixed-size buffers, no allocation, ``int`` returns** — matching the style
  of the hand-written example clients, so generated code drops in beside them.
* **Coercion and validation are separate**, mirroring section 5.1.1: ``_parse``
  converts and reports a missing or unparseable field; ``_validate`` enforces
  the declared rules. A caller that wants leniency calls only the first.
* **Deterministic output** (section B.17): declaration order everywhere, no
  timestamps, no absolute paths.
"""

from __future__ import annotations

import textwrap

from edumatcher.msgen.spec import Family, Field, Message, TextEncoding

#: C type per spec type, for fields that are not enums or strings.
_C_TYPE = {
    "int": "int64_t",
    "ticks": "int64_t",
    "float": "double",
    "bool": "uint8_t",
}


def _upper(name: str) -> str:
    return name.upper()


def _struct_name(message: Message, transport: str) -> str:
    return f"edu_{message.name}_{transport}_t"


def _enum_name(message: Message, f: Field) -> str:
    return f"edu_{message.name}_{f.name}_t"


def _enum_member(message: Message, f: Field, value: str) -> str:
    return f"EDU_{_upper(message.name)}_{_upper(f.name)}_{value}"


def _c_field_type(message: Message, f: Field) -> str:
    if f.type == "enum":
        return _enum_name(message, f)
    if f.type == "string":
        return "char"
    return _C_TYPE[f.type]


def _comment(f: Field, enc: TextEncoding) -> str:
    keys = "/".join(enc.keys[f.name])
    unit = f", unit: {f.unit}" if f.unit else ""
    return f"/* {keys}{unit} */"


def _block_comment(indent: str, text: str, width: int = 76) -> list[str]:
    """Wrap prose into a C block comment."""
    lines = textwrap.wrap(" ".join(text.split()), width=width - len(indent) - 3)
    if not lines:
        return []
    if len(lines) == 1:
        return [f"{indent}/* {lines[0]} */"]
    out = [f"{indent}/* {lines[0]}"]
    out += [f"{indent} * {line}" for line in lines[1:]]
    out.append(f"{indent} */")
    return out


def _cstr(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _text_messages(family: Family) -> list[tuple[Message, str, TextEncoding]]:
    """Every (message, transport, encoding) with a text projection, in order."""
    out: list[tuple[Message, str, TextEncoding]] = []
    for message in family.messages:
        for transport in sorted(message.text_encoding):
            out.append((message, transport, message.text_encoding[transport]))
    return out


def _enum_decls(message: Message, enc: TextEncoding) -> list[str]:
    out: list[str] = []
    for name in enc.include:
        f = message.field_by_name(name)
        if f.type != "enum":
            continue
        assert f.values is not None
        type_name = _enum_name(message, f)
        out.append("typedef enum {")
        for index, value in enumerate(f.values, start=1):
            comma = "," if index < len(f.values) else ""
            out.append(f"    {_enum_member(message, f, value)} = {index}{comma}")
        out.append(f"}} {type_name};")
        out.append("")
        out.append(f"const char *edu_{message.name}_{f.name}_to_str({type_name} v);")
        out.append(
            f"int edu_{message.name}_{f.name}_from_str(const char *s, "
            f"{type_name} *out);"
        )
        out.append("")
    return out


def _struct_decl(message: Message, transport: str, enc: TextEncoding) -> list[str]:
    out = ["typedef struct {"]
    for name in enc.include:
        f = message.field_by_name(name)
        comment = _comment(f, enc)
        if f.type == "string":
            size = f.validate.max_len
            assert size is not None  # loader enforces max_len (B.18 rule 8)
            out.append(f"    char {f.name}[{size + 1}];  {comment}")
        else:
            out.append(f"    {_c_field_type(message, f)} {f.name};  {comment}")
    injected = ", ".join(enc.gateway_injected)
    if injected:
        out += _block_comment(
            "    ",
            f"{injected} are gateway-injected {transport.upper()} envelope "
            "keys, parsed into the frame around this message rather than into "
            "it - see design section 4.6.",
        )
    out.append(f"}} {_struct_name(message, transport)};")
    return out


def _parse_impl(message: Message, transport: str, enc: TextEncoding) -> list[str]:
    struct = _struct_name(message, transport)
    fn = f"edu_{message.name}_{transport}_parse"
    msgtype_const = f"EDU_{_upper(message.name)}_{_upper(transport)}_MSGTYPE"

    out = [
        f"int {fn}(const calf_message_t *in, {struct} *out) {{",
        "    const char *raw;",
        "    char *end;",
        "",
        "    if (!in || !out) return EDU_MSG_ERR_FIELD;",
        "    memset(out, 0, sizeof(*out));",
        "",
        f"    if (strcmp(in->msg_type, {msgtype_const}) != 0)",
        "        return EDU_MSG_ERR_MSGTYPE;",
        "",
    ]

    for name in enc.include:
        f = message.field_by_name(name)
        key = enc.keys[name][0]
        out.append(f"    raw = calf_get_field(in, {_cstr(key)});")
        out.append("    if (!raw) return EDU_MSG_ERR_FIELD;")

        if f.type == "string":
            size = f.validate.max_len
            assert size is not None
            out.append(f"    if (strlen(raw) > {size}) return EDU_MSG_ERR_OVERFLOW;")
            out.append(f"    memcpy(out->{f.name}, raw, strlen(raw));")
        elif f.type == "enum":
            out.append(
                f"    if (edu_{message.name}_{f.name}_from_str(raw, &out->{f.name})"
                " != EDU_MSG_OK)"
            )
            out.append("        return EDU_MSG_ERR_FIELD;")
        elif f.type == "float":
            out.append("    errno = 0;")
            out.append(f"    out->{f.name} = strtod(raw, &end);")
            out.append("    if (end == raw || *end != '\\0' || errno == ERANGE)")
            out.append("        return EDU_MSG_ERR_FIELD;")
        elif f.type == "bool":
            out.append("    errno = 0;")
            out.append("    { long long v = strtoll(raw, &end, 10);")
            out.append("      if (end == raw || *end != '\\0' || errno == ERANGE)")
            out.append("          return EDU_MSG_ERR_FIELD;")
            out.append(f"      out->{f.name} = (uint8_t)(v != 0); }}")
        else:  # int, ticks
            out.append("    errno = 0;")
            out.append(f"    out->{f.name} = (int64_t)strtoll(raw, &end, 10);")
            out.append("    if (end == raw || *end != '\\0' || errno == ERANGE)")
            out.append("        return EDU_MSG_ERR_FIELD;")
        out.append("")

    out.append("    return EDU_MSG_OK;")
    out.append("}")
    return out


def _validate_impl(message: Message, transport: str, enc: TextEncoding) -> list[str]:
    struct = _struct_name(message, transport)
    fn = f"edu_{message.name}_{transport}_validate"
    out = [
        f"int {fn}(const {struct} *m, char *err, size_t errlen) {{",
        "    if (!m) return EDU_MSG_ERR_FIELD;",
        "",
    ]

    def check(cond: str, text: str) -> None:
        out.append(f"    if ({cond}) {{")
        out.append(f"        if (err && errlen) snprintf(err, errlen, {_cstr(text)});")
        out.append("        return EDU_MSG_ERR_FIELD;")
        out.append("    }")

    emitted = False
    for name in enc.include:
        f = message.field_by_name(name)
        v = f.validate
        me = f"m->{f.name}"
        for key, op, word in (
            ("gt", "<=", "> "),
            ("ge", "<", ">= "),
            ("lt", ">=", "< "),
            ("le", ">", "<= "),
        ):
            bound = getattr(v, key)
            if bound is None:
                continue
            emitted = True
            literal = f"{bound}" if f.type == "float" else f"{int(bound)}"
            check(f"{me} {op} {literal}", f"{f.name} must be {word}{literal}")
        if f.type == "string" and v.min_len is not None:
            emitted = True
            check(
                f"strlen({me}) < {v.min_len}",
                f"{f.name} is shorter than min_len {v.min_len}",
            )
        if f.type == "string" and v.max_len is not None:
            emitted = True
            check(
                f"strlen({me}) > {v.max_len}",
                f"{f.name} exceeds max_len {v.max_len}",
            )

    if not emitted:
        out.append("    (void)err;")
        out.append("    (void)errlen;")
        out.append("")
    out.append("    return EDU_MSG_OK;")
    out.append("}")
    return out


def _enum_impls(message: Message, enc: TextEncoding) -> list[str]:
    out: list[str] = []
    for name in enc.include:
        f = message.field_by_name(name)
        if f.type != "enum":
            continue
        assert f.values is not None
        type_name = _enum_name(message, f)

        out.append(f"const char *edu_{message.name}_{f.name}_to_str({type_name} v) {{")
        out.append("    switch (v) {")
        for value in f.values:
            out.append(f"        case {_enum_member(message, f, value)}:")
            out.append(f"            return {_cstr(value)};")
        out.append("        default:")
        out.append('            return "";')
        out.append("    }")
        out.append("}")
        out.append("")

        out.append(
            f"int edu_{message.name}_{f.name}_from_str(const char *s, "
            f"{type_name} *out) {{"
        )
        out.append("    if (!s || !out) return EDU_MSG_ERR_FIELD;")
        for value in f.values:
            out.append(f"    if (strcmp(s, {_cstr(value)}) == 0) {{")
            out.append(f"        *out = {_enum_member(message, f, value)};")
            out.append("        return EDU_MSG_OK;")
            out.append("    }")
        out.append("    return EDU_MSG_ERR_FIELD;")
        out.append("}")
        out.append("")
    return out


def render_header(family: Family, spec_path: str) -> str:
    """Return the generated ``.h`` for one family."""
    guard = f"EDUMATCHER_{_upper(family.family)}_H"
    lines = [
        f"/* GENERATED FROM {spec_path} - DO NOT EDIT",
        " *",
        " * Regenerate with:  make msgen  (or: poetry run pm-msgen generate)",
        " *",
        f" * Typed C bindings for the '{family.family}' message family, one struct",
        " * per declared text projection. A struct mirrors what its transport",
        " * actually carries, not the internal bus payload - see design section 5.2.",
        " */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stddef.h>",
        "#include <stdint.h>",
        "",
        '#include "calf_parser.h"',
        '#include "edumatcher_msg.h"',
        "",
        f"#define EDU_{_upper(family.family)}_FAMILY_VERSION {family.version}",
        "",
    ]

    for message, transport, enc in _text_messages(family):
        lines += _block_comment(
            "",
            f"--- {message.name} / {transport.upper()} {enc.msg_type} --- "
            + " ".join(str(message.doc.get("motivation", "")).split()),
        )
        lines.append("")
        lines.append(
            f"#define EDU_{_upper(message.name)}_{_upper(transport)}_MSGTYPE "
            f"{_cstr(enc.msg_type)}"
        )
        lines.append("")
        lines += _enum_decls(message, enc)
        lines += _struct_decl(message, transport, enc)
        lines.append("")
        struct = _struct_name(message, transport)
        lines += _block_comment(
            "",
            "Convert an already-tokenised line into the typed struct. Coerces "
            "but does not validate, mirroring the Python binding's from_dict "
            "(design section 5.1.1). Returns EDU_MSG_OK, EDU_MSG_ERR_MSGTYPE, "
            "EDU_MSG_ERR_FIELD or EDU_MSG_ERR_OVERFLOW.",
        )
        lines.append(
            f"int edu_{message.name}_{transport}_parse(const calf_message_t *in, "
            f"{struct} *out);"
        )
        lines.append("")
        lines += _block_comment(
            "",
            "Enforce the rules declared in the spec. Writes a message into err "
            "when it fails and errlen is non-zero. Returns EDU_MSG_OK or "
            "EDU_MSG_ERR_FIELD.",
        )
        lines.append(
            f"int edu_{message.name}_{transport}_validate(const {struct} *m, "
            "char *err, size_t errlen);"
        )
        lines.append("")

    lines.append(f"#endif /* {guard} */")
    return "\n".join(lines) + "\n"


def render_source(family: Family, spec_path: str) -> str:
    """Return the generated ``.c`` for one family."""
    lines = [
        f"/* GENERATED FROM {spec_path} - DO NOT EDIT",
        " *",
        " * Regenerate with:  make msgen  (or: poetry run pm-msgen generate)",
        " */",
        f'#include "edumatcher_{family.family}.h"',
        "",
        "#include <errno.h>",
        "#include <stdio.h>",
        "#include <stdlib.h>",
        "#include <string.h>",
        "",
    ]

    for message, transport, enc in _text_messages(family):
        lines += _enum_impls(message, enc)
        lines += _parse_impl(message, transport, enc)
        lines.append("")
        lines += _validate_impl(message, transport, enc)
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"
