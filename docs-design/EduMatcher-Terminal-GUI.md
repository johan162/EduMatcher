Version: 1.1.0

Date: 2026-07-17

Status: Design Proposal

> **Changelog v1.1.0**
> - Updated throughout for CALF `1.0.0`, which shipped after this document
>   was first written: the `DEPTH` channel, the `SYM=*` wildcard for `TOP`/
>   `TRADE`, and full `INDEX` documentation are now real, not proposed or
>   assumed-undocumented. See `EduMatcher-CALF-Extensions.md` and the
>   normative [CALF Protocol Reference](../docs/user-guide/920-app-calf-protocol.md).
> - §14 (Depth-of-Book) rewritten from a protocol-extension proposal into a
>   regular screen design section; folded into Symbol Detail as a toggle
>   (§9.2) rather than left as a separate blocked future phase.
> - §8 (Overview), §11 (Trade Tape), §12 (Movers) simplified to use one
>   `SYM=*` wildcard subscription each for `TOP`/`TRADE` instead of
>   enumerating every known symbol.
> - §17.1 rewritten to cover the one real new complexity CALF `1.0.0`
>   introduces for this design: `HELLO|RESUME=1` never accepts `SYM=*`, so
>   reconnect after a wildcard subscription requires resuming known symbols
>   individually rather than resuming the wildcard itself.
> - §22 Open Questions trimmed to what is still actually open; three
>   questions from v1.0.0 (INDEX documentation, `TOP`/`TRADE` wildcard,
>   whether `DEPTH` should exist and how it should be gated) are resolved.

# EduMatcher — Market Data Terminal (`pm-terminal`) Design Proposal



## Table of Contents

- [EduMatcher — Market Data Terminal (`pm-terminal`) Design Proposal](#edumatcher--market-data-terminal-pm-terminal-design-proposal)
  - [Table of Contents](#table-of-contents)
  - [1. Motivation](#1-motivation)
  - [2. Problem Statement](#2-problem-statement)
  - [3. Goals and Non-Goals](#3-goals-and-non-goals)
    - [3.1 Goals](#31-goals)
    - [3.2 Non-Goals](#32-non-goals)
  - [4. CALF/RALF Data Availability Audit](#4-calfralf-data-availability-audit)
    - [4.1 Method](#41-method)
    - [4.2 View-by-view data mapping](#42-view-by-view-data-mapping)
    - [4.3 Gaps found](#43-gaps-found)
    - [4.4 Should RALF be used?](#44-should-ralf-be-used)
    - [4.5 Verdict](#45-verdict)
  - [5. Technology Stack](#5-technology-stack)
    - [5.1 Stack](#51-stack)
    - [5.2 Monorepo layout](#52-monorepo-layout)
  - [6. Architecture](#6-architecture)
    - [6.1 Topology](#61-topology)
    - [6.2 Why a bridge instead of direct browser→CALF](#62-why-a-bridge-instead-of-direct-browsercalf)
    - [6.3 Data flow summary](#63-data-flow-summary)
    - [6.4 `pm-terminal-bridge` responsibilities](#64-pm-terminal-bridge-responsibilities)
    - [6.5 Multi-tab / multi-client fan-out](#65-multi-tab--multi-client-fan-out)
    - [6.6 Reconnect and gap handling](#66-reconnect-and-gap-handling)
  - [7. Application Shell and Navigation](#7-application-shell-and-navigation)
    - [7.1 Shell wireframe](#71-shell-wireframe)
    - [7.2 Top bar](#72-top-bar)
    - [7.3 Navigation rail](#73-navigation-rail)
    - [7.4 Connection status semantics](#74-connection-status-semantics)
  - [8. Screen Design — Market Overview](#8-screen-design--market-overview)
    - [8.1 Purpose](#81-purpose)
    - [8.2 Wireframe](#82-wireframe)
    - [8.3 Paging behaviour](#83-paging-behaviour)
    - [8.4 Column set](#84-column-set)
    - [8.5 Data sources](#85-data-sources)
  - [9. Screen Design — Symbol Detail](#9-screen-design--symbol-detail)
    - [9.1 Purpose](#91-purpose)
    - [9.2 Wireframe](#92-wireframe)
    - [9.3 Chart behaviour (OHLC + midpoint)](#93-chart-behaviour-ohlc--midpoint)
    - [9.4 Time-window zoom and presets](#94-time-window-zoom-and-presets)
    - [9.5 Values table](#95-values-table)
    - [9.6 Data sources](#96-data-sources)
  - [10. Screen Design — Index View](#10-screen-design--index-view)
    - [10.1 Purpose](#101-purpose)
    - [10.2 Wireframe](#102-wireframe)
    - [10.3 No-index-configured state](#103-no-index-configured-state)
    - [10.4 Data sources](#104-data-sources)
  - [11. Screen Design — Trade Tape / Time \& Sales](#11-screen-design--trade-tape--time--sales)
    - [11.1 Wireframe](#111-wireframe)
    - [11.2 Data sources](#112-data-sources)
  - [12. Screen Design — Market Movers / Heatmap](#12-screen-design--market-movers--heatmap)
    - [12.1 Wireframe](#121-wireframe)
    - [12.2 Data sources](#122-data-sources)
  - [13. Screen Design — Session \& Halt Status Board](#13-screen-design--session--halt-status-board)
    - [13.1 Wireframe](#131-wireframe)
    - [13.2 Data sources](#132-data-sources)
  - [14. Screen Design — Depth-of-Book](#14-screen-design--depth-of-book)
    - [14.1 Purpose and status](#141-purpose-and-status)
    - [14.2 What real venues do](#142-what-real-venues-do)
    - [14.3 Why `DEPTH` is cheap for `md_gateway` to serve](#143-why-depth-is-cheap-for-md_gateway-to-serve)
    - [14.4 `DEPTH` channel, as shipped](#144-depth-channel-as-shipped)
    - [14.5 Wireframe](#145-wireframe)
    - [14.6 Data sources](#146-data-sources)
    - [14.7 Deferred: order-flow imbalance and microprice](#147-deferred-order-flow-imbalance-and-microprice)
  - [15. Visual Design System](#15-visual-design-system)
  - [16. Client State Management](#16-client-state-management)
  - [17. `pm-terminal-bridge` Implementation Guide](#17-pm-terminal-bridge-implementation-guide)
    - [17.1 CALF session management](#171-calf-session-management)
    - [17.2 REST history proxy](#172-rest-history-proxy)
    - [17.3 Bridge → browser WS message schema](#173-bridge--browser-ws-message-schema)
    - [17.4 New files](#174-new-files)
  - [18. Security and Operational Notes](#18-security-and-operational-notes)
  - [19. Config Reference](#19-config-reference)
  - [20. Testing Strategy](#20-testing-strategy)
  - [21. Implementation Plan](#21-implementation-plan)
  - [22. Open Questions](#22-open-questions)
  - [23. Summary](#23-summary)



## 1. Motivation

EduMatcher has an order-entry GUI (`pm-trading-ui`, see
[EduMatcher-Trading-GUI.md](EduMatcher-Trading-GUI.md)) built for authenticated
traders against `pm-api-gwy`. It does not have a lightweight, read-only,
"watch the market" tool that a non-trading user — an instructor demoing the
exchange, a student studying price action, an observer, a bot author
sanity-checking a feed — can open without an API key and without any
trading surface at all.

This proposal specifies **`pm-terminal`**, a small Bloomberg-terminal-style
web application whose only job is to *display* market data: an overview of
all symbols, a deep single-symbol view with charting, an index view, and a
handful of the other panels every trading-floor overview tool has. It is
**strictly read-only** — there is no order entry, no authentication-gated
trading action, anywhere in this design.

Unlike `pm-trading-ui`, which talks to `pm-api-gwy` over REST/WebSocket,
`pm-terminal`'s live data comes from **CALF `1.0.0`**, the purpose-built
market-data protocol documented in the
[CALF Protocol Reference](../docs/user-guide/920-app-calf-protocol.md) (the
canonical, code-verified reference; see also
[EduMatcher-Market_Data_Protocol.md](EduMatcher-Market_Data_Protocol.md) and
[EduMatcher-CALF-Extensions.md](EduMatcher-CALF-Extensions.md) for the
design-history trail). CALF `1.0.0` ships all five channels this design
needs — `TOP`, `TRADE`, `STATE`, `INDEX`, and `DEPTH` — plus a `SYM=*`
wildcard for `TOP`/`TRADE`/`STATE`, so `pm-terminal` can lean on CALF more
directly than an earlier draft of this document assumed. Historical bars
(which CALF intentionally does not provide, by design, at any protocol
version) are sourced from `pm-api-gwy`'s existing `/history/*` endpoints,
the same store `pm-trading-ui` already uses.

## 2. Problem Statement

- There is no zero-friction way to just *look* at the market. Today, seeing
  live prices means running `pm-trading-ui` and logging in with an API key
  meant for a trading gateway identity.
- CALF was designed and built specifically to be a simple, human-readable
  feed for exactly this kind of consumer — but nothing consumes it as a
  polished visual client yet; the only worked client is the terminal example
  in the protocol doc and ad hoc bots.
- Instructors and students benefit from a "big screen" overview (paged
  symbol grid, index ticker, trade tape) that a trading blotter UI is not
  designed to present.
- There is a real question — closed by this document — of whether CALF as
  currently specified/implemented actually carries every field this kind of
  terminal needs. As of CALF `1.0.0` it covers every live data need in this
  design, including a full order-book depth ladder (`DEPTH`); the one
  remaining genuine gap is historical data (CALF is intentionally
  live-only), resolved below by reusing `pm-api-gwy`'s existing history
  endpoints.

## 3. Goals and Non-Goals

### 3.1 Goals

- Ship a Node.js/Vite web application, structured the same way as
  `config-gui` (npm/pnpm workspace: `apps/*` + `packages/*`), that runs
  entirely without a trading API key.
- Consume live data exclusively via **CALF `1.0.0`** (`TOP`, `TRADE`,
  `STATE`, `INDEX`, `DEPTH`), through a small first-party bridge process
  (§6) because browsers cannot open the raw TCP sockets CALF uses.
- Provide, at minimum, the five view families the user asked for:
  1. **Market Overview** — all symbols, auto-paging, configurable per-page
     delay.
  2. **Symbol Detail** — OHLC bar chart + bid/ask midpoint line, a full
     values table, and a zoomable time window. Large-screen only.
  3. **Index View** — chart of the configured index (if any).
  4. **Depth-of-Book** — a Level 2 ladder for the active symbol, sourced
     directly from CALF `DEPTH` (§14).
  5. Other common trading-floor panels, scoped in §4/§11–§13.
- Verify, before designing, exactly what CALF (and RALF, where relevant)
  actually deliver today — not what an older draft of the protocol doc used
  to say it delivers, but what the shipped `md_gateway` code allows (§4),
  cross-checked against the current normative
  [CALF Protocol Reference](../docs/user-guide/920-app-calf-protocol.md).
- Make full use of what CALF `1.0.0` already provides — the `DEPTH` channel
  and the `SYM=*` wildcard for `TOP`/`TRADE` — rather than working around
  gaps that no longer exist (§4, §14).
- Reuse the visual language, component choices, and monorepo conventions
  already established by `config-gui` and `pm-trading-ui` so the three
  frontends feel like one family.

### 3.2 Non-Goals

- No order entry, no authentication for trading, no write path to the
  engine, ever. If a future need for authenticated views arises it belongs
  in `pm-trading-ui`, not here.
- No multi-level order-entry DOM with click-to-trade (that is
  `pm-trading-ui`'s Trading Workspace). §14's depth ladder is read-only;
  order-ticket wiring against depth data is explicitly out of scope here,
  now and later — that capability, if ever built, belongs in
  `pm-trading-ui`.
- No mobile/small-screen layout for Symbol Detail — the user confirmed this
  is a large-screen tool.
- No new persistence layer. `pm-terminal-bridge` is stateless beyond
  in-memory CALF replay/reconnect bookkeeping; all durable history continues
  to live in `pm-stats` behind `pm-api-gwy`.
- No RALF integration in v1 (§4.4 explains why, and what would change that).

## 4. CALF/RALF Data Availability Audit

This section is the "verify before designing" step the user asked for. It
was done against **both** sources, in this priority order: (1) the shipped
gateway code in `src/edumatcher/md_gateway/`, `engine/order_book.py`, and
`api_gateway/`, and (2) the normative
[CALF Protocol Reference](../docs/user-guide/920-app-calf-protocol.md),
cross-checked against
[EduMatcher-CALF-Extensions.md](EduMatcher-CALF-Extensions.md) and
[EduMatcher-Post-Trade-Dissemination-Gateway.md](EduMatcher-Post-Trade-Dissemination-Gateway.md).
Code wins where the two disagree; as of CALF `1.0.0` they agree everywhere
relevant to this design.

### 4.1 Method

For each planned view, list the data points it needs, then mark where each
one actually comes from today.

### 4.2 View-by-view data mapping

| View | Data point | Source | Status |
|---|---|---|---|
| Overview | Live LAST / BID / ASK / sizes | CALF `TOP` (`SNAP`/`MD`), `SUB\|CH=TOP\|SYM=*` | ✅ available |
| Overview | Live trade prints (for LAST/flash) | CALF `TRADE`, `SUB\|CH=TRADE\|SYM=*` | ✅ available |
| Overview | Today's OPEN (for % change) | `pm-api-gwy` `GET /history/daily` | ⚠️ not in CALF — REST needed (CALF is intentionally live-only) |
| Overview | Session cumulative volume | `pm-api-gwy` `GET /history/daily` (`volume`) | ⚠️ not in CALF — REST needed |
| Overview | Instrument/session state (halt badge) | CALF `STATE` | ✅ available |
| Symbol Detail | Live top-of-book (chart tail, midpoint) | CALF `TOP` | ✅ available |
| Symbol Detail | Live trade prints (tape, LAST) | CALF `TRADE` | ✅ available |
| Symbol Detail | Historical OHLC bars (1D+ granularity) | `pm-api-gwy` `GET /history/daily` | ⚠️ not in CALF — REST needed |
| Symbol Detail | Historical intraday bars (1m/5m/1h) | `pm-api-gwy` `GET /history/trades`, bucketed client-side | ⚠️ not in CALF — REST needed |
| Symbol Detail | Historical bid/ask midpoint | *nowhere* | ❌ genuine gap — see §9.3 |
| Symbol Detail | Session/halt state | CALF `STATE` | ✅ available |
| Symbol Detail | Depth ladder for active symbol | CALF `DEPTH` (`SNAP`/`DEPTH`, `SUB\|CH=DEPTH\|SYM=<symbol>`) | ✅ available — see §14 |
| Index View | Live index level, OHL, %chg | CALF `INDEX` (`IDX`/`SNAP`) | ✅ available and fully documented in the normative CALF reference |
| Index View | Historical index level series | *unconfirmed query surface* | ⚠️ gap — treated as v1 limitation, see §10, §22 |
| Trade Tape | Cross-symbol trade prints | CALF `TRADE`, `SUB\|CH=TRADE\|SYM=*` | ✅ available — single wildcard subscription |
| Movers/Heatmap | LAST + %chg for all symbols | CALF `TOP`/`TRADE` (wildcard) + REST open | ✅ composable from above |
| Session/Halt Board | Session phase + per-symbol halts | CALF `STATE` (`SYM=*` and per-symbol) | ✅ available |
| Depth ladder | Multi-level book | CALF `DEPTH` (`SNAP`/`DEPTH`) | ✅ available — see §14 |

### 4.3 Gaps found

1. **No historical data in CALF (by design).** CALF is explicitly scoped as
   a live-only feed; historical data is out of scope at every protocol
   version, including `1.0.0`. This applies equally to symbols and to the
   index — only live `INDEX` snapshots/updates are queryable through CALF.
   All historical bars, for symbols and for the index, have to come from
   somewhere else. `pm-api-gwy`'s `GET /history/daily` and
   `GET /history/trades` (`src/edumatcher/api_gateway/routers/history.py`,
   backed by `pm-stats` SQLite) are that somewhere else, and are already
   proven by `pm-trading-ui`. Resolution: §6, §9, §17.2.

2. **No historical bid/ask (midpoint).** Neither CALF nor `pm-stats` retains
   historical book state — only historical trades and daily OHLCV built from
   them. A historical "midpoint chart" is therefore not reconstructable
   before the terminal was open watching live `TOP` data. Treated as an
   accepted v1 limitation, with explicit UI labelling (§9.3) rather than a
   protocol change, since retaining full historical book state is a much
   bigger and more invasive addition than anything else in this audit.

Two gaps present in an earlier draft of this document — `INDEX` being
undocumented, and no wildcard subscription for `TRADE`/`TOP` — were resolved
upstream in CALF `1.0.0` (see
[EduMatcher-CALF-Extensions.md](EduMatcher-CALF-Extensions.md) §4–§5) and are
no longer open. A third — no multi-level depth over CALF — was resolved the
same way via the new `DEPTH` channel (§14 below documents it as shipped, not
proposed). All three are recorded in the CHANGELOG rather than repeated here
as live gaps.

### 4.4 Should RALF be used?

**No, not for this application.** RALF
([EduMatcher-Post-Trade-Dissemination-Gateway.md](EduMatcher-Post-Trade-Dissemination-Gateway.md))
is a reconciliation/post-trade feed scoped to `ROLE=CLEARING` and
`ROLE=AUDIT` consumers, carrying execution-level identifiers
(`ORDER_ID`, `EXEC_ID`, `MATCH_ID`, gateway attribution, liquidity flags).
Its own design doc (§14 of the CALF protocol doc, written by the same
author) explicitly argues for keeping post-trade/execution semantics out of
the general market-data path: *"book consumers are not... forced to parse
settlement-oriented payloads."* A market-data terminal is exactly the
"book consumer" that recommendation protects. RALF's longer 24-hour replay
window is tempting for a deeper trade tape, but pulling it in would mean
authenticating as a clearing/audit role for a tool that should need no
credentials at all, and it would blur a separation the protocol design
itself calls out as correct. CALF's `TRADE` channel — one `SYM=*` wildcard
subscription, as of CALF `1.0.0` — is the right and sufficient source for
the Trade Tape (§11).

### 4.5 Verdict

CALF `1.0.0` (`TOP` + `TRADE` + `STATE` + `INDEX` + `DEPTH`, all fully
documented in the normative CALF reference) covers every *live* data need in
this design, including the full order-book ladder. Only one gap remains for
full parity with a real terminal: historical data, which CALF intentionally
never carries at any version — resolved by reusing `pm-api-gwy`'s existing
history endpoints (§6, §17.2), an architecture decision, not a protocol
change. Everything else in this design is buildable today against CALF as
shipped, with no protocol extension required.

## 5. Technology Stack

### 5.1 Stack

| Layer | Choice | Rationale |
|---|---|---|
| Frontend framework | React 18 + TypeScript, bundled with Vite | Matches `config-gui`; fast dev loop |
| Styling | Tailwind CSS + shadcn/ui (Radix primitives) | Matches both `config-gui` and `pm-trading-ui`; accessible-by-default |
| Charts | TradingView Lightweight Charts v5 | Same library `pm-trading-ui` uses; candlestick + line series, time-axis zoom/pan built in |
| Tables/grids | TanStack Table v8 | Matches `pm-trading-ui`; virtualized rows for the Overview grid |
| Client state | Zustand | Matches both sibling apps; fine-grained subscriptions suit tick-rate updates |
| Server/cache state | TanStack Query v5 | REST history calls only (§17.2); WS ticks bypass it and write straight into Zustand |
| Routing | React Router v7 | One route per view (`/overview`, `/symbol/:sym`, `/index/:id`, `/tape`, `/movers`, `/session`) |
| Bridge runtime | Node.js 22 LTS | Matches `config-gui`'s backend runtime choice |
| Bridge framework | Fastify | Matches `config-gui`'s `apps/server`; first-class TS, lightweight |
| CALF client | Hand-rolled TCP line client (`net.Socket`) in the bridge | CALF is a bespoke text protocol; no existing npm package speaks it — mirrors the worked Python client in the protocol doc §17 |
| Browser transport | Native WebSocket, one connection per browser tab to `pm-terminal-bridge` | No trading-side auth-frame complexity, so no need for `pm-trading-ui`'s bespoke `ManagedSocket`; a thin reconnect wrapper is enough (§17.3) |
| Icons | Lucide React | Matches both sibling apps |

`pm-terminal` intentionally does **not** include React Hook Form, Zod forms,
or any mutation-oriented library — there is nothing in this application the
user submits.

### 5.2 Monorepo layout

Same shape as `config-gui` (`apps/` + `packages/` npm/pnpm workspace),
substituting a CALF bridge for `config-gui`'s Fastify config API:

```
terminal-gui/
  apps/
    web/                    React frontend (Vite)
    bridge/                 Fastify backend: CALF TCP client + WS fan-out + history proxy
  packages/
    calf-protocol/          CALF line parser/builder (TS port of md_gateway/protocol.py's grammar)
    shared-types/            TS types shared by web + bridge (ticks, bars, symbols, index, halts)
  package.json               npm/pnpm workspaces root
```

`packages/calf-protocol` is deliberately a thin, dependency-free package —
it only knows the wire grammar (`MSGTYPE|KEY=VALUE|...`), not gateway
semantics — so it can eventually be published and reused by any other
TypeScript CALF client, the same way `md_gateway/protocol.py` is the
reusable parsing core on the Python side.

## 6. Architecture

### 6.1 Topology

```mermaid
flowchart LR
    subgraph Browser["Browser tab(s) — pm-terminal SPA"]
        REACT["React component tree"]
        ZUSTAND["Zustand store\n(ticks, bars, index, halts, symbols)"]
        TQ["TanStack Query\n(history cache)"]
        WS["WS client\n(reconnect wrapper)"]
        REACT --> ZUSTAND
        REACT --> TQ
        REACT --> WS
    end

    WS -->|"WS /stream\n(JSON frames)"| BRIDGE["pm-terminal-bridge\nFastify + Node :8090"]
    TQ -->|"REST /api/history/*\n(proxied)"| BRIDGE

    BRIDGE -->|"CALF over TCP :5570\nHELLO/SUB/SNAP/MD/TRADE/STATE/IDX/DEPTH"| MDGWY["pm-md-gwy"]
    BRIDGE -->|"REST GET /api/v1/history/*\n(server-held API key)"| APIGWY["pm-api-gwy :8080"]
```

`pm-terminal-bridge` is the only new backend process. Everything it talks to
already exists (`pm-md-gwy`, `pm-api-gwy`).

### 6.2 Why a bridge instead of direct browser→CALF

CALF is raw newline-delimited TCP (see "Transport and session model" in the
normative CALF reference). Browsers have no API to open arbitrary TCP
sockets — WebSocket or nothing. Two shapes were considered (this was raised
as a clarifying question and resolved in favour of the first):

| Option | Trade-off |
|---|---|
| **Own Node WS↔TCP bridge (chosen)** | New small process, but zero changes to `pm-md-gwy` or the CALF spec; matches `config-gui`'s existing pattern of "frontend + small first-party Node backend"; the bridge can also hide the `pm-api-gwy` API key server-side (§18) |
| Extend `pm-md-gwy` for native WebSocket | Avoids a second process, but changes shared trading infrastructure to serve one read-only viewer's transport preference; couples `pm-md-gwy`'s release cycle to `pm-terminal`'s |

### 6.3 Data flow summary

| Data path | Direction | Mechanism |
|---|---|---|
| Symbol list, index list | Bridge → Browser | WS `hello` frame, sourced from CALF `WELCOME|SYMBOLS=` + config |
| Top-of-book snapshot/update (all symbols) | Bridge → Browser | WS `top` frame ⇐ CALF `SNAP`/`MD` (`CH=TOP`), one bridge-side `SUB|CH=TOP|SYM=*` |
| Trade prints (all symbols) | Bridge → Browser | WS `trade` frame ⇐ CALF `TRADE`, one bridge-side `SUB|CH=TRADE|SYM=*` |
| Session/halt state | Bridge → Browser | WS `state` frame ⇐ CALF `STATE` |
| Index level | Bridge → Browser | WS `index` frame ⇐ CALF `SNAP`/`IDX` (`CH=INDEX`) |
| Depth ladder (active symbol only) | Bridge → Browser | WS `depth` frame ⇐ CALF `SNAP`/`DEPTH` (`CH=DEPTH`, one concrete symbol at a time — `SYM=*` is not allowed for `DEPTH`, see §14) |
| Historical daily bars | Browser → Bridge → `pm-api-gwy` → Browser | REST `GET /api/history/daily?symbol=…` (proxied, §17.2) |
| Historical trade ticks (intraday bucketing) | Browser → Bridge → `pm-api-gwy` → Browser | REST `GET /api/history/trades?symbol=…` (proxied) |
| Bridge liveness / CALF connection health | Bridge → Browser | WS `bridge_status` frame |

### 6.4 `pm-terminal-bridge` responsibilities

- Hold exactly **one** CALF TCP session to `pm-md-gwy` regardless of how
  many browser tabs are connected (§6.5).
- On startup, `HELLO`, then immediately `SUB|CH=STATE,TOP,TRADE|SYM=*` and
  `SUB|CH=INDEX|SYM=<configured index ids>` — all four wildcard-eligible or
  index subscriptions are available from the first `SUB` call, with no need
  to wait for `WELCOME|SYMBOLS=` first. `CH=DEPTH` is **not** part of this
  always-on set (§14): the bridge only issues `SUB|CH=DEPTH|SYM=<symbol>`
  for the symbol currently open in a browser tab's Symbol Detail or Depth
  view, and `UNSUB`s it once no tab is viewing that symbol anymore, to avoid
  paying `DEPTH`'s heavier per-tick bandwidth for symbols nobody is looking
  at (mirrors the bandwidth reasoning CALF itself uses to justify excluding
  `DEPTH` from the wildcard).
- Track `last_seq` per `(CH, SYM)` exactly like the worked Python client in
  the protocol doc, and use `RESUME`/`LASTSEQ` on reconnect (§6.6) — noting
  that `RESUME` must always target a concrete symbol, never `SYM=*` (§17.1).
- Translate every inbound CALF line into one small JSON frame and fan it out
  to all connected browser WebSocket clients (§17.3).
- Own the single `pm-api-gwy` API key used for `/history/*` reads, so it
  never reaches the browser (§18).
- Serve nothing else — no persistence, no computed analytics beyond simple
  per-connection fan-out. Change/percentage math, bucketing, and paging all
  happen client-side in React, same as `pm-trading-ui`'s chart bucketing
  (§16).

### 6.5 Multi-tab / multi-client fan-out

Every browser tab (Overview on one monitor, Symbol Detail on another) opens
its own WebSocket to the bridge, but the bridge keeps a **single shared CALF
subscription set**, unioned across all connected browser clients — not one
CALF session per tab. This mirrors `pm-md-gwy`'s own "shared per-stream ring
buffer, not per-client" design one layer up the stack. For the always-on
wildcard subscriptions (`TOP`, `TRADE`, `STATE`, `INDEX`), this union is
trivial — they are held for the bridge's entire lifetime regardless of tab
count, so there is nothing to reference-count. `DEPTH` is the one exception:
because it is per-symbol, not wildcard (§14), the bridge reference-counts
how many browser tabs currently have that symbol's Depth-of-Book panel open
and only holds `SUB|CH=DEPTH|SYM=<symbol>` while the count is above zero,
`UNSUB`-ing when the last interested tab navigates away or closes.

### 6.6 Reconnect and gap handling

If the bridge's CALF TCP connection drops, it reconnects and resumes exactly
as the worked client in the protocol doc does: `HELLO` with
`RESUME=1`/`LASTSEQ=` per stream, falling back to a fresh `SNAP` on
`ERR|CODE=REPLAY_MISS`. Because `RESUME=1` never accepts `SYM=*` (§17.1),
the bridge resumes its wildcard `TOP`/`TRADE`/`STATE` subscriptions one
concrete known symbol at a time — see §17.1 for the exact sequencing. Browser
WebSocket clients are not torn down for a brief CALF hiccup — they simply
see a `bridge_status: {calf: "RECONNECTING"}` frame and then resume
receiving ticks once the bridge is caught up. If a browser tab's own
WebSocket drops, it reconnects to the bridge and receives a fresh
`hello`/state snapshot — it does not need to track CALF sequence numbers
itself, only the bridge does.

## 7. Application Shell and Navigation

### 7.1 Shell wireframe

```
┌──────────────────────────────────────────────────────────────────────────┐
│ pm-terminal   [Overview] [Symbol] [Index] [Tape] [Movers] [Session]  ●LIVE│
├──────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│                           < active view content >                        │
│                                                                            │
│                                                                            │
├──────────────────────────────────────────────────────────────────────────┤
│ CONTINUOUS  •  3 symbols halted  •  CALF connected  •  14:32:07 UTC       │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Top bar

- App name, a fixed row of view tabs (not a collapsible sidebar — six views
  is small enough for a single row), and a global connection indicator
  (`●LIVE` / `●RECONNECTING` / `●OFFLINE`, driven by `bridge_status`).
- A symbol quick-jump (`Cmd/Ctrl+K`) that filters the known symbol list and
  navigates straight to Symbol Detail — useful once the Overview grid is
  paging through dozens of symbols.

### 7.3 Navigation rail

Six top-level routes, each a tab: Overview, Symbol (last-viewed symbol, or a
picker if none yet), Index, Tape, Movers, Session. No role gating anywhere —
every route is reachable with no login, matching the non-goal in §3.2.

### 7.4 Connection status semantics

| Indicator | Meaning |
|---|---|
| `●LIVE` (green) | Bridge's CALF session is `ACTIVE`; ticks flowing |
| `●RECONNECTING` (amber) | Bridge lost its CALF session and is retrying (§6.6); browser keeps last-known values, greyed slightly |
| `●OFFLINE` (red) | Browser's own WebSocket to the bridge is down; full-screen banner, no stale data shown |

## 8. Screen Design — Market Overview

### 8.1 Purpose

The default landing view: every tradable symbol, auto-paging, meant to run
unattended on a lobby/classroom display as well as be actively browsed.

### 8.2 Wireframe

```
┌──────────────────────────────────────────────────────────────────────────┐
│ MARKET OVERVIEW                          Page 2 / 5   ⏸ pause  ⚙ 8s ▾    │
├────────┬─────────┬─────────┬─────────┬──────────┬──────────┬────────────┤
│ SYMBOL │  LAST    │  CHG    │  %CHG   │   BID    │   ASK    │  VOLUME    │
├────────┼─────────┼─────────┼─────────┼──────────┼──────────┼────────────┤
│ AAPL   │  150.12  │ +0.42  │ +0.28%  │ 150.10   │ 150.12   │  184,300   │
│ MSFT   │  421.05  │ -1.10  │ -0.26%  │ 421.00   │ 421.08   │   92,410   │
│ TSLA   │  248.77  │ +3.65  │ +1.49%  │ 248.75   │ 248.80   │  310,922   │
│ EDU01  │   58.20  │  0.00  │  0.00%  │  58.15   │  58.24   │    4,110   │
│  …     │    …     │   …    │    …    │    …     │    …     │     …      │
├────────┴─────────┴─────────┴─────────┴──────────┴──────────┴────────────┤
│ ████████████████████░░░░░░░░  next page in 3s        ‹ prev   next ›     │
└──────────────────────────────────────────────────────────────────────────┘
```

Green/red flash on each cell when a new `MD`/`TRADE` changes its value
(same `FlashCell` pattern `pm-trading-ui` already uses).

### 8.3 Paging behaviour

- Symbols are split into fixed-size pages (rows-per-page derived from
  viewport height so the grid never scrolls — a lobby display has no mouse).
- A per-page dwell timer advances automatically; **the delay is a user
  setting** (`⚙` control: 3s / 5s / 8s / 15s / 30s / custom), persisted per
  browser via `localStorage`.
- Hovering the grid or pressing `⏸` pauses auto-paging; `‹`/`›` step pages
  manually at any time, `⏸`/`▶` toggles resume.
- All rows on all pages stay live regardless of which page is currently
  shown — paging is purely a client-side rendering concern, not a
  subscription concern, so numbers never go stale. This falls out for free
  from the bridge's single `SUB|CH=TOP,TRADE|SYM=*` wildcard subscription
  (§6.4): every symbol is already flowing into the bridge and out to every
  connected tab regardless of what that tab currently renders, so there is
  no per-page subscribe/unsubscribe logic to write at all.

### 8.4 Column set

| Column | Meaning | Source |
|---|---|---|
| SYMBOL | Ticker | CALF `WELCOME|SYMBOLS=` / config |
| LAST | Last trade price | CALF `TOP.LAST` (falls back to `TRADE.PX`) |
| CHG | `LAST − OPEN` | computed, `OPEN` from REST `/history/daily` |
| %CHG | `CHG / OPEN × 100` | computed |
| BID / ASK | Best bid/ask | CALF `TOP.BID`/`TOP.ASK` |
| VOLUME | Session cumulative volume | REST `/history/daily.volume`, live-incremented client-side by summing CALF `TRADE.QTY` since page load |
| (badge, not a column) | Halted / auction indicator overlaid on SYMBOL | CALF `STATE` |

### 8.5 Data sources

```
WS  bridge → top      (CH=TOP, SYM=* — one bridge-side wildcard subscription, all symbols)
WS  bridge → trade    (CH=TRADE, SYM=* — one bridge-side wildcard subscription, all symbols)
WS  bridge → state    (CH=STATE, SYM=*  and per-symbol halts)
REST bridge → /api/history/daily?date=today   (once per session for OPEN/VOLUME baseline)
```

## 9. Screen Design — Symbol Detail

### 9.1 Purpose

The deep-dive view for one instrument: chart, values table, zoomable time
window. Large-screen only, as confirmed by the user — no responsive
mobile layout is specified.

### 9.2 Wireframe

```
┌──────────────────────────────────────────────────────────────────────────┐
│ AAPL  — CONTINUOUS            150.12  +0.42 (+0.28%)     Vol 184,300     │
├──────────────────────────────────────────────────────────────────────────┤
│ [1D] [5D] [1M] [3M] [YTD] [All] [Live]  ☑ OHLC  ☑ Midpoint  ☐ Depth ▾    │
│                                                                            │
│   152 ┤                                          ╭╮                     │
│   151 ┤                              ╭╮       ╭──╯╰╮   ┃┃┃┃  ← candles  │
│   150 ┤ ┃┃┃┃  ╭───╮  ┃┃┃┃  ╭────╮ ╭──╯╰──╮────╯    ╰─╮ ┃┃┃┃  midpoint ‥ │
│   149 ┤ ┃┃┃┃╭─╯   ╰──┃┃┃┃──╯    ╰─╯       ╰──╮        ╰┃┃┃┃             │
│   148 ┤ ┃┃┃┃╯                                ╰────╮   ┃┃┃┃              │
│       └────────────────────────────────────────────────────────────────┤
│         09:30      10:30      11:30      12:30      13:30      14:30    │
│  ▂▃▁▂▅▃▂▁▃▄▂▁▂▃▁▅▂▁▃▂▁▄▃▂▁▃▄▂▁ (volume histogram, shares each interval)  │
├────────────────────────────┬───────────────────────────────────────────┤
│  VALUES                    │  drag-select on the chart to zoom;         │
│  Open        149.70        │  presets above reset to their fixed window │
│  High        152.05        │                                            │
│  Low         148.10        │                                            │
│  Last        150.12        │                                            │
│  Bid / Ask   150.10 / 150.12│                                           │
│  Mid (live)  150.11         │                                           │
│  Prev Close  149.70         │                                           │
│  Volume      184,300        │                                           │
│  Session     CONTINUOUS     │                                           │
└────────────────────────────┴───────────────────────────────────────────┘
```

Toggling `☑ Depth` replaces the values panel (right-hand side, or a
slide-out on narrower large-screen widths) with the Depth-of-Book ladder —
see §14 for its own wireframe and data source. It is off by default: unlike
`OHLC`/`Midpoint`, which reuse subscriptions the bridge already holds for
every symbol, enabling Depth causes the bridge to open a new
`SUB|CH=DEPTH|SYM=<symbol>` for this one symbol (§6.4), so it is opt-in per
viewer rather than always-on.

### 9.3 Chart behaviour (OHLC + midpoint)

- **OHLC bars** are candlesticks built from historical bars (§9.4) with the
  live-forming bar updated in place from CALF `TRADE` prints, exactly the
  pattern `pm-trading-ui`'s chart already implements (bucket ticks into the
  current-timeframe candle, replace on each trade).
- **Midpoint** is `(BID + ASK) / 2` from CALF `TOP`, drawn as a thin
  secondary line series over the candles. Per the gap in §4.3 point 2,
  **there is no historical bid/ask** — the midpoint line only has real data
  from the moment `pm-terminal` (or the bridge, if already running) started
  observing `TOP` updates for this symbol. The UI must make this explicit:
  the midpoint series starts partway across the chart with a small
  `mid data begins here` marker, rather than silently drawing a flat or
  interpolated line over the historical portion. Both series can be
  toggled independently (checkboxes in the wireframe above).
- Both series/toggles are independent of the timeframe presets — switching
  from `1D` to `5D` keeps whichever series are enabled on.

### 9.4 Time-window zoom and presets

- Preset buttons (`1D`, `5D`, `1M`, `3M`, `YTD`, `All`, `Live`) set the
  visible window; `Live` pins the right edge to now and scrolls with
  incoming ticks (Lightweight Charts' native realtime mode).
- Free-form zoom: click-drag a horizontal range on the chart to zoom in
  (Lightweight Charts' built-in range selection); scroll wheel / pinch to
  zoom in and out continuously; double-click to reset to the active preset.
- **Bar granularity switches with zoom level**, same rule `pm-trading-ui`
  already uses (§16.3 there): `1D`/`5D` render 1m or 5m bars bucketed from
  `GET /history/trades`; `1M`+ render the daily bars from
  `GET /history/daily` directly (no point rendering 90 days of 1-minute
  bars).

### 9.5 Values table

Plain key/value panel, not a grid — one instrument, so no need for
`TanStack Table` here. All rows are live except `Open`/`Prev Close`, which
come from the daily history row fetched once per symbol view.

### 9.6 Data sources

```
WS   bridge → top     (CH=TOP, this symbol)         → Bid/Ask/Mid, live candle tail
WS   bridge → trade   (CH=TRADE, this symbol)        → Last, live candle OHLC updates, volume
WS   bridge → state   (CH=STATE, this symbol + SYM=*)→ Session badge
WS   bridge → depth   (CH=DEPTH, this symbol — only while the Depth toggle is on, §9.2, §14) → ladder
REST bridge → /api/history/daily?symbol=AAPL         → Open/High/Low/Prev Close, 1D+ bars
REST bridge → /api/history/trades?symbol=AAPL&limit=…→ intraday bar bucketing
```

Note that `top`, `trade`, and `state` above arrive at this symbol regardless
of whether Symbol Detail is open, since the bridge already holds them as
part of its always-on `SYM=*` wildcard subscriptions (§6.4) — Symbol Detail
just filters the shared stream down to one symbol client-side. `depth` is
the exception: it is the one WS frame type that actually causes a new CALF
subscription when this view (or its Depth toggle) opens, and causes an
`UNSUB` when it closes (§6.5).

## 10. Screen Design — Index View

### 10.1 Purpose

Chart and headline stats for a configured exchange index (§4 of
[EduMatcher-Index.md](EduMatcher-Index.md)), up to five may exist per
exchange.

### 10.2 Wireframe

```
┌──────────────────────────────────────────────────────────────────────────┐
│ EDU100 INDEX                    1048.73   +6.63 (+0.64%)                 │
├──────────────────────────────────────────────────────────────────────────┤
│ [1D] [5D] [1M] [3M] [YTD] [All] [Live]                                   │
│                                                                            │
│  1056 ┤                    ╭╮                                           │
│  1050 ┤            ╭───────╯╰╮      ╭──╮                                │
│  1044 ┤  ╭─────────╯          ╰──────╯  ╰────────╮                      │
│  1038 ┤──╯                                        ╰──────               │
│       └───────────────────────────────────────────────────────────────┤
│         09:30       10:30       11:30       12:30       13:30           │
├──────────────────────────────┬───────────────────────────────────────┤
│  Open   1042.10               │  Constituents (top weights)             │
│  High   1056.30                │  AAPL  18.2%   ▲                       │
│  Low    1040.05                │  MSFT  15.7%   ▼                       │
│  Aggregate cap  $7.35T         │  TSLA   9.1%   ▲                       │
│  Session  CONTINUOUS           │  …                                     │
└────────────────────────────────┴─────────────────────────────────────┘
```

Constituent weights use the same `AGGCAP`-relative math the index design
doc already defines; the constituent list itself is static configuration
(not live per-constituent weight streaming — see §22).

### 10.3 No-index-configured state

If the exchange has zero indexes configured, the **Index** tab is not
hidden — it shows an explanatory empty state ("This exchange has no index
configured") rather than disappearing, so the tab layout stays stable
across differently-configured classroom exchanges.

### 10.4 Data sources

```
WS   bridge → index   (CH=INDEX, SYM=<index id>)   → live level, OHL, %chg
REST bridge → /api/history/daily?symbol=<index id> → historical level series, if/when pm-stats carries index rows (§22 — currently unconfirmed for indexes specifically)
```

## 11. Screen Design — Trade Tape / Time & Sales

### 11.1 Wireframe

```
┌──────────────────────────────────────────────────────────────────────────┐
│ TRADE TAPE                         Symbol: [ All ▾ ]      ⏸ pause        │
├──────────┬────────┬──────────┬────────┬──────────────────────────────────┤
│  TIME    │ SYMBOL │  PRICE   │  QTY   │  SIDE                            │
├──────────┼────────┼──────────┼────────┼──────────────────────────────────┤
│ 14:32:07 │ TSLA   │  248.77  │  200   │  ▲ BUY                           │
│ 14:32:06 │ AAPL   │  150.12  │  150   │  ▲ BUY                           │
│ 14:32:05 │ MSFT   │  421.05  │   80   │  ▼ SELL                          │
│ 14:32:04 │ AAPL   │  150.10  │  300   │  ▼ SELL                          │
│  …       │  …     │   …      │   …    │   …                              │
└──────────┴────────┴──────────┴────────┴──────────────────────────────────┘
```

New rows insert at the top and scroll down; a bounded ring buffer (last
~500 prints, client-side) keeps memory flat. Symbol filter narrows the tape
without changing the underlying subscription (the bridge already holds a
single `SUB|CH=TRADE|SYM=*` wildcard subscription covering every symbol,
per §6.4).

### 11.2 Data sources

```
WS  bridge → trade   (CH=TRADE, SYM=* — one bridge-side wildcard subscription, all symbols)
```

## 12. Screen Design — Market Movers / Heatmap

### 12.1 Wireframe

```
┌──────────────────────────────────────────────────────────────────────────┐
│ MOVERS                                    [ Gainers | Losers | Active ]  │
├────────┬─────────┬─────────┬──────────────────────────────────────────┤
│ SYMBOL │  LAST    │  %CHG   │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  (bar scaled to %chg) │
├────────┼─────────┼─────────┼──────────────────────────────────────────┤
│ TSLA   │  248.77  │ +1.49% │  ██████████████████                       │
│ AAPL   │  150.12  │ +0.28% │  ████                                     │
│ EDU01  │   58.20  │  0.00% │                                           │
│ MSFT   │  421.05  │ -0.26% │  ████                                     │
│  …     │    …     │   …    │   …                                       │
└────────┴─────────┴─────────┴──────────────────────────────────────────┘
```

`Active` sorts by session volume instead of %chg — a common third tab on
real overview boards, and cheap here since Overview (§8) already computes
volume per symbol.

### 12.2 Data sources

Same feed as Overview (§8.5) — Movers is a different sort/rank over the
identical live+REST-baseline dataset, no new subscriptions.

## 13. Screen Design — Session & Halt Status Board

### 13.1 Wireframe

```
┌──────────────────────────────────────────────────────────────────────────┐
│ SESSION STATUS                                                           │
├──────────────────────────────────────────────────────────────────────────┤
│  Exchange session:  CONTINUOUS   (since 09:30:00, prev: OPENING_AUCTION) │
├──────────────────────────────────────────────────────────────────────────┤
│  ACTIVE HALTS                                                            │
│  ┌────────┬────────────────┬───────────────┬─────────────────────────┐ │
│  │ SYMBOL │ STATE          │ PREV          │ SINCE                   │ │
│  ├────────┼────────────────┼───────────────┼─────────────────────────┤ │
│  │ TSLA   │ HALTED         │ CONTINUOUS    │ 11:02:17                │ │
│  └────────┴────────────────┴───────────────┴─────────────────────────┘ │
│  (empty state: "No symbols currently halted")                            │
└──────────────────────────────────────────────────────────────────────────┘
```

### 13.2 Data sources

```
WS  bridge → state   (CH=STATE, SYM=* for session phase, per-symbol for halts)
```

This view is a pure re-render of state already required for the badges
elsewhere (§8.4, §9.6) — no new data, just a dedicated place to see the
whole board's health at a glance, which is genuinely useful for the
"lobby display" use case in §8.1.

## 14. Screen Design — Depth-of-Book

### 14.1 Purpose and status

A Level 2 order-book ladder for whichever symbol is currently open in
Symbol Detail (§9), toggled on from there rather than being its own nav
tab. This section was originally written as a protocol-extension proposal
for a `DEPTH` channel that did not exist yet; CALF `1.0.0` has since shipped
it exactly as proposed (see
[EduMatcher-CALF-Extensions.md](EduMatcher-CALF-Extensions.md) §6 and the
normative [CALF Protocol Reference](../docs/user-guide/920-app-calf-protocol.md)),
so this is now a regular, buildable screen — not a future increment blocked
on a protocol change. The background on what real venues do and what
EduMatcher already computed internally (§14.2 in the original draft) is kept
below because it explains *why* the ladder is cheap for `md_gateway` to
serve, which still matters for capacity planning even though the channel
itself is no longer new.

### 14.2 What real venues do

Real exchange feeds are conventionally described in three tiers:

| Level | Content | Example real feeds |
|---|---|---|
| Level 1 | Best bid/ask + sizes (what CALF `TOP` provides) | Most consolidated tape/SIP feeds |
| Level 2 | Aggregated depth by price, several to many levels (what CALF `DEPTH` provides) | Nasdaq TotalView (aggregated view), CME MDP 3.0 Market-By-Price (`MBP-10`) |
| Level 3 | Full order-by-order book, every resting order individually | Nasdaq TotalView-ITCH (Market-By-Order), CME MDP 3.0 Market-By-Order |

A Bloomberg-style terminal's depth ladder is a Level 2 view: aggregated
quantity per price level, not individual orders. That is also the right
target for EduMatcher — Level 3 would expose per-order identity CALF
deliberately keeps out of the public feed at every version, `DEPTH`
included (see "Out of scope in CALF 1.0.0" in the normative reference).

### 14.3 Why `DEPTH` is cheap for `md_gateway` to serve

- `OrderBook.snapshot()` (`src/edumatcher/engine/order_book.py`) aggregates
  every resting order into per-price-level rows, sorted best-first, on every
  `book.{SYMBOL}` publish — the exact Level 2 shape `DEPTH` needs.
- `md_gateway` already subscribed to `book.{SYMBOL}` for `TOP` before
  `DEPTH` existed; `DEPTH` reuses that same subscription and payload rather
  than opening a new one — confirmed in the shipped
  `_poll_engine_events`/`normalise_depth` code path
  (`src/edumatcher/md_gateway/gateway.py`,
  `src/edumatcher/md_gateway/normaliser.py`).
- No engine change was required to ship `DEPTH` — it was purely a
  normaliser/gateway addition, which is why it landed quickly once proposed.

### 14.4 `DEPTH` channel, as shipped

Mirrors the `TOP`/`SNAP` shape, per the normative CALF reference:

| Field | Req | Type | Description |
|---|---|---|---|
| `CH` | ✓ | string | `DEPTH` |
| `SYM` | ✓ | string | Instrument symbol — always a concrete symbol; `SYM=*` is not valid for `DEPTH` |
| `SEQ` | ✓ | int | Monotonic sequence for `(DEPTH, SYM)` |
| `TS` | ✓ | string | Event/snapshot timestamp |
| `LEVELS` | ✓ | int | Number of levels included per side (`market_data_gateway.depth_levels`, default 10, gateway-wide — no per-client override) |
| `BIDS` | — | string | Comma-separated `price:qty:count` triples, best price first; omitted (not empty) when no resting bids |
| `ASKS` | — | string | Comma-separated `price:qty:count` triples, best price first; omitted (not empty) when no resting asks |

```text
SUB|CH=DEPTH|SYM=AAPL
SNAP|CH=DEPTH|SYM=AAPL|SEQ=1|TS=2026-07-11T14:32:00.000Z|LEVELS=10|BIDS=150.10:1200:3,150.09:800:2,150.08:400:1|ASKS=150.12:900:2,150.13:600:1,150.14:250:1
DEPTH|CH=DEPTH|SYM=AAPL|SEQ=2|TS=2026-07-11T14:32:00.512Z|LEVELS=10|BIDS=150.10:1400:4,150.09:800:2,150.08:400:1|ASKS=150.12:900:2,150.13:600:1,150.14:250:1
```

`DEPTH` is **full-ladder replace per message, not a per-level diff** — each
message carries a side's complete current top-`LEVELS` ladder, sent only
when the tracked levels actually changed since the previous `DEPTH`/`SNAP`
for that symbol. `pm-terminal`'s depth-rendering code should always replace
its entire in-memory ladder for a side on receipt, never attempt to patch
one price level in place.

`SUB|CH=DEPTH|SYM=*` is invalid — the gateway rejects it with
`ERR|CODE=INVALID_SYMBOL` — because `DEPTH` messages are heavier than `TOP`
(up to `2 × depth_levels` price levels each); this is exactly why §6.4/§6.5
scope `pm-terminal-bridge`'s `DEPTH` subscription to one symbol at a time,
reference-counted by how many open tabs are viewing it, rather than folding
it into the always-on wildcard set the other channels use.

### 14.5 Wireframe

```
┌──────────────────────────────────────────────────────────────────────────┐
│ AAPL — DEPTH                                                             │
├───────────────────┬────────┬──────────────────┬────────┬────────────────┤
│        BID QTY     │  BID   │       │  ASK     │ ASK QTY│                │
├───────────────────┼────────┼──────────────────┼────────┼────────────────┤
│           1,400    │ 150.10 │  ████ │  150.12  │    900 │                │
│             800    │ 150.09 │  ██   │  150.13  │    600 │                │
│             400    │ 150.08 │  █    │  150.14  │    250 │                │
│  …                  │  …    │       │   …      │    …   │                │
├───────────────────┴────────┴──────────────────┴────────┴────────────────┤
│ up to LEVELS rows per side (10 by default, gateway-configured)           │
└──────────────────────────────────────────────────────────────────────────┘
```

Bar length scales to `qty` relative to the largest level currently shown on
either side, same convention as the Movers bar (§12.1). Rows beyond the
gateway's configured `LEVELS` simply don't exist in the feed — there is no
"load more" affordance, since `pm-terminal` cannot request a deeper ladder
than the gateway is configured to publish (§14.4).

### 14.6 Data sources

```
WS  bridge → depth   (CH=DEPTH, one concrete symbol — the symbol currently open in Symbol Detail with the Depth toggle on, §6.4, §9.2)
```

### 14.7 Deferred: order-flow imbalance and microprice

`OrderBook.depth_snapshot()` separately computes `bid_depth`, `ask_depth`,
`imbalance` (`[-1, 1]`), and `microprice` on a different engine topic,
`depth.{SYMBOL}`, which `md_gateway` does not subscribe to. This is
explicitly deferred in
[EduMatcher-CALF-Extensions.md](EduMatcher-CALF-Extensions.md) §7 ("Order-flow
imbalance / microprice fields... a clean follow-up once `DEPTH` has shipped
and proven itself") — not part of CALF `1.0.0`'s `DEPTH` channel. If/when
those fields are added to CALF, they are a natural extension of the ladder
above (an `IMB=`/`MICROPX=` field pair on the same message or a lightweight
companion channel) and this screen would gain an imbalance readout with no
other structural change. Not built out further here; tracked as a future
increment, not an open question blocking this design.

## 15. Visual Design System

Reuses the palette and component conventions already established by
`pm-trading-ui` (§8 there is the canonical reference) rather than inventing
a new one:

| Element | Convention |
|---|---|
| Price up / flash | Green background flash, fades over ~600ms (`FlashCell`) |
| Price down / flash | Red background flash, same fade |
| Halted badge | Amber pill, `HALTED` |
| Auction phase badge | Blue pill, `OPENING_AUCTION` / `CLOSING_AUCTION` |
| Continuous session | No badge — absence of a badge *is* the "normal" signal |
| Disconnected/stale data | Entire affected panel dims to ~50% opacity, small "stale" icon in its corner |
| Typography | Tabular figures (`font-variant-numeric: tabular-nums`) on every price/qty column so digits don't jitter horizontally on update |
| Density | Compact row height by default (this is a "many symbols on screen" tool, not a spacious dashboard) |

## 16. Client State Management

```
┌─────────────────────────────────────────────────────────────┐
│  Zustand (synchronous, in-memory, ephemeral)                │
│  • WS connection status (bridge_status frames)               │
│  • Known symbol list + index list (from `hello` frame)       │
│  • Live top-of-book per symbol (bid/ask/sizes)                │
│  • Live last trade + rolling session volume per symbol        │
│  • Active halts / session phase                                │
│  • Trade tape ring buffer (bounded, ~500 entries)              │
│  • Active symbol (drives Symbol Detail route)                  │
│  • Depth ladder for the active symbol, when Depth toggle is on │
│  • UI prefs: overview page delay, chart series toggles incl. Depth (persisted to localStorage) │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│  TanStack Query (server state, stale-while-revalidate)        │
│  • Daily history rows (`/api/history/daily`) — 5m stale time  │
│  • Trade history for intraday bucketing (`/api/history/trades`) — 60s stale time │
└─────────────────────────────────────────────────────────────┘
```

This is a deliberately smaller split than `pm-trading-ui`'s (§5.3 there) —
there are no orders, positions, or mutations, so the "server state" layer
only ever holds read-only history, never anything invalidated by a write.

## 17. `pm-terminal-bridge` Implementation Guide

### 17.1 CALF session management

```python
# Mirrors md_gateway's own ClientSession shape, one level up
class CalfUplink:
    socket: net.Socket            # TCP connection to pm-md-gwy :5570
    state: "CONNECTED" | "ACTIVE" | "RECONNECTING"
    last_seq: dict[(str, str), int]   # (CH, SYM) -> last SEQ seen, SYM is a concrete symbol or "*"
    subscribed: set[(str, str)]       # (CH, SYM) currently SUB'd, includes ("TOP","*") etc.
    symbols: list[str]                 # from WELCOME|SYMBOLS=, grown as new symbols are learned
    ch_supported: set[str]             # parsed from WELCOME|CH_SUPPORTED=
```

- On connect: `HELLO|CLIENT=pm-terminal-bridge|PROTO=CALF1`, then
  immediately `SUB|CH=STATE,TOP,TRADE|SYM=*` and
  `SUB|CH=INDEX|SYM=<configured index ids>` (§6.4) — all are available from
  the first `SUB` with no need to wait on `WELCOME|SYMBOLS=` first, since
  `SYM=*` covers symbols the bridge hasn't even learned about yet (they
  fan out automatically once the gateway sees them, per the CALF `1.0.0`
  wildcard semantics). Parse `WELCOME|CH_SUPPORTED=` and only send
  `SUB|CH=DEPTH|...` calls if `DEPTH` is present, so the bridge degrades
  gracefully against an older gateway build instead of erroring on every
  depth-toggle request.
- **Reconnect is where the wildcard subscriptions get more work, not less.**
  `HELLO|RESUME=1` only ever resumes one `(CH, SYM)` stream per `HELLO`, and
  `SYM=*` is invalid for `RESUME` on every channel — the gateway rejects it
  outright, even for `TOP`/`TRADE`/`STATE`, because there is no wildcard
  snapshot baseline to fall back on for a replay miss (§920 of the CALF
  reference, "Reconnect behavior"). So the bridge cannot simply resend
  `HELLO|RESUME=1|CH=TOP|SYM=*|LASTSEQ=...` after a drop. Instead, on
  reconnect the bridge:
  1. Sends a plain `HELLO` (no `RESUME`) to re-establish the session and
     get a fresh `WELCOME`.
  2. Re-issues `SUB|CH=STATE,TOP,TRADE|SYM=*` and
     `SUB|CH=INDEX|SYM=<index ids>` immediately — this restores live
     delivery going forward for every symbol right away, same as first
     connect.
  3. For any symbol the bridge was actively serving to a browser tab
     (i.e. had non-empty `last_seq` for), issues a **separate**
     `HELLO...RESUME=1|CH=<ch>|SYM=<that concrete symbol>|LASTSEQ=...`
     per stream to backfill the gap between disconnect and step 2's fresh
     `SUB`, exactly as the CALF reference's worked client example does —
     just looped over concrete symbols instead of assumed to work with a
     single wildcard call. This step is a best-effort gap-fill, not a
     correctness requirement: `pm-terminal` is a display-only viewer, so a
     brief tick gap during reconnect (visible to the user only as a short
     `RECONNECTING` state, §6.6) is an acceptable trade-off against the
     complexity of resuming every known symbol on every reconnect.
  4. `DEPTH` subscriptions follow the same per-symbol resume pattern in
     step 3, scoped to whichever symbols currently have their Depth toggle
     on (§6.5) — there is no wildcard `DEPTH` to re-establish in step 2.
- Buffer partial TCP reads and split on `\n` — the same non-negotiable rule
  the CALF reference calls out ("TCP stream requirement"); do not assume one
  `recv`/`data` event is one message.
- On `ERR|CODE=SLOW_CLIENT`, reconnect immediately following the sequence
  above (the bridge, not the browser, is the "client" CALF sees, so this
  only ever affects the bridge's own uplink, never a browser tab directly).

### 17.2 REST history proxy

The bridge exposes a thin, symbol/date/limit-passthrough proxy in front of
`pm-api-gwy`'s `/history/daily` and `/history/trades`:

```
GET /api/history/daily?symbol=AAPL&date=2026-07-11
GET /api/history/trades?symbol=AAPL&from=...&to=...&limit=1000
```

The bridge holds one long-lived `pm-api-gwy` API key (read-only history
scope — see §18) in its own config and attaches it server-side; the browser
never sees a credential. Responses are passed through unmodified (same
shape `pm-trading-ui` already consumes), so the frontend's history-fetching
code can be near-identical to `pm-trading-ui`'s existing implementation.

### 17.3 Bridge → browser WS message schema

One WebSocket per browser tab, JSON frames, discriminated by `type`:

```jsonc
{ "type": "hello", "symbols": ["AAPL","MSFT","TSLA"], "indexes": ["EDU100"] }
{ "type": "top", "sym": "AAPL", "seq": 101, "ts": "...", "bid": 150.10, "bidSz": 1400, "ask": 150.12, "askSz": 900, "last": 150.12, "lastSz": 200 }
{ "type": "trade", "sym": "AAPL", "seq": 44, "ts": "...", "px": 150.12, "qty": 200, "side": "BUY" }
{ "type": "state", "sym": "AAPL", "seq": 3, "ts": "...", "session": "HALTED", "prev": "CONTINUOUS" }
{ "type": "index", "sym": "EDU100", "seq": 42, "ts": "...", "level": 1048.73, "chg": 6.63, "pctChg": 0.64, "open": 1042.10, "high": 1056.30, "low": 1040.05 }
{ "type": "depth", "sym": "AAPL", "seq": 2, "ts": "...", "levels": 10, "bids": [[150.10,1400,4],[150.09,800,2]], "asks": [[150.12,900,2],[150.13,600,1]] }
{ "type": "bridge_status", "calf": "ACTIVE" | "RECONNECTING", "since": "..." }
```

`depth` frames are only sent to a browser tab that has subscribed to that
symbol's ladder via a `depth_subscribe`/`depth_unsubscribe` client→bridge
message (not shown above — a small control frame the browser sends when the
Depth toggle in Symbol Detail is switched on/off, §9.2), which is what
drives the bridge's reference-counted `SUB|CH=DEPTH`/`UNSUB` behavior
(§6.5). Every other frame type above is pushed to all connected tabs
unconditionally, since the bridge's `TOP`/`TRADE`/`STATE`/`INDEX`
subscriptions are always-on regardless of which tab wants what (§6.4). The
`BIDS`/`ASKS` `price:qty:count` wire triples are parsed once, server-side,
into `[price, qty, count]` number tuples so the browser never touches the
CALF colon/comma grammar.

Deliberately flat JSON, one object per CALF line — no client-side parsing
of the pipe-delimited wire format is needed; that translation happens once,
server-side, in `packages/calf-protocol`.

### 17.4 New files

| File | Purpose |
|---|---|
| `apps/bridge/src/main.ts` | Fastify app entry, WS route, HTTP proxy routes |
| `apps/bridge/src/calf/uplink.ts` | `CalfUplink` class (§17.1) |
| `apps/bridge/src/calf/subscriptions.ts` | Always-on `SYM=*` wildcard `SUB` for `TOP`/`TRADE`/`STATE`, config-driven `SUB|CH=INDEX` (§6.4) |
| `apps/bridge/src/calf/depth-refcount.ts` | Per-symbol `SUB\|CH=DEPTH`/`UNSUB` reference counting across browser tabs (§6.5, §9.2, §14.6) |
| `apps/bridge/src/history-proxy.ts` | `/api/history/*` passthrough to `pm-api-gwy` (§17.2) |
| `apps/bridge/src/ws-fanout.ts` | Per-tab WS session registry, frame broadcast |
| `packages/calf-protocol/src/index.ts` | `parseLine`/`buildLine`, TS port of `md_gateway/protocol.py`'s grammar |
| `packages/shared-types/src/index.ts` | `TopFrame`, `TradeFrame`, `StateFrame`, `IndexFrame`, `DepthFrame`, `DailyBar`, etc. |

## 18. Security and Operational Notes

- **No trading credentials ever reach the browser.** The one `pm-api-gwy`
  API key the bridge needs for `/history/*` lives only in the bridge's own
  config/environment, never serialized to the client.
- The CALF connection itself needs no credential today (trusted-network
  assumption, per the normative CALF reference's "Out of scope in CALF
  1.0.0" list, which still names a protocol-layer auth token as a
  possibility for a future version); if CALF ever grows a `TOKEN=` field,
  the bridge is the right and only place to hold it.
- `pm-terminal` should run on a read-only network path — it never needs
  outbound access to anything but `pm-md-gwy:5570` and `pm-api-gwy:8080`.
- Because every browser tab shares the bridge's single CALF uplink (§6.5),
  the bridge should cap total browser WS connections (config, default 200)
  to bound its own fan-out cost — this is the bridge's own concern, not a
  CALF-side limit.
- The bridge's own `max_symbols_per_client` exposure to `pm-md-gwy` is
  bounded and predictable: `TOP`/`TRADE`/`STATE` each contribute one entry
  (`"*"`) regardless of symbol count (per CALF's wildcard accounting rule),
  and `DEPTH` contributes one entry per symbol currently reference-counted
  above zero (§6.5) — in practice, at most the number of distinct symbols
  simultaneously open across all browser tabs' Symbol Detail views, which
  is naturally small. The bridge does not need its own separate cap on
  concurrent `DEPTH` subscriptions beyond what `pm-md-gwy`'s
  `max_symbols_per_client` already enforces.
- No PII anywhere in this application; it displays market data only.

## 19. Config Reference

```yaml
# apps/bridge/config.yaml
terminal_bridge:
  calf:
    host: "127.0.0.1"
    port: 5570
    client_id: "pm-terminal-bridge"
  api_gateway:
    base_url: "http://127.0.0.1:8080"
    api_key: "${PM_TERMINAL_API_KEY}"   # env var, never checked in
  server:
    bind_address: "0.0.0.0"
    port: 8090
    max_ws_clients: 200
  overview:
    default_page_delay_sec: 8
    symbols_per_page: "auto"            # derived from viewport at runtime
```

## 20. Testing Strategy

| Layer | Tool | What's covered |
|---|---|---|
| `packages/calf-protocol` | Vitest | Line parse/build round-trip, malformed-line rejection (mirrors `test_md_normaliser.py`'s cases) |
| `apps/bridge` uplink | Vitest + a fake CALF TCP server | HELLO/WELCOME handshake incl. `CH_SUPPORTED` parsing, wildcard `SUB` fan-out (§6.4), per-symbol `RESUME`-after-wildcard reconnect sequencing (§17.1 — this is the trickiest path and deserves its own dedicated test group), `DEPTH` reference-count subscribe/unsubscribe (§6.5), SLOW_CLIENT reconnect |
| `apps/bridge` history proxy | Vitest + mocked `pm-api-gwy` responses | Passthrough shape, error propagation (503 when stats DB unavailable) |
| `apps/web` components | Vitest + React Testing Library | FlashCell flash behaviour, Overview paging timer, chart series toggles incl. Depth toggle mount/unmount triggering `depth_subscribe`/`depth_unsubscribe` |
| End-to-end | Playwright, against a running `pm-engine` + `pm-md-gwy` + `pm-api-gwy` + bridge stack | Overview loads and pages; Symbol Detail chart renders and zooms; Depth ladder renders and updates on a resting-order change; a manual trade in the engine appears in the Tape within one polling interval |

## 21. Implementation Plan

| Phase | Scope |
|---|---|
| 1 | Monorepo scaffold; `packages/calf-protocol`; bridge CALF uplink connecting and logging parsed frames (no WS/browser yet) |
| 2 | Bridge WS fan-out + browser shell/nav (§7); Session & Halt board (§13, simplest view, validates the whole pipe end-to-end) |
| 3 | Market Overview (§8) incl. paging and REST-baseline OPEN/VOLUME |
| 4 | Symbol Detail (§9): chart, zoom, values table, live+historical splice |
| 5 | Index View (§10); Trade Tape (§11); Movers/Heatmap (§12) — all reuse Phase 2–4 plumbing |
| 6 | Depth ladder (§14): `CH=DEPTH` reference-counted subscribe/unsubscribe (§6.5), Symbol Detail Depth toggle and ladder rendering. No longer blocked on a protocol change — `DEPTH` ships in CALF `1.0.0` — so this can be pulled forward alongside Phase 4/5 rather than deferred; kept as its own phase here only because it depends on the per-symbol reference-counting plumbing being in place first, not because of any external blocker |

## 22. Open Questions

Four questions from the original draft of this document are now resolved
and removed from this list: whether `INDEX` should be formally documented
(it has been, in the normative CALF reference), whether `TRADE`/`TOP`
should gain a `SYM=*` wildcard (shipped in CALF `1.0.0`), whether the
proposed `DEPTH` channel should exist at all (shipped), and whether it
should ship opt-in-gated or on by default (shipped on by default, no
gateway config flag to disable it — only `depth_levels` tunes ladder
depth). What remains genuinely open:

1. Does `pm-stats` retain a queryable historical series for index levels
   specifically (not just per-symbol daily bars)? `EduMatcher-Index.md`
   mentions historical index values are stored on disk, but as a per-index
   JSONL file (`data/indexes/<id>_history.jsonl`), separate from the
   `stats.db` that `pm-api-gwy`'s `GET /history/daily` actually queries —
   so §10.4's REST call for index history may not resolve to real data as
   currently specified. This needs a follow-up check against `pm-index`'s
   storage and, likely, either a new `pm-api-gwy` endpoint or a documented
   v1 limitation (no historical index chart, headline stats only) before
   §10.4 can be finalized.
2. Constituent-level live weight updates for the Index view (§10.2) are
   shown as a static list in this design. Is per-constituent weight drift
   (as prices move intraday) worth streaming, or is a periodic
   recompute-on-open sufficient for a teaching tool?
3. Should `pm-terminal-bridge` eventually parse `WELCOME|CH_SUPPORTED=`
   defensively enough to run against a pre-`1.0.0` `pm-md-gwy` (falling back
   to enumerated per-symbol `SUB` for `TOP`/`TRADE` and hiding the Depth
   toggle entirely, per the capability-detection flow the CALF reference
   describes), or is targeting CALF `1.0.0` only an acceptable simplifying
   assumption given `pm-terminal` and `pm-md-gwy` are versioned and
   deployed together in this project? This document assumes the latter
   throughout (§17.1's `SUB|CH=STATE,TOP,TRADE|SYM=*` on connect has no
   fallback path) but flags it here since it is a real compatibility
   decision, not an oversight.

## 23. Summary

`pm-terminal` is a read-only, credential-free Bloomberg-style viewer that
consumes CALF `1.0.0` as its live backbone — exactly the audience CALF was
designed for — while reusing `pm-api-gwy`'s existing, already-proven history
endpoints for anything CALF intentionally doesn't carry, at any protocol
version. The audit in §4 found CALF `1.0.0` sufficient for every *live*
requirement in this design, including a full order-book depth ladder
(`DEPTH`, §14) and a single wildcard subscription for market-wide `TOP`/
`TRADE` feeds (Overview §8, Trade Tape §11) — capabilities an earlier draft
of this document had to work around or propose as protocol extensions,
which CALF `1.0.0` has since shipped in full. The one remaining real gap is
historical data, which CALF intentionally never carries at any version;
that is resolved by architecture decision (reuse `pm-api-gwy`, don't
reinvent storage, §6/§17.2) rather than a protocol change. Structurally it
mirrors `config-gui`: a small first-party Node/Fastify backend plus a
Vite/React frontend, sharing `pm-trading-ui`'s visual language so the three
EduMatcher web tools read as one family.
