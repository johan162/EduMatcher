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

from edumatcher.models.generated.admin import PREFIX_ADMIN_ACTION
from edumatcher.models.generated.auction import (
    PREFIX_AUCTION_INDICATIVE,
    PREFIX_AUCTION_RESULT,
)
from edumatcher.models.generated.circuit_breaker import (
    PREFIX_CIRCUIT_BREAKER_EXTEND,
    PREFIX_CIRCUIT_BREAKER_HALT,
    PREFIX_CIRCUIT_BREAKER_RESUME,
)
from edumatcher.models.generated.index import (
    PREFIX_INDEX_CONSTITUENT_CHANGE_ACK,
    PREFIX_INDEX_CORP_ACTION_ACK,
    PREFIX_INDEX_REBALANCE_ACK,
    TOPIC_INDEX_CONSTITUENT_CHANGE,
    TOPIC_INDEX_CORP_ACTION,
    TOPIC_INDEX_REBALANCE,
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
    TOPIC_ORDER_COMBO_CANCEL,
    TOPIC_ORDER_NEW,
    TOPIC_ORDER_OCO,
    TOPIC_ORDER_OCO_CANCEL,
)
from edumatcher.models.generated.quote import (
    PREFIX_QUOTE_ACK,
    PREFIX_QUOTE_STATUS,
    TOPIC_QUOTE_CANCEL,
    TOPIC_QUOTE_NEW,
)
from edumatcher.models.generated.session import (
    PREFIX_SESSION_TRANSITION_ACK,
    TOPIC_SESSION_STATE,
    TOPIC_SESSION_TRANSITION,
)
from edumatcher.models.generated.structure import (
    PREFIX_COMBO_ACK,
    PREFIX_COMBO_STATUS,
    PREFIX_OCO_ACK,
    PREFIX_OCO_CANCELLED,
)
from edumatcher.models.generated.system import (
    PREFIX_GATEWAY_AUTH,
    PREFIX_GATEWAY_BYE,
    TOPIC_EOD,
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
ORDER_OCO_CANCEL = TOPIC_ORDER_OCO_CANCEL
ORDER_COMBO = TOPIC_ORDER_COMBO
ORDER_COMBO_CANCEL = TOPIC_ORDER_COMBO_CANCEL
ORDER_ACK = _kind(PREFIX_ORDER_ACK)
ORDER_FILL = _kind(PREFIX_ORDER_FILL)
ORDER_CANCELLED = _kind(PREFIX_ORDER_CANCELLED)
ORDER_EXPIRED = _kind(PREFIX_ORDER_EXPIRED)
ORDER_AMENDED = _kind(PREFIX_ORDER_AMENDED)

TRADE_EXECUTED = TOPIC_TRADE_EXECUTED

QUOTE_NEW = TOPIC_QUOTE_NEW
QUOTE_CANCEL = TOPIC_QUOTE_CANCEL
QUOTE_ACK = _kind(PREFIX_QUOTE_ACK)
QUOTE_STATUS = _kind(PREFIX_QUOTE_STATUS)

OCO_ACK = _kind(PREFIX_OCO_ACK)
OCO_CANCELLED = _kind(PREFIX_OCO_CANCELLED)
COMBO_ACK = _kind(PREFIX_COMBO_ACK)
COMBO_STATUS = _kind(PREFIX_COMBO_STATUS)

SESSION_STATE = TOPIC_SESSION_STATE
SESSION_TRANSITION = TOPIC_SESSION_TRANSITION
SESSION_TRANSITION_ACK = _kind(PREFIX_SESSION_TRANSITION_ACK)
SYSTEM_EOD = TOPIC_EOD

ADMIN_ACTION = _kind(PREFIX_ADMIN_ACTION)

AUCTION_INDICATIVE = _kind(PREFIX_AUCTION_INDICATIVE)
AUCTION_RESULT = _kind(PREFIX_AUCTION_RESULT)

INDEX_CORP_ACTION = TOPIC_INDEX_CORP_ACTION
INDEX_CONSTITUENT_CHANGE = TOPIC_INDEX_CONSTITUENT_CHANGE
INDEX_REBALANCE = TOPIC_INDEX_REBALANCE
INDEX_CORP_ACTION_ACK = _kind(PREFIX_INDEX_CORP_ACTION_ACK)
INDEX_CONSTITUENT_CHANGE_ACK = _kind(PREFIX_INDEX_CONSTITUENT_CHANGE_ACK)
INDEX_REBALANCE_ACK = _kind(PREFIX_INDEX_REBALANCE_ACK)

CIRCUIT_BREAKER_HALT = _kind(PREFIX_CIRCUIT_BREAKER_HALT)
CIRCUIT_BREAKER_EXTEND = _kind(PREFIX_CIRCUIT_BREAKER_EXTEND)
CIRCUIT_BREAKER_RESUME = _kind(PREFIX_CIRCUIT_BREAKER_RESUME)

GATEWAY_AUTH = _kind(PREFIX_GATEWAY_AUTH)
GATEWAY_BYE = _kind(PREFIX_GATEWAY_BYE)
GATEWAY_CONNECT = TOPIC_GATEWAY_CONNECT
GATEWAY_DISCONNECT = TOPIC_GATEWAY_DISCONNECT
STARTUP_RECOVERY = TOPIC_STARTUP_RECOVERY
RECOVERY_ITEM = TOPIC_RECOVERY_ITEM

#: Spec families, as ``spec/messages/<family>.yaml`` names them and the
#: generated registry reports them on every topic. Used where a rule applies to
#: a whole family rather than to named messages -- every ``risk.*`` command is
#: a command episode, and a new one added to the spec is covered without an
#: edit here. Families are not topics, so the literal gate in
#: ``tests/test_msgen_literals.py`` does not reach them; a family rename shows
#: up as facts landing in ``orphan`` and is caught by the fixture tests.
FAMILY_RISK = "risk"
FAMILY_ADMIN = "admin"
FAMILY_INDEX = "index"
FAMILY_SESSION = "session"
FAMILY_CIRCUIT_BREAKER = "circuit_breaker"
FAMILY_AUCTION = "auction"
