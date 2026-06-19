# 21 - Automation with CommandClient & MM Bot Tuning

## Objective

Use EduMatcher's programmatic command client for repeatable admin workflows and
practice advanced `pm-mm-bot` runtime tuning for startup and reconciliation.

---

## Prerequisites

- Chapters 01-20 completed.
- Engine running with `GW_ADMIN` and at least one MM gateway configured.
- Python environment able to import `edumatcher.commands`.

---

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

---

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

:material-checkbox-blank-outline: **Checkpoint:** you can connect, read symbols, and read session status programmatically.

---

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

This is easier to run consistently than a manual multi-step console sequence.

:material-checkbox-blank-outline: **Checkpoint:** you can automate halt/cancel/verify/resume for one symbol.

---

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

---

## Exercise 4: Tune pm-mm-bot Startup Reliability

Run one bot with explicit startup controls:

```bash
pm-mm-bot \
  --symbol AAPL \
  --gap 0.10 \
  --qty 500 \
  --startup-session-timeout-sec 5.0 \
  --bootstrap-timeout-sec 1.0 \
  --qlegs-reconcile-interval-sec 15.0 \
  -v
```

Observe startup logs for:

- QBOOT bootstrap resolution.
- QLEGS reconciliation status.
- Session readiness before first quote.

Representative startup sequence:

```
[INFO] QBOOT reply: active_quote=None bootstrap_prices={...}
[INFO] QLEGS reconcile: symbol=AAPL state=clean
[INFO] Session state CONTINUOUS; issuing initial quote
```

:material-checkbox-blank-outline: **Checkpoint:** you can identify and tune the timeout knobs that control startup behavior.

---

## Exercise 5: Empty-Book Bootstrap Drill

Simulate sparse startup conditions and run bot with explicit bootstrap range:

```bash
pm-mm-bot --symbol AAPL --initial_min 95.00 --initial_max 105.00 -v
```

Then compare behavior with and without range configured.

Expected understanding:

- With range: bot can start quoting on fresh books.
- Without any bootstrap source: bot fails fast with clear reason.

:material-checkbox-blank-outline: **Checkpoint:** you can choose a bootstrap strategy appropriate for your environment.

---

## Exercise 6: Build a Combined Automation Flow

Design a short automation script that:

1. Checks session status.
2. Halts one symbol if needed.
3. Clears that symbol's resting orders.
4. Resumes symbol.
5. Verifies top-of-book depth.

Use `ExchangeCommandClient` methods only (no manual prompt commands).

:material-checkbox-blank-outline: **Checkpoint:** your script is deterministic, idempotent, and easy to rerun during drills.

---

## Summary

You now have advanced operational coverage for:

- Programmatic admin orchestration with `ExchangeCommandClient`.
- Repeatable incident-response style command sequencing.
- Practical `pm-mm-bot` tuning for startup/bootstrap/reconciliation behavior.

## Further Reading

- [Controlling the Exchange](../user-guide/02-commands.md)
- [Market-Maker Bot (pm-mm-bot)](../user-guide/17-mm-bot.md)
- [Market-Maker Bot CLI Reference](../user-guide/17-mm-bot.md#cli-reference)
- [Processes](../user-guide/10-processes.md)

You have completed the full training curriculum, including advanced operations.