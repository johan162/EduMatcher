Version: 1.1.0

Date: 2026-09-27

Status: Implemented

> **Update (v1.1.0) — implemented, with three deliberate deviations.**
>
> 1. **E3 was dropped.** The design made a gateway-wide flag inside a symbol
>    scope a hard error. That would have broken every existing command line
>    of the shape `pm-mm-bot --symbol AAPL --engine-pull ...`, which the
>    training material and the test suite both use, and §9.1 promised not to
>    break. Such a flag is now **hoisted** to the global scope and logged at
>    WARNING instead. `--config` and `--symbols` remain rejected in a symbol
>    scope — neither has a sensible hoisted meaning.
> 2. **`load_config_file` kept its signature.** The design had both loaders
>    returning `FileConfig`. Existing tests assert that `load_config_file`
>    returns the raw legacy dict, so the dispatcher was added as a new
>    `load_bot_config(path) -> FileConfig` and `load_config_file` stayed the
>    legacy flat loader, unchanged.
> 3. **The tier tables live in a new `mm_bot/params.py`**, not inline in the
>    modules that consume them, so `cli_scope.py`, `config.py`, `resolve.py`
>    and `main.py` all read one normative list.
>
> All 197 pre-existing `tests/test_mm_bot.py` + `tests/test_mm_bot_config.py`
> tests pass unmodified. The `edumatcher.mm_bot` package is at **100%
> statement and 100% branch coverage**.

# EduMatcher — Per-Symbol Configuration for `pm-mm-bot`

> **Read this first — what already exists.**
> `pm-mm-bot` is **already multi-symbol**. `docs-design/EduMatcher-MM-Bot-review.md`
> §5a was implemented and shipped in v1.5.0 of that document: one process,
> behind one gateway ID, already quotes N symbols via
> `--symbols AAPL,MSFT,TSLA`, with per-symbol state
> (`MMBot._symbols_state: dict[str, _SymbolState]`), per-symbol book/fill/
> circuit-breaker routing, and per-symbol startup failure isolation.
> A `--config <file>` flag also already exists (`src/edumatcher/mm_bot/config.py`).
>
> What does **not** exist, and what this document designs, is the part §5a.3
> explicitly deferred: **every tuning parameter is still gateway-wide.** One
> `--gap`, one `--qty`, one `--strategy`, one `--tif` is applied identically
> to every symbol. The existing config file is a flat list of those same
> gateway-wide values — it cannot say "AAPL quotes 0.10 wide in 500 lots,
> TSLA quotes 0.50 wide in 100 lots with inventory skew."
>
> This document therefore covers: (a) a repeated-`--symbol` CLI grammar where
> flags are scoped to the preceding `--symbol`, (b) a new structured YAML
> config-file schema with `defaults:` and per-symbol overrides, and (c) the
> `bot.py` changes needed to hold per-symbol *parameters* (today it only holds
> per-symbol *state*).

## Table of Contents

- [1. Scope](#1-scope)
- [2. Assumptions and open decisions](#2-assumptions-and-open-decisions)
- [3. Parameter tiers — what can vary per symbol](#3-parameter-tiers--what-can-vary-per-symbol)
- [4. CLI grammar — repeated `--symbol` scopes](#4-cli-grammar--repeated---symbol-scopes)
- [5. YAML config-file schema](#5-yaml-config-file-schema)
- [6. Precedence and merge rules](#6-precedence-and-merge-rules)
- [7. Internal changes to `bot.py`](#7-internal-changes-to-botpy)
- [8. Validation and error messages](#8-validation-and-error-messages)
- [9. Backward compatibility](#9-backward-compatibility)
- [10. Implementation plan — work packages](#10-implementation-plan--work-packages)
- [11. Test plan](#11-test-plan)
- [12. Out of scope](#12-out-of-scope)

---

## 1. Scope

### 1.1 In scope

1. **Per-symbol parameters on the CLI.** `--symbol` becomes repeatable, and
   every *symbol-scoped* flag that follows it applies to that symbol until the
   next `--symbol`.
2. **A structured YAML config file** (`--config <path>`) that expresses the
   same thing without a 400-character command line: gateway-wide settings, a
   `defaults:` block, and per-symbol override blocks.
3. **`MMBot` holding per-symbol parameters**, not just per-symbol state — the
   scalars `self.qty`, `self.tif`, `self.drift_ticks`, `self.strategy`,
   `self._max_position` and the five timing knobs move into `_SymbolState`.
4. Documentation, examples, and tests for all of the above.

### 1.2 Not in scope

Everything in [§12](#12-out-of-scope). In particular: no engine change, no
protocol change, no new pricing strategy, no hot-reload of the config file.

### 1.3 Files touched

| File | Change |
|------|--------|
| `src/edumatcher/mm_bot/bot.py` | Per-symbol parameters in `_SymbolState`; new `overrides=` constructor kwarg |
| `src/edumatcher/mm_bot/main.py` | Symbol-scope-aware argv handling; wire resolved per-symbol params |
| `src/edumatcher/mm_bot/config.py` | New v1 schema loader alongside the existing legacy flat loader |
| `src/edumatcher/mm_bot/cli_scope.py` | **New** — argv splitter (§4.3) |
| `src/edumatcher/mm_bot/resolve.py` | **New** — merge/precedence layer (§6) |
| `tests/test_mm_bot.py` | New per-symbol-parameter coverage |
| `tests/test_mm_bot_config.py` | New v1-schema coverage |
| `tests/test_mm_bot_cli_scope.py` | **New** — splitter + precedence coverage |
| `docs/user-guide/100-mm-bot.md` | New CLI grammar and config-file reference |
| `docs/examples/mm-bot/*.yaml` | **New** — worked example config files |
| `docs/training/020-setting-up-MM-bots.md` | New exercise |
| `CHANGELOG.md` | Unreleased entry |

---

## 2. Assumptions and open decisions

These are stated explicitly rather than decided silently. A reviewer who
disagrees with any of them should say so before Work Package 1 starts.

| # | Assumption | Why | If wrong |
|---|-----------|-----|----------|
| A1 | One `pm-mm-bot` process still means **one gateway ID**. Per-symbol parameters do not imply per-symbol gateways. | This is the whole point of review §5a; per-gateway identities are Phase C's job. | The design collapses to "run N processes" and nothing here is needed. |
| A2 | Specificity beats source: a per-symbol *file* setting beats a global *CLI* flag (§6). | Matches how `engine_config.yaml` resolves MM obligations (gateway-per-symbol > defaults-per-symbol > gateway-flat > global-flat). | Swap to source-first precedence; only §6 and WP5 change. |
| A3 | The existing flat config file keeps working, undeclared, as a legacy v0 format. | Files exist in the wild and in the training material. | Drop legacy support and make `version: 1` mandatory; WP4 shrinks. |
| A4 | Session-phase and shutdown timeouts stay gateway-wide (§3). | Session phase is exchange-wide; shutdown is process-wide. There is nothing per-symbol to express. | Move them to Tier 2; mechanical. |
| A5 | `--symbols AAPL,MSFT` (comma list) stays as a convenience alias for repeated `--symbol`, with no per-symbol overrides. | Already shipped and documented; removing it is a breaking change nobody asked for. | Deprecate with a warning in WP6. |
| A6 | No per-symbol logging configuration. | Records from one process go to one sink; the `[SYMBOL]` prefix already present in every log line is the discriminator. | Out of scope regardless — see §12. |

---

## 3. Parameter tiers — what can vary per symbol

Every existing flag lands in exactly one of two tiers. This table is the
**normative** list: the CLI splitter, the YAML schema, and the merge layer are
all generated from it, so it must not drift.

### 3.1 Tier 1 — gateway-wide (may **not** be symbol-scoped)

| Flag | YAML location | Reason it cannot vary per symbol |
|------|---------------|----------------------------------|
| `--label` | `gateway.label` | Part of the single gateway ID |
| `--id-suffix` | `gateway.id_suffix` | Part of the single gateway ID |
| `--engine-pull` | `gateway.engine_pull` | One PUSH socket per process |
| `--engine-pub` | `gateway.engine_pub` | One SUB socket per process |
| `--startup-session-timeout-sec` | `gateway.startup_session_timeout_sec` | Session phase is exchange-wide (A4) |
| `--shutdown-timeout-sec` | `gateway.shutdown_timeout_sec` | Shutdown is process-wide (A4) |
| `--log-level`, `-v`, `-q` | `logging.level` | One process, one log stream (A6) |
| `--log-target`, `--log-file`, `--log-failover-timeout` | `logging.*` | Same |
| `--config` | — | Chicken-and-egg: it selects the file |

### 3.2 Tier 2 — symbol-scoped (may vary per symbol)

| Flag | YAML key | Built-in default | Today's home in `bot.py` |
|------|----------|------------------|--------------------------|
| `--strategy` | `strategy` | `symmetric` | `self.strategy` |
| `--gap` | `gap` | `0.10` | `_SymbolState.gap` (already per-symbol) |
| `--qty` | `qty` | `500` | `self.qty` |
| `--max-position` | `max_position` | `null` | `self._max_position` |
| `--drift-ticks` | `drift_ticks` | `3` | `self.drift_ticks` |
| `--tif` | `tif` | `DAY` | `self.tif` |
| `--reissue-delay-ms` | `reissue_delay_ms` | `200` | `self._reissue_delay_sec` |
| `--heartbeat-interval-sec` | `heartbeat_interval_sec` | `5.0` | `self._heartbeat_interval_sec` |
| `--bootstrap-timeout-sec` | `bootstrap_timeout_sec` | `1.0` | `self._bootstrap_timeout_sec` |
| `--cancel-timeout-sec` | `cancel_timeout_sec` | `1.0` | `self._cancel_timeout_sec` |
| `--qlegs-reconcile-interval-sec` | `qlegs_reconcile_interval_sec` | `15.0` | `self._qlegs_reconcile_interval_sec` |
| `--initial_min` | `initial_min` | `null` | `self._initial_min` |
| `--initial_max` | `initial_max` | `null` | `self._initial_max` |

**Why the timing knobs are Tier 2.** A thin, fast-moving symbol wants a short
`reissue_delay_ms` and a tight `drift_ticks`; an illiquid one wants the
opposite. They are already applied *per symbol* inside `_tick_symbol` — only
the *value* is shared today. Moving the value costs one dataclass field each.

**One consequence to notice.** `_last_heartbeat` is currently a single
gateway-wide clock, and `_tick_symbol` contains a
`if symbol == self._primary_symbol:` guard to advance it exactly once per
tick. Once `heartbeat_interval_sec` is per symbol, `last_heartbeat` must move
into `_SymbolState` too, and that guard disappears. This is a simplification,
not extra work.

---

## 4. CLI grammar — repeated `--symbol` scopes

### 4.1 The grammar

```
pm-mm-bot [TIER1-FLAGS] [TIER2-FLAGS]
          --symbol SYM [TIER2-FLAGS]
          --symbol SYM [TIER2-FLAGS]
          ...
```

Rules, in plain words:

1. Anything before the **first** `--symbol` is the *global scope*.
2. Tier-1 flags may only appear in the global scope.
3. Tier-2 flags in the global scope set the default for **every** symbol.
4. Tier-2 flags after a `--symbol` apply to **that symbol only**, and override
   the global-scope value for it.
5. A symbol that names no flags of its own inherits everything.
6. `--symbols A,B,C` may be used **instead of** repeated `--symbol`, never
   together with it. It accepts no per-symbol overrides.

### 4.2 Worked example

```bash
pm-mm-bot \
  --engine-pull tcp://127.0.0.1:5555 \
  --label TECH --id-suffix 01 \
  --qty 500 --tif DAY --drift-ticks 3 \
  --symbol AAPL --gap 0.10 \
  --symbol MSFT --gap 0.20 --qty 200 \
  --symbol TSLA --gap 0.50 --qty 100 \
                --strategy inventory_skew --max-position 5000 \
                --initial_min 180 --initial_max 220
```

Resolves to gateway `MM_TECH_01` and:

| Symbol | strategy | gap | qty | tif | drift_ticks | max_position |
|--------|----------|-----|-----|-----|-------------|--------------|
| AAPL | symmetric | 0.10 | 500 | DAY | 3 | — |
| MSFT | symmetric | 0.20 | 200 | DAY | 3 | — |
| TSLA | inventory_skew | 0.50 | 100 | DAY | 3 | 5000 |

### 4.3 How the splitter works (`mm_bot/cli_scope.py`)

`argparse` cannot express "this flag belongs to the preceding `--symbol`".
So `main.py` splits `argv` **before** argparse sees it, then runs argparse
once per scope.

```python
@dataclass(frozen=True)
class ArgvScopes:
    global_argv: list[str]
    symbol_argv: list[tuple[str, list[str]]]  # (SYMBOL, that symbol's argv)


def split_argv_scopes(argv: list[str]) -> ArgvScopes:
    ...
```

Algorithm — deliberately the simplest thing that works:

1. Walk `argv` left to right.
2. On the token `--symbol`, take the **next** token as the symbol name and
   open a new scope. On `--symbol=VAL`, take `VAL` and open a new scope.
3. Every other token is appended to the currently open scope, or to
   `global_argv` if no scope is open yet.
4. Stop scope-splitting at a bare `--` separator; everything after it goes to
   the currently open scope verbatim.

There is **no need for a flag-arity table.** The only token that changes scope
is `--symbol`, and the only way a Tier-2 flag's *value* could be the literal
string `--symbol` is a value nobody will ever type. Do not build an arity
table; it is the kind of speculative machinery §2 of the repo instructions
warns about.

Then, per scope:

```python
_symbol_scope_parser()   # add_help=False, Tier-2 flags only, every default = None
```

Parsing a symbol scope with `parse_known_args` leaves any Tier-1 flag in the
leftovers. Leftovers are a hard error (§8, E3) — never silently ignored.

`None` as the universal default is load-bearing: it is what lets the merge
layer distinguish "not given" from "given the same value as the built-in
default", which today's `main.py` can only approximate by re-scanning `argv`
for the literal strings `--gap` / `--gap=`. That hack is deleted in WP6.

---

## 5. YAML config-file schema

### 5.1 Full example (`docs/examples/mm-bot/tech-desk.yaml`)

```yaml
# pm-mm-bot configuration — schema version 1
version: 1

gateway:
  label: TECH                        # gateway id becomes MM_TECH_01
  id_suffix: "01"
  engine_pull: tcp://127.0.0.1:5555
  engine_pub: tcp://127.0.0.1:5556
  startup_session_timeout_sec: 5.0
  shutdown_timeout_sec: 2.0

logging:
  level: INFO                        # CRITICAL|ERROR|WARNING|INFO|DEBUG
  target: server                     # server|stdout|file
  file: null                         # required when target: file
  failover_timeout_sec: 30

# Applied to every symbol unless that symbol overrides the key.
defaults:
  strategy: symmetric
  gap: 0.10
  qty: 500
  drift_ticks: 3
  reissue_delay_ms: 200
  tif: DAY
  heartbeat_interval_sec: 5.0
  bootstrap_timeout_sec: 1.0
  cancel_timeout_sec: 1.0
  qlegs_reconcile_interval_sec: 15.0

# The symbol universe this bot quotes. Mapping order is preserved and is the
# order symbols are started in.
symbols:
  AAPL: {}                           # inherits every default

  MSFT:
    gap: 0.20
    qty: 200

  TSLA:
    gap: 0.50
    qty: 100
    strategy: inventory_skew
    max_position: 5000
    initial_min: 180
    initial_max: 220
    drift_ticks: 5
```

### 5.2 Schema reference

| Path | Type | Req | Default | Constraints |
|------|------|:---:|---------|-------------|
| `version` | int | – | absent ⇒ legacy v0 (§9.2) | must be `1` when present |
| `gateway` | map | – | `{}` | Tier-1 keys only |
| `gateway.label` | str | – | derived from symbols | non-empty; `[A-Z0-9_]` after upper-casing |
| `gateway.id_suffix` | str | – | `"01"` | non-empty; quote it in YAML so `01` is not read as the integer `1` |
| `gateway.engine_pull` | str | – | `tcp://127.0.0.1:5555` | ZMQ endpoint |
| `gateway.engine_pub` | str | – | `tcp://127.0.0.1:5556` | ZMQ endpoint |
| `gateway.startup_session_timeout_sec` | float | – | `5.0` | `> 0` |
| `gateway.shutdown_timeout_sec` | float | – | `2.0` | `> 0` |
| `logging` | map | – | `{}` | |
| `logging.level` | enum | – | `WARNING` | `CRITICAL\|ERROR\|WARNING\|INFO\|DEBUG` |
| `logging.target` | enum | – | `server` | `server\|stdout\|file` |
| `logging.file` | str | cond. | `null` | required when `target: file` |
| `logging.failover_timeout_sec` | float | – | from log-client config | `> 0` |
| `defaults` | map | – | `{}` | Tier-2 keys only (§3.2) |
| `symbols` | map or list | **✔** | — | non-empty |
| `symbols.<SYM>` | map or `null`/`{}` | – | `{}` | Tier-2 keys only |

Tier-2 value constraints, applied identically in `defaults` and in any
`symbols.<SYM>` block:

| Key | Type | Constraint |
|-----|------|-----------|
| `strategy` | str | must be in `pricer.available_strategies()` |
| `gap` | float | `> 0` |
| `qty` | int | `> 0` |
| `max_position` | int or null | `> 0`; **only** valid with `strategy: inventory_skew` |
| `drift_ticks` | int | `> 0` |
| `tif` | enum | `DAY\|GTC` |
| `reissue_delay_ms` | int | `>= 0` |
| `heartbeat_interval_sec` | float | `> 0` |
| `bootstrap_timeout_sec` | float | `> 0` |
| `cancel_timeout_sec` | float | `> 0` |
| `qlegs_reconcile_interval_sec` | float | `> 0` |
| `initial_min` | float or null | `> 0`; must be set together with `initial_max` |
| `initial_max` | float or null | `> initial_min` |

### 5.3 Shorthand list form

For the common "same settings everywhere" case, `symbols` may be a list:

```yaml
version: 1
defaults:
  gap: 0.10
  qty: 500
symbols: [AAPL, MSFT, TSLA]
```

This is exactly equivalent to a mapping with three empty blocks. It exists so
the simple case does not have to type `{}` three times, and for no other
reason.

### 5.4 Design notes for the reviewer

- **Why a `symbols:` mapping rather than a list of `{symbol: AAPL, ...}`
  records?** It matches `engine_config.yaml`'s `symbols:` block, which every
  operator of this system already reads. Consistency inside the project beats
  abstract elegance.
- **Why a separate `gateway:` block instead of top-level keys?** It makes
  "this cannot be per-symbol" structurally obvious, so the Tier-1/Tier-2 split
  in §3 is visible in the file rather than only in the documentation.
- **Why `version:`?** It is the discriminator that lets the loader accept both
  the shipped flat format and this one without guessing (§9.2).

---

## 6. Precedence and merge rules

### 6.1 The rule

For each symbol, each Tier-2 key is resolved from the **first** source that
supplies it:

| Rank | Source |
|-----:|--------|
| 1 | The symbol's own CLI scope (`--symbol MSFT --gap 0.20`) |
| 2 | The symbol's block in the config file (`symbols.MSFT.gap`) |
| 3 | The global CLI scope (`--gap 0.20` before the first `--symbol`) |
| 4 | The config file's `defaults:` block |
| 5 | The built-in default from §3.2 |

Tier-1 keys resolve simply: CLI flag, then the config file's
`gateway:`/`logging:` block, then the built-in default.

### 6.2 Why specificity beats source (assumption A2)

Rank 2 above rank 3 is the only non-obvious line. The reasoning: if an
operator has written `symbols.TSLA.gap: 0.50` in a reviewed, version-controlled
file, a throwaway global `--gap 0.10` on the command line should widen the
symbols that were *not* individually tuned — not silently un-tune TSLA. The
operator who genuinely wants to override TSLA says so specifically:
`--symbol TSLA --gap 0.10`.

This mirrors `engine_config.yaml`'s MM-obligation resolution, which also puts
per-symbol file settings above gateway-wide ones
(`docs/user-guide/010-configuration.md`, "Market-Maker Obligation Defaults").

### 6.3 The symbol universe

The set of symbols is the **union** of the config file's `symbols:` keys and
the CLI's `--symbol` occurrences, in that order, de-duplicated. A `--symbol`
naming a symbol already present in the file opens an override scope for it
rather than adding a second entry. A repeated `--symbol AAPL` on one command
line is an error (§8, E5) — merging two scopes for the same symbol is exactly
the kind of surprising behaviour a long command line should not have.

### 6.4 `gap_was_explicit` becomes exact

`bot.py` derives a symbol's gap from its MM obligation only when the operator
did not choose one (`_startup_one_symbol`). Today `main.py` decides this by
re-scanning `argv` for the literal strings `--gap` / `--gap=`, plus a `"gap" in
file_values` check.

With `None`-sentinel defaults throughout (§4.3), this becomes exact and the
argv-scan is deleted:

```python
gap_was_explicit = resolved["gap"] is not None   # ranks 1-4 all count as explicit
```

---

## 7. Internal changes to `bot.py`

### 7.1 `_SymbolState` gains the parameters

Add to the existing dataclass (`bot.py:143`), alongside the state fields
already there:

```python
    # --- Per-symbol parameters (resolved by main.py, never mutated at runtime
    #     except `gap`, which startup may derive from the MM obligation) ---
    strategy: str = "symmetric"
    qty: int = 500
    max_position: int | None = None
    drift_ticks: int = 3
    tif: str = "DAY"
    reissue_delay_sec: float = 0.2
    heartbeat_interval_sec: float = 5.0
    bootstrap_timeout_sec: float = 1.0
    cancel_timeout_sec: float = 1.0
    qlegs_reconcile_interval_sec: float = 15.0
    initial_min: float | None = None
    initial_max: float | None = None
    last_heartbeat: float = 0.0
```

### 7.2 Constructor: one new kwarg, nothing removed

The existing flat-kwargs signature is **kept exactly as it is** and becomes the
"defaults for every symbol" layer. One optional kwarg is added:

```python
def __init__(
    self,
    *,
    gateway_id: str,
    symbol: str | None = None,
    symbols: list[str] | None = None,
    ...                                    # unchanged flat kwargs
    overrides: dict[str, dict[str, Any]] | None = None,
) -> None:
```

`overrides` maps symbol → the subset of §3.2 keys that differ for it. Building
each `_SymbolState` is then:

```python
base = {                                    # from the flat kwargs
    "strategy": strategy, "qty": qty, "tif": tif, ...
}
for sym in resolved_symbols:
    merged = {**base, **(overrides or {}).get(sym, {})}
    _reject_unknown_override_keys(sym, merged)
    self._symbols_state[sym] = _SymbolState(**merged, gap_was_explicit=...)
```

Rejected as over-engineering: a second `MMBot(symbol_params=[...])`
constructor form. `overrides=` expresses the new capability in one kwarg and
leaves all ~126 existing single-symbol tests untouched.

### 7.3 Call sites to convert

Mechanical: every read of a scalar becomes a read of `st.<field>`.

| Current | Becomes | Location |
|---------|---------|----------|
| `self.qty` | `st.qty` | `_send_quote` (`bid_qty`/`ask_qty`) |
| `self.tif` | `st.tif` | `_send_quote` |
| `self._max_position` | `st.max_position` | `_send_quote` saturation log |
| `self.strategy`, `self.drift_ticks`, `self._max_position` | `st.*` | `_startup_one_symbol` → `create_strategy(...)` |
| `self._initial_min` / `_initial_max` | `st.initial_min` / `st.initial_max` | `_resolve_bootstrap_reference` |
| `self._bootstrap_timeout_sec` | `st.bootstrap_timeout_sec` | `_request_bootstrap`, `_request_qlegs` |
| `self._cancel_timeout_sec` | `st.cancel_timeout_sec` | `_cancel_and_reissue` |
| `self._reissue_delay_sec` | `st.reissue_delay_sec` | fill/reissue scheduling |
| `self._heartbeat_interval_sec` | `st.heartbeat_interval_sec` | `_tick_symbol` |
| `self._qlegs_reconcile_interval_sec` | `st.qlegs_reconcile_interval_sec` | `_tick_symbol` |
| `self._last_heartbeat` | `st.last_heartbeat` | `_tick_symbol`; delete the `symbol == self._primary_symbol` guard |

`self._shutdown_timeout_sec` and `self._startup_session_timeout_sec` stay
scalar (Tier 1).

### 7.4 Backward-compatible proxies

`bot.py` already has the pattern (`bot.py:297-436`): a property pair proxying
to `self._symbols_state[self._primary_symbol]`. Add the same for the newly
per-symbol names so single-symbol tests and the `run()` startup log line keep
working unchanged:

`strategy`, `qty`, `drift_ticks`, `tif`, `_max_position`, `_reissue_delay_sec`,
`_heartbeat_interval_sec`, `_bootstrap_timeout_sec`, `_cancel_timeout_sec`,
`_qlegs_reconcile_interval_sec`, `_initial_min`, `_initial_max`,
`_last_heartbeat` — each with a getter **and** a setter, because existing
tests assign to several of them directly.

### 7.5 Poll timeout

`_run_loop` currently computes the poll interval from the two gateway-wide
timing scalars:

```python
shortest_interval_sec = min(self._heartbeat_interval_sec, self._reissue_delay_sec)
```

With per-symbol values it becomes the minimum across all **active** symbols:

```python
shortest_interval_sec = min(
    min(st.heartbeat_interval_sec, st.reissue_delay_sec)
    for st in (self._symbols_state[s] for s in active)
)
```

The existing `max(50, ...)` floor is unchanged. Note `reissue_delay_sec` can
legitimately be `0`, so the floor is what stops a busy loop — keep it.

### 7.6 Startup log line

`run()` logs one line naming `gap`, `qty`, `tif`, `drift_ticks`. With
per-symbol values, log one line per symbol instead:

```
starting: gateway=MM_TECH_01 symbols=AAPL,MSFT,TSLA
  [AAPL] strategy=symmetric gap=0.10 qty=500 tif=DAY drift_ticks=3
  [MSFT] strategy=symmetric gap=0.20 qty=200 tif=DAY drift_ticks=3
  [TSLA] strategy=inventory_skew gap=0.50 qty=100 tif=DAY drift_ticks=5 max_position=5000
```

This is the operator's confirmation that a long command line or a config file
resolved the way they intended, so it belongs at INFO, not DEBUG.

---

## 8. Validation and error messages

All of these are **startup** errors: log at ERROR and `SystemExit(1)` before
any socket is opened. None of them degrade a single symbol — an unparseable
command line or config file is an operator mistake, not a runtime condition.
(Per-symbol *degrade* remains exactly as review §5a.4 option 2 defines it, for
failures discovered by talking to the engine: symbol not listed, gap exceeds
the MM obligation, no reference price.)

| # | Condition | Message |
|---|-----------|---------|
| E1 | `--symbol` and `--symbols` both given | `--symbol and --symbols are mutually exclusive` |
| E2 | No symbol from any source | `no symbols configured: use --symbol, --symbols, or a config file with a 'symbols:' block` |
| E3 | Tier-1 flag inside a symbol scope | *(v1.1.0: hoisted to the global scope with a WARNING instead of rejected — see the update note at the top)* |
| E3b | `--config`/`--symbols` inside a symbol scope | `--symbols and --config are gateway-wide and cannot follow --symbol AAPL` |
| E4 | `--symbol` with no value / at end of argv | `--symbol requires a symbol name` |
| E5 | Same symbol named twice on the CLI | `--symbol AAPL given more than once` |
| E6 | Unknown key in `defaults:` or `symbols.<S>:` | `config file X: unknown key 'gapp' under symbols.AAPL (did you mean 'gap'?)` |
| E7 | Tier-1 key inside `defaults:`/`symbols.<S>:` | `config file X: 'engine_pull' is a gateway-wide setting; move it under 'gateway:'` |
| E8 | `version:` present and not `1` | `config file X: unsupported version 2 (this build understands version 1)` |
| E9 | `max_position` set for a non-skew strategy | `[TSLA] max_position is only meaningful with strategy inventory_skew (got symmetric)` |
| E10 | `strategy: inventory_skew` with no `max_position` | `[TSLA] max_position is required when strategy inventory_skew is selected` |
| E11 | Only one of `initial_min`/`initial_max` set | `[TSLA] initial_min and initial_max must be set together` |
| E12 | Any numeric constraint from §5.2 violated | `[MSFT] qty must be positive (got -1)` |

E9–E12 already exist in `main.py` as gateway-wide checks; they become
**per-symbol** checks run in a loop over the resolved symbol table. The
`(did you mean ...)` hint in E6 uses `difflib.get_close_matches` against the
allowed key set — cheap, and the single most common config-file mistake.

---

## 9. Backward compatibility

### 9.1 Command line

| Invocation | Still works? |
|------------|--------------|
| `--symbol AAPL --gap 0.1 --qty 500` | Yes, identically — one scope, one symbol |
| `--symbols AAPL,MSFT --gap 0.1` | Yes, identically — A5 |
| `--symbol AAPL --symbols MSFT` | No — already an error today (E1) |
| Flags placed *after* a single `--symbol` | Yes — they scope to that one symbol, which is the same thing |

The last row is the one to check carefully: today
`pm-mm-bot --symbol AAPL --gap 0.1` puts `--gap` in AAPL's scope rather than
the global scope. With one symbol, the resolved value is identical, so no
existing single-symbol command line changes meaning. **This is what makes the
new grammar additive rather than breaking**, and WP3 must have a test that
says so.

### 9.2 Config file

`load_config_file` dispatches on shape:

```python
if raw.get("version") == 1 or isinstance(raw.get("symbols"), dict):
    return _load_v1(raw, path)       # new structured schema, §5
return _load_legacy_flat(raw, path)  # today's code path, unchanged
```

Legacy flat files (a single mapping of `main.py` flag names, with `symbols:` as
a comma string or list of strings) keep loading and keep applying as
gateway-wide argparse defaults. Both loaders return the same internal shape
(§10, WP4) so `main.py` has exactly one code path after the load.

Document the flat form as deprecated in the user guide; do **not** emit a
runtime deprecation warning — a warning on every start of an otherwise working
setup is noise, and there is no removal date to point at.

### 9.3 `MMBot` API

No removals. `overrides=` defaults to `None`; every existing kwarg keeps its
meaning as the all-symbols default; every scalar attribute that moves into
`_SymbolState` keeps a proxy property (§7.4).

---

## 10. Implementation plan — work packages

Nine packages. Each is independently reviewable, leaves the repo green, and
has explicit done-criteria. **Every package ends with the standard gate:**

```bash
poetry run black --check src tests
poetry run flake8 src tests
poetry run mypy src tests
poetry run pyright src tests
poetry run pytest tests/test_mm_bot.py tests/test_mm_bot_config.py -q
```

"Gate green" below means all five commands pass. WP9 additionally runs the
full suite.

---

### WP0 — Baseline

**Do:** Record the current pass count of `tests/test_mm_bot.py` and
`tests/test_mm_bot_config.py`. Record the current `mypy`/`pyright` output for
`src/edumatcher/mm_bot/` as the diagnostic baseline. Do not change any code.

**Done when:**
- [ ] Baseline test count written into the WP1 PR description.
- [ ] Baseline type-checker output is empty (if it is not, fix or record the
      pre-existing diagnostics before starting WP1 — otherwise you cannot tell
      which ones you caused).

**Estimated diff:** 0 lines.

---

### WP1 — Per-symbol parameters in `_SymbolState`

**Do:** §7.1, §7.2, §7.3, §7.4. Add the fields, add `overrides=`, convert
every call site, add the proxy properties. Do **not** touch `main.py`,
`config.py`, or the CLI.

**Done when:**
- [ ] `_SymbolState` carries every Tier-2 parameter from §3.2.
- [ ] `grep -n "self\.qty\|self\.tif\|self\._max_position\|self\._initial_m" src/edumatcher/mm_bot/bot.py`
      returns **only** the proxy property definitions — no logic reads a
      per-symbol parameter off `self` any more.
- [ ] All pre-existing `tests/test_mm_bot.py` tests pass **unmodified**. If a
      test needs changing, stop and explain why in the PR — an unmodified pass
      is the whole safety net for this package.
- [ ] New test: `MMBot(symbols=["AAPL","MSFT"], qty=500, overrides={"MSFT": {"qty": 200}})`
      yields `_symbols_state["AAPL"].qty == 500` and
      `_symbols_state["MSFT"].qty == 200`.
- [ ] New test: an unknown key in `overrides` raises `ValueError` naming the
      key and the symbol.
- [ ] Gate green.

---

### WP2 — Per-symbol timing

**Do:** §7.5 and the `last_heartbeat` move from §7.1/§7.3. Delete the
`symbol == self._primary_symbol` guard in `_tick_symbol`.

**Done when:**
- [ ] `_last_heartbeat` exists only as a proxy property.
- [ ] Poll timeout is the minimum across active symbols, with the 50 ms floor
      intact.
- [ ] New test: two symbols with `heartbeat_interval_sec` 1.0 and 10.0; with a
      monkeypatched clock, driving `_tick()` repeatedly fires the fast
      symbol's heartbeat reissue roughly ten times for each of the slow
      symbol's, and neither resets the other's clock.
- [ ] New test: `reissue_delay_ms: 0` on one symbol still yields a poll
      timeout of exactly 50 ms.
- [ ] All WP1 tests still pass.
- [ ] Gate green.

---

### WP3 — Argv scope splitter

**Do:** New `src/edumatcher/mm_bot/cli_scope.py` with `ArgvScopes` and
`split_argv_scopes` (§4.3), plus the Tier-2-only scope parser. Pure functions,
no wiring into `main.py` yet.

**Done when:**
- [ ] New `tests/test_mm_bot_cli_scope.py` covers, at minimum:
      no `--symbol` at all (everything global); one `--symbol` with trailing
      flags; three `--symbol`s with mixed flags; `--symbol=AAPL` equals-form;
      a `--` separator; `--symbol` as the final token (E4); a repeated symbol
      (E5); a Tier-1 flag in a symbol scope (E3).
- [ ] Explicit regression test for §9.1's last row: splitting
      `["--symbol","AAPL","--gap","0.1"]` and resolving it produces the same
      parameter table as `["--gap","0.1","--symbol","AAPL"]`.
- [ ] `split_argv_scopes` never mutates its argument.
- [ ] Gate green.

---

### WP4 — v1 config-file loader

**Do:** Extend `src/edumatcher/mm_bot/config.py` with `_load_v1` and the shape
dispatcher (§9.2). Define the one internal return type both loaders produce:

```python
@dataclass(frozen=True)
class FileConfig:
    gateway: dict[str, Any]        # Tier-1 keys
    logging: dict[str, Any]
    defaults: dict[str, Any]       # Tier-2 keys
    symbols: dict[str, dict[str, Any]]   # SYMBOL -> Tier-2 overrides, order preserved
```

A legacy flat file returns `FileConfig(gateway=..., logging=..., defaults=<the
flat Tier-2 keys>, symbols={sym: {} for sym in ...})` — which is precisely why
`main.py` needs no branch on format.

**Done when:**
- [ ] `docs/examples/mm-bot/tech-desk.yaml` (the §5.1 file) loads and produces
      the §4.2 parameter table, asserted field by field in a test.
- [ ] The list shorthand (§5.3) produces the same `FileConfig` as the
      equivalent mapping form.
- [ ] Every existing `tests/test_mm_bot_config.py` test passes **unmodified**
      (legacy path).
- [ ] Error tests for E6, E7, E8, and for `symbols:` missing/empty.
- [ ] E6's "did you mean" hint fires for `gapp` → `gap`.
- [ ] Symbol keys are upper-cased; `symbols: {aapl: {...}}` resolves to `AAPL`.
- [ ] Gate green.

---

### WP5 — Merge and precedence layer

**Do:** New `src/edumatcher/mm_bot/resolve.py`:

```python
def resolve_symbol_params(
    file_config: FileConfig,
    global_cli: dict[str, Any],           # Tier-2, None = not given
    symbol_cli: list[tuple[str, dict[str, Any]]],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Return (ordered symbol list, symbol -> fully resolved Tier-2 params)."""
```

Implements §6.1's five ranks, §6.3's union/ordering, and the per-symbol
validation E9–E12. Pure function — no argparse, no I/O, no logging.

**Done when:**
- [ ] A table-driven test walks all five precedence ranks for one key
      (`gap`), asserting the winner at each rank as higher ranks are removed.
- [ ] Test: per-symbol file value beats global CLI value (A2 / §6.2), with a
      comment in the test naming the assumption — this is the line most likely
      to be "fixed" by a future reader who thinks it is a bug.
- [ ] Test: symbol universe is the union, file order first, CLI-only symbols
      appended.
- [ ] Tests for E9, E10, E11, E12, each asserting the symbol name appears in
      the message.
- [ ] Test: `gap` unset everywhere resolves to `None`, so §6.4's
      `gap_was_explicit` is `False`; set at any rank 1–4 gives `True`.
- [ ] Gate green.

---

### WP6 — Wire it into `main.py`

**Do:** Replace `main()`'s current flow with: split argv (WP3) → load file
(WP4) → parse global scope and each symbol scope → resolve (WP5) → validate →
construct `MMBot(..., overrides=...)`. Delete the `gap_was_explicit` argv scan
(§6.4). Keep `--symbols` working (A5). Add `--symbol` to the splitter's
vocabulary and remove it from the main argparse parser.

**Careful:** the current first-pass `parse_known_args` that finds `--config`
must run on `global_argv`, not on raw `argv`, or a `--config` typed after a
`--symbol` would be silently ignored. Better: make `--config` Tier-1 and let
E3 reject it in a symbol scope.

**Done when:**
- [ ] The §4.2 worked example, run with a stubbed `MMBot`, produces exactly
      the §4.2 table.
- [ ] Existing `TestMainParsing` tests pass unmodified.
- [ ] Test: config file + CLI overrides together produce the §6.1 ranking.
- [ ] Test: E1–E5 each exit `1` with the documented message on stderr/log.
- [ ] `grep -c '"--gap"' src/edumatcher/mm_bot/main.py` shows the argv-scan
      hack is gone.
- [ ] Gate green.

---

### WP7 — Gateway identity

**Do:** Confirm and, if needed, adjust label derivation with the new sources.
Rule (unchanged in spirit from review §5a.3): `--label`/`gateway.label` if
given; else the single symbol's name if there is exactly one; else
`SYM1_SYM2_...`. Gateway ID stays `MM_<LABEL>_<id_suffix>`.

**Done when:**
- [ ] Test: one symbol, no label → `MM_AAPL_01` (byte-identical to today).
- [ ] Test: three symbols, no label → `MM_AAPL_MSFT_TSLA_01`.
- [ ] Test: `gateway.label: TECH` in the file → `MM_TECH_01`; a CLI `--label`
      beats it.
- [ ] Test: `id_suffix: 01` written unquoted in YAML (so PyYAML yields the
      integer `1`) is rejected or normalised — decide which, document it, and
      assert it.
- [ ] Gate green.

---

### WP8 — Documentation and examples

**Do:**
- `docs/user-guide/100-mm-bot.md`: the §4 grammar, the §3 tier table, the §5
  schema reference, the §6 precedence table, the §8 error list.
- `docs/examples/mm-bot/tech-desk.yaml` (§5.1) and a minimal
  `docs/examples/mm-bot/single-symbol.yaml`.
- `docs/training/020-setting-up-MM-bots.md`: one exercise that starts a
  three-symbol bot from a config file and observes the different spreads.
- `CHANGELOG.md`: an Unreleased entry (see the `changelog-entry` skill;
  end-user framing, not implementation prose).
- Update this document's Status line to "Implemented".

**Done when:**
- [ ] `poetry run mkdocs build` is clean (no broken links, no orphan pages).
- [ ] Every example YAML in the docs is a real file under
      `docs/examples/mm-bot/` **and** is loaded by a test, so a doc example
      cannot rot into an invalid file.
- [ ] The user guide no longer says any Tier-2 parameter is gateway-wide.

---

### WP9 — Full verification

**Do:** Full gate across the repo, then a manual end-to-end run.

**Done when:**
- [ ] `poetry run pytest tests/ -n auto --cov=src/edumatcher --cov-fail-under=85`
      passes; no test outside `tests/test_mm_bot*.py` changed.
- [ ] `black`, `flake8`, `mypy`, `pyright` all clean on `src tests`.
- [ ] Manual run against a live `pm-engine`: a three-symbol config file with
      three different gaps, verified with `QLEGS` from an admin console —
      each symbol's resting legs show its own configured spread and size.
- [ ] Manual run: kill the bot with SIGTERM; all three symbols' quotes are
      cancelled within `gateway.shutdown_timeout_sec`.

---

## 11. Test plan

### 11.1 Regression safety net

The 126 existing `tests/test_mm_bot.py` + `tests/test_mm_bot_config.py` tests
must pass **unmodified** through WP1–WP5. WP6 may change only the assertions
that inspect `main.py`'s kwargs to `MMBot` — and any such change must be
called out as a deliberate behaviour change, exactly as review §5a did for the
`symbol=` → `symbols=[...]` change.

### 11.2 New coverage, by theme

| Theme | Key cases |
|-------|-----------|
| Splitter | §4.3 forms; E3–E5; argv not mutated |
| Loader | §5.1 example; list shorthand; legacy flat; E6–E8; upper-casing |
| Precedence | All five ranks; A2's rank-2-beats-rank-3 case; union ordering |
| Per-symbol params | Different `qty`/`gap`/`tif` reach the right `quote.new` payload |
| Per-symbol strategy | `inventory_skew` on one symbol, `symmetric` on another, in one bot |
| Per-symbol timing | Independent heartbeat clocks; independent QLEGS intervals |
| Isolation | A fill on A while B has an in-flight cancel (extend the existing `TestFillDuringCancelInFlight` pattern) with *different* per-symbol parameters, so a leaked parameter shows up as a wrong price or size |
| Validation | E9–E12 per symbol; the failing symbol is named |
| Back-compat | Every §9.1 row |

### 11.3 The test that matters most

One integration-style test using the existing fake-socket harness:

> Three symbols with deliberately different `gap`, `qty`, `tif`, and
> `strategy`. Drive a full startup, then a book update on each symbol in turn.
> Assert the three emitted `quote.new` payloads each carry that symbol's own
> `bid_qty`/`ask_qty`, `tif`, and a spread matching its own `gap`.

If a parameter leaks across symbols, this catches it in one assertion block.

---

## 12. Out of scope

- **Per-symbol gateway IDs.** That is review Phase C's swarm launcher; see
  review §5a.8 for when it is the right tool.
- **Hot reload.** The config file is read once at startup. Changing a symbol's
  gap means restarting the bot.
- **Per-symbol logging destinations** (A6).
- **New pricing strategies.** `symmetric` and `inventory_skew` only; this
  document changes *where parameters come from*, not what they drive.
- **Adding or removing symbols at runtime.** The symbol set is fixed for the
  process's life, matching the engine's own "symbol universe is fixed at
  startup" rule.
- **A JSON Schema file for the config format.** The §5.2 table plus the loader
  are the specification. Add one only if a GUI (like the existing
  `web-apps/config-gui` for `engine_config.yaml`) is ever built for it.
- **`pm-config-gen` support** for emitting mm-bot config files. Reasonable
  follow-up; not needed to ship this.
