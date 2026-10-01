Version: 0.3.0

Date: 2026-10-01

Status: Design proposal — not implemented. Replaces the v0.1 draft (REST-based) in full.
v0.3: second interview round. Adds dedicated SIMULATOR traders, MM clock sync, auction flow, scripted events and a news pane; open items O1–O9 resolved.

# EduMatcher — Exchange History Generator (`pm-populate`)

---

## 1. Purpose

Before a class session the instructor wants an exchange that looks as if it has
been running for months: price history with trends, shocks and rumours, daily
stats, audit trail, clearing positions and P&L per trader, and resting GTC
orders in the book. `pm-populate` produces this by starting the existing
exchange (in `DATA_PATH`) in **sim-clock mode**, then replaying N past business
days at accelerated pace. Each order goes through `pm-alf-gwy` under a dedicated
**simulation trader** (role `SIMULATOR`) at a backdated timestamp. Student desks
are never used: students start class with clean positions.

Secondary purpose: a long, heavy, end-to-end **stress test** of the whole stack.

### 1.1 Non-goals

- Not a real-time background trader during class (that is `pm-ai-trader` /
  `pm-mm-bot`).
- Not an append tool: it only ever builds history on a clean exchange.
- No backwards compatibility with data produced before the sim clock exists.

---

## 2. Settled decisions

| # | Topic | Decision |
|---|---|---|
| D1 | Order entry | Through `pm-alf-gwy`: one TCP session per `SIMULATOR` gateway. `pm-populate` is also on the ZMQ bus for clock control, market data and the news feed. |
| D2 | Fake time | Bus-driven **sim clock**. Every process reads business time through one `Clock` abstraction; in sim mode `pm-populate` sets it. |
| D3 | Period | `--from/--to` date range, or `--days N`, which ends yesterday. Business days only (Mon–Fri minus the engine's holiday calendar). |
| D4 | Volume | Target is **average orders per business day** (`--avg-orders`, default 5000). The trade count is whatever the flow produces. |
| D5 | Default history | `--days 120` (about 6 calendar months). |
| D6 | Phase 1 / Phase 2 | Phase 1 fixes *time, trader, symbol, side, order type, intent*. Phase 2 sets *price and qty* at send time from fair value and the live book. |
| D7 | Market model | fair value = market factor × beta + idiosyncratic random walk + jump events (news, rumours). |
| D8 | News | Written to a news log file in `DATA_PATH` **and** published on the bus as a new `news.*` topic. |
| D9 | Personalities | Archetypes are assigned by seed with weights. An optional populate YAML can pin individual traders. |
| D10 | Market makers | The profile's `pm-mm-bot`s run alongside. In sim mode they refresh on `clock.tick` by sim time, and `pm-populate` waits for their sync acks (§4.5). |
| D11 | Order types | `--order-types`, default `MARKET,LIMIT,ICEBERG`. Optional: `IOC`, `FOK`, `STOP`, `STOP_LIMIT`, `OCO`, `GTC`, `GTD`. |
| D12 | Lifecycle | Traders cancel and amend their resting orders. Cancels and amends are *extra* messages on top of `--avg-orders`. DAY orders expire at EOD. |
| D13 | Existing data | Refuse to run unless `DATA_PATH` has no trading state (`pm-opctl-cli clear --state` first). |
| D14 | Pacing | Strictly sequential: set clock → send → await ack → next. `--max-rate` is an optional cap. |
| D15 | Intraday shape | U-shaped intensity plus activity bursts after news on a symbol. |
| D16 | End state | After yesterday's EOD, stop the stack via opctl. The next normal start runs on the real clock. |
| D17 | Who trades | Only dedicated simulation traders. Student desks (TRADER) and MM gateways are never driven by `pm-populate`. Students start with clean positions. |
| D18 | Sim trader identity | New gateway role **`SIMULATOR`**. config-gen adds `SIM01..SIMnn`. The engine accepts a `SIMULATOR` login **only in sim-clock mode**. GUIs filter these gateways out of student-facing desk lists. |
| D19 | Sim trader count | Default `max(20, n_symbols // 3)` (50 for s150, 20 for s10). Overridden with config-gen `--sim-traders N`. |
| D20 | Carry-over | `SIMULATOR` gateways use `disconnect_behaviour: LEAVE_ALL`, so their GTC orders survive the last EOD and shutdown. Students meet real depth on day 1. |
| D21 | Class day | Sim traders are dormant: gateways and history are kept, but they can't connect in real-clock mode. Their resting GTC orders can still be filled by students, and clearing books those fills against them. |
| D22 | Auctions | Phase 1 plans dedicated auction-call flow for the opening and closing auctions on every day. |
| D23 | Scheduler | `pm-scheduler` is excluded from the sim profile. `pm-populate` sends transitions using the scheduler's functions. |
| D24 | v1 scope | In: scripted instructor events in the scenario YAML, and a news pane in trader-gui and terminal-gui (separate design). Out: corporate actions. |

---

## 3. Architecture

```
                       ┌──────────────────────── pm-populate ───────────────────────┐
                       │ Planner (Phase 1) │ Market model │ Personalities │ Report  │
                       │ Sequencer (Phase 2) ── clock ctl ── ALF session pool       │
                       └───────┬──────────────────┬───────────────────┬─────────────┘
              ALF/TCP (1 per   │      ZMQ PUSH:   │ CLOCK_SET,        │ ZMQ SUB: book.*,
              SIMxx gateway)   │      SESSION transitions, NEWS       │ trade.*, clock.*
                               ▼                  ▼                   │
                         pm-alf-gwy ──────▶   pm-engine  ─── PUB ─────┴──▶ clearing, stats,
                                                 ▲                           audit, index,
                                   pm-mm-bot(s) ─┘                           md/ralf/dc gwys
```

- `pm-populate` is the **time master** while it runs. The engine is the
  **time authority**: it applies `CLOCK_SET`, then republishes `clock.tick` on
  its PUB socket *before* any event stamped with the new time. ZMQ PUB keeps
  per-socket ordering, so every subscriber sees the clock move before the
  events that depend on it.
- Session transitions (PRE_OPEN → opening auction → CONTINUOUS → closing
  auction → CLOSED, EOD) are sent by `pm-populate` at the sim times from the
  engine's resolved schedule. `pm-scheduler` is **not** started in the sim
  profile: it sleeps on wall-clock time and would fight the sim clock. The
  transition-sending code is reused from `scheduler/main.py`, not copied.

---

## 4. The sim clock

This is the largest change and touches every process.

### 4.1 Two kinds of time

| Kind | Today | Under sim mode |
|---|---|---|
| **Business time**: event timestamps, trading date, EOD, GTD/DAY expiry, CB `resume_at_ns`, settlement dates, retention ages, file and partition names | `time.time_ns()`, `time.time()`, `datetime.now()`, `date.today()`, `now_ns()` | **Sim clock** |
| **Interval time**: debug summaries, flush cadence, socket timeouts, ALF rate tokens, MM refresh loop | `time.monotonic()` | **Unchanged** (real) |

The rule: anything that ends up *in data*, or decides *which day it is*, uses
the `Clock`. Anything that only paces a loop stays monotonic.

### 4.2 `models/clock.py`

- Keep `now_ns()` as the single business-time source, with the same
  strict-monotonic guarantee. Add `today()` and `now_dt(tz)`, both derived from
  it.
- Add a process-wide source switch: `real` (default) or `sim`. In `sim` the
  base is the last applied `clock.tick` value instead of `time.time_ns()`.
  Between ticks the clock **does not advance**; the monotonic +1 ns rule still
  orders events stamped at the same tick.
- Sim mode is selected by the process profile (an env var set by opctl, e.g.
  `EDU_CLOCK=sim`). It is never auto-detected.
- Every direct `time.time*/datetime.now/date.today` call for business time is
  replaced. A lint check (a flake8 plugin or a grep test) forbids new ones
  outside `clock.py`.

### 4.3 Clock protocol

- `CLOCK_SET {ts_ns}` is an ADMIN command on the engine PULL socket. It is
  rejected unless the engine runs in sim mode, and rejected if `ts_ns` is not
  after the current sim time.
- The engine applies the new time, **evaluates its timers** (CB reopen, GTD
  expiry, and any other `resume_at`-style deadlines), publishes `clock.tick`,
  then acks. `pm-populate` does not send the next order until the ack arrives.
- Downstream processes use the **event's own timestamp** for business dates
  (e.g. stats `trading_date(trade.ts_ns)`) wherever an event carries one. They
  follow `clock.tick` only for timestamps they create themselves (connect/
  disconnect events, snapshots, rollups).

### 4.4 Step 0: spike

Before building, list every business-time call site (about 40 files today:
engine, stats, clearing, index, log_srv, gateways, api_gateway, audit, …) and
classify each as business or interval time. The spike's output is a table
appended to this doc. Known hot spots include `engine/main.py` `datetime.now().date()`
(schedule resolution), `stats/main.py` `time.time()` (trading date), and
`stats` snapshot timestamps.

### 4.5 MM bots under the sim clock

In real mode, `pm-mm-bot` refreshes quotes on a monotonic interval. A sim day
can last only seconds of real time, so unchanged bots would quote a handful of
times per sim day, and same-seed runs would not be trade-identical. In sim
mode:

- The bot subscribes to `clock.tick`. On each tick it runs its normal refresh
  decision with **sim time** as "now": refresh if the sim time since its last
  refresh is at least its interval, or if its normal triggers fire (fill,
  book move).
- After handling a tick, including any quote it sent and the engine's ack, the
  bot publishes `mm.sync {gateway_id, tick_ts_ns}`.
- `pm-populate` knows the MM gateways in the profile. After each `CLOCK_SET`
  ack it waits for one `mm.sync` per MM bot before sending the next order.
  A missing sync after a timeout (default 2 s real time) aborts the run with
  the bot named. Silently continuing would make the run non-deterministic.
- Cost: one sync message per bot per tick. It is measured in the Phase-A
  spike. If it dominates, `pm-populate` can batch: one `CLOCK_SET` covers
  several slots in the same millisecond.

---

## 5. Run flow

```
preflight → start stack (sim profile) → set clock to day 1 PRE_OPEN
  → for each business day: plan (P1) → drive day (P2) → EOD
  → stop stack → write report
```

### 5.1 Preflight (fails fast, changes nothing)

1. The stack is not running (`pm-opctl-cli health -q` reports not running).
2. `DATA_PATH` has no trading state. Otherwise exit with a message that
   names `pm-opctl-cli clear --state`.
3. Load the compiled config: symbols (tick grid, collars, `order_limits`,
   reference prices), gateways with roles and ALF credentials, the engine
   schedule, the holiday country and the CB config.
4. There is at least one `SIMULATOR` gateway. Otherwise exit and say to
   regenerate the config with config-gen, which adds them by default (D19).
5. Resolve the business-day list. Fail if empty or if `--to` ≥ today.
6. Validate the scenario YAML: unknown symbols or gateways, and scripted
   events outside the period, are errors.
7. Build personalities and the market model from `--seed` (+ YAML).

### 5.2 Start

`pm-opctl-cli start <profile>` with the sim profile (`EDU_CLOCK=sim`, no
`pm-scheduler`, ALF `max_commands_per_second` raised, see §11). Wait until
`health` is green, then send `CLOCK_SET` to day 1 at PRE_OPEN − 1 min. Then
open one ALF session per `SIMULATOR` gateway. The engine accepts these
logins because it runs in sim mode (D18).

### 5.3 Per business day

**Initialisation**: the symbols and traders available *today*, excluding
halted symbols and traders whose personality sits this day out.

**Phase 1: plan**

1. Draw `N_d ~ Poisson(avg_orders × day_factor)`. `day_factor` is lognormal
   (σ≈0.25) and raised on news days.
2. Draw `N_d` strictly increasing timestamps in CONTINUOUS. Use the U-shaped
   intensity (§8.2) plus news bursts, by thinning a non-homogeneous Poisson
   process. Ties are broken with +1 µs.
3. For each slot choose a symbol (weighted by liquidity tier and news), a
   trader (weighted by each personality's activity on that symbol), then side,
   order type and **intent** from that personality (§7). Price and qty stay
   open.
4. Add the day's news events, both random and scripted (§6.3), and each
   trader's planned cancel/amend sweeps as extra slots in the same timeline.
5. **Auction flow** (D22): plan `a_open·N_d` orders inside the opening-auction
   call and `a_close·N_d` inside the closing-auction call (defaults 3 % and
   5 %). These are LIMIT and MARKET orders for the auction, priced at send time
   around the overnight-gapped fair value (open) or the current fair value
   (close). Every symbol with any activity that day gets at least one buy and
   one sell, so every active symbol prints at the open and close. Auction
   orders count toward `N_d`.

**Phase 2: drive**

1. Send PRE_OPEN and the opening-auction transition at their schedule times.
   The planned opening-auction slots are sent between them, with the same
   clock→send→ack loop as below.
2. CONTINUOUS. For each slot in order:
   1. `CLOCK_SET(slot.ts)`, await ack.
   2. If it's a news slot: update fair value, publish `news.*`, append to the
      news log.
   3. Otherwise resolve the intent into a concrete order (§7.3) against the
      current fair value and the latest book snapshot, then send it via that
      trader's ALF session and await the ack. Rejects are logged with their
      reason and counted, and the run continues.
3. Closing auction (with its planned slots), CLOSED, then EOD: DAY orders expire, clearing and stats
   roll up for real because the clock crossed the boundary.
4. `CLOCK_SET` to the next business day's PRE_OPEN, skipping weekends and
   holidays.

### 5.4 Finish

After the last day's EOD, close the ALF sessions. `LEAVE_ALL` keeps the GTC
orders (D20). Then run `pm-opctl-cli stop`, and
write the report (§10). A normal `pm-opctl-cli start` afterwards runs on the
real clock, and today is the first live day after the history.

---

## 6. Market model (the "drivers")

The model produces each symbol's **fair value** `F_s(t)`. Traders never see it
directly. They see noisy or lagged versions of it according to their
personality (§7), and the order flow they produce moves the traded price
toward it. The traded price is an *emergent* result, not a plotted line.

### 6.1 Continuous part

Work in log-price, `x_s = ln F_s`, stepped per planned slot (Δt = time since
the previous slot):

```
x_s(t+Δt) = x_s(t) + β_s·ΔM + σ_s·√Δt·ε_s + J_s
ΔM        = μ_M·Δt + σ_M·√Δt·ε_M                (one shared market factor)
```

- `F_s(0)` is the config reference price (`last_buy/last_sell` midpoint, in
  display money).
- `β_s` (default U[0.6, 1.4]) and `σ_s` (default 25–45 %/yr idiosyncratic) are
  drawn per symbol by seed. Both can be overridden in the YAML.
- The market factor gives realistic co-movement, so an index (`pm-index`)
  computed over the history looks like an index.
- Overnight gap: an extra draw at PRE_OPEN with variance equal to that of
  about 1/3 of a trading day. Opening auctions then have something to discover.
- A slow volatility regime (2-state Markov, calm/stressed, ≈ monthly switching)
  multiplies all σ. This produces visible quiet and turbulent months.

### 6.2 Guard rails

- `F_s` is clamped so that the target price stays inside the symbol's static
  collar band relative to the *previous close*. The model may push into the
  band edge, but must not demand prices the engine will reject every time.
- Circuit breakers are allowed to fire. A big news jump that trips one is a
  feature: students can find it in the history.

### 6.3 Jump events (news)

Each business day, each symbol draws events from a Poisson with a low rate
(default ≈ 1 event per symbol per 20 days). Market-wide events affect `ΔM`.

| Event | Effect on fair value | Notes |
|---|---|---|
| `EARNINGS_BEAT` / `EARNINGS_MISS` | jump ±3–8 % | Placed in the quarterly reporting window (pre-open) if the period covers one |
| `PROFIT_WARNING` | jump −8–20 % | Often followed by a few days of drift (under-reaction) |
| `MAJOR_WIN` (contract, approval) | jump +5–15 % | |
| `RUMOUR` | drift toward ±J over hours | Resolved 1–5 days later: **confirmed** (the jump completes) or **denied** (it reverts). The probability is in the YAML. |
| `MARKET_SHOCK` | `ΔM` jump −3–6 % | Hits all symbols, scaled by β |
| `RATE_DECISION` | `ΔM` jump ±1–2 % | On fixed dates |

- Informed personalities learn of an event a short time *before* publication
  (default 0–20 min). This gives pre-news drift, which is a nice classroom
  discussion point.
- Each event raises that symbol's order intensity and widens passive offsets
  for a decaying period (§8.2).

**Scripted events (D24).** The scenario YAML can pin events by date, time,
symbol, kind and magnitude. For a rumour, it can also pin the resolution and
its date. Scripted events are added to the random ones. `news: {random:
false}` turns the random ones off, for a fully authored storyline. A scripted
event does not consume the seed, so adding one doesn't reshuffle the rest of
the history.

### 6.4 News output

- **Bus**: new `news.{SYMBOL}` and `news.MARKET` topics with `{ts_ns, kind,
  headline, symbol, magnitude_hint, rumour_id, resolution}`. The message is
  generated by `pm-msgen` like all others. Audit captures it.
- **File**: `DATA_PATH/populate/news.yaml`, a chronological list with the
  same fields plus the *true* jump size. This is for the instructor and is
  not shown to students.
- **Student view (D24)**: a news pane in trader-gui and terminal-gui shows
  `news.*` live, plus the history back to the first populated day. History
  comes from `pm-api-gwy` (backed by the audit store). The bus message carries
  only `magnitude_hint` (e.g. "large"), never the true jump size. The pane
  has its own design doc (`EduMatcher-News-Pane.md`, to be written).
- Headlines come from templates (`"{name} issues profit warning; sees FY
  revenue down {pct}%"`), so no free text is needed.

---

## 7. Trader personalities

### 7.1 Archetypes

| Archetype | Sees | Typical behaviour | Default order types (filtered by `--order-types`) |
|---|---|---|---|
| **Noise / retail** | Last price only | Random side, small size, often MARKET. Chases after big moves. | MARKET, LIMIT |
| **Momentum** | Price trend over the last k minutes and days | Buys strength, sells weakness, uses stops to exit | LIMIT (marketable), STOP, STOP_LIMIT |
| **Value / contrarian** | Fair value with a lag (days) | Places passive limits against deviations, patient, GTC | LIMIT, GTC |
| **Informed** | Fair value with little noise, news early | Few but well-timed aggressive orders. Hides size with icebergs. | LIMIT, ICEBERG, IOC |
| **Institutional** | Fair value with a lag | Works a large parent order over a day or several days in slices. Iceberg-heavy, VWAP-like timing. | ICEBERG, LIMIT |
| **Day trader** | Book and short-term trend | Many in/out round trips, flat by close, OCO take-profit/stop pairs | LIMIT, IOC, FOK, OCO |

When an archetype's preferred type is not in `--order-types`, it falls back
to the nearest allowed type: STOP→LIMIT, OCO→LIMIT, IOC→LIMIT, GTC→DAY.
Every archetype can trade with just the default `MARKET,LIMIT,ICEBERG`.

### 7.2 Parameters per trader

Each trader is assigned an archetype, then draws its own parameters from that
archetype's ranges. Two "momentum" traders therefore differ:

`activity` (share of the day's orders), `symbol_focus` (1–all symbols, Zipf
weights), `size_range`, `aggressiveness` (P(cross)), `passive_offset_ticks`,
`signal_noise`, `signal_lag`, `risk_limit` (max |position| per symbol),
`stop_loss_pct`, `cancel_horizon` (how long a resting order may live before
it is repriced or cancelled), `gtc_share`.

Assignment: archetype weights come from the YAML (default noise 30 %, momentum
15 %, value 15 %, informed 5 %, institutional 10 %, day trader 25 %). The
`SIMULATOR` gateways are shuffled by seed and filled to the weights. YAML `traders:` can pin an
archetype and any parameter for a named gateway.

### 7.3 Intent → order (Phase 2)

Phase 1 stores an **intent**: `{trader, symbol, side, type, urgency}`, where
`urgency ∈ {cross, touch, passive}`. At send time:

- **Price**: `cross` uses MARKET, or a LIMIT through the opposite best (capped
  by the collar). `touch` joins the best on its own side. `passive` uses the
  trader's view of fair value ± `passive_offset_ticks` plus noise. Prices are
  snapped to the tick grid and clamped into the collar.
- **Qty**: drawn from the trader's size distribution, clamped by
  `order_limits` and the trader's risk limit. This uses the trader's tracked
  position: `pm-populate` follows fills from ALF execution reports. If the risk
  limit forces the opposite side or a zero qty, the side is flipped or the
  slot is skipped.
- **Iceberg**: `VISIBLE` is 10–25 % of QTY, snapped to lot.
- **Empty book**: with no opposite side, `cross` degrades to `touch` at fair
  value. This prevents MARKET rejects on an empty book.

### 7.4 Cancel / amend

Each trader keeps its resting orders. At planned sweep slots, and when fair
value moved by more than the trader's tolerance, an order older than
`cancel_horizon` or further than X ticks from the trader's current target is
repriced (amend) or cancelled. These are extra slots, not counted in
`--avg-orders` (D12). Expected overhead: about 30–60 % extra messages,
depending on the mix. The report shows the exact figure.

### 7.5 End-of-history state

A share of value and institutional orders are GTC (when `GTC` is in
`--order-types`). Because `SIMULATOR` gateways use `LEAVE_ALL` (D20), these
orders survive the last EOD and the shutdown. The students' first live day
therefore opens on a book with real depth from "old" orders. When students
fill against them, the sim traders' positions move in clearing like any
counterparty's. Student desks start flat.

---

## 8. Volume and timing

### 8.1 Daily count

`N_d ~ Poisson(avg_orders × day_factor_d)`. `day_factor` is lognormal
(mean 1) × a news uplift. The mean of `N_d` over the run matches
`--avg-orders` within sampling error. The report shows target vs actual.

### 8.2 Intraday intensity

`λ(t) = base × U(t) × Π_events (1 + k·e^{−(t−t_e)/τ})`

- `U(t)` is U-shaped: about 2.5× at the open and 2× at the close relative to
  midday.
- Each news event adds a decaying burst on its symbol (default k=4,
  τ=20 min).
- Timestamps are sampled by thinning, sorted, and made strictly increasing.

### 8.3 Allocation across symbols

Each symbol gets a liquidity tier (by seed, or from the YAML) with Zipf-like
weights, so a few names are busy and some are thin. News multiplies a
symbol's weight for the burst duration.

---

## 9. Pacing and reproducibility

- **Sequential**: one outstanding request at a time (clock ack, then order
  ack). Throughput is bounded by the stack's round-trip latency. This is the
  stress-test measurement.
- `--max-rate N` caps orders per real second. It defaults to unlimited.
- **Seeds**: one `--seed` feeds separate substreams for the market model,
  planner, each trader and the news. Changing `--order-types` does not change
  the fair-value paths.
- **Determinism**: with MM bots synchronised to the clock (§4.5) and every
  message acked before the next, the same seed and the same config produce
  identical fair-value paths, news, orders, trades, positions and book
  contents. Only engine order IDs differ (`os.urandom`). A Phase-F test runs
  the same seed twice and compares trades.

### 9.1 Runtime estimate (to be measured)

120 days × 5000 orders ≈ 600 k orders, plus about 40 % cancels/amends, plus
one clock round trip per message. That is about 1.7 M round trips. At about
1 ms each this is about 30 minutes. The figure is unverified and is measured
in the Phase-A spike.

---

## 10. Output and report

`DATA_PATH/populate/`:

- `run.yaml`: CLI args, seed, version, config digest, resolved business
  days and personalities (trader → archetype and parameters).
- `news.yaml`: §6.4.
- `fair_value.csv`: per symbol, a fair value per minute. It lets the
  instructor plot "true value vs traded price".
- `report.md`: per day, target vs actual orders, trades, cancels and
  rejects by reason. Per symbol: OHLC, volume and CB trips. Stress figures:
  messages/s, ack latency p50/p95/p99/max per message type, and the slowest
  day.

The console prints a progress line per day: date, orders, trades, rejects,
messages/s and ETA.

---

## 11. Changes to existing components

| Component | Change |
|---|---|
| `models/clock.py` | real/sim source, `today()`, `now_dt()`, tick application |
| all processes | Business-time call sites go through `clock` (§4.4). Follow `clock.tick` in sim mode. |
| `models/participant.py`, cverifier layer 2/3 | New role `SIMULATOR`. cverifier requires `SIMULATOR` gateways to have `disconnect_behaviour: LEAVE_ALL`. |
| `pm-config-gen` | Adds `SIM01..SIMnn` (`max(20, n_symbols//3)`, `--sim-traders N`) to every generated config, with ALF credentials. Example configs in `docs/examples/ref_data` regenerated. |
| `pm-engine` | `CLOCK_SET` admin command, timer evaluation on clock advance, `clock.tick` publish. Schedule resolution uses `clock.today()`. **`SIMULATOR` logins are rejected in real-clock mode.** |
| `pm-mm-bot` | Sim mode: refresh driven by `clock.tick` in sim time, `mm.sync` after each tick (§4.5) |
| `pm-stats`, `pm-clearing`, `pm-index`, `pm-audit`, `log_srv` | Trading date from the event timestamp. Retention and pruning ages use the sim clock. |
| `msgen` specs | New `clock.tick`, `CLOCK_SET`, `mm.sync` and `news.*` messages |
| `pm-api-gwy` | News history endpoint (for the news pane) |
| trader-gui, terminal-gui, config-gui | News pane (separate design). `SIMULATOR` gateways hidden from desk pickers and student lists, but visible as counterparties where those are shown. |
| `pm-opctl-cli` | Sim profile: `EDU_CLOCK=sim`, no scheduler, ALF rate limit and `max_connections` sized for the sim traders. `pm-populate` drives it through `start/stop/health`. |
| `pm-alf-gwy` | No protocol change |
| `pm-scheduler` | Transition-sending functions exposed for reuse. The process itself is unchanged. |
| lint/test | A check that forbids raw wall-clock calls outside `clock.py` |
| docs | A user-guide chapter on preparing a class with `pm-populate`. `pm-help` entry. Config chapter covers the `SIMULATOR` role. |

---|---|
| `models/clock.py` | real/sim source, `today()`, `now_dt()`, tick application |
| all processes | Business-time call sites go through `clock` (§4.4). Follow `clock.tick` in sim mode. |
| `pm-engine` | `CLOCK_SET` admin command, timer evaluation on clock advance, `clock.tick` publish. Schedule resolution uses `clock.today()`. |
| `pm-stats`, `pm-clearing`, `pm-index`, `pm-audit`, `log_srv` | Trading date from the event timestamp. Retention and pruning ages use the sim clock. |
| `msgen` specs | New `clock.tick`, `CLOCK_SET` and `news.*` messages |
| `pm-opctl-cli` | Sim profile: `EDU_CLOCK=sim`, no scheduler, ALF rate limit raised. `pm-populate` drives it through `start/stop/health`. |
| `pm-alf-gwy` | No protocol change. Its `max_commands_per_second` is raised in the sim profile. |
| `pm-scheduler` | Transition-sending functions exposed for reuse. The process itself is unchanged. |
| lint/test | A check that forbids raw wall-clock calls outside `clock.py` |
| docs | A user-guide chapter on preparing a class with `pm-populate`. `pm-help` entry. |

---

## 12. CLI

```
pm-populate [--config NAME] (--days N | --from YYYY-MM-DD --to YYYY-MM-DD)
            [--avg-orders 5000] [--order-types MARKET,LIMIT,ICEBERG]
            [--seed INT] [--scenario populate.yaml] [--max-rate N]
            [--dry-run] [--log-level LEVEL]
```

- `--days` defaults to 120 and ends yesterday. `--to` must be before today.
- `--dry-run` runs preflight and Phase 1 for all days. It writes `run.yaml`,
  `news.yaml`, `fair_value.csv` and a planned-volume summary, without starting
  the stack. This is useful for tuning a scenario quickly.

### 12.1 Scenario YAML (all optional)

```yaml
market:     {mu_annual: 0.06, sigma_annual: 0.15, regime_switch_days: 25}
symbols:
  ACME:     {beta: 1.3, sigma_annual: 0.40, tier: 1}
news:       {random: true, rate_per_symbol_day: 0.05, rumour_confirm_prob: 0.5}
auctions:   {open_share: 0.03, close_share: 0.05}
archetypes: {noise: 0.30, momentum: 0.15, value: 0.15,
             informed: 0.05, institutional: 0.10, day_trader: 0.25}
traders:
  SIM07:    {archetype: institutional, symbol_focus: [ACME]}
events:                                   # scripted, in addition to random ones
  - {date: 2026-06-12, time: "08:30", symbol: ACME, kind: PROFIT_WARNING, jump_pct: -15}
  - {date: 2026-07-03, time: "11:00", symbol: BETA, kind: RUMOUR, jump_pct: 10,
     resolve: {date: 2026-07-07, outcome: denied}}
```

---

## 13. Implementation plan

| Phase | Content | Exit criterion |
|---|---|---|
| A | Step-0 spike: call-site inventory and a latency probe (1 k clock+order round trips, with and without MM sync) | Table in §4.4. Measured ms per round trip. |
| B | Sim clock across all processes, `CLOCK_SET`/`clock.tick`, the lint rule | Existing tests pass in real mode. A sim-mode test runs 2 days with hand-sent orders and gives correct trading dates in stats, clearing and audit. |
| C | `SIMULATOR` role: config-gen, cverifier, engine login gate, GUI filtering | Real mode rejects a `SIMULATOR` login. Sim mode accepts it. Example configs regenerated. |
| D | `pm-populate` skeleton: preflight, opctl start/stop, ALF pool, day loop with session transitions and auction flow, uniform noise flow | 5 days × 500 orders end to end on s10. Every day prints at the open and close. |
| E | MM bot clock sync (§4.5) | Same-seed runs give identical trades |
| F | Market model, random and scripted news (bus + file), `--dry-run` | fair-value plots look right. News is visible in audit. |
| G | Personalities, intent resolution, cancel/amend, risk limits, GTC carry-over | Reject rate < 2 %. Books stay bounded over 120 days. GTC orders present after restart. |
| H | Report, stress figures, docs, `pm-help` | Full default run on s150 |
| — | News pane (trader-gui, terminal-gui, api-gwy) | Separate design doc |

---

## 14. Resolved items (v0.3 interview)

| Item | Resolution |
|---|---|
| O1 MM bots and determinism | MM bots sync to the sim clock (§4.5, D10). Runs are fully deterministic. |
| O2 MM quoting under compressed time | Resolved by O1: refresh cadence is in sim time |
| O3 Auctions | Planned auction flow (D22) |
| O4 Scheduler | Excluded from the sim profile. `pm-populate` drives transitions (D23). |
| O5 Corporate actions | Out of v1 (D24) |
| O6 Student-facing news | News pane in v1, separate design (D24) |
| O7 Trader count | Dedicated sim traders, `max(20, n_symbols//3)` (D19) |
| O8 CANCEL_ALL wipes carry-over | `SIMULATOR` gateways use `LEAVE_ALL` (D20) |
| O9 Whose history | Separate `SIMULATOR` traders. Students start clean (D17). |

## 15. Open items

- **O10. MM sync overhead.** Phase A measures the cost of one `mm.sync` per
  bot per tick. If it is too slow, batch slots per `CLOCK_SET` (§4.5).
- **O11. MM obligations and history.** MM bots quote through the whole
  history, so their positions and P&L carry into class too. Should MM gateways
  also be reset, or kept? Students don't trade on them, so keeping them is
  harmless.
