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
    "SCOPE_DENIED": ErrorCode(
        403,
        "ROLE_DENIED",
        "A `TRADER` or `MARKET_MAKER` key asked for another gateway's clearing or "
        "settlement data; only `ADMIN` reads beyond its own gateway.",
        "Gateway TRADER01 may read only its own clearing data, not MM01",
    ),
    "NOT_FOUND": ErrorCode(404, "UNKNOWN", "No such path.", "Not Found"),
    "UNKNOWN_ORDER": ErrorCode(
        404,
        "UNKNOWN",
        "The order id is unknown to the gateway, or absent from the audit trail.",
        "Unknown order ORD-20260806-00042",
    ),
    "UNKNOWN_COLLECTION": ErrorCode(
        404,
        "UNKNOWN",
        "No audit evidence collection with this id is configured "
        "(`api_gateways.<name>.audit_collections`).",
        "No audit collection 'class-9'",
    ),
    "UNKNOWN_SNAPSHOT": ErrorCode(
        404,
        "UNKNOWN",
        "No audit evidence snapshot has this id (or the id is malformed). "
        "Create one with `POST /audit/snapshots`.",
        "No snapshot 's-0123456789abcdef0123'",
    ),
    "UNKNOWN_ENTITY": ErrorCode(
        404,
        "UNKNOWN",
        "The snapshot holds no episode for this order, trade, quote, OCO, combo "
        "or command id (an ambiguous prefix matches none), or no record of this "
        "symbol.",
        "No order '9f2c' in this snapshot",
    ),
    "UNKNOWN_COMPANY": ErrorCode(
        404, "UNKNOWN", "No company profile for the symbol.", "No company for XYZ"
    ),
    "UNKNOWN_GATEWAY": ErrorCode(
        404,
        "UNKNOWN",
        "No participant has this gateway id.",
        "No participant has gateway id NOPE",
    ),
    "UNKNOWN_SYMBOL": ErrorCode(
        404,
        "UNKNOWN",
        "The symbol is not in the venue's reference data.",
        "Unknown symbol XYZ",
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
    "REOPEN_REJECTED": ErrorCode(
        409,
        "UNKNOWN",
        "The engine refused the reopen (force-uncross); `message` is its reason.",
        "AAPL is not halted",
    ),
    "DISCONNECT_REJECTED": ErrorCode(
        409,
        "UNKNOWN",
        "The engine refused to disconnect the gateway; `message` is its reason.",
        "Gateway not connected: TRADER01",
    ),
    "QUERY_REJECTED": ErrorCode(
        409,
        "UNKNOWN",
        "The engine refused the admin query; `message` is its reason.",
        "Unknown symbol: XYZ",
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
    "AMBIGUOUS_RUN": ErrorCode(
        409,
        "UNKNOWN",
        "The id appears in more than one engine run of the snapshot (a restart "
        "reused it); `runs` lists them. Repeat with `run_id`.",
        "The id appears in runs 1, 2: pass run_id",
    ),
    "CAPABILITY_UNAVAILABLE": ErrorCode(
        409,
        "UNKNOWN",
        "The snapshot's evidence cannot support this analysis; `reason` is a "
        "stable code (for example `NO_EVENTS`, `NOT_IN_RELEASE`). Not an empty "
        "result.",
        "The snapshot holds no audit record",
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
    "CLEARING_DB": ErrorCode(
        503,
        "UNKNOWN",
        "The `pm-clearing` ledger is missing, locked or unreadable. Not an empty "
        "ledger: retry, or check that `pm-clearing` is deployed.",
        "Clearing ledger unavailable: not found",
    ),
    "EOD_DB": ErrorCode(
        503,
        "UNKNOWN",
        "The `pm-eod` ledger is unreadable, or its roster is malformed. A "
        "missing ledger (pm-eod has not run yet) is `eod_db_available: false`, "
        "and a day without settlement an empty list, not this.",
        "EOD ledger unavailable: file is not a database",
    ),
    "AUDIT_INDEX_UNAVAILABLE": ErrorCode(
        503,
        "UNKNOWN",
        "The `pm-audit` index is not built or not running.",
        "Audit index unavailable",
    ),
    "AUDIT_SOURCE_UNAVAILABLE": ErrorCode(
        503,
        "UNKNOWN",
        "The audit evidence a collection or snapshot reads is missing, or a "
        "retained file changed after the snapshot pinned it; `reason` is "
        "`SOURCE_MISSING` or `SOURCE_CHANGED`. Never an empty result.",
        "audit/audit-2026-06-15.log.zst was removed after the snapshot",
    ),
    "COMPANY_DB_UNAVAILABLE": ErrorCode(
        503,
        "UNKNOWN",
        "The company database is missing or unreadable.",
        "Company database unavailable",
    ),
    "NEWS_DB_UNAVAILABLE": ErrorCode(
        503,
        "UNKNOWN",
        "pm-market-sim's news history cannot be read.",
        "News history unavailable",
    ),
}
