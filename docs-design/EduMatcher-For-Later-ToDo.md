Version: 1.0.0

Date: 2026-11-11

Status: Design and Research Proposal

# EduMatcher — For Later ToDo

Global findings that fall outside the work package that uncovered them. They
are recorded here so they are not forgotten; each one is picked up later as
its own piece of work.

## Status

| ID | Date | Area | Finding | Priority | Status |
|----|------|------|---------|----------|--------|
| L001 | 2026-11-11 | sim_forensics / msgen | pm-sim-forensics hard-codes 185 topic literals and is exempt from the literal gate | Low | Open |

## L001 — Topic literals in pm-sim-forensics

**Found:** 2026-11-11, when `test_msgen_literals.py` failed (12 tests) after
commit `dad29aba` moved `sim_forensics` from `tools/` into
`src/edumatcher/sim_forensics/`.

**Finding.** The literal gate (`pm-msgen grep-literals`, enforced by
`tests/test_msgen_literals.py`) scans `src/` for topic names written as string
literals instead of the generated `TOPIC_*` constants. Once `sim_forensics`
moved under `src/`, the gate found 185 literals across 10 modules in
`sim_forensics/checks/` (`breakers`, `coverage`, `cumulative`, `derived`,
`differential`, `immediate`, `matching`, `persistence`, `quotes`,
`refusals`). Families affected: order (67), risk (28), quote (23), system
(21), book (10), circuit_breaker (10), structure (10), auction (6), trade (6),
session (4).

**Interim fix (done).** `sim_forensics` was added to `_EXEMPT_PARTS` in
`src/edumatcher/msgen/literals.py`, and to the separate path filter in
`test_trade_executed_appears_nowhere_as_a_literal`. That restores the state
before the move: under `tools/`, it was never scanned.

**Remaining risk.** The gate exists because a publisher-side topic rename is
silent for a consumer. That applies to forensics too: if `trade.executed` is
renamed, forensics checks find no matching lines and report SKIPPED or pass
on empty data, without failing.

**Options.**

1. *Migrate.* Replace the literals with the generated `TOPIC_*` constants and
   remove the exemption. Many uses are prefix matches (`"order.ack."`,
   `"circuit_breaker.halt."`) or `startswith` tuples, which have no
   ready-made constant. They need either a prefix helper in the generated
   bindings or a derived prefix (for example `TOPIC_ORDER_ACK.split("{")[0]`).
   Check that this does not conflict with the "independent of the component
   it checks" principle in `sim_forensics/__init__.py`. The constants come
   from the spec, not the producer's code, so it probably does not.
2. *Guard without migrating.* Keep the literals, and add a test asserting that
   every topic or prefix that `sim_forensics` matches on is a declared topic
   (or a prefix of one) in `spec/`. A rename then fails that test instead of
   silently emptying a check.
3. *Accept.* Leave the exemption, and rely on the forensics coverage check
   noticing missing traffic.

**Recommendation.** Option 2: it closes the silent-rename hole with one test
and leaves the 185 lines alone.
