# ALF example clients and parser libraries

These examples demonstrate how to connect to `pm-alf-gwy` as an **external
client** over TCP.  They replicate the workflow of `pm-alf-console` but without
any ZeroMQ or `edumatcher` package dependency — only a plain TCP socket and
the ALF text protocol.

```
alf/
├── python/
│   ├── alf_parser.py       # Protocol library: parse, build, AlfSession
│   └── alf_client.py       # Interactive client with tab-completion
└── c/
    ├── alf_parser.h        # C library header
    ├── alf_parser.c        # C library implementation
    ├── alf_client.c        # Interactive C client with readline
    └── Makefile            # Build helper
```


## Prerequisites

**Engine and gateway running:**

```bash
pm-engine --verbose
pm-alf-gwy
```

`TRADER01` must be listed in `engine_config.yaml` under `participants`.

**Python:** Python 3.9+, no extra packages needed.

**C:** GNU readline.
- **macOS:** `brew install readline`
- **Linux:** `sudo apt install libreadline-dev`


## ALF wire format

```
VERB|KEY=VALUE|KEY=VALUE\n
```

- Command verbs and field keys are case-insensitive (normalized to uppercase)
- Fields without `=` are silently skipped
- Duplicate keys: last value wins

These normalization rules apply to commands received by the gateway. The
example parsers uppercase response verbs and keys, but preserve value case:
copy each `ORDER_ID` exactly into subsequent `AMEND` and `CANCEL` requests.
ALF prices remain decimal display prices; internal engine tick fields and
message-envelope changes do not change this TCP command format.


## Python

### Library: `alf_parser.py`

```python
from alf_parser import parse_alf_line, build_alf_line, AlfSession, AlfMessage

# Parse one line received from the gateway
msg: AlfMessage = parse_alf_line("ACK|ORDER_ID=abc|ACCEPTED=FALSE|REJECT_CODE=ORDER_NOT_FOUND|REASON=missing")
print(msg.msg_type)    # "ACK"
print(msg.fields)      # {"ORDER_ID": "abc", "ACCEPTED": "FALSE", "REJECT_CODE": "ORDER_NOT_FOUND", ...}

# Build a line to send
line: str = build_alf_line("NEW", {"SYM": "AAPL", "SIDE": "BUY",
                                    "TYPE": "LIMIT", "QTY": "100", "PRICE": "150.00", "TAG": "ORDER-001"})
# → "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TAG=ORDER-001\n"

# Full session: connect, HELLO/WELCOME handshake, send/recv
session = AlfSession.connect("127.0.0.1", 5565, "TRADER01")
print(session.gateway_id)          # "TRADER01"
print(session.welcome.gw_name)     # "alf-gwy01"
session.send("SYMBOLS")
msg = session.recv_msg()           # first line of SYMBOLS response
session.close()
```

`connect(..., timeout=5.0)` bounds the Python handshake and closes the socket
on failure. After a successful handshake, reads are blocking. Library users
must send `PING` periodically (more often than `WELCOME|IDLE`) themselves;
both interactive clients do this automatically.

### Interactive client: `alf_client.py`

```bash
cd docs/examples/alf/python

# Connect to local gateway
python3 alf_client.py --id TRADER01

# Connect to remote gateway
python3 alf_client.py --host 10.0.0.5 --port 5565 --id TRADER01

# Custom client name in gateway logs
python3 alf_client.py --id MM01 --client "my-mm-bot"
```

At the prompt:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TAG=order-001
[TRADER01]> AMEND|ID=<order-id>|PRICE=151.00|RTAG=req-001
[TRADER01]> CANCEL|ID=<order-id>|RTAG=req-002
[TRADER01]> SYMBOLS
[TRADER01]> ORDERS
[TRADER01]> POS
[TRADER01]> SESSION
[TRADER01]> STATUS
[TRADER01]> DC|STATE=ON
[TRADER01]> DC|STATE=OFF
[TRADER01]> HELP
[TRADER01]> EXIT
```

`AMEND` and `CANCEL` need the order's full 32-character ID, exactly as the
`ACK` line or the `ORDERS` table prints it.

Tab completes command verbs, field names, and enum values.
Command history is saved to `~/.alf_client_history`.

The clients display stop `TRIGGERED` notifications before subsequent fills,
and show fill trade IDs and maker/taker `LIQUIDITY` when supplied. Drop-copy
`DC_FILL` messages are displayed separately and never booked into the local
position ledger a second time. Local `POS` starts with this connection's
fills, not the gateway's historical holdings; use `POS|GW=<id>` for the
engine's position snapshot. Local P&L is realized P&L, and average cost is
reset to the execution price when a fill reverses the position.


## C

### Build

```bash
cd docs/examples/alf/c
make
```

### Run

```bash
# Connect to local gateway
./alf_client --id TRADER01

# Connect to remote gateway
./alf_client --host 10.0.0.5 --port 5565 --id TRADER01

# Disable ANSI colour codes
./alf_client --id TRADER01 --no-color
```

The C client supports the same commands as the Python client.
Tab-completion covers command verbs, field names, and common enum values.
Its handshake receive timeout is five seconds. As a bounded teaching example,
it stores up to 256 cached orders, 512 symbols/positions, and 512 rows in one
query response. Parser storage allows 64 fields, 63-byte keys, and 511-byte
values; overlong fields and lines are rejected rather than silently truncated.

### C library usage

```c
#include "alf_parser.h"

/* Parse */
char line[] = "ACK|ORDER_ID=abc|ACCEPTED=TRUE";
alf_message_t msg;
alf_parse_line(line, &msg);
printf("%s\n", msg.msg_type);                       /* "ACK" */
printf("%s\n", alf_get_field(&msg, "ACCEPTED"));    /* "TRUE" */

/* Build */
const char *kv[] = {"SYM", "AAPL", "SIDE", "BUY",
                    "TYPE", "LIMIT", "QTY", "100", "PRICE", "150.00", "TAG", "ORDER-001", NULL};
char buf[4096];
alf_build_line(buf, sizeof(buf), "NEW", kv);
/* → "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TAG=ORDER-001\n" */
write(sockfd, buf, strlen(buf));
```


## Differences from `pm-alf-console`

| Feature | `pm-alf-console` | `alf_client` (Python/C) |
|---------|-----------------|------------------------|
| Transport | ZMQ PUSH/SUB directly | TCP via `pm-alf-gwy` |
| Machine | Same host as engine | Any host |
| Dependencies | `edumatcher` package + ZMQ | Python stdlib (including readline), or C + GNU readline |
| P&L / POS | From local fill tracking | From local fill tracking |
| `POS\|GW=<id>` (query another gateway) | Yes | Yes |
| STATUS | Rich terminal display | Text table |
| QLEGS | Yes (local cache) | Yes (engine round trip) |
| Tab completion | Full context-aware | Commands, fields, enums |

## Verification

From the repository root, with the development environment installed:

```bash
poetry run pytest tests/test_alf_examples.py --no-cov
```

The tests compile and run the C code, test parser/session behavior, and drive
both interactive clients through the TCP gateway into the real engine handlers.
Covered workflows include order entry, amendment, fills and position reversals,
cancellation, OCO/combo orders, quotes, queries, stop triggering, drop-copy
delivery, validation errors, and clean exit.
