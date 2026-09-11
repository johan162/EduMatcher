# CP-0 checkpoint — "the bus is ready"

Phase 0 (AR-0.2 through AR-0.7, plus the AR-0.3b follow-up) is implemented and
committed on `feature/audit-replay`:

```
141beaf5 docs(audit): reword AR-0.3b's ts_ns doc so CP-0's grep genuinely passes
37aa3f85 fix(audit): AR-0.3b — finish the epoch_seconds-to-ts_ns conversion on order.yaml
f3ccc77b docs(audit): AR-0.7 — documentation and changelog sweep for Phase 0
6eca873e feat(audit): AR-0.6 — command_id on session.state
ee07a1b4 feat(audit): AR-0.5 — effect id lists and per-entity recovery events
c8d90078 feat(audit): AR-0.4 — a clock on book and depth snapshots
a6f3ed6b feat(audit): AR-0.3 — finish the ts_ns convention in the index family
5af6c6fa feat(audit): AR-0.2 — symbol on order.cancelled
```

CP-0 asks for all six items to be **demonstrated on one captured session from
`scripts/launch_all.sh`**. I can't do that from this sandbox — no working
Poetry environment, no ZMQ, can't run the engine or any gateway. Everything
below is either static verification (reading the code/spec and tracing call
paths) or direct execution of the specific functions/tests against the real
code with hand-rolled stubs for missing third-party packages (pyzmq, fastapi,
rich, prompt_toolkit, holidays, pytest). That is a meaningfully weaker bar
than "demonstrated on a captured session," and I want that gap to be explicit
rather than glossed over. Someone needs to run the actual checklist against a
real `launch_all.sh` session before Phase 1 starts — that's what CP-0 is for.

## Item-by-item

**1. Every engine-published line carries an envelope and a per-topic `seq` — no publisher bypasses `CausalPublisher`.**
Static verification, not from this session's work. `engine/main.py` has
exactly one publisher socket, `self.pub_sock = make_publisher(ENGINE_PUB_BIND_ADDR)`
(one assignment, line 572), and `make_publisher()` (`messaging/bus.py:256`)
always returns `CausalPublisher(SequencedPublisher(sock))` — envelope and seq
both come from that composition. There is no raw `zmq.PUB` socket
construction anywhere in `engine/main.py`, and all 141 `send_multipart` call
sites go through `self.pub_sock`, i.e. through the wrapper. So structurally
there's no bypass. Not independently re-verified by running a session —
this reads as solid pre-existing infrastructure, unrelated to Phase 0's own
changes.

**2. `pm-audit-cli events --symbol AAPL` returns cancellations.**
Fixed by AR-0.2 (already committed before this segment): `order.cancelled`
never carried `symbol` on the wire, which made it invisible to any
`--symbol` filter — `spec/messages/order.yaml`'s `order_cancelled.symbol`
field doc says this explicitly. Traced the fix: every `make_cancelled_msg`
call site in `engine/main.py` passes `order=<the cancelled Order>.to_dict()`;
`make_cancelled_msg` resolves `symbol` from that dict via `order_symbol(...)`
(`models/message.py:445`), so `symbol` is always populated now. On the query
side, `query_events`/`iter_entries` filter generically on `AuditEntry.symbol`
(parsed from the log line's JSON payload), with no per-topic special-casing
that would exclude `order.cancelled` rows. Verified by code tracing, not by
building a log file and running `pm-audit-cli events --symbol AAPL` against
it end-to-end.

**3. `grep -rn epoch_seconds spec/messages/` matches only `log.yaml`.**
Literally re-ran it — genuinely green now:
```
$ grep -rn epoch_seconds spec/messages/
spec/messages/log.yaml:155: ...
... (13 hits, all log.yaml)
```
This needed the AR-0.3b follow-up: `OrderDisplay.timestamp` and
`PriceLevelOrder.timestamp` were still `epoch_seconds` floats (a deliberate
display-unit conversion from AR-0.3, but one that left this checklist item
failing). Converted both to `ts_ns` (raw passthrough of `Order.timestamp`,
unconverted — it is not the book's time-priority key, see `arrival_seq`).
While tracing consumers of that field for the rename, found and fixed two
live regressions unrelated to `order.yaml` but the same bug class:
`alf_console/display.py` and `stats/main.py` were still reading
`index.update`/`index.history`'s pre-AR-0.3 `"timestamp"` key, months after
AR-0.3 renamed it to `ts_ns` — the console's INDEX view always showed "now"
instead of the real timestamp, and `pm-stats` logged a spurious warning and
used receipt time on every single `index.update`. Both fixed (commit
`37aa3f85`). A second pass caught the grep still matching `order.yaml` in
doc *prose* (explaining the old unit in English) even after the field
itself was fixed — reworded that prose so the literal grep command matches
only `log.yaml`, not just "in spirit" (commit `141beaf5`).

**4. `book.*` and `depth.*` lines carry `ts_ns`.**
From AR-0.4 (already committed). Confirmed present in
`spec/messages/book.yaml`: `ts_ns` fields on the book snapshot, the depth
message, and the book-diff message, each documented for why (letting a book
snapshot be ordered against `trade.executed.ts_ns`). Not independently
re-verified live.

**5. A kill switch's ack lists the ids it cancelled, and the count agrees.**
From AR-0.5 (committed this segment, `ee07a1b4`). Directly executed
`_handle_kill_switch` against the real engine (via `make_engine`/`connect`
test helpers, not pytest) with 3 live orders across 2 symbols, then asserted
`ack["cancelled_orders"] == 3`, `set(ack["cancelled_order_ids"]) ==
{submitted order ids}`, and `len(ack["cancelled_order_ids"]) ==
ack["cancelled_orders"]`. Passed. This is a genuine functional check against
real code, just not via a captured `launch_all.sh` session.

**6. `poetry run pytest` green; `pm-msgen check` green.**
`pm-msgen check` is genuinely green — reran it after every commit, most
recently after the AR-0.3b doc reword: `pm-msgen check: OK - 19 generated
file(s) match the spec`.

`poetry run pytest` **cannot be run in this sandbox at all** and is
unverified by me. Root cause, established repeatedly this session: no
working Poetry venv reachable from this environment (the project's `.venv`
is built for Python 3.14; this sandbox's system Python is 3.10, and pointing
at the venv's packages via `PYTHONPATH` fails immediately on missing
transitive dependencies like `tomli`), and no network egress for
`pip install` (proxy returns 403). What I did instead, for every test file
touched or exercised this session: imported the real modules under system
Python 3.10 (hand-stubbing only genuinely third-party, unavailable packages —
`pyzmq`, `fastapi`, `rich`, `prompt_toolkit`, `holidays` — never
`edumatcher` code itself) and called the relevant test functions/methods
directly, asserting the same things the real test would. That is not the
same as a real pytest run: it does not catch collection errors, fixture
wiring mistakes, or anything outside the specific functions I chose to
exercise. **This item needs a real `poetry run pytest` on your machine or in
CI before Phase 1 starts.**

## Black / mypy ("make sure mypy and black are green")

Same root cause as `poetry run pytest`: neither tool is installed, `pip
install black mypy --break-system-packages` fails on the same proxy 403, and
the project's own `.venv`-installed black/mypy can't be reused from system
Python 3.10 (same `tomli`-class failure). Substituted:

- **Line length**: `.flake8` sets `extend-ignore = E203, E501, W503`, so
  flake8 itself doesn't enforce black's 88-column limit project-wide — but I
  held every added line in this session's diff to it anyway, matching
  `[tool.black] line-length = 88`. Swept every line *I added* (not
  pre-existing lines, which would just report the file's prior state) across
  all ten hand-written files touched by AR-0.3b: zero exceed 88 columns.
  Separately found and fixed one genuine pre-existing violation in
  `index/cli.py` (from AR-0.3, unrelated to this diff but touched by this
  sweep) by wrapping the call the way black would.
- **Type annotations**: manually reviewed every new or changed function
  signature across the branch (AR-0.2 through AR-0.3b) for
  `mypy --strict`-compliant annotations — explicit `X | None = None` rather
  than implicit Optional, full return types, no bare `Any` where a concrete
  type was available. All read correctly typed, but this is a manual read,
  not a mypy run: it won't catch what mypy actually catches (Argument type
  mismatches you didn't feed test data for, some unreachable-code
  detections, `warn_unused_ignores`, etc.).
- `py_compile` clean on every changed `.py` file except
  `alf_console/main.py`, which has a pre-existing (predates all my edits,
  confirmed via `git show HEAD:...`), Python-3.10-incompatible f-string at
  line 840 — unrelated to anything touched this session. My own edit in
  that file (lines 887-897) was confirmed syntactically valid in isolation
  via `ast.parse()`.

**Bottom line: I believe the diff is black- and mypy-clean based on manual
review, but neither tool actually ran. Please run `make format` / `make
typecheck` (or `poetry run black --check` / `poetry run mypy`) for a real
answer before treating this as settled.**

## What to actually do next

1. On a machine with a working Poetry install: `poetry run pytest`, `make
   format`, `make typecheck`, and `make -C docs pdf-docs` (the
   `docs-design` build succeeded here, but `docs/Makefile` itself needs
   poetry and was never run).
2. Run `scripts/launch_all.sh`, capture a session, and walk the 6 CP-0 items
   against it literally (`pm-audit-cli events --symbol AAPL`, the kill
   switch, the `book.*`/`depth.*` payloads) rather than the code-level
   tracing above.
3. If all of that comes back clean, CP-0 is met and Phase 1 can start.
