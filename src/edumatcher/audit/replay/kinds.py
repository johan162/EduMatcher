"""Message kinds: each topic with its wildcard removed.

A Fact's ``kind`` is its topic with the actor or symbol stripped --
``order.ack.TRADER01`` becomes ``order.ack`` -- and both the state model and
the link resolver dispatch on it. Neither may spell one as a literal: a
publisher-side rename would leave them compiling, running, and silently
reacting to nothing, which is the exact failure ``pm-msgen``'s topic constants
and the literal gate in ``tests/test_msgen_literals.py`` exist to prevent.

So the names below are derived from the generated constants. For a
wildcard topic the generator exports a ``PREFIX_*`` ending in a dot, and the
kind is that prefix without it; for a fixed topic the ``TOPIC_*`` constant is
already the kind.
"""

from __future__ import annotations

from edumatcher.models.generated.circuit_breaker import (
    PREFIX_CIRCUIT_BREAKER_EXTEND,
    PREFIX_CIRCUIT_BREAKER_HALT,
    PREFIX_CIRCUIT_BREAKER_RESUME,
)
from edumatcher.models.generated.order import (
    PREFIX_ORDER_ACK,
    PREFIX_ORDER_AMENDED,
    PREFIX_ORDER_CANCELLED,
    PREFIX_ORDER_EXPIRED,
    PREFIX_ORDER_FILL,
    TOPIC_ORDER_AMEND,
    TOPIC_ORDER_CANCEL,
    TOPIC_ORDER_COMBO,
    TOPIC_ORDER_NEW,
    TOPIC_ORDER_OCO,
)
from edumatcher.models.generated.quote import PREFIX_QUOTE_ACK, TOPIC_QUOTE_NEW
from edumatcher.models.generated.session import (
    TOPIC_SESSION_STATE,
    TOPIC_SESSION_TRANSITION,
)
from edumatcher.models.generated.structure import PREFIX_OCO_ACK, PREFIX_OCO_CANCELLED
from edumatcher.models.generated.system import (
    PREFIX_GATEWAY_AUTH,
    PREFIX_GATEWAY_BYE,
    TOPIC_GATEWAY_CONNECT,
    TOPIC_GATEWAY_DISCONNECT,
    TOPIC_RECOVERY_ITEM,
    TOPIC_STARTUP_RECOVERY,
)
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED


def _kind(prefix: str) -> str:
    """``order.ack.`` -> ``order.ack``."""
    return prefix.rstrip(".")


ORDER_NEW = TOPIC_ORDER_NEW
ORDER_CANCEL = TOPIC_ORDER_CANCEL
ORDER_AMEND = TOPIC_ORDER_AMEND
ORDER_OCO = TOPIC_ORDER_OCO
ORDER_COMBO = TOPIC_ORDER_COMBO
ORDER_ACK = _kind(PREFIX_ORDER_ACK)
ORDER_FILL = _kind(PREFIX_ORDER_FILL)
ORDER_CANCELLED = _kind(PREFIX_ORDER_CANCELLED)
ORDER_EXPIRED = _kind(PREFIX_ORDER_EXPIRED)
ORDER_AMENDED = _kind(PREFIX_ORDER_AMENDED)

TRADE_EXECUTED = TOPIC_TRADE_EXECUTED

QUOTE_NEW = TOPIC_QUOTE_NEW
QUOTE_ACK = _kind(PREFIX_QUOTE_ACK)

OCO_ACK = _kind(PREFIX_OCO_ACK)
OCO_CANCELLED = _kind(PREFIX_OCO_CANCELLED)

SESSION_STATE = TOPIC_SESSION_STATE
SESSION_TRANSITION = TOPIC_SESSION_TRANSITION

CIRCUIT_BREAKER_HALT = _kind(PREFIX_CIRCUIT_BREAKER_HALT)
CIRCUIT_BREAKER_EXTEND = _kind(PREFIX_CIRCUIT_BREAKER_EXTEND)
CIRCUIT_BREAKER_RESUME = _kind(PREFIX_CIRCUIT_BREAKER_RESUME)

GATEWAY_AUTH = _kind(PREFIX_GATEWAY_AUTH)
GATEWAY_BYE = _kind(PREFIX_GATEWAY_BYE)
GATEWAY_CONNECT = TOPIC_GATEWAY_CONNECT
GATEWAY_DISCONNECT = TOPIC_GATEWAY_DISCONNECT
STARTUP_RECOVERY = TOPIC_STARTUP_RECOVERY
RECOVERY_ITEM = TOPIC_RECOVERY_ITEM
