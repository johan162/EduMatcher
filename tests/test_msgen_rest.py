"""The REST body models pm-msgen emits (models/generated/rest/).

pm-api-gwy declares and validates the engine replies it forwards against these,
so they must model exactly what ``to_dict`` puts on the bus: topic-only fields
absent, an omitted-when-empty field optional, every other field required, and a
payload serialised back with ``exclude_unset`` unchanged.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.msgen import spec as spec_mod
from edumatcher.msgen.generators.python import (
    _class_name,  # pyright: ignore[reportPrivateUsage]
    _payload_fields,  # pyright: ignore[reportPrivateUsage]
)
from edumatcher.models.generated.rest import order as rest_order
from edumatcher.models.generated.rest import risk as rest_risk
from edumatcher.models.generated.rest import system as rest_system

_ROOT = Path(__file__).resolve().parents[1]
_REST = _ROOT / "src/edumatcher/models/generated/rest"


def _families() -> list[spec_mod.Family]:
    _transports, families = spec_mod.load_all(_ROOT / "spec")
    return list(families)


def test_generated_rest_models_are_black_clean() -> None:
    black = pytest.importorskip("black")
    mode = black.Mode(line_length=88)
    offenders = [
        path.name
        for path in sorted(_REST.glob("*.py"))
        if black.format_str(path.read_text(encoding="utf-8"), mode=mode)
        != path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_required_fields_are_exactly_the_ones_to_dict_always_writes() -> None:
    """Required = always on the bus; optional = omitted when empty; and a
    topic-only field (gateway_id of system.session_status.{gateway_id}) is not
    in the body at all."""
    for family in _families():
        module = importlib.import_module(
            f"edumatcher.models.generated.rest.{family.family}"
        )
        for message in family.messages:
            model: type[BaseModel] = getattr(module, _class_name(message))
            body = _payload_fields(message)
            assert set(model.model_fields) == {f.name for f in body}, message.name
            required = {n for n, f in model.model_fields.items() if f.is_required()}
            always = {
                f.name for f in body if not (f.omit_when_none or f.omit_when_empty)
            }
            assert required == always, message.name


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (rest_system.Reference, docs.REFERENCE_BUNDLE),
        (rest_system.Symbols, docs.SYMBOLS),
        (rest_system.SessionStatus, docs.SESSION_STATUS),
        (rest_system.HaltStatus, docs.HALT_STATUS),
        (rest_system.QuoteBootstrap, docs.QUOTE_BOOTSTRAP),
        (rest_system.QuoteLegs, docs.QUOTE_LEGS),
        (rest_system.RiskState, docs.ADMIN_RISK_STATE),
        (rest_system.Gateways, docs.ADMIN_GATEWAYS),
        (rest_order.Orders, docs.ORDERS_LIST),
        (rest_order.OrderAck, docs.ORDER_ACK_EVENT),
        (rest_order.OrderAck, docs.ORDER_REJECT_EVENT),
        (rest_order.OrderCancelled, docs.ORDER_CANCELLED_EVENT),
        (rest_risk.KillSwitchAck, docs.MASS_CANCEL),
        (rest_risk.SymbolHaltAck, docs.ADMIN_HALT_ACK),
        (rest_risk.SymbolResumeAck, docs.ADMIN_RESUME_ACK),
        (rest_risk.CancelSymbolAck, docs.ADMIN_KILL_SYMBOL),
        (rest_risk.KillSwitchGatewayAck, docs.ADMIN_KILL_GATEWAY),
        (rest_risk.KillSwitchGlobalAck, docs.ADMIN_KILL_GLOBAL),
    ],
)
def test_a_real_payload_round_trips_unchanged(
    model: type[BaseModel], payload: dict[str, Any]
) -> None:
    """What the engine publishes survives validation and serialisation intact.

    The wire form is the generated dataclass's ``to_dict()`` -- exactly what the
    engine sends -- not the hand-written example, which may leave out a field
    the engine always writes (``triggered_level: null``)."""
    family = model.__module__.rsplit(".", 1)[1]
    binding = getattr(
        importlib.import_module(f"edumatcher.models.generated.{family}"),
        model.__name__,
    )
    wire = binding.from_dict(payload).to_dict()
    dumped = model.model_validate(wire).model_dump(mode="json", exclude_unset=True)
    assert dumped == wire


def test_an_omitted_field_stays_omitted_rather_than_null() -> None:
    """The documented contract: structure ids are "omitted rather than null"
    for an ordinary order. exclude_unset keeps it that way."""
    event = rest_order.OrderCancelled.model_validate({"order_id": "O1"})
    assert event.model_dump(exclude_unset=True) == {"order_id": "O1"}
