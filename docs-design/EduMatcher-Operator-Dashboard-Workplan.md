# EduMatcher — Operator Dashboard: Workplan and Progress

Tracks the implementation of
[`EduMatcher-Operator-Dashboard.md`](EduMatcher-Operator-Dashboard.md) (v0.3.0),
§18. One work package (WP) at a time; each WP ends with a holistic test run
(`make _check` + the full test suite, or `npm run typecheck && npm test` for
web apps), a review for new insights, and a proposed commit message. The
maintainer commits.

Started: 2026-10-18

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

Execution order follows the dependencies in §18.2 (A2 needs A3, so A3 runs
before A2).

| # | WP | Content | Depends on | Status | Done on |
|---|---|---|---|---|---|
| 1 | A1 | Message spec `health.yaml`, transports, publishers, generated code | — | ☑ | 2026-10-18 |
| 2 | A3 | `monitor` config section end to end (SCHEMA_VERSION 5, cverifier S124+/M029+, config-show, ports) | — | ☐ | |
| 3 | A2 | `edumatcher.health.HealthReporter`, `psutil` | A1, A3 | ☐ | |
| 4 | A4 | Engine metrics, reject funnel, book memory estimate, reporter, perf gate | A2 | ☐ | |
| 5 | A5 | Gateway metrics and reporters (ALF, BALF, MD, RALF, DC, API) | A2 | ☐ | |
| 6 | A6 | Service metrics and reporters (log-srv, stats, audit, clearing, scheduler, index, market-sim) | A2 | ☐ | |
| 7 | B1 | `pm-monitor` skeleton, process state, 1 Hz snapshot | A1–A3 | ☐ | |
| 8 | B2 | Health model and expected roster | B1 | ☐ | |
| 9 | B3 | Rates, engine-bus events, thresholds, host sampler | B1 | ☐ | |
| 10 | B4 | `metrics.db` store, downsampling, retention | B3 | ☐ | |
| 11 | B5 | Start-up integration: `emo` profiles, container `EXPOSE` | B1 | ☐ | |
| 12 | C1 | Scaffold `web-apps/dash-gui` | — | ☐ | |
| 13 | C2 | Bridge: monitor uplink, `/ws`, history REST | B1, B4, C1 | ☐ | |
| 14 | D1 | App shell, top bar, time picker, theme, settings | C1 | ☐ | |
| 15 | D2 | Widget library | D1 | ☐ | |
| 16 | D3 | Dashboard rows 1–7 | C2, D2 | ☐ | |
| 17 | D4 | Drawers and deep links | D3 | ☐ | |
| 18 | E1 | Compose (docker + curl), GHCR workflow, `mkbld.sh`, Makefiles, READMEs | C1, B5 | ☐ | |
| 19 | E2 | Operator-guide chapter and reference docs | D4, A3 | ☐ | |
| 20 | E3 | End-to-end scenarios | all | ☐ | |

## Per-WP checklist

1. Re-read the WP in §18 and the design sections it cites; check the named
   files/functions still exist.
2. Implement the tasks, each with its verifying test.
3. Holistic test: `make _check`, the full `pytest` suite (excluding perf
   unless the WP has a perf gate), plus app tests for TypeScript WPs.
4. Review: what did implementation reveal? Fix code, and update the design
   doc and later WPs where an assumption turned out wrong. Log it below.
5. Mark the WP ☑ here, propose a commit message, stop.

## Insights log

Findings made during implementation that changed code, the design or a later
WP. Numbered I1, I2, … so they can be referenced from commits.

| # | WP | Insight | Action |
|---|---|---|---|
| I1 | A1 | The generator handles everything §11.1 needs (records in records, lists of records, lists of `float`/`int`), so the snapshot is fully generated and validated. | No `json_payload` fallback. Design §11.1 now names `spec/messages/health.yaml` as the wire shape. |
| I2 | A1 | §11.1's TS sketch had a map (`files`), a positional tuple (`load`) and two undefined records (`GatewayStats`, `ActiveBreach`), and repeated the rate fields three times. | Spec uses `FileSize[]`, `load1/5/15`, defines both records and one `RateStats`. Wire is snake_case; C2.5 mirrors it. Differences listed in design §11.1. |
| I3 | A1 | A beacon `host` ≤ 64 (§7.4) would fail validation for a long FQDN, and validation happens in the sampler thread, so the process would go SILENT for good. | `host` ≤ 128 (as `LogRow.host`); design §7.4 updated; A2 truncates `gethostname()` to 128. |
| I4 | A1 | Generated `make_*` constructors validate, so any bad sample (label > 32, empty name) raises in the A2 sampler thread. | A2 watch-out: catch per beacon, count, keep the thread alive. A4 watch-out: label bound vs clamp. |
| I5 | A1 | The UI needs to know which processes are bots (Q2) and needs to read raw metrics not summarised elsewhere (row 6, D3.1). | Added `ProcessHealth.group` (EXCHANGE/BOT) and `ProcessHealth.metrics`; also `TradingStats.busy_pct`, `ExchangeStatus.session_timezone`, `health.event.severity`. |
| I6 | A1 | Measured a realistic snapshot: ≈ 65 KB, 0.8 ms to build and validate. | Validation cost dismissed; size noted in §11.1 and B1 (trim `ProcessHealth.metrics` for the engine first if needed). |
| I7 | A1 | `unit` vocabulary had no bytes/seconds/ms/µs; existing specs fudge these as `dimensionless`. | Added `bytes`, `duration_seconds`, `duration_millis`, `duration_micros` to `msgen/spec.py:UNITS`. Retro-fitting `log.yaml`'s `*_sec`/`*_ms` fields is a possible follow-up (doc-only change to its reference). |
| I9 | A1 | The holistic run caught that `"monitor.snapshot"` already exists as the frame type of the API gateway's `/admin/monitor` WebSocket (trader-gui), an unrelated protocol; `pm-msgen grep-literals` flagged it. | Johan chose to rename the bus family to `health` (`health.beacon/snapshot/event`, `spec/messages/health.yaml`); transports, publisher, config section and process name keep `monitor`. Design doc updated throughout. |
| I10 | A1 | Adding a spec family trips four cross-cutting gates: the pinned family list and message count, the audit-replay lexicon (every top-level enum value needs a gloss), and the builder-adoption gate (every message needs a `make_*` producer in `src/`). | Lexicon glosses for `health.event` `kind`/`severity`; count 121 → 124; a self-expiring `PENDING_ADOPTION` set in `test_msgen_adoption.py` that A2 (beacon) and B1/B3 (snapshot/event) must empty, enforced by a guard test. |
| I8 | A1 | `pm-msgen lint` dies with a raw PyYAML traceback on a YAML syntax error (e.g. a `>` block scalar inside a flow mapping) instead of a `SpecError` naming the file. | Follow-up, out of scope for this plan. |
