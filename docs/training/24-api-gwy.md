# API Gateway REST/WebSocket Training

## Objective

Train on configuring and using `pm-api-gateway` for REST order entry,
Swagger/OpenAPI exploration, WebSocket event handling, and multi-process logical
separation.

You will practice:

- generating `api_gateways` config with bearer credentials
- starting a named API gateway process
- using REST endpoints with trading and read-only keys
- receiving private and market-data events over WebSocket
- splitting API gateway processes by ALF `gateway_id`

 

## Prerequisites

- Chapters 01-23 completed.
- Engine and stats commands available from the current environment.
- REST examples available in `docs/examples/REST`.
- A terminal for `pm-engine`, one for `pm-stats`, one for `pm-api-gateway`, and one or more client terminals.

Recommended startup order:

1. Generate `engine_config.yaml`.
2. Start `pm-engine --verbose --config engine_config.yaml`.
3. Start `pm-stats --config engine_config.yaml`.
4. Start `pm-api-gateway --config engine_config.yaml --instance desk`.

 

## Background

`pm-api-gateway` is an HTTP and WebSocket wrapper around the matching engine. It
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

:material-checkbox-blank-outline: Checkpoint: you can identify one trading key and one read-only key in the config.

 

## Exercise 2: Start the API Gateway Process

Start the core processes with the generated config:

```bash
pm-engine --verbose --config engine_config.yaml
pm-stats --config engine_config.yaml
pm-api-gateway --config engine_config.yaml --instance desk
```

If the config contains only one `api_gateways` entry, `--instance` can be omitted.
Use it anyway in labs so the selected process is explicit.

Expected behavior:

- `pm-api-gateway` binds to `127.0.0.1:8080`
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

 

## Exercise 5: Use the Python REST Example

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

 

## Exercise 6: Use the C REST Example

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

 

## Exercise 7: Observe WebSocket Events

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
```

Expected behavior:

- private events correspond to the authenticated trading gateway
- public market-data access does not require a non-null `gateway_id`
- stale or unknown bearer keys are rejected

:material-checkbox-blank-outline: Checkpoint: you can explain when to use REST responses versus WebSocket events for order outcomes.

 

## Exercise 8: Configure Multiple Logical API Gateways

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
pm-api-gateway --config engine_config.yaml --instance desk
pm-api-gateway --config engine_config.yaml --instance algos
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

 

## Exercise 9: Write a Python CLI Client for LIMIT Order Entry

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

- Generate one or more `api_gateways` process configs with trading and
  read-only bearer credentials.
- Start and reach `pm-api-gateway` over REST, Swagger, and WebSocket.
- Submit, cancel, and observe orders through REST and private WebSocket events.
- Explain why a write-capable ALF `gateway_id` must be unique across every
  configured `api_gateways` process.

## Reflection

If two API gateway processes both listed the same `gateway_id` as a
read-only (`gateway_id: null`) credential, would that be a problem? Why does
the constraint only apply to non-null `gateway_id` values?

## Handoff for Chapter 25

Before starting [25 — Market Index (pm-index)](25-index.md), you can stop
`pm-api-gateway`; it is not required there. Keep `pm-engine` and `pm-stats`
running if you want to reuse the same session, or start fresh — Chapter 25
generates its own config with `pm-config-gen`.
