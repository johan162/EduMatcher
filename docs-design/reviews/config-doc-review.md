# Config doc review: `990-app-config-spec.md` vs. the loaders — 2026-09-22

Grammar/field-law audit of `docs/user-guide/990-app-config-spec.md` against
the actual runtime config loaders it claims to describe (`engine/config_loader.py`
plus the seven gateway/component `config.py` modules). The spec is normative
("where it and any tutorial disagree, this document governs"), so every
field name, type, default, and constraint was checked against the code that
actually parses `engine_config.yaml`, not against what seemed reasonable.

Scope: `engine/config_loader.py` (§3–§5, §7 CV1–CV13/CV18/CV19), the seven
`§6` auxiliary gateway blocks (`alf_gwy`, `balf_gwy`, `md_gateway`,
`ralf_gateway`, `api_gateway`, `dc_gateway`, `log_srv`), `index/config_loader.py`,
`mm_bot/config.py` (to confirm it's correctly out of scope), and
`scheduler/main.py`. Method: three parallel research passes (engine section;
gateway sections; scope/header check) followed by direct re-verification of
every surprising claim against the source before writing anything up.

Everything below marked **[doc, fixed]** has already been corrected in
`990-app-config-spec.md`. Everything marked **[source bug]** is a defect in
the code itself, left as found per this review's scope (docs review, not a
code change task) — flagged here for a follow-up fix.

## Doc fixes applied

1. **Header loader list was missing `dc_gateway/config.py`** (line 9-13).
   `dc_gateway` reads its own `dc_gateway:` section out of `engine_config.yaml`
   exactly like every other listed gateway loader, and §6.6 already documents
   it in full — there was no principled reason for the header to omit it.
   Added.

2. **`engine_tuning.*` was entirely undocumented.** `config_loader.py:1328-1412`
   reads an optional `engine_tuning:` mapping with five sub-fields:
   `snapshot_interval_sec` (float, `>0`, default `0.5` — and when present,
   **overrides** the top-level `snapshot_interval_sec` key, a precedence rule
   that also wasn't documented), `quote_history_maxlen` (int, `>0`, default
   `30`), `drop_copy_buffer_size` (int, `>0`, default `10000`),
   `recent_trades_maxlen` (int, `>0`, default `20`),
   `depth_snapshot_tolerance_ticks` (int, `>0`, default `100`). Zero mentions
   anywhere in the spec (§3 schema tree or §5). Added as new §5.3a plus a
   schema-tree entry.

3. **`auction_indicative_interval_sec` was entirely undocumented.**
   Top-level float, default `1.0`, `>0` (`config_loader.py:1347-1357`),
   consumed by `engine/main.py` to throttle indicative-uncross republishing
   during auction call phases. Added alongside `engine_tuning` in §5.3a and
   the schema tree.

4. **§5.10 `country`: "pm-engine never reads this key" was false.**
   `engine/main.py:2001-2021` (`_country_wire_code`) reads `engine_cfg.country`
   to derive the ISO alpha-2 code reported in outbound reference messages.
   The narrower true claim — pm-engine doesn't use `country` for schedule or
   holiday gating, only `pm-scheduler` does — has replaced the absolute
   "never reads" statement. Also clarified that the "logs a warning and
   substitutes Sweden" behavior described directly under the field table is
   `pm-scheduler`'s behavior specifically: the engine loader's own fallback
   (`config_loader.py:1444-1447`) is a bare non-empty-string check with no
   `python-holidays` recognition and no logging. CV16's `(pm-scheduler)`
   scoping was already correct; the surrounding prose wasn't.

5. **§6.5 `api_gateways`: two loader-read, validated fields were missing
   from the `ApiGwyProcSpec` table.** `market_data_cache_sec` (int, `>=0`,
   default `60`, TTL for cached market-data reads) and `session_timezone`
   (str, default `null`, validated as a real IANA timezone via
   `resolve_timezone`, used to resolve which trading day a date-only query
   refers to) are both read and enforced in `api_gateway/config.py:222-235`.
   Added to the table. (`engine_pull_addr`/`engine_pub_addr`/
   `index_pull_addr`/`index_pub_addr` are also technically YAML-overridable
   on this block, but — consistent with the same internal ZeroMQ addresses
   already correctly left undocumented on `alf_gateway`/`balf_gateway` — these
   are wiring addresses for the multi-process bus, not user-facing tuning
   knobs, and were deliberately left out of the doc as out of scope for this
   spec's audience.)

6. **§6.6 `dc_gateway.port` constraint was wrong: doc said `1..65535`, code
   only enforces `> 0`.** `dc_gateway/config.py:58-59` has no upper bound
   check. Corrected to `> 0`, matching the actual loader and matching how
   every other `Port` field in this spec is documented except
   `balf_gateway.port` (the one loader that really does enforce `1-65535`,
   see finding 8 below). No code changed — see the note in "Flagged source
   issues" about whether the upper bound *should* be enforced everywhere.

7. **§6.1/§6.2 `idle_timeout_sec`: doc default is only correct when the
   section is present.** See "Flagged source issues" #1/#2 below — this is
   primarily a source bug, but since it produces a real (and large) behavioral
   discrepancy today, a **KNOWN BUG** note was added inline on both affected
   rows so a reader troubleshooting an idle-timeout mismatch isn't misled by
   a table that states only the correct-when-present value.

## Everything checked and confirmed correct (no doc change needed)

- `CollarSpec` defaults (`static_band_pct=0.20`, `dynamic_band_pct=0.02`) and
  merge order (symbol collar keys win over the resolved risk-level collar).
- `CircuitBreakerSpec` built-in ladder (`L1=0.07/5min`, `L2=0.13/15min`,
  `L3=0.20/rest-of-day`) and the ACE reopening built-in defaults
  (`initial_band_pct=0.10`, `expansions=[{0.10,120e9},{0.20,300e9}]`,
  `random_end_max_ns=30e9`).
- `risk_controls.levels.<L>.order_limits`/`.circuit_breaker` rejection (§4.3,
  §5.5, CV8) — genuinely enforced in `config_loader.py:772-782`, not just
  documentation-only intent. (One harmless edge case: an explicit YAML
  `null` for either key is indistinguishable from key-absent and slips past
  the rejection — semantically a no-op either way, not worth flagging.)
- CV1–CV13, CV18, CV19 — all individually re-traced to the enforcing code and
  confirmed to match the table's wording, including qualifiers (CV3's
  `require_mm_seed_quotes` exception; CV13's "only under
  `circuit_breaker_defaults`" restriction; CV18's per-leg, not per-combo,
  tick-grid resolution).
- §6.3 (CALF/`market_data_gateway`), §6.4 (RALF/`post_trade_gateway`), and
  §6.7 (`log_server`, all 30 fields including the pairwise port-distinctness
  rule, `max_lease_sec >= lease_sec`, the `retention_days` `0`→`null`
  normalisation, hourly pruning cadence, and 2×heartbeat disconnect
  threshold) match the implementation exactly. RALF's and `dc_gateway`'s "no
  `enabled` key" claims are both true in code.
- CV14 (gateway-id prefix collision) and CV15 (`api_gateway` singular-key
  rejection, cross-instance `gateway_id` uniqueness) are both genuinely
  enforced — CV14 in `alf_gwy/config.py`/`balf_gwy/config.py` and mirrored in
  `pm-cverifier` (`S084`); CV15 in `api_gateway/config.py` and mirrored in
  `pm-cverifier` (`S080`, which delegates to the same function, so no drift
  risk there). CV14's enforcement point is structurally at `pm-config-deploy`
  compile time (via the same loaders), not at gateway-process startup
  directly — a bad config never reaches a compiled artifact the gateways
  could load, so the net effect matches the spec's `(pm-alf-gwy, pm-balf-gwy)`
  framing even though the mechanism is one step upstream of where a reader
  might expect it.
- `index/config_loader.py` doesn't read a separate file — it enriches an
  already-parsed `EngineConfig`'s `indices[]` with `outstanding_shares`/
  `reference_prices` pulled from `symbols`. §4.6/§5.8's `IndexSpec` content
  and CV10 (enforced in `engine/config_loader.py:1064-1133`, not in
  `index/config_loader.py`) both match code exactly.
- `mm_bot/config.py` reads an entirely separate file (`pm-mm-bot --config
  PATH`), unrelated to `engine_config.yaml`'s schema — the spec's silence on
  it is correct, not a gap. (`docs/user-guide/100-mm-bot.md` documents that
  file's format separately, as it should.)
- `scheduler/main.py` really does read only `engine_cfg.schedule` and
  `engine_cfg.country` — no other engine-section field — confirming the
  header's `(schedule and country only)` qualifier.

## Flagged source issues (not doc bugs — for a follow-up code fix)

These are defects in the loaders themselves, found while checking the doc
against them. Per this review's scope (bring the doc in line with the code,
not change the code), they are flagged here rather than fixed, with inline
**KNOWN BUG** notes added at the two doc locations they affect so a reader
isn't misled in the meantime.

1. **`alf_gwy/config.py:32` — wrong dataclass default for `idle_timeout_sec`.**
   `AlfGatewayConfig.idle_timeout_sec` defaults to `3600` at the dataclass
   level, but `_load_alf_gateway_config_from_raw` (config.py:102) explicitly
   resolves `30` as the default whenever the `alf_gateway:` section is
   *present*. When the section is **absent** from the YAML entirely (a
   common, legal, and arguably more common case than an explicit section
   with every key at its default), `_load_alf_gateway_config_from_raw`
   short-circuits at config.py:87-88 and returns
   `AlfGatewayConfig(gateway_roles=gw_roles)` — which uses the dataclass's
   `3600`, not `30`. This is a genuine 120× discrepancy (1 minute vs. 1 hour)
   between what the spec (correctly) documents as the default and what a
   deployed `pm-alf-gwy` actually runs with when the section is omitted.
   `config_deploy.py:174` compiles through this same code path, so the drift
   reaches the compiled artifact the gateway process actually loads, not
   just an in-memory object. **Fix:** change the dataclass field default to
   `30` to match the loader's own explicit default and the spec.

2. **`balf_gwy/config.py:36` — same bug, same pattern.**
   `BalfGatewayConfig.idle_timeout_sec` dataclass default is `300.0`; the
   loader's explicit default when the section is present is `30.0`
   (config.py:136). Section-absent path (config.py:117-118) returns the
   `300.0` dataclass default. Same 10× discrepancy, same
   `config_deploy.py:175` propagation into the compiled artifact. **Fix:**
   change the dataclass field default to `30.0`.

   Given both `alf_gwy` and `balf_gwy` have the identical bug shape (loader
   default correct, dataclass default stale/wrong, section-omitted path uses
   the wrong one), it's worth checking whether any other `config.py` in this
   family has the same shape — `md_gateway/config.py` was checked directly
   and does **not** have this bug (its dataclass and loader defaults agree
   everywhere), so this looks like an alf/balf-specific slip rather than a
   systemic pattern, but wasn't exhaustively re-checked across every field of
   every module.

3. **`dc_gateway.port` (and most other `Port` fields) accept any positive
   int, not just `1..65535`.** `dc_gateway/config.py:58-59` only checks
   `port <= 0`; nothing stops a config from setting `port: 99999999`, which
   `pm-dc-gwy` would then fail to bind with an OS-level error far from the
   config-validation step that should have caught it. The one loader that
   *does* enforce the real TCP range is `balf_gwy/config.py:126-127`
   (`if port <= 0 or port > 65535`). This review fixed the **doc** to match
   the (looser) actual behavior everywhere except `balf_gateway`, since
   fixing the doc was in scope and fixing seven loaders' validation was not
   — but the inconsistency itself (one gateway rejects out-of-range ports,
   the rest silently accept and defer the failure to the OS) is worth a
   deliberate decision: either tighten every `Port` field's validation to
   match `balf_gateway`'s, or drop `balf_gateway`'s extra check for
   consistency. Recommend the former (tightening), since an early, clear
   config-time rejection is strictly better than an OS bind error at process
   startup.

4. **`config_loader.py:341`'s dataclass-level `sessions_enabled: bool = False`
   default is dead code, not a functional bug.** Noted during the audit:
   the loader always passes an explicit resolved value (`raw.get(
   "sessions_enabled", True)`, config_loader.py:1291) into the
   `EngineConfig` constructor, so the dataclass field's own default of
   `False` never actually surfaces via `load_engine_config()`. It's only
   reachable by constructing `EngineConfig(...)` directly, which no
   production code path does. Not flagged as a fix — just noted here in case
   it's ever a source of confusion when reading the dataclass in isolation
   (a maintainer skimming the class definition would see `False` and
   reasonably expect that to be the loader's real default, which it isn't).

5. **A stale internal comment in `log_srv/config.py`** cites "§6.5, §7.6" for
   the `retention_days` `0`→`null` normalisation note — those section numbers
   don't correspond to the current doc structure (the relevant material is
   now §6.7 and CV17 under §7). Harmless (it's a code comment, not
   user-facing), not worth a doc change, noted here only so it doesn't get
   miscited if someone goes looking.

## Not re-verified independently

Both parallel research agents' work was spot-checked directly against source
for every claim that would change a default, a validated range, or a
"reads/doesn't read" assertion. The full §6.3/§6.4/§6.7 field-by-field sweep
(CALF, RALF, log_server — ~50 fields total) was taken from the research
pass's direct code citations without independently re-reading every line;
if a doubt surfaces about any specific field in those sections later, re-read
the cited `config.py:LINE` directly before trusting it further.
