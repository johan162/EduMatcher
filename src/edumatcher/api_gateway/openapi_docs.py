"""OpenAPI documentation for the REST API: examples, shared errors, tag text.

The route handlers return plain dicts (the engine's own replies, forwarded), so
FastAPI cannot derive a response example from a type -- left alone, Swagger
shows ``{"additionalProp1": {}}``. Every example here is a realistic payload
in the shape the engine, pm-stats or pm-index actually sends, built from the
message specs under ``spec/messages``; ``tests/test_api_gateway_openapi.py``
checks the engine-reply ones against the generated message classes so they
cannot drift from the wire format.

All examples describe one small, consistent market: symbols AAPL, MSFT and
TSLA, trading gateway TRADER01, market maker MM01, admin OPS01.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.openapi.models import Example
from fastapi.routing import APIRoute, iter_route_contexts
from starlette.routing import BaseRoute

from edumatcher.api_gateway.errors import ERROR_CODES
from edumatcher.api_gateway.schemas import ErrorResponse
from edumatcher.models.generated import index as index_msgs
from edumatcher.models.generated import news as news_msgs
from edumatcher.models.generated import order as order_msgs
from edumatcher.models.generated import risk as risk_msgs
from edumatcher.models.generated import system as system_msgs
from edumatcher.models.generated.order import topic_order_ack, topic_order_fill

API_DESCRIPTION = """\
REST/JSON and WebSocket gateway for EduMatcher order entry and market data.

## Authentication

Every request carries an API key as a bearer token:

    Authorization: Bearer <api_key>

Keys are configured per gateway process under `api_gateways.<name>.credentials`
in the engine config. A key maps to one of two things:

* a **trading gateway** (`gateway_id` set) -- may submit, amend and cancel
  orders and read its own orders, fills and positions. What it may do beyond
  that depends on the engine **role** of that gateway: `TRADER`,
  `MARKET_MAKER` (adds quoting) or `ADMIN` (adds the `/admin` endpoints and
  the venue-wide `/clearing` views; other roles read their own gateway's);
* a **read-only key** (`gateway_id` null) -- may read public data only:
  `/reference/*`, `/book`, `/news`, `/companies/{symbol}`, `/history/trades`,
  `/history/daily` and the other public history endpoints, `/bootstrap/trader`.
  Everything gateway-scoped answers `403 READ_ONLY`.

## Asynchronous order entry

`POST`, `PATCH` and `DELETE` on orders are **asynchronous**: the gateway hands
the request to the matching engine and, by default, answers `202` with
`status: PENDING` straight away. The engine's verdict (accepted, rejected,
filled) arrives on the private WebSocket stream. Add `?wait=ack` to hold the
response until the engine acknowledges, up to the gateway's `wait_ack_sec`
timeout; the verdict is then in `accepted`, `reject_code` and `event`.

## Errors

Every error uses one envelope, whatever the cause:

    {"error": {"code": "VALIDATION", "message": "...", "field": "price",
               "reject_code": "TICK_VIOLATION"}}

That includes an unknown path (`404 NOT_FOUND`), a wrong method
(`405 METHOD_NOT_ALLOWED`) and a gateway bug (`500 INTERNAL_ERROR`). `code` is
the HTTP-level category; `reject_code` is the same vocabulary the engine uses
on `order.ack` rejects, so REST and ALF clients see identical values for the
same mistake. `client_tag` / `request_tag` are echoed back when the request
carried one. Validation failures are always `400`.

## Status codes

`200` means the response carries the outcome; `202` means the request was
handed on and the outcome follows on a WebSocket. An order submit, cancel or
amend is `202` by default and `200` with `?wait=ack`. An admin command the
engine refuses is `409` with a command-specific code.

## Rate limiting

Write endpoints (POST/PATCH/DELETE) are limited per API key by a token bucket
(`rate_limit.writes_per_second`, `rate_limit.burst`). Over the limit the answer
is `429 RATE_LIMITED`. Reads are not limited.

## Prices and time

Prices are decimal display prices (`187.25`), always on the symbol's tick grid
(`tick_decimals` in `/reference/symbols`); an off-grid price is `400 TICK_VIOLATION`.
Timestamps named `ts_ns` / `*_ns` are epoch nanoseconds; `ts` in history rows is
ISO-8601 UTC. `date` filters are trading days in the exchange's own timezone
(`session_timezone` in `GET /session`).

## WebSocket

Live streams are WebSockets under `/api/v1/ws/` and are not part of this
OpenAPI document: `/api/v1/ws/private` (orders, fills, quotes),
`/api/v1/ws/market-data` (book, trades, depth, auction, session, halts, news),
and, for ADMIN keys, `/api/v1/ws/admin/monitor` and `/api/v1/ws/admin/sim`.
"""

TAGS_METADATA: list[dict[str, str]] = [
    {
        "name": "orders",
        "description": (
            "Order entry and management for the caller's own gateway: submit, "
            "amend, cancel, replace, OCO, combos, market-maker quotes and "
            "mass cancel. Requires a trading key. Writes are asynchronous -- "
            "see *Asynchronous order entry* above."
        ),
    },
    {
        "name": "reference",
        "description": (
            "Static venue configuration (symbols, tick sizes, collars, "
            "circuit-breaker ladders, indexes, trading schedule) and live "
            "session/halt state, plus news and company profiles. Reference "
            "endpoints are open to read-only keys; every response that "
            "derives from the reference bundle carries `config_version`, a "
            "hash that changes whenever the configuration does."
        ),
    },
    {
        "name": "market-data",
        "description": (
            "The order book as of now, over plain REST: one symbol's levels "
            "and last trades, or best bid/ask for every symbol. Open to "
            "read-only keys. Each reply carries the `seq` of the WebSocket "
            "`book` frame it corresponds to, so a client can read here, then "
            "subscribe, and drop frames it already has."
        ),
    },
    {
        "name": "history",
        "description": (
            "Read-only history from the pm-stats database: the caller's own "
            "order events and fills, public trades, daily OHLC, intraday "
            "snapshots and index series. List endpoints are keyset-paginated: "
            "pass the response's `next_cursor` back as `after` to get the next "
            "page; `has_more` says whether another page may exist. "
            "`retained_from` on order-event endpoints is the point pm-stats "
            "prunes at (null when nothing is pruned)."
        ),
    },
    {
        "name": "clearing",
        "description": (
            "Read-only post-trade data from the pm-clearing ledger and pm-eod's "
            "settlement ledger. A TRADER or MARKET_MAKER key reads its own "
            "gateway (naming another is `403 SCOPE_DENIED`); an ADMIN key reads "
            "the venue; a read-only key reads nothing. Money on a row comes as "
            "`<name>_ticks` (as stored, ticks of `tick_decimals`) and `<name>` "
            "(display currency); only display values are summed across symbols. "
            "Settlement amounts are integer minor units (`*_minor`, 2 decimals). "
            "Data lags fills by up to one clearing flush (5 s by default); raw "
            "trades are pruned after the retention window (90 days by default) "
            "while daily rows and close snapshots stay."
        ),
    },
    {
        "name": "bootstrap",
        "description": (
            "One-request startup payloads (reference data, session, "
            "positions, open orders, today's fills, halts, capability flags) "
            "so a client can render after a single call. Optional sections "
            "that time out come back `null` and are named in `incomplete`; "
            "required sections turn the whole call into `503 ENGINE_TIMEOUT`."
        ),
    },
    {
        "name": "admin",
        "description": (
            "Operator endpoints. Require a key whose gateway has the engine "
            "role `ADMIN`; any other trading key gets `403 ROLE_DENIED`. "
            "Covers session control, reference reload, circuit-breaker "
            "halt/resume, kill switches, index rebalancing, and cross-gateway "
            "views of orders, positions and gateways."
        ),
    },
]

# ---------------------------------------------------------------------------
# Shared identifiers
# ---------------------------------------------------------------------------

_ORDER_1 = "9f2c4e7a1b3d4c58a6e0f1d2c3b4a596"
#: For error examples elsewhere that name an order.
ORDER_ID_EXAMPLE = _ORDER_1
_ORDER_2 = "3b7e1d9a5c2f4e86b0a1d3c5e7f90214"
_ORDER_3 = "c81a64f0d2e94b37a5f6091e8d3b72c4"
_TRADE_1 = "T-20260829-000412"
_CMD = "cmd-5d0e8a3f7c1b4926a8e4f0b3c6d92e17"
_CONFIG_VERSION = "3f9a1c7e5b2d8046"
_T0 = 1788013800000000000  # 2026-08-29T13:30:00Z


def _json(example: Any, description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"example": example}},
    }


def _json_named(
    examples: dict[str, tuple[str, Any]], description: str
) -> dict[str, Any]:
    """A response with several named examples (Swagger shows a dropdown)."""
    return {
        "description": description,
        "content": {
            "application/json": {
                "examples": {
                    name: {"summary": summary, "value": value}
                    for name, (summary, value) in examples.items()
                }
            }
        },
    }


def ok(
    example: Any, description: str = "Success", status_code: int = 200
) -> dict[int | str, dict[str, Any]]:
    """``responses=`` entry for the success status, carrying a real example."""
    return {status_code: _json(example, description)}


def ok_named(
    examples: dict[str, tuple[str, Any]],
    description: str = "Success",
    status_code: int = 200,
) -> dict[int | str, dict[str, Any]]:
    return {status_code: _json_named(examples, description)}


#: The codes a route's key check can produce. Any key: unknown (`AUTH`); a
#: trading key the engine refuses (`ENGINE_AUTH`) or cannot be reached to
#: confirm (`ENGINE_UNAVAILABLE`).
ANY_KEY = ("AUTH", "ENGINE_AUTH", "ENGINE_UNAVAILABLE")
#: A gateway-scoped endpoint additionally refuses a read-only key.
TRADING_KEY = (*ANY_KEY, "READ_ONLY")


def errors(
    *codes: str, examples: dict[str, dict[str, Any]] | None = None
) -> dict[int | str, dict[str, Any]]:
    """``responses=`` entries for exactly the error *codes* a route can return.

    One response per HTTP status, listing its codes and carrying one named
    example per code (Swagger shows a dropdown). *examples* overrides a
    code's example fields (``message``, ``field``, ``reject_code``, ...);
    otherwise the registry's example message and default ``reject_code`` are
    used. Each route's set is held to what its code can raise by
    ``tests/test_api_gateway_error_codes.py``.
    """
    by_status: dict[int, list[str]] = {}
    for code in sorted(set(codes)):
        by_status.setdefault(ERROR_CODES[code].status, []).append(code)
    out: dict[int | str, dict[str, Any]] = {}
    for status_code, group in sorted(by_status.items()):
        named = {}
        for code in group:
            entry = ERROR_CODES[code]
            fields: dict[str, Any] = {
                "message": entry.example,
                "reject_code": entry.reject_code,
                **(examples or {}).get(code, {}),
            }
            named[code] = {
                "summary": code,
                "value": {"error": {"code": code, **fields}},
            }
        out[status_code] = {
            "model": ErrorResponse,
            "description": " ".join(
                f"`{code}`: {ERROR_CODES[code].meaning}" for code in group
            ),
            "content": {"application/json": {"examples": named}},
        }
    return out


#: ``examples=`` for the order-entry writes' ``VALIDATION``.
ORDER_VALIDATION = {
    "message": "LIMIT requires price",
    "field": "__root__",
    "reject_code": "MISSING_FIELD",
    "client_tag": "strategy-7",
}
#: ``examples=`` for the history filters' ``VALIDATION``.
FILTER_VALIDATION = {
    "message": "Invalid date format: yesterday (expected YYYY-MM-DD)",
    "field": "date",
}


def ok_or_acked(
    examples: dict[str, tuple[str, Any]],
    pending_description: str,
    acked_description: str,
) -> dict[int | str, dict[str, Any]]:
    """``202`` with the ``pending`` example, ``200`` with the others.

    For the writes that answer ``202`` by default and ``200`` once
    ``?wait=ack`` has the engine's outcome in the body.
    """
    pending = {name: ex for name, ex in examples.items() if name == "pending"}
    answered = {name: ex for name, ex in examples.items() if name != "pending"}
    return {
        202: _json_named(pending, pending_description),
        200: _json_named(answered, acked_description),
    }


def merge(*parts: dict[int | str, dict[str, Any]]) -> dict[int | str, dict[str, Any]]:
    out: dict[int | str, dict[str, Any]] = {}
    for part in parts:
        out.update(part)
    return out


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

ORDER_ACK_EVENT: dict[str, Any] = {
    "gateway_id": "TRADER01",
    "order_id": _ORDER_1,
    "accepted": True,
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "DAY",
    "qty": 100,
    "price": 187.25,
    "client_tag": "strategy-7",
}

ORDER_REJECT_EVENT: dict[str, Any] = {
    "gateway_id": "TRADER01",
    "order_id": _ORDER_1,
    "accepted": False,
    "reason": "Price 187.255 is not a multiple of tick 0.01",
    "reject_code": "TICK_VIOLATION",
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "DAY",
    "qty": 100,
    "client_tag": "strategy-7",
}

ORDER_SUBMITTED = {
    "pending": (
        "Default: returned immediately, engine verdict follows on the WebSocket",
        {
            "order_id": _ORDER_1,
            "client_tag": "strategy-7",
            "status": "PENDING",
            "accepted": None,
            "reject_code": None,
            "event": None,
            "ack_timeout": False,
        },
    ),
    "acked": (
        "With ?wait=ack: accepted by the engine",
        {
            "order_id": _ORDER_1,
            "client_tag": "strategy-7",
            "status": "ACKED",
            "accepted": True,
            "reject_code": None,
            "event": ORDER_ACK_EVENT,
            "ack_timeout": False,
        },
    ),
    "rejected": (
        "With ?wait=ack: rejected by the engine",
        {
            "order_id": _ORDER_1,
            "client_tag": "strategy-7",
            "status": "ACKED",
            "accepted": False,
            "reject_code": "TICK_VIOLATION",
            "event": ORDER_REJECT_EVENT,
            "ack_timeout": False,
        },
    ),
    "timeout": (
        "With ?wait=ack: sent, but the verdict did not arrive in time",
        {
            "order_id": _ORDER_1,
            "client_tag": "strategy-7",
            "status": "PENDING",
            "accepted": None,
            "reject_code": None,
            "event": None,
            "ack_timeout": True,
        },
    ),
}

ORDER_CANCELLED_EVENT: dict[str, Any] = {
    "gateway_id": "TRADER01",
    "order_id": _ORDER_1,
    "symbol": "AAPL",
    "client_tag": "strategy-7",
    "request_tag": "cxl-1",
    "remaining_qty": 100,
    "cum_qty": 0,
}

ORDER_CANCEL_RESULT = {
    "pending": (
        "Default: cancel sent, outcome follows on the WebSocket",
        {
            "order_id": _ORDER_1,
            "request_tag": "cxl-1",
            "status": "PENDING_CANCEL",
            "accepted": None,
            "reject_code": None,
            "event": None,
            "ack_timeout": False,
        },
    ),
    "acked": (
        "With ?wait=ack: the order was cancelled",
        {
            "order_id": _ORDER_1,
            "request_tag": "cxl-1",
            "status": "ACKED",
            "accepted": True,
            "reject_code": None,
            "event": ORDER_CANCELLED_EVENT,
            "ack_timeout": False,
        },
    ),
    "rejected": (
        "With ?wait=ack: the cancel was refused (e.g. already filled)",
        {
            "order_id": _ORDER_1,
            "request_tag": "cxl-1",
            "status": "REJECTED",
            "accepted": False,
            "reject_code": "ORDER_ALREADY_TERMINAL",
            "event": {
                "gateway_id": "TRADER01",
                "order_id": _ORDER_1,
                "accepted": False,
                "reason": "Order already filled",
                "reject_code": "ORDER_ALREADY_TERMINAL",
                "request_tag": "cxl-1",
            },
            "ack_timeout": False,
        },
    ),
}

ORDER_AMEND_RESULT = {
    "pending": (
        "Default: amend sent, outcome follows on the WebSocket",
        {
            "order_id": _ORDER_1,
            "request_tag": "amend-1",
            "status": "PENDING_AMEND",
            "accepted": None,
            "reject_code": None,
            "event": None,
            "ack_timeout": False,
        },
    ),
    "acked": (
        "With ?wait=ack: the order was amended",
        {
            "order_id": _ORDER_1,
            "request_tag": "amend-1",
            "status": "ACKED",
            "accepted": True,
            "reject_code": None,
            "event": {
                "gateway_id": "TRADER01",
                "order_id": _ORDER_1,
                "symbol": "AAPL",
                "qty": 100,
                "remaining_qty": 100,
                "price": 187.5,
                "old_price": 187.25,
                "old_qty": 100,
                "priority_reset": True,
                "client_tag": "strategy-7",
                "request_tag": "amend-1",
            },
            "ack_timeout": False,
        },
    ),
}

ORDER_REPLACED = {
    "pending": (
        "Default: original cancelled, replacement sent",
        {
            "cancelled_order_id": _ORDER_1,
            "replacement_order_id": _ORDER_2,
            "status": "PENDING",
            "accepted": None,
            "reject_code": None,
            "event": None,
            "ack_timeout": False,
        },
    ),
    "acked": (
        "With ?wait=ack: the replacement was accepted",
        {
            "cancelled_order_id": _ORDER_1,
            "replacement_order_id": _ORDER_2,
            "status": "ACKED",
            "accepted": True,
            "reject_code": None,
            "event": {**ORDER_ACK_EVENT, "order_id": _ORDER_2},
            "ack_timeout": False,
        },
    ),
}

_ORDER_DISPLAY_LIMIT: dict[str, Any] = {
    "id": _ORDER_1,
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "DAY",
    "quantity": 100,
    "remaining_qty": 60,
    "ts_ns": _T0,
    "status": "PARTIAL",
    "price": 187.25,
    "origin": "ORDER",
    "is_seed": False,
    "client_tag": "strategy-7",
    "arrival_seq": 18422,
}

_ORDER_DISPLAY_ICEBERG: dict[str, Any] = {
    "id": _ORDER_3,
    "symbol": "MSFT",
    "side": "SELL",
    "order_type": "ICEBERG",
    "tif": "GTC",
    "quantity": 5000,
    "remaining_qty": 5000,
    "ts_ns": _T0 + 41_000_000_000,
    "status": "NEW",
    "price": 412.8,
    "visible_qty": 500,
    "displayed_qty": 500,
    "origin": "ORDER",
    "is_seed": False,
    "client_tag": None,
    "arrival_seq": 18457,
}

ORDERS_LIST: dict[str, Any] = {
    "gateway_id": "TRADER01",
    "orders": [_ORDER_DISPLAY_LIMIT, _ORDER_DISPLAY_ICEBERG],
}

#: The cached view served by ``GET /orders/{id}``: the order as submitted,
#: overlaid by every engine event since (ack, fills, amend, cancel).
ORDER_CACHED: dict[str, Any] = {
    "order_id": _ORDER_1,
    "gateway_id": "TRADER01",
    "client_tag": "strategy-7",
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "DAY",
    "quantity": 100,
    "qty": 100,
    "price": 187.25,
    "accepted": True,
    "status": "PARTIAL",
    "fill_qty": 40,
    "fill_price": 187.25,
    "remaining_qty": 60,
    "cum_qty": 40,
    "liquidity_flag": "MAKER",
    "trade_ids": [_TRADE_1],
}

OCO_ACK_EVENT: dict[str, Any] = {
    "oco_id": "oco-2026-0042",
    "accepted": True,
    "reason": "",
    "order_id_1": "ORD-OCO-1",
    "order_id_2": "ORD-OCO-2",
}
COMBO_ACK_EVENT: dict[str, Any] = {
    "combo_id": "combo-spread-17",
    "accepted": True,
    "reason": "",
}
QUOTE_ACK_EVENT: dict[str, Any] = {
    "quote_id": "q-AAPL-0001",
    "accepted": True,
    "symbol": "AAPL",
    "reason": "",
    "bid_order_id": "ORD-QB-1",
    "ask_order_id": "ORD-QA-1",
}


def _structure_sent(ids: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """The pending and acked examples of an OCO, combo or quote submit."""
    unanswered = {"accepted": None, "reason": None, "event": None}
    return {
        "pending": (
            "Default: sent, the verdict follows on the WebSocket",
            {**ids, "status": "PENDING", **unanswered, "ack_timeout": False},
        ),
        "acked": (
            "With ?wait=ack: the engine's verdict",
            {
                **ids,
                "status": "ACKED",
                "accepted": True,
                "reason": None,
                "event": event,
                "ack_timeout": False,
            },
        ),
    }


OCO_SENT = _structure_sent({"oco_id": "oco-2026-0042"}, OCO_ACK_EVENT)


def _structure_cancel(ids: dict[str, Any], topic_kind: str) -> dict[str, Any]:
    """Pending / acked / rejected examples of an OCO, combo or quote cancel."""
    blank = {"accepted": None, "reject_code": None, "event": None}
    acked_event = {
        **ids,
        "accepted": True,
        "reason": "",
        "request_tag": "cxl-1",
        "cancelled_order_ids": [_ORDER_1, _ORDER_2],
    }
    refused_event = {
        **ids,
        "accepted": False,
        "reason": f"{topic_kind} not found",
        "reject_code": "ORDER_NOT_FOUND",
        "request_tag": "cxl-1",
        "cancelled_order_ids": [],
    }
    return {
        "pending": (
            "Default: cancel sent, outcome follows on the WebSocket",
            {**ids, "request_tag": "cxl-1", "status": "PENDING_CANCEL", **blank,
             "ack_timeout": False},
        ),
        "acked": (
            "With ?wait=ack: cancelled",
            {**ids, "request_tag": "cxl-1", "status": "ACKED", "accepted": True,
             "reject_code": None, "event": acked_event, "ack_timeout": False},
        ),
        "rejected": (
            "With ?wait=ack: the cancel was refused",
            {**ids, "request_tag": "cxl-1", "status": "REJECTED", "accepted": False,
             "reject_code": "ORDER_NOT_FOUND", "event": refused_event,
             "ack_timeout": False},
        ),
    }  # fmt: skip


OCO_CANCEL = _structure_cancel({"oco_id": "oco-2026-0042"}, "OCO")
COMBO_SENT = _structure_sent({"combo_id": "combo-spread-17"}, COMBO_ACK_EVENT)
COMBO_CANCEL = _structure_cancel({"combo_id": "combo-spread-17"}, "Combo")
QUOTE_SENT = _structure_sent(
    {"symbol": "AAPL", "quote_id": "q-AAPL-0001"}, QUOTE_ACK_EVENT
)
QUOTE_CANCEL = _structure_cancel({"symbol": "AAPL"}, "Quote")

MASS_CANCEL: dict[str, Any] = {
    "gateway_id": "TRADER01",
    "accepted": True,
    "cancelled_orders": 2,
    "cancelled_order_ids": [_ORDER_1, _ORDER_3],
    "cancelled_quotes": 0,
    "cancelled_quote_order_ids": [],
    "command_id": _CMD,
}

# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------

_COLLAR = {"static_band_pct": 10.0, "dynamic_band_pct": 5.0}
_DAY = {
    "pre_open": "08:30",
    "opening_auction_start": "08:55",
    "continuous_start": "09:00",
    "closing_auction_start": "17:25",
    "closing_auction_end": "17:30",
}
_SHORT_DAY = {
    "pre_open": "08:30",
    "opening_auction_start": "08:55",
    "continuous_start": "09:00",
    "closing_auction_start": "13:00",
    "closing_auction_end": "13:05",
}
_WEEKLY_SCHEDULE: dict[str, Any] = {
    "today_is_holiday": False,
    "upcoming_holidays": [
        {"date": "2026-12-24", "name": "Julafton"},
        {"date": "2026-12-25", "name": "Juldagen"},
    ],
    "mon": _DAY,
    "tue": _DAY,
    "wed": _DAY,
    "thu": _DAY,
    "fri": _DAY,
    "sat": None,
    "sun": None,
    "holidays": None,
    "today": _DAY,
}
_REFERENCE_SYMBOLS: list[dict[str, Any]] = [
    {
        "symbol": "AAPL",
        "tick_decimals": 2,
        "level": "standard",
        "collar": _COLLAR,
        "order_limits": {"max_order_qty": 100000, "max_order_value": 5000000.0},
        "circuit_breaker": {
            "reference_window_ns": 300000000000,
            "levels": [
                {
                    "name": "L1",
                    "price_shift_pct": 7.0,
                    "halt_duration_ns": 300000000000,
                },
                {"name": "L2", "price_shift_pct": 13.0, "halt_duration_ns": None},
            ],
        },
    },
    {"symbol": "MSFT", "tick_decimals": 2},
    {"symbol": "TSLA", "tick_decimals": 2, "level": "volatile"},
]
_REFERENCE_RISK: dict[str, Any] = {
    "levels": [
        {"name": "standard", "collar": _COLLAR},
        {
            "name": "volatile",
            "collar": {"static_band_pct": 20.0, "dynamic_band_pct": 10.0},
        },
    ],
    "default_level": "standard",
}
_INDEXES: list[dict[str, Any]] = [
    {
        "id": "EDU3",
        "base_value": 1000.0,
        "constituents": ["AAPL", "MSFT", "TSLA"],
        "description": "EduMatcher Large Cap 3",
    }
]
_REFERENCE_SCHEDULE: dict[str, Any] = {
    "sessions_enabled": True,
    "country": "SE",
    "schedule": _WEEKLY_SCHEDULE,
}

REFERENCE_BUNDLE: dict[str, Any] = {
    "gateway_id": "TRADER01",
    "symbols": _REFERENCE_SYMBOLS,
    "risk": _REFERENCE_RISK,
    "indexes": _INDEXES,
    "schedule": _REFERENCE_SCHEDULE,
    "config_version": _CONFIG_VERSION,
}
REFERENCE_CONFIG_VERSION = {"config_version": _CONFIG_VERSION}
REFERENCE_SYMBOLS = {
    "symbols": _REFERENCE_SYMBOLS,
    "config_version": _CONFIG_VERSION,
}
REFERENCE_RISK = {**_REFERENCE_RISK, "config_version": _CONFIG_VERSION}
REFERENCE_INDEXES = {"indexes": _INDEXES, "config_version": _CONFIG_VERSION}
REFERENCE_SCHEDULE = {**_REFERENCE_SCHEDULE, "config_version": _CONFIG_VERSION}

SYMBOLS: dict[str, Any] = {
    "gateway_id": "TRADER01",
    "symbols": [
        {"symbol": "AAPL", "tick_decimals": 2, "prev_close": 186.9},
        {"symbol": "MSFT", "tick_decimals": 2, "prev_close": 411.35},
        {
            "symbol": "TSLA",
            "tick_decimals": 2,
            "enforce_mm_obligation": True,
            "mm_max_spread_ticks": 20,
            "mm_min_qty": 100,
            "prev_close": 248.1,
        },
    ],
}

NEWS: dict[str, Any] = {
    "news": [
        {
            "id": "n-000127",
            "ts_ns": _T0 - 1_800_000_000_000,
            "scope": "SECTOR",
            "targets": ["TECH"],
            "kind": "REGULATORY",
            "status": "CONFIRMED",
            "headline": "Regulator opens review of cloud-contract practices",
            "sentiment": -0.35,
            "credibility": 0.9,
        },
        {
            "id": "n-000128",
            "ts_ns": _T0 - 600_000_000_000,
            "scope": "SYMBOL",
            "targets": ["AAPL"],
            "kind": "EARNINGS",
            "status": "RUMOUR",
            "headline": "Apple said to beat quarterly estimates",
            "sentiment": 0.6,
            "credibility": 0.55,
        },
    ],
    "sectors": {"TECH": ["AAPL", "MSFT"], "AUTO": ["TSLA"]},
}

COMPANY: dict[str, Any] = {
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "sector": "TECH",
    "industry": "Consumer electronics",
    "headquarters": "Cupertino, USA",
    "purpose": "Designs consumer devices, software and services",
    "key_market": "North America",
    "market_position": "Premium hardware with a closed software ecosystem",
    "origin": "CO_FOUNDERS",
    "founders": "Steve Jobs, Steve Wozniak, Ronald Wayne",
    "founder_story": "Started in a garage building personal computers.",
    "founded_year": 1976,
    "ipo_year": 1980,
    "ipo_valuation_musd": 1800.0,
    "ceo_name": "Tim Cook",
    "ceo_since": 2011,
    "ceo_industry_years": 40,
    "employees": 164000,
    "fiscal_year": 2025,
    "revenue_musd": 391000.0,
    "net_income_musd": 97000.0,
    "revenue_growth_pct": 2.0,
    "operating_margin_pct": 31.5,
    "free_cash_flow_musd": 108800.0,
    "market_cap_musd": 3000000.0,
    "dividend_yield_pct": 0.5,
    "debt_to_equity": 1.5,
    "credit_rating": "AA+",
    "competitors": "MSFT",
    "key_risk": "Dependence on iPhone sales",
    "years_in_business": 50,
    "ceo_tenure_years": 15,
    "pe_ratio": 30.9,
    "ps_ratio": 7.67,
    "net_margin_pct": 24.8,
}

SESSION_STATUS: dict[str, Any] = {
    "gateway_id": "TRADER01",
    "state": "CONTINUOUS",
    "sessions_enabled": True,
    "next": {"state": "CLOSING_AUCTION", "at": "2026-08-29T17:25:00+02:00"},
}


HALT_STATUS: dict[str, Any] = {
    "gateway_id": "TRADER01",
    "halted": [
        {
            "symbol": "TSLA",
            "resume_at_ns": _T0 + 300_000_000_000,
            "level": "L1",
            "halt_source": "CIRCUIT_BREAKER",
        },
        {"symbol": "MSFT"},
    ],
}

QUOTE_BOOTSTRAP: dict[str, Any] = {
    "gateway_id": "MM01",
    "quotes": [
        {
            "quote_id": "q-AAPL-0001",
            "gateway_id": "MM01",
            "symbol": "AAPL",
            "state": "ACTIVE",
            "bid_order_id": _ORDER_2,
            "ask_order_id": _ORDER_3,
            "bid_qty": 500,
            "ask_qty": 500,
            "bid_remaining_qty": 500,
            "ask_remaining_qty": 300,
            "bid_status": "NEW",
            "ask_status": "PARTIAL",
            "bid_price": 187.2,
            "ask_price": 187.3,
        }
    ],
}

QUOTE_LEGS: dict[str, Any] = {
    "gateway_id": "MM01",
    "legs": [
        {
            "quote_id": "q-AAPL-0001",
            "order_id": _ORDER_2,
            "symbol": "AAPL",
            "leg_side": "BUY",
            "qty": 500,
            "remaining": 500,
            "filled": 0,
            "status": "NEW",
            "quote_status": "ACTIVE",
            "price": 187.2,
        },
        {
            "quote_id": "q-AAPL-0001",
            "order_id": _ORDER_3,
            "symbol": "AAPL",
            "leg_side": "SELL",
            "qty": 500,
            "remaining": 300,
            "filled": 200,
            "status": "PARTIAL",
            "quote_status": "ACTIVE",
            "price": 187.3,
        },
    ],
    "show_requested": "ACTIVE",
    "complete": True,
    "recent": [],
}

POSITIONS: dict[str, Any] = {
    "positions": [
        {
            "symbol": "AAPL",
            "net_qty": 40,
            "avg_cost": 187.25,
            "last_price": 187.4,
            "market_value": 7496.0,
            "unrealized_pnl": 6.0,
            "realized_pnl_session": 125.5,
            "realized_pnl_mtd": 840.0,
            "realized_pnl_ytd": 5210.75,
        },
        {
            "symbol": "TSLA",
            "net_qty": -25,
            "avg_cost": 249.6,
            "last_price": None,
            "market_value": None,
            "unrealized_pnl": None,
            "realized_pnl_session": None,
            "realized_pnl_mtd": None,
            "realized_pnl_ytd": None,
        },
    ]
}

STATUS_TRADER: dict[str, Any] = {
    "orders": 12,
    "quote_legs": 0,
    "positions": {"AAPL": 40, "TSLA": -25},
    "known_symbols": ["AAPL", "MSFT", "TSLA"],
    "gateway_role": "TRADER",
}

# ---------------------------------------------------------------------------
# History (pm-stats)
# ---------------------------------------------------------------------------

_RETAINED_FROM = "2026-08-01T00:00:00+00:00"
_EVENT_ACK: dict[str, Any] = {
    "seq": 90211,
    "ts": "2026-08-29T13:30:00.118+00:00",
    "event_type": "ACK",
    "order_id": _ORDER_1,
    "gateway_id": "TRADER01",
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "DAY",
    "price": 187.25,
    "quantity": 100,
    "remaining_qty": 100,
    "status": "NEW",
    "fill_price": None,
    "fill_qty": None,
    "trade_ids": None,
    "reason": None,
    "reject_code": None,
    "client_tag": "strategy-7",
    "combo_parent_id": None,
    "oco_group_id": None,
    "priority_reset": None,
    "msg_id": "m-7f3a2c91",
}
_EVENT_FILL: dict[str, Any] = {
    **_EVENT_ACK,
    "seq": 90214,
    "ts": "2026-08-29T13:30:02.904+00:00",
    "event_type": "FILL",
    "remaining_qty": 60,
    "status": "PARTIAL",
    "fill_price": 187.25,
    "fill_qty": 40,
    "trade_ids": f'["{_TRADE_1}"]',
    "msg_id": "m-7f3a2d05",
}

HISTORY_ORDERS: dict[str, Any] = {
    "events": [_EVENT_ACK, _EVENT_FILL],
    "count": 2,
    "has_more": False,
    "retained_from": _RETAINED_FROM,
}
HISTORY_ORDERS_PAGED: dict[str, Any] = {
    **HISTORY_ORDERS,
    "has_more": True,
    "next_cursor": "eyJ0cyI6IjIwMjYtMDgtMjlUMTM6MzA6MDIuOTA0KzAwOjAwIiwic2VxIjo5MDIxNH0",
}
HISTORY_ORDER_LIFECYCLE: dict[str, Any] = {
    "events": [_EVENT_ACK, _EVENT_FILL],
    "count": 2,
    "retained_from": _RETAINED_FROM,
}
HISTORY_FILLS: dict[str, Any] = {
    "events": [_EVENT_FILL],
    "count": 1,
    "has_more": False,
    "retained_from": _RETAINED_FROM,
}
HISTORY_TRADES: dict[str, Any] = {
    "trades": [
        {
            "_rowid": 40118,
            "ts": "2026-08-29T13:30:02.904+00:00",
            "trade_id": _TRADE_1,
            "symbol": "AAPL",
            "price": 187.25,
            "quantity": 40,
            "tick_decimals": 2,
            "buy_gateway_id": "TRADER01",
            "sell_gateway_id": "MM01",
            "aggressor_side": "SELL",
        }
    ],
    "count": 1,
    "has_more": False,
}
HISTORY_DAILY: dict[str, Any] = {
    "daily": [
        {
            "date": "2026-08-29",
            "symbol": "AAPL",
            "open_price": 187.0,
            "high_price": 188.4,
            "low_price": 186.55,
            "close_price": 187.9,
            "open_bid": 186.95,
            "open_ask": 187.05,
            "close_bid": 187.85,
            "close_ask": 187.95,
            "volume": 1284300,
            "trade_count": 9417,
            "turnover": 240915000.0,
            "vwap": 187.58,
            "largest_trade_qty": 25000,
            "largest_trade_price": 187.3,
            "tick_decimals": 2,
        }
    ],
    "count": 1,
    "has_more": False,
}
HISTORY_PRICE_SNAPSHOTS: dict[str, Any] = {
    "snapshots": [
        {
            "_rowid": 220871,
            "ts": "2026-08-29T13:30:00+00:00",
            "symbol": "AAPL",
            "mid_price": 187.25,
            "best_bid": 187.2,
            "best_ask": 187.3,
            "pct_change": 0.19,
            "tick_decimals": 2,
        }
    ],
    "count": 1,
    "has_more": False,
}
HISTORY_INDEX_DAILY: dict[str, Any] = {
    "daily": [
        {
            "date": "2026-08-29",
            "index_id": "EDU3",
            "open_level": 1012.4,
            "high_level": 1018.9,
            "low_level": 1009.7,
            "close_level": 1016.2,
            "close_session_state": "CLOSED",
            "open_aggregate_cap": 5.62e12,
            "close_aggregate_cap": 5.66e12,
            "update_count": 4821,
        }
    ],
    "count": 1,
    "has_more": False,
}
HISTORY_INDEX_SNAPSHOTS: dict[str, Any] = {
    "snapshots": [
        {
            "_rowid": 91244,
            "ts": "2026-08-29T13:30:00+00:00",
            "index_id": "EDU3",
            "level": 1014.3,
            "aggregate_cap": 5.64e12,
            "divisor": 5.5598e9,
            "session_state": "CONTINUOUS",
            "day_open": 1012.4,
            "day_high": 1015.1,
            "day_low": 1011.9,
        }
    ],
    "count": 1,
    "has_more": False,
}
HISTORY_INDEXES = {"index_ids": ["EDU3"], "count": 1}
HISTORY_INDEX_EVENTS: dict[str, Any] = {
    "events": [
        {
            "type": "INIT",
            "ts_ns": _T0 - 86_400_000_000_000,
            "index_id": "EDU3",
            "level": 1000.0,
            "base_value": 1000.0,
            "divisor": 5.5598e9,
            "constituents": ["AAPL", "MSFT", "TSLA"],
        },
        {
            "type": "CORP_ACTION",
            "ts_ns": _T0 - 3_600_000_000_000,
            "index_id": "EDU3",
            "level": 1013.2,
            "symbol": "TSLA",
            "action": "SPLIT",
            "detail": "2-for-1",
            "old_divisor": 5.5598e9,
            "new_divisor": 5.5598e9,
        },
    ],
    "count": 2,
    "warnings": [],
}

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_CAPABILITIES = {
    "sessions_enabled": True,
    "stats_db_available": True,
    "audit_db_available": True,
    "index_available": True,
}
_FILLS_TODAY = {"events": [_EVENT_FILL], "count": 1}


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

ADMIN_TRANSITION = {
    "requested_state": "CLOSING_AUCTION",
    "status": "APPLIED",
    "command_id": _CMD,
}
ADMIN_RELOAD = {"status": "RELOADED", "config_version": _CONFIG_VERSION}
ADMIN_SIM: dict[str, Any] = {
    "available": True,
    "state": {
        "state": "RUNNING",
        "session": "CONTINUOUS",
        "seq": 18204,
        "ts_ns": _T0,
        "step_ns": 1_000_000_000,
        "symbols": 3,
        "seed": 55620099,
    },
    "values": {
        "seq": 18204,
        "ts_ns": _T0,
        "values": [
            {"symbol": "AAPL", "value": 187.31},
            {"symbol": "MSFT", "value": 412.02},
            {"symbol": "TSLA", "value": 247.77},
        ],
    },
}
ADMIN_GATEWAYS: dict[str, Any] = {
    "gateway_id": "OPS01",
    "gateways": [
        {
            "id": "TRADER01",
            "role": "TRADER",
            "connected": True,
            "description": "Student desk 1",
        },
        {
            "id": "MM01",
            "role": "MARKET_MAKER",
            "connected": True,
            "description": "Market maker",
        },
        {
            "id": "OPS01",
            "role": "ADMIN",
            "connected": True,
            "description": "Instructor console",
        },
    ],
}
ADMIN_DISCONNECT = {"gateway_id": "TRADER01", "status": "PENDING_DISCONNECT"}
ADMIN_HALT_ACK: dict[str, Any] = {
    "gateway_id": "OPS01",
    "accepted": True,
    "symbol": "TSLA",
    "cancelled_quotes": 1,
    "cancelled_quote_order_ids": [_ORDER_2],
    "command_id": _CMD,
}
ADMIN_RESUME_ACK: dict[str, Any] = {
    "gateway_id": "OPS01",
    "accepted": True,
    "symbol": "TSLA",
    "command_id": _CMD,
}
ADMIN_RISK_STATE: dict[str, Any] = {
    "gateway_id": "OPS01",
    "symbols": [
        {
            "symbol": "AAPL",
            "collar_reference_price": 187.3,
            "circuit_breaker": {
                "halted": False,
                "reference_price": 186.9,
                "trigger_price": 200.0,
                "expansion_index": 0,
            },
        },
        {
            "symbol": "TSLA",
            "collar_reference_price": 247.8,
            "circuit_breaker": {
                "halted": True,
                "reference_price": 270.0,
                "trigger_price": 250.0,
                "triggered_level": "L1",
                "expansion_index": 0,
                "resume_at_ns": _T0 + 300_000_000_000,
            },
        },
    ],
}
ADMIN_REBALANCE: dict[str, Any] = {
    "gateway_id": "OPS01",
    "accepted": True,
    "ts_ns": _T0,
    "updated_symbols": 2,
    "index_id": "EDU3",
    "level": 1014.3,
    "divisor": 5.5612e9,
    "old_divisor": 5.5598e9,
    "command_id": _CMD,
}
ADMIN_KILL_SYMBOL: dict[str, Any] = {
    "gateway_id": "OPS01",
    "accepted": True,
    "symbol": "TSLA",
    "cancelled_orders": 14,
    "cancelled_order_ids": [_ORDER_1, _ORDER_3],
    "cancelled_quotes": 1,
    "cancelled_quote_order_ids": [_ORDER_2],
    "command_id": _CMD,
}
ADMIN_KILL_GATEWAY: dict[str, Any] = {
    "gateway_id": "OPS01",
    "accepted": True,
    "target_gateway_id": "TRADER01",
    "cancelled_orders": 2,
    "cancelled_order_ids": [_ORDER_1, _ORDER_3],
    "cancelled_quotes": 0,
    "cancelled_quote_order_ids": [],
    "command_id": _CMD,
}
ADMIN_KILL_GLOBAL: dict[str, Any] = {
    "gateway_id": "OPS01",
    "accepted": True,
    "cancelled_orders": 57,
    "cancelled_order_ids": [_ORDER_1, _ORDER_3],
    "cancelled_quotes": 4,
    "cancelled_quote_order_ids": [_ORDER_2],
    "affected_gateways": 3,
    "affected_gateway_ids": ["MM01", "TRADER01", "TRADER02"],
    "command_id": _CMD,
}
ADMIN_ORDERS: dict[str, Any] = {
    "count": 1,
    "orders": [
        {
            **ORDER_CACHED,
            "gateway_id": "TRADER01",
        }
    ],
    "retention_sec": 3600,
}
ADMIN_ORDER_LIFECYCLE: dict[str, Any] = {
    "order_id": _ORDER_1,
    "indexed_through": "2026-08-29T15:10:41.207+00:00",
    "count": 2,
    "events": [
        {
            "timestamp": "2026-08-29T13:30:00.118000+00:00",
            "topic": topic_order_ack("TRADER01"),
            "gateway_id": "TRADER01",
            "symbol": "AAPL",
            "order_id": _ORDER_1,
            "payload": (
                '{"gateway_id": "TRADER01", "order_id": "' + _ORDER_1 + '", '
                '"accepted": true, "symbol": "AAPL", "side": "BUY", "qty": 100}'
            ),
        },
        {
            "timestamp": "2026-08-29T13:30:02.904000+00:00",
            "topic": topic_order_fill("TRADER01"),
            "gateway_id": "TRADER01",
            "symbol": "AAPL",
            "order_id": _ORDER_1,
            "payload": (
                '{"gateway_id": "TRADER01", "order_id": "' + _ORDER_1 + '", '
                '"fill_qty": 40, "fill_price": 187.25, "remaining_qty": 60, '
                '"status": "PARTIAL"}'
            ),
        },
    ],
}
ADMIN_POSITIONS: dict[str, Any] = {
    "gateway_id": "TRADER01",
    "count": 2,
    "positions": [
        {"symbol": "AAPL", "net_qty": 40, "avg_cost": 187.25},
        {"symbol": "TSLA", "net_qty": -25, "avg_cost": 249.6},
    ],
}

# ---------------------------------------------------------------------------
# Request examples and shared parameter text
# ---------------------------------------------------------------------------

STRUCTURE_CANCEL_ACK = (
    "`request_tag` (query) is echoed on the engine's cancel ack. Returns `202` "
    "(`PENDING_CANCEL`); with `?wait=ack`, `200` and the outcome (`ACKED`, or "
    "`REJECTED` with a `reject_code`), or `202` with `ack_timeout: true` if it "
    "did not come in time."
)

STRUCTURE_ACK = (
    "Returns `202` (`PENDING`), the verdict following on the private "
    "WebSocket; with `?wait=ack`, `200` and the verdict in the same response, "
    "or `202` with `ack_timeout: true` if it did not come in time. Send an "
    "`Idempotency-Key` to make a retry safe."
)

WAIT_ACK = (
    "Pass `ack` to hold the response until the engine acknowledges the "
    "request (up to the gateway's `wait_ack_sec`). Without it the call "
    "returns immediately with a `PENDING` status and the verdict arrives on "
    "the private WebSocket."
)

#: Named request bodies for ``POST /orders`` (Swagger shows a dropdown).
ORDER_REQUEST_EXAMPLES: dict[str, Example] = {
    "limit": {
        "summary": "Limit order",
        "description": "Buy 100 AAPL at 187.25, good for the day.",
        "value": {
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 100,
            "price": 187.25,
            "tif": "DAY",
            "client_tag": "strategy-7",
        },
    },
    "market": {
        "summary": "Market order",
        "description": "Takes whatever the book offers; `price` is forbidden.",
        "value": {
            "symbol": "MSFT",
            "side": "SELL",
            "order_type": "MARKET",
            "quantity": 50,
        },
    },
    "iceberg": {
        "summary": "Iceberg order",
        "description": "Shows 500 at a time out of 5000; `visible_qty` < `quantity`.",
        "value": {
            "symbol": "MSFT",
            "side": "SELL",
            "order_type": "ICEBERG",
            "quantity": 5000,
            "visible_qty": 500,
            "price": 412.8,
            "tif": "GTC",
        },
    },
    "stop_limit": {
        "summary": "Stop-limit order",
        "description": "Becomes a limit order at `price` once `stop_price` trades.",
        "value": {
            "symbol": "TSLA",
            "side": "SELL",
            "order_type": "STOP_LIMIT",
            "quantity": 25,
            "stop_price": 245.0,
            "price": 244.5,
        },
    },
    "trailing_stop": {
        "summary": "Trailing stop",
        "description": "Stop that follows the market at a fixed distance.",
        "value": {
            "symbol": "TSLA",
            "side": "SELL",
            "order_type": "TRAILING_STOP",
            "quantity": 25,
            "trail_offset": 2.5,
        },
    },
}


def drop_stock_validation_error(schema: dict[str, Any]) -> None:
    """Remove FastAPI's automatic ``422 HTTPValidationError`` from *schema*.

    This gateway answers a malformed request with ``400`` and its own error
    envelope (see ``RequestValidationError`` handling in ``main.py``), so the
    stock 422 FastAPI adds to every route documents a response that is never
    sent. Routes that really do return 422 declare it explicitly, without the
    stock schema, and are left alone.
    """
    for operations in schema.get("paths", {}).values():
        for operation in operations.values():
            response = operation.get("responses", {}).get("422")
            if response is None:
                continue
            body = response.get("content", {}).get("application/json", {})
            if body.get("schema", {}).get("$ref", "").endswith("/HTTPValidationError"):
                del operation["responses"]["422"]
    components = schema.get("components", {}).get("schemas", {})
    components.pop("HTTPValidationError", None)
    components.pop("ValidationError", None)


def restore_example_nulls(schema: dict[str, Any], routes: Sequence[BaseRoute]) -> None:
    """Put the ``null`` fields of every response example back into *schema*.

    FastAPI encodes the whole document with ``exclude_none``
    (``fastapi.openapi.utils.get_openapi``), which also strips each ``None``
    inside an example value: a nullable required field then looked optional
    to a client written from the contract (CG11, finding F11). Each example is
    copied again from the route's own ``responses=``, encoded without it.
    """
    for route in iter_route_contexts(routes):
        if not isinstance(route.original_route, APIRoute):
            continue
        if not route.include_in_schema:
            continue
        operations = schema["paths"][route.path_format]
        for method in route.methods or ():
            published = operations[method.lower()]["responses"]
            for code, documented in route.responses.items():
                media = documented.get("content", {}).get("application/json", {})
                for key in ("example", "examples"):
                    if key in media:
                        shown = published[str(code)]["content"]["application/json"]
                        shown[key] = jsonable_encoder(media[key])


# ---------------------------------------------------------------------------
# Route examples (WP-API04)
#
# What each route actually sends. The examples above are the engine's
# payloads, kept pure because they are checked against the message specs;
# a route's example is that payload as the engine serialises it (through the
# generated binding, so no always-present field is missing) plus whatever the
# gateway adds -- a D6 `count`, the session locale, an un-nested bootstrap.
# tests/test_api_gateway_openapi.py checks each against its response model.
# ---------------------------------------------------------------------------


def _wire(message: Any, example: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = message.from_dict(example).to_dict()
    return payload


def _counted(reply: dict[str, Any], key: str) -> dict[str, Any]:
    return {**reply, "count": len(reply[key])}


def _page(page: dict[str, Any], key: str) -> dict[str, Any]:
    """A history page as sent: no internal `_rowid`, `next_cursor` always set."""
    rows = [{k: v for k, v in row.items() if k != "_rowid"} for row in page[key]]
    cursor = (
        "eyJ0cyI6IjIwMjYtMDgtMjlUMTM6MzA6MDIuOTA0KzAwOjAwIn0"
        if page.get("has_more")
        else None
    )
    return {**page, key: rows, "next_cursor": cursor}


REFERENCE_REPLY = _wire(system_msgs.Reference, REFERENCE_BUNDLE)
REFERENCE_SYMBOLS_REPLY = {
    "symbols": REFERENCE_REPLY["symbols"],
    "count": len(REFERENCE_REPLY["symbols"]),
    "config_version": REFERENCE_REPLY["config_version"],
}
REFERENCE_INDEXES_REPLY = {
    "indexes": REFERENCE_REPLY["indexes"],
    "count": len(REFERENCE_REPLY["indexes"]),
    "config_version": REFERENCE_REPLY["config_version"],
}
SYMBOLS_REPLY = _counted(_wire(system_msgs.Symbols, SYMBOLS), "symbols")
SESSION: dict[str, Any] = {
    **_wire(system_msgs.SessionStatus, SESSION_STATUS),
    "session_timezone": "Europe/Stockholm",
    "session_date": "2026-08-29",
}
HALTS_REPLY = _counted(_wire(system_msgs.HaltStatus, HALT_STATUS), "halted")
QUOTES_REPLY = _counted(_wire(system_msgs.QuoteBootstrap, QUOTE_BOOTSTRAP), "quotes")
QUOTE_LEGS_REPLY = _counted(_wire(system_msgs.QuoteLegs, QUOTE_LEGS), "legs")
NEWS_REPLY: dict[str, Any] = {
    "news": [_wire(news_msgs.NewsEvent, item) for item in NEWS["news"]],
    "count": len(NEWS["news"]),
    "sectors": NEWS["sectors"],
}
POSITIONS_REPLY = _counted(POSITIONS, "positions")
STATUS_REPLY: dict[str, Any] = {"gateway_id": "TRADER01", "gateway_role": "TRADER"}
ORDERS_LIST_REPLY = _counted(_wire(order_msgs.Orders, ORDERS_LIST), "orders")
MASS_CANCEL_REPLY = _wire(risk_msgs.KillSwitchAck, MASS_CANCEL)

#: ``book.AAPL`` as the engine publishes it (display prices only).
BOOK_SNAPSHOT: dict[str, Any] = {
    "symbol": "AAPL",
    "tick_decimals": 2,
    "ts_ns": _T0 + 250_000_000,
    "bids": [
        {"price": 186.9, "qty": 300, "count": 2},
        {"price": 186.85, "qty": 500, "count": 1},
        {"price": 186.8, "qty": 1200, "count": 5},
    ],
    "asks": [
        {"price": 186.95, "qty": 250, "count": 1},
        {"price": 187.0, "qty": 600, "count": 3},
        {"price": 187.1, "qty": 900, "count": 4},
    ],
    "last_price": 186.95,
    "last_qty": 100,
    "last_buy_price": 186.95,
    "last_sell_price": 186.9,
    "recent_trades": [
        {
            "id": "T-20260829-000411",
            "symbol": "AAPL",
            "buy_order_id": _ORDER_2,
            "sell_order_id": _ORDER_3,
            "buy_gateway_id": "TRADER01",
            "sell_gateway_id": "MM01",
            "price": 186.9,
            "quantity": 50,
            "ts_ns": _T0 + 100_000_000,
        },
        {
            "id": _TRADE_1,
            "symbol": "AAPL",
            "buy_order_id": _ORDER_1,
            "sell_order_id": _ORDER_3,
            "buy_gateway_id": "TRADER01",
            "sell_gateway_id": "MM01",
            "price": 186.95,
            "quantity": 100,
            "ts_ns": _T0 + 200_000_000,
        },
    ],
}
#: ``seq`` the examples give ``BOOK_SNAPSHOT``'s WebSocket frame.
BOOK_SEQ = 4812
BOOK_REPLY: dict[str, Any] = {
    "symbol": "AAPL",
    "tick_decimals": 2,
    "ts_ns": _T0 + 250_000_000,
    "seq": BOOK_SEQ,
    "bids": [
        {"price": 186.9, "qty": 300, "count": 2, "price_ticks": 18690},
        {"price": 186.85, "qty": 500, "count": 1, "price_ticks": 18685},
        {"price": 186.8, "qty": 1200, "count": 5, "price_ticks": 18680},
    ],
    "asks": [
        {"price": 186.95, "qty": 250, "count": 1, "price_ticks": 18695},
        {"price": 187.0, "qty": 600, "count": 3, "price_ticks": 18700},
        {"price": 187.1, "qty": 900, "count": 4, "price_ticks": 18710},
    ],
    "last_price": 186.95,
    "last_price_ticks": 18695,
    "last_qty": 100,
    "last_buy_price": 186.95,
    "last_buy_price_ticks": 18695,
    "last_sell_price": 186.9,
    "last_sell_price_ticks": 18690,
    "recent_trades": [
        {**BOOK_SNAPSHOT["recent_trades"][0], "price_ticks": 18690},
        {**BOOK_SNAPSHOT["recent_trades"][1], "price_ticks": 18695},
    ],
}
BOOK_LIST_REPLY: dict[str, Any] = {
    "books": [
        {
            "symbol": "AAPL",
            "tick_decimals": 2,
            "ts_ns": _T0 + 250_000_000,
            "seq": BOOK_SEQ,
            "best_bid": BOOK_REPLY["bids"][0],
            "best_ask": BOOK_REPLY["asks"][0],
            "last_price": 186.95,
            "last_price_ticks": 18695,
        },
        {
            "symbol": "MSFT",
            "tick_decimals": 2,
            "ts_ns": _T0 + 120_000_000,
            "seq": 2031,
            "best_bid": {"price": 411.3, "qty": 200, "count": 1, "price_ticks": 41130},
            "best_ask": {"price": 411.4, "qty": 400, "count": 2, "price_ticks": 41140},
            "last_price": 411.35,
            "last_price_ticks": 41135,
        },
        {
            "symbol": "TSLA",
            "tick_decimals": 2,
            "ts_ns": _T0 - 60_000_000_000,
            "seq": 977,
            "best_bid": None,
            "best_ask": {"price": 248.4, "qty": 100, "count": 1, "price_ticks": 24840},
            "last_price": None,
            "last_price_ticks": None,
        },
    ],
    "count": 3,
}

HISTORY_ORDERS_REPLY = _page(HISTORY_ORDERS, "events")
HISTORY_FILLS_REPLY = _page(HISTORY_FILLS, "events")
HISTORY_TRADES_REPLY = _page(HISTORY_TRADES, "trades")
HISTORY_DAILY_REPLY = _page(HISTORY_DAILY, "daily")
HISTORY_PRICE_SNAPSHOTS_REPLY = _page(HISTORY_PRICE_SNAPSHOTS, "snapshots")
HISTORY_INDEX_DAILY_REPLY = _page(HISTORY_INDEX_DAILY, "daily")
HISTORY_INDEX_SNAPSHOTS_REPLY = _page(HISTORY_INDEX_SNAPSHOTS, "snapshots")

ADMIN_GATEWAYS_REPLY = _counted(_wire(system_msgs.Gateways, ADMIN_GATEWAYS), "gateways")
ADMIN_RISK_STATE_REPLY = _counted(
    _wire(system_msgs.RiskState, ADMIN_RISK_STATE), "symbols"
)
ADMIN_HALT_ACK_REPLY = _wire(risk_msgs.SymbolHaltAck, ADMIN_HALT_ACK)
ADMIN_RESUME_ACK_REPLY = _wire(risk_msgs.SymbolResumeAck, ADMIN_RESUME_ACK)
ADMIN_KILL_SYMBOL_REPLY = _wire(risk_msgs.CancelSymbolAck, ADMIN_KILL_SYMBOL)
ADMIN_KILL_GATEWAY_REPLY = _wire(risk_msgs.KillSwitchGatewayAck, ADMIN_KILL_GATEWAY)
ADMIN_KILL_GLOBAL_REPLY = _wire(risk_msgs.KillSwitchGlobalAck, ADMIN_KILL_GLOBAL)
ADMIN_KILL_GATEWAY_SYMBOL_REPLY = _wire(
    risk_msgs.KillSwitchGatewayAck,
    {
        **ADMIN_KILL_GATEWAY,
        "symbol": "AAPL",
        "cancelled_order_ids": [_ORDER_1],
        "cancelled_orders": 1,
    },
)
ADMIN_QUOTE_CANCEL_REPLY = _wire(
    risk_msgs.KillSwitchGatewayAck,
    {
        **ADMIN_KILL_GATEWAY,
        "target_gateway_id": "MM01",
        "symbol": "AAPL",
        "quotes_only": True,
        "cancelled_orders": 0,
        "cancelled_order_ids": [],
        "cancelled_quotes": 2,
        "cancelled_quote_order_ids": [_ORDER_2, _ORDER_3],
    },
)
ADMIN_HALT_ALL_REPLY = _wire(
    risk_msgs.CircuitBreakerHaltAllAck,
    {
        "gateway_id": "OPS01",
        "accepted": True,
        "halted_symbols": 3,
        "halted_symbol_ids": ["AAPL", "MSFT", "TSLA"],
        "cancelled_quotes": 4,
        "cancelled_quote_order_ids": [_ORDER_2, _ORDER_3],
    },
)
ADMIN_RESUME_ALL_REPLY = _wire(
    risk_msgs.CircuitBreakerResumeAllAck,
    {
        "gateway_id": "OPS01",
        "accepted": True,
        "resumed_symbols": 3,
        "resumed_symbol_ids": ["AAPL", "MSFT", "TSLA"],
    },
)
ADMIN_REOPEN_REPLY = {
    "dry_run": (
        "dry_run: the indicative print, nothing changed",
        _wire(
            risk_msgs.ForceUncrossAck,
            {
                "gateway_id": "OPS01",
                "accepted": True,
                "symbol": "AAPL",
                "dry_run": True,
                "indicative_price": 187.25,
                "indicative_qty": 1200,
                "surplus": 300,
                "imbalance_side": "BUY",
                "printed_price": None,
                "traded_qty": 0,
                "command_id": _CMD,
            },
        ),
    ),
    "reopened": (
        "Reopened at an operator price",
        _wire(
            risk_msgs.ForceUncrossAck,
            {
                "gateway_id": "OPS01",
                "accepted": True,
                "symbol": "AAPL",
                "dry_run": False,
                "indicative_price": 187.25,
                "indicative_qty": 1200,
                "surplus": 300,
                "imbalance_side": "BUY",
                "printed_price": 187.25,
                "traded_qty": 1200,
                "command_id": _CMD,
            },
        ),
    ),
}
ADMIN_GATEWAY_ORDERS_REPLY = _counted(
    _wire(order_msgs.Orders, {**ORDERS_LIST, "gateway_id": "MM01"}), "orders"
)
ADMIN_PRICE_LEVEL_REPLY = _counted(
    _wire(
        order_msgs.PriceLevelOrders,
        {
            "gateway_id": "OPS01",
            "symbol": "AAPL",
            "price": 187.25,
            "rejected": False,
            "orders": [{**_ORDER_DISPLAY_LIMIT, "gateway_id": "TRADER01"}],
        },
    ),
    "orders",
)
ADMIN_VOLUME_REPLY = _counted(
    _wire(
        system_msgs.Volume,
        {
            "gateway_id": "OPS01",
            "symbols": [
                {"symbol": "AAPL", "qty": 18400, "value": 3445200.0, "trades": 312},
                {"symbol": "MSFT", "qty": 9100, "value": 3756480.0, "trades": 140},
            ],
            "total_qty": 27500,
            "total_value": 7201680.0,
            "total_trades": 452,
        },
    ),
    "symbols",
)
ADMIN_REBALANCE_REPLY = _wire(index_msgs.IndexRebalanceAck, ADMIN_REBALANCE)

BOOTSTRAP_TRADER: dict[str, Any] = {
    "ts": "2026-08-29T13:30:05.412+00:00",
    "incomplete": [],
    "gateway_id": "TRADER01",
    "gateway_role": "TRADER",
    "session_timezone": "Europe/Stockholm",
    "reference": REFERENCE_REPLY,
    "session": SESSION,
    "positions": POSITIONS["positions"],
    "orders": ORDERS_LIST_REPLY["orders"],
    "recent_fills": HISTORY_FILLS_REPLY["events"],
    "halts": [],
    "capabilities": _CAPABILITIES,
}
BOOTSTRAP_MM: dict[str, Any] = {
    **BOOTSTRAP_TRADER,
    "gateway_id": "MM01",
    "gateway_role": "MARKET_MAKER",
    "quotes": QUOTES_REPLY["quotes"],
    "quote_legs": QUOTE_LEGS_REPLY["legs"],
}
BOOTSTRAP_ADMIN: dict[str, Any] = {
    "ts": "2026-08-29T13:30:05.412+00:00",
    "incomplete": [],
    "gateway_id": "OPS01",
    "gateway_role": "ADMIN",
    "session_timezone": "Europe/Stockholm",
    "reference": REFERENCE_REPLY,
    "session": SESSION,
    "gateways": ADMIN_GATEWAYS_REPLY["gateways"],
    "halts": [],
    "active_order_counts": {"TRADER01": 2, "MM01": 2, "OPS01": 0},
    "monitor_last_seq": {"TRADER01": 1843, "MM01": 5120, "OPS01": 77},
    "capabilities": _CAPABILITIES,
}


# ---------------------------------------------------------------------------
# Clearing (rows as clearing.db stores them, then as the routes return them)
# ---------------------------------------------------------------------------

_CL_DAY = "2026-08-29"
_CL_PREV_DAY = "2026-08-28"
_FLUSH = _T0 + 4_200_000_000


def _clearing_money(row: dict[str, Any], *money: str) -> dict[str, Any]:
    """*row* as a clearing route returns it: ``<name>_ticks`` as stored and
    ``<name>`` in display currency, per the row's ``tick_decimals``."""
    scale = 10 ** row["tick_decimals"]
    out = dict(row)
    for name in money:
        out[f"{name}_ticks"] = row[name]
        out[name] = None if row[name] is None else row[name] / scale
    return out


def _bounded(key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {key: items, "count": len(items), "has_more": False}


_POSITION_STORED: list[dict[str, Any]] = [
    {
        "gateway_id": "TRADER01",
        "symbol": "AAPL",
        "net_qty": 110,
        "tick_decimals": 2,
        "avg_cost": 18733.333333333332,
        "mark_price": 18800,
        "realized_pnl": 2666.666666666715,
        "unrealized_pnl": 7333.333333333467,
        "buy_qty": 150,
        "sell_qty": 40,
        "buy_notional": 2810000,
        "sell_notional": 752000,
        "last_trade_ts_ns": _T0,
        "updated_ts_ns": _FLUSH,
    },
    {
        "gateway_id": "TRADER01",
        "symbol": "MSFT",
        "net_qty": -20,
        "tick_decimals": 2,
        "avg_cost": 41210.0,
        "mark_price": 41150,
        "realized_pnl": 0.0,
        "unrealized_pnl": 1200.0,
        "buy_qty": 0,
        "sell_qty": 20,
        "buy_notional": 0,
        "sell_notional": 824200,
        "last_trade_ts_ns": _T0 - 3_600_000_000_000,
        "updated_ts_ns": _FLUSH,
    },
]
_POSITION_MONEY = (
    "avg_cost",
    "mark_price",
    "realized_pnl",
    "unrealized_pnl",
    "buy_notional",
    "sell_notional",
)
CLEARING_POSITIONS = [_clearing_money(r, *_POSITION_MONEY) for r in _POSITION_STORED]
CLEARING_POSITIONS_REPLY = _bounded("positions", CLEARING_POSITIONS)

CLEARING_EXPOSURE_REPLY = _bounded(
    "exposure",
    [
        _clearing_money(
            {
                "gateway_id": r["gateway_id"],
                "symbol": r["symbol"],
                "net_qty": r["net_qty"],
                "tick_decimals": r["tick_decimals"],
                "mark_price": r["mark_price"],
                "net_notional": r["net_qty"] * r["mark_price"],
                "gross_notional": abs(r["net_qty"] * r["mark_price"]),
                "realized_pnl": r["realized_pnl"],
                "unrealized_pnl": r["unrealized_pnl"],
                "total_pnl": r["realized_pnl"] + r["unrealized_pnl"],
            },
            "mark_price",
            "net_notional",
            "gross_notional",
            "realized_pnl",
            "unrealized_pnl",
            "total_pnl",
        )
        for r in _POSITION_STORED
    ],
)

_CLEARING_TRADE = _clearing_money(
    {
        "trade_id": "000007-000000412",
        "ts_ns": _T0,
        "ingest_ts_ns": _T0 + 1_250_000_000,
        "trade_date": _CL_DAY,
        "symbol": "AAPL",
        "quantity": 40,
        "tick_decimals": 2,
        "price": 18800,
        "buy_gateway_id": None,
        "sell_gateway_id": "TRADER01",
        "buy_order_id": None,
        "sell_order_id": _ORDER_1,
        "aggressor_side": "SELL",
        "match_type": "CONTINUOUS",
        "msg_id": "01K3QH4Z7T6R2W9X8V5N3M1B0C",
    },
    "price",
)
CLEARING_TRADES_REPLY: dict[str, Any] = {
    "trades": [_CLEARING_TRADE],
    "count": 1,
    "has_more": True,
    "next_cursor": "MTc4ODAxMzgwMDAwMDAwMDAwMDoxNzg4MDEzODAxMjUwMDAwMDAwOjAwMDAwNy0wMDAwMDA0MTI",
    "retained_from": "2026-06-01",
}

CLEARING_DAILY_REPLY = _bounded(
    "daily",
    [
        _clearing_money(
            {
                "trade_date": _CL_DAY,
                "gateway_id": "TRADER01",
                "symbol": "AAPL",
                "tick_decimals": 2,
                "traded_qty": 40,
                "traded_notional": 752000,
                "buy_qty": 0,
                "sell_qty": 40,
                "buy_notional": 0,
                "sell_notional": 752000,
                "net_amount": -752000,
                "realized_pnl": 2666.666666666715,
                "end_net_qty": 110,
                "end_avg_cost": 18733.333333333332,
                "end_unrealized_pnl": 7333.333333333467,
                "last_trade_ts_ns": _T0,
                "updated_ts_ns": _FLUSH,
            },
            "traded_notional",
            "buy_notional",
            "sell_notional",
            "net_amount",
            "realized_pnl",
            "end_avg_cost",
            "end_unrealized_pnl",
        )
    ],
)

CLEARING_CLOSE_SNAPSHOTS_REPLY = _bounded(
    "snapshots",
    [
        _clearing_money(
            {
                "trade_date": day,
                "gateway_id": "TRADER01",
                "symbol": "AAPL",
                "net_qty": qty,
                "tick_decimals": 2,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "mark_price": mark,
            },
            "realized_pnl",
            "unrealized_pnl",
            "mark_price",
        )
        for day, qty, realized, unrealized, mark in (
            (_CL_DAY, 110, 2666.666666666715, 7333.333333333467, 18800),
            (_CL_PREV_DAY, 150, 0.0, 2500.0000000002, 18750),
        )
    ],
)

CLEARING_SYMBOLS_REPLY = _bounded(
    "symbols",
    [
        _clearing_money(
            {
                "symbol": "AAPL",
                "tick_decimals": 2,
                "traded_qty": 380,
                "traded_notional": 7124000.0,
                "realized_pnl": 0.0,
                "open_net_qty": 0,
                "open_unrealized_pnl": 0.0,
            },
            "traded_notional",
            "realized_pnl",
            "open_unrealized_pnl",
        )
    ],
)

_PARTICIPANT = {
    "gateway_id": "TRADER01",
    "realized_pnl": 26.666666666667,
    "unrealized_pnl": 85.333333333335,
    "total_pnl": 112.000000000002,
    "position_count": 2,
    "open_position_count": 2,
    "last_update_ts_ns": _FLUSH,
}
CLEARING_PARTICIPANTS_REPLY = _bounded(
    "participants",
    [
        _PARTICIPANT,
        {
            **_PARTICIPANT,
            "gateway_id": "MM01",
            "realized_pnl": -26.666666666667,
            "unrealized_pnl": -85.333333333335,
            "total_pnl": -112.000000000002,
        },
    ],
)


def _participant_links(gateway_id: str) -> dict[str, str]:
    base = "/api/v1/clearing"
    names = {
        "positions": "positions",
        "exposure": "exposure",
        "trades": "trades",
        "daily": "daily",
        "close_snapshots": "close-snapshots",
        "gateway_sessions": "gateway-sessions",
        "settlements": "settlements",
        "balances": "balances",
    }
    return {key: f"{base}/{path}?gateway={gateway_id}" for key, path in names.items()}


CLEARING_PARTICIPANT: dict[str, Any] = {
    **_PARTICIPANT,
    "positions": CLEARING_POSITIONS,
    "latest_close_date": _CL_PREV_DAY,
    "links": _participant_links("TRADER01"),
}

CLEARING_GAP: dict[str, Any] = {
    "trade_date": _CL_DAY,
    "ts_ns": _T0 - 600_000_000_000,
    "run_seq": 7,
    "last_seq": 398,
    "next_seq": 401,
    "missing_trades": 2,
}
EOD_RUN: dict[str, Any] = {
    "trade_date": _CL_PREV_DAY,
    "status": "ok",
    "started_at": "2026-08-28T15:35:00+00:00",
    "finished_at": "2026-08-28T15:35:02+00:00",
    "steps": [
        {"step": "settle", "status": "ok", "message": "3 accounts"},
        {"step": "report", "status": "ok", "message": "3 statements"},
    ],
}
CLEARING_SUMMARY: dict[str, Any] = {
    "participant_count": 2,
    "open_position_count": 4,
    "realized_pnl": 0.0,
    "unrealized_pnl": 0.0,
    "last_trade_ts_ns": _T0,
    "last_flush_ts_ns": _FLUSH,
    "session_date": _CL_DAY,
    "gap_count": 1,
    "latest_gap": CLEARING_GAP,
    "eod_db_available": True,
    "last_eod_run": EOD_RUN,
}

CLEARING_SESSION_EVENTS_REPLY = _bounded(
    "events",
    [
        {
            "id": 42,
            "event_type": "PHASE",
            "ts_ns": _T0 + 9_000_000_000_000,
            "trade_date": _CL_DAY,
            "phase": {"state": "CLOSED", "prev_state": "CLOSING_AUCTION"},
        },
        {
            "id": 41,
            "event_type": "GAP",
            "ts_ns": CLEARING_GAP["ts_ns"],
            "trade_date": _CL_DAY,
            "gap": {
                key: CLEARING_GAP[key]
                for key in ("run_seq", "last_seq", "next_seq", "missing_trades")
            },
        },
        {
            "id": 37,
            "event_type": "EOD",
            "ts_ns": _T0 - 77_000_000_000_000,
            "trade_date": _CL_PREV_DAY,
            "eod": {"symbols_count": 3, "marked_symbols": ["AAPL", "MSFT", "TSLA"]},
        },
    ],
)

CLEARING_GATEWAY_SESSIONS_REPLY = _bounded(
    "sessions",
    [
        {
            "gateway_id": "TRADER01",
            "connected_at_ns": _T0 - 14_400_000_000_000,
            "disconnected_at_ns": None,
            "disconnect_reason": None,
        },
        {
            "gateway_id": "TRADER01",
            "connected_at_ns": _T0 - 100_800_000_000_000,
            "disconnected_at_ns": _T0 - 72_000_000_000_000,
            "disconnect_reason": "logout",
        },
    ],
)

CLEARING_RECONCILIATION_REPLY: dict[str, Any] = {
    **_bounded(
        "discrepancies",
        [
            _clearing_money(
                {
                    "side": "BUY",
                    "trade_date": _CL_PREV_DAY,
                    "gateway_id": "TRADER01",
                    "symbol": "AAPL",
                    "raw_qty": 150,
                    "summary_qty": 140,
                    "qty_diff": 10,
                    "tick_decimals": 2,
                    "raw_notional": 2810000,
                    "summary_notional": 2622500,
                    "notional_diff": 187500,
                },
                "raw_notional",
                "summary_notional",
                "notional_diff",
            )
        ],
    ),
    "retained_from": "2026-06-01",
    "compared_from": _CL_PREV_DAY,
    "compared_to": _CL_DAY,
}

CLEARING_HEALTH: dict[str, Any] = {
    "database": {
        "available": True,
        "detail": "readable",
        "wal_mode": "wal",
        "trade_events_rows": 18452,
        "gateway_symbol_positions_rows": 9,
        "gateway_daily_summary_rows": 512,
        "last_trade_ts_ns": _T0,
        "last_flush_ts_ns": _FLUSH,
    },
    "process": {"alive": True, "detail": "replied at 2026-08-29T13:30:05.118+00:00"},
}

CLEARING_SETTLEMENTS_REPLY: dict[str, Any] = {
    "settlements": [
        {
            "trade_date": _CL_PREV_DAY,
            "account": "TRADER01",
            "amount_minor": 2500,
            "amount": "25.00",
            "detail": {"AAPL": "25.0000000000002", "MSFT": "0"},
            "run_status": "ok",
        },
        {
            "trade_date": _CL_PREV_DAY,
            "account": "MM01",
            "amount_minor": -2500,
            "amount": "-25.00",
            "detail": {"AAPL": "-25.0000000000002", "MSFT": "0"},
            "run_status": "ok",
        },
    ],
    "count": 2,
    "has_more": False,
    "runs": [EOD_RUN],
}

CLEARING_BALANCES_REPLY: dict[str, Any] = {
    "balances": [
        {
            "account": "TRADER01",
            "opening_balance_minor": 1000000,
            "opening_balance": "10000.00",
            "settlement_total_minor": 2500,
            "settlement_total": "25.00",
            "balance_minor": 1002500,
            "balance": "10025.00",
        }
    ],
    "count": 1,
    "as_of": _CL_PREV_DAY,
    "last_settled_date": _CL_PREV_DAY,
}
