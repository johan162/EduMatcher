# Advanced Admin Operations

## Objective

Practice advanced exchange-operator controls that are documented but were not
covered in earlier training chapters: `KICK`, `QCANCEL`, `CANCEL_SYM`, and
manual session overrides via `SESSION|STATE=...`.

---

## Prerequisites

- Chapters 01-18 completed.
- `GW_ADMIN` configured with `role: ADMIN`.
- Engine and at least one trader and one MM gateway connected.

---

## Background

Earlier risk-control exercises focused on halt/resume and kill switch. In live
operations, admins also need targeted controls for:

- Disconnecting a specific participant (`KICK`).
- Cancelling one MM quote on one symbol without killing the whole gateway (`QCANCEL`).
- Clearing one symbol's resting book across all gateways (`CANCEL_SYM`).
- Forcing session state for controlled drills (`SESSION|STATE=...`).

These controls exist in both:

- Interactive admin console (`pm-admin` / ALF commands).
- One-shot scripting CLI (`pm-admin-cli`).

---

## Exercise 1: Disconnect a Gateway with KICK

From admin console:

```
[GW_ADMIN|ADMIN]> KICK|GW=TRADER02|REASON=Training_disconnect_check
```

Or with CLI:

```bash
pm-admin-cli --id GW_ADMIN kick --gw TRADER02 --reason "Training disconnect check"
```

Verification:

1. In the `TRADER02` terminal, confirm disconnect occurred.
2. Reconnect:

```bash
pm-gateway --id TRADER02
```

:material-checkbox-blank-outline: **Checkpoint:** gateway is disconnected and can reconnect cleanly.

---

## Exercise 2: Cancel One MM Quote with QCANCEL

First ensure an MM has an active quote on AAPL.

From admin console:

```
[GW_ADMIN|ADMIN]> QCANCEL|GW=MM_AAPL_01|SYM=AAPL
```

Or with CLI:

```bash
pm-admin-cli --id GW_ADMIN qcancel --gw MM_AAPL_01 --sym AAPL
```

Verify from MM gateway:

```
MM_AAPL_01> QLEGS|SYM=AAPL|SHOW=ALL
```

You should see the prior quote legs no longer active.

When to use this instead of manual MM-side `QUOTE_CANCEL`: use `QCANCEL` when
the MM process is unresponsive or when operations needs immediate symbol-scoped
intervention without relying on the MM terminal.

:material-checkbox-blank-outline: **Checkpoint:** one-symbol MM quote is cancelled without mass-cancelling all gateway orders.

---

## Exercise 3: Clear One Symbol Book with CANCEL_SYM

Create a few resting orders on TSLA from multiple gateways, then run:

From admin console:

```
[GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=TSLA
```

Or with CLI:

```bash
pm-admin-cli --id GW_ADMIN cancel-sym --sym TSLA
```

Verify:

```bash
pm-admin-cli --id GW_ADMIN book --sym TSLA
```

Confirm TSLA resting orders were cleared while other symbols remain unchanged.

:material-checkbox-blank-outline: **Checkpoint:** symbol-scoped cancel works across gateways.

---

## Exercise 4: Force Session State for Controlled Drills

Set session state explicitly:

From admin console:

```
[GW_ADMIN|ADMIN]> SESSION|STATE=CONTINUOUS
[GW_ADMIN|ADMIN]> SESSION|STATE=CLOSING_AUCTION
[GW_ADMIN|ADMIN]> SESSION|STATE=CLOSED
```

Or with CLI:

```bash
pm-admin-cli --id GW_ADMIN session --state CONTINUOUS
pm-admin-cli --id GW_ADMIN session --state CLOSING_AUCTION
pm-admin-cli --id GW_ADMIN session --state CLOSED
pm-admin-cli --id GW_ADMIN session-status
```

Use this to reproduce auction and close transitions deterministically in training.

:material-checkbox-blank-outline: **Checkpoint:** forced session transitions are visible and verifiable.

---

## Exercise 5: Run an Incident Micro-Runbook

Simulate a short incident response sequence:

1. Detect suspicious behavior on one gateway.
2. `KICK` the gateway.
3. `QCANCEL` one affected MM quote.
4. `CANCEL_SYM` for one stressed symbol.
5. `SESSION|STATE=CONTINUOUS` to restore normal operation if needed.

Example CLI sequence:

```bash
pm-admin-cli --id GW_ADMIN kick --gw TRADER02 --reason "Training incident"
pm-admin-cli --id GW_ADMIN qcancel --gw MM_AAPL_01 --sym AAPL
pm-admin-cli --id GW_ADMIN cancel-sym --sym AAPL
pm-admin-cli --id GW_ADMIN session-status
```

:material-checkbox-blank-outline: **Checkpoint:** you can explain when to use each control and why they are not interchangeable.

---

## Summary

You can now operate advanced admin controls beyond halt/resume:

- `KICK` for participant disconnection.
- `QCANCEL` for targeted MM quote cancellation.
- `CANCEL_SYM` for symbol-wide book clearing.
- `SESSION|STATE=...` for deterministic phase management.

## Reflection

Why does `CANCEL_SYM` clear an entire symbol's book while `QCANCEL` targets
only quote-based orders? In an incident where a single market maker's bot is
malfunctioning, which of these tools (or `KICK`, or the Chapter 11 kill
switch) would you reach for first, and why is that the *least* disruptive
choice available?

## Further Reading

- [Controlling the Exchange](../user-guide/02-commands.md)
- [Processes](../user-guide/10-processes.md)
- [Risk Controls](../user-guide/12-risk-controls.md)

**Next:** [20 - Drop-Copy Replay & Recovery Patterns](20-drop-copy-replay-recovery.md)