# ALF TCP Gateway Protocol Training

## Objective

Train on end-to-end usage of the ALF protocol through `pm-alf-gwy` using OS
CLI tools, the example parser libraries, and the interactive example clients.

You will practise:

- generating an `alf_gateway:` config with `pm-config-gen`
- starting `pm-alf-gwy` and verifying the port is listening using OS tools
- testing connectivity and the full session lifecycle manually with `nc` and `telnet`
- submitting, amending, and cancelling orders over a raw TCP session
- using the Python `alf_parser.py` / `alf_client.py` examples for scripted and interactive access
- building and running the C `alf_client` example
- operating control commands (`PING`, `ORDERS`, `QBOOT`, `KILL`)
- diagnosing error conditions from the `ERR|CODE=...` vocabulary

 

## Prerequisites

- Chapters 01-25 completed.
- Engine running and configured with at least two gateway IDs.
- `pm-alf-gwy` available in the environment (`poetry run pm-alf-gwy` or installed via `pipx`).
- Support libraries and clients available in `docs/examples/alf`:
  - `python/alf_parser.py`, `python/alf_client.py`
  - `c/alf_parser.h`, `c/alf_parser.c`, `c/alf_client.c`, `c/Makefile`

Recommended startup terminals:

1. Engine: `pm-engine --verbose`
2. ALF gateway: `pm-alf-gwy`
3. One or more client terminals for connection exercises

 

## Background

`pm-alf-gwy` is the TCP gateway for the ALF (ALmost Fix) protocol.
It accepts multiple simultaneous connections from external bots and scripts
written in any language, and translates ALF commands into the same engine ZMQ
messages used by the interactive `pm-alf-console` terminal.

In this chapter, the most important operational ideas are:

- Session establishment: `HELLO` → auth round-trip → `WELCOME` with automatic `SYMBOLS` bootstrap
- Authenticated order entry and management: `NEW`, `AMEND`, `CANCEL`, `QUOTE`
- Gateway kill-switch: `KILL` (with optional `SYM=` scope)
- Bootstrap state recovery: `ORDERS` and `QBOOT`
- Liveness: `PING`/`PONG` and unsolicited `HB` heartbeat lines
- Error escalation: per-error `ERR|CODE=...` and sliding-window forced disconnect

 

## Exercise 1: Generate a Config That Enables pm-alf-gwy

Generate `engine_config.yaml` with the `alf_gateway:` section enabled:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --gateways TRADER01 TRADER02 MM01:MARKET_MAKER \
  --alf-gateway \
  --alf-gateway-port 5565 \
  --alf-gateway-bind-address 127.0.0.1 \
  --output engine_config.yaml
```

Inspect the generated section:

```bash
grep -A15 '^alf_gateway:' engine_config.yaml
```

Expected output includes:

```yaml
alf_gateway:
  enabled: true
  port: 5565
  bind_address: 127.0.0.1
  heartbeat_interval_sec: 5
  idle_timeout_sec: 30
```

Start processes with that config:

```bash
pm-engine --verbose --config engine_config.yaml
pm-alf-gwy --config engine_config.yaml
```

:material-checkbox-blank-outline: Checkpoint: `pm-alf-gwy` starts, logs that it is listening on port 5565, and reports a successful engine ZMQ connection.

 

## Exercise 2: Verify the Port Is Listening with CLI Tools

Before writing any client code, confirm the gateway is actually bound to the
configured port using OS tools. This is the fastest way to rule out startup
failures, bind-address mismatches, and firewall issues.

**macOS:**

```bash
# lsof — shows the process name and PID holding the port
sudo lsof -iTCP:5565 -sTCP:LISTEN

# BSD netstat (ships with macOS)
netstat -an | grep LISTEN | grep 5565
```

Expected: a line with `pm-alf-gwy` (or `Python` if running under Poetry) and `LISTEN`.

**Linux:**

```bash
# ss — preferred on modern Linux
ss -tlnp 'sport = :5565'

# lsof
sudo lsof -iTCP:5565 -sTCP:LISTEN

# netstat (older distributions)
netstat -tlnp | grep 5565
```

Both commands should show a process bound to `*:5565` or `127.0.0.1:5565`.

If no output appears:

- the gateway is not running or failed to start — check logs
- `alf_gateway.enabled` may be `false` in the config
- the port may differ from what you expect — re-run `grep -A5 'alf_gateway:' engine_config.yaml`
- `pm-engine` must be running before `pm-alf-gwy` can complete its ZMQ handshake

:material-checkbox-blank-outline: Checkpoint: at least one CLI command shows a process listening on port 5565.

 

## Exercise 3: Manual Handshake Probe with nc

Use `nc` (netcat) to open a raw TCP connection and type ALF lines by hand.
This verifies the full session lifecycle — HELLO, auth, WELCOME, SYMBOLS — with
no code.

```bash
nc 127.0.0.1 5565
```

Type these lines, pressing Enter after each:

```text
HELLO|CLIENT=test|PROTO=ALF1|ID=TRADER01
SYMBOLS
EXIT
```

Expected response pattern:

1. `WELCOME|PROTO=ALF1|GW=alf-gwy01|ID=TRADER01|HBINT=5|IDLE=30`
2. Automatic `SYMBOLS|COUNT=N` block with one `SYMBOL|SYM=...|TICK=...` per instrument
3. `END|TYPE=SYMBOLS`
4. `HB|TS=...` every 5 seconds when quiet
5. Connection closes after `EXIT`

Also try `ORDERS` to see the empty bootstrap snapshot:

```text
HELLO|CLIENT=test|PROTO=ALF1|ID=TRADER01
ORDERS
EXIT
```

Expected: `ORDERS|COUNT=0|GW=TRADER01` and `END|TYPE=ORDERS`.

:material-checkbox-blank-outline: Checkpoint: `nc` session reaches `WELCOME` and receives a valid `SYMBOLS` block and an `END|TYPE=ORDERS` line.

 

## Exercise 3B: telnet and Non-Interactive One-Liner

**telnet** (macOS / Linux):

```bash
telnet 127.0.0.1 5565
```

Type `HELLO|CLIENT=test|PROTO=ALF1|ID=TRADER01` and press Enter. `telnet`
echoes characters locally so the line looks doubled in the terminal — the
`WELCOME` response confirms the gateway accepted it. Press `Ctrl-]`, then
type `quit` to close.

**Non-interactive probe — useful in scripts or CI pipelines:**

```bash
printf 'HELLO|CLIENT=ci|PROTO=ALF1|ID=TRADER01\nSYMBOLS\nEXIT\n' \
  | nc 127.0.0.1 5565
```

Expected: the full session including `WELCOME`, `SYMBOLS` block, and
`END|TYPE=SYMBOLS` is printed to stdout and the command exits cleanly.

:material-checkbox-blank-outline: Checkpoint: the one-liner prints `WELCOME` and `END|TYPE=SYMBOLS` without interaction.

 

## Exercise 4: Submit and Cancel an Order over nc

Open a new `nc` session and type all commands (press Enter after each line):

```bash
nc 127.0.0.1 5565
```

```text
HELLO|CLIENT=manual|PROTO=ALF1|ID=TRADER01
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00
ORDERS
```

Expected behavior:

- `ACK|ORDER_ID=<uuid>|ACCEPTED=TRUE|...` arrives immediately after `NEW`
- `ORDERS` shows the resting order with `STATUS=NEW` and `REMAINING=100`
- If `MM01` is quoting, the order may fill immediately and `ORDERS` returns `COUNT=0`

Cancel the resting order using the UUID from the `ACK`:

```text
CANCEL|ID=<uuid>
```

Expected: `CANCELLED|ORDER_ID=<uuid>`.

Try amending before cancelling to see priority rules in action:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=200|PRICE=149.00
AMEND|ID=<uuid>|PRICE=149.50|QTY=150
```

Expected: `AMENDED|ORDER_ID=...|PRICE=149.50|QTY=150|REMAINING=150|PRIORITY_RESET=TRUE`

:material-checkbox-blank-outline: Checkpoint: you can submit, confirm, amend, and cancel an order using only raw TCP and a terminal.

 

## Exercise 5: Use the Python Interactive Client

`alf_client.py` provides an `pm-alf-console`-style interactive session over
TCP, with tab-completion, background event display, and local P&L tracking.

```bash
cd docs/examples/alf/python
python3 alf_client.py --id TRADER01
```

At the prompt:

```text
[TRADER01]> SYMBOLS
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00
[TRADER01]> ORDERS
[TRADER01]> POS
[TRADER01]> STATUS
[TRADER01]> HELP
[TRADER01]> EXIT
```

Expected behavior:

- `POS` shows accumulated positions tracked locally by the client
- `STATUS` shows session info: gateway name, heartbeat interval, idle timeout
- fills, `HB`, and broadcast `SESSION`/`TRADE` events appear in real time while you type other commands
- Tab completes command verbs and field names
- Command history is saved across sessions to `~/.alf_client_history`

Connect to a remote gateway:

```bash
python3 alf_client.py --host 10.0.0.5 --port 5565 --id TRADER01
```

:material-checkbox-blank-outline: Checkpoint: interactive Python client connects, shows `WELCOME`, and `ORDERS` and `POS` respond correctly.

 

## Exercise 6: Use the Python Library Directly

`alf_parser.py` exposes `parse_alf_line`, `build_alf_line`, and the
`AlfSession` high-level class for use in scripts.

```bash
cd docs/examples/alf/python
python3 - <<'EOF'
from alf_parser import parse_alf_line, build_alf_line, AlfSession, AlfMessage

# Parse a line received from the gateway
msg: AlfMessage = parse_alf_line("ACK|ORDER_ID=abc|ACCEPTED=TRUE|SYMBOL=AAPL")
print(msg.msg_type)   # ACK
print(msg.fields)     # {"ORDER_ID": "abc", "ACCEPTED": "TRUE", ...}

# Build a line to send
line = build_alf_line("NEW", {
    "SYM": "AAPL", "SIDE": "BUY",
    "TYPE": "LIMIT", "QTY": "100", "PRICE": "150.00",
})
print(repr(line))  # 'NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00\n'

# High-level session: connect, HELLO/WELCOME, send/recv
session = AlfSession.connect("127.0.0.1", 5565, "TRADER01")
print(session.welcome.gw_name)   # alf-gwy01

session.send("ORDERS")
msg = session.recv_msg()         # header line of ORDERS response
print(msg.msg_type, msg.fields)

session.close()
EOF
```

Expected output: `ACK`, the parsed `fields` dict, the built line string, the
gateway name from `WELCOME`, and the `ORDERS` response header.

:material-checkbox-blank-outline: Checkpoint: `AlfSession.connect` completes the HELLO/WELCOME handshake and `recv_msg` returns a parsed message.

 

## Exercise 7: Build and Run the C Client

**macOS** — install Homebrew readline for full callback support if not already present:

```bash
brew install readline
```

**Linux:**

```bash
sudo apt install libreadline-dev   # Debian/Ubuntu
```

Build:

```bash
cd docs/examples/alf/c
make
```

Run:

```bash
./alf_client --id TRADER01
```

At the prompt:

```text
[TRADER01]> SYMBOLS
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00
[TRADER01]> ORDERS
[TRADER01]> EXIT
```

Expected behavior:

- the C client uses `select()` to multiplex the socket and stdin, so gateway
  events (fills, heartbeats, broadcasts) appear in real time while you type
- readline provides tab completion and persistent command history
- `--no-color` disables ANSI colour output for plain terminals

Try connecting to a remote host:

```bash
./alf_client --host 10.0.0.5 --port 5565 --id TRADER01
```

:material-checkbox-blank-outline: Checkpoint: C client connects, shows `WELCOME`, and a `NEW` order returns an `ACK`.

 

## Exercise 8: Control Commands and the Kill-Switch

### PING / PONG

```bash
nc 127.0.0.1 5565
```

```text
HELLO|CLIENT=ctrl|PROTO=ALF1|ID=TRADER01
PING
```

Expected: `PONG|TS=<ISO-8601-timestamp>`.

### QBOOT — quote bootstrap state (MARKET_MAKER role)

Open a second terminal and connect with the MM01 identity:

```bash
nc 127.0.0.1 5565
```

```text
HELLO|CLIENT=mm|PROTO=ALF1|ID=MM01
QBOOT
```

Expected: `QBOOT|COUNT=0` and `END|TYPE=QBOOT` initially.

Submit a quote then re-check:

```text
QUOTE|SYM=AAPL|BID=149.90|ASK=150.10|BID_QTY=500|ASK_QTY=500
QBOOT
```

Expected: `QBOOT|COUNT=1` with one active `QUOTE|...` line, then `END|TYPE=QBOOT`.

### KILL — cancel all resting orders and active quotes

```text
KILL
```

Expected: `KILL_ACK|ACCEPTED=TRUE|ORDERS=N|QUOTES=N`.

Confirm everything was cleared:

```text
ORDERS
QBOOT
```

Both responses should show `COUNT=0`.

Scope the kill to one symbol:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149.00
NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=50|PRICE=400.00
KILL|SYM=AAPL
ORDERS
```

Expected: only the MSFT order remains.

:material-checkbox-blank-outline: Checkpoint: you can use `PING`, `QBOOT`, and `KILL` (with and without `SYM=`) and interpret the responses.

 

## Exercise 9: Error Conditions and Operational Interpretation

Test typical protocol errors. Start a fresh `nc` session and send each line before
completing the `HELLO` handshake, or with invalid content:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00    (before HELLO)
HELLO|CLIENT=test|PROTO=WRONG|ID=TRADER01
HELLO|CLIENT=test|PROTO=ALF1|ID=NONEXISTENT
```

After a successful `HELLO`, try:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100          (missing PRICE for LIMIT)
NEW|SYM=UNKNOWN|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00
QUOTE|SYM=AAPL|BID=150.00|ASK=150.10|BID_QTY=500|ASK_QTY=500   (TRADER role)
```

Map each observed `ERR|CODE=...` to its operator remediation:

| Code | Practical interpretation |
|---|---|
| `AUTH_REQUIRED` | Client sent a non-`HELLO` first line; fix client code ordering |
| `PROTO_MISMATCH` | Wrong `PROTO=` value; must be exactly `ALF1` |
| `AUTH_FAILED` | Gateway ID not in `gateways.alf`; add to config and restart engine |
| `GATEWAY_ALREADY_CONNECTED` | Same ID connected from another session; disconnect it first |
| `MISSING_FIELD` | Required field absent for this order type; check command reference |
| `INVALID_VALUE` | Field value fails validation (e.g. `PRICE=NaN`, `QTY=0`); fix client |
| `SYMBOL_NOT_CONFIGURED` | Unknown symbol; run `SYMBOLS` to see the configured list |
| `ROLE_DENIED` | Command not allowed for this gateway's role (`QUOTE` requires `MARKET_MAKER`) |
| `RATE_LIMITED` | Commands arriving faster than `max_commands_per_second`; throttle client |

:material-checkbox-blank-outline: Checkpoint: you can map each `ERR|CODE` to the correct config or client-code fix.

 

## Support Libraries and Example Clients

Reference implementations used in this training chapter:

- `docs/examples/alf/python/alf_parser.py` — protocol library: `parse_alf_line`, `build_alf_line`, `AlfSession`
- `docs/examples/alf/python/alf_client.py` — interactive client with tab-completion, event display, and P&L tracking
- `docs/examples/alf/c/alf_parser.h` / `alf_parser.c` — C protocol library: `alf_parse_line`, `alf_build_line`, `alf_get_field`
- `docs/examples/alf/c/alf_client.c` — interactive C client using `select()` + readline

Use these to bootstrap ALF clients in any language that can open a TCP socket
and read newline-delimited text.

 

## Summary

You can now:

- Generate an `alf_gateway:` config with `pm-config-gen` and start `pm-alf-gwy`.
- Verify a TCP port is listening using `lsof`, `ss`, and `netstat` on macOS and Linux.
- Test the complete ALF session lifecycle manually with `nc` and `telnet` before writing any code.
- Submit, amend, and cancel orders over a raw TCP session and read `ACK`, `AMENDED`, and `CANCELLED` responses.
- Use `python3 alf_client.py` for interactive sessions with tab-completion and live event display.
- Script against the gateway using `AlfSession` from `alf_parser.py`.
- Build and run the C `alf_client` for a readline-based interactive session with `select()` multiplexing.
- Operate `PING`, `ORDERS`, `QBOOT`, and `KILL` and interpret their responses.
- Map `ERR|CODE=...` values to the correct config or client-side fix.

 

## Reflection

`pm-alf-gwy` (this chapter) and `pm-api-gateway` (Chapter 24) both allow
external clients to submit orders to the same matching engine. Answer the
following:

1. A Python bot connecting to `pm-alf-gwy` receives a `FILL` event pushed
   directly over its persistent TCP connection. A Python bot connecting to
   `pm-api-gateway` learns about the same fill through a WebSocket `events`
   stream. Both need to act on fills within milliseconds. Which transport has
   lower latency overhead and why?

2. A compliance team needs read-only access to every fill for **all** gateway
   IDs — not just their own. Can they use `pm-alf-gwy` for this? If not, which
   gateway process should they consume instead and with what role?

3. After a network interruption, an ALF bot reconnects and sends `ORDERS` to
   recover resting state. The API gateway equivalent is `GET /api/v1/orders`.
   At the protocol level, which reconnect handler is simpler to implement and
   why?

 

## Handoff for Chapter 27

This completes the external gateway protocol series. `pm-engine`,
`pm-alf-gwy`, and any other running processes can remain up if you want to
continue a live session, or you can stop them and start fresh for the next
chapter.

 

## Further Reading

- [ALF TCP Gateway](../user-guide/24-alf-gateway.md) — configuration, session lifecycle, command reference, and troubleshooting
- [ALF Protocol Reference](../user-guide/90-app-alf-protocol.md) — formal wire syntax and full field/enum definitions
- [Gateway Commands](../user-guide/08-gateway.md) — interactive command reference for `pm-alf-console`
- [Protocol Support Library Examples](../user-guide/80-examples.md)
- [Processes](../user-guide/10-processes.md)
