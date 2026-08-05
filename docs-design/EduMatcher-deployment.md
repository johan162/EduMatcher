Version: 2.0.0

Date: 2026-08-05

Status: Design and Research Proposal

# EduMatcher Deployment Strategy Proposal

## 1. Purpose

This proposal defines a practical deployment strategy for the full EduMatcher
system that is as painless as possible for operators and instructors.

The strategy covers:

- Packaging boundaries (what ships together, what ships separately)
- VM + container layering
- A first-party Compose experience
- Packaging policy for the ALF TCP example client
- Release artifacts and upgrade path

The core goal is a predictable "download, configure, start, operate" flow with
minimal manual wiring.

**What v2.0.0 adds.** v1.0.0 established the strategy. This revision adds the
technical design needed to actually build it: the deployment unit and why it is
not what you might expect (§5), a complete port and address map including two
collisions that exist today (§6), the start-ordering graph and what breaks when
it is violated (§7), the supervision trade-off (§8), the full `deploy/` bundle
with every script written out (§9–§14), release-artifact construction (§15),
upgrade and rollback (§16), and an acceptance matrix per phase (§20).

!!! note "Nothing here is implemented yet"
    Every path, script and file in §9 onward is a *specification*. None of it
    exists in the repository at the time of writing. Facts about the *current*
    system — ports, entry points, `vm/` behaviour, the config pipeline — are
    marked **(current)** and were read from the source, not assumed.


## 2. Problem Statement

Today EduMatcher has strong runtime components, but packaging is split:

- The Python runtime (`pm-*`) is installable and usable.
- VM bootstrap scripts exist in `vm/`, but need refresh to current release shape.
- Browser UIs (`terminal-gui`, `log-gui`, `config-gui`) are not delivered as one
  cohesive operator deployment experience.
- There is no single, official orchestrator that starts the whole system in one
  command for common scenarios.

For an end user, this creates too many integration decisions too early.

Three concrete symptoms, verified against the current tree:

1. **40 console entry points, no start order.** `pyproject.toml` declares 40
   `pm-*` commands. Nothing states which are long-running services, which are
   one-shot tools, or in what order the services must start.
2. **Two port collisions in a full-stack deployment** (§6.3). They cannot
   surface until someone runs every plane at once, which nobody has yet.
3. **A deploy step exists but is undocumented as a deployment step.**
   `pm-config-deploy` **(current)** is already the compile-and-install boundary,
   and it is more load-bearing than the draft implied — see §5.


## 3. Design Principles

1. One obvious path: provide a default deployment path that works for most users.
2. Layered complexity: start simple, then add optional services.
3. Explicit boundaries: separate core exchange runtime from optional UIs.
4. Immutable release units: versioned images and pinned Compose bundles.
5. Config-first operations: deploy one compiled config artifact, then start services.
6. Reproducible upgrades: no snowflake host state.
7. **Fail before starting, not after.** Every precondition that can be checked
   without side effects is checked by a preflight step that changes nothing
   (§11). A stack that refuses to start with a reason is better than one that
   starts and is subtly wrong.
8. **The deployment is data-first.** Container images are replaceable; the data
   directory is not. Backup and restore are part of the deployment design, not
   an afterthought (§13).


## 4. Recommended Partitioning

Partition the system into 4 deployable planes.

### 4.1 Core Exchange Plane (mandatory)

Python processes that define market behavior and persistent market records:

| Process | Role | Persistent state owned |
|---|---|---|
| `pm-engine` | Matching engine; binds the venue's ZMQ sockets | `gtc_orders.json`, `gtc_combos.json`, `book_stats.json` |
| `pm-audit` | Audit recorder | `audit.log`, `audit_index.db` |
| `pm-clearing` | Position/P&L recorder | `clearing.db`, `clearing_report.csv` |
| `pm-stats` | Market statistics recorder | `stats.db` |
| `pm-scheduler` | Session state machine (when sessions enabled) | none |
| `pm-index` | Index calculation (when indices configured) | none |

This plane is the operational heart. It should be startable with zero Node
runtime dependencies.

**All state paths above are `DATA_DIR`-relative and are not individually
configurable** **(current)** — see §5.

### 4.2 Access Plane (optional but common)

External protocol and API gateways:

| Process | Protocol | Default port **(current)** |
|---|---|---|
| `pm-md-gwy` | CALF market data | 5570 |
| `pm-api-gwy` | REST/WebSocket | 8080 |
| `pm-alf-gwy` | ALF text order entry | 5565 |
| `pm-balf-gwy` | BALF binary order entry | 5560 |
| `pm-ralf-gwy` | RALF post-trade | 5580 |
| `pm-dc-gwy` | Drop copy | 5590 |

This plane is enabled per integration need.

### 4.3 UX Plane (optional)

Operator/viewer UIs with their own bridge services:

| Application | Bridge port **(current)** | Upstream it needs |
|---|---|---|
| TapeDeck (`terminal-gui`) | 8090 | CALF 5570, log-srv 5600 |
| Log Operator Console (`log-gui`) | 8091 | LALF-PS 5601/5602, `log.db` |
| Config GUI (`config-gui`) | 8080 | none at runtime |

These should ship as prebuilt container images and never require the operator
to run npm locally.

### 4.4 Operations Plane (recommended)

Cross-cutting operational services:

- `pm-log-srv` — LALF collector on 5600, LALF-PS on 5601/5602
- `pm-log-cli` workflows — query, `diagnose`, `prune`
- backup/export tasks for `EDUMATCHER_DATA_DIR` (§13)

### 4.5 What is *not* a plane

Deliberately excluded from any deployment profile, because they are interactive
tools an operator runs by hand rather than services:

`pm-admin`, `pm-admin-cli`, `pm-alf-console`, `pm-viewer`, `pm-board`,
`pm-orders`, `pm-ticker`, `pm-calf-spy`, `pm-ralf-spy`, `pm-dc-spy`,
`pm-audit-cli`, `pm-clearing-cli`, `pm-stats-cli`, `pm-index-cli`,
`pm-index-admin-cli`, `pm-cverifier`, `pm-config-gen`, `pm-setup`.

Simulation drivers — `pm-ai-trader`, `pm-ai-swarm`, `pm-mm-bot` — are services
but belong to a *scenario*, not to a deployment. They get an optional `sim`
profile (§17) so a classroom demo can start them, and no supported deployment
requires them.


## 5. The deployment unit

This section is new in v2.0.0 and is the most important design constraint,
because it is not what a container-shaped intuition would predict.

### 5.1 One data directory is one exchange instance

**(current)** `src/edumatcher/config.py` resolves `DATA_DIR` once:

```
EDUMATCHER_DATA_DIR   (if set)
  → <repo>/src/data   (if running from a source checkout)
  → ~/.local/share/edumatcher
```

Everything else is derived from it and **cannot be overridden individually**:
`stats.db`, `clearing.db`, `audit.log`, `audit_index.db`, `log.db`,
`gtc_orders.json`, `book_stats.json`, `logs/`, and `ref_data/`.

The source comment is explicit that this is deliberate: a per-process `--config`
flag used to exist, and it failed quietly — `pm-md-gwy` would start with an
empty symbol universe and look healthy while the engine ran ten symbols.

**Deployment consequence:** `EDUMATCHER_DATA_DIR` is the single variable that
defines which exchange a process belongs to. Two processes with different values
are two exchanges that cannot see each other, and nothing will say so. Every
script in this design therefore sets it exactly once, in one place, and every
container mounts the same host path.

### 5.2 Configuration is compiled, not mounted

**(current)** `pm-config-deploy` validates an authored `engine_config.yaml`,
resolves every default once, and installs a compiled artifact:

```
<DATA_DIR>/ref_data/engine_config.json    ← what every process reads
<DATA_DIR>/ref_data/engine_config.yaml    ← the source it was built from
```

**No process accepts a config path.** This is a stronger guarantee than most
deployments have, and it inverts the usual Compose pattern: you do **not** mount
a config file into each service. You run one compile step against the shared
data directory, and every service picks it up.

```mermaid
flowchart LR
    AUTHORED["engine_config.yaml<br/>(version control)"]
    AUTHORED -->|"pm-config-deploy"| VALIDATE{"4-layer<br/>validation"}
    VALIDATE -->|"fails"| STOP["nothing installed<br/>exit non-zero"]
    VALIDATE -->|"passes"| COMPILED[("DATA_DIR/ref_data/<br/>engine_config.json")]
    COMPILED --> ENGINE["pm-engine"]
    COMPILED --> GWY["every gateway"]
    COMPILED --> REC["every recorder"]
```

**Deployment consequence:** config deployment is a *distinct, ordered phase*
before any service starts, and it is the only phase that can reject a rollout.
`deploy-up.sh` (§11) runs it first and aborts on failure.

### 5.3 What this means for the container boundary

A containerised Python plane must therefore:

- share one host directory as `EDUMATCHER_DATA_DIR` across every core and
  access container — not a per-service volume;
- run `pm-config-deploy` as a one-shot init container against that same volume,
  before any service container starts;
- never bake configuration into an image.

That is a strong argument for the hybrid model (§13 of v1.0.0, retained): the
data directory is shared mutable state, which containers make more awkward
rather than less.


## 6. Port and address map

### 6.1 Complete map (current defaults)

| Port | Bound by | Protocol | Direction | Plane |
|---|---|---|---|---|
| 5555 | `pm-engine` | ZMQ PULL | inbound from gateways | Core |
| 5556 | `pm-engine` | ZMQ PUB | outbound to everything | Core |
| 5557 | `pm-engine` | ZMQ PUB | drop copy | Core |
| 5558 | `pm-index` | ZMQ PUB | index levels | Core |
| 5559 | `pm-index` | ZMQ PULL | index control | Core |
| 5560 | `pm-balf-gwy` | BALF/TCP | external clients | Access |
| 5565 | `pm-alf-gwy` | ALF/TCP | external clients | Access |
| 5570 | `pm-md-gwy` | CALF/TCP | external clients | Access |
| 5580 | `pm-ralf-gwy` | RALF/TCP | external clients | Access |
| 5590 | `pm-dc-gwy` | DC/TCP | external clients | Access |
| 5600 | `pm-log-srv` | LALF/TCP | inbound from every `pm-*` | Ops |
| 5601 | `pm-log-srv` | ZMQ PUB | LALF-PS to viewers | Ops |
| 5602 | `pm-log-srv` | ZMQ PULL | LALF-PS control | Ops |
| 8080 | `pm-api-gwy` | HTTP/WS | external clients | Access |
| 8080 | `config-gui` | HTTP | operator browser | UX |
| 8090 | `terminal-gui` bridge | HTTP/WS | operator browser | UX |
| 8091 | `log-gui` bridge | HTTP/WS | operator browser | UX |

### 6.2 Reserved ranges

The design reserves, and the `.env.example` documents:

| Range | Purpose |
|---|---|
| 5555–5559 | Internal ZMQ. **Never published outside the host.** |
| 5560–5599 | External TCP protocol gateways |
| 5600–5602 | Logging subsystem |
| 8080–8099 | HTTP services |

### 6.3 Two collisions that exist today

Both are latent — they only bite when planes are combined, which no current
workflow does.

**Collision 1 — `pm-api-gwy` and `config-gui` both default to 8080.**
Profile C (§17) runs both. Whichever binds second fails.

*Resolution:* move `config-gui` to **8092**, keeping the 8090–8092 block for
browser UIs and leaving 8080 to the API gateway, which is the one an external
client is likely to have hard-coded. `.env.example` sets `CONFIG_GUI_PORT=8092`
and the Compose bundle publishes that. This is a deployment-level fix; the
container's internal port need not change.

**Collision 2 — `pm-api-gwy` defaults to `host = "0.0.0.0"`.**
**(current)** `api_gateway/config.py` defaults the bind host to all interfaces,
which contradicts §18's "bind to localhost by default unless explicitly opened".
On a laptop on a conference network this publishes an unauthenticated-by-default
trading API to the LAN.

*Resolution:* the deployment bundle sets `API_GWY_HOST=127.0.0.1` in
`.env.example` and Compose publishes as `127.0.0.1:8080:8080`. Preflight (§11)
warns when any `*_HOST` is `0.0.0.0` and `PROFILE` is not explicitly
`public`. **Changing the code default is out of scope for this document** but is
recommended separately.

!!! warning "The UI plane has no authentication"
    `log-gui` and `terminal-gui` have no login (see
    `docs/user-guide/285-log-srv-gui.md` §Security notes). They must never be
    published beyond loopback or a trusted interface without a reverse proxy in
    front. The Compose bundle binds them to `127.0.0.1` and requires an explicit
    opt-in to do otherwise.


## 7. Start ordering

### 7.1 The dependency graph

```mermaid
flowchart TD
    CFG["pm-config-deploy<br/>(one-shot, must succeed)"] --> LOG["pm-log-srv"]
    CFG --> ENGINE["pm-engine"]
    LOG -.->|"logging only"| ENGINE
    ENGINE --> AUDIT["pm-audit"]
    ENGINE --> CLEAR["pm-clearing"]
    ENGINE --> STATS["pm-stats"]
    ENGINE --> INDEX["pm-index"]
    ENGINE --> SCHED["pm-scheduler"]
    ENGINE --> GWY["access plane<br/>(alf/balf/md/ralf/dc/api)"]
    INDEX --> GWY
    GWY --> TD["terminal-gui bridge"]
    LOG --> LG["log-gui bridge"]
```

### 7.2 What actually breaks when order is violated

Ordering here is not cosmetic. Three cases with different failure modes:

| Violation | Failure mode | Detectable? |
|---|---|---|
| Gateway starts before `pm-engine` | `make_pusher` sets `IMMEDIATE=1`, so sends raise `zmq.Again` until the engine binds. ALF returns `ENGINE_UNAVAILABLE`; the API gateway now returns 503. | Yes — clean error |
| Recorder starts after `pm-engine` has already published | ZMQ PUB drops messages with no connected subscriber. Events between engine bind and recorder connect are **lost silently**. | **No** — this is the dangerous one |
| Any process starts before `pm-config-deploy` | Reads a missing or stale `engine_config.json` | Partially — stale is silent |

The second case is why recorders must be *up and subscribed* before the engine
starts accepting orders, not merely started at the same time. Two mitigations,
both specified here:

- **Ordering with a settle delay.** Start recorders, wait for their subscription
  to establish, then start the engine. Crude but effective; ZMQ offers no
  "subscription established" signal to the publisher.
- **Gap detection after the fact.** The statistics module already carries
  per-topic sequence numbers and `pm-stats-cli gaps` (see
  `docs/user-guide/140-statistics-and-reporting.md`). The post-start health
  check (§12) queries it, so a startup race that did lose events is *reported*
  rather than assumed away.

This is the honest position: startup ordering reduces the window, sequence gaps
detect when it was not reduced enough. Neither alone is sufficient.

### 7.3 Shutdown order

Reverse of startup, with one addition: `pm-engine` must be stopped with
`SIGTERM` and given time to complete `_shutdown()`, which is what persists the
resting GTC book. `SIGKILL` loses up to `_PERSIST_INTERVAL_SEC` (5 s) of book
state — bounded, but avoidable. Compose `stop_grace_period` is set to 30 s for
the engine and 10 s elsewhere.


## 8. Supervision: three options, decision deferred

The draft's §5.2 places the Python plane directly in the VM. That leaves open
what supervises ~12 long-running processes. This section presents the options
rather than committing, per the open decision in §21.

### 8.1 Option A — systemd units

One templated unit per service, plus a target for ordering.

```ini
# /etc/systemd/system/edumatcher-engine.service
[Unit]
Description=EduMatcher matching engine
After=network-online.target edumatcher-config.service
Requires=edumatcher-config.service
PartOf=edumatcher.target

[Service]
Type=simple
User=edumatcher
Environment=EDUMATCHER_DATA_DIR=/var/lib/edumatcher
ExecStart=/usr/local/bin/pm-engine
Restart=on-failure
RestartSec=2
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=edumatcher.target
```

```ini
# /etc/systemd/system/edumatcher-config.service — the compile gate
[Unit]
Description=EduMatcher configuration deploy
Before=edumatcher-engine.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=edumatcher
Environment=EDUMATCHER_DATA_DIR=/var/lib/edumatcher
ExecStart=/usr/local/bin/pm-config-deploy /etc/edumatcher/engine_config.yaml
```

**For:** restart policy, boot ordering, journald, `systemctl status` — all free
and all familiar. `Requires=` on the config unit makes §5.2's ordering
constraint structural: the engine cannot start if the compile failed.

**Against:** requires root; ties the design to systemd hosts; unit files are a
second place where `EDUMATCHER_DATA_DIR` is set, so §5.1's single-value
invariant needs enforcing across ~12 files (mitigated with
`EnvironmentFile=/etc/edumatcher/edumatcher.env`).

### 8.2 Option B — Compose for everything

Containerise the Python plane too, so one orchestrator covers all four planes.

**For:** one runtime model; `depends_on` with `condition: service_healthy`
expresses §7 directly; identical on laptop and server.

**Against:** contradicts v1.0.0's §13 decision. The shared-mutable-`DATA_DIR`
constraint (§5.3) makes containers *more* awkward here, not less — every core
and access container mounts the same read-write host directory, which is the
pattern containers are worst at. Also requires publishing core images, an open
decision (§21.1).

### 8.3 Option C — supervisor script

A `pm-stack` wrapper managing PIDs in `$DATA_DIR/run/`.

**For:** no root, no daemon, trivially portable, easy to read.

**Against:** no restart-on-failure, no boot ordering, and PID-file supervision
is a well-known source of stale-lock bugs. Adequate for a laptop demo, not for
anything left running.

### 8.4 Assessment

Option A is the strongest for the hybrid model this document recommends, and
Option C is a reasonable *additional* convenience for laptop use — they are not
mutually exclusive. Option B is coherent but is really a different deployment
model, and adopting it means revisiting §5.3 rather than just §8.

**This decision is deliberately left open** (§21.5). The `deploy/` bundle below
is written so that the Compose portion is independent of it: the UX plane always
runs under Compose, and §11's scripts drive whichever supervisor is chosen
through a single `stack_start`/`stack_stop` indirection.


## 9. The `deploy/` bundle

### 9.1 Layout

```
deploy/
├── README.md                     operator quick start
├── Makefile                      the only interface most operators need
├── .env.example                  every variable, documented, safe defaults
├── compose.yaml                  UX + ops plane; core/access if profile B
├── compose.core.yaml             overlay: containerised Python plane (opt-in)
├── compose.sim.yaml              overlay: ai-traders / mm-bot for demos
├── profiles/
│   ├── classroom-minimal.env     Profile A
│   ├── integration-lab.env       Profile B
│   └── operator-full.env         Profile C
├── config/
│   └── engine_config.example.yaml
├── systemd/
│   ├── edumatcher.target
│   ├── edumatcher-config.service
│   └── edumatcher@.service       templated unit (Option A)
└── scripts/
    ├── lib.sh                    shared helpers, sourced by all
    ├── preflight.sh              checks only, changes nothing
    ├── deploy-up.sh              the one command
    ├── deploy-down.sh
    ├── healthcheck.sh            post-start verification
    ├── backup.sh                 consistent DATA_DIR snapshot
    ├── restore.sh
    └── offline-bundle.sh         build the air-gapped tarball
```

### 9.2 Why a `Makefile` and scripts rather than Compose alone

Three things Compose cannot express and this system needs:

1. The config compile gate (§5.2) must run and *succeed* before anything starts.
2. Preflight checks that are host-level, not container-level — port
   availability, data directory writability, clock sanity.
3. Post-start verification that queries the running system (§12), including the
   sequence-gap check that detects the §7.2 startup race.


## 10. `.env.example`

```bash
# ===========================================================================
# EduMatcher deployment configuration
#
# Copy to .env and edit. Every value here has a safe default; the ones you are
# most likely to change are marked ★.
#
# One rule dominates this file: EDUMATCHER_DATA_DIR defines *which exchange*
# a process belongs to. Two processes with different values are two separate
# exchanges, and nothing will warn you. Set it once, here, and never per-service.
# ===========================================================================

# --- Identity and release ---------------------------------------------------
★ EDUMATCHER_VERSION=0.8.0          # pinned; images and wheel share this tag
★ EDUMATCHER_DATA_DIR=/var/lib/edumatcher
COMPOSE_PROJECT_NAME=edumatcher

# --- Authored configuration -------------------------------------------------
# Source of truth, kept under version control. Compiled by pm-config-deploy
# into $EDUMATCHER_DATA_DIR/ref_data/engine_config.json before anything starts.
★ ENGINE_CONFIG_SRC=./config/engine_config.yaml

# --- Profile ----------------------------------------------------------------
# core | core,access | core,access,ui | core,access,ui,ops   (+ ,sim)
★ COMPOSE_PROFILES=core,access,ui,ops

# --- Bind policy ------------------------------------------------------------
# BIND_ADDR is the interface every published port binds to. 127.0.0.1 means
# "this host only". Changing it exposes services that have NO AUTHENTICATION
# (the log and terminal UIs) — read §18 before you do.
★ BIND_ADDR=127.0.0.1
# Set to "public" only if you have read §18 and accept the exposure. Preflight
# refuses BIND_ADDR != 127.0.0.1 unless this is set.
EXPOSURE_ACKNOWLEDGED=

# --- Core plane (internal ZMQ — never published off-host) -------------------
ENGINE_PULL_PORT=5555
ENGINE_PUB_PORT=5556
DROP_COPY_PUB_PORT=5557
INDEX_PUB_PORT=5558
INDEX_PULL_PORT=5559

# --- Access plane -----------------------------------------------------------
BALF_PORT=5560
ALF_PORT=5565
CALF_PORT=5570
RALF_PORT=5580
DC_PORT=5590
API_GWY_PORT=8080
# The code default is 0.0.0.0 — see §6.3 collision 2. We override it.
API_GWY_HOST=127.0.0.1

# --- Operations plane -------------------------------------------------------
LOG_SRV_PORT=5600
LOG_SRV_PUB_PORT=5601
LOG_SRV_PULL_PORT=5602

# --- UX plane ---------------------------------------------------------------
TERMINAL_GUI_PORT=8090
LOG_GUI_PORT=8091
# 8092, not 8080: pm-api-gwy owns 8080. See §6.3 collision 1.
CONFIG_GUI_PORT=8092

# --- log-gui tuning (see docs/user-guide/285-log-srv-gui.md) ----------------
ISSUES_MIN_LEVEL=WARNING
ISSUES_ALERT_LEVEL=ERROR
ISSUES_RETENTION_DAYS=7
PROCESS_SILENCE_SEC=30
ERROR_RATE_NORMAL_PER_MIN=5
ERROR_RATE_ELEVATED_PER_MIN=20
ERROR_RATE_SEVERE_PER_MIN=100
QUERY_MAX_ROWS=5000
EXPORT_MAX_ROWS=1000000
LIVE_BATCH_THRESHOLD_PER_SEC=50

# --- Backup -----------------------------------------------------------------
BACKUP_DIR=/var/backups/edumatcher
BACKUP_RETAIN=14
```


## 11. Deployment scripts

### 11.1 `scripts/lib.sh`

```bash
#!/usr/bin/env bash
# Shared helpers. Sourced, never executed.

set -euo pipefail

RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[1;33m'; NC=$'\033[0m'

die()  { printf '%sERROR%s %s\n' "$RED" "$NC" "$*" >&2; exit 1; }
warn() { printf '%sWARN %s %s\n' "$YEL" "$NC" "$*" >&2; }
ok()   { printf '%s  ok %s %s\n' "$GRN" "$NC" "$*"; }
step() { printf '\n=== %s ===\n' "$*"; }

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

load_env() {
  [[ -f "$DEPLOY_DIR/.env" ]] || die "No .env found. Copy .env.example and edit it."
  set -a; . "$DEPLOY_DIR/.env"; set +a
  : "${EDUMATCHER_DATA_DIR:?must be set in .env}"
  : "${EDUMATCHER_VERSION:?must be set in .env}"
}

# Detect a container runtime, preferring podman, matching log-gui/config-gui.
detect_runtime() {
  if command -v podman >/dev/null 2>&1; then
    RUNTIME=podman; COMPOSE="podman-compose"
  elif command -v docker >/dev/null 2>&1; then
    RUNTIME=docker;  COMPOSE="docker compose"
  else
    die "Neither podman nor docker found."
  fi
  export RUNTIME COMPOSE
}

port_free() {  # port_free <port> -> 0 if nothing is listening
  ! (command -v ss >/dev/null && ss -lnt "sport = :$1" | grep -q LISTEN) 2>/dev/null
}

wait_for_tcp() {  # wait_for_tcp <host> <port> <timeout_sec>
  local host=$1 port=$2 timeout=${3:-30} waited=0
  while ! (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; do
    sleep 1; waited=$((waited + 1))
    [[ $waited -ge $timeout ]] && return 1
  done
  exec 3<&- 2>/dev/null || true
  return 0
}

# Single indirection point for the supervision decision (§8). Whichever option
# is chosen, only these two functions change.
stack_start_python_plane() {
  case "${SUPERVISOR:-systemd}" in
    systemd) sudo systemctl start edumatcher.target ;;
    compose) $COMPOSE -f "$DEPLOY_DIR/compose.yaml" \
                      -f "$DEPLOY_DIR/compose.core.yaml" up -d ;;
    script)  "$DEPLOY_DIR/scripts/pm-stack" up ;;
    *) die "Unknown SUPERVISOR: ${SUPERVISOR}" ;;
  esac
}

stack_stop_python_plane() {
  case "${SUPERVISOR:-systemd}" in
    systemd) sudo systemctl stop edumatcher.target ;;
    compose) $COMPOSE -f "$DEPLOY_DIR/compose.yaml" \
                      -f "$DEPLOY_DIR/compose.core.yaml" down ;;
    script)  "$DEPLOY_DIR/scripts/pm-stack" down ;;
  esac
}
```

### 11.2 `scripts/preflight.sh`

Changes nothing. Exits non-zero if the stack would not come up cleanly.

```bash
#!/usr/bin/env bash
# Preflight — verify every precondition WITHOUT side effects.
#
# Principle 7: a stack that refuses to start with a reason beats one that
# starts and is subtly wrong. Nothing here creates, writes or starts anything.

. "$(dirname "$0")/lib.sh"
load_env
detect_runtime

FAILED=0
fail() { printf '%sFAIL %s %s\n' "$RED" "$NC" "$*" >&2; FAILED=1; }

step "Runtime"
ok "container runtime: $RUNTIME ($($RUNTIME --version | head -1))"

step "EduMatcher runtime"
if command -v pm-engine >/dev/null 2>&1; then
  ok "pm-engine on PATH"
  installed="$(pm-engine --version 2>/dev/null | tail -1 || echo unknown)"
  [[ "$installed" == *"$EDUMATCHER_VERSION"* ]] \
    || warn "installed runtime ($installed) != EDUMATCHER_VERSION ($EDUMATCHER_VERSION)"
else
  fail "pm-engine not on PATH — run vm/install_edumatcher_runtime.sh"
fi
command -v pm-config-deploy >/dev/null 2>&1 || fail "pm-config-deploy not on PATH"

step "Data directory"
if [[ -d "$EDUMATCHER_DATA_DIR" ]]; then
  [[ -w "$EDUMATCHER_DATA_DIR" ]] && ok "writable: $EDUMATCHER_DATA_DIR" \
                                  || fail "not writable: $EDUMATCHER_DATA_DIR"
else
  parent="$(dirname "$EDUMATCHER_DATA_DIR")"
  [[ -w "$parent" ]] && ok "will be created: $EDUMATCHER_DATA_DIR" \
                     || fail "cannot create $EDUMATCHER_DATA_DIR (parent not writable)"
fi
avail_mb=$(df -Pm "$(dirname "$EDUMATCHER_DATA_DIR")" | awk 'NR==2 {print $4}')
[[ "$avail_mb" -ge 2048 ]] && ok "disk: ${avail_mb} MB free" \
                           || warn "only ${avail_mb} MB free; stats.db and log.db grow"

step "Authored configuration"
if [[ -f "$ENGINE_CONFIG_SRC" ]]; then
  # --check validates WITHOUT installing — exactly the preflight contract.
  if pm-config-deploy --check "$ENGINE_CONFIG_SRC" >/tmp/em-cfg-check.$$ 2>&1; then
    ok "config validates: $ENGINE_CONFIG_SRC"
  else
    fail "config validation failed:"; sed 's/^/       /' /tmp/em-cfg-check.$$ >&2
  fi
  rm -f /tmp/em-cfg-check.$$
else
  fail "authored config not found: $ENGINE_CONFIG_SRC"
fi

step "Ports"
declare -A PORTS=(
  [$ENGINE_PULL_PORT]="pm-engine PULL"   [$ENGINE_PUB_PORT]="pm-engine PUB"
  [$DROP_COPY_PUB_PORT]="drop copy"      [$LOG_SRV_PORT]="pm-log-srv LALF"
  [$LOG_SRV_PUB_PORT]="LALF-PS PUB"      [$LOG_SRV_PULL_PORT]="LALF-PS PULL"
)
case "$COMPOSE_PROFILES" in
  *access*) PORTS[$ALF_PORT]="pm-alf-gwy"; PORTS[$BALF_PORT]="pm-balf-gwy"
            PORTS[$CALF_PORT]="pm-md-gwy"; PORTS[$RALF_PORT]="pm-ralf-gwy"
            PORTS[$DC_PORT]="pm-dc-gwy";   PORTS[$API_GWY_PORT]="pm-api-gwy" ;;
esac
case "$COMPOSE_PROFILES" in
  *ui*) PORTS[$TERMINAL_GUI_PORT]="terminal-gui"; PORTS[$LOG_GUI_PORT]="log-gui"
        PORTS[$CONFIG_GUI_PORT]="config-gui" ;;
esac
for p in "${!PORTS[@]}"; do
  port_free "$p" && ok "$p free (${PORTS[$p]})" || fail "$p in use, needed by ${PORTS[$p]}"
done

# Catch §6.3 collision 1 if someone reverts CONFIG_GUI_PORT to 8080.
[[ "${CONFIG_GUI_PORT:-}" == "${API_GWY_PORT:-}" ]] \
  && fail "CONFIG_GUI_PORT == API_GWY_PORT ($API_GWY_PORT); see design §6.3"

step "Exposure"
if [[ "${BIND_ADDR:-127.0.0.1}" != "127.0.0.1" ]]; then
  if [[ -z "${EXPOSURE_ACKNOWLEDGED:-}" ]]; then
    fail "BIND_ADDR=$BIND_ADDR exposes UIs that have NO AUTHENTICATION.
       Set EXPOSURE_ACKNOWLEDGED=yes to proceed, or put a proxy in front."
  else
    warn "BIND_ADDR=$BIND_ADDR — unauthenticated UIs are reachable off-host"
  fi
else
  ok "loopback only"
fi
[[ "${API_GWY_HOST:-}" == "0.0.0.0" ]] && warn "API_GWY_HOST=0.0.0.0 (see §6.3)"

step "Images"
for img in terminal-gui log-gui config-gui; do
  ref="edumatcher-${img}:${EDUMATCHER_VERSION}"
  $RUNTIME image exists "$ref" 2>/dev/null || $RUNTIME image inspect "$ref" >/dev/null 2>&1 \
    && ok "$ref present" || warn "$ref not present locally (will be pulled or built)"
done

step "Clock"
# Trading dates and DST-aware session bounds depend on this being sane.
if command -v timedatectl >/dev/null 2>&1; then
  timedatectl show -p NTPSynchronized --value | grep -q yes \
    && ok "clock NTP-synchronised" || warn "clock is not NTP-synchronised"
fi

echo
[[ $FAILED -eq 0 ]] && { ok "preflight passed"; exit 0; } \
                    || { die "preflight failed — nothing was started"; }
```

### 11.3 `scripts/deploy-up.sh`

```bash
#!/usr/bin/env bash
# The one command. Ordered per design §7.

. "$(dirname "$0")/lib.sh"
load_env
detect_runtime

step "1/6  Preflight"
"$DEPLOY_DIR/scripts/preflight.sh" || die "aborted"

step "2/6  Data directory"
mkdir -p "$EDUMATCHER_DATA_DIR"/{ref_data,logs}
ok "$EDUMATCHER_DATA_DIR"

step "3/6  Compile and install configuration"
# The gate. Validation failure here means nothing starts (design §5.2).
pm-config-deploy "$ENGINE_CONFIG_SRC" || die "config deploy failed — nothing started"
pm-config-deploy --show

step "4/6  Operations plane"
# pm-log-srv first: every other process is a LALF client, and starting it first
# means their startup logging is captured rather than lost to a fallback file.
case "$COMPOSE_PROFILES" in
  *ops*) stack_start_service pm-log-srv
         wait_for_tcp 127.0.0.1 "$LOG_SRV_PORT" 20 || die "pm-log-srv did not bind"
         ok "pm-log-srv up on $LOG_SRV_PORT" ;;
esac

step "5/6  Core and access planes"
# Recorders before the engine. ZMQ PUB drops messages with no subscriber, so
# any event published before pm-stats/pm-audit/pm-clearing have connected is
# lost silently (design §7.2). The settle delay shrinks that window; the health
# check in step 6 detects whether it shrank it enough.
stack_start_python_plane
sleep "${RECORDER_SETTLE_SEC:-3}"
wait_for_tcp 127.0.0.1 "$ENGINE_PULL_PORT" 30 || die "pm-engine did not bind $ENGINE_PULL_PORT"
ok "core plane up"

step "6/6  UX plane"
case "$COMPOSE_PROFILES" in
  *ui*) $COMPOSE -f "$DEPLOY_DIR/compose.yaml" up -d
        ok "UX plane up" ;;
esac

step "Verification"
"$DEPLOY_DIR/scripts/healthcheck.sh"

cat <<EOF

  EduMatcher ${EDUMATCHER_VERSION} is up.

    TapeDeck            http://${BIND_ADDR}:${TERMINAL_GUI_PORT}
    Log console         http://${BIND_ADDR}:${LOG_GUI_PORT}
    Config builder      http://${BIND_ADDR}:${CONFIG_GUI_PORT}
    REST API            http://${API_GWY_HOST}:${API_GWY_PORT}/docs

    Data directory      ${EDUMATCHER_DATA_DIR}
    Stop with           make down

EOF
```

### 11.4 `scripts/deploy-down.sh`

```bash
#!/usr/bin/env bash
# Reverse of startup. The engine gets time to persist its resting book.

. "$(dirname "$0")/lib.sh"
load_env
detect_runtime

step "UX plane"
$COMPOSE -f "$DEPLOY_DIR/compose.yaml" down --remove-orphans || true

step "Core and access planes"
# SIGTERM, then wait. pm-engine's _shutdown() is what persists GTC orders,
# combos and book_stats; SIGKILL loses up to _PERSIST_INTERVAL_SEC (5s) of it.
stack_stop_python_plane

step "Operations plane"
case "${COMPOSE_PROFILES:-}" in *ops*) stack_stop_service pm-log-srv ;; esac

ok "stopped. Data directory left intact: $EDUMATCHER_DATA_DIR"
```


## 12. Post-start health verification

`scripts/healthcheck.sh` is the acceptance test for a deployment. It is also
usable standalone as a monitoring probe.

```bash
#!/usr/bin/env bash
# Verify a running deployment. Exit 0 healthy, 1 degraded, 2 broken.

. "$(dirname "$0")/lib.sh"
load_env

RC=0
degraded() { warn "$*"; [[ $RC -lt 1 ]] && RC=1; return 0; }
broken()   { printf '%sBROKEN%s %s\n' "$RED" "$NC" "$*" >&2; RC=2; }

step "Sockets"
for spec in "$ENGINE_PULL_PORT:pm-engine PULL" "$ENGINE_PUB_PORT:pm-engine PUB"; do
  port="${spec%%:*}"; name="${spec#*:}"
  port_free "$port" && broken "$name not listening on $port" || ok "$name on $port"
done

step "Configuration"
deployed="$EDUMATCHER_DATA_DIR/ref_data/engine_config.json"
if [[ -f "$deployed" ]]; then
  ok "compiled config present"
  # A config newer than the running engine means someone deployed without a
  # restart — the exchange is running the previous one.
  if [[ "$deployed" -nt "$EDUMATCHER_DATA_DIR/book_stats.json" ]]; then
    degraded "compiled config is newer than engine state — restart may be pending"
  fi
else
  broken "no compiled config at $deployed"
fi

step "Recorders"
# Liveness AND correctness. A recorder that is running but recorded nothing
# looks identical to a quiet market from the outside, so ask it directly.
if command -v pm-stats-cli >/dev/null 2>&1; then
  pm-stats-cli symbols >/dev/null 2>&1 && ok "stats.db readable" \
    || degraded "stats.db not readable — has pm-stats ever run?"
  # The §7.2 startup race leaves a sequence gap. This is where it surfaces.
  gaps="$(pm-stats-cli gaps --format json 2>/dev/null | grep -c '"seq"' || echo 0)"
  [[ "$gaps" -eq 0 ]] && ok "no feed sequence gaps" \
    || degraded "$gaps feed gap(s) detected — events were dropped, likely at startup"
fi
[[ -f "$EDUMATCHER_DATA_DIR/audit.log" ]] && ok "audit.log present" \
  || degraded "no audit.log"

step "Log server"
case "${COMPOSE_PROFILES:-}" in *ops*)
  port_free "$LOG_SRV_PORT" && broken "pm-log-srv not listening" || ok "pm-log-srv up"
  if command -v pm-log-cli >/dev/null 2>&1; then
    # diagnose exits 3 when it flags something — that is a finding, not an error.
    pm-log-cli diagnose >/tmp/em-diag.$$ 2>&1; dr=$?
    case $dr in
      0) ok "pm-log-cli diagnose: clean" ;;
      3) degraded "pm-log-cli diagnose flagged findings:"; sed 's/^/       /' /tmp/em-diag.$$ ;;
      *) degraded "pm-log-cli diagnose could not run" ;;
    esac
    rm -f /tmp/em-diag.$$
  fi ;;
esac

step "HTTP services"
probe() {  # probe <name> <url>
  local code
  code="$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 "$2" 2>/dev/null || echo 000)"
  [[ "$code" == "200" ]] && ok "$1 ($2)" || degraded "$1 unhealthy: HTTP $code"
}
case "${COMPOSE_PROFILES:-}" in *access*)
  probe "pm-api-gwy" "http://${API_GWY_HOST}:${API_GWY_PORT}/healthz" ;;
esac
case "${COMPOSE_PROFILES:-}" in *ui*)
  probe "log-gui bridge"  "http://${BIND_ADDR}:${LOG_GUI_PORT}/api/healthz"
  # Not just "is it up" — is its LALF-PS uplink actually ACTIVE?
  st="$(curl -fsS --max-time 5 "http://${BIND_ADDR}:${LOG_GUI_PORT}/api/bridge/status" 2>/dev/null || echo '{}')"
  grep -q '"ok":true' <<<"$st" || degraded "log-gui upstream not healthy: $st"
  probe "terminal-gui bridge" "http://${BIND_ADDR}:${TERMINAL_GUI_PORT}/api/bridge/status" ;;
esac

echo
case $RC in
  0) ok "healthy" ;;
  1) warn "degraded — usable, but see above" ;;
  2) printf '%sbroken%s\n' "$RED" "$NC" >&2 ;;
esac
exit $RC
```

### 12.1 Why the gap check is in the health check

It is the only thing in this design that can detect the silent failure mode of
§7.2. A deployment that started the engine before the recorders subscribed looks
completely healthy by every other measure — processes up, ports bound, no
errors — while having permanently lost the events published in that window.
`pm-stats-cli gaps` reports it. Treating a gap as *degraded* rather than
*broken* is deliberate: the exchange is running correctly now, but its record of
the first seconds is incomplete, and the operator should know before that
becomes an audit question.


## 13. Backup and restore

The data directory is the only thing in this system that cannot be rebuilt.

### 13.1 `scripts/backup.sh`

```bash
#!/usr/bin/env bash
# Consistent snapshot of EDUMATCHER_DATA_DIR.
#
# SQLite files must NOT be copied with cp while a writer is attached — WAL mode
# means the .db alone is an incomplete picture. `VACUUM INTO` produces a
# consistent snapshot from a live database without stopping anything.

. "$(dirname "$0")/lib.sh"
load_env

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR:?}/edumatcher-${EDUMATCHER_VERSION}-${STAMP}"
mkdir -p "$DEST"

step "SQLite databases (live-safe)"
for db in stats clearing audit_index log; do
  src="$EDUMATCHER_DATA_DIR/${db}.db"
  [[ -f "$src" ]] || continue
  sqlite3 "$src" "VACUUM INTO '$DEST/${db}.db'" \
    && ok "${db}.db" || warn "${db}.db snapshot failed"
done

step "Append-only and JSON state"
for f in audit.log clearing_report.csv gtc_orders.json gtc_combos.json book_stats.json; do
  [[ -f "$EDUMATCHER_DATA_DIR/$f" ]] && cp -p "$EDUMATCHER_DATA_DIR/$f" "$DEST/" && ok "$f"
done

step "Deployed configuration"
# Provenance: this records exactly what the exchange was running.
cp -rp "$EDUMATCHER_DATA_DIR/ref_data" "$DEST/" && ok "ref_data/"

step "Manifest"
cat > "$DEST/MANIFEST.txt" <<EOF
edumatcher_version=$EDUMATCHER_VERSION
taken_at=$STAMP
source_data_dir=$EDUMATCHER_DATA_DIR
host=$(hostname)
EOF
( cd "$DEST" && sha256sum -- * > SHA256SUMS 2>/dev/null || true )

step "Compress and prune"
tar -C "$(dirname "$DEST")" -czf "${DEST}.tar.gz" "$(basename "$DEST")" && rm -rf "$DEST"
ok "$(du -h "${DEST}.tar.gz" | cut -f1)  ${DEST}.tar.gz"

ls -1t "$BACKUP_DIR"/edumatcher-*.tar.gz 2>/dev/null \
  | tail -n +$(( ${BACKUP_RETAIN:-14} + 1 )) | xargs -r rm -f
ok "retaining ${BACKUP_RETAIN:-14} most recent"
```

### 13.2 `scripts/restore.sh`

```bash
#!/usr/bin/env bash
# Restore a snapshot. REFUSES to run against a live stack — restoring under a
# running engine would give it a data directory that changed beneath it.

. "$(dirname "$0")/lib.sh"
load_env

ARCHIVE="${1:?usage: restore.sh <backup.tar.gz>}"
[[ -f "$ARCHIVE" ]] || die "not found: $ARCHIVE"

port_free "$ENGINE_PULL_PORT" || die "pm-engine is running. Run 'make down' first."

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
tar -C "$TMP" -xzf "$ARCHIVE"
SRC="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -1)"

[[ -f "$SRC/MANIFEST.txt" ]] || die "no MANIFEST.txt — not an EduMatcher backup"
. "$SRC/MANIFEST.txt"
if [[ "$edumatcher_version" != "$EDUMATCHER_VERSION" ]]; then
  warn "backup is $edumatcher_version, deployment is $EDUMATCHER_VERSION"
  read -rp "Restore anyway? [y/N] " a; [[ "$a" == y ]] || exit 1
fi
( cd "$SRC" && sha256sum -c SHA256SUMS --quiet ) || die "checksum mismatch — archive is corrupt"

# Never overwrite in place: the current directory is moved aside, so a bad
# restore is itself reversible.
if [[ -d "$EDUMATCHER_DATA_DIR" ]]; then
  ASIDE="${EDUMATCHER_DATA_DIR}.pre-restore.$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$EDUMATCHER_DATA_DIR" "$ASIDE"; ok "previous data moved to $ASIDE"
fi
mkdir -p "$EDUMATCHER_DATA_DIR"
cp -rp "$SRC"/. "$EDUMATCHER_DATA_DIR/"
rm -f "$EDUMATCHER_DATA_DIR"/{MANIFEST.txt,SHA256SUMS}
ok "restored from $ARCHIVE — start with 'make up'"
```


## 14. `Makefile`

```makefile
# EduMatcher deployment — the only interface most operators need.
.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

S := ./scripts

help:            ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	 | awk -F':.*?## ' '{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

init:            ## Create .env from the example
	@test -f .env && echo ".env exists" || { cp .env.example .env; echo "created .env — edit it"; }

preflight:       ## Check every precondition; changes nothing
	@$(S)/preflight.sh

up: preflight    ## Start the stack (config deploy + all enabled planes)
	@$(S)/deploy-up.sh

down:            ## Stop the stack; data directory untouched
	@$(S)/deploy-down.sh

restart: down up ## Stop then start

health:          ## Verify a running deployment
	@$(S)/healthcheck.sh

config:          ## Recompile and install configuration (requires restart to take effect)
	@pm-config-deploy $${ENGINE_CONFIG_SRC}

config-check:    ## Validate configuration without installing
	@pm-config-deploy --check $${ENGINE_CONFIG_SRC}

backup:          ## Snapshot the data directory (safe while running)
	@$(S)/backup.sh

restore:         ## Restore a snapshot: make restore ARCHIVE=path.tar.gz
	@$(S)/restore.sh $(ARCHIVE)

logs:            ## Follow logs across the whole system
	@pm-log-cli tail --min-level INFO

diagnose:        ## Rule-based troubleshooting report
	@pm-log-cli diagnose

offline-bundle:  ## Build the air-gapped artifact set
	@$(S)/offline-bundle.sh

.PHONY: help init preflight up down restart health config config-check \
        backup restore logs diagnose offline-bundle
```


## 15. Release artifacts

### 15.1 The artifact set per version

| Artifact | Built by | Consumed by |
|---|---|---|
| `edumatcher-<v>-py3-none-any.whl` | `poetry build` | `vm/install_edumatcher_runtime.sh` |
| `edumatcher-terminal-gui:<v>` | `terminal-gui/Makefile dist` | Compose |
| `edumatcher-log-gui:<v>` | `log-gui/Makefile dist` | Compose |
| `edumatcher-config-gui:<v>` | `config-gui/Makefile dist` | Compose |
| `edumatcher-deploy-<v>.tar.gz` | §15.2 | operators |
| `edumatcher-offline-<v>.tar.gz` | `offline-bundle.sh` | air-gapped sites |

All six carry the **same version string**, which is the whole point: a
deployment bundle pins images by tag and the wheel by version, so
"which versions are running together" has one answer.

### 15.2 `scripts/offline-bundle.sh`

```bash
#!/usr/bin/env bash
# Build one archive that provisions a classroom with no internet access.

. "$(dirname "$0")/lib.sh"
load_env
detect_runtime

OUT="${DEPLOY_DIR}/dist/edumatcher-offline-${EDUMATCHER_VERSION}"
rm -rf "$OUT"; mkdir -p "$OUT"/{images,wheel,deploy}

step "Container images"
for img in terminal-gui log-gui config-gui; do
  ref="edumatcher-${img}:${EDUMATCHER_VERSION}"
  $RUNTIME image inspect "$ref" >/dev/null 2>&1 || die "missing image: $ref (build it first)"
  $RUNTIME save --output "$OUT/images/${img}.tar" "$ref"
  gzip -f "$OUT/images/${img}.tar"
  ok "$ref"
done

step "Python wheel"
# pip download, not just the wheel: an air-gapped host has no PyPI for deps.
pip download "edumatcher==${EDUMATCHER_VERSION}" --dest "$OUT/wheel" --no-input
ok "$(ls -1 "$OUT/wheel" | wc -l) wheels including dependencies"

step "Deployment bundle"
cp -r "$DEPLOY_DIR"/{compose.yaml,compose.core.yaml,.env.example,Makefile,scripts,profiles,config,systemd} \
      "$OUT/deploy/"

step "Installer"
cat > "$OUT/install.sh" <<'INSTALL'
#!/usr/bin/env bash
# Offline installer. Run as root on the target host.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RUNTIME=$(command -v podman || command -v docker) || { echo "no container runtime"; exit 1; }

for tar in "$HERE"/images/*.tar.gz; do
  echo "loading $(basename "$tar")"; "$RUNTIME" load --input "$tar"
done

python3 -m venv /opt/edumatcher/.venv
/opt/edumatcher/.venv/bin/pip install --no-index --find-links "$HERE/wheel" edumatcher
for cmd in /opt/edumatcher/.venv/bin/pm-*; do ln -sf "$cmd" "/usr/local/bin/$(basename "$cmd")"; done

mkdir -p /opt/edumatcher/deploy && cp -r "$HERE/deploy/." /opt/edumatcher/deploy/
echo "Installed. Next: cd /opt/edumatcher/deploy && make init && make up"
INSTALL
chmod +x "$OUT/install.sh"

step "Package"
tar -C "$(dirname "$OUT")" -czf "${OUT}.tar.gz" "$(basename "$OUT")"
sha256sum "${OUT}.tar.gz" > "${OUT}.tar.gz.sha256"
rm -rf "$OUT"
ok "$(du -h "${OUT}.tar.gz" | cut -f1)  ${OUT}.tar.gz"
```


## 16. Upgrade and rollback

### 16.1 Upgrade procedure

```bash
cd /opt/edumatcher/deploy
make backup                                    # 1. always, before anything
make down                                      # 2. clean stop; engine persists its book
sudo ./scripts/upgrade-runtime.sh --version 0.9.0   # 3. new wheel
sed -i 's/^EDUMATCHER_VERSION=.*/EDUMATCHER_VERSION=0.9.0/' .env  # 4. repoint images
make config-check                              # 5. does the config still validate?
make up                                        # 6. preflight → deploy → start → verify
make health                                    # 7. explicit re-verify
```

Step 5 is the one operators skip and should not. A new release may add
validation the authored config does not satisfy; finding that out *before*
stopping matters less than finding it out before starting, but finding it out at
all is the point.

### 16.2 What makes rollback possible

| Component | Rollback mechanism |
|---|---|
| Python runtime | Install previous version into a *new* venv; symlinks repoint atomically |
| Container images | Previous tags remain in the local store; change `EDUMATCHER_VERSION` |
| Deployed config | `ref_data/` holds both compiled artifact and its YAML source |
| Data | `backup.sh` snapshot from step 1 |

**The unresolved constraint: schema migrations are one-way.** `stats.db` carries
`SCHEMA_VERSION` (currently 5) and the recorder migrates on open. Nothing
migrates *down*. So rolling the runtime back after a schema-bumping release
requires restoring the pre-upgrade data snapshot, losing anything recorded since.

This is why step 1 is not optional, and it is a genuine limitation rather than a
procedural detail. Making downgrade safe would need either reverse migrations or
a schema-version compatibility check at startup that refuses rather than
corrupts. **Recommended as a follow-up** (§21.6).

### 16.3 `scripts/upgrade-runtime.sh` sketch

```bash
#!/usr/bin/env bash
# Atomic runtime swap: build the new venv beside the old, switch symlinks last.
set -euo pipefail
VERSION="${2:?usage: upgrade-runtime.sh --version X.Y.Z}"
NEW="/opt/edumatcher/.venv-${VERSION}"

python3 -m venv "$NEW"
"$NEW/bin/pip" install --upgrade pip
"$NEW/bin/pip" install "edumatcher==${VERSION}"

# Verify before switching: a venv that cannot report its own version is not one
# we should be pointing /usr/local/bin at.
"$NEW/bin/pm-engine" --version >/dev/null || { rm -rf "$NEW"; echo "new runtime unusable"; exit 1; }

for cmd in "$NEW"/bin/pm-*; do ln -sfn "$cmd" "/usr/local/bin/$(basename "$cmd")"; done
ln -sfn "$NEW" /opt/edumatcher/.venv-current
printf '%s\n' "$VERSION" > /opt/edumatcher/EDUMATCHER_VERSION
echo "Runtime now ${VERSION}. Previous venvs retained for rollback:"
ls -1d /opt/edumatcher/.venv-* 
```


## 17. Deployment Profiles

| | Profile A: Classroom Minimal | Profile B: Integration Lab | Profile C: Operator Full Stack |
|---|---|---|---|
| Planes | Core | Core + Access | Core + Access + UX + Ops |
| `COMPOSE_PROFILES` | `core` | `core,access` | `core,access,ui,ops` |
| Processes | 4–6 | 10–12 | 15–16 |
| Ports published | none | 5560–5590, 8080 | + 8090–8092, 5600 |
| `pm-log-srv` | no | optional | **required** |
| Backup schedule | manual | manual | daily via timer |
| Typical host | laptop VM, 2 GB | lab VM, 4 GB | server, 8 GB |

An optional `sim` profile adds `pm-ai-swarm` and `pm-mm-bot` to any of the
three, for demos that need visible market activity.


## 18. Security and Operations Baseline

For all packaged deployments:

- Bind external gateways to localhost by default unless explicitly opened.
  Preflight enforces this with `EXPOSURE_ACKNOWLEDGED` (§11.2).
- Keep API keys in env/secrets, never hardcoded in compose.
- Separate read-only dashboard/API credentials from trading credentials.
- Include health checks for engine sockets, scheduler status, stats/clearing
  liveness, and UI bridge upstream connectivity (§12).

### 18.1 Per-profile firewall

```bash
# Profile B — integration lab, gateways reachable from a lab subnet only.
LAB=10.0.0.0/24
for p in 5560 5565 5570 5580 5590 8080; do
  ufw allow from $LAB to any port $p proto tcp
done
# Internal ZMQ must never leave the host.
for p in 5555 5556 5557 5558 5559; do ufw deny in to any port $p; done
# Unauthenticated UIs: loopback only. Use an SSH tunnel to reach them.
for p in 8090 8091 8092; do ufw deny in to any port $p; done
ufw enable
```

### 18.2 The exposure the design refuses to hide

Three services have **no authentication whatsoever**: `log-gui`,
`terminal-gui`, and `config-gui`. Reaching any of them means reading every log
line the exchange has produced, or editing the configuration it will run.

The design's position is that this is acceptable *only* on loopback, and that
the deployment tooling should make exposing them a deliberate act rather than a
default. Hence `EXPOSURE_ACKNOWLEDGED`, which preflight requires and which
exists to be an uncomfortable extra step.

The recommended pattern for remote access is an SSH tunnel, not a bind change:

```bash
ssh -L 8090:127.0.0.1:8090 -L 8091:127.0.0.1:8091 operator@exchange-host
```


## 19. ALF TCP Example Client Packaging

Question: should the TCP/IP ALF example client in `docs/examples/alf/` be packaged now?

Recommendation: yes, but as an optional "tooling" package, not part of core runtime.

### 19.1 Why package it

- It is useful for integration testing and onboarding external client teams.
- It reduces copy-paste from docs into ad-hoc scripts.
- It provides a stable reference implementation for ALF connectivity.

### 19.2 How to package it

Option A (preferred): add a dedicated script entry point `pm-alf-example-client`
under a Poetry extra, so `pip install edumatcher` stays lean and
`pip install edumatcher[clients]` adds it.

Option B: a companion `edumatcher-clients` package.

Keep scope narrow: connect/logon, NEW/CANCEL/AMEND helpers, basic reconnect, no
strategy logic. Clearly labelled a reference client, not the interactive
terminal.

### 19.3 Its deployment role

Beyond onboarding, the example client is the natural **end-to-end smoke test**
for Profile B: connect, submit a limit order, observe the ack, cancel it,
disconnect. That exercises the full path — gateway, engine, recorders, drop copy
— in a way no health check can. §20 Phase 2 makes this an acceptance criterion.


## 20. Migration Plan

Each phase has acceptance criteria, because "done" otherwise means "the files
exist".

### Phase 1 — Deployable

**Work:** refresh `vm/` to the current release shape; publish the three UI
images per release; create `deploy/` per §9–§14; resolve both §6.3 collisions;
write the operator chapter for the user guide.

**Acceptance:**

1. A clean VM reaches a working Profile C with `make init && make up` and no
   manual steps beyond editing `.env`.
2. `make preflight` fails, with a specific reason and no side effects, for each
   of: port in use, invalid config, unwritable data directory, non-loopback bind
   without acknowledgement.
3. `make backup && make down && make restore ARCHIVE=… && make up` returns the
   exchange to its prior state, verified via `pm-stats-cli`.
4. `make health` exits 0 on a good stack and 1 with a named cause when
   `pm-log-srv` is stopped.

### Phase 2 — Verified

**Work:** package the ALF example client; add a CI job that boots Profile B in a
container and runs an end-to-end trade; ship `offline-bundle.sh`.

**Acceptance:**

1. CI boots Profile B, submits an order via `pm-alf-example-client`, and asserts
   the fill appears in `stats.db` and `audit.log`.
2. The offline bundle installs on a host with networking disabled.
3. The startup-race check (§12.1) reports zero gaps across 20 consecutive CI
   boots. **If it does not, §7.2's settle delay is insufficient and the ordering
   design needs revisiting** — this criterion exists to find that out.

### Phase 3 — Scaled

**Work:** evaluate containerising the Python core; add schema-downgrade
protection (§16.2); Kubernetes/Helm only on real demand.

**Acceptance:** a documented, tested rollback across a schema-bumping release
that does not require restoring a backup.


## 21. Open Decisions

1. Should `pm-engine` and core recorders get official container images in the
   same release, or one later? (Blocks §8.2.)
2. Should the deployment bundle live at `deploy/` in this repository or in a
   separate ops repository?
3. Should the one-command host wrapper be `make up` (assumes Make) or
   `./deploy-up.sh` (assumes nothing)? This design writes both, with Make as the
   documented path.
4. What minimum observability policy is mandatory for a "supported" deployment?
   This design assumes `pm-audit` + `pm-stats` are non-optional in every profile
   and that `pm-log-srv` is mandatory in Profile C only.
5. **Supervision model (§8) — deliberately open.** Options A/B/C are presented
   with trade-offs; `lib.sh` isolates the choice behind two functions so the
   rest of the bundle does not depend on it.
6. Should schema-version downgrade protection block a rollback, or warn? (§16.2)
7. Should `pm-api-gwy`'s `0.0.0.0` default be changed in code, or only overridden
   at deployment? This document does the latter; the former is safer.


## 22. Alternatives Considered

### A. VM-only (everything installed directly)

Pros: simplest runtime dependencies.
Cons: weak packaging story for multiple web UIs; harder image lifecycle.
**Decision:** not preferred.

### B. Container-only from day one

Pros: consistent artifact story.
Cons: bigger migration cost; higher operational complexity for classrooms; and
§5.3's shared-mutable-`DATA_DIR` constraint makes containers awkward for the
core plane specifically.
**Decision:** target later, not immediate default.

### C. Hybrid VM + containerized UIs (recommended)

Pros: lowest short-term friction; preserves the stable Python runtime path;
improves GUI deployment immediately.
Cons: two runtime models to document.
**Decision:** recommended default for the next release cycle.


## 23. Recommendation Summary

- Adopt **hybrid VM + containerized UIs** as the default operator path.
- Publish a **first-party `deploy/` bundle** with profiles, preflight, health
  verification and backup — not just a Compose file.
- Treat the **compiled config artifact as the deployment gate**: nothing starts
  until `pm-config-deploy` succeeds (§5.2).
- Treat `pm-log-srv` as an operations baseline in full-stack deployments.
- Package the ALF example client as an optional helper *and* as the Profile B
  end-to-end smoke test.
- Fix both port issues in §6.3 at the deployment layer now; consider fixing the
  `0.0.0.0` default in code separately.
- Keep container-only full core deployment as a planned next step, not a blocker.

Two things in this design are load-bearing and easy to underestimate: the
**single data directory** (§5.1), which silently defines instance identity, and
the **recorder-before-engine ordering** (§7.2), whose violation is undetectable
except through the sequence-gap check. Everything else is convenience.
