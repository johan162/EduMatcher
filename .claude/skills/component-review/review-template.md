# Review document template

File: `docs-design/reviews/EduMatcher-<Name>-Review-<YYYY-MM>.md`.
WP prefix: a short component tag (`STA`, `AUD`, `EOD`, …) → `WP-EOD01`.
Finding IDs: **H** (High), **C** (correctness), **P** (performance), **D**
(comments/docs), numbered within the document (`C1`, `C2`, …). The ID says
what kind of finding it is; the severity goes in the Sev column.

Writing style: short declarative sentences, concrete numbers, `file.py:line`
for every claim by inspection, code excerpts only where they make the defect
visible. Explain *why* it matters (what an operator sees, what money moves,
what stops). No hedging about things you could have checked.

---

```markdown
# <pm-name> Review — <YYYY-MM> (pre-1.0.0)

**Scope:** `src/edumatcher/<pkg>/` at `<short sha>` (v<version>): `a.py`
(<lines> lines, <role>), `b.py` (<lines>), …. <Which modules are shared and
who else reads them.> <Shared code read only where it decides this component's
behaviour, not reviewed as code of its own.>

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts and <guide chapter path> say what the code does.

**Previous work:** <design doc / earlier reviews and their fix IDs>. Their
fixes are in place and are not repeated here: <one-line list>.

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with a scratch script against the tree at `<sha>`, using
<the real writers/entry points>. *(measured)* means timed on this host against
<describe the synthetic data and its size>. The other findings are by
inspection, with line numbers given.

Status: **Open.** Decisions Q1–Qn are needed before WP-…

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (<rows in x.db, files, CLI output, exit code, metric>).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_<pkg>_*.py` <and the other
   suites that read this component> with `-n logical`, then
   black/flake8/mypy/pyright. Do not start the next WP with a known failing
   test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

<One paragraph: which fixtures/helpers the tests should use.>

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-XXX01 | <outcome-phrased title> | H1, D3 | Q1 | 1 d | ☐ | |

Suggested order: **WP-XXX01 → …**. <Why: what destroys data first, what
blocks other work, decisions pending, text-only WP last so texts describe the
final code.>

Estimated sequential effort: about N days, excluding review time and findings
discovered on the way.

---

## 1. Overall assessment

<What is sound, as a paragraph, so a reader knows what not to worry about.>

The defects are in <n> places:

- **<Theme> (H1).** <two or three sentences>
- …

Severity key: **High**: <money/data lost or misattributed without a
warning>. **Med**: <a wrong, lost or misleading figure; a failure that blocks
later work or is invisible to its supervisor>. **Low**: hardening, clarity,
hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Ledger | <one sentence, with the repro numbers> *(repro)* | XXX01 |
| D1–Dn | — | Comments | See §5 | XXX0n |

---

## 3. Correctness findings

### C1. <Title that states the defect> *(repro)* — Med

`file.py:120-140` `function_name`.

<Mechanism, with a short code excerpt if it helps.> <Repro: the steps and the
observed numbers as a table or output block.> <Consequence: what the operator
sees, what stops, what money moves.> <How it gets triggered in practice: a
list of real paths.>

**Fix.** <the direction, not the code; refer to Qn if a decision is needed>

---

## 4. Performance findings

<Say first whether any of this matters at today's sizes.>

### P1. <Title> *(measured)* — Low

<table: before numbers, the query plan lines, growth with history vs day>

**Fix.** <…>

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `file.py:187` | <what the text says vs what the code does> |

---

## 6. Verified as correct

- **<Area>.** <What was checked and why it is right, so it is not
  re-reviewed.>

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | <the question with options (a), (b), (c)> | **(a)**, because … <and why the others fail> |

---

## 8. Work packages

### WP-XXX01 — <Title> (H1, D3; after Q1)

**Tests first** (`tests/test_<file>.py`):

1. <Concrete scenario → expected observable result>. (Fails today.)
2. <Unchanged behaviour that must still hold>, unchanged.

**Change.** <the smallest change; names of functions and tables>

**Exit criteria.** Tests 1–n pass; <suites> green; <measurable target if
any>.

<After implementation, append:>

**Outcome (YYYY-MM-DD).** <What changed, design choices, docs touched,
which tests failed first and why, the full-suite count.>

**Follow-up (found during WP-XXXnn, YYYY-MM-DD).** <Only if a later WP found
a defect this WP caused or left behind: repro numbers, fix, tests.>

---

## 9. Out of scope, noted

- <Finding outside the scope, why it is not fixed here, and its `Lnnn` id in
  `EduMatcher-For-Later-ToDo.md` if it is a real defect.>
```

## Rules for the sections

- **Findings and WPs are separate.** §3 to §5 say *what is wrong*, with
  evidence. §8 says *how to fix it* and *how we will know*. Every finding ID
  appears in exactly one WP's Findings column (D-items can sit in the WP that
  changes the same code; the rest go in a final text-only WP).
- **WP titles state the outcome** ("Reruns never downgrade a settled day"),
  not the activity ("Fix rerun").
- **WP tests** are numbered, behavioural, and say "(Fails today.)" or
  "unchanged". They name the test file. A WP whose criteria cannot be
  measured is not done.
- **Exit criteria** are measurable: named tests pass, named suites are green,
  and any numeric target comes from a measurement or is labelled as a guess.
- **Decisions** carry a recommendation and the reason the alternatives fail.
  Once answered, mark them "(taken as recommended)" or record the answer, and
  add a line under the §7 heading.
- **Outcomes** are appended, never rewritten over the plan, so the document
  shows both what was intended and what was done.
- **Status line** at the top: Open → In progress → Done, uncommitted (with the
  last full-suite count and anything changed beyond the plan).
