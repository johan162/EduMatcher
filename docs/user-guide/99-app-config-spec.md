# Appendix: Engine Configuration Specification

**Status: Normative.** This appendix defines the formal structure of
`engine_config.yaml`, the single reference-data file for an EduMatcher exchange.
It is the authoritative schema; where it and any tutorial disagree, this document
governs. For worked examples, recipes, and rationale, see
[Configuration](01-configuration.md) (informative).

The schema described here is derived from and MUST match the runtime loaders:
`engine/config_loader.py`, `alf_gwy/config.py`, `balf_gwy/config.py`,
`ralf_gateway/config.py`, `md_gateway/config.py`, and `api_gateway/config.py`.
`pm-cverifier` is the reference validator.

---

## 1. Conventions

### 1.1 Requirement keywords

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **MAY**, and
**OPTIONAL** are to be interpreted as described in RFC 2119.

### 1.2 The file

The configuration is a single YAML 1.1 document whose root MUST be a **mapping**.
A loader given a non-mapping root MUST reject the file. When the file is **absent**
entirely, the engine runs in *unrestricted mode* (no symbol/gateway allowlist,
sessions disabled); that mode is out of scope here — this document specifies the
content of a *present* file.

### 1.3 Scalar type notation

Field tables and the schema tree (§3) use these type names:

| Type | YAML form | Definition |
|------|-----------|------------|
| `Bool` | boolean | `true` / `false` |
| `Int` | integer | whole number |
| `Float` | number | integer or decimal; parsed as floating point |
| `Str` | string | UTF-8 text |
| `Path` | string | filesystem path (`~` is expanded where noted) |
| `Symbol` | string | instrument id; **normalised to upper-case** on load |
| `GatewayId` | string | participant id; non-empty; **normalised to upper-case** |
| `IndexId` | string | index id; **alphanumeric**, upper-case, unique |
| `Price` | number | price in **display units** (e.g. `150.10`) |
| `Qty` | integer | quantity; `> 0` unless stated |
| `Ticks` | integer | count of minimum price increments; `> 0` |
| `Pct01` | number | fraction in the **open** interval `(0, 1)` |
| `Nanos` | integer | duration in nanoseconds; `> 0` (or `null` where noted) |
| `Secs` | number | duration in seconds; `> 0` |
| `Port` | integer | TCP port; `> 0` (BALF: `1..65535`) |
| `HHMM` | string | wall-clock local time `"HH:MM"` |
| `Enum<E>` | string | one member of enum `E` (§2); **case-insensitive**, stored upper-case |
| `List<T>` | sequence | ordered list of `T` |
| `Map<K,V>` | mapping | keyed collection; keys of type `K`, values of type `V` |

### 1.4 Field-table columns

Each section table uses: **Field**, **Type**, **Req** (`✔` required / `–`
optional), **Default** (value applied when the key is omitted from a *present*
file), and **Constraints**. A `Default` of `—` means the field has no default and,
if optional, its absence leaves the feature disabled.

### 1.5 Unknown keys

Loaders are **permissive**: a key not defined in this specification is **ignored**
and MUST NOT be relied upon for behaviour. Conforming producers SHOULD NOT emit
unknown keys. `pm-cverifier` MAY warn on them.

### 1.6 Case normalisation

`Symbol`, `GatewayId`, `IndexId`, and every `Enum<E>` value are upper-cased during
load. Producers MAY write any case; consumers compare upper-case.

---

## 2. Enumerations

| Enum | Members | Used by |
|------|---------|---------|
| `Role` | `TRADER`, `MARKET_MAKER`, `ADMIN` | `gateways.alf[].role` |
| `DisconnectBehaviour` | `CANCEL_QUOTES_ONLY`, `CANCEL_ALL`, `LEAVE_ALL` | `gateways.alf[].disconnect_behaviour` |
| `QuoteRefreshPolicy` | `INACTIVATE_ON_ANY_FILL`, `INACTIVATE_ON_FULL_FILL`, `NEVER_INACTIVATE` | `gateways.alf[].quote_refresh_policy` |
| `TIF` | `DAY`, `GTC`, `ATO`, `ATC` | quote/combo seeds |
| `ComboType` | `AON` | `market_maker_combos[].combo_type` |
| `Side` | `BUY`, `SELL` | combo legs |
| `OrderType` | `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `FOK`, `ICEBERG`, `IOC`, `TRAILING_STOP` | combo legs |
| `SmpAction` | `NONE`, `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, `CANCEL_BOTH` | combo legs |
| `ResumptionMode` | `AUCTION`, `CONTINUOUS` | circuit-breaker levels |
| `DuplicateSessionPolicy` | `REJECT_NEW`, `EVICT_OLD` | `balf_gateway.duplicate_session_policy` |

An `Enum<E>` value outside its member set MUST be rejected.

---

## 3. Formal schema tree

The complete structure at a glance. Annotations: `!` = REQUIRED key, `?` =
OPTIONAL key, `=` = default, `∈` = domain/constraint. Types are from §1.3–§2.
This tree is normative for *shape*; §4–§6 are normative for *field law*.

```yaml
# ── ENGINE (read by pm-engine) ──────────────────────────────────────────────
symbols:                    ! Map<Symbol, SymbolSpec>          # ≥0 entries; key required
gateways:                   ! Map
  alf:                      ! List<AlfGatewaySpec>             # ≥1 entry
sessions_enabled:           ? Bool = true
enforce_collars:            ? Bool = true
enforce_circuit_breakers:   ? Bool = true
snapshot_interval_sec:      ? Float = 0.5     ∈ > 0
mm_obligation_defaults:     ? MMObligationDefaultsSpec
risk_controls:              ? RiskControlsSpec
circuit_breaker_defaults:   ? CircuitBreakerSpec
market_maker_combos:        ? List<ComboSeedSpec>              # each: 2..10 legs
indices:                    ? List<IndexSpec>                  # ≤ 5
schedule:                   ? ScheduleSpec

# ── AUXILIARY GATEWAY BLOCKS (each read by its own process) ─────────────────
alf_gateway:                ? AlfGwyProcSpec        # pm-alf-gwy
balf_gateway:               ? BalfGwyProcSpec       # pm-balf-gwy
market_data_gateway:        ? MdGwyProcSpec         # pm-md-gwy   (CALF)
post_trade_gateway:         ? RalfGwyProcSpec       # pm-ralf-gwy (RALF)
api_gateways:               ? Map<Str, ApiGwyProcSpec>   # pm-api-gwy (named instances)

SymbolSpec:
  level:                    ? Str          ∈ key of risk_controls.levels
  tick_decimals:            ? Int = 2      ∈ 0..8
  outstanding_shares:       ? Int          ∈ > 0        # REQUIRED for index constituents
  last_buy_price:           ? Price
  last_sell_price:          ? Price
  market_maker_quotes:      ? List<MMQuoteSeedSpec>
  collar:                   ? CollarSpec
  circuit_breaker:          ? CircuitBreakerSpec         # per-symbol override

AlfGatewaySpec:                              # one entry of gateways.alf
  id:                       ! GatewayId
  description:              ? Str = ""
  role:                    ? Enum<Role> = TRADER
  disconnect_behaviour:    ? Enum<DisconnectBehaviour> = CANCEL_QUOTES_ONLY
  quote_refresh_policy:    ? Enum<QuoteRefreshPolicy> = INACTIVATE_ON_ANY_FILL
  enforce_mm_obligation:   ? Bool = <mm_obligation_defaults.enforce_mm_obligation | false>
  mm_max_spread_ticks:     ? Ticks = <default 10>
  mm_min_qty:              ? Qty   = <default 100>
  mm_obligations:          ? Map<Symbol, MMObligationSpec>
```

---

## 4. Domain sub-structures

### 4.1 `MMQuoteSeedSpec` — `symbols.<S>.market_maker_quotes[]`

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `gateway_id` | `GatewayId` | ✔ | — | MUST reference a configured gateway whose `role` is `MARKET_MAKER` |
| `bid_price` | `Price` | ✔ | — | `bid_price < ask_price` |
| `ask_price` | `Price` | ✔ | — | `> bid_price` |
| `bid_qty` | `Qty` | ✔ | — | `> 0` |
| `ask_qty` | `Qty` | ✔ | — | `> 0` |
| `tif` | `Enum<TIF>` | – | `DAY` | |
| `quote_id` | `Str` | – | `null` | empty string treated as `null` |
| `seed_once` | `Bool` | – | `true` | when `true`, skip injection if `book_stats` already has this symbol |

### 4.2 `CollarSpec` — `symbols.<S>.collar` and `risk_controls.levels.<L>.collar`

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `static_band_pct` | `Pct01` | – | `0.20` | `0 < x < 1` |
| `dynamic_band_pct` | `Pct01` | – | `0.02` | `0 < x < 1` |

A per-symbol `collar` is merged over the symbol's resolved `level` collar
(symbol keys win). When neither is present, no collar applies to the symbol.

### 4.3 `MMObligationSpec` — `gateways.alf[].mm_obligations.<S>`

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `enforce_mm_obligation` | `Bool` | – | gateway's `enforce_mm_obligation` | |
| `max_spread_ticks` | `Ticks` | – | gateway's `mm_max_spread_ticks` | `> 0` |
| `min_qty` | `Qty` | – | gateway's `mm_min_qty` | `> 0` |

### 4.4 `ComboSeedSpec` — `market_maker_combos[]`

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `combo_id` | `Str` | ✔ | — | non-empty |
| `combo_type` | `Enum<ComboType>` | – | `AON` | |
| `tif` | `Enum<TIF>` | – | `DAY` | |
| `legs` | `List<ComboLegSpec>` | ✔ | — | length `2..10`; symbols unique within the combo |

`ComboLegSpec`:

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `symbol` | `Symbol` | ✔ | — | MUST exist in `symbols` |
| `side` | `Enum<Side>` | ✔ | — | |
| `order_type` | `Enum<OrderType>` | ✔ | — | |
| `quantity` | `Qty` | ✔ | — | |
| `price` | `Ticks` | – | `null` | required by order types that carry a limit price |
| `stop_price` | `Ticks` | – | `null` | |
| `smp_action` | `Enum<SmpAction>` | – | `NONE` | |

### 4.5 `IndexSpec` — `indices[]`

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `id` | `IndexId` | ✔ | — | alphanumeric; unique across `indices` |
| `description` | `Str` | ✔ | — | non-empty |
| `base_value` | `Float` | – | `1000.0` | `> 0` |
| `publish_interval_sec` | `Secs` | – | `1.0` | `> 0` |
| `history_file` | `Path` | – | `data/indexes/<id>_history.jsonl` | non-empty |
| `state_file` | `Path` | – | `data/indexes/<id>_state.json` | non-empty |
| `constituents` | `List<Symbol>` | ✔ | — | non-empty; each MUST exist in `symbols` **and** define `outstanding_shares`; no duplicates |

### 4.6 `ScheduleSpec` — `schedule`

| Field | Type | Req | Default |
|-------|------|:---:|---------|
| `pre_open` | `HHMM` | – | `"09:00"` |
| `opening_auction_start` | `HHMM` | – | `"09:25"` |
| `continuous_start` | `HHMM` | – | `"09:30"` |
| `closing_auction_start` | `HHMM` | – | `"16:00"` |
| `closing_auction_end` | `HHMM` | – | `"16:05"` |

---

## 5. Engine sections

### 5.1 `symbols` (REQUIRED)

`Map<Symbol, SymbolSpec>`. The mapping key is the symbol id. A value of `null`/`{}`
is a valid empty spec. Symbol fields: see the schema tree (§3, `SymbolSpec`);
`market_maker_quotes` §4.1, `collar` §4.2, `circuit_breaker` §5.6.

### 5.2 `gateways.alf` (REQUIRED)

`List<AlfGatewaySpec>` with **at least one** entry (§3, `AlfGatewaySpec`). Gateway
ids MUST be unique after upper-casing. This list is the participant allowlist and
is **also** consumed by `pm-alf-gwy` and `pm-balf-gwy` for identity and role.

### 5.3 Engine behaviour flags

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `sessions_enabled` | `Bool` | – | `true` | when `true`, engine starts `CLOSED` and honours `schedule`/session transitions; when `false`, starts and stays `CONTINUOUS` |
| `enforce_collars` | `Bool` | – | `true` | global collar enforcement toggle |
| `enforce_circuit_breakers` | `Bool` | – | `true` | global circuit-breaker enforcement toggle |
| `snapshot_interval_sec` | `Float` | – | `0.5` | `> 0`; per-symbol book snapshot throttle |

> NOTE — `sessions_enabled` default: the engine loader applies `true` when the key
> is omitted from a *present* file. (A completely absent config file runs
> unrestricted with sessions disabled — see [Auctions & Scheduling](06-auctions-scheduling.md).)

### 5.4 `mm_obligation_defaults` (OPTIONAL) — `MMObligationDefaultsSpec`

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `enforce_mm_obligation` | `Bool` | – | `false` | |
| `mm_max_spread_ticks` | `Ticks` | – | `10` | `> 0` |
| `mm_min_qty` | `Qty` | – | `100` | `> 0` |
| `symbols` | `Map<Symbol, {enforce_mm_obligation, mm_max_spread_ticks, mm_min_qty}>` | – | `{}` | each key MUST exist in `symbols`; per-symbol fields default to the block-level values above |

These values supply the defaults inherited by `gateways.alf[]` obligation fields.

### 5.5 `risk_controls` (OPTIONAL) — `RiskControlsSpec`

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `default_level` | `Str` | – | `null` | non-empty; MUST be a key of `levels` |
| `levels` | `Map<Str, {collar: CollarSpec}>` | – | `{}` | level names upper-cased |

`risk_controls.levels.<L>.circuit_breaker` is **NOT supported** and MUST be
rejected; define circuit breakers under `circuit_breaker_defaults` (§5.6) instead.

### 5.6 `circuit_breaker_defaults` and `symbols.<S>.circuit_breaker` — `CircuitBreakerSpec`

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `reference_window_ns` | `Nanos` | – | `300000000000` (5 min) | rolling reference window |
| `levels` | `Map<Str, CBLevelSpec>` | – | built-in `L1/L2/L3` | non-empty after merge |

`CBLevelSpec`:

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `price_shift_pct` | `Pct01` | ✔ | — | `0 < x < 1` |
| `halt_duration_ns` | `Nanos` \| `null` | – | — | `> 0` when set; `null` = halt for the rest of the trading day |
| `resumption_mode` | `Enum<ResumptionMode>` | – | `AUCTION` | |

Merge order: `circuit_breaker_defaults` supplies defaults; a symbol's
`circuit_breaker.levels.<L>` overrides by level key. If no levels result from the
merge, the built-in ladder applies: `L1 = 0.07 / 5 min`, `L2 = 0.13 / 15 min`,
`L3 = 0.20 / rest-of-day`, all `AUCTION`.

### 5.7 `market_maker_combos` (OPTIONAL)

`List<ComboSeedSpec>` — see §4.4.

### 5.8 `indices` (OPTIONAL)

`List<IndexSpec>`, **at most 5** entries — see §4.5.

### 5.9 `schedule` (OPTIONAL)

`ScheduleSpec` — see §4.6. Consumed by `pm-engine` (when `sessions_enabled`) and,
independently, by `pm-scheduler`.

---

## 6. Auxiliary gateway blocks

Each block below is read **only** by its own process; `pm-engine` ignores them.
See [Configuration → Which Process Reads What](01-configuration.md#which-process-reads-what).

### 6.1 `alf_gateway` — `pm-alf-gwy`

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `enabled` | `Bool` | – | `true` | |
| `name` | `Str` | – | `"alf-gwy01"` | |
| `bind_address` | `Str` | – | `"0.0.0.0"` | |
| `port` | `Port` | – | `5565` | `> 0` |
| `heartbeat_interval_sec` | `Int` | – | `5` | `> 0` |
| `idle_timeout_sec` | `Int` | – | `30` | `> 0` |
| `max_connections` | `Int` | – | `64` | `> 0` |
| `max_client_queue` | `Int` | – | `10000` | `> 0` |
| `max_commands_per_second` | `Int` | – | `100` | `> 0` |
| `max_errors_before_disconnect` | `Int` | – | `50` | `> 0` |
| `error_window_sec` | `Int` | – | `60` | `> 0` |

Also consumes `gateways.alf` for identity/role.

### 6.2 `balf_gateway` — `pm-balf-gwy`

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `enabled` | `Bool` | – | `true` | |
| `name` | `Str` | – | `"balf-gwy01"` | |
| `bind_address` | `Str` | – | `"0.0.0.0"` | |
| `port` | `Port` | – | `5560` | `1..65535` |
| `heartbeat_interval_sec` | `Secs` | – | `1.0` | `> 0` |
| `heartbeat_timeout_sec` | `Secs` | – | `5.0` | `> 0` |
| `idle_timeout_sec` | `Secs` | – | `30.0` | `> 0` |
| `auth_timeout_sec` | `Secs` | – | `10.0` | `> 0` |
| `max_connections` | `Int` | – | `64` | `> 0` |
| `max_client_queue` | `Int` | – | `10000` | `> 0` |
| `max_messages_per_second` | `Int` | – | `100` | `> 0` |
| `max_errors_before_disconnect` | `Int` | – | `10` | `> 0` |
| `error_window_sec` | `Secs` | – | `60.0` | `> 0` |
| `duplicate_session_policy` | `Enum<DuplicateSessionPolicy>` | – | `REJECT_NEW` | |

Also consumes `gateways.alf` for identity, role, and `disconnect_behaviour`.

### 6.3 `market_data_gateway` — `pm-md-gwy` (CALF)

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `enabled` | `Bool` | – | `true` | |
| `name` | `Str` | – | `"md-gwy01"` | reported as `WELCOME\|GW=` |
| `bind_address` | `Str` | – | `"0.0.0.0"` | |
| `port` | `Port` | – | `5570` | `> 0` |
| `heartbeat_interval_sec` | `Int` | – | `1` | `> 0`; advertised as `WELCOME\|HBINT=` |
| `idle_timeout_sec` | `Int` | – | `5` | `> 0` |
| `replay_window_sec` | `Int` | – | `30` | `> 0`; advertised as `WELCOME\|REPLAY=` |
| `max_symbols_per_client` | `Int` | – | `200` | `> 0` |
| `max_client_queue` | `Int` | – | `10000` | `> 0` |
| `depth_levels` | `Int` | – | `10` | `> 0` |

### 6.4 `post_trade_gateway` — `pm-ralf-gwy` (RALF)

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `name` | `Str` | – | `"ralf-gwy01"` | |
| `bind_address` | `Str` | – | `"0.0.0.0"` | |
| `port` | `Port` | – | `5580` | `> 0` |
| `replay_retention_sec` | `Int` | – | `86400` | `> 0` |
| `heartbeat_interval_sec` | `Int` | – | `1` | `> 0` |
| `idle_timeout_sec` | `Int` | – | `5` | `> 0` |
| `max_client_queue` | `Int` | – | `10000` | `> 0` |
| `allowed_roles` | `List<Str>` | – | `[CLEARING, DROP_COPY, AUDIT]` | values upper-cased |

This block has no `enabled` key.

### 6.5 `api_gateways` — `pm-api-gwy` (REST / WebSocket)

`api_gateways` is a `Map<Str, ApiGwyProcSpec>` of **named instances** (the map key
is the instance name). The singular key `api_gateway` is **NOT supported** and MUST
be rejected.

`ApiGwyProcSpec`:

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `enabled` | `Bool` | – | `true` | |
| `host` | `Str` | – | `"127.0.0.1"` | |
| `port` | `Port` | – | `8080` | `> 0` |
| `log_level` | `Str` | – | `"info"` | |
| `swagger_enabled` | `Bool` | – | `true` | |
| `stats_db` | `Path` | – | resolved `stats.db` | `~` expanded |
| `credentials` | `List<ApiCredentialSpec>` | – | `[]` | api keys unique within instance |
| `rate_limit` | `RateLimitSpec` | – | see below | |
| `timeouts` | `TimeoutSpec` | – | see below | |

`ApiCredentialSpec`:

| Field | Type | Req | Default | Constraints |
|-------|------|:---:|---------|-------------|
| `api_key` | `Str` | ✔ | — | non-empty; unique within the instance |
| `gateway_id` | `GatewayId` | – | `null` | a `gateway_id` MUST NOT map to two different instances |
| `description` | `Str` | – | `""` | |

`RateLimitSpec`: `writes_per_second` `Int > 0 = 10`, `burst` `Int > 0 = 20`.
`TimeoutSpec`: `engine_auth_sec` `Secs > 0 = 3.0`, `engine_reply_sec` `Secs > 0 = 3.0`,
`wait_ack_sec` `Secs > 0 = 3.0`.

---

## 7. Cross-field and semantic constraints

A conforming document MUST satisfy all of the following. Violations MUST be
rejected at load.

| # | Rule |
|---|------|
| CV1 | `symbols` is present and a mapping; `gateways.alf` is present and a list with ≥ 1 entry. |
| CV2 | `gateways.alf[].id` values are unique (after upper-casing). |
| CV3 | If **any** gateway has `role: MARKET_MAKER`, then **every** symbol MUST define at least one `market_maker_quotes` entry. |
| CV4 | Every `market_maker_quotes[].gateway_id` references a configured gateway whose role is `MARKET_MAKER`. |
| CV5 | For each MM quote seed, `bid_price < ask_price` and `bid_qty, ask_qty > 0`. |
| CV6 | A symbol's `level` (explicit, else `risk_controls.default_level`) MUST be a key of `risk_controls.levels`, when any level is in effect. |
| CV7 | `risk_controls.default_level`, if set, MUST be a key of `risk_controls.levels`. |
| CV8 | `risk_controls.levels.<L>.circuit_breaker` MUST NOT appear. |
| CV9 | Each `market_maker_combos[]` has 2–10 legs; leg symbols are unique within the combo; every leg `symbol` exists in `symbols`. |
| CV10 | `indices` has ≤ 5 entries; each `id` is alphanumeric and unique; each constituent exists in `symbols` and defines `outstanding_shares`; constituents are non-empty and duplicate-free. |
| CV11 | Every key of `mm_obligation_defaults.symbols` references a symbol that exists in `symbols`. |
| CV12 | `collar.*_band_pct` ∈ (0,1); `circuit_breaker.levels.<L>.price_shift_pct` ∈ (0,1); `halt_duration_ns` is `> 0` or `null`; `resumption_mode` ∈ {AUCTION, CONTINUOUS}. |
| CV13 | `symbols.<S>.tick_decimals` ∈ 0..8; `outstanding_shares`, when present, `> 0`. |
| CV14 | (`pm-alf-gwy`, `pm-balf-gwy`) No `gateways.alf` id may be a prefix of another id. |
| CV15 | (`pm-api-gwy`) The singular `api_gateway` key is not supported; a `gateway_id` credential MUST NOT be shared across two `api_gateways` instances. |

---

## 8. Processing model

1. **Parse.** Load the document as YAML; a non-mapping root is rejected (§1.2).
2. **Section ownership.** `pm-engine` reads the engine sections (§5) plus the
   `SymbolSpec`/nested structures; each auxiliary process reads only its own block
   (§6). No single process reads the whole file.
3. **Normalisation.** Symbols, gateway ids, index ids, and enum values are
   upper-cased (§1.6).
4. **Validation.** Field-level constraints (§4–§6) are checked, then the
   cross-field rules (§7). The first violation MAY abort loading.
5. **Unknown keys** are ignored (§1.5).
6. **Whole-file validation.** `pm-cverifier` validates every section — including
   blocks no runtime process consumes on its own — across four layers (YAML,
   schema, semantic, completeness). It is the reference conformance checker.

---

## 9. Minimal conformant document

The smallest document that loads and supports trading (informative):

```yaml
gateways:
  alf:
    - id: TRADER01
symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 149.90
    last_sell_price: 150.10
```

If a `MARKET_MAKER` gateway is added, CV3 then requires a `market_maker_quotes`
block on every symbol.

---

## See also

- [Configuration](01-configuration.md) — informative reference, generator, recipes
- [Config Verifier (`pm-cverifier`)](23-config-verifier.md) — the reference validator
- [Risk Controls](12-risk-controls.md) — collar and circuit-breaker behaviour
- [Market Index (`pm-index`)](22-index.md) — index calculation using `indices`
- [External Protocols Overview](19-protocol-overview.md) — the gateways that read the auxiliary blocks
