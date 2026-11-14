# pm-cverifier / pm-config-gen Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/cverifier/` and `src/edumatcher/config_gen/` at
`7d4a63d2` (v0.79.0).

pm-cverifier: `cli.py` (202 lines), `layer1_yaml.py` (114, parse and
`include:`), `layer2_schema.py` (3 433, schema), `layer3_semantic.py` (1 400,
cross-field), `layer4_complete.py` (434, advisories), `formatter.py` (276),
`risk_summary.py` (191), `models.py` (65), `helpers.py` (45).

pm-config-gen: `cli.py` (2 444), `cli_parser.py` (1 472, argparse),
`builder.py` (1 087), `cli_comments.py` (1 166, the
`--comment-default-config-fields` text), `renderer.py` (327),
`warnings.py` (219), `symbol_spec.py` (230), `gateway_spec.py` (85),
`defaults.py` (175), `cb_spec.py` (45), `risk_spec.py` (44).

The verifier is the gate of `pm-config-deploy` (`config_deploy.validate`,
`config_deploy.py:171-181`, where any ERROR refuses the deploy) and of
`pm-new-symbol` (`new_symbol/install.py:15`). pm-config-gen writes the YAML
that both read.

The following were read only where they decide these tools' behaviour, and
were not reviewed as code of their own: `config_deploy.compile_config`, the
engine loader (`engine/config_loader.py`), the gateway, log-server and
monitor loaders, `config_include.load_config_mapping`, pm-scheduler's
`_validate_schedule_config` and pm-index's `config_loader`/`calculator`.

**Focus:** correctness, edge-case handling, performance, and whether the
comments, help texts, the `pm-help` registry and the operator guide's
`part-2-configure/010-the-configuration-workflow.md` and
`020-config-verifier.md` say what the code does.

**Previous work:** `docs-design/EduMatcher-Config-Verifier.md` and
`EduMatcher-config-generator.md` (the designs); the 2026-11-01 operator-guide
audit (commit `d99181c8`: C004 and the Risk Summary breaker line, M003's
effective limit, C013 under the data directory, the `--combo` and
`--session-timezone` help); and the config-include work (`include:`, Y005,
`origin_of` attribution, `--split`, `--api-keys-for` with a 0600 keys file).
Their fixes are in place and are not repeated here. Two For-Later items found
in the training-guide review fall inside this scope and are taken over here:
**L004** (the `Validate with` hint, now D6) and **L005** (the per-layer counts,
now C10).

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with a scratch script against the tree at `7d4a63d2`, driving
the real entry points: `pm-config-gen`, `pm-cverifier`,
`pm-config-deploy --check`, `cverifier.cli.run_layers` and the loaders that
`compile_config` calls. One script is a **differential harness**. It takes a
valid configuration, replaces one leaf at a time with each of `true`, `-1`,
`0`, `"x"`, `1.5`, `null`, `[]`, `{}`, `1e30`, `.nan` and `.inf` (or deletes
it), and compares the verifier's verdict with what the ten loaders of
`compile_config` do. It was run on `docs/examples/ref_data/s3-complex-setup`
and on a pm-config-gen file with every optional section.
*(measured)* means timed on this host: `s300-sim-setup` (300 symbols, 113
participants) and synthetic files of 3 000 symbols × 1 000 participants with
5 or 20 market makers. The other findings are by inspection, with line
numbers given.

Status: **Done, uncommitted** (2026-11-14). Decisions Q1–Q5 taken as
recommended (§7). Last full suite: 14 327 passed, 1 skipped. Beyond the plan:
- The example generators and the 32 example YAML files were regenerated
  (WP-CFG05, WP-CFG09).
- WP-CFG06 has a follow-up (collars without a reference price).
- Training chapters 01, 02 and 17 and operator-guide chapter 005 were
  re-run and rewritten where the new behaviour changed their transcripts.
- New For-Later row L025.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver: the verifier's codes, verdict and exit code, the
   generated file, pm-config-gen's exit code and messages, and whether
   `pm-config-deploy --check` accepts the file.
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_cverifier.py`,
   `tests/test_config_gen_*.py`, `tests/test_config_generated_fields_reach_artifact.py`,
   `tests/test_config_deploy*.py` and `tests/test_new_symbol*.py` with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP with
   a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Verifier tests use `_write_yaml` and `_codes` in `tests/test_cverifier.py`
and call `run_layers`/`main` directly. pm-config-gen tests drive `main()`
through `_run_main(monkeypatch, argv)` in `tests/test_config_gen_integration.py`.
Agreement with the deploy gate is asserted by calling
`config_deploy.compile_config` on the file under test.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-CFG01 | A verifier OK means pm-config-deploy compiles | C1, D1 | Q1 | 1 d | ☑ | 2026-11-14 |
| 2 | WP-CFG02 | Neither tool crashes or accepts NaN/∞ | C3, C4 | — | 0.5 d | ☑ | 2026-11-14 |
| 3 | WP-CFG03 | What stops a process from starting is an ERROR | C2 | Q2 | 0.25 d | ☑ | 2026-11-14 |
| 4 | WP-CFG04 | pm-config-gen never writes what pm-config-deploy refuses | C6, D6 | Q3, WP-CFG01 | 0.5 d | ☑ | 2026-11-14 |
| 5 | WP-CFG05 | Every pm-config-gen option takes effect or is refused | C7, C8, C12 | Q4 | 0.75 d | ☑ | 2026-11-14 |
| 6 | WP-CFG06 | The Risk Summary states what the engine will enforce | C5 | WP-CFG01 | 0.75 d | ☑ | 2026-11-14 |
| 7 | WP-CFG07 | Counts, codes and messages agree | C9, C10, C11 | Q5 | 0.5 d | ☑ | 2026-11-14 |
| 8 | WP-CFG08 | Parse once; no per-quote participant scan | P1, P2 | — | 0.25 d | ☑ | 2026-11-14 |
| 9 | WP-CFG09 | Comments, help texts, pm-help and guide | D2–D16 | WP-CFG01–08 | 0.75 d | ☑ | 2026-11-14 |

Suggested order: **WP-CFG01 → WP-CFG02 → WP-CFG03 → WP-CFG04 → WP-CFG05 →
WP-CFG06 → WP-CFG07 → WP-CFG08 → WP-CFG09**.

- WP-CFG01 first: it gives the verifier the loaded `EngineConfig` that
  WP-CFG04 and WP-CFG06 build on, and it closes the largest gap.
- WP-CFG02 next: it removes the tracebacks that end both tools (and
  pm-config-deploy) with the "warnings" exit code.
- WP-CFG03 to WP-CFG05 wait for decisions Q2–Q4.
- WP-CFG09 goes last, so every text describes the final code.

Estimated sequential effort: about 5.25 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The verifier's **structure is sound**. Four layers run in order, a Layer 1 or
Layer 2 error skips the rest, and every check that ran reports
independently. Unknown keys are caught at every level (S121), and the
messages are specific and carry a suggestion. The process blocks for ALF,
RALF, CALF, API, BALF, log server and monitor are re-validated through their
own loaders, so these blocks cannot pass the verifier and then fail to
compile. M018's port inventory covers every listener, including the fixed
ones. The `include:` attribution works across split files. The verifier
never writes a file.

pm-config-gen's **parsers are careful**:
- Participant ids are validated.
- Index, combo and monitor flags are checked against each other.
- Seed prices are snapped to each symbol's own grid.
- Schedule times are checked for order.
- The API keys file is created 0600.
- Every file except the market-maker stub template is loaded by the engine
  loader before it is written.

The defects are in five places:

- **The verifier's OK is not the deploy gate's OK (C1).** The engine section
  has no loader backstop, and several checks treat an explicit `null` as
  absent. pm-config-gen's own default market-maker template therefore
  verifies as "engine can start", and `pm-config-deploy` then refuses it.
  Across two baselines, 298 single-leaf mutations pass the verifier and fail
  to compile.
- **Errors reported as warnings, and values nobody refuses (C2, C4).** An
  out-of-order schedule, an index constituent without a reference price, and
  `.nan` in `snapshot_interval_sec` or an index's `base_value` all deploy. The
  exchange then runs without a scheduler, without pm-index or without book
  snapshots.
- **Crashes (C3).** A `.inf`/`.nan` price or quantity, a non-UTF-8 file or a
  non-string index constituent ends pm-cverifier, pm-config-deploy (and
  pm-config-gen, for `--seed-mm-mid-range 10:inf`) with a traceback. The
  verifier then exits 1, which is the code it documents as "warnings only".
- **pm-config-gen (C6, C7, C8).** It writes files that deploy refuses
  (prefix participant ids, port collisions, ports above 65535), because it
  validates with two loaders and not with the gate. It silently drops
  options: `--schedule --weekend --holidays` without `--sessions-enabled`,
  every `--ace-*` without `--cb-levels`, abbreviated flags, and repeated
  `--symbols`/`--participants`.
- **The Risk Summary (C5).** It reports "no collar configured" for inline
  collars, prints the built-in circuit-breaker ladder in place of the
  configured one, and reports "not enforced" for participant-level
  market-maker obligations.

Severity key: **Med**: the verifier, the deploy gate and the processes
disagree about a file (a deploy refused after an OK, or a process that
refuses a deployed file), a figure in the Risk Summary is wrong, a crash, or
an option is silently dropped. **Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| C1 | Med | Verifier ↔ deploy | 298 single-leaf mutations pass the verifier and fail `compile_config`. pm-config-gen's default MM template (`bid_price: null`) verifies "engine can start", and deploy refuses it *(repro)* | CFG01 |
| C2 | Med | Severity | An out-of-order schedule (M006) and an index constituent without a reference price (C008) are warnings. Deploy accepts them; pm-scheduler exits FATAL, pm-index raises at start *(repro)* | CFG03 |
| C3 | Med | Robustness | Traceback on `.inf`/`.nan` in prices, quantities, `tick_decimals` and nanosecond fields, on a non-UTF-8 file and on a non-string index constituent; exit 1 (= "warnings"); pm-config-deploy crashes too *(repro)* | CFG02 |
| C4 | Med | Non-finite | `snapshot_interval_sec: .nan` deploys and the engine never publishes a book snapshot; `base_value: .nan` deploys and pm-index refuses to start; pm-config-gen writes both from `--snapshot-interval nan` and `--index-base-value OMX:nan` *(repro)* | CFG02 |
| C5 | Med | Risk Summary | Inline collar → "no collar configured ⚠"; one symbol's L1=5 %/1 min → "L1=7 % (5 min), L2=13 %, L3=20 %" for all; participant `enforce_mm_obligation: true` → "not enforced" *(repro)* | CFG06 |
| C6 | Med | Config-gen gate | pm-config-gen writes, with exit 0, files pm-config-deploy refuses: `TRADER1 TRADER10` (S084), `--alf-port 5570` with CALF (M018), `--post-trade-port 70000` *(repro)* | CFG04 |
| C7 | Med | Config-gen options | `--schedule --weekend --holidays` without `--sessions-enabled` writes `sessions_enabled: false` and no schedule, exit 0 *(repro)* | CFG05 |
| C8 | Low | Config-gen options | Dropped silently: `--ace-*`/`--cb-window-ns` without `--cb-levels`; `--snapshot 2.0` (abbreviation); repeated `--symbols`/`--participants`/`--cb-levels` (last wins); `--symbols AAPL aapl`; an invalid `--symbol-opts` value is a WARN, exit 0 *(repro)* | CFG05 |
| C9 | Low | Report | The per-layer lines count by layer, the verdict by severity: `Completeness: 5 advisories` beside `3 WARNINGS, 4 ADVISORIES` (L005). "skipped (fix schema errors first)" after a YAML error; a missing file prints an empty Risk Summary *(repro)* | CFG07 |
| C10 | Low | Codes | S065 means two unrelated things; S081 blames `alf_gateway` (absent) for the S084 prefix error, so one defect is two errors | CFG07 |
| C11 | Low | M032 | M032 warns on every file without `api_gateways`, so every minimal config exits 1; `pm-config-gen --api-gateway` output warns unless `--api-gateway-readonly-key` *(repro)* | CFG07 |
| C12 | Low | Config-gen | `--cb-levels L1:0.1:0` and `cb_halt_l1=0` write `halt_duration_ns: null`, a rest-of-day halt; help says "omit HALT_MINS" for that *(repro)* | CFG05 |
| P1 | Low | Parse | Layer 1 parses the file twice: 0.48 of 0.50 s on s300; 9.7 of 12.6 s on 3 000 symbols *(measured)* | CFG08 |
| P2 | Low | M003 | `_effective_max_spread` scans the participant list for every seed quote: 7.9 s for 60 000 quotes × 1 020 participants *(measured)* | CFG08 |
| D1–D16 | — | Texts | See §5 | CFG01, CFG04, CFG09 |

---

## 3. Correctness findings

### C1. A verifier OK does not mean pm-config-deploy compiles *(repro)* — Med

The verifier is the gate of `pm-config-deploy` (`config_deploy.py:171-181`).
`compile_config` then runs ten loaders (`config_deploy.py:203-218`) and turns
any exception into "could not be resolved". The verifier's own contract, in
`020-config-verifier.md:44`, is that it reports "every hard error that
`load_engine_config()` would raise, plus additional ones".

For the ALF, RALF, CALF, API, BALF, log-server and monitor blocks the
verifier calls the block's own loader (S080–S083, S085, S101, S131), so
these blocks cannot drift. The **engine section has no such backstop**, and
neither does `dc_gateway` (`layer2_schema.py:2410-2493`). The hand-written
checks miss these families:

| Family | Example | Verifier | `compile_config` |
|---|---|---|---|
| Explicit `null` read as "absent" | `bid_price:` (null), `sessions_enabled:`, `mm_min_qty:`, `history_file:` | OK | `market_maker_quotes[0] is invalid`, `must be a boolean`, … |
| Shape of a nested block | `risk_controls.levels.CORE: 0`, `…collar: 'x'`, `circuit_breaker_defaults.levels.L2: 1.5`, `schedule.weekdays: 0`, `engine_tuning: 'x'` | OK | `must be a mapping` |
| Unchecked engine fields | `engine_tuning.quote_history_maxlen: 0`, `circuit_breaker_defaults.reference_window_ns: 'x'`, `participants[0].description: 1`, combo leg `price: 'x'` | OK | `must be > 0`, `must be a string`, … |
| Type narrower in the loader | `dc_gateway.heartbeat_interval_sec: 1.5` | OK (S094 accepts any number) | `must be an integer` |
| `indices[n].constituents:` null or absent | | OK (`layer2_schema.py:1399-1401` skips it) | `must be a non-empty list` |

The harness counted 227 such mutations on `s3-complex-setup` and 71 more on a
pm-config-gen file with every optional section.

The most common way in is pm-config-gen's own default output. With a
`MARKET_MAKER` participant and no `--seed-mm-mid-range`, it writes
`bid_price: null` / `ask_price: null` stubs:

```
$ pm-config-gen --symbols AAPL --participants TRADER01 MM01:MARKET_MAKER --output engine_config.yaml
$ pm-cverifier engine_config.yaml
...
Verdict:  ⚠ 3 WARNINGS, 4 ADVISORIES — engine can start but review warnings      (exit 1)
$ pm-config-deploy --check engine_config.yaml
[ERROR] …/engine_config.yaml could not be resolved: Symbol 'AAPL': market_maker_quotes[0] is invalid
        Nothing was deployed.
```

The operator sees a verifier that says the file is fine, and a deploy that
refuses it with a single terse loader message, which is the trial-and-error
loop the verifier exists to remove (`020-config-verifier.md:33-38`). With
`--strict` in CI, the verifier passes files the deployment step then
refuses.

The opposite direction, verifier ERROR and compile OK (221 mutations), is
almost all intended strictness that this review keeps:
- M022: a credential whose `gateway_id` is not a participant.
- M029/M030: monitor band order, hung timeout above the beacon interval.
- S092/S096/S098: names and booleans the log-server and DC loaders do not
  type-check.
- M033: heartbeat and idle timeout too close.

The cases where a loader accepts a value it should not are recorded in §9
(L024).

**Fix.** See Q1: an engine-section backstop like the block backstops, a DC
backstop, and field checks for the explicit-null family. The null family
needs its own checks because it is what the pm-config-gen template produces,
and it deserves a message that names the field.

### C2. A schedule or index that stops a process is only a warning *(repro)* — Med

**M006** (`layer3_semantic.py:492-520`) reports schedule times out of order
as WARN. pm-scheduler validates the same order at start-up and exits on it
(`scheduler/main.py:319-327`, `1395-1400`: `log.critical("FATAL: invalid
schedule …"); sys.exit(1)`). Repro, with `continuous_start: "16:30"` before
`closing_auction_start: "16:00"`:

```
[M006] WARN  Schedule times are out of order in 'schedule.weekdays': continuous_start=16:30 >= closing_auction_start=16:00.
Verdict:  ⚠ 2 WARNINGS, 3 ADVISORIES — engine can start but review warnings
OK — …/engine_config.yaml compiles (1 symbol(s), 2 gateway(s))
scheduler: ['schedule time 16:00 is not strictly after the previous entry (schedule.mon, … schedule.fri)']
```

The exchange deploys and pm-scheduler then refuses to start, so no session
transition is ever sent. M025, the chain check, cannot catch this: it walks
the five fields in their fixed order, which is always a legal chain.

**C008** (`layer4_complete.py:271-312`) reports an index constituent without
`last_buy_price`/`last_sell_price` as WARN. pm-index raises at start-up for
exactly that (`index/config_loader.py:30-41`, `_reference_price`), and
pm-config-gen refuses to write it (`config_gen/cli.py:2151-2173`).

**Fix.** Both become ERROR (Q2). The codes and messages stay the same.

### C3. Both tools crash on non-finite numbers and other odd input *(repro)* — Med

Python's `float()` accepts YAML's `.inf` and `.nan`, and the checks convert
those values on to `int`:
- `int(float('inf'))`: `OverflowError`.
- `round()` inside `to_ticks_exact_at`, via S078 (`layer2_schema.py:174-179`).
- `int(hd)` in S033/S068 and `int(val)` in the MM checks.

Each raises outside every `except (TypeError, ValueError)`. The harness found
73 crashing mutations on one baseline and 48 on the other: prices, quantities,
`tick_decimals`, `outstanding_shares`, `halt_duration_ns`,
`reference_window_ns`, `random_end_max_ns`, `min_duration_ns`, the MM
obligation fields and combo leg prices. Other crashes:

- A non-UTF-8 file: `read_text` raises `UnicodeDecodeError`, which is not an
  `OSError` (`layer1_yaml.py:360-372`). Traceback.
- `indices[0].constituents: [[]]`: `symbols.get(sym_raw)` with a list key
  (`layer4_complete.py:291`). `TypeError: unhashable type`.

```
$ pm-cverifier inf.yaml            # last_buy_price: .inf
  File ".../models/price.py", line 134, in to_ticks_exact_at
OverflowError: cannot convert float infinity to integer
$ echo $?
1
$ pm-config-deploy --check inf.yaml
OverflowError: cannot convert float infinity to integer           (exit 1, traceback)
```

The exit code is the worse half: pm-cverifier documents 1 as "warnings; no
errors" (`020-config-verifier.md:65-73`), so a CI step that accepts warnings
accepts a verifier that crashed. pm-config-gen has the same pattern in
`_validate_seed_mm_mid_range_grid` (`config_gen/cli.py:1873-1876`):
`--seed-mm-mid-range 10:inf` ends in an `OverflowError` traceback (exit 1),
and `nan:20` prints `[ERROR] cannot convert float NaN to integer`.

**Fix.** Treat a non-finite number like a non-numeric one in every numeric
check (one helper). Map `UnicodeDecodeError` to Y002. Make the index
constituent check type-safe. pm-cverifier's `main` maps any unexpected
exception to exit 2 with "cannot verify", never 1. pm-config-gen parses its
float options with a finite-only type.

### C4. NaN is accepted end to end where the processes cannot use it *(repro)* — Med

Range checks written as `if x <= 0: raise` let NaN through, because every
comparison with NaN is false. The checks affected:
- The verifier: S061 at `layer2_schema.py:1894-1911` and S047 at
  `1354-1382`.
- The engine loader.
- pm-config-gen: `_validate_basic_args`, `config_gen/cli.py:148`, and
  `--index-base-value`/`--index-interval` at `1772-1800`.

```
engine_tuning: {snapshot_interval_sec: .nan}
indices: [{id: OMX, …, base_value: .nan, publish_interval_sec: .nan, …}]

pm-cverifier → ⚠ 1 WARNING …;  pm-config-deploy --check → OK … compiles
engine: now - last >= nan → False   (engine/main.py:1154)
pm-index: ValueError: base_value must be a finite number > 0   (index/calculator.py:33)
```

With a NaN `snapshot_interval_sec` the engine never publishes a book snapshot
for any symbol, and nothing reports why. With a NaN `base_value` pm-index
refuses to start. pm-config-gen writes both, from `--snapshot-interval nan`
and `--index-base-value OMX:nan`, and reports them as passing validation.

**Fix.** The non-finite rule of C3 applies to every numeric field. pm-config-gen
refuses `nan`/`inf` in every float option.

### C5. The Risk Summary misstates what will be enforced *(repro)* — Med

The Risk Summary is documented as answering "What does this config actually
do at runtime?" (`020-config-verifier.md:592-597`). `risk_summary.build`
reads the raw mapping and looks at only part of it. The repro file has:
- AAPL with an inline collar and its own circuit breaker (`L1`: 5 %, 1 min).
- MSFT with neither.
- MM01 with `enforce_mm_obligation: true` and no `mm_obligation_defaults`.

| Line | Risk Summary | Engine (`load_engine_config`) |
|---|---|---|
| Collars | `enabled — enabled but no collar configured ⚠` | AAPL `CollarConfig(static 0.1, dynamic 0.02)`, MSFT none |
| Circuit breakers | `enabled — L1=7% (5 min), L2=13% (15 min), L3=20% (rest-of-day)` | AAPL one level, L1 5 % / 60 s; MSFT none |
| MM obligations | `not enforced` | MM01 `enforce_mm_obligation=True` |

These are the three lines' mechanisms:
- **Collars** come only from `risk_controls.levels` (`risk_summary.py:348-381`),
  and they list each level without saying which symbols use one.
- **Circuit breakers** use `circuit_breaker_defaults.levels` or, failing
  that, `_DEFAULT_CB_LEVELS` (`risk_summary.py:420-422`), even when the only
  breakers are symbol blocks.
- **MM obligations** read only `mm_obligation_defaults.enforce_mm_obligation`
  (`risk_summary.py:452-458`).

In the other direction, a collar on one of 300 symbols prints as if every
symbol had it.

**Fix.** Build the summary from the `EngineConfig` that WP-CFG01's backstop
loads, when it loads: say "n of N symbols" for collars and breakers, and
list the distinct ladders. Fall back to the raw best-effort summary only
when the file does not load.

### C6. pm-config-gen writes files that pm-config-deploy refuses *(repro)* — Med

`_validate_generated` (`config_gen/cli.py:2132-2148`) is documented as
loading the YAML "exactly as pm-engine will", so that a file "the engine's
own loader rejects is never written". It runs `load_engine_config` and
`load_named_api_gateway_configs` only: not the verifier, which is the deploy
gate, and not the other eight loaders. Repro, each with exit 0 and
`[INFO] Generated config passed load_engine_config() validation`:

| Command adds | pm-config-deploy --check |
|---|---|
| `--participants TRADER1 TRADER10` | refused, S084 (ids are prefixes of each other) |
| `--alf-gateway --market-data-gateway --alf-port 5570` | refused, M018 (port collision); pm-config-gen printed a `[WARN]` only |
| `--api-gateway --monitor --api-gateway-port 5610` | refused, M018 |
| `--post-trade-gateway --post-trade-port 70000` | refused, S082 (port range); the flag is checked only for `> 0` (`cli.py:172-173`), as are `--balf-port`, `--dc-port`, `--log-server-port`, `--market-data-port`, `--api-gateway-port` |

**Fix.** See Q3. `_validate_generated` runs `config_deploy.compile_config`
(verifier ERRORs plus every loader) in its temporary directory. The `[INFO]`
line and the HINT (D6) name what was checked.

### C7. Schedule options without `--sessions-enabled` are dropped *(repro)* — Med

`build()` writes `schedule` only when `sessions_enabled and emit_schedule`
(`builder.py:435`). `--schedule` sets `emit_schedule`, but
`sessions_enabled` stays false (`cli.py:959-962`, `2244`), and the default
is false. `--schedule` is documented as "Force emit schedule section"
(help) and "Force include/exclude `schedule`" (`010-the-configuration-workflow.md:283`).
`--weekend`, `--holidays` and every time flag go the same way:

```
$ pm-config-gen … --schedule --weekend --holidays --output engine_config.yaml     (exit 0)
sessions_enabled: false             # and no schedule: block
pm-cverifier → C009 "sessions_enabled is false and no schedule is configured. The exchange will start in CONTINUOUS state immediately."
```

An operator who asked for a weekly timetable gets an always-continuous
exchange, and only an INFO advisory says so.

**Fix.** See Q4.

### C8. Other pm-config-gen options are dropped silently *(repro)* — Low

Each of these exits 0 with a file that ignores what was asked:

1. **`--ace-initial-band`, `--ace-expansions`, `--ace-random-end-ns`,
   `--ace-random-seed`, `--no-ace`, `--cb-window-ns`** without `--cb-levels`.
   `circuit_breaker_defaults` is built only from `cb_levels`
   (`builder.py:404-405`). The guide says so (`010-…workflow.md:323-325`);
   the help does not.
2. **Abbreviated tuning flags.** argparse accepts `--snapshot 2.0` and
   `--quote-history 50` (`allow_abbrev` is on, `cli_parser.py:27`). But
   `_engine_tuning_was_requested` (`cli.py:965-977`) looks for the full
   spellings in `sys.argv`, so `engine_tuning` is not written. Repro:
   `--snapshot-interval 2.0` writes the block; `--snapshot 2.0` writes
   nothing.
3. **Repeated list options.** `--symbols`, `--participants` and `--cb-levels`
   are `nargs="+"` stores: a second occurrence replaces the first.
   `--participants TRADER01 OPS01:ADMIN … --participants MM01:MARKET_MAKER`
   loses OPS01. The pm-help entry calls `--cb-levels` "repeatable".
4. **`--symbols AAPL aapl`** writes one AAPL with an INFO line.
5. **`--symbol-opts`**:
   - An invalid value (`AAPL:tick_decimals=9`) or an unknown symbol is a
     `[WARN] … Ignored.`, exit 0 (`symbol_spec.py:61-65`, `227-230`).
   - The dedicated flags refuse the same input with exit 2: for example
     `--symbol-static-band` (`cli.py:625-626`).
6. **MM obligation flags** (`--mm-spread-ticks`, `--mm-min-qty`,
   `--enforce-mm-obligations`) without a `MARKET_MAKER` participant
   (`cli.py:2273`). There is nothing to apply them to, so this one needs
   only a note.

**Fix.** With Q4: `allow_abbrev=False`; `action="extend"` for the three list
options; duplicate symbols are an error; an invalid `--symbol-opts` value or
symbol is an error (exit 2), like the dedicated flags; `--ace-*` and
`--cb-window-ns` without `--cb-levels` are a usage error.

### C9. The report's counts and labels disagree *(repro)* — Low

`_layer_count_line` (`formatter.py:42-70`) counts every finding of a layer
in the layer's unit, and the verdict counts by severity
(`formatter.py:214-224`). Layer 4 holds C001, a WARN, and Layer 3 holds
M004, an INFO, so:

```
⚠ Semantic: 2 warnings
⚠ Completeness: 5 advisories
Verdict:  ⚠ 3 WARNINGS, 4 ADVISORIES — engine can start but review warnings
```

This is L005 from the training-guide review. Two related details:
- A skipped layer always says "skipped (fix schema errors first)"
  (`formatter.py:53`), also after a YAML error.
- A missing file still prints the Risk Summary with empty values
  (`Sessions disabled — `, `Order limits ` blank, `Admin gateway none [!]`),
  because `cli.py:167-171` builds an empty `RiskSummary`.

**Fix.** Count each layer by severity ("2 warnings, 1 advisory"); name the
skipping layer; print no Risk Summary when the file did not load.

### C10. Two codes are ambiguous — Low

- **S065** is used for `symbols.<S>.circuit_breaker` not being a mapping
  (`layer2_schema.py:672-701`) and for `locale.country` not being a string
  (`layer2_schema.py:1988-2000`). The guide flags the reuse
  (`020-config-verifier.md:259`). `--format json` consumers cannot tell the
  two apart.
- **S081** runs the ALF loader on every file
  (`layer2_schema.py:2337-2359`). That loader builds the participant roles
  and raises on prefix ids, so a file with no `alf_gateway` reports one
  defect twice:
  `[S084] … prefixes of each other` and
  `[S081] 'alf_gateway' section is invalid: participants IDs must not be prefixes…`.

**Fix.** Give `locale.country` its own code. Run S081 only when
`alf_gateway` is present.

### C11. M032 fires on files without any API gateway *(repro)* — Low

`_check_readonly_api_key` (`layer3_semantic.py:1165-1201`) warns whenever no
`gateway_id: null` credential exists, including when there is no
`api_gateways` section at all. Every minimal configuration therefore exits 1,
including the training guide's and every pm-config-gen file without
`--api-gateway`. And `pm-config-gen --api-gateway` writes no read-only key
unless `--api-gateway-readonly-key` is given (`cli.py:1585`), so its default
API output warns too.

**Fix.** See Q5.

### C12. A halt of 0 minutes is written as a rest-of-day halt *(repro)* — Low

`parse_cb_spec` accepts `HALT_MINS` 0 (`cb_spec.py:271`) and
`_build_cb_defaults` writes 0 as `halt_duration_ns: null` (`builder.py:835-836`).
`--symbol-opts cb_halt_l1=0` does the same (`builder.py:957-958`). `null`
means rest of day. The help says to omit `HALT_MINS` for that, so `0` is
read as "no halt" or as a typo and becomes the longest halt there is.

**Fix.** Refuse 0 (`HALT_MINS` must be > 0; omit it for rest of day).

---

## 4. Performance findings

Nothing here matters at today's sizes: the s300 simulation configuration
verifies in 0.50 s. The cost grows with the file, not with history.

### P1. Layer 1 parses the file twice *(measured)* — Low

`load_with_origins` calls `yaml.safe_load(text)` (`layer1_yaml.py:374-375`)
to classify Y003/Y004, then `load_config_mapping(path)` (`406-407`), which
parses the same file again.

| File | Layer 1 | one `safe_load` | Layers 2–4 |
|---|---|---|---|
| s300-sim (300 sym, 113 participants) | 0.50 s | 0.24 s | 0.00 s |
| 3 000 sym × 1 000 participants, 5 MMs | 9.66 s | 4.56 s | 1.96 s |
| 3 000 sym × 1 000 participants, 20 MMs | 35.96 s | 18.84 s | 7.71 s |

**Fix.** Parse once: give `load_config_mapping` the text already read, or let
Layer 1 classify the error raised by `load_config_mapping`. (The
`CSafeLoader` speed-up, 0.74 s instead of 4.56 s, belongs to
`config_include` and every other reader, so it goes in §9.)

### P2. M003 scans every participant for every seed quote *(measured)* — Low

`_effective_max_spread` (`layer3_semantic.py:114-156`) loops over
`participants` to find the quote's gateway, once per seed quote. The cost is
quotes × participants: 1.83 s for 15 000 quotes and 7.90 s for 60 000 quotes,
each against 1 006–1 021 participants.

**Fix.** Index the participants by upper-cased id once per run.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `020-config-verifier.md:44`; `layer3_semantic.py:1-8` | "every hard error that `load_engine_config()` would raise": not true (C1). The Layer 3 docstring says it covers "M001–M026" (it goes to M033) and that the raw values are "already well-formed" once Layer 2 passes. |
| D2 | `pm_help/registry.py:2329-2331` | pm-cverifier "Exit 0: no findings at/above threshold. Exit 1: one or more findings at/above threshold." The exit code ignores `--level`: 0 OK, 1 warnings, 2 errors (and 2 for warnings with `--strict`). |
| D3 | `pm_help/registry.py:2237-2241` | `--cb-levels NAME:SHIFT[:HALT_MINS[:MODE]]` "repeatable": there is no `MODE` (a fourth field is refused, `cb_spec.py:247-250`), and repeating replaces (C8). |
| D4 | `010-the-configuration-workflow.md:315`; `config_gen/defaults.py:16-20` | `--cb-levels` default "built-in ladder": without the flag no circuit breaker is written, and `pm-cverifier` reports C004. `DEFAULT_CB_LEVEL_SPECS` is never used. |
| D5 | `--schedule` help (`cli_parser.py`), pm-help `registry.py:2278-2283`, guide `:283` | "Force emit/include" (C7). `--sessions-enabled` help and pm-help ("disabled") do not say that pm-config-gen writes `sessions_enabled: false` while an absent key means `true` to the engine (`engine/config_loader.py:1459`). |
| D6 | `config_gen/cli.py:2435-2440`; `renderer.py:101-104` | `[HINT] Validate with: poetry run python -c … load_engine_config(Path("engine_config.yaml"))`, on stderr and in every generated file's header. It needs a checkout, names `engine_config.yaml` whatever `--output` was, and checks less than `pm-cverifier`/`pm-config-deploy --check` (L004). The `[INFO] … passed load_engine_config() validation` line (`2399-2402`) names the wrong check after WP-CFG04. |
| D7 | `renderer.py:269-270`; `warnings.py:190-203`; `--seed-last-prices` help | `last_buy_price: null` is annotated "REQUIRED: set last buy reference price", but the field is optional. The diagnostic says "Consider `--seed-last-prices` … They are required for collar initialization", but that flag writes only nulls, which provide no reference (the guide says so at `010-…:587`). |
| D8 | `layer3_semantic.py:207-208` | M001 suggests "Run pm-config-gen with `--seed-mm` to generate placeholder seeds". There is no such flag; `--seed-mm-mid-range MIN:MAX` generates real seeds, and the default writes the placeholders. |
| D9 | `layer3_semantic.py:279` | M003 "The seed quote would be immediately rejected": the engine injects seed quotes without a spread check (`engine/main.py:1218-1360`); the quote breaches the obligation from the start. |
| D10 | `cli_comments.py:120` | The generated file says "see ../../../docs/books/participant-guide/…": a repository-relative path in a file written to an operator's directory. |
| D11 | `warnings.py:116-123` | "emitting default schedule (09:00-16:05). Override with `--pre-open` …" is printed even when the times were overridden. |
| D12 | `--symbol-opts` help (`cli_parser.py`) | "Per-symbol overrides. Can be repeated." lists none of its 18 keys (`symbol_spec.py:29-48`). |
| D13 | `renderer.py:50-79` | `_SECTION_ORDER` has no entry for `alf_gateway`, `balf_gateway`, `log_server`, `monitor`, `indices` or `require_mm_seed_quotes`. They land under `# -- Additional fields --` after the combos, and four of them get no hint comment. |
| D14 | `020-config-verifier.md:530`; `layer2_schema.py:1714-1730` | M014 "thresholds not strictly increasing": the check compares the YAML order with the sorted order, so equal thresholds pass. |
| D15 | `--api-gateway-enabled`/`-disabled`, `-host`, `-port`, … help | They name `api_gateway.<field>`; the key is `api_gateways.<name>.<field>`. `--api-gateway-generate-keys` says "each configured ALF gateway" for each participant. |
| D16 | `--log-server-retention-days` help | "0 means unbounded retention, same as omitting the field with retention disabled": omitting the flag writes 30. |

---

## 6. Verified as correct

- **Layering and skips.** A Layer 1 or Layer 2 ERROR skips Layers 3 and 4
  (`cli.py:121-133`). Each check that ran reports independently. The deploy
  gate blocks on ERROR only and ignores warnings by design
  (`config_deploy.py:171-181`).
- **Process blocks.** ALF, RALF, CALF, API, BALF, log server and monitor are
  re-validated by their own loaders. The harness found no false accept in
  them.
- **Unknown keys (S121)** at every level, with a close-match hint. The
  process-block sets are pinned to the loaders' dataclasses by tests.
- **Tick grid (S078)** for every price, each against its own symbol's
  `tick_decimals`, standing down when `tick_decimals` is invalid.
- **Port inventory (M018)** covers every listener, log server's three ports
  and monitor's defaults included, and the fixed listeners with environment
  overrides.
- **Includes.** Y005 for include errors; findings are attributed to the
  included file (`in symbols.yaml`). `--split` and `--api-keys-for` produce
  files that verify and compile. The keys file is 0600 before any secret is
  written (`cli.py:2124-2129`).
- **pm-config-gen's cross-checks:**
  - Participant ids against a strict pattern.
  - Index constituents against symbols and outstanding shares, and their
    reference prices.
  - Combo leg prices on each leg's own grid.
  - The seed spread against the effective MM obligation.
  - Monitor bands and hung timeout.
  - Log-server port distinctness and the lease bound.
  - Schedule order whenever a block is written.
  - `--country` and `--session-timezone` against the real libraries.
- **Seed snapping.** `_seeded_midpoint` uses `Decimal` and the symbol's own
  grid. `_validate_seed_mm_mid_range_grid` refuses a range with no grid
  price or no positive bid.
- **Reproducible keys.** With `--seed`, or with a credentials file, API keys
  derive from `api:{seed}:{label}` and are identical across runs.

---

## 7. Decisions

Taken 2026-11-14: Johan asked for WP-CFG01–09 in one go; Q1–Q5 are taken as
recommended.

| # | Question | Recommendation |
|---|---|---|
| Q1 | How does the verifier close C1? (a) A backstop: after Layer 2, run the engine loader on the mapping and report its first error as a new code (S132) when no engine-section ERROR was reported. Do the same for `dc_gateway` (S133). Add field checks for the explicit-null family. (b) Mirror every loader rule by hand. (c) Drop the hand checks and rely on the loaders. | **(a).** It is the pattern the BALF, log-server and monitor blocks already use, and it makes "OK ⇒ compiles" true by construction. (b) is how the gap arose. (c) loses the specific, multi-finding messages, which are the verifier's purpose. The null checks are worth writing by hand because the pm-config-gen template produces them, and the backstop would name only the first. |
| Q2 | M006 (schedule order) and C008 (index constituent without reference price): warning or error? | **ERROR.** pm-scheduler and pm-index each refuse to start on them, and pm-config-deploy is the last place to stop the file. Keeping WARN says "engine can start" about an exchange that cannot open. |
| Q3 | How does pm-config-gen make sure it never writes a file deploy refuses (C6)? (a) Run `config_deploy.compile_config` on the rendered files in the temporary directory. (b) Add the missing checks (prefix ids, port range and collisions) to pm-config-gen by hand. | **(a).** One gate, the same as deploy's, and every future check comes for free. (b) duplicates the verifier and drifts. The MM stub template stays the one exception. With Q1 the verifier now reports its nulls as errors, so the HINT says the file will not deploy until they are filled. |
| Q4 | Schedule-shaping options without `--sessions-enabled` (C7): (a) usage error, (b) imply `--sessions-enabled`, (c) write the schedule with `sessions_enabled: false` (M005 warns). | **(a)**, exit 2, naming `--sessions-enabled`. It applies to `--schedule`, `--weekend`, `--holidays` and any time flag given explicitly. (b) changes the engine's start state behind the operator's back. (c) writes a block the engine ignores. The same rule covers `--ace-*`/`--cb-window-ns` without `--cb-levels` (C8). Detecting "given explicitly" needs `default=None` on those flags, with the defaults applied in the builder. |
| Q5 | M032 (C11): (a) warn only when an `api_gateways` section exists, and make `pm-config-gen --api-gateway` write the read-only key by default (`--no-api-gateway-readonly-key` to opt out); (b) keep it as is. | **(a).** Without any API gateway, "no read-only credential" is not the problem to report, and every minimal file exits 1 for it today. The dashboards need the key whenever an API gateway exists, so the generator should write it unless told not to. |

---

## 8. Work packages

### WP-CFG01 — A verifier OK means pm-config-deploy compiles (C1, D1; after Q1)

**Tests first** (`tests/test_cverifier.py`, new `tests/test_cverifier_deploy_agreement.py`):

1. The file pm-config-gen writes for
   `--symbols AAPL --participants TRADER01 MM01:MARKET_MAKER` gives an ERROR
   naming `symbols.AAPL.market_maker_quotes[0].bid_price`, and exits 2.
   (Fails today: exit 1.)
2. A parametrised table of single-leaf mutations of one base file, taken
   from the harness families of §3 C1. For each, the verifier reports an
   ERROR exactly when `config_deploy.compile_config` raises:
   - `null` for `sessions_enabled`, `enforce_collars`,
     `require_mm_seed_quotes`, `engine_tuning.snapshot_interval_sec`, the
     MM obligation defaults, a quote's price, quantity, `gateway_id` and
     `tif`, a collar band, `history_file` and `constituents`.
   - A non-mapping `risk_controls.levels.X`, `….collar`,
     `circuit_breaker_defaults.levels.L1`, `schedule.weekdays` and
     `engine_tuning`.
   - `engine_tuning.*` set to `0`, `-1` or `'x'`.
   - `reference_window_ns: 'x'`, `participants[0].description: 1` and a
     combo leg `price: 'x'`.
   - `dc_gateway.heartbeat_interval_sec: 1.5`.

   (Fails today for every row.)
3. The S132 backstop reports nothing when an engine-section ERROR is
   already present (no double report), and reports the loader's message when
   none is.
4. The existing verifier tests and the intended-strictness rows (M022, M029,
   M030, M033, S092/S096/S098) are unchanged.

**Change.** A raw-mapping entry point to the engine loader, if it does not
exist, the way the gateway loaders have one. S132 (engine backstop) and S133
(DC backstop) after Layer 2. Null-aware field checks for the null family, as
"is required / must be X, got null" findings. Keep the loaded `EngineConfig`
on the run for WP-CFG06. Text: §3 D1 (guide line 44, Layer 3 docstring) and
the check catalogue rows for S132/S133.

**Exit criteria.** Tests 1–4 pass. Rerunning the harness on both baselines
gives 0 false accepts. The verifier suites and `test_config_deploy*` are
green.

**Outcome (2026-11-14).**
- `engine/config_loader.py` gains `engine_config_from_raw(raw)`;
  `load_engine_config(path)` is now the file read plus that call (no
  behaviour change).
- **S132** (`layer2_schema.check_engine_loader`) runs from
  `cli.run_layers` *after* Layer 3, not in Layer 2. Several M codes (schedule
  M021–M028, indices M009–M011, seeds M001/M002/M020) describe loader errors
  more precisely and would otherwise be pre-empted, since a Layer 2 error
  skips Layer 3. It is quiet when any ERROR outside the process blocks
  (gateways, `log_server`, `monitor`, `api_gateways`) was already reported,
  and it is counted in the Semantic line. Like `compile_config`, it catches
  any exception from the loader.
- `run_layers` now returns `(layers, raw, engine_config)`; `run` is
  unchanged. The `EngineConfig` is kept for WP-CFG06.
- **S133** is the DC backstop (only when no `dc_gateway` finding).
- **S094** now mirrors the DC loader's `as_int` (whole seconds; `1.5` and
  `true` refused). The review's test listed `heartbeat_interval_sec: 1.5` as
  the S133 case; with S094 corrected, that case is S094 and the S133 test uses
  `port: null`, which no field check reads.
- The null family is reported by the field's own code with "has no value
  (null)":
  - S014 at the field's path (the pm-config-gen stub prices).
  - S037/S038/S041/S042, S060–S063, S113, S071–S073 and S076/S077.
  - S023, S048, S049 (constituents `null` or absent).
  - S016 for `tif: null`.
- Guide: line 44 reworded; S132/S133 catalogue rows; S094 wording; the range
  is now `S001`–`S133`. The Layer 3 docstring is corrected.
- Tests: new `tests/test_cverifier_deploy_agreement.py` (40 tests: 34
  single-leaf mutations and the stub template), all of which failed first,
  either because the verifier passed the file or because S132/S133 was
  missing. Three existing tests unpack the new `run_layers` triple.
- The harness rerun gives **0 false accepts** on both baselines (was 227 and
  71). One new false reject: `null` for a band on a risk level no symbol
  uses, consistent with S042's existing strictness on unused levels.
- Every `docs/examples/ref_data/*/engine_config.yaml` still verifies without
  an ERROR. Full suite: 14 224 passed, 1 skipped.

### WP-CFG02 — Neither tool crashes or accepts NaN/∞ (C3, C4)

**Tests first** (`tests/test_cverifier.py`, `tests/test_config_gen_integration.py`):

1. `last_buy_price: .inf`, `bid_qty: .inf`, `halt_duration_ns: .inf`,
   `tick_decimals: .inf` and a combo leg `price: .nan` each give an ERROR
   naming the field, exit 2, and no traceback. (Fails today: traceback,
   exit 1.)
2. `snapshot_interval_sec: .nan` and an index's `base_value: .nan` and
   `publish_interval_sec: .nan` are ERRORs. (Fails today: OK and compiles.)
3. A file with a `0xFF` byte gives Y002 "not UTF-8", exit 2. (Fails today:
   traceback.)
4. `indices[0].constituents: [[]]` gives an ERROR, no traceback. (Fails
   today.)
5. `main()` turns an unexpected exception (patched into a layer) into exit 2
   with "cannot verify". (Fails today: exit 1.)
6. pm-config-gen: `--snapshot-interval nan`, `--index-base-value OMX:inf`,
   `--seed-mm-mid-range 10:inf` and `nan:20` each exit 2 with an `[ERROR]`
   naming the flag. (Fails today: exit 0, exit 0, traceback, and an odd
   message.)

**Change.** One helper for "finite number" used by every numeric check (the
`int()` conversions included). Map `UnicodeDecodeError` to Y002. Guard the
C008 lookup on `str`. Add a `try` in pm-cverifier's `main` that exits 2.
Add a finite-float argparse type for pm-config-gen's float options and the
`ID:VALUE` / `MIN:MAX` parsers.

**Exit criteria.** Tests 1–6 pass. The harness reports 0 verifier crashes on
both baselines.

**Outcome (2026-11-14).**
- Verifier:
  - Every conversion guard in Layers 2–4 and `risk_summary` also catches
    `OverflowError` (`int(inf)`, `round(inf)`).
  - `layer2_schema._finite_float` refuses NaN and ∞ in the tick-grid check
    and in S011, S016, S047, S053, S061 and S116. S011/S016 now say "must be
    a finite number".
  - Combo leg `price`/`stop_price` get a finite check (S059, at the field
    path).
  - Y002 covers `UnicodeDecodeError` ("not UTF-8 text (byte n)").
  - C008 looks constituents up by upper-cased name through
    `symbol_cfg_by_upper_name`, so a non-string constituent finds nothing
    (M009 reports it) instead of raising.
  - `main` wraps `run_layers` and the Risk Summary: an unexpected exception
    prints `[ERROR] pm-cverifier cannot verify …` and exits 2.
- pm-config-gen:
  - `cli_parser.finite_float`, with an argparse wrapper that names the flag,
    replaces `type=float` on all ten float options.
  - It is used in `--seed-mm-mid-range`, `--index-base-value`,
    `--index-interval`, `--monitor-threshold`, `--symbol-max-order-value`,
    combo leg prices and `--symbol-opts max_order_value`. The parsers checked
    against `(0, 1)` already refused both.
- Tests: new `tests/test_cverifier_robustness.py` (17) and
  `tests/test_config_gen_robustness.py` (12). All failed first, for the
  reasons in §3: tracebacks, NaN accepted, a `RuntimeError` escaping `main`,
  and messages not naming the flag.
- Harness rerun: 0 crashes and 0 false accepts on both baselines. Six new
  intended rejects: NaN and ∞ in `snapshot_interval_sec` and in an index's
  `base_value`/`publish_interval_sec`, which the engine loader accepts
  (L024).
- Full suite: 14 253 passed, 1 skipped.

### WP-CFG03 — What stops a process from starting is an ERROR (C2; after Q2)

**Tests first** (`tests/test_cverifier.py`):

1. Weekday times with `continuous_start` after `closing_auction_start`:
   M006 ERROR, exit 2. `config_deploy.compile_config` raises `CompileError`.
   (Fails today: WARN, compiles.)
2. An index constituent with `outstanding_shares` and no last price: C008
   ERROR. (Fails today: WARN.)
3. A valid schedule and a priced constituent are unchanged.

**Change.** Raise the two severities. The catalogue rows in
`020-config-verifier.md` change accordingly.

**Exit criteria.** Tests pass; verifier and deploy suites are green.

**Outcome (2026-11-14).**
- M006 and C008 are ERROR, and their suggestions say which process refuses
  the file.
- Guide: the M006 and C008 catalogue rows, and the layer table (Layer 4 can
  now be ERROR).
- Tests: new `tests/test_cverifier_blocking_checks.py` (4). The two "is an
  error" tests failed first on WARN; the two "unchanged" tests passed before
  and after. The tests also assert that `compile_config` raises
  `CompileError`.
- No other guide passage or transcript mentions either code. Every bundled
  example still verifies without an ERROR.
- Full suite: 14 257 passed, 1 skipped.

### WP-CFG04 — pm-config-gen never writes what pm-config-deploy refuses (C6, D6; after Q3, WP-CFG01)

**Tests first** (`tests/test_config_gen_integration.py`):

1. `--participants TRADER1 TRADER10` exits 2 with `[ERROR] … S084 …` and
   writes nothing. (Fails today: exit 0, file written.)
2. `--alf-gateway --market-data-gateway --alf-port 5570` exits 2 (M018).
   (Fails today.)
3. `--post-trade-gateway --post-trade-port 70000` exits 2, and so do the
   other `*-port` flags above 65535. (Fails today.)
4. A valid run prints `[INFO] … passes pm-config-deploy --check`. The HINT
   names `pm-cverifier <output path>`, and the file header names the same.
   (Fails today.)
5. The MM stub template (no `--seed-mm-mid-range`) is still written, and its
   HINT says it will not deploy until the prices are filled.
6. `--split` and `--api-keys-for` runs are still accepted (unchanged).

**Change.** `_validate_generated` calls `config_deploy.compile_config` on the
temporary copy (sim file excluded) and reports the blocking findings in the
verifier's `code [path]: message` form. Port flags take a 1–65535 type. The
HINT and header (D6) are replaced. L004 is marked "moved" in the For-Later
list.

**Exit criteria.** Tests pass; `test_config_gen_*` and
`test_config_generated_fields_reach_artifact.py` are green.

**Outcome (2026-11-14).**
- `_validate_generated` calls `config_deploy.compile_config` on the temporary
  copy. A refusal prints `Generated config failed validation:` followed by
  either "pm-config-deploy would refuse it:" and one `CODE [path]: message`
  line per verifier finding, or the loader's own message. The now unused
  `load_engine_config`/`load_named_api_gateway_configs` imports are removed.
- `[INFO] Generated config passes pm-config-deploy --check.`
- The HINT is now `Check it with: pm-cverifier <output>` and
  `Install it with: pm-config-deploy <output>`; the file header says the
  same (D6, L004 closed).
- The stub-template HINT says pm-config-deploy refuses the file until the
  prices are set (S014).
- All eleven port options take a 1–65535 type (`cli_parser._port_arg`), so
  the `> 0` checks they made dead are removed from `_validate_basic_args`
  and the LALF-PS list. `--api-gateway-instance` PORT is 1–65535.
- Existing tests changed:
  - `test_alf_port_collision_is_warned` encoded C6 (exit 0 on a file deploy
    refuses). It is now `…_warned_and_refused`: exit 2, M018, nothing
    written.
  - `test_alf_port_out_of_range_is_rejected` asserts the argparse wording.
  - The loader-reject helper stubs `compile_config`.
- Tests: new `tests/test_config_gen_deploy_gate.py` (18). 16 failed first:
  exit 0 on S084/M018, ports above 65535 accepted, the old INFO and HINT.
  The `--alf-port` range case and the `--split`/`--api-keys-for` run passed
  before and after.
- Re-walked flows (lessons-learned §B1). A scratch script runs every
  `pm-config-gen` command in `docs/books`: 55 commands, all exit 0 except
  the training guide's intended "duplicate assignment" error. Three guide
  passages rewritten:
  - Training guide ch. 02 described the C1 trap ("`pm-cverifier` will
    report 0 errors on the stub").
  - The operator guide's "validate manually" `poetry run` command
    (`010-the-configuration-workflow.md`).
  - That chapter's MM-stub paragraph.
- `make completion` regenerated.
- Full suite: 14 275 passed, 1 skipped.

### WP-CFG05 — Every pm-config-gen option takes effect or is refused (C7, C8, C12; after Q4)

**Tests first** (`tests/test_config_gen_integration.py`, `tests/test_config_gen_symbol_spec.py`, `tests/test_config_gen_cb_spec.py`):

1. `--schedule`, `--weekend`, `--holidays` or `--pre-open 08:00` without
   `--sessions-enabled`: exit 2 naming `--sessions-enabled`. (Fails today:
   exit 0, no schedule.)
2. `--ace-initial-band 0.05` or `--cb-window-ns 1000` without `--cb-levels`:
   exit 2. (Fails today.)
3. `--snapshot 2.0` is a usage error (no abbreviations). (Fails today:
   accepted and dropped.)
4. `--participants A --participants B` keeps both. So do repeated `--symbols`
   and `--cb-levels`. (Fails today: the last wins.)
5. `--symbols AAPL aapl` exits 2 (duplicate). (Fails today.)
6. `--symbol-opts AAPL:tick_decimals=9` and `--symbol-opts MSFT:…` with MSFT
   not in `--symbols` exit 2. (Fails today: WARN, exit 0.)
7. `--cb-levels L1:0.1:0` and `cb_halt_l1=0` exit 2. (Fails today.)
8. `--sessions-enabled` with the defaults still writes the default schedule
   (unchanged).

**Change.** `allow_abbrev=False`. `action="extend"` for the three list
options. `default=None` on the schedule and ACE flags, with the defaults
applied in `ConfigSpec`. Usage checks in `_validate_basic_args`. Make
`symbol_spec` raise instead of warn. `HALT_MINS > 0`. The training-guide and
operator-guide commands are re-run to confirm they still pass (lessons-learned
§B1).

**Exit criteria.** Tests pass; `test_config_gen_*` green; every
`pm-config-gen` command in `docs/books` still exits 0 (a scripted check).

**Outcome (2026-11-14).**
- `cli._resolve_gated_options` runs first in `main`. The 15 time options
  and `--cb-window-ns`, `--ace-initial-band` and `--ace-random-end-ns` now
  have `default=None`, so "given" can be told from "defaulted"; the defaults
  are filled after the check.
- Given without their enabling flag, these are refused with exit 2, naming
  the options and the missing flag:
  - `--schedule`, `--weekend`, `--holidays` or any time option without
    `--sessions-enabled`, or together with `--no-schedule`;
  - any of `--cb-window-ns`, `--ace-initial-band`, `--ace-expansions`,
    `--ace-random-end-ns`, `--ace-random-seed` or `--no-ace` without
    `--cb-levels`.
- `allow_abbrev=False`. `--symbols`, `--participants` and `--cb-levels` use
  `action="extend"`. A symbol listed twice (case-insensitive) is an error.
- `parse_symbol_opts` raises for an unknown symbol or key, a token without
  `=`, or an invalid value, and returns only the overrides. The warning
  plumbing it made unused is removed (`_parse_specs`' tuple element and
  `evaluate_diagnostics(parsed_symbol_option_warnings=…)`).
- `HALT_MINS` and `cb_halt_lN` must be > 0.
- Existing tests changed:
  - The two "warns" tests in `test_config_gen_symbol_spec.py` now expect
    errors.
  - `test_parse_cb_spec_invalid_halt` matches the new wording.
  - `test_schedule_bad_time_format_fails` adds `--sessions-enabled` so that
    it still reaches the format check it tests.
  - WP-CFG02's combo case no longer repeats `--symbols AAPL` (now an
    extension, hence a duplicate).
- Tests: new `tests/test_config_gen_options.py` (24). 21 failed first; the
  three "unchanged" cases passed. The `cb_halt_l1=0` case was first written
  without a shift, which the WP-CFG04 gate already refused (S066), so it was
  corrected to carry `cb_shift_l1=0.05` before it was counted as failing.
- Beyond the plan: the example generators (`mkrefdata_common.py`,
  `mks150.sh`, `mks300.sh`) used `L3:…:0`, which is now refused, and
  became `L3:…`.
  - All 48 example YAML files were regenerated in a scratch copy: the
    configuration content is identical; only the header comments differ
    (the WP-CFG04 check/install hint and the corrected command).
  - The 32 changed files are installed. The venv's project metadata was
    stale (0.78.4), so `poetry install --only-root` was run first and the
    headers say v0.79.0.
- Guide: the session/schedule and CB/ACE option tables, the `--symbol-opts`
  key table and error rule, and `--symbols`/`--participants` repetition.
- The documented-commands script: 55 commands, all exit 0 except the
  intended error. `make completion` regenerated.
- Full suite: 14 299 passed, 1 skipped.

### WP-CFG06 — The Risk Summary states what the engine will enforce (C5; after WP-CFG01)

**Tests first** (`tests/test_cverifier.py`):

1. The §3 C5 file:
   - `Collars       enabled — 1 of 2 symbols (AAPL: static 10%, dynamic 2%)`.
   - `Circuit breakers enabled — 1 of 2 symbols (AAPL: L1=5% (1 min))`.
   - `MM obligations enforced (MM01)`.

   (Fails today on all three.)
2. A file with `risk_controls.default_level` and
   `circuit_breaker_defaults`: "N of N symbols" with the level and ladder
   (unchanged content, new counts).
3. A file that fails to load: the raw best-effort summary as today, marked
   "(from the file as written; it does not load)".
4. The JSON `risk_summary` gains the counts. The existing keys keep their
   meaning.

**Change.** `risk_summary.build` takes the loaded `EngineConfig` when there
is one. Collars and breakers are taken per symbol from it, and MM
enforcement from the participants and the policies.

**Exit criteria.** Tests pass; the guide's Risk Summary table matches.

**Outcome (2026-11-14).**
- `risk_summary.build(raw, engine=None)`. With the `EngineConfig` from
  `run_layers`, `_apply_engine` replaces the collar, breaker and MM lines:
  - Collars and breakers are taken per symbol from the merged config and
    grouped by setting (`k of N symbols (AAPL, MSFT: …; 40 symbols: …)`).
  - MM enforcement follows the engine's own precedence (`engine/main.py`
    4198-4217: gateway+symbol policy, global symbol policy, participant
    flag). The line lists the market makers (`MM01 on k of N symbols` when
    partial).
  - Percentages no longer round: 0.025 shows as 2.5%. The old `.0%`
    printed the chapter-005 file's 1.5% band as "2%". Halt durations that
    are not whole minutes show in seconds (90 s used to print as "1 min").
- Without an `EngineConfig`, the raw reading is kept unchanged (so are the
  existing `build(raw)` tests) and the heading says "(from the file as
  written; it does not load)".
- `RiskSummary` gains `mm_description`, `collared_symbols`,
  `circuit_breaker_symbols`, `mm_obligation_gateways` and `loaded`, and
  JSON carries the last four.
- Found on the way, and fixed with a regression test:
  - The S132 backstop returned no `EngineConfig` when an earlier error
    suppressed it, and `run_layers` returned before it on Layer 2 errors.
  - A file with only an S121 unknown key (which loads) was therefore
    summarised as "does not load".
  - The backstop now always tries the loader and suppresses only its
    finding, and the Layer 2 early return still loads for the summary.
- Tests: new `tests/test_cverifier_risk_summary.py` (5). The first four
  failed first, on the old lines and the missing JSON keys.
- Guide: the sample and the table in `020-config-verifier.md`, and the
  JSON paragraph. The chapter-005 transcript was re-run on its "complete
  file" and replaced with the real output. The `020` sample output is
  illustrative and was edited to the new format, not re-run.
- Full suite: 14 304 passed, 1 skipped.

**Follow-up (found during WP-CFG09, 2026-11-14).**
- Checking a new diagnostic against the engine showed that a collar is
  registered only at start-up, and only when the symbol then has a
  reference price (`engine/main.py:1402-1416`, the only writer of
  `self._collars`). The price comes from the file or from a previous run's
  persisted book stats.
- The WP-CFG06 summary counted every configured collar as applied. A
  collar on a symbol with no last price in the file is now marked
  `…, no reference price in the file`, and the guide's table says what
  that means.
- Test: `test_collar_without_a_reference_price_is_marked`, which failed
  first.

### WP-CFG07 — Counts, codes and messages agree (C9, C10, C11; after Q5)

**Tests first** (`tests/test_cverifier.py`, `tests/test_config_gen_integration.py`):

1. A file with M013 (WARN), M004 (INFO), C001 (WARN) and C007 (INFO): the
   layer lines read `Semantic: 1 warning, 1 advisory` and
   `Completeness: 1 warning, 1 advisory`, and they sum to the verdict.
   (Fails today.)
2. A YAML syntax error: the later layers read "skipped (fix the YAML error
   first)", and no Risk Summary is printed. A missing file: the same.
   (Fails today.)
3. `locale.country: 5` has its own code, distinct from S065. (Fails today.)
4. Prefix participant ids and no `alf_gateway`: S084 only, no S081. (Fails
   today.)
5. No `api_gateways`: no M032. An `api_gateways` section without a null
   credential: M032 as today. (Fails today for the first.)
6. `pm-config-gen --api-gateway` writes a read-only credential;
   `--no-api-gateway-readonly-key` suppresses it. (Fails today.)

**Change.** Formatter counts by severity, the skip reason, and no summary
for a file that did not load. The new code for `locale.country`. S081 is
guarded by the section's presence. M032 is guarded by the same. The
pm-config-gen default flips, with a `--no-` form. L005 is marked "moved" in
the For-Later list.

**Exit criteria.** Tests pass; transcripts in `020-config-verifier.md` and
the training guide's chapter 01 are regenerated.

**Outcome (2026-11-14).**
- Formatter:
  - A layer line counts by severity (`⚠ Completeness: 1 warning, 3
    advisories`); a layer with no findings keeps its usual wording.
  - `LayerOutcome.skip_reason` is shown: "fix the YAML error first" after
    Layer 1, "fix schema errors first" after Layer 2.
  - When Layer 1 has an error (missing, unreadable or unparseable file, or
    a broken include) the Risk Summary is left out. The verdict lines moved
    into `_verdict_lines` for that path.
- Codes:
  - `locale.country` is **S134** (S065 keeps only the circuit-breaker
    meaning).
  - S081 runs only when `alf_gateway` is present.
  - M032 is quiet when there is no (or an empty) `api_gateways` section.
- pm-config-gen writes the read-only key by default whenever it writes an
  API gateway: `--api-gateway-readonly-key`/`--no-api-gateway-readonly-key`
  with a default of on. Only the explicit flag also makes the section appear
  on its own. L005 is marked fixed in the For-Later list.
- Tests: new `tests/test_cverifier_report.py` (10). Eight failed first; the
  schema skip reason and "broken alf_gateway is S081" passed before and
  after.
  - The layer-count expectation was first written without C003/C004. It
    was corrected from the file's actual findings before counting the
    failure.
  - Existing tests changed to the new behaviour:
    `test_m032_warns_without_api_gateways` (now quiet), the three
    `test_s065_country_*` (now S134), and two `--api-keys-for` tests (the
    keys file now also carries the read-only key).
- Re-walked flows (lessons-learned §B1):
  - Re-run with the real files: chapter 005's Step 1 transcript (it showed
    L005 itself: "5 advisories" beside "4 ADVISORIES"), and training
    chapter 01 Exercises 3 and 4 (`engine_config.yaml` is now `OK`, exit 0;
    `generated.yaml` has only C001).
  - Rewritten: the passages expecting M032 in training chapters 01
    (Exercise 13), 02 and 17.
  - Updated: the guide's layer paragraph, the catalogue rows and the option
    table.
  - Documented commands: unchanged result.
- Full suite: 14 314 passed, 1 skipped.

### WP-CFG08 — Parse once; no per-quote participant scan (P1, P2)

**Tests first** (`tests/test_cverifier.py`):

1. `run_layers` calls the YAML parser once per file (counted with a patched
   `yaml.safe_load`/loader). (Fails today: twice.)
2. Y003 and Y004 keep their messages and line numbers (unchanged).
3. M003 resolves the same limit for every case already tested (unchanged).

**Change.** Layer 1 classifies from one parse. `_check_mm_seeds` builds a
participant index once.

**Exit criteria.** Tests pass. On the 3 000 × 1 000 × 20 file, Layer 1
falls by about half (18.8 s of 36.0 s measured) and M003 by about 7 s. The
targets are estimates from the §4 table; report the measured numbers.

**Outcome (2026-11-14).**
- `config_include.load_config_mapping(path, main_raw=None)` takes the main
  file already parsed. Layer 1 passes the mapping it parsed for Y003/Y004.
  This is the only change to the shared reader; every other caller is
  unchanged.
- `layer3_semantic._participants_by_id` is built once per run and passed to
  `_effective_max_spread`; the first entry for an id wins, as the old loop's
  `break` did.
- Tests: new `tests/test_cverifier_performance.py` (3). The two
  parse-count tests failed first (2 parses for 1 file, 3 for a file with
  one include); the Y003/Y004 test passed before and after.
- Measured (same files as §4; `run_layers` now also includes the S132
  loader run):

  | File | Layer 1 before → after | M003 (`_check_mm_seeds`) | `run_layers` total |
  |---|---|---|---|
  | s300-sim | 0.50 → 0.23 s | 0.00 s | 0.50 → 0.24 s |
  | 3 000 × 1 000, 5 MMs | 9.66 → 4.92 s | 1.83 → 0.04 s | 12.55 → 4.90 s |
  | 3 000 × 1 000, 20 MMs | 35.96 → 18.13 s | 7.90 → 0.14 s | 45.10 → 19.37 s |

  Both targets were met.
- Full suite: 14 317 passed, 1 skipped.

### WP-CFG09 — Comments, help texts, pm-help and guide (D2–D16)

**Tests first:** `tests/test_config_gen_cli_help.py` gains assertions for
the corrected `--schedule`, `--cb-levels`, `--symbol-opts` and
`--sessions-enabled` help. A pm-help test asserts pm-cverifier's exit-code
note.

**Change.** Every D item in §5 not already fixed by its WP. Remove
`DEFAULT_CB_LEVEL_SPECS` (its only purpose was the misleading default). Run
`make completion`.

**Exit criteria.** Tests pass; `make _check` is green; the guide's check
catalogue lists every code the verifier emits, with its final severity.

**Outcome (2026-11-14).**
- D2: pm-help's pm-cverifier exit-code note.
- D3: pm-help `--cb-levels NAME:SHIFT[:HALT_MINS]` (no MODE).
- D4: `DEFAULT_CB_LEVEL_SPECS` removed (the guide row was fixed in
  WP-CFG05).
- D5: the `--schedule`/`--no-schedule`, `--weekend`, `--holidays` and
  `--sessions-enabled` help and pm-help entries.
- D7:
  - A null last price is annotated "optional: set … or remove the line".
  - The `--seed-last-prices` help says a null is no reference price.
  - The diagnostic no longer recommends `--seed-last-prices`. It now says
    the engine applies no collar to a symbol until it starts with a
    reference price.
- D8, D9: the M001 and M003 suggestions. D9 is verified:
  - Seed injection (`engine/main.py:1218-1360`) has no spread check.
  - The live quote path rejects a quote that is too wide
    (`engine/main.py:4198-4230`).
- D10: the repository path in the commented defaults.
- D11: the schedule diagnostic states the written times.
- D12: `--symbol-opts` help lists its keys.
- D13: section headings for `alf_gateway`, `balf_gateway`, `log_server`,
  `monitor`, `require_mm_seed_quotes` and `indices`, with hints; no file
  has an "Additional fields" section any more.
- D14: M014's catalogue wording.
- D15: `api_gateways.<name>.…` in the 14 API help strings, and "each
  participant".
- D16: the `--log-server-retention-days` help ("Default 30", verified in
  `_build_log_server_spec`).
- Also: the guide's claim that every generated symbol carries
  `outstanding_shares` (only with `--outstanding-shares`).
- Generated artefacts: `make completion`;
  `tools/gen_config_gui_comments.py` (the Config GUI's
  `defaultFieldComments.ts` mirrors `cli_comments`); the example YAML files
  regenerated again (D13 moves sections and adds headings). Parsed content
  is identical in all 48 files, and 32 files changed text.
- Tests:
  - New `tests/test_config_tools_texts.py` (9). All failed first on the old
    texts, after a fix to my own test's `Option` attribute names.
  - Existing tests changed: the renderer's null-price hint, and
    `test_new_symbol`'s anchor (the section after `symbols` is now
    "Market-maker seed quotes").
  - The new `require_mm_seed_quotes` hint was reworded so that it does not
    contain the text `market_maker_quotes`, which
    `test_no_mm_seed_quotes_omits_quotes_and_warnings` rightly searches
    for.
- `mkdocs build` is clean. Full suite: 14 327 passed, 1 skipped.

---

## 9. Out of scope, noted

- **Loaders accept values they should refuse (L024).** The differential
  harness found these values in the engine and log-server loaders, which the
  verifier (rightly) refuses:
  - `tick_decimals: true` and `outstanding_shares: true` (bool read as 1).
  - `order_limits.max_order_qty: 1.5` (silently `int`ed to 1).
  - `schedule: 'x'`/`0` (treated as absent).
  - `log_server.enabled: 'x'`, and `log_server.name: 5`.
  - `snapshot_interval_sec`/index `base_value` `.nan` (`<= 0` checks).

  The loaders are other components' code. The verifier now stands in front
  of them, but any reader that bypasses it (tests, `load_engine_config`
  callers) still accepts them. New For-Later row **L024**.
- **`CSafeLoader`** would parse the s300 file in 0.02 s instead of 0.24 s.
  The parse lives in `config_include.load_config_mapping`, shared by every
  reader, and `compile_config` parses the file once per loader (ten times).
  That is a deploy-time cost of the shared include reader, not of these
  tools. Noted, not a defect.
- `pm-config-deploy --check` reports a loader failure as a single line
  without a code. After WP-CFG01 that path is reached only by a verifier
  bug, so it is left as is.
