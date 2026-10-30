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

from typing import Any

from fastapi.openapi.models import Example

from edumatcher.api_gateway.schemas import ErrorResponse
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
  `MARKET_MAKER` (adds quoting) or `ADMIN` (adds the `/admin` endpoints);
* a **read-only key** (`gateway_id` null) -- may read public data only:
  `/reference/*`, `/news`, `/companies/{symbol}`, `/history/trades`,
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
(`tick_decimals` in `/symbols`); an off-grid price is `400 TICK_VIOLATION`.
Timestamps named `ts_ns` / `*_ns` are epoch nanoseconds; `ts` in history rows is
ISO-8601 UTC. `date` filters are trading days in the exchange's own timezone
(see `/history/session`).

## WebSocket

Live streams are WebSockets and are not part of this OpenAPI document:
`/api/v1/ws/private` (orders, fills, quotes), `/api/v1/ws/market-data`
(book, trades, depth, auction, session, halts, news) and `/api/v1/ws/admin/monitor`.
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


def _error(code: str, message: str, **extra: str) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    error.update(extra)
    return {"error": error}


def _err_response(description: str, example: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": ErrorResponse,
        "description": description,
        "content": {"application/json": {"example": example}},
    }


#: Errors any authenticated endpoint can produce. Applied once, on the app.
COMMON_ERRORS: dict[int | str, dict[str, Any]] = {
    400: _err_response(
        "A parameter or body field is missing, unknown or invalid. "
        "`reject_code` is one of `MISSING_FIELD`, `UNSUPPORTED_FIELD`, "
        "`INVALID_VALUE`, `TICK_VIOLATION`; `field` names the culprit.",
        _error(
            "VALIDATION",
            "Input should be less than or equal to 5000",
            field="limit",
            reject_code="INVALID_VALUE",
        ),
    ),
    401: _err_response(
        "Missing, malformed or unknown API key. Carries `WWW-Authenticate: Bearer`.",
        _error(
            "AUTH",
            "Unknown API key",
            reject_code="AUTH_REQUIRED",
        ),
    ),
    403: _err_response(
        "The key is valid but not allowed to do this: a read-only key on a "
        "gateway-scoped endpoint (`READ_ONLY`), a non-ADMIN key on an admin "
        "endpoint (`ROLE_DENIED`), or the engine refused the gateway "
        "(`ENGINE_AUTH`).",
        _error(
            "ROLE_DENIED",
            "ADMIN role required",
            reject_code="ROLE_DENIED",
        ),
    ),
    503: _err_response(
        "The engine (or pm-index) did not answer within the configured " "timeout.",
        _error(
            "ENGINE_TIMEOUT",
            "Timed out waiting for engine reply",
            reject_code="INTERNAL_ERROR",
        ),
    ),
}

#: Added to routes with a request body or query validation.
VALIDATION_ERROR: dict[int | str, dict[str, Any]] = {
    400: _err_response(
        "The request is malformed or breaks a rule: missing/extra field, bad "
        "value, price off the tick grid. `reject_code` is one of "
        "`MISSING_FIELD`, `UNSUPPORTED_FIELD`, `INVALID_VALUE`, "
        "`TICK_VIOLATION`.",
        _error(
            "VALIDATION",
            "LIMIT requires price",
            field="__root__",
            reject_code="MISSING_FIELD",
            client_tag="strategy-7",
        ),
    )
}

#: Added to the history routes: their own filter checks (dates, cursors,
#: event types) answer like FastAPI's query validation.
INVALID_FILTER: dict[int | str, dict[str, Any]] = {
    400: _err_response(
        "A filter is malformed: a date or timestamp that does not parse, an "
        "unknown `event_type`, or a stale or foreign `after` cursor. `field` "
        "names the parameter.",
        _error(
            "VALIDATION",
            "Invalid date format: yesterday (expected YYYY-MM-DD)",
            field="date",
            reject_code="INVALID_VALUE",
        ),
    )
}

#: Added to the order-entry writes.
RATE_LIMITED: dict[int | str, dict[str, Any]] = {
    429: _err_response(
        "Write rate exceeded for this API key; retry after a short pause.",
        _error(
            "RATE_LIMIT",
            "Write rate exceeded",
            reject_code="RATE_LIMITED",
        ),
    )
}


def not_found(code: str, message: str) -> dict[int | str, dict[str, Any]]:
    return {
        404: _err_response(
            "Nothing with that identifier.",
            _error(code, message, reject_code="UNKNOWN"),
        )
    }


def conflict(code: str, message: str) -> dict[int | str, dict[str, Any]]:
    return {
        409: _err_response(
            "The engine refused the command; `message` is its reason.",
            _error(code, message, reject_code="UNKNOWN"),
        )
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
        },
    ),
}

ORDER_REPLACED = {
    "cancelled_order_id": _ORDER_1,
    "replacement_order_id": _ORDER_2,
    "status": "PENDING",
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

OCO_PENDING = {"id": "oco-2026-0042", "status": "PENDING", "event": None}
OCO_CANCEL = {"oco_id": "oco-2026-0042", "status": "PENDING_CANCEL"}
COMBO_PENDING = {"id": "combo-spread-17", "status": "PENDING", "event": None}
COMBO_CANCEL = {"combo_id": "combo-spread-17", "status": "PENDING_CANCEL"}
QUOTE_PENDING = {"id": "q-AAPL-0001", "status": "PENDING", "event": None}
QUOTE_CANCEL = {"symbol": "AAPL", "status": "PENDING_CANCEL"}

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
HISTORY_SESSION = {
    "country": "SE",
    "session_timezone": "Europe/Stockholm",
    "session_date": "2026-08-29",
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
HISTORY_INDEX_IDS = {"index_ids": ["EDU3"], "count": 1}
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

BOOTSTRAP_TRADER: dict[str, Any] = {
    "ts": "2026-08-29T13:30:05.412+00:00",
    "incomplete": [],
    "gateway_id": "TRADER01",
    "gateway_role": "TRADER",
    "session_timezone": "Europe/Stockholm",
    "reference": REFERENCE_BUNDLE,
    "session": SESSION_STATUS,
    "positions": [
        {"symbol": "AAPL", "net_qty": 40, "last_price": 187.4},
        {"symbol": "TSLA", "net_qty": -25, "last_price": None},
    ],
    "orders": ORDERS_LIST,
    "recent_fills": _FILLS_TODAY,
    "halts": {"gateway_id": "TRADER01", "halted": []},
    "capabilities": _CAPABILITIES,
}
BOOTSTRAP_MM: dict[str, Any] = {
    **BOOTSTRAP_TRADER,
    "gateway_id": "MM01",
    "gateway_role": "MARKET_MAKER",
    "quote_bootstrap": QUOTE_BOOTSTRAP,
    "quote_legs": QUOTE_LEGS,
}
BOOTSTRAP_ADMIN: dict[str, Any] = {
    "ts": "2026-08-29T13:30:05.412+00:00",
    "incomplete": [],
    "gateway_id": "OPS01",
    "gateway_role": "ADMIN",
    "session_timezone": "Europe/Stockholm",
    "reference": REFERENCE_BUNDLE,
    "session": {**SESSION_STATUS, "gateway_id": "OPS01"},
    "gateways": {
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
    },
    "halts": {"gateway_id": "OPS01", "halted": []},
    "active_order_counts": {"TRADER01": 2, "MM01": 2, "OPS01": 0},
    "monitor_last_seq": {"TRADER01": 1843, "MM01": 5120, "OPS01": 77},
    "capabilities": _CAPABILITIES,
}

# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

ADMIN_TRANSITION = {
    "requested_state": "CLOSING_AUCTION",
    "status": "APPLIED",
    "command_id": _CMD,
}
ADMIN_RELOAD = {"status": "RELOADED", "config_version": _CONFIG_VERSION}
ADMIN_SCHEDULE: dict[str, Any] = {
    "gateway_id": "OPS01",
    "sessions_enabled": True,
    "schedule": _WEEKLY_SCHEDULE,
}
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
ADMIN_GATEWAYS = BOOTSTRAP_ADMIN["gateways"]
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
ADMIN_HALTS: dict[str, Any] = {
    "gateway_id": "OPS01",
    "halted": HALT_STATUS["halted"],
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
