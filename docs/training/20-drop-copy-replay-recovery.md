# 20 - Drop-Copy Replay & Recovery Patterns

## Objective

Learn how to operate drop-copy consumers safely when connectivity gaps occur,
how sequence numbers are used for loss detection, and what replay support does
and does not exist in the current EduMatcher runtime.

---

## Prerequisites

- Chapters 01-19 completed.
- Engine running with drop-copy PUB enabled on `:5557`.
- Basic Python command-line familiarity.

---

## Background

Drop copy publishes per-participant fill events on:

- `drop_copy.event.<gateway_id>` (live stream)

Each message carries a monotonically increasing `seq` field. Consumers use this
to detect gaps and de-duplicate messages.

Important current limitation:

- Replay exists as an in-process publisher method.
- There is currently no external ZMQ replay-request handler for downstream
  clients to call directly.

So operationally, reconnect handling is currently:

1. Detect gap by sequence numbers.
2. Recover from available audit/statistics artifacts.
3. Re-establish live stream and continue from new high-water mark.

---

## Exercise 1: Subscribe and Print Sequence Numbers

Run a minimal drop-copy subscriber:

```bash
python - <<'PY'
import json
import zmq

ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.connect("tcp://127.0.0.1:5557")
sock.subscribe(b"drop_copy.event.")

print("listening on drop_copy.event.*")
for _ in range(10):
    topic, payload = sock.recv_multipart()
    msg = json.loads(payload)
    print(topic.decode(), "seq=", msg.get("seq"), "symbol=", msg.get("symbol"))
PY
```

Generate a few trades from gateways while this runs.

:material-checkbox-blank-outline: **Checkpoint:** you can observe increasing `seq` values on live drop-copy events.

---

## Exercise 2: Detect a Synthetic Gap

Use a subscriber with simple gap detection:

```bash
python - <<'PY'
import json
import zmq

last = None
ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.connect("tcp://127.0.0.1:5557")
sock.subscribe(b"drop_copy.event.")

print("watching for sequence gaps")
for _ in range(30):
    topic, payload = sock.recv_multipart()
    msg = json.loads(payload)
    seq = msg.get("seq")
    if last is not None and seq is not None and seq != last + 1:
        print(f"GAP detected: expected {last + 1}, got {seq}")
    last = seq
PY
```

Interrupt/restart the subscriber while trades are flowing to simulate missed events.

:material-checkbox-blank-outline: **Checkpoint:** you can explain how consumer-side gap detection works.

---

## Exercise 3: Validate Current Replay Constraint

Confirm current behavior from docs:

1. Review replay section in [Drop Copy](../user-guide/13-drop-copy.md).
2. Note that replay is in-process and there is no external replay-request
   handler wired into the engine loop.

Operational implication:

- Downstream clients cannot request historical replay over ZMQ yet.

:material-checkbox-blank-outline: **Checkpoint:** you can state the exact replay limitation and its impact on downstream consumers.

---

## Exercise 4: Recovery Workflow with Audit + Stats

When a gap is detected, run a practical recovery checklist:

1. Use `pm-audit --terminal --log-file ...` to keep an append-only event trail.
2. Use `pm-stats-cli trades --symbol <sym>` for post-gap trade verification.
3. Reconnect subscriber and continue from latest observed sequence.

Example verification commands:

```bash
pm-stats-cli trades --symbol AAPL --limit 20
tail -40 "$EDUMATCHER_DATA_DIR/audit.log"
```

:material-checkbox-blank-outline: **Checkpoint:** you can recover operational confidence after a subscriber interruption even without external replay requests.

---

## Exercise 5: Design a Consumer Gap Policy

Write a short policy for your drop-copy consumer:

- Gap detection rule (strictly sequential or tolerance window).
- Duplicate handling rule (ignore already-processed sequence IDs).
- Recovery source order (audit log first, stats snapshot second, then live stream).
- Alerting threshold (for example, gap size > N triggers operator page).

:material-checkbox-blank-outline: **Checkpoint:** your policy defines deterministic behavior for normal, degraded, and recovery modes.

---

## Summary

You now understand practical drop-copy reliability operations in EduMatcher:

- How to detect stream loss using `seq`.
- Why external replay is currently limited.
- How to run a safe recovery pattern using available tooling.

## Further Reading

- [Drop Copy](../user-guide/13-drop-copy.md)
- [Messages](../user-guide/09-messages.md)
- [Persistence](../user-guide/11-persistence.md)

**Next:** [21 - Automation with CommandClient & MM Bot Tuning](21-automation-commandclient-mm-bot.md)