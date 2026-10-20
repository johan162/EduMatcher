# The Simulation Container

!!! note "Learning objectives"
    After reading this chapter you will be able to:

    - Explain what is in the `edumatcher-ai-sim` image and how it differs
      from the plain `edumatcher` image
    - Read `compose.ai-sim.yaml` and change what it runs through its
      environment variables
    - Run the simulation on a server for a class, safely
    - Upgrade, reset, back up and build the image yourself

    **Prerequisites**: [Ten-Minute Start](../part-1-start-here/020-ten-minute-start.md).

## Two images, one exchange

| Image | What it is |
|---|---|
| `ghcr.io/johan162/edumatcher` | The exchange. Starts the `s10-basic` example with the `default` profile unless told otherwise |
| `ghcr.io/johan162/edumatcher-ai-sim` | The same image with different defaults: the `s300-sim` example, the `ai-sim` profile, Stockholm time, dead processes restarted |

Both are built from the same `Dockerfile` (`deployment/docker/`) — the
simulation is its last stage, a handful of environment variables on top of
the exchange — and published together with every release, for `amd64` and
`arm64`, tagged with the release version and `latest`. Nothing in the
simulation image is a fork: every program in it is the ordinary
`edumatcher` package.

```dockerfile
FROM runtime AS ai-sim

ENV EM_CONFIG=s300-sim \
    EM_PROFILE=ai-sim \
    EM_RESTART_DEAD=1 \
    EM_SPEED=1 \
    TZ=Europe/Stockholm
```

## What happens when it starts

The image's entry point (`entrypoint.sh`) does five things:

1. **Deploys the configuration** into `/data` — the `EM_CONFIG` example, or
   your own file if `EM_CONFIG_FILE` is set. On later starts it keeps what is
   deployed, unless `EM_CONFIG` names a different example than last time.
2. **Sets the clock**: with `EM_SPEED` other than 1, or `EM_START`, it
   passes them on to the scheduler (as `EDUMATCHER_SCHEDULER_SPEED` and
   `EDUMATCHER_SCHEDULER_START`).
3. **Starts the profile** with `pm-opctl-cli start ai-sim`.
4. **Watches it**: once a minute it restarts any process of the profile that
   has died, and says so in the container log (`docker logs edumatcher-sim`):

    ```text
    ==> 2026-11-03 09:00:41 Restarting: mm-bot
    ==> 2026-11-03 09:00:41   started mm-bot (pid 812): pm-mm-bot --gateway-id MM01 ...
    ```

    The market maker usually appears here once, a minute after the first
    start: it gives up if it starts before the engine is ready.
5. **Stops cleanly** on `docker stop` (or `compose down`): it stops every
   process of the profile, which takes up to a minute.

The image's health check asks whether the engine accepts connections, so
`docker ps` shows `healthy` once the exchange is up — whether or not the
market is open.

## `compose.ai-sim.yaml`

The compose file runs six containers in one compose project,
`edumatcher-sim`:

| Container | Image | Host port | |
|---|---|---|---|
| `edumatcher-sim` | `edumatcher-ai-sim` | 5560, 5565, 5570, 5580, 5590, 5600, 8080, 8081 | the exchange and the simulation |
| `edumatcher-sim-terminal-gui` | `edumatcher-terminal-gui` | 8090 | market-data terminal |
| `edumatcher-sim-log-gui` | `edumatcher-log-gui` | 8091 | log viewer |
| `edumatcher-sim-trader-gui` | `edumatcher-trader-gui` | 8093 | trading screen |
| `edumatcher-sim-book-gui` | `edumatcher-book-gui` | 8094 | order-book viewer |
| `edumatcher-sim-dash-gui` | `edumatcher-dash-gui` | 8095 | operator dashboard |

The GUIs reach the exchange over the compose network, at the host name
`edumatcher`; the host ports are for you and your students' browsers and
programs. The GUIs that read market history use the example's read-only API
key, which the compose file already knows.

There are two copies of this file, and they describe the same six
containers:

| | |
|---|---|
| `deployment/curl/compose.ai-sim.yaml` | What `install.sh --sim` fetches into `~/.edumatcher-sim`. Build-free: every image comes from GHCR. Its data directory is `./data` |
| `deployment/docker/compose.ai-sim.yaml` | The repository's own, which can also *build* the image (`make build-sim`). Its data directory is `./data-sim` |

The rest of this chapter uses the installed one and `./edumatcher.sh`.

### Settings

Everything is set with environment variables, in the `.env` file next to the
compose file (the installer writes one) or on the command line, as in
`EM_SPEED=24 docker compose -f compose.ai-sim.yaml up -d`:

| Variable | Default | Meaning |
|---|---|---|
| `EM_SPEED` | `1` | How many times faster than real time the trading calendar runs ([Accelerated Time](120-accelerated-time.md)) |
| `EM_START` | — | Where an accelerated calendar starts, local time, e.g. `2026-11-02T08:55` |
| `TZ` | `Europe/Stockholm` | The time zone of the trading hours |
| `EM_CONFIG_FILE` | — | Your own engine configuration, as a path inside the container (below) |
| `EM_VERSION` | `latest` | Which release of all six images to run, e.g. `0.51.0` |
| `GHCR_OWNER` | `johan162` | Whose published images to pull |
| `BIND_ADDR` | `127.0.0.1` | Which host interface the ports are published on |
| `TERMINAL_GUI_PORT`, `LOG_GUI_PORT`, `TRADER_GUI_PORT`, `BOOK_GUI_PORT`, `DASH_GUI_PORT` | 8090, 8091, 8093, 8094, 8095 | Host ports of the GUIs |
| `PM_READONLY_API_KEY` | the `s300-sim` key | The read-only key the GUIs use; change it only with your own configuration |
| `AISIM_IMAGE` | the GHCR image | A different backend image, e.g. one you built |

!!! tip "Pin a version for a course"
    `latest` moves with every release. For a course that runs for weeks,
    put `EM_VERSION=<version>` in `.env` so a restart never brings a
    different exchange. `./edumatcher.sh update 0.51.0` does it for you.

### Data

Everything the exchange writes is in the install's `data` directory, mounted
at `/data`: `~/.edumatcher-sim/data` for an installed simulation,
`./data-sim` next to the compose file in a checkout. It survives `stop`,
`start`, reboots and upgrades.

| To | Do |
|---|---|
| Start over, with a fresh market | `./edumatcher.sh stop`, delete `data`, `./edumatcher.sh start` |
| Back it up | Stop the stack, copy `data`, start it again |
| Look at a file | It is on your disk: `data/ai_swarm/`, `data/stats.db`, … |

A backup taken while the exchange runs can catch a database mid-write; stop
it first.

### The commands you will use

From the install directory (`cd ~/.edumatcher-sim`):

| Task | Command |
|---|---|
| Start | `./edumatcher.sh start` |
| Stop | `./edumatcher.sh stop` |
| Process table, container status | `./edumatcher.sh status` |
| A shell in the exchange | `./edumatcher.sh shell` |
| One command in it | `./edumatcher.sh shell pm-market-sim --status --id OPS01` |
| The container log (starts, restarts) | `./edumatcher.sh logs edumatcher` |
| The web addresses | `./edumatcher.sh urls` |
| Which directory is behind each container path | `./edumatcher.sh mounts` |
| Accelerate the calendar | `./edumatcher.sh speed 24 2026-11-02T08:55`, then `restart` |
| Upgrade | `./edumatcher.sh update` (or `update 0.51.0`) |
| Remove it | `./edumatcher.sh uninstall` (`--data` to delete the data too) |

The script is a wrapper around `docker compose` and `docker exec`; anything it
does you can do by hand — `docker compose -f compose.ai-sim.yaml up -d`,
`docker exec edumatcher-sim pm-opctl-cli list --no-restart`,
`docker logs -f edumatcher-sim`.

From a clone of the repository, `deployment/docker/Makefile` wraps the same
things: `make up-sim`, `make down-sim`, `make sim-status` (process table and
disk), `make sim-shell`; `make up-sim SPEED=24 START=2026-11-02T08:55` for an
accelerated run.

## Changing what it runs

### Your own configuration

The container deploys a configuration of your own when `EM_CONFIG_FILE`
names one. Start from the deployed one:

```bash
mkdir -p my-sim
./edumatcher.sh shell cat /data/ref_data/engine_config.yaml > my-sim/engine_config.yaml
./edumatcher.sh shell cat /data/ref_data/market_sim.yaml    > my-sim/market_sim.yaml
# edit my-sim/market_sim.yaml (or engine_config.yaml), then:
./edumatcher.sh config ./my-sim/engine_config.yaml
./edumatcher.sh restart
```

`config` copies both files into the install's `./config`, which is mounted
read-only at `/config`, and sets `EM_CONFIG_FILE=/config/engine_config.yaml`
in `.env` so it stays set. If the configuration is refused, the container log
says why (`./edumatcher.sh logs edumatcher`) — check it first with
`./edumatcher.sh shell pm-cverifier /config/engine_config.yaml`.

A deployed configuration stays deployed: clearing `EM_CONFIG_FILE` alone does
not bring `s300-sim` back. Clear it, then redeploy the bundled one and
restart:

```bash
./edumatcher.sh shell pm-setup --config s300-sim --force
./edumatcher.sh restart
```

### Your own traders or process flags

The traders' mix and the processes' flags are in the process profile.
Write the built-in profiles out once and edit the copy:

```bash
./edumatcher.sh shell pm-opctl-cli init
```

`init` writes `data/emo-config.yaml`, which from then on replaces the
built-in profiles. To use your own `swarm.yaml`, put it in `./config/` and
change the `ai-sim` profile's `ai-swarm` command to
`--swarm /config/swarm.yaml`; restart the stack. Delete
`emo-config.yaml` to go back to the built-in profiles (and get the profiles
of a newer release after an upgrade).

[Tuning the Traders](../part-2-how-it-works/060-tuning-the-traders.md) says
what to change.

## Opening it to a classroom

By default every port is published on `127.0.0.1`: only the machine itself
can reach the exchange. To let students in from the local network, set
`BIND_ADDR=0.0.0.0` in `.env` and restart, and first:

- **Change the API keys.** The example's keys are printed in this book. Use
  your own configuration (above) with new `api_key` values for every
  participant, and give each student only their own.
- **Keep it on a network you trust.** Nothing here is encrypted: API keys
  and orders travel in clear text. Put a TLS reverse proxy in front of the
  web ports if the network is not yours.
- **Mind the order gateways.** The API (8080) checks a key; the order
  gateways (5560, 5565) identify a participant by its ID alone, so anyone who
  reaches them can log on as any participant — an AI trader included, which
  then loses its session. Publish them only on a network you trust, or take
  their lines out of the compose file's `ports` and let students trade
  through the API and trader-gui.

## Resources

Measured on a 2-vCPU Linux machine, at real speed during continuous trading
(see [Running It for Weeks](../part-4-watch-and-teach/150-running-it-for-weeks.md)
for the details and for disk):

| | |
|---|---|
| CPU, whole exchange | about half of one core while the market is open; almost nothing while it is closed |
| Memory | about 1 GB for the exchange container (the sum of the processes' resident memory), flat over the day |
| Busiest processes | `pm-engine` and the two API gateways together, a tenth of a core each; then `pm-stats`, `pm-audit`, the swarm worker, `pm-alf-gwy` and `pm-mm-bot`, about a twentieth each |

A laptop that runs a browser comfortably runs the simulation.

## Upgrading

```bash
./edumatcher.sh update          # the newest release
./edumatcher.sh update 0.51.0   # ...or an exact one
```

The data directory is kept, and with it the deployed configuration and the
market's history. The release notes say when a release changes the `s300-sim`
example; to take the new one, start over with a fresh data directory, or
redeploy with the new example while keeping your history:
`./edumatcher.sh shell pm-setup --config s300-sim --force`, then restart.

## Building the image yourself

From a clone of the repository:

```bash
cd deployment/docker
make build-sim          # builds edumatcher-ai-sim:local from this checkout
make up-sim LOCAL=1     # runs it with the GUI images from GHCR
```

`make build-sim` builds a wheel from the checkout (it needs `poetry`) and the
image's `ai-sim` stage. Without `make`:

```bash
docker build --target ai-sim -t edumatcher-ai-sim:local deployment/docker
AISIM_IMAGE=edumatcher-ai-sim:local docker compose -f deployment/docker/compose.ai-sim.yaml up -d
```

(Without a wheel in `deployment/docker/.wheel/`, the build installs the
latest `edumatcher` from PyPI.)
