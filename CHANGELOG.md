## [v0.19.1] - 2026-08-07

Release Type: minor

### 📋 Summary
This release improves documentation quality and PDF usability across the User Guide and Exchange Intro outputs. It also expands training and finance learning material with new reference content and packaged presentation assets.

### ✨ Additions
- Added new finance introduction material for combo and implied orders
- Added packaged training presentation PDFs for easier offline distribution

### 🚀 Improvements
- Improved internal markdown link rewriting in Pandoc PDF builds for User Guide chapters
- Improved exchange-intro PDF link resolution to match user-guide behavior
- Improved dark-theme PDF link color contrast for better readability
- Improved training documentation coverage for configuration and API sections

### 🐛 Bug Fixes
- Fixed PDF chapter links that were emitted as literal markdown file links instead of internal document anchors

### 📚 Documentation
- Updated terminal GUI and TapeDeck related documentation and training content
- Updated exchange-intro and user-guide narrative content for clearer onboarding

## [v0.19.0] - 2026-08-07

### 📋 Summary
This release focus on extending the REST API with several areas and also improve the API documentation
and add a new normative reference appendix of all endpoints. 
Internally a rework of the mermaid filter, used in building the documentation via Pandoc, have been forked
and updated to cache generated PDF images which results in a dramatically reduced build time for the documentation.

### ⚠️ Breaking Changes
- Changed cumulative market-data subscription behavior to track symbol/channel pairs directly (instead of widening to a cross-product), which may reduce previously over-broad streams in existing clients

### ✨ Added
- Added API-gateway order visibility improvements: new admin endpoints for active orders and per-order lifecycle, plus richer monitor snapshots for operators
- Added stronger WebSocket state and recovery support: post-auth snapshots, sequence markers, and clearer event metadata for reconnecting clients
- Added market-data subscription enhancements with per-symbol/per-channel rules and explicit acknowledgement feedback for rejected or always-on channels
- Added config/runtime support for API-gateway order retention (`order_retention_sec`) and optional audit index integration for deep order-history lookups
- Added command correlation and acknowledgements for session transitions and kill-switch flows, plus richer order lifecycle events (including combo/OCO/quote relationships)
- Added APIs for getting reference data as a single source of truth

### 🚀 Improvements
- Improved the REST API documentation with a new separate normative API reference

### 🐛 Fixed
- Fixed API-gateway order-cache growth by expiring terminal orders after a configurable retention window while keeping active orders and positions intact
- Fixed silent session-transition failures by returning explicit acceptance/rejection outcomes to callers
- Fixed kill-switch concurrency limits by introducing command-level correlation instead of per-gateway serialization
- Fixed previously hard-to-detect WebSocket event drops by surfacing counters in health checks and logs

### 📚 Documentation 
- Updated devel documentatoin with information about the new mermaid-filter and configuration

### 🛠 Internal
- Added our own version of mermaid-filter that caches the generated PDF images. This cuts down the documentation build process by >5x !

## [v0.18.0] - 2026-08-04

Release Type: major

### 📋 Summary
This is again a substantial release which has improvement in almost all areas and several new features.

This release introduces TapeDeck, the new read-only `pm-terminal` trader information terminal, and follows it with hardening in CALF recovery, statistics correctness and developer setup automation.

The engine configuration now has exactly one location, and it is compiled. Every `pm-*` process reads `<EDUMATCHER_DATA_DIR>/ref_data/engine_config.json`, an artifact with every default already resolved and every value already validated. None of them accepts a path to it: the `--config`/`-c` flags and the `EDUMATCHER_CONFIG` variable are gone. 

 A new `pm-config-deploy` validates, compiles and installs an authored configuration, separating the file you edit and version from the artifact the exchange runs.

### ⚠️ Breaking Changes

- Removed `--config`/`-c` from `pm-engine`, `pm-scheduler`, `pm-api-gwy`, `pm-index`, `pm-md-gwy`, `pm-ralf-gwy`, `pm-balf-gwy`, `pm-alf-gwy`, `pm-dc-gwy`, `pm-log-srv` and `pm-ai-swarm`. `pm-cverifier`, `pm-config-gen` and `pm-index-cli` keep their explicit paths: they operate on arbitrary files by design and cannot desynchronise a running exchange
- Removed the `EDUMATCHER_CONFIG` environment variable. `EDUMATCHER_DATA_DIR` is now the only location knob, and it relocates the configuration together with `stats.db`, `log.db` and `audit.log` — so a wrong value fails loudly instead of degrading quietly
- Removed `pm-setup --config-dest`. The bundled sample is always compiled into `<DATA_DIR>/ref_data/`, so a fresh install can start the exchange immediately
- Changed `pm-scheduler` to exit with a fatal error when no configuration is deployed, rather than falling back to its built-in timetable. Against a fixed path a missing file means nothing was deployed, and running a schedule the engine has never seen is worse than not starting
- `pm-config-deploy` now **compiles** rather than copies. It validates the authored YAML with all four `pm-cverifier` layers, resolves every default once, and writes `<DATA_DIR>/ref_data/engine_config.json`. Every `pm-*` process reads that artifact; the YAML is installed beside it for provenance only
- Deploying is stricter than starting used to be. A configuration with a `MARKET_MAKER` gateway and no `market_maker_quotes` (`M001`), or an API credential naming a `gateway_id` absent from `gateways.alf` (`M022`), now refuses to deploy where it previously ran. Warnings do not block — a command that refused on advice would push people back towards editing the deployed copy by hand
- `pm-setup` compiles the bundled sample rather than copying it, so a fresh install starts on a real configuration instead of built-in defaults
- The Config GUI's download is the *authored* file; run `pm-config-deploy` on it before starting the exchange
- Existing stats databases can not be used

### ✨ Additions

- Compiled configuration
    - The seven subsystem loaders no longer parse YAML at runtime; each returns its section of the artifact. Defaults are decided once at compile time rather than in eight places that nothing kept in step
    - Absence and corruption are now distinguished. No artifact yields dataclass defaults, exactly as a missing YAML did, so read-only tools like `pm-calf-spy` and `pm-viewer` still run on a machine that has never had a configuration installed. An artifact that cannot be parsed, or whose schema version is unknown, raises instead
    - Added `edumatcher.config_artifact`: the artifact schema, a generic dataclass↔JSON codec, and the single reader every subsystem now uses. Around twenty config dataclasses across eight sections are (de)serialised by one codec rather than by hand-written per-class methods that would be one more thing to drift
    - Added a `meta` block recording schema version, compiler version, compile time, source path and two digests. `source_sha256` answers "has the authored file changed since this was built?" — checked at startup and warned about per process. `content_sha256` answers "has this file changed since it was built?" — recomputed on every load, and a hand-edited artifact is refused. It detects modification rather than malice: the digest travels inside the file it protects, so anyone who edits the payload can recompute it
    - Added a startup line to every process that reads the configuration, naming the artifact, when it was compiled and from which source
    - Added `pm-config-deploy`, which validates an authored `engine_config.yaml` with the same loader every process runs at startup and installs it as the deployed copy — so a successful deploy cannot be followed by a process failing to parse the file. The write is staged and renamed, so a process starting mid-deploy sees either the old configuration or the new one, never half of either. `--show` prints the deployed path
    - Added a startup `using engine config <path>` line to the eight processes that read it
- Reopening auctions (ACE)
    - Removed the per-level `resumption_mode` config field. It was settable, validated by the loader, checked twice by `pm-cverifier` (`S034`, `S069`), generated by `pm-config-gen` via three `--cb-resumption-l*` flags and documented in the config spec — and branched on nowhere. `AUCTION` and `CONTINUOUS` behaved identically. It could not have been implemented as specified either: LIMIT orders rest freely during a halt, so `CONTINUOUS` would restart matching on a crossed book, which is exactly what the unconditional uncross exists to prevent
    - Replaced the engine's `resumption_mode`/`mode` payload fields with `halt_source` (`CB` or `ADMIN`), which says what caused the halt. Whether a halt ends by itself is already expressed by the presence of `resume_at_ns`
    - Renamed CALF's `CB|MODE=` to `CB|SRC=` to match, and ALF's `RESUME|MODE=` to `RESUME|SRC=` — the ALF field read `resumption_mode` from a payload that only ever carried `mode`, so it had always been empty
    - Removed `pm-cverifier` codes `S034` and `S069`
    - Added **Automated Corridor Expansion** to circuit-breaker reopenings, modelled on Deutsche Börse's ACE and Nasdaq Rule 4120(c)(7). A halt now reopens only if the indicative uncross price falls inside a price corridor centred on the breaker's reference price. If it does not, the corridor widens one rung and another call phase begins instead of printing an outlying price. Configured under `circuit_breaker.reopening`, exchange-wide via `circuit_breaker_defaults` with per-symbol overrides that merge field-by-field
    - Added a **random end** to every reopening call phase, initial and extended. `halt_duration_ns` and each rung's `min_duration_ns` are now minimums, with a delay drawn uniformly from `[0, random_end_max_ns]` on top. A reopen instant that everyone can predict is one the last order in can target with full sight of the book and no time for anyone to respond. Set `random_seed` under `circuit_breaker_defaults` for reproducible demos; leave it unset for OS entropy
    - Added the **closing auction as ACE's backstop**, following Nasdaq's Hybrid Closing Cross. Because the ladder's last rung repeats indefinitely the corridor never stops widening, so ACE has no terminating condition of its own — the end of the trading day supplies one. A symbol still halted at `CLOSED` prints at the corridor boundary for a buy/sell imbalance, or at the equilibrium if that now sits inside. This is the only place the engine imposes a price rather than discovering one, and it can deliberately leave the book crossed: interest beyond the boundary survives to the next session rather than executing at a price the corridor exists to reject
    - Added `circuit_breaker.extend.{SYMBOL}`, published on every corridor adjustment with the indicative price and quantity, the imbalance side, the widened corridor, the expansion index and the new `resume_at_ns`. `circuit_breaker.halt.{SYMBOL}` gained `corridor_low`, `corridor_high` and `expansion`; a backstop resume carries `reason: "CLOSING_BACKSTOP"`, `clamped` and `print_price`
    - Added `pm-config-gen` flags `--no-ace`, `--ace-initial-band`, `--ace-expansions`, `--ace-random-end-ns` and `--ace-random-seed`, plus `--symbol-opts` keys `ace_enabled`, `ace_initial_band` and `ace_random_end_ns`
    - Made the ACE expansion ladder exchange-wide and *enforced* it: the loader rejects `circuit_breaker.reopening.expansions` on a symbol and `pm-cverifier` reports `S112`. It had been accepted by the loader but modelled by neither the Config GUI nor `pm-config-gen`, so a hand-authored per-symbol ladder was silently discarded the first time the file passed through the GUI. A capability one tool honours and another drops is worse than either consistent answer. A symbol may still override `initial_band_pct`, `enabled` and `random_end_max_ns` — the corridor's starting width describes the instrument, the escalation schedule describes the venue. See the README for what lifting the restriction would cost
    - Added `pm-cverifier` codes `S104`–`S111` for the `reopening` block. `S110` rejects a per-symbol `random_seed` as an error rather than a warning: the generator is engine-wide, so such a seed would be stored and then silently ignored, leaving the symbol looking configured while behaving as though it were not
- CALF carries display precision
    - Added `REF=` to `WELCOME` and the `SYMBOLS` reply: per-symbol `SYM:DEC` tuples carrying each instrument's `tick_decimals`. CALF clients previously had no way to learn an instrument's display precision at all — the only source was `GET /api/symbols`, which requires a *trading* credential that a market data consumer has no business holding — so every client assumed the default of `2` and was quietly wrong about any symbol configured otherwise, on every price it rendered
    - Kept it off the market data channels deliberately. `tick_decimals` never changes for a symbol, so repeating it on `TOP` or `TRADE` would put a constant on the hottest path in a protocol whose `MD` messages are explicitly deltas. It is reference data and rides the handshake
    - Made its *presence* the capability signal, as `CH_SUPPORTED` already does, so `PROTO` stays `CALF1` and no client breaks. A client seeing no `REF` falls back to `2` knowingly rather than by accident. `REF` covers exactly the symbols in `SYMBOLS=` and is omitted alongside it, so there is no partially-populated state to reason about
    - Chose the `SYM:DEC` tuple over parallel positional lists so it can grow to `SYM:DEC:MULT:CCY` when contract multiplier and currency are defined, with no further protocol change. Clients ignore trailing components they do not recognise
- CALF carries ACE
    - Extended CALF's `CB` channel with the reopening corridor: `CORRLO`, `CORRHI` and `EXP` on a halt, and a further `CB` event with `STATUS=HALTED` and updated values on every corridor expansion. `pm-md-gwy` now subscribes to `circuit_breaker.extend.` — without it ACE was invisible to every external client, which is worse than not having the feature: a terminal would show a `RESUMEAT` that had already passed and report the symbol as overdue to reopen, indefinitely. No `STATE` event accompanies an extension, since the symbol was halted before and after
    - Added `INDICPX`, `INDICQTY` and `IMB` to expansion events — the indicative uncross price, the quantity that would have executed, and which side the imbalance ran. Deliberately event-only and absent from the `SNAP` baseline, because they are computed once at the end of a call phase and replaying them later would assert a stale price for a book that has kept moving. `CORRLO`/`CORRHI`/`EXP` *are* in `SNAP`: they describe the halt still in force
    - Added `REASON=CLOSING_BACKSTOP`, `CLAMPED` and `PRINTPX` to a resume forced by the end of the trading day, so a client can tell a price the exchange imposed at the corridor boundary from one the book discovered
- Circuit Breakers
    - Added `reason` to `auction.result.{SYMBOL}`, surfaced as CALF `AUCTION|REASON=`: `SCHEDULED` (leaving a non-matching session phase), `REOPEN` (a halted symbol reopening) or `RECOVERY` (restored GTC orders at startup). The three were previously indistinguishable, so no client could tell a circuit-breaker reopening from the closing auction
    - Added per-symbol fan-out of exchange session transitions on CALF `STATE`. A subscription matches `SYM=*` or an exact symbol, and transitions were published only as `SYM=*`, so a client watching one instrument saw its halts and resumes but never learned the exchange had opened or closed. Halted symbols are deliberately skipped — a halt outlives the phase it began in
    - The terminal now labels the auction banner by reason rather than always saying "Auction uncrossed", and shows the halt source and reopening time as the independent facts they are
- TapeDeck trader information terminal
    - Added TapeDeck, the new read-only `pm-terminal` trader information terminal, with Overview, Symbol Detail, Trade Tape, Movers, Index and Session/Halt views behind a shared Fastify bridge that fans one CALF uplink and one history proxy out to multiple browser tabs
    - Added the remaining trader-facing screens around the original market overview: an Index board, a cross-symbol time-and-sales tape, movers rankings, per-symbol depth and halt detail, previous-close-aware symbol detail, and wallboard-style paging and density controls
    - Added a reusable Python `edumatcher.calf_client` together with C and Python CALF recovery examples, so external consumers can follow the standalone `RESUME` flow, decode handshake reference data and build gap-aware subscribers against the same protocol TapeDeck uses

### 🐛 Fixes
- Fixed `country` never reaching `EngineConfig`. It is emitted by `pm-config-gen` and validated by `pm-cverifier`, but no loader field captured it, so the compiled artifact dropped it and `pm-scheduler` was the only process that had ever read it — through its own private YAML parse
- Fixed schedule times being stored raw. `str(schedule_raw.get("pre_open"))` turned an unquoted `9:30`, which PyYAML reads as the sexagesimal integer `570`, into the string `"570"`, while `pm-scheduler` normalised the same file to `"09:30"`. `normalize_hhmm` now lives with the loader, so the artifact only ever holds canonical `HH:MM`
- Fixed `pm-index` re-parsing the YAML for constituent reference data. `outstanding_shares` and `reference_prices` are gathered from the constituent symbols rather than being fields of their own, so the artifact always carried enough; `index_runtime_configs()` now takes an `EngineConfig`
- Fixed `pm-md-gwy` reading its settings and its symbol universe through separate calls, so the two could describe different exchanges — the original failure this work began from
- Fixed the ALF gateway's `RESUME|MODE=` field, which read `resumption_mode` from a payload that only ever carried `mode`, and had therefore always been empty
- Fixed the scheduled `CLOSING_AUCTION → CLOSED` uncross sweeping symbols that were still halted. `_run_uncross()` iterated every book unconditionally, so a halted symbol was uncrossed by the session transition at the true equilibrium — which with ACE in place would have bypassed the corridor and the extension ladder entirely. Halted symbols are now skipped by the sweep and resolved by the backstop instead
- Fixed `pm-config-gen --cb-levels` advertising a `RESUMPTION_MODE` fourth field in its help text, and `010-configuration.md` documenting `cb_resumption_l1`/`l2`/`l3` `--symbol-opts` keys. Both described the knob removed earlier in this release
- Fixed CALF reporting a resumed symbol as `SESSION=CONTINUOUS` regardless of what the exchange was actually doing. `CircuitBreakerState.should_resume` consults no session state, so a timed halt can outlive its phase: an L2 halt (15 minutes by default) triggered shortly before the close resumes into `CLOSING_AUCTION` or `CLOSED`, and CALF was telling every client the symbol was trading on a closed exchange. A resume now rejoins the current session
- Fixed a symbol's cached session state being pinned by its first halt. `state_snapshot_fields` falls back to the exchange state only for symbols absent from `symbol_state`, and nothing updated that map afterwards — so any symbol that had ever halted reported a stale session in every later `SNAP`, for the rest of the day
- Multiple calculations and conceptual fixes in stats module including better discovery of lost information


### 🚀 Improvements
- Improved `pm-stats` after review hardening: trading-day classification, API/history semantics, gap visibility, query results and derived calculations now follow the corrected post-review rules rather than quietly mixing incompatible assumptions
- Improved stats ingestion safety with explicit feed-gap detection, a single-writer lock and tick-size-aware schema/calculation updates, and now refuse older stats databases rather than interpreting them under the wrong schema semantics


### 📚 Documentation 
- Added a full TapeDeck user-guide chapter covering container, Compose, separate-server and local-development operation, plus a user-facing screen tour and configuration reference
- Expanded the CALF gateway, protocol and training chapters to cover standalone `RESUME` recovery, gap-aware subscribers, handshake reference data and the market-data semantics TapeDeck depends on
- Added and refreshed design and presentation material for stats follow-up work, reference-data configuration, ALF/CALF/RALF/API gateway intros, drop-copy and the message-generator proposal
- Rewrote the configuration, getting-started, processes, FAQ and training-installation chapters around the authored-versus-deployed split, and added a `pm-config-deploy` section to the process reference
- Removed the config-path resolution order from the ALF, BALF, DC1 and CALF gateway chapters — there is nothing left to resolve
- Noted in the CALF gateway chapter why the single location matters most there: `pm-md-gwy`'s symbol universe is what `WELCOME|SYMBOLS=` and the `SYMBOLS` reply are built from
- Documented that a halt *is* a reopening auction's call phase: LIMIT orders rest, MARKET/FOK/IOC are rejected, no matching runs, and the halt always ends in an uncross. This was already the behaviour; nothing in the docs said so plainly, and the removed `resumption_mode` implied a choice that did not exist
- Rewrote the resumption section of the risk-controls chapter, and updated §920, §240, §241, §270, §990, the configuration chapter and the MM-quotes concept page
- Tweak blue header color for better visibility in the dark-theme
- Several introduction presentations has been added under `docs/presentation` 
- Rewrote intro and run-playbook in the user-guide
- Added several presentations for gettting started with EduMatcher


### 🛠 Internal
- Added `tests/test_config_single_source.py`, parametrised over every runtime entry point, asserting each rejects a config path and runs with no arguments at all
- Added `tests/test_config_deploy.py` covering validation, atomic replacement, and leaving a previous deployment intact when the new file is bad
- Fixed `test_api_gateway_history.py` and `test_api_gateway_pagination.py` helpers to forward `from_date`/`to_date`; calling the handlers directly leaves FastAPI's `Query` sentinels bound to those parameters
- Added extensive TapeDeck bridge, browser and engine test coverage for reconnect replay, data age, sorting, auction indication, previous-close handling, session countdowns and CALF replay repair
- Added stats follow-up tests around trading-day handling and feed-gap detection, and aligned build/setup tooling around local Poetry virtualenvs, initial-venv bootstrap and Multipass development snapshots
- Added stronger `scripts/verify_setup.sh` environment checks for Node/npm, Chrome, XeLaTeX, `readline-devel`, Pandoc >= 3.10, `DejaVu Sans`, required TeX style packages, `make` and `gcc`, with Fedora-aware package handling and guidance for unsupported Linux distributions
- Added `vm/mkdevnode.sh` plus root Makefile support to create, provision, restart and snapshot a Multipass Ubuntu development node from the repository workflow instead of a manual host-side checklist
- Improved `tools/verify_matching.sh` to deploy its verification configuration rather than passing it as a flag
- Added `tests/test_config_generated_fields_reach_artifact.py`, asserting that every top-level key `pm-config-gen` can emit has a declared landing in the artifact and is reachable from it. This is the invariant the three dropped-field bugs above violated; both guards are verified to fail when broken
- Added a declared-type conformance check over every config dataclass, catching values whose runtime type contradicts their annotation — `arg-type` is disabled for `tests.*`, so a fixture can otherwise build a config the codec will silently reshape
- Removed the redundant inner quotes in `list["MMQuoteSeed"]`-style annotations: `get_type_hints` resolves the outer string but leaves the argument a plain `str`, which made the codec hand back raw dicts. It now raises on an unresolved annotation rather than degrading quietly


## [v0.17.0] - 2026-07-29

Release Type: major

### 📋 Summary
This release introduces centralized logging for the whole exchange. `pm-log-srv` collects LALF log records from every `pm-*` process into a single SQLite-backed store, now with a LALF-PS ZeroMQ interface for live streaming, filtering, and backfill. A new web-based Log GUI (dashboard, live log explorer, alerts, process and health views) gives operators a real-time view of the whole system, backed by a Fastify bridge that talks LALF-PS on one side and serves the browser on the other. A new `pm-log-cli` complements it for terminal-based querying, tailing, and diagnostics. Every `pm-*` process now automatically logs to `pm-log-srv` when one is running, with automatic fallback to a local log file if the server is unreachable or goes down, so no logging is ever lost.

### ✨ Additions
- Added **LALF-PS**, the ZeroMQ log-distribution interface of `pm-log-srv`: a `PUB` socket (`:5601`) carrying live rows, notification ticks, backfill chunks and control acks, plus a `PULL` socket (`:5602`) receiving subscriber control requests — mirroring `pm-index`'s existing socket topology
- Added two subscription modes: `STREAM` pushes full log rows as they are committed, `NOTIFY` publishes coalesced "n new rows up to seq X" ticks carrying no row bodies
- Added chunked "last n minutes" backfill (`log.backfill_request`), delivered one bounded chunk per main-loop iteration so an arbitrarily large window never stalls LALF collection
- Added lease-based subscriber liveness: a `PUB` socket cannot observe a dead peer, so every subscription carries a TTL that the subscriber must refresh with `log.renew`; a subscriber that goes silent is reaped, its buffers discarded and its backfill cancelled
- Added server-side row filtering (`min_level`, `processes`, `loggers`, `sessions`, `contains`, `exceptions_only`), applied identically to live and backfill rows so a viewer sees no gap at the seam
- Added `log.server_state` liveness broadcast and `log.status_request` diagnostics
- Added `log_server:` config keys `pubsub_enabled`, `pub_port`, `pull_port`, `lease_sec`, `max_lease_sec`, `max_subscribers`, `notify_interval_ms`, `backfill_chunk_rows`, `max_backfill_minutes`, `max_backfill_rows`, `max_pending_rows`, `pub_sndhwm`, and `pm-log-srv` flags `--pub-port`, `--pull-port`, `--lease-sec`, `--no-pubsub`
- Added `pm-config-gen` support for every new `log_server` field via thirteen `--log-server-*` flags, including the `--log-server-pubsub-enabled`/`--log-server-pubsub-disabled` pair; passing any one of them implies the `log_server` block
- Added `pm-cverifier` codes `S102` (pm-log-srv's `port`, `pub_port` and `pull_port` must resolve to three different ports) and `S103` (`max_lease_sec` must not sit below `lease_sec`)
- Added a "LALF-PS — log distribution" section to the Config GUI's Gateways → Log Server sub-tab, covering all twelve fields with inline help; the ZeroMQ fields collapse away when the interface is switched off
- Added Config GUI diagnostics `log-server-port-overlap` and `log-server-lease-bounds` (errors, mirroring `S102`/`S103`) and `log-server-notify-exceeds-lease` (warning: a NOTIFY subscriber can be reaped between ticks)

### 🚀 Improvements
- Improved `pm-log-srv`'s writer thread to report the `seq` assigned to each committed row, so subscribers are notified only after the transaction commits — the live stream and `log.db` can never disagree
- Improved per-subscription memory safety: a subscriber that is alive but too slow sheds its oldest buffered rows and is told how many via a `dropped` counter, rather than growing the server without bound
- Improved `pm-cverifier`'s `M018` port-collision check to cover pm-log-srv's two LALF-PS ZeroMQ ports alongside every other configured listener, skipping them when `pubsub_enabled: false`; findings now name the offending field rather than always saying `.port`
- Improved `pm-cverifier`'s `S101` loader safety net to stay quiet once a more specific `log_server` finding has already been reported, instead of restating it
- Improved the Config GUI's port-collision rule to cover the LALF-PS ZeroMQ ports, deferring to the dedicated error rule for pm-log-srv's own three-port case so a collision is reported once rather than twice

### 📚 Documentation
- Added a full LALF-PS message catalogue to the Message Reference, with field tables, error codes and the log row schema
- Added a LALF-PS chapter to the Centralized Log Server guide covering socket topology, both modes, filtering, backfill, the lease rationale, slow-vs-dead subscribers, tuning, troubleshooting, and a complete worked subscriber
- Updated the engine configuration specification and sample config with the new `log_server:` keys
- Added a "LALF-PS fields" section to the configuration guide and documented the new `pm-config-gen` flags and `pm-cverifier` codes

### 🛠 Internal
- Added `tests/test_log_srv_pubsub.py` covering filters, both modes, chunked backfill, lease renewal and expiry, subscriber limits and error paths
- Added `tests/test_log_server_pubsub_config.py` pinning the generator, the verifier and the runtime loader to one another, including a generate→load round-trip
- Added Config GUI tests for LALF-PS emission, import round-trip, zod cross-field refinements and the new diagnostics rules
- Updated the `pm-log-srv` test fixture to bind ephemeral ZeroMQ ports so concurrent test workers cannot collide

## [v0.16.2] - 2026-07-27

Release Type: minor

### 📋 Summary
This release adds country-aware schedule and holiday handling across configuration and tooling, while improving consistency in process logging and reducing churn from generated documentation artifacts. It also refreshes user-guide and Exchange Intro build workflows with dynamic cover generation and cleaner chapter organization. Finally the look & feel of the orderbook viewer and ticker is greatly improved.

### ✨ Additions
- Added top-level `country` field support in engine configuration, config generator, and config validator
- Added country specification support in Config GUI
- Added country-aware holiday handling in scheduler startup to avoid opening on bank holidays for the configured country
- Added support for dc-gateway configuration in config-gen and config GUI

### 🚀 Improvements
- Improved engine and scheduler logging conventions to align with other processes
- Improved look & feel of orderbook viewer pm-viewer
- Improved look & feel of ticker pm-ticker

### 📚 Documentation
- Added information om country specification to schedule chapter
- Improved user-guide chapter ordering and naming for clearer navigation
- Improved process description

### 🛠 Internal
- Updated docs build workflows to stop committing generated intermediate files
- Updated Makefile and docs build targets to support the revised template and cover generation process
- Added dynamic cover page generation for Exchange Intro split outputs with new `cover-parts` target
- Updated Exchange Intro docs pipeline with auto-generated cover assets and intermediate template handling
- Refactored CLI startup options handling in API-gateway

## [v0.16.1] - 2026-07-19

Release Type: major

### 📋 Summary
This release introduces the new Config GUI, the new `pm-audit-cli` audit-trail inspection tool, expanded API Gateway operator controls, and broader CALF market-data capabilities. For Index handling a new admin client was added `pm-index-admin-cli` that handles corporate actions. 
The CALF protocol gets two new channels AUCTION and CB and in addition both DC, CALF and RALF gateways get a "spy" clients :

- `pm-calf-spy` , spy on the CALF protocol
- `pm-ralf_spy` , spy on the RALF protocol
- `pm-dc-spy` , spy on the engine drop-copy PUB channel

which are used to take a peek under the protocol hood what information the protocols are sending. These are purely read-only tools.
This release also hardens the matching engine, scheduler, gateways, and clearing pipeline, adds consistent logging controls across processes, and refreshes the user-guide, Exchange Intro, and protocol documentation at much larger scale than a typical minor release. It expands historical index and pricing visibility across the API and stats stack, improves engine handling of quote-leg requests, and tightens gateway/runtime behavior. 
Finally a new gateway was added, `pm-dc-gwy` to make the Drop-Copy available to external clients


### ⚠️ Breaking Changes
- Removed the legacy `clearing_v1` implementation in favor of the current SQLite-backed clearing flow and shared feed-schema contract

### ✨ Additions
- Added `config-gui`, a web application for creating and editing exchange reference data with Docker, Makefile, and workspace support
- Added `pm-audit-cli` together with audit indexing, querying, formatting, and a dedicated user-guide chapter
- Added `pm-index-admin-cli` index administration to handle index adjustment after corporate actions
- Added `pm-calf-spy` to print events sent on the CALF protocol
- Added `pm-ralf-spy` to print events sent on the RALF protocol
- Added `pm-dc-spy` to print all DC events
- Added `pm-dc-gwy` to make DC available for external clients
- Added two new channels to CALF protocol, `AUCTION` and `CB` to provide detailed auction and cb information
- Added ADMIN-only API Gateway operator commands and supporting session/schema updates
- Added CALF protocol extensions including deeper market-data coverage, configurable depth levels, and index-channel support
- Added consistent CLI-controlled logging options across gateway and operator processes, including AI trader, swarm, console, market-data, board, ticker, and viewer entrypoints
- Added Config GUI features for circuit-breaker settings, expert tuning, market-maker configuration, symbol overview, and proxy/frontend support
- Added an explicit shared clearing/engine feed contract in `models/feed_schema.py`
- Added statistics DB update interval control
- Added API support for index history and new history endpoints for index events and historical price snapshots
- Added keyset pagination for index-event history queries
- Added daily and historical index statistics persistence to the stats database
- Added engine handling for system.quote_legs_request with explicit completeness signaling for unavailable historical legs
- Added proxy-oriented container build support for Config GUI
- Added a new concepts chapter on implied orders
- Added QLEGS/RECENT-ALL history support for alf-gwy
- Added gateway-level SMP default for ALF NEW/combo/quote orders

### 🚀 Improvements
- Improved `pm-config-gen` with port-collision detection, chronological schedule validation, and tick-aware combo-leg pricing
- Improved `pm-cverifier` with stricter numeric validation, malformed-time/session checks, and stronger cross-value verification
- Improved logging consistency across engine, scheduler, gateways, audit tooling, and supporting CLI processes with startup flags and structured flow summaries
- Improved Config GUI validation around IPO/reference-price requirements and market-maker quote consistency
- Improved RALF sequence handling, replay filtering, and entitlement-aware delivery behavior
- Improved clearing robustness around reconciliation, warm-start behavior, aggregation, archive deduplication, and CLI display normalization
- Improved API gateway history path behavior and pagination flow under concurrent request load
- Improved index and stats outputs to make final end-of-day index levels clearer to operators
- Improved engine PULL-socket dispatch structure and unknown-topic observability through warning logs and counters
- Improved CALF and RALF example clients with broader protocol-coverage updates

### 🐛 Bug Fixes
- Fixed a large set of reviewed matching-engine defects covering persistence, auctioning, SMP, fills, OCO, order handling, snapshots, validation, exceptions, and related runtime edge cases
- Fixed scheduler state-sync, config-ingestion, and schedule-interpretation defects that could desynchronize runtime session behavior
- Fixed gateway connection-sequence hangs and failure handling across ALF, BALF, CALF, MD, and RALF paths, including blocking-send and malformed-config edge cases
- Fixed circuit-breaker and collar reference seeding so day-one IPO opening prices and persisted book stats are used correctly
- Fixed ALF C example and CI behavior to skip cleanly with diagnostics when GNU readline is unavailable
- Fixed logging initialization paths that could leave process output formatting inconsistent
- Fixed CALF RESUME validation to reject unsupported SYM=* subscriptions
- Fixed API gateway concurrency and pagination defects affecting history retrieval behavior
- Fixed REST API example clients for correctness and static-analysis compliance
- Fixed ALF example value-case handling and related example-code static-analysis issues
- Fixed user-guide broken links

### 📚 Documentation
- Added a full Config GUI chapter plus setup and usage documentation
- Added a full audit CLI chapter and updated release/PDF workflow support for its design materials
- Reorganized the user-guide into a cleaner numbered chapter order with updated navigation, cross-references, and process startup option tables
- Expanded Exchange Intro toward the second edition with new historical notes, revised structure, and a larger quiz/self-study set with answer keys and bundled PDFs
- Added a normative configuration-file specification and updated all protocol specifications to match the latest ALF, BALF, CALF, and RALF behavior
- Updated clearing, risk-control, market-data, README, architecture, and training materials to reflect the current product surface
- Added more self-study exercises and answer keys to the Exchange Intro, including a new quiz on the clearing process and its reconciliation behavior
- Updated user-guide chapters for index, API gateway, processes, statistics, persistence, and related messaging/examples to reflect the latest behavior
- Updated CALF/Index design documentation to align with the latest protocol depth and index-subscription semantics
- Refreshed training and examples documentation for CALF usage and API history workflows
- Added first draft of presentation for use in training
- Added SMP holistic overview in Risk Controls (mechanics, precedence rules, per-path support matrix, worked examples)

### 🛠 Internal
- Refactored the large admin command dispatch chain into handler-based dispatch
- Hardened RALF and other timing-sensitive tests to reduce CI flakiness and improve deterministic readiness checks
- Added richer CI diagnostics for skipped tests and C-example build failures
- Updated dependencies, formatting, and type-check fixes across Python and Node-based tooling
- Added pyright to the Makefile check target to strengthen CI/local static-type validation
- Updated and stabilized tests to align with new API/index return values and buffer-handling behavior
- Added top-level Makefile target to build multipass VM from dev snapshot
- Regenerated all example enging-configuration

## [v0.16.0] - (Not released)

Internal Beta testing version


## [v0.15.3] - 2026-07-07

Release Type: patch

### 📋 Summary
This patch release refreshes the Exchange Intro release bundle and knowledge-check materials, while tightening the supporting build and scripting flow.

### 📚 Documentation
- Updated Exchange Intro to v1.1.1 with refreshed quiz structure and Latex templates
- Added PDF versions of the knowledge quizzes
- Moved the quiz material into the Exchange Intro directory to match the book structure
- Updated README and Makefile support for knowledge checks

### 🛠 Internal
- Fixed the release and build shell script handling for the updated docs workflow

## [v0.15.2] - 2026-07-07

Release Type: patch

### 📋 Summary
This patch release improves persistence robustness against corrupt GTC data on
startup, expands negative and faulty-input test coverage for the engine and
gateways, and adds build and Exchange Intro tooling improvements.

### 🚀 Improvements
- Improved persistence robustness to handle corrupt GTC data on startup without crashing

### 📚 Documentation
- Updated Exchange Intro cover
- Updated book references in Exchange Intro
- Added Exchange Intro Makefile target to produce a bundle with each part as its own PDF

### 🛠 Internal
- Added negative tests covering invalid order and quote inputs to harden the engine
- Added `--no-docs` option to `mkbld.sh` to skip documentation generation during builds

## [v0.15.1] - 2026-07-07

Release Type: patch

### 📋 Summary
This patch release refreshes the Exchange Intro materials with a major structural and content revision, improves release documentation artifacts, and fixes a resource leak in clearing tests. It also polishes supporting references, protocol example descriptions, and build comments.

### ✨ Additions
- Added chapter-level user-guide PDF bundles as release artifacts
- Added generated PDF reports to the release asset set

### 🚀 Improvements
- Improved the Exchange Intro structure and content in the 1.1.0 revision
- Improved protocol example descriptions and supporting reference coverage in the Exchange Intro materials

### 🐛 Bug Fixes
- Fixed a resource leak caused by non-closed DB connections in clearing handler tests

### 📚 Documentation
- Updated Exchange Intro Booklet to v1.1.0 with new chapters and general updates. 
- Updated example configuration content to reflect the latest `pm-config-gen` options

### 🛠 Internal
- Updated Makefile comments and minor changelog wording


## [v0.15.0] - 2026-07-06

Release Type: minor

### 📋 Summary
This release focus on stability improvements for the new clearing process as well as adding the last missing configuration options to `pm-config-gen`for it to be able to generate all supported configurations. In addition, the clearing chapter of the user-guide has been updated to reflect the latest clearing design and implementation details as well as improved P&L calculation description. The user-guide cover image has also been updated to better reflect the actual content.

### ✨ Additions
- Added missing market-maker gateway configuration to `pm-config-gen`

### 🚀 Improvements
- Updated all example configurations in the user-guide to cover the latest `pm-config-gen` options

### 🐛 Bug Fixes
- Fixed a possible deadlock in a rare concurrent execution path in clearing process
- Fixed a unit misidentification bug (ns vs. ms) that could produce incorrect timing calculations in the clearing process

### 📚 Documentation
- Corrected a misleading warning in the configuration chapter that described BALF and CALF as future/unimplemented protocols — both are fully supported via top-level `balf_gateway` and `market_data_gateway` config keys
- Improved cross-references between user-guide chapters
- Updated user-guide cover image
- Improved P&L calculation description in the clearing chapter of the user-guide

### 🛠 Internal
- Updated Copilot assistant instructions for tool usage conventions
- Added per-chapter PDF generation capability to the user-guide docs build system

## [v0.14.1] - 2026-07-05

Release Type: patch

### 📋 Summary
This patch release hardens the new clearing workflow with normalization and reconciliation fixes and adds support for lifecycle messages around gateway connectivity and end-of-day processing. It also includes documentation polish and Makefile/test cleanup.

### ✨ Additions
- Added handling for `system.eod`, `gateway_connect`, and `gateway_disconnect` message-driven behavior in the clearing flow

### 🚀 Improvements
- Improved reconciliation logic to validate both buy-side and sell-side aggregates
- Improved clearing design documentation with secondary-message flow details

### 🐛 Bug Fixes
- Fixed double normalization in clearing output calculations
- Fixed duplicate target declarations in the docs-design Makefile that emitted override warnings

### 📚 Documentation
- Updated clearing design and user-guide content to align with the latest message flow and reporting behavior
- Updated docs PDF layout defaults for improved A4 readability

### 🛠 Internal
- Fixed lint and formatting issues across the updated clearing-related changes
- Reformatted and updated tests to keep static checks and style validation clean


## [v0.14.0] - 2026-07-05

Release Type: minor

### 📋 Summary
This release introduces a redesigned clearing process which now moves from a persisting in a *.cvs filr to a SQLite DB. In addition a new tool `pm-clearing-cli` 
is introduced whcih allow a clearing house to examine the trades in a srtuctured way.

### ✨ Additions
- Added a new clearing process `pm-clearing` based on the redesigned clearing process
- Added `tick_decimals` to `trade.executed` messages so clients can normalize display prices without reading symbol configuration
- Added `pm-clearing-cli` tool
- Added `--version` support across `pm-*` entrypoint modules


### 🚀 Improvements
- Improved clearing documentation with expanded process design details and updated implementation guidance
- Improved README structure and tightened project overview wording

### 📚 Documentation
- Updated message and clearing documentation for `tick_decimals` propagation and clearing CLI output behavior
- Updated the clearing redesign documentation with additional process and implementation details


### 🛠 Internal
- Expanded and reformatted clearing tests while resolving lint and mypy issues
- Cleaned up clearing code comments and related test formatting
- Added an initial contract-multiplier design document for future symbol-level economic exposure support


## [v0.13.5] - 2026-07-04

Release Type: patch

### 📋 Summary
This patch release tightens API gateway configuration handling and strengthens `pm-cverifier` checks for gateway-related sections. 
It also standardizes the API gateway process command name to match the gateway naming convention used across the project.

### ⚠️ Breaking Changes
- Renamed the API gateway process command from `pm-api-gateway` to `pm-api-gwy`; update scripts, automation, and operational runbooks that invoke the old command name
- Removed legacy singular `api_gateway` config compatibility and now require top-level `api_gateways` in `engine_config.yaml`

### 🚀 Improvements
- Improved `pm-cverifier` schema coverage for API gateway sections by validating `api_gateways` with runtime-loader semantics
- Improved config verification parity for post-trade and market-data gateway sections and tightened market-maker schema checks

### 📚 Documentation
- Updated user-guide, training, architecture, and design documents to consistently use `pm-api-gwy`
- Updated configuration and verifier documentation to reflect `api_gateways`-only support

### 🛠 Internal
- Expanded regression tests for API gateway config loading and verifier behavior around gateway section validation and legacy-key rejection


## [v0.13.4] - 2026-07-04

Release Type: patch

### 📋 Summary
This patch release hardens configuration verification and improves documentation for configuration workflows. It also fixes a flaky RALF example test timeout caused by PUB/SUB timing.

### 🚀 Improvements
- Improved `pm-cverifier` semantic and schema validation around market-maker settings and BALF gateway checks
- Improved verifier robustness for malformed config shapes to avoid crashes and return actionable findings

### 🐛 Bug Fixes
- Fixed intermittent timeout in `test_python_example_subscribes_and_parses_gateway_exec` by making the RALF PUB/SUB test resilient to subscription propagation timing

### 📚 Documentation
- Updated config verifier user-guide content with current checks and BALF gateway validation guidance
- Added startup training exercises for validating configs with `pm-cverifier`, including strict and JSON workflows
- Updated README structure and overview details for performance, protocols, and documentation navigation

### 🛠 Internal
- Added broad `pm-cverifier` regression coverage for BALF, market-maker, and malformed-input edge cases


## [v0.13.3] - 2026-07-04

Release Type: patch

### 📋 Summary
Fix a few broken links in the User Guide

### 📚 Documentation
- Fix broken links in BALF User Guide to normative protocol sections


## [v0.13.2] - 2026-07-04

Release Type: patch

### 📋 Summary
This patch release stabilizes documentation publishing by fixing the GitHub Pages deployment workflow due to deprecated deployment verbs.

### 🐛 Bug Fixes
- Fixed GitHub Pages documentation deployment by switching to the supported artifact-based actions flow

### 🛠 Internal
- Updated `.github/workflows/docs.yml` to remove legacy deployment steps and use the current GitHub Pages action pattern


## [v0.13.1] - 2026-07-03

Release Type: patch

### 📋 Summary
This patch release focuses on documentation quality and cross-platform doc build reliability after the 0.13.0 gateway release. The build system is now full compatible for Linux.

### 🚀 Improvements
- Improved documentation build portability by making the docs Makefile work on Linux environments

### 🐛 Bug Fixes
- Fixed decimal-mark interpretation so dot-based numeric parsing is handled correctly

### 📚 Documentation
- Added BALF training chapter content to expand external gateway training coverage
- Updated README with performance metrics captured from a Linux server


## [v0.13.0] - 2026-07-02

Release Type: minor

### 📋 Summary
This release introduces two new external-facing TCP gateways 
1) `pm-alf-gwy` (text ALF1 protocol) and 
2) `pm-balf-gwy` (binary BALF protocol). 
These new Gateways enable third-party trading systems to connect from external hosts over defined protocols without using the internal ZMQ bus. 
The internal trading console is renamed from `pm-gateway` to `pm-alf-console` to claify its role.

### ⚠️ Breaking Changes
- Renamed `pm-gateway` to `pm-alf-console`; any scripts, aliases, or systemd units invoking `pm-gateway` must be updated

### ✨ Additions
- Added `pm-alf-gwy`: new external-facing TCP gateway implementing the text-based ALF1 session protocol, with configurable gateway roles, rate limiting, heartbeat/idle timeouts, and `disconnect_behaviour` support
- Added `pm-balf-gwy`: new external-facing TCP gateway implementing the BALF binary protocol using fixed-size little-endian frames, full order lifecycle (new/cancel/amend), engine event delivery (ack/fill/cancelled/amended/expired), and deterministic reject-code classification
- Added reference C client (`alf_client.c`, `alf_parser.c`) and Python client (`alf_client.py`, `alf_parser.py`) for external ALF1 connections
- Added `docs/user-guide/24-alf-gateway.md`: full ALF gateway user-guide chapter with protocol reference and operator runbook
- Added `BALF` support to `pm-config-gen` and `pm-cverifier` 

### 📚 Documentation
- Updated user guide to cover the new BALF and ALF gateways


## [v0.12.5] - 2026-07-02

Release Type: patch

### 📋 Summary
This patch delivers an updated trainging section matching the latest code changes.

### 📚 Documentation
- Updated training section

## [v0.12.4] - 2026-07-01

Release Type: patch

### 📋 Summary
Documentation update with refreshed architecture overview and shortened `README.md`

### 📚 Documentation
- Converted ZMQ topology diagram, session state machine, and combo lifecycle state machine to Mermaid in the architecture overview
- Expanded the architecture message-topics reference to include all current messages: amend, OCO, quotes, risk controls, circuit-breaker events, drop-copy, and the index bus
- Updated Getting Started installation guide with current environment and setup steps
- Focused README scope and updated feature descriptions

## [v0.12.3] - 2026-07-01

Release Type: patch

### 📋 Summary
This patch hardens resource lifecycle and shutdown behavior across the stats,
clearing, CALF, RALF, and ticker paths, eliminating leaked SQLite, file, TCP,
and ZMQ handles found under strict warning checks. It also expands gateway and
post-trade documentation and adds broader regression coverage for index,
scheduler, and stats workflows.

### 🚀 Improvements
- Improved RALF gateway subscription handling by enforcing role-to-channel entitlement checks for non-AUDIT clients
- Improved RALF end-of-day reporting by tracking and emitting per-symbol trade counts in EOD events
- Improved build portability by adapting Puppeteer path handling for different operating systems

### 🐛 Bug Fixes
- Fixed leaked SQLite connections in `pm-stats` teardown paths that surfaced as `ResourceWarning` during full test runs
- Fixed leaked file, TCP, and ZMQ handles across clearing, index history, CALF, RALF, ticker, and related test fixtures by adding explicit cleanup paths and closing replaced sockets
- Fixed gateway receive-loop cleanup paths to guard double-close behavior and continue safely on malformed frames while still honoring `errno.EINTR`

### 📚 Documentation
- Expanded gateway and post-trade user-guide chapters with harmonized structure and richer protocol and operational guidance
- Updated README, Getting Started, VM runtime, and training material to reflect current feature scope and environment details

### 🛠 Internal
- Added broad regression coverage for `pm-index-cli`, scheduler helpers, stats order flows, and stats CLI output handling
- Fixed type and lint issues across test and support code
- Bumped project dependencies and refreshed build-script and Makefile support files


## [v0.12.2] - 2026-06-30

Release Type: patch

### 📋 Summary
This patch hardens ZMQ receive loops and socket lifecycle across all gateway and
process modules, eliminating socket leaks, over-broad exception catches, and
signal-handler safety violations. The CALF documentation is significantly
expanded with a full channel reference, protocol comparison table, and annotated
Python subscriber examples.

### 🐛 Bug Fixes
- Fixed `bids[0]["price"]` / `asks[0]["price"]` dict access in `board`, `ticker`, `stats`, and MM bot — raises `KeyError` on malformed book levels; changed to `.get("price")`
- Fixed `except zmq.ZMQError: break` in receive loops across `board`, `ticker`, `api_gateway`, `audit`, `clearing`, `index`, `stats`, and `md_gateway` — was catching all errors including real failures; now checks `errno.EINTR` and re-raises others
- Fixed `viewer` push socket not closed on exception path in `_request_snapshot`
- Fixed `ticker` accessing `self.sub` from main thread while daemon receive thread owns it — ZMQ thread-safety violation
- Fixed `clearing` signal handler calling `_stop()` which performed I/O and lock acquisition from a signal context — refactored to flag-only
- Fixed `clearing` and `audit` ZMQ sockets not closed when `run()` exits via exception
- Fixed `ralf_gateway` and `md_gateway` `--engine-pub` CLI default baking in a hardcoded address, silencing any config-file override; changed to `None`
- Fixed `md_gateway` ZMQ sockets created in `__init__` leaking when `run()` raises before reaching its own cleanup; wrapped main loop in `try/finally`
- Fixed `md_gateway` bare `decode(recv_multipart())` calls in `_poll_engine_events` — unguarded decode of a malformed engine frame would crash the gateway; wrapped in `try/except Exception: continue`
- Fixed `stats` `self.push` socket accessed from both main thread and receive thread without a lock; added `self._push_lock`
- Fixed `stats` subscription filter `"trade."` matching unintended topics; narrowed to `"trade.executed"`
- Fixed `scheduler` push socket not closed in `finally` on the `sys.exit(1)` path

### 📚 Documentation
- Added full CALF TCP protocol section to `09-messages.md` covering all 13 message types, error codes, and `pm-md-gwy` subscription filter row
- Added `INDEX` channel and `IDX` message definition to `92-app-calf-protocol.md`; synchronized ERR code descriptions between `92-app-calf-protocol.md` and `09-messages.md`
- Expanded `20-market-data-feed.md` with per-channel deep-dives (`TOP`, `TRADE`, `STATE`, `INDEX`), protocol comparison table, step-by-step connection guide, gap-detection and replay-recovery section, annotated Python subscriber using `examples/calf/calf_parser.py`, and targeted-subset subscription table

### 🛠 Internal
- Added code review skill to `.github/skills/code-review/SKILL.md`
- Updated `test_md_gateway_main.py` and `test_md_gateway_runtime_paths.py` to add `close()` method and `closed` property to test stubs
- Updated `test_ralf_main.py` for new `--engine-pub` default of `None`

## [v0.12.1] - 2026-06-29

Release Type: patch

### 📋 Summary
This patch release fixes eight bugs across the matching engine and MM bot, and refactors the ALF Gateway into separate submodules for better maintainability. Documentation is updated with improved API Gateway guidance, an expanded AI Trader design, and an index-controlled circuit-breaker design refresh.

### 🐛 Bug Fixes
- Fixed `_run_uncross()` not triggering stop orders whose stop price was reached by the equilibrium price
- Fixed `_run_uncross()` not updating the position ledger for auction fills, leaving position snapshots stale
- Fixed race condition in engine signal handler calling `_shutdown()` mid-handler instead of setting a flag
- Fixed passive orders resting in the book at shutdown silently matching on next startup with no trade emitted
- Fixed MM bot `_handle_order_fill` overwriting the cancel-confirmation timeout when a fill arrives while a cancel is already in flight
- Fixed MM bot `_handle_book` raising `KeyError` when a book message contains a malformed bid or ask level
- Fixed MM bot `_run_loop` crashing with an unhandled `ValueError` from `QuotePricer` when symbol metadata produces an invalid gap
- Fixed MM bot `_handle_quote_status` scheduling a duplicate reissue for orphaned `CANCELLED` events that follow an already-processed `INACTIVE`
- Fixed broken documentation links in the user-guide landing page

### 📚 Documentation
- Improved API Gateway training material and user-guide coverage
- Added expanded AI Trader v2 design with message structure, position snapshot protocol, and per-gateway fill history
- Refreshed index-controlled circuit-breaker design documentation

### 🛠 Internal
- Refactored ALF Gateway `main.py` into `completer.py` (tab-completion) and `display.py` (console helpers), with backward-compatible re-exports
- Reduced default VM disk allocation to 8 GB in bootstrap configuration


## [v0.12.0] - 2026-06-27

Release Type: minor

### 📋 Summary
This release introduces the new `pm-cverifier` command-line tool for validating exchange configuration files through layered checks and actionable output. It also refreshes VM bootstrap versioning and extends design documentation for configuration verification and index-controlled circuit-breaker behavior.

### ✨ Additions
- Added `pm-cverifier` CLI tooling with layered YAML, schema, semantic, and completeness validation

### 📚 Documentation
- Added user-guide and process documentation for running configuration verification workflows
- Added index-controlled circuit-breaker design documentation in the design docs set

### 🛠 Internal
- Improved build and release workflow by adding `mp-bump` execution to `mkbld.sh` to keep Multipass bootstrap version in sync with latest release.

## [v0.11.0] - 2026-06-26

Release Type: minor

### 📋 Summary
This release introduces index process tooling and improves operational robustness for the API Gateway and MM bot workflows. It also expands training and user-guide content for index and process usage.

### ✨ Additions
- Added `pm-index` process and `pm-index-cli` tool with supporting documentation

### 🚀 Improvements
- Improved API Gateway reliability and behavior across hardened runtime and route paths
- Improved MM bot resilience to dropped `quote.ack` and missed status flows with self-healing reissue behavior

### 🐛 Bug Fixes
- Fixed MM bot reissue liveness gaps that could leave quoting stalled after dropped acknowledgement paths

### 📚 Documentation
- Added exchange index usage and configuration training material
- Updated Getting Started and landing-page process guidance for clearer operator onboarding
- Updated MM bot user-guide coverage for reconciliation and recovery behavior

### 🛠 Internal
- Added a script to clean up old GitHub Actions workflows


## [v0.10.1] - 2026-06-25

Release Type: patch

### 📋 Summary
This patch release improves PDF documentation rendering stability and layout consistency for Mermaid-heavy content. It also includes minor documentation text refinements.

### 🚀 Improvements
- Improved Mermaid figure sizing in the PDF pipeline for more consistent diagram rendering
- Improved pagebreak handling in the Lua filter by emitting clearpage to better handle floating images

### 📚 Documentation
- Updated documentation text with minor wording and clarity refinements


## [v0.10.0] - 2026-06-24

Release Type: minor

### 📋 Summary
This release introduces the new API Gateway REST/WebSocket flow and strengthens matching-engine correctness in critical execution paths. It also expands Exchange Intro and User Guide coverage with new operational and known-limitations material, while improving PDF build reliability across documentation workspaces.

### ✨ Additions
- Added `pm-api-gateway` with REST and WebSocket support for authenticated order and event workflows
- Added API Gateway training material with end-to-end exercises for REST, WebSocket, and multi-instance gateway separation
- Added index calculation data support in statistics with `order_events` table and query coverage

### 🚀 Improvements
- Improved PDF build robustness with fail-fast LaTeX toolchain checks across documentation Makefiles

### 🐛 Bug Fixes
- Fixed three critical matcher defects affecting auction uncross handling after circuit-breaker resume, iceberg peek-quantity accounting, and aggressive sweep event duplication
- Fixed `OrderBook.cancel_order` corruption of quantity indexes when canceling untriggered STOP_LIMIT orders
- Fixed missing ALF gateway tab-completion behavior
- Fixed theoretical inconsistencies in `pm-stats` processing paths

### 📚 Documentation
- Added a detailed Known Limitations and Bugs chapter documenting the multi-level sweep aggressor VWAP/P&L limitation and proposed remediation paths
- Updated Exchange Intro preface and supporting text for improved readability and consistency


## [v0.9.2] - 2026-06-22

Release Type: patch

### 📋 Summary
This patch release refines `pm-config-gen` output with clearer, better-placed setting comments and more complete risk-level coverage, and hardens Mermaid diagram rendering against theme-related race conditions in the documentation builds. It also adds a complete set of example configurations (ref-data). 

### 🚀 Improvements
- Improved `pm-config-gen` generated configs by placing each setting's comment on the line above the setting for better readability
- Improved generated config comments with fuller per-setting explanations and previously missing `risk_level` settings
- Improved per-symbol risk-level configuration support in `pm-config-gen`

### 🐛 Bug Fixes
- Fixed a Mermaid rendering race condition with color themes that could produce inconsistent diagrams

### 📚 Documentation
- Clarified the distinction between circuit breakers and price collars in the configuration and risk-control documentation
- Minor text updates to the Exchange Intro

### 🛠 Internal
- Added a script to count glossary entries in the Exchange Intro book
- Removed an obsolete top-level config file
- Updated bootstrap and Multipass setup scripts to the latest versions
- Bumped Exchange Intro to 1.0.3


## [v0.9.1] - 2026-06-21

Release Type: patch

### 📋 Summary
This patch release improves configuration-generation workflows and refreshes the ref-data example set so generated files better expose available defaults to end users. It also includes targeted documentation and training refinements for CALF, RALF, and VM onboarding.

### ✨ Additions
- Added `pm-config-gen` support for emitting comment blocks that list defaultable `engine_config.yaml` fields when values are omitted
- Added expanded ref-data example profiles covering one, three, ten, and thirty-book setups across basic, nominal, and complex variants

### 🚀 Improvements
- Improved market-maker seed generation so configs can emit deterministic midpoint-based startup quotes instead of manual post-processing
- Improved `pm-config-gen` coverage for CALF-oriented configuration generation paths used by example datasets
- Improved generated example configs by regenerating all ref-data outputs with default-field comment visibility enabled

### 📚 Documentation
- Updated User Guide and training material for CALF and RALF workflows with additional operational guidance
- Updated VM installation guidance for a clearer setup path in training flows

### 🛠 Internal
- Updated release assets and example snapshots to align with regenerated config outputs


## [v0.9.0] - 2026-06-21

Release Type: minor

### 📋 Summary
This release fully implements the CALF protocol for market-data dissemination and extends the user-guide with practical examples and operator guidance. It also improves training coverage for CALF and RALF workflows.

### ✨ Additions
- Added CALF protocol implementation with companion documentation and third-party connection examples

### 🚀 Improvements
- Improved gateway operator readiness with a dedicated CALF and RALF runbook

### 📚 Documentation
- Added a new examples section in the User Guide for protocol-oriented workflows
- Updated training and User Guide content with expanded CALF and RALF coverage

### 🛠 Internal
- Improved user-guide structure by renaming appendixes to make room for additional chapters


## [v0.8.0] - 2026-06-20

Release Type: minor

### 📋 Summary
This release adds a turnkey Multipass VM runtime flow so users can bootstrap EduMatcher with a single curl command and run the EuMatcher platform directly in a fresh VM. It also improves onboarding documentation with VM-specific setup and launch guidance.

### ✨ Additions
- Added a Multipass VM provisioning pipeline in `vm/` with automated runtime installation and setup
- Added a curl bootstrap script to download and run the VM build and provisioning scripts without cloning the full repository

### 📚 Documentation
- Updated the docs landing page quick-start section with curl-based VM setup and links to detailed setup guides
- Illustration of Exchange and Order books created and added



## [v0.7.1] - 2026-06-20

Release Type: patch

### 📋 Summary
This patch release hardens cross-platform reliability for the RALF example integration tests, especially on Linux CI runners. It also improves protocol discoverability in the User Guide by adding a dedicated overview page that maps ALF, BALF, CALF, and RALF usage and references.


### 🐛 Bug Fixes
- Fixed Linux PTY read handling in RALF C example tests where EOF can surface as `EIO`
- Fixed Linux portability issues in RALF C example sources and build flags to avoid platform-specific crashes

### 📚 Documentation
- Added an External Protocols Overview chapter describing ALF, BALF, CALF, and RALF purpose, status, and where to find detailed protocol references
- Updated User Guide cross-links so protocol selection and process-level protocol context are easier to discover

### 🛠 Internal
- Cleaned up and refactored RALF example test code to reduce duplication while preserving behavior


## [v0.7.0] - 2026-06-20

Release Type: minor

### 📋 Summary
This release introduces the new RALF post-trade dissemination flow with the `pm-ralf-gwy` gateway, protocol appendix, and external client examples for clearing, drop-copy, and audit consumers. It also extends configuration generation and training content so operators and students can provision and run RALF workflows end to end.

### ✨ Additions
- Added `pm-ralf-gwy` post-trade dissemination gateway with RALF1 session handling, subscriptions, heartbeats, and replay support
- Added RALF protocol and user-guide material including the dedicated post-trade chapter and protocol appendix
- Added Python and C RALF parser and subscriber example libraries in `docs-design/examples/ralf`
- Added a dedicated training chapter for RALF protocol operations covering handshake, subscriptions, replay, and error-handling drills

### 🚀 Improvements
- Improved `pm-config-gen` to optionally emit a top-level `post_trade_gateway` section with configurable RALF listener options
- Improved release packaging to include training bundle artifacts


### 📚 Documentation
- Updated the RALF protocol appendix to explicitly state protocol support is provided through TCP connection to `pm-ralf-gwy`
- Expanded training and user-guide cross-references for new RALF and post-trade workflows


## [v0.6.1] - 2026-06-19

Release Type: patch

### 📋 Summary
This patch release adds a dedicated PDF pipeline for the Training Guide and aligns the training LaTeX templates with a single chapter-level TOC and training-specific cover output. It also updates release packaging to include training PDF artifacts.

### ✨ Additions
- Added a dedicated `training-pdf` Make target that builds all four Training Guide PDF variants into `docs/dist`
- Added release packaging updates so the Training Guide PDF bundle is included in GitHub release artifacts

### 📚 Documentation
- Updated and refined training chapters with improved user-guide cross-links and consistency updates

### 🛠 Internal
- Added a dedicated performance test Make target for easier benchmarking workflows
- Updated CI workflows to remain Node 24 compatible for artifact handling


## [v0.6.0] - 2026-06-19

Release Type: minor

### 📋 Summary
This release adds the new `pm-mm-bot` autonomous market-maker process and expands gateway support for market-maker startup and quote-leg inspection workflows (exposed through the new QBOOT and QLEGS commands). It also adds a self-paced training section which teaches the running and operation of the exchange. The user-guide material was significantly updated and expanded to match the latest release.

### ✨ Additions
- Added `pm-mm-bot` autonomous market-maker process for maintaining two-sided liquidity with session-aware startup, quote refresh, and repricing logic
- Added `QBOOT` command and wire message support for discovering existing active quote bootstrap state during market-maker startup and reconnect flows
- Added `QLEGS` operator command in `pm-gateway` for inspecting active and recently completed quote legs with fill-state visibility
- Added symbol metadata to `system.symbols.{GW}` replies and extended the gateway `SYMBOLS` command to display tick size and MM obligation metadata
- Added new training chapters covering advanced admin operations, drop-copy replay/recovery, and automation with `ExchangeCommandClient` and `pm-mm-bot`

### 🐛 Bug Fixes
- Fixed Mermaid rendering failures in MM design documentation caused by unescaped pipe characters in graph labels

### 📚 Documentation
- Added a full user-guide page for `pm-mm-bot` including CLI usage, bootstrap behavior, session handling, and troubleshooting guidance
- Updated gateway and message documentation to describe `QBOOT`, `QLEGS`, enriched `SYMBOLS` metadata, and MM-oriented operator workflows
- Added self-paced training material across installation, startup, market making, trade lifecycle, observer processes, and advanced operational topics

### 🛠 Internal
- Added latency performance test coverage 


## [v0.5.0] - 2026-06-17

Release Type: minor

### 📋 Summary
This release adds a new `pm-stats-cli` command for querying simulation statistics, refactors the exchange introduction documentation for easier maintenance, and optimizes the PDF build pipeline. It also improves process documentation and updates dependencies.

### ✨ Additions
- Added `pm-stats-cli` command for querying and reporting on simulation statistics stored in `stats.db`, replacing the need for direct SQL access

### 🚀 Improvements
- Improved documentation of all `pm-` CLI commands and processes
- Improved PDF build pipeline to run all builds in full parallel mode for faster build time
- Refactored Exchange Intro documentation into separate chapter files with a Manifest configuration for easier maintenance

### 📚 Documentation
- Added comprehensive statistics and reporting chapter to the User Guide documenting `pm-stats-cli` usage and capabilities
- Fixed broken documentation links in user-guide and related docs

### 🛠 Internal
- Bumped project dependencies to latest versions
- Bumped build-tools to latest version
- Updated default Make target


## [v0.4.0] - 2026-06-16

Release Type: minor

### 📋 Summary
This release focus on improving config documentation and generation. It adds a new `pm-config-gen` CLI for generating 
egine config `engine_config.yaml` file from concise command-line inputs. It also expands the
configuration documentation and design material so users can bootstrap configs
faster with fewer manual YAML errors.

### ✨ Additions
- Added `pm-config-gen` CLI tool for generating `engine_config.yaml` from high-level flags to make it less error prone to correctly write the engine configuration.

### 📚 Documentation
- Expanded the configuration guide with a full `pm-config-gen` reference, option tables, formats, and practical recipes
- Updated Getting Started, Running the Engine, docs landing page, and README quick-start paths to include `pm-config-gen`
- Refreshed configuration examples and design references to match current parser behaviour and defaults
- Improved FAQ
- Updated admonition rendering in Exchange Intro
- Updated various Mermaid graphs in docs

### 🛠 Internal
- Added design proposal for config-generator behaviour, option surface, and implementation plan


## [v0.3.3] - 2026-06-15

Release Type: patch

### 📋 Summary
This patch release hardens the documentation PDF toolchain and refreshes user-guide and architecture documentation. It focuses on reliable Mermaid and admonition rendering in generated PDFs while cleaning up docs build flow and fixing documentation issues.

### ✨ Additions
- Added Mermaid rendering support for User Guide and Design Docs PDF generation

### 🚀 Improvements
- Improved docs build flow by moving PDF bundle orchestration into Makefiles instead of `mkbld.sh`
- Improved docs Makefile consistency by reusing the same `node_modules` build-tools directory across docs pipelines

### 🐛 Bug Fixes
- Fixed PDF rendering of `note` admonitions and Lua-filtered admonition boxes which was missing

### 📚 Documentation
- Updated User Guide content and corrected broken-link references
- Updated architecture descriptions to match the current implementation
- Fixed multiple broken documentation links in the User Guide and related docs


## [v0.3.2] - 2026-06-14

Release Type: patch

### 📋 Summary
This patch release refreshes the documentation with an updated landing page and updated developer guidance and new design proposals for cross-host process distribution and statistics CLI reporting. No code changes.

### ✨ Additions
- Added cross-host load-balancing design proposal for running EduMatcher processes across multiple machines
- Added statistics CLI command design proposal to replace error-prone direct SQL querying of `stats.db`

### 📚 Documentation
- Improved documentation landing page structure and navigation for faster onboarding
- Updated developer practice and release workflow guidance to match current checklist and script behaviour
- Refreshed experiments proposal


## [v0.3.1] - 2026-06-14

Release Type: patch

### 📋 Summary
This patch release refreshes the FAQ with practical setup and runtime troubleshooting for the new pipx-based installation flow.

### 📚 Documentation
- Expanded FAQ with a new Installation & Setup section covering pipx vs Poetry usage, PATH issues after pipx install, `pm-setup` usage, config/data file lookup rules, and upgrade guidance
- Added FAQ entries for beginner runtime gotchas: pre-seeded MM liquidity matching the first aggressive order, `seed_once` behaviour across days, CLOSED startup state with sessions enabled, and practical state reset instructions
- Updated FAQ launcher references to `./tools/launch_all.sh` and added `tmux`/`screen` alternatives for server environments

### 🛠 Internal
- Updated GitHub Actions artifact upload steps to `actions/upload-artifact@v5` in CI and docs workflows to eliminate Node 20 deprecation warnings


## [v0.3.0] - 2026-06-14

Release Type: minor

### 📋 Summary
This release makes EduMatcher fully installable as a standalone runtime via `pipx install edumatcher`, with no source checkout or Poetry required for end users. A new `pm-setup` bootstrap command, two runtime environment variables (`EDUMATCHER_DATA_DIR`, `EDUMATCHER_CONFIG`), and an updated launch script give instructors and students a clean, repeatable installation path independent of the development environment.

### ✨ Additions
- Added `pm-setup` entry point to bootstrap a session directory: creates the data directory, copies the bundled sample `engine_config.yaml` to the working directory, and prints a shell profile snippet
- Added `EDUMATCHER_DATA_DIR` environment variable to override the data directory at runtime (default: `~/.local/share/edumatcher` when installed, `src/data/` in a source checkout)
- Added `EDUMATCHER_CONFIG` environment variable to override the engine config path at runtime (default: `./engine_config.yaml` in CWD when installed, repo-root file in a source checkout)
- Added `scripts/install-runtime.sh` one-shot installer: checks Python 3.13+, installs pipx if absent, installs `edumatcher` from PyPI, and runs `pm-setup`
- Bundled `engine_config.sample.yaml` as a package resource (extracted by `pm-setup` via `importlib.resources`)

### 🚀 Improvements
- Updated `tools/launch_all.sh` to detect installed vs source mode automatically: runs bare `pm-*` commands when on PATH, falls back to `poetry run` in a source checkout; exports `EDUMATCHER_DATA_DIR`/`EDUMATCHER_CONFIG` to each spawned Terminal window
- Improved `config.py` resolution: source-tree detection (`_IN_SOURCE_TREE`) keeps the existing developer defaults unchanged while enabling XDG-standard paths for installed users

### 📚 Documentation
- Rewrote Getting Started installation section with separate end-user (pipx) and developer (Poetry) tracks, env var reference table, and `pm-setup` walkthrough
- Added developer vs installed mode comparison table to Running the Exchange page
- Stripped `poetry run` prefix from all command examples in Running the Exchange and Processes pages; added installation-mode admonition and env var reference table to Processes page
- Added admonition in Getting Started five-minute walkthrough explaining that an existing MM seed quote may fill the first aggressive order before the second participant types anything

### 🛠 Internal
- Excluded `setup_cmd.py` from coverage reporting (bootstrap CLI not suitable for unit tests)
- Added `tests/test_config_runtime.py` with 5 tests covering `EDUMATCHER_DATA_DIR` and `EDUMATCHER_CONFIG` env var resolution
- Fixed pyright `reportConstantRedefinition` errors in `config.py` by replacing `if/elif/else` assignments with resolver functions
- Fixed mypy `attr-defined` errors in `test_config_runtime.py` by typing the helper return as `types.ModuleType`

## [v0.2.1] - 2026-06-14

Release Type: patch

### 📋 Summary
This patch release fixes a bug where MM seed quotes were re-injected on every engine restart, introduces the `seed_once` configuration field to control that behaviour, and substantially expands the User Guide with three new sections and comprehensive inline documentation for `engine_config.yaml`.

### ✨ Additions
- Added `seed_once` field to `market_maker_quotes` entries in `engine_config.yaml`: `true` (default) injects quotes only on the first startup for a symbol; `false` re-injects on every restart for repeatable demo setups
- Added Getting Started user guide section with architecture overview, minimum session walkthrough, and role-based reading path
- Added Market Making user guide section covering QUOTE command, quote lifecycle, quote refresh policies, MM obligations, MMP sequence, disconnect behaviour, and startup seeding
- Added AI Traders user guide section covering `pm-ai-trader` and `pm-ai-swarm`, personality profiles, decision loop, risk mechanisms, and classroom demo setup
- Added CLI Statistics commands design proposal identifying server-side commands for querying `stats.db` without raw SQL

### 🐛 Bug Fixes
- Fixed GTC quote legs being written to `gtc_orders.json` at shutdown, causing duplicate resting orders in the book on subsequent engine restarts

### 📚 Documentation
- Rewrote `engine_config.yaml` as a fully annotated reference covering all supported fields, precedence rules, and enum values; added examples of all three gateway roles (TRADER, MARKET_MAKER, ADMIN), per-symbol `mm_obligations` overrides, circuit-breaker level merging, and `seed_once` behaviour
- Expanded persistence user guide section with complete schema reference for `audit.log`, `clearing_report.csv`, and `stats.db` (DDL, column descriptions, example SQL queries)
- Added See Also footers to all user guide sections that lacked them
- Converted remaining ASCII diagrams to Mermaid in combo, auction/scheduling, drop-copy, and persistence sections
- Expanded PnL/clearing, gateway, and configuration sections with additional detail and worked examples

### 🛠 Internal
- Fixed black formatting violation in `config_loader.py`
- Made Exchange Intro PDF build optional in `mkbld.sh` behind a new `--intro` flag

## [v0.2.0] - 2026-06-14

Release Type: minor

### 📋 Summary
This release completes the protocol design documentation suite by publishing the BALF design proposal at v1.0.0 and integrating both BALF and CALF protocol appendixes into the User Guide. It marks the first minor version increment, establishing a stable baseline for the full protocol documentation set.

### 📚 Documentation
- Update glossary and sync global and Exchange Intro glossary

### ✨ Additions
- Added BALF protocol design proposal v1.0.0 covering allocation, liquidity, and feed mechanics
- Added BALF protocol description appendix to the User Guide
- Added CALF protocol appendix to the User Guide with harmonized terminology across all protocol appendixes

## [v0.1.9] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release expands the concept documentation with a new CALF market-data feed page, improves clarity across existing order-book pages, and reorganises the Glossary. GitHub Actions are also updated to be Node 24 compatible.
## [v0.3.0] - 2026-06-14

Release Type: minor

### 📋 Summary
This release makes EduMatcher fully installable as a standalone runtime via `pipx install edumatcher`, with no source checkout or Poetry required for end users. A new `pm-setup` bootstrap command, two runtime environment variables (`EDUMATCHER_DATA_DIR`, `EDUMATCHER_CONFIG`), and an updated launch script give instructors and students a clean, repeatable installation path independent of the development environment.

### ✨ Additions
- Added `pm-setup` entry point to bootstrap a session directory: creates the data directory, copies the bundled sample `engine_config.yaml` to the working directory, and prints a shell profile snippet
- Added `EDUMATCHER_DATA_DIR` environment variable to override the data directory at runtime (default: `~/.local/share/edumatcher` when installed, `src/data/` in a source checkout)
- Added `EDUMATCHER_CONFIG` environment variable to override the engine config path at runtime (default: `./engine_config.yaml` in CWD when installed, repo-root file in a source checkout)
- Added `scripts/install-runtime.sh` one-shot installer: checks Python 3.13+, installs pipx if absent, installs `edumatcher` from PyPI, and runs `pm-setup`
- Bundled `engine_config.sample.yaml` as a package resource (extracted by `pm-setup` via `importlib.resources`)

### 🚀 Improvements
- Updated `tools/launch_all.sh` to detect installed vs source mode automatically: runs bare `pm-*` commands when on PATH, falls back to `poetry run` in a source checkout; exports `EDUMATCHER_DATA_DIR`/`EDUMATCHER_CONFIG` to each spawned Terminal window
- Improved `config.py` resolution: source-tree detection (`_IN_SOURCE_TREE`) keeps the existing developer defaults unchanged while enabling XDG-standard paths for installed users

### 📚 Documentation
- Rewrote Getting Started installation section with separate end-user (pipx) and developer (Poetry) tracks, env var reference table, and `pm-setup` walkthrough
- Added developer vs installed mode comparison table to Running the Exchange page
- Stripped `poetry run` prefix from all command examples in Running the Exchange and Processes pages; added installation-mode admonition and env var reference table to Processes page
- Added admonition in Getting Started five-minute walkthrough explaining that an existing MM seed quote may fill the first aggressive order before the second participant types anything

### 🛠 Internal
- Excluded `setup_cmd.py` from coverage reporting (bootstrap CLI not suitable for unit tests)
- Added `tests/test_config_runtime.py` with 5 tests covering `EDUMATCHER_DATA_DIR` and `EDUMATCHER_CONFIG` env var resolution
- Fixed pyright `reportConstantRedefinition` errors in `config.py` by replacing `if/elif/else` assignments with resolver functions
- Fixed mypy `attr-defined` errors in `test_config_runtime.py` by typing the helper return as `types.ModuleType`

## [v0.2.1] - 2026-06-14

Release Type: patch

### 📋 Summary
This patch release fixes a bug where MM seed quotes were re-injected on every engine restart, introduces the `seed_once` configuration field to control that behaviour, and substantially expands the User Guide with three new sections and comprehensive inline documentation for `engine_config.yaml`.

### ✨ Additions
- Added `seed_once` field to `market_maker_quotes` entries in `engine_config.yaml`: `true` (default) injects quotes only on the first startup for a symbol; `false` re-injects on every restart for repeatable demo setups
- Added Getting Started user guide section with architecture overview, minimum session walkthrough, and role-based reading path
- Added Market Making user guide section covering QUOTE command, quote lifecycle, quote refresh policies, MM obligations, MMP sequence, disconnect behaviour, and startup seeding
- Added AI Traders user guide section covering `pm-ai-trader` and `pm-ai-swarm`, personality profiles, decision loop, risk mechanisms, and classroom demo setup
- Added CLI Statistics commands design proposal identifying server-side commands for querying `stats.db` without raw SQL

### 🐛 Bug Fixes
- Fixed GTC quote legs being written to `gtc_orders.json` at shutdown, causing duplicate resting orders in the book on subsequent engine restarts

### 📚 Documentation
- Rewrote `engine_config.yaml` as a fully annotated reference covering all supported fields, precedence rules, and enum values; added examples of all three gateway roles (TRADER, MARKET_MAKER, ADMIN), per-symbol `mm_obligations` overrides, circuit-breaker level merging, and `seed_once` behaviour
- Expanded persistence user guide section with complete schema reference for `audit.log`, `clearing_report.csv`, and `stats.db` (DDL, column descriptions, example SQL queries)
- Added See Also footers to all user guide sections that lacked them
- Converted remaining ASCII diagrams to Mermaid in combo, auction/scheduling, drop-copy, and persistence sections
- Expanded PnL/clearing, gateway, and configuration sections with additional detail and worked examples

### 🛠 Internal
- Fixed black formatting violation in `config_loader.py`
- Made Exchange Intro PDF build optional in `mkbld.sh` behind a new `--intro` flag

## [v0.2.0] - 2026-06-14

Release Type: minor

### 📋 Summary
This release completes the protocol design documentation suite by publishing the BALF design proposal at v1.0.0 and integrating both BALF and CALF protocol appendixes into the User Guide. It marks the first minor version increment, establishing a stable baseline for the full protocol documentation set.

### 📚 Documentation
- Update glossary and sync global and Exchange Intro glossary

### ✨ Additions
- Added BALF protocol design proposal v1.0.0 covering allocation, liquidity, and feed mechanics
- Added BALF protocol description appendix to the User Guide
- Added CALF protocol appendix to the User Guide with harmonized terminology across all protocol appendixes

## [v0.1.9] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release expands the concept documentation with a new CALF market-data feed page, improves clarity across existing order-book pages, and reorganises the Glossary. GitHub Actions are also updated to be Node 24 compatible.

### 📚 Documentation
- Added new concept page explaining the CALF market-data protocol: channels, subscription flow, sequence-based gap detection, reconnect behaviour, and index dissemination
- Improved wording and corrected depth examples in the order book introduction
- Moved glossary terms from the order-book deep-dive page into the main Glossary section

### 🛠 Internal
- Updated GitHub Actions workflows and composite action to use Node 24 compatible action versions (`checkout@v5`, `setup-python@v6`, `cache@v5`)


## [v0.1.8] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release fixes chapter numbering in generated User Guide PDFs and cleans up related documentation build templates and Makefile flow.

### 🐛 Bug Fixes
- Fixed User Guide chapter numbering by switching LaTeX templates from front matter to main matter before chapter content
- Fixed incorrect imprint text in User Guide templates

### 🛠 Internal
- Cleaned up docs Makefile pipeline and template handling for PDF generation


## [v0.1.7] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release improves documentation usability by adding light and dark viewing modes for the doc-site

### 📚 Documentation
- Updated documentation theming to support both light and dark presentation modes
- Added repo link in doc eadings


## [v0.1.6] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release cleans up release artifact layout so Python distributions stay at the top level while documentation PDFs remain in their own build directories.

### 🛠 Internal
- Kept Python distribution artifacts in the top-level dist directory for publishing
- Kept documentation PDF builds in the docs dist directories to avoid mixing release assets
- Add PyPi publishing


## [v0.1.5] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release improves the release automation flow by fixing GitHub release script issues and tightening package validation behavior during publication.

### 🚀 Improvements
- Improved release packaging validation to only verify Python distribution artifacts with Twine

### 🐛 Bug Fixes
- Fixed GitHub release script behavior during release execution


## [v0.1.4] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release improves the documentation build and release workflow while expanding the market data and index design documentation set. It also streamlines artifact generation to reduce duplicate build work.

### 🚀 Improvements
- Improved build and release scripts to avoid duplicate artifact builds
- Improved documentation PDF pipeline by cleaning Markdown inputs before rendering
- Improved visual documentation by replacing an ASCII graph with a Mermaid diagram

### 📚 Documentation
- Added index calculation design documentation
- Updated CALF design proposal content
- Fixed README documentation site URL

### 🛠 Internal
- Updated User Guide LaTeX templates to include a cover page for book-style output


## [v0.1.3] - 2026-06-11

Release Type: patch

### 📋 Summary
This patch release fixes issues in the GitHub release automation flow and stabilizes post-release branch synchronization after v0.1.2.

### 🐛 Bug Fixes
- Fixed GitHub release script behavior for release creation flow

### 🛠 Internal
- Updated release branch synchronization after v0.1.2


## [v0.1.2] - 2026-06-11

Release Type: patch

### 📋 Summary
This patch release extends the release pipeline to build and bundle the Exchange Introduction document alongside the main package, producing a ZIP archive of all four PDF variants as a release asset.

### 🚀 Improvements
- Improved release build to include Exchange Intro PDF generation in parallel with the main docs build

### 🛠 Internal
- Added ZIP bundling of Exchange Intro PDFs into a single release asset archive
- Updated main build target to invoke the Exchange Intro build step


## [v0.1.1] - 2026-06-11

Release Type: patch

### 📋 Summary
This patch release hardens the first-time release workflow after the initial public launch. It focuses on branch initialization and merge-path clarity so releases from develop to main complete predictably.

### 🛠 Internal
- Improved release script messaging around preconditions for squash merges
- Updated release process checks to surface branch-state issues earlier


## [v0.1.0] - 2026-06-11

Release Type: minor

### 📋 Summary
This is the inaugural public release of EduMatcher, featuring a complete educational matching engine with all essential exchange functionality. Designed for educational purposes, the engine implements realistic order matching, market data, and session management while intentionally omitting authentication and authorization to focus on core exchange principles.

### ✨ Additions
- Added complete order matching engine supporting multiple order types and matching algorithms
- Added market data management and quote generation
- Added session and trading day management
- Added participant and instrument registry
- Added CLI for engine simulation and introspection
- Added MCP (Model Context Protocol) server for AI model integration
- Added comprehensive exchange architecture documentation
- Added Python API for programmatic access to matching engine

### 🚀 Improvements
- Optimized matching performance for high-volume order streams
- Implemented efficient message handling and session state tracking

### 📚 Documentation
- Added complete user guide and architecture documentation
- Added full introduction to principles of an Exchange
- Added glossary and exchange concepts reference
- Added quick-start examples and API reference
- Added integration guide for MCP server usage

### 🛠 Internal
- Established comprehensive test coverage for matching logic and order types
- Configured Poetry-based development environment with dev, docs, and MCP extras
- Set up CI/CD pipeline and automated testing
- Configured code quality checks (type checking, linting, formatting)
- Added build system for PDF documentation generation
