# Protocol Support Library Examples

!!! note "Learning objectives"
    After reading this chapter you will understand:

    - where protocol support-library source code lives
    - the Python and C APIs exposed by each parser library
    - how to run the example clients for each gateway
    - how to validate gateway connectivity quickly using reusable example code
    - how to navigate parser-library source files when integrating external clients


## Scope

This chapter covers source-code examples for all external protocol gateways
and the REST API:

| Protocol | Gateway | Port | Directory |
|----------|---------|------|-----------|
| ALF  | `pm-alf-gwy`  | 5565 | `docs/examples/alf`  |
| CALF | `pm-md-gwy`   | 5570 | `docs/examples/calf` |
| RALF | `pm-ralf-gwy` | 5580 | `docs/examples/ralf` |
| BALF | `pm-balf-gwy` | 5560 | `docs/examples/balf` |
| REST | `pm-api-gwy`  | 8080 | `docs/examples/REST` |

See also: [Protocol Overview](19-protocol-overview.md)


---

## ALF support library and examples

ALF (`pm-alf-gwy`) is the primary order-entry gateway.  External clients
connect over TCP and exchange text lines using the ALF wire format.

### Source files

| File | Description |
|------|-------------|
| [alf/python/alf_parser.py](../examples/alf/python/alf_parser.py) | Python parser, builder, and session helper |
| [alf/python/alf_client.py](../examples/alf/python/alf_client.py) | Interactive Python client with tab-completion |
| [alf/c/alf_parser.h](../examples/alf/c/alf_parser.h) | C library header |
| [alf/c/alf_parser.c](../examples/alf/c/alf_parser.c) | C library implementation |
| [alf/c/alf_client.c](../examples/alf/c/alf_client.c) | Interactive C client with readline |
| [alf/c/Makefile](../examples/alf/c/Makefile) | Build helper |

### Wire format

```
VERB|KEY=VALUE|KEY=VALUE\n
```

Command verbs and field keys are case-insensitive (normalized to uppercase).
Segments without `=` are silently skipped.  Duplicate keys: last value wins.

### Python API — `alf_parser.py`

**`parse_alf_line(line: str) → AlfMessage`**
: Parse one ALF line.  Returns an `AlfMessage(msg_type, fields)` frozen
  dataclass.  Raises `AlfParseError` on malformed input.

**`build_alf_line(msg_type: str, fields: dict | None) → str`**
: Build one `\n`-terminated ALF line.  Raises `AlfParseError` if the
  message type contains invalid characters or any field contains `|`.

**`AlfSession.connect(host, port, gateway_id, client_name, timeout) → AlfSession`**
: Open a TCP connection and complete the `HELLO`/`WELCOME` handshake.
  Returns an authenticated session object.

**`AlfSession.send(msg_type, fields)`**
: Build and send one ALF line over the established connection.

**`AlfSession.recv_msg() → AlfMessage`**
: Block until one complete `\n`-terminated line arrives and parse it.

**`AlfSession.close()`**
: Send `PING` (optional liveness check) and close the socket.

### Python usage pattern

```python
from alf_parser import parse_alf_line, build_alf_line, AlfSession, AlfMessage

# Parse one line received from the gateway
msg: AlfMessage = parse_alf_line("ACK|ORDER_ID=abc|ACCEPTED=TRUE|SYMBOL=AAPL")
print(msg.msg_type)   # "ACK"
print(msg.fields)     # {"ORDER_ID": "ABC", "ACCEPTED": "TRUE", "SYMBOL": "AAPL"}

# Build a line to send
line: str = build_alf_line("NEW", {
    "SYM": "AAPL", "SIDE": "BUY", "TYPE": "LIMIT",
    "QTY": "100", "PRICE": "150.00",
})
# → "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00\n"

# Full session: connect, perform HELLO/WELCOME handshake, send and receive
session = AlfSession.connect("127.0.0.1", 5565, "TRADER01")
print(session.welcome.gw_name)          # "alf-gwy01"
session.send("SYMBOLS")
msg = session.recv_msg()                # first line of SYMBOLS response
session.close()
```

### Run Python interactive client

```bash
cd docs/examples/alf/python

# Connect to local gateway as TRADER01
python3 alf_client.py --id TRADER01

# Connect to remote gateway with a custom client name in logs
python3 alf_client.py --host 10.0.0.5 --port 5565 --id MM01 --client "my-mm-bot"
```

At the prompt, tab-completion is available for commands, field names, and enum
values.  Command history is persisted to `~/.alf_client_history`.

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00
[TRADER01]> AMEND|ID=<order-id>|PRICE=151.00
[TRADER01]> CANCEL|ID=<order-id>
[TRADER01]> KILL
[TRADER01]> SYMBOLS
[TRADER01]> ORDERS
[TRADER01]> POS
[TRADER01]> STATUS
[TRADER01]> HELP
[TRADER01]> EXIT
```

### C API — `alf_parser.h`

**`int alf_parse_line(char *line, alf_message_t *out)`**
: Parse one mutable ALF line in-place.  Returns 0 on success, negative
  on error (`-1` null args, `-2` empty line, `-3` invalid verb,
  `-4` too many fields).

**`const char *alf_get_field(const alf_message_t *msg, const char *key)`**
: Return the value for `key` (case-insensitive), or `NULL` if absent.

**`int alf_build_line(char *out, size_t cap, const char *msg_type, const char * const *kv)`**
: Write one ALF line into `out`.  `kv` is a `NULL`-terminated array of
  alternating key/value strings.  Returns bytes written or `-1` on overflow.

### C usage pattern

```c
#include "alf_parser.h"

/* Parse */
char line[] = "ACK|ORDER_ID=abc|ACCEPTED=TRUE";
alf_message_t msg;
alf_parse_line(line, &msg);
printf("%s\n", msg.msg_type);                    /* "ACK" */
printf("%s\n", alf_get_field(&msg, "ACCEPTED")); /* "TRUE" */

/* Build */
const char *kv[] = {
    "SYM", "AAPL", "SIDE", "BUY",
    "TYPE", "LIMIT", "QTY", "100", "PRICE", "150.00", NULL,
};
char buf[4096];
alf_build_line(buf, sizeof(buf), "NEW", kv);
/* → "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00\n" */
```

### Build and run C client

```bash
cd docs/examples/alf/c
make

# Connect to local gateway
./alf_client --id TRADER01

# Connect to remote gateway; disable ANSI colours
./alf_client --host 10.0.0.5 --port 5565 --id TRADER01 --no-color
```

The C client supports the same commands and tab-completion as the Python client.

### Manual gateway sanity check

```bash
nc 127.0.0.1 5565
```

Then type:

```text
HELLO|CLIENT=manual01|PROTO=ALF1|ID=TRADER01
NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=10
SYMBOLS
ORDERS
```

See also:

- [ALF Gateway](24-alf-gateway.md)
- [Appendix - ALF Protocol](90-app-alf-protocol.md)


---

## CALF support library and examples

CALF (`pm-md-gwy`) is the market data feed gateway.  Subscribers connect over
TCP and receive a stream of top-of-book, trade, and other market-data events.

### Source files

| File | Description |
|------|-------------|
| [calf/calf_parser.py](../examples/calf/calf_parser.py) | Python parser and builder |
| [calf/calf_subscriber.py](../examples/calf/calf_subscriber.py) | Python subscriber example |
| [calf/calf_parser.h](../examples/calf/calf_parser.h) | C library header |
| [calf/calf_parser.c](../examples/calf/calf_parser.c) | C library implementation |
| [calf/calf_subscriber.c](../examples/calf/calf_subscriber.c) | C subscriber example |
| [calf/Makefile](../examples/calf/Makefile) | Build helper |

### Wire format

```
MSGTYPE|KEY=VALUE|KEY=VALUE\n
```

Fields missing `=` raise `CalfParseError`.  Duplicate keys are not permitted.

### Python API — `calf_parser.py`

**`parse_calf_line(line: str) → CalfMessage`**
: Parse one CALF line.  Returns a `CalfMessage(msg_type, fields)` frozen
  dataclass.  Raises `CalfParseError` on malformed input.

**`build_calf_line(msg_type: str, fields: dict | None) → str`**
: Build one `\n`-terminated CALF line.  Raises `CalfParseError` for invalid
  message types or fields containing `|`.

### Python usage pattern

```python
from calf_parser import build_calf_line, parse_calf_line

# Build a HELLO line
line = build_calf_line("HELLO", {"CLIENT": "demo01", "PROTO": "CALF1"})
# → "HELLO|CLIENT=demo01|PROTO=CALF1\n"

# Parse a WELCOME response
msg = parse_calf_line("WELCOME|PROTO=CALF1|GW=md-gwy01|HBINT=1|REPLAY=30")
print(msg.msg_type)          # "WELCOME"
print(msg.fields["HBINT"])   # "1"

# Parse a streaming TOP-OF-BOOK update
top = parse_calf_line("TOP|SYM=AAPL|BID=149.50|ASK=150.00|SEQ=1042")
print(top.fields["BID"])     # "149.50"
```

### Run Python example

```bash
cd docs/examples/calf

# Subscribe to TOP and TRADE for AAPL
python3 calf_subscriber.py --host 127.0.0.1 --port 5570 \
    --channels TOP,TRADE --symbols AAPL

# Resume from a known sequence number (single-stream resume)
python3 calf_subscriber.py --host 127.0.0.1 --port 5570 \
    --resume --resume-ch TOP --resume-sym AAPL --lastseq 1042
```

### C API — `calf_parser.h`

**`int calf_parse_line(char *line, calf_message_t *out)`**
: Parse one mutable CALF line in-place.  Returns 0 on success, negative on
  error.

**`const char *calf_get_field(const calf_message_t *msg, const char *key)`**
: Return the value for `key`, or `NULL` if absent.

### C usage pattern

```c
#include "calf_parser.h"

char line[] = "TOP|SYM=AAPL|BID=149.50|ASK=150.00|SEQ=1042";
calf_message_t msg;
calf_parse_line(line, &msg);
printf("%s\n", calf_get_field(&msg, "BID"));  /* "149.50" */
```

### Build and run C example

```bash
cd docs/examples/calf
make
./calf_subscriber 127.0.0.1 5570
```

### Manual gateway sanity check

```bash
nc 127.0.0.1 5570
```

Then type:

```text
HELLO|CLIENT=manual01|PROTO=CALF1
SUB|CH=TOP,TRADE|SYM=AAPL
```

See also:

- [Market Data Feed (CALF)](20-market-data-feed.md)
- [Appendix - CALF Protocol](92-app-calf-protocol.md)


---

## RALF support library and examples

RALF (`pm-ralf-gwy`) is the post-trade dissemination gateway.  Clients
connect over TCP and receive execution reports, drop-copy events, and
audit records.

### Source files

| File | Description |
|------|-------------|
| [ralf/ralf_parser.py](../examples/ralf/ralf_parser.py) | Python parser and builder |
| [ralf/ralf_subscriber.py](../examples/ralf/ralf_subscriber.py) | Python subscriber example |
| [ralf/ralf_parser.h](../examples/ralf/ralf_parser.h) | C library header |
| [ralf/ralf_parser.c](../examples/ralf/ralf_parser.c) | C library implementation |
| [ralf/ralf_subscriber.c](../examples/ralf/ralf_subscriber.c) | C subscriber example |
| [ralf/Makefile](../examples/ralf/Makefile) | Build helper |

### Wire format

```
MSGTYPE|KEY=VALUE|KEY=VALUE\n
```

Identical text-line structure to CALF; field parsing rules are the same.

### Python API — `ralf_parser.py`

**`parse_ralf_line(line: str) → RalfMessage`**
: Parse one RALF line.  Returns a `RalfMessage(msg_type, fields)` frozen
  dataclass.  Raises `RalfParseError` on malformed input.

**`build_ralf_line(msg_type: str, fields: dict | None) → str`**
: Build one `\n`-terminated RALF line.  Raises `RalfParseError` for invalid
  message types or fields containing `|`.

### Python usage pattern

```python
from ralf_parser import build_ralf_line, parse_ralf_line

# Build a HELLO line
line = build_ralf_line("HELLO", {
    "CLIENT": "demo01",
    "PROTO": "RALF1",
    "ROLE": "CLEARING",
    "LASTSEQ": "0",
})
# → "HELLO|CLIENT=demo01|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0\n"

# Parse a WELCOME response
msg = parse_ralf_line("WELCOME|PROTO=RALF1|GW=ralf-gwy01|ROLE=CLEARING")
print(msg.msg_type)         # "WELCOME"
print(msg.fields["ROLE"])   # "CLEARING"

# Parse an inbound execution report
fill = parse_ralf_line("FILL|SYM=AAPL|SIDE=BUY|QTY=100|PRICE=150.00|SEQ=77")
print(fill.fields["PRICE"]) # "150.00"
```

### Run Python example

```bash
cd docs/examples/ralf

# Subscribe as CLEARING role, all channels, all symbols
python3 ralf_subscriber.py --host 127.0.0.1 --port 5580 \
    --role CLEARING --channels CLEARING,DROP_COPY,AUDIT --symbols '*'

# Resume from a known sequence number
python3 ralf_subscriber.py --host 127.0.0.1 --port 5580 \
    --role CLEARING --channels CLEARING --symbols '*' --lastseq 77
```

### C API — `ralf_parser.h`

**`int ralf_parse_line(char *line, ralf_message_t *out)`**
: Parse one mutable RALF line in-place.  Returns 0 on success, negative on
  error.

**`const char *ralf_get_field(const ralf_message_t *msg, const char *key)`**
: Return the value for `key`, or `NULL` if absent.

### C usage pattern

```c
#include "ralf_parser.h"

char line[] = "FILL|SYM=AAPL|SIDE=BUY|QTY=100|PRICE=150.00|SEQ=77";
ralf_message_t msg;
ralf_parse_line(line, &msg);
printf("%s\n", ralf_get_field(&msg, "PRICE")); /* "150.00" */
```

### Build and run C example

```bash
cd docs/examples/ralf
make
./ralf_subscriber 127.0.0.1 5580 CLEARING
```

### Manual gateway sanity check

```bash
nc 127.0.0.1 5580
```

Then type:

```text
HELLO|CLIENT=manual01|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0
SUB|CH=CLEARING|SYM=*
```

See also:

- [Post-Trade Dissemination (RALF)](18-post-trade.md)
- [Appendix - RALF Protocol](93-app-ralf-protocol.md)


---

## BALF support library and examples

BALF (`pm-balf-gwy`) is the binary order-entry gateway, intended for
ultra-low-latency clients.  Frames are fixed-length little-endian structs
rather than text lines.

### Source files

| File | Description |
|------|-------------|
| [balf/balf_parser.py](../examples/balf/balf_parser.py) | Python binary parser |
| [balf/balf_parser.c](../examples/balf/balf_parser.c) | C binary parser |

### Binary frame structure

Every BALF frame begins with an 8-byte header:

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 | Magic (`0xBA`) |
| 1 | 1 | Version (`0x01`) |
| 2 | 1 | Message type |
| 3 | 1 | Flags |
| 4 | 4 | Sequence number (LE uint32) |

Prices are encoded as fixed-point integers scaled by `100_000_000`
(8 decimal places).

### Supported message types

| Constant | Value | Description |
|----------|-------|-------------|
| `MSG_LOGON` | `0x01` | Session logon |
| `MSG_LOGON_ACK` | `0x02` | Logon acknowledgement |
| `MSG_NEW_ORDER` | `0x10` | New order |
| `MSG_ORDER_ACK` | `0x11` | Order acknowledgement |
| `MSG_CANCEL_ORDER` | `0x12` | Cancel request |
| `MSG_CANCEL_ACK` | `0x13` | Cancel acknowledgement |
| `MSG_AMEND_ORDER` | `0x14` | Amend request |
| `MSG_AMEND_ACK` | `0x15` | Amend acknowledgement |
| `MSG_EXECUTION_REPORT` | `0x20` | Fill / execution report |
| `MSG_HEARTBEAT` | `0x30` | Heartbeat |
| `MSG_LOGOUT` | `0x40` | Session logout |

### Python API — `balf_parser.py`

**`parse_header(frame: bytes) → Header`**
: Parse the 8-byte BALF header.  Returns a `Header(magic, version, msg_type,
  flags, seq_no)` frozen dataclass.  Raises `ValueError` on bad magic or
  unsupported version.

**`split_frame(frame: bytes) → tuple[Header, bytes]`**
: Validate frame length against the expected size for the message type, then
  return `(header, body_bytes)`.  Raises `ValueError` for unknown message
  types or wrong frame sizes.

**`decode_price(raw: int) → float`**
: Convert a raw fixed-point integer to a float price value.

**`parse_logon_ack(body: bytes) → dict`**
: Decode a `LOGON_ACK` body.  Returns a dict with keys `gateway_id`,
  `accepted`, `reject_code`, `message`.

**`parse_order_ack(body: bytes) → dict`**
: Decode an `ORDER_ACK` body.  Returns a dict with keys `client_order_id`,
  `order_id`, `timestamp_ns`, `accepted`, `reject_code`, `reason`.

**`parse_execution_report(body: bytes) → dict`**
: Decode an `EXECUTION_REPORT` body.  Returns a dict with keys
  `client_order_id`, `order_id`, `fill_price_raw`, `fill_qty`,
  `remaining_qty`, `timestamp_ns`, `symbol`, `side`, `status`.

### Python usage pattern

```python
from balf_parser import (
    parse_header, split_frame, decode_price,
    parse_logon_ack, parse_order_ack, parse_execution_report,
    MSG_LOGON_ACK, MSG_ORDER_ACK, MSG_EXECUTION_REPORT,
    FRAME_SIZES,
)

# Decode a raw frame received from TCP
hdr, body = split_frame(raw_bytes)

if hdr.msg_type == MSG_EXECUTION_REPORT:
    report = parse_execution_report(body)
    price = decode_price(report["fill_price_raw"])
    print(f"fill: {report['symbol']} qty={report['fill_qty']} price={price}")
elif hdr.msg_type == MSG_ORDER_ACK:
    ack = parse_order_ack(body)
    print(f"order_id={ack['order_id']} accepted={ack['accepted']}")
```

### Run the gateway

```bash
pm-balf-gwy --config engine_config.yaml

# Override bind port
pm-balf-gwy --config engine_config.yaml --port 5560

# Override engine host
pm-balf-gwy --config engine_config.yaml --engine-host 10.0.0.5
```

The gateway binds on port **5560** by default.  BALF uses fixed-length binary
frames so there is no text-mode manual sanity check; use the Python parser
library or a binary client tool to verify connectivity.

See also:

- [BALF Gateway](25-balf-gateway.md)
- [Appendix - BALF Protocol](91-app-balf-protocol.md)


---

## REST API support library and examples

`pm-api-gwy` exposes a JSON REST API for order submission and session queries.
The support library (`api_gateway_client`) uses only the Python standard
library and the C standard socket API — no third-party HTTP libraries are
required.

### Source files

| File | Description |
|------|-------------|
| [REST/python/api_gateway_client.py](../examples/REST/python/api_gateway_client.py) | Python REST client library |
| [REST/python/demo_info.py](../examples/REST/python/demo_info.py) | Print gateway status, symbols, and session info |
| [REST/python/submit_market_order.py](../examples/REST/python/submit_market_order.py) | Submit a MARKET order from the command line |
| [REST/c/api_gateway_client.h](../examples/REST/c/api_gateway_client.h) | C library header |
| [REST/c/api_gateway_client.c](../examples/REST/c/api_gateway_client.c) | C library implementation |
| [REST/c/demo_info.c](../examples/REST/c/demo_info.c) | C equivalent of demo_info.py |
| [REST/c/Makefile](../examples/REST/c/Makefile) | Build helper |

### Authentication

All requests require a `Bearer` token in the `Authorization` header.
The default development key is `key-trader-demo`.

Configure via environment variables:

```bash
export EDUMATCHER_API_URL="http://127.0.0.1:8080"
export EDUMATCHER_API_KEY="key-trader-demo"
```

### Python API — `api_gateway_client.py`

**`ApiGatewayClient(base_url, api_key, timeout=5.0)`**
: Construct a client for the given base URL and API key.

**`client.get_json(path: str) → dict`**
: Issue a `GET` request and return the parsed JSON body.  Raises
  `RuntimeError` on HTTP error responses.

**`client.post_json(path: str, payload: dict) → dict`**
: Issue a `POST` request with a JSON body and return the parsed JSON
  response.  Raises `RuntimeError` on HTTP error responses.

### Python usage pattern

```python
from api_gateway_client import ApiGatewayClient

client = ApiGatewayClient("http://127.0.0.1:8080", "key-trader-demo")

# Query endpoints
status  = client.get_json("/api/v1/status")
symbols = client.get_json("/api/v1/symbols")
session = client.get_json("/api/v1/session")

# Submit a MARKET order
result = client.post_json("/api/v1/orders", {
    "symbol":     "AAPL",
    "side":       "BUY",
    "order_type": "MARKET",
    "quantity":   100,
})
print(result["order_id"], result["status"])

# Submit and wait for the engine ACK
result = client.post_json("/api/v1/orders?wait=ack", {
    "symbol":     "MSFT",
    "side":       "SELL",
    "order_type": "MARKET",
    "quantity":   50,
})
print(result.get("event"))   # engine acknowledgement event
```

### Run Python examples

```bash
cd docs/examples/REST/python

# Print gateway status, symbols, and session information
python3 demo_info.py

# Submit a BUY MARKET order for 100 AAPL
python3 submit_market_order.py --side BUY --symbol AAPL --qty 100

# Submit and block until the engine ACKs
python3 submit_market_order.py --side SELL --symbol MSFT --qty 50 --wait-ack

# Override URL or key on the command line
python3 submit_market_order.py --url http://10.0.0.5:8080 --key mykey \
    --side BUY --symbol TSLA --qty 10
```

### C API — `api_gateway_client.h`

**`ApiGatewayClient api_gateway_client(host, port, api_key)`**
: Construct a client struct (stack-allocated).

**`char *api_gateway_get(const ApiGatewayClient *client, const char *path)`**
: Issue a `GET` request and return the raw HTTP response body as a
  heap-allocated string.  The caller must `free()` the result.
  Returns `NULL` on network or allocation failure.

### C usage pattern

```c
#include "api_gateway_client.h"
#include <stdlib.h>
#include <stdio.h>

const char *key = getenv("EDUMATCHER_API_KEY") ?: "key-trader-demo";
ApiGatewayClient client = api_gateway_client("127.0.0.1", 8080, key);

char *body = api_gateway_get(&client, "/api/v1/symbols");
if (body) {
    printf("%s\n", body);
    free(body);
}
```

### Build and run C example

```bash
cd docs/examples/REST/c
make

# Print status, symbols, and session info
./demo_info
```

### Manual API sanity check

```bash
curl -s -H "Authorization: Bearer key-trader-demo" \
     http://127.0.0.1:8080/api/v1/status | python3 -m json.tool

curl -s -X POST \
     -H "Authorization: Bearer key-trader-demo" \
     -H "Content-Type: application/json" \
     -d '{"symbol":"AAPL","side":"BUY","order_type":"MARKET","quantity":10}' \
     http://127.0.0.1:8080/api/v1/orders | python3 -m json.tool
```

See also:

- [API Gateway](21-api-gateway.md)


---

## Integration guidance

Use the parser libraries as the protocol boundary in your client code:

1. Read bytes from TCP (or HTTP for REST).
2. Split by newline into protocol lines (text protocols) or read fixed-size
   frames (BALF).
3. Parse lines or frames using the appropriate parser library.
4. Route by `msg_type` and fields.
5. Track `SEQ` checkpoints per protocol rules to enable gap detection and
   replay on reconnect.

This keeps socket handling separate from protocol semantics and makes unit
testing straightforward — pass raw strings or byte buffers directly into the
parser functions without a network connection.