# FAQ: Setup and Operation

Questions about running an exchange beyond the first start: seed quotes,
the scheduler, watching the message bus, participant allowlists, and where the
configuration and data files live. The first-day questions are in the Quick
Start Guide's [FAQ & Common Mistakes](../../quick-start/90-backmatter/010-faq.md);
questions about orders and positions are in the Participant Guide's
[FAQ: Orders, Sessions and Positions](../../participant-guide/90-backmatter/010-faq-orders-and-positions.md).

## Starting the exchange

### Why did the seed MM quote disappear after the second day?

By default, `market_maker_quotes` entries have `seed_once: true`. This means the
seed is skipped whenever that market maker already has a live quote on the symbol
that was restored from the previous run. A quote that was traded away or that
expired is not restored, so its seed fires again; otherwise the real market maker
is expected to keep submitting its own quotes.

To inject the seed on every startup (e.g. for a repeatable classroom demo):

```yaml
market_maker_quotes:
  - gateway_id: MM01
    bid_price: 149.00
    ask_price: 151.00
    bid_qty: 500
    ask_qty: 500
    tif: DAY
    seed_once: false    # inject on every startup
```

To force a day-1 re-injection without changing the config:

```bash
rm data/book_stats.json    # or $EDUMATCHER_DATA_DIR/book_stats.json
```


### Why did `pm-scheduler` exit immediately?

Because no configuration is deployed. The scheduler exits with a fatal error
rather than falling back to its built-in default times — running a timetable
the engine has never seen is worse than not starting at all.

```bash
pm-config-deploy engine_config.yaml
```


---

## Seeing what is happening

### How do I see what messages are flowing between processes?

Run `pm-audit --terminal` in a separate window. It subscribes to **all**
ZeroMQ messages and prints them to stdout, giving a full real-time trace of
every event in the system.


---

## Participants

### Why is my order rejected with "Gateway not authenticated"?

Your gateway ID is not in the engine's allowlist. Gateway IDs must be
pre-configured in `engine_config.yaml` under `participants`:

```yaml
participants:
    - id: GW01
      role: TRADER
      description: My first trader
```

Deploy the configuration (`pm-config-deploy`) and restart the engine after
editing it.


---

## Configuration and data files

### The engine says it cannot find its configuration. Where should the file be?

In exactly one place, always:

```
<EDUMATCHER_DATA_DIR>/ref_data/engine_config.json
```

| Mode | Data directory |
|---|---|
| **pipx installed** | `~/.local/share/edumatcher` |
| **Source checkout** | `<repo>/src/data/` |
| **Either** | `EDUMATCHER_DATA_DIR`, if set |

The message means nothing has been deployed there yet. Install a configuration
and the error goes away:

```bash
pm-config-deploy ~/my-session/engine_config.yaml
pm-config-deploy --show        # print the path it deployed to
```

There is no `--config` flag and no `EDUMATCHER_CONFIG` variable. Both used to
exist, and the reason they no longer do is that they let one process be
started against a configuration the rest of the exchange had never seen — the
resulting symptom (a gateway reporting no instruments while the engine happily
traded ten) gave no hint of the cause.


### Where are my data files stored?

Data files (`gtc_orders.json`, `stats.db`, `audit.log`, etc.) go to:

| Mode | Data directory |
|---|---|
| **pipx installed** | `~/.local/share/edumatcher` |
| **Source checkout** | `<repo>/src/data/` |
| **Either** | `EDUMATCHER_DATA_DIR` environment variable (highest priority) |

To isolate two sessions from each other, run each in its own directory and set
`EDUMATCHER_DATA_DIR` to a different path:

```bash
export EDUMATCHER_DATA_DIR=~/sessions/morning
pm-engine
```

