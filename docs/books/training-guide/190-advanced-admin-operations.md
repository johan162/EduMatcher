# Advanced Admin Operations

## Objective

Practice the two targeted exchange-operator controls the earlier chapters
did not use — `KICK` and `QCANCEL` — and combine them with `CANCEL_SYM` (used
since chapter 08) into a short incident runbook, in both the console and the
one-shot CLI.

 


!!! abstract "Background reading"
    - [The Admin Console and Exchange Commands](../operator-guide/part-3-run/020-admin-console-and-commands.md)

## Prerequisites

- Chapters 01-18 completed.
- `GW_ADMIN` configured with `role: ADMIN`.
- Engine running with `pm-admin --id GW_ADMIN`, `TRADER01`, `TRADER02` and a
  `MM_AAPL_01` console connected, and the market open in `CONTINUOUS`. After
  chapter 17's engine restart, start any of these consoles again.

 

## Background

Earlier risk-control exercises focused on halt/resume and kill switch. In live
operations, admins also need targeted controls for:

- Disconnecting a specific participant (`KICK`).
- Cancelling one MM quote on one symbol without killing the whole gateway (`QCANCEL`).
- Clearing one symbol's resting book across all gateways (`CANCEL_SYM`).

These controls exist in both:

- Interactive admin console (`pm-admin` / ALF commands).
- One-shot scripting CLI (`pm-admin-cli`).

!!! note "Use a separate identity for each operator client"
    The interactive console uses `GW_ADMIN`; one-shot commands use
    `ADMIN_CLI`. The chapter 01 configuration defines both as ADMIN so the
    console and CLI can stay connected at once. A duplicate live connection
    with the same participant ID is refused.

 

## Exercise 1: Disconnect a Gateway with KICK

From admin console:

```
[GW_ADMIN|ADMIN]> KICK|GW=TRADER02|REASON=Training_disconnect_check
```

Or with CLI:

```bash
pm-admin-cli --id ADMIN_CLI kick --gw TRADER02 --reason "Training disconnect check"
```

Verification:

1. The `TRADER02` console is **not told** it was kicked; its prompt looks
   unchanged. Confirm the disconnect from the operator side with `GATEWAYS`
   (`TRADER02` now shows `no` under *Connected*), and from the trader side by
   sending any order: it is refused with
   `code=AUTH_REQUIRED  Gateway not connected: TRADER02`.
2. Leave that console (`EXIT`) and reconnect with a fresh one:

```bash
pm-alf-console --id TRADER02
```

:material-checkbox-blank-outline: **Checkpoint:** gateway is disconnected and can reconnect cleanly.

 

## Exercise 2: Cancel One MM Quote with QCANCEL

Give `MM_AAPL_01` an active quote on AAPL first:

```
[MM_AAPL_01]> QUOTE|SYM=AAPL|BID=149.95|ASK=150.05|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=AAPL-QC-001
```

Then pull it from the admin console:

```
[GW_ADMIN|ADMIN]> QCANCEL|GW=MM_AAPL_01|SYM=AAPL
```

Or with CLI:

```bash
pm-admin-cli --id ADMIN_CLI qcancel --gw MM_AAPL_01 --sym AAPL
```

The admin console answers `QCANCEL OK  MM_AAPL_01  AAPL`, and the market
maker sees its quote go (each line also carries a `[HH:MM:SS.mmm]` time):

```
CANCELLED <bid_id> reason=KILL_SWITCH
CANCELLED <ask_id> reason=KILL_SWITCH
QUOTE CANCELLED  AAPL-QC-001  ADMIN kill switch
```

`QLEGS|SYM=AAPL|SHOW=ALL` on the market maker shows both legs `CANCELLED`.
Re-send the `QUOTE` (with a new `QUOTE_ID`) before trying the CLI form.

When to use this instead of manual MM-side `QUOTE_CANCEL`: use `QCANCEL` when
the MM process is unresponsive or when operations needs immediate symbol-scoped
intervention without relying on the MM terminal.

:material-checkbox-blank-outline: **Checkpoint:** one-symbol MM quote is cancelled without mass-cancelling all gateway orders.

 

## Exercise 3: Run an Incident Micro-Runbook

Simulate a short incident response sequence:

1. Detect suspicious behavior on one gateway.
2. `KICK` the gateway.
3. `QCANCEL` one affected MM quote.
4. `CANCEL_SYM` for one stressed symbol.
5. Check the session is still `CONTINUOUS`.

Example CLI sequence:

```bash
pm-admin-cli --id ADMIN_CLI kick --gw TRADER02 --reason "Training incident"
pm-admin-cli --id ADMIN_CLI qcancel --gw MM_AAPL_01 --sym AAPL
pm-admin-cli --id ADMIN_CLI cancel-sym --sym AAPL
pm-admin-cli --id ADMIN_CLI book --sym AAPL
pm-admin-cli --id ADMIN_CLI session-status
```

Each prints one line (`KICK  sent disconnect for TRADER02`,
`QCANCEL OK  MM_AAPL_01  AAPL`, `CANCEL_SYM OK  AAPL  orders=<n>  quotes=<n>`),
then the empty AAPL book and the session state.

`TRADER02` is now disconnected: leave its console and start a new one before
the next chapter, which needs it.

:material-checkbox-blank-outline: **Checkpoint:** you can explain when to use each control and why they are not interchangeable.

 

## Summary

You can now operate advanced admin controls beyond halt/resume:

- `KICK` for participant disconnection.
- `QCANCEL` for targeted MM quote cancellation.
- `CANCEL_SYM` for symbol-wide book clearing, now from a script as well.

## Reflection

Why does `CANCEL_SYM` clear an entire symbol's book while `QCANCEL` targets
only quote-based orders? In an incident where a single market maker's bot is
malfunctioning, which of these tools (or `KICK`, or the Chapter 11 kill
switch) would you reach for first, and why is that the *least* disruptive
choice available?

## Further Reading

- [Controlling the Exchange](../operator-guide/part-3-run/020-admin-console-and-commands.md)
- [Processes, Environment and Ports](../reference-manual/part-1-command-line/010-processes-environment-and-ports.md)
- [Risk Controls](../operator-guide/part-4-run-a-market/040-risk-controls.md)

**Next:** [20 — Closing the Day](195-closing-the-day.md)