Version: 0.1.0

Date: 2026-10-11

Status: Design proposal — not implemented

# EduMatcher — Operator Dashboard (`pm-dash`, `web-apps/dash-gui`) and Health Instrumentation (`pm-monitor`) Design and Implementation Plan

## Table of Contents

1. [Summary](#1-summary)
2. [Requirements](#2-requirements)
3. [Decisions taken before this design](#3-decisions-taken-before-this-design)
4. [Observability audit — what exists today](#4-observability-audit--what-exists-today)
5. [Gap analysis — what needs new instrumentation](#5-gap-analysis--what-needs-new-instrumentation)
6. [Architecture](#6-architecture)
7. [New instrumentation: the health beacon](#7-new-instrumentation-the-health-beacon)
8. [New instrumentation: per-process metric catalogue](#8-new-instrumentation-per-process-metric-catalogue)
9. [`pm-monitor` — the collector](#9-pm-monitor--the-collector)
10. [Health model — healthy, degraded, hung, dead](#10-health-model--healthy-degraded-hung-dead)
11. [Bridge ↔ browser protocol](#11-bridge--browser-protocol)
12. [Screen design](#12-screen-design)
13. [Widget library](#13-widget-library)
14. [Configuration](#14-configuration)
15. [Container, Makefile, ports and versioning](#15-container-makefile-ports-and-versioning)
16. [Repository layout](#16-repository-layout)
17. [Test strategy](#17-test-strategy)
18. [Implementation plan — work packages](#18-implementation-plan--work-packages)
19. [Risks and open questions](#19-risks-and-open-questions)

---

## 1. Summary

EduMatcher has no single place where an operator can see whether the exchange
is healthy. The pieces exist, but they are scattered and partial:

- `pm-opctl-cli list` shows PID, RSS and uptime from `ps`, but only on demand,
  only on the host that started the profile, and only from a process that is
  *alive*. It cannot tell a hung process from a working one (its own README
  says so: a ZMQ `tcp` check succeeds while the application loop is stuck).
- `pm-log-srv`'s `processes` table knows who connected and when they last
  spoke, but its `HB` frame comes from a **background thread** and is sent
  only when the connection is idle. A process whose main loop is deadlocked
  keeps heartbeating forever.
- The engine knows everything about orders, trades, participants and books,
  but keeps almost none of it as counters, and publishes only a few polled
  snapshots (`system.gateways`, `system.volume`).

This design adds three things:

1. **A health beacon** (`edumatcher.health`) that every long-running `pm-*`
   process emits every 2 s: its own memory, CPU, threads, file descriptors,
   **main-loop age** (time since the main loop last completed an iteration),
   and a small set of application counters and gauges. The main-loop age is
   what makes hung-process detection possible.
2. **`pm-monitor`**, a new Python process that collects the beacons, samples
   the host (CPU, memory, disk), listens to the engine's lifecycle events
   (connects, disconnects, halts, session transitions, diagnostics), derives
   rates and health states, persists a downsampled history to `metrics.db`,
   and republishes a live 1 Hz snapshot.
3. **`pm-dash`** (`web-apps/dash-gui`), a Grafana-style web dashboard with
   the same structure, tooling, theme mechanism and container setup as
   `book-gui`. Its bridge reads `pm-monitor`'s live feed over ZeroMQ and its
   history from a read-only `metrics.db` — exactly the shape of `log-gui`
   (live from LALF-PS, history from `log.db`).

No Grafana, no Prometheus, no time-series database. One new Python dependency
(`psutil`) and no new npm chart library: `recharts` is already used by
`log-gui` and `trader-gui`; gauges and the state timeline are small
hand-written SVG components.

## 2. Requirements

| # | Requirement (from the request) | Where addressed |
|---|---|---|
| R1 | Total memory usage | §8.1 host metrics, §12.3 row *Overview* |
| R2 | Memory per exchange process | §7 beacon `rss_bytes`, §12.3 row *Processes* |
| R3 | Submitted orders — total, avg per min / hour / day | §8.2 `engine.orders_in`, §9.4 rate derivation, §12.3 row *Trading* |
| R4 | Concluded trades | §8.2 `engine.trades`, §12.3 row *Trading* |
| R5 | Connected participants | §8.2 `engine.participants_connected`, §12.3 row *Participants* |
| R6 | Orders per participant — total, avg per min / hour / day | §8.2 labelled counters, §12.3 participant table |
| R7 | Connections / disconnections | §8.2 counters + §9.2 lifecycle events, §12.3 state timeline |
| R8 | CPU usage | §7 beacon `cpu_pct`, §8.1 host CPU |
| R9 | Number of order books and memory per order book | §8.3 book gauges + memory estimate |
| R10 | Hung / healthy processes | §7.3 main-loop age, §10 health model |
| R11 | Other vital health information | §8.4–§8.6 (latency, rejects, drops, feed gaps, disk, DB sizes, diagnostics) |
| R12 | Web app with the same structure as existing web-apps | §15, §16 |
| R13 | Dark and light theme | §12.5 |
| R14 | Speed-meter gauges, graphs, big numbers, Grafana-like colours | §12, §13 |
| R15 | Identify missing instrumentation and health messages | §5, §7, §8 |

**Non-goals.** No alert delivery (e-mail, Slack, paging) — threshold breaches
are logged as `WARNING` through the normal log path, so `log-gui`'s existing
alerting picks them up (§9.6). No process control from the dashboard (start,
stop, restart stays in `pm-opctl-cli`). No user-configurable dashboard editor
— the layout is fixed in code. No PromQL-like query language. No
authentication (§3).

## 3. Decisions taken before this design

Settled with Johan on 2026-10-11:

| Question | Decision | Consequence |
|---|---|---|
| Where are metrics collected? | **A new `pm-monitor` process** | Neither `pm-log-srv` nor `pm-api-gwy` takes on a second job. |
| How are CPU and memory sampled? | **Add `psutil`** as a runtime dependency | Same code on macOS and Linux; host totals, FDs and threads for free. `psutil` is already in `poetry.lock` as a transitive dev dependency; it becomes a direct one. |
| How much history? | **Persist to `metrics.db`** with downsampling | Day-level averages and post-mortems survive a restart of `pm-monitor` or of the engine. |
| Who may open the dashboard? | **No authentication**, like `log-gui` | Internal operator tool on the trusted network; the same posture as LALF-PS. Bind to loopback by default (§15.2). |

## 4. Observability audit — what exists today

Every source below was read in the tree on 2026-10-11.

| Source | What it gives | Limits that matter here |
|---|---|---|
| `pm-opctl-cli list` / `health` (`emo/cli.py`) | Per process in the active profile: PID alive, `tcp` connect or `healthcheck` result, uptime and RSS via `ps -o etime=,rss=` | On demand only, no history. Only the profile started on this host. `tcp` succeeds against a hung process (libzmq accepts in its I/O thread). No CPU. |
| `<DATA>/emo/active-profile` + profile definition | Which processes **should** be running | Not consumed by anything but `pm-opctl-cli`. Reused by `pm-monitor` (§9.3). |
| `pm-log-srv` `processes` table (`log_srv/schema.py`) | One row per LALF session: process, instance, PID, host, `connected_at`, `last_seen_at`, `disconnected_at`, `log_count` | `HB` is sent by the `TcpLogHandler` **background thread**, only when the socket is idle — proves the interpreter is alive, not that the main loop runs. Probe connections create a second row per PID (see `log-gui` Connections view). |
| `pm-log-srv` `server_stats` | Lifetime totals: events, connections, truncated, errors | Lifetime only, no rates. |
| Engine `system.gateways.{GW}` (polled) | Every configured participant: id, role, description, `connected` | No connect time, no counters, polled request/reply. |
| Engine `system.gateway_auth.{GW}` / `system.gateway_bye.{GW}` (broadcast) | Every accepted/rejected connect and every disconnect, with `reason` (`heartbeat_timeout` when the engine expired a silent session) | Events only — nobody counts them. |
| Engine `system.volume.{GW}` (polled) | Per symbol and total: qty, value, trade count — the engine's own running counters (`OrderBook.daily_qty/daily_value_ticks/daily_trades`) | Trades only; nothing about orders. Reset only by engine restart. |
| Engine `system.diagnostic` (broadcast) | Absorbed internal failures, with a per-component running `count` (`MAINTENANCE_FLUSH`, `DISPATCH_ERROR`, `UNDECODABLE_MESSAGE`, `UNROUTED_TOPIC`) | Only fires on a failure, so a zero count is never published. |
| Engine `_debug_counts` (`_dbg_count`) | A rich set of decision counters | Only accumulated when the logger is at `DEBUG`, flushed to the log as text, then cleared. Not usable as metrics. |
| `pm-api-gwy` `GET /api/v1/healthz` | `ok`, `active_gateways` (this instance only), `dropped_events` | Per instance; dropped count is the only rate-like figure. |
| `stats.db` `order_events` (`pm-stats`) | Every ack / reject / fill / cancel / amend / expire with `gateway_id`, `symbol`, `ts`; indexed `(gateway_id, ts)` | Correct source for **historical** per-participant reports, but a full-table aggregation per refresh is the wrong tool for a 1 Hz dashboard, and it records outcomes, not inbound submissions. |
| `stats.db` `feed_gaps` | Detected sequence gaps in the engine trade stream | Nobody surfaces it live. |
| `pm-stats-cli health` | pm-stats process + DB read/write check | Exit code only. |
| ALF/BALF/MD gateways | `self._clients` dict per gateway; `max_connections` enforced | Count is never exported. |

**Conclusion.** Liveness by PID and the participant roster exist. Everything
the request calls a *rate*, every per-participant order figure, per-book
sizes and memory, CPU, and any trustworthy hung-process signal do **not**.

## 5. Gap analysis — what needs new instrumentation

| # | Metric requested | Available today? | Gap | New instrumentation (section) |
|---|---|---|---|---|
| G1 | Total memory (host) | No | Nothing samples the host | `pm-monitor` host sampler via `psutil.virtual_memory()` (§8.1) |
| G2 | Memory per process | Partly (`ps` on demand, same host) | Continuous, cross-host, history | Beacon `rss_bytes` (§7.2) |
| G3 | CPU per process / host | No | — | Beacon `cpu_pct`, host `cpu_percent(percpu=True)` (§7.2, §8.1) |
| G4 | Orders submitted (total, rates) | No | Engine has no inbound-order counter | `engine.orders_in{gateway}` counter (§8.2) |
| G5 | Orders per participant | Only historically via `order_events` | No live counter | Same counter, labelled by gateway (§8.2) |
| G6 | Trades | Yes, polled (`system.volume`) | Not pushed, not in history | Engine beacon carries `engine.trades{symbol}`, `engine.traded_qty{symbol}`, `engine.traded_value{symbol}` from the existing book counters (§8.2) |
| G7 | Connected participants | Yes, polled (`system.gateways`) | Not pushed | Gauge `engine.participants_connected` (§8.2) |
| G8 | Connections / disconnections | Events only | Never counted | Counters `engine.connects`, `engine.disconnects`, `engine.heartbeat_timeouts`, `engine.auth_rejects` + lifecycle events persisted by `pm-monitor` (§8.2, §9.2) |
| G9 | Number of order books | Derivable from reference data | Not exported | Gauge `engine.books` (§8.3) |
| G10 | Memory per order book | **No** | Python has no per-object-graph memory API that is cheap | `OrderBook.memory_estimate()` (§8.3) |
| G11 | Hung processes | **No** (PID + `tcp` cannot see it) | No signal from the main loop | Beacon `loop_age_ms` / `loop_lag_ms` (§7.3) |
| G12 | Engine processing latency | No | — | `engine.handle_us` p50/p99/max per interval (§8.4) |
| G13 | Reject ratio | Only historically | — | `engine.rejects{gateway}` (§8.2) |
| G14 | Gateway client counts and drops | No | `_clients` never exported | Per-gateway gauges/counters (§8.5) |
| G15 | Log ingest rate, DB and audit-file growth | Lifetime totals only | — | `pm-log-srv` counters + `pm-monitor` file sizes (§8.5, §8.1) |
| G16 | Expected-but-missing processes | Only via `pm-opctl-cli list` | — | `pm-monitor` reads the active profile (§9.3) |
| G17 | Engine diagnostics | Broadcast on failure | Counts not visible when zero | Engine beacon carries `engine.diagnostics{component}` (§8.4) |
| G18 | Session state, halts | Yes, broadcast | Not on any operator timeline | `pm-monitor` subscribes and records annotations (§9.2) |

New **messages** needed (all in a new `spec/messages/monitor.yaml`, generated
by `pm-msgen` like every other family):

| Message | Topic | Transport | Direction |
|---|---|---|---|
| `beacon` | `monitor.beacon` | `monitor_push` (new) | every `pm-*` process → `pm-monitor` |
| `snapshot` | `monitor.snapshot` | `monitor_pub` (new) | `pm-monitor` → dashboard bridge, 1 Hz |
| `event` | `monitor.event` | `monitor_pub` | `pm-monitor` → bridge, on each status change / lifecycle event |

No new engine bus topic is needed: the engine's metrics travel in its own
beacon like every other process's.

## 6. Architecture

```mermaid
flowchart LR
  subgraph procs["pm-* processes (any host)"]
    ENG["pm-engine<br/>HealthReporter"]
    GW["pm-alf-gwy / pm-balf-gwy / pm-md-gwy<br/>pm-ralf-gwy / pm-dc-gwy / pm-api-gwy"]
    SVC["pm-log-srv / pm-stats / pm-audit<br/>pm-clearing / pm-scheduler / pm-index ..."]
  end

  ENG -- "monitor.beacon (PUSH)" --> PULL
  GW -- "monitor.beacon (PUSH)" --> PULL
  SVC -- "monitor.beacon (PUSH)" --> PULL
  ENG -- "engine PUB :5556<br/>gateway_auth / gateway_bye /<br/>diagnostic / session / CB halt" --> SUB

  subgraph MON["pm-monitor"]
    PULL["PULL :5610"]
    SUB["SUB engine :5556"]
    HOST["host sampler<br/>(psutil)"]
    PROF["expected roster<br/>(emo active profile)"]
    AGG["aggregator<br/>rates · health · thresholds"]
    PUB["PUB :5611<br/>monitor.snapshot / monitor.event"]
    DB[("metrics.db<br/>SQLite WAL")]
    PULL --> AGG
    SUB --> AGG
    HOST --> AGG
    PROF --> AGG
    AGG --> PUB
    AGG --> DB
  end

  subgraph DASH["web-apps/dash-gui (pm-dash)"]
    BR["bridge (Fastify)<br/>:5195 dev / :8095 container"]
    WEB["web (React + Vite)"]
  end

  PUB -- ZMQ SUB --> BR
  DB -. "read-only node:sqlite" .-> BR
  BR -- "WS /ws + REST /api/*" --> WEB
```

Why this shape:

- **Beacons are pushed, not scraped.** A pull/scrape model needs every
  process to bind an HTTP port; EduMatcher processes are ZeroMQ clients that
  mostly bind nothing. A `PUSH` socket per process is one line of setup, is
  non-blocking with a high-water mark, and costs nothing when `pm-monitor` is
  down (messages are dropped at HWM, never block the sender — §7.5).
- **Counters, not events.** The engine increments plain integers on its hot
  path and ships the totals every 2 s. `pm-monitor` turns totals into rates
  by differencing (§9.4). This keeps the matching path free of any
  per-message publish and makes `pm-monitor` restart-safe: it loses at most
  one interval, never the day's totals.
- **Live over ZMQ, history from SQLite** — the same split `log-gui` already
  uses against `pm-log-srv`, so the bridge code has a working model to copy.
- **The bridge never joins the engine bus.** It only talks to `pm-monitor`.

## 7. New instrumentation: the health beacon

### 7.1 Module

New package `src/edumatcher/health/`:

```python
class HealthReporter:
    """Samples this process and PUSHes monitor.beacon every interval."""

    def __init__(self, process: str, instance: str | None = None) -> None: ...
    def start(self) -> None: ...          # starts the sampler thread
    def tick(self) -> None: ...           # main loop: "I completed an iteration"
    def publish(self, metrics: Sequence[MetricSample]) -> None: ...
                                          # main loop: latest app metrics snapshot
    def stop(self) -> None: ...           # sends a final beacon (final=True)
```

Each long-running process creates one reporter in `main()` after it has read
its configuration, calls `tick()` once per main-loop iteration, and calls
`publish()` from its main loop when `reporter.due()` says an interval has
passed. When the compiled config has no `monitor` section, `HealthReporter`
is never constructed (§14) — there is no disabled-mode code path.

### 7.2 Threading — why two halves

| Half | Runs on | Does |
|---|---|---|
| `tick()` / `publish()` | the process's **main loop** | Stores `time.monotonic()` into one float; every interval stores an immutable tuple of `MetricSample` built from the process's own counters. Never touches a socket. |
| sampler | a daemon thread | Every `beacon_interval_sec`: reads `psutil.Process()` (RSS, CPU, threads, FDs), reads the last tick time and the last published tuple, builds `monitor.beacon`, sends it on its own `PUSH` socket. |

The split exists for one reason: **if the main loop hangs, the thread keeps
reporting** — with a growing `loop_age_ms`. A beacon built on the main loop
would simply stop, and silence cannot distinguish "hung" from "dead" or from
"network partition". The thread never reads application state directly
(only the tuple the main loop hands over), so there is no locking and no
`dict changed size during iteration` risk.

### 7.3 Main-loop age and loop lag

| Field | Meaning | How |
|---|---|---|
| `loop_age_ms` | Time since the main loop last called `tick()` | `now − last_tick` at sample time |
| `loop_lag_ms` | Worst iteration duration in the interval | `tick()` records `max(now − previous_tick)` and resets it at each sample |

Placement per process kind (all verified loop shapes, §4 of the audit):

| Process kind | Loop | Where `tick()` goes |
|---|---|---|
| `pm-engine`, `pm-index`, `pm-scheduler`, `pm-market-sim` | `zmq.Poller.poll(timeout=200)` | Top of the `while self._running:` body — at least 5 ticks/s even when idle |
| `pm-stats`, `pm-audit`, `pm-clearing` | poll loop + worker thread | Main poll loop. The writer thread gets its own queue-depth gauge (§8.5) |
| `pm-alf-gwy`, `pm-balf-gwy`, `pm-md-gwy`, `pm-ralf-gwy`, `pm-dc-gwy`, `pm-log-srv` | `select`-style loop with timeout | Top of the loop |
| `pm-api-gwy` | asyncio under uvicorn | A dedicated task: `await asyncio.sleep(0.25); reporter.tick()`. `loop_lag_ms` then measures **event-loop lag** (sleep overshoot), the standard asyncio stall signal |
| `pm-mm-bot`, `pm-ai-swarm` | participant bots | Optional; included when started from an `emo` profile (they are exchange clients, not exchange processes — §12.3 shows them in a separate group) |

Short-lived CLIs (`pm-*-cli`, `pm-config-*`, `pm-setup`, `pm-help`, …) and
the TUIs (`pm-viewer`, `pm-board`, `pm-ticker`, `pm-orders`,
`pm-alf-console`) do **not** emit beacons.

### 7.4 `monitor.beacon` fields

| Field | Type | Unit | Notes |
|---|---|---|---|
| `process` | string ≤ 32 | — | Same name the process uses in its LALF `HELLO` (`CLIENT`) |
| `instance` | string ≤ 32, optional | — | e.g. `desk` / `dashboards` for `pm-api-gwy` |
| `pid` | int | — | |
| `host` | string ≤ 64 | — | `socket.gethostname()` |
| `boot_id` | string ≤ 16 | — | Random per process start; a change means restart even if PID is reused |
| `seq` | int ≥ 0 | — | Per `boot_id`; gaps = lost beacons |
| `started_at_ns` | int | epoch_nanos | Process start |
| `interval_sec` | float | seconds | The sender's beacon interval; the monitor's silence timers use it |
| `rss_bytes` | int | bytes | `memory_info().rss` |
| `cpu_pct` | float | percent of one core | `cpu_percent(None)` since previous sample |
| `threads` | int | — | `num_threads()` |
| `fds` | int, optional | — | `num_fds()` (POSIX only; absent on Windows) |
| `loop_age_ms` | float | ms | §7.3 |
| `loop_lag_ms` | float | ms | §7.3 |
| `final` | bool | — | `True` on the last beacon of a clean shutdown → status `STOPPED`, not `DEAD` |
| `metrics` | list of `MetricSample` | — | Application metrics, §8 |

`MetricSample` (a list entry, never a map — the spec family's convention):

| Field | Type | Notes |
|---|---|---|
| `name` | string ≤ 64 | Dotted, e.g. `engine.orders_in` |
| `kind` | enum `COUNTER` / `GAUGE` | Counters are monotonic since process start |
| `label` | string ≤ 32, default `""` | One dimension at most: a gateway id, a symbol, a component. Cardinality is bounded by configuration |
| `value` | float | |

### 7.5 Transport and failure behaviour

- New transports in `spec/transports.yaml`: `monitor_push` (PUSH → PULL,
  `MONITOR_PULL_ADDR`) and `monitor_pub` (PUB → SUB, `MONITOR_PUB_ADDR`).
- The sampler's `PUSH` socket: `SNDHWM = 10`, `LINGER = 0`,
  `send(..., zmq.NOBLOCK)`; on `zmq.Again` the beacon is dropped and a local
  counter increments (reported in the next beacon as
  `health.beacons_dropped`). **A down `pm-monitor` never slows or blocks any
  exchange process.**
- Wire encoding: the usual two frames `[topic, json_payload]`. At 2 s × ~15
  processes this is < 10 messages/s; JSON is fine.

## 8. New instrumentation: per-process metric catalogue

Naming: `<process-family>.<metric>`. `C` = counter (since process start),
`G` = gauge. "Label" is the single dimension.

### 8.1 Host and files — sampled by `pm-monitor` itself

| Metric | K | Label | Source |
|---|---|---|---|
| `host.cpu_pct` | G | `""` and `cpu0..N` | `psutil.cpu_percent(percpu=True)` |
| `host.load1` / `load5` / `load15` | G | | `psutil.getloadavg()` |
| `host.mem_total_bytes` / `mem_used_bytes` / `mem_available_bytes` | G | | `virtual_memory()` |
| `host.swap_used_bytes` | G | | `swap_memory()` |
| `host.disk_free_bytes` / `disk_total_bytes` | G | | `disk_usage(DATA_DIR)` |
| `files.size_bytes` | G | `log.db`, `stats.db`, `audit`, `clearing.db`, `metrics.db`, `gtc` | `os.stat` on the paths `edumatcher.config` already defines (`LOG_DB_FILE`, `STATS_DB_FILE`, `AUDIT_LOG_FILE`, …) |

Host metrics describe the host `pm-monitor` runs on. In the container
deployment that is the whole exchange; in a cross-host deployment the
per-process `rss_bytes`/`cpu_pct` remain correct per host, and the
dashboard groups processes by `host` (§12.3).

### 8.2 Engine — trading and participants

Held in a new `EngineMetrics` object (`engine/metrics.py`, plain `dict[str, int]`
counters, no locking — single-threaded engine). Increment sites are the
existing handler funnels.

| Metric | K | Label | Increment / read site |
|---|---|---|---|
| `engine.orders_in` | C | gateway | Every inbound new-order request **before** validation — what the participant *submitted* (R3, R6) |
| `engine.rejects` | C | gateway | Every reject ack (new, amend, cancel, quote) |
| `engine.cancels_in` | C | gateway | Inbound cancel requests |
| `engine.amends_in` | C | gateway | Inbound amend requests |
| `engine.quotes_in` | C | gateway | Inbound quote messages (market makers) |
| `engine.fills` | C | gateway | Fill events per participant side |
| `engine.trades` | C | symbol | Read from the existing `OrderBook.daily_trades` — no new increment |
| `engine.traded_qty` | C | symbol | Existing `OrderBook.daily_qty` |
| `engine.traded_value` | C | symbol | Existing `daily_value_ticks`, converted at the boundary like `system.volume` |
| `engine.participants_connected` | G | `""` and role | `sum(s.connected for s in self._sessions.values())` |
| `engine.participant_connected` | G | gateway | 0/1 — feeds the state timeline |
| `engine.connects` | C | gateway | `_handle_gateway_connect`, accepted |
| `engine.auth_rejects` | C | gateway | `_handle_gateway_connect`, rejected |
| `engine.disconnects` | C | gateway | `_handle_gateway_disconnect` (all reasons) |
| `engine.heartbeat_timeouts` | C | gateway | `_expire_silent_gateways` |
| `engine.resting_orders` | G | gateway | `len(book._orders_by_gateway[gw])` summed over books — the index already exists |

"Total orders" for the exchange is the sum over labels, computed by
`pm-monitor`; the engine does not keep a second unlabelled counter that could
disagree.

### 8.3 Engine — order books

Computed by the engine once every `book_metrics_interval_sec` (default 10 s),
not every beacon: all of it is O(number of books), none of it O(orders).

| Metric | K | Label | Source |
|---|---|---|---|
| `engine.books` | G | | `len(self._books)` |
| `book.resting_orders` | G | symbol | `len(book._order_index)` |
| `book.stop_orders` | G | symbol | `len(_buy_stops) + len(_sell_stops) + len(_trailing_stops)` |
| `book.bid_levels` / `book.ask_levels` | G | symbol | `len(_bid_qty)`, `len(_ask_qty)` |
| `book.heap_entries` | G | symbol | `len(_bids) + len(_asks)` — includes lazily-invalidated entries |
| `book.heap_garbage_pct` | G | symbol | `100 × (heap_entries − live entries) / heap_entries` — shows whether `_compact_heaps` is keeping up |
| `book.est_bytes` | G | symbol | `OrderBook.memory_estimate()` below |
| `book.halted` | G | symbol | 0/1 from `_halted_symbols` |

**Memory per order book (G10).** Python offers no cheap exact answer:
`sys.getsizeof` is shallow, `tracemalloc` costs 30–50 % throughput and cannot
attribute by book, and a recursive walk is O(orders). The estimate therefore
is

```
est_bytes = Σ sys.getsizeof(container)      # the 9 containers in __slots__
          + n_orders  × ORDER_BYTES          # one Order (slots dataclass) + its id strings
          + n_entries × ENTRY_BYTES          # one _HeapEntry (slots) + key tuple
          + n_trades  × TRADE_BYTES          # recent_trades deque
```

`ORDER_BYTES`, `ENTRY_BYTES` and `TRADE_BYTES` are **measured, not guessed**:
a unit test builds a book with 10 000 representative orders under
`tracemalloc`, divides, and asserts the constants in `engine/metrics.py` are
within ±15 % of the measurement — so they cannot rot silently when `Order`
gains a field. The dashboard labels the figure "est." everywhere. The sum of
all `book.est_bytes` divided by engine RSS is shown as "books share of
engine memory", which is the operationally useful number.

### 8.4 Engine — processing health

| Metric | K | Label | Source |
|---|---|---|---|
| `engine.msgs_in` | C | | Every PULL message dispatched |
| `engine.handle_us_p50` / `_p99` / `_max` | G | | Per-interval: `time.perf_counter_ns()` around the dispatch call into a fixed 1024-slot ring, percentiles computed at publish time (not per message) |
| `engine.poll_batch_max` | G | | Largest number of messages drained in one poll iteration in the interval — the only observable proxy for PULL-queue backlog, since ZeroMQ does not expose queue depth |
| `engine.diagnostics` | C | component | The existing `_error_count`, `_unknown_topic_count`, `_undecodable_count`, `_flush_error_count` — published even when zero (G17) |
| `engine.session_state` | G | | Enum ordinal of `_session_state`; `pm-monitor` maps it back to the name |
| `engine.halted_symbols` | G | | `len(_halted_symbols)` |
| `engine.gtc_flush_ms` | G | | Duration of the last GTC persistence flush |

### 8.5 Gateways and services

| Process | Metric | K | Label | Source |
|---|---|---|---|---|
| ALF / BALF gateways | `gwy.clients` | G | | `len(self._clients)` |
| | `gwy.clients_max` | G | | `config.max_connections` |
| | `gwy.logons` / `gwy.logoffs` | C | | Session open / close paths |
| | `gwy.msgs_in` / `gwy.msgs_out` | C | | Frame read / write paths |
| | `gwy.protocol_errors` | C | | `ERR` frames sent |
| `pm-md-gwy` | `md.clients` / `md.clients_max` | G | | `len(self._clients)`, `max_connections` |
| | `md.msgs_out` | C | | Fan-out send path |
| | `md.slow_consumer_drops` | C | | Fan-out back-pressure path |
| `pm-ralf-gwy`, `pm-dc-gwy` | `gwy.clients`, `gwy.msgs_out` | G / C | | As above |
| `pm-api-gwy` | `api.ws_sessions` | G | channel | Count of open WebSockets per router (`events`, `market-data`, `admin/monitor`, `admin/sim`) |
| | `api.http_requests` / `api.http_5xx` | C | | A one-line Starlette middleware |
| | `api.dropped_events` | C | | The existing `engine.dropped_events` |
| | `api.engine_timeouts` | C | | `TimeoutError` in `await_topic` |
| `pm-log-srv` | `log.events_in` | C | | Existing `total_log_events` path |
| | `log.sessions` | G | | Authenticated LALF sessions |
| | `log.writer_queue` | G | | Writer thread queue depth |
| | `log.ps_subscriptions` | G | | LALF-PS leases |
| `pm-stats` | `stats.events_recorded` | C | | Writer path |
| | `stats.writer_queue` | G | | Writer thread queue depth |
| | `stats.feed_gaps` | C | | Same place that inserts into `feed_gaps` |
| `pm-audit` | `audit.records` / `audit.bytes` | C | | Writer path |
| `pm-clearing` | `clearing.trades_settled` | C | | Settlement path |
| `pm-scheduler` | `sched.next_transition_in_s` | G | | Seconds until next scheduled transition |

### 8.6 Every process — supplied by `HealthReporter`

`health.beacons_dropped` (C), `health.gc_gen2` (C, `gc.get_stats()[2]["collections"]`
— long gen-2 pauses show up as `loop_lag_ms` spikes, and this shows why).

## 9. `pm-monitor` — the collector

### 9.1 Process shape

Single-threaded `zmq.Poller` loop (the EduMatcher norm), plus the
`HealthReporter` for itself — `pm-monitor` monitors its own memory and loop
like everyone else. Entry point `pm-monitor = "edumatcher.monitor.main:main"`;
it logs through the normal LALF client.

Loop, 200 ms tick:

1. Drain `PULL :5610` → update per-`(process, instance, host)` state.
2. Drain `SUB` on the engine PUB → lifecycle events (§9.2).
3. Every 1 s: sample host (§8.1), evaluate health (§10) and thresholds
   (§9.6), publish `monitor.snapshot`.
4. Every 10 s: write raw samples batch to `metrics.db`.
5. Every 60 s: roll raw → 1-minute buckets; every 60 min: apply retention.

### 9.2 Engine bus subscriptions (events only)

| Topic prefix | Becomes `monitor.event` kind |
|---|---|
| `system.gateway_auth.` | `CONNECT` / `AUTH_REJECT` (with reason) |
| `system.gateway_bye.` | `DISCONNECT` (with reason — `heartbeat_timeout` is highlighted) |
| `system.diagnostic` | `DIAGNOSTIC` |
| session status broadcast | `SESSION` (state transition) |
| `circuit_breaker.halt.` / `.resume.` | `HALT` / `RESUME` |

Plus internally generated: `PROCESS_STATUS` (every health-state change of a
process, §10), `THRESHOLD` (breach / clear). These are the dashboard's
annotations and its event log.

### 9.3 Expected roster

At start and when the file changes, `pm-monitor` reads
`<DATA>/emo/active-profile` and the matching profile (built-in or
`emo-config.yaml`) through `edumatcher.emo.cli.load_profiles()` — the same
function `pm-opctl-cli` uses. A process in the profile that has never sent a
beacon is `MISSING`. Without an active profile (processes started by hand)
the roster is "whatever has beaconed", and nothing is `MISSING`.

The mapping profile-entry → beacon is by the first word of `command`
(`pm-api-gwy`) plus `--instance` when present — the same rule
`matches_command` already applies.

### 9.4 Rates — what "avg per min / hour / day" means

For a counter `c` with samples `(t_i, v_i)`:

- **Increment** `Δ_i = v_i − v_{i−1}`; if `v_i < v_{i−1}` the process
  restarted (or `boot_id` changed) and `Δ_i = v_i`. This is what lets
  "orders today" survive an engine restart.
- **Total today** = Σ Δ since the start of the trading day in the exchange's
  `session_timezone` (the same rule `pm-stats` uses).
- **Rate now** (`/s`, `/min`) = Σ Δ over the last 60 s ÷ 60 (× 60).
- **Avg per minute** = Σ Δ over the last 60 min ÷ 60.
- **Avg per hour** = total today ÷ hours elapsed since the session opened
  (first `SESSION` transition out of `CLOSED` today, else midnight).
- **Avg per day** = mean of `daily_totals` over the last 7 trading days that
  have data.

All four are computed in `pm-monitor` and shipped in `monitor.snapshot`, so the
browser never re-derives them and every client agrees.

### 9.5 `metrics.db`

SQLite, WAL mode, same conventions as `stats.db`/`log.db` (UTC ISO-8601
`ts`, append-only tables, `(filter, ts)` indexes).

```sql
CREATE TABLE samples_raw (          -- retention: monitor.retention.raw_hours (24)
    ts      TEXT NOT NULL,
    source  TEXT NOT NULL,          -- "process/instance@host" or "host"
    name    TEXT NOT NULL,
    label   TEXT NOT NULL DEFAULT '',
    value   REAL NOT NULL
);
CREATE INDEX idx_raw ON samples_raw(name, label, ts);

CREATE TABLE samples_1m (           -- retention: monitor.retention.minute_days (7)
    ts      TEXT NOT NULL,          -- bucket start
    source  TEXT NOT NULL,
    name    TEXT NOT NULL,
    label   TEXT NOT NULL DEFAULT '',
    v_min   REAL, v_avg REAL, v_max REAL, v_last REAL,
    delta   REAL,                   -- counters: reset-corrected increment in the bucket
    PRIMARY KEY (name, label, source, ts)
);

CREATE TABLE daily_totals (         -- kept indefinitely (tiny)
    date    TEXT NOT NULL,          -- trading date in session_timezone
    name    TEXT NOT NULL,
    label   TEXT NOT NULL DEFAULT '',
    total   REAL NOT NULL,
    PRIMARY KEY (date, name, label)
);

CREATE TABLE events (               -- retention: minute_days
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    kind    TEXT NOT NULL,
    subject TEXT NOT NULL,          -- gateway id, process key, symbol
    detail  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_ev_ts ON events(ts);
```

Size check: ~15 processes × ~25 series + per-symbol/per-gateway series
(≈ 20 symbols × 8 + 30 participants × 9) ≈ 800 series. Raw at 2 s for 24 h
≈ 35 M rows — too many. Therefore **raw is written at 10 s resolution**
(the last value per series per 10 s; `pm-monitor` keeps full 2 s resolution
in memory for the last 15 minutes) → ≈ 7 M rows/day, ~350 MB. That is still
large for an educational install, so the default `raw_hours` is **6**
(≈ 90 MB) and 1-minute buckets cover the rest (≈ 8 M rows / 7 days,
~400 MB). These numbers are estimates to confirm in WP-B4 (§19, Q3).

### 9.6 Thresholds

Static, from configuration (§14), evaluated every second in `pm-monitor`:

| Rule (default) | Warn | Critical |
|---|---|---|
| Host CPU | 80 % | 95 % |
| Host memory used | 80 % | 92 % |
| Disk free on data dir | < 15 % | < 5 % |
| Process `loop_age_ms` | > 1 000 | > `hung_after_sec` (5 s) → HUNG |
| Engine `handle_us_p99` | > 2 000 µs | > 10 000 µs |
| Process RSS growth | > 50 % over 1 h | > 100 % over 1 h |
| Reject ratio (exchange) | > 10 % / 5 min | > 30 % / 5 min |
| `book.heap_garbage_pct` | > 50 % | > 80 % |
| `md.slow_consumer_drops`, `api.dropped_events`, `stats.feed_gaps` | any increase in 5 min | — |

A breach or clear produces a `THRESHOLD` event and a single `WARNING` /
`ERROR` log line through LALF (`"threshold engine.handle_us_p99 CRIT 12345 > 10000"`),
so `log-gui` alerting already covers notification. No second alerting system.

## 10. Health model — healthy, degraded, hung, dead

Evaluated per process every second in `pm-monitor`:

| State | Colour | Condition (first match wins) |
|---|---|---|
| `STOPPED` | grey | Last beacon had `final=True` |
| `MISSING` | dark red | In the active profile, never beaconed since `pm-monitor` started |
| `DEAD` | red | No beacon for `silent_after × interval_sec` **and** (same host) `psutil.pid_exists(pid)` is false, or (other host) no beacon for 2 × that |
| `SILENT` | red | No beacon for `silent_after × interval_sec`, PID still exists — the whole interpreter is stuck (e.g. a C extension holding the GIL) or the PUSH path is broken |
| `HUNG` | magenta | Beacons arrive but `loop_age_ms > hung_after_sec × 1000` — the sampler thread runs, the main loop does not |
| `DEGRADED` | amber | Any warn/critical threshold on this process, or `loop_lag_ms > 1000` |
| `HEALTHY` | green | Otherwise |
| `RESTARTED` (overlay) | blue badge | `boot_id` changed in the last 10 min |

`HUNG` vs `SILENT` vs `DEAD` is the main improvement over today: three
different failures that currently all look like either "running" or "✗".

Exchange-level status (the big tile in the top bar): `DOWN` if `pm-engine`
is `DEAD`/`SILENT`/`HUNG`/`MISSING`; `IMPAIRED` if any other expected process
is; `DEGRADED` if anything is `DEGRADED`; else `OPERATIONAL`.

## 11. Bridge ↔ browser protocol

The bridge holds one ZMQ `SUB` to `pm-monitor :5611` and one read-only
`node:sqlite` handle on `metrics.db`, regardless of browser count (the
`log-gui` pattern).

### 11.1 WebSocket `/ws`

```ts
type ServerMsg =
  | { type: "hello"; version: string; monitor: "UP" | "DOWN"; sessionTz: string }
  | { type: "snapshot"; data: MonitorSnapshot }       // on connect + 1 Hz
  | { type: "event"; data: MonitorEvent }             // as they happen
  | { type: "monitor_state"; monitor: "UP" | "DOWN" }; // no snapshot for 3 s

interface MonitorSnapshot {
  ts: string;
  exchange: { status: "OPERATIONAL" | "DEGRADED" | "IMPAIRED" | "DOWN";
              sessionState: string; tradingDate: string };
  host: { cpuPct: number; cpuPerCore: number[]; load: [number, number, number];
          memTotal: number; memUsed: number; swapUsed: number;
          diskFree: number; diskTotal: number; files: Record<string, number> };
  processes: ProcessHealth[];
  trading: { ordersToday: number; ordersPerSecNow: number;
             ordersAvgPerMin: number; ordersAvgPerHour: number; ordersAvgPerDay: number | null;
             tradesToday: number; tradesPerSecNow: number; /* same avgs */
             tradedValueToday: number; rejectPct5m: number;
             handleP50Us: number; handleP99Us: number };
  participants: ParticipantStats[];
  books: BookStats[];
  gateways: GatewayStats[];
  thresholds: ActiveBreach[];
}

interface ProcessHealth {
  key: string; process: string; instance: string | null; host: string; pid: number;
  state: "HEALTHY" | "DEGRADED" | "HUNG" | "SILENT" | "DEAD" | "MISSING" | "STOPPED";
  restartedRecently: boolean; uptimeSec: number;
  rssBytes: number; cpuPct: number; threads: number; fds: number | null;
  loopAgeMs: number; loopLagMs: number; lastBeaconAgeMs: number;
  spark: { rss: number[]; cpu: number[] };   // last 60 samples, for inline sparklines
}

interface ParticipantStats {
  id: string; role: string; connected: boolean; connectedSince: string | null;
  ordersToday: number; ordersPerMinNow: number; ordersAvgPerMin: number;
  ordersAvgPerHour: number; ordersAvgPerDay: number | null;
  rejectPct: number; fillsToday: number; restingOrders: number;
  connectsToday: number; disconnectsToday: number; heartbeatTimeoutsToday: number;
}

interface BookStats {
  symbol: string; restingOrders: number; stopOrders: number;
  bidLevels: number; askLevels: number; estBytes: number;
  heapGarbagePct: number; tradesToday: number; halted: boolean;
}
```

The snapshot is ~20–60 KB at 30 participants and 20 symbols; 1 Hz is fine
on a LAN. Sparkline arrays are only included for processes.

### 11.2 REST (history)

| Endpoint | Returns |
|---|---|
| `GET /api/series?name=&label=&source=&from=&to=` | `{ points: [ts, v][] }` — picks `samples_raw` or `samples_1m` by range (≤ `raw_hours` → raw), at most 1 000 points (server-side bucketing) |
| `GET /api/series/multi?name=&labels=a,b,c&from=&to=` | Several labels of one metric, for stacked charts |
| `GET /api/rate?name=&label=&from=&to=&bucket=1m\|1h` | Counter increments per bucket (from `delta`) — the "orders per minute" chart |
| `GET /api/daily?name=&label=&days=30` | `daily_totals` rows |
| `GET /api/events?from=&to=&kind=` | Event log / annotations |
| `GET /api/bridge/status` | Bridge's own state: monitor uplink, DB path, version |

Ranges: `5m`, `15m`, `1h`, `6h`, `24h`, `7d` — the Grafana time picker set.

## 12. Screen design

### 12.1 Layout principles (from Grafana)

- **Rows of panels** in a 24-column grid, each row collapsible and
  remembered per browser (`localStorage`, try/catch).
- **Status first**: the top row answers "is the exchange OK?" in under a
  second from across the room.
- **Every number has a context**: a sparkline, a threshold colour, or a
  delta.
- **Shared time range and crosshair**: one time picker drives every chart;
  hovering a chart draws the same vertical line on all charts in view.
- **Annotations**: events (§9.2) appear as thin vertical markers on every
  time-series chart, coloured by kind, with a tooltip.

### 12.2 Top bar

```
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ ▣ EduMatcher Operator v0.1.0 │ ● OPERATIONAL │ CONTINUOUS · 2026-10-11 │ ⏱ Last 1h ▾ │ ⟳ 1s ▾ │ ☾ │ ⚙ │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

`TopBar.tsx` follows `book-gui`: wordmark with the application name in the
orange `--accent`, green `--brand-version`. The status pill takes the
exchange status colour. A red banner appears under the bar when the bridge
or `pm-monitor` is unreachable ("pm-monitor down — data frozen at 11:42:05"),
and all panels dim.

### 12.3 Rows

```
Row 1 — OVERVIEW
┌──────────────┬──────────────┬──────────────┬──────────────┬──────────────┬──────────────┐
│ PROCESSES    │ PARTICIPANTS │ ORDERS TODAY │ TRADES TODAY │ ORDERS / s   │ ENGINE p99   │
│  14 / 15     │   23 / 30    │   184 302    │    41 776    │    212.4     │   640 µs     │
│ 1 DEGRADED   │ ▁▂▃▅▆▆▇ conn │ ~3 071 /min  │ ~696 /min    │ ▁▃▅▇▆▅▆▇█▆   │ ▂▂▃▂▂▅▂▂▂▂   │
├──────────────┴───┬──────────┴───────┬──────┴───────────┬──┴──────────────┴──────────────┤
│   ╭─────╮        │   ╭─────╮        │   ╭─────╮        │ EXCHANGE MEMORY (stacked area  │
│  ╱  62% ╲  CPU   │  ╱  71% ╲  MEM   │  ╱  38% ╲  DISK  │ by process, last 1h)           │
│  ‾‾‾‾‾‾‾  host   │  ‾‾‾‾‾‾‾  11.3G  │  ‾‾‾‾‾‾‾  used   │ ▁▁▂▂▂▃▃▃▃▃▄▄▄▄▄▄▄▄▄▄           │
└──────────────────┴──────────────────┴──────────────────┴────────────────────────────────┘

Row 2 — PROCESSES
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ ● pm-engine        HEALTHY   up 05:12  RSS 412 MB ▁▂▂▃▃  CPU 38% ▃▅▄▆▅  loop 3ms  lag 41ms │
│ ● pm-api-gwy/desk  HEALTHY   up 05:12  RSS 118 MB ▁▁▁▁▂  CPU  6% ▁▂▁▁▂  loop 0ms  lag 12ms │
│ ◐ pm-stats         DEGRADED  up 05:12  RSS 96 MB  ▁▁▁▁▁  CPU 71% ▅▆▇▇█  writer queue 4 112  │
│ ◆ pm-clearing      HUNG      up 05:12  RSS 88 MB           CPU  0%      loop 14.2 s ⚠      │
│ ✕ pm-index         MISSING   (in profile "default", never seen)                            │
│ ── Participant bots ───────────────────────────────────────────────────────────────────── │
│ ● pm-mm-bot        HEALTHY   …                                                             │
├───────────────────────────────────────────┬───────────────────────────────────────────────┤
│ MEMORY PER PROCESS (bar gauge, sorted)    │ CPU PER PROCESS (lines, last range)           │
│ pm-engine     ███████████████████ 412 MB  │                                               │
│ pm-api-gwy    █████ 118 MB                │                                               │
│ pm-stats      ████ 96 MB                  │                                               │
└───────────────────────────────────────────┴───────────────────────────────────────────────┘

Row 3 — TRADING ACTIVITY
┌───────────────────────────────────────────┬───────────────────────────────────────────────┐
│ ORDERS / min (stacked bars, top 8          │ TRADES / min + TRADED VALUE (dual axis)       │
│ participants + "other")                    │                                               │
├─────────────┬─────────────┬───────────────┼───────────────────────────────────────────────┤
│ avg / min   │ avg / hour  │ avg / day (7d)│ REJECT RATIO % (line, threshold bands)         │
│   3 071     │  184 260    │   1.21 M      │                                               │
└─────────────┴─────────────┴───────────────┴───────────────────────────────────────────────┘

Row 4 — PARTICIPANTS
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ STATE TIMELINE (one lane per participant, green = connected, red tick = heartbeat timeout) │
│ MM-01   ████████████████████████████████████████████                                      │
│ TR-07   ████████  ██████████▌ ████████████████████                                        │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ ID     Role  Conn  Since  Orders today  /min now  avg/min  avg/h   avg/d  Rej%  Rest  C/D/HB│
│ MM-01  MM    ●     08:58  61 220        ▅ 212     201      12 060  …      0.3   40    1/0/0 │
│ TR-07  TRD   ●     10:41  1 804         ▂ 12      9        540     …      14.2▲ 6     3/2/1 │
└───────────────────────────────────────────────────────────────────────────────────────────┘

Row 5 — ORDER BOOKS
┌──────────────────┬────────────────────────────────────────────────────────────────────────┐
│ BOOKS   20       │ Symbol Resting Stops BidLv AskLv  Est. mem   Heap garbage  Trades  State │
│ BOOK MEM ≈ 61 MB │ AAA    1 204   12    84    91     4.1 MB ▇   12 %  ▂       8 102   ●    │
│ (15 % of engine) │ BBB    88      0     12    14     0.3 MB ▁   71 %  ▇ ⚠     214     HALT │
└──────────────────┴────────────────────────────────────────────────────────────────────────┘

Row 6 — GATEWAYS & INFRASTRUCTURE
┌─────────────────────┬─────────────────────┬─────────────────────┬─────────────────────────┐
│ ALF clients  ◔ 12/64│ MD clients  ◔ 31/256│ API WS sessions  9  │ Log ingest  412 ev/s ▃▅ │
│ BALF clients ◔ 3/64 │ MD drops  0         │ API dropped evts 0  │ Feed gaps today  0      │
├─────────────────────┴─────────────────────┴─────────────────────┴─────────────────────────┤
│ DATA FILES (bar gauge): log.db 1.2 GB · stats.db 340 MB · audit 820 MB · metrics.db 110 MB │
│ ENGINE DIAGNOSTICS: MAINTENANCE_FLUSH 0 · DISPATCH_ERROR 0 · UNDECODABLE 0 · UNROUTED 2   │
└───────────────────────────────────────────────────────────────────────────────────────────┘

Row 7 — EVENT LOG (newest first; filter by kind)
11:42:05  DISCONNECT   TR-07  heartbeat_timeout
11:30:00  SESSION      CONTINUOUS → CLOSING_AUCTION
11:12:44  PROCESS      pm-clearing  HEALTHY → HUNG
```

Interactions:

- Clicking a process row opens a **detail drawer**: RSS / CPU / threads /
  FDs / loop age / loop lag charts plus its application metrics, and a
  "open in log-gui" link (`log-gui` URL configurable, filtered by process).
- Clicking a participant opens its drawer: orders/min, rejects, fills,
  resting orders and its connect/disconnect events.
- Clicking a symbol opens its drawer plus an "open in book-gui" link.
- Any stat tile or gauge: hover shows the threshold definition.

### 12.4 Routes

`/` (all rows), `/process/:key`, `/participant/:id`, `/book/:symbol` — the
drawers are also deep-linkable for sharing a URL in an incident. The time
range is a query parameter (`?from=now-1h`), as in Grafana.

### 12.5 Theme and colours

Same mechanism as `book-gui` and `log-gui`: CSS variables swapped by a
`.dark` class on `<html>`, dark by default, toggle in the top bar, font-size
scaling (XS…XXL) via the shared `useFontSizeStore` pattern.

Base tokens (`--bg`, `--bg-subtle`, `--bg-raised`, `--border`, `--fg`,
`--fg-subtle`, `--accent`, `--brand-version`) are copied from `book-gui`
unchanged so the apps look like one family.

**Deliberate difference.** `book-gui` reserves green/red for price direction
only. This app shows no prices, so green/amber/red mean **health**, which is
the operator convention and Grafana's. New tokens:

| Token | Dark | Light | Used for |
|---|---|---|---|
| `--ok` | `#73bf69` | `#1a7f37` | HEALTHY, below warn |
| `--warn` | `#f2cc0c` | `#9a6700` | DEGRADED, warn band |
| `--crit` | `#f2495c` | `#c8102e` | DEAD / SILENT / critical band |
| `--hung` | `#b877d9` | `#8250df` | HUNG (distinct from dead on purpose) |
| `--missing` | `#8f3b47` | `#82071e` | MISSING |
| `--stopped` | `#7b8394` | `#808b9c` | STOPPED, no data |
| `--info` | `#5794f2` | `#0b5fce` | RESTARTED badge, session annotations |
| `--series-1 … --series-8` | Grafana classic palette: `#7eb26d #eab839 #6ed0e0 #ef843c #e24d42 #1f78c1 #ba43a9 #705da0` | darkened variants with ≥ 4.5:1 contrast on white | Categorical series (processes, participants) |

State is never shown by colour alone: every state also has a glyph
(`● ◐ ◆ ✕ ○`) and a text label, for colour-blind operators and for
screenshots pasted into incident notes.

## 13. Widget library

All in `apps/web/src/components/widgets/`. Time-series and bar widgets wrap
`recharts` (already a dependency of `log-gui` and `trader-gui`, same major
version `^2.15.0`). Gauge and state timeline are hand-written SVG: `recharts`
has no gauge, and adding Apache ECharts only for one widget type would put a
second chart library in the family.

| Widget | Implementation | Props (essentials) |
|---|---|---|
| `Gauge` | SVG, ~120 lines. 240° arc; background track; coloured threshold bands (`ok`/`warn`/`crit`); needle or filled arc (setting); big value in the centre; unit and min/max labels | `value, min, max, thresholds: {warn, crit}, unit, label, invert?` (`invert` for "disk free", where low is bad) |
| `StatTile` | div + inline SVG sparkline | `value, unit, label, spark?: number[], sub?: string, thresholds?, colorMode: "value" \| "background"` (Grafana's two stat modes) |
| `TimeSeries` | `recharts` `LineChart` / `AreaChart` (stacked) | `series[], range, annotations[], thresholds?, unit, stacked?` — draws threshold lines/bands and annotation markers via `ReferenceLine` / `ReferenceArea` |
| `RateBars` | `recharts` `BarChart` stacked | `buckets[], series[]` — orders/min by participant |
| `BarGauge` | CSS grid of horizontal bars, gradient by threshold | `items: {label, value}[], max, unit, thresholds?` |
| `StateTimeline` | SVG lanes | `lanes: {id, segments: {from, to, state}[], marks: {ts, kind}[]}[]` |
| `HealthTable` | Plain table + inline sparkline + state glyph | Process and participant tables |
| `EventLog` | Virtualised list | `events[]` |
| `Row` | Collapsible section header with a count badge (e.g. "PROCESSES · 1 degraded") | |

Shared hook `useCrosshair()` (zustand) broadcasts the hovered timestamp so
every `TimeSeries` draws the same `ReferenceLine`.

Formatting helpers: bytes (`KiB/MiB/GiB`, binary), rates (`/s`, `/min`),
µs/ms auto-scaling, durations `HH:MM`, and large counts with thin-space
grouping — one `lib/format.ts`, unit-tested.

## 14. Configuration

New optional top-level section in the authored `engine_config.yaml`,
compiled into the artifact like every other section (and therefore part of
the config digest — see the project note on schema changes invalidating
deployed artifacts):

```yaml
monitor:
  bind_address: 127.0.0.1     # pm-monitor PULL/PUB bind; processes connect to monitor_host
  host: 127.0.0.1             # where processes send beacons
  pull_port: 5610
  pub_port: 5611
  beacon_interval_sec: 2
  hung_after_sec: 5
  silent_after_beacons: 3
  book_metrics_interval_sec: 10
  retention:
    raw_hours: 6
    minute_days: 7
  thresholds:                 # every key optional; defaults in §9.6
    host_cpu_pct: { warn: 80, crit: 95 }
    host_mem_pct: { warn: 80, crit: 92 }
    disk_free_pct: { warn: 15, crit: 5 }
    engine_handle_p99_us: { warn: 2000, crit: 10000 }
    reject_pct_5m: { warn: 10, crit: 30 }
    rss_growth_pct_1h: { warn: 50, crit: 100 }
    heap_garbage_pct: { warn: 50, crit: 80 }
```

- **Absent section ⇒ no monitoring.** No process constructs a
  `HealthReporter`, `pm-monitor` refuses to start with a clear error. There
  is no "enabled: false" flag — absence is the switch.
- Validation: `cverifier` layer 2 schema + layer 3 semantics
  (`warn` < `crit`, except `disk_free_pct` where `warn` > `crit`;
  `hung_after_sec > beacon_interval_sec`; ports not colliding with
  `gateway_ports.py`). `pm-config-show` gets a MONITORING panel;
  `config-gui` support is a follow-up (§19.3).
- `gateway_ports.py` gains the two listeners so `pm-config-show` and the
  port-collision checks know them.
- All bundled examples under `docs/examples/` get a `monitor:` section, so
  the default stack is monitored.

Bridge environment (`apps/bridge/src/config.ts`), mirroring `log-gui`:

| Variable | Default | |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `5195` (dev), `8095` (container) | |
| `MONITOR_HOST` | `127.0.0.1` | `edumatcher` in compose |
| `MONITOR_PUB_PORT` | `5611` | |
| `METRICS_DB_PATH` | `$EDUMATCHER_DATA_DIR/metrics.db` | `/backend-data/metrics.db` in compose (read-only mount) |
| `LOG_GUI_URL` / `BOOK_GUI_URL` | unset | Enables the cross-app links |
| `CORS_ORIGIN` | `*` | |

## 15. Container, Makefile, ports and versioning

### 15.1 Ports

Following the `web-apps/README.md` numbering scheme with **N = 5**:

| What | Port |
|---|---|
| Container web | `8095` |
| Dev web (Vite) | `8195` |
| Dev bridge | `5195` |
| `pm-monitor` PULL / PUB | `5610` / `5611` |

All verified unused in `src/`, `deployment/` and `web-apps/` on 2026-10-11.

### 15.2 Packaging

- `web-apps/dash-gui/` is a copy of `book-gui`'s skeleton: npm workspaces,
  `Dockerfile`, `docker-compose.yml` + `docker-compose.linux.yml`,
  `Makefile` with the same target names (`install build typecheck test lint
  dev dev-web dev-bridge cbuild up down restart logs ps cdist ghcr-*`),
  `TopBar.tsx` reading `version.json`. `APP_NAME := edumatcher-dash-gui`,
  `SERVICE_NAME := dash-gui`, `WEB_PORT ?= 8095`.
- No API key plumbing (unlike `book-gui`), since `pm-monitor` needs none.
- The bridge binds `127.0.0.1` by default; compose publishes it as
  `${BIND_ADDR:-127.0.0.1}:8095`, like every other GUI.
- `deployment/docker/compose.guis.yaml`: new `dash-gui` service
  (`MONITOR_HOST: edumatcher`, `./data` read-only at `/backend-data`).
- `deployment/docker/entrypoint.sh` and `emo` built-in profiles: start
  `pm-monitor` right after `pm-log-srv` (so it is up before the engine and
  sees the engine's first beacon), with `tcp: "127.0.0.1:5610"`. Added to
  `default` and `mini`; not to `micro`.
- `entrypoint.sh:open_gateway_binds()` must include `monitor.bind_address`
  so the bridge container can reach it (the loopback-bind trap).
- `web-apps/Makefile`: `up-dash` / `down-dash` / `logs-dash`, and the app in
  `up`/`down`.
- `web-apps/README.md`: new row in the app table and the dependency table.
- GHCR publishing workflow: the sixth image (follow-up, as for `book-gui`).
- `pyproject.toml`: `psutil` under `[tool.poetry.dependencies]`;
  `pm-monitor` under `[tool.poetry.scripts]`.

## 16. Repository layout

```
src/edumatcher/
  health/
    __init__.py
    reporter.py          HealthReporter (§7)
    samples.py           MetricSample helpers, counter registry
  monitor/
    __init__.py
    main.py              pm-monitor entry point, poll loop (§9.1)
    config.py            monitor section loader
    state.py             per-process state, health evaluation (§10)
    rates.py             counter → increment/rate/avg (§9.4)
    host.py              psutil host sampler (§8.1)
    roster.py            expected processes from emo profile (§9.3)
    thresholds.py        §9.6
    store.py             metrics.db schema, writer, downsampling, retention (§9.5)
  engine/
    metrics.py           EngineMetrics + OrderBook memory constants (§8.2–§8.4)
spec/messages/monitor.yaml
spec/transports.yaml      + monitor_push, monitor_pub

web-apps/dash-gui/
  apps/
    bridge/src/
      config.ts
      main.ts
      server.ts           Fastify: /ws, /api/*, static
      monitor-uplink.ts   ZMQ SUB to pm-monitor, UP/DOWN state
      metrics-db.ts       read-only node:sqlite queries (§11.2)
      ws-fanout.ts
      logging/logger.ts
    web/src/
      App.tsx, main.tsx, index.css, version.json
      components/layout/  AppShell.tsx TopBar.tsx StatusStrip.tsx TimePicker.tsx
      components/widgets/ Gauge.tsx StatTile.tsx TimeSeries.tsx RateBars.tsx
                          BarGauge.tsx StateTimeline.tsx HealthTable.tsx EventLog.tsx Row.tsx
      components/shared/  SettingsPopover.tsx Drawer.tsx
      views/              DashboardView.tsx ProcessDrawer.tsx ParticipantDrawer.tsx BookDrawer.tsx
      store/              useDashStore.ts useFontSizeStore.ts usePrefsStore.ts useCrosshair.ts
      lib/                format.ts ws.ts api.ts thresholds.ts
  packages/dash-types/src/ index.ts ws.ts
  Dockerfile  docker-compose.yml  docker-compose.linux.yml  Makefile  README.md
```

## 17. Test strategy

| Layer | Tests |
|---|---|
| `health` | Reporter sends at interval; `loop_age_ms` grows when `tick()` stops while beacons keep coming (the hung case); `final=True` on stop; HWM drop path never blocks (no monitor bound) |
| Engine metrics | Each counter increments exactly once per handler path, including reject paths; `participants_connected` matches `system.gateways`; trade counters equal `system.volume`; book gauges on a scripted book; **memory constants within ±15 % of a `tracemalloc` measurement** (§8.3); perf: `test_max_tps` must not regress more than 2 % with metrics on |
| `pm-monitor` | Rates with counter resets and `boot_id` change; trading-day boundary in `session_timezone`; every health state of §10 from synthetic beacon streams (incl. HUNG vs SILENT vs DEAD); MISSING from an emo profile; threshold breach → event + log line; downsampling and retention; reads its own beacon |
| Bridge | Uplink UP/DOWN transitions; `/api/series` picks raw vs 1m by range and caps points; DB opened read-only (write attempt fails) |
| Web | `Gauge` geometry and threshold colouring incl. `invert`; `StatTile` modes; format helpers; snapshot → store; theme toggle swaps tokens; vitest + Testing Library, as `book-gui` |
| End to end | `make up-all` in `deployment/docker`; kill `-STOP` the clearing process → dashboard shows `SILENT`; inject a sleep in a test hook of `pm-stats`' main loop → `HUNG`; stop `pm-monitor` → banner, then recovery |

Python changes verified with black, flake8, mypy, pyright (project rule).

## 18. Implementation plan — work packages

| WP | Content | Depends on | Est. |
|---|---|---|---|
| **Phase A — instrumentation** | | | |
| A1 | `spec/messages/monitor.yaml`, transports, `pm-msgen` generation | — | 0.5 d |
| A2 | `edumatcher.health` (`HealthReporter`), `psutil` dependency, unit tests | A1 | 1 d |
| A3 | `monitor:` config section: compiled artifact, cverifier L2/L3, `pm-config-show`, `gateway_ports.py`, examples | — | 1 d |
| A4 | Engine: `EngineMetrics`, counters §8.2, book gauges + memory estimate §8.3, processing metrics §8.4, perf check | A2 | 2 d |
| A5 | Gateways (ALF, BALF, MD, RALF, DC, API) metrics §8.5 + reporter wiring | A2 | 1.5 d |
| A6 | Services (log-srv, stats, audit, clearing, scheduler, index, market-sim) metrics + reporter wiring | A2 | 1 d |
| **Phase B — collector** | | | |
| B1 | `pm-monitor` skeleton: loop, PULL, own reporter, process state, PUB snapshot | A1–A3 | 1 d |
| B2 | Health model §10, emo roster §9.3 | B1 | 1 d |
| B3 | Rates §9.4, engine-bus events §9.2, thresholds §9.6 | B1 | 1.5 d |
| B4 | `metrics.db` store, downsampling, retention, size measurement (Q3) | B3 | 1 d |
| B5 | `emo` profiles, `entrypoint.sh`, bind fix | B1 | 0.5 d |
| **Phase C — bridge** | | | |
| C1 | Scaffold `web-apps/dash-gui` from `book-gui`; types package; Makefile/Dockerfile/compose | — | 0.5 d |
| C2 | `monitor-uplink.ts`, `/ws` fan-out, `metrics-db.ts`, REST §11.2 | B1, B4, C1 | 1.5 d |
| **Phase D — web** | | | |
| D1 | App shell, TopBar, time picker, theme tokens §12.5, settings | C1 | 1 d |
| D2 | Widgets §13 (Gauge, StatTile, TimeSeries+annotations+crosshair, RateBars, BarGauge, StateTimeline) | D1 | 2.5 d |
| D3 | Rows 1–7 §12.3 | C2, D2 | 2 d |
| D4 | Drawers + routes §12.4 | D3 | 1 d |
| **Phase E — integration and docs** | | | |
| E1 | `compose.guis.yaml`, `web-apps/Makefile`, `web-apps/README.md` | C1, B5 | 0.5 d |
| E2 | Operator guide chapter ("Observe and recover" part): reading the dashboard, health states, thresholds | D4 | 1 d |
| E3 | End-to-end scenarios §17 | all | 1 d |
| | **Total** | | **≈ 27 d** |

Phase A is valuable on its own: once beacons exist, `pm-opctl-cli list`
could show HUNG too (not in scope here, noted as a follow-up).

## 19. Risks and open questions

### 19.1 Risks

| # | Risk | Mitigation |
|---|---|---|
| K1 | Counter increments on the engine hot path cost throughput | Plain `dict[str,int]` `+=` keyed by already-interned gateway ids; latency ring writes one int; percentiles computed once per interval. Gate on `test_max_tps` (≤ 2 % regression) in A4 |
| K2 | `psutil` sampling in a thread contends for the GIL | One sample every 2 s, ~50 µs; negligible. `cpu_percent(None)` is non-blocking |
| K3 | Book memory estimate is wrong | Measured constants with a guard test (§8.3); labelled "est." in the UI |
| K4 | Label cardinality explodes (participants × metrics) | Labels are only configured gateways and symbols — bounded by config. `pm-monitor` rejects samples whose label is unknown to the compiled config and counts them (`monitor.rejected_samples`) |
| K5 | `metrics.db` grows large | 10 s raw resolution, short raw retention, measured in B4 |
| K6 | Clock skew between hosts | `pm-monitor` stamps samples with its **receive** time; sender `started_at_ns` only used for uptime |
| K7 | The loopback-bind trap hides `pm-monitor` from the bridge container | `open_gateway_binds()` covers `monitor.bind_address` (B5); verified via the compiled artifact, not the YAML |
| K8 | A process that never calls `tick()` (missed wiring) shows as HUNG forever | Every reporter-wired process is in an integration test that asserts `HEALTHY` within 10 s of start |

### 19.2 Open questions

| # | Question | Proposed answer |
|---|---|---|
| Q1 | App name: `pm-dash` / `dash-gui`, or `pm-ops` / `ops-gui`? | `pm-dash` / `dash-gui` |
| Q2 | Should participant bots (`pm-mm-bot`, `pm-ai-swarm`) beacon? They are clients, possibly on a student's machine | Yes when started from an `emo` profile; shown in their own group, never counted in exchange status |
| Q3 | Default retention (`raw_hours: 6`, `minute_days: 7`) | Confirm after measuring in B4 |
| Q4 | Should `pm-opctl-cli list` read `pm-monitor`'s state to show HUNG/SILENT? | Follow-up, out of scope |
| Q5 | "Orders submitted" — count inbound requests (including those rejected) or accepted orders only? | Inbound, with rejects as a separate counter; accepted = `orders_in − rejects` is shown in the participant drawer |

### 19.3 Follow-ups (not in this plan)

- `config-gui` editor for the `monitor` section.
- GHCR publishing of the `dash-gui` image.
- `pm-opctl-cli` integration (Q4).
- Optional Prometheus text exposition from `pm-monitor` for users who do run
  Grafana — trivial once `pm-monitor` exists, deliberately not done now.
