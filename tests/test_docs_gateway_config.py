"""The formal specification's line-gateway blocks are the code's.

`market_data_gateway`, `post_trade_gateway` and `dc_gateway` are each stated
twice in the normative reference -- a grammar block in §3 and a field table
in §6 -- and a field added to (or a default changed in) the runtime config
dataclass without the docs would otherwise go unnoticed. That is how
`max_connections` could have reached pm-ralf-gwy and pm-dc-gwy undocumented.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.ralf_gateway.config import RalfGatewayConfig

FORMAL = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "books"
    / "reference-manual"
    / "part-3-configuration"
    / "030-formal-specification.md"
)

#: Runtime fields that are not YAML keys: each loader takes them from the
#: bus-address constants (or a CLI flag) and ignores the file.
_NOT_YAML = frozenset(
    {"engine_pub_addr", "engine_pull_addr", "index_pub_addr", "drop_copy_pub_addr"}
)

#: Defaults resolved from the environment at run time, so the documented
#: value is the unset-variable one and cannot be compared here.
_ENV_DEFAULTS = frozenset({"bind_address"})

BLOCKS = [
    ("MdGwyProcSpec", "### 6.3 `market_data_gateway`", MarketDataGatewayConfig),
    ("RalfGwyProcSpec", "### 6.4 `post_trade_gateway`", RalfGatewayConfig),
    ("DcGwyProcSpec", "### 6.6 `dc_gateway`", DcGatewayConfig),
]


def _grammar(spec_type: str) -> dict[str, Any]:
    """`name: ? Type = default  ∈ ...` lines of one §3 block, in order."""
    text = FORMAL.read_text()
    block = text.split(f"\n{spec_type}:", 1)[1].split("\n\n", 1)[0]
    entries = re.findall(r"^  (\w+):\s+\? \S+ = (.+?)(?:\s{2,}∈.*)?$", block, re.M)
    return {name: yaml.safe_load(default) for name, default in entries}


def _table(heading: str) -> dict[str, Any]:
    """`| `name` | `Type` | Req | Default | ... |` rows of one §6 table."""
    text = FORMAL.read_text()
    start = text.index(heading)
    end = text.find("\n### ", start + len(heading))
    section = text[start:end]
    rows = re.findall(r"^\| `(\w+)` \| `[^`]+` \| [^|]* \| ([^|]*) \|", section, re.M)
    return {name: yaml.safe_load(default.strip().strip("`")) for name, default in rows}


def _code_defaults(cls: type) -> dict[str, Any]:
    instance = cls()
    out: dict[str, Any] = {}
    for f in fields(cls):
        if f.name in _NOT_YAML:
            continue
        value = getattr(instance, f.name)
        out[f.name] = list(value) if isinstance(value, tuple) else value
    return out


@pytest.mark.parametrize(("spec_type", "heading", "cls"), BLOCKS)
def test_the_grammar_lists_exactly_the_yaml_fields_in_order(
    spec_type: str, heading: str, cls: type
) -> None:
    assert list(_grammar(spec_type)) == list(_code_defaults(cls))


@pytest.mark.parametrize(("spec_type", "heading", "cls"), BLOCKS)
def test_the_grammar_states_the_code_defaults(
    spec_type: str, heading: str, cls: type
) -> None:
    documented = _grammar(spec_type)
    for name, default in _code_defaults(cls).items():
        if name in _ENV_DEFAULTS:
            continue
        assert documented[name] == default, name


@pytest.mark.parametrize(("spec_type", "heading", "cls"), BLOCKS)
def test_the_section_table_matches_the_grammar(
    spec_type: str, heading: str, cls: type
) -> None:
    assert _table(heading) == _grammar(spec_type)
