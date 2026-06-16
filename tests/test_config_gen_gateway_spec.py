from __future__ import annotations

import pytest

from edumatcher.config_gen.gateway_spec import parse_gateway_spec
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole


def test_parse_gateway_spec_defaults() -> None:
    parsed = parse_gateway_spec("trader01")
    assert parsed.gateway_id == "TRADER01"
    assert parsed.role == ParticipantRole.TRADER
    assert parsed.disconnect_behaviour == DisconnectBehaviour.CANCEL_ALL


def test_parse_gateway_spec_mm_default_disconnect() -> None:
    parsed = parse_gateway_spec("MM01:MARKET_MAKER")
    assert parsed.role == ParticipantRole.MARKET_MAKER
    assert parsed.disconnect_behaviour == DisconnectBehaviour.CANCEL_QUOTES_ONLY


def test_parse_gateway_spec_explicit_disconnect() -> None:
    parsed = parse_gateway_spec("OPS01:ADMIN:LEAVE_ALL")
    assert parsed.role == ParticipantRole.ADMIN
    assert parsed.disconnect_behaviour == DisconnectBehaviour.LEAVE_ALL


def test_parse_gateway_spec_invalid_role() -> None:
    with pytest.raises(ValueError, match="Invalid role"):
        parse_gateway_spec("GW1:NOPE")


def test_parse_gateway_spec_invalid_disconnect() -> None:
    with pytest.raises(ValueError, match="Invalid disconnect_behaviour"):
        parse_gateway_spec("GW1:TRADER:WHATEVER")
