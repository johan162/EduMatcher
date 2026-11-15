# Automation with CommandClient & MM Bot Tuning

## Objective

Use EduMatcher's programmatic command client for repeatable admin workflows and
practice advanced `pm-mm-bot` runtime tuning for startup and reconciliation.

 
!!! abstract "Background reading"
    - [The Admin Console and Exchange Commands](../operator-guide/part-3-run/020-admin-console-and-commands.md)
    - [Market-Maker Bot](../participant-guide/part-3-market-making/030-the-market-maker-bot.md)

## Prerequisites

- Chapters 01-21 completed.
- Engine running with `GW_ADMIN` and at least one MM gateway configured.
- Python environment able to import `edumatcher.commands`.

 

## Background

The interactive tools are excellent for manual operation, but production-like
operations often require deterministic automation:

- One-shot operator runbooks (halt/resume, symbol cleanup, gateway checks).
- Repeatable incident actions with explicit timeouts.
- MM bot tuning for startup reliability in sparse-book conditions.

This chapter combines two advanced surfaces:

1. `ExchangeCommandClient` (programmatic admin command API).
2. Advanced `pm-mm-bot` runtime flags such as bootstrap timeout and QLEGS
   reconciliation interval.

 

!!! warning "Close `pm-admin` and the MM console first"
    `ExchangeCommandClient("GW_ADMIN")` logs on as `GW_ADMIN`, and the bot in
    Exercise 4 as `MM_AAPL_01`. The engine allows one connection per
    participant, so leave any open `pm-admin --id GW_ADMIN` and
    `pm-alf-console --id MM_AAPL_01` (`Ctrl-C`) before running the scripts.
    If you forget, `connect()` does **not** raise: it returns
    `accepted: False, reason: 'Gateway already connected: GW_ADMIN'`, read-only
    calls such as `symbol_list()` still work, and only the commands that change
    something fail. A script that matters should check `auth["accepted"]`.

## Exercise 1: Run a Minimal CommandClient Session

Execute a short Python script:

```bash
python - <<'PY'
from edumatcher.commands import ExchangeCommandClient

with ExchangeCommandClient("GW_ADMIN") as client:
    auth = client.connect()
    print("auth:", auth)
    symbols = client.symbol_list()
    print("symbols:", symbols)
    state = client.session_status()
    print("session:", state)
PY
```

Expected:

```
auth: {'gateway_id': 'GW_ADMIN', 'accepted': True, 'reason': '', 'description': ''}
symbols: ['AAPL', 'MSFT', 'TSLA']
session: {'state': 'CONTINUOUS', 'sessions_enabled': True}
```

:material-checkbox-blank-outline: **Checkpoint:** you can connect, read symbols, and read session status programmatically.

 

## Exercise 2: Script a Safe Symbol-Protection Runbook

Run a scripted sequence:

```bash
python - <<'PY'
from edumatcher.commands import ExchangeCommandClient

with ExchangeCommandClient("GW_ADMIN") as c:
    c.connect()
    c.symbol_halt("AAPL")
    c.cancel_symbol("AAPL")
    book = c.book_depth("AAPL")
    print("AAPL bids:", len(book.get("bids", [])), "asks:", len(book.get("asks", [])))
    c.symbol_resume("AAPL")
    print("AAPL resumed")
PY
```

It prints `AAPL bids: 0 asks: 0` and `AAPL resumed`. This is easier to run
consistently than a manual multi-step console sequence.

Now run it a second time, straight away. A runbook script is run again
whenever someone is unsure whether the first run finished, so it must be
**idempotent**: the second run must end in the same state (AAPL trading, its
book empty) and must not fail just because there is nothing left to cancel.
This one is, because every step it takes is safe to repeat.

:material-checkbox-blank-outline: **Checkpoint:** you can automate halt/cancel/verify/resume for one symbol, and the script runs twice in a row with the same result.

 

## Exercise 3: Automate Gateway Exposure Cleanup

Use API methods to clear one participant and verify no resting orders remain:

```bash
python - <<'PY'
from edumatcher.commands import ExchangeCommandClient

target = "TRADER02"

with ExchangeCommandClient("GW_ADMIN") as c:
    c.connect()
    c.kill_switch(target)
    orders = c.order_list(target)
    print("remaining orders for", target, ":", len(orders))
PY
```

Optional extension:

- Add `gateway_kick(target, reason=...)` after `kill_switch` when operational
  policy requires immediate disconnect.

:material-checkbox-blank-outline: **Checkpoint:** you can explain when to use kill-switch only vs. kill-switch + kick.

 

## Exercise 4: Tune pm-mm-bot Startup Reliability

Run one bot with explicit startup controls. A bot started on an empty book
with no range to draw a price from stops with
`startup failed: no reference price available`, and the last trade price saved
from an earlier session does not count, so the command gives it a start range:

```bash
pm-mm-bot \
  --symbol AAPL \
  --gap 0.10 \
  --qty 500 \
  --initial_min 149.00 \
  --initial_max 151.00 \
  --startup-session-timeout-sec 5.0 \
  --bootstrap-timeout-sec 1.0 \
  --qlegs-reconcile-interval-sec 15.0 \
  -v
```

Its log is long; look for:

- Bootstrap reference resolution (existing quote adopted, or a random-range
  price).
- Session readiness before the first quote.
- QLEGS reconciliation, which is silent while everything agrees and only
  logs when it finds a mismatch.

Every bot log line is prefixed with the bot's gateway ID (`[<gateway_id>]`),
and per-symbol lines add a `[<symbol>]` tag. Representative startup lines
(after the usual timestamp/level/logger prefix):

```
[MM_AAPL_01] starting: gateway=MM_AAPL_01 symbols=AAPL
[MM_AAPL_01] [AAPL] strategy=symmetric gap=0.1 qty=500 tif=DAY drift_ticks=3
[MM_AAPL_01] [AAPL] book mid=None
[MM_AAPL_01] [AAPL] bootstrap from random range: 149.12
[MM_AAPL_01] [AAPL] QUOTE sent bid=149.07 ask=149.17
[MM_AAPL_01] running symbols=['AAPL'] session=CONTINUOUS
[MM_AAPL_01] [AAPL] quote ACK id=MM_AAPL_01-AAPL-…
[MM_AAPL_01] [AAPL] quote.status: ACTIVE
```

At startup the bot asks the engine for the AAPL book. `book mid=None` means
it was empty (Exercise 2 cleared it), so the price came from the
`--initial_min`/`--initial_max` range. With quotes or orders on both sides
of the book, the bot takes the book's mid instead, and the `bootstrap from
random range` line does not appear.

**Now without the range.** Stop the bot (`Ctrl-C`; it cancels its quote on
the way out, so the book is empty again) and start it with no price source
at all:

```bash
pm-mm-bot --symbol AAPL -v
```

```
[MM_AAPL_01] [AAPL] book mid=None
[MM_AAPL_01] startup warning: [AAPL] startup failed: no reference price available (no book, no trade, no bootstrap, no random range)
[MM_AAPL_01] startup warning: startup failed: no symbol survived startup checks
pm-mm-bot exiting with code 1
```

It fails fast and says why. On a fresh exchange, give a bot a range; on a
busy one, the book is enough.

:material-checkbox-blank-outline: **Checkpoint:** you can identify the timeout knobs that control startup, and say which price source a bot uses on an empty and on a busy book.

!!! note "Most of these knobs can differ per symbol"
    `--bootstrap-timeout-sec` and `--qlegs-reconcile-interval-sec` are
    per-symbol settings: on a multi-symbol bot each symbol may be given its
    own, either by scoping the flag after that symbol's `--symbol` or from
    its block in a config file (see [02 — Setting Up Market-Maker
    Liquidity](020-setting-up-MM-bots.md), Exercise 8).
    `--startup-session-timeout-sec` is the exception and stays process-wide,
    because the session phase it waits for is exchange-wide and there is
    nothing per-symbol to express.

    The QBOOT/QLEGS *requests themselves*, and the startup/gap checks they
    inform, run once per symbol regardless. A
    `pm-mm-bot --symbols AAPL,MSFT,TSLA -v` run shows three independent
    `[AAPL]`/`[MSFT]`/`[TSLA]`-tagged QBOOT and QLEGS exchanges in the
    startup log, not one — so a `--bootstrap-timeout-sec` tuned down
    aggressively for a fast classroom demo is a budget applied to *each*
    symbol's round trip in turn, not split across them.

 

## Summary

You now have advanced operational coverage for:

- Programmatic admin orchestration with `ExchangeCommandClient`.
- Repeatable incident-response style command sequencing.
- Practical `pm-mm-bot` tuning for startup/bootstrap/reconciliation behavior.

## Reflection

Why does this chapter insist your automation scripts be idempotent (safe to
rerun) rather than accepting "runs correctly once" as good enough? Think
about an incident-response scenario at 3am — what goes wrong if an on-call
engineer reruns a non-idempotent halt/clear/resume script by mistake?

## Further Reading

- [Controlling the Exchange](../operator-guide/part-3-run/020-admin-console-and-commands.md)
- [The Market-Maker Bot (`pm-mm-bot`)](../participant-guide/part-3-market-making/030-the-market-maker-bot.md)
- [Market-Maker Bot CLI Reference](../participant-guide/part-3-market-making/030-the-market-maker-bot.md#cli-reference)
- [Market-Maker Bot — Per-symbol failure isolation](../participant-guide/part-3-market-making/030-the-market-maker-bot.md#per-symbol-failure-isolation)
- [02 — Setting Up Market-Maker Liquidity — one bot, multiple symbols](020-setting-up-MM-bots.md)
- [Processes, Environment and Ports](../reference-manual/part-1-command-line/010-processes-environment-and-ports.md)

You have completed the operator track. The remaining chapters (23–28) cover the external protocols — RALF, CALF, the REST/WebSocket API, the market index, and the ALF/BALF TCP gateways.