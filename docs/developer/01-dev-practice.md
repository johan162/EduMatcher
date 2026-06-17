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

1. [How an Exchange Works](../how-exchange-works.md)
2. [Running the Exchange](../user-guide/03-running-the-engine.md)
3. [Architecture Overview](../architecture/01-architecture.md)
4. [Verification](04-verification.md)



##  Development environment

### Recommended Python version

`pyproject.toml` currently allows Python `^3.11`, but the type-checking and
formatting configuration targets **Python 3.13**. In practice, **Python 3.13 is
the safest development target** because it matches the repo's strict-analysis
configuration.

### Canonical setup

The project is **Poetry-first**. The most reliable setup path is:

```bash
poetry config virtualenvs.in-project true
poetry install --with dev,docs
```

Then activate the environment if you want shell-local tools:

```bash
source .venv/bin/activate
```

### Optional helper script

The repository also contains `scripts/verify_setup.sh`. It is useful as a
smoke-check helper, especially on a fresh machine, but it still contains some
older inherited messages and command names from a previous project. Treat the
**Poetry commands above as the source of truth**, and use the script as a
convenience wrapper rather than as the canonical definition of the environment.

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
| `src/edumatcher/gateway/` | Interactive gateway and command parsing | Trader entry workflow |
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
3. `src/edumatcher/gateway/main.py`
4. `src/edumatcher/models/message.py`
5. `tests/test_*` files closest to the area you plan to change



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
poetry run black --check src tests
poetry run flake8 src tests
poetry run mypy src tests
poetry run pytest tests/ -m "not perf"
poetry run mkdocs build
```

The Makefile provides wrappers if you prefer shorter commands:

```bash
make install
make check
make test
make docs
make build
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

### Minimal reference data

EduMatcher uses `engine_config.yaml` for reference data. A one-symbol minimal
configuration can look like this:

```yaml
gateways:
  alf:
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

See [Configuration](../user-guide/01-configuration.md) for the full schema.

### Recommended startup order

Start the engine first. All other processes depend on its sockets being bound.

```bash
# Terminal 1 — matching engine
poetry run pm-engine --verbose

# Terminal 2 — optional scheduler
poetry run pm-scheduler --now

# Terminal 3 — market maker gateway
poetry run pm-gateway --id MM01

# Terminal 4 — trader gateway
poetry run pm-gateway --id TRADER01

# Terminal 5 — operator console
poetry run pm-admin --id GW_ADMIN

# Terminal 6 — live order book
poetry run pm-viewer --symbol AAPL

# Terminal 7 — audit log
poetry run pm-audit --terminal

# Terminal 8 — clearing / P&L
poetry run pm-clearing
```

Optional observers you will often add:

```bash
poetry run pm-orders
poetry run pm-stats
poetry run pm-ticker --interval 15
poetry run pm-board
```

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
poetry run pytest tests/ -m "not perf"
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

Read [Verification](04-verification.md) before changing this flow. It explains
why deterministic replay is hard and how the repository avoids common traps such
as clocks, ACK ordering, and persisted GTC state.

###  Performance tests

Performance tests are intentionally separate from the normal CI path. They
measure engine behavior, not the full end-to-end network stack.

```bash
# Full perf run
poetry run pytest -o addopts='' tests/test_perf.py -v -s -m perf -p no:cov

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

### A practical rule of thumb

If a script's behavior disagrees with `pyproject.toml`, `Makefile`, or the
current docs, trust the **project configuration and live code first**. Several
scripts and script help texts still show traces of an older project name, so a
developer should read them critically rather than assuming every string is up to
date.



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

- **configuration semantics** → update `docs/user-guide/01-configuration.md`
- **runtime commands or startup behavior** → update `docs/user-guide/03-running-the-engine.md`
- **gateway commands** → update `docs/user-guide/08-gateway.md`
- **message payloads or topics** → update `docs/user-guide/09-messages.md`
- **risk, MM quotes, persistence, or drop copy** → update the corresponding user-guide page
- **developer workflow** → update this page and related developer docs

This repository already has a lot of explanatory documentation. Reuse it rather
than duplicating large explanations in new pages.



##  Current release workflow

Follow `release_checklist.md` as the source of truth.
The practical flow below is aligned with the current script behavior.

### Release checklist

1. Bump the `pyproject.toml` version  
    ```sh
    poetry version <NEW VERSION>  
    ```

2. Add a new `CHANGELOGENTRY.md`. Use the `/changelog` skill to create a draft version based on the git-logs

3. Run the complete build script `scripts/mkbld.sh` and fix any potential issues until it runs clean.

4. Check in all modified files, some versions (e.g. README.md) have been bumped by the `mkbld.sh` script. Make sure the `develop`  branch is clean.

5. Run the release script `script/mkrelease <RELEASE-TYPE>` to handle merge into `main` and verify that all things are in place. Fix potential isssues until it runs clean. This will also trigger GitHub actions like publishing the `gh-pages` to the doc-site.

6. Make the GitHub release with `scripts/mkghrelease.sh` 


The intended release flow is:

1. Bump version and prepare changelog
2. Build and validate all release artifacts
3. Run scripted release from `develop`
4. Verify CI on `main`
5. Create GitHub release from latest tag on `main`

### Step-by-step

```bash
# 1. Bump version in pyproject.toml
poetry version 0.3.2

# 2. Create the changelog template (release type is major|minor|patch)
./scripts/mkchlogentry.sh 0.3.2 patch

# 3. Edit CHANGELOG.md and replace placeholder bullets

# 4. Build and validate release artifacts.
# Use --intro for real releases because mkghrelease.sh expects the intro bundle.
./scripts/mkbld.sh --intro

# 5. Commit release-ready changes on develop, then preview release actions
GITHUB_USER=<your-gh-user> ./scripts/mkrelease.sh patch --dry-run

# 6. Execute the local release flow (squash merge develop -> main, tag, push, sync back)
GITHUB_USER=<your-gh-user> ./scripts/mkrelease.sh patch

# 7. After CI is green on main, create the GitHub release from main
git switch main && git pull --ff-only
./scripts/mkghrelease.sh
```

### What `mkrelease.sh` expects

The script is designed around this model:

- `GITHUB_USER` environment variable is set
- you are on a **clean `develop` branch**
- local `develop` is synced with remote
- the requested version is not already tagged
- `CHANGELOG.md` already contains an entry for that version
- release artifacts already exist in `dist/` and pass `twine check`

Important usage detail: `mkrelease.sh` argument is only the release type
(`major`, `minor`, or `patch`). The version is read from `pyproject.toml`.

During execution, `mkrelease.sh` will:

1. validate repo state and changelog/version/tag preconditions
2. squash-merge `develop` into `main` and create `v<version>` tag
3. push `main` and the tag
4. merge `main` back into `develop` and push `develop`
5. wait for GitHub Actions completion with `gh run watch --exit-status`

### What `mkghrelease.sh` expects

The script is designed around this model:

- `GITHUB_USER` environment variable is set
- authenticated `gh` CLI on PATH
- you are on a **clean `main` branch** synced with remote
- latest release tag already exists on `main`
- required artifacts exist:
  - wheel in `dist/`
  - sdist in `dist/`
  - user-guide bundle in `docs/dist/`
  - exchange-intro bundle in `docs-exchange-intro/dist/`

It auto-detects pre-releases from tags ending in `rcN` (or you can force with
`--pre-release`) and creates the GitHub release using notes extracted from
`CHANGELOG.md`.

### What `mkbld.sh` currently does

`mkbld.sh` is the build gate before release scripts. It currently:

1. validates environment and required Poetry tools
2. runs `black`, `flake8`, `mypy` (and `pyright` if available)
3. runs tests with coverage threshold **80%**
4. updates coverage badge when `coverage.xml` changed
5. builds and verifies Python packages
6. builds user-guide PDF bundle and HTML docs
7. optionally builds Exchange Intro bundle when `--intro` is provided

For release publishing, prefer running `./scripts/mkbld.sh --intro`.

### Release caution

Some release scripts still contain inherited project-name strings and old help
references. Always sanity-check:

- version number
- package name in `pyproject.toml`
- changelog entry content
- branch and tag targets
- contents of `dist/`

before pushing a real release.



##  Common pitfalls for new developers

### Starting clients before the engine

Most processes assume the engine sockets already exist. Start `pm-engine` first.

### Using a gateway ID that is not in `engine_config.yaml`

`pm-gateway --id SOMEONE` only works if that gateway is configured.

### Forgetting that observer processes depend on each other

`pm-ticker` and `pm-board` rely on statistics written by `pm-stats`.

### Assuming docs-only changes need no validation

They still need:

```bash
poetry run mkdocs build
```

### Treating helper scripts as canonical truth

Some scripts are polished automation; others still show drift from earlier repo
history. Read before relying on them.

### Ignoring end-to-end behavior

A change that passes unit tests can still break:

- startup order
- message topics
- gateway acknowledgements
- persistence restore
- UI observers

That is why a minimal live run is worth doing.



##  Suggested first-week path for a new developer

If you are onboarding, this is a good sequence:

1. Set up Poetry and build the docs
2. Run the minimal live system once
3. Submit a few manual orders through `pm-gateway`
4. Run the normal test suite
5. Read the deterministic verification page
6. Pick one small bug fix or documentation improvement
7. Run the full quality gate before opening a PR

That path teaches both the **theory** and the **operational shape** of the
system before you attempt deeper engine work.
