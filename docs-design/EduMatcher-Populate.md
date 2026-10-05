Version: 0.4.0

Date: 2026-10-01

Status: Design ready for implementation. The implementation plan is in
`docs-design/EduMatcher-Populate-Plan.md`.

Change log:

- v0.4 (2026-10-01): Every assumption was re-verified against the code
  (§3), and ten v0.3 claims turned out wrong and are corrected. New
  decisions D25–D33 cover engine day-boundary semantics, TIFs, clearing
  retention and audit rotation. The engine re-stamps orders in sim mode. The
  MM sync now goes through the engine. Business-cadence timers move to sim
  time. A risk register (§17) and a call-site inventory (Appendix A) were
  added.
- v0.3: dedicated SIMULATOR traders, MM clock sync, auction flow, scripted
  events, news pane.
- v0.2: first full draft (ALF, sim clock, personalities).
- v0.1: REST draft, discarded.

# EduMatcher — Exchange History Generator (`pm-populate`)

---

## Table of Contents

1. [Purpose and scope](#1-purpose-and-scope)
2. [Decisions](#2-decisions)
3. [Verified facts about the existing code](#3-verified-facts-about-the-existing-code)
4. [Architecture](#4-architecture)
5. [The sim clock](#5-the-sim-clock)
6. [Engine changes](#6-engine-changes)
7. [The SIMULATOR role](#7-the-simulator-role)
8. [pm-mm-bot in sim mode](#8-pm-mm-bot-in-sim-mode)
9. [pm-populate process](#9-pm-populate-process)
10. [Market model](#10-market-model)
11. [Trader personalities and order generation](#11-trader-personalities-and-order-generation)
12. [Volume and timing](#12-volume-and-timing)
13. [News](#13-news)
14. [Outputs and report](#14-outputs-and-report)
15. [Determinism contract](#15-determinism-contract)
16. [Performance budget](#16-performance-budget)
17. [Risk register (holistic review)](#17-risk-register-holistic-review)
18. [Open items](#18-open-items)
19. [Appendix A — wall-clock call-site inventory](#appendix-a--wall-clock-call-site-inventory)
20. [Appendix B — new messages](#appendix-b--new-messages)
21. [Appendix C — scenario YAML schema](#appendix-c--scenario-yaml-schema)

---

## 1. Purpose and scope

Before a class, the instructor wants an exchange that looks as if it has been
trading for months. Students should find:

- price history with trends, shocks and rumours;
- daily OHLC/volume stats;
- clearing positions and P&L for the (simulated) market participants;
- resting GTC orders in the book on day one.

`pm-populate` builds this history on an existing, deployed but stopped
exchange in `DATA_PATH`. It works in four steps:

1. Start the stack in **sim-clock mode**.
2. Drive N past business days at accelerated pace.
3. Send every order through `pm-alf-gwy` under a dedicated **simulation
   trader** (role `SIMULATOR`).
4. Stop the stack.

Student desks are never touched, so students start class with clean
positions. The run also serves as a long, heavy, end-to-end stress test.

### 1.1 Non-goals

- No live background flow during class. Sim traders are dormant on class day
  (D21).
- No appending to an existing history, and no resuming an aborted run. A
  failed run is cleaned with `pm-opctl-cli clear --all` and run again (R12).
- No backwards compatibility. Configs must be regenerated to get `SIMULATOR`
  gateways. Old configs fail preflight with a clear message.
- Corporate actions are out of scope. The news pane in the GUIs has its own
  design doc; this doc only covers the backend that feeds it (§13).

### 1.2 Glossary

| Term | Meaning |
|---|---|
| **Sim time** | Business time while the stack runs in sim mode. It is set only by `pm-populate`. |
| **Slot** | One planned action at one sim timestamp: an order, cancel, amend, news item or session transition |
| **Tick** | One `clock.set` → `clock.tick` step that moves sim time to a slot's timestamp |
| **Intent** | A Phase-1 plan for an order: everything except price and quantity |
| **Barrier** | The point after which `pm-populate` knows every consequence of earlier actions has been processed and published |
| **SIM trader** | A gateway with role `SIMULATOR` (`SIM01…`), driven only by `pm-populate` |

---

## 2. Decisions

Settled with Johan across three interview rounds and the v0.4 review.
Decisions marked † were corrected in v0.4 after checking the code.

| # | Topic | Decision |
|---|---|---|
| D1 | Order entry | Orders go through `pm-alf-gwy`, with one TCP session per SIM gateway. `pm-populate` is also on the ZMQ bus (PUSH to the engine, SUB to the engine PUB) for clock, session transitions, news and market data. |
| D2 | Fake time | Bus-driven sim clock. Every process reads business time through `edumatcher.models.clock`, and in sim mode `pm-populate` advances it. |
| D3 † | Period | `--from/--to`, or `--days N` (default 120) ending yesterday. Business days are those where `engine.schedule_resolve.resolve_day()` returns a schedule; not simply "Mon–Fri minus holidays", because weekends and holidays can carry their own schedules. |
| D4 | Volume | `--avg-orders` (default 5000) is the average count of new orders per business day. |
| D5 | Default history | 120 business days |
| D6 | Phase 1 / Phase 2 | Phase 1 fixes time, trader, symbol, side, order type, TIF and urgency. Phase 2 sets price and quantity at send time. |
| D7 | Market model | Fair value = market factor × beta + idiosyncratic random walk + regime + jumps. It is simulated on a 1-minute sim-time grid (§10). |
| D8 † | News | The engine relays news onto the bus (`news.{SYMBOL}`, `news.MARKET`). `pm-stats` stores it for history (§13). The instructor file `news.yaml` holds the true magnitudes. |
| D9 | Personalities | Six archetypes, assigned by seed. The scenario YAML can override them. |
| D10 † | Market makers | The profile's `pm-mm-bot`s run in sim mode. They act only on `clock.tick` or on messages received before it, then send `clock.sync` through the engine. `pm-populate` waits for one `clock.synced` per bot before every action (§8). |
| D11 † | Order types | `--order-types`, default `MARKET,LIMIT,ICEBERG`. Optional: `IOC`, `FOK`, `STOP`, `STOP_LIMIT`, `TRAILING_STOP`, `OCO`. `LIMIT` is mandatory, because passive and auction flow need it. IOC and FOK are **order types** in EduMatcher, not TIFs. |
| D12 | Lifecycle | Traders cancel and amend their resting orders. These messages are extra, on top of `--avg-orders`. |
| D13 † | Existing data | Refuse to run unless the data directory is clean in the sense of `pm-opctl-cli clear --all`. `clear --state` keeps the audit log and log DB, and a mixed real/sim audit trail is misleading. |
| D14 | Pacing | Strictly sequential: one outstanding action, then a barrier. `--max-rate` is an optional cap in actions per real second. |
| D15 | Intraday shape | U-shaped intensity plus bursts after news on a symbol |
| D16 | End state | After the last day's CLOSED, `pm-opctl-cli stop`. The next normal start runs on the real clock. |
| D17 | Who trades | Only `SIMULATOR` gateways. Students start clean. |
| D18 | Sim trader identity | New role `SIMULATOR`. The engine refuses a `SIMULATOR` gateway connect unless it runs in sim mode. |
| D19 | Sim trader count | config-gen `--sim-traders N\|auto`, default auto = `max(20, n_symbols // 3)`. `0` means none. |
| D20 | Carry-over | SIM gateways use `disconnect_behaviour: LEAVE_ALL`, so GTC orders survive into class |
| D21 | Class day | SIM traders are dormant: the gateways exist but can't connect. Students may fill against their resting GTC orders. |
| D22 † | Auctions | Phase 1 plans auction-call flow every day as **LIMIT** orders. MARKET, IOC and FOK are rejected outside CONTINUOUS (`engine/main.py::_handle_new_order`). |
| D23 | Scheduler | `pm-scheduler` is excluded from the sim profile. `pm-populate` sends `session.transition` itself. |
| D24 | v1 scope | Scripted instructor events: in. News backend (bus, stats table, API endpoint): in. News pane: separate design. Corporate actions: out. |
| D25 | Day boundary (new) | The engine publishes `system.eod` on the transition to CLOSED. At shutdown it publishes only if no EOD was sent since the last PRE_OPEN. On PRE_OPEN it re-references each symbol's static collar to the last traded price. This applies in **both** modes (§6.2). |
| D26 | TIFs (new) | Separate `--tifs`, default `DAY,GTC`. GTD does not exist (TIF is `DAY, GTC, ATO, ATC`). `ATO`/`ATC` may be added for auction flow. |
| D27 | Clearing retention (new) | Keep the default 90 days, but prune by the **clock's** date instead of SQLite `date('now')`. Raw `trade_events` older than 90 days of sim time are pruned. Summaries and positions are kept, and stats keeps every trade. |
| D28 | Audit rotation (new) | `pm-audit` rotation goes from 10 MB × 5 to **100 MB × 5**, in both modes. The history's audit trail is still only partial (R4). |
| D29 | Order timestamp (new) | In sim mode the engine overwrites the incoming `order.ts_ns` with its own `now_ns()` on receipt (§6.1). |
| D30 | Clock start (new) | Sim mode is selected by the env var `EDU_CLOCK=sim:<epoch_ns>`, which every child of `pm-opctl-cli start` inherits. Business time is defined from process start, with no "unset" state. |
| D31 | Three time categories (new) | Business timestamps, business-cadence intervals and operational intervals (§5.1). The first two follow sim time; the last stays real. |
| D32 | Logging during a run (new) | The sim profile strips `--verbose` from all commands, because the engine logs every NEW at INFO (R5). |
| D33 | SIM SMP default (new) | config-gen sets `smp_action: CANCEL_RESTING` for SIM gateways |

---

## 3. Verified facts about the existing code

Everything below was read in the tree on 2026-10-01. Line numbers will drift,
so use them only to locate the code. **Bold** marks facts that changed the
design.

### 3.1 Time

| # | Fact | Where |
|---|---|---|
| F1 | `now_ns()` is the shared strictly increasing ns clock, built on `time.time_ns()`. Engine, order book, clearing and `Order.create` use it. | `models/clock.py` |
| F2 | About 121 direct wall-clock calls in `src/` outside msgen/valuation/config_gen/pm_help, plus 1 in `clock.py`. Inventory in Appendix A. | grep |
| F3 | **ULIDs (`msg_id` on every published message) take their ms prefix from `time.time()`, and audit-replay orders by it** | `models/envelope.py::new_ulid`, `audit/replay/ordering.py` |
| F4 | **The ALF gateway stamps `ts_ns` when it builds the order (`Order.create`), and the order book keeps that value on entry** | `alf_gwy/gateway.py::_handle_new_single`, `models/order.py::Order.create` |
| F5 | Book time priority uses the engine-assigned `arrival_seq`, not `ts_ns` | `models/order.py` (comment on `arrival_seq`), `engine/order_book.py` |
| F6 | **Engine book snapshots are throttled by `time.monotonic()` (`snapshot_interval_sec`) and published from the 200 ms maintenance loop** | `engine/main.py::_flush_snapshots`, `_run_maintenance` |
| F7 | **`pm-stats` price snapshots are written every 15 minutes of `time.monotonic()` per symbol** | `stats/main.py` (`SNAPSHOT_INTERVAL_SEC`, around line 1425) |
| F8 | **`pm-index` publish throttling uses `time.monotonic()`** | `index/main.py` around line 319 |
| F9 | **`pm-clearing` prunes with SQLite `date('now', -N days)`, a hidden wall clock** (also in the reconciliation query and the CLI) | `clearing/store.py::prune_old_events` and around line 1259, `clearing/cli.py` around line 644 |
| F10 | Schedule times are machine-local wall-clock times. The scheduler converts them DST-aware via `time.mktime(..., tm_isdst=-1)`. | `scheduler/main.py::_seconds_until_local` |
| F11 | Engine "today" (`_weekly_schedule_wire`, `_restore_gtc`) is `datetime.now().date()`, machine-local | `engine/main.py` around lines 281 and 1198 |
| F12 | `pm-stats` and `pm-clearing` bucket trading dates by `--timezone` (default **UTC**), from the event `ts_ns` | `stats/trading_day.py`, `clearing/ledger.py::trade_date` |
| F13 | CB reopening tails use `self._reopening_rng`, which is seeded only if `reopening_random_seed` is set in config | `engine/main.py` around lines 496 and 571 |

### 3.2 Engine behaviour

| # | Fact | Where |
|---|---|---|
| F14 | The engine is single-threaded: a PULL poll loop (200 ms timeout), then `_run_maintenance()`. One PUB socket, plus a separate drop-copy PUB on :5557. | `engine/main.py::run` |
| F15 | With sessions enabled the engine starts CLOSED. Valid transitions: CLOSED→PRE_OPEN→(OPENING_AUCTION→)CONTINUOUS→(CLOSING_AUCTION→)CLOSED. | `models/session.py::VALID_TRANSITIONS` |
| F16 | **An invalid transition is logged and dropped with no reply.** A valid one publishes `session.state`, plus `session.transition_ack.{gw}` when `reply_to` is set. | `engine/main.py::_handle_session_transition` |
| F17 | **MARKET, FOK and IOC are rejected (`SESSION_NOT_PERMITTED`) in every state except CONTINUOUS, and while a symbol is halted.** ATO is accepted only in OPENING_AUCTION, ATC only in CLOSING_AUCTION. | `engine/main.py::_handle_new_order` |
| F18 | Uncross runs when leaving a non-matching state. DAY orders expire on →CLOSED. Daily counters reset on →PRE_OPEN. | `engine/main.py::_handle_session_transition` |
| F19 | **`system.eod` is published only in `_shutdown()`.** Its consumers are clearing (mark-to-market, EOD row, prune), stats (close bid/ask, flush), index (`_finalize_eod`) and ralf-gwy (EOD lines). | `engine/main.py` around line 6306 |
| F20 | **Static collar `reference_price` is set once, at startup, from book_stats/config, and never re-referenced. Dynamic band is ±`dynamic_band_pct` (default 2 %) around `last_trade_price`.** | `engine/main.py::_load_config` around line 1155, `engine/collar.py::validate_collar` |
| F21 | CB reference is a rolling window of trades (`reference_window_ns`), stamped with `now_ns()`. A halt resumes when `now >= resume_at_ns`, checked in `_flush_circuit_breakers`. | `engine/circuit_breaker.py` |
| F22 | On shutdown, all resting DAY and GTC orders are saved to `gtc_orders.json` and book stats (last buy/sell, `prev_close`) to `book_stats.json`. On start, persisted stats win over the config seeds. | `engine/main.py::_shutdown`, `engine/persistence.py` |
| F23 | `disconnect_behaviour` is one of `CANCEL_QUOTES_ONLY`, `CANCEL_ALL`, `LEAVE_ALL`, and the engine honours all three | `models/participant.py`, `engine/main.py::_handle_gateway_disconnect` |
| F24 | Gateway "auth" is a `gateway.connect` checked against the configured ALF gateway ids. No secret is involved. | `engine/main.py::_handle_gateway_connect` |

### 3.3 ALF gateway

| # | Fact | Where |
|---|---|---|
| F25 | Line protocol: `CMD\|KEY=VAL\|…\n`, with keys and values upper-cased. `HELLO\|CLIENT=x\|PROTO=ALF1\|ID=<gw>` comes first. | `alf_gwy/protocol.py` |
| F26 | Commands: NEW (TYPE=…, including OCO and COMBO), AMEND (ID, PRICE/QTY, RTAG), CANCEL (ID or OCO_ID or COMBO_ID, RTAG), **QUOTE/QUOTE_CANCEL (MARKET_MAKER only)**, KILL, DC, SYMBOLS, ORDERS, QBOOT, QLEGS, SESSION, POS, PING. | `alf_gwy/gateway.py::_handle_client_line` |
| F27 | Responses: `ACK` (ORDER_ID, ACCEPTED, REASON, REJECT_CODE, TAG/RTAG), `FILL`, `AMENDED`, `CANCELLED`, `EXPIRED`, `OCO_ACK`, `COMBO_ACK`, … Gateway-side validation failures come back as `ERR` (CODE, TAG). | `alf_gwy/gateway.py::_route_gateway_scoped_event` |
| F28 | **Defaults: `max_commands_per_second=100` per session (token bucket), `idle_timeout_sec=30`, `max_connections=64`, `max_errors_before_disconnect=50` per 60 s.** | `alf_gwy/config.py` |
| F29 | `GATEWAY_ALREADY_CONNECTED` when a second session uses the same id | `alf_gwy/gateway.py::_handle_hello` |
| F30 | OCO fields: `OCO_ID, SYM, QTY, TIF, LEG1_SIDE/LEG1_TYPE/LEG1_PRICE/LEG1_STOP/LEG1_TRAIL`, same for `LEG2_` | `alf_gwy/gateway.py::_handle_new_oco` |

### 3.4 Other processes and tooling

| # | Fact | Where |
|---|---|---|
| F31 | `pm-mm-bot` talks ZMQ directly (PUSH + SUB, no ALF). Its timers (reissue, cancel timeout, fade) use `time.monotonic()`. `_tick()` runs whenever the poll times out. Handlers for book drift, session state and CB halt call `_cancel_and_reissue` or `_cancel_quote` directly. Bootstrap can use an unseeded `random.uniform`. | `mm_bot/bot.py` |
| F32 | **The audit log rotates at 10 MB × 5.** It stamps each record's receipt time with `datetime.now()`. | `audit/main.py` around lines 112 and 367 |
| F33 | opctl profiles are lists of `{name, command, tcp?, healthcheck?}`. Children inherit `os.environ`. `start_profile` already rewrites commands (it appends `--log-level DEBUG` for `-d`). The built-in `default` profile contains `pm-scheduler --daily` and `--verbose` everywhere. | `emo/cli.py` |
| F34 | `clear --state` removes book_stats, gtc orders/combos, stats.db, clearing.db, clearing report and `indexes/`. `--all` also removes audit log and index, log DB, log fallback dir and the opctl runtime dir. | `emo/cli.py::STATE_PATHS`, `NON_STATE_PATHS` |
| F35 | Roles are `TRADER`, `MARKET_MAKER`, `ADMIN`. The role list is repeated in cverifier (`_VALID_ROLES`), config-gen (`_ROLE_DEFAULT_DISCONNECT`), config-gui (`PARTICIPANT_ROLES`, `defaults.ts`), trader-gui (`GatewayRole`, `LoginPage` role check), alf/balf gateway role maps and api-gwy `engine_client`. | grep |
| F36 | trader-gui logs in with an **API key** from `api_gateways.*.credentials`. A gateway with no key cannot log in. config-gen auto-generates keys for ALF gateways unless told not to. | `trader-gui/.../LoginPage.tsx`, `config_gen/cli_parser.py` |
| F37 | Adding an enum *value* adds no dataclass field, so compiled-config digests are not invalidated (see `config_artifact` notes). Adding a dataclass field does invalidate them. | `config_artifact.py` |
| F38 | `s150-nominal-setup`: 150 symbols, 12 ALF gateways (TRADER01–10, OPS01, MM01), MM01 seed quotes with `seed_once`, `enforce_collars: false`, CB enforced, `sessions_enabled: true`, schedule 09:00/09:25/09:30/16:00/16:05, no `country` (so `DEFAULT_COUNTRY`), no `reopening_random_seed`. | `docs/examples/ref_data/s150-nominal-setup/engine_config.yaml` |
| F39 | `pm-ai-trader` already has `PersonalityProfile` presets (aggressive, cautious, many-small, …). It is a real-time bot and is not reused by `pm-populate`. Only the idea is shared. | `ai_trader/personality.py` |

### 3.5 v0.3 claims corrected by these facts

| v0.3 said | Reality | Fix |
|---|---|---|
| "ALF carries orders, not quotes" | ALF supports QUOTE for MARKET_MAKER (F26) | Irrelevant to the design, since MM bots use ZMQ. Wording removed. |
| GTD TIF; IOC/FOK as TIF | No GTD; IOC/FOK are order types (F17, `models/order.py`) | D11, D26 |
| Auction flow uses LIMIT and MARKET | MARKET rejected outside CONTINUOUS (F17) | D22: LIMIT only |
| EOD rollups "run for real" when the clock crosses the close | EOD only at shutdown (F19) | D25 |
| Collars "relative to the previous close" | Static reference fixed at startup (F20) | D25 re-references at PRE_OPEN |
| "Monotonic stays real" | Book snapshots, stats snapshots and index publishing are business cadences (F6–F8) | D31 |
| Business days = Mon–Fri minus holidays | `resolve_day()` semantics (F10) | D3 |
| Clean data = `clear --state` | Leaves audit and logs (F34) | D13 |
| MM bot publishes `mm.sync` | Bots have no PUB socket (F31) | §8: relay via engine |
| GUIs must hide SIM traders from desk pickers | Login is by API key; SIM gets none (F36) | Only role lists need the new value |

---

## 4. Architecture

```
                    ┌──────────────────────────── pm-populate ─────────────────────────────┐
                    │ Preflight · Calendar · Planner (P1) · Market model · Personalities   │
                    │ Sequencer (P2): barrier loop · Book/position tracker · Report        │
                    └──────┬───────────────────────────┬──────────────────────┬────────────┘
       ALF/TCP, one session│ per SIMxx                 │ ZMQ PUSH             │ ZMQ SUB
       NEW/AMEND/CANCEL/OCO│ ACK/ERR/FILL…             │ clock.set            │ clock.tick, clock.synced,
                           ▼                           │ session.transition   │ session.state, book.*,
                     pm-alf-gwy ── PUSH ──▶ pm-engine ◀┘ news.publish         │ trade.executed, order.*.SIMxx,
                                               │   ▲                          │ circuit_breaker.*
                                               │   └── PUSH (quote.*, clock.sync) ── pm-mm-bot(s)
                                               └── PUB ──▶ stats, clearing, audit, index, md/ralf/dc gwys,
                                                           api-gwys, alf-gwy, mm-bot(s), pm-populate
```

Roles:

- **pm-populate** is the time master. It decides when sim time moves and
  serialises every action.
- **pm-engine** is the time authority. It applies `clock.set`, runs its timers
  and business-cadence flushes, then publishes `clock.tick`. Because every
  subscriber reads the same PUB socket in order, every subscriber sees all
  events stamped up to a tick before the tick itself (F14).
- **pm-mm-bot** follows ticks and reports with `clock.sync`, which the engine
  republishes as `clock.synced`.

### 4.1 One slot, step by step

```
pm-populate                     engine                        mm-bot(s)        alf-gwy
    │ clock.set{ts}  ──PUSH──▶     │ apply ts; CB/ACE timers;      │                │
    │                              │ flush dirty book snapshots;   │                │
    │ ◀── SUB  book.*, clock.tick ─┤ publish clock.tick ──────────▶│ apply; _tick() │
    │                              │ ◀── quote.* (if any) ─ PUSH ──┤                │
    │                              │ ◀── clock.sync ──────  PUSH ──┤                │
    │ ◀── SUB  quote acks…, clock.synced{gw,ts} (×K bots)          │                │
    │ resolve intent → order (book view = snapshots up to this tick)                │
    │ NEW|…|TAG=t  ─────────────────────────── TCP ─────────────────────────────▶  │
    │                              │ ◀──────────────────── order.new ── PUSH ───────┤
    │                              │ match; publish ack/fills/trade                 │
    │ ◀── TCP  ACK|…|TAG=t ────────────────────────────────────────────────────────┤
    │ (next slot)                  │                                                │
```

The **barrier invariant**: when `pm-populate` sends `clock.set` for slot *n+1*,
the engine has fully processed slot *n*'s order. That holds because
`pm-populate` got the ALF response, which the engine only produces after
handling the order. When `pm-populate` then sees `clock.tick(n+1)` and all
`clock.synced(n+1)`, it has also received every event of slot *n* and every
MM reaction to them on its SUB socket.

**The MM bots' PUSH, alf-gwy's PUSH and pm-populate's PUSH are different
sockets.** Their relative order at the engine is only ever fixed by these
waits. That is why nothing may be sent without one.

---

## 5. The sim clock

### 5.1 Three categories of time (D31)

| Category | Examples | Real mode | Sim mode |
|---|---|---|---|
| **B: business timestamp / date** | event `ts_ns`, ULID prefix, trading date, "today", order-event rows, audit receipt time, clearing prune cutoff | wall clock | sim clock |
| **C: business cadence** | engine book-snapshot throttle, auction-indicative throttle, CB/ACE timers, stats price-snapshot interval, index publish throttle, MM bot reissue/fade/cancel-timeout timers | `time.monotonic()` | sim seconds |
| **O: operational** | heartbeats, idle timeouts, rate-limit tokens, flush cadence, persistence checkpoint, debug summaries, socket timeouts, log server timestamps and retention | `time.monotonic()` / wall clock | **unchanged (real)** |

The test for B: does the value end up in persisted or published business
data, or decide which day it is? The test for C: does the interval decide
*how often business data is sampled or acted on*? Everything else is O.

### 5.2 `models/clock.py` API

```python
def is_sim() -> bool
def now_ns() -> int            # B. Strictly increasing, as today. In sim mode: max(last+1, sim_ns)
def now_s() -> float           # B. now_ns() / 1e9 (convenience for time.time() call sites)
def now_dt(tz: tzinfo | None = None) -> datetime   # B. aware datetime; tz=None means local
def today() -> date            # B. local calendar date of now_ns() (matches F10/F11)
def cadence_s() -> float       # C. time.monotonic() in real mode, sim_ns / 1e9 in sim mode
def apply_tick(ts_ns: int) -> None   # sim only; raises ClockError if ts_ns < current
def reset_clock_for_tests() -> None  # exists; extended to reset the mode too
```

Rules:

1. **Mode selection**: at import, read `EDU_CLOCK`. Unset or `real` gives
   real mode. `sim:<int epoch ns>` gives sim mode with that start time.
   Anything else raises `ClockError` at import, so a typo fails loudly.
2. **Between ticks the sim clock does not advance.** `now_ns()` still returns
   strictly increasing values (+1 ns per call), exactly as today when the wall
   clock stalls. This is what orders events stamped within one tick.
3. `apply_tick(ts)` with `ts == current` is allowed and is a pure barrier.
   `ts < current` raises `ClockError`.
4. Thread safety: one module lock, shared by `now_ns()` and `apply_tick()`,
   because stats, audit and api-gwy are multi-threaded.
5. `new_ulid()` takes its ms prefix from `now_ns() // 1_000_000` instead of
   `time.time()` (F3). Its existing monotonic-within-ms logic is unchanged.

### 5.3 How a process follows the clock

There is one helper, used by every bus subscriber:

```python
# models/clock.py
CLOCK_TICK_TOPIC = TOPIC_CLOCK_TICK   # "clock.tick" from generated bindings
def follow(topic: str, payload: dict[str, Any]) -> bool:
    """If topic is clock.tick and we are in sim mode, apply it; return True if consumed."""
```

Each process that subscribes to the engine PUB does two things in sim mode:

- adds `clock.tick` to its subscription list;
- calls `clock.follow()` first in its dispatch.

Processes that subscribe to the empty prefix (audit) get the topic for free,
but must still call `follow()`.

| Process | Must follow ticks | Why |
|---|---|---|
| pm-stats | yes | order-event rows, book-receipt dates, EOD date, snapshot cadence |
| pm-clearing | yes | session_events, flush timestamps, prune cutoff |
| pm-audit | yes | receipt timestamps |
| pm-index | yes | history `ts_ns`, publish cadence |
| pm-alf-gwy, pm-balf-gwy | yes | `Order.create` stamps (re-stamped by the engine anyway, D29); ULIDs |
| pm-md-gwy, pm-ralf-gwy, pm-dc-gwy | yes | business `TS` fallbacks, ULIDs |
| pm-api-gwy (×2) | yes | `session_date`, event envelopes |
| pm-mm-bot | yes, and drives behaviour (§8) | |
| pm-log-srv | **no** | operational |
| pm-scheduler | not started in sim mode | |

### 5.4 Engine handling of `clock.set`

`clock.set {ts_ns}` arrives on the engine PULL socket. The handler:

1. In real mode, reject with a `system.diagnostic` (`component=CLOCK`,
   error "not in sim mode") and change nothing.
2. If `ts_ns < clock.now`, reject the same way ("clock moves forward only").
3. `clock.apply_tick(ts_ns)`.
4. `_flush_circuit_breakers()` (CB resume and ACE extend/uncross) and
   `_flush_auction_indicative()`.
5. `_flush_snapshots()`, with the throttle measured by `clock.cadence_s()`.
6. Publish `clock.tick {ts_ns}`.

In sim mode, `_run_maintenance()` **does not** call `_flush_snapshots`,
`_flush_circuit_breakers` or `_flush_auction_indicative`. They run only from
step 4/5. Otherwise a snapshot published between ticks, which MM bots react
to, would race the next action and break determinism (§15).
`_flush_persistence` and `_flush_debug_summary` stay in maintenance.

`clock.sync {gateway_id, ts_ns}` (from MM bots, sim mode only) makes the
engine publish `clock.synced {gateway_id, ts_ns}`. It has no other effect.

At startup in sim mode the engine logs at WARNING:
`SIM CLOCK MODE — business time starts at <iso> and only moves on clock.set`.

---

## 6. Engine changes

### 6.1 Order timestamp in sim mode (D29)

`alf-gwy` stamps `ts_ns` when it builds the order (F4). It sees `clock.tick`
on its own SUB socket, which can lag the tick `pm-populate` saw, so the stamp
could carry the previous tick's time. In sim mode, `_handle_new_order`,
`_handle_oco_order` and `_handle_combo_order` set `order.ts_ns = now_ns()`
before any processing. Real mode is unchanged.

### 6.2 Day boundaries (D25, both modes)

1. **EOD at CLOSED.** In `_handle_session_transition`, after the CLOSED branch
   (DAY expiry, CB reset), publish `make_eod_msg([book.snapshot() for …])`
   and set `self._eod_sent_today = True`. On →PRE_OPEN, set it back to
   False. In `_shutdown()`, publish EOD only if `not self._eod_sent_today`.
   This also covers `sessions_enabled: false`, where the flag is never set.
2. **Collar re-reference at PRE_OPEN.** On →PRE_OPEN, for each symbol in
   `self._collars`, set `reference_price` from `book.last_trade_price`. If
   there is none, use the same last-buy/last-sell rule as `_load_config()`.
   Log the old and new reference at INFO for each symbol whose reference
   changed.
3. Update `spec/messages/system.yaml::eod` ("once per trading day at the
   close; at shutdown only if the day had none"). Update
   `docs/user-guide/120-risk-controls.md` §"Price collars" ("static reference
   is re-taken at every PRE_OPEN"), and add a CHANGELOG entry.
4. Consumers are already per-day safe. Clearing writes one EOD row per
   trade_date and prunes. Stats flushes the day's accumulator. Index runs
   `_finalize_eod`. ralf-gwy emits per-symbol EOD lines and clears its
   counts. None of them assumes EOD is the last message before exit. This
   must be confirmed by WP-09's tests.

### 6.3 Clearing prune (D27)

`prune_old_events()`, the reconciliation retention guard and the CLI count
query take an explicit `cutoff_date: str` parameter, computed in Python as
`(clock.today() - timedelta(days=retention_days)).isoformat()`, in place of
`date('now', …)`. They compare `trade_date < :cutoff`. Note that `trade_date`
is in the clearing `--timezone` while `clock.today()` is local; the difference
is at most one day at the boundary, which is acceptable for a retention window.

### 6.4 Audit rotation (D28)

In `audit/main.py`, change the `RotatingFileHandler` to `maxBytes=100 * 1024 *
1024`. `backupCount` stays 5. Document the 600 MB worst case (active file plus
5 backups) in the audit chapter.

### 6.5 News relay

`news.publish {…}` arriving on PULL is validated (field lengths, `kind` enum)
and republished as `news.{SYMBOL}` or `news.MARKET` (Appendix B). It is
allowed in both modes. It takes no gateway id, matching how
`session.transition` works today.

---

## 7. The SIMULATOR role

| Area | Change |
|---|---|
| `models/participant.py` | `ParticipantRole.SIMULATOR = "SIMULATOR"` |
| `engine/config_loader.py` | Accepted through the enum. No new fields (F37). |
| `engine/main.py::_handle_gateway_connect` | If `cfg.role == SIMULATOR and not clock.is_sim()`: publish `gateway_auth(accepted=False, reason="SIMULATOR gateways may only connect in sim-clock mode")` and log at WARNING |
| `alf_gwy`, `balf_gwy` | SIMULATOR is treated like TRADER: allowed NEW/AMEND/CANCEL/KILL/POS, refused QUOTE (`ROLE_DENIED`) |
| `cverifier` layer 2 | Add the value to `_VALID_ROLES` |
| `cverifier` layer 3 | A SIMULATOR gateway must have `disconnect_behaviour: LEAVE_ALL` (error). It must not appear in any `api_gateways.*.credentials` (error), and must not appear in `market_maker_quotes` (error). Warn if the count of SIMULATOR gateways is greater than `alf_gateway.max_connections`. |
| `config_gen` | `_ROLE_DEFAULT_DISCONNECT[SIMULATOR] = LEAVE_ALL`. New `--sim-traders N\|auto` (default `auto`) appends `SIM01..SIMnn` (zero-padded to 2 digits, 3 if > 99) with description `Simulation trader (pm-populate)` and `smp_action: CANCEL_RESTING` (D33). SIM gateways are excluded from API-key auto-generation. An explicit `--participants` entry that collides with a SIM id is an error. |
| `api_gateway/engine_client.py` | No change. Unknown roles already fail closed to TRADER, and SIM gateways have no keys. |
| config-gui | Add to `PARTICIPANT_ROLES`, extend the `defaults.ts` role union and default disconnect (LEAVE_ALL), and add a diagnostics rule mirroring cverifier |
| trader-gui | Add `"SIMULATOR"` to the `GatewayRole` type (the admin gateway list shows it). LoginPage is unchanged: SIM can never log in. |
| example configs | Regenerate every `docs/examples/ref_data/*` setup with the new default |
| docs | Configuration chapter (roles table), risk chapter (SMP default), pm-help |

---

## 8. pm-mm-bot in sim mode

The goal is that the bots' quoting is a deterministic function of the bus
stream, with time measured in sim seconds.

1. All timer reads (`time.monotonic()` in reissue, cancel timeout, fade,
   pricer `on_fill`, last-quote-sent) become `clock.cadence_s()`. Bootstrap
   and handshake deadlines (`_authenticate`, `_request_symbols`,
   `_request_bootstrap`, `_request_qlegs`, `_wait_for_session`) stay real,
   because they are operational (O).
2. In sim mode `_run_loop` **does not** call `_tick()` on poll timeout. It
   calls `_tick()` only when it receives `clock.tick`, and only after
   `clock.follow()`. Then it immediately pushes `clock.sync {gateway_id,
   ts_ns}`.
3. Event handlers that send directly (book drift → `_cancel_and_reissue`,
   session state → cancel, CB halt → cancel) are left as they are. Every
   such message arrives on the SUB socket before the tick that follows it,
   so the bot's PUSH carries the reaction before the `clock.sync`, and the
   engine processes both in that order.
4. **Registration**: after startup bootstrap completes (all symbols active),
   the bot pushes `clock.sync {gateway_id, ts_ns: <current>}` once. That tells
   `pm-populate` the bot is ready.
5. The bootstrap `random.uniform` path (no reference price) is not
   deterministic. In sim mode, the bot logs a WARNING when it uses it.
   Preflight warns when a configured MM symbol has no `last_buy_price` or
   `last_sell_price`.
6. Cost: per tick, one `clock.sync` PUSH and one `clock.synced` PUB per bot.

`pm-populate` learns K, the number of bots, as the number of profile entries
whose `command[0] == "pm-mm-bot"`. It waits for K distinct registrations
(timeout 60 s real) before day 1.

---

## 9. pm-populate process

### 9.1 Package layout

```
src/edumatcher/populate/
  __init__.py
  main.py          # CLI, top-level orchestration, cleanup
  cli.py           # argparse, validation
  preflight.py     # §9.3
  calendar.py      # business days, schedule → epoch ns (DST-aware, local tz)
  stack.py         # opctl start/stop/health wrappers, sim profile transform
  bus.py           # ZMQ PUSH/SUB, clock.set+wait, transitions, sync wait, trackers
  alf.py           # ALF session pool, line I/O, correlation, keepalive
  model/market.py  # fair value, regime, gaps (§10)
  model/news.py    # random + scripted events, rumours (§13)
  model/volume.py  # daily counts, intraday intensity, thinning (§12)
  traders.py       # archetypes, parameters, assignment (§11)
  intents.py       # Phase 1 planner
  pricing.py       # Phase 2 intent → concrete command (§11.4)
  sequencer.py     # the barrier loop (§9.6)
  scenario.py      # YAML load/validate (Appendix C)
  report.py        # §14
```

The entry point is `pm-populate = "edumatcher.populate.main:main"` in
`pyproject.toml`, with a `pm-help` registry entry. Use the house logging
setup: `_configure_logging`, `--log-level`, logclient.

### 9.2 CLI

```
pm-populate [--profile NAME]                                 # opctl profile, default: default
            (--days N | --from YYYY-MM-DD --to YYYY-MM-DD)   # default --days 120
            [--avg-orders 5000]
            [--order-types MARKET,LIMIT,ICEBERG]
            [--tifs DAY,GTC]
            [--seed INT]                                     # default: random, printed
            [--scenario FILE]
            [--max-rate N]                                   # actions per real second, 0 = unlimited (default)
            [--fair-value-csv close|minute|off]              # default close (§10.3)
            [--dry-run]
            [--log-level LEVEL]
```

Validation (exit code 2, message naming the flag):

- `--to` must be strictly before `clock.today()` in real mode, i.e. today.
- `--from ≤ --to`.
- `--days ≥ 1`.
- The resolved business-day list must not be empty.
- `LIMIT` must be in `--order-types`.
- `DAY` must be in `--tifs`.
- Unknown order types or TIFs are rejected.
- `--avg-orders ≥ 10`.

### 9.3 Preflight (no side effects)

Each check fails with exit code 3 and a one-line remedy.

1. No `pm-*` process is running except this one (`emo.cli.pgrep_pids("pm-")`
   minus `os.getpid()`). Remedy: `pm-opctl-cli stop`.
2. None of `STATE_PATHS` or `NON_STATE_PATHS`, except the opctl runtime dir,
   exists. Remedy: `pm-opctl-cli clear --all`.
3. The compiled config loads (`load_compiled_config`) with no digest error.
4. `sessions_enabled` is true and a schedule is present.
5. There is at least one `SIMULATOR` gateway. Remedy: regenerate with
   `pm-config-gen` (D19).
6. `n_sim ≤ alf_gateway.max_connections`.
7. The profile exists and contains `pm-engine` and `pm-alf-gwy`.
8. `--scenario` validates (Appendix C).
9. Warnings only:
   - `reopening_random_seed` is unset (CB reopen timing will not be
     reproducible);
   - an MM symbol has no reference price (§8 rule 5);
   - the calendar span is longer than clearing retention (D27);
   - `enforce_collars` is true with `dynamic_band_pct < 0.01` (very slow
     price discovery after news).

### 9.4 Stack start and stop

`stack.sim_profile(processes)` returns a copy with:

- every entry whose `command[0] == "pm-scheduler"` removed;
- every `--verbose`, `-v` and `-vv` token removed from all commands (D32).

`stack.start(profile, sim_start_ns)`:

1. Set `os.environ["EDU_CLOCK"] = f"sim:{sim_start_ns}"`.
2. Call `emo.cli.start_profile(profile_name, processes_override=…)`. This is a
   small new parameter on `start_profile`; the existing debug rewrite stays
   as it is.
3. Poll `health_profile(quiet=True)` until it returns 0, with a 60 s timeout.

`sim_start_ns` is day 1's PRE_OPEN minus 60 s, local tz.

`stack.stop()` calls `emo.cli.stop_profile()`. `main()` wraps the whole run in
`try/finally` and installs SIGINT/SIGTERM handlers, so **the stack is always
stopped**: on success, on error and on Ctrl-C. Exit codes: 0 success, 1 run
error (stack stopped, data dirty), 2 usage, 3 preflight.

### 9.5 Connections

- **Bus**: `make_pusher(ENGINE_PULL_ADDR)`, then
  `make_subscriber(ENGINE_PUB_ADDR)` subscribed to: `clock.`,
  `session.state`, `book.`, `trade.executed`, `circuit_breaker.`,
  `order.ack.SIM`, `order.fill.SIM`, `order.cancelled.SIM`,
  `order.expired.SIM`, `order.amended.SIM`. Prefix matching on `SIM` covers
  every SIM gateway.
- **ALF**: one TCP connection per SIM gateway to `alf_gateway.port`. Send
  `HELLO|CLIENT=pm-populate|PROTO=ALF1|ID=SIMxx` and wait for the auth result
  line, timeout 10 s. Any failure aborts.
- **Keepalive**: before each slot, any session idle for more than 10 s real
  time gets `PING`. A missing `PONG` within 5 s aborts. This guards F28's
  30 s idle timeout.
- **Rate limit**: the per-session bucket is 100/s (F28). In sequential mode a
  single session cannot exceed about 1 action per round trip, but cancel
  sweeps can hit one trader repeatedly. On `ERR|CODE=RATE_LIMITED`, sleep
  `1/100 s` and resend, at most 3 times, then abort. Count retries in the
  report.

### 9.6 The sequencer (barrier loop)

```
for day in business_days:
    plan = planner.plan_day(day)                     # Phase 1, pure function of (seed, day, model state)
    for slot in plan.slots:                          # strictly increasing ts_ns
        throttle(max_rate)
        bus.clock_set(slot.ts_ns)                    # PUSH clock.set
        bus.wait_tick(slot.ts_ns, timeout=5s)        # SUB clock.tick (consumes book.*, fills… on the way)
        bus.wait_synced(K, slot.ts_ns, timeout=2s)   # K × clock.synced
        match slot.kind:
          TRANSITION: bus.transition(state, next); bus.wait_state(state, 5s)
                      bus.clock_set(slot.ts_ns); wait_tick; wait_synced   # let MM bots react; barrier
          NEWS:       model.apply(news); bus.news_publish(news)            # barrier = next slot's tick
          ORDER|CANCEL|AMEND:
                      cmd = pricing.resolve(slot.intent, tracker, model)   # may return SKIP(reason)
                      if cmd: resp = alf.send_and_wait(cmd, timeout=5s)    # ACK/AMENDED/CANCELLED/OCO_ACK/ERR
                              tracker.on_response(cmd, resp)
    report.end_of_day(day)
```

Rules:

- A timeout anywhere is fatal. Log the slot, stop the stack, exit 1. A silent
  continue would break the barrier invariant (§4.1).
- A news publish has no reply. Its barrier is the next slot's `clock.tick`,
  since the engine processes PULL in order and the news is published before
  that tick.
- The tracker updates positions from `order.fill.SIM*` and books from
  `book.*` while waiting for ticks. **All tracker state used to price slot n
  was received before `clock.tick(n)`** (§4.1). Fills from slot n−1 that
  belong to other traders are therefore visible.
- An engine reject (`ACK ACCEPTED=FALSE`) or an `ERR` is counted per
  `REJECT_CODE`/`CODE`, and the run continues.
- `--dry-run` runs §9.3 checks 2–9, all Phase-1 planning and the market model
  for every day, and writes `run.yaml`, `news.yaml`, `fair_value.csv` and
  `plan_summary.csv`. It does not start the stack. Phase 1 must not depend on
  Phase-2 feedback, which also lets the dry run report planned volumes
  exactly (§11.3).

### 9.7 Day transitions

The per-day schedule is `resolve_day(day)`, five HH:MM times. They are
converted to epoch ns in local tz with `time.mktime((y,m,d,h,mi,0,0,0,-1))`,
the same DST rule as F10. The planner emits TRANSITION slots at each time:

- PRE_OPEN
- OPENING_AUCTION
- CONTINUOUS
- CLOSING_AUCTION
- CLOSED

Each carries `next` (state and ISO time of the following transition), like the
scheduler does. After CLOSED, the next day starts with a clock.set to that
day's PRE_OPEN (ticks may jump across nights, weekends and holidays).

---

## 10. Market model

### 10.1 Fair value on a 1-minute grid

For each business day, from PRE_OPEN to CLOSED inclusive, and per symbol *s*,
log fair value `x_s(t_k)` is stepped on a 1-minute sim grid. With Δ = 1 min in
years (1/(252·390) for a 6.5 h day; use the actual session minutes):

```
ΔM_k   = μ_M·Δ + σ_M·R(t)·√Δ·ε_M,k                     (one market factor)
x_s,k+1 = x_s,k + β_s·ΔM_k + σ_s·R(t)·√Δ·ε_s,k + J_s,k  (J = news jumps, §13)
```

- `x_s,0 = ln(ref_s)`, where `ref_s` is the config `last_buy_price`, else
  `last_sell_price`. This is the same preference as F20. A symbol with
  neither is excluded from the run, with a warning.
- β_s ~ U[0.6, 1.4], σ_s ~ U[0.25, 0.45] annualised, μ_M = 0.06, σ_M = 0.15,
  all drawn from the `market` substream (§15). Normal draws use
`random.Random.gauss`. The scenario YAML can
  override them.
- `R(t)` is the regime multiplier: a 2-state Markov chain (calm 1.0, stressed
  2.0) with mean holding times of 25 and 5 business days.
- **Overnight gap**: one extra step at PRE_OPEN with variance equal to 0.3 of
  a full day's variance.
- Between grid points, the planner and pricing use the value of the last grid
  point (step-hold). Because the grid is independent of the slots, changing
  `--avg-orders` or `--order-types` cannot change any fair-value path.

### 10.2 Guard rails (verified against F17, F20, F21)

The engine's rules bind the *order prices*, not the model. The model is never
clamped (except for the floor below); `pricing.py` clamps orders (§11.4).

- **Static collar**: once D25 is in, the static band re-references to the last
  trade at every PRE_OPEN. A daily move greater than `static_band_pct` (20 %
  default) can therefore only happen across days. That is realistic and
  needs nothing else.
- **Dynamic collar**: ±2 % around the last trade. A −15 % news jump realises
  through a sequence of trades, each within 2 % of the previous one. That
  gives a visible "slide" over minutes, which is the intended classroom
  effect.
- **Circuit breakers** may fire. While a symbol is halted (tracked from
  `circuit_breaker.halt/resume.*`), pricing only emits LIMIT orders for it
  (F17).
- **Floor**: `x_s` is floored at `ln(10 · tick_size)`, so a symbol cannot
  walk to zero.

### 10.3 Output

`fair_value.csv` has the columns `date,time,symbol,fair_value,regime`, one row
per symbol per minute. For s150 × 120 days × 426 min that is about 7.7 M rows
(about 300 MB). With `--fair-value-csv minute|close|off` (default `close`),
`close` writes one row per symbol per day. `minute` is for calibration.

---

## 11. Trader personalities and order generation

### 11.1 Archetypes

| Archetype | Signal used at send time | Urgency mix (cross/touch/passive) | Preferred types → fallback | TIF mix |
|---|---|---|---|---|
| noise | last trade only | 40/30/30 | MARKET→LIMIT(cross), LIMIT | DAY |
| momentum | trend of last-trade over 30 sim-min and 5 days | 50/30/20 | LIMIT, STOP/STOP_LIMIT (exits)→LIMIT | DAY |
| value | fair value lagged 2–5 days, plus noise | 5/15/80 | LIMIT | GTC 60 % |
| informed | fair value + small noise, sees news 0–20 min early | 60/20/20 | LIMIT, IOC→LIMIT, ICEBERG | DAY |
| institutional | fair value lagged 1 day; works a parent order | 20/30/50 | ICEBERG→LIMIT, LIMIT | DAY 70 %, GTC 30 % |
| day trader | last-trade trend over 5 sim-min plus book imbalance | 50/40/10 | LIMIT, IOC/FOK→LIMIT, OCO (exit)→none | DAY |

Fallback rules:

- A type not in `--order-types` falls back as shown.
- A TIF not in `--tifs` falls back to DAY.
- An OCO exit with OCO disabled is simply not planned.
- MARKET requires CONTINUOUS and a non-halted symbol; otherwise it becomes
  LIMIT(cross).

### 11.2 Per-trader parameters

These are drawn from archetype ranges on the trader's own substream:

- `activity` weight (log-normal σ 0.5);
- `symbol_focus` (k symbols with Zipf(1.1) weights; k from 3 to all);
- `size_range` (lot-free integer quantities, clamped by `order_limits`);
- `aggressiveness` (shifts the urgency mix ± 10 points);
- `passive_offset_ticks`;
- `signal_noise_pct`, `signal_lag`;
- `risk_limit` (max |position| per symbol, in shares; default 2 % of
  `outstanding_shares`, or 50 000 when that is absent);
- `cancel_horizon_min`;
- `stop_loss_pct` (momentum and day trader).

**Assignment**: archetype weights default to noise 30, momentum 15, value 15,
informed 5, institutional 10, day trader 25 (%). SIM gateways are sorted, then
shuffled on the `assignment` substream and filled by the largest-remainder
method. `traders:` in the scenario pins an archetype and/or parameters per
gateway.

### 11.3 Phase 1: intents

For each planned order slot, Phase 1 picks:

- the symbol, weighted by tier × news uplift;
- the trader, weighted by `activity × focus_weight(symbol)`;
- the side;
- the type and TIF;
- the urgency.

Side comes from the archetype's signal *as known at planning time*. That
means the fair-value path, news and the trader's lag only, never live book
data, which keeps Phase 1 a pure function (§9.6 dry run). Noise picks
50/50. Momentum and informed take the sign of their signal with p = 0.7.
Value takes the sign of (lagged fair − last day's model close). Institutional
follows its parent order's side.

### 11.4 Phase 2: pricing (`pricing.resolve`)

Inputs:

- the intent;
- the tracker: the last book snapshot per symbol, the last trade price,
  halted flags, session state, this trader's position and open orders;
- the model: the trader's view of fair value.

Steps:

1. **Phase gate**. Outside CONTINUOUS, or when halted, MARKET, IOC and FOK
   become LIMIT, and urgency `cross` becomes `touch`.
2. **Price**:
   - `cross`: through the opposite best by `1 + ⌊U·3⌋` ticks, or at the
     trader's fair view if the opposite side is empty.
   - `touch`: equal to own-side best, or the trader's fair view ± 1 tick if
     that side is empty.
   - `passive`: the trader's fair view ∓ `passive_offset_ticks` ±
     noise.
3. **Clamp**: to the dynamic collar `[last·(1−d), last·(1+d)]` when
   `enforce_collars` and a collar exists for the symbol, then to the static
   band around the PRE_OPEN reference (tracked by pm-populate exactly as
   D25 defines it). Clamp to ≥ 1 tick. Snap to the tick grid (`tick_decimals`
   from config).
4. **Quantity**: draw from `size_range`. Clamp to `order_limits.max_order_qty`
   and to `max_order_value / price` when set. Clamp so that
   |position + signed qty| ≤ `risk_limit`. If the clamp gives 0, flip side
   once. If still 0, return `SKIP(risk)`.
5. **Iceberg**: `VISIBLE = max(1, round(QTY · U[0.10, 0.25]))`, and must be
   < QTY. If QTY < 2, use LIMIT instead.
6. **STOP/STOP_LIMIT**: `STOP` is placed `stop_loss_pct` away from the
   trader's average entry, on the loss side. Only when the trader holds a
   position.
7. **OCO** (day trader exit): leg 1 is a LIMIT take-profit, leg 2 a STOP
   stop-loss, QTY equal to the position. Only when the position is non-zero.
8. **Cancel/amend slots** pick the trader's oldest open order on that symbol
   that is older than `cancel_horizon` or further than 2× the passive offset
   from the current target. Choose AMEND (to the new target price) with p =
   0.6, else CANCEL. Return `SKIP(no-order)` when nothing qualifies.
9. Every command carries `TAG` (NEW) or `RTAG` (AMEND/CANCEL) =
   `P<day-index>-<slot-index>`. That value is unique and is used to correlate
   responses (F27).

**Invariant, tested**: every command produced by `resolve()` passes the
engine's own `validate_collar()` and order-limit checks for the tracked state.
A collar or order-limit reject during a run is a pricing bug.

### 11.5 GTC hygiene

At the start of each day, any GTC order older than `max_gtc_age_days`
(default 10 business days) is scheduled for cancellation in that day's first
continuous hour. The report records the end-of-run resting-order count per
symbol. Acceptance requires median < 40 and max < 200 resting orders per
symbol (§17 R16).

---

## 12. Volume and timing

- **Daily count**: `N_d ~ Poisson(avg_orders · f_d)`, with
  `f_d = LogNormal(−σ²/2, σ=0.25) · (1 + 0.5·news_count_d / n_symbols)`.
- **Auction share**: `a_open = 0.03`, `a_close = 0.05` of `N_d`, placed
  uniformly in [PRE_OPEN, CONTINUOUS) and [CLOSING_AUCTION, CLOSED). They are
  LIMIT orders, TIF DAY, or ATO/ATC if enabled in `--tifs` and inside the
  matching window (F17). Every symbol with any continuous slot that day gets
  at least one buy and one sell auction order in each auction.
- **Continuous**: the remaining slots are placed by thinning a
  non-homogeneous Poisson process with `λ(t) = U(t) · Π(1 + 4·e^{−(t−t_e)/20min})`.
  - `U` is a U-shape: piecewise-linear, 2.5× at the open, 1× from 11:00 to
    14:30 local, 2× at the close.
  - The product runs over news events on the slot's symbol, applied at
    symbol-pick time.
- **Cancel/amend slots**: per trader per day, `Poisson(0.4 · orders_d(trader))`,
  placed uniformly in continuous.
- **Timestamps** are integer µs, strictly increasing within the day (add
  1 µs on a tie). Transition slots sit exactly on schedule times; orders never
  share a transition's timestamp.

---

## 13. News

### 13.1 Generation

Each business day and symbol, the number of events is
`Poisson(rate_per_symbol_day)`, default 0.05. Market events (`MARKET_SHOCK`
p = 0.01 per day, `RATE_DECISION` on the 3rd Wednesday of each month) affect
`ΔM`. Kinds and jump sizes (the sign is fixed per kind; the magnitude is
uniform in the range):

| Kind | Jump J | Time of day | Follow-up |
|---|---|---|---|
| `EARNINGS_BEAT` / `EARNINGS_MISS` | ±3–8 % | PRE_OPEN | |
| `PROFIT_WARNING` | −8–20 % | any | +3 days drift of −J/4 spread over the days |
| `MAJOR_WIN` | +5–15 % | any | |
| `RUMOUR` | ramp to ±J/2 over 2 h | any | Resolves 1–5 business days later. `confirmed` (p from YAML, default 0.5) applies the remaining J/2; `denied` reverts the ramp over 1 h. |
| `MARKET_SHOCK` | ΔM −3–6 % | any | |
| `RATE_DECISION` | ΔM ±1–2 % | 14:00 local | |

- Informed traders apply the jump to their view `lead ~ U[0, 20] min` before
  publication.
- Scripted events (Appendix C) are added to the random ones and draw nothing
  from the seed.

### 13.2 Bus, storage and API

- `pm-populate` sends `news.publish`, and the engine republishes it as
  `news.{SYMBOL}` / `news.MARKET` (§6.5, Appendix B). The payload carries
  `headline`, `kind`, `magnitude_hint ∈ {SMALL, MEDIUM, LARGE}`, `rumour_id`
  and `resolution ∈ {"", CONFIRMED, DENIED}`. **It never carries the true
  jump.**
- `pm-stats` subscribes to `news.` and inserts into a new table
  `news_events(ts TEXT, symbol TEXT NULL, kind TEXT, headline TEXT,
  magnitude_hint TEXT, rumour_id TEXT NULL, resolution TEXT NULL)` with an
  index on (symbol, ts). This avoids relying on the audit trail (R4).
- `pm-api-gwy` adds `GET /api/v1/history/news?symbol=&from=&to=&limit=` in
  `routers/history.py`, following the `/trades` pattern.
- Headlines come from templates in `populate/model/news_templates.yaml`, e.g.
  `"{name} issues profit warning; sees FY revenue down {pct}%"`. `{name}` is
  the symbol.

---

## 14. Outputs and report

Everything is written under `DATA_PATH/populate/`, which `clear --all` must
also remove (add it to `NON_STATE_PATHS`):

| File | Content |
|---|---|
| `run.yaml` | args, seed, EduMatcher version, config `content_sha256`, business days, SIM gateway → archetype and parameters, MM bot count |
| `news.yaml` | every event with true J, publish time, informed lead, rumour resolution |
| `fair_value.csv` | §10.3 |
| `plan_summary.csv` | per day: planned orders, auction orders, cancels/amends, news count |
| `report.md` | per day: actual sends, accepted, rejected by code, SKIPs by reason, trades (from `trade.executed`), CB halts. Per symbol: open/close/high/low/volume, close vs model fair (tracking error). Stress: actions/s, latency p50/p95/p99/max for clock round trip, sync wait and ALF round trip; slowest day; ALF rate-limit retries. |

The console prints one progress line per day:
`2026-06-12  orders 5 132  trades 3 870  rej 41  1 820 act/s  ETA 00:21:14`.

---

## 15. Determinism contract

**Same seed, same config and same code produce identical** fair-value paths,
news, plans and the sequence of commands sent. In the engine they also
produce identical trades (symbol, price, qty, buy gateway, sell gateway, ts),
the same final positions per gateway, and the same final resting book (price,
qty, side, gateway per level). Order ids, ULIDs' random bits and real-time
log timestamps differ.

This holds because:

- every action is serialised by the barrier (§4.1);
- all business cadences run on sim time and engine flushes run only inside
  `clock.set` (§5.4);
- MM bots act only on bus input (§8);
- arrival priority is engine-sequenced (F5);
- the engine re-stamps order times (D29).

**Seed substreams**: EduMatcher has no numpy dependency, and none is added.
Every random stream is a stdlib `random.Random(substream_seed(seed, *names))`,
where `substream_seed` is
`int.from_bytes(sha256(f"{seed}|{'|'.join(names)}".encode()).digest()[:8], "big")`.
The stream names are `market`, `regime`, `news`, `assignment`, `traders|<GW>`,
and per day `volume|<date>` and `plan|<date>`. Because each day's plan has its
own stream, it does not depend on how many draws earlier days used.

**Conditions** (preflight warns if they're not met):

- `reopening_random_seed` is set (F13);
- every MM symbol has a reference price (§8 rule 5);
- no other client connects during the run (checked by preflight 1).

**Test**: WP-34 runs the same seed twice on s10 (3 days × 300 orders) and
compares the tuples above.

---

## 16. Performance budget

Per order slot there are three sequential round trips: `clock.set` → tick;
K × `clock.synced` (in parallel); ALF NEW → ACK.

| Item | Estimate (unmeasured) | Measured in WP-00 |
|---|---|---|
| ZMQ PUSH→engine→PUB round trip (Python) | 0.15–0.4 ms | |
| ALF TCP→gwy→engine→gwy→TCP round trip | 0.4–1.0 ms | |
| MM sync (K = 1) | +0.2 ms | |
| Per order slot | ≈ 1–1.6 ms | |
| Default run: 120 × (5000 + ~2000 cancel/amend + 5 transitions) | ≈ 0.85 M slots → **15–25 min** | |
| Audit volume per order slot | ≈ 1.5–2.5 KB → 1.3–2.1 GB total; 500 MB retained (D28) | |
| stats.db growth | order-event rows ≈ 3 M, trades ≈ 0.4 M → ~1 GB | |

The design does not change if these are off by 3×. If they're off by 10×,
the remedy is batching (O1).

---

## 17. Risk register (holistic review)

Each risk names its mitigation and the work package (WP, see the plan) that
must prove it. ✔ means fixed by design; ⚠ means a residual risk that is
accepted or monitored.

| # | Risk | Impact | Mitigation | WP |
|---|---|---|---|---|
| R1 ✔ | Static collar reference frozen at startup (F20) | Mass `STATIC_COLLAR_BREACH` after a few weeks of drift; history flattens | D25 re-reference at PRE_OPEN | 09 |
| R2 ✔ | EOD only at shutdown (F19) | 119 of 120 days without clearing marks, stats close book or index finalize | D25 EOD at CLOSED | 08 |
| R3 ⚠ | Clearing prunes raw rows older than 90 days | Oldest ~80 days of raw clearing rows gone | D27: prune by sim date; preflight warning; stats keeps every trade | 10 |
| R4 ⚠ | Audit rotation | Even at 100 MB × 5, the full history (1–2 GB est.) does not fit; audit-replay sees only the tail | D28; news history stored in stats; WP-00 measures bytes per slot so docs can state how many days survive | 11, 00 |
| R5 ✔ | Engine logs every NEW at INFO; the default profile uses `--verbose` | Log DB and stdout files grow by GBs; slows the run | D32: sim profile strips `--verbose` | 16 |
| R6 ⚠ | MM sync overhead with many bots or symbols | Run time multiplies | Measure in WP-00 with K = 1 and K = 4; O1 batching fallback | 00, 17 |
| R7 ✔ | ALF idle timeout 30 s, 100 cmds/s, 64 connections | Sessions dropped mid-run | Keepalive PING, RATE_LIMITED retry, preflight on the connection count | 22, 20 |
| R8 ⚠ | Timezones: the schedule is local; stats and clearing default to UTC | A session crossing UTC midnight splits days in stats/clearing | Preflight warns if any schedule time, converted to UTC, falls on a different date than its local date for the run's span. Docs. | 20 |
| R9 ⚠ | Gap between `--to` and class day | History ends days before class, with no trading in between | Docs: run it the day before; `--to` defaults to yesterday. Report states the last sim date. | 36 |
| R10 ✔ | Dynamic collar ±2 % and CB halts block news jumps | Rejects; prices lag fair value | Pricing clamps (§11.4); halt gate; calibration acceptance of the tracking error | 30, 35 |
| R11 ⚠ | CB reopen RNG unseeded | Same-seed runs diverge after the first halt | Preflight warning; determinism test config sets the seed | 20, 34 |
| R12 ✔ | Crash mid-run leaves partial history | Confusing state | `finally` stop; exit 1 with "data is partial: run pm-opctl-cli clear --all"; no resume in v1 | 24 |
| R13 ✔ | pm-populate killed (SIGKILL) leaves the stack running in sim mode; the next `start` says "already running" | Class starts on a sim clock | Engine sim banner; `pm-opctl-cli list` shows `EDU_CLOCK` (small add); docs troubleshooting: `pm-opctl-cli stop` | 16, 36 |
| R14 ✔ | `EDU_CLOCK` leaks into a normal shell | Real stack starts in sim mode | Only set inside pm-populate's own process env; engine banner; SIM connect gate makes misuse visible | 01, 06 |
| R15 ⚠ | Disk: audit 500 MB + stats ~1 GB + fair_value.csv | Disk full | Preflight warns if free space on `DATA_PATH` < 3 GB; `close` default for the CSV | 20 |
| R16 ✔ | GTC orders pile up over 120 days | Huge books on day 1; slow snapshots | §11.5 hygiene plus acceptance thresholds | 31, 35 |
| R17 ✔ | Snapshot/ACE flush between ticks races MM reactions | Non-determinism | §5.4: those flushes run only in `clock.set` in sim mode | 06, 34 |
| R18 ✔ | ULIDs on the wall clock while event ts is sim | audit-replay ordering and time display inconsistent | §5.2 rule 5 | 03 |
| R19 ✔ | alf-gwy stamps orders with a stale tick | Non-deterministic order ts | D29 engine re-stamp | 06 |
| R20 ✔ | Invalid transition silently dropped (F16) | pm-populate waits forever | `wait_state` timeout → fatal with the state pair in the message | 21 |
| R21 ⚠ | Price discovery doesn't track fair value (weak informed flow, MM quotes anchoring) | Unrealistic history | Calibration WP with numeric acceptance (median close tracking error < 3 %, 90th percentile < 8 %); tune archetype weights | 35 |
| R22 ✔ | Self-match within one SIM trader | SMP cancels counted as noise | D33 `CANCEL_RESTING`; report counts | 12 |
| R23 ⚠ | `pm-index` history under sim: INIT stamped at the sim start | Index history begins at day 1, which is correct; on class day `default_from` is 30 real days | Accept; documented | — |
| R24 ✔ | Config without SIM gateways, or old artifact | Confusing failure | Preflight 3 and 5 with remedies | 20 |
| R25 ⚠ | Real-mode behaviour change from D25 (EOD at CLOSED, collar re-reference) | Existing tests and docs assume shutdown-only EOD | Called out in CHANGELOG; WP-08/09 update tests and docs | 08, 09 |
| R26 ✔ | Class-day `_restore_gtc` uses "today" | Wrong DAY-staleness check | Uses `clock.today()` (real on class day) | 03 |
| R27 ⚠ | Students could fill against SIM GTC orders priced at a stale fair value from the last sim day | Free money for the first student | Accepted; it is realistic (stale limit orders exist). §11.5 caps age. | — |

---

## 18. Open items

- **O1. Batching if WP-00 shows the slot cost > 5 ms.** One `clock.set` per
  run of consecutive slots within the same sim millisecond. This is designed
  but not built unless needed.
- **O2. MM gateway history (was O11).** MM bots quote through the whole run,
  so MM gateways arrive at class with history and positions. The
  recommendation is to keep them. Pending Johan's confirmation; no code
  impact either way.
- **O3. News pane design** (separate doc): consumes `news.*` live and
  `/history/news`.

---

## Appendix A — wall-clock call-site inventory

Category per §5.1: **B** business → `clock.now_*`/`today`; **C** cadence →
`clock.cadence_s()`; **O** operational → unchanged, added to the lint
allowlist with this table as the justification. "Client" means a CLI or
display tool that never runs in the sim stack.

| File | Sites | Category | Note |
|---|---|---|---|
| models/clock.py | 1 | — | the source itself |
| models/envelope.py `new_ulid` | 1 | B | F3 |
| models/message.py index factories (5× `ts_ns=time.time_ns()`) | 5 | B | |
| models/message.py log renew/unsubscribe/status (3× `time.time()`) | 3 | O | log protocol |
| engine/main.py `_weekly_schedule_wire`, `_restore_gtc` | 2 | B | `today()` |
| engine/main.py `_flush_snapshots`, `_flush_auction_indicative` throttles | 2 | C | `time.monotonic()` today |
| engine/main.py debug / maintenance / persistence monotonic | rest | O | |
| stats/main.py feed-gap row, symbol upsert, snapshot ts, order-event ts, `_on_book`, `_on_eod`, missing-ts fallbacks (×2) | 8 | B | |
| stats/main.py price-snapshot interval (monotonic) | 1 | C | F7 |
| clearing/store.py `date('now')` (×2), clearing/cli.py (×1) | 3 | B | §6.3 |
| clearing/main.py flush interval monotonic | 2 | O | EOD forces a flush |
| index/main.py history ts (×4), state `last_updated`, history request defaults (×2) | 7 | B | |
| index/main.py publish throttle (monotonic) | 1 | C | F8 |
| audit/main.py receipt ts | 1 | B | |
| audit/main.py flush timer | 2 | O | |
| audit/indexer.py, audit/replay/* | 3 | Client | |
| api_gateway bootstrap `today`, history `session_date`, history `now` | 3 | B | |
| api_gateway events.py `now_iso` | 1 | B | envelope timestamp |
| api_gateway caches.py retention | 2 | O | in-memory cache eviction |
| alf_gwy PONG/HB TS | 2 | O | |
| ralf_gateway TS on lines (×6) | 6 | O | session-level timestamps |
| ralf_gateway trade TS fallback (line ~462) | 1 | B | |
| md_gateway snapshot `TS`, HB | 2 | O | |
| md_gateway `_event_ts` fallbacks (×3) | 3 | B | |
| dc_gateway PONG/HB/idle | 3 | O | |
| balf_gwy/codec.py `now_ns` | 1 | B | |
| log_srv/*, logclient/* | 20 | O | logs are operational by definition |
| scheduler/main.py | 6 | O | excluded in sim |
| alf_console, viewer, board, orders, ticker, *_spy, log_cli, index/cli, index/admin_cli, calf_client, config_deploy, config_show | ~25 | Client | |

WP-02's lint test lists every O and Client site explicitly, as file plus
function name. A new wall-clock call anywhere else fails the test.

---

## Appendix B — new messages

All of these go into `spec/messages/` and are generated with
`pm-msgen generate`, which also regenerates
`docs/user-guide/270-message-reference.md`.

```yaml
# spec/messages/system.yaml (append)
  - name: clock_set
    topic: "clock.set"
    transport: [engine_push]
    doc: { motivation: "pm-populate to engine: move sim time to ts_ns (sim mode only).",
           published_by: [populate], since: "1.x" }
    fields:
      - { name: ts_ns, type: int, validate: { min: 0 } }

  - name: clock_tick
    topic: "clock.tick"
    transport: [engine_pub]
    doc: { motivation: "Engine to all: sim time is now ts_ns. Published after timers and
           snapshot flushes for that instant.", published_by: [engine], since: "1.x" }
    fields:
      - { name: ts_ns, type: int }

  - name: clock_sync
    topic: "clock.sync"
    transport: [engine_push]
    doc: { motivation: "MM bot to engine: everything triggered up to tick ts_ns has been sent.",
           published_by: [mm_bot], since: "1.x" }
    fields:
      - { name: gateway_id, type: string, validate: { max_len: 32 } }
      - { name: ts_ns, type: int }

  - name: clock_synced
    topic: "clock.synced"
    transport: [engine_pub]
    doc: { motivation: "Engine relay of clock.sync for pm-populate.", published_by: [engine], since: "1.x" }
    fields:
      - { name: gateway_id, type: string, validate: { max_len: 32 } }
      - { name: ts_ns, type: int }

# spec/messages/news.yaml (new file)
  - name: news_publish
    topic: "news.publish"
    transport: [engine_push]
    fields: &news_fields
      - { name: symbol, type: string, required: false, omit_when_empty: true, validate: { max_len: 16 } }
      - { name: kind, type: string, validate: { max_len: 32 } }
      - { name: headline, type: string, validate: { max_len: 200 } }
      - { name: magnitude_hint, type: string, validate: { max_len: 8 } }   # SMALL|MEDIUM|LARGE
      - { name: rumour_id, type: string, required: false, omit_when_empty: true, validate: { max_len: 32 } }
      - { name: resolution, type: string, required: false, omit_when_empty: true, validate: { max_len: 16 } }
  - name: news_item
    topic: "news.{symbol}"          # symbol "MARKET" for market-wide items
    transport: [engine_pub]
    fields: [ *news_fields, { name: ts_ns, type: int } ]
```

The exact YAML keys must follow the existing spec conventions. The generator
is the authority, and WP-05 adapts the sketch to it.

---

## Appendix C — scenario YAML schema

```yaml
market:     { mu_annual: 0.06, sigma_annual: 0.15, calm_days: 25, stressed_days: 5, stressed_mult: 2.0 }
symbols:
  ACME:     { beta: 1.3, sigma_annual: 0.40, tier: 1 }   # tier 1..3 (weights 3:2:1)
news:       { random: true, rate_per_symbol_day: 0.05, rumour_confirm_prob: 0.5,
              market_shock_prob_day: 0.01, rate_decisions: true }
auctions:   { open_share: 0.03, close_share: 0.05 }
archetypes: { noise: 30, momentum: 15, value: 15, informed: 5, institutional: 10, day_trader: 25 }
traders:
  SIM07:    { archetype: institutional, symbol_focus: [ACME], risk_limit: 200000 }
gtc:        { max_age_days: 10 }
events:
  - { date: 2026-06-12, time: "10:30", symbol: ACME, kind: PROFIT_WARNING, jump_pct: -15 }
  - { date: 2026-07-03, time: "11:00", symbol: BETA, kind: RUMOUR, jump_pct: 10,
      resolve: { date: 2026-07-07, time: "09:45", outcome: DENIED } }
```

Validation errors include:

- unknown top-level key;
- unknown symbol or gateway;
- a gateway that is not SIMULATOR;
- weights that don't sum to > 0;
- an event date that is not a business day in the run;
- an event time outside PRE_OPEN..CLOSED;
- a rumour resolve date before the event;
- `kind` not in §13.1;
- an event jump where the kind's sign disagrees.
