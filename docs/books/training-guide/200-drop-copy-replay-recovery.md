# Drop-Copy Replay & Recovery Patterns

## Objective

Learn how to operate drop-copy consumers safely when connectivity gaps occur,
how sequence numbers are used for loss detection, and what replay support does
and does not exist in the current EduMatcher runtime.

 


!!! abstract "Background reading"
    - [Drop Copy](../protocols-and-clients/part-3-session-behaviour/060-drop-copy.md)
    - [DC Gateway](../operator-guide/part-5-gateways/060-drop-copy-gateway.md)

## Prerequisites

- Chapters 01-20 completed, with the engine running (it always binds the
  drop-copy feed on `:5557`), the market open and `TRADER01` and `TRADER02`
  connected.
- Basic Python command-line familiarity. The scripts run with the container
  shell's `python` (see chapter 13, Exercise 3, for other installs).

 

## Background

Drop copy publishes per-participant fill events on:

- `drop_copy.event.<gateway_id>` (live stream)

Each message carries a `seq` field that increases contiguously within its
gateway's stream. Consumers use it to detect gaps and de-duplicate messages.
Each gateway has an independent counter, starting at 1; it resets when the
engine restarts. A consumer listening to multiple gateways must track the last
sequence separately for each `gateway_id`.

Important current limitation:

- Replay exists as an in-process publisher method
  (`DropCopyPublisher.replay(recipient_id, from_seq, gateway_id=...)`), backed
  by one circular in-memory buffer of the last 10,000 events across all
  gateways (roughly 16 minutes of history at a sustained ~10 fills/second).
- There is currently no external ZMQ replay-request handler for downstream
  clients to call directly — and even once one exists, replay is bounded by
  that 10,000-event buffer, not unlimited history.

The [Drop Copy](../protocols-and-clients/part-3-session-behaviour/060-drop-copy.md)
reference describes the replay method; `pm-dc-gwy` (chapter 13) has no
replay either. A downstream client cannot ask for "events N through M"
again. So operationally, reconnect handling is currently:

1. Detect gap by sequence numbers.
2. Recover from available audit/statistics artifacts.
3. Re-establish live stream and continue from new high-water mark.

 

## Exercise 1: Subscribe and Print Sequence Numbers

Run a minimal drop-copy subscriber:

```bash
python - <<'PY'
import json
import zmq

ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.connect("tcp://127.0.0.1:5557")
sock.subscribe(b"drop_copy.event.TRADER01")

print("listening on drop_copy.event.TRADER01")
for _ in range(10):
    topic, payload = sock.recv_multipart()
    msg = json.loads(payload)
    print(topic.decode(), "seq=", msg.get("seq"), "symbol=", msg.get("symbol"))
PY
```

While it runs, make `TRADER01` trade. Have `TRADER02` rest an offer, then
buy from it one share at a time — every fill is one drop-copy event for
`TRADER01`:

```
[GW_ADMIN|ADMIN]> CANCEL_SYM|SYM=AAPL
[TRADER02]> NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=DAY
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=1
```

Repeat the last line a few times. (`CANCEL_SYM` first, so the market maker's
bid does not take `TRADER02`'s offer. If AAPL has drifted far from 150 since
chapter 17, a 150.00 offer may be refused with `COLLAR_BREACH`; offer near
the last trade from `BOOK|SYM=AAPL` instead.)

:material-checkbox-blank-outline: **Checkpoint:** you can observe increasing `seq` values on live drop-copy events.

 

## Exercise 2: Detect a Synthetic Gap

A gap is a sequence number that is not the last one plus one. You cannot
provoke a real one on a quiet local machine, and restarting a subscriber does
not produce one either: a fresh subscriber has no last number to compare
with. So this subscriber throws away every fifth event it receives itself,
simulating lost messages:

```bash
python - <<'EOF'
import json
import zmq

last = None
seen = 0
ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.connect("tcp://127.0.0.1:5557")
sock.subscribe(b"drop_copy.event.TRADER01")

print("watching for gaps (deliberately dropping every 5th event)")
for _ in range(30):
    topic, payload = sock.recv_multipart()
    if topic != b"drop_copy.event.TRADER01":  # prefix match: skip TRADER010...
        continue
    seen += 1
    if seen % 5 == 0:          # simulate a lost message
        continue
    msg = json.loads(payload)
    seq = msg.get("seq")
    if last is not None and seq is not None and seq != last + 1:
        print(f"GAP detected: expected {last + 1}, got {seq}")
    last = seq
EOF
```

Send `TRADER01`'s one-share buys again (a dozen or so). You should see a line
such as `GAP detected: expected 8, got 9` for every fifth event. That is the
whole mechanism: the **consumer**, not the publisher, notices the
discontinuity — which is why every consumer you write needs this
check.

:material-checkbox-blank-outline: **Checkpoint:** you have seen at least one
`GAP detected` line, and can explain why a subscriber restart does not produce
one.

 

## Exercise 3: Recovery Workflow with Audit + Stats

Because there is no replay, a consumer that saw a gap has to rebuild what it
missed from the records other processes keep. When a gap is detected, run a
practical recovery checklist:

1. Use `pm-audit --terminal --audit-log-file ...` to keep an append-only event
   trail. Note the flag: `--audit-log-file` sets the *audit trail* path;
   `--log-file` is the process's own operational log and will not contain
   trade events.
2. Use `pm-stats-cli trades --symbol <sym>` for post-gap trade verification.
3. Reconnect subscriber and continue from latest observed sequence.

Example verification commands:

```bash
pm-stats-cli trades --symbol AAPL --limit 20
tail -40 "$EDUMATCHER_DATA_DIR/audit.log"
```

:material-checkbox-blank-outline: **Checkpoint:** you can recover operational confidence after a subscriber interruption even without external replay requests.

 

## Exercise 4: Design a Consumer Gap Policy

Write a short policy for your drop-copy consumer:

- Gap detection rule (strictly sequential or tolerance window).
- Duplicate handling rule (ignore already-processed sequence IDs).
- Recovery source order (audit log first, stats snapshot second, then live stream).
- Alerting threshold (for example, gap size > N triggers operator page).

:material-checkbox-blank-outline: **Checkpoint:** your policy defines deterministic behavior for normal, degraded, and recovery modes.

 

## Summary

You now understand practical drop-copy reliability operations in EduMatcher:

- How to detect stream loss using `seq`.
- Why external replay is currently limited.
- How to run a safe recovery pattern using available tooling.

## Reflection

Why does the drop-copy feed number every event with a monotonic `seq`
instead of relying on subscribers to just count messages received? What
silent failure mode would go undetected if `seq` didn't exist and a
subscriber's socket briefly dropped messages?

## Further Reading

- [Drop Copy](../protocols-and-clients/part-3-session-behaviour/060-drop-copy.md)
- [Messages](../protocols-and-clients/part-5-message-reference/010-message-reference.md)
- [Persistence](../operator-guide/part-6-observe-and-recover/010-persistence.md)

**Next:** [22 - Automation with CommandClient & MM Bot Tuning](210-automation-commandclient-mm-bot.md)