# Market Data Feed (CALF)

!!! note "Learning objectives"
    After reading this page you will understand:

    - what `pm-md-gwy` does and why CALF exists as an external feed
    - what data is available on each channel (`TOP`, `TRADE`, `STATE`, `INDEX`, `DEPTH`)
    - which channels accept the `SYM=*` wildcard (`TOP`, `TRADE`, `STATE` — not `INDEX`/`DEPTH`)
    - how to detect gateway capability via `WELCOME|CH_SUPPORTED=` before relying on `DEPTH`
    - when to choose CALF over the other available protocols
    - how to start the gateway and verify connectivity from a terminal
    - how to subscribe to a filtered subset of symbols and channels
    - how snapshot delivery works and when to expect a `SNAP`
    - how to detect sequence gaps and recover with `RESUME=1`
    - how to write a working Python subscriber using the library in `examples/calf/`
    - which operational checks to use when debugging connectivity problems


## What this process is

`pm-md-gwy` is the CALF market-data gateway.  The matching engine publishes
market events on an internal ZeroMQ PUB socket (`:5556`) that is not accessible
to external clients.  `pm-md-gwy` bridges that gap: it subscribes to the engine
PUB socket, normalises raw engine events into CALF lines, and re-publishes them
over TCP (default port `5570`) in a format any language can consume with a plain
socket and line-split logic.

```mermaid
flowchart TB
    E[pm-engine\nZMQ PUB :5556] -->|"book.*, trade.executed\nsession.state\ncircuit_breaker.*\nindex.*"| G

    subgraph G["pm-md-gwy  (TCP :5570)"]
        direction TB
        N["Normalise & sequence"]
        R["Replay buffer\n(time-bounded)"]
        F["Per-client fanout"]
        N --> R --> F
    end

    G --> C1["Bot / algo\n(Python, C, …)"]
    G --> C2["Recorder\n(CSV, DB)"]
    G --> C3["Display / viewer"]
```

Responsibilities of `pm-md-gwy`:

- translates engine events into CALF lines
- assigns **per-stream sequence numbers** on each `(channel, symbol)` pair
- keeps a **time-bounded replay buffer** so reconnecting clients can recover
  missed messages without a full snapshot
- sends an automatic **baseline snapshot** (`SNAP`) when a client first
  subscribes to a `TOP`, `STATE`, `INDEX`, or `DEPTH` stream (a wildcard
  `TOP` subscription gets one real `SNAP` per known symbol, not a single
  `SYM=*` snapshot)
- advertises which channels a given gateway build supports via
  `WELCOME|CH_SUPPORTED=`, so clients can detect `DEPTH`/`INDEX`/wildcard
  availability without a protocol version bump
- enforces per-client subscription limits and disconnects slow clients


## Prerequisites

- `pm-engine` running
- `pm-md-gwy` running
- symbols configured in `engine_config.yaml`

Optional but recommended in config:

```yaml
market_data_gateway:
  enabled: true
  name: "md-gwy01"
  bind_address: "0.0.0.0"
  port: 5570
  heartbeat_interval_sec: 1
  idle_timeout_sec: 5
  replay_window_sec: 30
  max_symbols_per_client: 200
  max_client_queue: 10000
  depth_levels: 10
```


## Start the gateway

Installed mode:

```bash
pm-engine --verbose
pm-md-gwy --config engine_config.yaml
```

Developer mode:

```bash
poetry run pm-engine --verbose
poetry run pm-md-gwy --config engine_config.yaml
```


## Quick connect test

Use `nc` (or `telnet`) to validate the line protocol from the command line before
writing any code:

```bash
nc 127.0.0.1 5570
```

Then type:

```text
HELLO|CLIENT=demo01|PROTO=CALF1
SUB|CH=TOP,TRADE|SYM=AAPL
```

Expected response pattern:

1. `WELCOME|...` — session open
2. `SNAP|CH=TOP|SYM=AAPL|...` — baseline snapshot
3. `MD|...` when top of book changes
4. `TRADE|...` when a trade executes
5. `HB|...` when the stream is quiet

To verify the STATE channel and the wildcard subscription:

```text
SUB|CH=STATE|SYM=*
```

You should receive an immediate `SNAP|CH=STATE|SYM=*|...` followed by live
`STATE|...` lines on session-phase and halt/resume events.

Since CALF `1.0.0`, `SYM=*` also works for `TOP` and `TRADE` — useful for a
market-wide trade tape or "watch everything" bot:

```text
SUB|CH=TRADE|SYM=*
```

Unlike `STATE`'s wildcard, a wildcard `TOP` subscription does **not** send a
single `SNAP|SYM=*`. It sends one real `SNAP` per symbol the gateway
currently knows about, then live `MD` for any symbol — including ones added
later — through that same subscription.

To verify the `DEPTH` channel (check `WELCOME|CH_SUPPORTED=` first — see
below):

```text
SUB|CH=DEPTH|SYM=AAPL
```

Expect an immediate `SNAP|CH=DEPTH|SYM=AAPL|LEVELS=...|BIDS=...|ASKS=...`,
then a `DEPTH|...` line whenever the top price levels change.


## What information is available

The gateway exposes five logical channels.  Each represents a different view of
market activity.

### Channel `TOP` — best bid, ask, and last trade

`TOP` carries incremental updates to the top-of-book for a single symbol.
When the best bid price, bid size, ask price, ask size, or last-trade price/size
changes, the gateway emits one `MD` line containing only the fields that changed.

**When you get it:** Subscribe with `CH=TOP|SYM=<symbol>`.  The gateway
immediately sends a `SNAP` baseline, then streams incremental `MD` events.
Since CALF `1.0.0`, `SYM=*` is also valid on `TOP` — it produces one `SNAP`
per known symbol rather than a single wildcard snapshot (see "Channel
summary" below).

**Typical use cases:** algo trading, live bid/ask/last widgets, real-time price
tracking.

**Wire example:**

```text
SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=2026-06-30T09:30:00.000Z|BID=150.10|BIDSZ=1200|ASK=150.12|ASKSZ=900|LAST=150.11|LASTSZ=300
MD|CH=TOP|SYM=AAPL|SEQ=2|TS=2026-06-30T09:30:00.500Z|BID=150.11|BIDSZ=1400
MD|CH=TOP|SYM=AAPL|SEQ=3|TS=2026-06-30T09:30:01.100Z|ASK=150.13|ASKSZ=700|LAST=150.12|LASTSZ=200
```

Fields omitted from `MD` are **unchanged** from the last known state.  A
receiver merges each `MD` into a local state object seeded from the `SNAP`.

---

### Channel `TRADE` — every trade print

`TRADE` carries one line per matched trade: price, quantity, and aggressor side.
There is **no baseline `SNAP`** — the stream starts from events that occur after
the subscription becomes active.

**When you get it:** Subscribe with `CH=TRADE|SYM=<symbol>`, or `SYM=*`
(CALF `1.0.0`+) to receive every trade across every symbol on one
subscription — handy for a market-wide tape without enumerating tickers.

**Typical use cases:** time-and-sales tape, VWAP/OHLCV calculation, fill
attribution.

**Wire example:**

```text
TRADE|CH=TRADE|SYM=AAPL|SEQ=44|TS=2026-06-30T09:30:01.100Z|PX=150.12|QTY=200|SIDE=BUY
```

---

### Channel `STATE` — session and symbol states

`STATE` carries two kinds of transitions:

- **Session-wide** (e.g. `PRE_OPEN → OPENING_AUCTION → CONTINUOUS`) with `SYM=*`
- **Symbol-level** circuit-breaker halts and resumes with `SYM=<symbol>`

The gateway sends an immediate `SNAP` for each new `(STATE, symbol)` stream.

`STATE` was the first channel to support `SYM=*`. Since CALF `1.0.0`, `TOP`
and `TRADE` also accept it (in any combination with `STATE`). `SYM=*` is
never valid for `INDEX` or `DEPTH` — see "Channel summary" below.

**When you get it:** `CH=STATE|SYM=*` for everything, or `CH=STATE|SYM=<symbol>`
for a single symbol.

**Typical use cases:** gating order flow on halts, session-phase displays,
back-test state annotation.

**Wire example:**

```text
SNAP|CH=STATE|SYM=*|SEQ=1|TS=2026-06-30T09:30:00.000Z|SESSION=PRE_OPEN
STATE|CH=STATE|SYM=*|SEQ=2|TS=2026-06-30T09:30:00.000Z|SESSION=OPENING_AUCTION|PREV=PRE_OPEN
STATE|CH=STATE|SYM=*|SEQ=3|TS=2026-06-30T09:30:05.000Z|SESSION=CONTINUOUS|PREV=OPENING_AUCTION
STATE|CH=STATE|SYM=AAPL|SEQ=1|TS=2026-06-30T10:02:17.000Z|SESSION=HALTED|PREV=CONTINUOUS
STATE|CH=STATE|SYM=AAPL|SEQ=2|TS=2026-06-30T10:05:00.000Z|SESSION=CONTINUOUS|PREV=HALTED
```

---

### Channel `INDEX` — index level updates

`INDEX` carries one `IDX` line every time the index level is recalculated.
Since CALF `1.0.0`, the gateway sends an immediate baseline `SNAP` on
subscribe — the same pattern as `TOP`/`STATE`/`DEPTH` — followed by live
`IDX` updates.

**When you get it:** `CH=INDEX|SYM=<index_id>` (e.g. `CH=INDEX|SYM=EDU50`).
`SYM=*` is not valid for `INDEX` — an explicit index id is always required.

**Typical use cases:** index trackers, portfolio benchmark display, monitoring
day-open / day-high / day-low for the composite index.

**Wire example:**

```text
SNAP|CH=INDEX|SYM=EDU50|SEQ=1|TS=2026-06-30T09:30:00.000Z|LEVEL=5100.00|SESSION=PRE_OPEN
IDX|CH=INDEX|SYM=EDU50|SEQ=12|TS=2026-06-30T09:30:01.100Z|LEVEL=5123.45|SESSION=CONTINUOUS|OPEN=5100.00|CHG=+23.45|PCTCHG=+0.46
```

---

### Channel `DEPTH` — aggregated multi-level order book

`DEPTH` carries the top N price levels per side (Level 2 — aggregated by
price, never per individual order). Whenever any of the tracked levels
change, the gateway emits a `DEPTH` line with the **complete current ladder**
for the affected side(s), not a per-level diff — a client always replaces
its in-memory ladder for that side on receipt.

**When you get it:** Subscribe with `CH=DEPTH|SYM=<symbol>`. The gateway
immediately sends a `SNAP` baseline, then streams `DEPTH` updates whenever
the top levels change. `SYM=*` is not valid for `DEPTH` — it is deliberately
excluded because a wildcard depth subscription could multiply one client's
bandwidth footprint by the entire symbol count.

**Typical use cases:** order-book visualisation (DOM/ladder widgets), simple
liquidity/depth analysis, teaching Level 2 concepts.

**Wire example:**

```text
SNAP|CH=DEPTH|SYM=AAPL|SEQ=1|TS=2026-06-30T09:30:00.000Z|LEVELS=10|BIDS=150.10:1200:3,150.09:800:2|ASKS=150.12:900:2,150.13:600:1
DEPTH|CH=DEPTH|SYM=AAPL|SEQ=2|TS=2026-06-30T09:30:00.500Z|LEVELS=10|BIDS=150.10:1400:4,150.09:800:2|ASKS=150.12:900:2,150.13:600:1
```

Each level in `BIDS`/`ASKS` is `PRICE:QTY:COUNT`, comma-separated, best price
first. `QTY` is the total resting quantity at that price; `COUNT` is how many
individual orders were aggregated into it.

The number of levels per side (`LEVELS`, default 10) is a gateway-wide
setting (`market_data_gateway.depth_levels`) — there is no per-client
override in CALF `1.0.0`. Not every gateway build supports `DEPTH` yet; check
`WELCOME|CH_SUPPORTED=` before relying on it (see "Connecting and
subscribing" below).

---

### Channel summary

| Channel | Message type | Baseline `SNAP`? | `SYM=*` wildcard? | Primary data |
|---------|-------------|-------------------|-------------------|--------------|
| `TOP`   | `MD`        | Yes (per-symbol burst when `SYM=*`) | Yes (1.0.0+)     | Best bid/ask/last per symbol |
| `TRADE` | `TRADE`     | No                | Yes (1.0.0+)      | Trade price, qty, aggressor side |
| `STATE` | `STATE`     | Yes               | Yes               | Session phase; symbol halt/resume |
| `INDEX` | `IDX`       | Yes (1.0.0+)      | No                | Index level, day stats |
| `DEPTH` | `DEPTH`     | Yes               | No                | Aggregated multi-level order book (Level 2) |


## When to use CALF — protocol comparison

EduMatcher offers several ways to obtain market data.  The right choice depends
on your context.

| Approach | Transport | Data available | Best for | Not suitable for |
|----------|-----------|---------------|----------|------------------|
| **CALF** (`pm-md-gwy`) | TCP text | TOP, TRADE, STATE, INDEX, DEPTH | External clients; any language; snapshot + replay | Internal Python code that already imports edumatcher |
| **Internal ZMQ PUB** (`:5556`) | ZMQ binary | Raw engine events (`book.*`, `trade.executed`, …) | Internal Python processes (`pm-stats`, bots) | External clients; languages without a ZMQ binding |
| **REST API** (`pm-api-gwy`) | HTTP/JSON | Snapshot queries; order status | Web dashboards; one-shot queries | Low-latency streaming; high-frequency incremental data |
| **WebSocket API** (`pm-api-gwy`) | WebSocket/JSON | Streaming market data (JSON) | Browser-based UIs; REST-native stacks | Latency-critical paths |
| **RALF** (`pm-ralf-gwy`) | TCP text | Post-trade events (fills, positions, clearing) | External clearing, drop-copy, audit consumers | Pre-trade market data; top-of-book streaming |
| **Drop Copy** (ZMQ `:5557`) | ZMQ binary | Fill events only | Internal fill-monitoring processes | General market data |

**Key rules:**

- External client in any language → **use CALF**.
- Internal Python process that imports `edumatcher` → use ZMQ PUB directly via `make_subscriber()`.
- Web UI → use the REST/WebSocket API gateway.
- Post-trade / clearing / audit → use RALF.


## Connecting and subscribing

Every CALF session follows this sequence:

```mermaid
sequenceDiagram
    participant C as Client
    participant G as pm-md-gwy

    C->>G: TCP connect :5570
    C->>G: HELLO|CLIENT=mybot|PROTO=CALF1
    G-->>C: WELCOME|PROTO=CALF1|GW=md-gwy01|HBINT=1|REPLAY=30|SYMBOLS=AAPL,MSFT|CH_SUPPORTED=TOP,TRADE,STATE,INDEX,DEPTH
    C->>G: SUB|CH=TOP,TRADE|SYM=AAPL,MSFT
    G-->>C: SNAP|CH=TOP|SYM=AAPL|SEQ=100|...
    G-->>C: SNAP|CH=TOP|SYM=MSFT|SEQ=55|...
    loop Live stream
        G-->>C: MD / TRADE / HB
    end
    C->>G: EXIT
```

### Step 1 — Send `HELLO`

```text
HELLO|CLIENT=mybot|PROTO=CALF1
```

`CLIENT` is a free-text identifier (max 32 chars) used for gateway logging.
`PROTO` must be exactly `CALF1` — this does **not** change between CALF
`1.0.0` and earlier gateways.  The gateway replies with `WELCOME` or closes
the connection on protocol error.  Check the `SYMBOLS` field in `WELCOME` for
the list of configured symbols — useful for building a dynamic subscription
list.  Also check `CH_SUPPORTED`: if present, it lists every channel this
gateway build actually supports (e.g. `TOP,TRADE,STATE,INDEX,DEPTH`).  If
`CH_SUPPORTED` is **absent**, assume a pre-`1.0.0` gateway that only supports
`TOP`/`TRADE`/`STATE` and no `SYM=*` wildcard outside `STATE`.

### Step 2 — Subscribe

```text
SUB|CH=TOP,TRADE|SYM=AAPL,MSFT
```

Multiple channels and symbols are comma-separated.  The subscription is the
Cartesian product of all listed channels × symbols.  Multiple `SUB` lines are
cumulative; existing subscriptions are preserved.

Since CALF `1.0.0`, `SYM=*` also works for `TOP` and `TRADE`:

```text
SUB|CH=TOP,TRADE,STATE|SYM=*
```

### Step 3 — Receive snapshots

For each new `TOP`, `STATE`, `INDEX`, or `DEPTH` subscription pair the
gateway sends an immediate `SNAP`.  Store the `SEQ` — it is your baseline
sequence number for that stream.  `TRADE` never gets a baseline `SNAP`.

A wildcard `TOP` subscription (`SYM=*`) is the one exception to "one `SNAP`
per pair": it produces **one `SNAP` per symbol the gateway currently knows
about**, not a single `SNAP` with a literal `SYM=*`. Expect a burst of
per-symbol `SNAP` lines, then live `MD` for any symbol — including symbols
that only become known later — through that one subscription.

Build a per-symbol state dictionary seeded from the `SNAP`, then merge each
subsequent `MD` into it.

### Step 4 — Cancel subscriptions

```text
UNSUB|CH=TRADE|SYM=MSFT
```

`UNSUB` is idempotent — removing a pair you are not subscribed to has no effect.

### Step 5 — Handle heartbeats

When the stream is quiet the gateway sends periodic heartbeats (`HB|TS=...`).
You can probe with `PING`; the gateway replies `PONG`.  If the gateway receives
no inbound traffic for `idle_timeout_sec` seconds it closes the connection.

### Step 6 — Disconnect

```text
EXIT
```


## Subscribing to a targeted subset

Subscribe only to what you need to minimise gateway-side fanout and parsing
overhead.

| Goal | `SUB` line |
|------|------------|
| Best bid/ask for one symbol | `SUB\|CH=TOP\|SYM=AAPL` |
| Trade tape for one symbol | `SUB\|CH=TRADE\|SYM=AAPL` |
| Everything for one symbol | `SUB\|CH=TOP,TRADE,STATE\|SYM=AAPL` |
| Session state only (all symbols) | `SUB\|CH=STATE\|SYM=*` |
| Top-of-book for every symbol | `SUB\|CH=TOP\|SYM=*` (CALF `1.0.0`+) |
| Market-wide trade tape | `SUB\|CH=TRADE\|SYM=*` (CALF `1.0.0`+) |
| Top and trades for several symbols | `SUB\|CH=TOP,TRADE\|SYM=AAPL,MSFT,GOOG` |
| Index level | `SUB\|CH=INDEX\|SYM=EDU50` |
| Order book ladder for one symbol | `SUB\|CH=DEPTH\|SYM=AAPL` (CALF `1.0.0`+) |
| Build up incrementally | Multiple `SUB` lines are cumulative |

!!! tip "Symbol discovery"
    The `SYMBOLS` field in `WELCOME` lists all configured symbols as a
    comma-separated string.  Use it instead of hard-coding symbol names.

!!! tip "Capability discovery"
    The `CH_SUPPORTED` field in `WELCOME` lists every channel this gateway
    build supports (e.g. `TOP,TRADE,STATE,INDEX,DEPTH`). Check it before
    subscribing to `DEPTH` or relying on the `TOP`/`TRADE` wildcard so your
    client degrades gracefully against an older gateway instead of handling
    an `ERR` reactively.


## Gap detection and replay recovery

Every stream has an independent, monotonically increasing `SEQ` starting at 1.
Track `last_seq[(CH, SYM)]` on every received message and check:

```
gap detected when:  received_seq != last_seq + 1
```

**Recovery option 1 — replay within window**

Reconnect with `RESUME=1` for a single stream:

```text
HELLO|CLIENT=mybot|PROTO=CALF1|RESUME=1|CH=TOP|SYM=AAPL|LASTSEQ=99
```

The gateway replays all events with `SEQ > 99` that are still inside the replay
window (`replay_window_sec`, default 30 s), then continues live.

**Recovery option 2 — replay miss**

If the requested `LASTSEQ` is older than the window the gateway sends
`ERR|CODE=REPLAY_MISS|...` followed by a fresh `SNAP`.  Accept the `SNAP` and
reset your local state.

!!! note
    `RESUME=1` applies to **one stream per `HELLO`**.  For multi-stream
    recovery, reconnect normally and re-`SUB`; the gateway sends fresh `SNAP`s.


## Python subscriber example

The `examples/calf/` directory contains ready-to-run Python and C libraries.

```
examples/calf/
├── calf_parser.py        # parser + serializer library
├── calf_subscriber.py    # full working subscriber example
├── calf_parser.h         # C parser library
├── calf_parser.c
├── calf_subscriber.c     # C subscriber example
└── Makefile
```

### Zero-dependency minimal client

For a quick smoke-test or a self-contained script that has no local imports:

```python
import socket

sock = socket.create_connection(("127.0.0.1", 5570))
sock.sendall(b"HELLO|CLIENT=bot01|PROTO=CALF1\n")
sock.sendall(b"SUB|CH=TOP,TRADE|SYM=AAPL\n")

buf = bytearray()
while True:
    chunk = sock.recv(4096)
    if not chunk:
        break
    buf.extend(chunk)
    while b"\n" in buf:
        idx = buf.index(b"\n")
        line = buf[:idx].decode("utf-8").strip()
        del buf[:idx + 1]
        if line:
            print(line)
```

!!! warning "TCP is a byte stream"
    Never assume one `recv()` equals one message.  Always buffer and split on
    newlines as shown above.

### Using the `calf_parser.py` library

`calf_parser.py` in `examples/calf/` provides `parse_calf_line` and
`build_calf_line`:

```python
from calf_parser import parse_calf_line, build_calf_line, CalfMessage

# Parse a line received from the gateway
msg: CalfMessage = parse_calf_line("MD|CH=TOP|SYM=AAPL|SEQ=101|BID=150.11|BIDSZ=1400")
print(msg.msg_type)   # "MD"
print(msg.fields)     # {"CH": "TOP", "SYM": "AAPL", "SEQ": "101", ...}

# Build a line to send to the gateway
line: str = build_calf_line("SUB", {"CH": "TOP,TRADE", "SYM": "AAPL"})
# → "SUB|CH=TOP,TRADE|SYM=AAPL\n"
```

### Annotated end-to-end subscriber

This snippet is a condensed version of `calf_subscriber.py` annotated to
highlight the key CALF patterns.

```python
import socket
from calf_parser import parse_calf_line, build_calf_line


class LineReader:
    """Buffer TCP bytes and yield complete CALF lines."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.buf = bytearray()

    def recv_line(self) -> str:
        while True:
            nl = self.buf.find(b"\n")
            if nl >= 0:
                line = bytes(self.buf[:nl])
                del self.buf[:nl + 1]
                return line.decode("utf-8", errors="replace")
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("gateway closed connection")
            self.buf.extend(chunk)


def send(sock: socket.socket, msg_type: str, fields: dict[str, str]) -> None:
    sock.sendall(build_calf_line(msg_type, fields).encode())


with socket.create_connection(("127.0.0.1", 5570), timeout=5) as sock:
    reader = LineReader(sock)

    # Authenticate
    send(sock, "HELLO", {"CLIENT": "mybot", "PROTO": "CALF1"})
    welcome = parse_calf_line(reader.recv_line())
    assert welcome.msg_type == "WELCOME", f"unexpected: {welcome}"
    known_symbols = welcome.fields.get("SYMBOLS", "").split(",")
    print(f"Connected. Gateway knows: {known_symbols}")

    # Subscribe
    send(sock, "SUB", {"CH": "TOP,TRADE", "SYM": "AAPL,MSFT"})
    send(sock, "SUB", {"CH": "STATE", "SYM": "*"})

    # Per-stream state
    top: dict[str, dict[str, str]] = {}           # symbol → current top fields
    last_seq: dict[tuple[str, str], int] = {}     # (CH, SYM) → last seen SEQ

    while True:
        msg = parse_calf_line(reader.recv_line())

        if msg.msg_type in ("MD", "TRADE", "STATE", "IDX", "DEPTH", "SNAP"):
            ch  = msg.fields.get("CH", "")
            sym = msg.fields.get("SYM", "")
            seq = int(msg.fields.get("SEQ", "0"))

            # Gap check
            prev = last_seq.get((ch, sym))
            if prev is not None and seq != prev + 1:
                print(f"GAP on ({ch},{sym}): expected {prev + 1}, got {seq}")
                # → trigger recovery: reconnect with RESUME=1
            last_seq[(ch, sym)] = seq

            # This example only subscribes to TOP/TRADE/STATE, so it only
            # special-cases CH=="TOP" here. A SNAP for CH=="INDEX" or
            # CH=="DEPTH" carries the same field shape as the IDX/DEPTH
            # message respectively (see the elif branches below) — seed
            # local state for those the same way if you subscribe to them.
            if msg.msg_type == "SNAP" and ch == "TOP":
                # Seed local state from baseline
                top[sym] = {k: v for k, v in msg.fields.items()
                            if k in ("BID", "BIDSZ", "ASK", "ASKSZ", "LAST", "LASTSZ")}
                print(f"SNAP  {sym}: {top[sym]}")

            elif msg.msg_type == "MD":
                # Merge incremental update
                top.setdefault(sym, {}).update(
                    {k: v for k, v in msg.fields.items()
                     if k in ("BID", "BIDSZ", "ASK", "ASKSZ", "LAST", "LASTSZ")}
                )
                print(f"TOP   {sym}: BID={top[sym].get('BID')} ASK={top[sym].get('ASK')}")

            elif msg.msg_type == "TRADE":
                print(f"TRADE {sym}: PX={msg.fields['PX']} QTY={msg.fields['QTY']} SIDE={msg.fields['SIDE']}")

            elif msg.msg_type == "STATE":
                print(f"STATE {sym}: {msg.fields.get('PREV','?')} → {msg.fields['SESSION']}")

            elif msg.msg_type == "IDX":
                print(f"IDX   {sym}: LEVEL={msg.fields['LEVEL']} CHG={msg.fields.get('CHG','n/a')}")

            elif msg.msg_type == "DEPTH":
                bids = msg.fields.get("BIDS", "")
                asks = msg.fields.get("ASKS", "")
                n_bids = bids.count(",") + 1 if bids else 0
                n_asks = asks.count(",") + 1 if asks else 0
                print(f"DEPTH {sym}: {n_bids} bid levels, {n_asks} ask levels")

        elif msg.msg_type == "HB":
            pass  # heartbeat — ignore or use for liveness tracking

        elif msg.msg_type == "ERR":
            print(f"ERR {msg.fields['CODE']}: {msg.fields.get('MSG','')}")
            if msg.fields["CODE"] == "SLOW_CLIENT":
                break  # terminal — must reconnect
```

### Run the bundled examples

```bash
cd docs/examples/calf

# Subscribe to TOP and TRADE for one symbol
python3 calf_subscriber.py --host 127.0.0.1 --port 5570 \
    --channels TOP,TRADE --symbols AAPL

# Multiple channels and symbols
python3 calf_subscriber.py --channels TOP,TRADE,STATE --symbols AAPL,MSFT

# Reconnect with single-stream replay
python3 calf_subscriber.py --resume --resume-ch TOP --resume-sym AAPL --lastseq 1042
```

For a C client (useful for latency-sensitive or non-Python environments):

```bash
cd docs/examples/calf && make
./calf_subscriber 127.0.0.1 5570
```


## Common errors and fixes

| Error code        | Typical cause                                    | Action                                            |
|-------------------|--------------------------------------------------|---------------------------------------------------|
| `AUTH_REQUIRED`   | `SUB` sent before `HELLO`                        | Send `HELLO` first                                |
| `PROTO_MISMATCH`  | Wrong or missing `PROTO`                         | Use `PROTO=CALF1`                                 |
| `INVALID_CHANNEL` | Unknown `CH` value                               | Use `TOP`, `TRADE`, `STATE`, `INDEX`, or `DEPTH`  |
| `INVALID_SYMBOL`  | Unknown symbol, or `SYM=*` used with `INDEX`/`DEPTH` | Use configured symbols; `SYM=*` only for `STATE`/`TOP`/`TRADE` |
| `SUB_LIMIT`       | Too many subscribed symbols                      | Reduce requested symbol set                       |
| `REPLAY_MISS`     | Requested replay is outside buffer window        | Accept fresh `SNAP` and reset local baseline      |
| `SLOW_CLIENT`     | Client cannot drain the outbound stream fast enough | Reconnect and process faster; terminal error   |
| `BAD_MESSAGE`     | Malformed or oversized line (> 4096 bytes)       | Fix line syntax/framing                           |


## Operational checklist

1. Confirm `pm-engine` is running and publishing (`pm-engine --verbose`)
2. Confirm `pm-md-gwy` is running
3. Confirm TCP port is reachable (`nc 127.0.0.1 5570`)
4. Confirm `HELLO` receives `WELCOME`
5. Confirm `SUB` receives expected `SNAP` and live flow
6. Track `SEQ` per stream; on reconnect use `RESUME=1` with `LASTSEQ`
7. On `REPLAY_MISS`: accept the recovery `SNAP` and reset local state


## See also

- [External Protocols Overview](19-protocol-overview.md) — ALF, BALF, CALF, RALF at a glance
- [Appendix — CALF Protocol](92-app-calf-protocol.md) — normative wire format, full field tables, sequencing rules
- [API Gateway](21-api-gateway.md) — REST and WebSocket market data alternative
- [Post-Trade Dissemination (RALF)](18-post-trade.md) — fills and post-trade events
- [Messages Reference](09-messages.md#calf-tcp-protocol-pm-md-gwy) — CALF messages in the full message catalogue
- [Processes](10-processes.md) — where `pm-md-gwy` sits in the process model



## Prerequisites

- `pm-engine` running
- `pm-md-gwy` running
- symbols configured in `engine_config.yaml`

Optional but recommended in config:

```yaml
market_data_gateway:
  enabled: true
  name: "md-gwy01"
  bind_address: "0.0.0.0"
  port: 5570
  heartbeat_interval_sec: 1
  idle_timeout_sec: 5
  replay_window_sec: 30
  max_symbols_per_client: 200
  max_client_queue: 10000
  depth_levels: 10
```


## Start the gateway

Installed mode:

```bash
pm-engine --verbose
pm-md-gwy --config engine_config.yaml
```

Developer mode:

```bash
poetry run pm-engine --verbose
poetry run pm-md-gwy --config engine_config.yaml
```


## Quick connect test (manual)

Use `nc` (or `telnet`) to validate the line protocol quickly:

```bash
nc 127.0.0.1 5570
```

Then send:

```text
HELLO|CLIENT=demo01|PROTO=CALF1
SUB|CH=TOP,TRADE|SYM=AAPL
```

Expected pattern:

1. `WELCOME|...`
2. `SNAP|CH=TOP|SYM=AAPL|...`
3. `MD|...` when top of book changes
4. `TRADE|...` when a trade executes
5. `HB|...` when the stream is otherwise quiet


## Minimal Python third-party client

```python
import socket

sock = socket.create_connection(("127.0.0.1", 5570))
sock.sendall(b"HELLO|CLIENT=bot01|PROTO=CALF1\n")
sock.sendall(b"SUB|CH=TOP,TRADE|SYM=AAPL\n")

buf = bytearray()
while True:
    chunk = sock.recv(4096)
    if not chunk:
        break
    buf.extend(chunk)
    while b"\n" in buf:
        idx = buf.index(b"\n")
        line = buf[:idx].decode("utf-8").strip()
        del buf[:idx + 1]
        if line:
            print(line)
```

Important: CALF uses TCP stream framing. Never assume one `recv()` equals one message.


## Recovery on reconnect

If your client disconnects, reconnect with `RESUME=1` for one stream:

```text
HELLO|CLIENT=bot01|PROTO=CALF1|RESUME=1|CH=TOP|SYM=AAPL|LASTSEQ=1042
```

Gateway behavior:

- replay hit: emits missing messages `SEQ > LASTSEQ`
- replay miss: emits `ERR|CODE=REPLAY_MISS|...` then a fresh `SNAP`

For multi-stream recovery, reconnect with normal `HELLO` and resubscribe.


## Common errors and fixes

| Error code        | Typical cause                                   | Action                                           |
|-------------------|-------------------------------------------------|--------------------------------------------------|
| `AUTH_REQUIRED`   | `SUB` sent before `HELLO`                       | Send `HELLO` first                               |
| `PROTO_MISMATCH`  | Wrong or missing `PROTO`                        | Use `PROTO=CALF1`                                |
| `INVALID_CHANNEL` | Unknown `CH`                                    | Use `TOP`, `TRADE`, `STATE`, `INDEX`, or `DEPTH` |
| `INVALID_SYMBOL`  | Unknown symbol, or `SYM=*` used with `INDEX`/`DEPTH` | Use configured symbols; `SYM=*` only for `STATE`/`TOP`/`TRADE` |
| `SUB_LIMIT`       | Too many subscribed symbols                     | Reduce requested symbol set                      |
| `REPLAY_MISS`     | Requested replay is outside buffer window       | Accept fresh `SNAP` and continue                 |
| `SLOW_CLIENT`     | Client cannot drain outbound stream fast enough | Reconnect and process faster                     |
| `BAD_MESSAGE`     | Malformed line or oversize line                 | Fix line syntax/framing                          |


## Operational checklist

1. Verify engine is running and publishing (`pm-engine --verbose`)
2. Verify gateway is running (`pm-md-gwy`)
3. Verify TCP port is reachable (`nc 127.0.0.1 5570`)
4. Confirm `HELLO` then `WELCOME` handshake
5. Confirm `SUB` creates expected `SNAP`
6. Track per-stream `SEQ` and trigger recovery on gaps


## Dedicated Gateway Runbook (pm-md-gwy)

Use this section as a focused operator runbook for the running CALF gateway.

### Start commands

Installed mode:

```bash
pm-engine --verbose
pm-md-gwy --config engine_config.yaml
```

Developer mode:

```bash
poetry run pm-engine --verbose
poetry run pm-md-gwy --config engine_config.yaml
```

### Minimal client probe

Manual probe using `nc`:

```bash
nc 127.0.0.1 5570
```

Then send:

```text
HELLO|CLIENT=ops01|PROTO=CALF1
SUB|CH=TOP,TRADE|SYM=AAPL
```

Expected sequence:

1. `WELCOME|...`
2. `SNAP|CH=TOP|SYM=AAPL|...`
3. live `MD|...` and `TRADE|...`
4. periodic `HB|...` while the stream is quiet

### Optional state-channel probe

To verify session and symbol-state routing, use wildcard state subscription:

```text
SUB|CH=STATE|SYM=*
```

Expected:

1. immediate `SNAP|CH=STATE|SYM=*|...`
2. live `STATE|...` transitions on session/halt/resume events

### Optional wildcard and DEPTH probes (CALF `1.0.0`+)

Check `WELCOME|CH_SUPPORTED=` first — these two channels are only guaranteed
on `1.0.0`+ gateways.

```text
SUB|CH=TRADE|SYM=*
SUB|CH=DEPTH|SYM=AAPL
```

Expected:

1. `TRADE|...` for every symbol on the market, no baseline `SNAP`
2. immediate `SNAP|CH=DEPTH|SYM=AAPL|LEVELS=...|BIDS=...|ASKS=...`, then
   `DEPTH|...` whenever the top price levels change

### Reconnect replay behavior

Single-stream resume probe:

```text
HELLO|CLIENT=ops01|PROTO=CALF1|RESUME=1|CH=TOP|SYM=AAPL|LASTSEQ=1042
```

Outcomes:

- replay hit: events with `SEQ > LASTSEQ`, then live continuation
- replay miss: `ERR|CODE=REPLAY_MISS`, followed by recovery `SNAP`

### Fast error triage

| Error code        | Typical cause                            | Action                                           |
|-------------------|------------------------------------------|--------------------------------------------------|
| `AUTH_REQUIRED`   | `SUB` before successful `HELLO`          | Authenticate first                               |
| `PROTO_MISMATCH`  | Wrong or missing protocol value          | Use `PROTO=CALF1`                                |
| `INVALID_CHANNEL` | Unsupported `CH` value                   | Use `TOP`, `TRADE`, `STATE`, `INDEX`, `DEPTH`    |
| `INVALID_SYMBOL`  | Unknown symbol, or `SYM=*` with `INDEX`/`DEPTH` | Use configured symbols; `SYM=*` only for `STATE`/`TOP`/`TRADE` |
| `REPLAY_MISS`     | Replay point outside retention           | Accept `SNAP` and reset local baseline           |
| `SLOW_CLIENT`     | Client too slow to drain stream          | Reconnect and increase consume throughput        |
| `BAD_MESSAGE`     | Malformed line syntax                    | Fix message format                               |

### Operator checklist

1. Confirm engine is publishing `book.*`, `trade.executed`, and session/circuit-breaker events
2. Confirm `pm-md-gwy` is running
3. Confirm TCP reachability (`nc 127.0.0.1 5570`)
4. Confirm `HELLO` receives `WELCOME`
5. Confirm `SUB` receives expected `SNAP` and live flow
6. Track `SEQ`; on reconnect use `RESUME=1` with `LASTSEQ`


## See also

- [External Protocols Overview](19-protocol-overview.md)
- [Appendix - CALF Protocol](92-app-calf-protocol.md)
- [Processes](10-processes.md)
