# BALF TCP Gateway Protocol Training

## Objective

Train on end-to-end usage of the BALF protocol through `pm-balf-gwy` using OS
CLI tools, a minimal Python client, and the BALF parser reference libraries.

You will practise:

- generating a `balf_gateway:` config with `pm-config-gen`
- starting `pm-balf-gwy` and verifying the port is listening using OS tools
- testing connectivity and session auth with a binary `LOGON` probe script
- submitting and cancelling orders over a raw BALF TCP session
- handling heartbeats (`HEARTBEAT` / `HEARTBEAT_ACK`) correctly
- decoding `LOGON_ACK`, `ORDER_ACK`, and `CANCEL_ACK` responses
- validating frame parsing using the Python and C BALF parser examples
- diagnosing reject/error conditions from BALF reject codes

 


!!! abstract "Background reading"
    - [BALF Gateway](../operator-guide/part-5-gateways/020-balf-gateway.md)
    - [BALF Protocol](../protocols-and-clients/part-2-specifications/020-balf.md)

## Prerequisites

- Chapters 01-26 completed.
- Engine running and configured with at least two gateway IDs.
- `pm-balf-gwy` available in the environment (`poetry run pm-balf-gwy` or installed via `pipx`).
- Support parser examples available in `docs/examples/balf`:
  - `balf_parser.py`
  - `balf_parser.c`

Recommended startup terminals:

1. Engine: `pm-engine --verbose`
2. BALF gateway: `pm-balf-gwy`
3. One or more client terminals for connection exercises

 

## Background

`pm-balf-gwy` is the TCP gateway for BALF (Binary ALF).
It accepts simultaneous external client connections and translates fixed-width
binary frames into the same engine semantics used by ALF command workflows.

In this chapter, the most important operational ideas are:

- Session establishment: `LOGON` -> auth round-trip -> `LOGON_ACK`
- Authenticated order entry and management: `NEW_ORDER`, `CANCEL_ORDER`, `AMEND_ORDER`
- Fill and lifecycle feedback: `ORDER_ACK`, `CANCEL_ACK`, `AMEND_ACK`, `EXECUTION_REPORT`
- Liveness: `HEARTBEAT`/`HEARTBEAT_ACK` and timeout-driven disconnects
- Binary safety rules: fixed frame size by `msg_type`, little-endian numeric fields, reserved bytes set to zero
- Error interpretation: BALF reject codes in `LOGON_ACK` and `ORDER_ACK`

 

## Exercise 1: Generate a Config That Enables `pm-balf-gwy`

Generate `engine_config.yaml` with the `balf_gateway:` section enabled:

```bash
pm-config-gen \
  --symbols AAPL MSFT \
  --participants TRADER01 TRADER02 OPS01:ADMIN MM01:MARKET_MAKER \
  --no-mm-seed-quotes \
  --balf-gateway \
  --balf-port 5560 \
  --balf-bind-address 127.0.0.1 \
  --output engine_config.yaml --force
```

!!! note "Back up, check, deploy — then restart"
    This chapter starts from a fresh configuration (its operator is `OPS01`),
    and `--force` replaces your `engine_config.yaml`: save a copy first if you
    want to come back to it (`cp engine_config.yaml engine_config.before-ch27.yaml`).
    As always, nothing changes until you deploy it and restart the engine:
    `pm-cverifier engine_config.yaml`, then `pm-config-deploy engine_config.yaml`.

Inspect the generated section:

```bash
grep -A20 '^balf_gateway:' engine_config.yaml
```

Expected output includes:

```yaml
balf_gateway:
  name: balf-gwy01
  bind_address: 127.0.0.1
  port: 5560
  heartbeat_interval_sec: 1
  heartbeat_timeout_sec: 5
  idle_timeout_sec: 30
  auth_timeout_sec: 10
  max_connections: 64
```

Start processes with that config:

```bash
pm-engine --verbose
pm-balf-gwy
```

:material-checkbox-blank-outline: Checkpoint: `pm-balf-gwy` starts, logs that it is listening on port 5560, and reports a successful engine ZMQ connection.

 

## Exercise 2: Verify the Port Is Listening with CLI Tools

Before writing client code, confirm the gateway is bound to the configured port.

**macOS:**

```bash
sudo lsof -iTCP:5560 -sTCP:LISTEN
netstat -an | grep LISTEN | grep 5560
```

Expected: a line with `pm-balf-gwy` (or `Python` under Poetry) and `LISTEN`.

**Linux:**

```bash
ss -tlnp 'sport = :5560'
sudo lsof -iTCP:5560 -sTCP:LISTEN
netstat -tlnp | grep 5560
```

If no output appears:

- the gateway is not running or failed to start
- `balf_gateway.enabled` may be `false` in config
- the port may differ from expectation
- `pm-engine` must be running before `pm-balf-gwy` can complete its startup handshake

:material-checkbox-blank-outline: Checkpoint: at least one CLI command shows a process listening on port 5560.

 

## Exercise 3: Manual Binary `LOGON` Probe with Python

Because BALF is binary, use a short Python probe instead of `nc` or `telnet`.
This verifies the full auth lifecycle with no client framework.

```bash
python3 - <<'EOF'
import socket
import struct

BALF_MAGIC = 0xBA
BALF_VERSION = 0x01
MSG_LOGON = 0x01
MSG_LOGON_ACK = 0x02


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("connection closed")
        buf.extend(chunk)
    return bytes(buf)

header = struct.pack("<BBBBI", BALF_MAGIC, BALF_VERSION, MSG_LOGON, 0, 0)
body = struct.pack("<16sB7s", b"TRADER01", BALF_VERSION, b"\x00" * 7)

sock = socket.create_connection(("127.0.0.1", 5560), timeout=5)
sock.sendall(header + body)

ack = recv_exact(sock, 92)
msg_type = ack[2]
if msg_type != MSG_LOGON_ACK:
    raise RuntimeError(f"expected LOGON_ACK, got 0x{msg_type:02X}")

payload = ack[8:]
gw_raw, accepted, reject_code, msg_len, _, msg_bytes = struct.unpack("<16sBBBB64s", payload)
gw = gw_raw.rstrip(b"\x00").decode("ascii", errors="replace")
msg = msg_bytes[:msg_len].decode("ascii", errors="replace")

print(f"LOGON_ACK gateway={gw!r} accepted={bool(accepted)} code=0x{reject_code:02X} msg={msg!r}")
sock.close()
EOF
```

Expected success pattern:

```text
LOGON_ACK gateway='TRADER01' accepted=True code=0x00 msg='gateway=balf-gwy01 hbint=1s'
```

:material-checkbox-blank-outline: Checkpoint: probe receives `LOGON_ACK` with `accepted=True`.

 

## Exercise 3B: Non-Interactive Reachability Check for CI

Use this one-liner to fail fast in scripts and CI:

```bash
python3 - <<'EOF'
import socket, struct, sys
sock = socket.create_connection(("127.0.0.1", 5560), timeout=3)
logon = struct.pack("<BBBBI16sB7s", 0xBA, 0x01, 0x01, 0, 0, b"TRADER01", 0x01, b"\x00"*7)
sock.sendall(logon)
ack = sock.recv(92)
ok = len(ack) == 92 and ack[2] == 0x02 and ack[24] == 1
print("BALF_PROBE_OK" if ok else "BALF_PROBE_FAIL")
sock.close()
sys.exit(0 if ok else 1)
EOF
```

Expected: prints `BALF_PROBE_OK` and exits with code `0`.

:material-checkbox-blank-outline: Checkpoint: one-liner succeeds without manual interaction.

 

## Exercise 4: Submit and Cancel an Order over BALF

Run a minimal BALF client that authenticates, sends `NEW_ORDER`, waits for
`ORDER_ACK`, then sends `CANCEL_ORDER` and checks `CANCEL_ACK`.

```bash
python3 - <<'EOF'
import socket
import struct

BALF_MAGIC = 0xBA
BALF_VERSION = 0x01
PRICE_SCALE = 100_000_000

MSG_LOGON = 0x01
MSG_LOGON_ACK = 0x02
MSG_NEW_ORDER = 0x10
MSG_ORDER_ACK = 0x11
MSG_CANCEL_ORDER = 0x12
MSG_CANCEL_ACK = 0x13
MSG_HEARTBEAT = 0x30
MSG_HEARTBEAT_ACK = 0x31
MSG_LOGOUT = 0x40

FRAME_SIZES = {
    MSG_LOGON_ACK: 92,
    MSG_ORDER_ACK: 60,
    MSG_CANCEL_ACK: 32,
    MSG_HEARTBEAT: 16,
}


def build_header(msg_type, seq_no):
    return struct.pack("<BBBBI", BALF_MAGIC, BALF_VERSION, msg_type, 0, seq_no)


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("connection closed")
        buf.extend(chunk)
    return bytes(buf)


def recv_frame(sock):
    header = recv_exact(sock, 8)
    msg_type = header[2]
    size = FRAME_SIZES[msg_type]
    body = recv_exact(sock, size - 8)
    return msg_type, body

sock = socket.create_connection(("127.0.0.1", 5560), timeout=5)
seq = 0

# LOGON
logon = build_header(MSG_LOGON, 0) + struct.pack("<16sB7s", b"TRADER01", BALF_VERSION, b"\x00" * 7)
sock.sendall(logon)
msg_type, body = recv_frame(sock)
if msg_type != MSG_LOGON_ACK or body[16] != 1:
    raise RuntimeError("LOGON failed")
print("LOGON_ACK accepted")

# NEW_ORDER (LIMIT BUY 100 AAPL @ 150.00)
seq += 1
new_order = build_header(MSG_NEW_ORDER, seq) + struct.pack(
    "<Q8sqqqIIBBBB",
    1,
    b"AAPL",
    int(150.00 * PRICE_SCALE),
    0,
    0,
    100,
    0,
    1,
    2,
    1,
    0,
)
sock.sendall(new_order)

while True:
    msg_type, body = recv_frame(sock)
    if msg_type == MSG_HEARTBEAT:
        seq += 1
        sent_ns = struct.unpack_from("<Q", body)[0]
        hb_ack = build_header(MSG_HEARTBEAT_ACK, seq) + struct.pack("<Q", sent_ns)
        sock.sendall(hb_ack)
        continue
    if msg_type == MSG_ORDER_ACK:
        order_id = struct.unpack_from("<Q", body, 8)[0]
        accepted = body[24] == 1
        if not accepted:
            raise RuntimeError("ORDER_ACK rejected")
        print(f"ORDER_ACK accepted order_id={order_id}")
        break

# CANCEL_ORDER
seq += 1
cancel = build_header(MSG_CANCEL_ORDER, seq) + struct.pack("<QQ", 2, order_id)
sock.sendall(cancel)
msg_type, body = recv_frame(sock)
if msg_type != MSG_CANCEL_ACK or body[16] != 1:
    raise RuntimeError("CANCEL_ACK rejected")
print("CANCEL_ACK accepted")

# LOGOUT
seq += 1
sock.sendall(build_header(MSG_LOGOUT, seq))
sock.close()
print("LOGOUT sent")
EOF
```

Expected behavior:

- `LOGON_ACK accepted`
- `ORDER_ACK accepted order_id=...`
- `CANCEL_ACK accepted`
- `LOGOUT sent`

:material-checkbox-blank-outline: Checkpoint: you can submit and cancel an order over a raw BALF TCP session.

 

## Exercise 4B: Amend an Order and Receive Fills

Exercise 4 sent an order and cancelled it. The other half of order entry is
what comes back when the order trades. This exercise uses two sessions —
`TRADER01` rests a bid, amends it, and `TRADER02` sells into it — and decodes
the `AMEND_ACK` and both sides' `EXECUTION_REPORT`. The market must be open
(`SESSION|STATE=PRE_OPEN`, then `CONTINUOUS`, from `pm-admin --id OPS01`) and
AAPL's book empty (the configuration from Exercise 1 has no seed quotes).

```bash
python3 - <<'EOF'
import socket
import struct

PRICE_SCALE = 100_000_000
FRAME_SIZES = {0x02: 92, 0x11: 60, 0x13: 32, 0x15: 48, 0x20: 64, 0x30: 16}


def header(msg_type, seq):
    return struct.pack("<BBBBI", 0xBA, 0x01, msg_type, 0, seq)


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("connection closed")
        buf.extend(chunk)
    return bytes(buf)


def next_frame(sock, want):
    """Return the body of the next `want` frame, answering heartbeats."""
    while True:
        h = recv_exact(sock, 8)
        body = recv_exact(sock, FRAME_SIZES[h[2]] - 8)
        if h[2] == 0x30:
            sock.sendall(header(0x31, 0) + body[:8])
            continue
        if h[2] == want:
            return body


def session(gateway):
    sock = socket.create_connection(("127.0.0.1", 5560), timeout=10)
    sock.sendall(header(0x01, 0) + struct.pack("<16sB7s", gateway, 1, b"\x00" * 7))
    assert next_frame(sock, 0x02)[16] == 1, "LOGON rejected"
    return sock


def new_order(sock, seq, client_id, side, price, qty):
    sock.sendall(
        header(0x10, seq)
        + struct.pack("<Q8sqqqIIBBBB", client_id, b"AAPL", round(price * PRICE_SCALE), 0, 0, qty, 0, side, 2, 1, 0)
    )
    return struct.unpack_from("<Q", next_frame(sock, 0x11), 8)[0]


def report(label, body):
    cid, oid, px, qty, rem = struct.unpack_from("<QQqII", body)
    print(f"{label}: EXECUTION_REPORT client_order_id={cid} fill={qty}@{px / PRICE_SCALE:.2f} remaining={rem}")


resting = session(b"TRADER01")
taker = session(b"TRADER02")

order_id = new_order(resting, 1, 1, 1, 150.00, 100)          # BUY 100 @ 150.00
print("TRADER01 resting order_id", order_id)

# AMEND: new price 150.50 and new total quantity 200 (flags: bit0 price, bit1 quantity)
resting.sendall(header(0x14, 2) + struct.pack("<QQqIB7s", 2, order_id, round(150.50 * PRICE_SCALE), 200, 0b11, b"\x00" * 7))
body = next_frame(resting, 0x15)
cid, oid, px, qty, rem, accepted, reset = struct.unpack_from("<QQqIIBB", body)
print(f"AMEND_ACK accepted={bool(accepted)} price={px / PRICE_SCALE:.2f} qty={qty} priority_reset={bool(reset)}")

new_order(taker, 1, 7, 2, 150.50, 120)                       # SELL 120 @ 150.50 crosses it
report("TRADER02 (taker)", next_frame(taker, 0x20))
report("TRADER01 (resting)", next_frame(resting, 0x20))
EOF
```

Expected:

```text
TRADER01 resting order_id 1
AMEND_ACK accepted=True price=150.50 qty=200 priority_reset=True
TRADER02 (taker): EXECUTION_REPORT client_order_id=7 fill=120@150.50 remaining=0
TRADER01 (resting): EXECUTION_REPORT client_order_id=1 fill=120@150.50 remaining=80
```

Read it against the [BALF specification](../protocols-and-clients/part-2-specifications/020-balf.md):

- `amend_flags` `0b11` says both the price and the quantity changed. `new_quantity`
  is the new **total**, so 200 means 200 shares in all, as with `AMEND` in
  Chapter 04.
- `priority_reset=True`: a price change always loses time priority.
- The fill is at the resting order's price, 150.50 (the taker's limit equals it
  here). Both sides then get their own `EXECUTION_REPORT`; the `client_order_id`
  in each is the number that session chose (1 and 7). The 80 shares left on the
  bid stay on the book until you cancel them with `CANCEL_ORDER`, as in
  Exercise 4.

:material-checkbox-blank-outline: Checkpoint: you decoded an `AMEND_ACK` with `priority_reset=True` and the two
`EXECUTION_REPORT` frames of one trade, and can say why the resting side's
`remaining` is 80.

 

## Exercise 5: Validate Parser Libraries (Python and C)

Run the provided parser self-tests to verify your local BALF decode tooling.

Python parser:

```bash
cd docs/examples/balf
python3 balf_parser.py
```

Expected output: `balf_parser.py self-test: OK`

C parser:

```bash
cd docs/examples/balf
cc -std=c11 -Wall -Wextra -pedantic -O2 balf_parser.c -o balf_parser
./balf_parser
```

Expected output includes:

```text
LOGON_ACK gateway_id=TRADER01 accepted=1 reject_code=0 msg=ok
balf_parser.c self-test: OK
```

:material-checkbox-blank-outline: Checkpoint: both parser examples run successfully.

 

## Exercise 6: Duplicate Session Policy and Heartbeat Behaviour

Set `duplicate_session_policy` in `balf_gateway:` and observe behaviour by
connecting two clients using the same gateway ID.

- With `REJECT_NEW`, second `LOGON` should receive `LOGON_ACK` with reject code `0x02`.
- With `EVICT_OLD`, first client disconnects and second session is accepted.

Also verify heartbeat handling:

- Keep a client idle and watch for `HEARTBEAT` frames.
- Ensure your client replies with `HEARTBEAT_ACK`.
- Skip ACK replies to confirm timeout disconnect after `heartbeat_timeout_sec`.

:material-checkbox-blank-outline: Checkpoint: observed both duplicate-session behaviour and heartbeat timeout semantics.

 

## Exercise 7: Error Conditions and Operational Interpretation

Trigger representative reject conditions and map them to remediation:

1. `LOGON` with unknown `gateway_id`
2. `LOGON` with wrong `proto_version`
3. `NEW_ORDER` with unknown symbol
4. `NEW_ORDER` with invalid quantity (`0`)
5. `NEW_ORDER` `LIMIT` with missing required `price` (send `price=0`)

Use this mapping:

| Message | Code | Practical interpretation |
|---|---|---|
| `LOGON_ACK` | `0x01` | Gateway ID not configured in engine |
| `LOGON_ACK` | `0x02` | Gateway already connected (duplicate session) |
| `LOGON_ACK` | `0x03` | Protocol version mismatch |
| `ORDER_ACK` | `0x03` | Symbol not configured |
| `ORDER_ACK` | `0x04` | Market closed |
| `ORDER_ACK` | `0x07` | Symbol halted |
| `ORDER_ACK` | `0x08` | Rejected by the current session phase |
| `ORDER_ACK` | `0x0B` | Rejected by a price collar |
| `ORDER_ACK` | `0x0C` | Invalid field — bad quantity, or a LIMIT order with no price |
| `ORDER_ACK` | `0xFF` | Other error; inspect reason string |

The full code list is in
[Appendix: BALF Protocol — reject codes](../protocols-and-clients/part-2-specifications/020-balf.md).
Note that `ORDER_ACK` and `LOGON_ACK` use **different** code spaces: `0x01` on a
logon means "gateway not configured", while on an order it means the same thing
about the *gateway*, and a bad **symbol** is `0x03`.

:material-checkbox-blank-outline: Checkpoint: you can map BALF reject codes to the correct config or client-code fix.

 

## Support Libraries and Example Clients

Reference implementations used in this training chapter:

- `docs/examples/balf/balf_parser.py` — Python BALF frame parser and decode helpers
- `docs/examples/balf/balf_parser.c` — C BALF frame parser and decode helpers

Use these as wire-format references when building clients in Python, C, C++,
or Rust.

 

## Summary

You can now:

- Generate a `balf_gateway:` config with `pm-config-gen` and start `pm-balf-gwy`.
- Verify a TCP port is listening using `lsof`, `ss`, and `netstat` on macOS and Linux.
- Probe a BALF session with a minimal binary `LOGON` script.
- Submit and cancel orders using raw BALF frames over TCP.
- Handle heartbeats and sequence progression safely in client code.
- Decode BALF responses and rejects using parser examples.
- Map `LOGON_ACK` and `ORDER_ACK` reject codes to concrete fixes.

 

## Reflection

`pm-balf-gwy` (this chapter) and `pm-alf-gwy` (Chapter 26) both feed the same
matching engine semantics but through different wire formats. Answer the
following:

1. For a latency-sensitive strategy written in C++, why might fixed-width BALF
   framing outperform text ALF parsing in practice?

2. For classroom demos and ad-hoc operations, why is ALF often still a better
   choice than BALF despite higher parsing overhead?

3. If a BALF client repeatedly disconnects after being idle, which heartbeat
   settings and client behaviours should you inspect first?

 

## Where to go next

This completes the BALF training chapter. `pm-engine`, `pm-balf-gwy`, and any
supporting processes can remain up if you want to continue live testing, or you
can stop them and start fresh for the next chapter.

 

## Further Reading

- [BALF TCP Gateway](../operator-guide/part-5-gateways/020-balf-gateway.md) — configuration, lifecycle, and troubleshooting
- [BALF Protocol Reference](../protocols-and-clients/part-2-specifications/020-balf.md) — formal frame layouts and enum/reference tables
- [The Configuration Workflow](../operator-guide/part-2-configure/010-the-configuration-workflow.md) — `balf_gateway:` generation with `pm-config-gen`
- [Protocol Support Library Examples](../protocols-and-clients/part-4-writing-clients/030-example-libraries.md)
- [Processes, Environment and Ports](../reference-manual/part-1-command-line/010-processes-environment-and-ports.md)
