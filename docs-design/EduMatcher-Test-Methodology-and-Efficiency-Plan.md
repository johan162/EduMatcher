# Test methodology and efficiency workplan

**Status:** Proposed; intended to sequence and complete K19 of the
[key-component fixes workplan](./EduMatcher-Key-Component-Fixes-Workplan.md).

## 1. Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|----|---------|------------|------|--------|---------|
| 0 | T0 | Establish a trustworthy suite baseline | — | TBD | ◐ | |
| 1 | T1 | Make test layers explicit | T0 | TBD | ☐ | |
| 2 | T2 | Map tests to business contracts and oracles | T1 | TBD | ☐ | |
| 3 | T3 | Apply shared invariants to relevant scenarios | T2 | TBD | ☐ | |
| 4 | T4 | Complete restart-equivalence coverage | T2 | TBD | ☐ | |
| 5 | T5 | Build the failure and value-domain matrices | T2 | TBD | ☐ | |
| 6 | T6 | Expand mutation testing without multiplying suite cost blindly | T3–T5 | TBD | ☐ | |
| 7 | T7 | Reduce feedback time using measurements | T0, T6 | TBD | ☐ | |
| 8 | T8 | Layer CI and publish risk-relevant suite signals | T1, T7 | TBD | ☐ | |

T0 is in progress; the initial full-suite run completed but did not retain the
final timing summary required for its baseline. Estimates will be set after T0
measures the work and available test-runner data.

## Purpose

Improve the suite's ability to detect business-rule defects while reducing the
time and effort needed to get useful feedback. The goal is not to maximize
test count, line coverage, or mutation score in isolation. Tests should be
derived from exchange and protocol contracts, assert externally meaningful
outcomes, and run at the lowest cost that still provides trustworthy evidence.

The [business-contract testing guidelines](./EduMatcher-Testing-Guidelines.md)
define the test-design expectations. This plan defines the staged engineering
work to apply and measure them.

## Current evidence and constraints

- The test suite is split across many `test_*.py` modules, and the default
  pytest configuration excludes `heavy`, probabilistic, performance, e2e, and
  container tests.
- Shared support already exists for actors, bad values, call counting, failure
  injection, and restart equivalence. `tests/test_support_harness.py` tests
  those helpers.
- Restart-equivalence and injected-failure tests already cover selected stats,
  index, and clearing scenarios. Engine and gateway restart tests also exist.
- `tools/mutate_engine.py` provides pinned engine mutants; its Makefile help
  estimates a full mutation run at about 50 minutes. K19 calls for broader
  coverage of clearing, index, and stats as well.
- CI currently runs one coverage-enabled pytest job with logical xdist workers.
  Runtime changes must preserve worker isolation and the coverage threshold.
- A default-suite run with `--no-cov` and no xdist workers completed
  successfully. It was still running after 10m45s; the run output did not
  preserve the final duration summary, so this is a cost signal, not the T0
  baseline.

The first work package records a reproducible timing and category baseline.
Do not treat one machine's duration as an acceptance threshold.

## Goals and non-goals

### Goals

1. Make business-contract coverage visible by component, scenario, and risk.
2. Extend restart, failure, hostile-value, multi-actor, and invariant testing
   where an explicit gap is found.
3. Use representative mutations to demonstrate that new checks detect
   deliberate business defects.
4. Give contributors fast, reliable local feedback and give CI a clear full
   regression gate.
5. Improve runtime only where measurements show a repeatable bottleneck, and
   retain deterministic failure diagnostics.

### Non-goals

- Changing production behavior solely to make tests easier or faster.
- Blindly changing every shared fixture to contain multiple actors; actor
  cardinality must match the business rule under test.
- Removing integration or end-to-end coverage to reduce CI duration.
- Enforcing flaky wall-clock limits on ordinary correctness tests.
- Adding a third-party mutation or property-testing dependency before a trial
  shows it improves on the repository's existing helpers and pinned mutants.

## Work packages

### T0 — Establish a trustworthy suite baseline

**Work:** Inventory pytest cases and markers by component and test layer.
Capture clean-run durations with and without coverage, worker count, the
slowest tests, collection time, and current CI duration. Record the exact
commands, environment, and commit. Identify flaky tests from repeated runs,
not from a single failure.

**Done when:**

- A committed baseline records commands and test counts by marker/category,
  plus measured runtime observations and their environment.
- A short repeated run confirms that timing variation is not being mistaken
  for a code improvement.
- Tests that are expensive because they duplicate setup or scenarios are
  listed with evidence, not just suspected.

### T1 — Make test layers explicit

**Work:** Define documented suites for focused unit/contract feedback, the
default regression suite, and opt-in expensive system, probabilistic,
performance, and container checks. Audit marker use and ensure each test is
included in at least one named suite. Keep default-suite semantics stable
until the inventory and CI impact are understood.

**Done when:**

- One documented command exists for each supported feedback layer.
- Collection checks prove that no test is silently excluded by an empty
  selection or an unregistered/unused marker.
- CI's full correctness gate still runs every required non-optional layer.

### T2 — Map tests to business contracts and oracles

**Work:** For high-risk exchange behaviors, maintain a small matrix from
contract/rule to scenario, observable assertion, and test location. Prioritize
the K1–K18 defects and the §4 examples. Strengthen assertions that only check
totals, implementation-private state, or successful execution when the
business result can be observed independently.

**Done when:**

- Each selected high-risk rule has an independent expected result and a
  per-entity or durable/wire assertion.
- At least three representative deliberate defects are detected by the
  intended contract tests.
- The matrix records genuine gaps separately from covered behavior; it does
  not count files or lines as contract coverage.

### T3 — Apply shared invariants to relevant scenarios

**Work:** Consolidate reusable exchange invariants without forcing irrelevant
checks onto every test. Start with OCO exclusivity, prohibited self-match,
AON atomicity, visible quantity, finite index level, and ledger idempotence.
Attach assertions at scenario boundaries or operation boundaries where the
state is valid and meaningful.

**Done when:**

- Every invariant has an independent definition, scope, and positive test.
- Relevant deterministic and randomized scenarios invoke the invariant
  checks, with seed and scenario context in failures.
- A deliberate violation of at least two invariants is caught by the shared
  assertion rather than a test-specific duplicate assertion.

### T4 — Complete restart-equivalence coverage

**Work:** Inventory stateful processes and define component-specific
observables and durable artifacts. Extend the existing restart helper and
tests for engine, clearing, stats, and index. Exercise applicable combinations
of trades, duplicates/replay, corporate actions, and phase changes; do not
force inapplicable events into a component's scenario.

**Done when:**

- Every in-scope stateful process has at least one restart-equivalence scenario
  that checks durable state and business-visible results.
- Scenario coverage and exclusions are recorded in a matrix.
- A deliberately omitted or corrupted persisted field causes the relevant
  equivalence test to fail.

### T5 — Build the failure and value-domain matrices

**Work:** Inventory durable writes, socket operations, engine sends, and
decoded-message handlers by process. For recoverable operations, inject a
failure once and verify eventual success without loss or double application.
For handlers, test applicable hostile values and verify a valid subsequent
message is still processed. Record non-recoverable or inapplicable cases with
their rationale.

**Done when:**

- Each in-scope failure point and handler is listed with a test or an explicit
  reviewed exclusion.
- Fault tests exercise full workflows when an earlier successful action makes
  a later failure consequential.
- At least one representative failure and one hostile-value defect are
  demonstrated to fail before the corresponding fix/check and pass afterward.

### T6 — Expand mutation testing without multiplying suite cost blindly

**Work:** Keep the existing pinned engine mutants and add a small, curated set
for clearing, index, and stats. First run each mutant against focused relevant
tests; run the full default suite only for survivors or as a periodic audit.
Report killed, survived, invalid, and timed-out mutants separately. Record the
test IDs that kill each mutant and maintain a no-regression baseline after
reviewing changes to the mutant set.

**Done when:**

- Mutants represent reviewed business defects and are pinned to source
  changes that cannot silently stop applying.
- Every mutant is checked by its focused tests; the periodic broader audit is
  reproducible.
- CI or a scheduled workflow detects regression against the reviewed baseline
  without running every mutant against the entire suite on every pull request.

### T7 — Reduce feedback time using measurements

**Work:** Use T0's profile to address the largest repeatable costs. Candidate
changes include removing duplicated process startup, using narrower fixtures,
improving test data setup/cleanup, and selecting worker counts based on
observed throughput. Avoid optimizing test bodies at the expense of their
contract assertions. Keep resource isolation explicit under xdist.

**Done when:**

- Each optimization includes before/after measurements from the same
  environment and a correctness-equivalence check.
- Repeated runs show a useful improvement without increased flakiness, leaked
  resources, or weakened coverage.
- No optimization relies on arbitrary sleeps, shared mutable state between
  workers, or machine-specific time thresholds.

### T8 — Layer CI and publish risk-relevant suite signals

**Work:** After T1 and T7, make CI feedback layers explicit: fast checks on
every change, the complete regression suite as a required gate, and scheduled
or manually invoked expensive audits. Publish denominators for selected
contract, restart, failure-injection, and invariant coverage alongside the
mutation baseline. Do not replace line coverage or delete existing system
tests.

**Done when:**

- Every pull request still receives a required full correctness result and
  coverage gate.
- Expensive mutation/performance/system audits have an owner, cadence, and
  visible result.
- Metrics include numerators and denominators and are reproducible from the
  repository.

## Suggested order

T0 → T1 → T2 → T3/T4/T5 → T6 → T7 → T8.

T3, T4, and T5 can proceed independently after T0, but each should use the
shared test conventions from T2. Runtime work in T7 must not begin until T0
provides a baseline; CI reshaping in T8 depends on the suite boundaries and
cost data from T1 and T7.

## Completion

This plan is complete when T0–T8 meet their done criteria, the K19 completion
criteria in the key-component workplan are satisfied, and the full correctness
suite remains green. Update both this plan and K19 as packages land; do not
mark the retrospective complete based on documentation or line coverage alone.
