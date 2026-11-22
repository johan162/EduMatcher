# pm-audit-replay Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/audit/replay/` at `87f3cbcd` (v0.83.4): `cli.py`
(1 269 lines, the CLI and the index policy), `detect.py` (1 027, the
cross-message findings), `rerun.py` (917, `rerun`), `render_text.py` (914),
`links.py` (848, the link resolver), `state.py` (751, the state model),
`index.py` (726, the episode index writer), `episodes.py` (660, the
assembler), `queue.py` (606, `queue`), `facts.py` (471), `reader.py` (439,
the index reader), `views.py` (436), `render_json.py` (361), `ordering.py`
(327), `lexicon.py` (326), `anomalies.py` (292), `derived.py` (269),
`templates.py` (254), `kinds.py` (220), `terminal.py` (172), `stats.py`
(125), `pipeline.py` (84). The shared readers it calls were read where they
decide its behaviour: `audit/query.py` (`iter_entries`, `parse_ts`,
`discover_log_files`, `discover_day_files`) and `audit/rawlines.py` (the
re-run's line splitter, shared with pm-sim-forensics). The engine paths the
re-run drives (`Engine._publish_dispatch`, `_flush_persistence`,
`_book_may_reject`) were read to check what the trail can contain. None of
those were reviewed as code of their own.

**Focus:** correctness, edge-case handling, performance at simulation scale,
and whether the comments, help texts, the `pm-help` entry, the operator
guide's chapters `part-6-observe-and-recover/030-audit-replay.md` and
`035-answering-a-dispute.md` and the reference manual's `pm-audit-replay`
section say what the code does.

**Previous work:** `docs-design/EduMatcher-Audit-Replay.md` (phases AR-0 to
AR-8, checkpoints CP-1 to CP-8), `EduMatcher-Audit-Completeness-Workplan.md`
(A4 `rerun`, A8 `queue`), the sim-forensics fixes the re-run carries (S37
live clock, X10 batched `IN`, X11 cancel batches, X13 request refusals) and
the pm-audit review of 2026-11 (C11 `rawlines` without `chain=`, C12
pm-audit-cli's `--to YYYY-MM-DD` made end-of-day). Their fixes are in place
and are not repeated here, except that C12 was fixed for pm-audit-cli only
(C5 below is the replay half).

**Method:** every line of the files above was read. Findings marked
*(repro)* were reproduced with scratch scripts against the tree at
`87f3cbcd`, through `pm-audit-replay`'s own `main()`, on synthetic trails in
pm-audit's line format and on trails recorded by the real engine
(`tests.test_sim_forensics_rerun.record`). *(measured)* means timed on this
host (36 cores, 125 GB; runs niced and pinned to 8 cores beside a running
simulation) against the **live simulation trail of 2026-11-22**: 71 closed
parts of 256 MB plus `audit.log`, 18 GB, about 27 million lines. A part holds
about 375 000 lines and 21 minutes of trading. Findings marked *(real
trail)* were found in that trail. The other findings are by inspection, with
line numbers given.

Status: **Done, uncommitted** (2026-11-22). All ten WPs implemented in one
go, in the suggested order, followed by a holistic review (§10). Decisions
Q1–Q4 were not answered before implementation; each was implemented as its
recommendation (Q1 a, Q2 a, Q3 b, Q4 a) and is to be confirmed.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (CLI output, exit code, the findings in `anomalies`,
   the rows of the index, files left on disk, peak memory).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_audit_replay_*.py`,
   `tests/test_sim_forensics_*.py` and `tests/test_audit_*.py` with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP
   with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Tests drive `edumatcher.audit.replay.cli.main` with `--log-file`/`--db` in
`tmp_path`. Trails come from two sources: `tests.test_sim_forensics_rerun.record`
for a trail the real engine wrote (OCO, quote, cancel and restart paths), and
a small line builder in the style of the replay fixtures for shapes the
engine cannot be made to produce on demand (a late fill, a 10 000.04 print).
The OCO-cancel and quote-cancel false positives need a recorded trail that
contains `order.oco_cancel` and `quote.cancel`; extend `record` rather than
hand-writing those chains.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-RPL01 | `--db` never destroys a file that is not an index, and a build never leaves a half index behind | H1, C7 | — | 1 d | ☑ | 2026-11-22 |
| 2 | WP-RPL02 | A healthy simulation trail reads clean: one episode per order, no unsolicited or unmatched cancels that were asked for | H2, C1 | — | 1.5 d | ☑ | 2026-11-22 |
| 3 | WP-RPL03 | A live, day-sized trail is answered without rebuilding the index on every call | H3 (index), C4 | Q1 | 2 d | ☑ | 2026-11-22 |
| 4 | WP-RPL04 | The reports hold one episode at a time, and pass 1 forgets what has been answered | H3 (memory), P1 | Q2 | 2 d | ☑ | 2026-11-22 |
| 5 | WP-RPL05 | `story` reads only the links of the episodes it shows | P2 | — | 0.5 d | ☑ | 2026-11-22 |
| 6 | WP-RPL06 | `stats` counts the same findings as `anomalies` | C3 | — | 0.5 d | ☑ | 2026-11-22 |
| 7 | WP-RPL07 | Every price in a finding or a sentence is printed exactly | C9 | — | 0.5 d | ☑ | 2026-11-22 |
| 8 | WP-RPL08 | `rerun` and `queue` answer a live trail honestly and refuse what they ignore | C6, C8, C10, C11 | Q4 | 1.5 d | ☑ | 2026-11-22 |
| 9 | WP-RPL09 | CLI edges: `--to` a date, exit codes, a subcommand required, values validated, suggestions that run | C5, C12, C13, P3 | — | 1 d | ☑ | 2026-11-22 |
| 10 | WP-RPL10 | Comments, docstrings, `pm-help`, guide and reference manual say what the code does | C2, D1–D11 | Q3, all | 1 d | ☑ | 2026-11-22 |

Suggested order: **WP-RPL01 → 02 → 07 → 06 → 05 → 09 → 08 → 03 → 04 → 10**.
WP-RPL01 first because it deletes files. WP-RPL02 next because it is what
makes `anomalies --severity warn` usable at all on a simulation trail, and
every later WP's tests read that report. 07, 06, 05 and 09 are small and
independent. 08 waits on Q4, 03 on Q1 and 04 on Q2 (04 builds on the index
policy 03 settles). The text-only WP-RPL10 is last so the texts describe the
final code.

Estimated sequential effort: about 11.5 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The reconstruction itself is careful. Units are read off each message rather
than guessed, so a price is never rescaled wrongly. Ordering by `eseq`
within a publisher run is right, and a late fact does not regress the
`SEQ_GAP` high-water mark. A declared origin is kept apart from an unknown
cause. The re-run's completeness gates (an `eseq` jump, a recorder restart
while the engine ran, a first start that restored orders) hold, and on a real
part it re-ran 43 554 commands in 11.6 s. Text and NDJSON agree by
construction. None of that needs another look (§6).

The defects are in five places:

- **`--rebuild` deletes whatever `--db` names (H1).** `open_index` discards any
  file whose schema version it cannot read, so `--db data/clearing.db
  --rebuild` deletes the clearing ledger and writes an episode index in its
  place. Without `--rebuild` the same mistake is a traceback. Two invocations
  at once crash one another (C7).
- **The bug-hunting view is flooded on a healthy simulation trail (H2, C1).**
  One 21-minute part of today's trail yields 2 560 `CANCEL_UNSOLICITED`
  warnings, every one an OCO or quote leg cancelled by a recorded request, and
  25 `CANCEL_UNMATCHED` warnings for cancels that lost the race to a fill.
  Over a day that is about 185 000 false warnings. Step 2 of the dispute
  procedure ("`anomalies --severity warn` over the day ... a clean result
  means") can never come out clean, and a real finding drowns.
- **A live, day-sized trail is out of reach (H3).** The index covers the
  whole live trail and is stale whenever `audit.log` grows, so every call on
  a running exchange rebuilds it: about 73 minutes and 50 GB for today's
  trail. The reports then hold every episode of the window with its payload:
  2.46 GB per part, more than this 125 GB host has for a whole day.
- **Findings that depend on the window (C2, C3, C4).** A fill after an order's
  end goes unreported once the order is 2 000 facts behind, which is
  0.2 seconds at simulation rate. `stats` counts different findings from
  `anomalies`. The indexed and `--no-index` answers for one window differ,
  where the guide says they are identical.
- **The re-run on a running exchange (C6, C8).** A half-written last line
  crashes `rerun` and `queue` with a `JSONDecodeError`, and the final-book
  check compares with a checkpoint up to 5 s older than the trail.

Severity key: **High**: a file destroyed, or the tool's verdict on a trail
wrong at scale (a healthy trail reported broken, or the tool unusable on the
trail it exists for). **Med**: a wrong, lost or misleading finding or figure;
a crash on an input the tool will meet in normal use. **Low**: hardening,
clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| H1 | High | Index | `--rebuild` deletes and replaces any file `--db` names: a SQLite file lost its table, a text file became an index; without `--rebuild` a traceback *(repro)* | RPL01 |
| H2 | High | Findings | 2 560 `CANCEL_UNSOLICITED` warnings per part for OCO and quote legs cancelled by a recorded request *(real trail)* | RPL02 |
| H3 | High | Scale | Every call on a live trail rebuilds a 73-minute, 50 GB index; the reports hold 2.46 GB per part *(measured)* | RPL03, RPL04 |
| C1 | Med | Episodes | A request or ack after an order's last fill opens new episodes: 25 false `CANCEL_UNMATCHED` and 34 orders split in three per part; `story` shows one third, a prefix finds none *(real trail)* | RPL02 |
| C2 | Med | Findings | `FILL_AFTER_TERMINAL` and `QTY_MISMATCH` are lost once the order is 2 000 facts behind (0.2 s at sim rate) *(repro)* | RPL10 (Q3) |
| C3 | Med | `stats` | `stats` runs no detector and retires nothing: it reports findings `anomalies` does not, misses the ones it does, and ignores `--symbol` *(repro)* | RPL06 |
| C4 | Med | Index | Indexed and `--no-index` answers for one window differ (714 vs 720 episodes); the guide says identical *(real trail)* | RPL03 |
| C5 | Low | Window | `--to 2026-11-22` ends at that day's midnight; pm-audit-cli includes the day *(repro)* | RPL09 |
| C6 | Med | Re-run | A half-written last line crashes `rerun` and `queue` with `JSONDecodeError` *(repro)* | RPL08 |
| C7 | Med | Index | Two invocations at once: one dies with `StaleIndexError`; a build clears the live index in place *(repro)* | RPL01 |
| C8 | Med | Re-run | The final-book check on a running engine compares with a checkpoint up to 5 s old: false differences, exit 1 | RPL08 (Q4) |
| C9 | Med | Wording | `%g` prices: "BUY order … filled at 10000, through its 10000 limit" for 10 000.04 against 10 000.00 *(repro)* | RPL07 |
| C10 | Low | `queue` | An ambiguous or empty `--order` prefix silently answers for the first match, exit 0 *(repro)* | RPL08 |
| C11 | Low | Re-run | `rerun`/`queue` accept and ignore `--date`, `--from`, `--to`, `--last`, `--gateway`, `--kind`, `--tz` *(repro)* | RPL08 |
| C12 | Low | CLI | Empty window exits 0 in four reports (guide: 1); no subcommand exits 0 silently; `--top -1` and `--clock-skew-warn -5` accepted *(repro)* | RPL09 |
| C13 | Low | CLI | The `story` command printed under each finding drops `--log-file`, `--db` and `--date` | RPL09 |
| P1 | Low | Memory | Pass 1 keeps every cancel and amend request on an enveloped trail: +35 MB per part *(measured)* | RPL04 |
| P2 | Med | `story` | Every hop loads the whole `stated_links` table: 1.6 s and 72 MB per part, ×72 for a day *(measured)* | RPL05 |
| P3 | Low | Window | `--to` reads to the end of the trail: 4.8 s per later part *(measured)* | RPL09 |
| D1–D11 | — | Texts | See §5 | RPL10 |

---

## 3. Correctness findings

### H1. `--rebuild` deletes whatever `--db` names *(repro)* — High

`index.py:302-320` `open_index`, `index.py:332-354` `_schema_version_of` and
`_discard`; `cli.py:746-764` `ensure_index`.

```python
if db_path.exists() and _schema_version_of(db_path) != SCHEMA_VERSION:
    _discard(db_path)
```

`_schema_version_of` returns None for *any* file it cannot read a
`replay_meta` row from (`except sqlite3.DatabaseError: return None`), which
covers a SQLite file of another tool and a file that is not a database at
all. None is not `SCHEMA_VERSION`, so the file and its `-wal`/`-shm` siblings
are unlinked and a new index is written under the name. The docstring says
the rule is meant for "an index of the wrong shape".

Repro, with a 2 000-line real excerpt as the trail:

| `--db` | Command | Before | After |
|---|---|---|---|
| `precious.db` (SQLite, table `money`, one row) | `--rebuild episodes` | 8 KB, table `money` | 4.4 MB, tables `replay_meta`, `episodes`, … — `money` gone, exit 0 |
| `notes.txt` (text) | `index --rebuild` | 15 B | 4.4 MB episode index, exit 0 |
| `data/clearing.db` | `episodes` (no `--rebuild`) | — | `sqlite3.OperationalError: no such table: replay_meta` traceback |

The third row is `open_readonly` → `check_versions` → `read_meta` raising an
error `ensure_index` does not catch (`cli.py:752` catches only
`FileNotFoundError` and `StaleIndexError`). Neither path writes to the
file; the first two do. A mistyped `--db` next to the data files, or a
completion that picks `clearing.db` over `audit_replay.db`, destroys a ledger
with no backup prompt and exit 0.

**Fix.** Discard only a file that is an episode index: one with a
`replay_meta` table, whatever its version (a half-built one has the table).
Refuse anything else with exit 2, naming the file, on both the build and the
read path.

### H2. OCO and quote cancels are reported as unsolicited *(real trail)* — High

`detect.py:684-699` (`_close_order`).

`CANCEL_UNSOLICITED` fires when an order's episode holds an
`order.cancelled` with no `cancel_reason` and no `order.cancel` in the same
episode. The engine cancels an OCO's legs for an `order.oco_cancel` and a
quote's legs for a `quote.cancel` (or a replacing `quote.new`). Those
requests belong to the OCO and quote episodes, the legs' `order.cancelled`
carry no `cancel_reason`, and so every one is "unsolicited". Each carries a
recorded `cause=` naming the request:

```
[…14:58:00.709] [order.cancelled.AI077] [… cause=01M81W76VQF98QFP2KDF8JYZNB …]
    {"order_id": "b929a796…", "oco_group_id": "AI077-MWRHBTBO-612B", …}
[…14:58:02.205] [order.cancelled.MM01] [… cause=01M81W78AKRS6EHN7XB8483B0R …]
    cause: [quote.cancel] {"gateway_id": "MM01", "symbol": "SPOT"}
```

Part 70 of today's trail (374 707 lines, 21 minutes):

| Findings at warn or above | Count | Of which |
|---|---|---|
| `CANCEL_UNSOLICITED` | 2 560 | 1 682 OCO legs, 878 quote legs; all 2 560 carry a `causation_id` |
| `CLOCK_SKEW` | 135 | real: engine and receipt clocks > 0.1 s apart under load |
| `CANCEL_UNMATCHED` | 25 | all false, see C1 |
| `RESUME_WITHOUT_HALT` | 18 | the halts are in part 69 (a window edge) |

At 72 parts a day that is about 184 000 false warnings. The operator guide
says `tools/verify_audit_trail.sh` "is expected to come out green", and the
dispute procedure (`035-answering-a-dispute.md`, step 2) says a clean
`anomalies --severity warn` over the day proves the trail complete. The
verification dataset has no OCOs or quotes, so it passes; a simulation day
cannot.

**Fix.** A cancellation is solicited when the trail records what caused it:
a `causation_id` (the publisher stated the cause, whether or not it is in
the window), a `cancel_reason`, or a request in the episode. Report
`CANCEL_UNSOLICITED` only when none of the three is there.

### H3. A live, day-sized trail is out of reach *(measured)* — High

`cli.py:737-764` `ensure_index`, `index.py:241-259` `fingerprint`,
`index.py:711-718` `is_current`; `cli.py:899-923` `_from_log`,
`reader.py:43-75` `episodes_in_window`, `render_text.py:878-900` `narrate`.

Two properties combine.

*The index is rebuilt on every call while the exchange runs.* It covers the
whole live trail (every unarchived part plus `audit.log`, by design: "a cache
may not depend on the question"), and it is current only while the size and
mtime of every file match. `audit.log` changes every millisecond the exchange
runs, so `stream --last 15m`, `anomalies` and `story` on a running exchange
all start with a full rebuild:

| Trail | Index state | Wall time |
|---|---|---|
| 40 000 real lines | absent | 11.3 s |
| same | current | 4.1 s |
| same plus **one** appended line | stale → full rebuild | 10.9 s |
| one part, 374 707 lines | absent | 61.0 s, 6 140 lines/s, 702 MB index (2.7× the log), peak RSS 337 MB |
| today's live trail, ~27 M lines (72 × part) | always stale | ≈ 73 min and ≈ 50 GB in the data directory, per call |

AR-3.4 dropped the incremental build because "a rebuild is fast enough …
2.7 minutes for a million-line day … paid once per log rather than per
invocation". A simulation day is 27 times that, and on a live log the cost
is paid per invocation.

*The reports hold their whole window.* `stream`, `episodes`, `digest` and
`anomalies` (and the `--no-index` path of each) build a list of every
episode in the window with every fact's payload, then sort the events:

| One part (374 707 lines) | Wall | Peak RSS |
|---|---|---|
| `stream` from the index | 42.8 s | 2.46 GB |
| `anomalies --severity error` from the index | 29.8 s | 2.46 GB |
| `anomalies --severity error --no-index` | 41.2 s | 1.62 GB |
| hydrating every episode of the index (`episodes_in_window`) | 27.5 s | — |

That is about 6.5 KB a line. Today's trail would need 115–175 GB; the host
has 125 GB. `anomalies` needs only each episode's findings, `episodes` one
row, `digest` a ranking and its top N, but all of them keep everything.

The guide's "Reconstruction is a single streaming pass with bounded memory"
and its 0.01 ms `story` lookup are both true of pass 1 and of one keyed
read. Neither is what an operator meets on the trail the tool exists for.

**Fix.** Two decisions: what the index covers and when it is rebuilt (Q1),
and which reports must be bounded (Q2).

### C1. A late request or ack splits an order into new episodes *(real trail)* — Med

`episodes.py:409-452` `EpisodeAssembler.feed`, `episodes.py:557-565`
`_close`; `reader.py:78-97` `episode_by_anchor`; `detect.py:704-722`.

An order's episode closes when the state model says the order is terminal,
and `_close` removes it from `_open` at once, while it waits in `_closing` for
the reorder window to pass. A fact for the order that arrives in that window
finds no open episode and opens a new one. `_closing_outcome` then reads the
model's terminal status and closes the new episode on its first fact. A
cancel that loses the race to a fill becomes three episodes:

```
6610 order.fill.AI081     order 625d5f71… FILLED            → episode 4919 (closes)
6998 order.cancel          order 625d5f71…                   → episode 5179, outcome FILLED
6999 order.ack.AI081       accepted=false ORDER_NOT_FOUND    → episode 5180, outcome FILLED
```

Episode 5179 holds an `order.cancel` and no answer, so `CANCEL_UNMATCHED`
fires ("cancel requested … and nothing came back"), though the refusal is the
next line. Part 70: 25 such warnings, and 34 orders split into three
episodes. Reading them back:

- `story --order 625d5f717a718aa709a3295790d81753` (exact) takes the first
  row of three (`_hydrate(conn, exact)[0]`) and shows the fill only.
- `story --order 625d5f717a` (a prefix) asks for `LIMIT 2` rows, gets two
  rows of the same order, and says `no order matching '625d5f717a' in the
  index`, exit 1.

**Fix.** A fact whose `(kind, anchor)` has an episode still in `_closing`
joins that episode. Read back, a prefix is ambiguous only between two
*anchors*, and `story` seeds from every episode of the anchor.

### C2. A fill after an order's end goes unreported beyond the window *(repro)* — Med

`episodes.py:582-602` `_retire` → `state.py:311-320` `retire_order`;
`state.py:437-500`.

When an order's episode retires (2 000 facts or 5 s after it closed), the
state model forgets the order. A later fill finds no order, creates a fresh
`OrderState` with status `NEW` and no submission, and raises nothing.

| Trail: buy 10 FILLED, then … | Default window | `--reorder-window 5000` |
|---|---|---|
| a second fill of 5, 2 001 facts later | `FILL_WITHOUT_TRADE` only | `FILL_AFTER_TERMINAL`, `QTY_MISMATCH` ("fills total 15 but quantity - remaining_qty = 10"), `FILL_WITHOUT_TRADE` |

At the simulation's ~10 000 lines a second, 2 000 facts is 0.2 s. The
module docstring of `state.py` says the model "keeps everything, which is
what makes `FILL_AFTER_TERMINAL` and `ACK_DUPLICATE` work at any distance";
the pipeline always retires, so that is never the case. The same applies to
`ILLEGAL_STATUS_TRANSITION` for a late cancel or expiry. `stats` reports the
two findings on the same trail (C3), because it never retires anything.

**Fix.** Q3: keep a record of ended orders for the whole read, or say in the
guide and the docstrings that these findings reach as far as the reorder
window.

### C3. `stats` counts different findings from `anomalies` *(repro)* — Med

`cli.py:1121-1131` `_run_stats`, `stats.py:53-71` `collect`.

`stats` runs `reconstruct` only: no `Detector`, no assembler. So its
"Anomalies" section has none of `detect.py`'s 27 codes (`ACK_MISSING`,
`PRICE_THROUGH_LIMIT`, `TRADE_LEG_MISSING`, `CLOCK_SKEW`, …) and, since
nothing retires, it reports `FILL_AFTER_TERMINAL` at any distance where
`anomalies` does not (C2). On the C2 trail:

| Report | Findings |
|---|---|
| `anomalies` | `PRICE_THROUGH_LIMIT`, `FILL_WITHOUT_TRADE` |
| `stats` | `FILL_AFTER_TERMINAL`, `QTY_MISMATCH` |

`stats --symbol NOPE` prints the whole window's counts: the filters are
accepted and ignored. The dispute chapter pairs `anomalies` and `stats` as the
answer to "Is the trail complete?".

**Fix.** Count the findings from the same pipeline `anomalies` runs and apply
the same filters, or refuse the filters with exit 2.

### C4. Indexed and `--no-index` answers for one window differ *(real trail)* — Med

`cli.py:899-923` `_from_log` versus `reader.py:43-75`.

With the index, a window selects episodes that *opened* in it, reconstructed
from the whole trail. With `--no-index`, the window is applied to the lines
before reconstruction, so an order whose submission is before `--from` is
assembled from its tail. On the 2 000-line excerpt with `--from
2026-11-22T14:58:00.600`:

| | Episodes | Findings |
|---|---|---|
| index | 714 | 118 (21 `CANCEL_UNSOLICITED`, 97 `TERMINAL_MISSING`) |
| `--no-index` | 720 | 119 (22, 97) |

The guide: "Everything else works with or without it, and is required to
produce identical output either way". It holds only without a window.

**Fix.** Follows from Q1: if the reports stop using the index (Q1 a), the
two paths are one path; otherwise the guide must say what differs.

### C5. `--to YYYY-MM-DD` ends at that day's midnight *(repro)* — Low

`cli.py:598-609` `window_bounds` calls `parse_ts(args.to_ts)` without
`end_of_day=True`. The 2 000-line excerpt is all on 2026-11-22:

| Command | Result |
|---|---|
| `pm-audit-replay --no-index --to 2026-11-22 episodes` | empty table, exit 0 |
| `pm-audit-replay --no-index --from 2026-11-22 --to 2026-11-22 stream` | "nothing to narrate in this window" |
| `pm-audit-cli events --to 2026-11-22` | the day's lines |

The pm-audit review fixed this for pm-audit-cli (C12, `audit/cli.py:609`);
pm-audit-replay's module docstring says its window flags "deliberately
mirror pm-audit-cli's".

**Fix.** `--to` with a bare date is the end of that day, as in pm-audit-cli.

### C6. A half-written last line crashes `rerun` and `queue` *(repro)* — Med

`rerun.py:779`, `788`, `805`, `809`, `814`, `817`, `829` (`json.loads(ln.body)`);
`rawlines.py:92-97` (`int(...)` on the meta).

`rerun` and `queue` read the live trail to its current end. A line pm-audit
is writing is visible half-written. Cut inside its JSON body:

```
rerun:              JSONDecodeError: Unterminated string starting at: line 1 column 2
queue --order …:    JSONDecodeError: Unterminated string starting at: line 1 column 2
--no-index stream:  exit 0 (parse_line drops the line)
```

A meta section that does not parse (`seq=abc`) raises `ValueError` from
`rawlines.lines` the same way. Exit 3 ("the trail cannot be re-run") exists
for exactly this class of input.

**Fix.** The last line of the last file without a terminating newline is a
write in progress and is not read. Any other line whose body or meta does not
parse raises `Unavailable` naming its time and topic (exit 3).

### C7. Two invocations at once crash, and a build clears the index in place *(repro)* — Med

`index.py:663-708` `build` / `clear`; `cli.py:746-764`.

A rebuild empties every table of the live file (`clear`, committed) and then
fills it. Meanwhile another invocation opens it, finds no `schema_version`
(`StaleIndexError`), and starts its own rebuild, which clears the first
build's rows. Repro on a 40 000-line trail: `index --rebuild` in the
background, `anomalies` one second later. The second finished; the first
died at its final `open_readonly`:

```
edumatcher.audit.replay.index.StaleIndexError: Episode index declares no schema_version; rebuild it with --rebuild.
```

A build interrupted by Ctrl-C leaves an empty index (the old one is already
cleared), so the next call pays the full build again. `anomalies` has no
primary key, so two builds that interleave their inserts can store a finding
twice.

**Fix.** Build into a temporary file beside the index and move it into place
with `os.replace` when complete. A reader sees the old index or the new one,
never a half one, and an interrupted build leaves the old index intact.

### C8. The final-book check on a running engine compares with an older checkpoint — Med

`rerun.py:650-671` `final_book`; `engine/main.py:471-475`
(`_PERSIST_INTERVAL_SEC = 5.0`), `engine/main.py:7710-7745`.

`final_book` compares the re-run's resting book after the *last line read*
with `gtc_orders.json`. While the engine runs, that file is its last
periodic checkpoint, up to 5 s (or one halt change) older than the trail.
Every order placed, filled or cancelled in between is a difference
(`E4`), and `rerun` exits 1, "a difference". After a `kill -9` the file is
the last checkpoint too, and the restart path already knows that (it compares
with the `STARTUP` checkpoint). The dispute procedure's step 3 runs `rerun`
during the day. The re-run also drops resting `ATO`/`ATC` orders from nothing:
the engine persists only `GTC` and `DAY` (`engine/main.py:7663-7668`), while
`final_book` compares every resting order.

**Fix.** Q4.

### C9. `%g` prices in findings and sentences *(repro)* — Med

`detect.py:428-429`, `535-536`, `627`, `859-861`, `939`; `state.py:236`;
`render_text.py:545`, `554`; `views.py:430`; `facts.py:119-121`.

`f"{price:g}"` rounds to six significant digits. A buy limit of 10 000.00
filled at 10 000.04:

```
ERROR  09:00:00.005  PRICE_THROUGH_LIMIT    order aaaaaa…
       BUY order aaaa… filled at 10000, through its 10000 limit
```

An error that contradicts itself. The same rounding reaches
`PRICE_OUTSIDE_CORRIDOR`, `DROP_COPY_DISAGREE`, `PRINT_PRICE_DISAGREE`,
`LEG_PRICE_DISAGREE`, the halt corridor in a rejection's explanation
(`describe_halt`), the `corridor`/`triggered at` clauses, `digest`'s `vwap`,
and `Price.render` for a display price with no scale (1 234.567 prints as
1234.57). The narrator's own `_money` already formats with the symbol's tick
precision when it has one; the findings never do.

**Fix.** One formatter: the symbol's tick precision when known, otherwise the
float's shortest exact form (`repr`).

### C10. `queue --order` takes the first match of a prefix *(repro)* — Low

`queue.py:216-221`: `if not ident.startswith(self.target): return False`, and
the first `order.new` that matches is followed. `queue --order ""` on a
recorded trail answered for `eb56a12c` (the first order), exit 0; any prefix
shared by two orders does the same. `story --order` refuses an ambiguous
prefix, and the help text promises "the order id, or a prefix of it".

**Fix.** Collect the matching ids over the trail; two or more is exit 2 naming
them, none is exit 1.

### C11. `rerun` and `queue` accept options they ignore *(repro)* — Low

`cli.py:1170-1233`. Both take only the directory of `--log-file` and read
every file in it (`rerun(Path(args.log_file).expanduser().parent)`). They
accept and ignore `--date`, `--from`, `--to`, `--last`, `--gateway`, `--kind`,
`--no-index`, `--rebuild` and the detection options; `rerun` also ignores
`--symbol`, `queue` ignores `--tz` (its clock is UTC). `--date 1999-01-01
rerun` re-ran today's trail, exit 0. A `--log-file` naming one archive re-runs
the whole directory. `index` already refuses a window for the same reason.

**Fix.** Refuse the options each command ignores (exit 2), and refuse a
`--log-file` that names an archive or a day part.

### C12. Exit codes and values *(repro)* — Low

- `cli.py:990-1004`, `1121-1131`: `episodes`, `digest`, `anomalies` and
  `stats` exit 0 on an empty window (an empty table, "No findings across 0
  episode(s).", "No facts in window."). The guide's exit table: "1 Nothing to
  narrate". `stream` and `story` exit 1.
- `cli.py:1265`, `406-415`: no subcommand prints nothing and exits 0. The
  `required=False` reason ("while the renderers are still being built") is
  out of date.
- `cli.py:483-489`: `digest --top -1` shows every episode but the last
  ("... 1 more episode(s)"); `--top 0` shows none.
- `cli.py:369-378`: `--clock-skew-warn -5` turns every stamped message into a
  `CLOCK_SKEW` warning (1 171 on the 2 000-line excerpt, none at the
  default); `nan` disables the check silently.

**Fix.** Exit 1 when the window holds no episode (no fact, for `stats`);
require a subcommand; `--top` ≥ 1; `--clock-skew-warn` a finite number ≥ 0.

### C13. The suggested `story` command reads another trail — Low

`views.py:218-228` `story_command` prints `pm-audit-replay story --order X -v
--explain`. After `--log-file /tmp/run/audit.log`, `--db …` or `--date
2026-11-21`, the suggestion runs against the default trail and index (and
with `--date` gone, against today): the order is not found there, or the index
for the default trail is built first. The guide's advice is "paste the
suggestion".

**Fix.** Carry the source options the run was given (`--log-file`, `--db`,
`--date`) into the suggestion.

---

## 4. Performance findings

H3 is the one that matters at today's sizes. The three below are smaller.

### P1. Pass 1 keeps every request on an enveloped trail *(measured)* — Low

`links.py:732-743` (`_register` appends every `order.cancel`, `order.amend`
and structure cancel), `links.py:436-482` (`_request_cause` pops them, but is
reached only from `_fallback`, i.e. for facts *without* an envelope),
`links.py:775-818` (`forget` leaves the lists alone: "resolution already pops
those"); `state.py:433-435` (`_requests` is discarded only by a refusing ack).

On a current trail every fact has an envelope, so nothing is ever popped.
Four consecutive parts (1.54 M lines):

| After part | `_cancel_requests` | `_amend_requests` | `StateModel._requests` | structure cancels | RSS |
|---|---|---|---|---|---|
| 1 | 15 583 | 2 920 | 18 493 | 1 895 | 118 MB |
| 2 | 31 043 | 5 624 | 36 634 | 3 876 | 156 MB |
| 3 | 46 579 | 8 370 | 54 909 | 5 743 | 183 MB |
| 4 | — | — | — | — | 202 MB |

About 35 MB a part, 2.5 GB over a day, against the docstrings' "memory flat
on a log of any length" (`episodes.py:587`, `index.py`, the guide).

**Fix.** `forget` drops the request entries the retiring fact registered, and
the state model's request set is cleared with them.

### P2. `story` loads every link of the index on every hop *(measured)* — Med

`reader.py:216-223` `_hydrate` calls `reader.py:358-375` `_stated_links`,
which reads the whole `stated_links` table ("a story is a handful of episodes
and a window is bounded, so one scan beats a query per line"). `walk` hydrates
once per hop (`reader.py:196-207`). One part's index:

| Step | Time | Memory |
|---|---|---|
| `_stated_links` | 1.58 s | 72 MB, 148 411 keys |
| `story --order b929a796` (depth 2) end to end | 2.50 s | 121 MB RSS |
| CLI start and a miss, for comparison | 0.73 s | 72 MB |

A day's index holds 72 times that: about 2 minutes and 5 GB per hop. The
design's target is 100 ms.

**Fix.** Read the links of the refs being hydrated only, over an index on
`stated_links(to_ref)` (a schema change: bump `SCHEMA_VERSION`; the existing
rule discards the old index).

### P3. `--to` reads the trail to its end *(measured)* — Low

`audit/query.py:494-502`: with `to_dt` set, every later line is parsed and
dropped. 4.76 s per 256 MB part after the bound, against 0.20 s for a part
before `--from` (skipped by the stamp floor). `--from 08:00 --to 09:00` on
today's trail parses about 65 parts it cannot use: about 5 minutes.
pm-audit-cli shares the reader (§9).

**Fix.** On the replay path, stop reading once a stamp passes `to_dt` by more
than the reorder window's seconds.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `pm_help/registry.py:1477-1525` | Says "Under construction … no subcommand is registered yet"; `--date` "Shorthand for a whole UTC day" (it is the session-timezone day's files); detail default `-v` (it is level 1, no flag); formats lack `csv`; `--force-color`, `--strict`, `--clock-skew-warn` missing; the synopsis names no subcommand |
| D2 | `cli.py:11-19`, `406-415` | "Two subcommands so far" (there are nine); "with none, the command validates its options and exits, as it did through phase 1"; `required=False` "while the renderers are still being built" |
| D3 | `anomalies.py` (`FILL_WITHOUT_TRADE`) | "The trade is published before its fills, so by the time a fill is read its trade has been read too". The engine publishes the fills first (`engine/main.py:3856-3862`), as `detect.py:446-450` says |
| D4 | `links.py:216-221`, `503-529` | The fill→trade `matched_with` rule ("a fill to its trade") looks up a trade that has not been read yet: zero such links in a real part's 179 347 (all 24 981 `matched_with` come from the trade side). Dead on current trails; the docstring describes it as working |
| D5 | `state.py:14-19`, `311-320` | "Left alone it keeps everything, which is what makes `FILL_AFTER_TERMINAL` and `ACK_DUPLICATE` work at any distance": the pipeline always retires (C2) |
| D6 | `episodes.py:585-588`, `index.py:15-23`, guide "bounded memory" | "makes the memory flat on a log of any length": pass 1 grows (P1) and the reports hold the window (H3). AR-3.4's "2.7 minutes for a million-line day" is the reason given for no incremental build; a sim day is 27 M lines |
| D7 | guide `030-audit-replay.md` "The episode index" | "required to produce identical output either way" (C4); size "roughly 4.4× the log" (2.7× on a real part); "Built automatically when … stale" without saying a growing `audit.log` is always stale |
| D8 | guide `030-audit-replay.md` "Exit codes" | "1 Nothing to narrate": four reports exit 0 (C12) |
| D9 | guide `030-audit-replay.md` "What a clean run does not prove" / "A clean run is a claim" | Says the verification script comes out green; true for its dataset, false for any trail with OCOs or quotes until WP-RPL02 |
| D10 | `035-answering-a-dispute.md` step 5 | "Quote with `--anonymise` when the answer goes to a participant": only `queue` has `--anonymise`; `story` and `stream` name every counterparty |
| D11 | `035-answering-a-dispute.md` step 2, reference manual exit codes | Step 2's clean-run claim (H2); the procedure gives no idea of the cost of `anomalies` over a day (H3) |

---

## 6. Verified as correct

- **Units.** Every tick price is converted with its own message's
  `tick_decimals`; a missing scale is printed in ticks and labelled
  (`TICK_SCALE_UNKNOWN`), never guessed (`facts.py:238-301`).
- **Ordering.** `eseq` within a publisher run is the canonical order; a late
  fact is tagged and does not lower `SEQ_GAP`'s high-water mark
  (`ordering.py:258-315`); `eseq` gaps are checked in receipt order before
  the reorder window (`ordering.py:210-255`).
- **Envelope semantics.** A declared origin (envelope, no `causation_id`) is
  never given an inferred cause (`links.py:338-342`); a message is never its
  own cause (`links.py:259-274`).
- **`FILL_BEFORE_ACK` with deferred acks.** For a FOK (and IOC/market with
  matching off) the engine defers the ack until the book has decided, but
  still sends it before `_publish_dispatch` publishes the fills
  (`engine/main.py:2453-2475`), so no false inversion. Part 70: none.
- **Request refusals.** A refused cancel or amend does not reject the order
  (X13; `state.py:420-431`).
- **Re-run gates and throughput.** An `eseq` jump, a recorder restart while
  the engine ran, a first start that restored orders and a missing config are
  each `Unavailable` (exit 3, `rerun.py:720-753`, `556-566`). Part 1 of
  today's trail (487 448 lines, 43 554 commands) re-ran in 11.6 s at 104 MB;
  a day is about 11 minutes, which matches the guide's "minutes".
- **The `--no-index` window floor.** Lines before `--from` are skipped
  unparsed: 0.20 s per part (`query.py:420-476`).
- **Text and NDJSON agree.** Both come from one `Renderer` at one `Options`
  (`render_json.py:84-116`); colour and `--tz` never reach JSON.
- **Id abbreviation.** Lengthened until every printed prefix is unique, per
  kind in the tabular views (`render_text.py:131-157`, `views.py:127-147`).

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | What does the index cover, and when is it rebuilt on a live trail? (a) The reports (`stream`, `episodes`, `digest`, `anomalies`, `stats`) always read the log within their window and never build an index; only `story` uses it. `story` builds it when absent or when rules or detection changed, or on `--rebuild`; a trail that has changed since is answered from the index with a note on stderr naming `covered_to` and `--rebuild`. (b) Keep the automatic rebuild but one index per trading day, so only today's rebuilds. (c) Revisit AR-3.4 and build incrementally. | **(a).** It removes the rebuild from every report (a windowed `--last 15m` then reads 15 minutes, not a day), makes C4 disappear because there is one path, and keeps the index for the one command that needs random access. (b) still rebuilds today's 50 GB on every call while the exchange runs. (c) needs the state model, the resolver and the open episodes restored across a chunk boundary, which AR-3.4 measured as a full re-read in practice. |
| Q2 | Which reports must run in bounded memory? (a) `anomalies`, `episodes`, `digest` and `stats` become aggregations over retired episodes (each keeps findings, one row, or a top-N heap) and drop the payloads; `stream`, `story`, `json` and `markdown` keep holding their window, and the guide says what that costs (≈ 6.5 KB a line) and to narrow the window. (b) Also make `stream` narrate as facts leave the reorder window. | **(a).** It covers the whole-day questions (is anything wrong, what kind of day) with flat memory. Whole-day prose is not a question anyone reads to the end; (b) needs the renderer's cross-episode lookups (counterparty, owner) rebuilt for a streaming order, for no reader. |
| Q3 | `FILL_AFTER_TERMINAL`, `QTY_MISMATCH` and `ILLEGAL_STATUS_TRANSITION` beyond the reorder window: (a) keep `order_id → final status` for every ended order for the whole read; (b) document that these findings reach as far as the reorder window, and that `--reorder-window` widens it. | **(b).** (a) costs about 3 M orders × ~150 B ≈ 450 MB on a sim day, against the bounded memory Q2 buys. A late fill from a defect normally arrives in the same input (milliseconds); the knob for a longer reach exists. |
| Q4 | The final-book check: (a) compare only when the trail's last run ends with the engine's shutdown checkpoint (`system.book_checkpoint` reason `EOD`), otherwise print "final book: not checked (the engine had not shut down when the trail ends)"; and compare only `GTC`/`DAY` orders, the ones the engine persists. (b) Always compare and document that a running engine shows differences. | **(a).** A difference that is only the checkpoint interval is a false exit 1 in the dispute procedure. The trail says when it ended cleanly; an abrupt stop is already compared at the next start. |

---

## 8. Work packages

### WP-RPL01 — `--db` never destroys a file that is not an index, and a build never leaves a half index behind (H1, C7)

**Tests first** (`tests/test_audit_replay_index.py`, `tests/test_audit_replay_cli.py`):

1. `--db other.db --rebuild episodes`, where `other.db` is a SQLite file with
   a table `money`: exit 2, stderr names the file, `money` still holds its
   row. (Fails today.)
2. The same with a text file as `--db` and `index --rebuild`: exit 2, the
   file's bytes unchanged. (Fails today.)
3. `--db other.db episodes` (no `--rebuild`): exit 2, no traceback.
   (Fails today.)
4. An index of an older `SCHEMA_VERSION` is still discarded and rebuilt,
   unchanged.
5. A build that raises halfway (patch the writer to raise after the first
   batch) leaves the previous index readable with its old row counts.
   (Fails today.)
6. A reader holding the index open while a rebuild completes still reads the
   old rows; a new reader reads the new ones. (Fails today: the rebuild
   clears in place.)

**Change.** `open_index` discards only a file with a `replay_meta` table;
anything else raises a new `NotAnIndexError` that `ensure_index` and
`_run_index` turn into exit 2. `build` writes to `<db>.building-<pid>` and
`os.replace`s it into place after `finish`; `clear` goes. Readers already
open read-only.

**Exit criteria.** Tests 1–6 pass; `tests/test_audit_replay_*.py` green.

**Outcome (2026-11-22).** `index._require_index` asks the file's schema for a
`replay_meta` table (any version); a file without one, or one that is not a
database, raises the new `NotAnIndexError`, which `main` turns into exit 2
naming the file, on the read path (`open_readonly`) and the build path alike.
`build` refuses before reading the log, writes `<db>.building-<pid>` with
`journal_mode=OFF`/`synchronous=OFF` (the scratch file is nobody's until it is
moved), and `os.replace`s it into place; any exception, Ctrl-C included,
removes the scratch file and leaves the old index. `clear`, the `rebuild=`
upsert mode and the unused `writing()` went. The finished index is in
rollback-journal mode, no longer WAL: a `-wal`/`-shm` pair belongs to the file
*name* and would outlive the replace (stale siblings of an older WAL index are
removed before it). Read-only URIs are now percent-encoded
(`_readonly_uri`). Tests: `TestOnlyAnIndexIsEverReplaced`,
`TestABuildIsAtomic` (index) and `TestDbNamesOnlyAnIndex` (CLI) — all 8 failed
first (`DID NOT RAISE`, `OperationalError: no such table`, exit 0, `8 == 7`
episodes after the failed build); `test_the_index_is_in_wal_mode` became
`test_the_finished_index_is_one_file`. Full suite: 15 263 passed, 1 skipped.

### WP-RPL02 — A healthy simulation trail reads clean (H2, C1)

**Tests first** (`tests/test_audit_replay_episodes.py`,
`tests/test_audit_replay_anomalies.py`; extend `record` with an
`order.oco_cancel` and a `quote.cancel`):

1. An OCO cancelled by `order.oco_cancel`: no `CANCEL_UNSOLICITED` on its
   legs. (Fails today.)
2. A quote cancelled by `quote.cancel`: none on its legs. (Fails today.)
3. An `order.cancelled` with neither `causation_id`, `cancel_reason` nor a
   request in its episode: `CANCEL_UNSOLICITED`, unchanged.
4. An order filled, then `order.cancel` and its `ORDER_NOT_FOUND` refusal
   within the window: one episode, outcome `FILLED`, no `CANCEL_UNMATCHED`.
   (Fails today.)
5. `story --order <full id>` and `story --order <prefix>` on that order both
   narrate the fill, the cancel and the refusal. (Fails today.)
6. A cancel with no answer at all still raises `CANCEL_UNMATCHED`, unchanged.
7. Part-scale check (manual, recorded in the outcome): `anomalies --severity
   warn --no-index` on one part of a simulation trail leaves only
   `CLOCK_SKEW` and window-edge findings.

**Change.** `detect._close_order`: solicited when the cancel fact has a
`causation_id`. `EpisodeAssembler.feed`: look in `_closing` for the anchor
before opening a new episode. `reader.episode_by_anchor`: ambiguity by
`DISTINCT anchor_key`; `_run_story` seeds `walk` from every episode of the
anchor.

**Exit criteria.** Tests 1–6 pass; check 7 recorded; goldens updated only
where an episode was previously split (each diff explained in the outcome).

**Outcome (2026-11-22).** `detect._close_order`: a cancellation is solicited
when it carries a `causation_id`, a `cancel_reason`, or has a request in its
episode. `EpisodeAssembler` keeps the order episodes waiting in `_closing` by
order id (`_closing_orders`, dropped at retirement and at `drain`); a later
fact for that order joins the episode as a `progress` event instead of opening
a new one. Orders only: a second halt on a symbol is still a second episode.
`reader.episode_by_anchor` became `episodes_by_anchor`: every episode of the
anchor, ambiguity judged between `DISTINCT anchor_key`s, and the prefix looked
up as a range on `idx_ep_kind_key` (`LIKE` could not use the index and read `_`
as a wildcard); `walk` takes several seeds and `_run_story` seeds from all of
them. `record()` in `tests/test_sim_forensics_rerun.py` gained `cancels=True`:
the recorder then writes `cause=` on the engine's output, and the run cancels
the OCO (`order.oco_cancel`) and the quote (`quote.cancel`) and asks to cancel
the buy it has already filled (refused `ORDER_NOT_FOUND`). The new
`tests/test_audit_replay_recorded.py` covers tests 1–6; 1, 2, 4 and 5 (both the
full id and a prefix) failed first as described, 3 failed because the other
legs fired too (3 findings, not 1), 6 passed. Goldens: no diff (none of the
fixtures has a late fact). Check 7 on part 70 of the live sim trail (374 707
lines), `anomalies --severity warn --no-index`: 135 `CLOCK_SKEW` and 18
`RESUME_WITHOUT_HALT` (window edge), nothing else (before: 2 560
`CANCEL_UNSOLICITED`, 25 `CANCEL_UNMATCHED`); 41.6 s, 1.62 GB peak RSS.
`StampedRecorder._line` (`test_sim_forensics_breakers.py`) takes the new
`cause` parameter. The full suite ran once for WP-RPL02 and WP-RPL07 together
(started RPL07 while the part-scale check ran): 15 275 passed, 1 skipped.

### WP-RPL03 — A live, day-sized trail is answered without rebuilding on every call (H3 index part, C4; after Q1)

Written for Q1 (a).

**Tests first** (`tests/test_audit_replay_cli.py`):

1. `episodes`, `digest`, `anomalies`, `stats`, `stream` with a window create
   no index file. (Fails today.)
2. `story` after appending one line to `audit.log`: no rebuild (the index's
   `built_at` is unchanged), the answer is printed, and stderr says the
   index covers to `covered_to` and names `--rebuild`. (Fails today.)
3. `story` with no index, or one built under another `RULES_VERSION` or
   detection key: builds, unchanged.
4. `--rebuild story`: rebuilds, unchanged.
5. A report with and without `--no-index` gives the same output for a window
   that cuts an order in half (the C4 trail). (Fails today.)

**Change.** `_run_stream` and `_run_view` call `_from_log` always;
`--no-index` and `--rebuild` become options of `story` and `index` only
(refused elsewhere, exit 2). `ensure_index` rebuilds on absence, rules or
detection, and otherwise returns the index with a `stale` flag the caller
reports.

**Exit criteria.** Tests 1–5 pass; `stream --last 15m` on a 375 000-line
trail without an index finishes in under 5 s (a guess, from 0.2 s per
skipped part plus 15 minutes of lines at ~10 000 lines/s; to be measured).

**Outcome (2026-11-22).** Written for Q1 (a), the recommendation (taken
without an explicit answer; see the hand-over). The reports (`stream`,
`episodes`, `digest`, `anomalies`, `stats`) always reconstruct their window
off the log and never open or build the index. `--no-index` is **removed**:
under (a) it has no remaining use (the reports never use the index, `story`
and `index` need it), and a flag that changes nothing is the kind of option
C11 refuses. `--rebuild` is refused (exit 2) outside `story` and `index`;
`--db` is still accepted by the reports, because it is carried into the
`story` commands they suggest. `ensure_index(args, files, refresh=...)`
builds when the index is absent, of another schema or rules (as before), of
other detection settings, or on `--rebuild`; when only the trail changed,
`index` (`refresh=True`) rebuilds, and `story` reads the index as it stands
provided the trail has only grown (`_only_grown`: every file the index read,
bar the live `--log-file`, is still in the trail; another `--date` or an
archived day rebuilds), printing on stderr "the index (…) covers the trail to
<covered_to>; the trail has grown since. Add --rebuild to include the rest."
`index --date D` is now accepted (a day is its files, which `story --date D`
indexes too); `--from`/`--to`/`--last` are still refused. Follow-up found
while measuring the exit criterion: `--last 15m` on the live trail took
17.9 s, 14 s of it skipping 72 closed parts line by line before the window;
`_window` now leaves out a closed plain part whose last line (read from the
file's end, `_ends_before`) is stamped before `--from`. Tests
(`TestOnlyStoryUsesTheIndex`, `test_a_part_that_ends_before_the_window_is_not_read`):
all failed first except the three "unchanged" ones (story builds when absent,
for other detection settings, on `--rebuild`); the C4 test first passed for
the wrong reason (its window cut no order) and was moved between order
4f2c9a's acceptance and its fill. Tests that compared an indexed report with
the log path now compare the log path with episodes read back through
`reader` (what `story` narrates); three tests of `--no-index` itself were
removed; `test_audit_day_scope` builds its day index with `index --date`;
`tools/verify_audit_trail.sh` drops `--no-index`. Measured on the live sim
trail (72 parts + `audit.log`, the sim's market closed at the time so the
window held 27 331 book-snapshot episodes rather than trading):
`--last 15m stream` 3.8 s and 250 MB, `episodes` 4.0 s, no index file
written. A trading 15 minutes is about 270 000 lines, so expect about 45 s at
pass 1's ~6 000 lines/s; the 5 s guess holds only for a quiet window.
`make completion` regenerated. Full suite: 15 328 passed, 1 skipped.

### WP-RPL04 — The reports hold one episode at a time, and pass 1 forgets what has been answered (H3 memory part, P1; after Q2)

Written for Q2 (a).

**Tests first** (`tests/test_audit_replay_views.py`,
`tests/test_audit_replay_links.py`, `tests/test_audit_replay_state.py`):

1. `anomalies`, `episodes`, `digest --top 5` and `stats` on a generated trail
   of 200 000 lines: peak traced memory (`tracemalloc`) under a bound that does
   not grow when the trail is doubled. (Fails today.)
2. Their output is identical to today's on the replay fixtures, unchanged.
3. After 10 000 cancelled orders have retired, `_cancel_requests`,
   `_amend_requests`, `_structure_cancels` and `StateModel._requests` are
   empty. (Fails today.)
4. A cancel request still links to its effect on an envelope-less trail,
   unchanged.

**Change.** The four reports consume `detected(assemble(...))` as a stream
and keep only findings, rows or a top-N heap. `LinkResolver.forget` removes
the request entries a retiring fact registered; `StateModel` drops a request
id with them.

**Exit criteria.** Tests 1–4 pass; `anomalies --no-index` on one 375 000-line
part measured below 400 MB peak RSS (today 1.62 GB; the bound is a guess from
pass 1's 337 MB).

**Outcome (2026-11-22).** Written for Q2 (a), the recommendation (taken
without an explicit answer; see the hand-over). `views.Row` is what the
tabular views read of an episode without its facts (id, kind, anchor,
outcome, opening time and key, span, actor, symbol, findings, and the derived
figures when asked for); `views.row()` takes one as the episode retires, and
every view accepts episodes or rows. The CLI streams the window
(`_stream_from_log` through `_Counted`, which counts what passed for the
tallies and "nothing to narrate"): `anomalies` keeps only the rows with a
finding at `--severity` or worse, `digest --top N` keeps `heapq.nsmallest(N)`
rows by the new `views.digest_key`, `episodes` and `digest` without `--top`
keep one row per episode (no derived figures for `episodes`), and `stats`
already counted on the way (WP-RPL06). `stream` and `story` still hold their
window (Q2 a). Ids are abbreviated among the episodes *printed* (`anomalies`,
`digest`), which is what the abbreviation exists for. `LinkResolver.forget`
now removes the request a retiring `order.cancel`, `order.amend` or structure
cancel registered (`_unregister`, which also drops an emptied key), and the
assembler calls the new `StateModel.forget_request` for every retiring fact.
Tests (`tests/test_audit_replay_memory.py`): the flat-memory tests for
`anomalies` and `digest --top 5` and the per-row bound for `episodes` failed
first (traced peak 14.3 → 27.8 MB and 25.0 → 49.3 MB for 1 500 → 3 000
orders; 9.5 KB per episode), the request test held 2 500 entries; `stats`
passed before and after. The first version of the generated trail was itself
wrong (one global `seq=` and every line its own `chain=`, so `SEQ_GAP` and
`CHAIN_BROKEN` errors on every line) and was corrected to a trail that reads
"No findings"; the 31 tests that compare each bounded report with the views
fed the whole window pass before and after. The per-row bound is 3 000 bytes:
measured about 2.4 KB per `episodes` row on the generated trail (row, cells
and table text), against my guess of 1.5 KB. Measured on part 70 (374 707
lines), niced and pinned beside the running sim: `anomalies --severity warn`
33.0 s and 323 MB peak RSS (before: 41.2 s, 1.62 GB), `digest --top 5` 35.7 s
and 323 MB, `stats` 32.9 s and 323 MB, `episodes` 37.9 s and 491 MB for
199 206 rows. Full suite: 15 363 passed, 1 skipped (10 warnings, all one
`SyntaxWarning` from an escape in the new `views` docstring, fixed after the
run; flake8 W605 caught it too).

### WP-RPL05 — `story` reads only the links of the episodes it shows (P2)

**Tests first** (`tests/test_audit_replay_index.py`):

1. The SQL `story --order X` executes (captured with
   `set_trace_callback`) contains no `SCAN stated_links` in its plans.
   (Fails today.)
2. `story` output on the fixtures is unchanged, including `--explain`.
3. `SCHEMA_VERSION` 4 index is discarded and rebuilt, unchanged rule.

**Change.** `_stated_links(conn, refs)` with `WHERE to_ref IN (...)` in
batches; index `idx_sl_to ON stated_links(to_ref)`; `SCHEMA_VERSION = 5`.

**Exit criteria.** Tests 1–3 pass; `story` on the one-part index under 1 s
end to end (today 2.50 s; the CLI's own start is 0.73 s).

**Outcome (2026-11-22).** `reader._stated_links(conn, refs)` reads only the
links pointing at the refs of the episodes being hydrated, in batches of
`IN (...)` over the new `idx_sl_to ON stated_links(to_ref)`; `_batches` is
generic over the id type. `SCHEMA_VERSION = 5`, so an older index is refused
and rebuilt by the existing rule (test 3 is the existing
`test_a_stale_schema_version_forces_a_rebuild`). Test 1
(`TestStoryReadsOnlyItsOwnLinks`, captured with `set_trace_callback` and
`EXPLAIN QUERY PLAN`) failed first on `SELECT * FROM stated_links` → `SCAN
stated_links`; the story goldens (test 2) are unchanged. Measured on part 70
of the live sim trail (374 707 lines): `story --order b929a796` 0.80 s and
72 MB RSS end to end (before: 2.50 s, 121 MB), a miss 0.83 s, so the cost is
now the CLI's start. The same index built in 54.2 s at 337 MB peak RSS into
one 708 MB file (before WP-RPL01: 61.0 s, WAL). `make dbdocs` regenerated.
Full suite: 15 283 passed, 1 skipped.

### WP-RPL06 — `stats` counts the same findings as `anomalies` (C3)

**Tests first** (`tests/test_audit_replay_stats.py`):

1. On the C2/C3 trail, the codes and counts in `stats`' "Anomalies" section
   equal those `anomalies --format json` lists. (Fails today.)
2. `stats --symbol S` counts only episodes on `S`, as `anomalies --symbol S`
   does. (Fails today.)
3. Envelope coverage and link confidence are unchanged on the fixtures.

**Change.** `_run_stats` runs the `_from_log` pipeline (detector and
assembler) and counts facts, links and findings from the filtered episodes.

**Exit criteria.** Tests 1–3 pass.

**Outcome (2026-11-22).** `stats.collect_episodes` counts every fact of every
episode and the findings of its facts and of the episode itself, consuming an
iterator. The CLI's `--no-index` pipeline became `_stream_from_log` (an
iterator of filtered episodes; `_from_log` lists it) with the filters as one
predicate, `_wanted`, so `stats` reads exactly what `anomalies --no-index`
reads, one episode at a time. `collect(steps)` stays as the step-level
primitive the unit tests use. Tests: `TestStatsCountsWhatAnomaliesReports`
(fixtures 03 and 04 failed first, e.g. stats lacked `CLOCK_SKEW`,
`TRADE_LEG_MISSING`, `ACK_MISSING`, `FILL_BEFORE_ACK`; `--symbol NOPE` printed
the whole window's 10 facts; the fact-count part of test 3 passed before and
after). Full suite: 15 282 passed, 1 skipped.

### WP-RPL07 — Every price in a finding or a sentence is printed exactly (C9)

**Tests first** (`tests/test_audit_replay_anomalies.py`,
`tests/test_audit_replay_render.py`):

1. Buy limit 10 000.00 filled at 10 000.04: the detail reads "filled at
   10000.04, through its 10000.00 limit". (Fails today.)
2. A corridor 12 345.60–12 999.99 prints as such in the halt clause and in
   `PRICE_OUTSIDE_CORRIDOR`. (Fails today.)
3. `digest` VWAP 12 345.678 is not rounded to 12 345.7. (Fails today.)
4. 74.80 still prints as 74.80 where the scale is known, unchanged.

**Change.** One helper used by `detect`, `state.describe_halt`,
`render_text` and `views`: tick precision when the symbol's scale is known,
`repr(float)` otherwise.

**Exit criteria.** Tests 1–4 pass; no `:g` left on a price in `replay/`
(grep).

**Outcome (2026-11-22).** `facts.price_text(value, scale)`: the scale's
decimals when known, otherwise the float's shortest exact form with no `.0`
on a whole number. `Price.render` uses it (also for an unresolved price in
ticks). The detector learns each symbol's `tick_decimals` from the first
message that declares them (`Detector._scales`, bounded by symbols) and
prints every price in `PRICE_THROUGH_LIMIT`, `PRICE_OUTSIDE_CORRIDOR`,
`DROP_COPY_DISAGREE`, `PRINT_PRICE_DISAGREE` and `LEG_PRICE_DISAGREE` through
`Detector._money`. `SymbolState` keeps the corridor's `tick_decimals` for
`describe_halt`; the narrator's corridor and trigger clauses use each
`Price`'s own `render()`; the digest's VWAP and the book-level fallback use
`price_text`. Tests: `TestEveryPriceIsPrintedExactly` (5, all failed first:
"filled at 10000, through its 10000 limit", "12345.6-13000", "1234.57"; the
VWAP test first failed on its own fixture and was fixed before the code). Two
existing assertions encoded the rounded text ("through its 75 limit", "70-80
corridor") and now read "75.00" and "70.00-80.00". `grep ':g}'` in `replay/`
leaves only seconds and the depth-imbalance ratio. Full suite: see WP-RPL02.

### WP-RPL08 — `rerun` and `queue` answer a live trail honestly and refuse what they ignore (C6, C8, C10, C11; after Q4)

**Tests first** (`tests/test_audit_replay_rerun_cli.py`,
`tests/test_audit_replay_queue.py`):

1. A recorded trail plus half a line (cut inside the JSON): `rerun` exit 0
   with the same counts as the whole trail. (Fails today: traceback.)
2. A malformed line in the middle (`seq=abc`, or a truncated body followed by
   more lines): exit 3, stderr names its time and topic. (Fails today.)
3. A trail whose last run did not shut down: "final book: not checked (…)",
   no `E4`. (Fails today.) One that shut down: compared, unchanged.
4. A resting `ATO` order at the end is not reported as missing from
   `gtc_orders.json`. (Fails today.)
5. `queue --order ""` and a prefix shared by two orders: exit 2 naming the
   candidates. (Fails today.)
6. `rerun --date …`, `--from`, `--gateway`, `--kind`; `queue --tz …`;
   `--log-file` naming an archive: exit 2. (Fails today.)

**Change.** `rawlines.lines` skips the last line of the last file when it
has no newline and raises `Unavailable` for meta it cannot parse;
`rerun.inputs` turns a body that does not parse into `Unavailable`.
`final_book` per Q4. `OrderQueue` collects matching ids in a first pass
over `order.new` lines (`rawlines.lines` with a topic filter). `validate_args`
refuses the options per command.

**Exit criteria.** Tests 1–6 pass; `tests/test_sim_forensics_*.py` green
(shared `rawlines`).

**Outcome (2026-11-22).** Written for Q4 (a), the recommendation (taken without
an explicit answer; see the hand-over). `rawlines.lines` stops before the last
line of the last file when it has no newline yet, and raises `Unavailable`
naming the line's time and topic when its `seq`/`eseq` does not parse; the
new `rawlines.body(ln)` does the same for a payload, and replaces every
`json.loads(ln.body)` in `rerun.inputs` (and `startup_message`). `inputs`
takes an `eod` callback, called for each book checkpoint with reason `EOD`
(`Engine._shutdown` publishes them after persisting `gtc_orders.json`); such a
checkpoint is no longer stored as a start's `told` checkpoint. `Rerun` sets
`shut_down` on it and clears it at each restart, and `final_book` compares
only when the last run shut down, and only `GTC`/`DAY` orders
(`_PERSISTED_TIFS`, as `Engine._resting_gtc_orders`); otherwise
`book_unchecked` says why, which `rerun` prints ("final book: not checked
(the engine had not shut down when the trail ends)") and the sim-forensics E4
check carries as its note. `queue --order` first collects the matching
`order.new` ids (`queue.order_ids`, parsing only lines that contain the
prefix): none is exit 1 as before, two or more exit 2 naming up to five. For
`rerun` and `queue`, `validate_args` refuses a `--log-file` naming an archive
or day part and every option they ignore (`--date`, `--from`, `--to`,
`--last`, `--gateway`, `--kind`, `--no-index`, `--rebuild`, `--strict`,
`--clock-skew-warn`, `--reorder-window`; `--symbol` for `rerun`, `--tz` for
`queue`), exit 2. `record()` in `tests/test_sim_forensics_rerun.py` now ends
with the engine's own `_shutdown()` (which writes `gtc_orders.json`), with
`shutdown=False` for a trail whose engine is still running. Tests (in
`test_audit_replay_rerun_cli.py` and `test_audit_replay_queue.py`): all
failed first except "a trail that ends with the shutdown compares the book"
(unchanged behaviour) — `JSONDecodeError`/`ValueError: invalid literal ...
'abc24'` tracebacks, "final book: 3 differences" against a stale file, the
ATO/ATC stub counted 2, `--order ""` answered exit 0, every ignored option
exit 3 or 0. The half-line test first passed for the wrong reason (it cut a
`system.*` line the re-run skips unparsed) and was changed to cut an
`order.ack` line before the fix. Full suite: 15 314 passed, 1 skipped.

### WP-RPL09 — CLI edges (C5, C12, C13, P3)

**Tests first** (`tests/test_audit_replay_cli.py`):

1. `--to 2026-11-22` includes lines of 2026-11-22; `--from D --to D` is that
   whole day. (Fails today.)
2. `episodes`, `digest`, `anomalies` on an empty window exit 1 with "nothing
   to narrate in this window"; `stats` on no facts exits 1. (Fails today.)
3. No subcommand: exit 2 with usage. (Fails today.)
4. `--top 0`, `--top -1`, `--clock-skew-warn -1`, `--clock-skew-warn nan`:
   exit 2. (Fails today.)
5. After `--log-file X --db Y`, the suggested command contains both; after
   `--date D`, it contains `--date D`. (Fails today.)
6. A `--to` bound early in a two-part trail: the second part is not parsed
   (count `parse_line` calls). (Fails today.)

**Change.** `parse_ts(..., end_of_day=True)` for `--to`; `_run_view` and
`_run_stats` return 1 on empty; `required=True` on the subparsers; argparse
types for `--top` and `--clock-skew-warn`; `story_command` takes the source
options; a replay-side read that stops once a recorder stamp passes `to_dt`
by the reorder seconds.

**Exit criteria.** Tests 1–6 pass; `make completion` regenerated.

**Outcome (2026-11-22).** `--to` with a bare date is the end of that day
(`window_bounds` and the `--from`/`--to` order check both use
`parse_ts(..., end_of_day=True)`). The reports exit 1 with "nothing to narrate
in this window" when the window holds no episode, and `stats` exits 1 on "No
facts in window."; an empty *finding list* over a non-empty window stays exit
0. A subcommand is required (`required=True`: usage and exit 2). `digest --top`
takes `parse_top` (≥ 1) and `--clock-skew-warn` `parse_skew` (finite, ≥ 0).
`story_source(args)` carries `--log-file` and `--db` (when not the defaults,
shell-quoted) and `--date` into every suggested `story` command, in the text
and the NDJSON `story` field. `_window` reads the `--no-index` window and stops
at the first line stamped more than the reorder window's seconds past `--to`.
Tests: `TestCliEdges` and `test_a_subcommand_is_required` (14, all failed
first: an empty table at exit 0, `DID NOT RAISE SystemExit`, the bare `story
--command 8812` suggestion, 30 `parse_line` calls against at most 11).
Existing tests that parsed options with no subcommand now name one; two
equality tests between an indexed and a `--no-index` run now give both the
same `--db` (the suggestion names it); `test_audit_day_scope`'s empty live
trail now expects exit 1. `make completion`: no change (the help texts did not
change). Full suite: 15 295 passed, 1 failed (that `test_audit_day_scope`
test, updated and rerun green), 1 skipped.

### WP-RPL10 — Comments, docstrings, `pm-help`, guide and reference manual say what the code does (C2, D1–D11; after Q3 and all other WPs)

**Tests first** (`tests/test_pm_help*.py`, `tests/test_audit_replay_cli.py`):

1. The `pm-help pm-audit-replay` entry lists every global option argparse
   defines and every subcommand. (Fails today.)
2. Under Q3 (b): the guide's rows for `FILL_AFTER_TERMINAL`, `QTY_MISMATCH`
   and `ILLEGAL_STATUS_TRANSITION` name the reorder-window reach, and the C2
   trail's behaviour is asserted as documented (no finding at the default
   window, the findings with `--reorder-window 5000`).

**Change.** D1–D11 as listed in §5; the guide's index section, exit codes,
"clean run" claims and the dispute chapter rewritten against the code after
WP-RPL01–09; the reference manual's exit codes; `make completion`;
`mkdocs build` clean.

**Exit criteria.** Tests 1–2 pass; every passage in §5 re-read against the
final code (lessons-learned B1).

**Outcome (2026-11-22).** Written for Q3 (b), the recommendation (taken
without an explicit answer; see the hand-over). Test 1
(`test_the_pm_audit_replay_entry_matches_its_parser`) compares the `pm-help`
entry's options and subcommands with `build_parser()` both ways; it failed
first (`--no-index`, `-vv`, `-vvv` listed; `--clock-skew-warn`, `--strict`,
`--force-color` missing; no subcommands). Test 2
(`TestALateFillIsSeenWithinTheReorderWindow`) asserts the documented reach:
no `FILL_AFTER_TERMINAL`/`QTY_MISMATCH` for a late fill 2 001 facts on at the
default window, both with a 5 000-fact window; it passes on the code as it
stands, as a test of documented behaviour should. Texts: D1 the `pm-help`
entry rewritten (nine subcommands with their arguments, every option, the
day-file `--date`, level 1 as default, `csv`, exit codes); D2 the CLI module
docstring and `_add_commands` (done with WP-RPL03/09); D3 `FILL_WITHOUT_TRADE`
and the detector's `_trades` comment say the engine publishes fills first;
D4 `LinkResolver._structural` says the trade states the trade/order join on a
current trail and the fill-to-trade rule serves trails where the trade came
first; D5 `state.py` and `retire_order` state the reorder-window reach; D6
`EpisodeAssembler._retire` and `index.py` (with WP-RPL01) stop promising flat
memory for the reports; the `stated_links` schema comment no longer mentions
an incremental build. D7–D9 and D11: the guide's index section (who uses it,
the grown-trail note, 2.8× size, measured build rate, atomic build, refused
`--db`, a warning on a simulation day's size), a new "Memory" section, the
window and `--to` rules, the exit-code table, the `CANCEL_UNSOLICITED`/
`CANCEL_UNMATCHED` rows, a note on the late-fill reach, the clean-run tip
(what a simulation trail still shows, with part 70's counts), the suggested
command's source options, `rerun`'s final book and refusals, `queue`'s
ambiguity, and "Read a one-off trail" in place of `--no-index`. D10 and D11:
the dispute chapter's steps 2, 3 and 5 (what to expect on a busy day and the
measured cost, the final book during the day, and that only `queue` has
`--anonymise`). The reference manual's section matches. Three docstrings
that used `--no-index` as shorthand were reworded. `make completion`,
`make dbdocs`, `mkdocs build` clean. Full suite: 15 366 passed, 1 skipped.

---

## 9. Out of scope, noted

- **pm-audit-cli's `iter_entries` reads to the end after `--to`** (P3). The
  replay fix stays on the replay path; pm-audit-cli pays the same 4.8 s per
  later part. A small inefficiency, not a defect; not added to the For-Later
  list.
- **The re-run of part 1 found one differing episode** (`order.new` on CHD:
  the re-run published `order.cancelled.MM01` and `quote.status.MM01` where the
  live engine did not). The run was made with 0.83.2 and re-run with 0.83.4;
  the guide's advice is to re-run with the run's engine version before
  calling it non-determinism. Worth one run under 0.83.2 when the engine is
  next reviewed (ENG03/08/09 are open); not a replay defect.
- **The engine's leg cancels carry no `cancel_reason`** for OCO and quote
  cancels. H2 is fixed on the replay side, which is enough; a reason on those
  cancels would also help participants' own logs. Not a defect.

---

## 10. Holistic review after the WPs (2026-11-22)

Done after WP-RPL10, over the whole component and the flows the guide
describes, with the simulation stopped (its trail then ends at the engine's
shutdown).

**Validated at real scale.**

| Check | Result |
|---|---|
| `rerun` over the whole simulation day (72 parts, 27 054 652 messages) | 4 637 697 commands re-ran; 0 hidden inputs; 0 differing episodes; final book compared (the trail ends with the `EOD` checkpoints) with 0 differences; exit 0; 962 s, 624 MB peak RSS |
| `anomalies --severity warn` over 4 consecutive parts (974 605 episodes) | 143.8 s at 186 MB peak RSS — flat across parts (one part alone peaked at 1.62 GB before WP-RPL04) |
| `--last 15m stream` over the live 72-part trail | 3.8 s with no index written (WP-RPL03) |
| `story` on a one-part index | 0.80 s (WP-RPL05) |

**Found and fixed (performance, behaviour unchanged).** A profile of
`anomalies` on 60 000 real lines showed four avoidable costs, now removed:
`audit.query.parse_ts` tried `strptime("%Y-%m-%d")` first and raised a
`ValueError` on every full timestamp (it now skips that for a value with a
`T`); `audit.query._match_topic` scanned every wildcard prefix twice per line
(now `lru_cache`d, bounded at 65 536 topics); `facts.normalise` copied every
fact with `dataclasses.replace` to set `publisher_run = 0` (now only for runs
after the first); `EpisodeAssembler._closing` was a list popped from the front
(now a `deque`). 5.81 s → 4.58 s on the excerpt (−21 %), with the NDJSON
findings and the `-vv` narration byte-identical before and after. The two
shared functions in `audit/query.py` keep their behaviour for pm-audit-cli.
What remains in the profile is spread over price and time resolution and JSON
decoding.

**Found and documented, not changed.**

- **`TRADE_LEG_MISSING` at a window's start.** On the 4-part run the one
  error was `trade 000001-000333542 has 0 fill leg(s)`: the trade is line 2
  of part 10, its two fills the last lines of part 9 (the engine publishes a
  match's fills before its trade). It is a window-edge finding at *error*
  severity, which the dispute chapter's "no finding at error" would misread;
  both guide chapters now name it. Demoting it (as `ARRIVAL_SEQ_GAP` is
  behind `--strict`) would need the detector to know the window started
  within a reorder window of the trade, and would hide a genuinely lost pair
  of fills at a day's start; left as is, documented.
- **Building a day's index is still over an hour.** By decision Q1 (a) only
  `story` pays it, once, and then reads the grown trail with a note.
- **`stream` and `story` hold their window** (Q2 a), now stated in the guide
  with the per-line cost.

**Re-walked flows (lessons-learned B1).** `tools/verify_audit_trail.sh`
(drops `--no-index`; its empty-trail guard runs before the report, so the new
exit 1 on an empty window cannot end it early); the dispute procedure's five
steps against the new exit codes and `rerun`'s final-book rule; the guide's
cookbook commands (every one still parses: `stream --date … --symbol …`,
`anomalies --severity error --date …`, `digest --top 20`, `episodes
--outcome REJECTED --format csv`, `stats --date …`, `queue --order …`).

**Full suite after the review:** 15 366 passed, 1 skipped; black, flake8,
mypy, pyright, msgen, dbdocs, openapi and `mkdocs build` clean.

