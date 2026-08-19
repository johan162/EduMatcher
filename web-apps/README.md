# EduMatcher web apps

Four independent browser applications for the EduMatcher exchange. Each is
its own npm workspace with its own `package.json`, `Dockerfile`,
`docker-compose.yml`, and `Makefile` — nothing here is shared between them,
and none of the Python `pm-*` processes depend on this directory existing.
It exists purely to keep four self-contained frontend projects out of the
repository root.

| App | System name | Role | Dev port(s) | Container port |
| --- | --- | --- | --- | --- |
| [`log-gui/`](log-gui/) | `pm-log-ui` | Operator console over `pm-log-srv`'s logs — live tail, search, alerts, acks | bridge `5191`, web `8191` | `8091` |
| [`trader-gui/`](trader-gui/) | `pm-trading-ui` | Trading terminal (TRADER / MARKET_MAKER / ADMIN personas) against `pm-api-gwy` | web `8193` | `8093` |
| [`terminal-gui/`](terminal-gui/) | `pm-terminal` | Read-only, credential-free market display ("TapeDeck") | bridge `5190`, web `8190` | `8090` |
| [`config-gui/`](config-gui/) | n/a | Browser builder for authored `engine_config.yaml`, companion to `pm-config-gen` | server `5192`, web `8192` | `8092` |

"Dev port(s)" is what `make dev` binds to (backend + Vite dev server,
started together). "Container port" is what `make up` publishes on
`localhost`. The two port ranges are deliberately disjoint and follow a
shared numbering scheme: each app's container port is `809N`, its dev web
port is `819N`, and its dev backend port (where it has one) is `519N`, all
sharing the same `N`. `trader-gui` has no dev-mode backend process — its
`apps/serve/` server only runs in production — so it has no `519N` port.

Each app's own `README.md` is the full developer reference: project layout,
getting started, every environment variable, startup order, and Makefile
targets.

## Starting all GUIs together

A `Makefile` in this directory orchestrates `log-gui`, `terminal-gui`, and
`trader-gui` as a group. The key variable is `VM_BACKEND_IP`: set it to the
IP address of the VM (or host) running the EduMatcher backend processes, and
all three containers are pointed at that address automatically.

```bash
# All three GUIs, backend on Docker Desktop host (no VM — uses host.docker.internal):
make up

# All three GUIs, backend running in a Multipass or other VM:
make up VM_BACKEND_IP=192.168.64.10

# Stop all three:
make down VM_BACKEND_IP=192.168.64.10   # or just: make down

# Export once for the session and omit from every command:
export VM_BACKEND_IP=192.168.64.10
make up
make ps
make down
```

`VM_BACKEND_IP` is translated into the right per-app environment variable
before each app's compose stack starts:

| App | Env var set | Port assumed |
| --- | --- | --- |
| `log-gui` | `LOG_SRV_HOST` | `5601`/`5602` (LALF-PS) |
| `terminal-gui` | `CALF_HOST`, `API_GATEWAY_URL`, `LOG_SRV_HOST` | `5570` (CALF), `8080` (REST), `5600` (LALF) |
| `trader-gui` | `API_PROXY_TARGET` | `8080` (REST/WS) |

When `VM_BACKEND_IP` is not set, each app's compose file falls back to
`host.docker.internal`, which is correct for Docker Desktop on macOS/Windows.

Each app can still be driven individually from its own directory (`make up`,
`make down`, etc.). The orchestration Makefile is purely additive — it
delegates to each app's own Makefile via `$(MAKE) -C`.

Available top-level targets:

| Target | Description |
| --- | --- |
| `up` | Start all three GUI containers |
| `down` | Stop and remove all three |
| `restart` | `down` then `up` |
| `ps` | Show container status for all three |
| `up-log` / `up-terminal` / `up-trader` | Start a single app |
| `down-log` / `down-terminal` / `down-trader` | Stop a single app |
| `logs-log` / `logs-terminal` / `logs-trader` | Follow a single app's container logs |

## Backend dependencies

None of these apps depend on each other, but each depends on one or more
`pm-*` processes to show live data:

| App | Requires | Optional |
| --- | --- | --- |
| `log-gui` | `pm-log-srv` (LALF-PS, `5601`/`5602`; reads its `log.db`) | `pm-log-cli` on `PATH`, for the Diagnostics view |
| `trader-gui` | `pm-api-gwy` (REST + WebSocket, `8080`) | — |
| `terminal-gui` | `pm-md-gwy` (CALF TCP, `5570`), `pm-api-gwy` (REST, `8080`) | `pm-log-srv` (`5600`) — falls back to stdout/file logging if unreachable |
| `config-gui` | — | `pm-cverifier` on `PATH`, for the "Verify" button |

## Common shape

Every app follows the same layout:

```
<app>/
  apps/                 One or more npm workspace packages: always a `web/`
                         frontend, plus a backend package whose name varies
                         (`server/`, `bridge/`, or `serve/` — see each app's
                         own README for its actual layout)
  packages/              Shared TypeScript (types, protocol codecs, query builders)
  Dockerfile              Single-container production image
  docker-compose.yml       Compose wrapper around Dockerfile
  Makefile                 install / dev / test / build / up / down — the
                            same target names across all four apps
```

`log-gui` and `terminal-gui` each ship a small first-party Fastify backend
(`apps/bridge/`) that talks to the Python side directly (LALF-PS or CALF
TCP) and serves the built frontend in production. `trader-gui` has no
bridge process — its backend (`apps/serve/`) is a zero-dependency static
file server that only proxies REST/WebSocket calls through to `pm-api-gwy`.
`config-gui` is the odd one out entirely: it has no required runtime
dependency on any `pm-*` process — its backend (`apps/server/`) only
imports, validates, and generates YAML, and its optional `verify:python`
check is the only place it shells out to the Python engine.

## Running one

From the app's own directory:

```bash
cd web-apps/<app>
make up        # container stack, or:
make dev       # local Node processes
```

See the app's own `README.md` for prerequisites, environment variables, and
the exact startup order for that app's backend dependencies.
