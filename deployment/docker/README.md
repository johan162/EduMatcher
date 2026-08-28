# EduMatcher in a container

A complete EduMatcher exchange — every `pm-*` process, the reference data, the
databases and the logs — inside one container that you use exactly like the
Multipass VM: log in, run `pm-*` commands, attach interactive helpers to the
bus. Unlike the VM it survives a laptop suspend and comes with the correct
clock.

```bash
make build     # build the image (from a freshly built local wheel)
make up        # start the exchange
make shell     # log in and look around
make down      # stop it
```

---

## Table of contents

- [Why a container instead of the VM](#why-a-container-instead-of-the-vm)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Logging in](#logging-in)
- [What is in the image](#what-is-in-the-image)
- [Ports](#ports)
- [Exposing the ZeroMQ bus](#exposing-the-zeromq-bus)
- [The whole system: backend plus web GUIs](#the-whole-system-backend-plus-web-guis)
- [SSH access](#ssh-access)
- [The data directory](#the-data-directory)
- [Choosing the configuration and the profile](#choosing-the-configuration-and-the-profile)
- [Make targets](#make-targets)
- [Configuration reference (`.env`)](#configuration-reference-env)
- [Building from a development wheel](#building-from-a-development-wheel)
- [Useful Docker / Podman commands](#useful-docker--podman-commands)
- [Troubleshooting](#troubleshooting)
- [Design notes](#design-notes)

---

## Why a container instead of the VM

The Multipass runtime VM in [`../vm/`](../vm/) does the same job, but a VM is
a full machine with a clock problt: after a host suspend the lock has drifted, 
which an exchange with market calendars and scheduled auctions notices immediately.

A container has neither problem. It shares the host kernel and therefore the
host clock, there is no guest to resume, and if something does go wrong
`make down && make up` is a few seconds rather than a rebuild. What you give
up is kernel isolation, which an educational exchange does not need.

The container is used as a *machine*, not as a microservice: one container,
`pm-opctl-cli` as the process manager inside it, and you log in to work. That
is deliberate — see [Design notes](#design-notes).

## Requirements

- Podman **or** Docker, with a compose implementation:
  - Podman, with `podman-compose` (preferred) or the `podman compose` subcommand
  - Docker with Compose v2 (`docker compose`) or `docker-compose`
- GNU make
- ~1.5 GB of disk for the build, ~300 MB for the finished image

Podman is preferred automatically when both are installed. Override with:

```bash
make up CONTAINER_ENGINE=docker
```

Check what was detected:

```bash
make info
```

## Quick start

```bash
cd container
make build
make up
make status          # one row per process, green when healthy
make shell           # a root shell inside the exchange
```

Inside the shell everything behaves as it does in the VM:

```bash
pm-opctl-cli list
pm-config-show
pm-alf-console --id TRADER01 --verbose
pm-viewer --symbol AAPL
pm-board
```

From the **host**, the gateways are already reachable on localhost:

```bash
pm-calf-spy  --host 127.0.0.1 --port 5570      # market data (CALF)
pm-ralf-spy  --host 127.0.0.1 --port 5580      # post trade (RALF)
curl -s http://127.0.0.1:8080/api/v1/healthz   # desk REST API
```

Stop it again:

```bash
make down            # container gone, ./data kept
```

## Logging in

Two ways in, both giving a root shell with `EDUMATCHER_DATA_DIR=/data` and
every `pm-*` command on `PATH`:

| | Command | Notes |
|---|---|---|
| **exec** (default) | `make shell` | Instant, nothing extra to run. Open as many terminals as you like — run it again in another window. |
| **ssh** (opt-in) | `make up SSH=1` then `make ssh` | Feels exactly like the VM: works from any terminal without the container CLI, and `scp`/`rsync` work. See [SSH access](#ssh-access). |

Interactive helpers (`pm-alf-console`, `pm-viewer`, `pm-board`,
`pm-admin`) need a TTY, and both paths provide one.

## What is in the image

| | |
|---|---|
| Base | `python:3.13-slim-bookworm` |
| EduMatcher | installed with `pip` into `/opt/edumatcher/.venv`, on `PATH` |
| OS extras | `procps` (pm-opctl-cli uses `pgrep`/`ps`), `tini` (PID 1), `tzdata`, `curl`, `openssh-server` |
| Data | `/data`, bind-mounted from `./data` |
| PID 1 | `entrypoint.sh` under `tini` |

The build is two-stage: the venv is assembled in a builder stage and copied
into a clean runtime stage, so pip caches and build leftovers never ship.

On start, `entrypoint.sh`:

1. creates `/data` and runs `pm-setup --config <EM_CONFIG>` (idempotent —
   an already-deployed configuration is kept unless `EM_CONFIG` changed)
2. starts `sshd`, if `SSH=1`
3. runs `pm-opctl-cli start <EM_PROFILE>`
4. waits, and on `SIGTERM` runs `pm-opctl-cli stop` before exiting

## Ports

All published ports bind to `127.0.0.1` by default. Set `BIND_ADDR=0.0.0.0`
in `.env` to reach the exchange from other machines on your network.

**Always published** — the client-facing gateways:

| Port | Process | Protocol | Purpose |
|-----:|---------|----------|---------|
| 5560 | `pm-balf-gwy` | TCP | Binary ALF order entry |
| 5565 | `pm-alf-gwy` | TCP | ALF order entry |
| 5570 | `pm-md-gwy` | TCP | Market data (CALF/MDLF) |
| 5580 | `pm-ralf-gwy` | TCP | Post trade (RALF) |
| 5590 | `pm-dc-gwy` | TCP | Drop copy (DCLF) |
| 5600 | `pm-log-srv` | TCP | Log ingest (LALF) |
| 8080 | `pm-api-gwy` | HTTP | REST API, `desk` instance |
| 8081 | `pm-api-gwy` | HTTP | REST API, `dashboards` instance |

**Published with `ZMQ=1`** — the raw message bus:

| Port | Process | Socket | Purpose |
|-----:|---------|--------|---------|
| 5555 | `pm-engine` | ZMQ PULL | Order intake |
| 5556 | `pm-engine` | ZMQ PUB | Event + book feed |
| 5557 | `pm-engine` | ZMQ PUB | Drop-copy feed |
| 5558 | `pm-index` | ZMQ PUB | Index values |
| 5559 | `pm-index` | ZMQ PULL | Index commands |
| 5601 | `pm-log-srv` | ZMQ PUB | LALF-PS broadcast |
| 5602 | `pm-log-srv` | ZMQ PULL | LALF-PS control |

**Published with `SSH=1`**: host port `2222` → container port `22`.

`make ports` lists what is actually mapped on a running container.

## Exposing the ZeroMQ bus

The gateways bind `0.0.0.0` and need nothing special. The engine's three bus
sockets and `pm-index`'s two default to `127.0.0.1` and need to be told
otherwise: `ZMQ=1` sets `EDUMATCHER_ENGINE_BIND_HOST` and
`EDUMATCHER_INDEX_BIND_HOST` to `0.0.0.0`, which is honoured directly by
`edumatcher.config` — no relay process involved. `pm-log-srv` needs no
override; it already binds `0.0.0.0` unconditionally.

```bash
make up ZMQ=1

# then, from the host:
pm-dc-spy --host 127.0.0.1 --port 5557        # engine drop-copy feed
```

Keep it off unless you need it — every published port is one more way into a
running exchange.

## The whole system: backend plus web GUIs

```bash
make up-all                                # exchange + terminal-, log- and trader-gui
make up-all CONFIG=ten-nominal             # on a bundled example configuration
make up-all CONFIG=~/mine/engine_config.yaml   # on a configuration of your own
make up-all CONFIG_GUI=1                   # and the configuration builder too
make down-all                              # stop and remove everything
```

| GUI | URL | Talks to |
|---|---|---|
| Trading terminal | <http://localhost:8090> | `pm-md-gwy` 5570, `pm-api-gwy` 8081, `pm-log-srv` 5600 |
| Log viewer | <http://localhost:8091> | `pm-log-srv` 5601/5602, and `data/log.db` read-only |
| Config builder | <http://localhost:8092> | nothing — standalone, hence `CONFIG_GUI=1` |
| Trader GUI | <http://localhost:8093> | `pm-api-gwy` 8080 |

### How the GUIs reach the exchange

They share the compose project, so they share its network, and the backend
answers to the hostname `edumatcher`. Every gateway already binds `0.0.0.0`
inside the container — including `pm-log-srv`'s LALF-PS sockets — so this
needs no `ZMQ=1`, no published host port, and no `host.docker.internal`,
`host-gateway` or VM IP. It behaves identically under Podman, Docker Desktop
and Linux Docker.

The published host ports are for *you* — `curl`, Swagger, `pm-dc-spy` — not
for the GUIs. `make up-all ZMQ=1 SSH=1` still works and still means what it
meant before.

`log-gui` additionally needs the file `log.db`, not just a socket, so `./data`
is mounted into it read-only. The bridge opens the database read-only and
`pm-log-srv` keeps it in rollback-journal mode, so nothing tries to write a
`-wal` file on a read-only mount.

### Loopback gateway binds are opened inside the container

The bundled examples set `bind_address: 127.0.0.1` on `market_data_gateway`
and `post_trade_gateway`. On a laptop that is a sensible default — the
gateways have no authentication, so a wildcard bind puts order entry on
whatever network you are attached to. Inside a container it protects nothing
and breaks everything: the network namespace is already the boundary, `.env`'s
`BIND_ADDR` (still `127.0.0.1`) is what decides host exposure, and a
loopback-bound gateway is simply unreachable from a sibling container. It is
what leaves terminal-gui's market-data panel empty with `calf: RECONNECTING`.

The entrypoint therefore rewrites `bind_address:`/`host:` lines that say
`127.0.0.1` to `0.0.0.0` in the deployed configuration and recompiles it, so
`make config-show` keeps describing what the processes actually do. It runs
for bundled examples and for your own `CONFIG=<file>` alike, touches only
those two keys — the only bind keys in the schema — and is a no-op on
restart. Nothing about a bare-metal `pm-setup` changes.

Note this is diagnosable from inside: `make status` shows
`tcp connect to 127.0.0.1:5570 ok` either way, because that healthcheck
connects over loopback *within* the container. A green process table does not
mean a gateway is reachable from a sibling container.

### Why `up-all` is two phases

`terminal-gui` reads history through `pm-api-gwy` with the read-only
credential (`gateway_id: null`), which is generated *per configuration* — a
different key in every bundled example — and lives on the `dashboards`
instance (8081), not `desk` (8080). It does not exist until the exchange has
deployed its configuration, so `up-all` starts the backend, reads the key out
of `data/ref_data/engine_config.json`, and only then starts the GUIs with it.
A configuration with no such credential is not an error: the live market-data
feed still works, and `up-all` warns that history will be unavailable.

### Running a configuration of your own

`CONFIG=<path>` copies the file to `./config/engine_config.yaml`, which is
mounted read-only at `/config`, and the entrypoint deploys it with
`pm-config-deploy` instead of unpacking a bundled example. The file is
re-deployed on every `up-all`, so editing it and running `make up-all` again
is the edit-test loop. `CONFIG=<name>` (no `/`, no `.yaml`) still means a
bundled example, exactly as for `make up`.

## SSH access

```bash
make up SSH=1
make ssh                     # or: ssh -p 2222 root@localhost
```

`make up SSH=1` runs `make keys` first, which collects every `~/.ssh/*.pub` on
the host into `deployment/docker/.ssh/authorized_keys`. That file is mounted read-only
into the container and copied into place with the ownership and mode `sshd`
insists on. No key material is baked into the image, and adding a key is a
`make keys && make restart` away — no rebuild.

The container's own host keys are generated once and kept in
`data/ssh-hostkeys/`, so recreating the container does not trip your
`known_hosts`.

`scp` and `rsync` work as they would against any machine:

```bash
scp -P 2222 my-engine_config.yaml root@localhost:/data/ref_data/
```

To build a smaller image with no `openssh-server` at all, set `WITH_SSH=0` in
`.env` and rebuild.

## The data directory

`./data` on the host is `/data` in the container, and it is the canonical
EduMatcher data directory (`EDUMATCHER_DATA_DIR`), so everything the exchange
persists is directly visible and editable from the host:

```text
data/
├── ref_data/
│   ├── engine_config.yaml     the authored configuration
│   └── engine_config.json     the compiled artifact every process reads
├── emo/                       pm-opctl-cli PID files and per-process logs
│   ├── engine.log
│   └── ...
├── audit.log                  the audit trail
├── clearing.db  stats.db  log.db
├── gtc_orders.json  gtc_combos.json  book_stats.json
└── ssh-hostkeys/              only when SSH=1 has been used
```

It survives `make down`. `make clean-data` deletes it after confirming.

Follow one process's log from the host without entering the container:

```bash
make proc-logs P=engine
tail -f data/emo/alf-gwy.log
```

Edit the configuration on the host and reload it:

```bash
vim data/ref_data/engine_config.yaml
make config-deploy      # validates and recompiles engine_config.json
make restart            # processes read the artifact at start
```

## Choosing the configuration and the profile

Two settings decide what the exchange looks like. Both live in `.env` and can
be overridden per command.

**`EM_CONFIG`** — which bundled example configuration is deployed, named the
way `pm-config-deploy --example` names them:

```text
one-basic     three-basic     ten-basic     thirty-basic
one-nominal   three-nominal   ten-nominal   thirty-nominal
one-complex   three-complex   ten-complex   thirty-complex
```

```bash
make up CONFIG=ten-nominal
```

Changing it redeploys the configuration in `./data` on the next `make up`
(the entrypoint remembers which example the directory was built from).

**`EM_PROFILE`** — which `pm-opctl-cli` profile is started:

| Profile | What runs |
|---|---|
| `default` | The full nominal stack: logging, audit, stats, clearing, engine, scheduler, all gateways, both API instances, index |
| `mini` | A trading-capable subset |
| `micro` | Centralized logging plus the engine |

```bash
make up PROFILE=micro
```

To change what a profile contains, generate the file and edit it on the host:

```bash
make shell
pm-opctl-cli init        # writes /data/emo-config.yaml
exit
vim data/emo-config.yaml
make restart
```

## Make targets

| Target | Does |
|---|---|
| `make build` | Build the image from a freshly built local wheel. `PYPI=1` installs latest PyPI instead; `VERSION=0.20.2` pins a PyPI release |
| `make up` | Start the exchange. `CONFIG=`, `PROFILE=`, `ZMQ=1`, `SSH=1` |
| `make up-all` | Start the exchange *and* the web GUIs. `CONFIG=`, `PROFILE=`, `CONFIG_GUI=1`, `ZMQ=1`, `SSH=1` |
| `make down-all` | Stop and remove every container, GUIs included |
| `make down` | Stop and remove the container; `./data` is kept |
| `make restart` | Restart the container (re-runs the entrypoint) |
| `make shell` | Interactive root shell in the container |
| `make ssh` | Log in over ssh (needs `make up SSH=1`) |
| `make keys` | Rebuild `.ssh/authorized_keys` from `~/.ssh/*.pub` |
| `make status` | `pm-opctl-cli list` — process table with uptime and RSS |
| `make health` | `pm-opctl-cli health` — exits 0 when every process is OK |
| `make logs` | Follow the entrypoint output (startup, shutdown) |
| `make proc-logs P=engine` | Follow one process log from `data/emo/` |
| `make config-deploy` | Recompile `data/ref_data/engine_config.yaml` |
| `make config-show` | Show the deployed configuration |
| `make ports` | List the published ports |
| `make info` | Show the detected engine, compose command and image name |
| `make clean` | Remove the container and the image |
| `make clean-data` | Delete `./data` (asks first) |

Flags combine: `make up ZMQ=1 SSH=1 CONFIG=ten-complex PROFILE=mini`.

## Configuration reference (`.env`)

`.env` is created from `.env.example` on the first `make build`/`make up`. It
is git-ignored, so it is the right place for host-specific choices.

| Variable | Default | Meaning |
|---|---|---|
| `COMPOSE_PROJECT_NAME` | `edumatcher` | Compose project name |
| `EDUMATCHER_VERSION` | *(empty)* | PyPI version to install; empty = latest |
| `WITH_SSH` | `1` | Install `openssh-server` in the image |
| `EM_CONFIG` | `three-basic` | Bundled example configuration to deploy |
| `EM_PROFILE` | `default` | `pm-opctl-cli` profile to start |
| `TZ` | `UTC` | Container timezone — match your trading calendar |
| `BIND_ADDR` | `127.0.0.1` | Host interface the ports bind to |
| `SSH_PORT` | `2222` | Host port forwarded to sshd |
| `TERMINAL_GUI_PORT` / `LOG_GUI_PORT` / `CONFIG_GUI_PORT` / `TRADER_GUI_PORT` | `8090` / `8091` / `8092` / `8093` | Host ports for the GUIs started by `make up-all` |
| `IMAGE_NAME` / `IMAGE_TAG` | `edumatcher` / `local` | Image naming |
| `CONTAINER_NAME` | `edumatcher` | Container name |

**Timezone matters.** The scheduler runs auctions against a market calendar.
Leaving `TZ=UTC` is fine and predictable; setting `TZ=Europe/Stockholm` makes
the container agree with your wall clock.

## Building from PyPI instead of local source

`make build` (no flags) is the default and builds from your local source
checkout: it runs `poetry build --format wheel` in the repository root,
copies the freshest `dist/*.whl` into `deployment/docker/.wheel/`, and the
Dockerfile installs it. Every plain rebuild picks up whatever you've
changed locally, including uncommitted changes — there's no flag to
remember for that to happen.

To containerize a released build instead:

```bash
make build PYPI=1        # latest PyPI release
make build VERSION=0.20.2  # a specific pinned release
```

Either form clears `deployment/docker/.wheel/` first, so a stale local wheel never
shadows the PyPI install. `VERSION=` alone (without `PYPI=1`) also goes to
PyPI — pinning a version only makes sense against a release, so it implies
`PYPI=1`.

`DEV=1` is still accepted for anyone's existing muscle memory or scripts,
but it's a no-op now — building from local source is already the default.

**If a rebuilt container doesn't seem to reflect a source change**, this
build-source selection is the first thing to check — confirm you didn't
pass `PYPI=1`/`VERSION=` by accident (e.g. left over in your shell history)
when you meant to build from local source.

## Useful Docker / Podman commands

Every command below works with `docker` or `podman` — substitute whichever you
use. `make` covers the common cases; these are for when you want to poke at
the machinery directly.

**Looking around**

```bash
docker ps                                    # is it running, and healthy?
docker stats edumatcher                      # live CPU/memory of the container
docker top edumatcher                        # every pm-* process inside
docker port edumatcher                       # the published port map
docker inspect edumatcher | less             # everything, in JSON
docker logs --tail 50 -f edumatcher          # entrypoint output
docker image ls edumatcher                   # image size
docker history edumatcher:local              # where those megabytes went
```

**Getting in and running things**

```bash
docker exec -it edumatcher bash              # a shell (this is `make shell`)
docker exec -it edumatcher pm-opctl-cli list
docker exec -it edumatcher pm-alf-console --id TRADER01 --verbose
docker exec edumatcher pm-stats-cli health   # one-shot, no TTY
docker exec -u root edumatcher ls -l /data
```

**Moving files**

```bash
docker cp edumatcher:/data/audit.log ./audit.log
docker cp ./engine_config.yaml edumatcher:/data/ref_data/
```

(Or just use `./data` on the host — it is the same directory.)

**Lifecycle**

```bash
docker compose up -d                         # = make up
docker compose -f compose.yaml -f compose.zmq.yaml up -d     # = make up ZMQ=1
docker compose down                          # = make down
docker compose restart edumatcher
docker compose build --no-cache              # rebuild ignoring layer cache
docker compose config                        # the fully merged configuration
docker restart edumatcher
docker stop edumatcher && docker start edumatcher
```

**Podman specifics**

```bash
podman machine list                          # macOS/Windows: the podman VM
podman machine start
podman generate systemd --name edumatcher --new --files   # run it as a service
podman unshare ls -l data/                   # inspect rootless-mapped files
```

**Cleaning up**

```bash
docker compose down --volumes                # also drops any named volumes
docker rmi edumatcher:local
docker system df                             # what is using disk
docker system prune                          # reclaim it (careful)
```

## Troubleshooting

**`make up` says no compose implementation.**
Install Docker Compose v2 or `podman-compose`. `make info` shows what was
detected; `CONTAINER_ENGINE=docker` forces an engine.

**`docker ps` shows `unhealthy`.**
The health check is a TCP connect to the engine on 5555. If it fails, the
engine did not start: `make logs`, then `tail data/emo/engine.log`.

**`make health` reports FAIL but everything works.**
With the stock `default` profile, `index-srv` is probed on `127.0.0.1:5610`
while `pm-index` actually binds 5558/5559, so that one row is always
`not responding`. Everything else is a real signal. Fix it for your own setup
with `pm-opctl-cli init` and correct the `tcp:` line in `data/emo-config.yaml`.

**A port is already in use on the host.**
Something else is on 5555–5602 or 8080/8081 — often a `pm-*` process you
started outside the container. Stop it, or change the host side of the mapping
in `compose.yaml`.

**Host-side bus clients cannot connect on 5555–5557.**
Those ports only exist with `make up ZMQ=1`. Confirm with `make ports`.

**Configuration changes do not take effect.**
Processes read the compiled artifact at start. After editing
`data/ref_data/engine_config.yaml`, run `make config-deploy && make restart`.

**A source code change does not take effect after `make build`.**
Confirm the build actually used local source and not a PyPI release —
`PYPI=1` or `VERSION=` (even one left over from a previous invocation in
your shell history) makes `make build` skip your local checkout entirely.
The build log's first line says which path was taken
(`building wheel from the repository checkout` vs. `building from PyPI`).
A quick way to confirm the *installed* package matches your source: `make
shell`, then `python3 -c "import edumatcher; print(edumatcher.__file__)"`
and check whichever module you changed for the expected content, or look
for an `ImportError` on a name you just added — that means the running
container is still on an old release.

**`make build` fails because `poetry` is not installed.**
The default build path runs `poetry build --format wheel` in the repo
root. If you don't have Poetry set up and just want a released version,
use `make build PYPI=1` (or `VERSION=x.y.z`) instead — those don't need
Poetry at all.

**Changing `EM_CONFIG` did nothing.**
The entrypoint redeploys only when the name differs from the one recorded in
`data/.container-config`. To force a clean slate: `make down && make clean-data
&& make up`.

**`make ssh` is refused.**
`make up SSH=1` must have been used (`docker port edumatcher` should show
`22/tcp`), `WITH_SSH` must not be `0`, and you need at least one key in
`~/.ssh/*.pub`. `make logs` reports how many authorized keys it found.

**`podman-compose` chokes on the overlay files.**
Older versions merge multi-file setups poorly. Put the settings straight into
`compose.yaml`, or update `podman-compose` to a current release.

**Build fails trying to reach `docker.io`, even though `podman build` works.**
`podman compose` — the built-in subcommand, not the standalone `podman-compose`
tool — is only a thin wrapper: it searches for an external compose provider on
`PATH` and silently delegates to whatever it finds, which is commonly the
standalone `docker-compose` binary if one happens to be installed. That tool
then pulls the base image through Docker's own registry/auth stack, not
Podman's, so it can fail with a `docker.io` authentication error on a machine
where Podman itself is set up correctly. Confirm it with:

```bash
podman compose version
```

If the output starts with `Executing external compose provider "..."` before
the version banner, that is the cause. This Makefile prefers the standalone
`podman-compose` over the `podman compose` subcommand for exactly this reason
— `make info` shows which one it picked.

**Everything is wedged.**
`make down && make up` recreates the container in seconds; `./data` is kept.
`make clean-data` starts from an empty exchange.

## Design notes

**One container, many processes.** EduMatcher's engine binds its ZeroMQ bus
sockets to `127.0.0.1` by default (overridable via `EDUMATCHER_ENGINE_BIND_HOST`,
see [Exposing the ZeroMQ bus](#exposing-the-zeromq-bus)), so nothing forces
every `pm-*` process into one network namespace anymore. This deployment still
keeps them together: one container that behaves like a machine is simpler and
closer to how the system is meant to be operated — with `pm-opctl-cli` as the
process manager, exactly as in the VM — and splitting it up would turn a
teaching system into a distributed deployment exercise for no benefit this
setup needs.

**Running as root.** The container runs as root, like a VM you `sudo` in. It
keeps the bind-mounted `./data` free of UID-mapping puzzles across macOS,
rootless Podman and rootful Docker. It is a sandboxed educational exchange,
not a production venue; if you want a non-root runtime, add a `USER` to the
Dockerfile and make sure the UID owning `./data` matches.

**`tini` as PID 1.** `pm-opctl-cli` detaches its children into their own
session, so PID 1 must reap orphans or the container slowly fills with
zombies. `tini` does that and forwards `SIGTERM` to the entrypoint, which stops
the profile cleanly before exiting.

**`restart: unless-stopped`.** The exchange comes back after a host reboot or
an engine crash, and stays down when you actually asked for it to be down.
