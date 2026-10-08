# Development Practice and Release Process

!!! note "Learning objectives"
    After reading this page you will understand:

    - How to set up a local Python development environment for EduMatcher
    - Which quality gates are expected before you commit or release
    - How the code base is structured and where to start reading it
    - Which helper scripts exist under `scripts/` and `tools/`, and when to use them
    - How to run a minimal exchange while developing
    - How to run deterministic verification and performance tests
    - How the current release workflow is intended to work
    - Which common developer mistakes are easy to avoid



##  What kind of project you are joining

EduMatcher is a **multi-process educational exchange**. It is not just a single
matching function or a toy order-book exercise. The repository contains:

- a matching engine
- interactive gateways
- market-data and monitoring processes
- persistence and reporting components
- developer tooling, benchmarks, and deterministic verification tools

That matters for development style. Most changes should be thought about at
three levels:

1. **Core matching logic** — order validation, book state, fills, session rules
2. **Process boundaries** — ZeroMQ topics, startup order, persistence, observers
3. **Documentation and operability** — can another developer understand, run, and verify the change?

If you are new to the code base, start by reading these pages in order:

1. [How an Exchange Works](../../../how-exchange-works.md)
2. [Running the Exchange](../../operator-guide/part-3-run/010-running-the-exchange.md)
3. [Architecture Overview](../part-1-architecture/010-architecture-overview.md)
4. [Verification](030-verification.md)



##  Development environment

### Recommended Python version

`pyproject.toml` requires Python `^3.13`, and the type-checking and formatting
configuration targets the same version — so **Python 3.13 is the development
target**, not merely the safest one. An earlier `^3.11` floor was raised; code
in the tree now uses 3.12+ syntax (PEP 701 nested f-strings, for one), so an
older interpreter fails at import rather than at runtime.

### Canonical setup

The project is **Poetry-first**. The most reliable setup path is:



```bash
# Clone the repo
git clone https://github.com/johan162/EduMatcher.git
cd EduMatcher

# Verify necessart environment
./scripts/verify_setup.sh

# Setup poetry && Python
poetry config virtualenvs.in-project true
poetry install --with dev,docs

# Verify that a full build (incl. documents) succeeds
./scripts/mkbld.sh --intro
```

Then activate the environment if you want shell-local tools:

```bash
source .venv/bin/activate
```

### Basic toolchain expectations

You should have these available locally:

| Tool | Why you need it |
|---|---|
| Python 3.13 | Matches the repo's linting and typing targets |
| Poetry | Dependency and virtualenv management |
| Git | Branching, release, and tag workflow |
| `gh` | Used by the GitHub release script |
| MkDocs | Installed through Poetry docs dependencies |

If you plan to use the containerised docs workflow, you also need **Podman**
for `scripts/docs-contctl.sh`.


##  Repository map

When you are orienting yourself, this is the practical top-level map:

| Path | What lives there | Typical reason to open it |
|---|---|---|
| `src/edumatcher/engine/` | Matching engine, config loading, persistence, risk logic | Core exchange behavior |
| `src/edumatcher/alf_gwy/`, `balf_gwy/` | Protocol gateways: ALF (text) and BALF (binary) order entry | Trader entry workflow |
| `src/edumatcher/alf_console/` | Interactive trader console and command parsing | Hands-on order entry, demos |
| `src/edumatcher/api_gateway/` | REST/WebSocket edge for the web GUIs | Browser-facing flows |
| `src/edumatcher/md_gateway/`, `dc_gateway/`, `ralf_gateway/` | Market-data (CALF), drop-copy and RALF relay gateways | Feed and post-trade consumers |
| `src/edumatcher/commands/` | Admin/console command clients and tooling | Operator workflows and scripted control |
| `src/edumatcher/messaging/` | Transport and message-bus helpers | Socket wiring and topic flow |
| `src/edumatcher/models/` | Shared message, order, and domain models | Data structures and message payloads |
| `src/edumatcher/clearing/` | P&L and trade-settlement logic | Post-trade reporting |
| `src/edumatcher/ai_trader/` | AI trader and swarm entry points | Agent-based flow and experiments |
| `src/edumatcher/viewer/`, `board/`, `ticker/`, `orders/`, `audit/`, `stats/` | Read-side processes and UIs | Operational visibility |
| `src/edumatcher/scheduler/` | Session transitions | Trading-day lifecycle |
| `src/edumatcher/setup_cmd.py` | `pm-setup` bootstrap command | Runtime setup for installed mode |
| `tests/` | Unit, integration, and performance tests | Regression protection |
| `tools/` | Verification utilities and launch helpers | Deterministic validation, scripted demos |
| `scripts/` | Build, release, docs, and maintenance helpers | Automation |
| `docs/` | User, architecture, concept, and developer documentation | Documentation updates |
| `docs-design/` | Design proposals and implementation plans | Architecture and feature design review |
| `release_checklist.md` | Canonical release checklist | Pre-release gate and release sequencing |

### Good first files to read

If you want to understand the runtime quickly, read:

1. `src/edumatcher/engine/main.py`
2. `src/edumatcher/engine/config_loader.py`
3. `src/edumatcher/alf_gwy/gateway.py` — the simplest gateway, and the one
   [Order flow](../part-2-inside-the-engine/020-order-flow-end-to-end.md) traces end to end
4. `src/edumatcher/models/message.py`
5. `tests/test_*` files closest to the area you plan to change

If you prefer a narrative to a file listing, read
[Order flow: from keystroke to resting order](../part-2-inside-the-engine/020-order-flow-end-to-end.md) first —
it walks one order through every file above in the order the code touches
them.

##  Development workflow expectations

### Default working style

For most changes, follow this loop:

1. Understand the existing behavior in code and tests
2. Make the smallest complete change that solves the problem
3. Run the narrowest relevant tests first
4. Run the standard quality gate before considering the work done
5. Update documentation if behavior, commands, or configuration changed

### Code quality gates

These are the checks a developer is expected to run regularly:

```bash
make check
make test
```

The Makefile provides wrappers if you prefer shorter commands:

```bash
make install     # install Python dependencies
make check       # run static lints
make test        # run all tests
make docs-site   # build documentation site 
make build       # build Python wheel
```

but the standard way to run all checks and a full build is the `mkbld.sh` script

```
./scripts/mkbld.sh
```


### Standards enforced by the repo

- **Formatting**: `black`, line length 88
- **Linting**: `flake8`
- **Typing**: `mypy` in strict mode
- **Testing**: `pytest`
- **Coverage gates**:
  - `make test` enforces **85%**
  - `scripts/mkbld.sh` currently enforces **80%** (release automation threshold)
- **Docs build**: `mkdocs build` should pass after doc changes
- **Shell completion**: every `[tool.poetry.scripts]` entry point must expose a
  module-level `build_parser() -> argparse.ArgumentParser` with no
  parameters and no side effects -- `main()` calls it too, so there is
  exactly one place each parser is defined. `tools/gen_completion.py` reads
  those factories to render `src/edumatcher/completion/pm-completion.{bash,zsh}`
  (shipped as package data, served by `pm-help --completion bash|zsh`);
  `tests/test_shell_completion.py` fails both if a command lacks the
  contract and if the committed scripts drift from what the factories
  currently produce. After adding a command or changing a flag, subcommand,
  `choices=` list or help text, run `make completion` and commit the
  result -- see [Installation → Shell completion](../../operator-guide/part-1-install-and-deploy/010-installation.md#shell-completion).

### What to preserve

This repository values:

- exact behavior over speculative abstraction
- deterministic tests over hand-wavy correctness
- documentation that matches the real code
- small, reviewable changes instead of large refactors

If you notice unrelated technical debt while doing a focused task, note it, but
do not silently expand the scope of your change.

##  Running a minimal system while developing

It is worth keeping a **small live system** available during development. Even
when unit tests pass, a real end-to-end run catches startup, wiring, and event
flow mistakes early.

This section covers a minimal system on the host. If you are working on one of
the web applications instead, the fastest loop is the exchange in containers
with the app running locally against it — see
[The Development Loop](020-development-workflow.md).

### Where your data directory actually is

Every process — `pm-engine`, `pm-setup`, `pm-config-deploy`, the test suite,
all of them — resolves one shared `DATA_DIR` (`edumatcher.config.DATA_DIR`)
and reads/writes everything under it: `ref_data/engine_config.yaml`,
the compiled `ref_data/engine_config.json`, `gtc_orders.json`, the audit and
stats databases, and so on. Which directory that is depends on how
EduMatcher is running, and mixing the two up is a common source of
"why doesn't my change do anything" / "why does pytest suddenly fail"
confusion:

| You are | `DATA_DIR` resolves to |
|---|---|
| Running from a source checkout (`poetry run ...`, or any test you run with `pytest`) | `<repo>/src/data/` — this is the **default in a dev environment** |
| Running an installed build (`pipx install edumatcher`, no source checkout) | `~/.local/share/edumatcher` |
| Either of the above, with `EDUMATCHER_DATA_DIR` set | Whatever that variable points at — always wins |

The detection is automatic and based on where `edumatcher/config.py` itself
lives on disk (inside a `src/` directory means "source checkout"), not on
how you invoke a command. So in this repository's normal poetry workflow,
`src/data/ref_data/engine_config.json` is **the** compiled artifact every
local process and every test that loads real config reads — there is no
separate "test data dir" or "dev data dir" to keep in sync.

**Customizing the location:** export `EDUMATCHER_DATA_DIR=/some/path` before
running any EduMatcher process; every process that reads `DATA_DIR` will
follow it consistently as long as the variable stays set for all of them
(e.g. in your shell profile, or in a `.env` a launcher script sources).
This is the same variable `pm-setup --data-dir` and the containerized
`edumatcher.sh` deployments use, so a single override applies everywhere.
See the `Runtime configuration` docstring at the top of
`src/edumatcher/config.py` for the full priority order, including the
host/container-split fallback to `./data` in the current directory.

**Why this matters for `pm-config-deploy` / `pm-setup`:** these compile a
source YAML into `<DATA_DIR>/ref_data/engine_config.json`, and every process
refuses to start against a stale or hand-edited copy of that file (it
verifies a content digest recorded at compile time). If you change something
about the compiled config's shape — add a field to `EngineConfig`, for
instance — an artifact compiled by older code will fail that check under the
new code with `ArtifactError: compiled config has been modified since it was
compiled`. That is not corruption; it means `src/data/ref_data/engine_config.json`
in your checkout needs recompiling: run `poetry run pm-config-deploy --example
<name>` (or `pm-setup --force`) again so it's rebuilt under the current code.
This is *exactly* the situation a full local `pytest` run will hit right
after pulling a change that touches the compiled config's shape — the
failures are pointing at `src/data/`, not at the test files.

The three config commands divide up as: **`pm-config-gen`** authors a fresh
`engine_config.yaml` from high-level CLI inputs (symbol count, gateways,
sessions) when you want a new scenario rather than an edit to an existing
one; **`pm-config-deploy`** compiles an authored YAML into the deployed
`ref_data/` artifacts; and **`pm-config-show`** prints what is actually
deployed, which is the one to reach for when the engine's behaviour and your
YAML appear to disagree.

### Minimal reference data

EduMatcher uses `engine_config.yaml` for reference data. A one-symbol minimal
configuration can look like this:

```yaml
participants:
  - id: TRADER01
    description: First trader
  - id: MM01
    description: Market maker
    role: MARKET_MAKER
  - id: GW_ADMIN
    description: Operator console
    role: ADMIN

symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 149.90
    last_sell_price: 150.10
    market_maker_quotes:
      - gateway_id: MM01
        bid_price: 149.90
        ask_price: 150.10
        bid_qty: 500
        ask_qty: 500
        tif: DAY
        quote_id: MM-AAPL-SEED
```

See [Configuration](../../operator-guide/part-2-configure/010-the-configuration-workflow.md) for the full schema.

### Recommended startup order

Start the engine first. All other processes depend on its sockets being bound.

#### Core background/exchange processes
```bash
# Terminal 1 - Start the log server
poetry run pm-log-srv 

# Terminal 2 — audit log
poetry run pm-audit --terminal

# Terminal 3 — matching engine
poetry run pm-engine --verbose

# Terminal 4 — optional scheduler
poetry run pm-scheduler --now

# Terminal 5 - Statistics
poetry run pm-stats

# Terminal 10 — clearing / P&L
poetry run pm-clearing
```

An easier way to start all basic exchange processes is to use the admin command `pm-opctl-cli` (OPerationall Control Client)

```
pm-opctl-cli start
```

to then check all processes are running

```
pm-opctl-cli list
```

and finally to stop all processes

```
pm-opctl-cli stop
```


#### Start obersvers

```bash
# Terminal 9 — live order book
poetry run pm-viewer --symbol AAPL

# Terminal 10 — live all symbol display
poetry run pm-board
```

#### Start interactive terminals

```bash
# Terminal 11 — Trader01 terminal
poetry run pm-alf-console --id TRADER01

# Terminal 12 — Trader02 terminal
poetry run pm-alf-console --id TRADER02

# Terminal 8 — operator console
poetry run pm-admin --id GW_ADMIN
```


### Inspecting a run after the fact

The processes above are the *live* view. Every store they write also has a
read-only query CLI, and reaching for one is almost always faster than
opening the SQLite file or grepping a log by hand:

| Command | Reads | Reach for it when |
|---|---|---|
| `pm-audit-cli` | `data/audit.log` (+ rotated `.gz`) | "what happened on the bus?" — filter by topic, gateway, symbol, time |
| `pm-stats-cli` | the stats database | OHLCV, trades, order events, order lifecycle, gaps |
| `pm-clearing-cli` | the clearing database | positions, P&L, and `reconcile` against the raw trade archive |
| `pm-log-cli` | `pm-log-srv` | operational logs from every process in one place |
| `pm-index-admin-cli` | `pm-index` | corporate actions, constituent changes, rebalances |

Three more that are easy to miss:

- **`pm-mm-bot`** — the market-maker bot. Start one before a demo and the
  book has resting liquidity to trade against; without it an AI-trader swarm
  produces a thin, jumpy book. See [AI bot traders](../../participant-guide/part-4-automated-trading/020-how-the-bots-decide.md).
- **`pm-dc-spy`**, **`pm-ralf-spy`**, **`pm-calf-spy`** — tail the drop-copy,
  RALF and CALF feeds without writing a subscriber. The fastest way to see
  whether a gateway is emitting what you think it is.
- **`pm-help`** (alias **`pm-man`**) — browses the documentation for any
  EduMatcher command from the terminal.

### Logging levels and pm-log-srv

Every `pm-*` process configures its own logging once at startup, in a
`_configure_logging(args)` function in that process's `main.py`. Three things
are decided there: the **level** (from `--log-level {CRITICAL,ERROR,WARNING,
INFO,DEBUG}`, or `-v`/`-vv`/`-q` if `--log-level` is not given — see the flag
table under [`pm-engine`](../../reference-manual/part-1-command-line/010-processes-environment-and-ports.md#pm-engine-matching-engine)
for the exact precedence, which is the same in every process), and the
**target** — where the resulting `LogRecord`s go, via `--log-target
{server,stdout,file}`. The default target, `server`, auto-detects a running
`pm-log-srv` with a LALF `HELLO`/`WELCOME` handshake and, if one answers,
attaches a `TcpLogHandler` as the process's *only* logging handler. That
handler ships every record — at whatever level the process was started
with — over TCP to `pm-log-srv`, so `log.debug(...)` calls throughout the
codebase reach the same centralized log you would otherwise read with
`pm-log-cli` or `log-gui`, with no separate wiring required.

This has two consequences worth knowing before you go looking for a way
around them:

- **There is no environment variable.** The level is a plain CLI argument,
  resolved once per process at startup. Nothing in this codebase reads a
  `LOG_LEVEL`-style variable.
- **The level cannot be changed on a running process.** `_configure_logging`
  runs once in `main()`, before the process's event loop starts, and nothing
  listens for `SIGHUP` or any other runtime toggle. To see `DEBUG` output
  from a process, restart it with `--log-level DEBUG` (or `-vv`). `pm-log-srv`
  itself does not need restarting — it is a passive collector — only the
  client process whose behaviour you are debugging does.

If you normally bring the stack up with `pm-opctl-cli` rather than starting
processes by hand, start (or restart) it with `-d`/`--debug` (alias `-vv`) to
apply `--log-level DEBUG` to every process in the profile at once:

```bash
pm-opctl-cli stop
pm-opctl-cli start -d
```

See [`pm-opctl-cli`](../../reference-manual/part-1-command-line/010-processes-environment-and-ports.md#pm-opctl-cli-operational-process-control)
for the full flag reference.

### macOS convenience launcher

For demos or quick manual runs on macOS, use:

```bash
./tools/launch_all.sh
./tools/launch_all.sh AAPL MSFT
```

`tools/launch_all.sh` opens one Terminal window per process using AppleScript.
It is convenient, but it is **macOS-only** and it launches the standard demo
layout, not a custom research topology.

### Quick signs the system is healthy

You should expect to see:

- engine startup banner with bound ports `5555`, `5556`, and `5557`
- successful gateway authentication
- a visible two-sided book in `pm-viewer` after `MM01` connects
- order acknowledgements and fills flowing back to the submitting gateway



##  Verification and test strategy

There are three different kinds of checks in this repository, and they answer
different questions.

###  Normal regression tests

Run these continuously while developing:

```bash
poetry run pytest -n auto tests/ -m "not perf"
```

or via the master Makefile

```bash
make test
```

These are the default correctness tests and should remain fast enough for
frequent reruns.

###  Deterministic engine verification

EduMatcher includes a dedicated replay-and-compare verification flow under
`tools/`. This is the right choice when you need confidence that the production
engine still agrees with the paper-trading oracle.

```bash
bash tools/verify_matching.sh
```

Useful variants:

```bash
bash tools/verify_matching.sh --seed 7
bash tools/verify_matching.sh --count 500
bash tools/verify_matching.sh --tolerance 0.01
```

Read [Verification](030-verification.md) before changing this flow. It explains
why deterministic replay is hard and how the repository avoids common traps such
as clocks, ACK ordering, and persisted GTC state.

###  Performance tests

Performance tests are intentionally separate from the normal CI path. They
measure engine behavior, not the full end-to-end network stack.

```bash
# Full perf run
poetry run pytest -o addopts='' tests/test_perf.py -v -s -m perf -p no:cov
# or
make test-perf

# Throughput-focused view
poetry run pytest -o addopts='' tests/test_perf.py -v -s -m perf -k max_tps -p no:cov

# Latency-focused view
poetry run pytest -o addopts='' tests/test_perf.py -v -s -m perf -k latency -p no:cov

# Normal test run without perf tests
poetry run pytest tests/ -m "not perf"
```

Important interpretation rule: the performance tests primarily measure **engine
processing cost**, not total production wire latency.

### When to run which check

| Situation | Minimum check |
|---|---|
| Small logic change in one module | Narrow tests for that area, then `pytest tests/ -m "not perf"` |
| Message schema or process wiring change | Normal tests + a live minimal-system run |
| Matching-engine algorithm change | Normal tests + `tools/verify_matching.sh` |
| Performance-sensitive hot-path change | Normal tests + performance tests |
| Documentation-only change | `poetry run mkdocs build` |



##  Helper scripts under `scripts/` and `tools/`

The repo includes useful helper scripts, but not all of them are equally
authoritative. In general:

- prefer **Poetry and Makefile commands** for day-to-day work
- use scripts for automation, release flow, or convenience wrappers
- read a script before trusting it in a new CI or release workflow

### Core scripts

| Script | Use it for | Notes |
|---|---|---|
| `scripts/mkbld.sh` | Full local build / validation pipeline | Runs lint/type/tests/build/docs; updates README version line; Exchange Intro PDF build is optional and requires `--intro` |
| `scripts/mkchlogentry.sh` | Create a new `CHANGELOG.md` release template | Intended before `mkrelease.sh` |
| `scripts/mkrelease.sh` | Local release workflow from `develop` | Requires `GITHUB_USER`, clean/synced `develop`, existing changelog entry for current `pyproject.toml` version, and already-built `dist/` artifacts |
| `scripts/mkghrelease.sh` | Publish the GitHub release from `main` | Requires `gh` auth, clean/synced `main`, latest `v*` tag, and release artifacts (wheel, sdist, user-guide bundle, Exchange Intro bundle) |
| `scripts/mkdocs.sh` | Serve, build, deploy, or clean MkDocs docs | Helpful for docs-only work |
| `scripts/mkcovupd.sh` | Update the README coverage badge from `coverage.xml` | Secondary helper; inspect output before committing |
| `scripts/verify_setup.sh` | Smoke-check a local environment | Contains some inherited naming; use with caution |
| `scripts/docs-contctl.sh` | Run docs in a Podman container | Useful when validating the containerised docs image |
| `tools/verify_matching.sh` | Deterministic engine verification | Strong confidence check for engine changes |
| `tools/launch_all.sh` | macOS demo/process launcher | Good for manual demos, not for production orchestration |
| `tools/gen_completion.py` | Regenerate bash/zsh shell completion for every `pm-*` command | Dev-only (imports `shtab`); run via `make completion` after changing a command's flags |


##  Documentation workflow

Developer-facing work is not finished until the docs still build cleanly.

### Fast documentation loop

```bash
poetry run mkdocs serve
```

### One-shot validation

```bash
poetry run mkdocs build
```

### What to update when behavior changes

If you change:

- **configuration semantics** → update `../../operator-guide/part-2-configure/010-the-configuration-workflow.md`
- **runtime commands or startup behavior** → update `../../operator-guide/part-3-run/010-running-the-exchange.md`
- **gateway commands** → update `../../participant-guide/part-2-orders/010-the-trader-console.md` (and `../../participant-guide/part-1-trading-basics/010-gateways-and-how-you-connect.md` for general gateway concepts)
- **message payloads or topics** → update `../../protocols-and-clients/part-5-message-reference/010-message-reference.md`
- **risk, MM quotes, persistence, or drop copy** → update the corresponding user-guide page
- **developer workflow** → update this page and related developer docs

This repository already has a lot of explanatory documentation. Reuse it rather
than duplicating large explanations in new pages.



##  Mermaid diagrams in the docs build (cached Pandoc filter)

The PDF docs pipeline (`docs/Makefile`, `docs-design/Makefile`,
`docs-exchange-intro/Makefile`) renders every ` ```mermaid ` code block to an
image via Pandoc's `--filter` mechanism. We use our **own** filter,
`scripts/mermaid-filter-cached.js`, instead of the stock `mermaid-filter` npm
package installed under `build-tools/node_modules/`.

### Why a custom filter

Rendering one diagram means launching `mmdc` (`@mermaid-js/mermaid-cli`),
which starts a full headless Chrome instance via Puppeteer — by far the
slowest step in a documentation build, repeated once per diagram, on every
single build, even though the diagrams themselves rarely change. Building all
four PDF variants (A4/B5, light/dark) in parallel (`make -j4`) multiplies
that cost further, since they share the same Markdown sources.

`scripts/mermaid-filter-cached.js` adds a render cache on top of the stock
filter's behavior: a diagram whose Mermaid source hasn't changed is reused
from disk instead of being re-rendered.

### Why it isn't just a patch to the installed package

`build-tools/` is entirely git-ignored and is wiped and recreated by
`npm install` on every fresh checkout (see the `$(NODE_MODULES_PATH):` targets
in the Makefiles). Editing
`build-tools/node_modules/.bin/mermaid-filter` (a symlink into
`build-tools/node_modules/mermaid-filter/index.js`) directly would be
silently lost the next time dependencies are (re)installed. The cached filter
therefore lives as a normal, version-controlled file under `scripts/`, and
each Makefile's `MERMAID_FILTER` variable points at it instead of the
npm-installed binary.

### How the cache works

- **Cache key**: sha256 of the raw Mermaid diagram text, truncated to 12 hex
  characters — independent of caption, filename, or which document the
  diagram appears in, so two identical diagrams anywhere share one render.
- **Cache location**: `build-tools/.mermaid-cache/<hash>.<format>` by
  default, overridable with `MERMAID_FILTER_CACHE_DIR`. This is deliberately
  **not** the per-build `.mermaid-img` directory the Makefiles pass via
  `MERMAID_FILTER_LOC` — that directory is `rm -rf`'d at the start of every
  PDF build, so anything cached there would never survive to be reused.
- **Cache hit**: `mmdc`/Puppeteer is skipped entirely; the previously
  rendered file is referenced directly from the cache.
- **Cache miss**: rendered via `mmdc` exactly as the stock filter does, then
  persisted into the cache using a write-to-temp-then-atomic-rename so that
  concurrent builds (the four `make -j4` PDF variants, which share diagrams)
  can never observe — or produce — a partially-written cache file.

Caveat: the cache key covers only the diagram text, not rendering options
(`MERMAID_FILTER_THEME`/`WIDTH`/`FORMAT`/`SCALE`/...). Changing one of those
globally does not invalidate previously cached renders. To force a full
re-render, delete `build-tools/.mermaid-cache/` (or point
`MERMAID_FILTER_CACHE_DIR` somewhere fresh).



