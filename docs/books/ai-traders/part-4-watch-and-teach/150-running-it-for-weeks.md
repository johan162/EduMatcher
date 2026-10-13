# Running It for Weeks

!!! note "Learning objectives"
    After reading this chapter you will be able to:

    - Prepare the simulation to run unattended for a month or more
    - Say what grows on disk, by how much, and where it stops growing
    - Check its health in a minute a day, and know what the container repairs
      by itself
    - Back it up, upgrade it and restart it without losing the market's history

## Before you leave it

| Check | Why |
|---|---|
| **Pin the version**: `EM_VERSION=<release>` in `.env` | `latest` changes with every release; a restart would bring a different exchange |
| **Free disk**: at least 4 GB for 30 days | See [What grows](#what-grows) |
| **The machine stays awake** | A laptop that sleeps stops the market; nothing trades while it sleeps, and the day's schedule resumes when it wakes |
| **Docker starts at boot** (Docker Desktop: *Start when you sign in*; Linux: `systemctl enable docker`) | The containers restart after a reboot only if Docker itself does |
| **Time zone** is what you want (`TZ`, default `Europe/Stockholm`) | The trading hours follow it |
| **`EM_START` is not set** | It would send the calendar back at every restart |

## What the container repairs by itself

| Event | What happens |
|---|---|
| A process dies | Restarted within a minute; the container log notes it (`docker logs edumatcher-sim`). The market maker can take up to four: the engine keeps its old session until it misses three heartbeats, a minute apart, and refuses the new one until then |
| The container dies or the machine reboots | Docker restarts it (`restart: unless-stopped`); the exchange redeploys nothing, keeps its data and starts the profile again |
| The engine restarts during trading | The AI traders and the market maker log on again; the engine restarts flat (positions from zero, GTC orders restored) and `CLOSED`. The scheduler does not notice: during the trading day the market stays closed until you restart it with `docker exec edumatcher-sim pkill -f pm-scheduler` (the watchdog starts it again within a minute, and it catches up to the current phase) |
| The market model restarts | It continues from the values it saved at most 10 seconds earlier |
| Daylight saving time changes | The scheduler re-reads the wall clock every few minutes; the next phase happens at the right local time |
| A holiday | No trading that day; nothing to do |

## What grows

Measured with the `s300-sim` set-up at real speed on a 2-vCPU machine: the
growth over continuous trading at the swarm's steady 80 actions a second
(about 1,400 trades a minute), scaled to a 6.5-hour trading day. Your numbers
will be close if you keep the example's budget; they scale with it. "7 days"
are calendar days, so about five trading days are kept.

| File | Per trading day | Kept | Stops growing at |
|---|---|---|---|
| `stats.db` — trades and price snapshots | about 85 MB | 7 days | about 0.45 GB |
| `stats.db` — order events | about 250 MB an hour | the last 72 minutes (`--keep-order-events-days 0.05`) | about 0.3 GB, within the first trading day |
| `stats.db` — daily statistics | about 30 KB | for good | — (about 1 MB a month) |
| `clearing.db` — trades | about 155 MB | 7 days, pruned at every close | about 0.8 GB |
| `clearing.db` — positions and daily summaries | a few hundred KB | for good | — |
| `log.db` | about 5 MB | 30 days | about 150 MB |
| `audit.log*` | far more than it keeps | the last 60 MB | 60 MB |
| `ai_swarm/*.jsonl` | about 30 KB | for good | — |
| `emo/*.log` | a few KB | for good | — |

**Projected for 30 calendar days (21–22 trading days): about 2 GB in
`./data-sim`.** Most of it is there after the first week; after that only the
log (until day 30) and the small daily files grow.

!!! note "Why the audit trail is so short"
    The audit trail records every message on the exchange's bus. In this
    market that is tens of megabytes a minute, so the 60 MB it keeps (six
    10 MB files) cover only the last few minutes of trading. It is there to
    investigate what just happened, not to keep history; the statistics
    database and the swarm's daily summaries keep the history.

**Disk at a faster calendar.** The exchange's work — and so the growth — is
per wall-clock second, not per trading day. At `EM_SPEED=24` a trading day
writes a twenty-fourth of the table above, but 24 of them pass in a day —
and the share of the wall-clock time spent trading is the same at any speed
(6.5 hours of every 24, less weekends). So the disk fills at the same rate
per real day at any speed.

## A minute a day

From the repository's `deployment/docker` (or with the commands it wraps):

```bash
make sim-status
```

```text
pm-opctl profile: ai-sim
...
data: 1.2G   disk free: 41G
```

Look for:

1. every process `running`;
2. the disk free comfortably above what the next weeks need;
3. once a week, `./edumatcher.sh logs edumatcher | grep Restarting` — the same
   process restarting every day is worth a look in its log;
4. one daily summary file per trading day in `data/ai_swarm/`.

## Backups

The whole state is the install's `data` directory. To copy it consistently,
stop first:

```bash
./edumatcher.sh stop
tar czf sim-backup-$(date +%F).tgz data
./edumatcher.sh start
```

The market is closed at night and at weekends — a good time. To restore,
stop, replace `data` with the backup's, start.

## Upgrading during a run

```bash
./edumatcher.sh update          # the newest release
./edumatcher.sh update 0.51.0   # ...or an exact one
```

Do it while the market is closed. The data directory is kept; the deployed
configuration stays as it was (a new release's version of `s300-sim` is
deployed only on a fresh data directory). If you wrote the profiles out with
`pm-opctl-cli init`, your `emo-config.yaml` keeps the old profiles too:
compare it with the new release's built-in ones
(`docker exec -e EDUMATCHER_DATA_DIR=/tmp/scratch edumatcher-sim pm-opctl-cli init`
writes them to `/tmp/scratch/emo-config.yaml` in the container, away from
yours).

## The evidence

The numbers in this chapter come from runs of the `edumatcher-ai-sim` set-up
recorded in the repository (`docs-design/reviews/ai-sim/`): a soak covering
34 trading days at accelerated speed (`EM_SPEED=600`, under two hours), with
every daily summary written, memory within 5 % of where it started, and the
market maker killed once on purpose and back in under three minutes; and
real-time runs for the CPU and disk figures.
