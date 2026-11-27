# EduMatcher — Audit GUI Workplan (R0, R1, R2)

Companion design: [EduMatcher-Audit-GUI.md](EduMatcher-Audit-GUI.md) (1.1.0-design)

Status: **In progress** (AG0, AG1 done). This plan orders the work needed to deliver the
whole design: the R0 thin slice, the R1 evidence workbench, and R2
behavioural surveillance. Section numbers such as "design §9.4" refer to the
companion design. Code takes precedence over both documents; a WP that finds
a contradiction records it in section 8 and corrects the design.

Started: 2026-11-27

## Delivery rule: test first

Every WP follows true TDD, as in the
[Clearing GUI workplan](EduMatcher-Clearing-GUI-Workplan.md):

1. Add one or more tests that express the WP's externally observable
   behaviour. Expectations come from message and exchange contracts and the
   metric definitions in design §3, not from today's output
   ([testing guidelines](EduMatcher-Testing-Guidelines.md)).
2. Run the focused tests and record the expected failure. The failure must
   be caused by the missing behaviour, not by an import, fixture or
   assertion mistake.
3. Implement the smallest production change that makes them pass.
4. Add boundary, authorization, unit/precision, unavailable-source and
   regression cases found during implementation.
5. Run the WP's focused tests and the affected package suites. Do not start
   the next WP with a known failing test.

A finding discovered while working a WP becomes a failing regression test
before its fix. Every SQLite connection opened by production code or tests is
closed in `finally`/`closing`/fixture teardown, including on failures.

Per-WP verification (in addition to the focused tests):

```bash
poetry run black --check src tests
poetry run flake8 src tests
poetry run mypy src tests
poetry run pyright src tests
poetry run pytest tests/ -n logical          # affected suites at minimum
make openapi && make openapi-check           # after any REST contract change
make completion                              # after any CLI argparse/help change
make -C web-apps/audit-gui typecheck test    # from AG5 on, for GUI changes
```

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

### R0 — thin vertical slice (design AU-0)

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 0 | AG0 | Shared "audit world" fixtures and API test harness | — | 2 d | ☑ | 2026-11-27 |
| 1 | AG1 | Evidence collections, minimal snapshot descriptor and capability model | AG0, D1 | 1.5 d | ☑ | 2026-11-27 |
| 2 | AG2 | Audit router skeleton: ADMIN guard, errors, events, stories, findings | AG1 | 2 d | ☐ | |
| 3 | AG3 | Market read models: depth heatmap and order lifelines | AG2, D6 | 2.5 d | ☐ | |
| 4 | AG4 | `pm-sim-forensics` report adapter in the consistency lane | AG1, AG2 | 1 d | ☐ | |
| 5 | AG5 | `audit-gui` foundation: workspace, auth, shell, proxy, evidence banner | AG2 | 2 d | ☐ | |
| 6 | AG6 | Market canvas (Analyse, R0 layers), story drawer, raw evidence | AG3, AG4, AG5 | 3 d | ☐ | |
| 7 | AG7 | R0 acceptance, help text and holistic review | AG6 | 1 d | ☐ | |

### R1 — explain and verify (design AU-1 … AU-6)

| # | WP | Content | Design pkg | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 8 | AG8 | Full source catalogue: legacy, rotation, zstd, retired, torn, run resets, mutation | AU-1 | AG7 | 2.5 d | ☐ | |
| 9 | AG9 | Worker process, job store and job API; `prepare`/`verify`/`forensics_import` | AU-2 | AG8 | 3 d | ☐ | |
| 10 | AG10 | Typed filter grammar, cursors, counts, bounds and `reproduce` blocks | AU-2 | AG8 | 2 d | ☐ | |
| 11 | AG11 | Integrity & Coverage workspace | AU-3 | AG9, AG10 | 2 d | ☐ | |
| 12 | AG12 | Explorer: episodes/raw events, causal graph, Pivot (`/analyze`) | AU-3 | AG10 | 3 d | ☐ | |
| 13 | AG13 | Evidence basket, deep links and Findings workspace (existing lanes) | AU-3 | AG12 | 1.5 d | ☐ | |
| 14 | AG14 | Descriptive aggregates: `/summary`, `/participants`, `/symbols` | AU-4 | AG10 | 3 d | ☐ | |
| 15 | AG15 | Market-quality read model: `/market/{symbol}/quality` | AU-4 | AG3, AG14 | 2 d | ☐ | |
| 16 | AG16 | Simulator context adapter: news, true value, presets, clock offset | AU-4 | AG8, D5 | 1.5 d | ☐ | |
| 17 | AG17 | Counterparty `/flows` and the `/frames` frame service | AU-4 | AG14 | 2 d | ☐ | |
| 18 | AG18 | Overview, Participants, Market Analyse tabs and compare mode | AU-4 | AG13–AG16 | 3 d | ☐ | |
| 19 | AG19 | Illustration player and first illustrations: flow ring, Sankey, news absorption | AU-4 | AG17, AG18 | 2 d | ☐ | |
| 20 | AG20 | Re-run and queue jobs in the worker, with divergence tracking | AU-5 | AG9 | 3 d | ☐ | |
| 21 | AG21 | Market Replay mode: transport, book at cursor, Recorded/Reproduced/Queue | AU-5 | AG6, AG13, AG20 | 3 d | ☐ | |
| 22 | AG22 | Replay illustrations: queue ladder, layering, domino, momentum, corridor, auction, SMP, swimlane | AU-5 | AG19, AG21 | 3 d | ☐ | |
| 23 | AG23 | Evidence bundle, CSV and Parquet notebook exports with redaction | AU-6 | AG9, AG13, D8 | 2.5 d | ☐ | |
| 24 | AG24 | Debrief reports, teaching clips, saved views | AU-6 | AG18, AG19, AG23, D4 | 2.5 d | ☐ | |
| 25 | AG25 | R1 hardening: benchmark, accessibility, deployment, docs, holistic review | AU-6 | AG11, AG22, AG24, D2 | 3 d | ☐ | |

### R2 — behavioural surveillance (design AU-7)

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 26 | AG26 | Detector framework: contract, profiles, result states, grouping, baselines, `scan` job | AG25 | 3 d | ☐ | |
| 27 | AG27 | Scenario bots, labelled corpus and benign look-alikes | AG26, D7 | 3 d | ☐ | |
| 28 | AG28 | Detectors A: layering, churn, paired round trips, circular ring, self-trade/SMP | AG26, AG27, D3 | 3 d | ☐ | |
| 29 | AG29 | Detectors B: price run, momentum ignition, stop hunting, iceberg pinging, breaker gaming, auction steering, close window | AG26, AG27, D3 | 3 d | ☐ | |
| 30 | AG30 | Detectors C: liquidity withdrawal, concentration, adverse selection, pre-publication, lead/lag | AG16, AG26, AG27, D3 | 3 d | ☐ | |
| 31 | AG31 | Review state: dispositions, notes, cases, change audit | AG25 | 2.5 d | ☐ | |
| 32 | AG32 | Behavioural lane UI, evidence cards, threshold workbench, cycle overlay | AG28, AG31 | 2.5 d | ☐ | |
| 33 | AG33 | R2 hardening, precision/recall report and holistic review | AG28–AG32 | 2 d | ☐ | |

Critical path: **AG0 → AG1 → AG2 → AG3 → AG6 → AG7 → AG8 → AG9 → AG20 →
AG21 → AG22 → AG25 → AG26 → AG27 → AG29 → AG32 → AG33.**

Parallel tracks once their dependencies are green:

- After AG8: AG10 → AG12 → AG13 and AG10 → AG14 → AG15/AG17, alongside the
  worker track AG9 → AG20.
- AG16 (simulator context) only needs AG8 and decision D5.
- AG23 can start as soon as AG9 and AG13 are done.
- In R2, AG31 can run alongside AG26–AG30; AG28–AG30 can run in parallel
  once AG27 delivers the corpus.

Estimated sequential effort: R0 15 d, R1 44.5 d, R2 22 d; about **82 days**,
excluding review time, findings and deployment-environment investigation.

## 1. Gate decisions

The design's open decisions (design §13.3) block specific WPs only. Until a
decision is made, the WP uses the stated default and records it in section 8.

| ID | Decision | Needed before | Default if undecided |
|---|---|---|---|
| D1 | Deployment ownership and paths of evidence collections and the derivative job/result store; storage and retention budgets; anchor handling | AG1 (minimal), AG9 (store) | One collection = the configured `data/` audit directory; derivative store under `data/audit-gui/`; no external anchor. |
| D2 | Reference capture and machine for the performance targets (design §11.1) | AG25 | Generated with `edumatcher-sim` to the design's minimum size; 8 cores, 16 GiB, SSD. |
| D3 | R2 detector profiles, numeric thresholds, baseline history and escalation policy | AG28–AG30 | No shipped default profile. Detectors run only with an explicit profile, and thresholds are calibrated on the AG27 corpus. |
| D4 | Future reviewer role or participant-safe extract workflow | AG24 | ADMIN-only. Per-gateway debrief pages are instructor-reviewed extracts (design §9.8). |
| D5 | Whether simulations record a gateway → ai_trader preset mapping; simulator/engine clock alignment | AG16 | No preset labels. Clock offset is measured from co-observed events and shown; analyses are disabled above the offset bound. |
| D6 | `book.*`/`depth.*` publication cadence in classroom configurations | AG3, AG15 | Measured per snapshot; heatmap bins never finer than the median observation interval. |
| D7 | Location and ownership of scenario bots and their labelled corpus | AG27 | A new `edumatcher.sim_scenarios` package with its own entry point, refusing to start without a simulation marker. |
| D8 | Accept `pyarrow` (not a dependency today) for Parquet notebook export | AG23 | Added to a new optional `audit` dependency group/extra only; without it the export offers NDJSON and CSV and reports Parquet as unavailable. |

## 2. Scope and source-of-truth constraints

- Evidence authority is the retained audit trail read through the existing
  parsers (`audit.query`, `audit.replay.reader`), plus the manifest. Indexes,
  read models, job results and the GUI are derivatives.
- Simulator context comes from `market_sim_news.db` (`news_events`,
  `value_jumps`). pm-api-gwy already serves news history (`GET /api/v1/news`,
  any key) and the live true values (`GET /api/v1/admin/sim`). There is no
  API for true-value history; AG16 adds a read-only adapter for it. None of
  this is audit evidence.
- The engine, gateways, recorders and stores are not changed by this plan,
  except where a WP explicitly adds a read-only query helper. No WP adds an
  order, control or configuration write path.
- New Python code lives in `src/edumatcher/audit/service/` (adapters, read
  models, jobs, worker) and `src/edumatcher/api_gateway/routers/audit.py`.
  New web code lives in `web-apps/audit-gui/`, following
  `web-apps/clearing-gui/`.
- New config keys follow the clearing precedent: added to the API-gateway
  config, the verifier, config-gen comments and config-gui (types, zod,
  defaults, codec, UI) in the same WP.
- Every REST change ends with `make openapi` and the updated "Audit" chapter
  of `docs/books/protocols-and-clients/part-2-specifications/060-rest-and-websocket.md`.

Excluded from all WPs: live alerting, near-live in-session review (needs an
incremental episode index), cross-venue data, beneficial ownership, LLM text
generation, ML scores, and any participant self-service access.

## 3. Shared test data and conventions

AG0 builds the fixtures; later WPs extend them rather than creating isolated
data. Audit data is **recorded**, not hand-written: drive the in-process
engine and the real audit writer the way `tests/test_sim_forensics_rerun.py`
(`record`) does, and reuse the `tests/fixtures/replay/` logs for narrow
replay cases.

The base "audit world" contains:

- two symbols with different `tick_decimals` (2 and 4) and four gateways:
  MM01 (quotes), TRADER01–03;
- a continuous phase with a layering-like sequence by TRADER02 (large
  displayed orders, opposite-side fill, cancellation), an MM quote
  replacement burst, and an owner cancel burst;
- a stop order cascade with recorded trigger links, an iceberg with refills,
  an IOC probe sequence, and a self-match-prevention cancel;
- a halt and resumption, an opening and a closing auction with indicative
  updates;
- an `ESEQ_GAP` planted by removing lines, a recorder restart, and a second
  run with reused counters (run reset);
- a three-gateway trade cycle TRADER01→TRADER02→TRADER03→TRADER01 and a
  paired round trip;
- a `market_sim_news.db` with a rumour, its confirmation, a retraction and
  value jumps, with a known clock offset; and
- a `pm-sim-forensics` report with PASS, FAIL, SKIPPED and ERROR checks.

Every fixture has a hand-computed **expectation table** (executions, owner
cancels, lifelines, spreads, flows) written from the contract, not from the
code under test. The API harness is `tests/api_gateway_harness.py`;
credentials cover ADMIN, TRADER, MARKET_MAKER and read-only keys. GUI tests
use Vitest and Testing Library as in `clearing-gui`; browser journeys use
the clearing GUI's end-to-end pattern.

## 4. Work packages — R0

### AG0 — Shared "audit world" fixtures and API test harness

**Purpose.** One recorded, realistic audit session and its expectation
tables, reused by every later WP.

**Covers:** design §3.2, §11.2 (scenarios 1–6), section 3 of this plan.
**Depends on:** —

**Test-first workstep.** Write fixture self-tests that assert the
expectation tables against the *raw* audit lines with a deliberately naive
reader (topic and payload only): N unique `trade.executed` identities, the
planted gap, the restart marker, two runs, both tick scales. They fail
because the fixture builder does not exist.

**Implementation worksteps.**

1. Add `tests/audit_gui_world.py` (not collected) with `build(tmp_path,
   **variants)`, reusing `record` from `tests/test_sim_forensics_rerun.py`
   and generated message models for every command.
2. Add variants: `gap`, `restart`, `run_reset`, `no_config`, `zstd_archive`,
   `torn_tail`, `sim_context`, `forensics_report`.
3. Write the expectation tables as module constants, with a comment per
   number saying how it follows from the contract.
4. Add `make_audit_app(world)` on top of `tests/api_gateway_harness.py`, with
   ADMIN, TRADER, MARKET_MAKER and read-only keys.

**Exit criteria.** Fixture self-tests pass; building the base world takes
< 3 s; no fixture writes outside `tmp_path`; all connections closed.

**Performance impact.** Test-only. Session-scoped caching of the built world
is allowed only for read-only use.

### AG1 — Evidence collections, minimal snapshot descriptor and capability model

**Purpose.** Pin what a report is about before anything reads it.

**Covers:** design §6, §7.2. **Depends on:** AG0, D1.

**Test-first workstep.** Tests that creating a snapshot of the base world
yields a descriptor with file inventory, sizes, hashes, a complete-line
cutoff for the active file, runs, receipt-time extent and per-capability
availability; that appending to the active log afterwards does not change
reads through that snapshot; that an unknown snapshot ID is a typed
"unavailable" result; and that a `no_config` world reports re-run as
unavailable with a reason.

**Implementation worksteps.**

1. Config key `api_gateways.<name>.audit_collections` (list of
   `{id, path}`), mirrored in verifier, config-gen and config-gui.
2. `audit/service/snapshot.py`: `SnapshotDescriptor` (frozen dataclass),
   `create_snapshot(collection)`, `open_snapshot(id)`; descriptors stored as
   JSON in the derivative store with a content-derived ID.
3. `audit/service/capabilities.py`: capability enum (`stories`,
   `causality`, `prices`, `book`, `rerun`, `queue`, `sim_context`,
   `forensics`) with stable unavailable-reason codes.
4. Read only through existing parsers. Never write to source files.

**Exit criteria.** Snapshot reads are stable under source append; a mutated
retained file is detected by hash; reason codes are documented.

**Performance impact.** Hashing is O(file size) once per snapshot and is
reported. R0 creates snapshots synchronously (bounded to one session); AG9
moves this into a `prepare` job.

### AG2 — Audit router skeleton: ADMIN guard, errors, events, stories, findings

**Purpose.** The first authenticated, typed, bounded read routes.

**Covers:** design §8 (`/collections`, `/snapshots/{id}`, `/events`,
`/stories`, `/findings` without behavioural rows), §8.1. **Depends on:** AG1.

**Test-first workstep.** Through the ASGI harness: every route is 403 for
TRADER, MARKET_MAKER and read-only keys; `/events` returns canonical keys,
nanosecond timestamps as strings, tick values with `tick_decimals`, and
source references; `/stories/order/{id}` returns the replay story with link
confidences; `/findings` returns existing replay anomaly codes in the right
lanes (design §4.1); missing source is 503, unknown entity 404, invalid
filter 422, unsupported capability a typed reason and not an empty list.

**Implementation worksteps.**

1. `api_gateway/routers/audit.py` under `/api/v1/audit`, registered in
   `api_gateway/main.py`, using existing auth and error envelopes; new error
   codes in the registry.
2. Adapters over `audit.replay.pipeline.reconstruct` and the render-JSON
   model. Do not re-derive business rules.
3. Lane mapping for every existing anomaly code in
   `audit/replay/anomalies.py`, with a test that fails if a new code is
   added without a lane.
4. Page size default 100, max 1,000; `has_more` and a cursor.
5. `make openapi`; REST chapter section "Audit (ADMIN)".

**Exit criteria.** Role matrix test covers every route; OpenAPI check is
green; no route accepts a filesystem path.

**Performance impact.** R0 reconstructs one session per snapshot and caches
it per snapshot ID in the API process, bounded by an LRU of one. AG9
replaces this with worker-built read models.

### AG3 — Market read models: depth heatmap and order lifelines

**Purpose.** The two visualisations that drive R0.

**Covers:** design §9.4, §8 (`heatmap`, `lifelines`), §8.1 caps.
**Depends on:** AG2, D6.

**Test-first workstep.** From the base world's expectation tables:

- heatmap cells equal recorded displayed quantity per level for each
  observation interval; gap and halt intervals are masked; cadence is
  reported; bins are never finer than the median observation interval;
- each lifeline's start, end, price, displayed quantity, segment breaks on
  amendment, and end reason (filled, owner cancel, system cancel by reason,
  expired, still open) match the order's recorded lifecycle;
- more than 5,000 segments returns per-level aggregates with
  `aggregated: true`;
- a window that cuts an order shows it as censored, not ended.

**Implementation worksteps.**

1. `audit/service/market.py`: observation timeline from `book.*`/`depth.*`
   with validity intervals; lifeline builder from order facts.
2. Routes `/market/{symbol}/heatmap` and `/market/{symbol}/lifelines`.
3. Integer tick arithmetic; display conversion only with recorded
   `tick_decimals`.

**Exit criteria.** All of the above pass for both tick scales; the halt and
the gap render as masks.

**Performance impact.** Linear in events in the window; binning on the
server. Measure the base world and a 1-million-event generated session; record
the numbers in the WP's done note.

### AG4 — `pm-sim-forensics` report adapter

**Purpose.** Show the strongest cross-store evidence in the consistency lane.

**Covers:** design §2, §4.1, §6. **Depends on:** AG1, AG2.

**Test-first workstep.** With the `forensics_report` variant: FAIL rows
appear in the consistency lane with check ID, sample rows and data scope;
SKIPPED and ERROR appear as their own states; PASS never appears as a
finding; a report whose inputs do not match the snapshot is flagged
"different inputs".

**Implementation worksteps.** Read the report written by
`pm-sim-forensics --out` (no re-implementation), pin its hash and its
covered inputs in the snapshot descriptor, and merge into `/findings`.

**Exit criteria.** Tests above pass; the snapshot reports `forensics`
capability as available or unavailable with a reason.

**Performance impact.** Negligible (one small report file).

### AG5 — `audit-gui` foundation

**Purpose.** A deployable, authenticated, read-only SPA shell.

**Covers:** design §7.1, §9.1 (shell, top bar), §9.2 item 1 (evidence
banner). **Depends on:** AG2.

**Test-first workstep.** Vitest tests: a non-ADMIN key is refused with a
clear message; the snapshot picker lists collections; the evidence banner
shows extent, gap count, manifest state as "checked, unanchored" /
"failed" / "no manifest" separately, and cannot be collapsed while a
check has failed; an API 503 renders an error state, not zeros.

**Implementation worksteps.**

1. Scaffold `web-apps/audit-gui` from `clearing-gui` (apps/web, apps/serve,
   Dockerfile, compose, Makefile, `.env.example`).
2. Typed API client with Zod schemas generated or hand-written from the
   OpenAPI contract; TanStack Query; Zustand for snapshot/scope.
3. Shell with the seven workspaces (unbuilt ones show "not in this release"),
   top bar, Explain switch, historical-snapshot label.

**Exit criteria.** `make -C web-apps/audit-gui build test typecheck` green;
container serves the app behind the same-origin proxy.

**Performance impact.** Bundle size recorded; ECharts loaded on demand.

### AG6 — Market canvas, story drawer, raw evidence

**Purpose.** The R0 user experience: one symbol, one session.

**Covers:** design §9.4 (canvas, Analyse without tabs beyond events &
checks), §9.3 drawer (story, checks, raw evidence), §9.9.
**Depends on:** AG3, AG4, AG5.

**Test-first workstep.** Component tests against recorded API fixtures:

- clicking a lifeline opens the order story and its raw lines;
- brushing sets the interval in the URL;
- masked heatmap areas are hatched and carry a tooltip with the reason;
- the end-reason markers have text equivalents;
- keyboard navigation moves between marks;
- Back/Forward restores drawer and interval.

**Implementation worksteps.** ECharts heatmap and custom-series lifelines;
trades layer; phase/halt/gap bands; flow strip; URL-addressable drawer with
Story, Checks and Raw evidence tabs; no red/green-only encoding.

**Exit criteria.** The AU-0 acceptance checks (design §11) pass end to end in
the browser on the base world.

**Performance impact.** Canvas rendering; at most one heatmap and one
lifeline request per interval change, debounced.

### AG7 — R0 acceptance, help text and holistic review

**Purpose.** Prove the slice and fix the contracts before generalising.

**Covers:** design §11 AU-0. **Depends on:** AG6.

**Worksteps.** Run the AU-0 acceptance list; write in-app help for the
canvas and drawer; review AG0–AG6 for contract drift against the design and
record findings in section 8; update the design where the code is right.

**Exit criteria.** AU-0 acceptance met; no open P1 findings.

## 5. Work packages — R1

### AG8 — Full source catalogue

**Covers:** design AU-1, §7.2, §9.7 inventory. **Depends on:** AG7.

**Test-first workstep.** Using the AG0 variants: legacy lines without
envelopes, rotated day parts, zstd archives, retired days (tombstones),
missing files, a torn trailing line, run resets with reused IDs, and a
retained file mutated after snapshot. Each yields its exact state and reason;
a run reset never joins stories across runs; reads never modify sources.

**Implementation worksteps.** Extend `snapshot.py` to the full inventory;
add the manifest verification result (chain/content and anchoring as
separate fields); per-run extents and ordering mode (`eseq` or legacy).

**Exit criteria.** Design §11.2 scenarios 4 and 5 pass.

**Performance impact.** Verification is O(retained bytes); it moves to the
`verify` job in AG9.

### AG9 — Worker process, job store and job API

**Covers:** design AU-2, §7.3, §8 `/jobs`, `/results`. **Depends on:** AG8, D1.

**Test-first workstep.**

- `POST /jobs` with each R1 kind returns 202. Identical requests are
  de-duplicated, and unknown kinds or options return 422.
- Cancelling and timing out both leave no partial generation.
- Killing the worker marks its job `failed`, with a reason, after restart.
- Scratch directories are removed on success, failure and cancel.
- A read during a rebuild stays on the old generation.
- Progress is `null` until the total is known.

**Implementation worksteps.**

1. `audit/service/jobs.py`: SQLite job store (application-owned) with
   states `queued/running/succeeded/failed/cancelled/unavailable`, stage,
   progress, heartbeat.
2. `audit/service/worker.py`: separate process, one expensive job at a
   time, resource/time/disk limits, atomic publication of read-model
   generations.
3. Job kinds `prepare` (builds the snapshot read models, replacing AG2's
   in-process cache), `verify`, `forensics_import`.
4. Routes `/jobs`, `/jobs/{id}`, `/jobs/{id}/cancel`, `/results/{id}`.

**Exit criteria.** Design §11.2 scenarios 8 and 10 pass; the API process
never runs reconstruction.

**Performance impact.** Job acknowledgement ≤ 1 s; heartbeat ≤ 2 s; measured.

### AG10 — Typed filter grammar, cursors, counts, bounds, `reproduce`

**Covers:** design §8.1. **Depends on:** AG8.

**Test-first workstep.**

- Grammar: valid filters parse to typed chips. Unknown fields return 422
  with suggestions. Values reach SQL only as bound parameters, which a
  test proves with an injection attempt.
- Cursors: a cursor is stable across pages and rejected for a different
  snapshot or filter.
- Counts and IDs: counts are labelled `exact` or `lower_bound`, and an
  ambiguous ID prefix returns a selection list.
- `reproduce`: every route's `reproduce` block, re-issued, returns the
  same page. Where a CLI command line is given, running it yields the same
  IDs.

**Implementation worksteps.** `audit/service/filters.py` (grammar, field
registry shared with `/analyze`); cursor codec; `reproduce` builder.

**Exit criteria.** Grammar documented in the REST chapter and in-app help.

### AG11 — Integrity & Coverage workspace

**Covers:** design §9.7, §2.2. **Depends on:** AG9, AG10.

**Test-first workstep.** API and UI tests show the four kinds of confidence
separately. A failed check is never summarised as "verified". An
engine-wide gap with unknown topics marks all dependent capabilities as
affected. Re-run eligibility names the earliest missing prerequisite. A new
generation does not change an open view.

**Implementation worksteps.** `/snapshots/{id}` extensions; gap map; clock
warnings; config/engine-build coverage; stale-generation action.

**Exit criteria.** Design journey 10.4 up to "request re-run" works.

### AG12 — Explorer, causal graph and Pivot

**Covers:** design §9.3, §8 (`/episodes`, `/graph`, `/analyze`).
**Depends on:** AG10.

**Test-first workstep.**

- Episodes: the list uses the existing episode kinds, and the Raw toggle
  keeps the scope.
- Graph: the default depth is 1 and the maximum is 3 levels and 200 nodes,
  with omitted-node counts. Recorded and inferred links are labelled
  differently, and "recorded links only" hides heuristics.
- Pivot: "owner-cancel rate by gateway × phase" on the base world equals
  the expectation table, and every cell drills to its rows.
- Unknown topics and enums are highlighted, not dropped.

**Implementation worksteps.** Episode and graph adapters over the replay
index; `/analyze` with enumerated measures/dimensions using the AG14 metric
registry (stub measures added here, completed in AG14); Explorer UI with
Episodes/Raw/Pivot tabs and the full drawer (adds Causality and Market
context tabs).

**Exit criteria.** Design §11.2 scenario 3 passes in the UI.

### AG13 — Evidence basket, deep links and Findings workspace

**Covers:** design §9.1 (basket), §9.6, §9.8 (deep links). **Depends on:** AG12.

**Test-first workstep.** Pinning items from every workspace keeps their
snapshot and generation; items from another snapshot are flagged; a deep
link restores snapshot, scope, cursor, drawer and basket; Findings shows the
four lanes with the behavioural lane marked "not available in this release";
the evidence card shows claim, "does not establish", counter-explanations,
raw sources.

**Implementation worksteps.** Basket store (URL + browser storage);
Findings workspace for existing lanes; evidence card component (reused by
R2).

### AG14 — Descriptive aggregates

**Covers:** design §3.1–§3.2, §8 (`/summary`, `/participants`, `/symbols`).
**Depends on:** AG10.

**Test-first workstep.** On the base world, against the expectation tables:

- Execution counting: one venue execution per trade, regardless of fills
  and drop copies.
- Cancellations: owner, system (by reason) and quote-replacement
  cancellations are counted separately.
- Ratios:
  - The cancelled-order rate uses an entry cohort, with censored orders
    shown.
  - A message-to-trade ratio with zero executions is `null` with its
    numerator shown.
  - The fill ratio follows the declared amendment policy.
- Lifetime and units: lifetimes are right-censored, and there are no
  cross-symbol share sums.
- Every metric has a definition in its API metadata.

**Implementation worksteps.** `audit/service/metrics.py` with a versioned
metric registry (definition text, formula, unit, denominator), materialised
by the `prepare` job; routes.

**Exit criteria.** Design §11.2 scenarios 1, 2 and 6 pass.

**Performance impact.** Aggregates built once per generation; queries are
indexed lookups.

### AG15 — Market-quality read model

**Covers:** design §3.1 (market quality), §3.2 (time weighting), §3.3
(formulas). **Depends on:** AG3, AG14.

**Test-first workstep.**

- Spreads are time-weighted, not event-weighted. A test with one long and
  many short quote intervals fails if they are averaged per event.
- Effective spread, realized spread and price impact follow the design
  §3.3 formulas, using the taker's side and the last eligible `mid(t-)`.
- Trades with no eligible mid are excluded and counted.
- Gap, halt and one-sided intervals are excluded, and the excluded
  duration is reported.
- Auction prints are not benchmarked against the continuous market.

**Implementation worksteps.** `/market/{symbol}/quality`; horizons as
enumerated options.

**Exit criteria.** Design §11.2 scenario 11 passes.

### AG16 — Simulator context adapter

**Covers:** design §6 (simulator context), §8 `/context`. **Depends on:** AG8, D5.

**Test-first workstep.** With `sim_context`:

- News and value jumps are returned with provenance.
- The clock offset is measured and reported. Pre-publication analyses are
  disabled when the offset exceeds the window, which is design §11.2
  scenario 12.
- A world without the database returns "not available for this snapshot".
- Preset labels appear only when a mapping exists.
- Non-ADMIN keys are refused.

**Implementation worksteps.** Read-only helper for `value_jumps`, next to
`market_sim.news_history.read_news_events` (reuse it, do not copy SQL);
pinned into the descriptor; `/context`.

### AG17 — Counterparty `/flows` and the `/frames` frame service

**Covers:** design §8 (`/flows`, `/frames`), §9.11.1. **Depends on:** AG14.

**Test-first workstep.**

- Flows: `/flows` totals equal the expectation table. Each trade counts
  once, seller → buyer (design §11.2 scenario 14), and pair shares of both
  sides are included.
- Frames: `/frames` returns one frame per canonical event with source
  badge, gap/freeze markers and skipped spans. More than 2,000 frames are
  bucketed and flagged, and the frame list equals the static event table.

**Implementation worksteps.** Flow read model per bucket; frame service
with pluggable illustration kinds (`flow_ring`, `sankey`, `news_absorption`
here; AG22 adds the rest).

### AG18 — Overview, Participants, Market Analyse tabs, compare mode

**Covers:** design §9.2, §9.4.1, §9.5, §9.1 (compare). **Depends on:** AG13–AG16.

**Test-first workstep.** UI tests:

- Overview: tiles state their scope and counting basis. Behavioural tiles
  are absent before a completed scan. A brush on the activity strip opens
  Market. "What changed?" shows its unavailable state.
- Participants: the profile tabs show definitions and sample counts. The
  outcome funnel's numbers equal `/participants`. The inventory path is
  labelled "net traded in window".
- Market Analyse: the Quality, Participants, Levels and Events & checks
  tabs work. Patterns shows its R2 unavailable state.
- Compare mode: aligns two gateways on shared axes and shows coverage
  differences first.
- Clearing link: the link to clearing keeps gateway, symbol and date.

**Implementation worksteps.** Workspaces and charts per design §9.10 (no
gauges, radar or dual axes).

**Exit criteria.** Design journeys 10.2 (without Replay) and 10.3 (without
R2) work.

### AG19 — Illustration player and first illustrations

**Covers:** design §9.11 (rules, flow ring, Sankey, news absorption).
**Depends on:** AG17, AG18.

**Test-first workstep.**

- Player controls: play, pause, step and speed are tied to the shared
  cursor.
- Gaps and compression: a gap freezes the frame with a "no data" overlay,
  and the time-compression label lists skipped spans.
- Accessibility: `prefers-reduced-motion` and keyboard-only users get the
  static chart and table by default.
- Source badges are always visible.
- Flow ring: its per-pair totals equal the counterparty matrix, and the R1
  ring has no cycle highlighting.

**Implementation worksteps.** Shared `IllustrationPlayer` component;
ECharts `lines` effect for the ring; Sankey with a sliding window; news
absorption overlay.

### AG20 — Re-run and queue jobs

**Covers:** design §9.4.2 (Reproduced, Queue explanation), §7.3. **Depends on:** AG9.

**Test-first workstep.**

- Results: an eligible fixture re-runs with zero differences. A known
  queue question returns priority order and quantity ahead that match
  explicit price-time rules.
- Refusals: missing initial history, config or a gap makes the job
  `unavailable` with its reason.
- Divergence: a planted divergence invalidates all later queue results.
- Isolation: no production socket or state path is touched, which the
  test checks with a patched environment.
- Cleanup: scratch is removed in every outcome.

**Implementation worksteps.** Job kinds `rerun` and `queue` over
`audit.replay.rerun.rerun` and `audit.replay.queue` (`OrderQueue`,
`LevelQueue`) in the worker; structured result adapters with first
divergence and version info; anonymised queue labels for extracts.

**Exit criteria.** Design §11.2 scenario 9 passes.

### AG21 — Market Replay mode

**Covers:** design §9.4.2. **Depends on:** AG6, AG13, AG20.

**Test-first workstep.**

- Stepping and seeking: step by event, episode, trade, phase or finding.
  Seeking by ID works. Keyboard-only stepping works.
- Book at cursor: shows the last observation and its age.
- Mode labels: the Recorded, Reproduced and Queue modes stay labelled. A
  diverged re-run shows a banner, never a success-shaped pane.
- Seeking: reverse seek uses cached checkpoints or replays from a valid
  point, with progress and cancel.
- Idle skips: skipped idle periods are labelled.

**Implementation worksteps.** Transport bar; ladder pane; event timeline
pane; re-run/queue request flow through `/jobs`.

**Exit criteria.** Design journey 10.1 works end to end.

### AG22 — Replay illustrations

**Covers:** design §9.11.2 (queue ladder, layering, domino, momentum,
corridor, auction curves, SMP collision, swimlane), §9.11.3.
**Depends on:** AG19, AG21.

**Test-first workstep.** For each illustration:

- Its frame list equals its static table.
- A gap freezes the frame.
- Its source rules hold:
  - Queue ladder: per-order blocks only with an eligible re-run. Otherwise
    it shows level bars and "not determinable".
  - Domino chain: dashed heuristic links.
  - Auction curves: fall back to the indicative price when the inputs are
    missing.
  - Swimlane: never computes latency across clocks.
  - Corridor: shows thresholds from recorded configuration.

**Implementation worksteps.** Frame kinds in `/frames`; the Illustrate
layer toggle in Replay mode; the swimlane in the Explorer drawer.

### AG23 — Exports

**Covers:** design §9.8 (evidence bundle, CSV, notebook export), §8.1
redaction. **Depends on:** AG9, AG13.

**Test-first workstep.**

- Bundle reproducibility: an evidence bundle from the basket reproduces
  its results from the pinned descriptor. Its hash inventory verifies, and
  it lists redactions and truncations.
- Parquet export: reloads in pandas with the documented schema, units and
  tick scales.
- CSV safety: CSV escapes formula-leading cells.
- Credentials: none appear in exports or URLs.
- Authorization: non-ADMIN download is refused.
- Snapshot expiry: an expired snapshot gives an explicit unavailable
  result.

**Implementation worksteps.** `export` job (bundle, NDJSON, CSV; Parquet
via `pyarrow` per D8, with `poetry lock` and the dependency documented);
redaction rules shared with AG24. Without `pyarrow`, Parquet is reported as
an unavailable capability, not a failed job.

### AG24 — Debrief reports, teaching clips, saved views

**Covers:** design §9.8 (debrief), §9.11.3 (clips), §9.1 (saved views),
journey 10.5. **Depends on:** AG18, AG19, AG23, D4.

**Test-first workstep.**

- Session report: the `debrief` job produces the session report with
  notable episodes chosen by the documented rules.
- Per-gateway page redaction: the page pseudonymises other gateways with
  stable per-report aliases. It omits reserve data and other gateways' raw
  records, and includes the true value only when enabled for a finished
  session.
- Clips: clips carry the snapshot ID and badge and follow the same
  redaction.
- Saved views: saved views round-trip.

**Implementation worksteps.** Report templates (Markdown/HTML); clip
renderer (frame strip SVG; WebM optional); saved-view store in browser
storage.

### AG25 — R1 hardening

**Covers:** design §11.1, §11.2, AU-6 acceptance. **Depends on:** AG11,
AG22, AG24, D2.

**Worksteps.**

1. Generate the reference session (D2) and record cold and warm timings,
   preparation and job throughput, and worker memory against design §11.1.
   Fix the read model or narrow the documented scope if targets fail.
2. Accessibility pass (axe, keyboard, reduced motion, colour) on every
   workspace.
3. Deployment docs (`web-apps/audit-gui/README.md`, compose,
   `deployment/`), operator guide section, REST chapter, in-app help with
   Training Guide links, `make openapi`.
4. Run all R1 journeys (design §10.1–10.6, without R2 steps) and every
   design §11.2 scenario.
5. Holistic review of AG8–AG24; record findings in section 8; update the
   design where code is right.

**Exit criteria.** R1 release checklist (section 7) complete.

## 6. Work packages — R2

### AG26 — Detector framework

**Covers:** design §4.3, §8 `scan`. **Depends on:** AG25.

**Test-first workstep.** A trivial test detector proves the framework:

- Declaration: it declares ID/version, rule text, eligibility, formulas,
  thresholds, windows, minimum samples, clock basis and gap policy.
- Result states: results carry all six states. "No candidates" appears
  only for `completed` and eligible.
- Baselines: baselines use only earlier eligible windows, and a future
  baseline is rejected.
- Grouping: grouping is deterministic.
- Comparisons: the number of comparisons is reported.
- Scope: a scan over a scope with a gap excludes the gap and says so.

**Implementation worksteps.** `audit/service/detectors/` (base class,
profile loader, baseline store, grouping), `scan` job, results in the
derivative store.

### AG27 — Scenario bots and labelled corpus

**Covers:** design §4.4. **Depends on:** AG26, D7.

**Test-first workstep.**

- Guard: a bot refuses to start without the simulation marker.
- Scenario sessions: each scenario produces a recorded session and a
  label manifest whose episode windows contain the intended pattern.
- Look-alikes: each benign look-alike (MM repricing, halt cancels,
  thin-book news reaction, IOC sweep) is produced and labelled benign.

**Implementation worksteps.** Scenario bots per design §4.2 pattern in the
D7 location; corpus generator script producing pinned scenario snapshots;
labels stored with the snapshots only.

### AG28 — Detectors A

Layering/spoofing-like, high-rate churn, repeated paired round trips,
circular trading ring (bounded cycle search), same-gateway self-trade/SMP
cluster.

**Depends on:** AG26, AG27, D3.

**Test-first workstep per detector.** It fires on its labelled scenario and
not on the benign look-alikes. Its evidence card has the declared inputs and
counter-explanations. Precision and recall on the corpus are recorded. For
the circular ring, the labelled three-gateway ring is found, and an
MM-dominated benign session does not escalate.

### AG29 — Detectors B

Price run and reversal, momentum ignition, stop-trigger hunting, iceberg
pinging, breaker/collar gaming, auction indicative steering, close/open
window influence.

**Depends on:** AG26, AG27, D3. Same test-first structure as AG28; stop and
iceberg detectors additionally prove they use only recorded trigger/refill
links and mark privileged inputs.

### AG30 — Detectors C

Liquidity withdrawal before stress, preferential counterparty concentration,
repeated adverse-selection asymmetry, pre-publication positioning (news and
value need AG16; index/corporate-action events from the audit trail),
cross-symbol lead/lag (exploratory, multiple-comparison guarded).

**Depends on:** AG16, AG26, AG27, D3. Same test-first structure.

### AG31 — Review state

**Covers:** design §4.3 dispositions, §9.8 cases. **Depends on:** AG25.

**Test-first workstep.**

- Dispositions: the five states change with reviewer, time and reason.
  Superseded dispositions are kept. "Explained" changes no thresholds and
  deletes nothing.
- Cases: hold basket items and linked snapshots.
- Auditing and authorization: every change is audited, and non-ADMIN
  writes are refused.
- Storage: nothing is written to audit files or replay indexes.

**Implementation worksteps.** Review-state store in the application DB;
narrowly scoped mutation routes; Investigations workspace extensions.

### AG32 — Behavioural lane UI, threshold workbench, cycle overlay

**Covers:** design §9.6, §4.4 workbench, §9.11.2 ring (cycle highlighting).
**Depends on:** AG28, AG31.

**Test-first workstep.**

- Behavioural lane: shows scan state, rule and profile versions, and
  per-rule strength separately from severity.
- Threshold workbench: a sweep creates new profile versions and never
  rewrites old results. It shows candidate counts and labelled hit/miss
  counts side by side.
- Flow ring: highlights cycles only from completed detector results.
- Market canvas: the Patterns tab shows rule-by-rule candidates.

**Implementation worksteps.** `threshold_sweep` job; Findings behavioural
lane and workbench UI; ring overlay; disposition actions on evidence cards.

### AG33 — R2 hardening and holistic review

**Depends on:** AG28–AG32.

**Worksteps.** Precision/recall report per detector and look-alike at the
shipped profiles (published with the release); design §11.2 scenario 7;
journeys 10.2 and 10.3 including R2 steps; performance of a full scan on the
reference session; documentation; holistic review of AG26–AG32.

## 7. Release checklists

**R0 (after AG7):** AU-0 acceptance; role matrix green; OpenAPI committed;
no source writes; findings recorded.

**R1 (after AG25):**

- Every design §11.2 scenario has a passing test, and its name is listed
  here.
- Performance measurements are recorded against design §11.1.
- Accessibility pass complete.
- Deployment, operator and REST docs updated; `make openapi-check` green.
- Every journey in design §10.1–10.6, without R2 steps, works with keyboard
  only.
- No capability shows an empty success when it is unavailable.

**R2 (after AG33):**

- A precision/recall report is published for every shipped detector and
  profile.
- Scenario bots are proven refused outside simulations.
- Disposition history is audited.
- "No suspicious activity" appears only after a completed, eligible scan.

## 8. Findings

Record findings here as WPs are worked: ID, WP, severity (P1–P3), summary,
resolution. Holistic reviews (AG7, AG25, AG33) add a subsection each.

| ID | WP | Sev. | Finding | Resolution |
|---|---|---|---|---|
| AGF1 | AG0 | P3 | The engine publishes no `session.state` at startup; the phase it starts in is only on its STARTUP `system.book_checkpoint.<symbol>` (`phase`). A phase band (AG3/AG6, design §9.4) built from `session.state` alone has no phase before the first transition. | Recorded, with a world test pinning the STARTUP checkpoint phase. AG3 takes the initial phase from the checkpoint, and shows "unknown" where neither exists. |
| AGF3 | AG1 | P3 | Creating a snapshot parses every record (through `iter_entries`) at about 91,000 records/s: a 52 MB, 92,000-record trail takes 1.0 s to pin and 0.85 s to read. The 10-million-event reference session (design §11.1) would take about 110 s per snapshot. | Acceptable for R0 (synchronous, one session). AG9 moves it into the `prepare` job; AG25 measures it against §11.1 and may switch the scan to `rawlines` (unparsed skipping). |
| AGF2 | AG0 | P3 | Section 3 lists the gap, recorder restart and second run as part of "the base audit world"; AG0 step 2 lists them as variants. | Implemented as opt-in variants: `build(tmp, gap=True, ...)`. The base world is one gap-free run, so its tables stay exact. |

### 8.1 AG0 done note (2026-11-27)

- `tests/audit_gui_world.py`: `build(tmp_path, **variants)` records one
  trading day through a real in-process Engine, the real publisher stack
  (`CausalPublisher` over `SequencedPublisher`), pm-audit's `_meta_section`
  and `AuditFile`. Commands are generated message models with a root
  envelope, echoed and dispatched as `Engine.run` does, each followed by a
  real maintenance pass (book/depth/indicative observations). The engine and
  receipt clocks are pinned (receipt = engine + 1 ms; one second per
  command). Order ids are fixed (`order_id(name)`).
- Expectation tables (module constants, each number derived in a comment):
  17 executions (AAA 2 decimals, BBB 4 decimals), seller→buyer flows, owner
  cancels by gateway, system cancels by reason (`QUOTE_REPLACED` 6,
  `CIRCUIT_BREAKER_HALT` 1, `SELF_MATCH_PREVENTED` 1,
  `INSUFFICIENT_LIQUIDITY` 1), 3 DAY expiries at the close, 2 iceberg
  refills, MM01's quote after its replacement burst, and 35 named order
  lifecycles (`LIVES`). All matched the recorded session on the first run.
- The halt is an instructor halt (`risk.symbol_halt` from OPS01, a fifth,
  ADMIN gateway that never trades), not a price-triggered breaker: it is
  deterministic and cancels MM01's live quote leg with
  `CIRCUIT_BREAKER_HALT`.
- Variants: `gap` (the second burst cancel's command and effects removed;
  `World.gap_eseq`), `restart` (pm-audit restarts before the halt; nothing
  lost), `run_reset` (run 2 from the persisted book, counters from 1 again,
  TRADER02 reuses `layer_1`'s order id), `no_config` (engine started from
  YAML: `system.startup` carries no config), `zstd_archive` (day rolled and
  archived with a manifest entry), `torn_tail`, `sim_context`
  (`market_sim_news.db`: rumour→confirmed on AAA with a value jump,
  rumour→retracted on BBB; simulator clock +250 ms), `forensics_report`
  (written by pm-sim-forensics' own report writer with real check
  metadata; statuses PASS/FAIL/SKIPPED/ERROR are set by the fixture, not
  computed).
- `make_audit_app(world, audit_db=)`: the real app with ADMIN (OPS01),
  TRADER, MARKET_MAKER and read-only keys; roles come from a stub engine.
  AG1 adds the `audit_collections` wiring.
- `tests/test_audit_gui_world.py` (28 tests) checks the tables with a naive
  line reader, and that pm-audit-replay's own detectors report the planted
  `ESEQ_GAP` and `RECORDER_RESTART`. Building every variant but
  `zstd_archive` takes well under 3 s; nothing is written outside
  `tmp_path`; the module passes with `ResourceWarning` as an error.
- Facts later WPs need: `auction.indicative.*` carries `eq_price_ticks` and
  `eq_qty`; the base world's read-only tests share a module-scoped build. A
  shared session fixture is left until a second test module needs it.

### 8.2 AG1 done note (2026-11-27)

- D1 default used: a gateway with no `audit_collections` has one collection,
  `default`, the data directory. The derivative store is a parameter
  (`create_snapshot(collection, store)`); AG2 passes `data/audit-gui/`.
- Config key `api_gateways.<name>.audit_collections` (list of `{id, path}`;
  ids `[A-Za-z0-9_-]{1,32}`, unique, at least one entry when present) in the
  loader (`AuditCollection`), the verifier (`_API_INSTANCE_KEYS`, new
  `_API_COLLECTION_KEYS` with S121 for unknown entry keys), config-gen field
  comments (regenerated into config-gui), config-gui (types, zod, defaults,
  codec, an id/path table in the Gateways tab) and the configuration
  references (operator guide 005 and 050, reference manual 010 and 030).
- `audit/service/snapshot.py`: `create_snapshot` hashes every file
  (`audit_files`), copies the active file's complete lines into the store
  (a torn tail is reported as `torn_bytes` and left out), scans the pinned
  records once (`iter_entries`) and derives the id (`s-` + 20 hex) from
  collection id, root and every file's name, kind, cutoff and hash, so an
  unchanged trail gives the same snapshot. `open_snapshot(store, id)`
  rejects malformed ids before touching the filesystem; `entries()` reads
  the pinned copy plus the retained files, after checking each still has
  its pinned size and hash (`SOURCE_CHANGED` / `SOURCE_MISSING`), and names
  each record's source file relative to the collection.
- `audit/service/capabilities.py`: capabilities `stories`, `causality`,
  `prices`, `book`, `rerun`, `queue`, `sim_context`, `forensics`; the
  reason codes are documented in its module docstring. `sim_context` and
  `forensics` are `NOT_ATTACHED` until AG16 and AG4 attach their sources.
  Re-run eligibility in AG1 checks only the engine start and recorded
  config; gaps, restarts and initial book history are AG8/AG20.
- Not in AG1 (AG8): manifest verification, per-run extents and ordering
  mode, legacy/rotated/retired/missing-file states.
