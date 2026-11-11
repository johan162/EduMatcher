# Clearing GUI (`pm-clearing-ui`)

!!! note "Learning objectives"
    After reading this page you will understand:

    - What the Clearing GUI is for, and how it reaches the clearing data
    - What must be configured and running for each of its screens
    - How to start it with the stack, on its own, or for development
    - How to use the ADMIN screens: freshness, feed gaps, health,
      reconciliation and EOD settlement
    - How to diagnose an error it shows
    - What load it puts on the exchange, and what it deliberately leaves out


## Overview

The **Clearing GUI** (`pm-clearing-ui`, `web-apps/clearing-gui/`, port
**8096**) is a read-only browser client over the post-trade ledger
`pm-clearing` writes (`clearing.db`) and the settlement ledger `pm-eod`
writes (`eod.db`). An ADMIN key sees the whole venue; a TRADER or
MARKET_MAKER key sees its own gateway — the participants' side is described in
the Participant Guide's [Clearing GUI](../../participant-guide/part-6-front-ends/040-clearing-gui.md)
chapter.

The browser talks to one service only: `pm-api-gwy`, through its
`/api/v1/clearing` routes (and `/api/v1/status`, `/api/v1/symbols`). The
gateway opens both databases read-only, enforces who may see what, and
answers every request; the GUI's own server serves static files and proxies
`/api`. No database path, bus address or health socket ever reaches the
browser.

```
browser ──/api──▶ pm-clearing-ui-serve (8096) ──▶ pm-api-gwy (8080)
                                                     ├─ clearing.db (read-only) ◀─ pm-clearing
                                                     ├─ eod.db + roster (read-only) ◀─ pm-eod
                                                     └─ pm-clearing health ping (ADMIN health only)
```


## What must be running

| Screen | Needs |
|---|---|
| Everything | `pm-api-gwy` (the `desk` instance in the shipped stack) and `pm-engine` (it confirms each key and its role) |
| Positions, trades, history, events, sessions, reconciliation, overview | `clearing_db` in the gateway's `api_gateways` block pointing at the file `pm-clearing` writes (default `data/clearing.db`) |
| EOD Settlement, balances | `eod_db` pointing at `pm-eod`'s ledger (default `data/eod.db`); opening balances from `ref_data/roster.yaml` beside it |
| Health's process line | `pm-clearing` running on the host the gateway reaches as `EDUMATCHER_ENGINE_HOST`, health port `EDUMATCHER_CLEARING_HEALTH_PORT` (5563) — the same check `pm-clearing-cli health` makes |
| My Quote Obligations | The engine's resolved symbol settings (`GET /api/v1/symbols`) |

Keys: participants log in with their trading gateway's key, operators with an
ADMIN gateway's key (`OPS01` in the bundled configurations). A read-only key
cannot log in. See [API Gateway](../part-5-gateways/050-api-gateway.md) for
the routes, the `clearing_db` / `eod_db` settings and the access rules.


## Starting it

**With the stack.** The source-built and released compose stacks run it
beside the other GUIs (`edumatcher-clearing-gui`, published on
`CLEARING_GUI_PORT`, default 8096), proxying to the `desk` gateway.
`./edumatcher.sh urls` and `make up-all` list it.

**On its own, in a container.**

```bash
cd web-apps/clearing-gui
API_PROXY_TARGET=http://host.containers.internal:8080 make up   # Podman
make up                                                          # Docker Desktop
```

**Without a container.**

```bash
cd web-apps/clearing-gui
make install && make build
API_PROXY_TARGET=http://localhost:8080 make serve    # production build on :8096
make dev                                             # Vite on :8196, /api → localhost:8080
```

| Variable | Default | Meaning |
|---|---|---|
| `API_PROXY_TARGET` | unset (compose: `http://host.docker.internal:8080`) | Where `/api/*` goes. Unset: `/api/*` answers 503 with an explanation |
| `HOST` / `PORT` | `0.0.0.0` / `8096` | The static server's listener |
| `STATIC_DIR` | `apps/web/dist` | The built application |
| `CLEARING_GUI_PORT` | `8096` | Host port the container is published on |


## The ADMIN screens

**Clearing Overview** — the first place to look.

- *Last clearing write / newest trade*: when `pm-clearing` last committed.
  Fills are written in batches (100 trades or 5 seconds), so up to 5 seconds
  of lag is normal; minutes mean `pm-clearing` is stalled or not receiving.
- *Feed gap* (red alert): `pm-clearing` saw the engine's trade ids jump on
  the latest session date — trades it never received. Positions and P&L may
  be missing them. Run a reconciliation and check the audit trail. No gap
  does not prove the feed was complete; it is only the absence of evidence.
- *Health*: two separate lines. **Database** — whether `clearing.db` could be
  read, its journal mode and row counts. **pm-clearing process** — whether
  its receive loop answered a ping. A readable database with a silent
  process means the data is frozen at the last write.
- Participants (click one to drill down), the last `pm-eod` run, recent
  session events.

**Participants / drill-down** — one gateway's totals and the same tabs a
participant sees, for that gateway.

**Symbols** — traded quantity and value per symbol over a date range, and the
aggregate signed position now. That aggregate is zero while every holder is a
gateway; it is not open interest.

**Events** — `PHASE`, `EOD` and `GAP` events with their content. Times are
when clearing observed the event.

**Gateway Sessions** — connect/disconnect history, filterable by gateway and
"connected only".

**Reconciliation** — compares the raw trades with the daily rows for an
explicit date range, on demand (**Run**). Only days that still have raw
trades (the retention window, `pm-clearing --retention-days`, 90 by default)
can be compared; the result says which window was compared. An empty result
reads *No discrepancy in the queried retained data* — not a verified
history. A discrepancy row shows the side, day, gateway and symbol with the
raw and daily quantities and values.

**EOD Settlement** — every account's daily settlement in minor units, the
`EXCHANGE` rounding account, the derived balances, and each `pm-eod` run with
its steps.


## Diagnosing what it shows

| The GUI says | Cause | Check |
|---|---|---|
| *Cannot reach the API gateway* / top bar *API unreachable* | `pm-api-gwy` down, or the proxy target wrong | `API_PROXY_TARGET`; `curl http://<gateway>:8080/api/v1/healthz` |
| *Gateway reached, but the engine did not answer* (login) | `pm-engine` not running | `pm-opctl-cli status` |
| `CLEARING_DB: … unavailable: not found` | `clearing_db` points at no file | the gateway's `clearing_db`; `pm-clearing-cli health --extended` |
| `CLEARING_DB: … database is locked` | a read waited out a long write | usually transient; retry |
| `EOD_DB: … unavailable` | no `eod.db` (pm-eod never ran) or a malformed roster | `pm-eod status`; the gateway log names the roster line |
| Health: *pm-clearing process: not answering* | `pm-clearing` stopped, or the health address differs | `pm-clearing-cli health` from the gateway's host |
| *API contract error* | the GUI and the gateway are different versions | deploy matching versions |
| Feed gap alert | trades lost on the bus between engine and clearing | reconcile the day; compare with the audit trail |

The gateway logs every unreadable store as a WARNING (`clearing: cannot read
…`), with an explanation in the log ledger (`pm-log-cli explain`).


## Load on the exchange

The GUI is built to stay cheap however long it is left open:

- current state — positions, exposure, participants, the overview summary —
  is refreshed every 5 seconds, matching the clearing flush, from small
  aggregate tables;
- health every 30 seconds (each call pings `pm-clearing` once);
- trades, history, events and settlement only when a screen or filter asks;
  reconciliation only on **Run**, never automatically;
- every list is bounded (`limit`, at most 5 000 rows); the trade audit pages
  200 at a time by cursor.

Measured with `tools/clearing_api_bench.py` on a 180 000-trade ledger (90 days,
40 gateways, 20 symbols), in-process through the real gateway app:

| Request | Cadence | p50 | Response |
|---|---|---:|---:|
| Overview summary | 5 s | 3 ms | 0.3 kB |
| Participants | 5 s | 4 ms | 7 kB |
| One gateway's positions / exposure | 5 s | 4 ms | 10 kB |
| Health (bench: a silent process and a 50 ms ping bound; live, at most the 0.5 s ping bound) | 30 s | 52 ms | 0.3 kB |
| A trade page (200 rows, venue or one gateway) | on demand | 10–12 ms | 75 kB |
| One gateway's daily rows (1 000) | on demand | 19–45 ms | 585 kB |
| Symbol activity, 90 days | on demand | 93 ms | 5 kB |
| Reconciliation, 7 days / 90 days | on Run | 0.12 s / 1.2 s | — |


## What it leaves out

Release 1.0 shows only what the system records. There is no margin,
collateral, equity, buying power, credit limit, open interest, intraday P&L
history, client (sub-)account, or market-maker presence/compliance figure,
and no way to change anything. The design and the conditions for any of
these are in `docs-design/EduMatcher-Clearing-GUI.md` §10 and §13.
