# EduMatcher — Training Guide Review: Workplan

Addresses the open questions and unverified cases in
[`reviews/EduMatcher-Trainging-Review.md`](./reviews/EduMatcher-Trainging-Review.md).
The review covers the Training Guide, chapters 00–29, and reports two product
fixes and documentation corrections already made. This plan takes those
reported completions as context; it does not independently re-validate them.

The review records **21 open questions (Q1–Q21)** and several unverified
installation routes and exercises. Some questions are design choices rather
than established defects. Resolve the intended contract before choosing a
product change or documenting an exception.

**Test-first is mandatory for behavior changes.** Where a question concerns
reproducible behavior, first add a test or controlled reproduction that
captures the exact setup and fails against the current behavior. Only then
change production code. If the agreed behavior matches current behavior, keep
the behavior, add a contract test where practical, and correct the guide or
protocol documentation.

Started: 2026-11-06

---

## 1. Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Findings | Depends on | Status | Done on |
|---|----|---------|----------|------------|--------|---------|
| 1 | T1 | Audit startup delivery and completeness | Q1 | — | ☑ | 2026-11-06 |
| 2 | T2 | Orphaned quote remainders on disconnect and kill | Q2, Q20 | — | ☑ | 2026-11-06 |
| 3 | T3 | Combo self-match prevention contract | Q3 | Contract decision | ☑ | 2026-11-06 |
| 4 | T4 | Console logout after engine connection loss | Q4 | — | ☑ | 2026-11-07 |
| 5 | T5 | Admin console identities and safe reset guidance | Q5, Q6 | — | ☑ | 2026-11-07 |
| 6 | T6 | Clearing totals and gateway quote-status scope | Q7, Q8 | — | ☑ | 2026-11-07 |
| 7 | T7 | Installed examples, C exercises and version metadata | Q9, Q10, Q21 | — | ☐ | |
| 8 | T8 | Normal-use warnings and artifact errors | Q11 | Contract decision | ☑ | 2026-11-08 |
| 9 | T9 | Swarm budget semantics | Q12 | Contract decision | ☐ | |
| 10 | T10 | Teaching configuration, persisted orders and collars | Q13 | Contract decision | ☐ | |
| 11 | T11 | Session-transition rejection replies | Q14 | — | ☐ | |
| 12 | T12 | Index history, listing and restored session phase | Q15, Q16 | Contract decision for Q15 | ☐ | |
| 13 | T13 | ATO expiry reason | Q17 | — | ☐ | |
| 14 | T14 | Generated API-key usability and safety | Q18 | Contract decision | ☐ | |
| 15 | T15 | Per-recipient drop-copy sequence | Q19 | Contract decision | ☐ | |
| 16 | T16 | Close training-route and exercise verification gaps | §§3–4 | T7 for installed routes | ☐ | |

### 1.1 Question → WP index

| Question | WP | Question | WP | Question | WP |
|---|---|---|---|---|---|
| Q1 | T1 | Q8 | T6 | Q15 | T12 |
| Q2 | T2 | Q9 | T7 | Q16 | T12 |
| Q3 | T3 | Q10 | T7 | Q17 | T13 |
| Q4 | T4 | Q11 | T8 | Q18 | T14 |
| Q5 | T5 | Q12 | T9 | Q19 | T15 |
| Q6 | T5 | Q13 | T10 | Q20 | T2 |
| Q7 | T6 | Q14 | T11 | Q21 | T7 |

---

## 2. Execution rules

1. **Record each decision before implementation.** For Q3, Q5, Q7, Q8, Q11,
   Q12, Q13, Q15, Q18, Q19 and Q21, write down the accepted user-visible or
   protocol contract in the relevant specification, design note or WP notes.
   Do not silently turn a suggested direction into a requirement.
2. **Reproduce first.** A code WP starts with a deterministic test using the
   actual component boundary implicated by the review (for example a gateway
   request, persisted state, or per-recipient topic), not a test of a private
   helper alone. Capture the old behavior in the test name/assertions.
3. **Separate code and guide outcomes.** A product behavior change is not
   complete until its corresponding instructions, expected output and
   troubleshooting guidance are correct. Conversely, if behavior is intended,
   document the supported behavior and provide a runnable check.
4. **Do not test against the developer's running exchange.** Use isolated
   temporary data directories and network/process namespaces where needed.
   Never use a broad `pm-opctl-cli clear` or `stop` against shared processes.
5. **Evidence and completion.** Keep the exact command, scenario inputs,
   observed result and expected result alongside each new test or verification
   record. Do not mark a package done based only on a guide edit or a passing
   happy-path run.

The review reports that the first two product fixes and chapter 00–29
documentation corrections were already made. Preserve them while completing
these packages; if a regression is found, add it to the relevant WP rather
than duplicating the prior fix.

---

## 3. Work packages

### T1 — Audit startup delivery and completeness (Q1)

**Question to resolve:** Is the missing first event caused by slow subscription
startup, a first-message flush-timer race, or the review harness? Establish
which layer drops or delays the event before changing the audit implementation.

Steps:
1. Add a failing deterministic integration test that starts `pm-audit`, waits
   for an explicit readiness condition, then publishes uniquely identified
   audit events at fixed offsets (including one immediately after readiness
   and one after the first flush interval).
2. Assert that every published event appears exactly once in both the
   configured durable audit output and the expected terminal/output channel,
   with a bounded maximum delivery delay. On failure, record whether the raw
   SUB socket received the event, whether it entered `_add_to_buffer`, and
   whether `_flush_locked` wrote it.
3. Repeat with the monitor used in the review: one event every three seconds
   over 36 seconds. Keep startup/readiness and first-publication timing
   controlled so the run distinguishes a slow-joiner from a timer defect.
4. Fix the earliest failing layer; do not mask loss by changing only the guide
   to recommend waiting.
5. Update audit startup/readiness instructions only after the supported
   behavior is established.

**Definition of done:**
- The new regression test fails on the pre-fix behavior and passes after the
  fix, or proves the product delivers correctly once a documented readiness
  condition is met.
- All known published event IDs are accounted for exactly once in durable
  output; a restart/reopen check confirms buffered events are not lost.
- The guide accurately explains startup readiness and flush latency.
- Targeted audit tests and the full project test/type/lint checks pass.

**Result (2026-11-06):** The missing first event is explained by ZeroMQ's
PUB/SUB slow-joiner window, not by the audit buffer timer or file writer.
`test_publication_before_audit_subscription_is_not_replayed` confirms that a
publication made before `pm-audit` subscribes is not replayed; after XPUB
confirms the audit subscription, `test_events_after_subscription_are_recorded_once_within_flush_interval`
publishes 13 unique events from offset 0 through 36 seconds at 3-second
intervals. A raw SUB observer receives each event, while the audit records it
exactly once in the file and terminal within the 10-second default flush
interval. The test closes and reopens the audit file and confirms the entries
remain intact. No production code change was warranted. The operator guide now
instructs operators to start the recorder before the engine and verify the
`system.startup` event; it clarifies that `pm-audit-cli health` does not
acknowledge the upstream subscription.

Verification:
- `poetry run pytest tests/test_audit_e2e.py -m e2e -q` — passed
- Full suite — 13,460 passed, 1 skipped; 90% coverage (85% required)
- Repository-wide Black, Flake8, mypy and pyright — passed
- `poetry run mkdocs build` — passed
- `scripts/checkdocs.py` still reports the two pre-existing `Y005` errors
  for `/tmp/symbols.yaml` and `/tmp/desk-keys.yaml`, outside T1's scope

### T2 — Orphaned quote remainders on disconnect and kill (Q2, Q20)

**Resolution:** Quote-origin remainders are quote exposure, even after a
partial fill removes their quote from `QuoteIndex`. `CANCEL_QUOTES_ONLY` and
`CANCEL_ALL` cancel those remainders on disconnect; `LEAVE_ALL` intentionally
preserves them. Participant `KILL` cancels them and counts their IDs under
`cancelled_quotes` / ALF `QUOTES`.

Steps:
1. Before changing code, add failing engine-level tests that:
   - submit a quote with two legs, partially fill one leg, and leave the
     inactive remainder resting;
   - disconnect the quoting gateway under both `CANCEL_QUOTES_ONLY` and
     `CANCEL_ALL`;
   - repeat with the participant's own `risk.kill_switch`;
   - assert both the acknowledged counts/reason and the durable/book-visible
     resting orders after each action.
2. Add a restart variant matching Q20: persist the half-filled quote state,
   restart the engine, send participant `KILL`, and query orders through the
   ALF gateway. Assert there is no quote remainder if the contract says kill
   cancels all resting orders and active quotes.
3. Decide whether disconnect policy cancels all quote-origin remainders or
   intentionally preserves a stated subset. Align behavior with the
   configuration and command contracts; do not change unrelated quote
   replacement behavior.
4. If cancellation is required, apply the existing orphan-leg cancellation
   mechanism to the affected paths and ensure acknowledgements count removed
   orders consistently.
5. Update participant/operator guidance and the affected chapter's expected
   `KILL_ACK` and `ORDERS` output.

**Definition of done:**
- Each exact setup above has a regression test that fails before and passes
  after a required behavior fix; tests assert per-order state, not just totals.
- Both quote legs and acknowledgement counts agree after disconnect, kill
  and restart.
- The intentional behavior for each disconnect policy is documented.
- Targeted engine/gateway tests and full project checks pass.

**Result (2026-11-06):** Added failing-before tests for both disconnect
policies and participant `KILL`; the initial run failed in all three cases
because the orphan remained in the book and `KILL` omitted it from its
acknowledgement. Both disconnect cleanup and participant `KILL` now call the
existing indexed orphan-leg helper. The `LEAVE_ALL` early return remains
unchanged. The restart regression persists a 1,000-share GTC quote after a
340-share partial fill, restores the 660-share remainder, sends `KILL` through
the ALF command handler, and verifies the subsequent ALF `ORDERS` response is
empty. Participant, operator, and training guidance now match this behavior.

Verification:
- Final disconnect/restart regression tests — 13 passed
- Full suite — 13,466 passed, 1 skipped; 90.36% coverage (85% required)
- Repository-wide Black, Flake8, mypy, pyright — passed
- `poetry run mkdocs build` — passed

### T3 — Combo self-match prevention contract (Q3)

**Decision:** AON entry preflight must count only liquidity executable under
the child's resolved SMP policy. With `NONE`, same-gateway liquidity counts
and may self-trade; with any `CANCEL_*` policy, it does not count, and if
that leaves a leg short while it would otherwise cross, the combo fails
without cancelling or trading the resting order. Omitted per-leg SMP resolves
to the gateway default, and explicit `NONE` overrides that default. Once a
combo child is resting, it applies its own resolved SMP action whenever it
later becomes the aggressor (including after a marketable amend).

Steps:
1. Record the expected semantics for `NONE`, `CANCEL_AGGRESSOR`,
   `CANCEL_RESTING` and `CANCEL_BOTH`, covering both entry preflight and
   execution of a resting combo.
2. Add contract tests first for the review's exact scenario: one gateway rests
   an AAPL offer, then submits an AON combo whose first leg crosses that offer
   and whose second leg has external liquidity. Vary SMP policy and omitted
   gateway default; assert combo status, per-leg fills, trades and resting
   orders.
3. Add a separate case where a resting combo's child later encounters the
   same gateway's order. Assert the agreed policy at execution time.
4. Only if the agreed contract differs from current results, fix entry
   preflight and/or execution to use consistent SMP semantics. Preserve
   AON's all-or-nothing guarantee.
5. Correct chapter 10 Exercise 13B and its checkpoint to match the tested
   contract.

**Definition of done:**
- Each agreed SMP case is represented by a deterministic failing-before
  regression test when a behavior change is required.
- AON produces either all intended fills or no fills; no own trade occurs
  unless the agreed policy is `NONE`.
- The guide's predictions and checkpoint agree with the contract tests.
- Targeted combo tests and full project checks pass.

**Result (2026-11-06):** Added entry contract tests for all four SMP actions,
omitted SMP using the configured gateway default, and explicit `NONE`
overriding a non-`NONE` default. Added execution tests that rest an AON combo,
stage same-gateway liquidity, and amend a child across it. The tests confirm
that current preflight and matching behavior satisfy the decision: non-`NONE`
entry rejects the own-only AAPL liquidity without trades or cancellations;
`NONE` fills both legs, including the self-trade. On a later marketable amend,
`CANCEL_AGGRESSOR` cancels the combo child and sibling, `CANCEL_RESTING`
cancels the own order and leaves the child resting, `CANCEL_BOTH` cancels both
sides and the sibling, and `NONE` self-trades. No engine behavior change was
needed. Updated Exercise 13B and its checkpoint with the two distinct
behaviors and their outcomes.

Verification:
- `poetry run pytest tests/test_combo.py -q --no-cov` — 34 passed
- Targeted combo, gateway-integration, and engine-acceptance tests — 67 passed
- Full suite — 13,477 passed, 1 skipped; 90.36% coverage (85% required)
- Repository-wide Black, Flake8, mypy, pyright — passed
- `poetry run mkdocs build` — passed

### T4 — Console logout after engine connection loss (Q4)

**Decision:** When an authenticated console detects that its engine connection
was lost, it logs out and prints `Engine connection was lost; logging out.`
It does not retry commands or authenticate again automatically; the operator
starts a new console session after the engine is available.

Steps:
1. Add regression tests that reproduce a lost engine transport during an
   admin command and during ALF command/heartbeat delivery.
2. Assert both clients print the explicit connection-lost message and exit
   without sending further commands or a misleading graceful disconnect.
3. Update console troubleshooting and the guide's "after engine restart"
   instructions to require starting a new console session.

**Definition of done:**
- Regression tests reproduce lost-transport behavior and verify logout for
  both clients.
- A lost session cannot continue issuing commands or appear connected.
- The guide documents the message and the required new console session;
  targeted tests pass.

**Result (2026-11-07):** Both clients monitor their engine transport for a
ZeroMQ disconnect and log out with the requested message, even while idle.
`pm-admin` exits its prompt and closes without trying to send a graceful
disconnect. `pm-alf-console` monitors the engine event socket and also logs
out on a failed command send or heartbeat. Added a real ZMQ peer-disconnect
test for the ALF listener plus admin command and idle-monitor tests. Updated
the guide introduction and restart instructions.

Verification:
- `poetry run pytest tests/test_commands_console.py tests/test_alf_console_heartbeat.py -q --no-cov` — 48 passed
- Full suite — 13,484 passed, 1 skipped; 90.38% coverage (85% required)
- Black, Flake8, mypy, pyright, and MkDocs — passed

### T5 — Admin identities and safe reset guidance (Q5, Q6)

**Decision (2026-11-07):** Simultaneous `pm-admin` and `pm-admin-cli` sessions
use separate configured ADMIN identities: `GW_ADMIN` for the interactive
console and `ADMIN_CLI` for the one-shot CLI. Reusing an already-connected ID
is an error. For resets, stop all EduMatcher processes first; use the narrowest
reset that meets the scenario's needs.

Steps:
1. Add an engine gateway-auth integration test that connects two distinct
   configured ADMIN IDs concurrently, verifies both can issue an ADMIN-only
   command, then attempts a second live connection with the first ID and
   asserts the exact `Gateway already connected` refusal.
2. Add both identities to example configurations and document which ID each
   operator client uses. Ensure the chosen IDs pass the configuration
   verifier's participant-ID checks.
3. Create a reset matrix for `book_stats.json`, `pm-opctl-cli clear --state`,
   and `--all`: what each removes, required stopped processes, and what must be
   redeployed/restarted.
4. Verify each reset's exact file/directory effects in a disposable data
   directory. Include a safety check that both clear modes warn about active
   processes and refuse a non-interactive request without `--yes`.
5. Add a concise "Starting over" section, explain that the active-process
   warning is not a hard block, and link it from chapters that need a clean
   exchange.

**Definition of done:**
- The simultaneous-session behavior is explicitly selected and the scenario
  is verified through the supported workflow.
- Every reset's effects and preconditions match observed files/process state.
- The guide has one linked reset reference instead of divergent instructions.
- Relevant CLI tests and documentation checks pass.

**Result (2026-11-07):** Separate ADMIN identities are supported by the
engine's existing one-live-connection-per-ID rule. The engine integration
test connects `GW_ADMIN` and `ADMIN_CLI` concurrently, confirms both are
authorized for an ADMIN-only halt operation, and confirms a duplicate
`GW_ADMIN` connection is refused with `Gateway already connected: GW_ADMIN`.
Chapter 01 and the market-maker/capstone examples configure both identities;
the risk-controls and advanced-admin chapters consistently use
`GW_ADMIN` for `pm-admin` and `ADMIN_CLI` for `pm-admin-cli`.

The risk-controls chapter now has the single reset matrix. It distinguishes
deleting only `book_stats.json` from `clear --state` and `clear --all`, names
the removed and preserved state, requires processes to be stopped, warns that
the process check is advisory (and `--yes` bypasses confirmation), and
highlights EOD/settlement data loss with `--all`. Chapters that require a clean
exchange link to this matrix. A disposable-directory test verifies every
listed data path for both scopes and confirms configuration remains; the CLI
warning/refusal test covers both scopes.

Verification:
- `poetry run pytest tests/test_emo_cli.py tests/test_engine_integration.py -q --no-cov` — 104 passed
- Black, Flake8, mypy and pyright on both changed test files — passed
- `poetry run mkdocs build` — passed
- `poetry run python scripts/checkdocs.py` — links, CLI, and anchors clean;
  only the two pre-existing `Y005` missing `/tmp/symbols.yaml` and
  `/tmp/desk-keys.yaml` warnings remain

### T6 — Clearing totals and gateway quote-status scope (Q7, Q8)

**Decisions (2026-11-07):** `pm-clearing-cli symbols` reports gross
participant-side activity, summing both counterparties. It is not market
volume; market volume counts each executed trade once. `STATUS` quote-leg
counts reflect only quote submissions made by the connected gateway, not
market-wide activity.

Steps:
1. For Q7, verify a single market trade against the ledger's per-gateway
   summaries and symbol aggregation. Pin the chosen gross participant-side
   accounting model with a clean clearing database and ensure it cannot be
   confused with market volume.
2. Keep the existing gross aggregation; clarify the field scope in CLI and
   guide descriptions.
3. For Q8, add a failing console test where a non-market-maker gateway gets a
   normal fill without submitting a quote. Compare its `STATUS` quote-leg
   counts with quote IDs acknowledged to that gateway.
4. Fix quote-leg tracking to ignore non-quote fills and verify an acknowledged
   quote leg still updates on fill. Clarify that `STATUS` is local to the
   connected gateway and does not report market-wide quote totals.
5. Correct chapter 08 and clearing CLI guidance to match the confirmed
   accounting and ownership contracts.

**Definition of done:**
- Tests establish the exact accounting and ownership invariants using
  per-trade/per-gateway assertions.
- Any code change has a failing-before regression test and passes it after.
- CLI output and the relevant guide chapters describe the same scope.
- Targeted clearing/console tests and full project checks pass.

**Result (2026-11-07):** Clearing calls `_apply_leg` once for each
counterparty, accumulating the same quantity/notional into each gateway's
daily summary. `query_symbols` sums those per-gateway rows, while `pm-stats`
consumes one `trade.executed` print per market trade. The user confirmed the
intended Q7 contract is gross participant-side activity, not once-per-trade
market volume. A new SQLite-backed test records one 800-share trade, checks
800 shares on each gateway's daily row, checks the symbol totals equal the sum
of both gateway rows for quantity and notional, and confirms there is one raw
trade event.

For Q8, the review's public-broadcast hypothesis was not supported by the
console's subscriptions: `order.fill.<gateway_id>` is a private per-gateway
topic. Instead, the console's fill handler called quote-leg tracking for every
fill and synthesized a cached quote leg with quote ID `?` for ordinary orders.
A new regression test failed on that path; `_record_fill_for_quote_leg` now
ignores fills whose order IDs were not introduced by a quote acknowledgement.
The test also verifies a real acknowledged quote leg still updates on fill.
Chapter 08 now describes those counters as this console's quote submissions,
not a market-wide count.

Verification:
- `poetry run pytest tests/test_clearing_store.py tests/test_clearing_ledger.py tests/test_clearing_cli.py tests/test_alf_console_quote_ack.py -q --no-cov` — 202 passed
- `poetry run pytest tests/test_alf_console_quote_ack.py tests/test_alf_console_heartbeat.py -q --no-cov` — 16 passed
- Full suite — 13,490 passed, 1 skipped; 90.39% coverage (85% required)
- Repository-wide Black, Flake8, mypy and pyright — passed
- `poetry run mkdocs build` — passed
- `poetry run python scripts/checkdocs.py` — links, CLI and anchors clean;
  only the two pre-existing `Y005` missing `/tmp/symbols.yaml` and
  `/tmp/desk-keys.yaml` warnings remain

### T7 — Installed examples, C exercises and version metadata (Q9, Q10, Q21)

**Question to resolve:** What is the supported way to locate packaged examples
for `pm-ai-swarm` and `pm-news play`, and should C exercises be optional in
images without a compiler or should compiled clients ship? Q9 additionally
asks whether stale Poetry version output is packaging metadata or an
installation issue.

Steps:
1. Build a wheel from the current source, install it into a clean environment
   outside the checkout, and reproduce `pm-engine --version`,
   `pm-eod --version`, `pm-ai-swarm` example loading and `pm-news play` with
   the packaged data.
2. Add a regression test for packaged example resolution that runs without a
   repository checkout. If an example is addressed by name, assert the name
   resolves to the same packaged file as the documented path.
3. Determine whether stale version output is reproducible after a clean
   install. Fix version metadata/build configuration only if the clean install
   still reports a version other than the package version; document the
   required reinstall for an already-stale editable environment if that is
   the only cause.
4. Verify C-exercise prerequisites in the published container. Choose either
   to ship runnable compiled examples (with architecture/build provenance
   addressed) or to mark those exercises optional and provide a supported
   Python/raw-socket alternative.
5. Update chapters 23–25, 27–29 and installation guidance to use the verified
   examples path and state compiler prerequisites.

**Definition of done:**
- A clean wheel-installed environment resolves all documented examples and
  reports the correct version without access to the checkout.
- The container instructions do not imply unavailable `make`/`cc` tools.
- Chosen packaging/C-exercise behavior has automated or scripted verification.
- Packaging checks and relevant documentation tests pass.

### T8 — Normal-use warnings and artifact errors (Q11)

**Question to resolve:** Should missing-monitor beacon warnings and expected
engine-unreachable heartbeats be quiet below WARNING? Should invalid artifact
startup show a concise error rather than a traceback?

**Contract decision (2026-11-08):** Missing or unavailable monitoring and
engine-unreachable heartbeat sends during restarts are expected operational
noise: log them at DEBUG, retaining the existing beacon rate limit. Disabled
monitoring sends no beacons and emits no warning. An invalid deployed artifact
must stop `pm-engine` with status 1 and one actionable error; traceback
diagnostics are available at DEBUG.

Steps:
1. Add log-capture tests first for: (a) a process with no monitor configured,
   (b) a configured but unavailable monitor over at least two reporting
   intervals, (c) engine shutdown/restart heartbeat transitions, and
   (d) a malformed deployed artifact.
2. Record current levels, repeat rates, traceback and final actionable
   message. Agree which conditions are expected operational noise versus
   operator-actionable faults.
3. Change only expected-noise levels/rate limiting and top-level artifact
   error presentation. Preserve diagnostic details in debug logs or an
   explicit verbose mode.
4. Update troubleshooting guidance with the normal and error outputs.

**Definition of done:**
- Tests assert exact severity/repeat behavior and actionable error text.
- Expected conditions do not flood normal-use output; real failures retain
  enough diagnostic context to debug.
- Invalid artifacts still fail startup with a nonzero result and no
  success-shaped fallback.
- Targeted tests and docs checks pass.

**Evidence:**
- `poetry run pytest tests/test_health_reporter.py tests/test_alf_console_heartbeat.py tests/test_engine_main.py tests/test_config_runtime_readers.py -q --no-cov`
  — 77 passed. With monitoring disabled, no reporter/log is created; a
  configured monitor rejecting beacons over three sampler intervals logs at
  DEBUG without stopping the reporter. Repeated controlled send attempts verify
  the 60-second rate limit. A heartbeat send failure during engine loss logs
  the drop at DEBUG, retains the single logout error/message, and stops the
  console. Malformed JSON (`{ not json`) makes `pm-engine` exit 1 with one
  actionable error; `-vv` retains exception details at DEBUG.
- `poetry run mkdocs build` — passed; the Training Guide index and Chapter 01
  describe the normal and debug output.
- `poetry run black --check src tests`, `poetry run flake8 src tests`,
  `poetry run mypy src tests`, and `poetry run pyright src tests` — passed.

### T9 — Swarm budget semantics (Q12)

**Question to resolve:** Is `budget: 40` a hard per-second cap, a moving
average, or a target rate with burst allowance?

Steps:
1. Specify the rate window, burst tolerance, whether all order actions count,
   and the measurement point (scheduled, attempted, accepted or completed).
2. Add a deterministic fake-clock/rate-limiter test first. Request actions
   through at least several windows, including a burst at a window boundary,
   and assert the selected bound. Add a swarm integration measurement over
   the same window and counter definition.
3. If a hard cap is intended, correct pacing so no measured window exceeds
   the limit (within explicitly documented timer/measurement tolerance). If a
   target/average is intended, expose and document expected burst and
   averaging behavior.
4. Update `swarm.yaml` comments, status output labels and chapter 14.

**Definition of done:**
- The tests distinguish a hard cap from an average/target and reproduce the
  reported `45.1/s` scenario.
- Status output reports the same rate window and action definition as the
  configuration.
- The guide says "about" only if the agreed contract is approximate.
- Targeted swarm tests and docs checks pass.

### T10 — Teaching configuration and persisted exchange history (Q13)

**Question to resolve:** Should teaching examples isolate learners from
persisted same-day `DAY` orders and historical reference prices, or teach the
operator-documented persistence/collar behavior explicitly?

Steps:
1. Add a deterministic scenario test that runs the relevant chapter setup
   twice against the same business-day data directory, including a resting
   `DAY` order and a persisted last/reference price. Capture which commands
   fail or produce different predictions on the second run.
2. Decide whether the training configuration should use a wider dynamic
   collar, a clean disposable data directory/reset, or explicit exercises
   about persisted state. Do not change production persistence semantics
   solely to make the training example repeatable.
3. If changing example configuration, add a test that deploys it, restarts
   the engine, and verifies both order persistence and the intended collar
   bounds. If retaining defaults, add explicit starting-state and expected
   rejection checks to the chapter.
4. Link to the reset instructions from T5 where a clean state is required.

**Definition of done:**
- The repeated-run scenario reliably reproduces the hidden-history effect.
- The selected teaching setup is repeatable and does not contradict operator
   persistence documentation.
- Relevant examples and chapter predictions are verified from a clean
   checkout/data directory and a second run.

### T11 — Session-transition rejection replies (Q14)

**Finding:** The engine logs and returns without replying when a requested
transition is invalid from the current phase; REST then times out instead of
returning the documented rejection.

Steps:
1. Add a failing engine/API integration test: set the market to
   `CONTINUOUS`, request transition to `CONTINUOUS`, and assert a prompt
   negative reply with a reason; assert REST returns `409 TRANSITION_REJECTED`
   rather than waiting for `503 ENGINE_TIMEOUT`. Also test an unknown target
   and sessions-disabled mode as existing reply-path controls.
2. Fix the invalid-allowed-transition branch to use the same reply contract
   as the other rejected cases.
3. Exercise `pm-admin-cli session` for an invalid transition and decide whether
   it should return the rejection promptly or continue to wait for a later
   phase broadcast. Document the selected distinction.
4. Update API/CLI documentation and the training chapter's invalid-transition
   example.

**Definition of done:**
- The exact `CONTINUOUS` → `CONTINUOUS` test fails before and passes after.
- REST returns the documented status and reason within the normal response
  timeout; no false transition broadcast is emitted.
- CLI behavior is intentionally tested and documented.
- Targeted session/API tests and full project checks pass.

### T12 — Index history, listing and restored session phase (Q15, Q16)

**Questions to resolve:** Is date-only `TO=` inclusive or exclusive? Should
`INDEX` list every configured index? How does a restarted `pm-index` learn the
current session phase? Which gateway roles support `INDEX`?

Steps:
1. For Q15, add a failing history-query test with records on the `TO` date and
   on the following date. Test equal `FROM`/`TO` values and a timestamp-valued
   `TO`; agree and assert inclusive-date or exclusive-date semantics, then
   align operator/participant docs and training chapter.
2. For Q16 index listing, publish updates for two indices with different
   throttling intervals and query `INDEX`. Assert that the response lists both
   IDs if the command is documented as a list; otherwise change help/docs to
   say it returns only the latest update.
3. Add a failing restart test that opens the market, starts or resets
   `pm-index`, and checks update events and daily roll-up session state before
   any subsequent phase change. Make the service obtain the current phase
   from an authoritative initial state/snapshot if required by the contract.
4. Check `INDEX` availability through each documented role, including
   `pm-admin`; either implement the supported command or correct the
   "any gateway role" documentation.
5. Re-run the chapter 26 second-index exercise with explicit deployment and
   verify the output through the documented interface.

**Definition of done:**
- Date boundary behavior is tested with records on both sides of the
  boundary and documented consistently.
- Multi-index output and restart phase are correct under the selected
  contracts, including before the next broadcast.
- Every documented role's command availability is verified.
- Chapter 26 is runnable from a clean, deployed configuration; targeted index
  tests and docs checks pass.

### T13 — ATO expiry reason (Q17)

**Finding:** An ATO remainder expiring after the opening auction is reported
with a DAY-order/trading-day-ended reason, which misstates both the order type
and timing.

Steps:
1. Add a failing auction integration test: submit an ATO order with a
   non-marketable remainder, complete the opening uncross while the business
   day remains active, and capture the order's final event/reject reason and
   client-visible message.
2. Define the reason for an unfilled ATO remainder separately from DAY
   end-of-day expiry. Update the expiry path and message schema only as needed
   to preserve compatibility.
3. Assert the order is no longer live, no unintended trade occurs, and the
   emitted reason identifies the ATO auction expiry.
4. Update auction/order-type documentation and the training example.

**Definition of done:**
- The test reproduces the incorrect reason before the fix and asserts the
  corrected client-visible reason after it.
- Order state, trade state and expiry event agree.
- Relevant clients/specification/examples are updated and targeted auction
  tests pass.

### T14 — Generated API-key usability and safety (Q18)

**Question to resolve:** How should a user obtain random generated API keys
for documentation and examples without making secrets predictable from
`--seed` or exposing them in unsafe output?

Steps:
1. Add a failing config-generation test showing that `--seed` reproduces
   non-secret configuration but generated keys are random and the generated
   credentials are not readily discoverable by the documented workflow.
2. Choose a secure contract. Prefer cryptographically random keys independent
   of `--seed`, written to a credentials file with restrictive permissions
   and clearly disclosed to the invoking user. Do not derive live credentials
   from a reproducibility seed. Decide whether user-supplied
   `--api-gateway-key GW=KEY` is also needed.
3. Implement the selected output path and test that generated keys match the
   deployed config, are not printed to general logs, are not overwritten
   silently, and the credentials file permissions are appropriate.
4. Update REST examples to read keys from the generated credentials file or
   use explicit placeholders with clear substitution instructions.

**Definition of done:**
- A clean generation/deploy exercise can authenticate using the documented
  procedure without guessing a key.
- Repeating `--seed` does not make credentials predictable or identical
  unless explicitly overridden by a user-provided test key.
- Secret handling, file permissions and error cases are covered by tests.
- Documentation and config-generator tests pass.

### T15 — Per-recipient drop-copy sequence (Q19)

**Question to resolve:** Is `seq` required to be contiguous for each
participant subscription, as promised by the protocol and chapter 21, or is
it explicitly a global sequence whose per-recipient gaps must be interpreted
differently?

Steps:
1. Add a failing multi-recipient protocol test: two gateways receive a trade;
   each subscribes only to its own `drop_copy.event.<GW>` topic. Interleave
   additional events for both gateways and assert the sequence contract for
   each recipient independently.
2. Test replay using each recipient's buffer, including a missing range and
   engine restart. Verify sequence values are meaningful to the consumer of
   that recipient's stream and do not imply false gaps.
3. If the promised per-recipient gap detector is the contract, maintain
   recipient-scoped sequence state and use it consistently for live delivery
   and replay. If global sequence is intentional, amend protocol and chapter
   language and define how consumers detect loss on filtered streams.
4. Update the drop-copy specification, examples and chapter 21 with the
   tested semantics, including restart behavior.

**Definition of done:**
- A two-gateway test reproduces the stride-2 observation and validates the
  chosen sequence contract for both live and replayed events.
- No false gap is reported for a complete recipient stream.
- Protocol, implementation and chapter agree on scope and reset behavior.
- Targeted drop-copy tests and docs checks pass.

### T16 — Close training-route and exercise verification gaps (§§3–4)

**Scope:** Complete all explicit "not verified" items in the review and
validate prior review corrections on the supported distribution routes.

Steps:
1. Create a verification matrix with route, environment, chapter/exercise,
   command/input, expected result and captured result. Use disposable
   directories and a private network namespace; do not operate on a shared
   simulation.
2. Verify container chapters 04 onward; the Multipass route; pipx install; and
   the real installer in a disposable environment. For deployment steps that
   could affect global processes or state (including `pm-opctl-cli stop` or
   `start`), replace them with a safe isolated validation or document them as
   manual checks that must not be run on a shared host.
3. Finish the unplayed chapter 10 Exercises 14B/15B and chapter 14
   retracted-rumour/chip-race scenarios; create deterministic fixtures for
   chapter 24 Exercise 4D corridor expansion and 4E non-default
   `tick_decimals`; run chapter 28 Exercise 6 with `EVICT_OLD`.
4. Validate chapter 29's interactive key bindings, pick-lists, 120-column
   layout and PDF/`p` workflow in a controlled terminal. Verify the chapter
   22 design-exercise limitations, chapter 27 `RATE_LIMITED`, and chapter 23
   `BAD_MESSAGE`/`SLOW_CLIENT` using deterministic, bounded tests instead of
   unreliable manual timing where possible.
5. Run `scripts/checkdocs.py`; fix and regression-check the two reported
   `Y005` snippets in the operator configuration guide if they remain present.
   Run a full `mkdocs build` and resolve newly introduced failures, keeping
   unrelated pre-existing failures clearly separated.
6. Re-run representative chapters 00–29 from the supported Python and
   packaged/container routes after T1–T15 changes. Confirm every command
   block's stated starting state, output and recovery steps.

**Definition of done:**
- Every listed unverified route/exercise has a recorded pass, a bounded
  automated test, or a clearly documented reason it cannot safely be run.
- No verification command operates on the developer's live exchange or
  deletes shared data.
- `scripts/checkdocs.py` has no unresolved errors attributable to the
  reviewed training/operator examples; any unrelated baseline is recorded.
- `mkdocs build` succeeds and the final chapter verification matrix matches
  the committed guide.

---

## 4. Risks and decision gates

- **Protocol changes:** T3, T4, T11 and T15 may change client-visible behavior.
  Finalize the contract and check protocol compatibility before implementation;
  update specs, clients and examples together.
- **Secret handling:** T14 must not make generated API credentials
  deterministic from `--seed` or expose them in routine logs.
- **Stateful tests:** T1, T2, T10 and T12 need isolated durable state and
  deterministic restart/readiness boundaries. A sleep-only reproduction is
  not sufficient.
- **Documentation versus product behavior:** T5, T6, T8, T9, T12 and T13 have
  open semantic questions. If current behavior is intentional, record the
  decision and correct documentation rather than shipping an unnecessary
  behavior change.
- **Installer/system-wide actions:** T16's installer, Multipass and process
  control checks must run only in disposable environments. Never use global
  stop/clear commands on a developer machine with unrelated `pm-*` processes.
