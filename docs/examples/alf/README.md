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
pm-alf-gwy --config engine_config.yaml
```

`TRADER01` must be listed in `engine_config.yaml` under `gateways.alf`.

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


## Python

### Library: `alf_parser.py`

```python
from alf_parser import parse_alf_line, build_alf_line, AlfSession, AlfMessage

# Parse one line received from the gateway
msg: AlfMessage = parse_alf_line("ACK|ORDER_ID=abc|ACCEPTED=TRUE|SYMBOL=AAPL")
print(msg.msg_type)    # "ACK"
print(msg.fields)      # {"ORDER_ID": "ABC", "ACCEPTED": "TRUE", "SYMBOL": "AAPL"}

# Build a line to send
line: str = build_alf_line("NEW", {"SYM": "AAPL", "SIDE": "BUY",
                                    "TYPE": "LIMIT", "QTY": "100", "PRICE": "150.00"})
# → "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00\n"

# Full session: connect, HELLO/WELCOME handshake, send/recv
session = AlfSession.connect("127.0.0.1", 5565, "TRADER01")
print(session.gateway_id)          # "TRADER01"
print(session.welcome.gw_name)     # "alf-gwy01"
session.send("SYMBOLS")
msg = session.recv_msg()           # first line of SYMBOLS response
session.close()
```

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
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00
[TRADER01]> AMEND|ID=<order-id>|PRICE=151.00
[TRADER01]> SYMBOLS
[TRADER01]> ORDERS
[TRADER01]> POS
[TRADER01]> STATUS
[TRADER01]> HELP
[TRADER01]> EXIT
```

Tab completes command verbs, field names, and enum values.
Command history is saved to `~/.alf_client_history`.


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
                    "TYPE", "LIMIT", "QTY", "100", "PRICE", "150.00", NULL};
char buf[4096];
alf_build_line(buf, sizeof(buf), "NEW", kv);
/* → "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00\n" */
write(sockfd, buf, strlen(buf));
```


## Differences from `pm-alf-console`

| Feature | `pm-alf-console` | `alf_client` (Python/C) |
|---------|-----------------|------------------------|
| Transport | ZMQ PUSH/SUB directly | TCP via `pm-alf-gwy` |
| Machine | Same host as engine | Any host |
| Dependencies | `edumatcher` package + ZMQ | stdlib only |
| P&L / POS | From local fill tracking | From local fill tracking |
| STATUS | Rich terminal display | Text table |
| QLEGS | Yes (local cache) | Not available |
| Tab completion | Full context-aware | Commands, fields, enums |
