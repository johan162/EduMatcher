# EduMatcher — Audit Trail Completeness for 1.0: Review and Workplan

Question put before 1.0.0: is the audit trail complete enough to recreate every
trade and reject, to meet the traceability and evidence expectations placed on
an exchange, and to answer a dispute about a trade that happened or one that
did not? Is `pm-audit-replay` complete enough?

Method: read-only review of `audit/writer.py`, `audit/main.py`, `audit/archive.py`,
`engine/main.py` (`_echo_command`, `_expire_silent_gateways`), `spec/messages/`
(order, trade, system, book), `docs-design/EduMatcher-Audit-Replay.md` and
`tools/sim_forensics/checks/rerun.py`. Nothing was executed. Each finding below
must be re-validated against source by its WP's first step (test-first).

One WP at a time. Every WP ends with new tests green, `make _check` plus the
full suite green, a holistic review, and a proposed commit message. The
maintainer commits.

Started: 2026-11-04

---

## 1. Verdict

The matching record is strong; the evidential record is not yet.

**Already in place (no work):**

- Every inbound command is echoed into the trail *before* handling
  (`Engine._echo_command`), so commands that had no effect are still recorded
  and the record survives a crash mid-handler.
- Rejects carry a stable `reject_code` (about 40 members) and a causation id
  to the command that provoked them.
- Completeness is provable: `eseq` (socket-wide) and per-topic `seq` are
  recorded on every line; replay reports `SEQ_GAP`, `ESEQ_GAP`,
  `TRADE_COUNTER_GAP`.
- Runs are self-describing: `system.startup` carries the compiled config,
  `config_sha256`, engine version, git commit and state-file hashes;
  `system.book_checkpoint` carries the full priority-ordered book at startup,
  each phase change and EOD; `engine.trace` carries queue position, iceberg
  refills and trailing ratchets.
- `pm-audit-replay` checks lifecycle, quantity/price conservation, trade-leg
  agreement, liquidity flags, drop-copy agreement and causality; the
  sim-forensics `rerun` check re-executes the echoed commands through a fresh
  engine and compares output message for message.

**Gaps** (G1 is the only one that is strictly an evidence requirement):

| # | Gap | Severity | WP |
|---|-----|----------|----|
| G1 | No tamper evidence: no hash chain, signature or anchored digest; archive SHA-256 is internal only; `--keep-days` deletes; docs call the trail "immutable" | High | A1 |
| G2 | **Revised.** Reload is accepted only when the engine runs from YAML (no deployed artifact); then `system.startup` carries no config at all. With an artifact the config is fully recorded and reload is rejected | Low | A2 |
| G3 | Gateway-local rejects (rate limit, auth, malformed, role) never reach the bus, so the exchange can neither show nor disprove "I sent it" | Med | A3 |
| G4 | Re-execution lives in `tools/sim_forensics`, not in the shipped replay; its E1 lists inputs the trail does not hold (silent-gateway expiry, wall-clock timers other than the breaker's) | Med | A4 |
| G5 | A command without an envelope frame is not echoed; nothing alerts | Low | A5 |
| G6 | Recording can lose data silently: `pm-audit` down, SUB high-water mark, up to `--flush-interval` of buffered lines on hard kill, fsync only at roll | Med | A6 |
| G7 | Ack and fill carry no engine timestamp; the audit stamp is `pm-audit` receipt time | Low | A7 |
| G8 | "Why did my resting order not fill" has no queue view: replay deliberately keeps no book; queue-position proxy not built | Low | A8 |
| G9 | Audit-Replay §17 acceptance checklist entirely unticked | Low | A9 |

## 2. Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Gap | Depends on | Est. | Status | Done on |
|---|----|---------|-----|------------|------|--------|---------|
| 1 | A1 | Daily evidence manifest: hash chain across days, `pm-audit-cli verify` | G1 | — | 2 d | ◐ | 2026-11-04 (code + docs done, uncommitted) |
| 2 | A2 | Decision: option 3. Audited runs must use a deployed artifact; replay flags `CONFIG_NOT_RECORDED` | G2 | — | 0.25 d | ◐ | 2026-11-04 (uncommitted) |
| 3 | A3 | Gateway-local rejects: record to the trail, or document as out of scope (decision D1) | G3 | D1 | 1.5 d / 0.25 d | ☐ | |
| 4 | A4 | Promote the re-run to a supported verification command; close or document the hidden inputs | G4 | A2 | 2.5 d | ☐ | |
| 5 | A5 | Unenveloped command: count it and surface it | G5 | — | 0.5 d | ◐ | 2026-11-04 (uncommitted) |
| 6 | A6 | Recorder durability: fsync policy, gap-on-restart marker, documented loss window | G6 | A1 | 1.5 d | ☐ | |
| 7 | A7 | Engine clock on ack and fill (decision D2) | G7 | D2 | 1 d | ☐ | |
| 8 | A8 | `story --queue`: book/queue view from checkpoint plus echoed commands (decision D3) | G8 | A4 | 2 d | ☐ | |
| 9 | A9 | Close out: tick §17, evidence/dispute chapter in the operator guide | G9 | A1–A6 | 1 d | ☐ | |

Order: A1, A2, A5 are independent and cheap; do A1 first. A4 re-runs only artifact runs (reload is rejected on those, so the config never changes mid-run).

## 3. Decisions (answered 2026-11-04)

**Resolved:** D1 = record the disputable classes (auth, role, rate limit); D2 = add `ts_ns` to ack and fill; D3 = build the queue view for 1.0 (A8 is in scope). Start with A1. Original options and recommendations kept below.

- **D1 (A3).** Record gateway-local rejects (new `gateway.reject` message
  published by the gateway to the engine PUSH, echoed like a command) or
  declare them out of the exchange's evidential scope? Recording costs a new
  spec message and a gateway→engine hop on the reject path; declaring costs
  nothing but leaves "I sent it" undecidable for those cases. Recommendation:
  record the *auth, role and rate-limit* classes (disputable), leave malformed
  frames to a counter.
- **D2 (A7).** Add `ts_ns` to `order.ack` and `order.fill`, or state that
  sequence (`eseq`) is the ordering authority and wall time is advisory?
  Recommendation: add it; the engine already reads its clock per batch, so it
  is nearly free, and it removes the receipt-clock caveat from any legal claim.
- **D3 (A8).** Is a queue view in scope for 1.0, or documented as "reconstruct
  with the re-run"? Recommendation: document for 1.0, build in 1.x.

## 4. Work packages

Every WP starts with a test that fails on today's code (or, for pure
documentation WPs, a doc-lint that fails).

### A1 — Daily evidence manifest

**Problem.** Nothing proves a day's trail is as it was at close.
`archive._digest` hashes only to verify its own compression.

**Change.** When a day is closed (`AuditFile` on-day-closed hook, then the
archiver), append to one append-only `audit/manifest.jsonl` (implemented; supersedes the
per-day-file idea so a reopened day appends instead of rewriting): day, line count,
byte count, SHA-256 of the content, `prev` (hash of the previous line), writer version. Each manifest is the hash
of the one before: editing any day breaks every later manifest. Add
`pm-audit-cli verify [--date D | --all]` recomputing from parts or `.zst` and
checking the chain. `--keep-days` removes archives only after writing a
tombstone line into the chain (the day's hash stays; the content goes).
Replace "immutable" in docs with what is actually guaranteed (tamper-*evident*,
and only against someone who cannot also rewrite every later manifest, so
document anchoring the latest hash off-host as the operator's step).

**Tests.** Edit one byte in an archived day → `verify` fails and names the day;
delete a middle manifest → chain break reported; retention leaves chain
verifiable; crash between close and manifest write → next start regenerates
(manifest writing is idempotent).

**Done when** `verify` passes on a fresh multi-day fixture and fails on each
tamper case above.

### A2 — Reload records the effective config

**Change.** On an accepted `system.reference_reload`, the engine publishes the
new compiled config the same way `system.startup` does (new
`system.config_applied` message: `config_sha256`, `config`, `command_id`,
`run_seq`). Replay and the re-run apply it at that point in the stream.

**Tests.** Reload changing a tick size and a collar → trail holds both
contents; `rerun` after the reload matches the live engine. Rejected reload
publishes nothing new.

### A3 — Gateway-local rejects

Depends on D1. If "record": new spec message, published by the ALF, BALF and
REST gateways on auth/role/rate-limit refusal, carrying `gateway_id`,
`reject_code`, `reason`, a client-supplied tag if any, and the gateway's own
clock; engine echoes it as it does commands; replay renders it as a standalone
episode. If "out of scope": operator-guide paragraph stating which rejects the
trail cannot show and why, plus a gateway reject counter in the health beacon.

### A4 — Promote the re-run

**Change.** Move the engine re-run out of `tools/sim_forensics` into
`pm-audit-replay verify --rerun` (read-only, builds a fresh engine from the
`system.startup` config plus any `system.config_applied`, feeds echoed
commands, compares output). Report differences as findings with the engine
version of the run and of the re-run.

**Hidden inputs.** Enumerate every engine action not caused by an echoed
command (silent-gateway expiry, TIF expiry on a schedule, any timer other than
the breaker's). For each, either echo it as an input (a `system.timer` record
before its effects, as `BREAKER_TIMER` does today) or document it as a
known non-reproducible input. Prefer echoing: the cost is one message per
timer firing.

**Tests.** Existing `rerun` tests move with the code; add a fixture with a
silent-gateway expiry and a TIF expiry that re-run reproduces.

### A5 — Unenveloped commands

**Change.** In `_echo_command`, when a command arrives with fewer than three
frames, increment a health counter and log once per gateway at WARNING.
Replay's `ENVELOPE_MISSING` already exists for the output side; add the input
side to the operator dashboard. No change to the echo itself.

### A6 — Recorder durability

**Change.** (a) fsync policy: fsync on each flush when `--fsync` is set
(default on for a day's active file; measure cost). (b) On start, `pm-audit`
writes a `# recorder-start` marker line so a stop-and-restart gap is visible in
the trail itself, not only in `eseq`. (c) Document the loss window and the SUB
high-water mark; expose a drop estimate (eseq gap since last line) as a health
metric.

**Tests.** Kill -9 after flush leaves a readable file and no torn line is
parsed as a record; restart writes the marker; gap metric rises on a forced
drop.

### A7 — Engine clock on ack and fill

Depends on D2. Add `ts_ns` (epoch nanos, the engine's clock read for the batch)
to `order.ack` and `order.fill` in the spec, regenerate, and have replay show
it at `-vv` as it does for trades. Existing logs stay readable (field absent).
No backwards-compat code beyond the optional field.

### A8 — Queue view

Depends on D3 and A4. `story --queue --order ID`: from the latest
`book_checkpoint` plus `engine.trace` and echoed commands, show the order's
place in its level over time and what traded ahead of it. Out of scope if D3 =
document.

### A9 — Close-out

Tick the Audit-Replay §17 checklist item by item (or record why not); add an
operator-guide chapter "Answering a dispute": which question is answered by
which command (`story`, `anomalies`, `verify`, `verify --rerun`), what the
trail cannot show (G3 if out of scope, hidden inputs), and the off-host
anchoring step from A1.

## 5. Verification (whole plan)

- `pm-audit-cli verify --all` clean on a verification run; fails on tamper.
- `tools/verify_audit_trail.sh` still clean (anomalies at warn).
- `verify --rerun` shows E2 PASS on a multi-session sim run including a
  reload, an expiry and a breaker.
- Full suite, black, flake8, mypy, pyright per the project workflow.
