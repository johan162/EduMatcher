---
name: component-review
description: Holistic pre-release review of one EduMatcher component (a src/edumatcher/<pkg>/ directory and the CLI, docs and shared code around it) for correctness, edge cases, performance and comment/help-text accuracy, written up as docs-design/reviews/EduMatcher-<Name>-Review-<YYYY-MM>.md with findings separated from test-first work packages; and the later implementation of those WPs. Use when asked to "review <component>" in the style of the stats/audit/EOD reviews, or to "complete/implement WP-<XXX>nn" from such a review document.
---

# Component review (EduMatcher)

Two phases, usually in separate turns:

1. **Review** → a review document with findings, decisions and work packages.
   Nothing in `src/` changes in this phase.
2. **Implement** → the WPs, one at a time (or "in one go" when asked), each
   test-first, each verified by the full suite, each with a recorded outcome.

Reference documents that already follow this style. Read one before writing a
new review, and match it:
`docs-design/reviews/EduMatcher-EOD-Review-2026-11.md` (the most complete,
with outcomes and a follow-up), `EduMatcher-Stats-Review-2026-11.md` and
`EduMatcher-Audit-Review-2026-11.md`.

Supporting files in this skill, which you must read:
- `review-template.md`: the exact document skeleton and section rules.
- `lessons-learned.md`: defect patterns to hunt for and process mistakes
  to avoid. Go through its checklist during every review and again before
  closing every WP.

## Ground rules (both phases)

- **No guessing.** Every claim in the document is one of: *(repro)*,
  reproduced with a scratch script against the real code; *(measured)*, timed
  on this host; or by inspection, with `file.py:line` given. If you are unsure
  how something behaves, read the related code (callers, the other process that
  writes the data, the docs that promise the behaviour) until you know. Ask the
  user only for decisions that are genuinely theirs; put those in §7
  Decisions with a recommendation.
- **Scope:** the named directory, plus the shared functions it calls *where they
  decide its behaviour*. Read every line of the scope and the operator, user or
  reference docs that describe it. Shared code outside the scope is fixed only
  on the paths the component uses. The rest goes in §9 and, if it is a real
  defect, in `docs-design/EduMatcher-For-Later-ToDo.md` as a new `Lnnn` status
  row plus a detailed section.
- **Focus:** correctness (wrong, lost or misleading numbers; silent failure);
  edge cases (reruns, restarts, resets, retention, empty or missing files,
  clock and date edges, bad input); performance (measured, and whether it grows
  with history or with the day); and readability: comments, docstrings, help
  texts and guide passages that say something the code does not do.
- **Scratch work** (repro scripts, bench databases) goes in the session
  scratchpad, never in the repo. Repro scripts drive the real writers (for
  example `clearing.store` writers and `run_day`), not hand-made rows, wherever
  possible.
- Follow the user's CLAUDE.md: Poetry commands, black/flake8/mypy/pyright/pytest
  clean, `pytest -n logical` (never `-n auto`), surgical changes, no backwards
  compatibility or migration code unless asked.
- Never commit. End with a proposed commit message (EduMatcher's Conventional
  Commit style with the attribution line from the system reminder).

## Phase 1: the review

1. **Orient.** `wc -l` the scope; read the module docstrings; find the earlier
   design doc and reviews of the component (`docs-design/`, the auto-memory
   index) and list what they already fixed, so it is not reported again
   ("Previous work").
2. **Read every line**, then each shared function the component calls, and the
   code of *other processes* that write the data it reads (that is where the
   worst bugs hide; see lessons-learned §A1).
3. **Walk each user-facing flow** the docs describe (the guide's procedures,
   the training exercises, the scheduler hook, reruns, resets) through the real
   code. Unit tests rarely cover these sequences.
4. **Reproduce** every suspected correctness defect with a minimal script, and
   put the observed numbers in the finding as a table or a short output block.
   Reproduce the *consequence* (money lost, scheduler stuck, wrong exit code),
   not just the mechanism.
5. **Measure** performance on a realistic synthetic database (sim scale: tens
   of days, about 10⁵ trades a day, hundreds of gateways × tens of symbols).
   Check `EXPLAIN QUERY PLAN` for every day-scoped query. Report before/after
   numbers and say whether the cost grows with history or with the day.
6. **Check every text**: module docstrings, comments, `--help`, the `pm-help`
   registry (`src/edumatcher/pm_help/registry.py`), the operator guide chapter,
   the reference manual, and the training and participant guides.
7. **Write the document** from `review-template.md`. Findings first (what is
   wrong and why, with evidence), then decisions, then WPs (how to fix it,
   test-first, with exit criteria). Every finding maps to exactly one WP.
8. **Out-of-scope** findings go in §9, and real defects also get a For-Later
   `Lnnn` entry.
9. **Save a project memory** for the review (status, key findings, open
   decisions) and add its index line.
10. **Report to the user** briefly: the headline defect(s) with their repro
    numbers, the counts by severity, the measured performance, and the
    decisions needed. The findings live in the document, not in the chat.

## Phase 2: implementing WPs

For each WP, in the document's suggested order (stop after each one unless the
user said "in one go"):

1. **Tests first.** Write the WP's numbered tests. Run them focused
   (`poetry run pytest <files> -q --no-cov`) and check from the `E` lines that
   each "(Fails today.)" test fails *for the right reason*. Tests marked
   "unchanged" must pass before and after.
2. **Smallest production change** that makes them pass. Match the
   surrounding style; no speculative options.
3. **Boundary and regression cases** found on the way become tests too.
4. **Docs in the same WP** when behaviour visible to users changes (messages,
   exit codes, files), unless a later text-only WP owns them. Regenerate the
   generated artefacts: `make dbdocs` (SQLite schema docs), `make completion`
   (shell completion from argparse help).
5. **Verify:** `poetry run black src tests`, `make _check` (black, flake8,
   mypy, pyright, msgen, dbdocs, openapi), then the full suite **in the
   foreground**:
   `timeout 900 poetry run pytest tests/ -n logical --no-cov -q -p no:cacheprovider`
   (about 2 minutes). Do not edit files while a suite is running.
6. **Re-check the exit criteria** honestly. If a numeric target is missed,
   say so in the outcome with the measured number and the reason; do not
   quietly weaken the test.
7. **Record the outcome** in the WP section ("**Outcome (YYYY-MM-DD).**"
   followed by what changed, design choices, which tests failed first, and the
   full-suite count), tick the status table (☑ + date), and update the
   document's Status line.
8. **Re-walk the documented flows** the change touches (lessons-learned
   §B1). If that reveals a defect, including one your own earlier WP
   introduced, fix it test-first, record it as a "Follow-up" under the WP that
   caused it, and say so in the hand-over.

When all WPs are done: set the Status line to "Done, uncommitted", update
memory, and hand over with: what changed for users, the full-suite result,
anything done beyond the plan, items the WP text said to confirm (exit codes,
contracts), stray files you did not create, and the proposed commit message.
