from __future__ import annotations

import pytest

from edumatcher.config_gen.gateway_spec import parse_gateway_spec
from edumatcher.models.order import SmpAction
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole


def test_parse_gateway_spec_defaults() -> None:
    parsed = parse_gateway_spec("trader01")
    assert parsed.gateway_id == "TRADER01"
    assert parsed.role == ParticipantRole.TRADER
    assert parsed.disconnect_behaviour == DisconnectBehaviour.CANCEL_ALL


def test_parse_gateway_spec_smp_action_defaults_none() -> None:
    """smp_action is not part of the colon-delimited spec syntax -- it is
    always SmpAction.NONE from parse_gateway_spec() and is only set
    afterwards via the separate --gateway-smp flag (see cli.py)."""
    parsed = parse_gateway_spec("TRADER01:TRADER:CANCEL_ALL:Some desc")
    assert parsed.smp_action == SmpAction.NONE


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


def test_parse_gateway_spec_description() -> None:
    parsed = parse_gateway_spec("MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY:Primary MM")
    assert parsed.description == "Primary MM"
    assert parsed.role == ParticipantRole.MARKET_MAKER


def test_parse_gateway_spec_description_defaults_empty() -> None:
    parsed = parse_gateway_spec("TRADER01")
    assert parsed.description == ""


def test_parse_gateway_spec_too_many_parts() -> None:
    with pytest.raises(ValueError, match="expected ID"):
        parse_gateway_spec("A:B:C:D:E")
