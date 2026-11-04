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
| G2 | **Revised.** Reload is rejected when startup config is not recorded. Audited runs must use a deployed artifact; replay flags YAML-started runs as `CONFIG_NOT_RECORDED` | Low | A2 |
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
| 2 | A2 | Require a recorded compiled config before accepting a reference reload | G2 | — | 0.25 d | ◐ | 2026-11-04 (uncommitted) |
| 3 | A3 | Gateway-local rejects: `system.gateway_reject` for auth, role and rate-limit refusals (D1 = record) | G3 | D1 | 1.5 d | ◐ | 2026-11-04 (uncommitted) |
| 4 | A4 | Promote the re-run to `pm-audit-replay rerun`; heartbeat timeouts become one chain and a reproducible input | G4 | A2 | 2.5 d | ◐ | 2026-11-04 (uncommitted) |
| 5 | A5 | Unenveloped command: count it and surface it | G5 | — | 0.5 d | ◐ | 2026-11-04 (uncommitted) |
| 6 | A6 | Recorder durability: fsync policy, gap-on-restart marker, documented loss window | G6 | A1 | 1.5 d | ◐ | 2026-11-04 (uncommitted) |
| 7 | A7 | Engine clock on ack and fill (decision D2) | G7 | D2 | 1 d | ◐ | 2026-11-04 (uncommitted) |
| 8 | A8 | `pm-audit-replay queue`: order and level views, observing the re-run (D3, Q1-Q4 decided) | G8 | A4 | 3 d | ◐ | 2026-11-04 (uncommitted) |
| 9 | A9 | Close out: tick §17, evidence/dispute chapter in the operator guide | G9 | A1–A6 | 1 d | ☐ | |

Order: A1, A2, A5 are independent and cheap; do A1 first. A4 re-runs only artifact runs; accepted reloads cannot change the config during an auditable run.

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

### A2 — Reject reloads when startup config is not recorded

**Decision.** Audited runs must start from a deployed compiled artifact. A
YAML-started engine has no compiled config in `system.startup`, so it must not
accept a reference reload that changes the active configuration without an
auditable record. Reject the reload and direct the operator to deploy the
artifact with `pm-config-deploy`.

**Tests.** A reload request on the YAML fallback path is rejected and leaves
the active config unchanged. A compiled-artifact startup continues to reject
reload because there is no reloadable YAML source. Replay reports
`CONFIG_NOT_RECORDED` for YAML-started runs.

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

### A8 — Queue view (design decided 2026-11-04)

**Decisions:** Q1 = observe the re-run (no trail-only model in 1.0); Q2 = operator tool with `--anonymise`; Q3 = **both** the order view and the level view are in A8 (about +1 day, so 3 d); Q4 = no cache. The text below is the design as proposed; where it calls the level view a follow-up, it is now in scope.

**The question it answers.** "My resting order did not fill. Where was it in the
queue, what traded ahead of it, and did the market ever reach its price?" Today
`story` shows the order's own events and `rerun` shows the engine agrees, but
nothing shows the *level*: the replay's state model deliberately keeps no book.

**Approach: observe the re-run, do not build a second book.** A4's `rerun`
already holds an engine whose book is exactly the live one after every command.
A8 adds an observer hook to `Rerun` (called after each input with the engine and
the ids bound live <-> re-run) and a `queue` module that, for one order, reads
the engine's own book after each input:

- its symbol, side, price, and **place in its level** (k of n, shares ahead,
  the orders ahead with gateway and arrival_seq), from `book.resting_orders()`
  sorted by the engine's own priority key;
- the event that changed it: a trade ahead (id, qty, which resting order), a
  cancel or expiry ahead, an amend that lost priority, an iceberg refill sent to
  the back, a stop that armed or fired;
- the market around it: best opposite price against its limit, the prices that
  traded, and any halt, session phase or SMP event in the window.

Using the engine means iceberg hidden size, stop triggers, trailing ratchets and
amend-priority rules are the engine's, not a replay re-implementation that could
disagree with it. The trail cross-check is free: the re-run is already compared
with the live output, and `engine.trace` `RESTED.priority_seq` is compared with
the re-run's position at the moment the order rested.

**Command.** `pm-audit-replay queue --order ID [--symbol S] [--format text|ndjson]`.
Text is a timeline, one line per change in position, ending in a verdict:
"filled in full at 10:41:07", "cancelled by its owner with 3 orders and 1 200
shares still ahead", or "still resting: its price was never reached (best
opposite 10.05, its limit 10.00)". Exit codes as `rerun`.

**What it cannot do.** It inherits `rerun`'s conditions: the trail begins at an
engine start, holds one run, carries its config; it reads the whole trail per
query. A mid-day window or a multi-run day is not answerable (see Q1).

**Tests.** A scripted book with a known queue (three orders at a level, a trade
that takes the first two, a cancel of one ahead, an amend that loses priority,
an iceberg refill) asserts the exact position at each step; the verdict wording
for filled, cancelled-with-queue-ahead and price-never-reached; and a planted
disagreement between `engine.trace` and the re-run is reported.

**Open questions (decide before building).**

- **Q1. Re-run only, or also a trail-only model from `book_checkpoint`?** The
  checkpoint holds the whole book in priority order at startup, each phase change
  and EOD, so a model seeded from it plus echoed commands and `engine.trace`
  could answer a mid-day window or a multi-run day without the engine. It would
  also be a second matching implementation (amend priority, iceberg refill, SMP,
  stops) that must be kept in step. Recommendation: re-run only for 1.0; seed
  the re-run from a checkpoint in 1.x to lift the "begins at engine start" limit.
- **Q2. Who may see it?** The view names the other gateways and quantities ahead
  of the order, and an iceberg's hidden size. That is right for an operator and
  wrong to hand a participant as it stands. Recommendation: operator tool only
  for 1.0, with `--anonymise` that replaces other gateways by stable labels
  (A, B, C) and hides iceberg reserve, so an excerpt can go in a dispute reply.
- **Q3. Order-centred only, or also a level timeline** (`queue --symbol S --price P`:
  the queue at one price over time)? The level view answers "what happened at
  10.00 between 10:30 and 10:45" without choosing an order. Recommendation: order
  view first; the level view reuses the observer hook and is a second small WP.
- **Q4. Cost.** One whole-trail pass per query (minutes on a full simulated
  day). Acceptable for a dispute tool; if not, cache the per-symbol position
  series in the episode index. Recommendation: no cache for 1.0.

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
