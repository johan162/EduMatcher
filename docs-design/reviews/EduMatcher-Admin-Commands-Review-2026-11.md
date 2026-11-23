# pm-admin / pm-admin-cli Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/commands/` at `05a9ba70` (v0.83.4): `client.py`
(982 lines, `ExchangeCommandClient`: the PUSH/SUB sockets, `connect`, `_recv`
and one method per engine command), `console.py` (1 454, `pm-admin`: the
command parser, the shared `execute_command` with one `_cmd_*` handler per
command, every table printer, the prompt_toolkit REPL `AdminConsole`, its
heartbeat thread and engine-disconnect watch), `cli.py` (353, `pm-admin-cli`:
argparse, `_args_to_fields`, `main`) and `__init__.py` (20). `ExchangeCommandClient`
is also used by `pm-index-admin-cli` (the `index_*` methods) and by the
training chapter 21 automation examples; only its admin-command paths are
reviewed here. Read where they decide this component's behaviour, not
reviewed as code of their own: the engine handlers that answer each command
(`engine/main.py` `_handle_gateway_connect` `:2986-3075`,
`_handle_gateway_disconnect` `:4699-4762`, `_handle_kill_switch`,
`_handle_kill_switch_gateway` `:4931-`, `_handle_orders_request` `:3086-3096`,
`_handle_position_request` `:2816-2840`, `_query_status` `:2805-2814`,
`_gateway_status` `:925-946`, `_handle_force_uncross` `:5633-`,
`_flush_snapshots` `:1210-`), `messaging/bus.py` `make_pusher`/`make_publisher`,
`models/ids.py` and `cli_pipe.py`.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, `--help`, `HELP`, the pm-help registry, the operator guide chapter
(`docs/books/operator-guide/part-3-run/020-admin-console-and-commands.md`),
the reference manual sections
(`docs/books/reference-manual/part-1-command-line/010-processes-environment-and-ports.md:3250-3375`)
and training chapter 19 (`docs/books/training-guide/190-advanced-admin-operations.md`)
say what the code does.

**Previous work:** no earlier review of this component. Fixes already in
place from other work and not repeated here: every awaited ack topic is
subscribed (`tests/test_commands_ack_subscriptions.py`); `make_pusher` with
the causal envelope and fail-fast send; `BOOK` drains queued broadcasts before
asking (`_discard_pending`); `SESSION` prints the engine's refusal instead of
timing out (L009, WP-FL08); prices in `BOOK` at the symbol's scale and no
"× None" after a restart (L006/L008, WP-FL17); the heartbeat thread and logout
on SIGHUP/SIGTERM and on engine disconnect (`f7ceae81`); `KILL`/`QCANCEL` on
another gateway use the attributed ADMIN `risk.kill_switch_gateway`; the
engine answers orders/position queries with a `status` (L030, WP-FL06);
`pipe_safe` on `pm-admin-cli` (L013). For-Later items that touch this
component: L039 (queries carry no requester) and L043 (the `LEVEL` price
filter rounds an off-grid price), see §9.

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with scratch scripts against the tree at `05a9ba70`, either
against a real `pm-engine` started on a scratch data directory with the
`s1-basic-setup` configuration (ADMIN id `OPS01`), or, where a market-data load
was needed, against a stand-in engine process that binds the real
`make_puller`/`make_publisher` and answers with the engine's own builders
(`make_gateway_auth_msg`, `make_book_msg`, `make_volume_msg`,
`make_orders_msg`, `make_circuit_breaker_halt_all_ack_msg`). The clients are
the real `ExchangeCommandClient`, `AdminConsole._dispatch` and the installed
`pm-admin`/`pm-admin-cli` entry points. *(measured)* means timed on this host.
The other findings are by inspection, with line numbers given.

Status: **Done, uncommitted (2026-11-23).** All six WPs and a holistic review
done in one go; last full suite 15 479 passed, 1 skipped. Q2 and Q3 taken as
recommended without an explicit answer (to confirm); Q1 implemented as option
(b), not the recommended (a), because (a) did not fix H1 (WP-ADM01 outcome).
Beyond the plan: the holistic review's HR1 fix, the REST and index-guide
texts, and training chapter 21 Exercise 3.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (lines printed, the process exit code, frames pushed to
   the engine, the ack the engine publishes).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_commands*.py`,
   `tests/test_command_correlation.py`, `tests/test_engine_admin_*.py`,
   `tests/test_api_gateway_admin*.py` and `tests/test_shell_completion.py`
   with `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP
   with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Unit tests can keep injecting sockets (`_push_sock`/`_sub_sock`/`_recv_queue`,
as `tests/test_commands.py` does) and engine replies built with the engine's
builders. The two delivery defects (H1, C1) need real sockets: the review's
scratch stand-in engine (about 50 lines: `make_puller` + `make_publisher` on
free ports, a `book.<SYM>` stream at a set rate, auth/volume/orders answers)
can become a fixture in `tests/test_commands_delivery.py`. Engine-side changes
(WP-ADM03) use `tests/engine_harness.py` `make_engine`.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-ADM01 | A reply is never lost to the market-data backlog of an idle console | H1 | Q1 | 0.5 d | ☑ | 2026-11-23 |
| 2 | WP-ADM02 | A connect never misses its own auth reply and locks the ID | C1 | Q2 | 0.5 d | ☑ | 2026-11-23 |
| 3 | WP-ADM03 | A mistyped gateway id fails every targeted command | C2, D7 | Q3 | 0.75 d | ☑ | 2026-11-23 |
| 4 | WP-ADM04 | No typed line or lost engine ends with a traceback, and both tools exit non-zero on failure | C3, C4, C5 | — | 0.5 d | ☑ | 2026-11-23 |
| 5 | WP-ADM05 | Script output is plain text, prices and ids are shown as they are, and bad numbers are refused locally | C6, C7, C8 | — | 0.5 d | ☑ | 2026-11-23 |
| 6 | WP-ADM06 | Comments, help texts and guides say what the code does | D1–D6, D8–D11 | WP-ADM01–05 | 0.5 d | ☑ | 2026-11-23 |

Suggested order: **WP-ADM01 → WP-ADM02 → WP-ADM03 → WP-ADM04 → WP-ADM05 →
WP-ADM06**. WP-ADM01 makes the console usable on a busy market at all, and
WP-ADM02 changes the same connect/receive code. WP-ADM03 closes the incident
playbook gap where every step of a typo'd runbook reports success. WP-ADM04
and WP-ADM05 are local hardening. WP-ADM06 goes last so every text describes
the code as it ends up.

Estimated sequential effort: about 3.25 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The **command set** is complete and consistent: every console command has a
CLI subcommand and a client method, both front ends go through one
`execute_command` (`console.py:1091-1148`), and every awaited ack topic is
subscribed (a test enforces it). **Mutating commands** carry the operator's id:
halts, cancels, reopen and the ADMIN kill switch for another gateway all name
the caller, and the engine checks the ADMIN role per command. **Session
lifecycle** in `pm-admin` is sound: a heartbeat on its own socket keeps the id,
SIGHUP/SIGTERM log out, and an engine disconnect is detected through a socket
monitor and logs out cleanly. `--format json` returns the same object that is
rendered, for every subcommand.

The defects are in four places:

- **Delivery (H1, C1).** The client subscribes to every `book.*` snapshot and
  every market maker's `quote.ack`, and only `BOOK` drains that backlog before
  asking. After a few seconds idle on a busy market the queue is full and the
  engine's reply to the next command is dropped: the operator sees TIMEOUT
  for a `HALT` that was executed. Separately, a fresh client can send its
  connect before its subscription has reached the engine; the reply is lost,
  the engine has the ID connected, and every later call is refused as
  "already connected" for up to three minutes.
- **Wrong target (C2).** A mistyped gateway id succeeds at every step of the
  documented incident runbook: `kill` (OK, 0/0), `kick` (sent), `qcancel`
  (OK), `orders` (none), `position` (none), all with exit 0. The engine
  already says `UNKNOWN_GATEWAY` for orders and positions; the client throws
  it away.
- **Failure paths (C3–C5).** `pm-admin` exits 0 when it cannot connect or is
  refused; a typed `[/` ends the session with a rich `MarkupError`;
  `pm-admin-cli` prints a `zmq.Again` traceback when the engine goes away
  between connect and command.
- **Output (C6–C8).** Text output carries ANSI escapes into pipes and files;
  `ORDERS`/`LEVEL` truncate ids and print `149.5`; `PRICE=nan` turns an
  asserted reopen price into "open at equilibrium".

Severity key: **High**: an operator command reported as failed while it was
executed, or a tool unusable in normal operation. **Med**: a wrong or
misleading answer to the operator; a failure that blocks later commands.
**Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Delivery | An idle client's SUB queue fills with `book.*`/`quote.ack` traffic; at 500 msg/s after 10 s idle every reply (VOLUME, ORDERS, HALT ack) is dropped and the command TIMEs OUT though the engine executed it *(repro)* | ADM01 |
| C1 | Med | Connect | The connect can overtake the SUB subscription: 1 in 19 and 1 in 82 fresh connects against the real engine missed the auth reply, and the ID was then refused for ~180 s (281 consecutive refusals) *(repro)* | ADM02 |
| C2 | Med | Targets | An unknown gateway id: `kill`, `kick`, `qcancel`, `orders`, `position` all report success and exit 0 *(repro)* | ADM03 |
| C3 | Low | Exit code | `pm-admin` exits 0 after a connect timeout, an auth refusal or a lost engine *(repro)* | ADM04 |
| C4 | Low | Console | A typed value containing `[/` raises `MarkupError` out of `_dispatch` and ends the session; so does any other unexpected exception *(repro)* | ADM04 |
| C5 | Low | CLI | Engine gone between connect and command: `zmq.Again` traceback, from the command and again from `disconnect()` in `finally` *(repro)* | ADM04 |
| C6 | Low | CLI output | `force_terminal=True` puts ANSI escapes into piped/redirected text output *(repro)* | ADM05 |
| C7 | Low | Input | `PRICE=nan`/`inf` is sent as `null`: `REOPEN` opens at the natural equilibrium instead of the asserted price, `LEVEL` shows the whole symbol; `--timeout 0`/negative accepted *(repro)* | ADM05 |
| C8 | Low | Display | `ORDERS`/`LEVEL` cut 32-character ids to 14 and print `str(price)` (`149.5`), stop orders show `—`; `REOPEN` prints raw floats; `position` JSON spread is `0.20000000000000284` | ADM05 |
| D1–D11 | — | Texts | See §5 | ADM03, ADM06 |

---

## 3. Correctness findings

### H1. An idle client loses its own replies on a busy market *(repro)* — High

`client.py:140-169` `_ACK_SUB_PREFIXES`, `:271-278` (subscribed for the
client's whole life), `:293-308` `_discard_pending` (called only by
`book_depth`, `:629`), `:329-400` `_recv`.

The SUB socket subscribes to `book.` (every symbol's snapshot, published per
dirty symbol at most every `snapshot_interval_sec` = 0.5 s,
`engine/main.py:1210-1224`) and `quote.ack.` (every market maker's quote
acks; no method ever awaits it). Nothing reads the socket while `pm-admin`
waits at its prompt. ZeroMQ queues up to the PUB's SNDHWM plus the SUB's
RCVHWM (both the default 1 000) and then **drops new messages** for this
subscriber. The next command's reply is one of those new messages: the engine
publishes it within milliseconds, while the client is still draining the
backlog oldest first.

Repro (stand-in engine with the real publisher, 50 symbols, a `book.<SYM>`
snapshot of 10 levels a side, client idle between commands):

| Feed rate | Idle | Queued | VOLUME | ORDERS | VOLUME again |
|---|---|---|---|---|---|
| — | 2 s | 0 | OK, 1 ms | OK, 1 ms | OK, 1 ms |
| 200 msg/s | 10 s | 2 000 | OK, 46 ms | OK, 53 ms | OK, 42 ms |
| 250 msg/s | 10 s | 2 500 | OK, 314 ms | | |
| 100 msg/s | 30 s | 3 000 | OK, 55 ms | | |
| 50 msg/s | 60 s | 3 000 | OK, 190 ms | | |
| 500 msg/s | 0.5 s | 250 | OK, 10 ms | OK, 9 ms | OK, 9 ms |
| 500 msg/s | 10 s | 5 000 | **TIMEOUT** | **TIMEOUT** | **TIMEOUT** |

The command itself is delivered (PUSH is a separate socket), so a mutating
command is **executed and reported as TIMEOUT**: `HALT`, `KILL`, `CANCEL_SYM`,
`REOPEN`, `SESSION`. In the 300-symbol sim configuration
(`docs/examples/ref_data/s300-sim-setup/`, default 0.5 s interval) the
snapshot stream alone can reach 600 msg/s, i.e. a full queue after a few
seconds of idle, before any `quote.ack`. The loss starts between 3 000 and 5 000 queued messages on this host (the two
socket HWMs plus kernel buffers), whatever the rate. The same backlog also hands the next
command a *stale* reply: a late ack of a command that timed out earlier, or
an `order.orders.<GW>` / `system.position_snapshot.<GW>` reply that another
client asked for (these topics are keyed by the target, not the requester,
L039). `pm-admin-cli` is not affected in practice: it sends its one command
right after connecting.

**Fix.** See Q1: drain before every request, and stop subscribing to what is
never awaited.

### C1. A connect can miss its own auth reply, and the ID is then locked for three minutes *(repro)* — Med

`client.py:259-278` (PUSH, then SUB connect and subscribe), `:406-428`
`connect`.

`connect()` sends `system.gateway_connect` as soon as the PUSH connection is
up (it retries `zmq.Again`), with nothing that waits for the SUB connection's
subscription to reach the engine's PUB socket. When the engine answers before
the subscription has arrived, the `system.gateway_auth.<id>` reply is not
delivered. The engine has the session connected (`engine/main.py:3051-3066`),
the client reports a timeout, and `pm-admin-cli` exits after `close()`
without a disconnect (`cli.py:333-339`). Nothing beats for that session, so
the engine frees it only after 3 × 60 s of silence (`_HEARTBEAT_MISSED_LIMIT`,
`GATEWAY_HEARTBEAT_INTERVAL_SEC`).

Repro, fresh `ExchangeCommandClient("OPS01").connect()` in a loop against the
real `pm-engine` (`o` = accepted and disconnected, `T` = timeout, `R` = refused):

```
ooooooooooooooooooTRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRRR … (281 R)
{'ok': 18, 'timeout': 1, 'refused': 281} | first refusal: Gateway already
connected: OPS01 — if that session is gone, the ID is freed within 179 s
```

A second run: 81 accepted, then one timeout, then 218 refusals. Against the
stand-in engine, which answers faster, 26 of 300 connects missed the reply.
Sixty sequential `pm-admin-cli session-status` processes against the real
engine all succeeded (process start-up gives the subscription time), so the
rate in scripts is lower than in the loop, but one miss is enough: a cron
job's every call then fails for three minutes with "Auth refused … (check
role: ADMIN in engine_config.yaml)" (D4). `pm-admin` has the same race at
start-up.

**Fix.** See Q2: prove the SUB path is live before sending the connect.

### C2. A mistyped gateway id succeeds at every step *(repro)* — Med

`client.py:604-612` `gateway_kick`, `:633-640` `order_list`,
`:807-822` `position_snapshot`; `console.py:763-827` `_cmd_kill`, `_cmd_kick`,
`_cmd_qcancel`, `:848-863` `_cmd_orders`, `:988-1054` `_cmd_position`;
`engine/main.py:4931-4991` `_handle_kill_switch_gateway`.

Against the real engine, with `NOSUCH01` not configured:

```
kill --gw NOSUCH01              -> exit 0 : KILL OK  NOSUCH01  orders=0  quotes=0
kick --gw NOSUCH01              -> exit 0 : KICK  sent disconnect for NOSUCH01
orders --gw NOSUCH01            -> exit 0 : No resting orders for NOSUCH01
position --gw NOSUCH01          -> exit 0 : No position or active quotes for NOSUCH01
qcancel --gw NOSUCH01 --sym AAPL -> exit 0 : QCANCEL OK  NOSUCH01  AAPL
```

- `order_list` and `position_snapshot` return only the list; the reply's
  `status` (`UNKNOWN_GATEWAY`, `NOT_CONNECTED`, L030) is dropped, so "unknown"
  and "nothing" print the same. `NOT_CONNECTED` is not shown either.
- `_handle_kill_switch_gateway` checks the caller and that a target is named
  (`:4989`), never that the target is a participant, so it acknowledges an
  unknown target with zero cancels. pm-api-gwy's
  `POST /admin/gateways/{id}/kill-switch` returns the same 200.
- `KICK` has no ack (`system.gateway_disconnect`); the engine silently
  ignores an unknown id (`:4703-4710`) and, for a configured but
  disconnected one, runs the disconnect behaviour again.

The operator guide's incident script (`020-admin-console-and-commands.md:690-710`,
`set -e`: halt, kill, kick, orders, resume) and training chapter 19's
micro-runbook are exactly this sequence. With a one-letter typo every step
reports success and the script resumes the market while the real participant
still has its orders and its session.

**Fix.** See Q3.

### C3. `pm-admin` exits 0 when it never got a session *(repro)* — Low

`console.py:1246-1264` `run` returns `None` on a connect timeout and on an
auth refusal; `:1444-1450` `main` ignores it, and a lost engine connection
also ends normally.

```
$ pm-admin --id GW_ADMIN </dev/null     # no engine running
Connection timed out.  Is the engine running?  (default: tcp://127.0.0.1:5555)
exit=0
```

pm-alf-console exits 1 in the same cases (WP-ACN05). A wrapper (pm-opctl,
a tmux launcher) cannot tell a refused console from a normal `EXIT`.

**Fix.** `run()` returns 1 for a timeout, a refusal and a lost engine, 0 for
`EXIT`/EOF/Ctrl-C; `main` exits with it.

### C4. A typed `[/` or any unexpected exception ends the console session *(repro)* — Low

`console.py:1213-1227` `_dispatch` catches `zmq.Again` and
`CommandTimeoutError` only; `run()` calls it unguarded (`:1311-1314`), so any
other exception leaves the prompt loop, logs out and prints a traceback.
Several printers put typed text into rich markup unescaped: the unknown-command
line (`:1146`), `Invalid PRICE: {price_str!r}` (`:725`, `:882`), `No resting
orders for {gw}` (`:333`), the `LEVEL` label (`:377-383`), and every engine
`reason` that echoes a typed symbol or id. Against the real engine:

```
'ORDERS|GW=[/x]':            MarkupError escapes _dispatch -> run() leaves the prompt loop
'LEVEL|SYM=AAPL|PRICE=[/b]': MarkupError escapes _dispatch -> run() leaves the prompt loop
'[/q]':                      MarkupError escapes _dispatch -> run() leaves the prompt loop
```

The ADMIN participants in the example configurations are `LEAVE_ALL`, so no
orders are cancelled, but the operator loses the session mid-incident. The
same path ends the session for a `CommandError` or a malformed reply.

**Fix.** Escape typed values and engine reasons (`rich.markup.escape`) where
they are printed; `run()` catches `Exception` around `_dispatch`, logs it
(`log.exception`) and prints one red line, as pm-alf-console does
(`alf_console/main.py:2319-2330`).

### C5. `pm-admin-cli` prints a traceback when the engine goes away *(repro)* — Low

`cli.py:355-369`: only `CommandTimeoutError` is caught around
`execute_command`, and `client.disconnect()` in `finally` can raise again.
`make_pusher` sends with `SNDTIMEO 0` and `IMMEDIATE`, so a send after the
engine connection dropped raises `zmq.Again`. Repro: a stand-in engine that
exits 0.2 s after answering the connect:

```
  File ".../commands/cli.py", line 346, in main
  File ".../commands/client.py", line 432, in disconnect
  ...
zmq.error.Again: Resource temporarily unavailable
exit=1
```

The exit code is right; the output is a 20-line traceback on stderr instead
of a sentence, and `--format json` prints nothing on stdout.

**Fix.** Catch `zmq.Again` around the command (print "Engine connection lost"
or `{"error": "engine_unreachable"}`, exit 1) and make the `finally`
disconnect best-effort.

---

### C6. Text output carries ANSI escapes into pipes and files *(repro)* — Low

`console.py:110-111`: one module-level `Console(..., force_terminal=True)`,
shared with `pm-admin-cli`. `force_terminal` exists for the REPL, whose
`patch_stdout` proxy hides the terminal. In `pm-admin-cli` it makes every
text-mode line coloured regardless of the destination:

```
$ pm-admin-cli --id GW_ADMIN halt | od -c | head -1
0000000 033 [ 1 ; 3 1 m H A L T E D 033 [ 0 m ...
```

`grep "HALTED  2 symbol"` on a log of a scripted run does not match, and
`NO_COLOR` is ignored. The tool is documented as the scripting one.

**Fix.** Force the terminal only for the REPL; `pm-admin-cli` lets rich
detect the destination.

### C7. Non-finite numbers are sent as "no value" *(repro)* — Low

`console.py:719-726` (`REOPEN`) and `:876-883` (`LEVEL`) accept anything
`float()` accepts; `cli.py:158-167` uses `type=float`. The generated builders
encode `nan` and `inf` as `null`:

```
make_force_uncross_msg('A','AAPL',price=nan)        -> {... 'price': None}
make_price_level_orders_request_msg('A','AAPL',inf) -> {... 'price': None}
```

`REOPEN|SYM=AAPL|PRICE=nan` therefore **opens at the natural equilibrium**,
the action the operator explicitly did not ask for, and `LEVEL …|PRICE=inf`
lists the whole symbol under the label `AAPL @ inf`. A negative or zero price
is refused by the engine for `REOPEN` (`engine/main.py` `_handle_force_uncross`,
"price must be positive") but not for `LEVEL`. `--timeout` accepts 0 and
negative values (`cli.py:103-109`): with 0, `connect()` gives up on the first
`zmq.Again` and reports "Connection timed out" against a running engine.

**Fix.** Refuse a non-finite or non-positive `PRICE` locally with the existing
"Invalid PRICE" line (exit 1); `--timeout` must be ≥ 1.

### C8. Ids, prices and derived figures are printed lossily — Low

- `_print_orders` and `_print_level` (`console.py:351-353`, `:397-399`) cut
  the order id to 14 characters (`o.get("id", "")[:14]`); engine ids are 32
  hex characters (`models/ids.py:13,43`), so the printed id matches nothing
  in pm-audit, the trader's console or the REST API.
- The same printers use `str(o.get("price"))`: `149.5` for 149.50, `12.5` for
  a 3-decimal `12.500`, although the reply carries `tick_decimals`
  (`engine/main.py:546-547`). A STOP order (no limit price) shows `—` and its
  `stop_price` is not shown at all.
- `REOPEN` prints `indicative_price`/`printed_price` raw (`:746`, `:755`):
  `100.0 x 500`, while the guide shows `100.00 x 500`.
- `POSITION` computes `spread = ask - bid` and `mid` in floats (`:1041-1043`):
  the JSON output for bid 149.70 / ask 149.90 is `"spread":
  0.20000000000000284` (the guide shows `0.20`); the text output hides it
  with `.4f` at every scale.

**Fix.** Full id; prices at `tick_decimals` (the `BOOK` helper already does
this, `:296-299`); a stop column (or `stop <px>` in the price cell); spread and
mid rounded to the symbol's decimals (plus one for mid).

---

## 4. Performance findings

Nothing here grows with history or with the day; every command is one engine
round trip (two for `POSITION`). Measured on this host against the real
engine:

| What | Time |
|---|---|
| `pm-admin-cli --id OPS01 session-status`, wall clock (5 runs) | 0.53–0.58 s, 55 MB RSS |
| of which `import edumatcher.commands.cli` | 0.43–0.46 s |
| of which `edumatcher.commands.console` (prompt_toolkit, rich) | 0.20 s cumulative |

The CLI imports the REPL's prompt_toolkit stack it never uses; at 0.55 s per
call a five-step runbook costs under 3 s, so no change is proposed. The drain
WP-ADM01 adds costs about 50 ms for a full 2 000-message backlog (the 200
msg/s row of H1) and nothing when the queue is empty.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `console.py:12-29` | The module docstring's command list omits `HALT_SYM`, `RESUME_SYM`, `CANCEL_SYM`, `SESSION_STATUS`, `SCHEDULE`, `GATEWAYS`, `VOLUME`. |
| D2 | `console.py:166-217` `_HELP_TEXT` | The in-console reference omits `SESSION_STATUS`, `SCHEDULE`, `GATEWAYS` and `VOLUME`, which the completer offers and the guide documents. |
| D3 | `console.py:1251-1254` | The timeout hint hard-codes `(default: tcp://127.0.0.1:5555)`; the address is `ENGINE_PULL_ADDR` (`EDUMATCHER_ENGINE_HOST`). |
| D4 | `cli.py:341-346`, `console.py:1258-1262` | Every refusal is followed by "(check role: ADMIN in engine_config.yaml)", including "already connected" and "not configured". The engine does not check the role at connect (`engine/main.py:2986-3075`): a TRADER id connects and each ADMIN command is refused later. |
| D5 | `cli.py:180` "# ---- Any connected gateway ----", `client.py:8` "Risk (any GW)", `:563` | `kill`/`qcancel` on another gateway use the ADMIN-only `risk.kill_switch_gateway`; the help strings of `kill`, `qcancel`, `kick`, `position` say nothing about roles while the others say "(ADMIN role required)". |
| D6 | `client.py:1-20` | The docstring lists 10 of the client's 30 methods; step 6 names `docs/commands.md`, which does not exist; step 3 ("add the ack prefix to `_ACK_SUB_PREFIXES`") changes with WP-ADM01. |
| D7 | `client.py:604-611` `gateway_kick`; guide `:409-413`, `:463-470` | "Verify the effect with `order_list`" / "Useful to confirm a `kill` or `kick` took effect … should print 'No resting orders'": orders say nothing about the connection (and stay for a `LEAVE_ALL` gateway); `GATEWAYS` does. "Exit code is always 0 if the engine is reachable" changes with WP-ADM03. |
| D8 | pm-help registry `pm_help/registry.py:2087-2228` | `pm-admin` lacks `REOPEN` and `POSITION`; `pm-admin-cli` lacks `reopen`, `level`, `position`, `--format` and the exit codes. |
| D9 | Reference manual `010-processes-environment-and-ports.md:3250-3375` | "without needing a full gateway session" (it authenticates as a participant); the sent-messages table lacks `risk.kill_switch_gateway` (KILL/QCANCEL on another gateway) and `system.quote_bootstrap_request` (POSITION); the subscribed table gives `quote.ack.{GW_ID}` as the QCANCEL ack (it is `quote.cancel_ack`), omits `risk.kill_switch_gateway_ack`, and lists `session.state`, which is not subscribed (the SESSION reply is `session.transition_ack`); the CLI table omits `position --sym` and the exit codes. |
| D10 | Operator guide `020-admin-console-and-commands.md` | Every example uses `--id GW_ADMIN` for both the console and the CLI, and the shell scripts use it while the chapter's console runs; a running console holds the id and the CLI is refused (training chapter 19 has the note, `190-advanced-admin-operations.md:40-44`; this chapter does not). |
| D11 | Operator guide, examples | The `position` text example shows a gateway header and an extra indent the code does not print (`console.py:438-458`); `LEVEL` ids `66d5940c-f1a7` are UUID-like, the real ones 32 hex; `149.50` in the `LEVEL` table is printed `149.5` today (C8); the JSON `spread`/`mid` (C8). |

---

## 6. Verified as correct

- **Ack subscriptions.** Every `_recv(topic_x(...))` prefix is in
  `_ACK_SUB_PREFIXES` (test enforced); `order.orders.` does not match
  `order.orders_request` (the request is PULL-only anyway).
- **Self versus other gateway.** `KILL`/`QCANCEL` on the console's own id use
  the self-service messages and on any other id the attributed
  `risk.kill_switch_gateway` (with `quotes_only` for `QCANCEL`); the engine
  checks the caller's ADMIN role (`engine/main.py:4977-4987`).
- **`execute_command` contract.** Every handler returns `(accepted, result)`;
  `--format json` prints exactly the returned object, and the CLI's exit code
  follows `accepted` (the `LEVEL` handler uses `not rejected`, matching its
  reply).
- **Heartbeat and logout.** The heartbeat thread has its own socket
  (`console.py:1175-1194`); `logout_on_hangup` ends the prompt the same way
  `EXIT` does; the engine-disconnect monitor is detached before the socket
  closes (`client.py:438-450`), avoiding the libzmq blocking-monitor hang.
- **SESSION.** An illegal transition is answered with the engine's reason and
  exit 1 (WP-FL08).
- **BOOK.** Drains the broadcast backlog first, so it never shows a stale
  snapshot; prices at the symbol's scale.
- **Volume.** The engine resets counters at `PRE_OPEN` and restart as the
  guide says; the reply is a list of per-symbol dicts as `_print_volume`
  expects (the client docstring's "dict of symbol →" is wrong, folded into
  D6).

---

## 7. Decisions

Answers (2026-11-23, user asked for all WPs in one go): Q2 and Q3 taken as
recommended, to confirm. Q1: **(b)** after (a) was built and measured
insufficient (draining the SUB pipe leaves the backlog in the TCP buffers and
the publisher's pipe); (b)'s subscription race is covered by re-sending
idempotent queries after 200 ms of silence.

| # | Question | Recommendation |
|---|---|---|
| Q1 | How does a request get its reply past the market-data backlog (H1)? (a) drain both SUB sockets before every request (move `_discard_pending` into the send path), and drop the never-awaited `quote.ack.` subscription; (b) subscribe to the exact reply topic per request and unsubscribe after; (c) raise RCVHWM | **(a)**: one place, works for every command, also removes stale late replies. (b) adds a subscription race to every command (the C1 mechanism). (c) only moves the threshold: a console idle for an hour overflows any bound, and a deeper queue means more stale data to wade through. |
| Q2 | How does `connect()` know its reply can arrive (C1)? (a) before the connect, send `system.session_state_request` (answered to anyone, `engine/main.py:2737-2750`) every 100 ms until its `system.session_status.<id>` reply arrives, then connect; (b) a fixed 0.1 s sleep, as pm-alf-console does; (c) on a timeout, send a disconnect to free the ID | **(a)**: it proves the exact path the auth reply takes, on any network. (b) is a guess that fails on a slower hop. (c) is dangerous: when the lost reply was a *refusal*, the blind disconnect logs out the other process that holds the ID. |
| Q3 | How do targeted commands treat an unknown or disconnected gateway (C2)? (a) `ORDERS`/`POSITION` use the reply `status`: `UNKNOWN_GATEWAY` is a failure (exit 1), `NOT_CONNECTED` is shown with a "(not connected)" note; the engine refuses an unknown target in `_handle_kill_switch_gateway` (`Gateway not configured: X`, also fixing the REST 200); `KICK` asks `gateway_list()` first and refuses an unknown id and a not-connected one (exit 1); (b) client-side only, a `gateway_list()` before every targeted command | **(a)**: the engine already knows and says it for queries; the kill-switch refusal belongs where the REST API gets it too. (b) costs a round trip per command and leaves REST accepting typos. The KICK pre-check is client-side because the disconnect message has no ack (§9, L044). |

---

## 8. Work packages

### WP-ADM01 — A reply is never lost to the market-data backlog of an idle console (H1; after Q1)

**Tests first** (`tests/test_commands_delivery.py`, real sockets, stand-in
engine fixture):

1. Stream `book.<SYM>` at 500 msg/s, leave the client idle 10 s, call
   `volume()`: the reply arrives within the 3 s timeout. (Fails today.)
2. Same backlog, then `halt_all()` against a stand-in that acks it: the ack
   arrives. (Fails today.)
3. A late `system.volume.<id>` reply published while the client is idle is
   not returned by the next `volume()` call; the fresh one is. (Fails today.)
4. `book_depth()` still returns a snapshot published after the request,
   unchanged.
5. `_ACK_SUB_PREFIXES` has no prefix that no method awaits
   (`tests/test_commands_ack_subscriptions.py`, extended). (Fails today:
   `quote.ack.`.)

**Change.** Call `_discard_pending()` at the start of every request (in
`_send`/`_send_index`, not in `connect`'s retry loop after the first send);
remove `PREFIX_QUOTE_ACK` from `_ACK_SUB_PREFIXES`; update the "Adding a new
command" steps in the module docstring.

**Exit criteria.** Tests 1–5 pass; `tests/test_commands*.py` green; the H1
table's 500 msg/s / 10 s row gives three OKs.

**Outcome (2026-11-23).** Q1 was implemented as option **(b)**, not the
recommended (a), and the review's §7 is corrected accordingly: draining
before every request (a) was built first and tested, and the scratch H1
repro still lost the first reply after 10 s idle at 500 msg/s. Draining
empties only the SUB-side pipe; the backlog held in the kernel TCP buffers
and the publisher's own pipe keeps the path full while the reply is
published. The client now subscribes for its whole life only to the exact
topics of replies addressed to its own id (`_OWN_ENGINE_TOPICS`,
`_OWN_INDEX_TOPICS`); a reply keyed by a symbol or a target gateway
(`book.<SYM>`, `order.orders.<GW>`, `system.position_snapshot.<GW>`,
`system.quote_bootstrap.<GW>`, `risk.kill_switch_ack.<GW>`,
`quote.cancel_ack.<GW>` for another gateway) is subscribed by the new
`_ask` for that one request and unsubscribed after. The subscription race
this opens is covered by re-sending an idempotent query after 200 ms of
silence (`_RESEND_AFTER_SEC`); the two non-idempotent self-service cancels
naming another gateway (reachable only through the Python API, the console
uses the ADMIN kill switch for others) wait 50 ms after subscribing. Every
command method now goes through `_ask`; `_recv` matches topics exactly
(a subscription is a byte prefix: `system.volume.GW_ADMIN` also delivered
`…GW_ADMIN2`). The drain before every request stays, for late replies of
timed-out commands. `quote.ack.` (never awaited) is no longer subscribed.

Tests: `tests/test_commands_delivery.py` (new; a stand-in engine thread and,
for the load case, a stand-in engine *process*
`tests/commands_standin_engine.py` streaming 3 000 snapshots/s, because
in-process the GIL let the client's drain win and the flood test passed for
the wrong reason). Failed first: the busy-market test (`CommandTimeoutError`
on `system.volume.GW_ADMIN`) and the stale-reply test (`111 == 222`).
`tests/test_commands_ack_subscriptions.py` rewritten for the new contract
(replies are awaited only through `_ask`/`connect`; every own topic is
awaited; a target-keyed reply is subscribed exactly around its request; an
own reply needs no temporary subscription); its new "no unawaited prefix"
test failed first on `quote.ack.`. Two existing tests adjusted: the
`__new__`-built client in the index-send test needs `_recv_queue`, and the
monitor test's `MagicMock` SUB socket (always "readable") became `None`.
`TestBookDepthIgnoresStaleSnapshots` keeps its purpose; its engine thread now
answers every request, since `BOOK` may be re-sent. Scratch H1 repro after
the change: 3 × OK in 1 ms (was TIMEOUT). Full suite: 15 436 passed,
1 skipped.

### WP-ADM02 — A connect never misses its own auth reply and locks the ID (C1; after Q2)

**Tests first** (`tests/test_commands_delivery.py`):

1. 300 fresh clients connect (and disconnect) in a loop against the stand-in
   engine: no timeout. (Fails today: 26/300.)
2. With an injected queue, `connect()` sends `system.session_state_request`
   before `system.gateway_connect` and does not send the connect until the
   status reply arrived. (Fails today.)
3. No engine: `connect()` raises `CommandTimeoutError` within the timeout,
   unchanged.
4. The engine refuses (ID held): the refusal is returned, no disconnect is
   sent. Unchanged.

**Change.** `connect()` probes with `make_session_state_request_msg(gw)` every
100 ms until `topic_session_status(gw)` is received or the timeout expires,
then sends the connect as today.

**Exit criteria.** Tests 1–4 pass; the scratch `real_race.py` loop against a
real engine: 300 × accepted.

**Outcome (2026-11-23).** Q2 taken as recommended. `connect()` first calls
the new `_await_reply_path`, which sends `system.session_state_request`
every 100 ms until the reply arrives on the client's own
`system.session_status.<id>` topic, then sends the connect as before (the
injected-queue test mode skips the probe). A probe that cannot reach the
engine ends in the same "Engine not reachable" `CommandTimeoutError`.

Test 1 changed from the plan: after WP-ADM01 the 300-connect loop no longer
failed against the stand-in (0/300; WP-ADM01's drain calls `poll()` on the
SUB socket before the connect, which lets ZeroMQ attach the pipe and send
the subscriptions when the TCP handshake is already done), while the real
engine still lost the reply (12 accepted, then 1 timeout and 987 "already
connected" refusals). A loop that passes before the fix proves nothing, so
it was replaced by a deterministic test: a stand-in engine that binds its PUB
socket 300 ms after its PULL socket, so the connect is answered before any
subscriber can be connected. It failed first with `CommandTimeoutError` on
`system.gateway_auth.GW_ADMIN` (3 of 3 runs), and the order test with no
`session_state_request` before the connect; the refusal test (no
disconnect sent) passed before and after. Exit criterion: the scratch loop
against a real `pm-engine`, 1 000 fresh connects, 1 000 accepted, 0
timeouts. Full suite: 15 439 passed, 1 skipped.

### WP-ADM03 — A mistyped gateway id fails every targeted command (C2, D7; after Q3)

**Tests first**:

1. `tests/test_engine_admin_scoped_cancel.py`: `risk.kill_switch_gateway`
   naming an unconfigured target is refused with `Gateway not configured:
   NOSUCH01` and an `admin.action` with `accepted: false`. (Fails today.)
2. Same file: a configured but disconnected target is still cleared
   (accepted, its resting orders cancelled), unchanged.
3. `tests/test_commands_console.py`: `ORDERS|GW=NOSUCH01` with an
   `UNKNOWN_GATEWAY` reply returns `False` and prints "Unknown gateway";
   `--format json` prints the reply with its `status`. (Fails today.)
4. Same: `ORDERS` with `NOT_CONNECTED` lists the orders and says "(not
   connected)". (Fails today.)
5. Same for `POSITION` with `UNKNOWN_GATEWAY`. (Fails today.)
6. `KICK|GW=NOSUCH01` and `KICK` of a configured but disconnected gateway
   send no `system.gateway_disconnect` and return `False` with a reason;
   `KICK` of a connected one sends it, unchanged otherwise. (Fails today.)
7. `tests/test_commands_cli.py`: `kill`, `kick`, `orders`, `position`,
   `qcancel` with an unknown `--gw` exit 1. (Fails today.)
8. `tests/test_api_gateway_admin.py`: the kill-switch endpoint for an unknown
   gateway answers the `KILL_SWITCH_REJECTED` error. (Fails today.)

**Change.** `order_list`/`position_snapshot` keep returning the list and raise
`CommandError` for `UNKNOWN_GATEWAY` (the documented Python API in the
operator guide's API section and training chapter 21 keeps its shape; only
this package calls them); a `NOT_CONNECTED` status is exposed through a
`status` keyword-only variant or attribute chosen in the WP; the handlers
print and return per Q3;
`_handle_kill_switch_gateway` refuses a target that is not in
`_allowed_participants`; `_cmd_kick` checks `gateway_list()` first. D7: the
`gateway_kick` docstring and the guide's kick passages say to check
`GATEWAYS`.

**Exit criteria.** Tests 1–8 pass; engine admin, commands and API admin suites
green; the C2 repro gives exit 1 for all five lines.

**Outcome (2026-11-23).** Q3 taken as recommended.
`Engine._handle_kill_switch_gateway` refuses a target that is not a
configured participant (`Gateway not configured: X`, with an
`admin.action` `accepted: false`), so `KILL`/`QCANCEL` on a typo fail, and
the REST kill switch answers 409 `KILL_SWITCH_REJECTED` instead of 200. The
client gained `orders_reply`/`positions_reply`, which return the engine's
whole reply plus the `gateway_id` asked about (the reply body names it only
in its topic); `order_list`/`position_snapshot` keep their list shape for
the documented Python API and raise `CommandError` for `UNKNOWN_GATEWAY`.
`ORDERS` and `POSITION` fail on `UNKNOWN_GATEWAY` with `REJECTED  Gateway not
configured: X` and print `X is not connected (stored state shown)` for
`NOT_CONNECTED`; their `--format json` output is now
`{gateway_id, status, orders}` / `{gateway_id, status, positions}`
(previously a bare list; documented in WP-ADM06). `KICK` asks `gateway_list()`
first and refuses an unknown or a not-connected id without sending anything.
D7: the `gateway_kick` docstring and the guide's `kick`, `orders`,
`gateway_kick` and `order_list` passages now say to check `GATEWAYS`.

Failed first: the engine test (`accepted` was `True`), five console tests
(ORDERS/POSITION unknown and not-connected, KICK unknown and disconnected),
the CLI exit-code test (the console still called `order_list`), and the
client tests (`CommandError` not raised). Plan test 8 (REST) was not added:
the API passes the engine's verdict through `_require_accepted`, which
`tests/test_api_gateway_admin.py:278` already covers with a refusing fake
engine; the new behaviour is the engine's and is tested there. Five existing
POSITION tests were updated for the new result shape. Real engine: the five
C2 commands with `NOSUCH01` now all exit 1 with `Gateway not configured`;
`orders --gw TRADER01` (logged off) prints the not-connected line and exits
0; `kick --gw TRADER01` exits 1 (`Gateway not connected`). Full suite:
15 452 passed, 1 skipped.

### WP-ADM04 — No typed line or lost engine ends with a traceback, and both tools exit non-zero on failure (C3, C4, C5)

**Tests first**:

1. `tests/test_commands_console.py`: `AdminConsole.run()` with a client whose
   `connect` times out returns 1; with a refused auth returns 1; with
   `EXIT` returns 0; `main()` exits with that code. (Fails today.)
2. Same: `_dispatch("ORDERS", {"GW": "[/x]"})`, the unknown command `[/q]` and
   `PRICE=[/b]` print the literal text and raise nothing. (Fails today.)
3. Same: a handler raising `RuntimeError` inside the scripted `run()` loop
   prints one "Command failed" line and the next line is still read. (Fails
   today.)
4. `tests/test_commands_cli.py`: `zmq.Again` from the command send exits 1
   with "Engine connection lost" on stderr (text) or
   `{"error": "engine_unreachable"}` on stdout (json), no traceback; a
   `zmq.Again` from the final disconnect is ignored. (Fails today.)

**Change.** `run()` returns an int; `main` passes it to `sys.exit`; typed
values and engine reasons go through `rich.markup.escape`; `run()` guards
`_dispatch` with `except Exception` + `log.exception`; `cli.main` catches
`zmq.Again` and wraps the final disconnect.

**Exit criteria.** Tests 1–4 pass; commands suites green.

**Outcome (2026-11-23).** `AdminConsole.run()` returns 1 after a connect
timeout, an auth refusal or a lost engine and 0 after `EXIT`/EOF/Ctrl-C or a
hangup; `main()` exits with it. `run()` guards `_dispatch` with
`except Exception`, logs it (`log.exception`, new ledger entry
`log_ledger/entries/admin_console.yaml`, required by
`test_every_call_site_has_an_entry`, which failed the first full run) and
prints `Command failed: …`. Every string from the operator or the engine that
reaches rich markup goes through `rich.markup.escape`, including table titles
and cells (rich parses those too): ids, symbols, gateways, descriptions,
reasons, typed prices and the unknown-command line. `pm-admin-cli` catches
`zmq.Again` from the command (`Engine connection lost (<addr>).` on stderr,
or `{"error": "engine_unreachable"}`) and ignores it from the final
disconnect.

Failed first: the exit-code tests (`None == 1`, `DID NOT RAISE SystemExit`),
four markup cases with `MarkupError` and the engine-reason case, the
catch-all test (`RuntimeError` escaped), both CLI cases (`zmq.Again`). One
planned case was wrong: `POSITION|GW=[/x]` prints no gateway at all, so it
was replaced by `KILL|GW=[/x]`. The markup tests render through a real rich
`Console` on a `StringIO`; the existing print-capturing fake would never
parse markup. `test_main_parses_id_and_runs` now expects `SystemExit(0)`.
Real processes: `pm-admin` with no engine exits 1 (was 0); `pm-admin-cli
halt` against a stand-in that exits after the auth: timeout line and exit 1,
no traceback (the send itself was still delivered, so the command path's
`zmq.Again` is covered by the unit test only). Full suite: 15 464 passed,
1 skipped.

### WP-ADM05 — Script output is plain text, prices and ids are shown as they are, and bad numbers are refused locally (C6, C7, C8)

**Tests first** (`tests/test_commands_console.py`, `tests/test_commands_cli.py`):

1. `pm-admin-cli halt` with stdout redirected to a file writes no `\x1b[`.
   (Fails today.)
2. The REPL console still forces ANSI under `patch_stdout`, unchanged.
3. `REOPEN|SYM=AAPL|PRICE=nan`, `PRICE=inf`, `LEVEL|…|PRICE=-1` and
   `reopen --price nan` print "Invalid PRICE", send nothing and return/exit
   failure. (Fails today.)
4. `--timeout 0` is a usage error (exit 2). (Fails today.)
5. `ORDERS` and `LEVEL` print the full 32-character id and `149.50` for a
   2-decimal symbol, `12.500` for a 3-decimal one, and a STOP order's stop
   price. (Fails today.)
6. `REOPEN` prints `100.00 x 500`; `POSITION` JSON for bid 149.70 / ask 149.90
   has `spread` 0.2 exactly. (Fails today.)

**Change.** Create the console with `force_terminal` only in `AdminConsole.run`
(or let `cli.main` swap in a detecting console); a `_parse_price` helper
refusing non-finite and non-positive values; `--timeout` with a positive-int
type; printers use a `tick_decimals` formatter (shared with `_print_book`);
spread/mid rounded.

**Exit criteria.** Tests 1–6 pass; commands suites and
`tests/test_shell_completion.py` green (`make completion` if help changes).

**Outcome (2026-11-23).** C6: the shared console keeps `force_terminal=True`
for the REPL (rich fixes its colour system when the console is created, and
`patch_stdout` hides the terminal), and `pm-admin-cli` swaps in a plain
`Console()` before running its command, so a pipe or a file gets plain text
and `NO_COLOR` is honoured. C7: a new `_parse_price` refuses a non-finite or
non-positive `PRICE` locally ("Invalid PRICE: 'nan' is not a positive
number", nothing sent) for `REOPEN` and `LEVEL`; `--timeout` must be ≥ 1
(argparse error, exit 2). C8: `ORDERS`/`LEVEL` print the full order id (the
ID column no longer wraps) and prices at the order's `tick_decimals` through
a shared `_px` (also used by `BOOK`), with `stop <px>` for stop orders; the
client caches each symbol's `tick_decimals` from the symbols reply
(`tick_decimals()`, filled by `symbol_list()` or on first use: one extra round
trip for a one-shot `reopen`/`position`), which `REOPEN` and `POSITION` use;
`POSITION` rounds spread to the symbol's decimals and mid one place finer in
the data and prints bid/ask/spread/mid at that scale (avg cost stays at four
decimals: it is a VWAP, not on the grid).

Failed first: five price-refusal cases (`True is False`), both table cases
(14-character id), the reopen text (`100.0 x 50`), the spread
(`0.20000000000001705`), the timeout, the ANSI and the CLI `nan` tests; the
REPL-still-forced test passed before and after. The CLI tests got an autouse
fixture restoring the shared console, since `main()` now replaces it and a
later REPL test on the same xdist worker would see the swapped one. Real
engine: `session-status | od -c` has no escapes; `reopen --price nan`
exit 1 with nothing sent; `--timeout 0` exit 2. Full suite: 15 477 passed,
1 skipped.

### WP-ADM06 — Comments, help texts and guides say what the code does (D1–D6, D8–D11)

**Tests first.** None for texts; the `pm-help` registry consistency tests and
`tests/test_shell_completion.py` must stay green.

**Change.** D1–D6 in the code; D8 registry entries (`pm-admin` REOPEN,
POSITION; `pm-admin-cli` reopen, level, position, `--format`, exit codes
0/1/2); D9 reference manual tables; D10 a note in the operator guide that the
console and the CLI need separate ADMIN ids, and the scripts use a CLI id;
D11 the examples regenerated from the code. Re-walk the guide's incident
scripts and training chapter 19 against the final behaviour (lessons B1).

**Exit criteria.** Every D item resolved; `make _check` green; `mkdocs build`
without new warnings.

**Outcome (2026-11-23).** D1–D6 in the code: the console module docstring
and `HELP` list every command (`HALT_SYM` … `VOLUME`); the timeout hint names
`ENGINE_PULL_ADDR`; the "(check role: ADMIN …)" hint is gone from both tools
(the refusal reason says what is wrong, and the role is checked per command);
`cli.py`'s help says which per-gateway commands need ADMIN for another
gateway, that `kick` refuses an unknown or disconnected gateway, and that
`--id` must not be one a running console holds; its docstring lists exit
codes 0/1/2; the client docstring lists all its methods, marks the
self-service messages (L044), and step 6 names the operator guide;
`volume()`'s docstring says list. `make completion` regenerated
`pm-completion.zsh`. D8: registry entries for `REOPEN`, `POSITION`, `reopen`,
`level`, `position`, `--format`, both tools' exit codes and the one-id note.
D9: reference manual tables (messages per command, own vs per-request
subscriptions, `session.transition_ack`, `position --sym`, CLI exit codes).
D10/D11: the operator guide's CLI examples use `ADMIN_CLI` with a note on
one id per running client; exit codes; the JSON shapes of `orders` and
`position`; the `position` text and JSON examples; the `LEVEL` tables
regenerated from the real printer; the Python API table (self-service
messages are not checked, `orders_reply`/`positions_reply`/`tick_decimals`,
`session_advance`'s ack is `session.transition_ack.{GW}`, not
`session.state`).

Re-walk (lessons B1), beyond the plan: the guide's Python incident example
used the self-service `kill_switch("TRADER01")` from the ADMIN client; it now
uses `kill_switch_gateway` and checks `accepted`. Training chapter 21
Exercise 3 the same. The guide's `set -e` incident script: after WP-ADM03
`kick` exits 1 for a participant that already logged off, which would stop
the script with the market halted; the line now ends in `|| true` with a
comment (a typo still stops the script at `kill`, which refuses unknown ids).
Training chapter 19 needs no change (its `KICK` targets a connected
`TRADER02`). `mkdocs build`: one warning before and after (not in these
pages). Full suite: 15 477 passed, 1 skipped.

### Holistic review (2026-11-23)

All changes re-read as one diff (`commands/client.py`, `console.py`,
`cli.py`, `engine/main.py` `_handle_kill_switch_gateway`, registry, the
books), looking for interference between the WPs, and every flow re-run
against a real `pm-engine` (`s1-basic-setup`, ADMIN `OPS01`): all 19
`pm-admin-cli` subcommands, `--format json orders`, and the interactive
`pm-admin` in a pty (a `[/x]` line, a typo'd `KICK`, `VOLUME`, `EXIT`: the
markup printed literally, the `KICK` refused, the session kept, exit 0).

- **HR1 (fixed, WP-ADM05 × the H1 lesson).** `REOPEN` looked up the symbol's
  decimals *after* sending the uncross. In `pm-admin-cli` that lookup is a
  fresh round trip, and a timeout there would have reported an executed
  reopen as TIMEOUT with exit 1, exactly the H1 consequence. The lookup now
  runs before the command (text output only; JSON needs none), so a timeout
  means nothing was sent. Tests: the lookup comes first and a timeout in it
  sends nothing (failed first: `force_uncross` was called), JSON mode does
  no lookup. `POSITION`'s lookup is read-only and stays after its queries.
- **Checked, no change.** WP-ADM01's drain in `_send` runs before WP-ADM02's
  probes and before the `KICK` pre-check, never between a request and its
  reply. Re-sends (WP-ADM01) only apply to `BOOK`, `ORDERS`, `POSITION` and
  quote bootstrap, all read-only. `orders_reply`/`positions_reply`
  (WP-ADM03) go through the temporary subscriptions of WP-ADM01. The escaped
  strings (WP-ADM04) include everything WP-ADM03 and WP-ADM05 added to the
  output. `pm-admin-cli` swaps the shared console (WP-ADM05) after connect,
  so the auth and timeout lines are unaffected; the CLI tests restore it.
  `pm-index-admin-cli` uses the same client; its `index_*` replies are own
  topics on the index SUB socket, and its timeout text changed with
  `_recv` ("No ack on …"), now also in the index-administration guide.
- **Texts added in the review:** the guide's `kill`/`qcancel` sections and
  the REST chapter's kill-switch endpoints say that an id that is not
  configured is refused (the REST answer for it is now 409, not 200).

Full suite after the review: 15 479 passed, 1 skipped.

---

## 9. Out of scope, noted

- **Target-only commands are unauthenticated and unattributed (new L044).**
  `risk.kill_switch`, `quote.cancel` and `system.gateway_disconnect` carry only
  the gateway they act on, which is also the reply topic; the engine cannot
  tell the participant from anyone else on the PUSH socket. `pm-admin`'s
  `KICK` therefore reaches the audit trail as the target's own logout, with
  the operator's id nowhere, and has no ack (C2's client-side pre-check is
  the most this component can do). Same class as L039; a fix is an ADMIN
  `risk.gateway_kick` message with requester, ack and `admin.action`, which
  is an engine and wire change for 1.x.
- **`LEVEL` rounds an off-grid price filter** to the nearest tick
  (`engine/main.py:3130-3132`): already L043.
- **Orders/position replies are keyed by the target (L039)**: another
  client's reply for the same target can satisfy the console's wait. With
  WP-ADM01's drain only a reply published during the wait can be taken, and
  its content is the same snapshot.
- **`pm-index-admin-cli`** shares `ExchangeCommandClient`; its own commands
  (`index_*`) were not reviewed. WP-ADM01's drain also applies to its
  `_send_index` path, and WP-ADM03 changes `order_list`'s return type, which
  it does not use.
- **`emo/` (`pm-opctl-cli`)** is the other half of CR03 in the
  remaining-reviews workplan and is not covered here.
- **Re-sent queries reach other subscribers too.** An idempotent query
  re-sent after 200 ms of silence (WP-ADM01) makes the engine publish a
  second reply on a topic keyed by the target (`system.position_snapshot.X`,
  `book.X`), which the target's own clients also receive. The content is the
  same snapshot, and a slow engine is the only trigger.
- **pm-index-admin-cli has the C1 race on its own path.** `pm-index` has no
  connect handshake, so a first request can still be answered before the
  index SUB subscription arrives (unchanged by this review; the drain's
  `poll()` makes it rarer). A probe like WP-ADM02's needs a request
  `pm-index` answers to anyone.
