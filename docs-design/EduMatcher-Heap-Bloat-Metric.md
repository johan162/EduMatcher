# Heap bloat metric replaces heap garbage % (WP-HB01)

## Problem

`pm-monitor` raised hundreds of `threshold heap_garbage_pct WARN 74.7 > 50 on ECL`
events (933 WARN + 39 CRIT in 100 minutes of the overnight sim, 265 distinct
symbols), each needing acknowledgement in `pm-log-gui`.

## Root cause

`heap_garbage_pct = 100 × (heap_entries − live_entries) / heap_entries` is not a
health signal, because `OrderBook._compact_heaps` is *designed* to let garbage
build up: it rebuilds the heaps only when they exceed `2 × live + 64` entries.
A perfectly healthy book therefore oscillates between 0 % and a ceiling of

    (L + 64) / (2L + 64)     L = live entries

| L | 18 | 30 | 100 | 300 | 1000 |
|---|----|----|-----|-----|------|
| ceiling | 82 % | 76 % | 62 % | 55 % | 52 % |

The default bands (WARN 50, CRIT 80) sit *inside* that healthy range for every
book size, so the rule fires in normal operation and flaps (903 "cleared"
events). The `MIN_HEAP_ENTRIES = 100` gate (I68) papered over small books only.

Forcing Python GC is irrelevant: the dead entries are strongly referenced by the
heaps; only `_compact_heaps` frees them, and it already runs.

## Design

Measure what the rule was meant to detect — *is compaction keeping up?* — as the
overshoot past the compaction bound:

    heap_bloat_ratio = heap_entries / (_COMPACT_FACTOR × live_entries + _COMPACT_SLACK)

* Healthy: ≤ 1.0 (compaction fires the moment the ratio would exceed 1.0).
* Independent of book size, so one band fits every book; no minimum-sample gate
  (the slack term makes small books read ≈ 0.05).
* Defaults: **WARN 1.5, CRIT 3.0**. Above 1.0 means a retire-without-compact
  path exists; 3× the bound means compaction has effectively stopped.

`BookStats` owns the formula (`heap_bloat_ratio` property) next to the constants.

### Engine fix found while designing

`_compact_heaps` is called only from `_purge_from_indexes`. Two other paths
retire a heap entry and push a replacement without compacting: an amend that
loses priority, and `_reinsert_iceberg`. A book that only amends or refills
icebergs can grow its heaps without bound until some order is removed. The new
metric would (rightly) flag it, so both paths now call `_compact_heaps()` after
the push, making "ratio ≤ 1 after every mutation" an invariant that a test pins.

### Breaking changes (pre-1.0, no compatibility code)

* Gauge `engine.book_heap_garbage_pct` → `engine.book_heap_bloat_ratio`
  (`engine.book_heap_entries` stays).
* `health.yaml` `BookStats.heap_garbage_pct` (percent, 0–100) →
  `heap_bloat_ratio` (dimensionless, ≥ 0); regenerated models (`make msgen`),
  REST model, OpenAPI.
* Monitor threshold rule `heap_garbage_pct` → `heap_bloat_ratio`
  (`--monitor-threshold heap_bloat_ratio:1.5:3`); `MIN_HEAP_ENTRIES` removed.
* Config files carrying `heap_garbage_pct` are rejected as an unknown rule —
  old configs are not migrated.
* Web: dash-gui (types, bridge default band, Books row, Book drawer, metric
  name, fixtures/tests), config-gui (schema types/defaults, Monitor tab,
  YAML comments).
* Docs: operator guide (005, 010, 060), reference manual, protocol message
  reference, architecture book 010, design docs
  (`EduMatcher-Operator-Dashboard.md`), shipped `engine_config.*`,
  `ref_data` examples, CHANGELOG.

## Work items

- [x] H1 Engine: `BookStats.heap_bloat_ratio`; compact after amend/iceberg refill; tests (incl. invariant under random amend/refill/cancel mix).
- [x] H2 Spec + generated models (`health.yaml`, `make msgen`), engine gauge, `activity.py` record.
- [x] H3 Monitor rule: rename, new default band, drop `MIN_HEAP_ENTRIES`; config/CLI/completion/config-gen/shipped YAML+JSON.
- [x] H4 Python tests updated + new (rule fires only on bloat, not on 76 % garbage).
- [x] H5 Web: dash-gui and config-gui (+ their tests).
- [x] H6 Docs (CHANGELOG is written at release); `docs/examples/ref_data` comments updated.
- [x] H7 Gates (2026-11-01): `make _check` clean, pytest 12030 passed, vitest dash-gui 504 / config-gui 180, tsc clean. **e2e skipped: the live sim holds the exchange ports — rerun `make test-e2e` with the sim stopped.**
- [ ] H8 Running sim: restart pm-monitor with the new defaults and confirm no more garbage events.
