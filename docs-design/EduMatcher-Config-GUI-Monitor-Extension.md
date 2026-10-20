# EduMatcher — `config-gui` Extension: the `monitor` Block and Full Block Coverage

Version: 0.1.0

Date: 2026-10-19

Status: Implemented (see §8)

Extends [`EduMatcher-Config-GUI.md`](EduMatcher-Config-GUI.md). Context:
the operator dashboard plan
([`EduMatcher-Operator-Dashboard.md`](EduMatcher-Operator-Dashboard.md))
added the top-level `monitor` block (WP-A3) and `pm-config-gen --monitor`
(after WP-B7); `config-gui` knew nothing of either.

## 1. Requirements

1. `config-gui` edits the `monitor` block, available at the **Intermediate**
   persona.
2. Every major configuration block the engine and its processes read is
   supported by `config-gui`; missing support is added.
3. A **top-level** checkbox controls `--comment-default-config-fields` (the
   commented defaults header), visible whatever tab is open.

## 2. Coverage audit (2026-10-19)

The Python side is the authority: `config_show.extract.KNOWN_TOP_LEVEL` (the
recognised top-level sections), the verifier's accepted-key tables
(`cverifier.layer2_schema._*_KEYS`, pinned to the loaders by tests) and the
`--comment-default-config-fields` shape (pinned to both). Every key was
looked up in the GUI codec (`packages/yaml-codec/src/build.ts`, `parse.ts`).

| # | Finding | Kind |
|---|---|---|
| G1 | `monitor` — not modelled; an imported block survived only as unmapped passthrough, uneditable | Missing block |
| G2 | `locale` — the GUI wrote a **top-level** `country`, which no Python loader reads: a config exported with `Germany` ran pm-scheduler on Sweden's holidays. `locale.session_timezone` not modelled | **Bug** + missing field |
| G3 | `auction_indicative_interval_sec` — not modelled | Missing field |
| G4 | `log_server.client` (`connect_timeout_sec`, `failover_timeout_sec`, `failover_dir`) — read by every process; not modelled | Missing sub-block |
| G5 | `api_gateways.<name>`: `clearing_db`, `market_data_cache_sec`, `engine_pull_addr`, `engine_pub_addr`, `index_pull_addr`, `index_pub_addr` — not modelled | Missing fields |
| G6 | `ENGINE_DEFAULT_MM_MAX_SPREAD_TICKS = 10`; the engine's default has been 20 since commit `6bb80490`. An import of a file without `mm_max_spread_ticks` read 10 and could write it back | **Bug** |
| G7 | The TypeScript copy of the comment-defaults text (`defaultFieldComments.ts`, "ported verbatim") had drifted by 274 diff lines: no `locale`, `require_mm_seed_quotes` or `monitor` entries, a stale schedule shape, wrong defaults (`mm_max_spread_ticks: 10`, ALF `max_connections: 64`), an obsolete `api_gateways.session_timezone` | **Bug** (misleading output) |
| G8 | The comment-defaults switch existed only on the Review tab | Requirement 3 |
| G9 | Nothing outside the `MAINTENANCE:` comments tied the TypeScript mirrors to Python, which is how G2, G6 and G7 happened | Process gap |

Every other top-level section and every other key matched.

## 3. The monitor block in `config-gui`

### 3.1 Placement

A new tab **Health Monitoring** (`/monitor`), `minPersona: "I"`, between
*Auxiliary Gateways* and *Engine Tuning*. Not a sub-tab of Auxiliary
Gateways: `monitor` is not a gateway, and every process reads it.

### 3.2 Fields by persona

| Field | Persona | Control |
|---|---|---|
| Write `monitor` section (`include`) | Intermediate | Switch; off = block omitted, every process runs on the defaults (the text says so — it does not disable monitoring) |
| `enabled` | Intermediate | Switch; off = no beacons, pm-monitor idles |
| `beacon_interval_sec` | Intermediate | Number (> 0) |
| `hung_after_sec` | Intermediate | Number (> beacon interval) |
| `silent_after_beacons` | Intermediate | Integer (> 0) |
| `retention.raw_hours`, `retention.minute_days` | Intermediate | Integers (> 0) |
| `thresholds.<rule>` × 7 | Intermediate | A table: rule, meaning, warn, crit, a "lower is worse" note for `disk_free_pct`, and a reset-to-default action per row |
| `bind_address`, `host`, `pull_port`, `pub_port` | Expert | Text / port, with the bind-vs-host explanation |
| `book_metrics_interval_sec` | Expert | Number (> 0) |

Help text per field mirrors the operator guide's *Health Monitoring* chapter,
and each names its `pm-config-gen` flag (`--monitor-*`), as the other panels
do.

### 3.3 Model and codec

- `EngineConfigDraft.monitor: MonitorConfigDraft` — `include` plus every
  field; thresholds as `Record<rule, {warn, crit}>` over a fixed rule list.
- Defaults `DEFAULT_MONITOR`, `MONITOR_THRESHOLD_RULES`,
  `INVERTED_THRESHOLD_RULES` in `schema/src/defaults.ts`, pinned to
  `MonitorConfig()` by a Python test (§6).
- Build: when `include`, the whole block, every field (as `pm-config-gen
  --monitor` writes it). Parse: a `monitor` block sets `include` and every
  given field over the defaults; absent fields keep the loader's defaults.

### 3.4 Diagnostics (mirror pm-cverifier)

| Rule | Severity | Mirrors |
|---|---|---|
| `monitor-threshold-order` — warn strictly below crit (above for `disk_free_pct`) | error | M029 |
| `monitor-hung-vs-interval` — `hung_after_sec > beacon_interval_sec` | error | M030 |
| `monitor-host-unreachable` — host cannot reach bind (neither equal, nor a wildcard bind, nor both loopback) | warning | M031 |
| `monitor-ports-equal` — `pull_port ≠ pub_port` | error | M018 (self) |
| `session-timezone-unknown` — not an IANA zone (§4, G2) | error | loader |
| Port collision — the monitor's two ports join the existing `port-collision` check, **also when the block is not written** (pm-monitor then binds 5610/5611 by default), unless `enabled: false` | warning | M018 |

## 4. The other gaps

| # | Change | Persona | Where |
|---|---|---|---|
| G2 | `locale: {country, session_timezone}` written (each only when it differs from its default, as `pm-config-gen`) and read on import. A top-level `country` is no longer read — no Python loader reads it — so a file that has one keeps it only as unmapped passthrough. New field *Session time zone* (IANA name; diagnostic `session-timezone-unknown` checks it with `Intl`) | Intermediate (country stays Beginner) | Basics → Locale (the section already held Country) |
| G3 | `auction_indicative_interval_sec`, written when it differs from 1.0 | Expert | Engine Tuning |
| G4 | *Log client (every process)* sub-section: connect timeout, failover timeout, failover directory; `client` written when any differs from its default | Expert | Auxiliary Gateways → Log Server |
| G5 | API instance: `clearing_db`, `market_data_cache_sec`, and the four bus addresses (written when they differ from their defaults) | Expert | Auxiliary Gateways → API |
| G6 | `ENGINE_DEFAULT_MM_MAX_SPREAD_TICKS = 20` | — | defaults.ts |
| G7 | `defaultFieldComments.ts` regenerated from `cli_comments.py` by `tools/gen_config_gui_comments.py`; the TypeScript renderer's section order and hints realigned with `renderer.py` (`Locale` section and its hints, `dc_gateway`, `monitor`) | — | yaml-codec |

## 5. Top-level comment-defaults checkbox (G8)

A labelled checkbox **"Comment defaults"** in the top bar, next to the
persona selector, bound to `draft.output.commentDefaultFields` — the field the
Review tab's switch already uses, so the two always agree. Its tooltip: *Add
a commented-out header with every optional section at its default values,
ready to uncomment — `pm-config-gen --comment-default-config-fields`.* It is
stored with the draft, so an exported file and a re-opened session agree.

## 6. Drift guards (G9)

A Python test, `tests/test_config_gui_mirrors.py`, reads the TypeScript
sources (no Node needed) and fails when they fall behind:

1. Every `KNOWN_TOP_LEVEL` section is written by `build.ts` and recognised by
   `parse.ts`.
2. Every key of the verifier's process-block, API, log-client and monitor
   tables appears in `build.ts`.
3. `defaultFieldComments.ts` equals `build_default_engine_field_comment_lines()`
   line for line (regenerate with `tools/gen_config_gui_comments.py`).
4. The default constants in `defaults.ts` equal their Python sources
   (`config_gen.defaults`, `MonitorConfig()`, `LogClientConfig()`, the engine
   loader's `_DEFAULT_*`).

## 7. Compatibility

No backwards compatibility is provided, by policy:

- **Autosaved drafts** from the previous version are not migrated: the
  storage key moves to `edumatcher.config-gui.draft.v3`, so an old draft is
  simply no longer offered for restore.
- **Files with a top-level `country`** (written by earlier `config-gui`
  versions) are not converted; that key was never read, so re-select the
  country after import.
- **Exports** change in exactly two ways for an existing config: `country`
  is now under `locale` (the fix), and the new fields appear only when set.
- `npm run verify:python` (the golden check through the real Python loader)
  now also runs `compile_config()` — every section's loader and the
  verifier's blocking checks — over a new `every-block.yaml` fixture that
  sets every new field to a non-default value.

## 8. Implementation record

Implemented on 2026-10-19 together with this document: schema, codec,
diagnostics, the Health Monitoring tab, the other panels, the top-bar
checkbox, the Python mirror test, the generator script, vitest coverage,
and the operator-guide `config-gui` chapter. The tabs were checked rendered
in headless Chrome at Intermediate and Expert (fields by persona, M029/M031
in the drawer, the time-zone error on Basics, the log-client section).
