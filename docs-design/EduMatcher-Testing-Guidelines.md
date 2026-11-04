# Business-contract testing guidelines

The test suite should establish that EduMatcher behaves like an exchange, not
just that its current implementation runs without errors. A test is useful
when its expected result comes from a business rule, a message contract, or an
independent oracle—not merely from observing what the code under test happens
to do.

These guidelines turn the gaps in
[the key-component workplan](./EduMatcher-Key-Component-Fixes-Workplan.md)
into reviewable test expectations. K19 is adding coverage and measurement in
stages; this document is guidance, not a claim that every listed path is
already covered.

## Start with the exchange outcome

Describe the scenario in domain terms: who submits which orders, what market
event occurs, and what each participant, operator, or downstream process must
observe. Derive expected results from the requirements, message schema, or
trading rules. Do not copy the implementation's control flow or comments into
the expected result.

Where possible, make the test fail against the defect before fixing the
production code. Keep the oracle independent: do not call the same matching,
rounding, aggregation, or persistence logic to calculate the expected answer.

## Construct the state the rule needs

Fixtures should make relevant interactions possible. If a rule concerns
participants, symbols, precision, connections, order legs, or constituents,
include multiple distinct values and assert their separate outcomes. In
particular, use different tick precisions when testing price conversion and
multiple actors when testing ownership, self-match prevention, or correlation.

A one-entity fixture is appropriate when the business rule is genuinely about
one entity or when it deliberately tests a boundary such as the final index
constituent. It should not be the default for behavior whose purpose is to
coordinate multiple entities.

Reuse the existing [actor fixtures](../tests/support/actors.py),
[bad-value cases](../tests/support/badvalues.py),
[failure injectors](../tests/support/faults.py),
[restart oracle](../tests/support/restart.py), and
[structural counters](../tests/support/counting.py) rather than creating
parallel helpers for the same purpose.

## Assert invariants per entity

An aggregate can hide an incorrect allocation. Assert which order filled,
which sibling was cancelled, each participant's trade and position, and the
resulting ledger or rollup—not only the total matched quantity or row count.
After operations that can alter shared state, check the relevant invariant,
such as OCO exclusivity, no prohibited self-match, AON atomicity, visible
quantity consistency, finite index values, or ledger idempotence.

Prefer shared invariant assertions where they can be applied across scenarios.
Keep an invariant independent of the operation's return value; otherwise the
same defect can affect both the behavior and its check.

## Cross durable and wire boundaries

When behavior crosses a process boundary, inspect what the next process or
client actually receives: persisted records, a restored snapshot, or the
published message. In-memory state alone cannot prove that a write, replay,
snapshot, or wire response is correct.

For restart behavior, compare durable state and business-visible observables
before and after constructing a fresh process from persisted state. Do not
seed private state by hand if the production startup path is responsible for
reconstructing it.

## Prove recovery from partial failure

Inject failures at durable writes, socket operations, and engine sends. For
recoverable operations, make the operation fail once and then succeed; assert
the final business result, including that work was neither lost nor applied
twice. Exercise failures inside the full workflow where an earlier successful
step can make a later failure destructive, rather than testing only the
isolated send or write.

Maintain an explicit inventory of relevant call sites and their failure tests.
A new durable write, socket operation, or engine send should either have a
recovery test or a recorded reason why failure is not recoverable or relevant.

## Test hostile values at the boundary

Malformed bytes are only one kind of bad input. Exercise well-formed messages
with values outside the business domain: absent optional fields, `None`,
non-finite numbers, negative zero, fractional values where integers are
required, oversized strings, and values on the wrong price scale.

For message handlers, verify both that invalid input does not escape the
handler loop and that a subsequent valid message is still processed. Apply
each value only where its type and meaning make sense; a shared bad-value set
is a source of cases, not a claim that every value is valid for every field.

## Break ordering and correlation assumptions

Pipeline requests, interleave symbols, and return correlated responses out of
order. Assert each result is attached to the correct request or symbol. A
test that sends one request and awaits its reply before sending the next does
not verify pipelining or non-FIFO resolution.

## Treat cost as observable behavior

For paths whose scaling matters, assert structural work: call counts,
iteration counts, or database query plans. Avoid wall-clock thresholds for
ordinary correctness tests; machine load makes them noisy and they do not
identify the source of extra work.

## Use mutation testing as a check on the tests

A useful mutation changes a business outcome—for example, order priority,
auction allocation, idempotency, or persisted state. The relevant regression
test should fail against that mutation. Record which tests kill each pinned
mutant, and prevent the score from regressing; do not treat a mutation score
as a substitute for reviewing the business contract or as a target to inflate
with implementation-shaped assertions.

## Measure coverage that reflects risk

Test count and line coverage remain useful diagnostics, but neither shows
whether multi-actor states, restart behavior, failures, or domain invariants
were exercised. Report the denominator alongside each metric. K19's useful
suite-level measures are:

- mutation score for the pinned hot-path mutants;
- restart-equivalence coverage across required stateful components and
  scenarios;
- fault-injection coverage across the inventoried failure points; and
- the number and scenario coverage of shared business invariants.

## Review checklist

Before adding or changing a behavior test, ask:

- Is the expected result stated in business or protocol terms?
- Does the fixture contain enough distinct actors and values to expose the
  interaction under test?
- Are outcomes asserted per order, participant, or durable record where an
  aggregate could conceal an error?
- Does the test inspect the persisted or published result when that is the
  actual contract boundary?
- Does it cover partial failure, invalid values, or adversarial ordering when
  those are relevant to the behavior?
- Is the oracle independent of the production implementation?
- Would a deliberate defect in this rule make the test fail?
