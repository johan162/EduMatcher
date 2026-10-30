"""Every ``error.code`` the gateway can answer with, in one table.

The spec's "Common error codes" table, each route's OpenAPI error responses
(``openapi_docs.errors``) and the envelope's default ``reject_code``
(``main``'s HTTPException handler) all come from here, and tests hold the
three -- and what the code can actually raise -- to it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorCode:
    status: int
    #: Set on the envelope when the raise site gives none.
    reject_code: str
    meaning: str
    #: ``message`` of the OpenAPI example when a route does not supply one.
    example: str


ERROR_CODES: dict[str, ErrorCode] = {
    "VALIDATION": ErrorCode(
        400,
        "INVALID_VALUE",
        "A body field, query parameter, header or history filter failed "
        "validation; `field` names it. `reject_code` is one of `MISSING_FIELD`, "
        "`UNSUPPORTED_FIELD`, `INVALID_VALUE`, `TICK_VIOLATION`.",
        "Input should be less than or equal to 5000",
    ),
    "AUTH": ErrorCode(
        401,
        "AUTH_REQUIRED",
        "Missing, malformed or unknown API key. The reply carries "
        "`WWW-Authenticate: Bearer`.",
        "Unknown API key",
    ),
    "ENGINE_AUTH": ErrorCode(
        403,
        "AUTH_FAILED",
        "The engine refused the key's gateway identity.",
        "Gateway TRADER01 is disabled",
    ),
    "READ_ONLY": ErrorCode(
        403,
        "ROLE_DENIED",
        "A read-only key used on a gateway-scoped endpoint.",
        "API key is read-only",
    ),
    "ROLE_DENIED": ErrorCode(
        403,
        "ROLE_DENIED",
        "The key's gateway lacks the role the endpoint needs (`ADMIN`, or "
        "`MARKET_MAKER` for `/bootstrap/mm`).",
        "ADMIN role required",
    ),
    "NOT_FOUND": ErrorCode(404, "UNKNOWN", "No such path.", "Not Found"),
    "UNKNOWN_ORDER": ErrorCode(
        404,
        "UNKNOWN",
        "The order id is unknown to the gateway, or absent from the audit trail.",
        "Unknown order ORD-20260806-00042",
    ),
    "UNKNOWN_COMPANY": ErrorCode(
        404, "UNKNOWN", "No company profile for the symbol.", "No company for XYZ"
    ),
    "METHOD_NOT_ALLOWED": ErrorCode(
        405,
        "UNKNOWN",
        "The path exists but not for this method; the reply carries `Allow`.",
        "Method Not Allowed",
    ),
    "TRANSITION_REJECTED": ErrorCode(
        409,
        "UNKNOWN",
        "The engine refused the session transition; `message` is its reason.",
        "Cannot transition from CLOSED to CONTINUOUS",
    ),
    "RELOAD_REJECTED": ErrorCode(
        409,
        "UNKNOWN",
        "The engine refused the reference reload; `message` is its reason.",
        "Reload refused during CONTINUOUS",
    ),
    "HALT_REJECTED": ErrorCode(
        409,
        "UNKNOWN",
        "The engine refused the halt; `message` is its reason.",
        "Unknown symbol: XYZ",
    ),
    "RESUME_REJECTED": ErrorCode(
        409,
        "UNKNOWN",
        "The engine refused the resume; `message` is its reason.",
        "TSLA is not halted",
    ),
    "KILL_SWITCH_REJECTED": ErrorCode(
        409,
        "UNKNOWN",
        "The engine refused the kill switch; `message` is its reason.",
        "Unknown gateway: NOPE01",
    ),
    "REBALANCE_REJECTED": ErrorCode(
        409,
        "UNKNOWN",
        "`pm-index` refused the rebalance; `message` is its reason.",
        "Unknown index: NOPE",
    ),
    "REPLACE_REJECTED": ErrorCode(
        409,
        "UNKNOWN",
        "The engine refused the original's cancel (it already filled, say); "
        "nothing was sent. `reject_code` is the engine's.",
        "Order already filled",
    ),
    "IDEMPOTENCY_KEY_REUSED": ErrorCode(
        409,
        "UNKNOWN",
        "The `Idempotency-Key` was already used for a different request.",
        "This Idempotency-Key was used for a different request; use a new key "
        "for a new request.",
    ),
    "RATE_LIMIT": ErrorCode(
        429,
        "RATE_LIMITED",
        "Per-key write limit exceeded; retry after a short pause.",
        "Write rate exceeded",
    ),
    "INTERNAL_ERROR": ErrorCode(
        500,
        "INTERNAL_ERROR",
        "A gateway bug; the message carries no internals.",
        "Internal server error",
    ),
    "INDEX_ERROR": ErrorCode(
        502, "UNKNOWN", "`pm-index` answered with an error.", "Unknown index: NOPE"
    ),
    "ENGINE_TIMEOUT": ErrorCode(
        503,
        "INTERNAL_ERROR",
        "No engine reply in time. Transient; retry.",
        "Timed out waiting for engine reply",
    ),
    "ENGINE_UNAVAILABLE": ErrorCode(
        503,
        # The value ALF sends for the same condition (alf_gwy/protocol.py).
        "INTERNAL_ERROR",
        "The command could not be handed to the engine (down or "
        "backpressured); nothing was sent. Transient; retry.",
        "Engine unavailable",
    ),
    "SYMBOLS_NOT_READY": ErrorCode(
        503,
        "SYMBOL_NOT_READY",
        "Order entry before the symbol's tick precision reached the gateway. "
        "Transient; retry.",
        "Reference data for AAPL is not loaded yet",
    ),
    "INDEX_TIMEOUT": ErrorCode(
        503, "UNKNOWN", "No `pm-index` reply in time.", "Timed out waiting for pm-index"
    ),
    "STATS_DB": ErrorCode(
        503,
        "UNKNOWN",
        "The `pm-stats` database is not present.",
        "Stats DB not found at /var/lib/edumatcher/stats.db",
    ),
    "AUDIT_INDEX_UNAVAILABLE": ErrorCode(
        503,
        "UNKNOWN",
        "The `pm-audit` index is not built or not running.",
        "Audit index unavailable",
    ),
    "COMPANY_DB_UNAVAILABLE": ErrorCode(
        503,
        "UNKNOWN",
        "The company database is missing or unreadable.",
        "Company database unavailable",
    ),
}
