# User Guide review — first-impression chapters (2026-09-20)

Scope: `docs/user-guide/000-getting-started.md`, `001-learning-path.md`,
`005-installation.md`, `010-configuration.md`, `020-config-verifier.md`.
Every finding below was checked against the actual source in the repo
(mounted at `$HOME/mnt/EduMatcher` on your machine), not against the docs'
own internal consistency alone. Findings are grouped by chapter, most
severe first within each group.

---

## 000-getting-started.md

### CRITICAL — `pm-opctl-cli start`/`list` sample transcripts don't match real output
Two separate problems in the same two code blocks:

1. **Process names are wrong.** The doc's `start` transcript shows bare names
   (`market-data-gwy`, `post-trade-gwy`, `drop-copy-gwy`, `api-desk-gwy`,
   `api-dashboards-gwy`). The real `default` profile (`src/edumatcher/emo/cli.py`,
   `DEFAULT_PROCESSES`) uses names like `"market-data-gwy (md-gwy)"`,
   `"post-trade-gwy (ralf-gwy)"`, `"drop-copy-gwy (dc-gwy)"` — `cmd_start`
   prints `f"  started {name} (pid {pid}): ..."` using that literal string, so
   real output includes the parenthetical suffix the doc's transcript omits.
   Same problem carries into the `list` transcript, which also renders `name`
   verbatim into a `{name:<20}` field — a 24-character name like
   `market-data-gwy (md-gwy)` will not fit the 20-column field the doc's table
   implies.
2. **Separator line length is wrong.** `list_profile()` (`emo/cli.py`) always
   prints `"-" * 94` regardless of terminal width; the doc's sample shows a
   73-dash line. Minor on its own, but combined with (1) the whole transcript
   reads as hand-typed rather than a real capture, which for a first-impression
   chapter under-delivers on "trust this exactly."

Fix: either re-run `pm-opctl-cli start` / `list` for real and paste the actual
output, or shorten `DEFAULT_PROCESSES` display names in code — but that's a
product decision, not a docs-only fix, since the parenthetical is presumably
there to disambiguate the gateway's underlying binary from its role name.

### LOW — `pm-viewer --s <SYMBOL>` uses an unconventional flag form
`--s` is not a defined option — `pm-viewer` defines `--symbol`/`-s`
(`src/edumatcher/viewer/main.py:753-759`). `--s` happens to work only because
argparse resolves it as an unambiguous prefix of `--symbol` (verified by
running it). It is not documented, canonical, or guaranteed stable if another
`--s*` flag is ever added to `pm-viewer`. Every other reference to this command
in the guide (learning-path.md, and elsewhere in this same file) correctly
uses `--symbol`. Recommend changing this one instance to `--symbol AAPL` or
`-s AAPL` for consistency and safety.

### Confirmed correct (spot-checked, no action needed)
- `EDUMATCHER_DATA_DIR` resolution algorithm (env var → source-checkout →
  installed default) matches `src/edumatcher/config.py` exactly, including the
  three defaults given.
- `tick_decimals: 2` → `150.25` stored as `15025` — confirmed against
  `_config_ticks`/`to_ticks_exact_at` and the dataclass default.
- `ZMQ=1` making the bus ports available outside the container — confirmed in
  `deployment/docker/Makefile` and `compose.yaml`.
- The API-gateway API-key claim (`api_key` required per credential entry in
  `engine_config.yaml`) matches `api_gateway/config.py`.
- `pm-config-gen --symbols/--gateways/--output/--seed-mm-mid-range/
  --seed-last-prices-from-mm` all exist as documented.
- `s3-basic` as the `pm-setup` default, and `edumatcher.sh shell` /
  `config`/`start`/`stop`/`status`/`logs`/`mounts`/`urls` subcommands, all
  confirmed against source.

---

## 001-learning-path.md

No independent factual errors found beyond what's shared with
005-installation.md (curl one-liner, `edumatcher.sh config s3-basic-nomm`,
`s3-nominal`, `pm-cverifier`, `pm-config-gen` flags — all confirmed real).
The stage structure, checkpoints, and troubleshooting table commands
(`./edumatcher.sh status/logs/mounts/urls`, `pm-config-show`) all check out
against source. This chapter is in solid shape.

---

## 005-installation.md

### CRITICAL — Gateway port diagram assigns the wrong port to nearly every gateway
The "two planes" mermaid diagram states:
```
pm-alf-gwy 5560 · pm-md-gwy 5570
pm-balf-gwy 5580 · pm-ralf-gwy 5590
pm-dc-gwy 5600 · pm-log-srv 5601/5602
pm-api-gwy 8080/8081
```
Actual ports, from `src/edumatcher/gateway_ports.py` (confirmed independently
via `emo/cli.py`'s `DEFAULT_PROCESSES` tcp-healthcheck addresses):

| Gateway | Doc says | Actually is |
|---|---|---|
| `pm-alf-gwy` | 5560 | **5565** |
| `pm-balf-gwy` | 5580 | **5560** |
| `pm-ralf-gwy` | 5590 | **5580** |
| `pm-dc-gwy` | 5600 | **5590** |
| `pm-log-srv` | 5601/5602 only | **5600 (TCP)** + 5601/5602 |
| `pm-md-gwy` | 5570 | 5570 ✓ (correct) |

Everything except `pm-md-gwy` is shifted, and `pm-log-srv`'s primary TCP port
(5600) is missing entirely. Anyone connecting to "port 5560 for order entry"
per this diagram would actually reach `pm-balf-gwy` (binary protocol), not
`pm-alf-gwy` (text protocol) — a real, embarrassing failure mode for a
first-impression chapter.

### HIGH — Published port range shown as contiguous, but it isn't
Same diagram: `published 5560-5600, 8080-8081 via BIND_ADDR`. The actual
compose file (`deployment/curl/compose.yaml`) publishes exactly `5560, 5565,
5570, 5580, 5590, 5600, 8080, 8081` — large gaps in between are not published.
Stating a range implies every port in it is open. Combine with the mapping
error above and a reader has no reliable picture of what's actually reachable.

### HIGH — VM mode's data directory is misidentified
Doc's directory table says the VM's data lives at `/home/ubuntu/session`.
Actually `deployment/vm/mknode.sh` sets `EDUMATCHER_DATA_DIR=
/home/ubuntu/.local/share/edumatcher` in `.bashrc` — the same installed
default as pipx mode. `/home/ubuntu/session` is just the working directory
`pm-setup` happens to be run from, not the data directory.

### HIGH — `USE_PROXY_CA`/`CA_CERT_FILE` build args are documented but do nothing on the path described
The doc says these vars let you install a corporate CA cert for config-gui.
`compose.config-gui.yaml` builds from `web-apps/config-gui/Dockerfile`, which
declares no such `ARG` — only the separate, unused `Dockerfile.proxy` does.
Following the documented `make up-all CONFIG_GUI=1` flow silently ignores a
corporate CA cert a reader supplies this way.

### MEDIUM — install.sh downloads 4 files, doc says 3
Doc: "Downloads `compose.yaml`, `edumatcher.sh` and `.env.example`." Actual
`deployment/curl/install.sh` also downloads `compose.zmq.yaml`. Not wrong in
spirit, but incomplete for a paragraph whose point is "everything comes from
one pinned commit."

### MEDIUM — "twelve ready-made configurations" undercounts by half
The doc enumerates `{one,three,ten,thirty} x {basic,nominal,complex}` = 12.
`deployment/curl/edumatcher.sh`'s `EXAMPLES` list (and `pm-setup`'s own
docstring) documents 24 valid names — the 12 stated plus a `-nomm` variant of
each (e.g. `s3-basic-nomm`, used correctly elsewhere in this same chapter
set, in learning-path.md Stage 1). The enumeration should mention the `-nomm`
suffix explicitly.

### MEDIUM — `TZ` default documented as `UTC` for the source-build path, but ships as `Europe/Stockholm`
`deployment/docker/.env.example` (used by `make build`/`make up-all` when no
`.env` exists yet) sets `TZ=Europe/Stockholm`, not `UTC`. The curl-install
`.env.example` does correctly default to `UTC` — this is specific to the
from-source path.

### MEDIUM — `NPM_REGISTRY` can't actually be set the way the doc says
Doc: "export it before `make up-all`." `compose.guis.yaml`'s build `args:` for
the three GUI images list `NPM_STRICT_SSL`/`HTTP_PROXY`/`HTTPS_PROXY`/
`NO_PROXY` but not `NPM_REGISTRY`, even though the Dockerfiles declare and use
`ARG NPM_REGISTRY`. A shell-exported `NPM_REGISTRY` is silently dropped before
it reaches the build.

### LOW — build success message shown as a literal string, but it isn't
Doc shows the literal line `Installing local wheel: /tmp/wheel/edumatcher-<version>.whl`.
The Dockerfile actually globs `*.whl`, so the real line includes the wheel's
full build tag/platform suffix, not a clean `<version>.whl`.

### Note — "10-step developer release checklist" not present in this chapter
The task description mentioned this, but it isn't actually in
005-installation.md as currently written — nothing to check here; if it's
meant to be here, it's missing outright.

### Confirmed correct
All `edumatcher.sh` subcommands; `make` targets and flags (`build`, `up`,
`up-all`, `ZMQ=1`, `SSH=1`, `CONFIG_GUI=1`, `CONFIG=`, `PROFILE=`); backend
Dockerfile build args; most `.env` variables (`EM_VERSION`, `GHCR_OWNER`,
`EM_CONFIG`, `BIND_ADDR`, GUI ports, etc.); data-directory resolution for pipx
and Poetry modes; `<DATA_DIR>` file layout; `pm-setup` flags; `mknode.sh`
flags; `pm-help --completion`, `pm-engine --log-level`, `pm-audit-cli events`.

---

## 010-configuration.md (3272 lines — reviewed in two halves)

### CRITICAL — `--cb-levels` documents a 4th, non-existent `RESUMPTION_MODE` field
Doc (line ~275, example at ~966): `--cb-levels NAME:SHIFT[:HALT_MINS[:RESUMPTION_MODE]]`
with values `AUCTION`/`CONTINUOUS`. The real parser
(`src/edumatcher/config_gen/cb_spec.py::parse_cb_spec`) only accepts 2–3
colon-separated parts and raises `ValueError` on a 4th. There is no
`resumption_mode` field anywhere in `CircuitBreakerConfig`/`CircuitBreakerLevel`.
This project's own `docs/user-guide/120-risk-controls.md:553` confirms the
field "has been removed." **The example command shown at line 966 would crash
if a reader ran it as written.** This is the single most damaging finding in
the whole review — a copy-pasted command from the configuration chapter fails.

Two more stale leftovers from the same removed feature, lower severity:
- Line ~970: a heading, "Per-symbol `CONTINUOUS` resumption override,"
  describing a mechanism that never existed as a per-symbol override (the
  example under it doesn't even use `CONTINUOUS`).
- Line ~962: "(no auction on L2 halt recovery)" — per `120-risk-controls.md`,
  every halt recovery always runs the reopening auction regardless of the old
  field.

### HIGH — Self-contradictory "Missing-file Behavior" table
Line ~1144: a table gives a "Missing explicit `--config`" column for both
`pm-engine` and `pm-scheduler`. Neither process has a `--config` flag at all
(confirmed against `build_parser()` in both `engine/main.py` and
`scheduler/main.py`) — and the chapter says so itself, correctly, earlier:
"No process accepts a config path, so it is not possible to start two of them
against different files." The table directly contradicts the chapter's own
preceding sentence.

### MEDIUM — "Mandatory Fields" section overstates the `market_maker_quotes` requirement
Line ~2378 (and repeated in the Formal Specification's cross-field rules,
line ~3091): states `market_maker_quotes` becomes mandatory unconditionally
whenever a `MARKET_MAKER` gateway exists. `config_loader.py` actually gates
this on `require_mm_seed_quotes` (default `true`, can be set `false`) — and
the chapter documents that override correctly elsewhere (line 215). The
normative "Mandatory Fields" statement and the appendix rule should both
mention the escape hatch.

### MEDIUM — "Formal Specification" appendix (the doc's own designated ground truth) omits real fields
This is the reference table readers are meant to treat as authoritative, so
gaps here matter more than elsewhere:
- Top-level fields table (line ~2878) omits `require_mm_seed_quotes`,
  `country`, `indices`, `auction_indicative_interval_sec` — all real fields
  parsed by `load_engine_config()`.
- `symbols.<SYMBOL>` fields table (line ~3017) omits `order_limits`
  (max_order_qty/max_order_value) and `outstanding_shares` entirely.
- Cross-field validation rules (line ~3086) documents the rejection of
  `risk_controls.levels.<LEVEL>.circuit_breaker` but not the identical,
  equally real rejection of `risk_controls.levels.<LEVEL>.order_limits`
  (same code path, same style of error message in `config_loader.py`).

### LOW — undocumented cverifier check `M026` (and the `country` key it validates)
`src/edumatcher/cverifier/layer3_semantic.py` implements a real `M026` warning
for an unrecognized `country` value, and `country` itself is never documented
as a config key anywhere in this chapter's check catalogue or field tables.

### LOW — `S065` check code is reused for two unrelated conditions in source, but the doc only documents one
The doc's catalogue lists `S065` as "circuit_breaker/.levels not a mapping."
`layer2_schema.py` also emits `S065` for an unrelated `'country' must be a
non-empty string when provided` check. A reader who sees `S065` referencing
`country` in real output won't find that meaning in the doc's table.

### Confirmed correct — extensive
Both review passes independently verified (down to exact defaults, enum
values, and in several cases verbatim message text) essentially everything
else: all CLI option defaults for `pm-config-gen` (snapshot interval, quote
history, MM spread/qty, schedule times, gateway ports/timeouts, log-server/
LALF-PS fields); every other enum (`OrderType`, `TIF`, `SmpAction`,
`ParticipantRole`, `ComboType`, `DisconnectBehaviour`,
`QuoteRefreshPolicy`); the 24 `--example` shorthand names' characteristics;
collar/order-limits field paths and the "no risk-level form" claim for order
limits; the "nine sections" compiled-artifact claim; the four cverifier
layers; numeric defaults throughout (snapshot_interval_sec 0.5,
quote_history_maxlen 30, collar 20%/2%, CB ladder 7/13/20%, ACE reopening
defaults, depth_snapshot_tolerance_ticks 100, drop-copy port 5557); the
combo-leg price-required-by-order-type rule; the "Verifying the Deployed
Artifact" section (content digest vs. schema-version vs. staleness checks).

---

## 020-config-verifier.md

### HIGH — Sample "Risk Summary" output is missing a real line the tool always prints
The doc's example transcript (and its accompanying field-reference table)
never shows or mentions an "Order limits" line. `formatter.py::format_text`
unconditionally prints one, right between "Collars" and "Circuit breakers."
Anyone comparing a real run to this doc will see an extra, unexplained line.

### HIGH — Same example is missing the "(built-in defaults)" suffix it should have
The example's circuit-breaker numbers (L1=7%/5min, L2=13%/15min,
L3=20%/rest-of-day) exactly match the code's hardcoded defaults, which only
apply when `circuit_breaker_defaults` is absent from the config — and that
is exactly the condition under which `risk_summary.py` appends
`" (built-in defaults)"` to the line. The doc's sample is missing that
suffix, meaning the example doesn't reflect what a real "using the defaults"
run actually prints.

### HIGH — `M026` check exists in source but is completely undocumented
Same finding as in 010-configuration.md above — `M026` fires a warning when
`country` isn't recognized by the `holidays` package; neither the check nor
the `country` key are documented in this chapter's own check catalogue, even
though the catalogue's stated range is "`M001`–`M025`" (which is simply
wrong — `M026` exists and is reachable).

### MEDIUM — `S065` overloaded for two unrelated conditions (see above); only one documented in this chapter's own catalogue.

### MEDIUM — "CLI Reference" block is styled as literal `--help` output but isn't
The doc's code block uses "Arguments:" / paraphrased help text. Real argparse
`--help` says "positional arguments:", includes `-h/--help`, and uses
slightly different (though not materially different) wording for each flag's
help string. All the flags themselves (`--format`, `--level`, `--no-color`,
`--strict`, `--help`, `--version`) are correct in name, default, and choices —
this is a presentation/paraphrase issue, not a functional one, but a reader
who pastes `pm-cverifier --help` and diffs it against the doc will see a
mismatch and may doubt the rest of the chapter.

### Confirmed correct — extensive
All CLI flags and their defaults/choices; the exit-code table (0/1/2) and
`--strict`'s WARN→2 promotion; all three Quick Start commands (parse
successfully against the real parser); the M013 message and suggestion text
(verbatim match, including a full YAML snippet); every other Y/S/M/C check
code spot-checked (S078, S086, S110/S112, M001, M011, M017, M018/M022,
M014/C010, C001–C013, C007/C012) matches source exactly in severity and
firing condition; the `api_gateways` `gateway_id: null` example behaves as
described; `log_server.retention_days` convention (0 and null both mean
unbounded).

---

## Summary for prioritization

If you fix nothing else before someone reads these chapters, fix these three
— each one is a command or number a reader will copy verbatim and have fail
or silently mislead them:

1. **010-configuration.md** — the `--cb-levels ...:RESUMPTION_MODE` example
   (line ~966) will crash if run. Delete the 4th field and the two
   `CONTINUOUS`/resumption-mode leftovers nearby.
2. **005-installation.md** — the gateway port diagram has almost every port
   wrong. Regenerate it from `src/edumatcher/gateway_ports.py` directly.
3. **000-getting-started.md** — the `pm-opctl-cli start`/`list` sample
   transcripts don't match what the tool actually prints (names, column
   widths). Re-capture real output rather than hand-typing it.

Everything else is real but lower-stakes: stale/incomplete reference tables
(the "Formal Specification" appendix, the M-code catalogue), a few `.env`/
build-arg claims that are technically true in isolation but don't survive the
documented workflow, and cosmetic paraphrase-vs-literal mismatches in
`--help` output.
