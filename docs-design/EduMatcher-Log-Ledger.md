# EduMatcher — Log Ledger: Explanations and Actions for WARNING+ Log Messages

An operator who opens a WARNING, ERROR or CRITICAL row in the log-GUI sees
the raw message and nothing else. Most messages only make sense to someone who
has read the code that emits them. This plan adds a **log ledger**: a central,
version-controlled catalogue with one entry per WARNING+ log call site in
`src/edumatcher`. Each entry has a short **explanation** (what happened and why
it matters) and a list of **suggested actions**. `pm-log-cli` and the log-GUI
both read the same ledger. The GUI shows the two texts in the row drawer, below
the message.

One work package (WP) at a time, as in the other workplans. Each WP ends with
the holistic test run, a review, and a proposed commit message. The maintainer
commits.

Started: 2026-11-09

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 1 | L1 | Template id end to end: logclient → LALF `TPL` → `log_events.tpl` → LALF-PS → bridge `LogRow.tpl`; `schema_version` table (v2) checked at startup; constant templates at the dynamic call sites | — | 1 d | ☑ | 2026-11-09 |
| 2 | L2 | `edumatcher.log_ledger`: format, loader, AST call-site scanner, coverage test; `pm-log-cli ledger list/show/check/export`, `explain <seq>`, `--explain` on `query`/`tail`; seed entries for `log_srv` (`logclient` has no WARNING+ call) | L1 | 1 d | ☑ | 2026-11-09 |
| 3 | L3 | log-GUI: bridge loads the ledger, `GET /api/ledger`; drawer panels *Explanation* + *Suggested actions*; "no ledger entry" state | L2 | 0.5 d | ☑ | 2026-11-09 |
| 4 | L4 | Content: engine, orders, board, messaging, ticker | L2 | 0.5 d | ☐ | |
| 5 | L5 | Content: gateways (alf_gwy, balf_gwy, api_gateway, md_gateway, dc_gateway, ralf_gateway, calf_client, ralf_spy, dc_spy) | L2 | 1 d | ☐ | |
| 6 | L6 | Content: alf_console, clearing, audit, stats | L2 | 0.5 d | ☐ | |
| 7 | L7 | Content: ai_trader, mm_bot, market_sim, index, viewer | L2 | 0.5 d | ☐ | |
| 8 | L8 | Content: monitor, scheduler, health, config*, setup, the rest. Coverage test becomes a hard failure, docs | L4–L7 | 0.5 d | ☐ | |

## 1. Decisions

Decided with the maintainer on 2026-11-09:

| # | Question | Decision |
|---|---|---|
| D1 | How is a row matched to its ledger entry? | **The log template is captured at the source.** The logclient handler computes a template id from `(record.name, record.msg)` (logger + unformatted format string) and sends it with the row. Lookup is an exact key match in Python and in TypeScript, so no regex matcher exists in two languages that could drift apart. |
| D2 | How is the content written? | **Infrastructure first, then content one package group at a time** (L4–L7). Until L8 the coverage test lists missing entries for packages that are not done yet; packages that are done must be complete. L8 makes every gap a hard failure. |
| D3 | How does `pm-log-cli` show the ledger? | All three: `explain <seq>`, an `--explain` flag on `query`/`tail`, and `ledger list/show/check/export`. |
| D4 | Old `log.db` files | Not migrated (standing rule: no backwards compatibility). `log.db` gets a `schema_version` table and starts at **version 2**; a file without the table counts as version 1. `open_db` checks the version every time it opens an existing file, writable or read-only. On a mismatch it raises `LogDbSchemaError`, and `pm-log-srv` logs CRITICAL "delete log.db" and exits 1. `pm-log-cli` and the log-GUI bridge fail with the same message. A brand-new (empty) file is created at the current version. |

## 2. Template id

```
tpl = sha1(logger ␟ template)[:12]        # ␟ = U+241F, as in the bridge fingerprint
```

* `logger` is `record.name`, and `template` is `str(record.msg)` **before**
  `%`-formatting.
* It is computed only for `levelno >= WARNING`. INFO and DEBUG rows get
  `tpl = NULL`, which costs nothing on the hot path where most rows are.
* Twelve hex characters (48 bits) are far more than enough for ~340 entries.
  `ledger check` fails on a collision.
* Why a hash and not the template text: the LALF header line cannot contain
  `|` or `\n`, and storing a ~60-byte template on every WARNING+ row in
  `log.db` is wasted space when the ledger already holds the text.
* Third-party loggers (uvicorn, asyncio, zmq) also get a `tpl`. They have no
  ledger entry, so every reader shows "no ledger entry", which is correct.

### 2.1 Pipeline changes (L1)

| Layer | Change |
|---|---|
| `logclient/handler.py` `_build_log_frame` | compute `tpl` and pass it to `build_log_frame` |
| `logclient/protocol.py` | optional `TPL=` header field on `LOG`; stored as sent (like `LINE`, it is advisory) |
| `log_srv/schema.py` | `log_events.tpl TEXT` (nullable); `INSERT_LOG_EVENT` gets one more column |
| `log_srv/server.py`, `writer.py` | carry `tpl` from the frame into `LogEventRow` |
| `log_srv/pubsub.py` `row_to_dict` | `"tpl": row.tpl` |
| `log_cli/queries.py` | `tpl` in the selected columns |
| `log-gui/packages/log-types` `LogRow` | `tpl: string \| null` |
| `log-gui/apps/bridge/src/log-db.ts` | select `tpl` |
| `spec/messages/log.yaml` `LogRow` (+ `make msgen`) | `tpl` (nullable, max 12). **Required.** LALF-PS rows go through the generated `LogRow.from_dict`, which drops any field the spec does not declare. Without it, `tpl` reached `log.db` but never the live stream or backfill (found in L1, covered by `test_template_id_reaches_live_and_backfill_rows`) |
| `log_srv/schema.py` | `schema_version` table, `SCHEMA_VERSION = 2`, `check_schema_version` in `open_db` (both modes). The old additive `_migrate()` is gone, because no older file is accepted any more |
| `log-gui/apps/bridge/src/log-db.ts` | `LOG_DB_SCHEMA_VERSION = 2`. `open()` refuses any other version, and `/api/status` shows the reason. A Python test keeps the two constants equal |

The single function that computes the id lives in
`edumatcher/logclient/protocol.py` (`template_id(logger, template)`), because
the logclient must not import the ledger package. The ledger loader imports it
from there.

### 2.2 Dynamic call sites

The first count, 22 sites, also included argparse `parser.error(...)`. Only
four real log calls passed a non-constant template, and L1 fixed them:

* `engine/main.py`, global kill switch: the f-string becomes a `%s` template.
* `board/main.py` and `orders/main.py`, `_log_startup_warnings`: the warnings
  are collected at import time, before logging is configured. They were
  pre-formatted strings, so each one got its own `tpl`. They are now
  `(template, args)` pairs that are replayed as `log.warning(template, *args)`.
* `monitor/collector.py` `_warn(kind, msg, *args)`: this already passes the
  caller's constant template through, so it needed no change.

There are also **relay sites**: a helper that receives the template from its
caller and logs it. Examples are `monitor/collector.py` `_warn`,
`health/reporter.py` `_warn`/`_log_rate_limited` (via `log.log(level, …)`)
and the board/orders startup warnings. At runtime `record.msg` is the
caller's constant, so `tpl` is stable. The L2 scanner cannot see the template
at the log call, though. It needs a small relay table: for each relay, the
callee to look for and which argument holds the template (for example
`self._warn` arg 0 in `health.reporter`, `warnings.append` tuple item 0 in
`board.main`). Any other non-constant WARNING+ template stays a hard error.

## 3. Ledger format (L2)

Package `src/edumatcher/log_ledger/`, data in `entries/<group>.yaml`, one file
per package group so each content WP edits its own file.

```yaml
# entries/engine.yaml
- logger: edumatcher.engine.engine
  template: "SMP uncross on %s left a crossed book (bid %s >= ask %s)"
  level: ERROR
  explanation: >
    After a self-match-prevention uncross the best bid is still at or above
    the best ask. The book is in a state the matching rules forbid, and new
    orders may trade at wrong prices.
  actions:
    - Halt the symbol with `pm-opctl-cli halt <symbol>`.
    - Save `audit.db` and the engine state file before restarting.
    - Report it as an engine bug with the symbol and time.
```

* The key is `(logger, template)`. `tpl` is computed when the file loads and is
  never written by hand.
* `level` is for display and for the lint check only. The scanner verifies
  that it matches the call site.
* `explanation` is 1–3 sentences of plain text. `actions` is 1–4 imperative
  lines. Backticks mark commands; the GUI renders them in monospace and the CLI
  prints them as is.
* Each action is written as a double-quoted YAML string. A bare string that
  contains `: ` becomes a mapping, and one that starts with a backtick is a YAML
  error. The loader rejects the first ("actions must be a list of 1-4
  non-empty strings"), and it names the file and entry index.
* No Markdown, no HTML, no links. The text has to read well in a terminal.

### 3.1 Loader API

```python
@dataclass(frozen=True)
class LedgerEntry:
    tpl: str
    logger: str
    template: str
    level: str
    explanation: str
    actions: tuple[str, ...]

def load_ledger() -> dict[str, LedgerEntry]      # keyed by tpl; cached
```

The data files ship as package data (`importlib.resources`), so an installed
`pm-log-cli` has them and needs no source tree.

### 3.2 Call-site scanner and coverage test

`edumatcher.log_ledger.scan` walks `src/edumatcher` with `ast` and finds every
`<x>.warning/.error/.critical/.exception(...)` call whose receiver resolves to
a logger:

* The logger name is resolved from the module's `getLogger(__name__)` or
  `getLogger("literal")` assignment. A call whose logger the scanner cannot
  resolve is an error, so the scanner never skips a site without saying so.
* `.exception` counts as ERROR.
* Calls such as `warnings.warn` or `console.error`, which are not logging
  calls, are excluded by receiver resolution and not by a name list.

`tests/test_log_ledger.py`:

1. Every call site has an entry, except in packages listed in
   `PENDING_PACKAGES`. A companion test fails when a pending package has no
   gaps left, so a finished package has to leave the set and the gate closes
   on it. L4–L7 remove their packages, and L8 deletes the set.
2. Every entry has a call site, so a stale entry fails.
3. The entry `level` equals the call-site level.
4. No template is non-constant at WARNING+.
5. There are no `tpl` collisions.
6. A round-trip test: a real `LalfLogHandler` record produces the same `tpl`
   as the ledger entry for that site.

`pm-log-cli ledger check` runs checks 1–5 on an installed source tree and is
what an author runs while writing entries.

## 4. `pm-log-cli` (L2)

| Command | Output |
|---|---|
| `pm-log-cli explain <seq>` | the row, then `Explanation:` and a numbered `Actions:` list. If the row has no entry: `No ledger entry for this message (tpl=…)`. If the row is below WARNING: says so. `--format json` adds an `explain` object |
| `pm-log-cli query … --explain` / `tail … --explain` | under each WARNING+ row with an entry, the explanation and actions indented below it. Rows without an entry are unchanged |
| `pm-log-cli ledger list [--logger PREFIX] [--level L]` | table: tpl, level, logger, template |
| `pm-log-cli ledger show <tpl>` | one entry in full |
| `pm-log-cli ledger check` | §3.2 checks 1–5; exit 0/1 |
| `pm-log-cli ledger export --format json` | `{tpl: {logger, template, level, explanation, actions}}`; what the log-GUI bridge reads |

Man page (`pm_help`) and the operator-guide `pm-log-cli` chapter are updated
in L2.

## 5. log-GUI (L3)

* **Bridge**: at startup it runs `pm-log-cli ledger export --format json` once,
  the same way `routes/diagnostics.ts` already shells out to `pm-log-cli`, and
  keeps the result in memory. `GET /api/ledger` returns it. When `pm-log-cli`
  is missing, it returns an empty ledger plus `available: false`. Every other
  view keeps working, as for Diagnostics.
* **Web**: `useLedger()` fetches `/api/ledger` once (react-query, `staleTime:
  Infinity`). The Explorer drawer (`views/Explorer.tsx`, below the message
  block) shows, for WARNING+ rows:
  * **Explanation** panel: the entry's explanation.
  * **Suggested actions** panel: numbered list, with backtick spans rendered in
    monospace.
  * No entry: one muted line, "No ledger entry for this message", with the
    `tpl` so it can be reported.
  * Ledger unavailable: one muted line saying `pm-log-cli` is not available.
* Changes to the ledger reach the GUI when the bridge restarts. There is no
  hot reload, because the ledger only changes with a release.
* Vitest: the drawer renders both panels, the no-entry state and the
  unavailable state. Bridge test for the export parsing and the 503 fallback.

Notes from L3:

* The bridge loads the ledger lazily, on the first `GET /api/ledger`, not at
  startup. A successful export is kept until the bridge restarts. A failed one
  is not kept, so the next drawer that opens tries again; the bridge logs a
  warning, and the route answers 200 with `available: false` and the reason.
* The container image installs `edumatcher` from PyPI when no wheel is placed
  in `.wheel/`. A release older than L2 has no `ledger` subcommand, so the
  drawer then says "No explanations available: … ledger export failed". This
  is correct and needs no code.
* e2e (`tests/test_log_ledger_e2e.py`): the real bridge on the mini exchange's
  `log.db` serves exactly the shipped ledger, and headless Chrome opens a real
  scheduler WARNING in the Explorer and finds the drawer's ledger text. Until
  L8 that is the no-entry line. The test reuses `Page`/`until` from
  `test_monitor_e2e.py`.

Out of scope for this plan, noted for later: the Alerts view issue detail could
show the same panels, and the bridge fingerprint could use `tpl` instead of the
regex normaliser.

## 6. Content WPs (L4–L8)

Each content WP:

1. runs `pm-log-cli ledger check` to list the missing entries for its packages;
2. reads each call site in context and writes the entry. The explanation says
   what the operator sees and what it means for the exchange, not what the
   code does. The actions are concrete: commands, config keys, files to check,
   when to escalate. If nothing needs doing (an expected, self-healing
   warning), the action says so plainly;
3. reviews the call sites it reads: a message that is really INFO, or one that
   is unclear, is fixed at the source in the same WP and the change is listed;
4. removes its packages from `PENDING_PACKAGES`.

Writing entries often uncovers wrong log levels and unclear messages. The
review step (3) is part of the WP, not a side effect.

### 6.1 Notes from L2 for the content WPs

* **pm-log-srv's own messages never reach `log.db`.** Its `--log-target` is
  stdout or a file, never itself. Its entries (`log_srv.yaml`) are therefore
  only reachable through `pm-log-cli ledger list/show`, never through `explain`
  or the GUI drawer. They are kept for completeness. If operators need it, a
  later `ledger search TEXT` could find the entry for a line from pm-log-srv's
  console.
* **Logger-parameter helpers removed.** `config_artifact.report_deployment()`
  and `healthcheck.answer_health_ping()` took the caller's logger, so one
  message had a different `tpl` in each of 13 processes. They now log
  through their own module loggers. The `logger` column for those messages
  changes from e.g. `edumatcher.engine.main` to `edumatcher.config_artifact`;
  `process` still says which process logged them.
* **Scanner coverage at L2:** 302 WARNING+ call sites, 301 distinct keys, no
  unresolved site. Relay table: board/orders startup warnings, `monitor`
  `_warn`, and `health.reporter` `_warn`/`_log_rate_limited`. `log.log(level,
  …)` levels resolve through `logging.X`, `a if c else b`, and module-level
  dicts of `logging.X`.
* **Seen on a real `mini` exchange (e2e):** pm-scheduler logs two WARNINGs at
  every start ("no confirmation that the engine applied CLOSING_AUCTION/CLOSED
  …"). L8 should check whether they are real or noise before writing their
  entry.

## 7. Open questions

| # | Question | Answer |
|---|---|---|
| Q1 | An existing `log.db` lacks the `tpl` column. | Decided 2026-11-09: the `schema_version` table plus a fail-fast check. See D4. |
| Q2 | Should `has_exception` rows key on the exception type instead of the template? | No. `log.exception("x failed")` already has a constant template, and the traceback stays in the message. |
| Q3 | Templates with no literal text, such as `log.warning("%s", warning)` in `config_artifact.py`. | They give one `tpl` for many different messages, so one generic entry has to cover all of them. L2's `ledger check` lists them, and the content WP rewrites each one to a specific template or splits the call. |
