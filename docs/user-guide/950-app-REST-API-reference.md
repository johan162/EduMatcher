# Appendix: REST API Reference

> **Status: Normative.** This appendix is the single source of truth for the
> `pm-api-gwy` REST contract as exposed under `/api/v1`. For an operational,
> tutorial-style guide see [API Gateway (REST/WebSocket)](260-api-gateway.md).
> The key words MUST, MUST NOT, SHOULD, and MAY are used per RFC 2119.

## Scope & conventions

This appendix documents the client-visible REST surface of the API gateway.
It covers request shapes, replies, query parameters, auth rules, and the
stable error codes returned by the gateway. WebSocket streams are documented
in [API Gateway (REST/WebSocket)](260-api-gateway.md) and are not repeated
here.

All paths are rooted at `/api/v1`.

## Endpoint index

### Bootstrap

| Endpoint | Access | Purpose |
|---|---|---|
| [GET /api/v1/bootstrap/trader](#get-apiv1bootstraptrader) | Any valid key | One-request startup payload for TRADER / MARKET\_MAKER / ADMIN |
| [GET /api/v1/bootstrap/mm](#get-apiv1bootstrapmm) | MARKET\_MAKER key | One-request startup payload for MARKET\_MAKER (adds quote state) |
| [GET /api/v1/bootstrap/admin](#get-apiv1bootstrapadmin) | Admin role | One-request startup payload for ADMIN |

### Trading REST

| Endpoint | Access | Purpose |
|---|---|---|
| [POST /api/v1/orders](#post-apiv1orders) | Trading key | Submit one order for the caller's gateway |
| [DELETE /api/v1/orders/{order_id}](#delete-apiv1ordersorder_id) | Trading key | Cancel one live order |
| [PATCH /api/v1/orders/{order_id}](#patch-apiv1ordersorder_id) | Trading key | Amend price and/or quantity on one live order |
| [POST /api/v1/orders/{order_id}/replace](#post-apiv1ordersorder_idreplace) | Trading key | Cancel then replace one live order |
| [GET /api/v1/orders](#get-apiv1orders) | Trading key | Return the caller gateway's live order cache |
| [GET /api/v1/orders/{order_id}](#get-apiv1ordersorder_id) | Trading key | Return one cached order |
| [POST /api/v1/oco](#post-apiv1oco) | Trading key | Submit an OCO pair |
| [DELETE /api/v1/oco/{oco_id}](#delete-apiv1ocooco_id) | Trading key | Cancel an OCO pair |
| [POST /api/v1/combos](#post-apiv1combos) | Trading key | Submit a combo order |
| [DELETE /api/v1/combos/{combo_id}](#delete-apiv1comboscombo_id) | Trading key | Cancel a combo order |
| [POST /api/v1/quotes](#post-apiv1quotes) | Trading key | Submit a two-sided market-maker quote |
| [DELETE /api/v1/quotes/{symbol}](#delete-apiv1quotessymbol) | Trading key | Cancel the active quote for one symbol |
| [POST /api/v1/mass-cancel](#post-apiv1mass-cancel) | Trading key | Cancel all resting exposure for the caller or one symbol |
| [POST /api/v1/kill-switch](#post-apiv1kill-switch) | Trading key | Alias of mass-cancel |
| [GET /api/v1/symbols](#get-apiv1symbols) | Trading key | Return instrument metadata |
| [GET /api/v1/session](#get-apiv1session) | Trading key | Return the current engine session state |
| [GET /api/v1/status](#get-apiv1status) | Trading key | Return gateway cache summary and resolved role |
| [GET /api/v1/healthz](#get-apiv1healthz) | Public | Liveness probe |
| [GET /api/v1/quotes/bootstrap](#get-apiv1quotesbootstrap) | Trading key | Return active market-maker quote bootstrap state |
| [GET /api/v1/quotes/legs](#get-apiv1quoteslegs) | Trading key | Return current quote-leg state |
| [GET /api/v1/positions](#get-apiv1positions) | Trading key | Return current net positions |

### Reference data

| Endpoint | Access | Purpose |
|---|---|---|
| [GET /api/v1/reference](#get-apiv1reference) | Authenticated key | Return the full reference bundle |
| [GET /api/v1/reference/config-version](#get-apiv1referenceconfig-version) | Authenticated key | Return the reference bundle version |
| [GET /api/v1/reference/symbols](#get-apiv1referencesymbols) | Authenticated key | Return per-symbol tick and risk metadata |
| [GET /api/v1/reference/risk](#get-apiv1referencerisk) | Authenticated key | Return risk-band definitions |
| [GET /api/v1/reference/indexes](#get-apiv1referenceindexes) | Authenticated key | Return configured exchange index definitions |
| [GET /api/v1/reference/schedule](#get-apiv1referenceschedule) | Authenticated key | Return session schedule metadata |
| [POST /api/v1/admin/reference/reload](#post-apiv1adminreferencereload) | Admin role | Reload the compiled reference bundle |

### History

| Endpoint | Access | Purpose |
|---|---|---|
| [GET /api/v1/history/orders](#get-apiv1historyorders) | Trading key | Return the caller gateway's order lifecycle events |
| [GET /api/v1/history/orders/{order_id}](#get-apiv1historyordersorder_id) | Trading key | Return the full lifecycle of one order |
| [GET /api/v1/history/fills](#get-apiv1historyfills) | Trading key | Return fill events |
| [GET /api/v1/history/trades](#get-apiv1historytrades) | Authenticated key | Return public trade tape rows |
| [GET /api/v1/history/daily](#get-apiv1historydaily) | Authenticated key | Return daily OHLCV rows |
| [GET /api/v1/history/price-snapshots](#get-apiv1historyprice-snapshots) | Authenticated key | Return intraday price snapshots |
| [GET /api/v1/history/index-daily](#get-apiv1historyindex-daily) | Authenticated key | Return daily index OHLC rows |
| [GET /api/v1/history/index-snapshots](#get-apiv1historyindex-snapshots) | Authenticated key | Return intraday index snapshots |
| [GET /api/v1/history/index-ids](#get-apiv1historyindex-ids) | Authenticated key | List index ids with recorded data |
| [GET /api/v1/history/index-events](#get-apiv1historyindex-events) | Authenticated key | Return index structural and audit events |

### Admin REST

| Endpoint | Access | Purpose |
|---|---|---|
| [POST /api/v1/admin/session/transition](#post-apiv1adminsessiontransition) | Admin role | Request a session-phase transition |
| [GET /api/v1/admin/session/schedule](#get-apiv1adminsessionschedule) | Admin role | Return current session schedule settings |
| [GET /api/v1/admin/gateways](#get-apiv1admingateways) | Admin role | List configured gateways and live connection state |
| [POST /api/v1/admin/gateways/{gid}/disconnect](#post-apiv1admingatewaysgiddisconnect) | Admin role | Forcibly disconnect one gateway |
| [POST /api/v1/admin/circuit-breaker/trigger](#post-apiv1admincircuit-breakertrigger) | Admin role | Halt one symbol through the circuit breaker |
| [POST /api/v1/admin/circuit-breaker/resume](#post-apiv1admincircuit-breakerresume) | Admin role | Resume one halted symbol |
| [GET /api/v1/admin/halts](#get-apiv1adminhalts) | Admin role | Return the current active halts table |
| [GET /api/v1/admin/risk/state](#get-apiv1adminriskstate) | Admin role | Return live per-symbol risk state |
| [GET /api/v1/admin/orders](#get-apiv1adminorders) | Admin role | Return the cross-gateway active-order table |
| [GET /api/v1/admin/orders/{order_id}](#get-apiv1adminordersorder_id) | Admin role | Return the full cross-gateway lifecycle of one order |
| [POST /api/v1/admin/kill-switch/symbol](#post-apiv1adminkill-switchsymbol) | Admin role | Cancel all resting exposure on one symbol |
| [POST /api/v1/admin/kill-switch/gateway](#post-apiv1adminkill-switchgateway) | Admin role | Cancel all resting exposure for one gateway |
| [POST /api/v1/admin/kill-switch/global](#post-apiv1adminkill-switchglobal) | Admin role | Cancel all resting exposure across every gateway and symbol |
| [GET /api/v1/admin/indexes](#get-apiv1adminindexes) | Admin role | Return index configuration for the ADMIN UI |
| [POST /api/v1/admin/indexes/{id}/rebalance](#post-apiv1adminindexesidrebalance) | Admin role | Rebalance one configured index |
| [POST /api/v1/admin/reference/reload](#post-apiv1adminreferencereload) | Admin role | Reload the compiled reference bundle in place |

### Auth and roles

- Trading and admin REST requests use `Authorization: Bearer <api_key>`.
- `gateway_id: null` credentials are read-only and may access public history
  and reference data, but not trading or admin write endpoints.
- ADMIN endpoints require a credential whose resolved engine gateway role is
  `ADMIN`.

### Key types and provisioning

This appendix uses two access labels in endpoint tables:

- `Authenticated key` (also called `Authentication key`): any configured API
  key accepted by `pm-api-gwy`. This includes both read-only and trading keys.
- `Trading key`: an authenticated key whose configured `gateway_id` is not
  `null`. This key is bound to one engine gateway identity and can submit and
  manage that gateway's orders.

How keys are specified:

- Keys are configured by operators in `engine_config.yaml` under
  `api_gateways.<INSTANCE>.credentials`.
- Each credential entry has `api_key` and `gateway_id`.
- `gateway_id: null` creates a read-only authenticated key.
- `gateway_id: <GW_ID>` creates a trading-capable key for that gateway.

Example:

```yaml
api_gateways:
  default:
    credentials:
      - api_key: key-trader-demo
        gateway_id: TRADER01
        description: Trading client for TRADER01
      - api_key: key-dashboard-demo
        gateway_id: null
        description: Read-only dashboard client
```

How to get a key:

- API keys are provisioned out-of-band by the venue/operator team.
- There is no REST endpoint in `pm-api-gwy` to self-issue or rotate keys.
- After updating credentials, restart/redeploy the API gateway instance so the
  new key set is loaded.

### Common error codes

| Code | HTTP status | Meaning |
|---|---:|---|
| `AUTH` | `401` | Missing or malformed API key |
| `ENGINE_AUTH` | `403` | Engine rejected the gateway identity |
| `READ_ONLY` | `403` | Read-only key used on a trading endpoint |
| `ROLE_DENIED` | `403` | Non-admin key used on an admin endpoint |
| `VALIDATION` | `400`, `422` | Request body or parameters failed validation |
| `RATE_LIMIT` | `429` | Per-key write limit exceeded |
| `ENGINE_TIMEOUT` | `503` | No engine reply in time |
| `STATS_DB` | `503` | `pm-stats` database not present |
| `AUDIT_INDEX_UNAVAILABLE` | `503` | `pm-audit` index not built or not running |
| `UNKNOWN_ORDER` | `404` | Order id has no audited events |
| `TRANSITION_REJECTED` | `409` | Session transition refused by the engine |
| `RELOAD_REJECTED` | `409` | Reference reload rejected |
| `REBALANCE_REJECTED` | `409` | Index rebalance rejected |
| `INDEX_TIMEOUT` | `503` | No `pm-index` reply in time |
| `INDEX_ERROR` | `502` | `pm-index` rejected the request |

### Swagger/OpenAPI documentation

The API gateway supports live API documentation through FastAPI:

- OpenAPI schema: `/openapi.json`
- Swagger UI: `/docs`

These endpoints are available when `swagger_enabled: true` in the
`api_gateways` configuration. When disabled, `/docs` and `/openapi.json` are
not exposed.

### Common reply shapes

- `202 Accepted` means the gateway accepted the request and is waiting for the
  engine or `pm-index` to confirm it.
- `200 OK` is used for read endpoints and for a few admin endpoints whose
  response is immediately authoritative.
- Pagination endpoints return `count`, `has_more`, and `next_cursor` where
  applicable; `after` is the opaque cursor input.

### Canonical error envelope

All non-2xx replies MUST use this JSON envelope shape.

| Field | Type | Required | Description |
|---|---|---|---|
| `error` | `Object` | yes | Top-level error container |
| `error.code` | `String` | yes | Stable machine-readable code (for example `VALIDATION`) |
| `error.message` | `String` | yes | Human-readable summary |
| `error.field` | `String` | no | Field name when validation pinpoints one input field |

Canonical example:

```json
{
  "error": {
    "code": "VALIDATION",
    "message": "Input should be greater than 0",
    "field": "quantity"
  }
}
```

### Pagination contract

Endpoints that support pagination use keyset cursoring with these rules:

- Clients MAY pass `after` (opaque cursor from a previous response).
- Replies include `count` and `has_more`.
- When another page exists, replies MUST include `next_cursor`.
- Clients fetch the next page by passing `after=<next_cursor>` unchanged.
- Ordering is deterministic and backend-defined per endpoint; cursors are valid
  only for the same endpoint and compatible filter set.
- A malformed, stale, or cross-endpoint cursor returns `422 VALIDATION`.

### Order correlation with `client_tag`

Order submit supports `client_tag` as an optional client-supplied correlation
tag.

- Scope: the tag is client-scoped and opaque.
- Behavior: the gateway and engine do not enforce uniqueness.
- Lifetime: when supplied, the tag is echoed on order lifecycle events and on
  cached order reads so clients can map exchange-assigned `order_id` values
  back to their own submissions.

### Category examples

The examples below are normative shape examples for each category. Values are
illustrative.

#### Trading example (`POST /api/v1/orders`)

Minimal request:

```json
{
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "LIMIT",
  "quantity": 100,
  "price": 187.25
}
```

Full request:

```json
{
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "LIMIT",
  "quantity": 100,
  "price": 187.25,
  "tif": "DAY",
  "smp_action": "CANCEL_AGGRESSOR",
  "client_tag": "desk1-aapl-00042"
}
```

Minimal response:

```json
{
  "order_id": "ORD-20260806-00042",
  "status": "PENDING"
}
```

Full response:

```json
{
  "order_id": "ORD-20260806-00042",
  "client_tag": "desk1-aapl-00042",
  "status": "ACKED",
  "accepted": true,
  "event": {
    "order_id": "ORD-20260806-00042",
    "accepted": true,
    "gateway_id": "G1"
  }
}
```

#### Reference data example (`GET /api/v1/reference`)

Minimal response:

```json
{
  "symbols": [],
  "risk": {},
  "indexes": [],
  "schedule": {},
  "config_version": "sha256:..."
}
```

Full response:

```json
{
  "symbols": [
    {
      "symbol": "AAPL",
      "tick_decimals": 2,
      "level": "L1"
    }
  ],
  "risk": {
    "default_level": "L1",
    "levels": {
      "L1": {
        "soft_pct": 5.0,
        "hard_pct": 10.0
      }
    }
  },
  "indexes": [
    {
      "id": "TECH10",
      "description": "Tech sample index"
    }
  ],
  "schedule": {
    "sessions_enabled": true,
    "country": "US"
  },
  "config_version": "sha256:6d8d..."
}
```

#### History example (`GET /api/v1/history/trades`)

Minimal response:

```json
{
  "trades": [],
  "count": 0,
  "has_more": false
}
```

Full response:

```json
{
  "trades": [
    {
      "symbol": "AAPL",
      "price": 187.3,
      "quantity": 50,
      "ts": "2026-08-06T09:30:00Z"
    }
  ],
  "count": 1,
  "has_more": true,
  "next_cursor": "eyJhZnRlciI6Ii4uLiJ9"
}
```

#### Admin example (`POST /api/v1/admin/session/transition`)

Minimal request:

```json
{
  "to_state": "CONTINUOUS"
}
```

Full request:

```json
{
  "to_state": "CONTINUOUS"
}
```

Minimal response:

```json
{
  "requested_state": "CONTINUOUS",
  "status": "APPLIED",
  "command_id": "c_01K17P..."
}
```

Full response:

```json
{
  "requested_state": "CONTINUOUS",
  "status": "APPLIED",
  "command_id": "c_01K17P9B7C6W9X0Y8Z7"
}
```

### Compatibility and deprecation policy

- Versioning: this surface is namespaced under `/api/v1`.
- Backward compatibility: additive changes (new optional fields/endpoints) MAY
  be introduced within v1 without changing the base path.
- Breaking changes (field removal, required-field additions, semantic
  redefinition) MUST ship under a new versioned base path.
- Deprecation: deprecated fields/endpoints SHOULD be documented with migration
  guidance before removal in a later major API version.

## Bootstrap

Bootstrap endpoints return a single composed response that a browser client
can fetch immediately after authenticating, replacing the 6–13 sequential
round-trips the current login flow requires.  Sub-queries inside each handler
run in parallel using `asyncio.gather`.

Each response includes an `incomplete` array.  When a field is listed there
its value is `null`; the rest of the response is still usable.  Required
fields (marked below) return `503 ENGINE_TIMEOUT` on failure — the response
would be too incomplete to be useful without them.

---

### `GET /api/v1/bootstrap/trader`

Purpose: one-request startup payload for TRADER, MARKET\_MAKER, and ADMIN
sessions.  Returns identity, full reference data, live session state,
positions, active orders, today's recent fills, and capability flags.

**Access:** any valid key (read-only keys receive `gateway_role: "READ_ONLY"`,
empty `positions`, and empty `orders`).

**Query parameters**

| Name | Type | Default | Constraints | Description |
|---|---|---|---|---|
| `fills_limit` | `int` | `50` | `1..500` | Maximum number of today's fill events to include in `recent_fills` |

**Reply `200 OK`**

```jsonc
{
  "ts": "2026-07-27T09:30:01.123Z",
  "incomplete": [],               // field names that timed out (values are null)

  "gateway_id": "TRADER01",       // null for read-only keys
  "gateway_role": "TRADER",       // TRADER | MARKET_MAKER | ADMIN | READ_ONLY

  // identical to GET /reference
  "reference": {
    "symbols": [ { "symbol": "AAPL", "tick_decimals": 2, ... } ],
    "risk":     { "default_level": "L2", "levels": { ... } },
    "schedule": { "sessions_enabled": true, "country": "Sweden", "schedule": { ... } },
    "config_version": "7f3a2c1"
  },

  // identical to GET /session; null if engine timed out (optional)
  "session": { "state": "CONTINUOUS", "since": "2026-07-27T09:30:00.000Z" },

  // identical to GET /positions (pure cache, never null)
  "positions": [ { "symbol": "AAPL", "net_qty": 200, "last_price": 210.25 } ],

  // identical to GET /orders response body (required — 503 on failure)
  "orders": { "orders": [ /* Order[] */ ] },

  // today's fills, limited to fills_limit; null if stats DB absent (optional)
  "recent_fills": { "events": [ /* Fill[] */ ], "count": 12 },

  // capability flags — assembled from config, never null
  "capabilities": {
    "sessions_enabled": true,    // from reference.schedule.sessions_enabled
    "stats_db_available": true,  // false → history unavailable
    "audit_db_available": false, // false → order lifecycle drill-down unavailable
    "index_available": false     // false → index tab unavailable
  }
}
```

**Required fields** (return `503 ENGINE_TIMEOUT` if they fail):
`reference`, `orders` (omitted for read-only keys).

**Optional fields** (appear as `null` + listed in `incomplete` on failure):
`session`, `recent_fills`.

**Errors**

| Code | Status | When |
|---|---|---|
| `AUTH` | `401` | Missing or malformed key |
| `ENGINE_TIMEOUT` | `503` | `reference` or `orders` could not be fetched |
| `VALIDATION` | `422` | `fills_limit` is not a valid integer |

---

### `GET /api/v1/bootstrap/mm`

Purpose: one-request startup payload for MARKET\_MAKER sessions.  Superset of
`/bootstrap/trader` — adds active quote bootstrap state and quote legs.

**Access:** MARKET\_MAKER key only.  TRADER and ADMIN keys receive `403`.

**Query parameters:** same as `/bootstrap/trader` (`fills_limit`).

**Reply `200 OK`**

All fields from `/bootstrap/trader`, plus:

```jsonc
{
  // ...trader fields...
  "gateway_role": "MARKET_MAKER",

  // identical to GET /quotes/bootstrap; null if engine timed out (optional)
  "quote_bootstrap": { "quotes": [ /* ActiveQuote[] */ ] },

  // identical to GET /quotes/legs; null if engine timed out (optional)
  "quote_legs": { "legs": [ /* QuoteLeg[] */ ] }
}
```

**Required fields:** `reference`, `orders`.

**Optional fields:** `session`, `recent_fills`, `quote_bootstrap`, `quote_legs`.

**Errors**

| Code | Status | When |
|---|---|---|
| `AUTH` | `401` | Missing or malformed key |
| `READ_ONLY` | `403` | Read-only key (no gateway\_id) |
| `ROLE_DENIED` | `403` | Key resolves to TRADER or ADMIN role |
| `ENGINE_TIMEOUT` | `503` | `reference` or `orders` could not be fetched |
| `VALIDATION` | `422` | `fills_limit` is not a valid integer |

---

### `GET /api/v1/bootstrap/admin`

Purpose: one-request startup payload for ADMIN sessions.  Returns reference
data, session state, the full gateway roster, active halts, per-gateway
active-order counts, per-gateway drop-copy sequence numbers, and capability
flags.

**Access:** ADMIN role required.  TRADER and MARKET\_MAKER keys receive `403`.

**No query parameters.**

**Reply `200 OK`**

```jsonc
{
  "ts": "2026-07-27T09:30:01.250Z",
  "incomplete": [],

  "gateway_id": "INSTRUCTOR",
  "gateway_role": "ADMIN",

  // identical to GET /reference (required — 503 on failure)
  "reference": { /* symbols, risk, schedule, config_version */ },

  // identical to GET /session; null if engine timed out (optional)
  "session": { "state": "CONTINUOUS", "since": "..." },

  // identical to GET /admin/gateways response body; null if engine timed out (optional)
  "gateways": {
    "gateways": [
      { "gateway_id": "TRADER01", "role": "TRADER", "description": "...", "connected": true }
    ]
  },

  // identical to GET /admin/halts response body; null if engine timed out (optional)
  "halts": { "halted": [ { "symbol": "AAPL", "level": "L2", ... } ] },

  // per-gateway active (non-terminal) order count — pure cache, never null
  "active_order_counts": { "TRADER01": 3, "MM01": 12 },

  // per-gateway highest drop-copy stream_seq seen — pure cache, never null
  "monitor_last_seq": { "TRADER01": 100482, "MM01": 88213 },

  "capabilities": {
    "sessions_enabled": true,
    "stats_db_available": true,
    "audit_db_available": false,
    "index_available": false
  }
}
```

**Required fields:** `reference`.

**Optional fields:** `session`, `gateways`, `halts`.
The `gateways` and `halts` fields are also supplied by the `monitor.snapshot`
frame that the `WS /api/v1/admin/monitor` socket sends immediately after auth
— a partial bootstrap response is therefore recoverable without a manual retry.

**Errors**

| Code | Status | When |
|---|---|---|
| `AUTH` | `401` | Missing or malformed key |
| `ROLE_DENIED` | `403` | Key is not ADMIN |
| `ENGINE_TIMEOUT` | `503` | `reference` could not be fetched |

---

## Trading REST

### `POST /api/v1/orders`

Purpose: submit one order for the caller's gateway.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | yes | Instrument symbol |
| `side` | `Side` | yes | `BUY` or `SELL` |
| `order_type` | `OrderType` | yes | `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `FOK`, `ICEBERG`, `IOC`, or `TRAILING_STOP` |
| `quantity` | `Int` | yes | Positive order quantity |
| `tif` | `Tif` | no | Time-in-force; defaults to `DAY` |
| `price` | `Price` | conditional | Required for limit-style orders |
| `stop_price` | `Price` | conditional | Required for stop-style orders |
| `visible_qty` | `Qty` | conditional | Required for iceberg orders |
| `trail_offset` | `Ticks` | conditional | Required for trailing-stop orders |
| `smp_action` | `SmpAction` | no | Self-match prevention action |
| `client_tag` | `Str` | no | Optional opaque client correlation tag |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | `{"order_id": "...", "status": "PENDING"}` | Default immediate reply |
| `200 OK` | `{"order_id": "...", "status": "ACKED", "accepted": false, "reject_code": "COLLAR_BREACH", "reason": "collar breach"}` | Returned when `?wait=ack` waits for the matching ACK; rejected ACKs include a stable machine-readable `reject_code` and the human-readable `reason` |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `ROLE_DENIED` | ADMIN-only restriction violated |
| `VALIDATION` | Body does not match the order type |
| `RATE_LIMIT` | Write limit exceeded |
| `ENGINE_TIMEOUT` | Engine did not ACK in time |

### `DELETE /api/v1/orders/{order_id}`

Purpose: cancel one live order in the caller's gateway.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `order_id` | `Str` | yes (path) | Order to cancel |
| `wait` | `Bool` | no | `?wait=ack` waits for `order.cancelled.*` |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | `{"order_id": "...", "status": "PENDING"}` | Request accepted |
| `200 OK` | cancel ACK payload | Returned when waiting for the ACK |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `VALIDATION` | Bad path or query |
| `ENGINE_TIMEOUT` | Engine did not ACK in time |

### `PATCH /api/v1/orders/{order_id}`

Purpose: amend price and/or quantity on one live order.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `order_id` | `Str` | yes (path) | Order to amend |
| `price` | `Price` | conditional | New order price |
| `quantity` | `Qty` | conditional | New order quantity |
| `wait` | `Bool` | no | `?wait=ack` waits for `order.amended.*` |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | `{"order_id": "...", "status": "PENDING"}` | Request accepted |
| `200 OK` | amend ACK payload | Returned when waiting for the ACK |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `VALIDATION` | Neither or both fields invalid |
| `ENGINE_TIMEOUT` | Engine did not ACK in time |

### `POST /api/v1/orders/{order_id}/replace`

Purpose: cancel one live order and submit a replacement in one workflow.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `order_id` | `Str` | yes (path) | Order to replace |
| body | `Order` fields | yes | Same shape as `POST /orders` |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | cancel ACK then replacement ACK | Synchronous cancel-then-submit workflow |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `VALIDATION` | Replacement body invalid |
| `ENGINE_TIMEOUT` | Cancel or submit timed out |

### `GET /api/v1/orders`

Purpose: return the caller gateway's live order cache.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | no | Filter by symbol |
| `status` | `OrderStatus` | no | Filter by order status |
| `after` | `Cursor` | no | Opaque page cursor |
| `limit` | `Int` | no | Page size, bounded by the gateway |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "orders": [...], "count": N, "has_more": bool, "next_cursor": str? }` | Current live orders |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `VALIDATION` | Query parameters invalid |
| `ENGINE_TIMEOUT` | Fresh snapshot request to the engine timed out |

### `GET /api/v1/orders/{order_id}`

Purpose: return one cached order from the caller gateway.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `order_id` | `Str` | yes (path) | Order to fetch |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | cached order object | Current order state |
| `404 Not Found` | error envelope | Order id not in cache |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `UNKNOWN_ORDER` | Order id unknown to the cache |

### `POST /api/v1/oco`

Purpose: submit an OCO pair.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `oco_id` | `Str` | yes | Group id for the pair |
| `symbol` | `Symbol` | yes | Instrument symbol |
| `quantity` | `Qty` | yes | Total quantity |
| `leg1` | `OrderLeg` | yes | First leg definition |
| `leg2` | `OrderLeg` | yes | Second leg definition |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | ack payload | OCO accepted for processing |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `VALIDATION` | Body invalid |
| `ENGINE_TIMEOUT` | Engine did not ACK in time |

### `DELETE /api/v1/oco/{oco_id}`

Purpose: cancel an OCO pair.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `oco_id` | `Str` | yes (path) | OCO group to cancel |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | cancel ack payload | OCO cancel accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `ENGINE_TIMEOUT` | Cancel timed out |

### `POST /api/v1/combos`

Purpose: submit a combo order.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `combo_id` | `Str` | yes | Combo group id |
| `legs` | `List<ComboLeg>` | yes | Leg list |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | ack payload | Combo accepted for processing |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `VALIDATION` | Body invalid |
| `ENGINE_TIMEOUT` | Engine did not ACK in time |

### `DELETE /api/v1/combos/{combo_id}`

Purpose: cancel a combo order.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `combo_id` | `Str` | yes (path) | Combo group to cancel |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | cancel ack payload | Combo cancel accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `ENGINE_TIMEOUT` | Cancel timed out |

### `POST /api/v1/quotes`

Purpose: submit a two-sided market-maker quote.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | yes | Quoted instrument |
| `bid_price` | `Price` | yes | Bid price |
| `bid_qty` | `Qty` | yes | Bid quantity |
| `ask_price` | `Price` | yes | Ask price |
| `ask_qty` | `Qty` | yes | Ask quantity |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | quote ack payload | Quote accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `VALIDATION` | Quote body invalid |
| `ENGINE_TIMEOUT` | Quote ACK timed out |

### `DELETE /api/v1/quotes/{symbol}`

Purpose: cancel the active quote for one symbol.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | yes (path) | Quoted instrument |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | cancel ack payload | Quote cancel accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `ENGINE_TIMEOUT` | Cancel timed out |

### `POST /api/v1/mass-cancel`

Purpose: cancel all resting exposure for the caller or one symbol.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | no | Restrict the cancel to one symbol |
| `reason` | `Str` | no | Free-text note carried to monitor events |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | ack payload | Cancel request accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `ENGINE_TIMEOUT` | Engine did not ACK in time |

### `POST /api/v1/kill-switch`

Purpose: alias of `POST /api/v1/mass-cancel`.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | no | Optional symbol-scoped kill |
| `reason` | `Str` | no | Free-text note |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | ack payload | Same behavior as `/mass-cancel` |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `ENGINE_TIMEOUT` | Engine did not ACK in time |

### `GET /api/v1/symbols`

Purpose: return instrument metadata for the caller gateway.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "symbols": [...] }` | Current symbol metadata |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/session`

Purpose: return the current engine session state for the caller.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | session state object | Current session state |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/status`

Purpose: return the gateway cache summary and resolved role.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | status object | Cache summary, resolved role, and for ADMIN keys `gateway_count` |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |

### `GET /api/v1/healthz`

Purpose: liveness probe for the API gateway.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No auth required |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | health object | Gateway is enabled and its engine listener is alive |

**Errors**

| Code | When |
|---|---|
| none | — | This endpoint does not require auth |

### `GET /api/v1/quotes/bootstrap`

Purpose: return the active market-maker quote bootstrap state.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | quote bootstrap object | Current quote bootstrap state |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/quotes/legs`

Purpose: return the current quote-leg state for the caller.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "legs": [...] }` | Current quote legs |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/positions`

Purpose: return current net positions by symbol.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "positions": [...] }` | Net positions for the caller gateway |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

## Reference data

Base path: `/api/v1/reference`. These endpoints expose compiled reference data
that changes only when an admin reloads it.

### `GET /api/v1/reference`

Purpose: return the full reference bundle in one round-trip.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "symbols", "risk", "indexes", "schedule", "config_version" }` | Full resolved reference bundle |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/reference/config-version`

Purpose: return the content-hash version of the reference bundle.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "config_version": "..." }` | Opaque bundle version hash |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/reference/symbols`

Purpose: return per-symbol tick and risk metadata.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "symbols": [...], "config_version": "..." }` | One object per symbol (each carries its own `symbol`) |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/reference/risk`

Purpose: return risk-band definitions and the default risk level.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "default_level", "levels", "config_version" }` | Risk-band configuration |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/reference/indexes`

Purpose: return configured exchange index definitions.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "indexes": [...], "config_version": "..." }` | Static index definitions |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/reference/schedule`

Purpose: return session schedule metadata.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | schedule object | `sessions_enabled`, `country`, and session transition times |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `POST /api/v1/admin/reference/reload`

Purpose: reload the compiled reference bundle without restarting the engine.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No request body |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "status": "RELOADED", "config_version": "..." }` | Reference bundle reloaded successfully |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `RELOAD_REJECTED` | Reload would change the symbol or index set |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

## History

Base path: `/api/v1/history`. Trading endpoints are scoped to the caller's
gateway id; public history accepts any valid key.

### `GET /api/v1/history/orders`

Purpose: return the caller gateway's order lifecycle events.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | no | Filter by symbol |
| `event_type` | `Str` | no | Filter by event type |
| `date` | `Date` | no | Single trading date |
| `from` | `DateTime` | no | Range start |
| `to` | `DateTime` | no | Range end |
| `limit` | `Int` | no | Page size |
| `after` | `Cursor` | no | Opaque page cursor |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | paginated list envelope | Order lifecycle events for the caller gateway |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `STATS_DB` | `pm-stats` database missing |
| `VALIDATION` | Query invalid |

### `GET /api/v1/history/orders/{order_id}`

Purpose: return the full lifecycle of one order for the caller gateway.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `order_id` | `Str` | yes (path) | Order to fetch |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "order_id", "count", "events" }` | Full lifecycle for one order |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `STATS_DB` | `pm-stats` database missing |
| `VALIDATION` | Path invalid |

### `GET /api/v1/history/fills`

Purpose: return fill events for the caller gateway.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | no | Filter by symbol |
| `date` | `Date` | no | Trading date |
| `from` | `DateTime` | no | Range start |
| `to` | `DateTime` | no | Range end |
| `limit` | `Int` | no | Page size |
| `after` | `Cursor` | no | Opaque page cursor |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | paginated list envelope | Fill history for the caller gateway |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `STATS_DB` | `pm-stats` database missing |

### `GET /api/v1/history/trades`

Purpose: return public trade tape rows.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | no | Filter by symbol |
| `date` | `Date` | no | Trading date |
| `from` | `DateTime` | no | Range start |
| `to` | `DateTime` | no | Range end |
| `limit` | `Int` | no | Page size |
| `after` | `Cursor` | no | Opaque page cursor |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | paginated list envelope | Public trade rows |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `STATS_DB` | `pm-stats` database missing |

### `GET /api/v1/history/daily`

Purpose: return daily OHLCV rows.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | no | Filter by symbol |
| `date` | `Date` | no | Single trading day |
| `from` | `Date` | no | Range start |
| `to` | `Date` | no | Range end |
| `limit` | `Int` | no | Page size |
| `after` | `Cursor` | no | Opaque page cursor |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | paginated list envelope | Daily OHLCV rows |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `STATS_DB` | `pm-stats` database missing |

### `GET /api/v1/history/price-snapshots`

Purpose: return intraday price snapshots.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | yes | Instrument symbol |
| `date` | `Date` | no | Trading day |
| `from` | `DateTime` | no | Range start |
| `to` | `DateTime` | no | Range end |
| `limit` | `Int` | no | Page size |
| `after` | `Cursor` | no | Opaque page cursor |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | paginated list envelope | Intraday mid/bid/ask series |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `STATS_DB` | `pm-stats` database missing |

### `GET /api/v1/history/index-daily`

Purpose: return daily index OHLC rows.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `index_id` | `IndexId` | no | Index id |
| `date` | `Date` | no | Single trading day |
| `from` | `Date` | no | Range start |
| `to` | `Date` | no | Range end |
| `limit` | `Int` | no | Page size |
| `after` | `Cursor` | no | Opaque page cursor |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | paginated list envelope | Daily index rows |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `STATS_DB` | `pm-stats` database missing |

### `GET /api/v1/history/index-snapshots`

Purpose: return intraday index snapshots.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `index_id` | `IndexId` | yes | Index id |
| `date` | `Date` | no | Trading day |
| `from` | `DateTime` | no | Range start |
| `to` | `DateTime` | no | Range end |
| `limit` | `Int` | no | Page size |
| `after` | `Cursor` | no | Opaque page cursor |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | paginated list envelope | Intraday index series |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `STATS_DB` | `pm-stats` database missing |

### `GET /api/v1/history/index-ids`

Purpose: list index ids with recorded data.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `date` | `Date` | no | Filter by trading day |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "index_ids": [...], "count": N }` | Index ids with data |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `STATS_DB` | `pm-stats` database missing |

### `GET /api/v1/history/index-events`

Purpose: return index structural and audit events from `pm-index`.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `index_id` | `IndexId` | yes | Index id |
| `from` | `Secs` | no | Unix time start |
| `to` | `Secs` | no | Unix time end |
| `types` | `Str` | no | Repeatable event-type filter |
| `max_records` | `Int` | no | Reply cap |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "events": [...], "count": N }` | Structural audit log |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `INDEX_TIMEOUT` | `pm-index` did not reply in time |
| `INDEX_ERROR` | `pm-index` rejected the request |

## Admin REST

Base path: `/api/v1/admin`. ADMIN role required.

### `POST /api/v1/admin/session/transition`

Purpose: request a session-phase transition from the engine.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `to_state` | `SessionState` | yes | Requested session phase |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | `{"requested_state": "...", "status": "APPLIED", "command_id": "..."}` | Transition request accepted and applied |
| `409 Conflict` | error envelope | The engine refused the transition |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `VALIDATION` | Invalid `to_state` |
| `TRANSITION_REJECTED` | Engine rejected the transition |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/admin/session/schedule`

Purpose: return the current session schedule settings.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | schedule object | Current schedule and session enablement |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/admin/gateways`

Purpose: list configured gateways and live connection state.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "gateways": [...] }` | Gateway roster and connection status |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `POST /api/v1/admin/gateways/{gid}/disconnect`

Purpose: forcibly disconnect one gateway.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `gid` | `GatewayId` | yes (path) | Gateway to disconnect |
| `reason` | `Str` | no | Optional note |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | `{ "gateway_id": "...", "status": "DISCONNECTED" }` | Gateway disconnect accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `POST /api/v1/admin/circuit-breaker/trigger`

Purpose: halt one symbol through the engine's circuit-breaker path.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | yes | Symbol to halt |
| `level` | `Str` | yes | Requested level name |
| `reason` | `Str` | no | Optional note |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | ack payload | Halt accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `VALIDATION` | Symbol or level invalid |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `POST /api/v1/admin/circuit-breaker/resume`

Purpose: resume one halted symbol.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | yes | Symbol to resume |
| `reason` | `Str` | no | Optional note |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | ack payload | Resume accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/admin/halts`

Purpose: return the current active halts table.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "halted": [...] }` | Currently-halted symbols; each `{ symbol, resume_at_ns?, level?, halt_source? }` |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/admin/risk/state`

Purpose: return live per-symbol risk state.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "symbols": [...] }` | Current collar and circuit-breaker state (one object per symbol) |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/admin/orders`

Purpose: return the cross-gateway active-order table.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | no | Filter by symbol |
| `gateway_id` | `GatewayId` | no | Filter by gateway |
| `status` | `OrderStatus` | no | Filter by status |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "count": N, "orders": [...], "retention_sec": N }` | Current cross-gateway active orders |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |

### `GET /api/v1/admin/orders/{order_id}`

Purpose: return the full cross-gateway lifecycle of one order.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `order_id` | `Str` | yes (path) | Order to fetch |
| `limit` | `Int` | no | Maximum number of events |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "order_id", "count", "events" }` | Full audited lifecycle |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `AUDIT_INDEX_UNAVAILABLE` | No audit index available |
| `UNKNOWN_ORDER` | No audited events for the order |

### `POST /api/v1/admin/kill-switch/symbol`

Purpose: cancel all resting exposure on one symbol.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `symbol` | `Symbol` | yes | Symbol to cancel |
| `reason` | `Str` | no | Optional note |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | ack payload | Symbol kill-switch accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `POST /api/v1/admin/kill-switch/gateway`

Purpose: cancel all resting exposure for one target gateway.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `target_gateway_id` | `GatewayId` | yes | Gateway to cancel |
| `reason` | `Str` | no | Optional note |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | ack payload | Gateway kill-switch accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `POST /api/v1/admin/kill-switch/global`

Purpose: cancel all resting exposure across every gateway and symbol.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `reason` | `Str` | no | Optional note |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | ack payload | Global kill-switch accepted |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

### `GET /api/v1/admin/indexes`

Purpose: return index configuration for the ADMIN UI.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No query parameters |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "indexes": [...], "config_version": "..." }` | Static index definitions |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |

### `POST /api/v1/admin/indexes/{id}/rebalance`

Purpose: rebalance one configured index through `pm-index`.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| `id` | `IndexId` | yes (path) | Index to rebalance |
| `updates` | `List<RebalanceUpdate>` | yes | Shares-outstanding updates |
| `reason` | `Str` | no | Optional note |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | rebalance ack | Update accepted and applied |
| `409 Conflict` | error envelope | Rebalance rejected |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `VALIDATION` | Batch body invalid |
| `REBALANCE_REJECTED` | `pm-index` rejected the request |
| `INDEX_TIMEOUT` | `pm-index` did not reply in time |
| `INDEX_ERROR` | `pm-index` returned an error |

### `POST /api/v1/admin/reference/reload`

Purpose: reload the compiled reference bundle in place.

**Arguments**

| Name | Type | Req | Description |
|---|---|---|---|
| none | — | — | No request body |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `200 OK` | `{ "status": "RELOADED", "config_version": "..." }` | Reference bundle reloaded |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `ROLE_DENIED` | Caller is not ADMIN |
| `RELOAD_REJECTED` | Reload would change the symbol or index set |
| `ENGINE_TIMEOUT` | Engine did not reply in time |

## Operational notes

- Read-only dashboard keys can call reference and public history endpoints,
  but not trading or admin write endpoints.
- `order_retention_sec` bounds the live order cache, the private
  `orders.snapshot` frame, and `GET /api/v1/admin/orders`.
- `market_data_cache_sec` bounds the market-data stream cache that backs the
  snapshot-on-subscribe, `snapshot`, and `resume` controls on
  `WS /api/v1/market-data` (latest `book`/`depth`/`auction` snapshots are kept
  regardless of age; only the `trades` tail is bounded).
- WebSocket streams use the chapter-level contracts in
  [API Gateway (REST/WebSocket)](260-api-gateway.md); this appendix is REST
  only.
