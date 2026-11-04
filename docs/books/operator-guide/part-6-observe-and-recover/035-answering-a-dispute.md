# Answering a Dispute

!!! note "Learning objectives"
    After reading this page you will be able to:

    - Say which command answers which dispute: "you never got my order", "why was
      I rejected", "why did I not trade", "why that price", "was the record changed"
    - Show that the trail you are quoting is complete, unaltered, and agrees with
      what the engine does
    - Anchor the trail's evidence outside the host that wrote it
    - State plainly what the trail cannot show

The audit trail is written to be read by someone who was not there. This chapter
is the order to read it in when a participant, a clearing counterparty or a
reviewer asks the exchange to prove what happened. The tools are described in
[Audit Trail](020-audit-trail.md) and [Audit Replay](030-audit-replay.md); this
page says which one to reach for.

## Which command answers which question

| The question | Reach for | What it shows |
|---|---|---|
| "I sent an order and you ignored it" | `pm-audit-replay story --order ID`, then `stream --gateway GW` around the time | The order as received (the engine echoes every command before acting on it), its acknowledgement with the engine's clock (`ts_ns`), or the reject and its reason. If the gateway itself refused the request (login, role, rate limit) it is a `system.gateway_reject` record with the peer address |
| "Why was I rejected?" | `story --order ID -v --explain` | The `reject_code`, and the market state behind it: the halt, session phase, collar or limit, each tied to the message that set it |
| "Why did my order not trade?" | `pm-audit-replay queue --order ID` | Where it stood in its level after every change, what traded or was cancelled ahead of it, and whether the market ever reached its price (best opposite price against its limit) |
| "What happened at that price?" | `queue --symbol SYM --price P` | Who rested, traded and left at one level, with what it held after each change |
| "Why did I get that fill and that price?" | `story --order ID`, `story --trade ID` | Both sides of each trade, aggressor and resting side, maker or taker, the VWAP of a sweep and the trade ids behind it |
| "Is the trail complete?" | `pm-audit-replay anomalies --severity warn`, `pm-audit-replay stats` | `SEQ_GAP` and `ESEQ_GAP` prove a missing message; `RECORDER_RESTART` says the recorder was down; low envelope coverage says a publisher bypassed the causal wrapper |
| "Has the record been altered?" | `pm-audit-cli verify` | Every archived day against the hash chain in `manifest.jsonl`; it names the day that differs |
| "Does the engine agree with the record?" | `pm-audit-replay rerun` | A fresh engine fed the trail's commands publishes what the live engine did, message for message |
| "What was the exchange running?" | `story` on the `system.startup` episode | Engine version, source commit, the full compiled configuration and its SHA-256, the state files it started from |

## The procedure

Do these in order and keep the output; each step makes the next one worth quoting.

1. **Prove the record is unaltered.** `pm-audit-cli verify` must exit `0`. Compare
   the *head hash* it prints with the one you anchored off-host (see
   [below](#anchoring-the-head-hash)). A match means no archived day, and no
   manifest entry before the anchor, has changed since it was anchored.
2. **Prove it is complete.** `pm-audit-replay anomalies --severity warn` over the
   day. A clean result means every per-topic and engine-wide sequence runs without
   a hole, every fill has its trade, and the quantities conserve. Any `SEQ_GAP`,
   `ESEQ_GAP` or `RECORDER_RESTART` in the window you are about to quote must be
   explained first.
3. **Show the engine agrees.** `pm-audit-replay rerun` over the trail. Zero hidden
   inputs and zero differing episodes mean the trail is not only self-consistent but
   is what the matching engine does with those commands. Run it with the engine
   version the day ran on (the output names both versions).
4. **Answer the question** with `story`, `queue` or `stream` from the table above.
5. **Quote with `--anonymise`** when the answer goes to a participant, so other
   gateways appear as `gateway A`, `gateway B` and iceberg reserve is left out. The
   inspected order's own gateway keeps its name.

Every sentence the narrator prints traces to a field in a recorded line, and
`--show-source` prints the file and line number so a reader can go and look.

## Anchoring the head hash

`pm-audit-cli verify` ends with the hash of the newest manifest entry. Each entry
contains the hash of the one before it, so that single value commits to every
archived day to date. Anyone who can rewrite the files on the recorder host can
rewrite the whole chain, so the evidence is only as good as the place that value
is kept.

After each day closes (the archive is made shortly after midnight in the session
timezone), copy the head hash somewhere the recorder host cannot write:

```bash
pm-audit-cli verify | tail -1      # OK: 12 day(s) in the manifest, 0 problem(s); head 3f9a…
```

Send it by mail to a mailbox the operator does not control, commit it to a
separate repository, or write it to an append-only system. Keep the date with it.
When a day is disputed, run `verify` and compare. A chain that verifies but whose
head differs from the anchored one has been cut back or rewritten after the anchor.

Retention (`--keep-days`) removes old archives but leaves a `retired` line in the
manifest with the day's last hash, so the chain still verifies and the day's
digest is still on record; the content is not.

## What the trail cannot show

Say these before someone else does.

- **Messages the recorder did not receive.** While `pm-audit` is stopped nothing
  is recorded. The gap is proven by `ESEQ_GAP` and the restart by `RECORDER_RESTART`,
  but the content is not recoverable. Past a 200 000-message receive backlog the
  subscriber drops; `audit.missed_messages` counts what it can prove it missed. See
  [What can be lost](020-audit-trail.md#what-can-be-lost).
- **A hard stop of the recorder or the host.** Up to one write buffer
  (`--buffer-size` messages or `--flush-interval` seconds) is lost to `kill -9`;
  up to `--fsync-interval` seconds more to a power loss.
- **Refusals the gateways do not report.** Login, role and rate-limit refusals are
  recorded. Malformed frames, field-validation refusals and a read-only REST key
  attempting a write are counted by the gateway and are not in the trail. A burst
  of repeated refusals is one record per second per peer with a `count`; the count
  of the final burst is lost if the peer then goes quiet.
- **Commands that bypassed the envelope.** A client that does not use the project's
  client library cannot be echoed. `engine.diagnostics{component="UNRECORDED_COMMAND"}`
  counts them; a non-zero value means the trail is not a complete record of what the
  exchange was asked to do.
- **Inputs other than commands and two timers.** The re-run reproduces the circuit
  breaker's reopen and the disconnect of a gateway that stopped sending heartbeats.
  Anything else the engine did with no command behind it appears as a *hidden input*
  and cannot be reproduced.
- **A trail that cannot be re-run.** `rerun` and `queue` start from the trail's
  first line, which must be an engine start that began with an empty book, and every
  run must carry its compiled configuration. Restarts in between are re-run. Once
  retention has removed the day the data directory began empty, the trail can still
  be read with `story` and `stream`, but not re-executed. An engine that ran from a
  YAML file rather than a deployed artifact has no configuration in its trail
  (`CONFIG_NOT_RECORDED`). A trail with a proven hole (`ESEQ_GAP`, or a recorder
  restart while the engine ran) is not re-run either: its verdict would blame the
  engine for what the recorder missed.
- **Time.** Every line carries the recorder's receipt time. Engine clock readings
  (`ts_ns`) are on trades, fills, acknowledgements and book snapshots, and ordering
  between messages is by the engine's own sequence, not by either clock. A client's
  own timestamp on an order is the client's, and the engine does not use it.
- **Tamper-proof storage.** The manifest makes an edit evident; it does not prevent
  one. Without an anchored head hash the chain proves only internal consistency.

## See Also

- [Audit Trail](020-audit-trail.md): the file format, day parts and archives, the
  evidence manifest, what can be lost
- [Audit Replay](030-audit-replay.md): every subcommand, the anomaly codes,
  re-executing the trail, the queue view
