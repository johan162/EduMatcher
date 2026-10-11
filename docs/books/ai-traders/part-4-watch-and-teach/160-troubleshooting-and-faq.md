# Troubleshooting and FAQ

## When something does not work

| You see | Likely cause | Do |
|---|---|---|
| `pull access denied` / `manifest unknown` on `up` | The release you asked for (`EM_VERSION`, or `latest`) has no `edumatcher-ai-sim` image | Pin a release that has one, or [build it yourself](../part-3-run-it/110-the-simulation-container.md#building-the-image-yourself) |
| `port is already allocated` | Another EduMatcher stack, or another program, holds 5560–5600, 8080/8081 or 8090–8094 | Stop the other stack (`make down-all`, `./edumatcher.sh stop`); only one can run |
| Nothing trades | The market is closed: weekend, a Swedish holiday, or outside 09:00–16:05 Stockholm time | `docker exec edumatcher-sim date`; for trading now, [accelerated time](../part-3-run-it/120-accelerated-time.md) |
| The market closed in the middle of the day and stays closed | The engine restarted (it starts `CLOSED`) and the running scheduler did not notice | `docker exec edumatcher-sim pkill -f pm-scheduler`: the container restarts it within a minute and it catches up to the current phase |
| Trading starts at the wrong hour | The container's time zone is not the one you think | `TZ` in `.env` (default `Europe/Stockholm`) |
| `mm-bot` is `dead` right after a start | It started before the engine was ready and gave up | Nothing: the container restarts it within a minute |
| `mm-bot` restarted several times in a row after it died | The engine still holds the dead bot's session and refuses a second one for `MM01` | Nothing: the engine drops that session after three missed heartbeats, about three minutes, and the next restart logs on |
| A process keeps coming back as `dead` | It fails at start | Its console output: `docker exec edumatcher-sim tail -50 /data/emo/<name>.log`; and the Log Operator Console |
| `ai-swarm` dead, `ai-swarm.log` says a participant is missing | The deployed configuration does not register `AI001`–`AI100` (you deployed another one) | Deploy `s300-sim` or a configuration with those participants |
| `market-sim` dead, log says `no …/market_sim.yaml` | The deployed configuration came without a market model | Put a `market_sim.yaml` next to your `engine_config.yaml` and deploy again |
| Value and news traders send nothing | `pm-market-sim` is not running | `pm-opctl-cli list`; see the row above |
| Unknown profile `ai-sim` | `emo-config.yaml` in the data directory was written by an older release and replaces the built-in profiles | Delete `./data-sim/emo-config.yaml` (or add an `ai-sim` profile to it) and restart |
| Swarm logs `cancel … never answered` steadily, `actions/s` far below budget | The machine is overloaded: the exchange cannot keep up | Lower `budget` ([Tuning the Traders](../part-2-how-it-works/060-tuning-the-traders.md#the-swarm)); check `docker stats` |
| The GUIs show no history, Order Book Viewer empty | The read-only API key does not match the deployed configuration | With your own configuration, set `PM_READONLY_API_KEY` to its read-only key (`pm-config-show -a`) |
| `./data-sim` keeps growing | Expected: trades are kept 7 days and the log 30 days, so it grows quickly for the first week, slowly until day 30, then levels off | [Running It for Weeks](150-running-it-for-weeks.md#what-grows) |
| After a restart the accelerated calendar went back in time | `EM_START` applies at every start | Remove `EM_START` after the first start ([Accelerated Time](../part-3-run-it/120-accelerated-time.md#traps)) |
| Prices drift far from the values | The market maker is not anchored, or there are too few value traders per symbol | `--anchor-sim`, the composition, `per_agent` ([Tuning the Traders](../part-2-how-it-works/060-tuning-the-traders.md)) |

## FAQ

**Can students see the true values?** No. The values travel on the market
model's own sockets, bound inside the container, and the API serves them to
ADMIN keys only. Headlines are public; their impact on the values is not.

**Can students lose money to the bots?** Yes — that is the point. The AI
traders are participants like the students, and the informed ones trade on
better information. The P&L is play money.

**Can I trade against the AI traders with my own program?** Yes. Connect as
one of `TRADER01`–`TRADER10` through the API (port 8080) or the order
gateway (5565), exactly as on any EduMatcher exchange; the Protocols and
Clients book describes both.

**Do the AI traders learn?** No. Each follows its preset's fixed rules with
its own random choices. What changes from day to day is the market — the
values, the news, the other traders — not the rules.

**Is a run repeatable?** The model is seeded (`seed` in `market_sim.yaml`)
and so are the traders (`seed` in `swarm.yaml`), but the order in which
messages from a hundred traders reach the engine depends on timing, so two
runs diverge within seconds. The *statistics* of a run — how far prices
stray, how much each kind of trader makes — are repeatable; the exact
prices are not.

**How do I start over?** Stop the stack, delete `./data-sim`, start it.

**How do I give the market a fresh set of values without losing the
history?** Stop the stack, delete `./data-sim/market_sim_state.json`, start
it: the model starts again from the engine's previous closes.

**Why is there no trading at 09:00 on a Monday in January?** Swedish public
holidays — Epiphany, 6 January, for one — are closed days on the
`s300-sim` calendar. Use your own configuration's `locale.country` and `holidays`
settings to change the calendar.

**Can I run it in the cloud?** Yes; any machine with Docker and two cores
will do. Mind the [classroom security notes](../part-3-run-it/110-the-simulation-container.md#opening-it-to-a-classroom)
before you publish the ports.

**Can I run two simulations side by side?** Not with the bundled compose
file: both would want the same ports. Copy it, change every host port and
the project and container names, and use a different data directory.
