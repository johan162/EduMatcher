# Trader Information Terminal — "TapeDeck" (`pm-terminal`)

!!! note "Learning objectives"
    After reading this page you will understand:

    - What the Trader Information Terminal is for, and when to use it instead
      of a trading or administration tool
    - Which services must be running before the display becomes useful
    - How to start the terminal locally or in a container
    - What each of the six screens is meant to help a viewer understand
    - How to recognise normal disconnected, missing-history, and no-index
      states without mistaking them for broken screens
    - Which settings an operator is most likely to adjust


## Overview

**TapeDeck** is the friendly nickname this guide uses for the Trader
Information Terminal, whose system name is `pm-terminal` and whose source code
lives in `web-apps/terminal-gui/`. It is a read-only market display for the EduMatcher
exchange: a browser window for watching live prices, trades, auctions, halts,
indexes, and depth-of-book information.

It is deliberately *not* a trading application. There is no order entry, no
login screen, and no write path from the browser back into the exchange. Use it
for a classroom wallboard, a demo display, an observer workstation, or a quick
operator check that the market-data feed is alive. Use the trading client for
placing orders, and the administration tools for changing exchange state.

The terminal shows live data from the [CALF market-data feed](240-calf-gateway.md)
and reads historical bars and index history through the [API Gateway](260-api-gateway.md).
The browser never sees an API key; the small bridge process running beside the
web UI holds the upstream connections.


### What starts when you run it

Running TapeDeck starts one server process, `pm-terminal-bridge`, and serves
the web page from that same process in the container setup. The bridge opens
one live CALF connection to [`pm-md-gwy`](240-calf-gateway.md), shares that
single feed across every open browser tab, and opens history requests to
[`pm-api-gwy`](260-api-gateway.md) when charts or previous-close data are
needed. Optional operational logs go to
[the centralized log server](280-log-srv.md) when it is available.

Most users do not need the following diagram to operate the terminal, but it
is useful when deciding which host names and ports to put in the container
environment.

```mermaid
flowchart LR
    subgraph Browser["Browser tab(s)"]
        UI["React app\n(Zustand + TanStack Query)"]
    end
    UI -->|"WS /ws/stream\n(JSON frames)"| BRIDGE["pm-terminal-bridge\nFastify + Node :8090"]
    UI -->|"REST /api/history/*\n(proxied)"| BRIDGE
    BRIDGE -->|"CALF TCP :5570\none session, shared by every tab"| MDGWY["pm-md-gwy"]
    BRIDGE -->|"REST GET /history/*\n(server-held API key)"| APIGWY["pm-api-gwy :8080"]
    BRIDGE -.->|"LALF TCP :5600\noperational logging"| LOGSRV["pm-log-srv"]
```

## Prerequisites

| Requirement | Notes |
|---|---|
| **`pm-md-gwy`** ([CALF gateway](240-calf-gateway.md)) | Required for live prices, trades, session state, auctions, halts, indexes, and depth. The terminal can start without it, but it will show `RECONNECTING`/`OFFLINE` until the feed is reachable. |
| **`pm-api-gwy`** ([API Gateway](260-api-gateway.md)) with a read-only API key | Required for charts, previous-close data, index history, and Overview/Movers `Open`/`Volume` columns. Live prices still tick without it. |
| **`pm-log-srv`** ([Centralized Log Server](280-log-srv.md)) — optional | Used only for operational logs. If it is unavailable, the terminal still starts and writes to stdout or the local failover log directory. |
| **Podman ≥ 4** or **Docker ≥ 24** with a Compose plugin | Needed for the recommended container run path. |
| **Node.js ≥ 20** and **npm ≥ 10** | Needed only for local development without a container. |

## Running the application

### Recommended: run the container

Start the exchange services first, or at least know where they are reachable
from inside the container:

1. Start `pm-md-gwy` so live CALF market data is available.
2. Start `pm-api-gwy` and provide a read-only `PM_TERMINAL_API_KEY` if you want
    charts, previous-close comparisons, and historical index data.
3. Optionally start `pm-log-srv` for centralized operational logs.
4. Start TapeDeck and open the browser.

From `web-apps/terminal-gui/`:

```bash
export PM_TERMINAL_API_KEY='...'   # read-only API-gateway key, history only
make up                            # auto-detects Docker or Podman
```

Then open **http://localhost:8090**. Use `make logs` to follow the bridge log
and `make down` to stop the container.

The Compose file defaults to services on the host machine. The defaults work
on Docker Desktop. On Podman, or if Linux Docker cannot resolve
`host.docker.internal`, set the host names explicitly before starting:

```bash
export CALF_HOST=host.containers.internal
export API_GATEWAY_URL=http://host.containers.internal:8080
export LOG_SRV_HOST=host.containers.internal
make up
```

Use `TERMINAL_GUI_PORT` if port `8090` is already taken on the host:

```bash
TERMINAL_GUI_PORT=8091 make up
```

The container serves the built React frontend, the WebSocket endpoint, and the
small read-only history proxy from the same port. There is no database volume:
the only bind mount is `./logs:/app/logs`, used when the optional log server is
not reachable after startup.

### Alternative: direct Compose commands

```bash
PM_TERMINAL_API_KEY='...' docker compose up --build -d
docker compose logs -f terminal-gui
docker compose down
```

With Podman, use `podman-compose` for the same commands.

### Running on a separate display server

TapeDeck does not have to run on the same machine as the matching engine,
`pm-md-gwy`, or `pm-api-gwy`. A common deployment is:

- **Exchange server**: runs the engine, `pm-md-gwy`, `pm-api-gwy`, and
  optionally `pm-log-srv`.
- **Display server**: runs only the TapeDeck container and serves the browser
  UI to viewers.

No protocol change is needed on the exchange side. The terminal bridge is just
another external CALF client plus a read-only history client. The practical
requirements are:

| Exchange-side item | What to check |
|---|---|
| `pm-md-gwy` | It normally binds to `0.0.0.0:5570`, so no application change is needed unless your config deliberately set `market_data_gateway.bind_address` to `127.0.0.1`. The display server must be able to open TCP `5570` on the exchange host. |
| `pm-api-gwy` | It normally binds to `0.0.0.0:8080`, so no application change is needed unless your config deliberately set `api_gateways.<name>.host` to `127.0.0.1`. The display server must be able to reach HTTP `8080`. |
| API key | Create or reuse a read-only `pm-api-gwy` key with `gateway_id: null`; TapeDeck only needs history reads and never sends the key to browsers. |
| `pm-log-srv` | Optional. If you want centralized terminal logs, make TCP `5600` reachable and set `LOG_SRV_HOST` on the display server. If not, set `LOG_SRV_ENABLED=false` or let the container write its fallback log to `./logs`. |
| Firewall / routing | Open only the ports the display server actually needs: TCP `5570` for CALF, TCP `8080` for history, and optionally TCP `5600` for logs. Browsers only need access to the display server's `8090` port, not to the exchange gateways. |

On the display server, use the prepared image rather than building from source.
The exact image name depends on how the release was delivered:

```bash
# Option A: image from a registry
podman pull edumatcher-terminal-gui:<VERSION>

# Option B: image tarball from a release bundle
podman load --input edumatcher-terminal-gui-<VERSION>.tar.gz
```

Then run the container, pointing it at the exchange server's network name or IP
address:

```bash
mkdir -p logs

podman run -d --name terminal-gui \
  --restart unless-stopped \
  -p 8090:8090 \
  -v "$PWD/logs:/app/logs" \
  -e CALF_HOST=exchange.example.org \
  -e CALF_PORT=5570 \
  -e API_GATEWAY_URL=http://exchange.example.org:8080 \
  -e PM_TERMINAL_API_KEY='...' \
  -e INDEX_IDS=MAIN \
  -e LOG_SRV_ENABLED=false \
  edumatcher-terminal-gui:<VERSION>
```

Use `docker` instead of `podman` if that is your container runtime. If
centralized logging is available, replace `LOG_SRV_ENABLED=false` with:

```bash
-e LOG_SRV_ENABLED=true \
-e LOG_SRV_HOST=exchange.example.org \
-e LOG_SRV_PORT=5600
```

After startup, open **http://display-server.example.org:8090** from a browser.
If the page loads but shows `RECONNECTING`, the display server can serve the
UI but cannot reach `pm-md-gwy`. If live prices tick but charts or previous
close values are missing, check `API_GATEWAY_URL` and `PM_TERMINAL_API_KEY`.

### Local development

From the `web-apps/terminal-gui/` directory:

```bash
make install    # npm workspace install
make dev        # bridge on :8090, Vite dev server on :5179
```

Open **http://localhost:5179** for the Vite development server. The web app
talks to the bridge on **http://localhost:8090**. If `pm-md-gwy` is not yet
running, the page can load but the connection indicator will show
`RECONNECTING`/`OFFLINE` until the feed appears. `make dev-bridge` runs only
the bridge, `make dev-web` runs only the web server, and `make test` runs the
Vitest suite across the workspace.

## A tour of the interface

📷 **Figure 1 — The app shell.** Capture the Overview screen in dark theme,
showing the full shell: the top bar (app name, the six view tabs, density and
theme toggles, the connection indicator) and the footer status strip.
Suggested file: `images/terminal-gui/fig-01-app-shell.png`.

### Top bar

A single row (not a collapsible sidebar — six destinations is small enough
for one row, and a data-dense terminal wants its horizontal space for
numbers, not navigation chrome) holding:

- The six view tabs: **Overview**, **Symbol**, **Index**, **Tape**,
  **Movers**, **Session**.
- A **density** control (gauge icon) that cycles **Lobby → Standard →
  Dense**. This is a display preference, not a mode — every route and every
  data point stays reachable at every setting; only defaults change (larger
  type and a longer page delay under Lobby, tighter rows and shorter delay
  under Dense). It persists to the browser's `localStorage`, so a different
  browser or profile always starts on **Standard**.
- A **theme** toggle (dark by default — the working default for a trading
  screen — with a full light palette for bright rooms and projectors).
- A **connection indicator**: `LIVE` (green), `RECONNECTING` (amber), or
  `OFFLINE` (red), reflecting the bridge's own CALF session state, plus the
  gateway id it is talking to.

### Status strip (footer)

A single-line summary meant to be readable from across a room: the current
session phase (blank/no badge during `CONTINUOUS` — the absence of a badge
*is* the "everything is normal" signal),
a countdown to the next scheduled phase transition when the feed has named
one, the number of currently-halted symbols, the total symbol count, the
CALF connection state, **the age of the last market-data tick**, and a UTC
clock.

!!! note "Connection state and data age are two different readings, on purpose"
    "CALF connected" only says the pipe is open — it says nothing about
    whether anything is actually coming down it, and a feed that has gone
    silent behind a healthy socket is exactly the failure a reader most needs
    to catch. The status strip shows both: connection state, and separately,
    how long it has been since the last tick arrived. A silently frozen
    exchange still reads "CALF connected" but its tick age keeps climbing.

## Screen tour

### Market Overview

The default landing view: every tradable symbol, paginated, meant to run
unattended on a classroom or lobby display just as well as be actively
browsed.

📷 **Figure 2 — Market Overview.** Capture a multi-page symbol list mid-session
with a mix of up/down movers and at least one halted symbol, the Watchlist
toggle visible. Suggested file: `images/terminal-gui/fig-02-overview.png`.

Key behaviors:

- **Auto-paging.** Rows are split into pages sized to fit the viewport
  (`⚙` control offers 3s/5s/8s/15s/30s dwell times, or a density-based
  default), so the grid never needs to scroll — useful for an unattended
  display with no mouse. Hovering the grid, sorting a column, or typing in
  the symbol search **suspends** auto-advance (a reader who is actively
  interacting with the board should not have it slide out from under them);
  the manual `‹`/`›`/pause controls keep working regardless.
- **Every row stays live on every page.** Paging is purely a rendering
  concern — the bridge already holds one wildcard subscription covering
  every symbol, so there is no per-page subscribe/unsubscribe to do, and
  numbers on a page you are not currently viewing never go stale.
- **Sortable columns** and a **type-ahead symbol search** — both narrow/order
  what is shown without touching the underlying subscription.
- **Watchlist.** Click the `☆` next to any symbol to pin it; the
  `All`/`☆ Watchlist` toggle switches the grid between paging through every
  symbol and paging through only pinned ones. This is client-only,
  `localStorage`-persisted state — there is no server-side watchlist and
  nothing to log into.
- **A row fades after a configurable silence threshold** (`fade …` control —
  choices from 1 minute to 1 hour, or off). The right value is a property of
  the exchange, not of the terminal: a busy, liquid book and a thin classroom
  exchange want very different thresholds, so it is exposed rather than
  hardcoded.
- **During a call auction phase**, the quote columns (`Bid`/`Ask`) are
  replaced by auction-indicative columns (indicative uncross price/quantity,
  imbalance) for symbols currently in an opening or closing auction — a call
  phase is a different kind of market, not a display preference, so the grid
  follows it automatically rather than offering a toggle.
- **Not-executable banners.** When the whole board is outside continuous
  trading (closed, or in a call auction), a banner says so explicitly rather
  than merely dimming the numbers — the prices and volumes shown remain an
  accurate record, they are just not currently tradable. A separate banner
  appears if the previous-close lookup failed (percentage change is then
  measured from today's open instead, and marked with a small `*`) or if the
  history service itself is unreachable (Open/Volume/Turnover columns go
  blank; live prices are unaffected).

### Symbol Detail

The deep-dive view for one instrument: a candlestick + midpoint chart, a
values table, and an optional depth ladder. Large-screen only, by design —
there is no responsive mobile layout.

📷 **Figure 3 — Symbol Detail.** Capture a symbol with a visible price history
(1D or 5D preset), both the OHLC and Midpoint series toggled on, and the
Values panel. A second capture with the Depth toggle on instead of Values
would usefully show the two-panel swap described below. Suggested files:
`images/terminal-gui/fig-03-symbol-detail.png` and
`images/terminal-gui/fig-03b-symbol-detail-depth.png`.

- **Header.** Symbol, session badge, last price, change and %change (always
  quoted against the *previous close*, footnoted when no previous close is
  on record and the figure falls back to today's open instead), and today's
  volume.
- **Chart.** Time-window presets (`1D`/`5D`/`1M`/`3M`/`YTD`/`All`/`Live`),
  free-form drag-zoom, and two independently toggleable series: OHLC
  candlesticks (built from historical bars, with the live-forming bar updated
  in place from CALF `TRADE` prints) and a spliced midpoint line — a coarser,
  15-minute-resolution historical segment giving way to a tick-by-tick live
  segment from CALF `TOP`, drawn in a slightly muted style where it is the
  coarser data. A reference line for the previous close is always drawn, and
  a VWAP line appears on the `1D`/`Live` presets only (VWAP is a same-session
  benchmark; drawing it across a multi-day preset would be quoting today's
  average against days it has nothing to do with).
- **Auction and halt context.** An auction uncross fills a dismissible
  banner (equilibrium price or "no cross," matched quantity, and any residual
  imbalance) that distinguishes an opening/closing auction, a
  circuit-breaker **reopening** auction, and a startup/recovery uncross by
  name, rather than calling all three "auction uncrossed." A halted symbol
  expands to show the circuit-breaker detail — trigger level, trigger and
  reference price, and a **corridor bar** showing the price band the symbol
  may reopen inside, with the last indicative price marked against it. This
  is the visual explanation of *why* a halt is still running: if the marker
  sits outside the band, the call phase was extended rather than printing.
- **Values panel ↔ Depth ladder.** The `☐ Depth` toggle *replaces* the
  Values panel with the [Depth-of-Book ladder](#depth-of-book) rather than
  showing both side by side. This is deliberate, not a space-saving
  afterthought: unlike `OHLC`/`Midpoint`, which reuse subscriptions the
  bridge already holds for every symbol, turning Depth on causes the bridge
  to open a brand-new per-symbol CALF subscription — so it is opt-in per
  viewer, and the panel swap is a visible reminder that this is a heavier,
  deliberately-requested data stream.

### Depth-of-Book

A Level 2 ladder (aggregated quantity per price level — never per-order
identity, which CALF does not carry at any version) for whichever symbol
currently has the Depth toggle on in Symbol Detail. It is not its own
navigation tab.

📷 **Figure 4 — Depth ladder.** Capture a symbol with resting orders on both
sides, ideally with at least one row whose distance-from-touch marker is
visible. Suggested file: `images/terminal-gui/fig-04-depth-ladder.png`.

Columns run outward from the touch in both directions —
`Cum | Qty | # | Bid ‖ Ask | # | Qty | Cum` — so the two best prices meet in
the middle and the cumulative totals sit at the outer edges, where the eye
ends up after scanning inward. Two things worth calling out:

- **The `#` column** is the count of individual resting orders aggregated
  into that price level — genuinely useful context a bare quantity doesn't
  convey (1,400 shares from one order reads very differently than the same
  1,400 split across four), and it costs nothing extra since `COUNT` is
  already on the CALF wire.
- **Rows are evenly spaced regardless of price gaps**, with the actual
  distance from the touch shown as a percentage figure beside each row
  instead. Spacing rows by price would collapse to unreadable slivers the
  moment one level sat far out; the trade-off is that a lone level far from
  a tight cluster would otherwise look like just the next rung down, which
  is exactly what the percentage-distance figure (and a subtle highlight
  when a level is unusually far out) corrects for.

A **Bid depth / Ask depth / Imbalance** summary line below the ladder states
the book's lean as a percentage (e.g. "62% bid") rather than a bid:ask ratio,
since a ratio's useful range is lopsided (0.2 and 5.0 are the same imbalance
mirrored) while a percentage reads the same distance from 50% either way.

### Index View

Headline level and a historical chart for a configured exchange index (see
[Market Index](150-market-index.md)).

📷 **Figure 5 — Index View.** Capture the chart on a `1M`+ preset (to show the
daily-bar rendering) alongside the Open/High/Low panel and, if any exist,
the Recent changes strip. Suggested file: `images/terminal-gui/fig-05-index-view.png`.

The headline level, change, and session badge always come from the **live**
CALF `INDEX` stream, never from a historical REST row for the current date —
`/history/index-daily`'s `close_level` is only guaranteed final once the
session for that date has actually closed, so quoting it live for *today*
would risk showing a figure that is still moving. Open/High/Low are safe to
read from the REST row even intraday, since those are running-so-far values
that only get more accurate as the day progresses. Switching indexes (when
more than one is configured) costs nothing upstream — the bridge holds a
standing subscription for every configured index regardless of which one a
given tab is currently viewing. If the exchange has no index configured at
all, the tab still exists and shows an explicit empty state rather than
being hidden, so the tab row never shifts between differently-configured
classroom exchanges.

### Trade Tape / Time & Sales

Every print on the exchange, newest first, filterable by symbol.

📷 **Figure 6 — Trade Tape.** Capture the unfiltered tape with several
symbols' prints visible. If reproducible, a second capture showing a gap
marker row would be a good addition — see the callout below for how to
trigger one deliberately in a test environment.
Suggested file: `images/terminal-gui/fig-06-trade-tape.png`.

The symbol filter narrows what is *displayed*; the bridge's underlying
`SYM=*` wildcard subscription means every symbol's prints are already
arriving regardless of the filter, so switching it is instant and free.
`Pause` freezes the visible rows without losing anything — the tape keeps
recording underneath, and `Resume` shows the current state rather than a
gap where the pause was.

!!! note "Gap markers are a real, shipped feature, not a hypothetical"
    If the bridge's CALF connection drops and cannot fully repair a symbol's
    trade sequence on reconnect (the replay window has already rolled past
    the missed messages), the tape shows an explicit marker row — *"gap in
    the tape — some prints for `SYMBOL` were missed"* — in place among the
    prints it falls between, rather than silently omitting the missing
    prints or, worse, saying nothing at all. A record with an unmarked hole
    in it is worse than one that admits the hole, because a viewer has no
    way to tell it apart from a genuinely quiet stretch. This is the direct
    result of a real CALF protocol fix made while building TapeDeck.

### Movers

A different ranking over the same data the Overview grid already computes —
no new subscriptions.

📷 **Figure 7 — Movers.** Capture the Gainers tab with several bars of
different lengths visible. Suggested file: `images/terminal-gui/fig-07-movers.png`.

Three tabs: **Gainers** and **Losers** rank by percentage change from the
previous close (falling back to today's open, and labelled as such, when no
previous close is available); **Active** ranks by session turnover (value
traded) instead — a common third view on real market boards, and cheap here
since Overview already computes turnover per symbol. Each row's bar is
scaled relative to the largest value currently shown on that tab.

### Session & Halt Status Board

Three panels in one view: the exchange-wide session phase, every symbol
currently halted with its full circuit-breaker detail, and the auctions that
have uncrossed since the tab was opened.

📷 **Figure 8 — Session & Halt Status Board.** Capture a state with at least
one active halt and one completed auction result, so both tables have
content. Suggested file: `images/terminal-gui/fig-08-session-board.png`.

- **Active halts** shows, per halted symbol: circuit-breaker level, trigger
  and reference price (blank for an operator-initiated halt, which carries
  neither), how and when it resumes (a converted wall-clock time for a timed
  halt, or `Manual` for one that only ends on an explicit operator action),
  and how long it has been halted.
- **Recent auction results** is a session-scoped, client-side ring buffer of
  every auction uncross seen since the tab opened — not a durable audit
  trail (that is `pm-index`'s own structural log, surfaced separately via the
  Index View's "Recent changes" strip). An omitted equilibrium price is
  labelled `(no cross)` rather than shown as a blank, since "no crossable
  interest at all" is a meaningfully different outcome from a price, just an
  unusual one.
- Opening this view is itself one of the two triggers for the bridge to hold
  a per-symbol `CB` subscription (the other is opening that symbol's own
  Symbol Detail view) — closing the tab releases every subscription it was
  the sole reason for.

## Configuration reference

The container is configured with environment variables. Most installations only
need to set `PM_TERMINAL_API_KEY` and, when the upstream services are not on the
default host names, `CALF_HOST`, `API_GATEWAY_URL`, and `LOG_SRV_HOST`.

| Variable | Container default | Purpose |
|---|---|---|
| `TERMINAL_GUI_PORT` | `8090` | Host port exposed by `docker-compose.yml`; use this when `8090` is already in use. |
| `HOST` / `PORT` | `0.0.0.0` / `8090` | Bridge bind address inside the container. |
| `CORS_ORIGIN` | `*` | CORS allow-list |
| `STATIC_DIR` | — | Serve a built frontend from here (single-container mode) |
| `MAX_WS_CLIENTS` | `200` | Browser-tab cap |
| `CALF_HOST` / `CALF_PORT` | `host.docker.internal` / `5570` | `pm-md-gwy`; use `host.containers.internal` for Podman if needed. |
| `CALF_CLIENT_ID` | `pm-terminal-bridge` | CALF `HELLO.CLIENT` |
| `CALF_PING_INTERVAL_SEC` | `60` | Keepalive; belt-and-braces now that the gateway's idle timer honours outbound traffic too |
| `INDEX_IDS` | — | Comma-separated index ids to subscribe to (CALF has no "list the indexes" request) |
| `API_GATEWAY_URL` | `http://host.docker.internal:8080` | `pm-api-gwy`; use `host.containers.internal` for Podman if needed. |
| `PM_TERMINAL_API_KEY` | — | Read-only (`gateway_id: null`) key, history reads only — never sent to the browser |
| `LOG_SRV_ENABLED` | `true` | `false` skips even the startup probe |
| `LOG_SRV_HOST` / `LOG_SRV_PORT` | `host.docker.internal` / `5600` | `pm-log-srv`; use `host.containers.internal` for Podman if needed. |
| `LOG_CONNECT_TIMEOUT_SEC` | `0.5` | Startup probe and each reconnect attempt |
| `LOG_FAILOVER_TIMEOUT_SEC` | `30` | Grace window before the one-way switch to a local log file |
| `LOG_QUEUE_MAXSIZE` | `2000` | Bounded backlog while reconnecting |
| `LOG_FAILOVER_DIR` | `/app/logs` | Where the post-failover log file goes; bind-mounted to `./logs` by Compose. |

## Troubleshooting

| Symptom | Likely cause | What to check |
|---|---|---|
| Every screen shows the red "Disconnected from pm-terminal-bridge" banner | The browser's own WebSocket to the bridge is down | Confirm the bridge process is running and reachable at `HOST:PORT`; check the browser console for the WS connection error |
| Connection indicator shows `RECONNECTING` and never returns to `LIVE` | The bridge cannot reach `pm-md-gwy` | Confirm `CALF_HOST`/`CALF_PORT` point at a running gateway, and that nothing (e.g. a firewall) blocks that TCP connection from the bridge's host |
| Charts and Open/Volume columns are empty or show an "unavailable" banner, but live prices still tick | The bridge cannot reach `pm-api-gwy`, or `PM_TERMINAL_API_KEY` is missing/invalid | Check the bridge's startup log for a `PM_TERMINAL_API_KEY is unset` warning; confirm `API_GATEWAY_URL` is correct and the key is a valid read-only history key |
| Index tab shows "This exchange has no index configured" | Expected, not an error, when no index is configured for this exchange | Set `INDEX_IDS` if an index should be shown |
| A tape gap marker appears | The bridge's CALF connection dropped for long enough that the gateway's replay window rolled past the missed trades | Expected behavior under a real disconnect — see [Trade Tape](#trade-tape-time-sales) above; not itself a bug to fix |
| Prices render to the wrong number of decimal places | The connected `pm-md-gwy` predates the `REF=` per-symbol precision field | Upgrade the gateway; TapeDeck falls back to two decimal places when `REF=` is absent, which is a compatibility fallback, not a defect in TapeDeck |

## Related documentation

- [CALF Gateway - Market Data Feed](240-calf-gateway.md) — the protocol
  TapeDeck's bridge speaks upstream
- [API Gateway](260-api-gateway.md) — the REST history endpoints the bridge
  proxies
- [Centralized Log Server](280-log-srv.md) — the bridge's optional
  operational-logging destination
- [Configuration GUI (`config-gui`)](030-config-GUI.md) — the sibling
  application TapeDeck shares its monorepo shape and deployment conventions
  with
- `docs-design/EduMatcher-Terminal-GUI.md` — the full design document (repository checkout only)
- `web-apps/terminal-gui/README.md` — the implementation's own record of every
  deviation from that design document (repository checkout only)
