"""--comment-default-config-fields must document every recognised key.

The block is hand-maintained text, so a new loader field or section silently
goes undocumented unless something compares it to the code. This compares it
to the verifier's accepted-key tables (themselves pinned to the loaders) and
to the config viewer's list of known top-level sections.
"""

from __future__ import annotations

import pytest

from edumatcher.config_gen.cli_comments import build_default_engine_field_comment_lines
from edumatcher.config_show.extract import KNOWN_TOP_LEVEL
from edumatcher.cverifier import layer2_schema

LINES = build_default_engine_field_comment_lines({})


def _shape(block: str) -> str:
    start = LINES.index(f"{block}:")
    end = LINES.index("", start)
    return "\n".join(LINES[start:end])


def _notes(block: str) -> str:
    start = LINES.index(f"{block} entries")
    end = LINES.index("", start)
    return "\n".join(LINES[start:end])


@pytest.mark.parametrize("key", sorted(KNOWN_TOP_LEVEL))
def test_every_top_level_section_has_a_shape_entry(key: str) -> None:
    assert any(line.startswith(f"{key}:") for line in LINES), key


@pytest.mark.parametrize("block", sorted(layer2_schema._PROCESS_BLOCK_KEYS))
def test_every_process_block_field_is_shown_and_explained(block: str) -> None:
    shape, notes = _shape(block), _notes(block)
    for key in sorted(layer2_schema._PROCESS_BLOCK_KEYS[block]):
        assert f"{key}:" in shape, f"{block}.{key} missing from the shape example"
        assert key in notes, f"{block}.{key} missing from the field notes"


def test_api_gateway_and_log_client_fields_are_shown_and_explained() -> None:
    shape, notes = _shape("api_gateways"), _notes("api_gateways")
    for key in sorted(
        layer2_schema._API_INSTANCE_KEYS
        | layer2_schema._API_RATE_LIMIT_KEYS
        | layer2_schema._API_TIMEOUT_KEYS
        | layer2_schema._API_CREDENTIAL_KEYS
    ):
        assert f"{key}:" in shape, f"api_gateways {key} missing from the shape example"
        assert key in notes, f"api_gateways {key} missing from the field notes"
    log_shape, log_notes = _shape("log_server"), _notes("log_server")
    for key in sorted(layer2_schema._LOG_CLIENT_KEYS):
        assert f"{key}:" in log_shape
        assert f"client.{key}" in log_notes
