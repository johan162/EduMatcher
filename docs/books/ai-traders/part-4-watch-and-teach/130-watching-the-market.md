# Watching the Market

!!! note "Learning objectives"
    After reading this chapter you will be able to:

    - Use each browser application to watch the simulated market
    - Use the command-line tools inside the container for what the browser
      does not show: the values, the traders' activity, the logs
    - Read the AI traders' daily results and say which kind of trader is
      winning

    **Prerequisites**: [Ten-Minute Start](../part-1-start-here/020-ten-minute-start.md).

## The four windows

| Application | Address | Watch it for |
|---|---|---|
| **TapeDeck** (terminal-gui) | <http://localhost:8090> | The whole market at a glance: movers, the trade tape, sessions and halts, the news |
| **Order Book Viewer** (book-gui) | <http://localhost:8094> | One symbol's book, price level by price level, with its tape |
| **Trading GUI** (trader-gui) | <http://localhost:8093> | Trading as a student desk; the instructor's screens with the `OPS01` key |
| **Log Operator Console** (log-gui) | <http://localhost:8091> | What every process is doing; warnings and errors |

Each has its own chapter in the Participant or Operator's Guide (see
[See also](#see-also)); here is what to look at in a simulated market.

### TapeDeck: the market at a glance

Put it on the classroom screen. The **Market Overview** and **Movers** show
which of the 300 shares are moving; a share that moved a lot with no
headline in the **News** view probably jumped (an unannounced change in its
value), or is being pushed by momentum traders. The **Trade Tape** shows who
traded: `AI` ids are the swarm, `MM01` the market maker, `TRADER` ids your
students. During the auctions the **Session & Halt Status Board** counts
down to the next phase.

### Order Book Viewer: one book up close

Pick a symbol and watch for a minute:

- The market maker's quotes are the 200-share levels 20 cents apart, around
  the middle of the book. When one is filled, that side stays empty for
  about 5 seconds, until the bot posts a fresh pair.
- The AI traders' orders are everything else: small passive orders from the
  noise traders near the touch, larger ones from value investors and
  institutions, an iceberg showing a fifth of its size.
- After a headline the book empties on one side within seconds as news
  traders sweep it, then refills at the new price.

### Trading GUI: trade in it

Students log in with their desk keys
([Ten-Minute Start](../part-1-start-here/020-ten-minute-start.md#open-the-browser-applications))
and trade like any participant: their orders meet the AI traders' orders in
the same books. Logged in as `OPS01` you get the operator's screens —
session control, halts, the kill switch — the same as on any exchange. Use
them carefully on a market that is meant to keep running: a halted symbol
stays halted until you resume it.

### Log Operator Console: what the processes say

Filter by process. `pm-ai-swarm` writes one status line a minute and a
summary after each close; `pm-market-sim` logs every headline it publishes;
`pm-scheduler` every phase change. Warnings are worth a look; a steady trickle
of `cancel … never answered` from the swarm means the exchange is
overloaded (see [Troubleshooting](160-troubleshooting-and-faq.md)).

## The command line

Everything below runs inside the exchange container. Either prefix each
command with `docker exec edumatcher-sim`, or open a shell there once —
`docker exec -it edumatcher-sim bash` — and type them as shown. (By hand,
without the container, type them in any terminal with
`EDUMATCHER_DATA_DIR` set.)

### Is everything running?

```bash
pm-opctl-cli list --no-restart
```

One row per process, with its uptime and memory. `dead` rows are restarted
by the container within a minute.

### What is the market doing?

```bash
pm-log-cli query --process pm-ai-swarm --grep "actions=" --limit 3
```

```text
[w1-AI001-AI100] t=480s session=CONTINUOUS actions=58029 (120.9/s) live_orders=2325 fills=27616 rejects=25
[w1-AI001-AI100] t=900s session=CONTINUOUS actions=91317 (101.4/s) live_orders=2368 fills=38669 rejects=25
```

`actions` counts new orders and cancels since the swarm started, and the rate
in brackets is the average over that whole time, closed hours included. For
the current rate, take two lines: (91317 − 58029) / (900 − 480) is 79 a
second, the swarm's budget of 80. `live_orders` is how many orders the
traders have working; `rejects` should stay a tiny share of the actions.

```bash
pm-board                 # a rotating board of symbols: last, change, volume
pm-viewer -s AAPL        # one order book in the terminal
pm-ticker                # a scrolling ticker of the day's prices
```

### How far from the values?

```bash
pm-market-sim --status --id OPS01
```

lists the shares whose prices are furthest from their true values (see
[The True Value](../part-2-how-it-works/030-the-true-value.md#how-close-does-the-market-get)).

### The news

```bash
pm-news list            # headlines as they are published (Ctrl+C to stop)
```

### The day's statistics

```bash
pm-stats-cli daily --symbol AAPL                    # open, high, low, close, volume per day
pm-stats-cli trades --symbol AAPL --limit 10        # the last trades
pm-stats-cli dates                                  # the trading dates recorded
```

`pm-stats` keeps the daily rows for good and individual trades for the last
seven days ([Running It for Weeks](150-running-it-for-weeks.md)).

## Who made money

After each close (five seconds after, so the closing auction's fills are in)
the swarm writes one line per trader to
`/data/ai_swarm/<date>-<worker>.jsonl` — on the host,
`./data-sim/ai_swarm/`:

```json
{"closed_at": "2026-11-03T15:05:05+00:00", "day": 2, "agent": "AI007",
 "preset": "value-investor", "submitted": 412, "fills": 233, "filled_qty": 9120,
 "cancels": 160, "rejected": 0, "killed": 0, "unseen_expiries": 0,
 "gtc_orders": 0, "gross_position": 1840, "pnl_realized": 412.10, "pnl_mtm": 87.40}
```

The counters are for that day; the profit and loss (`pnl_realized`, made on
closed positions, and `pnl_mtm`, on the open position at the last price)
since the trader last started. To total the latest P&L by kind of trader:

```bash
python3 - <<'EOF'
import glob, json
latest = {}
for path in sorted(glob.glob("/data/ai_swarm/*.jsonl")):
    for line in open(path):
        row = json.loads(line)
        latest[row["agent"]] = row
by_preset = {}
for row in latest.values():
    pnl = row["pnl_realized"] + row["pnl_mtm"]
    total, n = by_preset.get(row["preset"], (0.0, 0))
    by_preset[row["preset"]] = (total + pnl, n + 1)
for preset, (total, n) in sorted(by_preset.items(), key=lambda kv: -kv[1][0]):
    print(f"{preset:16} {n:3} traders  P&L {total:12.2f}  per trader {total / n:10.2f}")
EOF
```

In a market like `s300-sim` the informed traders — value investors,
institutions, news traders — usually come out ahead, and the noise and
momentum traders behind: that is what being informed is worth. If the
order flips, the market is giving the uninformed an edge — worth a look at
the settings ([Tuning the Traders](../part-2-how-it-works/060-tuning-the-traders.md)).
It makes a good class discussion either way: who paid whom, and why.

## For the instructor: the values through the API

The values are available to ADMIN keys through the API gateway, for your own
dashboards and scripts:

```bash
curl -s -H "Authorization: Bearer key-ops01-9yn0rc" \
    http://localhost:8080/api/v1/admin/sim
```

returns the model's state and every share's latest value; the WebSocket
`ws://localhost:8080/api/v1/admin/sim` streams them. Students' keys are
refused.

## See also

- [TapeDeck](../../participant-guide/part-6-front-ends/010-trading-info-terminal.md),
  [the Trading GUI](../../participant-guide/part-6-front-ends/020-trading-platform-gui.md),
  [the Order Book Viewer](../../participant-guide/part-6-front-ends/030-order-book-gui.md),
  [the Log Operator Console](../../operator-guide/part-6-observe-and-recover/050-log-console.md)
- [AI Traders & News](../../training-guide/140-ai-traders.md) — classroom exercises
- [Running the AI-Trader Swarm](../../operator-guide/part-3-run/030-ai-trader-swarm.md#logs-and-daily-summaries) — the swarm's logs and summaries in full
