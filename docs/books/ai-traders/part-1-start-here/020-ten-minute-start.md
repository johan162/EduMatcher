# Ten-Minute Start

!!! note "Learning objectives"
    After this chapter you will have:

    - A simulated exchange running, with its AI traders, market maker and news
    - The four browser applications open on it
    - Checked that it is healthy, and know how to stop and restart it

    **Prerequisites**: Docker (Docker Desktop on macOS and Windows) or Podman
    with `podman compose`; about 2 GB of free memory and 4 GB of free disk (for a month's running).

There are two ways to run the simulation. The **container** is the one this
chapter uses: one file, one command, the browser applications included.
The **hand-built** way runs the same processes straight on your machine with
`pipx`; it is in [A Complete Set-up by Hand](../part-3-run-it/100-a-complete-setup-by-hand.md).

## Get the compose file

The simulation is one compose file, `compose.ai-sim.yaml`. Everything else —
the exchange, its configuration, the AI traders, the browser applications —
comes in images from the GitHub Container Registry.

```bash
mkdir edumatcher-sim && cd edumatcher-sim
curl -fsSLO https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/docker/compose.ai-sim.yaml
```

!!! tip "From a clone of the repository"
    The same file is `deployment/docker/compose.ai-sim.yaml`. There,
    `make up-sim` does the next step ([Start it](#start-it)) and `make down-sim` stops it again.

## Start it

```bash
docker compose -f compose.ai-sim.yaml up -d
```

(With Podman: `podman compose -f compose.ai-sim.yaml up -d`, and `podman`
for `docker` in every command of this book.) The first start
downloads five images. Then:

```text
 ✔ Container edumatcher-sim               Started
 ✔ Container edumatcher-sim-terminal-gui  Started
 ✔ Container edumatcher-sim-book-gui      Started
 ✔ Container edumatcher-sim-log-gui       Started
 ✔ Container edumatcher-sim-trader-gui    Started
```

The exchange deploys its configuration and starts its processes; give it
half a minute.

**Checkpoint.** Ask the exchange for its process table:

```bash
docker exec edumatcher-sim pm-opctl-cli list --no-restart
```

Every row should say `running` (a gateway may say `not responding` for the
first few seconds while it binds its port). The last three rows are the
simulation: `mm-bot`, `market-sim` and `ai-swarm`.

!!! note "Is the market open?"
    The simulation keeps real trading hours: 09:00–16:05 Stockholm time,
    Monday to Friday, closed on Swedish public holidays. Outside those hours
    everything runs but nothing trades; the books show the last day's
    closing state. To see trading right now, whatever the time, use
    [See a trading day now](#see-a-trading-day-now).

## Open the browser applications

| Application | Address | Shows |
|---|---|---|
| **terminal-gui** | <http://localhost:8090> | A market-data terminal: watchlists, quotes, charts, the news |
| **book-gui** | <http://localhost:8094> | One symbol's order book, level by level, live |
| **log-gui** | <http://localhost:8091> | The log of every process, searchable |
| **trader-gui** | <http://localhost:8093> | A trading screen — log in as a student desk |

The trader-gui asks for an API key. The simulation's desks and their keys:

| Participant | Role | API key |
|---|---|---|
| `TRADER01` | student desk | `key-trader01-rwlr0v` |
| `TRADER02` | student desk | `key-trader02-uzytnc` |
| `TRADER03` | student desk | `key-trader03-rwqo7n` |
| `TRADER04` | student desk | `key-trader04-3etdg0` |
| `TRADER05` | student desk | `key-trader05-k0c8fm` |
| `TRADER06` | student desk | `key-trader06-xcv14m` |
| `TRADER07` | student desk | `key-trader07-8b5rdy` |
| `TRADER08` | student desk | `key-trader08-8ndd87` |
| `TRADER09` | student desk | `key-trader09-b3bj7h` |
| `TRADER10` | student desk | `key-trader10-m1men1` |
| `OPS01` | instructor (ADMIN) | `key-ops01-3e34rs` |

!!! warning "These keys are public"
    They are in the bundled example and in this book. The compose file
    publishes the exchange on `127.0.0.1` only, so nobody else can reach it.
    Before you open it to a network, read
    [The Simulation Container](../part-3-run-it/110-the-simulation-container.md#opening-it-to-a-classroom).

**Checkpoint.** During trading hours, terminal-gui's watchlist ticks and
book-gui's book for `AAPL` changes every second or two.

## Look at the hidden value

The true values are secret from students, but not from the instructor. In
the container, as `OPS01`:

```bash
docker exec edumatcher-sim pm-market-sim --status --id OPS01
```

During trading this lists the symbols whose price is furthest from their
true value:

```text
pm-market-sim: RUNNING seq=1843 symbols=300 open_rumours=1
symbol        value        mid  mid/value
DXCM          84.12      85.31     +1.41%
...
```

Outside trading hours it says `PAUSED` and shows no values. The gap column
is the whole point of the simulation; [The True Value](../part-2-how-it-works/030-the-true-value.md)
explains it.

## See a trading day now

To watch a day without waiting for 09:00, restart the simulation with an
accelerated clock that starts just before the open:

```bash
docker compose -f compose.ai-sim.yaml down
EM_SPEED=10 EM_START=2026-11-02T08:58 docker compose -f compose.ai-sim.yaml up -d
```

`EM_START` is a Monday morning; `EM_SPEED=10` runs the calendar ten times
faster than the clock on the wall. The pre-open starts within seconds, the
opening auction two and a half minutes later, continuous trading half a
minute after that, and the whole trading day takes about 42 minutes.
[Accelerated Time](../part-3-run-it/120-accelerated-time.md) explains what
changes and what does not.

To go back to real hours:

```bash
docker compose -f compose.ai-sim.yaml down
docker compose -f compose.ai-sim.yaml up -d
```

## Stop it, start it again

```bash
docker compose -f compose.ai-sim.yaml down     # stop and remove the containers
docker compose -f compose.ai-sim.yaml up -d    # start again where it left off
```

Everything the exchange has recorded — trades, statistics, logs, the model's
values, the traders' daily results — is in `./data-sim` next to the compose
file and survives `down`. The containers restart on their own after a reboot
(`restart: unless-stopped`). To start from scratch, stop it and delete
`./data-sim`.

## What you have now

A market that will keep trading every weekday for as long as the machine is
on. The rest of the book explains what you are looking at and how to change
it. If you only read one more chapter, read
[The True Value](../part-2-how-it-works/030-the-true-value.md).

## If something does not work

| You see | Do |
|---|---|
| `pull access denied` or `manifest unknown` | The image for that version is not published yet: pin one that is with `EM_VERSION=<version>`, or build it — [The Simulation Container](../part-3-run-it/110-the-simulation-container.md#building-the-image-yourself) |
| `port is already allocated` | Another EduMatcher stack (or anything else) holds 5560–5600, 8080/8081 or 8090–8094. Stop it first; only one stack can run at a time |
| The process table shows `dead` | Wait a minute: the container restarts dead processes once a minute. If it stays dead, see [Troubleshooting](../part-4-watch-and-teach/160-troubleshooting-and-faq.md) |
| No trading during the day | Check the time zone: the clock is Stockholm's. `docker exec edumatcher-sim date` |
