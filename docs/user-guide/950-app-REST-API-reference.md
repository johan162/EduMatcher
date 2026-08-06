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

### Trading REST

| Endpoint | Purpose |
|---|---|
| [POST /api/v1/orders](#21-post-apiv1orders) | Submit one order for the caller's gateway |
| [DELETE /api/v1/orders/{order_id}](#22-delete-apiv1ordersorder_id) | Cancel one live order |
| [PATCH /api/v1/orders/{order_id}](#23-patch-apiv1ordersorder_id) | Amend price and/or quantity on one live order |
| [POST /api/v1/orders/{order_id}/replace](#24-post-apiv1ordersorder_idreplace) | Cancel then replace one live order |
| [GET /api/v1/orders](#25-get-apiv1orders) | Return the caller gateway's live order cache |
| [GET /api/v1/orders/{order_id}](#26-get-apiv1ordersorder_id) | Return one cached order |
| [POST /api/v1/oco](#27-post-apiv1oco) | Submit an OCO pair |
| [DELETE /api/v1/oco/{oco_id}](#28-delete-apiv1ocooco_id) | Cancel an OCO pair |
| [POST /api/v1/combos](#29-post-apiv1combos) | Submit a combo order |
| [DELETE /api/v1/combos/{combo_id}](#210-delete-apiv1comboscombo_id) | Cancel a combo order |
| [POST /api/v1/quotes](#211-post-apiv1quotes) | Submit a two-sided market-maker quote |
| [DELETE /api/v1/quotes/{symbol}](#212-delete-apiv1quotessymbol) | Cancel the active quote for one symbol |
| [POST /api/v1/mass-cancel](#213-post-apiv1mass-cancel) | Cancel all resting exposure for the caller or one symbol |
| [POST /api/v1/kill-switch](#214-post-apiv1kill-switch) | Alias of mass-cancel |
| [GET /api/v1/symbols](#215-get-apiv1symbols) | Return instrument metadata |
| [GET /api/v1/session](#216-get-apiv1session) | Return the current engine session state |
| [GET /api/v1/status](#217-get-apiv1status) | Return gateway cache summary and resolved role |
| [GET /api/v1/healthz](#218-get-apiv1healthz) | Liveness probe |
| [GET /api/v1/quotes/bootstrap](#219-get-apiv1quotesbootstrap) | Return active market-maker quote bootstrap state |
| [GET /api/v1/quotes/legs](#220-get-apiv1quoteslegs) | Return current quote-leg state |
| [GET /api/v1/positions](#221-get-apiv1positions) | Return current net positions |

### Reference data

| Endpoint | Purpose |
|---|---|
| [GET /api/v1/reference](#31-get-apiv1reference) | Return the full reference bundle |
| [GET /api/v1/reference/config-version](#32-get-apiv1referenceconfig-version) | Return the reference bundle version |
| [GET /api/v1/reference/symbols](#33-get-apiv1referencesymbols) | Return per-symbol tick and risk metadata |
| [GET /api/v1/reference/risk](#34-get-apiv1referencerisk) | Return risk-band definitions |
| [GET /api/v1/reference/indexes](#35-get-apiv1referenceindexes) | Return configured exchange index definitions |
| [GET /api/v1/reference/schedule](#36-get-apiv1referenceschedule) | Return session schedule metadata |
| [POST /api/v1/admin/reference/reload](#37-post-apiv1adminreferencereload) | Reload the compiled reference bundle |

### History

| Endpoint | Purpose |
|---|---|
| [GET /api/v1/history/orders](#41-get-apiv1historyorders) | Return the caller gateway's order lifecycle events |
| [GET /api/v1/history/orders/{order_id}](#42-get-apiv1historyordersorder_id) | Return the full lifecycle of one order |
| [GET /api/v1/history/fills](#43-get-apiv1historyfills) | Return fill events |
| [GET /api/v1/history/trades](#44-get-apiv1historytrades) | Return public trade tape rows |
| [GET /api/v1/history/daily](#45-get-apiv1historydaily) | Return daily OHLCV rows |
| [GET /api/v1/history/price-snapshots](#46-get-apiv1historyprice-snapshots) | Return intraday price snapshots |
| [GET /api/v1/history/index-daily](#47-get-apiv1historyindex-daily) | Return daily index OHLC rows |
| [GET /api/v1/history/index-snapshots](#48-get-apiv1historyindex-snapshots) | Return intraday index snapshots |
| [GET /api/v1/history/index-ids](#49-get-apiv1historyindex-ids) | List index ids with recorded data |
| [GET /api/v1/history/index-events](#410-get-apiv1historyindex-events) | Return index structural and audit events |

### Admin REST

| Endpoint | Purpose |
|---|---|
| [POST /api/v1/admin/session/transition](#51-post-apiv1adminsessiontransition) | Request a session-phase transition |
| [GET /api/v1/admin/session/schedule](#52-get-apiv1adminsessionschedule) | Return current session schedule settings |
| [GET /api/v1/admin/gateways](#53-get-apiv1admingateways) | List configured gateways and live connection state |
| [POST /api/v1/admin/gateways/{gid}/disconnect](#54-post-apiv1admingatewaysgiddisconnect) | Forcibly disconnect one gateway |
| [POST /api/v1/admin/circuit-breaker/trigger](#55-post-apiv1admincircuit-breakertrigger) | Halt one symbol through the circuit breaker |
| [POST /api/v1/admin/circuit-breaker/resume](#56-post-apiv1admincircuit-breakerresume) | Resume one halted symbol |
| [GET /api/v1/admin/halts](#57-get-apiv1adminhalts) | Return the current active halts table |
| [GET /api/v1/admin/risk/state](#58-get-apiv1adminriskstate) | Return live per-symbol risk state |
| [GET /api/v1/admin/orders](#59-get-apiv1adminorders) | Return the cross-gateway active-order table |
| [GET /api/v1/admin/orders/{order_id}](#510-get-apiv1adminordersorder_id) | Return the full cross-gateway lifecycle of one order |
| [POST /api/v1/admin/kill-switch/symbol](#511-post-apiv1adminkill-switchsymbol) | Cancel all resting exposure on one symbol |
| [POST /api/v1/admin/kill-switch/gateway](#512-post-apiv1adminkill-switchgateway) | Cancel all resting exposure for one gateway |
| [POST /api/v1/admin/kill-switch/global](#513-post-apiv1adminkill-switchglobal) | Cancel all resting exposure across every gateway and symbol |
| [GET /api/v1/admin/indexes](#514-get-apiv1adminindexes) | Return index configuration for the ADMIN UI |
| [POST /api/v1/admin/indexes/{id}/rebalance](#515-post-apiv1adminindexesidrebalance) | Rebalance one configured index |
| [POST /api/v1/admin/reference/reload](#516-post-apiv1adminreferencereload) | Reload the compiled reference bundle in place |

### Auth and roles

- Trading and admin REST requests use `Authorization: Bearer <api_key>`.
- `gateway_id: null` credentials are read-only and may access public history
  and reference data, but not trading or admin write endpoints.
- ADMIN endpoints require a credential whose resolved engine gateway role is
  `ADMIN`.

### Common error codes

| Code | HTTP status | Meaning |
|---|---:|---|
| `AUTH` | `401` | Missing or malformed API key |
| `ENGINE_AUTH` | `403` | Engine rejected the gateway identity |
| `READ_ONLY` | `403` | Read-only key used on a trading endpoint |
| `ROLE_DENIED` | `403` | Non-admin key used on an admin endpoint |
| `VALIDATION` | `400`, `422` | Request body or parameters failed validation |
| `DUPLICATE` | `409` | `client_order_id` already active |
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
| `client_order_id` | `Str` | no | Optional idempotency key in the session cache |

**Reply**

| Status | Shape | Meaning |
|---|---|---|
| `202 Accepted` | `{"order_id": "...", "status": "PENDING"}` | Default immediate reply |
| `200 OK` | engine ACK payload | Returned when `?wait=ack` waits for the matching ACK |
| `409 Conflict` | error envelope | `client_order_id` already active |

**Errors**

| Code | When |
|---|---|
| `AUTH` | Missing or malformed key |
| `READ_ONLY` | Read-only credential used |
| `ROLE_DENIED` | ADMIN-only restriction violated |
| `VALIDATION` | Body does not match the order type |
| `DUPLICATE` | `client_order_id` already active |
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
| `200 OK` | `{ "symbols": {...}, "config_version": "..." }` | Symbol metadata keyed by symbol |

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
| `200 OK` | `{ "halts": [...] }` | Active halts for the venue |

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
| `200 OK` | `{ "symbols": {...} }` | Current collar and circuit-breaker state |

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
- WebSocket streams use the chapter-level contracts in
  [API Gateway (REST/WebSocket)](260-api-gateway.md); this appendix is REST
  only.
