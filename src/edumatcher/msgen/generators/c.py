"""Emit the C binding for one family's external projections.

Text (CALF/RALF) key-value projections and BALF fixed binary frames.

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

import re
import textwrap

from edumatcher.msgen.spec import (
    BinaryEncoding,
    Family,
    Field,
    LayoutEntry,
    Message,
    TextEncoding,
)

_CHAR_ARRAY = re.compile(r"char\[(\d+)\]")

#: ``repr`` -> C type for a binary field. Signed/unsigned is preserved because
#: the wire says so; the struct field is what a client reads directly.
_REPR_C_TYPE = {
    "u8": "uint8_t",
    "i8": "int8_t",
    "u16": "uint16_t",
    "i16": "int16_t",
    "u32": "uint32_t",
    "i32": "int32_t",
    "u64": "uint64_t",
    "i64": "int64_t",
    "f32": "float",
    "f64": "double",
}

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
    return _enum_decls_for(message, list(enc.include))


def _enum_decls_for(message: Message, names: list[str | None]) -> list[str]:
    """Emit the enum type, ``to_str`` and ``from_str`` for each enum field."""
    out: list[str] = []
    for name in names:
        if name is None:
            continue
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
    return _enum_impls_for(message, list(enc.include))


def _enum_impls_for(message: Message, names: list[str | None]) -> list[str]:
    out: list[str] = []
    for name in names:
        if name is None:
            continue
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


def _binary_messages(family: Family) -> list[tuple[Message, str, BinaryEncoding]]:
    """Every (message, transport, encoding) with a binary layout, in order."""
    out: list[tuple[Message, str, BinaryEncoding]] = []
    for message in family.messages:
        for transport in sorted(message.binary_encoding):
            out.append((message, transport, message.binary_encoding[transport]))
    return out


def _bin_struct_name(message: Message, transport: str) -> str:
    return f"edu_{message.name}_{transport}_t"


def _bin_field_decl(message: Message, entry: LayoutEntry) -> str:
    """Declare one laid-out field, typed by what it is rather than by its repr.

    A ``scale``d integer is a price, so it becomes a ``double`` the caller can
    use; the raw ``i64`` never escapes the parser. An enum becomes the generated
    enum type rather than the byte that carries it.
    """
    assert entry.field is not None and entry.repr is not None
    f = message.field_by_name(entry.field)
    comment = f"/* {entry.repr} @{entry.offset}"
    comment += f", unit: {f.unit}" if f.unit else ""
    if entry.scale:
        comment += f", wire is x{entry.scale}"
    comment += " */"

    match = _CHAR_ARRAY.fullmatch(entry.repr)
    if match:
        size = int(match.group(1))
        return f"    char {f.name}[{size + 1}];  {comment}"
    if f.type == "enum":
        return f"    {_enum_name(message, f)} {f.name};  {comment}"
    if entry.scale:
        return f"    double {f.name};  {comment}"
    return f"    {_REPR_C_TYPE[entry.repr]} {f.name};  {comment}"


def _bin_read(entry: LayoutEntry, message: Message) -> list[str]:
    """Read one field out of the body at its declared offset."""
    assert entry.field is not None and entry.repr is not None
    f = message.field_by_name(entry.field)
    src = f"body + {entry.offset}"
    match = _CHAR_ARRAY.fullmatch(entry.repr)

    if match:
        size = int(match.group(1))
        return [
            f"    memcpy(out->{f.name}, {src}, {size});",
            f"    out->{f.name}[{size}] = '\\0';",
        ]
    if f.type == "enum":
        assert entry.enum_map is not None
        out = [f"    switch (edu_rd_{entry.repr}({src})) {{"]
        for value, code in entry.enum_map.items():
            out.append(f"        case {code}:")
            out.append(
                f"            out->{f.name} = {_enum_member(message, f, value)};"
            )
            out.append("            break;")
        out += [
            "        default:",
            "            return EDU_MSG_ERR_FIELD;",
            "    }",
        ]
        return out
    if entry.scale:
        return [
            f"    out->{f.name} = (double)edu_rd_{entry.repr}({src}) / {entry.scale}.0;"
        ]
    return [f"    out->{f.name} = edu_rd_{entry.repr}({src});"]


def _bin_readers_used(family: Family) -> list[str]:
    """Which little-endian readers this family's layouts actually need."""
    used: set[str] = set()
    for _message, _transport, enc in _binary_messages(family):
        for entry in enc.layout:
            if entry.repr and not _CHAR_ARRAY.fullmatch(entry.repr):
                used.add(entry.repr)
    return sorted(used)


#: Emission order for the byte-wise readers. Each signed reader is written in
#: terms of its unsigned twin, so the twin must come first.
_READER_ORDER = ("u8", "i8", "u16", "i16", "u32", "i32", "u64", "i64")

_LE_READERS = {
    "u8": ("uint8_t", "return p[0];"),
    "i8": ("int8_t", "return (int8_t)p[0];"),
    "u16": ("uint16_t", "return (uint16_t)(p[0] | (p[1] << 8));"),
    "i16": ("int16_t", "return (int16_t)(p[0] | (p[1] << 8));"),
    "u32": (
        "uint32_t",
        "return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |\n"
        "           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);",
    ),
    "i32": ("int32_t", "return (int32_t)edu_rd_u32(p);"),
    "u64": (
        "uint64_t",
        "uint64_t v = 0;\n"
        "    int i;\n"
        "    for (i = 7; i >= 0; i--) v = (v << 8) | p[i];\n"
        "    return v;",
    ),
    "i64": ("int64_t", "return (int64_t)edu_rd_u64(p);"),
}


def _bin_reader_impls(family: Family) -> list[str]:
    """Emit only the readers used, byte-wise so alignment never matters.

    Reading through a cast pointer would be undefined behaviour on a body that
    is not suitably aligned, and BALF offsets are packed rather than aligned —
    ``side`` sits at body offset 48 with no padding before it.
    """
    out: list[str] = []
    needed = _bin_readers_used(family)
    # i32/i64 are written in terms of the unsigned readers, so pull those in.
    for token in list(needed):
        if token == "i64" and "u64" not in needed:
            needed.append("u64")
        if token == "i32" and "u32" not in needed:
            needed.append("u32")
    # Fixed order, not sorted: edu_rd_i64 is written in terms of edu_rd_u64, so
    # the unsigned reader must be defined first or the signed one calls an
    # undeclared function. Sorting alphabetically put i64 first and -Werror
    # caught it.
    for token in _READER_ORDER:
        if token not in needed or token not in _LE_READERS:
            continue
        ctype, body = _LE_READERS[token]
        out.append(f"static {ctype} edu_rd_{token}(const uint8_t *p) {{")
        out += [f"    {line}" for line in body.split("\n")]
        out.append("}")
        out.append("")
    return out


def _bin_parse_impl(message: Message, transport: str, enc: BinaryEncoding) -> list[str]:
    struct = _bin_struct_name(message, transport)
    fn = f"edu_{message.name}_{transport}_parse"
    prefix = f"EDU_{_upper(message.name)}_{_upper(transport)}"

    out = [
        f"int {fn}(const uint8_t *frame, size_t len, {struct} *out) {{",
        "    const uint8_t *body;",
        "",
        "    if (!frame || !out) return EDU_MSG_ERR_FIELD;",
        f"    if (len < {enc.frame_size - enc.body_size}) return EDU_MSG_ERR_SHORT;",
        "    if (frame[0] != EDU_BALF_MAGIC) return EDU_MSG_ERR_MAGIC;",
        "    if (frame[1] != EDU_BALF_VERSION) return EDU_MSG_ERR_VERSION;",
        f"    if (frame[2] != {prefix}_MSGTYPE) return EDU_MSG_ERR_MSGTYPE;",
        f"    if (len != {prefix}_FRAME_SIZE) return EDU_MSG_ERR_LENGTH;",
        "",
        "    memset(out, 0, sizeof(*out));",
        f"    body = frame + {enc.frame_size - enc.body_size};",
        "",
    ]
    for entry in sorted(enc.layout, key=lambda e: e.offset):
        if entry.is_reserved:
            continue
        out += _bin_read(entry, message)
    out += ["", "    return EDU_MSG_OK;", "}"]
    return out


def _bin_validate_impl(
    message: Message, transport: str, enc: BinaryEncoding
) -> list[str]:
    struct = _bin_struct_name(message, transport)
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
    for entry in sorted(enc.layout, key=lambda e: e.offset):
        if entry.is_reserved:
            continue
        assert entry.field is not None
        f = message.field_by_name(entry.field)
        v = f.validate
        me = f"m->{f.name}"
        unsigned = (
            entry.repr is not None
            and entry.repr.startswith("u")
            and not entry.scale
            and f.type != "enum"
        )
        for key, op, word in (
            ("gt", "<=", "> "),
            ("ge", "<", ">= "),
            ("lt", ">=", "< "),
            ("le", ">", "<= "),
        ):
            bound = getattr(v, key)
            if bound is None:
                continue
            # `ge: 0` against an unsigned wire type cannot fail, and emitting it
            # is not merely redundant: gcc rejects `unsigned < 0` under
            # -Wtype-limits, so the generated file would not compile at all.
            # The Python binding still enforces the rule, where the value is a
            # signed int and the check is meaningful.
            if unsigned and key == "ge" and bound <= 0:
                continue
            emitted = True
            literal = (
                f"{bound}" if entry.scale or f.type == "float" else f"{int(bound)}"
            )
            check(f"{me} {op} {literal}", f"{f.name} must be {word}{literal}")
        if f.type == "string" and v.max_len is not None:
            emitted = True
            check(
                f"strlen({me}) > {v.max_len}",
                f"{f.name} exceeds max_len {v.max_len}",
            )

    if not emitted:
        out += ["    (void)err;", "    (void)errlen;", ""]
    out += ["    return EDU_MSG_OK;", "}"]
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
        " * per declared external projection. A struct mirrors what its transport",
        " * actually carries, not the internal bus payload - see design section 5.2.",
        " */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stddef.h>",
        "#include <stdint.h>",
        "",
    ]
    # calf_parser.h supplies calf_message_t, which only a text projection needs.
    # A BALF-only family must not drag the CALF tokeniser into a client's build.
    if _text_messages(family):
        lines.append('#include "calf_parser.h"')
    lines += [
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

    for message, transport, binary in _binary_messages(family):
        prefix = f"EDU_{_upper(message.name)}_{_upper(transport)}"
        lines += _block_comment(
            "",
            f"--- {message.name} / {transport.upper()} 0x{binary.msg_type:02X} --- "
            + " ".join(str(message.doc.get("motivation", "")).split()),
        )
        lines.append("")
        lines.append(f"#define {prefix}_MSGTYPE 0x{binary.msg_type:02X}")
        lines.append(f"#define {prefix}_FRAME_SIZE {binary.frame_size}")
        lines.append(f"#define {prefix}_BODY_SIZE {binary.body_size}")
        if binary.price_scale is not None:
            lines.append(f"#define {prefix}_PRICE_SCALE {binary.price_scale}LL")
        lines.append("")
        lines += _enum_decls_for(message, [e.field for e in binary.layout if e.field])
        lines.append("typedef struct {")
        for entry in sorted(binary.layout, key=lambda e: e.offset):
            if entry.is_reserved:
                lines.append(
                    f"    /* bytes {entry.offset}..{entry.offset + entry.size} "
                    "reserved, must be zero */"
                )
                continue
            lines.append(_bin_field_decl(message, entry))
        lines.append(f"}} {_bin_struct_name(message, transport)};")
        lines.append("")
        struct = _bin_struct_name(message, transport)
        lines += _block_comment(
            "",
            f"Parse one complete {binary.frame_size}-byte frame, header included. "
            "Checks magic, version, msg_type and length before reading any "
            "field: a frame of the wrong length is not this message, and "
            "unpacking it anyway would read neighbouring bytes as values. "
            "Coerces but does not validate (design section 5.1.1). Returns "
            "EDU_MSG_OK, EDU_MSG_ERR_SHORT, EDU_MSG_ERR_MAGIC, "
            "EDU_MSG_ERR_VERSION, EDU_MSG_ERR_MSGTYPE, EDU_MSG_ERR_LENGTH or "
            "EDU_MSG_ERR_FIELD.",
        )
        lines.append(
            f"int edu_{message.name}_{transport}_parse(const uint8_t *frame, "
            f"size_t len, {struct} *out);"
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

    lines += _bin_reader_impls(family)

    for message, transport, enc in _text_messages(family):
        lines += _enum_impls(message, enc)
        lines += _parse_impl(message, transport, enc)
        lines.append("")
        lines += _validate_impl(message, transport, enc)
        lines.append("")

    for message, transport, binary in _binary_messages(family):
        lines += _enum_impls_for(message, [e.field for e in binary.layout if e.field])
        lines += _bin_parse_impl(message, transport, binary)
        lines.append("")
        lines += _bin_validate_impl(message, transport, binary)
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"
