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
  --gateways TRADER01 TRADER02 MM01:MARKET_MAKER \
  --balf-gateway \
  --balf-port 5560 \
  --balf-bind-address 127.0.0.1 \
  --output engine_config.yaml
```

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
```

Start processes with that config:

```bash
pm-engine --verbose --config engine_config.yaml
pm-balf-gwy --config engine_config.yaml
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
| `ORDER_ACK` | `0x01` | Symbol not configured |
| `ORDER_ACK` | `0x02` | Invalid quantity |
| `ORDER_ACK` | `0x03` | Price required but missing |
| `ORDER_ACK` | `0x05` | Session/market phase rejected order |
| `ORDER_ACK` | `0xFF` | Other error; inspect reason string |

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

 

## Handoff for Chapter 28

This completes the BALF training chapter. `pm-engine`, `pm-balf-gwy`, and any
supporting processes can remain up if you want to continue live testing, or you
can stop them and start fresh for the next chapter.

 

## Further Reading

- [BALF TCP Gateway](../user-guide/25-balf-gateway.md) — configuration, lifecycle, and troubleshooting
- [BALF Protocol Reference](../user-guide/91-app-balf-protocol.md) — formal frame layouts and enum/reference tables
- [Configuration](../user-guide/01-configuration.md) — `balf_gateway:` generation with `pm-config-gen`
- [Protocol Support Library Examples](../user-guide/80-examples.md)
- [Processes](../user-guide/10-processes.md)
