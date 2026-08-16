# EduMatcher Market Data Terminal (`pm-terminal`)

A read-only, credential-free Bloomberg-style viewer for the EduMatcher
exchange. Design: [`docs-design/EduMatcher-Terminal-GUI.md`](../../docs-design/EduMatcher-Terminal-GUI.md).

Structured the same way as [`log-gui`](../log-gui): an `apps/*` + `packages/*`
npm workspace, a small first-party Node/Fastify backend alongside a Vite/React
frontend, Zustand for client state.

```
terminal-gui/
  apps/
    bridge/            Fastify: CALF TCP uplink + WS fan-out + history proxy
    web/               React frontend (Vite)
  packages/
    calf-protocol/     CALF wire grammar (TS port of md_gateway/protocol.py)
    lalf-client/       LALF producer client for pm-log-srv
    terminal-types/    Types shared by web + bridge
```

## Status

| Phase | Scope                                                          | State       |
| ----- | -------------------------------------------------------------- | ----------- |
| 1     | `packages/calf-protocol`, `packages/terminal-types`            | done        |
| 2     | `packages/lalf-client`                                         | done        |
| 3     | Bridge CALF uplink + per-symbol reference counting             | done        |
| 4     | Bridge Fastify server: WS fan-out, history proxy, logging      | done        |
| 5     | App shell (light/dark, density presets) + Session & Halt board | done        |
| 6     | Market Overview + Watchlist                                    | done        |
| 7     | Symbol Detail (chart, values, depth toggle)                    | done        |
| 8     | Index View, Trade Tape, Movers                                 | not started |

## Quick start

```bash
make install
make test
make dev            # bridge on :8090, Vite dev server on :5179
```

`make dev-bridge` alone needs a running `pm-md-gwy` on `:5570`; the UI renders
its disconnected state until one is reachable.

## Theme

Dark by default — the working default for a trading screen — with a full light
palette for bright rooms and projectors. Both are CSS-variable sets swapped by
a `.dark` class on `<html>`, so the same Tailwind class names render either.
Amber is the accent because it is the trading-floor convention and stays
legible on both a near-black lobby display and a bright monitor; green and red
are reserved exclusively for price direction, so the one signal a trader scans
for stays scannable.

Density (Lobby / Standard / Dense, design §7.5) and theme both persist to
`localStorage`. Neither is a mode: every route and data point stays reachable
at any setting.

## Bridge configuration

Environment variables, mirroring `log-gui/apps/bridge/src/config.ts`. Design
§19 specifies a YAML file; environment variables are used instead so both
first-party Node backends configure and containerise identically. Names and
defaults still track §19 one-for-one.

| Variable                        | Default                 | Purpose                                                                          |
| ------------------------------- | ----------------------- | -------------------------------------------------------------------------------- |
| `HOST` / `PORT`                 | `127.0.0.1` / `8090`    | Bridge bind address                                                              |
| `CORS_ORIGIN`                   | `*`                     | CORS allow-list                                                                  |
| `STATIC_DIR`                    | —                       | Serve a built frontend from here (single-container mode)                         |
| `MAX_WS_CLIENTS`                | `200`                   | Browser-tab cap (§18)                                                            |
| `CALF_HOST` / `CALF_PORT`       | `127.0.0.1` / `5570`    | `pm-md-gwy`                                                                      |
| `CALF_CLIENT_ID`                | `pm-terminal-bridge`    | `HELLO.CLIENT`                                                                   |
| `CALF_PING_INTERVAL_SEC`        | `60`                    | Keepalive; belt-and-braces since the idle-timer fix — see **CALF changes** below |
| `INDEX_IDS`                     | —                       | Comma-separated index ids to `SUB\|CH=INDEX` for                                 |
| `API_GATEWAY_URL`               | `http://127.0.0.1:8080` | `pm-api-gwy`                                                                     |
| `PM_TERMINAL_API_KEY`           | —                       | Read-only (`gateway_id: null`) key, history reads only                           |
| `LOG_SRV_ENABLED`               | `true`                  | `false` skips even the startup probe                                             |
| `LOG_SRV_HOST` / `LOG_SRV_PORT` | `127.0.0.1` / `5600`    | `pm-log-srv`                                                                     |
| `LOG_CONNECT_TIMEOUT_SEC`       | `0.5`                   | Startup probe and each reconnect attempt                                         |
| `LOG_FAILOVER_TIMEOUT_SEC`      | `30`                    | Grace window before the one-way switch to file                                   |
| `LOG_QUEUE_MAXSIZE`             | `2000`                  | Bounded backlog while reconnecting                                               |
| `LOG_FAILOVER_DIR`              | `<data>/logs`           | Where the post-failover log file goes                                            |

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

**7. Per-symbol auction badges are unreachable (§8.4).** The column table wants
a "halted / auction indicator" on the symbol from CALF `STATE`. Only the halt
half is possible: `normalise_halt`/`normalise_resume` emit `HALTED` or
`CONTINUOUS` and nothing else per symbol, and auction phases arrive
exchange-wide under `SYM=*`. Overview badges halts; the exchange phase shows in
the status strip.

**8. History rows use `ts`, not `timestamp`.** The `TradeRow` and
`PriceSnapshotRow` types written in Phase 1 named the column `timestamp`; the
endpoints return `ts`, straight off pm-stats' SQLite with no renaming in the
proxy. Nothing exercised those types until the chart did, at which point every
bar would silently have vanished. Corrected, along with the fields those rows
actually carry (`trade_id`, gateway ids, `pct_change`).

**9. `GET /history/daily` needs no per-symbol polling (§8.5).** The design has
the grid re-poll "for every symbol currently visible". Omitting both `symbol`
and `date` returns every symbol for the latest available date in one request,
which is fewer round trips and stays correct as the grid pages.

**10. Change is quoted against the previous close, not the session open
(§8.4, §9.5).** The design's column table defines `Chg`/`%Chg` relative to
today's open, and the Movers board (§12) ranks on that same figure. An open
cannot represent a gap: a symbol that opened 5% below yesterday's close and has
since recovered 1% is down on the day, but against its own open it reads
`+1.00%`, in green, and sorts onto the **Gainers** tab. Every terminal quotes
the previous close for that reason, so this one does too. `open` remains its
own column and its own row on Symbol Detail.

Nothing publishes a previous close — it is absent from CALF and `/history/daily`
has no such column — so `lib/prev-close.ts` derives one from a ten-day window of
the ranged `/history/daily` form (one request, every symbol). The newest date in
that window marks the current session and the most recent close before it is the
reference; a symbol whose window holds only the current session, because it was
listed today or has been dormant longer than the window, falls back to the open
and is **marked** as doing so rather than quietly meaning something different
from the row above it.

The three views that quote a change all route it through the one `buildRows` in
`lib/overview-rows.ts`. Symbol Detail previously computed its own, which is how
it came to disagree with the grid while wearing the same label.

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
though not on merely _queuing_ one, so a client that has stopped draining still
ages out. `idle_timeout_sec`'s runtime default also moved 300 → 5, matching the
sample config, config generator, config spec and both protocol docs; 300 only
ever made sense as cover for this bug. `CALF_PING_INTERVAL_SEC` is now
belt-and-braces rather than load-bearing.

**`TOP.LAST` refreshes after a trade.** `normalise_trade` wrote the new price
into the gateway's top-of-book cache so a `SNAP` would be immediately right —
which also made the next `normalise_book` see `LAST` as unchanged and suppress
it. `MD` therefore never carried a new last price, leaving a
continuously-connected client on the value baked into its original `SNAP`
while a reconnecting one saw the truth. The cache was serving two masters:
"current state, for `SNAP`" and "last value sent, for diffing". These are now
separate (`top_cache` and `top_sent`), so both are correct with no staleness
window, and `TopOfBook` is frozen like its `DepthBook`/`CBStatus` siblings —
the shared instance had made an in-place mutation reach through both.

**`RESUME` is a standalone, repeatable command.** It was a `RESUME=1` flag on
`HELLO`, which the gateway processes exactly once per connection — so a client
following several streams could recover one and had to take the gap on the
rest. `RESUME|CH=..|SYM=..|LASTSEQ=..` is now sent after the handshake, as many
times as needed, and a malformed one returns `ERR` without closing the session.

The bridge now uses it. `CalfUplink` tracks the last `SEQ` seen per
`(channel, symbol)`, independent of any one connection — the gateway's own
counters live in its process, not the socket, so a value from before a
reconnect is exactly what is needed to notice the drop cost anything. A gap on
`TOP`/`STATE`/`DEPTH`/`CB` is left for the `SNAP` the reconnect's `SUB` already
triggers; those channels have a baseline, so resuming them too would just
replay data about to be superseded. `TRADE` has no baseline — a missed print
is gone unless replayed, and it is also the one channel read as a record
rather than as current state (§11) — so a `TRADE` gap gets a per-symbol
`RESUME` instead. `AUCTION` shares that no-baseline shape but is not resumed,
to keep this change to the stream the report actually named; its gaps are
still reported, same as a `TRADE` gap the gateway could no longer replay
(`ERR|CODE=REPLAY_MISS`). The web app surfaces an unrepaired gap as a marker
row in the Trade Tape, in place among the prints it falls between — a `TRADE`
gap only; an `AUCTION` one is dropped in the store, because the marker says
"prints were missed" and that is false of any other channel.

Three things about `RESUME` are easy to get wrong and are worth stating.

`replay_since` returns **everything** past `LASTSEQ`, not just what the client
missed — so a reply re-sends the message that revealed the gap, and anything
delivered live while the request was in flight. `CalfUplink` records the
sequence range each `RESUME` was sent for and emits a below-baseline message
only if it falls inside one; outside, it is a redelivery and is dropped.
Getting this wrong in either direction is a data defect: emit the duplicates
and the same trade prints twice, drop them all and the backfill is lost.

A `SNAP` **re-baselines**, and is never a gap. The gateway answers
`REPLAY_MISS` with one, so a `SNAP` that left the baseline behind would make
the next live message look like a fresh gap and `RESUME` again, against a
window already proved too old — once per print, indefinitely.

A sequence going backwards on a *new connection* is a gateway that restarted,
not a replay: its counters live in process memory and begin again at 1. That
case adopts the new numbering. Treating it as duplicates would black the
stream out for as long as the new gateway lives.

Gateway-side, `RESUME` no longer sends a `SNAP` after `REPLAY_MISS` on `TRADE`
or `AUCTION`. `_send_snapshot_for_stream` has no branch for either, so what it
produced was an envelope with no payload — which `decodeTrade`, keyed on `CH`
like every other line, read as a print of zero shares at zero price. The bridge
drops such a `SNAP` too, since it has to work against gateways that still send
one.

**`REF` carries per-symbol display precision.** Every price on every screen
was rendered at two decimals, because that is `price()`'s default and nothing
overrode it. `tick_decimals` is per-symbol and configurable, so a symbol quoted
to four decimals had its last price, spread, bps spread, OHLC, VWAP and range
bar all silently rounded — and there was no way to fix it here, because the
only client-reachable source was `GET /api/symbols`, behind a trading
credential this terminal deliberately does not hold.

That is a gap for _every_ CALF consumer, not just this one, so it was closed in
the protocol: `WELCOME` and the `SYMBOLS` reply now carry `REF=SYM:DEC,...`.
Reference data rather than market data, so it rides the handshake instead of
repeating a constant on every `TOP` tick. Its presence is the capability
signal, exactly as `CH_SUPPORTED`'s is, so no `PROTO` bump and no existing
client breaks; a gateway without it means the terminal falls back to two
decimals knowingly. The tuple grows to `SYM:DEC:MULT:CCY` when contract
multiplier and currency land.

### Also deliberate, not a design error

- `GET /api/symbols` is still **not** proxied. It requires a trading credential
  (`require_trading` in `api_gateway/routers/reference.py`), which is design
  §22's open question 1. `REF` removes the only pressing reason to want it —
  display precision — so this can stay closed until reference data the wire
  does not carry is actually needed.
- `LalfClient` queues log _records_, not pre-encoded frames. The Python
  original queues bytes and so must discard its backlog at failover; holding
  records lets that backlog reach the fallback file, which is what §17.5's
  "no log call is ever silently dropped" actually asks for.

## TODO

- `AUCTION` gaps are reported but not resumed, unlike `TRADE` — see `CalfUplink`'s class docstring and `RESUMABLE_CHANNELS`. Worth doing if auction prints turn out to matter to a reader the way trade prints do.
