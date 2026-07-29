Version: 1.0.0

Date: 2026-07-29

Status: Design Note (Informational — no action proposed)

# EduMatcher — Concurrency Model: `select()`/Threads/ZeroMQ vs. `asyncio`

## Table of Contents

- [1. Background](#1-background)
- [2. What the codebase actually does today](#2-what-the-codebase-actually-does-today)
- [3. Why this note exists](#3-why-this-note-exists)
- [4. Option A — Keep the current model](#4-option-a--keep-the-current-model)
- [5. Option B — Refactor every process to `asyncio`](#5-option-b--refactor-every-process-to-asyncio)
- [6. Risk assessment for a full refactor](#6-risk-assessment-for-a-full-refactor)
- [7. Recommendation](#7-recommendation)
- [8. Open questions](#8-open-questions)



## 1. Background

While implementing `pm-log-srv` (see `EduMatcher-log-srv.md`), the original
design draft (§7.3) assumed the new process would use "one `asyncio` task
per connection," reasoning by analogy with `api_gateway/engine_client.py`,
which does use `asyncio` in part. During implementation, inspecting the
actual reference implementation this feature was meant to mirror —
`md_gateway/gateway.py`, EduMatcher's CALF market-data gateway — showed
that it does not use `asyncio` at all. It uses a plain blocking-socket
accept loop multiplexed with `select.select()` in a single thread. That was
a genuine surprise: an outside observer reading `engine_client.py` in
isolation would reasonably guess `asyncio` was the house standard for
network I/O in this codebase. It is not. `pm-log-srv` was implemented to
match the actual precedent (`select()`-based, single-threaded, one extra
background thread for batched SQLite writes), not the design draft's
`asyncio` assumption, and the design doc was corrected to note this
deviation explicitly.

This note exists to document that finding properly: what the codebase
actually does, why it plausibly ended up this way, and what a deliberate,
wall-to-wall refactor to `asyncio` would cost and risk if anyone proposes
it later. It is informational — it does not propose doing the refactor.

## 2. What the codebase actually does today

A survey of every `pm-*` process entrypoint (33 total, per
`pyproject.toml`'s `[tool.poetry.scripts]`) finds three genuinely distinct
concurrency styles in use, plus one hybrid:

**A. Raw `socket` + single-threaded `select.select()` — 6 processes.**
This is the pattern for every TCP gateway that terminates external
(non-ZeroMQ) client connections: `pm-md-gwy` (`md_gateway/gateway.py`),
`pm-alf-gwy` (`alf_gwy/gateway.py`), `pm-ralf-gwy`
(`ralf_gateway/gateway.py`), `pm-dc-gwy` (`dc_gateway/gateway.py`),
`pm-balf-gwy` (`balf_gwy/gateway.py`), and now `pm-log-srv`
(`log_srv/server.py`). Each runs one non-blocking accept/read/write loop on
the main thread, calling `select.select(readable, [], [], 0)` once per
tick to find which sockets are ready. Where a process also needs
timer-driven background work that would otherwise block that loop on I/O —
`pm-log-srv`'s batched SQLite writes — it gets exactly one dedicated
`threading.Thread` for that specific job, not a thread per connection.

**B. ZeroMQ + `zmq.Poller()`, single-threaded — roughly 15 processes.**
The engine itself, and most of the bus-attached processes (`pm-engine`,
`pm-orders`, `pm-ticker`, `pm-stats`, `pm-audit`, `pm-clearing`, `pm-board`,
`pm-viewer`, `pm-index`, `pm-ai-trader`, `pm-ai-swarm`, `pm-mm-bot`,
`pm-alf-console`, `pm-commands`/`pm-admin`), use `zmq.Poller()` as their
main-loop dispatcher: a single thread blocks on `poller.poll(timeout)` and
dispatches whichever ZeroMQ sockets became readable. This is architecturally
the same shape as (A) — one thread, one multiplexed wait — just using
ZeroMQ's own poller instead of the stdlib's. No file in `src/` imports
`zmq.asyncio`; the async ZeroMQ integration pyzmq ships is simply not used
anywhere.

**C. Blocking client sockets on a dedicated background thread — widespread,
paired with (A) or (B).** Many of the same processes above additionally run
one fixed background `threading.Thread` for a specific narrow job: a ZMQ
receive loop that hands parsed messages back to the main thread via a queue
or callback (`audit/main.py`, `stats/main.py`, `orders/main.py`,
`ticker/main.py`), a heartbeat/ping thread (`ralf_spy/client.py`,
`calf_spy/client.py`), or the batched-writer pattern `pm-log-srv` itself
uses. This is one thread per *responsibility*, never one thread per
*connection* — the connection-handling itself always stays inside a single
`select()`/`zmq.Poller()` loop.

**D. `pm-api-gwy` — genuine hybrid, and the only real `asyncio` user.**
`api_gateway/main.py` runs FastAPI under `uvicorn`, so the process itself
does have a real `asyncio` event loop (`asyncio.get_running_loop()` is
called once, in the FastAPI `lifespan` context, to capture a loop handle).
But the ZeroMQ side of that process (`engine_client.py`, `index_client.py`)
is not `async def`/`await`-driven I/O — it is exactly pattern (C): a
background thread blocks on `zmq.Poller().poll()`, and results are handed
into the asyncio loop via `loop.call_soon_threadsafe(...)`. So even the one
process that legitimately runs an event loop does not use `asyncio` for its
own socket I/O — only for serving HTTP/WebSocket requests, which is what
FastAPI/uvicorn require. `docs-design/EduMatcher-ALF-API-Gwy2.md` describes
this design accurately (a "SUB reader (daemon)" thread bridging into the
event loop via `call_soon_threadsafe`, with an `asyncio.Queue(maxsize=256)`
for backpressure); it does not describe the ZMQ side as "asyncio", though a
skim of the client-module names alone can suggest otherwise, which is
presumably how the earlier `pm-log-srv` draft's assumption arose.

**Tally:** of 33 entrypoints, roughly 6 fall into (A), ~15 into (B), most of
those additionally using (C) for one or two background jobs, 1 (`pm-api-gwy`)
is the (D) hybrid, and the remainder are lighter CLI/spy/config tools with
minimal or client-only threading.

## 3. Why this note exists

Nothing is broken today. This note is not a response to a defect — it is
the natural follow-up to having been surprised once by an incorrect
assumption about a house pattern, and wanting a durable, citable answer the
next time someone (human or another design pass) assumes "this codebase
uses `asyncio`" and reaches for it by default. The short answer, worth
stating plainly: **it doesn't, except for HTTP/WebSocket serving in
`pm-api-gwy`.** Every process that owns raw sockets or ZeroMQ sockets
multiplexes them with a single-threaded, callback-free poll loop
(`select()` or `zmq.Poller()`), falling back to one fixed background thread
per distinct blocking responsibility where needed.

## 4. Option A — Keep the current model

**Pros**
- Consistency: 32 of 33 processes already share one of two closely related
  shapes (`select()`-loop or `zmq.Poller()`-loop, both single-threaded, both
  using the same "one thread per responsibility, not per connection"
  escape hatch). A new process copying an existing sibling gets the pattern
  right by construction, as `pm-log-srv` did once corrected.
- No new dependency on the interpreter's asyncio scheduler semantics
  (cancellation, task groups, `loop.call_soon_threadsafe` bridging) beyond
  the one process that already needs it for FastAPI.
- Debuggability: a `select()`/`zmq.Poller()` loop's entire state is visible
  in one stack frame with `pdb`; there is no hidden event-loop scheduler
  interleaving callbacks from unrelated tasks.
- The existing test suites, house style, and onboarding material (design
  docs, docstrings, `docs/user-guide/170-processes.md`) are all written
  against this model. Nothing needs to change to keep teaching it
  correctly.

**Cons**
- Two nearly-but-not-quite-identical poll primitives exist side by side
  (`select.select()` for raw-socket gateways, `zmq.Poller()` for bus
  processes) rather than one. A newcomer has to learn both, even though
  they're conceptually the same idea.
- Blocking background threads (pattern C) introduce real cross-thread
  hazards — shared mutable state, GIL-released blocking calls, and the
  need for queues/locks at every boundary — that a single-threaded
  `async`/`await` continuation would not have. `pm-log-srv`'s own writer
  thread, for instance, requires an explicit lock around the SQLite
  connection and a bounded queue with documented backpressure behavior;
  under `asyncio` this could arguably collapse into an `async with
  aiosqlite` pattern with no cross-thread lock at all — at the cost of
  swapping `sqlite3` for `aiosqlite`.
- `select()` has a well-known scalability ceiling (historically ~1024 file
  descriptors on many platforms, and O(n) per-call overhead as fd count
  grows). Every current process's connection count is small (single-digit
  to low-hundreds of gateway/bus clients in a teaching/simulation
  deployment), so this ceiling is nowhere close to being hit, but it is a
  latent limit that `asyncio`'s underlying selector abstraction (which can
  transparently use `epoll`/`kqueue`) does not share in the same way.

## 5. Option B — Refactor every process to `asyncio`

Hypothetically: rewrite all 33 entrypoints so that every gateway's
socket-handling loop and every bus process's ZeroMQ handling runs as
`async def` coroutines under one `asyncio` event loop per process,
presumably using `asyncio.start_server`/`asyncio.open_connection` for the
six raw-socket gateways and `zmq.asyncio.Context`/`Poller` for the ZeroMQ
side.

**Pros**
- A single, consistent concurrency idiom across the entire codebase — one
  way to write "wait for the next thing to happen," not two.
- Eliminates most of the background-thread-plus-queue plumbing in pattern
  (C): a blocking ZMQ receive or a batched DB write could become an
  `await`-able coroutine directly inside the same loop that handles
  network I/O, removing several `threading.Thread`/`queue.Queue`/lock pairs
  codebase-wide (e.g. `log_srv/writer.py`'s `WriterThread`, every
  `*/main.py`'s `Thread(target=self._receive, ...)`).
  `zmq.asyncio` exists specifically to make this substitution
  straightforward for the ZeroMQ side.
- Timeouts, cancellation, and "run N things concurrently and wait for the
  first/all to finish" become first-class language features
  (`asyncio.wait_for`, `asyncio.gather`, `asyncio.TaskGroup`) instead of
  hand-rolled deadline/`select()`-timeout arithmetic (see `log_srv/writer.py`'s
  `_drain_and_write`, which manually computes a `deadline` and subtracts
  `time.monotonic()` — the kind of code `asyncio.wait_for` exists to
  replace).
  `pm-api-gwy` would no longer be the only process with a "real" event
  loop and could drop its `call_soon_threadsafe` bridge entirely, since its
  ZMQ client could become a normal awaited coroutine in the same loop
  serving HTTP requests.

**Cons**
- This is a rewrite of the concurrency core of every long-running process
  in the system, not an incremental change. Every gateway's accept/read/
  write loop, every bus process's message-dispatch loop, and every
  currently-synchronous helper function called from inside those loops
  (SQLite queries, file I/O, `time.sleep`) would need to become
  non-blocking or be wrapped in `run_in_executor`/a thread pool — otherwise
  a single slow synchronous call anywhere silently stalls the entire
  process, which is a materially worse failure mode under `asyncio` than
  under the current model (a blocked thread in the current model only
  stalls that one thread's responsibility, not the whole process).
- `sqlite3` (used by `pm-stats`, `pm-audit`, `pm-clearing`, `pm-log-srv`,
  and their CLIs) has no native async driver in the stdlib; every DB call
  in an async rewrite either needs `aiosqlite` (a new dependency, different
  API surface, different failure modes) or must be pushed onto a thread
  pool via `loop.run_in_executor`, which reintroduces the exact
  cross-thread boundary the rewrite was meant to remove, just with extra
  indirection.
- `zmq.asyncio` changes ZeroMQ's own recv/send calls into coroutines but
  does not change the semantics of ZeroMQ socket types (REQ/REP, PUB/SUB,
  ROUTER/DEALER) — all existing message-flow design docs
  (`EduMatcher-Market_Data_Protocol.md` and friends) remain valid, but every
  call site touching a ZMQ socket in all ~15 bus processes still has to be
  located, converted, and re-tested.
- Signal handling (SIGINT/SIGTERM) already has at least one documented
  subtlety under the current model — `viewer/main.py:587` notes that
  `zmq.Poller.poll()` is interrupted by SIGINT, which the code relies on
  for clean shutdown. `asyncio`'s own signal handling
  (`loop.add_signal_handler`) is a different mechanism with different
  cross-platform guarantees (notably weaker on Windows, irrelevant here
  since this is POSIX-only, but still a fresh thing to get right in all 33
  processes rather than one).
- Testing surface: every existing test that spins up a process (e.g.
  `test_log_srv_server.py`, which starts a real `LogServer` on a background
  `threading.Thread` and talks to it over a real socket) would need to be
  rewritten around `pytest-asyncio` or an equivalent event-loop-aware test
  harness. This is not exotic, but it is 100% of the integration-style
  tests in the suite, all at once.
- No current pain point motivates this. Every process's connection/message
  volume is small (a teaching/simulation exchange, not a production
  low-latency venue), so none of `asyncio`'s scalability advantages over
  `select()`/`zmq.Poller()` are currently being left on the table in a way
  that shows up as an actual bottleneck.

## 6. Risk assessment for a full refactor

| Risk | Likelihood | Impact | Notes |
|---|---|---|---|
| Silent event-loop stalls from an un-converted blocking call | High | High | Every synchronous helper (SQLite, file I/O, `time.sleep`, DNS) becomes a hazard; easy to miss one during a 33-process rewrite |
| Regression in shutdown/signal behavior | Medium | High | At least one process (`pm-viewer`) already depends on a specific poll-interrupt-on-SIGINT behavior that doesn't carry over unchanged |
| `aiosqlite` behavioral drift from `sqlite3` | Medium | Medium | Different connection/transaction semantics; affects `pm-stats`, `pm-audit`, `pm-clearing`, `pm-log-srv`, and every one of their CLIs' read paths |
| Test-suite rewrite effort exceeds refactor effort itself | Medium | Medium | Every process-level integration test currently assumes real threads/sockets, not an event loop under test control |
| Partial migration leaves two idioms live longer than either alone | High if not done atomically | Medium | A half-migrated codebase (some processes async, some not) is strictly worse for the "what pattern do I copy" problem this note exists to solve |
| No measurable performance or capability gain at current scale | High | Low (as a cost, not benefit) | This is a teaching/simulation system; none of the 33 processes are anywhere near `select()`'s fd-count ceiling |

## 7. Recommendation

Do not refactor. The current model is consistent (two closely related
single-threaded poll idioms, not thirty-three ad hoc ones), well
understood, already correctly documented in this codebase's design docs and
user guide, and is not causing any observed problem. A full `asyncio`
refactor would touch every long-running process at once, trade one set of
well-understood hazards (thread/queue/lock plumbing) for a different set
(blocking-call stalls, a new DB driver, signal-handling changes,
test-harness rewrite) for a consistency benefit that can be had more
cheaply by simply writing this note down: **new processes that own raw
sockets or ZeroMQ sockets should copy `md_gateway/gateway.py`'s
`select()`-based loop (or the nearest `zmq.Poller()`-based sibling), not
reach for `asyncio`,** with the single documented exception being
`pm-api-gwy`, which needs `asyncio` only because FastAPI/uvicorn require
it for HTTP/WebSocket serving, not for its own ZeroMQ traffic.

## 8. Open questions

1. If a future process genuinely needs to handle a connection count that
   pushes against `select()`'s practical ceiling, should that one process
   use `selectors.DefaultSelector` (stdlib, transparently picks
   `epoll`/`kqueue`, same synchronous single-threaded style, no `asyncio`
   commitment) as an intermediate step before considering `asyncio`?
2. Should `docs/user-guide/170-processes.md` or a top-level architecture
   doc gain a short "concurrency model" callout so this isn't only
   discoverable by reading this design note?
3. Is there any appetite for consolidating the two poll idioms — i.e.,
   could the raw-socket gateways be rewritten atop `zmq`'s pattern (unlikely,
   since they speak non-ZeroMQ wire protocols like ALF/BALF/CALF/RALF/LALF
   to external clients) or vice versa? Preliminary read: no, these are
   different transports for a reason, not an accidental duplication.

## See also

- `EduMatcher-log-srv.md` §7.3 — the design-draft passage that assumed
  `asyncio` and was subsequently corrected against this note's findings.
- `src/edumatcher/log_srv/server.py` module docstring — the implementation's
  own record of the `select()`-vs-`asyncio` decision for `pm-log-srv`
  specifically.
- `docs-design/EduMatcher-ALF-API-Gwy2.md` — the accurate design description
  of `pm-api-gwy`'s actual asyncio/thread hybrid.
- `docs/user-guide/170-processes.md` — process inventory and startup
  reference for every `pm-*` entrypoint surveyed in §2 above.
