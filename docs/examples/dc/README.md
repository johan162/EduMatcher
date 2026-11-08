# DC1 (drop-copy) example clients and parser libraries

This directory contains:

- `dc_parser.py`: Python parser/serializer library for DC1 lines
- `dc_subscriber.py`: Python subscriber example using the Python library
- `dc_parser.h` + `dc_parser.c`: C parser library for DC1 lines
- `dc_subscriber.c`: C subscriber example using the C library
- `Makefile`: build helper for the C client

Both subscribers connect to `pm-dc-gwy` for one participant's gateway ID and
put the received `DC_FILL` lines to use the way a risk or back-office system
would: a running per-symbol tally of fills, executed quantity, VWAP and the
`MAKER`/`TAKER` split. `DC_FILL` carries no side, so this is an activity
tally, not a net position. Both examples also check the drop-copy `SEQ` for
gaps and restarts, and shut down cleanly on Ctrl-C with a final summary.

See [Drop-Copy TCP Gateway](../../books/operator-guide/part-5-gateways/060-drop-copy-gateway.md)
for the wire contract both clients follow, and
[Drop Copy](../../books/protocols-and-clients/part-3-session-behaviour/060-drop-copy.md)
for where the feed comes from.

## DC1 wire format

Messages are text lines:

```text
MSGTYPE|KEY=VALUE|KEY=VALUE\n
```

## Run Python example

```bash
cd docs/examples/dc
python3 dc_subscriber.py --host 127.0.0.1 --port 5590 --id TRADER01
```

`--id` is the participant whose fills you receive. It is not checked against
any allowlist: drop copy has no entitlement model. To watch several
participants, run one client per ID.

Run `python3 dc_subscriber.py --help` for the full flag list.

## Build and run C example

```bash
cd docs/examples/dc
make
./dc_subscriber 127.0.0.1 5590 TRADER01
```

Arguments are positional: `host [port [gateway_id]]` (defaults
`127.0.0.1 5590 TRADER01`). Press Ctrl-C for a clean shutdown: the client
sends `EXIT`, then prints the final per-symbol tally.

## Sequence numbers

`SEQ` is a separate counter for each gateway ID, starting at 1, so a DC1
session sees its own ID's fills numbered `1, 2, 3, …`. The examples report two
things on stderr:

- a `SEQ` that skips ahead: fills were lost (`!! SEQ gap`). DC1 has no
  replay, so the missing fills have to be recovered some other way;
- a `SEQ` at or below the last one seen: not a duplicate but an engine
  restart, which starts the counter again from 1 (`!! SEQ went backwards`).

Either way the new value becomes the baseline.

## Session behaviour

The same in all three line gateways (`pm-md-gwy`, `pm-ralf-gwy`,
`pm-dc-gwy`), and what both examples rely on:

- **Send `HELLO` straight after connecting.** A connection that sends none
  within 5 seconds gets `EXIT|REASON=auth_timeout` and is closed.
- **Check the reply.** `ERR|CODE=AUTH_REQUIRED` (missing `CLIENT`/`ID`, or
  `PROTO` not `DC1`) in reply to `HELLO` is the gateway refusing the session;
  it closes the connection, so both examples print the error and exit with
  status 1.
- **No `SUB`.** The `ID` in `HELLO` is the whole subscription; `DC_FILL`
  lines start arriving straight after `WELCOME`.
- **Errors are `ERR|CODE=..|DETAIL=..`.** `SLOW_CLIENT`, and `BAD_MESSAGE`
  for a line over 4096 bytes, end the session (the gateway sends the line,
  then closes); every other code leaves it open.
- **The gateway announces its own closes.** Besides the terminal `ERR`s, it
  sends `EXIT|REASON=idle_timeout` or `EXIT|REASON=auth_timeout` before
  closing. Both examples print the reason and exit with status 1.
- **No `PING` needed.** Traffic in both directions counts against the idle
  timeout, so a client that keeps reading stays connected on the gateway's
  own `HB` lines.
- **`EXIT` works both ways.** On Ctrl-C both examples send a bare `EXIT`;
  the gateway flushes what is queued, then closes.

## What the examples send

- `HELLO|CLIENT=...|PROTO=DC1|ID=<gateway_id>`
- `EXIT` on Ctrl-C

Then they parse incoming `DC_FILL`/`HB`/`ERR`/`EXIT` lines and keep the
per-symbol fill tally described above.
