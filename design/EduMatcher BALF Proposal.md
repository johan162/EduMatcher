# BALF: Binary ALF Protocol — Design Proposal

**Status:** PROPOSAL — for discussion  
**Version:** draft-0.1  
**Date:** 1 June 2026  
**Author:** Engineering  

---

## 1. Motivation

ALF (ALmost-FIX) is designed for interactive human use and simple bot
development. Several properties make it unsuitable for latency-sensitive
participants:

| Problem | ALF behaviour | HFT impact |
|---------|--------------|------------|
| Text parsing | `|` splitting, ASCII-to-float conversion | CPU cycles on the hot path |
| Variable message length | Unknown bytes-to-read until delimiter found | Forces buffered reads |
| No sequence numbers | Message loss is undetectable at the protocol level | Silent gap risk |
| No heartbeat | Dead session discovered only by absence of data | Unknown session liveness |
| stdin/stdout coupling | `pm-gateway` is an interactive process | Incompatible with poll/epoll loops |
| Price as ASCII decimal | `"150.25"` is 6 bytes + float parse | Unnecessary work per order |

**BALF** (Binary ALF) is a fixed-width binary protocol with the same semantic
model — identical order types, TIF values, SMP rules, and gateway authentication
— but designed from first principles for low-latency programmatic access.

### What BALF does NOT change

- The engine itself. BALF is translated by a new `pm-balf-gateway` process into
  the same ZeroMQ/JSON engine messages that ALF already produces.
- The set of tradeable instruments or order types available to a session.
- Gateway authentication — the same allowlist in `engine_config.yaml` is used.

### Non-goals for this proposal

- Encryption — delegate to TLS at the transport layer or a tunnel. BALF frames
  are cleartext.
- RDMA / kernel-bypass — BALF is designed to sit cleanly above a standard TCP
  socket; the trade-off between TCP and kernel-bypass transports is a separate
  decision.
- Multi-leg combo and OCO orders — deferred to Phase 2 once the core protocol
  is validated.

---

## 2. Architecture

```
                 ┌─────────────────────┐
                 │  BALF Client        │
                 │  (Rust / C / other) │
                 └────────┬────────────┘
                          │ TCP :5560 (proposed)
                          │ raw binary frames
                          ▼
                 ┌─────────────────────┐
                 │  pm-balf-gateway    │ (new process)
                 │  translates BALF ↔  │
                 │  engine ZeroMQ/JSON │
                 └──────┬──────────────┘
                        │ PUSH → tcp://localhost:5555
                        │ SUB  ← tcp://localhost:5556
                        ▼
                 ┌─────────────────────┐
                 │  EduMatcher Engine  │ (unchanged)
                 └─────────────────────┘
```

`pm-balf-gateway` is the BALF analogue of `pm-gateway`. It accepts one TCP
connection per client, performs gateway authentication against the engine's
allowlist, and relays order traffic in both directions.

---

## 3. Transport

- **Protocol:** TCP, single full-duplex connection per gateway session.
- **Port:** 5560 (proposed; configurable in `engine_config.yaml`).
- **Framing:** All BALF messages are fixed-width; the size is entirely determined
  by the `msg_type` byte in the header. There is no length field to parse. The
  receiver reads exactly `BALF_MSG_SIZE[msg_type]` bytes after reading the
  8-byte header.
- **Byte order:** Little-endian throughout. Modern trading infrastructure runs
  on x86; little-endian avoids byte-swap overhead on every price field.
- **Connection limit:** One TCP connection per gateway ID. A second connection
  with the same ID rejects at LOGON unless the first connection has been
  cleanly closed.

---

## 4. Frame Format

Every BALF message is an 8-byte header followed by a fixed-length body whose
size is determined by `msg_type`.

```
 0               1               2               3
 0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7
┌───────────────┬───────────────┬───────────────┬───────────────┐
│     magic     │    version    │   msg_type    │     flags     │
│    (0xBA)     │     (0x01)    │               │               │
├───────────────┴───────────────┴───────────────┴───────────────┤
│                           seq_no                              │
│                         (uint32 LE)                           │
└───────────────────────────────────────────────────────────────┘
         [body follows immediately — size fixed by msg_type]
```

### 4.1 Header fields

| Offset | Field | Type | Description |
|--------|-------|------|-------------|
| 0 | `magic` | `u8` | Always `0xBA`. Receiver must reject frames where this is wrong. |
| 1 | `version` | `u8` | Protocol version. Currently `1`. |
| 2 | `msg_type` | `u8` | Message type code — see §5. |
| 3 | `flags` | `u8` | Bit 0: `RETRANSMIT` — set when replaying a previously sent message. All other bits reserved, must be zero. |
| 4–7 | `seq_no` | `u32 LE` | Monotonically increasing sequence number. Client-to-server and server-to-client share separate counters, each starting at 1 on the first non-LOGON message. LOGON itself always carries seq_no `0`. |

### 4.2 Price encoding

All prices and price-like offsets (limit price, stop price, trailing offset)
are encoded as **signed 64-bit integers scaled by 10⁸**.

```
encoded = round(display_price × 100_000_000)

  $150.25   →  15_025_000_000
  $0.0001   →           10_000
  −$2.00    →  −200_000_000  (spread price or basis)
```

The scale provides 8 decimal places of precision, sufficient for equities,
fixed income, and most derivatives. A zero value (`0i64`) means the field is
not applicable for the given order type.

### 4.3 Symbol encoding

Symbols are stored as **8 bytes, zero-padded ASCII, left-aligned**. `"AAPL"` is
encoded as `[0x41, 0x50, 0x50, 0x4C, 0x00, 0x00, 0x00, 0x00]`. Symbols longer
than 8 ASCII characters are not supported in BALF v1.

### 4.4 Gateway ID encoding

Gateway IDs are stored as **16 bytes, zero-padded ASCII, left-aligned**.
`"TRADER01"` is `[0x54, 0x52, 0x41, 0x44, 0x45, 0x52, 0x30, 0x31, 0x00, ...]`.

### 4.5 Order ID encoding

Engine-generated order IDs are UUIDs. In BALF they are stored as **16 raw bytes
(RFC 4122 binary form, no hyphens)**. When the engine rejects an order, the
order ID field is all-zeros.

### 4.6 Client Order ID

Every client-to-server order message carries a `client_order_id` — a `u64` that
the client assigns. The server echoes it in every corresponding response. This
lets clients correlate responses with requests without UUID parsing.

---

## 5. Message Type Reference

### 5.1 Summary table

| Code | Name | Direction | Body bytes | Total frame bytes |
|------|------|-----------|------------|-------------------|
| `0x01` | `LOGON` | Client → Server | 24 | 32 |
| `0x02` | `LOGON_ACK` | Server → Client | 84 | 92 |
| `0x10` | `NEW_ORDER` | Client → Server | 52 | 60 |
| `0x11` | `ORDER_ACK` | Server → Client | 60 | 68 |
| `0x12` | `CANCEL_ORDER` | Client → Server | 24 | 32 |
| `0x13` | `CANCEL_ACK` | Server → Client | 32 | 40 |
| `0x14` | `AMEND_ORDER` | Client → Server | 44 | 52 |
| `0x15` | `AMEND_ACK` | Server → Client | 48 | 56 |
| `0x20` | `EXECUTION_REPORT` | Server → Client | 64 | 72 |
| `0x30` | `HEARTBEAT` | Bidirectional | 8 | 16 |
| `0x31` | `HEARTBEAT_ACK` | Bidirectional | 8 | 16 |
| `0x40` | `LOGOUT` | Client → Server | 0 | 8 |

All sizes include the 8-byte header.

---

### 5.2 `LOGON` (0x01) — Client → Server

Sent immediately after the TCP connection is established, before any orders.
`seq_no` is `0`.

**Body (24 bytes):**

```
Offset  0  │  gateway_id     │  u8[16]  │  Zero-padded ASCII gateway ID
Offset 16  │  proto_version  │  u8      │  Must be 1
Offset 17  │  _reserved      │  u8[7]   │  Must be zero
```

---

### 5.3 `LOGON_ACK` (0x02) — Server → Client

Sent in response to `LOGON`. `seq_no` is `0` on this message; normal
sequencing begins from `1` on subsequent messages.

**Body (84 bytes):**

```
Offset  0  │  gateway_id     │  u8[16]  │  Echoed gateway ID
Offset 16  │  accepted       │  u8      │  1 = accepted, 0 = rejected
Offset 17  │  reject_code    │  u8      │  See reject codes below; 0 if accepted
Offset 18  │  msg_len        │  u8      │  Byte length of the meaningful part of msg[]
Offset 19  │  _pad           │  u8      │  Reserved, zero
Offset 20  │  msg            │  u8[64]  │  Human-readable description or rejection reason
```

**Reject codes:**

| Code | Meaning |
|------|---------|
| `0x00` | No error (accepted) |
| `0x01` | Gateway ID not configured in engine |
| `0x02` | Gateway ID already connected |
| `0x03` | Protocol version mismatch |
| `0xFF` | Other (see `msg` field) |

---

### 5.4 `NEW_ORDER` (0x10) — Client → Server

**Body (52 bytes):**

```
Offset  0  │  client_order_id  │  u64 LE  │  Client-assigned reference, echoed in all responses
Offset  8  │  symbol           │  u8[8]   │  Zero-padded ASCII symbol
Offset 16  │  price            │  i64 LE  │  Limit price × 10⁸; 0 for MARKET/STOP orders
Offset 24  │  stop_price       │  i64 LE  │  Stop trigger × 10⁸; 0 if unused
Offset 32  │  trail_offset     │  i64 LE  │  Trailing offset × 10⁸; 0 if unused
Offset 40  │  quantity         │  u32 LE  │  Order quantity
Offset 44  │  visible_qty      │  u32 LE  │  ICEBERG peak size; 0 for all other types
Offset 48  │  side             │  u8      │  1 = BUY, 2 = SELL
Offset 49  │  order_type       │  u8      │  See order type codes below
Offset 50  │  tif              │  u8      │  See TIF codes below
Offset 51  │  smp              │  u8      │  See SMP codes below
```

**Order type codes:**

| Code | ALF equivalent | Required price fields |
|------|---------------|----------------------|
| `0x01` | `MARKET` | none (price = 0) |
| `0x02` | `LIMIT` | `price` |
| `0x03` | `IOC` | `price` |
| `0x04` | `FOK` | `price` |
| `0x05` | `STOP` | `stop_price` |
| `0x06` | `STOP_LIMIT` | `stop_price` and `price` |
| `0x07` | `ICEBERG` | `price` and `visible_qty` |
| `0x08` | `TRAILING_STOP` | `trail_offset`; optionally `stop_price` |

**TIF codes:**

| Code | ALF equivalent |
|------|---------------|
| `0x01` | `DAY` |
| `0x02` | `GTC` |
| `0x03` | `ATO` |
| `0x04` | `ATC` |

**SMP codes:**

| Code | ALF equivalent |
|------|---------------|
| `0x00` | `NONE` |
| `0x01` | `CANCEL_AGGRESSOR` |
| `0x02` | `CANCEL_RESTING` |
| `0x03` | `CANCEL_BOTH` |

---

### 5.5 `ORDER_ACK` (0x11) — Server → Client

Sent for every `NEW_ORDER`. Arrives before any `EXECUTION_REPORT` for the same
order.

**Body (60 bytes):**

```
Offset  0  │  client_order_id  │  u64 LE  │  Echoed from NEW_ORDER
Offset  8  │  order_id         │  u8[16]  │  Binary UUID assigned by engine; all-zeros if rejected
Offset 24  │  timestamp_ns     │  u64 LE  │  Nanoseconds since Unix epoch (engine receive time)
Offset 32  │  accepted         │  u8      │  1 = accepted, 0 = rejected
Offset 33  │  reject_code      │  u8      │  See reject codes below; 0 if accepted
Offset 34  │  reason_len       │  u8      │  Length of meaningful bytes in reason[]
Offset 35  │  reason           │  u8[25]  │  Rejection reason string (ASCII); zeros if accepted
```

**Reject codes:**

| Code | Meaning |
|------|---------|
| `0x00` | Accepted |
| `0x01` | Symbol not configured |
| `0x02` | Invalid quantity (zero or negative) |
| `0x03` | Price required but missing |
| `0x04` | FOK — insufficient liquidity |
| `0x05` | Market closed / phase rejection |
| `0x06` | Unknown order type |
| `0x07` | ICEBERG visible_qty ≥ quantity |
| `0x08` | TRAILING_STOP — no prior trade price |
| `0xFF` | Other (see `reason` field) |

---

### 5.6 `CANCEL_ORDER` (0x12) — Client → Server

**Body (24 bytes):**

```
Offset  0  │  client_order_id  │  u64 LE  │  New client ref for this cancel request
Offset  8  │  order_id         │  u8[16]  │  Binary UUID of the order to cancel
```

---

### 5.7 `CANCEL_ACK` (0x13) — Server → Client

**Body (32 bytes):**

```
Offset  0  │  client_order_id  │  u64 LE  │  Echoed from CANCEL_ORDER
Offset  8  │  order_id         │  u8[16]  │  Order being cancelled
Offset 24  │  accepted         │  u8      │  1 = cancelled, 0 = rejected
Offset 25  │  cancel_reason    │  u8      │  0 = client request, 1 = SMP, 2 = session end, 3 = IOC/FOK expire
Offset 26  │  _reserved        │  u8[6]   │  Must be zero
```

---

### 5.8 `AMEND_ORDER` (0x14) — Client → Server

Amends price and/or quantity of a resting LIMIT or ICEBERG order. At least one
of the `amend_flags` bits must be set.

**Body (44 bytes):**

```
Offset  0  │  client_order_id  │  u64 LE  │  New client ref for this amend request
Offset  8  │  order_id         │  u8[16]  │  Binary UUID of the order to amend
Offset 24  │  new_price        │  i64 LE  │  New limit price × 10⁸; ignored if bit 0 of amend_flags is clear
Offset 32  │  new_quantity     │  u32 LE  │  New total quantity; ignored if bit 1 of amend_flags is clear
Offset 36  │  amend_flags      │  u8      │  Bit 0 = price changed, bit 1 = quantity changed
Offset 37  │  _reserved        │  u8[7]   │  Must be zero
```

---

### 5.9 `AMEND_ACK` (0x15) — Server → Client

**Body (48 bytes):**

```
Offset  0  │  client_order_id  │  u64 LE  │  Echoed from AMEND_ORDER
Offset  8  │  order_id         │  u8[16]  │  Amended order
Offset 24  │  new_price        │  i64 LE  │  Price after amendment × 10⁸
Offset 32  │  new_quantity     │  u32 LE  │  Total quantity after amendment
Offset 36  │  remaining_qty    │  u32 LE  │  Unfilled quantity after amendment
Offset 40  │  accepted         │  u8      │  1 = accepted, 0 = rejected
Offset 41  │  priority_reset   │  u8      │  1 = order lost time priority; 0 = priority preserved
Offset 42  │  _reserved        │  u8[6]   │  Must be zero
```

---

### 5.10 `EXECUTION_REPORT` (0x20) — Server → Client

Sent for every partial or full fill. Both sides of a match (aggressor and
resting order) receive their own `EXECUTION_REPORT`.

**Body (64 bytes):**

```
Offset  0  │  client_order_id  │  u64 LE  │  Echoed from the original NEW_ORDER
Offset  8  │  order_id         │  u8[16]  │  Filled order UUID
Offset 24  │  fill_price       │  i64 LE  │  Execution price × 10⁸
Offset 32  │  fill_qty         │  u32 LE  │  Quantity matched in this event
Offset 36  │  remaining_qty    │  u32 LE  │  Unfilled quantity after this fill
Offset 40  │  timestamp_ns     │  u64 LE  │  Trade timestamp — nanoseconds since Unix epoch
Offset 48  │  symbol           │  u8[8]   │  Symbol (for convenience; matches original order)
Offset 56  │  side             │  u8      │  1 = BUY, 2 = SELL
Offset 57  │  status           │  u8      │  1 = PARTIAL, 2 = FILLED
Offset 58  │  _reserved        │  u8[6]   │  Must be zero
```

---

### 5.11 `HEARTBEAT` (0x30) — Bidirectional

Either side may send a heartbeat at any time. The recipient must respond with
`HEARTBEAT_ACK`. A session is considered dead if no traffic (including
heartbeats) arrives within 5 seconds (configurable). The default send interval
is 1 second.

**Body (8 bytes):**

```
Offset  0  │  send_time_ns  │  u64 LE  │  Sender's wall-clock time in nanoseconds since Unix epoch
```

---

### 5.12 `HEARTBEAT_ACK` (0x31) — Bidirectional

**Body (8 bytes):**

```
Offset  0  │  orig_send_time_ns  │  u64 LE  │  Echo of the send_time_ns from the HEARTBEAT
```

---

### 5.13 `LOGOUT` (0x40) — Client → Server

Graceful disconnect. No body. After sending `LOGOUT`, the client must not send
any further messages and should close the TCP connection. The server will flush
any pending outbound messages and then close the connection on its side.

**Body: none (total frame = 8 bytes, header only).**

---

## 6. Session Lifecycle

```
Client                                    pm-balf-gateway
  │                                               │
  │──── TCP SYN ────────────────────────────────►│
  │◄─── TCP SYN-ACK ────────────────────────────│
  │                                               │
  │──── LOGON (seq=0) ──────────────────────────►│  gateway authenticates with engine
  │◄─── LOGON_ACK (seq=0) ──────────────────────│  accepted=1 or 0
  │                                               │
  │  (accepted=0 → client should close TCP)       │
  │                                               │
  │──── NEW_ORDER (seq=1) ──────────────────────►│
  │◄─── ORDER_ACK (seq=1) ──────────────────────│
  │◄─── EXECUTION_REPORT (seq=2) ───────────────│  if immediate fill
  │                                               │
  │──── CANCEL_ORDER (seq=2) ───────────────────►│
  │◄─── CANCEL_ACK (seq=3) ─────────────────────│
  │                                               │
  │◄─── HEARTBEAT (seq=N) ──────────────────────│  server-initiated liveness check
  │──── HEARTBEAT_ACK (seq=M) ─────────────────►│
  │                                               │
  │──── LOGOUT (seq=K) ─────────────────────────►│
  │ (server closes TCP after flushing)            │
```

### Sequence number rules

- Separate, independent sequence counters for each direction.
- Both counters start at **1** on the first non-LOGON message.
- LOGON and LOGON_ACK carry seq_no `0` by convention and are not part of the
  numbered sequence.
- Sequence numbers increment by 1 per message. They wrap to 1 (not 0) at
  `UINT32_MAX`.
- A gap in the inbound sequence number is a protocol error; the receiver should
  log it and may close the connection.
- The `RETRANSMIT` flag (bit 0 of `flags`) must be set when replaying a
  previously sent message (e.g. during session recovery). The sequence number
  on a retransmit carries the **original** sequence number of the message.

---

## 7. Worked Examples

### 7.1 Submit a LIMIT BUY order for 100 AAPL at $150.25

ALF equivalent: `NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.25`

Frame bytes (60 total, shown as hex with annotations):

```
Header (8 bytes):
  BA 01 10 00  │  magic=0xBA, version=1, msg_type=NEW_ORDER(0x10), flags=0
  01 00 00 00  │  seq_no=1 (LE)

Body (52 bytes):
  01 00 00 00  00 00 00 00  │  client_order_id = 1 (LE u64)
  41 50 50 4C  00 00 00 00  │  symbol = "AAPL\0\0\0\0"
  00 10 28 65  03 00 00 00  │  price = 15_025_000_000 = 0x0000000003652810 (LE i64)
  00 00 00 00  00 00 00 00  │  stop_price = 0
  00 00 00 00  00 00 00 00  │  trail_offset = 0
  64 00 00 00  │  quantity = 100 (LE u32)
  00 00 00 00  │  visible_qty = 0
  01           │  side = BUY
  02           │  order_type = LIMIT
  01           │  tif = DAY
  00           │  smp = NONE
```

Price calculation: 150.25 × 100,000,000 = 15,025,000,000 = `0x0000_0003_6528_1000`  
In little-endian bytes: `00 10 28 65 03 00 00 00`

### 7.2 Cancel that order

```
Header:
  BA 01 12 00  │  msg_type=CANCEL_ORDER(0x12)
  02 00 00 00  │  seq_no=2

Body:
  02 00 00 00  00 00 00 00  │  client_order_id = 2
  [16 bytes of binary UUID received in ORDER_ACK]
```

---

## 8. Rust Implementation

### 8.1 Types and constants

```rust
// balf.rs — BALF protocol types and codec
//
// Compile with: rustc --edition 2021 balf_example.rs

use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::{SystemTime, UNIX_EPOCH};

// ── Constants ───────────────────────────────────────────────────────────────

pub const BALF_MAGIC: u8   = 0xBA;
pub const BALF_VERSION: u8 = 0x01;

// Price scale factor: multiply display price by this before encoding
pub const PRICE_SCALE: i64 = 100_000_000;

// Message type codes
pub mod msg {
    pub const LOGON:            u8 = 0x01;
    pub const LOGON_ACK:        u8 = 0x02;
    pub const NEW_ORDER:        u8 = 0x10;
    pub const ORDER_ACK:        u8 = 0x11;
    pub const CANCEL_ORDER:     u8 = 0x12;
    pub const CANCEL_ACK:       u8 = 0x13;
    pub const AMEND_ORDER:      u8 = 0x14;
    pub const AMEND_ACK:        u8 = 0x15;
    pub const EXECUTION_REPORT: u8 = 0x20;
    pub const HEARTBEAT:        u8 = 0x30;
    pub const HEARTBEAT_ACK:    u8 = 0x31;
    pub const LOGOUT:           u8 = 0x40;
}

// Total frame sizes (header + body)
pub fn frame_size(msg_type: u8) -> Option<usize> {
    match msg_type {
        msg::LOGON            => Some(32),
        msg::LOGON_ACK        => Some(92),
        msg::NEW_ORDER        => Some(60),
        msg::ORDER_ACK        => Some(68),
        msg::CANCEL_ORDER     => Some(32),
        msg::CANCEL_ACK       => Some(40),
        msg::AMEND_ORDER      => Some(52),
        msg::AMEND_ACK        => Some(56),
        msg::EXECUTION_REPORT => Some(72),
        msg::HEARTBEAT        => Some(16),
        msg::HEARTBEAT_ACK    => Some(16),
        msg::LOGOUT           => Some(8),
        _                     => None,
    }
}

// ── Order type, side, TIF, SMP codes ────────────────────────────────────────

pub mod side {
    pub const BUY:  u8 = 0x01;
    pub const SELL: u8 = 0x02;
}

pub mod order_type {
    pub const MARKET:        u8 = 0x01;
    pub const LIMIT:         u8 = 0x02;
    pub const IOC:           u8 = 0x03;
    pub const FOK:           u8 = 0x04;
    pub const STOP:          u8 = 0x05;
    pub const STOP_LIMIT:    u8 = 0x06;
    pub const ICEBERG:       u8 = 0x07;
    pub const TRAILING_STOP: u8 = 0x08;
}

pub mod tif {
    pub const DAY: u8 = 0x01;
    pub const GTC: u8 = 0x02;
    pub const ATO: u8 = 0x03;
    pub const ATC: u8 = 0x04;
}

pub mod smp {
    pub const NONE:              u8 = 0x00;
    pub const CANCEL_AGGRESSOR:  u8 = 0x01;
    pub const CANCEL_RESTING:    u8 = 0x02;
    pub const CANCEL_BOTH:       u8 = 0x03;
}

// ── Helper: encode a display price to wire format ───────────────────────────

pub fn encode_price(display: f64) -> i64 {
    (display * PRICE_SCALE as f64).round() as i64
}

pub fn decode_price(wire: i64) -> f64 {
    wire as f64 / PRICE_SCALE as f64
}

// ── Helper: encode a symbol or gateway ID into a fixed-width byte array ─────

pub fn encode_symbol(s: &str) -> [u8; 8] {
    let mut buf = [0u8; 8];
    let bytes = s.as_bytes();
    let len = bytes.len().min(8);
    buf[..len].copy_from_slice(&bytes[..len]);
    buf
}

pub fn encode_gateway_id(s: &str) -> [u8; 16] {
    let mut buf = [0u8; 16];
    let bytes = s.as_bytes();
    let len = bytes.len().min(16);
    buf[..len].copy_from_slice(&bytes[..len]);
    buf
}

// ── Header builder ───────────────────────────────────────────────────────────

pub fn build_header(msg_type: u8, flags: u8, seq_no: u32) -> [u8; 8] {
    let mut h = [0u8; 8];
    h[0] = BALF_MAGIC;
    h[1] = BALF_VERSION;
    h[2] = msg_type;
    h[3] = flags;
    h[4..8].copy_from_slice(&seq_no.to_le_bytes());
    h
}

// ── Message builders ─────────────────────────────────────────────────────────

pub fn build_logon(gateway_id: &str) -> Vec<u8> {
    let mut buf = Vec::with_capacity(32);
    buf.extend_from_slice(&build_header(msg::LOGON, 0, 0));
    buf.extend_from_slice(&encode_gateway_id(gateway_id)); // 16 bytes
    buf.push(BALF_VERSION);                                  // proto_version
    buf.extend_from_slice(&[0u8; 7]);                        // reserved
    buf
}

pub struct NewOrderParams<'a> {
    pub client_order_id: u64,
    pub symbol:          &'a str,
    pub side:            u8,
    pub order_type:      u8,
    pub tif:             u8,
    pub smp:             u8,
    pub quantity:        u32,
    pub price:           f64,       // 0.0 for MARKET
    pub stop_price:      f64,       // 0.0 if unused
    pub trail_offset:    f64,       // 0.0 if unused
    pub visible_qty:     u32,       // 0 unless ICEBERG
}

pub fn build_new_order(params: &NewOrderParams, seq_no: u32) -> Vec<u8> {
    let mut buf = Vec::with_capacity(60);
    buf.extend_from_slice(&build_header(msg::NEW_ORDER, 0, seq_no));
    buf.extend_from_slice(&params.client_order_id.to_le_bytes());
    buf.extend_from_slice(&encode_symbol(params.symbol));
    buf.extend_from_slice(&encode_price(params.price).to_le_bytes());
    buf.extend_from_slice(&encode_price(params.stop_price).to_le_bytes());
    buf.extend_from_slice(&encode_price(params.trail_offset).to_le_bytes());
    buf.extend_from_slice(&params.quantity.to_le_bytes());
    buf.extend_from_slice(&params.visible_qty.to_le_bytes());
    buf.push(params.side);
    buf.push(params.order_type);
    buf.push(params.tif);
    buf.push(params.smp);
    buf
}

pub fn build_cancel_order(client_order_id: u64, order_id: [u8; 16], seq_no: u32) -> Vec<u8> {
    let mut buf = Vec::with_capacity(32);
    buf.extend_from_slice(&build_header(msg::CANCEL_ORDER, 0, seq_no));
    buf.extend_from_slice(&client_order_id.to_le_bytes());
    buf.extend_from_slice(&order_id);
    buf
}

pub fn build_amend_order(
    client_order_id: u64,
    order_id: [u8; 16],
    new_price: Option<f64>,
    new_quantity: Option<u32>,
    seq_no: u32,
) -> Vec<u8> {
    let mut buf = Vec::with_capacity(52);
    buf.extend_from_slice(&build_header(msg::AMEND_ORDER, 0, seq_no));
    buf.extend_from_slice(&client_order_id.to_le_bytes());
    buf.extend_from_slice(&order_id);

    let price_wire = new_price.map_or(0i64, encode_price);
    let qty_wire   = new_quantity.unwrap_or(0u32);
    let flags: u8  = (new_price.is_some() as u8) | ((new_quantity.is_some() as u8) << 1);

    buf.extend_from_slice(&price_wire.to_le_bytes());
    buf.extend_from_slice(&qty_wire.to_le_bytes());
    buf.push(flags);
    buf.extend_from_slice(&[0u8; 7]); // reserved
    buf
}

pub fn build_logout(seq_no: u32) -> Vec<u8> {
    build_header(msg::LOGOUT, 0, seq_no).to_vec()
}

// ── Response parsing ──────────────────────────────────────────────────────────

pub struct LogonAck {
    pub gateway_id: [u8; 16],
    pub accepted:   bool,
    pub reject_code: u8,
    pub message:    String,
}

pub struct OrderAck {
    pub client_order_id: u64,
    pub order_id:        [u8; 16],
    pub timestamp_ns:    u64,
    pub accepted:        bool,
    pub reject_code:     u8,
    pub reason:          String,
}

pub struct ExecutionReport {
    pub client_order_id: u64,
    pub order_id:        [u8; 16],
    pub fill_price:      f64,
    pub fill_qty:        u32,
    pub remaining_qty:   u32,
    pub timestamp_ns:    u64,
    pub symbol:          String,
    pub side:            u8,
    pub status:          u8,  // 1=PARTIAL, 2=FILLED
}

// Read exactly n bytes from the stream (blocking)
fn read_exact(stream: &mut TcpStream, n: usize) -> std::io::Result<Vec<u8>> {
    let mut buf = vec![0u8; n];
    stream.read_exact(&mut buf)?;
    Ok(buf)
}

/// Read the next complete BALF frame from the stream.
/// Returns (msg_type, seq_no, body_bytes) or an IO error.
pub fn read_frame(stream: &mut TcpStream) -> std::io::Result<(u8, u32, Vec<u8>)> {
    let header = read_exact(stream, 8)?;
    if header[0] != BALF_MAGIC {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("Bad magic byte: 0x{:02X}", header[0]),
        ));
    }
    let msg_type = header[2];
    let seq_no   = u32::from_le_bytes(header[4..8].try_into().unwrap());
    let total    = frame_size(msg_type).ok_or_else(|| {
        std::io::Error::new(std::io::ErrorKind::InvalidData,
            format!("Unknown msg_type: 0x{:02X}", msg_type))
    })?;
    let body = read_exact(stream, total - 8)?;
    Ok((msg_type, seq_no, body))
}

pub fn parse_logon_ack(body: &[u8]) -> LogonAck {
    let mut gw = [0u8; 16];
    gw.copy_from_slice(&body[0..16]);
    let accepted    = body[16] == 1;
    let reject_code = body[17];
    let msg_len     = body[18] as usize;
    let message     = String::from_utf8_lossy(&body[20..20 + msg_len.min(64)]).to_string();
    LogonAck { gateway_id: gw, accepted, reject_code, message }
}

pub fn parse_order_ack(body: &[u8]) -> OrderAck {
    let client_order_id = u64::from_le_bytes(body[0..8].try_into().unwrap());
    let mut order_id    = [0u8; 16];
    order_id.copy_from_slice(&body[8..24]);
    let timestamp_ns    = u64::from_le_bytes(body[24..32].try_into().unwrap());
    let accepted        = body[32] == 1;
    let reject_code     = body[33];
    let reason_len      = body[34] as usize;
    let reason = String::from_utf8_lossy(&body[35..35 + reason_len.min(25)]).to_string();
    OrderAck { client_order_id, order_id, timestamp_ns, accepted, reject_code, reason }
}

pub fn parse_execution_report(body: &[u8]) -> ExecutionReport {
    let client_order_id = u64::from_le_bytes(body[0..8].try_into().unwrap());
    let mut order_id    = [0u8; 16];
    order_id.copy_from_slice(&body[8..24]);
    let fill_price_raw  = i64::from_le_bytes(body[24..32].try_into().unwrap());
    let fill_qty        = u32::from_le_bytes(body[32..36].try_into().unwrap());
    let remaining_qty   = u32::from_le_bytes(body[36..40].try_into().unwrap());
    let timestamp_ns    = u64::from_le_bytes(body[40..48].try_into().unwrap());
    let symbol = String::from_utf8_lossy(
        body[48..56].split(|&b| b == 0).next().unwrap_or(&body[48..56])
    ).to_string();
    let side   = body[56];
    let status = body[57];
    ExecutionReport {
        client_order_id,
        order_id,
        fill_price: decode_price(fill_price_raw),
        fill_qty,
        remaining_qty,
        timestamp_ns,
        symbol,
        side,
        status,
    }
}
```

### 8.2 Full session example

```rust
// main.rs — Connect, authenticate, submit a LIMIT order, receive ack and fill

mod balf; // bring in the types above

use balf::*;

fn now_ns() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos() as u64
}

fn main() -> std::io::Result<()> {
    let mut stream = TcpStream::connect("127.0.0.1:5560")?;
    let mut send_seq: u32 = 0;
    let mut client_order_counter: u64 = 0;

    // ── Step 1: LOGON ────────────────────────────────────────────────────────
    let logon = build_logon("TRADER01");
    stream.write_all(&logon)?;
    println!("Sent LOGON for TRADER01");

    // ── Step 2: Wait for LOGON_ACK ───────────────────────────────────────────
    let (msg_type, _, body) = read_frame(&mut stream)?;
    assert_eq!(msg_type, msg::LOGON_ACK, "Expected LOGON_ACK");
    let ack = parse_logon_ack(&body);
    if !ack.accepted {
        eprintln!("LOGON rejected: code={} msg={}", ack.reject_code, ack.message);
        return Ok(());
    }
    println!("LOGON accepted: {}", ack.message);

    // ── Step 3: Submit a LIMIT BUY 100 AAPL @ $150.25 ───────────────────────
    send_seq += 1;
    client_order_counter += 1;

    let order = build_new_order(&NewOrderParams {
        client_order_id: client_order_counter,
        symbol:          "AAPL",
        side:            side::BUY,
        order_type:      order_type::LIMIT,
        tif:             tif::DAY,
        smp:             smp::NONE,
        quantity:        100,
        price:           150.25,
        stop_price:      0.0,
        trail_offset:    0.0,
        visible_qty:     0,
    }, send_seq);
    stream.write_all(&order)?;
    println!("Sent NEW_ORDER seq={send_seq} clordid={client_order_counter}");

    // ── Step 4: Read ORDER_ACK ───────────────────────────────────────────────
    let (msg_type, _, body) = read_frame(&mut stream)?;
    assert_eq!(msg_type, msg::ORDER_ACK, "Expected ORDER_ACK");
    let order_ack = parse_order_ack(&body);
    if !order_ack.accepted {
        eprintln!(
            "Order rejected: code={} reason={}",
            order_ack.reject_code, order_ack.reason
        );
        return Ok(());
    }
    println!(
        "Order accepted: order_id={:?} ts_ns={}",
        &order_ack.order_id, order_ack.timestamp_ns
    );
    let active_order_id = order_ack.order_id;

    // ── Step 5: Wait for an EXECUTION_REPORT (if resting, may not arrive) ───
    // In a real client this would be in a receive loop on a separate thread.
    let (msg_type, _, body) = read_frame(&mut stream)?;
    if msg_type == msg::EXECUTION_REPORT {
        let er = parse_execution_report(&body);
        println!(
            "Fill: {}x{} @ {:.4}  remaining={} status={}",
            er.symbol, er.fill_qty, er.fill_price, er.remaining_qty,
            if er.status == 1 { "PARTIAL" } else { "FILLED" }
        );
    }

    // ── Step 6: Cancel the order if still resting ────────────────────────────
    send_seq += 1;
    client_order_counter += 1;
    let cancel = build_cancel_order(client_order_counter, active_order_id, send_seq);
    stream.write_all(&cancel)?;
    println!("Sent CANCEL seq={send_seq}");

    let (msg_type, _, body) = read_frame(&mut stream)?;
    assert_eq!(msg_type, msg::CANCEL_ACK);
    let accepted = body[24] == 1;
    println!("Cancel {}", if accepted { "confirmed" } else { "rejected" });

    // ── Step 7: Graceful logout ──────────────────────────────────────────────
    send_seq += 1;
    stream.write_all(&build_logout(send_seq))?;
    println!("Sent LOGOUT");

    Ok(())
}
```

---

## 9. C Implementation

### 9.1 Types and constants

```c
/* balf.h — BALF protocol definitions
 *
 * Compile example:  gcc -O2 -Wall -o balf_example balf_example.c
 */

#ifndef BALF_H
#define BALF_H

#include <stdint.h>
#include <string.h>

/* ── Constants ─────────────────────────────────────────────────────────────── */

#define BALF_MAGIC        0xBAu
#define BALF_VERSION      0x01u
#define PRICE_SCALE       100000000LL  /* 10^8 */

/* Message type codes */
#define BALF_LOGON            0x01u
#define BALF_LOGON_ACK        0x02u
#define BALF_NEW_ORDER        0x10u
#define BALF_ORDER_ACK        0x11u
#define BALF_CANCEL_ORDER     0x12u
#define BALF_CANCEL_ACK       0x13u
#define BALF_AMEND_ORDER      0x14u
#define BALF_AMEND_ACK        0x15u
#define BALF_EXECUTION_REPORT 0x20u
#define BALF_HEARTBEAT        0x30u
#define BALF_HEARTBEAT_ACK    0x31u
#define BALF_LOGOUT           0x40u

/* Side codes */
#define BALF_SIDE_BUY         0x01u
#define BALF_SIDE_SELL        0x02u

/* Order type codes */
#define BALF_TYPE_MARKET      0x01u
#define BALF_TYPE_LIMIT       0x02u
#define BALF_TYPE_IOC         0x03u
#define BALF_TYPE_FOK         0x04u
#define BALF_TYPE_STOP        0x05u
#define BALF_TYPE_STOP_LIMIT  0x06u
#define BALF_TYPE_ICEBERG     0x07u
#define BALF_TYPE_TRAILING    0x08u

/* TIF codes */
#define BALF_TIF_DAY          0x01u
#define BALF_TIF_GTC          0x02u
#define BALF_TIF_ATO          0x03u
#define BALF_TIF_ATC          0x04u

/* SMP codes */
#define BALF_SMP_NONE             0x00u
#define BALF_SMP_CANCEL_AGGRESSOR 0x01u
#define BALF_SMP_CANCEL_RESTING   0x02u
#define BALF_SMP_CANCEL_BOTH      0x03u

/* Fill status codes */
#define BALF_STATUS_PARTIAL   0x01u
#define BALF_STATUS_FILLED    0x02u

/* Amend flags (bitmask) */
#define BALF_AMEND_PRICE    0x01u
#define BALF_AMEND_QTY      0x02u

/* ── Wire structs (packed — no compiler padding on the wire) ────────────────── */

#pragma pack(push, 1)

typedef struct {
    uint8_t  magic;       /* 0xBA                          */
    uint8_t  version;     /* 1                             */
    uint8_t  msg_type;
    uint8_t  flags;
    uint32_t seq_no;      /* little-endian                 */
} BalfHeader;             /* 8 bytes                       */

typedef struct {
    BalfHeader hdr;
    uint8_t  gateway_id[16];
    uint8_t  proto_version;
    uint8_t  reserved[7];
} BalfLogon;              /* 32 bytes                      */

typedef struct {
    BalfHeader hdr;
    uint8_t  gateway_id[16];
    uint8_t  accepted;
    uint8_t  reject_code;
    uint8_t  msg_len;
    uint8_t  _pad;
    uint8_t  msg[64];
} BalfLogonAck;           /* 92 bytes                      */

typedef struct {
    BalfHeader hdr;
    uint64_t client_order_id;  /* little-endian */
    uint8_t  symbol[8];
    int64_t  price;            /* fixed-point x10^8, little-endian */
    int64_t  stop_price;
    int64_t  trail_offset;
    uint32_t quantity;
    uint32_t visible_qty;
    uint8_t  side;
    uint8_t  order_type;
    uint8_t  tif;
    uint8_t  smp;
} BalfNewOrder;           /* 60 bytes                      */

typedef struct {
    BalfHeader hdr;
    uint64_t client_order_id;
    uint8_t  order_id[16];
    uint64_t timestamp_ns;
    uint8_t  accepted;
    uint8_t  reject_code;
    uint8_t  reason_len;
    uint8_t  reason[25];
} BalfOrderAck;           /* 68 bytes                      */

typedef struct {
    BalfHeader hdr;
    uint64_t client_order_id;
    uint8_t  order_id[16];
} BalfCancelOrder;        /* 32 bytes                      */

typedef struct {
    BalfHeader hdr;
    uint64_t client_order_id;
    uint8_t  order_id[16];
    uint8_t  accepted;
    uint8_t  cancel_reason;
    uint8_t  reserved[6];
} BalfCancelAck;          /* 40 bytes                      */

typedef struct {
    BalfHeader hdr;
    uint64_t client_order_id;
    uint8_t  order_id[16];
    int64_t  new_price;
    uint32_t new_quantity;
    uint8_t  amend_flags;
    uint8_t  reserved[7];
} BalfAmendOrder;         /* 52 bytes                      */

typedef struct {
    BalfHeader hdr;
    uint64_t client_order_id;
    uint8_t  order_id[16];
    int64_t  new_price;
    uint32_t new_quantity;
    uint32_t remaining_qty;
    uint8_t  accepted;
    uint8_t  priority_reset;
    uint8_t  reserved[6];
} BalfAmendAck;           /* 56 bytes                      */

typedef struct {
    BalfHeader hdr;
    uint64_t client_order_id;
    uint8_t  order_id[16];
    int64_t  fill_price;
    uint32_t fill_qty;
    uint32_t remaining_qty;
    uint64_t timestamp_ns;
    uint8_t  symbol[8];
    uint8_t  side;
    uint8_t  status;
    uint8_t  reserved[6];
} BalfExecutionReport;    /* 72 bytes                      */

typedef struct {
    BalfHeader hdr;
    uint64_t send_time_ns;
} BalfHeartbeat;          /* 16 bytes                      */

#pragma pack(pop)

/* ── Frame size lookup ──────────────────────────────────────────────────────── */

static inline int balf_frame_size(uint8_t msg_type) {
    switch (msg_type) {
        case BALF_LOGON:            return  32;
        case BALF_LOGON_ACK:        return  92;
        case BALF_NEW_ORDER:        return  60;
        case BALF_ORDER_ACK:        return  68;
        case BALF_CANCEL_ORDER:     return  32;
        case BALF_CANCEL_ACK:       return  40;
        case BALF_AMEND_ORDER:      return  52;
        case BALF_AMEND_ACK:        return  56;
        case BALF_EXECUTION_REPORT: return  72;
        case BALF_HEARTBEAT:        return  16;
        case BALF_HEARTBEAT_ACK:    return  16;
        case BALF_LOGOUT:           return   8;
        default:                    return  -1;
    }
}

/* ── Price helpers ──────────────────────────────────────────────────────────── */

static inline int64_t balf_encode_price(double display_price) {
    return (int64_t)(display_price * (double)PRICE_SCALE + 0.5);
}

static inline double balf_decode_price(int64_t wire_price) {
    return (double)wire_price / (double)PRICE_SCALE;
}

/* ── Symbol / gateway ID helpers ────────────────────────────────────────────── */

static inline void balf_encode_symbol(uint8_t dst[8], const char *sym) {
    memset(dst, 0, 8);
    strncpy((char *)dst, sym, 8);
}

static inline void balf_encode_gateway_id(uint8_t dst[16], const char *gw) {
    memset(dst, 0, 16);
    strncpy((char *)dst, gw, 16);
}

/* ── Header builder ──────────────────────────────────────────────────────────── */

static inline void balf_fill_header(BalfHeader *h, uint8_t msg_type,
                                    uint8_t flags, uint32_t seq_no) {
    h->magic    = BALF_MAGIC;
    h->version  = BALF_VERSION;
    h->msg_type = msg_type;
    h->flags    = flags;
    /* Store seq_no in little-endian regardless of host byte order */
    uint32_t le = seq_no;  /* x86 is already LE; on BE hosts use htole32() */
    memcpy(&h->seq_no, &le, 4);
}

#endif /* BALF_H */
```

### 9.2 Full session example

```c
/* balf_example.c — POSIX TCP client: connect, authenticate, submit order
 *
 * Compile: gcc -O2 -Wall -o balf_example balf_example.c
 * Run:     ./balf_example 127.0.0.1 5560 TRADER01
 */

#include "balf.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <time.h>

/* ── Blocking read of exactly n bytes ──────────────────────────────────────── */

static int read_exact(int fd, void *buf, size_t n) {
    size_t done = 0;
    while (done < n) {
        ssize_t r = recv(fd, (char *)buf + done, n - done, 0);
        if (r <= 0) {
            if (r == 0) fprintf(stderr, "Connection closed by server\n");
            else        perror("recv");
            return -1;
        }
        done += (size_t)r;
    }
    return 0;
}

/* ── Read a complete BALF frame ─────────────────────────────────────────────── */

typedef struct {
    uint8_t  msg_type;
    uint32_t seq_no;
    uint8_t  body[256];  /* largest frame body is 84 bytes */
} BalfFrame;

static int read_frame(int fd, BalfFrame *out) {
    BalfHeader hdr;
    if (read_exact(fd, &hdr, sizeof(hdr)) < 0) return -1;
    if (hdr.magic != BALF_MAGIC) {
        fprintf(stderr, "Bad magic: 0x%02X\n", hdr.magic);
        return -1;
    }
    int total = balf_frame_size(hdr.msg_type);
    if (total < 0) {
        fprintf(stderr, "Unknown msg_type: 0x%02X\n", hdr.msg_type);
        return -1;
    }
    int body_len = total - (int)sizeof(BalfHeader);
    memcpy(&out->seq_no, &hdr.seq_no, 4); /* already LE */
    out->msg_type = hdr.msg_type;
    if (body_len > 0) {
        if (read_exact(fd, out->body, (size_t)body_len) < 0) return -1;
    }
    return 0;
}

/* ── Nanoseconds since epoch ────────────────────────────────────────────────── */

static uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

/* ── Main ────────────────────────────────────────────────────────────────────── */

int main(int argc, char *argv[]) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <host> <port> <gateway_id>\n", argv[0]);
        return 1;
    }
    const char *host       = argv[1];
    int         port       = atoi(argv[2]);
    const char *gateway_id = argv[3];

    /* ── Connect ────────────────────────────────────────────────────────────── */
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 1; }

    /* Disable Nagle — send every write immediately */
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons((uint16_t)port);
    inet_pton(AF_INET, host, &addr.sin_addr);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("connect"); close(fd); return 1;
    }
    printf("Connected to %s:%d\n", host, port);

    uint32_t send_seq       = 0;
    uint64_t clordid_counter = 0;
    BalfFrame frame;

    /* ── Step 1: LOGON ──────────────────────────────────────────────────────── */
    BalfLogon logon;
    memset(&logon, 0, sizeof(logon));
    balf_fill_header(&logon.hdr, BALF_LOGON, 0, 0);
    balf_encode_gateway_id(logon.gateway_id, gateway_id);
    logon.proto_version = BALF_VERSION;
    send(fd, &logon, sizeof(logon), 0);
    printf("Sent LOGON for %s\n", gateway_id);

    /* ── Step 2: LOGON_ACK ──────────────────────────────────────────────────── */
    if (read_frame(fd, &frame) < 0 || frame.msg_type != BALF_LOGON_ACK) {
        fprintf(stderr, "Did not receive LOGON_ACK\n"); close(fd); return 1;
    }
    {
        BalfLogonAck *ack = (BalfLogonAck *)(&frame - 1); /* body is frame.body */
        /* Parse from raw body bytes */
        uint8_t accepted    = frame.body[16];
        uint8_t reject_code = frame.body[17];
        uint8_t msg_len     = frame.body[18];
        char    msg[65];
        memset(msg, 0, sizeof(msg));
        memcpy(msg, frame.body + 20, msg_len < 64 ? msg_len : 64);
        (void)ack;

        if (!accepted) {
            fprintf(stderr, "LOGON rejected: code=%d msg=%s\n", reject_code, msg);
            close(fd); return 1;
        }
        printf("LOGON accepted: %s\n", msg);
    }

    /* ── Step 3: NEW_ORDER — LIMIT BUY 100 AAPL @ $150.25 ──────────────────── */
    send_seq++;
    clordid_counter++;

    BalfNewOrder order;
    memset(&order, 0, sizeof(order));
    balf_fill_header(&order.hdr, BALF_NEW_ORDER, 0, send_seq);
    memcpy(&order.client_order_id, &clordid_counter, 8);
    balf_encode_symbol(order.symbol, "AAPL");

    int64_t price_wire = balf_encode_price(150.25);
    memcpy(&order.price, &price_wire, 8);

    uint32_t qty = 100;
    memcpy(&order.quantity, &qty, 4);

    order.side       = BALF_SIDE_BUY;
    order.order_type = BALF_TYPE_LIMIT;
    order.tif        = BALF_TIF_DAY;
    order.smp        = BALF_SMP_NONE;

    send(fd, &order, sizeof(order), 0);
    printf("Sent NEW_ORDER seq=%u clordid=%llu AAPL BUY 100 @ 150.25\n",
           send_seq, (unsigned long long)clordid_counter);

    /* ── Step 4: ORDER_ACK ──────────────────────────────────────────────────── */
    if (read_frame(fd, &frame) < 0 || frame.msg_type != BALF_ORDER_ACK) {
        fprintf(stderr, "Did not receive ORDER_ACK\n"); close(fd); return 1;
    }
    uint8_t active_order_id[16];
    uint8_t order_accepted;
    {
        /* body layout: [0..7]=client_order_id, [8..23]=order_id,
           [24..31]=timestamp_ns, [32]=accepted, [33]=reject_code,
           [34]=reason_len, [35..59]=reason */
        uint64_t echo_clordid;
        memcpy(&echo_clordid, frame.body,      8);
        memcpy(active_order_id, frame.body + 8, 16);
        uint64_t ts_ns;
        memcpy(&ts_ns, frame.body + 24, 8);
        order_accepted  = frame.body[32];
        uint8_t rcode   = frame.body[33];
        uint8_t rlen    = frame.body[34];
        char    reason[26]; memset(reason, 0, sizeof(reason));
        memcpy(reason, frame.body + 35, rlen < 25 ? rlen : 25);

        if (!order_accepted) {
            fprintf(stderr, "Order rejected: code=%d reason=%s\n", rcode, reason);
            close(fd); return 1;
        }
        printf("Order accepted: clordid=%llu ts_ns=%llu\n",
               (unsigned long long)echo_clordid,
               (unsigned long long)ts_ns);
    }

    /* ── Step 5: Optionally receive EXECUTION_REPORT ────────────────────────── */
    /* In a real client this runs in a dedicated receive thread with select/epoll */
    if (read_frame(fd, &frame) == 0 && frame.msg_type == BALF_EXECUTION_REPORT) {
        int64_t  fp_wire;
        uint32_t fq, rq;
        uint64_t fill_ts;
        memcpy(&fp_wire,  frame.body + 24, 8);
        memcpy(&fq,       frame.body + 32, 4);
        memcpy(&rq,       frame.body + 36, 4);
        memcpy(&fill_ts,  frame.body + 40, 8);
        char sym[9]; memset(sym, 0, 9);
        memcpy(sym, frame.body + 48, 8);
        uint8_t status = frame.body[57];
        printf("Fill: %s x%u @ %.4f  remaining=%u  status=%s\n",
               sym, fq, balf_decode_price(fp_wire), rq,
               status == BALF_STATUS_PARTIAL ? "PARTIAL" : "FILLED");
    }

    /* ── Step 6: CANCEL_ORDER ────────────────────────────────────────────────── */
    send_seq++;
    clordid_counter++;

    BalfCancelOrder cancel;
    memset(&cancel, 0, sizeof(cancel));
    balf_fill_header(&cancel.hdr, BALF_CANCEL_ORDER, 0, send_seq);
    memcpy(&cancel.client_order_id, &clordid_counter, 8);
    memcpy(cancel.order_id, active_order_id, 16);
    send(fd, &cancel, sizeof(cancel), 0);
    printf("Sent CANCEL seq=%u\n", send_seq);

    if (read_frame(fd, &frame) == 0 && frame.msg_type == BALF_CANCEL_ACK) {
        printf("Cancel %s\n", frame.body[24] ? "confirmed" : "rejected");
    }

    /* ── Step 7: LOGOUT ───────────────────────────────────────────────────────── */
    send_seq++;
    BalfHeader logout_hdr;
    balf_fill_header(&logout_hdr, BALF_LOGOUT, 0, send_seq);
    send(fd, &logout_hdr, sizeof(logout_hdr), 0);
    printf("Sent LOGOUT\n");

    close(fd);
    return 0;
}
```

---

## 10. Performance Characteristics

### Parse cost comparison

| Operation | ALF | BALF |
|-----------|-----|------|
| Split message into fields | `O(n)` string scan | None — offsets are fixed |
| Price decode | `strtod()` or `float()` | `memcpy` + integer multiply |
| Symbol lookup | `strcmp` | 8-byte integer compare (single instruction) |
| Order ID (cancel/amend) | UUID string parse (36 chars) | 16-byte `memcpy` |
| **Minimum bytes per LIMIT order** | 49 bytes (ASCII `NEW\|SYM=AAPL\|...`) | **60 bytes** (fixed) |
| **Maximum bytes per LIMIT order** | Unbounded (long symbol/price strings) | **60 bytes** (fixed) |

BALF messages are slightly larger than the shortest ALF equivalent because
they carry richer metadata (sequence number, timestamp, client order ID). The
value is predictability: the receiver knows exactly how many bytes to read
before the first byte arrives.

### TCP_NODELAY

Both the client and `pm-balf-gateway` should set `TCP_NODELAY` to disable
Nagle's algorithm. With fixed-size messages that are sent as a single `write()`
or `send()`, Nagle would only add latency without benefit.

### Receive threading model

Because BALF frames are fixed-width per message type, a tight receive loop can
be written without a state machine:

```c
while (running) {
    BalfHeader hdr;
    read_exact(fd, &hdr, 8);
    int sz = balf_frame_size(hdr.msg_type);
    read_exact(fd, body_buf, sz - 8);
    dispatch(hdr.msg_type, body_buf);
}
```

For kernel-bypass scenarios (e.g., DPDK or RDMA), `dispatch()` can be
called directly from the NIC receive callback without a thread context switch.

---

## 11. Configuration (proposed additions to `engine_config.yaml`)

```yaml
# Existing ALF gateway configuration — unchanged
sessions_enabled: true

gateways:
  alf:
    - id: TRADER01
      description: Human trader workstation
      role: TRADER

  # New BALF section — same allowlist model, separate role config
  balf:
    - id: TRADER01
      description: HFT algo — same identity as ALF TRADER01
      role: TRADER
    - id: ALGO01
      description: Market-making algorithm
      role: MARKET_MAKER
      mm_max_spread_ticks: 5
      mm_min_qty: 50

balf_gateway:
  bind_address: "0.0.0.0"
  port: 5560
  heartbeat_interval_sec: 1
  heartbeat_timeout_sec:  5
```

A BALF gateway ID does **not** need to match an ALF gateway ID. Both use the
same engine allowlist enforcement, but the `balf:` section is checked
independently of `alf:`.

---

## 12. Implementation Plan (proposed)

| Phase | Deliverable |
|-------|-------------|
| **Phase 1** | `pm-balf-gateway` process: TCP accept loop, LOGON/LOGON_ACK, `NEW_ORDER` → `ORDER_ACK` + `EXECUTION_REPORT`, `CANCEL_ORDER` → `CANCEL_ACK`, `AMEND_ORDER` → `AMEND_ACK`, heartbeat, logout |
| **Phase 2** | `QUOTE_NEW` / `QUOTE_CANCEL` for market-maker gateways; `KILL_SWITCH` message; `OCO_ORDER` |
| **Phase 3** | TLS support; per-session sequence-number recovery / retransmit request |
| **Phase 4** | Benchmark harness comparing ALF vs BALF round-trip latency under load |

Phase 1 requires no changes to the matching engine — only a new process that
speaks BALF on one side and the existing ZeroMQ/JSON engine API on the other.

---

## 13. Open Questions

1. **Byte order**: This proposal uses little-endian throughout. Network
   convention is big-endian (as used by NASDAQ ITCH/OUCH). The argument for LE
   is that all target hardware is x86 and avoiding `htons()`/`ntohl()` on every
   price field saves real cycles. Big-endian would align with FIX binary FAST
   and CME SBE. **Decision needed.**

2. **Order ID space**: The proposal uses the engine's UUID (16 bytes binary).
   Alternatively, BALF could assign a compact `u64` session-scoped order ID
   and maintain a mapping internally, avoiding 16-byte UUIDs on the wire for
   cancel and amend messages. This halves the CANCEL_ORDER frame from 32 to
   24 bytes.

3. **Combo and OCO**: Deferred to Phase 2. The binary encoding of multi-leg
   orders is non-trivial; variable-length leg arrays would break the
   fixed-frame property. Options include a separate `LEG` message type or a
   pre-negotiated maximum leg count with a fixed struct of that size.

4. **Sequence number recovery**: The current proposal detects gaps but does not
   specify a retransmit-request mechanism. Real exchange protocols (CME iLink,
   NASDAQ OUCH) use a separate `Resend Request` message. This needs design for
   Phase 3.

5. **Multicast market data**: BALF currently covers only order entry
   (client → exchange). A companion read-only market data protocol (BDMD —
   Binary Direct Market Data) could be proposed separately for low-latency
   feed consumption.
