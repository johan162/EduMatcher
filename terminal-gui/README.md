# EduMatcher Market Data Terminal (`pm-terminal`)

A read-only, credential-free Bloomberg-style viewer for the EduMatcher
exchange. Design: [`docs-design/EduMatcher-Terminal-GUI.md`](../docs-design/EduMatcher-Terminal-GUI.md).

Structured the same way as [`log-gui`](../log-gui): an `apps/*` + `packages/*`
npm workspace, a small first-party Node/Fastify backend alongside a Vite/React
frontend, Zustand for client state.

```
terminal-gui/
  apps/
    bridge/            Fastify: CALF TCP uplink + WS fan-out + history proxy
    web/               React frontend (Vite)          [not yet built]
  packages/
    calf-protocol/     CALF wire grammar (TS port of md_gateway/protocol.py)
    lalf-client/       LALF producer client for pm-log-srv
    terminal-types/    Types shared by web + bridge
```

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | `packages/calf-protocol`, `packages/terminal-types` | done |
| 2 | `packages/lalf-client` | done |
| 3 | Bridge CALF uplink + per-symbol reference counting | done |
| 4 | Bridge Fastify server: WS fan-out, history proxy, logging | done |
| 5+ | Web shell, Overview, Symbol Detail, Index, Tape, Movers, Depth | not started |

## Quick start

```bash
make install
make test
make dev-bridge     # needs a running pm-md-gwy on :5570
```

## Bridge configuration

Environment variables, mirroring `log-gui/apps/bridge/src/config.ts`. Design
§19 specifies a YAML file; environment variables are used instead so both
first-party Node backends configure and containerise identically. Names and
defaults still track §19 one-for-one.

| Variable | Default | Purpose |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8090` | Bridge bind address |
| `CORS_ORIGIN` | `*` | CORS allow-list |
| `STATIC_DIR` | — | Serve a built frontend from here (single-container mode) |
| `MAX_WS_CLIENTS` | `200` | Browser-tab cap (§18) |
| `CALF_HOST` / `CALF_PORT` | `127.0.0.1` / `5570` | `pm-md-gwy` |
| `CALF_CLIENT_ID` | `pm-terminal-bridge` | `HELLO.CLIENT` |
| `CALF_PING_INTERVAL_SEC` | `60` | Keepalive; belt-and-braces since the idle-timer fix — see **CALF changes** below |
| `INDEX_IDS` | — | Comma-separated index ids to `SUB\|CH=INDEX` for |
| `API_GATEWAY_URL` | `http://127.0.0.1:8080` | `pm-api-gwy` |
| `PM_TERMINAL_API_KEY` | — | Read-only (`gateway_id: null`) key, history reads only |
| `LOG_SRV_ENABLED` | `true` | `false` skips even the startup probe |
| `LOG_SRV_HOST` / `LOG_SRV_PORT` | `127.0.0.1` / `5600` | `pm-log-srv` |
| `LOG_CONNECT_TIMEOUT_SEC` | `0.5` | Startup probe and each reconnect attempt |
| `LOG_FAILOVER_TIMEOUT_SEC` | `30` | Grace window before the one-way switch to file |
| `LOG_QUEUE_MAXSIZE` | `2000` | Bounded backlog while reconnecting |
| `LOG_FAILOVER_DIR` | `<data>/logs` | Where the post-failover log file goes |

## Deviations from the design document (v1.5.0)

Each of these was found by checking the design against shipped code
(`src/edumatcher/md_gateway/`, `api_gateway/routers/`, `logclient/`) before
implementing. Three turned out to be defects in CALF itself and were fixed
upstream rather than worked around here — see **CALF changes** below.

**1. `CB.RESUMEAT` is ISO-8601 text, not epoch nanoseconds (§17.3).**
`normaliser._ns_to_iso()` converts the engine's `resume_at_ns` before it
reaches the wire. The WS frame field is `resumeAt: string`, not `resumeAtNs`.

**2. CALF `MD` messages are deltas (§17.3).** `normalise_book` emits only
fields whose value changed. §17.3's `top` frame implies a complete book every
time. The bridge keeps a per-symbol `TopCache` and fans out the merged view, so
the documented frame shape holds for browsers — but something had to do the
merging, and doing it once server-side is cheaper than once per tab.

**3. There is no `date=today` (§8.5).** `validate_date` requires a real date;
omitting `date` returns the latest available row. The frontend should omit it
rather than send the literal `today`.

**4. Exchange-wide `STATE` arrives under `SYM=*` (§17.3).**
`normalise_session_state` returns the literal `"*"` as its symbol. §17.3's one
worked example shows a concrete symbol, which would lead a reader to assume
session transitions are per-symbol. Both forms travel on the same
`SUB|CH=STATE|SYM=*` subscription and consumers must distinguish them.

**5. `SNAP|CH=INDEX` can be metadata-only (§10).** `index_snapshot_fields`
returns an empty map until pm-index publishes its first `index.update`, so a
fresh subscriber's first `index` frame may carry no `level` at all. Not an
error state; the Index view must render it as "no data yet".

**6. `ERR|CODE=SLOW_CLIENT` is never sent (§17.1).** The gateway drops an
over-queued client silently: `_queue_raw` clears the queue and marks the
session closing, then `_flush_client_writes` disconnects. `240-calf-gateway.md`
already documents this honestly; §17.1 of the terminal design assumed the
`ERR` was actionable. Handled as an ordinary close.

## CALF changes made while building this

Three findings were protocol or gateway defects affecting every CALF consumer,
not just this terminal, so they were fixed at the source.

**A withdrawn book side is now representable.** `MD` omitted `BID` entirely
when the last resting bid was lifted, sending only `BIDSZ=0`. Omission means
"unchanged" to a delta-merging client, so the stale price stayed on screen
indefinitely — while a client that reconnected got a `SNAP` with no bid at all.
Two clients on the same feed, disagreeing about the book, forever. `MD` now
sends an explicitly empty `BID=`/`ASK=` to mark a side withdrawn; `TopDelta`
carries `null` for it and `TopCache` clears the field.

**The idle timer honours outbound traffic.** `ClientSession.last_activity`
advanced only in `_read_client_data`, contradicting the protocol's own
documented "no inbound **and** no outbound traffic" rule, so any purely passive
consumer was dropped on a fixed cycle. It now advances on a successful send —
though not on merely *queuing* one, so a client that has stopped draining still
ages out. `idle_timeout_sec`'s runtime default also moved 300 → 5, matching the
sample config, config generator, config spec and both protocol docs; 300 only
ever made sense as cover for this bug. `CALF_PING_INTERVAL_SEC` is now
belt-and-braces rather than load-bearing.

**`RESUME` is a standalone, repeatable command.** It was a `RESUME=1` flag on
`HELLO`, which the gateway processes exactly once per connection — so a client
following several streams could recover one and had to take the gap on the
rest. `RESUME|CH=..|SYM=..|LASTSEQ=..` is now sent after the handshake, as many
times as needed, and a malformed one returns `ERR` without closing the session.
`buildResume` is available in `packages/calf-protocol`; the bridge does not use
it yet (see TODO).

### Also deliberate, not a design error

- `GET /api/symbols` is **not** proxied. It requires a trading credential
  (`require_trading` in `api_gateway/routers/reference.py`), which is design
  §22's open question 1. It is wired in only once that is resolved.
- `LalfClient` queues log *records*, not pre-encoded frames. The Python
  original queues bytes and so must discard its backlog at failover; holding
  records lets that backlog reach the fallback file, which is what §17.5's
  "no log call is ever silently dropped" actually asks for.


## TODO

- The bridge does not use RESUME yet. It still reconnects and re-subscribes, which the design accepts for a display-only viewer; wiring it up needs per-stream last_seq tracking in the uplink and would change reconnect behaviour. Worth doing as its own change.