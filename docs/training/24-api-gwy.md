# API Gateway REST/WebSocket Training

## Objective

Train on configuring and using `pm-api-gwy` for REST order entry, reference-data
and history queries, admin operations, Swagger/OpenAPI exploration, WebSocket
event handling, and multi-process logical separation.

You will practice:

- generating `api_gateways` config with bearer credentials
- starting a named API gateway process
- using REST endpoints with trading and read-only keys
- querying reference data and order/trade history over REST
- exercising admin REST endpoints with a resolved `ADMIN` role
- receiving private and market-data events over WebSocket
- splitting API gateway processes by ALF `gateway_id`

 

## Prerequisites

- Chapters 01-23 completed.
- Engine and stats commands available from the current environment.
- REST examples available in `docs/examples/REST`.
- A terminal for `pm-engine`, one for `pm-stats`, one for `pm-api-gwy`, and one or more client terminals.
- Optional: `pm-audit` running, if you want to see a populated reply instead of
  `AUDIT_INDEX_UNAVAILABLE` from the audited order-lifecycle call in Exercise 10.
- This chapter is a hands-on tour of the normative
  [Appendix: REST API Reference](../user-guide/950-app-REST-API-reference.md) —
  keep it open alongside this chapter for the full endpoint-by-endpoint
  contract (arguments, replies, and error codes) behind every call made here.

Recommended startup order:

1. Generate `engine_config.yaml`.
2. Start `pm-engine --verbose`.
3. Start `pm-stats`.
4. Start `pm-api-gwy --instance desk`.

 

## Background

`pm-api-gwy` is an HTTP and WebSocket wrapper around the matching engine. It
uses bearer tokens from `api_gateways.<NAME>.credentials`. A credential with a
non-null `gateway_id` can submit and manage orders for that ALF gateway. A
credential with `gateway_id: null` is read-only and can use status, reference,
market-data, history, and public WebSocket paths.

Multiple API gateway processes are configured with top-level `api_gateways`:

```yaml
api_gateways:
  desk:
    port: 8080
    credentials:
      - api_key: key-trader-demo
        gateway_id: TRADER01
  algos:
    port: 8081
    credentials:
      - api_key: key-algo-demo
        gateway_id: ALGO01
```

A non-null `gateway_id` may appear in only one `api_gateways` entry. This keeps
private session and event state owned by one API gateway process. Read-only
`gateway_id: null` credentials may appear in multiple entries.

### Authentication model: API key → gateway_id → engine role

Every REST and WebSocket call carries one bearer token:
`Authorization: Bearer <api_key>`. The gateway looks the key up in its own
credential table and resolves it to a session holding just `api_key`,
`gateway_id`, and `description` — nothing more. Three access levels follow
directly from that one resolved `gateway_id`:

| Resolved `gateway_id` | Access |
|---|---|
| `null` | Read-only: reference data, history, public market data, `/status`, `/healthz` |
| a configured ALF `gateway_id` | Trading: everything read-only gets, plus order/quote/combo/OCO submission and cancellation scoped to that one gateway |
| a configured ALF `gateway_id` whose **engine** role is `ADMIN` | Everything trading gets, plus every `/api/v1/admin/*` endpoint |

The important detail is the third row: the API gateway does **not** store an
"is admin" flag on the credential itself. It asks the *engine* what role the
resolved `gateway_id` has, and only accepts `ADMIN` for admin endpoints. This
is why `OPS01:ADMIN` in Exercise 1 configures the role on the **ALF gateway**,
not on the API key — the key is only a pointer to that gateway identity.

See [Appendix: REST API Reference — Auth and roles](../user-guide/950-app-REST-API-reference.md#auth-and-roles)
for the normative statement of this model, including how keys are provisioned.

 

## Exercise 1: Generate a Single API Gateway Config

Generate a local lab config with trading keys and one read-only dashboard key:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 TRADER02 OPS01:ADMIN \
  --outstanding-shares AAPL:15400000000 \
  --outstanding-shares MSFT:7430000000 \
  --api-gateway \
  --api-gateway-name desk \
  --api-gateway-readonly-key \
  --api-gateway-host 127.0.0.1 \
  --api-gateway-port 8080 \
  --seed 20260624 \
  --output engine_config.yaml
```

Inspect the generated section:

```bash
grep -A40 '^api_gateways:' engine_config.yaml
```

Expected behavior:

- top-level `api_gateways:` exists
- `desk:` has `port: 8080`
- generated credentials exist for `TRADER01`, `TRADER02`, `OPS01`, and one read-only key

Note down `OPS01`'s generated key — its resolved engine role is `ADMIN`, and
Exercise 10 uses it for every admin REST call.

:material-checkbox-blank-outline: Checkpoint: you can identify one trading key, one read-only key, and the `OPS01` admin key in the config.

 

## Exercise 2: Start the API Gateway Process

Start the core processes with the generated config:

```bash
pm-engine --verbose
pm-stats
pm-api-gwy --instance desk
```

If the config contains only one `api_gateways` entry, `--instance` can be omitted.
Use it anyway in labs so the selected process is explicit.

Expected behavior:

- `pm-api-gwy` binds to `127.0.0.1:8080`
- startup fails if `api_gateways.desk.enabled` is `false`
- startup fails if the same non-null `gateway_id` is assigned to two named entries

:material-checkbox-blank-outline: Checkpoint: `GET /api/v1/status` is reachable once the process is running.

 

## Exercise 3: Explore Swagger with a Bearer Key

Open Swagger in a browser:

```text
http://127.0.0.1:8080/docs
```

Use the Authorize control and paste a generated bearer token. Then run:

```bash
curl -H 'Authorization: Bearer key-trader-demo' \
  http://127.0.0.1:8080/api/v1/status
```

Replace `key-trader-demo` with a key from your generated config.

Try the same request with a read-only key, then try a write endpoint with the
read-only key.

Expected behavior:

- status works for trading and read-only keys
- order entry rejects a read-only key
- Swagger lists the same route shapes exposed by `/openapi.json`

:material-checkbox-blank-outline: Checkpoint: you can authenticate in Swagger and explain which key is allowed to submit orders.

 

## Exercise 4: Submit and Cancel an Order over REST

Submit a limit order with a trading key:

```bash
curl -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Authorization: Bearer key-trader-demo' \
  -H 'Content-Type: application/json' \
  -d '{
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "quantity": 100,
    "price": 209.50,
    "tif": "DAY"
  }'
```

Capture the returned `order_id`, then cancel it:

```bash
curl -X DELETE http://127.0.0.1:8080/api/v1/orders/ORDER_ID \
  -H 'Authorization: Bearer key-trader-demo'
```

Expected behavior:

- the submit call returns an accepted response or an engine validation error
- a valid cancel request targets the authenticated credential's `gateway_id`
- read-only keys cannot submit or cancel orders

:material-checkbox-blank-outline: Checkpoint: you can submit an order and observe its cancel path or explain the engine-side validation error.

 

## Exercise 5: Query Reference Data

Reference-data endpoints expose compiled, mostly-static configuration: tick
sizes, risk bands, index definitions, and the session schedule. They change
only when an admin reloads the reference bundle (Exercise 10) — never per
trade or per order.

Fetch the full bundle in one call:

```bash
curl -H 'Authorization: Bearer key-readonly-demo' \
  http://127.0.0.1:8080/api/v1/reference
```

Then fetch the individual sections used most often:

```bash
curl -H 'Authorization: Bearer key-readonly-demo' \
  http://127.0.0.1:8080/api/v1/reference/symbols

curl -H 'Authorization: Bearer key-readonly-demo' \
  http://127.0.0.1:8080/api/v1/reference/risk

curl -H 'Authorization: Bearer key-readonly-demo' \
  http://127.0.0.1:8080/api/v1/reference/schedule

curl -H 'Authorization: Bearer key-readonly-demo' \
  http://127.0.0.1:8080/api/v1/reference/config-version
```

Every reference reply carries `config_version` — a content hash of the
compiled bundle. Compare the value returned by `/reference/config-version`
against the one embedded in `/reference/symbols`; they must match. A client
can poll this one small value instead of every field to notice a config
change.

Expected behavior:

- a read-only key can call every `/reference/*` endpoint
- `tick_decimals` for `AAPL`/`MSFT` in `/reference/symbols` matches what you
  passed to `pm-config-gen`
- `config_version` is identical across every `/reference/*` reply taken at
  the same point in time

:material-checkbox-blank-outline: Checkpoint: you can explain the difference
between `GET /api/v1/reference` (one round-trip) and the per-section
endpoints, and what `config_version` is for.

 

## Exercise 6: Use the Python REST Example

From the REST example directory, run the Python client or adapt it with the key
and port from your config:

```bash
cd docs/examples/REST/python
EDUMATCHER_API_URL=http://127.0.0.1:8080 \
EDUMATCHER_API_KEY=key-trader-demo \
python3 demo_info.py
```

Use the example source as a reference for adding status, order-entry, and cancel
calls to a test harness.

:material-checkbox-blank-outline: Checkpoint: the Python client reaches the gateway and sends authenticated requests.

 

## Exercise 7: Use the C REST Example

Build and run the C example from the REST example directory:

```bash
cd docs/examples/REST/c
make
EDUMATCHER_API_KEY=key-trader-demo ./demo_info
```

Expected behavior:

- the client sends an Authorization header
- status or order-entry responses are printed as JSON
- connection errors identify an unavailable gateway process or wrong port

:material-checkbox-blank-outline: Checkpoint: the C example can call the running API gateway with a configured key.

 

## Exercise 8: Query Order and Trade History

History endpoints read from `pm-stats`'s database, so `pm-stats` must be
running and must have been running while your orders and trades happened —
it cannot reconstruct events from before it started.

Submit and fill an order (repeat Exercise 4 with a marketable price, or cross
`TRADER01` against `TRADER02`), then query its lifecycle with a trading key:

```bash
curl -H 'Authorization: Bearer key-trader-demo' \
  "http://127.0.0.1:8080/api/v1/history/orders?symbol=AAPL&limit=10"

curl -H 'Authorization: Bearer key-trader-demo' \
  http://127.0.0.1:8080/api/v1/history/orders/ORDER_ID

curl -H 'Authorization: Bearer key-trader-demo' \
  "http://127.0.0.1:8080/api/v1/history/fills?symbol=AAPL"
```

The public trade tape and daily OHLCV accept any authenticated key, not only
a trading key:

```bash
curl -H 'Authorization: Bearer key-readonly-demo' \
  "http://127.0.0.1:8080/api/v1/history/trades?symbol=AAPL&limit=5"

curl -H 'Authorization: Bearer key-readonly-demo' \
  "http://127.0.0.1:8080/api/v1/history/daily?symbol=AAPL"
```

Walk a second page using the cursor from the first reply:

```bash
curl -H 'Authorization: Bearer key-readonly-demo' \
  "http://127.0.0.1:8080/api/v1/history/trades?symbol=AAPL&limit=5&after=NEXT_CURSOR"
```

Expected behavior:

- `/history/orders` and `/history/fills` are scoped to the caller's own
  gateway — `TRADER01`'s key never sees `TRADER02`'s orders
- `/history/trades` and `/history/daily` are public and show both sides
- a reply with `"has_more": true` always includes `next_cursor`; passing it
  back unchanged as `after` returns the next page
- if `pm-stats` is not running, every history call returns `503 STATS_DB`

:material-checkbox-blank-outline: Checkpoint: you can explain why
`/history/orders` is gateway-scoped but `/history/trades` is not.

 

## Exercise 9: Observe WebSocket Events

Connect to private events before submitting new orders:

```bash
python3 -m websockets ws://127.0.0.1:8080/api/v1/events
```

Once connected, the CLI waits for you to type. Send the authentication message
as your first input, then press Enter:

```text
> {"api_key": "key-trader-demo"}
< {"type": "authenticated", "gateway_id": "TRADER01"}
```

In another terminal, submit or cancel an order with the same key. Observe the
private event stream.

Then connect to a public market-data WebSocket with a read-only key:

```bash
python3 -m websockets ws://127.0.0.1:8080/api/v1/market-data
```

After authentication, send a subscription control message:

```text
> {"api_key": "key-readonly-demo"}
< {"type": "authenticated"}
> {"action": "subscribe", "symbols": ["AAPL"], "channels": ["book", "trades"]}
< {"type": "subscription", "data": {"items": [...], "always": ["session", "circuit_breaker"], "rejected": []}}
```

Each rule can have its own symbols, so one socket can carry an overview plus a
focused instrument:

```text
> {"action": "subscribe", "items": [
    {"symbols": ["*"],    "channels": ["book", "trades"]},
    {"symbols": ["AAPL"], "channels": ["depth"]}
  ]}
```

Expected behavior:

- private events correspond to the authenticated trading gateway
- public market-data access does not require a non-null `gateway_id`
- stale or unknown bearer keys are rejected
- every event carries `topic` and a per-topic `seq`; a jump in `seq` for a
  topic means your client read too slowly and events were dropped
- `session` and `circuit_breaker` arrive whether or not you subscribed — the
  ack lists them under `always`

:material-checkbox-blank-outline: Checkpoint: you can explain when to use REST responses versus WebSocket events for order outcomes.

 

## Exercise 10: Admin REST — Session Control, Risk, and Cross-Gateway Orders

Confirm the resolved role first, with `OPS01`'s key from Exercise 1:

```bash
curl -H 'Authorization: Bearer key-ops01-demo' \
  http://127.0.0.1:8080/api/v1/status
```

`gateway_role` must read `ADMIN`; the reply also includes `gateway_count`, a
field only ADMIN callers get back. Now try the same idea with a trading key:

```bash
curl -i -H 'Authorization: Bearer key-trader-demo' \
  http://127.0.0.1:8080/api/v1/admin/halts
```

Expect `403 ROLE_DENIED` — a trading key is never accepted on `/admin/*`,
regardless of which gateway it is bound to.

Trigger and resume a circuit-breaker halt with the ADMIN key:

```bash
curl -X POST http://127.0.0.1:8080/api/v1/admin/circuit-breaker/trigger \
  -H 'Authorization: Bearer key-ops01-demo' \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "AAPL", "level": "L1"}'

curl -H 'Authorization: Bearer key-ops01-demo' \
  http://127.0.0.1:8080/api/v1/admin/halts

curl -X POST http://127.0.0.1:8080/api/v1/admin/circuit-breaker/resume \
  -H 'Authorization: Bearer key-ops01-demo' \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "AAPL"}'
```

Request a session transition. This call now waits for the engine's verdict
instead of firing and forgetting:

```bash
curl -i -X POST http://127.0.0.1:8080/api/v1/admin/session/transition \
  -H 'Authorization: Bearer key-ops01-demo' \
  -H 'Content-Type: application/json' \
  -d '{"to_state": "CONTINUOUS"}'
```

A successful transition returns `202` with `status: "APPLIED"` and a
`command_id`. Requesting a state the engine cannot apply (for example when
sessions are disabled) returns `409 TRANSITION_REJECTED` with a `reason`,
instead of leaving you to guess from a timeout.

Look at cross-gateway order visibility:

```bash
curl -H 'Authorization: Bearer key-ops01-demo' \
  "http://127.0.0.1:8080/api/v1/admin/orders?symbol=AAPL"
```

This is the only endpoint that shows every gateway's resting orders in one
call; a trading key never sees this. Note the `retention_sec` field in the
reply — filled/cancelled/expired orders are evicted from this view after
`order_retention_sec` (default one hour, configurable per `api_gateways`
instance), while resting orders are never evicted regardless of age.

Fetch one order's full cross-gateway lifecycle from the audit trail:

```bash
curl -i -H 'Authorization: Bearer key-ops01-demo' \
  http://127.0.0.1:8080/api/v1/admin/orders/ORDER_ID
```

This endpoint is optional: it depends on a separate `pm-audit` index that
this gateway only *reads*, never writes. If `pm-audit` has not built one,
expect `503 AUDIT_INDEX_UNAVAILABLE` — every other admin endpoint keeps
working normally.

Finally, cancel resting exposure with the kill-switch family:

```bash
curl -X POST http://127.0.0.1:8080/api/v1/admin/kill-switch/symbol \
  -H 'Authorization: Bearer key-ops01-demo' \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "AAPL", "reason": "training exercise"}'

curl -X POST http://127.0.0.1:8080/api/v1/admin/kill-switch/gateway \
  -H 'Authorization: Bearer key-ops01-demo' \
  -H 'Content-Type: application/json' \
  -d '{"target_gateway_id": "TRADER01", "reason": "training exercise"}'
```

Expected behavior:

- a trading key gets `403 ROLE_DENIED` on every `/admin/*` path
- `/admin/session/transition` blocks for the engine's verdict and never just
  times out silently
- `/admin/orders` returns orders from every gateway, not just `OPS01`'s
- `/admin/orders/{order_id}` either returns the full lifecycle or a clear
  `503 AUDIT_INDEX_UNAVAILABLE` if no audit index is deployed

:material-checkbox-blank-outline: Checkpoint: you can explain why role
resolution happens against the engine rather than being a property of the
API key itself.

 

## Exercise 11: Configure Multiple Logical API Gateways

Generate two API gateway process configs, one for desk trading and one for
algorithmic trading:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 ALGO01 OPS01:ADMIN \
  --api-gateway-instance desk:TRADER01:8080 \
  --api-gateway-instance algos:ALGO01:8081 \
  --seed 20260624 \
  --output engine_config.yaml
```

Start each named process in a separate terminal:

```bash
pm-api-gwy --instance desk
pm-api-gwy --instance algos
```

Try an invalid duplicate assignment:

```bash
pm-config-gen \
  --symbols AAPL \
  --gateways TRADER01 \
  --api-gateway-instance desk:TRADER01 \
  --api-gateway-instance algos:TRADER01 \
  --dry-run
```

Expected behavior:

- `desk` listens on `8080` and owns `TRADER01`
- `algos` listens on `8081` and owns `ALGO01`
- duplicate non-null `gateway_id` assignment is rejected before runtime

:material-checkbox-blank-outline: Checkpoint: you can run two API gateway processes and explain why a write-capable gateway ID is globally unique across them.

 

## Exercise 12: Write a Python CLI Client for LIMIT Order Entry

Use the `ApiGatewayClient` library from `docs/examples/REST/python` to write a
small script that submits a LIMIT order and prints the engine response.

```python
import argparse, json, os, sys
sys.path.insert(0, "docs/examples/REST/python")
from api_gateway_client import ApiGatewayClient

parser = argparse.ArgumentParser()
parser.add_argument("--side",   required=True, choices=["BUY", "SELL"])
parser.add_argument("--symbol", required=True)
parser.add_argument("--qty",    required=True, type=int)
parser.add_argument("--price",  required=True, type=float)
parser.add_argument("--wait-ack", action="store_true")
args = parser.parse_args()

client = ApiGatewayClient(
    os.environ.get("EDUMATCHER_API_URL", "http://127.0.0.1:8080"),
    os.environ.get("EDUMATCHER_API_KEY", "key-trader-demo"),
)
path = "/api/v1/orders" + ("?wait=ack" if args.wait_ack else "")
result = client.post_json(path, {
    "symbol": args.symbol.upper(),
    "side":   args.side,
    "order_type": "LIMIT",
    "quantity": args.qty,
    "price":  args.price,
})
print(json.dumps(result, indent=2))
```

Run it from the repo root:

```bash
python3 limit_order.py --side BUY --symbol AAPL --qty 100 --price 209.50
python3 limit_order.py --side BUY --symbol AAPL --qty 100 --price 209.50 --wait-ack
```

Expected behavior:

- without `--wait-ack`: `status` is `PENDING` and `event` is null
- with `--wait-ack`: `status` is `ACKED` and `event` contains the engine response
- sending a read-only key returns `403 READ_ONLY`
- omitting `--price` returns `400 VALIDATION` because `LIMIT` requires `price`

A fully documented `MARKET` order version that follows the same pattern is
available at `docs/examples/REST/python/submit_market_order.py`.

:material-checkbox-blank-outline: Checkpoint: your script prints `order_id` and `status` from a live gateway.

 

## Support Libraries and Example Clients

Reference examples used in this training chapter:

- `docs/examples/REST/python`
- `docs/examples/REST/c`

Use these examples as small integration clients when building course labs,
smoke tests, or external adapter prototypes.

 

## Summary

You can now:

- Generate one or more `api_gateways` process configs with trading, read-only,
  and ADMIN-resolved bearer credentials.
- Start and reach `pm-api-gwy` over REST, Swagger, and WebSocket.
- Submit, cancel, and observe orders through REST and private WebSocket events.
- Query the reference-data, history, and admin REST surfaces, and explain what
  each returns and who is allowed to call it.
- Explain why a write-capable ALF `gateway_id` must be unique across every
  configured `api_gateways` process, and why ADMIN access is resolved from the
  engine rather than stored on the API key.

See [Appendix: REST API Reference](../user-guide/950-app-REST-API-reference.md)
for the full normative contract behind every endpoint used in this chapter.

## Reflection

If two API gateway processes both listed the same `gateway_id` as a
read-only (`gateway_id: null`) credential, would that be a problem? Why does
the constraint only apply to non-null `gateway_id` values?

`GET /api/v1/status` returns a different `gateway_role` for the same running
engine depending on which key you authenticate with. Where does that role
actually come from, and what would go wrong if the API gateway instead
trusted a role embedded directly in the key?

## Handoff for Chapter 25

Before starting [25 — Market Index (pm-index)](25-index.md), you can stop
`pm-api-gwy`; it is not required there. Keep `pm-engine` and `pm-stats`
running if you want to reuse the same session, or start fresh — Chapter 25
generates its own config with `pm-config-gen`.
