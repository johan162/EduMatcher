"""Append a symbol to the YAML text, leaving everything else verbatim."""

from __future__ import annotations

from typing import Any

import yaml


def _content_end(node: yaml.Node) -> Any:
    """Where *node*'s last character is, ignoring comments that follow it.

    A block collection's own end mark sits at the next token, past any
    trailing comments and blank lines, which usually belong to the next
    section. The last leaf's end is where the content really stops.
    """
    if isinstance(node, yaml.ScalarNode) or (
        isinstance(node, yaml.CollectionNode) and node.flow_style
    ):
        return node.end_mark
    if isinstance(node, yaml.MappingNode):
        children = [child for pair in node.value for child in pair]
    else:
        children = list(node.value)
    if not children:
        return node.end_mark
    return max(
        (_content_end(child) for child in children),
        key=lambda mark: (mark.line, mark.column),
    )


def insert_symbol(text: str, symbol: str, payload: dict[str, Any]) -> str:
    """Append *symbol* to the ``symbols`` mapping, leaving the rest verbatim."""
    document = yaml.compose(text, Loader=yaml.SafeLoader)
    if not isinstance(document, yaml.MappingNode):
        raise ValueError("configuration must be a YAML mapping")
    symbols = next(
        (value for key, value in document.value if key.value == "symbols"), None
    )
    if not isinstance(symbols, yaml.MappingNode) or not symbols.value:
        raise ValueError("configuration has no symbols mapping to add to")
    if symbols.flow_style:
        raise ValueError("rewrite 'symbols' in block style; it is a flow mapping")

    last_key, last_value = symbols.value[-1]
    end = _content_end(last_value)
    at = end.line + (end.column > 0)
    lines = text.splitlines(keepends=True)
    if at and not lines[at - 1].endswith("\n"):
        lines[at - 1] += "\n"
    indent = " " * last_key.start_mark.column
    block = yaml.safe_dump(
        {symbol: payload}, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    lines.insert(at, "".join(indent + line for line in block.splitlines(True)))
    updated = "".join(lines)

    expected = yaml.safe_load(text)
    expected["symbols"][symbol] = payload
    if yaml.safe_load(updated) != expected:
        raise ValueError(
            "the symbol cannot be appended without changing the rest of the "
            "file; add it by hand"
        )
    return updated
