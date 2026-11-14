# pm-index / pm-index-cli / pm-index-admin-cli Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/index/` at `d16baf53` (v0.79.0): `main.py` (1 173
lines, pm-index), `calculator.py` (313), `history.py` (163),
`config_loader.py` (89), `__init__.py` (16), pm-index-cli's `cli.py` (900)
and pm-index-admin-cli's `admin_cli.py` (696). pm-index's `index.update`
is read by pm-stats (`index_level_snapshots`, `index_daily_stats`),
pm-md-gwy (the `IDX` line) and the GUIs; pm-api-gwy sends
`index.rebalance`. `ExchangeCommandClient`'s `index_*` methods
(`commands/client.py`) were read where they decide the CLI's behaviour, not
reviewed as code of their own.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts and the operator guide's index chapters
(`part-4-run-a-market/070-market-index.md`, `080-index-administration.md`)
say what the code does.

**Previous work:** `docs-design/EduMatcher-Index.md` (the design),
`EduMatcher-index-admin-cli.md`, and the key-component fixes K7 (state
checkpoint, atomic write, restore authority) and K8 (refused delist leaves
the index unchanged, typed command fields). Their fixes are in place and are
not repeated here.

**Method:** every line of the files above was read. Findings marked
*(repro)* were reproduced with a scratch script against the tree at
`d16baf53`, driving `IndexProcess` with fake sockets as
`tests/test_index_main.py` does; *(measured)* means timed on this host. The
others are by inspection, with line numbers given. The engine's ordering of
uncross trades and `session.state` was read in `engine/main.py:6170-6232`.

Status: **Open.** Decisions Q1–Q3 not yet taken.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (`index.update` frames, acks, the state and history
   files, CLI output, exit code).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_index_*.py`,
   `tests/test_api_gateway_index_events.py` and `tests/test_msgen_index.py`
   with `-n logical`, then black/flake8/mypy/pyright. Do not start the next
   WP with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Process tests build `IndexProcess` with the five socket factories patched
(the `proc_with_fakes` fixture in `tests/test_index_main.py`) and call the
handlers directly.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-IDX01 | A command is applied, persisted and acknowledged together | C5, C7 | — | 0.5 d | ☐ | |
| 2 | WP-IDX02 | Day open/high/low and the close across phases and engine restarts | C2, C4, C10 | — | 0.5 d | ☐ | |
| 3 | WP-IDX03 | The last level is always published | C1 | — | 0.25 d | ☐ | |
| 4 | WP-IDX04 | The loop survives a write failure and exits only when stopped | C8, C9 | — | 0.25 d | ☐ | |
| 5 | WP-IDX05 | CLI output and small items | C12, C13, C14, C15 | — | 0.5 d | ☐ | |
| 6 | WP-IDX06 | Incremental aggregate cap; drain per wake-up | P1, P2 | — | 0.25 d | ☐ | |
| 7 | WP-IDX07 | Corporate actions and the market price | C3 | Q1 | 0.5 d | ☐ | |
| 8 | WP-IDX08 | Share deltas resolved by pm-index | C6 | Q2 | 0.5 d | ☐ | |
| 9 | WP-IDX09 | Catch up on prices after a start | C11 | Q3 | 0.5 d | ☐ | |
| 10 | WP-IDX10 | Comments, docstrings, help texts, guide | D1–D8 | WP-IDX01–09 | 0.5 d | ☐ | |

Suggested order: **WP-IDX01 → WP-IDX02 → WP-IDX03 → WP-IDX04 → WP-IDX05 →
WP-IDX06 → WP-IDX07 → WP-IDX08 → WP-IDX09 → WP-IDX10**. WP-IDX01 removes the
one path that can apply a corporate action twice. WP-IDX02 and WP-IDX03 fix
figures every subscriber sees, and should land before the next simulation
run. WP-IDX07–09 wait for decisions Q1–Q3. WP-IDX10 goes last so every text
describes the code as it ends up.

Estimated sequential effort: about 4.25 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **calculation** is sound. Every divisor adjustment preserves the level
at the moment of the action (the split's integer rounding included); the
memoised aggregate cap is invalidated by every method that changes a price,
a share count or the constituent set; a refused delist leaves the index as
it was; the rebalance batch is validated before any mutation; inbound
identifiers are clamped and numeric fields typed, so a malformed command is
refused rather than crashing the process. The state file is written
atomically and is the restore authority, and the history archive is
validated on write and on read.

The defects sit in four places:

- **Session bookkeeping (C2, C4).** The engine publishes an uncross's trades
  *before* the new `session.state`, and pm-index clears the day at
  `CONTINUOUS`, so the opening print never reaches the day's open. A
  mid-session engine restart latches the day as finalised, and the real close
  is then never published.
- **Publishing (C1).** The throttle drops the trailing level: a trade inside
  `publish_interval_sec` of the previous publish is never broadcast unless
  something else happens later.
- **Command atomicity (C5).** A corporate action is applied in memory and
  published before its history record and state file are written; if either
  write fails, the client gets no ack, the state on disk is the old one,
  and a retry applies the action a second time.
- **The model's contract with the market (C3, C6).** Splits and dividends
  change the index's view of a price, but nothing in EduMatcher changes the
  market's; the next trade at the unchanged price moves the index by the
  split factor. `--delta` resolves share counts from history records that
  do not hold them all.

Severity key: **Med** — a wrong figure on the wire or on disk, or a command
that can be applied twice; **Low** — hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| C1 | Med | Publish | The throttle drops the trailing level: two trades 0.1 s apart with a 1 s interval publish the first; the second is never published (internal 1100, last published 1050) *(repro)* | IDX03 |
| C2 | Med | Day OHLC | The opening uncross prints before `session.state CONTINUOUS`, which clears the day: the day's open/high/low miss the opening print (open 1255 instead of 1250). Reaches pm-md-gwy's `OPEN/HIGH/LOW` and pm-stats' `day_*` columns *(repro)* | IDX02 |
| C3 | Med | Corp actions | A split or dividend changes the index's price, not the market's: after a 2:1 split the next trade at the unchanged price moves the level 1000 → 1500; after a 10.00 dividend, 1000 → 1052.6 *(repro)* | IDX07 |
| C4 | Med | EOD | The engine's `system.eod` at a mid-session stop finalises the day and latches it; after the restart the real `CLOSED` publishes no close *(repro)* | IDX02 |
| C5 | Med | Commands | A corp action, constituent change or rebalance is applied and published before its history record and state file are written; if either fails, no ack, the old state on disk, and a retry applies it twice *(repro)* | IDX01 |
| C6 | Low | Admin CLI | `shares --delta` takes the last count from history records, which hold neither the configured counts, nor a split's, nor a rebalance's: 1000 shares, a 2:1 split, `--delta -100` → 900 instead of 1900. The split case is documented *(repro)* | IDX08 |
| C7 | Low | Calculator | A reverse split can round a holding to 0 shares; pm-index persists it and then refuses its own state on the next start (`shares_outstanding must be > 0`) *(repro)* | IDX01 |
| C8 | Low | Loop | `_checkpoint` and `history.flush` in `run()` are unguarded: a full disk ends pm-index (and `close()` raises again from the same checkpoint) | IDX04 |
| C9 | Low | Loop | EINTR on `poll` ends the loop and pm-index exits 0 although nobody stopped it | IDX04 |
| C10 | Low | Restart | A mid-session restart starts the day's open/high/low at the restart level; documented as "diagnostics", but the `day` record on the wire (md-gwy, pm-stats) is then wrong for the rest of the day | IDX02 |
| C11 | Low | Start-up | No catch-up: after a start, each constituent keeps its state-file (or config) price until it trades again; trades lost at the SUB high-water mark (default 1 000) go unnoticed | IDX09 |
| C12 | Low | Commands | `add` accepts any symbol: a typo becomes a constituent whose price never moves | IDX05 |
| C13 | Low | pm-index-cli | `events` prints `REBALANCE` rows with an empty symbol and detail; the help lists four of the five types; `%g` prints a divisor of 7 007 123 456.78 as `7.00712e+09` | IDX05 |
| C14 | Low | Admin CLI | `history` keeps the oldest `--limit` records of the window (the help says "recent"), prints `REBALANCE` without detail and `ts_ns` raw | IDX05 |
| C15 | Low | pm-index-cli | `events --index X` without a deployed config prints `[ERROR] No compiled configuration …` and then answers normally | IDX05 |
| P1 | Low | Trade path | Every trade recomputes the aggregate cap over all constituents: 4.2 / 15.1 / 56.3 µs per trade at 10 / 100 / 500 constituents *(measured)* | IDX06 |
| P2 | Low | Loop | One message per socket per `poll` wake-up, with a checkpoint scan and a history flush per index each time | IDX06 |
| D1–D8 | — | Comments | See §5 | IDX10 |

---

## 3. Correctness findings

### C1. The throttle drops the trailing level *(repro)* — Med

`main.py:441-459` `_publish_level`. A trade within `publish_interval_sec`
of the last publish returns without publishing, and nothing publishes it
later: the loop (`main.py:986-1017`) has no timer for a pending level. The
published level stays at the last one that happened to fall outside the
interval until the next trade, corporate action, status reply or close.

Reproduced with `publish_interval_sec = 1.0`: trades at 110 and 120 in
AAPL 0.1 s apart, then an idle loop for 1.2 s. Internal level 1100, last
`index.update` 1050, one update in total.

In a quiet market (or a thin index) the stale level is what pm-stats
records, what md-gwy clients see and what the trader GUI shows, for as long
as the constituents stay quiet. The guide (`070-…:268-271`) and the design
(§5.4) both say "the internal level is always up to date; the throttle
controls only how often `index.update` messages are broadcast", which reads
as a rate limit with a trailing edge.

**Fix.** Mark the index "pending" when a level is computed but not
published; the loop publishes a pending level once the interval has passed.

### C2. The opening print is dropped from the day *(repro)* — Med

`main.py:528-537`: `_reset_for_new_session` runs on `OPENING_AUCTION` **and**
`CONTINUOUS`. The engine runs the uncross before it publishes the new state
(`engine/main.py:6175-6232`: `_run_uncross`, then `make_session_state_msg`),
so the opening auction's trades reach pm-index while it is still in
`OPENING_AUCTION`, and the `CONTINUOUS` that follows clears them. The same
happens on a direct `PRE_OPEN → CONTINUOUS`.

Reproduced: `OPENING_AUCTION`, an opening print in AAPL (level 1250),
`CONTINUOUS`, a trade in MSFT: `day` is `open=1255, high=1255, low=1255`.
The opening level is not the day's open, and an opening print that set the
day's high or low is lost.

The `day` record is relayed by md-gwy (`md_gateway/normaliser.py:433-438`,
`OPEN=…|HIGH=…|LOW=…`) and stored by pm-stats in every
`index_level_snapshots` row (`stats/main.py:1765`). The guide documents the
reset (`070-…:274-277`, D3).

**Fix.** Start a new day at `PRE_OPEN`, the only state after `CLOSED`
(`models/session.py:30-36`); nothing trades between `PRE_OPEN` and the
opening uncross. The closing side is right: the closing uncross and the
backstop also print before `session.state CLOSED`, so the close includes
them (§6).

### C3. Splits and dividends move the index on the next trade *(repro)* — Med

`calculator.py:155-222`. A split multiplies the shares and divides the
constituent's price; a dividend lowers the price; the divisor keeps the
level. Both assume the market will trade at the adjusted price from then on
(the design, §6.3: "on ex-date, the stock price drops by
dividend_per_share"). Nothing in EduMatcher makes it do so: the engine,
pm-market-sim and pm-mm-bot have no corporate actions, so the next print
comes at the old price and replaces the adjusted one.

Reproduced (two constituents, 100 shares each at 100.00, level 1000):

| action | level after the action | after the next AAPL trade at 100.00 |
|---|---|---|
| SPLIT 2:1 on AAPL | 1000.0 | **1500.0** |
| CASH_DIVIDEND 10.00 on AAPL | 1000.0 | **1052.6** |

The guide's note (`070-…:330-334`, "Applying them during continuous
trading means the index will have a brief moment where the pre-adjustment
divisor is used for one more trade") describes a different, smaller effect
and suggests the action is otherwise safe. See Q1.

### C4. A mid-session engine restart suppresses the real close *(repro)* — Med

`main.py:461-478` `_finalize_eod`, `main.py:934-935`, `main.py:549-560`.
`system.eod` is the engine's last message at *every* stop, not only at the
end of the day. pm-index finalises on it: publishes the level with
`session_state = CLOSED` and sets `eod_finalized_for_session`. When the
engine comes back, its status reply (`_handle_session_status`) sets the
state to `CONTINUOUS` but leaves the latch set; only `OPENING_AUCTION` or
`CONTINUOUS` *transitions* clear it. At the real `CLOSED`, `_finalize_eod`
skips the index: no forced close is published, and the day's close is
whatever the throttle last let through (C1).

Reproduced: `CONTINUOUS`, a trade, `system.eod`, status reply `CONTINUOUS`,
a trade, `CLOSED`: no `index.update` with `session_state = CLOSED` after the
real close; `eod_finalized_for_session` stays True.

**Fix.** A non-`CLOSED` state (a `session.state` or a status reply) clears
the latch without clearing the day: the engine is trading again, so the
session has not ended.

### C5. A command can be applied without being persisted or acknowledged *(repro)* — Med

`main.py:672-701` (corp action), `763-788` (constituent change), `890-917`
(rebalance). The order is: mutate the calculator, publish the level,
append the history record, write the state file, send the ack. An
exception after the mutation (a full disk on `history.append` or on
`_persist_state`) escapes to `_handle_pull_message`, which logs a WARNING.

Reproduced with `history.append` raising `ENOSPC` on a SHARES_ISSUANCE:
divisor 20 → 30 in memory and on the wire, 20 in the state file, no ack.
Then:

- the operator's `pm-index-admin-cli` times out ("Is pm-index running?"),
  and the natural next step, running it again, applies the action a second
  time (a second split halves the price again);
- `dirty` is not set, so the change reaches the state file only with the
  next trade's checkpoint, or never if pm-index stops first, and a
  restart reverts it while the subscribers saw it.

**Fix.** Apply the command to a copy of the calculator, write the state
file, then the history record, then swap the copy in, publish and ack. A
failure before the swap rejects the command with the error and changes
nothing. `command_id` is already echoed; it is not needed for this.

### C6. `--delta` misses split, rebalance and configured counts *(repro)* — Low

`admin_cli.py:413-469` `_resolve_delta`. The last count is taken from
`ADD_CONSTITUENT` records and `SHARES_ISSUANCE` corp actions. Three things
set a count without either:

- the configuration (the `INIT` record has the constituents, not their
  shares), so `--delta` on an unchanged constituent is refused;
- a `SPLIT` (the record says `2:1`, not the result);
- a `REBALANCE` (the record lists the symbols, not their new counts).

Reproduced: 1000 shares, then a 2:1 split (pm-index holds 2000);
`--delta -100` resolves to **900** and would set it. The guide documents the
split case (`080-…:255-259`) but not the rebalance case, and the command
does not refuse; it silently sends the wrong absolute count. pm-index holds
the live count; resolving it anywhere else is a second source of truth.
See Q2.

### C7. A reverse split can leave a holding of zero shares *(repro)* — Low

`calculator.py:168-170` rounds `shares × num / den` half-up; a 1:10 reverse
split of 4 shares gives 0. The calculator accepts it (the constituent then
counts for nothing), pm-index persists `"AAPL": 0`, and the next start fails
in `IndexCalculator.__init__` with "shares_outstanding must be > 0 for AAPL"
until `--reset` discards every runtime change. Refuse a split whose result
rounds below one share.

### C8. A write failure in the loop ends pm-index — Low

`main.py:1015-1017`: `self._checkpoint()` and `idx.history.flush()` run
outside any guard. An `OSError` (disk full, a lost mount) escapes `run()`;
`main()` logs CRITICAL and calls `close()`, whose `_checkpoint(force=True)`
raises the same error again inside `finally`, so the traceback shown is
the second one. The state file is a checkpoint; failing to write it should
not stop the live index. Log at ERROR, keep `dirty`, retry at the next
interval.

### C9. EINTR ends the loop with status 0 — Low

`main.py:1001-1004`: an `EINTR` from `poll` `break`s out of the loop, `run()`
returns, and pm-index exits 0 without being stopped. pyzmq retries EINTR
and signals reach the main thread here (pm-index polls on its main thread),
so a signal handler runs first; it should still be `continue` (the same
pattern was fixed in pm-audit and pm-stats).

### C10. A restart restarts the day — Low

`main.py:356-360`: `day_open`/`day_high`/`day_low` are written to the state
file and never read back ("a persisted diagnostic"). A mid-session restart
publishes `day.open` = the level at the restart, and `high`/`low` from
there, for the rest of the day; md-gwy relays it and pm-stats stores it.
The guide says so (`070-…:436-437`), so this is documented, but the figure
is wrong and the data to fix it is already in the file. Restore the day
when the state file says the session was not finalised (persist the latch
from C4 alongside it).

### C11. No price catch-up after a start — Low

On start, each constituent's price is the state file's (up to 30 s older
than the stop) or the configured reference price, and it stays so until the
symbol trades again; for a thinly traded constituent that can be all day.
Trades that arrive while pm-index is down, or that ZeroMQ drops at the SUB
high-water mark (ZMQ's default of 1 000, `make_subscriber` without
`rcvhwm`), are never noticed: pm-index checks no sequence. The engine
answers `book.snapshot_request` with `book.{symbol}`, which carries
`last_price`. See Q3.

### C12. `add` accepts a symbol that does not trade — Low

`main.py:736-748`. Nothing checks the symbol against the configured
instruments, which pm-index has (`compiled.engine.symbols`). A typo (`APPL`)
becomes a constituent at its initial price for ever, weighted by its share
count. The admin CLI's prompt warns about it (`admin_cli.py:547-548`);
pm-index can refuse it.

### C13. pm-index-cli `events` output — Low

`cli.py:290-312` `_project_event` has no `REBALANCE` branch (the record
carries `symbols`, a list), so a rebalance shows an empty symbol and detail.
The module docstring, the `events` help and the `--type` help list four
types; the parser accepts the fifth. `_stringify` (`cli.py:320-327`) prints
floats with `%g`: a divisor of 7 007 123 456.78 shows as `7.00712e+09`, a
level of 12 345.67 as `12345.7` (fixed the same way in pm-stats-cli, C3 of
the stats review).

### C14. pm-index-admin-cli `history` — Low

`admin_cli.py:598-637`. `records[: args.limit]` keeps the **oldest** records
of the window, while the help says "Show recent … history"; `REBALANCE`
falls through to an empty detail; `ts_ns` is printed as a raw integer.

### C15. A spurious `[ERROR]` from pm-index-cli — Low

`cli.py:189-210`: with no deployed config and no `--config`,
`_resolve_history_files` calls `_load_engine_config`, which prints
`[ERROR] No compiled configuration …` before raising `SystemExit`; the
caller catches it and falls back to `--data-dir` as intended, so the command
answers correctly after printing an error. Use `_try_load_engine_config`
there.

---

## 4. Performance findings

### P1. The aggregate cap is recomputed on every trade *(measured)* — Low

`calculator.py:110-120` and `138-153`: `update_price` invalidates the
memoised cap, and `recalculate` rebuilds it over every constituent. Timed
with `_handle_trade` on 20 000 trades:

| constituents | throttled (1 s) | publish every trade |
|---:|---:|---:|
| 10 | 4.2 µs | 12.9 µs |
| 100 | 15.1 µs | 32.3 µs |
| 500 | 56.3 µs | 59.2 µs |

The configured indices are small (10–50), so this is not a problem today;
a 500-name index caps pm-index at about 18 000 trades a second.
`cap += (new − old) × shares` on a price update is O(1); keep the full
recompute for every structural change, where it also resets float drift.

### P2. One message per wake-up — Low

`main.py:986-1017`. Each iteration polls three sockets, handles at most one
engine and one command message, scans every index for a due checkpoint and
flushes every history file. Draining up to a bound (e.g. 256) per wake-up
with `zmq.NOBLOCK` takes the per-message `poll` and scan out of a burst (the
same change as pm-stats' P4).

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `main.py:1` | No module docstring. Every other process states its usage, subscriptions, files and restore rules there; pm-index's are spread over method comments. |
| D2 | `history.py:18-23`, `history.py:30-36`; `cli.py:7-9`, `432`, `454`; `admin_cli.py:5-7`, `312-313` | The record-type lists omit `REBALANCE` (and the admin docstring's method list omits `index_history`). |
| D3 | `070-market-index.md:268-277`, `330-334` | The guide documents the `CONTINUOUS` reset (C2) and a throttle that is "always up to date" (C1); the corporate-action note understates C3. |
| D4 | `main.py:162`, `467`, `526` | `_ManagedIndex.day_close` is written and never read (`tests/test_index_main.py:615` pins it). |
| D5 | `main.py:1067-1072`; `cli.py:421-425` | `-q/--quiet` "Reduce log output to warnings/errors": WARNING is already the default, so the flag does nothing. `--no-header` says "csv output only" but also suppresses the table header. |
| D6 | `main.py:873-879` | The rebalance's partial-failure comment says "only the aggregate-cap-non-positive guard … can still fail here". It cannot fail either (every price and count is positive), and the path it describes skips the `REBALANCE` history record. Say it is unreachable, or remove it with WP-IDX01's copy-and-swap. |
| D7 | `calculator.py:201-211`; `calculator.py:38` | `apply_cash_dividend` mutates the price before its own `old_cap` guard (every other action checks first); `_constituents` maps each symbol to itself (a set would say what it is). |
| D8 | `main.py:660`, `751` | A rejection built from `str(KeyError(...))` keeps the quotes: the reason reads `'unknown constituent: XYZ'`. |

---

## 6. Verified as correct

- **Divisor continuity.** Split (including the half-up share rounding,
  corrected through the divisor), dividend, issuance, add and delist each
  keep `cap / divisor` unchanged at the moment of the action; an add to an
  index whose cap was zero restarts from `base_value`.
- **Memoised cap.** Every method that changes a price, a count or the
  constituent set calls `_invalidate_cap()`; no read path sees a stale cap.
- **Command validation.** `_int_field`/`_float_field` refuse bool, None,
  NaN, fractions and text; identifiers are clamped to the spec's 32
  characters before they are echoed, so a reply cannot fail validation; the
  rebalance batch is checked (shape, unknown and duplicate symbols,
  non-positive counts) before any mutation; a refused delist changes
  nothing.
- **State file.** Written with `atomic_write_text`; restored as the
  authority for divisor, constituents, counts and prices; an `index_id`
  mismatch refuses to start; a persisted constituent set that differs from
  the config is kept, with a warning.
- **History.** Validated through `HistoryRecord` on write (a failing record
  is stored as-is and logged) and on read (a non-conforming row is skipped
  with a warning); a missing file is "no history yet", an unreadable one an
  error the operator sees.
- **The close.** The closing uncross and the closing backstop print before
  `session.state CLOSED` (`engine/main.py:6175-6183`), so the forced close
  includes them.
- **Shutdown.** SIGINT/SIGTERM stop the loop; `close()` checkpoints every
  dirty index and flushes and closes the history files.
- **Paths.** The engine config resolves `history_file`/`state_file` to
  absolute paths, and pm-index-cli resolves its `--data-dir` fallback the
  same way, so the process and the CLI read the same files.
- **Health process match.** `find_process_pids("pm-index")` does not count
  `pm-index-cli` or `pm-index-admin-cli`.

---

## 7. Decisions

Open; recommendations given.

| # | Question | Recommendation |
|---|---|---|
| Q1 | Splits and dividends assume the market trades at the adjusted price, and nothing in EduMatcher adjusts it (C3). What does 1.0 promise? | Document the contract and say it where the operator acts: the action models the index side of an ex-date, and the constituent must then trade at the adjusted price (for a simulation, by changing its reference price or the bots' anchor). `pm-index-admin-cli split`/`dividend` print that in the confirmation; the guide's note is rewritten. Exchange-side corporate actions (book, reference prices, bots) are 1.x, recorded in the For-Later list. |
| Q2 | `--delta` resolves counts from history (C6). Fix the client, or move the delta to pm-index? | Move it: `index.corp_action` `SHARES_ISSUANCE` gains an optional `shares_delta` (exactly one of it and `new_shares_outstanding`), applied to pm-index's live count atomically; the ack carries the resulting count. The CLI stops reading history for it. `REBALANCE` records gain the new counts per symbol, so the archive says what happened. Spec change (`pm-msgen`). |
| Q3 | Catch up on prices after a start (C11)? | Yes: on start, and when the engine's status reply arrives after a restart, send `book.snapshot_request` for every constituent and apply each `book.{symbol}`'s `last_price` like a trade. No sequence checking: a missed print is replaced by the next one, and the catch-up covers the restart case that matters. |

---

## 8. Work packages

Each WP lists the tests to write first, the production change, and the exit
criteria. Test files are existing ones unless marked new.

### WP-IDX01 — Commands are atomic (C5, C7)

**Goal.** A command is applied, persisted, recorded and acknowledged
together, or not at all; no command can leave a state pm-index cannot load.

**Tests first** (`tests/test_index_robustness.py`):

1. `history.append` raising `ENOSPC` on a SPLIT: the reply is a rejection
   naming the error; divisor, prices and counts in memory and in the state
   file are unchanged; no `index.update` was published. (Fails today: no
   reply, memory changed.)
2. `_persist_state` raising on a SHARES_ISSUANCE: the same.
3. The same two for ADD, DELIST and REBALANCE.
4. After a rejected command, the same command again is applied once.
5. A 1:10 split of 4 shares is refused ("would leave AAPL with 0 shares");
   a 1:2 split of 3 shares (→ 2) is accepted.
6. A restart after each accepted command restores the same level.

**Change.** Each handler applies the change to a copy of the calculator
(`copy.deepcopy` or a `clone()`), writes the state file, appends the history
record, then swaps the copy in, publishes and acks; an `OSError` before the
swap rejects. The split refuses a result below one share. D6's comment goes
with the removed partial path.

**Exit criteria.** Tests pass; `tests/test_index_*.py` green.

### WP-IDX02 — Day and close across phases and restarts (C2, C4, C10)

**Tests first** (`tests/test_index_main.py`, or a new
`tests/test_index_session_day.py`):

1. `PRE_OPEN`, `OPENING_AUCTION`, an opening print, `CONTINUOUS`, a trade:
   `day.open` is the opening print's level. (Fails today.)
2. `PRE_OPEN → CONTINUOUS` with an uncross print before the `CONTINUOUS`:
   the same.
3. `CLOSED → PRE_OPEN` starts a new day (`day` None, latch clear).
4. The C4 repro: `system.eod`, status `CONTINUOUS`, a trade, `CLOSED` → a
   forced `index.update` with `session_state = CLOSED` and the final level.
   (Fails today.)
5. A restart mid-session (state file with day and an open latch) publishes
   the restored `day.open`; a restart after the close starts afresh.

**Change.** `_reset_for_new_session` on `PRE_OPEN` only; a non-`CLOSED`
state or status clears `eod_finalized_for_session`; persist the latch and
restore `day` from the state file when the latch is open.

**Exit criteria.** Tests pass; md-gwy and pm-stats index tests green.

### WP-IDX03 — Publish the trailing level (C1)

**Tests first** (`tests/test_index_main_runtime.py`):

1. Two trades 0.1 s apart with a 0.3 s interval, then an idle loop for
   0.5 s: the last `index.update` carries the second trade's level.
   (Fails today.)
2. A steady stream of trades still publishes at most once per interval.
3. A forced publish (corp action, close) clears the pending level.

**Change.** `_ManagedIndex.pending`; `_publish_level` sets it when it
throttles; the loop publishes pending indices whose interval has passed.

**Exit criteria.** Tests pass.

### WP-IDX04 — The loop survives a write failure (C8, C9)

**Tests first** (`tests/test_index_main_runtime.py`):

1. `_persist_state` raising `ENOSPC` once from the loop's checkpoint: the
   loop keeps running, the index stays dirty, the next checkpoint writes.
   (Fails today: `run()` raises.)
2. `history.flush` raising once: the same.
3. `poll` raising `ZMQError(EINTR)` once: the loop continues.
4. `close()` after a failing checkpoint logs and still closes every socket.

**Change.** Guard the loop's checkpoint and flush with `except OSError`
(ERROR log, retry next interval); EINTR `continue`s; `close()` guards its
own checkpoint.

**Exit criteria.** Tests pass.

### WP-IDX05 — CLI output and small items (C12, C13, C14, C15)

**Tests first** (`tests/test_index_cli.py`, `tests/test_index_admin_cli.py`,
`tests/test_index_robustness.py`):

1. `add` of a symbol absent from the configured instruments is rejected
   ("APPL is not a configured symbol"); a configured one is accepted.
2. `pm-index-cli events` shows a `REBALANCE` row with its symbols; a
   divisor of 7007123456.78 prints in full; `--help` lists five types.
3. `pm-index-admin-cli history --limit 2` over three records shows the two
   newest; `REBALANCE` has a detail; the time is ISO.
4. `pm-index-cli events --index EDU` with no deployed config prints no
   `[ERROR]` line and answers from `--data-dir`.

**Change.** pm-index keeps the configured symbol set and checks `ADD`
against it. `_project_event` and the admin `history` printer gain a
`REBALANCE` branch; `_stringify` prints floats with 15 significant digits
(as pm-stats-cli); `history` slices the tail and formats the stamp;
`_resolve_history_files` uses `_try_load_engine_config`.

**Exit criteria.** Tests pass; completions regenerated if help text
changed.

### WP-IDX06 — Incremental cap and drain (P1, P2)

**Tests first** (`tests/test_index_calculator.py`,
`tests/test_index_main_runtime.py`):

1. 10 000 random price updates over 50 constituents: the incremental cap
   equals a full recompute within 1e-9 relative; every structural action
   recomputes exactly.
2. A bench in the WP notes: ≤ 6 µs per throttled trade at 500 constituents.
3. 300 queued trades are handled in one wake-up without another `poll`.

**Change.** `update_price` adjusts the memoised cap by the difference when
it is valid; the loop drains up to N messages per wake-up.

**Exit criteria.** Tests pass; bench recorded.

### WP-IDX07 — Corporate actions and the market price (C3; after Q1)

**Tests first** (`tests/test_index_admin_cli.py`):

1. Per Q1: the `split` and `dividend` confirmations state that the
   constituent must trade at the adjusted price; `--yes` prints it too.
2. The guide's corporate-action section is checked by the docs build only.

**Change.** Prompt text; guide (`070-…` corporate actions, the note), the
admin chapter; a For-Later entry for exchange-side corporate actions.

**Exit criteria.** Tests pass; `mkdocs build` clean.

### WP-IDX08 — Share deltas in pm-index (C6; after Q2)

**Tests first** (`tests/test_index_robustness.py`,
`tests/test_index_admin_cli.py`, `tests/test_msgen_index.py`):

1. `SHARES_ISSUANCE` with `shares_delta = -100` after a 2:1 split of 1000
   shares sets 1900; the ack carries 1900. (Fails today.)
2. Both or neither of `shares_delta`/`new_shares_outstanding` is rejected;
   a delta that leaves ≤ 0 shares is rejected.
3. `pm-index-admin-cli shares --delta` sends `shares_delta` and prints the
   resulting count from the ack; it sends no history request.
4. A `REBALANCE` history record lists each symbol's new count.

**Change.** Spec (`spec/messages/index.yaml`), `pm-msgen generate`,
handler, admin CLI, `ExchangeCommandClient.index_corp_action`; guide's
`--delta` caveats go.

**Exit criteria.** Tests pass; `pm-msgen check` clean.

### WP-IDX09 — Price catch-up after a start (C11; after Q3)

**Tests first** (`tests/test_index_main.py`):

1. `_initialise` then the status reply: one `book.snapshot_request` per
   constituent is sent (fake engine push).
2. A `book.AAPL` with `last_price` updates the constituent like a trade; a
   snapshot without `last_price` changes nothing.
3. A status reply after an engine restart requests again.

**Change.** Subscribe to `book.` for constituents only (or to each
`book.{symbol}`), request snapshots on start and on each status reply,
apply `last_price`; guide's start-up section.

**Exit criteria.** Tests pass.

### WP-IDX10 — Comments, docstrings, help texts, guide (D1–D8)

**Change.** Fix D1–D8 as listed in §5; reread both index chapters of the
operator guide against the code as it ends up (day boundary, close after a
restart, trailing publish, atomic commands, `add` check, `--delta`).

**Exit criteria.** `mkdocs build` clean; a reread of every module and class
docstring in `src/edumatcher/index/*.py` against the code finds nothing
stale.

---

## 9. Out of scope, noted

- `health -q` exits `-1` (status 255); already recorded as L017 in
  `EduMatcher-For-Later-ToDo.md`.
- pm-index's PULL socket has no authentication; `--id` is a routing key
  only. Documented by design (`EduMatcher-index-admin-cli.md` §9).
- The health beacon carries vitals only (design A6.6), so a pm-index whose
  every message fails is visible only in its log. A handler-error counter
  would be a design change, not a fix.
- The history archive is flushed every loop iteration but never fsynced; a
  power loss can drop its last records while the state file (written with
  `atomic_write_text`, which fsyncs before the rename) survives. The archive
  is an audit aid, not the restore authority; WP-IDX01's write order (state
  first) keeps the authority ahead of it.
- `ExchangeCommandClient`'s index methods were not reviewed as code.
- Exchange-side corporate actions (adjusting books, reference prices and
  bots on an ex-date): 1.x, see Q1.
