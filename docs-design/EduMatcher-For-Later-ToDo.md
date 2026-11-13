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
| L002 | 2026-11-11 | trader-gui | `formatChangePct` shows "-0.00%" (and "+0.00%" for zero) for a change that rounds to zero | Low | Open |
| L003 | 2026-11-13 | docs (operator guide, quick start, participant guide) | Container install has seven web applications (Clearing GUI on 8096), the books say six / 8090–8095 | Low | Open |
| L004 | 2026-11-13 | pm-config-gen | `[HINT] Validate with: poetry run python -c … Path("engine_config.yaml")` is wrong for installed users and names the wrong file | Low | Open |
| L005 | 2026-11-13 | pm-cverifier | Header counts `Semantic: 2 warnings` while the verdict says `1 WARNING` (the INFO M004 is counted as a warning) | Low | Open |
| L006 | 2026-11-13 | consoles / pm-mm-bot | Prices printed as raw floats: `149.8`, `@149.93333333333334`, `book mid=150.51999999999998` | Low | Open |

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

## L002 — trader-gui "-0.00%" change

**Found:** 2026-11-11, while doing clearing-GUI follow-up CG16 (no "-0.00" in
`formatPrice` / `formatSignedPrice`).

**Finding.** `trader-gui/apps/web/src/lib/formatters.ts` `formatChangePct`
signs on the unrounded value and formats with `toFixed(2)`: a change of
-0.001 % renders "-0.00%", and a flat symbol "+0.00%". Same defect class as
F20/CG16, but CG16 named only the two price formatters, so it was left alone.

**Fix.** Sign on the rounded text, as `formatSignedPrice` now does (the
private `fixed` helper in the same file), test-first:
`formatChangePct(149.9999, 150)` gives `"0.00%"`.

## L003 — "Six web applications" in the other books

**Found:** 2026-11-13, training-guide review (container route).

**Finding.** `./edumatcher.sh start` brings up seven web applications; the
seventh is the Clearing GUI (`pm-clearing-ui`) on port 8096
(`CLEARING_GUI_PORT`). The training guide is fixed. Still saying six, or
8090–8095: `operator-guide/part-1-install-and-deploy/010-installation.md`
(lines ~29, 33, 81), `operator-guide/part-3-run/010-running-the-exchange.md`
(~54), `quick-start/90-backmatter/020-when-something-does-not-work.md` (~32),
`participant-guide/part-6-front-ends/010-trading-info-terminal.md` (~163) and
`030-order-book-gui.md` (~211).

## L004 — pm-config-gen validation hint

**Found:** 2026-11-13, training guide chapter 01.

**Finding.** After writing its output, `pm-config-gen` prints
`[HINT] Validate with: poetry run python -c 'from pathlib import Path; from
edumatcher.engine.config_loader import load_engine_config; print(load_engine_config(Path("engine_config.yaml")))'`.
The command needs a Poetry checkout, and it names `engine_config.yaml` even when
`--output generated.yaml` was given. `pm-cverifier <output file>` is the
command the documentation teaches.

## L005 — pm-cverifier semantic count

**Found:** 2026-11-13, training guide chapter 01.

**Finding.** For the chapter 01 configuration the summary block says
`⚠ Semantic: 2 warnings` while the verdict says `1 WARNING, 4 ADVISORIES`; the
second "warning" is the INFO-level `M004`. The two counts should agree.

## L006 — Float formatting of prices

**Found:** 2026-11-13, training guide chapters 02–05.

**Finding.** `pm-alf-console` prints fills as `@149.8` and averages as
`@149.93333333333334`; `pm-admin BOOK` shows `149.8`; `pm-mm-bot --verbose`
logs `book mid=150.51999999999998`. Prices should be printed with the
symbol's `tick_decimals` (an average could keep more digits, but rounded).

