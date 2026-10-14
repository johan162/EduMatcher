# A Complete Set-up by Hand

!!! note "Learning objectives"
    After reading this chapter you will be able to:

    - Run the whole simulation straight on your machine, without containers
    - Name every process it runs and what each one is for
    - Find every file it reads and writes
    - Make your own variant of the simulation — other symbols, other traders,
      another market model — and run it

    **Prerequisites**: Python 3.13 and `pipx`
    ([Quick Start: Install and Start](../../quick-start/part-1-see-it-run/020-install-and-start.md)
    covers installing them).

The container in [Ten-Minute Start](../part-1-start-here/020-ten-minute-start.md)
is this chapter packaged. Doing it by hand takes a few more commands, but you
see every part, and you can change anything.

## Install and start

```bash
pipx install edumatcher
export EDUMATCHER_DATA_DIR=~/edumatcher-sim     # where everything is kept
pm-setup --config s300-sim                      # deploy the example
pm-opctl-cli start ai-sim                       # start the 17 processes
```

`pm-setup --config s300-sim` creates the data directory and deploys the
bundled `s300-sim` example into it: the engine configuration and the market
model's `market_sim.yaml`. `pm-opctl-cli start ai-sim` starts the process
profile. Every `pm-*` command finds the data directory through
`EDUMATCHER_DATA_DIR`, so set it in every terminal you use (or in your shell
profile).

**Checkpoint.**

```bash
pm-opctl-cli list
```

prints one row per process; all should be `running` within half a minute.
If `mm-bot` shows `dead`, it started before the engine was ready — answer
`y` when `list` offers to restart it (the container does this by itself).

!!! warning "Time zone"
    The scheduler follows your computer's local clock. `s300-sim` keeps
    09:00–16:05 on the Swedish calendar; outside Sweden, start the profile
    with `TZ=Europe/Stockholm pm-opctl-cli start ai-sim` to keep Stockholm
    hours, or leave it and trade 09:00–16:05 *your* time.

To stop everything:

```bash
pm-opctl-cli stop
```

## Accelerated time by hand

The scheduler reads two environment variables (the container sets them from
`EM_SPEED` and `EM_START`):

```bash
EDUMATCHER_SCHEDULER_SPEED=24 EDUMATCHER_SCHEDULER_START=2026-11-02T08:55 \
    pm-opctl-cli start ai-sim
```

[Accelerated Time](120-accelerated-time.md) explains what this does.

## What runs

The `ai-sim` profile is the full exchange plus three simulation processes.
`pm-opctl-cli show` prints where the profiles are defined; this is what it
starts:

| Process | Command | Role |
|---|---|---|
| `log` | `pm-log-srv` | Collects every process's log into `log.db` (kept 30 days) |
| `audit` | `pm-audit --verbose` | The audit trail of every message, `audit.log` |
| `stats` | `pm-stats --verbose --keep-days 7 --keep-order-events-days 0.05` | Daily statistics (kept for good), every trade (kept 7 days) and every order event (kept about an hour) in `stats.db` |
| `clearing` | `pm-clearing --verbose --print-every 0 --retention-days 7` | Positions and settlement, `clearing.db`: a week of individual trades (pruned at every close), daily summaries for good; without its console P&L table, which it would redraw every 100 trades |
| `engine` | `pm-engine` | Matching: the 300 order books |
| `scheduler` | `pm-scheduler --daily --verbose` | The trading calendar |
| `market-data-gwy (md-gwy)` | `pm-md-gwy --verbose` | Market data for terminal-gui and other clients |
| `post-trade-gwy (ralf-gwy)` | `pm-ralf-gwy --verbose` | Post-trade feed |
| `drop-copy-gwy (dc-gwy)` | `pm-dc-gwy --verbose` | Drop copies |
| `api-desk-gwy (api-gwy)` | `pm-api-gwy --verbose --instance desk` | REST/WebSocket API for trading (port 8080) |
| `api-dashboards-gwy (api-gwy)` | `pm-api-gwy --verbose --instance dashboards` | Read-only API for the GUIs (port 8081) |
| `alf-gwy` | `pm-alf-gwy --verbose` | The order gateway the AI traders and trader consoles use |
| `balf-gwy` | `pm-balf-gwy --verbose` | The binary order gateway |
| `index-srv` | `pm-index --verbose` | Index calculation |
| `mm-bot` | `pm-mm-bot --gateway-id MM01 --all-symbols --strategy symmetric --gap 0.20 --qty 200 --reissue-delay-ms 5000 --drift-ticks 15 --anchor-sim 0.3` | The market maker, anchored to the true values |
| `market-sim` | `pm-market-sim --verbose` | The market model: true values and news |
| `ai-swarm` | `pm-ai-swarm --swarm <examples>/s300-sim-setup/swarm.yaml --verbose` | The hundred AI traders |

The engine runs without `--verbose` here: with it, it logs every order it
accepts, which on this market is tens of millions of log lines a month.

## Where everything is

Everything lives under `$EDUMATCHER_DATA_DIR` (`/data` in the container,
`./data-sim` on its host):

| Path | What | Grows? |
|---|---|---|
| `ref_data/engine_config.yaml`, `engine_config.json` | The deployed configuration (source and compiled) | no |
| `ref_data/market_sim.yaml` | The deployed market model | no |
| `market_sim_state.json` | The model's current values, saved every 10 s | no |
| `market_sim_news.db` | Published news and rumour events queried by `pm-news past` | grows with each event |
| `emo/` | `pm-opctl` PID files and each process's console output (`<name>.log`) | slowly |
| `log.db` | Every process's log | up to 30 days, then flat |
| `audit.log`, `audit.log.1`–`.5` | The audit trail, rotated at 10 MB | capped at 60 MB |
| `stats.db` | Daily statistics; trades, order events, snapshots | rollups forever, trades and snapshots 7 days, order events about an hour |
| `clearing.db` | Clearing events and positions | trades 7 days, daily summaries and positions for good |
| `ai_swarm/<date>-<worker>.jsonl` | Each AI trader's results, one line per trader per day | about 50 KB a day |
| `gtc_orders.json`, `gtc_combos.json` | Orders that survive the close | no |

[Running It for Weeks](../part-4-watch-and-teach/150-running-it-for-weeks.md)
has the measured sizes.

## Your own variant

The bundled example is read-only; make a copy and change that. Find it with
the Python of the environment `pipx` installed EduMatcher into:

```bash
EM_PY="$(pipx environment --value PIPX_LOCAL_VENVS)/edumatcher/bin/python"
"$EM_PY" -c "from edumatcher.config_deploy import examples_root; print(examples_root())"
```

and copy its `s300-sim-setup` directory:

```bash
cp -r "$("$EM_PY" -c 'from edumatcher.config_deploy import examples_root; print(examples_root())')/s300-sim-setup" ~/my-sim
```

| File | Change it to change | Deploy with |
|---|---|---|
| `engine_config.yaml` | Symbols, participants, the trading hours, the market maker's obligations | `pm-config-deploy ~/my-sim/engine_config.yaml` |
| `market_sim.yaml` | Volatility, correlation, jumps, news rates ([The True Value](../part-2-how-it-works/030-the-true-value.md), [News and Rumours](../part-2-how-it-works/040-news-and-rumours.md)) | the same command: it deploys the `market_sim.yaml` beside the engine configuration too |
| `swarm.yaml` | How many traders, which kinds, how busy ([Tuning the Traders](../part-2-how-it-works/060-tuning-the-traders.md)) | point the profile at it (below) |

The profile is the one piece that is not a file yet. Write the built-in
profiles out, so you can edit them:

```bash
pm-opctl-cli init          # writes $EDUMATCHER_DATA_DIR/emo-config.yaml
```

In `emo-config.yaml`, find the `ai-sim` profile's `ai-swarm` entry and
change its `--swarm` path to `~/my-sim/swarm.yaml` (spelled out in full —
`/home/you/my-sim/swarm.yaml`). From now on `pm-opctl-cli` uses that file's
profiles instead of the built-in ones; the market maker's flags, the
retention of `pm-stats` and everything else are yours to edit there too.

Then restart:

```bash
pm-opctl-cli stop
pm-opctl-cli start ai-sim
```

!!! tip "Change one thing at a time"
    Restart, watch a trading day, compare. [Tuning the Traders](../part-2-how-it-works/060-tuning-the-traders.md)
    says what each setting is expected to do and how to see it.

## Running the pieces one at a time

To see how the parts fit, start the trading core yourself, each command in
its own terminal (with `EDUMATCHER_DATA_DIR` set):

```bash
pm-engine
pm-alf-gwy -v
pm-scheduler --daily -v
pm-market-sim -v
pm-mm-bot --gateway-id MM01 --all-symbols --strategy symmetric --gap 0.20 \
    --qty 200 --reissue-delay-ms 5000 --drift-ticks 15 --anchor-sim 0.3
pm-ai-swarm --swarm ~/my-sim/swarm.yaml -v
```

That is a trading market without statistics, clearing, audit or the GUIs'
APIs. Stop the swarm and the market keeps its quotes; stop the market maker
and watch the books thin out and the prices drift from the values; stop `pm-market-sim` and watch the value and
news traders fall silent.
