# Configuring & Starting Up

## Objective

By the end of this chapter you will have a working exchange with at least one
gateway and three tradeable symbols, ready to accept orders.
In addition you have become familiar with the three tools:

- **`pm-config-gen`** used to automatically generate configuration file based on options and flags. 
- **`pm-cverifier`**  used to verify an existing (possibly hand-crafterd) configuration file for errors or missing settings
- **`pm-config-deploy`** used to compile a verified configuration file and install it as the artifact `pm-engine`/`pm-scheduler` actually read

 


!!! abstract "Pre-reading in the User Guide"
    - [Configuration](../user-guide/010-configuration.md)
    - [Config Verifier](../user-guide/020-config-verifier.md)
    - [Running the Exchange](../user-guide/040-running-the-exchange.md)

## Prerequisites

- EduMatcher installed and `pm-setup` completed (see [00 — Installation & Setup](000-installation.md)).

## Background

EduMatcher requires two essential processes:

1. **pm-engine** — the matching engine.
2. **pm-scheduler** — drives session phase transitions.

A **gateway** (`pm-alf-console`) connects traders to the engine.

Neither process reads `engine_config.yaml` directly, and neither accepts a
config path on its command line. `engine_config.yaml` is the file *you*
author and edit; what they actually read is a **compiled artifact** at
`$EDUMATCHER_DATA_DIR/ref_data/engine_config.json`, produced by
`pm-config-deploy` (see [00 — Installation & Setup](000-installation.md) for
where that directory comes from). This chapter's exercises follow that exact
pipeline: author → verify → deploy → start.

The artifact carries its own tamper and staleness checks: every load
recomputes a SHA-256 over the artifact's own content and refuses to start if
it no longer matches what was recorded at compile time, and every process
separately checks the artifact's recorded hash of the *source* YAML against
the YAML currently on disk, warning (but still starting) if you edited the
source and forgot to redeploy. Exercise 12 walks through both.

 

## Exercise 1: Create a Minimal Configuration

Create a file called `engine_config.yaml` in your working directory:

```yaml
symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 150.00
    last_sell_price: 150.00
  MSFT:
    tick_decimals: 2
    last_buy_price: 420.00
    last_sell_price: 420.00
  TSLA:
    tick_decimals: 2
    last_buy_price: 250.00
    last_sell_price: 250.00

gateways:
  alf:
    - id: TRADER01
      description: "Alice — first trader"
      role: TRADER
    - id: TRADER02
      description: "Bob — second trader"
      role: TRADER
    - id: GW_ADMIN
      description: "Exchange operator"
      role: ADMIN
```

!!! note "Why `tick_decimals`, not `tick_size`"
    A symbol's price granularity is given as a **number of decimal places**,
    not a tick size: `tick_decimals: 2` means prices move in units of 0.01.
    The engine matches on integer ticks internally, which is why it is
    expressed this way.

    `last_buy_price` / `last_sell_price` seed the reference price used by the
    price-collar checks. Without them a symbol has no reference and its collar
    is never enforced — which is exactly the trap Chapter 11 Exercise 2 depends
    on avoiding.

    Keys the engine does not recognise — `tick_size`, `last_price`,
    `description` on a *symbol* — are silently ignored rather than rejected, so
    a typo here fails quietly. `pm-cverifier` in Exercise 3 is how you catch
    that.

:material-checkbox-blank-outline: **Checkpoint:** file saved, YAML is valid (no tabs!).

This file is only the **authored source** — nothing reads it yet. `pm-engine`
will not see any of this until you compile and install it with
`pm-config-deploy` in Exercise 5.

 

## Exercise 2: Generate a Config with pm-config-gen

Instead of writing YAML by hand, you can use the `pm-config-gen` helper to
scaffold a configuration. Try generating an equivalent config:

```bash
pm-config-gen \
  --symbols AAPL MSFT TSLA \
  --symbol-opts AAPL:tick_decimals=2 \
  --symbol-opts MSFT:tick_decimals=2 \
  --symbol-opts TSLA:tick_decimals=2 \
  --gateways TRADER01:TRADER TRADER02:TRADER GW_ADMIN:ADMIN \
  --static-band 0.10 \
  --dynamic-band 0.05 \
  --sessions-enabled \
  --output engine_config.yaml --force
```

This produces a ready-to-use `engine_config.yaml` with:

- Three symbols (AAPL, MSFT, TSLA) with 2-decimal tick precision.
- Two trader gateways and one admin gateway.
- Static and dynamic price collars pre-configured.
- Session schedule enabled (PRE_OPEN → CONTINUOUS → CLOSED).

Inspect the generated file:

```bash
cat engine_config.yaml
```

!!! tip "Dry-run mode"
    Add `--dry-run` to preview the output without writing a file:
    ```bash
    pm-config-gen --symbols AAPL MSFT TSLA --gateways TRADER01 --dry-run
    ```

!!! tip "Adding market-maker gateways"
    You can include MM gateways in the same command:
    ```bash
    pm-config-gen \
      --symbols AAPL MSFT TSLA \
      --gateways TRADER01 TRADER02 GW_ADMIN:ADMIN MM_AAPL_01:MARKET_MAKER \
      --enforce-mm-obligations \
      --output engine_config.yaml --force
    ```

:material-checkbox-blank-outline: **Checkpoint:** generated config matches the manual one; symbols and gateways present.

 

## Exercise 3: Validate the Config with pm-cverifier

Before starting runtime processes, verify the file:

```bash
pm-cverifier engine_config.yaml
```

Check the verdict and exit code:

```bash
echo $?
```

Expected for this chapter config:

- Verdict is `OK` or `WARN` (depending on optional sections you did or did not add).
- Exit code is `0` when there are no warnings/errors, `1` when warnings exist, and `2` when hard errors exist.

!!! tip "CI-style validation"
    Treat warnings as failures and emit machine-readable output:
    ```bash
    pm-cverifier --strict --format json engine_config.yaml
    ```

!!! tip "Focus only on actionable items"
    Hide info-level advisories while iterating:
    ```bash
    pm-cverifier --level warn engine_config.yaml
    ```

:material-checkbox-blank-outline: **Checkpoint:** you can run `pm-cverifier`, read the verdict, and interpret its exit code.

## Exercise 4: Practice Fixing Verifier Findings

Create a temporary broken config and use `pm-cverifier` to diagnose it:

```bash
cp engine_config.yaml engine_config.bad.yaml
```

Edit `engine_config.bad.yaml` and intentionally introduce two issues:

1. Remove the `GW_ADMIN` gateway entry.
2. Set one symbol's `tick_decimals` to an invalid value like `12`.

Run verifier:

```bash
pm-cverifier engine_config.bad.yaml
```

You should see at least:

- `M013` warning (no ADMIN gateway).
- `S010` error (invalid `tick_decimals`).

Now fix the file and rerun until verdict is `OK` or your expected warning-only state.

:material-checkbox-blank-outline: **Checkpoint:** you can reproduce a verifier finding, map it to a check code, and clear it by fixing the config.

## Exercise 5: Compile and Deploy the Config with pm-config-deploy

Verified YAML is still just a file on disk — no process reads it until it is
compiled and installed. Check that it compiles without installing anything:

```bash
pm-config-deploy --check engine_config.yaml
```

Expected output:

```
OK — engine_config.yaml compiles (3 symbol(s), 3 gateway(s))
```

Now actually deploy it:

```bash
pm-config-deploy engine_config.yaml
```

Expected output:

```
Compiled engine_config.yaml
      to /Users/you/.local/share/edumatcher/ref_data/engine_config.json
   3 symbol(s), 3 gateway(s).
   Restart any running processes to pick it up.
```

Confirm where it landed:

```bash
pm-config-deploy --show
ls -la "$EDUMATCHER_DATA_DIR/ref_data"
```

Expected behavior:

- `--check` validates and reports symbol/gateway counts but writes nothing
- deploying overwrites the previous `ref_data/engine_config.json` atomically —
  a process reading it mid-deploy sees either the old configuration or the
  new one, never a half-written file
- if `engine_config.yaml` fails validation, deploy fails and prints
  `[ERROR] ...` followed by `Nothing was deployed.`; any previous deployment
  is left untouched
- deploying does **not** restart any already-running `pm-engine`/`pm-scheduler`
  — they must be (re)started to pick up the new artifact, which Exercise 6
  does next

:material-checkbox-blank-outline: **Checkpoint:** you can explain, in one
sentence, the difference between `engine_config.yaml` and
`$EDUMATCHER_DATA_DIR/ref_data/engine_config.json`.

 

## Exercise 6: Start the Engine

Open a terminal and run:

```bash
pm-engine
```

`pm-engine` takes no config path on its command line — it always reads
whatever is currently deployed at `$EDUMATCHER_DATA_DIR/ref_data/engine_config.json`,
which is exactly the artifact Exercise 5 just installed.

Expected output includes (exact wording/log format may vary by version — this
is illustrative, not a literal match target):

```
[INFO] Loaded 3 symbols: AAPL, MSFT, TSLA
[INFO] Loaded 3 gateways
[INFO] Engine listening on :5555 (PULL), publishing on :5556 (PUB)
```

The stable way to confirm the engine actually loaded your config, independent
of log wording, is to query it from a gateway once connected (Exercise 8) with
`SYMBOLS` — if it lists `AAPL`, `MSFT`, and `TSLA`, the engine started correctly
regardless of what the startup banner said.

:material-checkbox-blank-outline: **Checkpoint:** engine is running without errors.

 

## Exercise 7: Start the Scheduler

In a **second terminal**:

```bash
pm-scheduler
```

Expected output (illustrative):

```
[INFO] Session state: PRE_OPEN
```

The scheduler will transition through PRE_OPEN → OPENING_AUCTION → CONTINUOUS
automatically, following the timetable in the deployed configuration. To skip
the wait and drive the sequence immediately, restart it with `--now`:

```bash
pm-scheduler --now --delay 5
```

`--now` starts the day's sequence from this moment instead of the configured
wall-clock times; `--delay 5` gives you five seconds between phases.

!!! note "If nothing was deployed"
    `pm-scheduler` refuses to guess a schedule the engine has never seen. If
    Exercise 5 was skipped, it exits immediately with a fatal error naming
    `pm-config-deploy`, instead of silently falling back to a built-in
    timetable.

:material-checkbox-blank-outline: **Checkpoint:** scheduler reports session state changes.

 

## Exercise 8: Connect a Gateway

In a **third terminal**:

```bash
pm-alf-console --id TRADER01
```

You should see:

```
[INFO] Connected as TRADER01
TRADER01>
```

Try typing `ORDERS` — it should report no resting orders for this gateway.

:material-checkbox-blank-outline: **Checkpoint:** gateway prompt is interactive and connected.

 

## Exercise 9: Verify the Setup

From the gateway prompt, confirm the three symbols are available by attempting
a tiny limit order:

```
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=0.01|TIF=DAY
```

You should see an acknowledgement (the order rests since no matching ask exists).

Repeat for `MSFT` and `TSLA` to confirm all three books are active.

:material-checkbox-blank-outline: **Checkpoint:** all three symbols accept orders.

 

## Exercise 10: Connect the Operator Console

!!! important "Two different consoles — this trips everyone up once"
    EduMatcher has **two** interactive consoles, and they accept different
    commands. Mixing them up is the most common early mistake, because the
    error is just `Unknown command`.

    | | `pm-alf-console` | `pm-admin` |
    |---|---|---|
    | Who it is | A **trader** | The **exchange operator** |
    | Prompt | `[TRADER01]> ` | `[GW_ADMIN|ADMIN]> ` |
    | Commands | `NEW`, `AMEND`, `CANCEL`, `STATUS`, `ORDERS`, `POS`, `QUOTE`, `QLEGS`, `SYMBOLS`, `SESSION`, `INDEX` | `BOOK`, `ORDERS|GW=`, `HALT`, `HALT_SYM`, `RESUME_SYM`, `CANCEL_SYM`, `KILL|GW=`, `KICK`, `QCANCEL`, `SESSION|STATE=`, `SESSION_STATUS`, `SCHEDULE`, `GATEWAYS`, `VOLUME` |
    | Sees the whole book? | No — only its own orders | Yes |

    A trader cannot inspect the order book, halt a symbol, or move the session.
    Those are operator powers, and they live in `pm-admin`.

    Throughout this guide, a prompt of `[GW_ADMIN|ADMIN]>` means "type this in
    the `pm-admin` terminal"; anything else means the trader console.

In a **fourth terminal**, start the operator console. Note this is
`pm-admin`, **not** `pm-alf-console`:

```bash
pm-admin --id GW_ADMIN
```

`GW_ADMIN` must be a gateway with `role: ADMIN` in your configuration — that
is what Exercise 2 created.

Now look at the order book, which no trader console can do:

```
[GW_ADMIN|ADMIN]> BOOK|SYM=AAPL
```

You should see a book snapshot (possibly with the 1-lot bid from Exercise 9).

Try two more operator queries:

```
[GW_ADMIN|ADMIN]> GATEWAYS
[GW_ADMIN|ADMIN]> SESSION_STATUS
```

`GATEWAYS` lists every configured gateway and whether it is connected;
`SESSION_STATUS` reports the current trading phase.

:material-checkbox-blank-outline: **Checkpoint:** `pm-admin` is connected, `BOOK|SYM=AAPL`
shows the book, and you can state which of the two consoles a given command
belongs to.

!!! tip "Keep both terminals open from here on"
    Every later chapter assumes you have a trader console *and* an operator
    console available. Leaving both running saves restarting them constantly.

 

## Exercise 11: Inspect Enriched SYMBOLS Metadata

From any connected gateway:

```
[TRADER01]> SYMBOLS
```

In addition to symbol IDs, inspect metadata fields exposed by the gateway view,
including symbol description and matching constraints such as tick size and MM
obligation settings when configured.

:material-checkbox-blank-outline: **Checkpoint:** you can identify at least `description` and `tick_size` for each symbol from `SYMBOLS` output.

 

## Exercise 12: Break — and Recognise — the Artifact's Hash Checks

The compiled artifact records two independent SHA-256 hashes in its `meta`
block: `content_sha256` (the artifact against itself) and `source_sha256`
(the artifact against the `engine_config.yaml` it was built from). This
exercise reproduces both failures on purpose, so you recognise the real
message the first time you see it instead of the first time it costs you an
afternoon. See [Configuration — Verifying the Deployed
Artifact](../user-guide/010-configuration.md#verifying-the-deployed-artifact)
for the full explanation this exercise is drilling.

**Part A — trip the content-digest check (an error).**

In the engine's terminal, stop it with `Ctrl-C`. Then hand-edit the
*deployed* artifact directly — something `pm-config-deploy` never does and
nothing should:

```bash
python3 -c "
import json
p = '$EDUMATCHER_DATA_DIR/ref_data/engine_config.json'
data = json.load(open(p))
data['symbols']['AAPL']['tick_decimals'] = 4
json.dump(data, open(p, 'w'), indent=2)
"
```

Start the engine again in the same terminal:

```bash
pm-engine
```

Expected: the engine refuses to start, reporting that the compiled config's
payload no longer matches its recorded content digest — naming
`pm-config-deploy`, not manual editing, as the fix.

Recover by recompiling the (untouched) source that is still sitting next to
the artifact, then start the engine again:

```bash
pm-config-deploy engine_config.yaml
pm-engine
```

**Part B — trip the source-staleness check (a warning).**

Leave this engine running. In another terminal, edit the *authored* YAML and
deliberately skip the deploy step — this only changes the file on disk, it
does not affect the already-running engine:

```bash
sed -i.bak 's/tick_decimals: 2/tick_decimals: 3/' engine_config.yaml   # edits AAPL's line, the first match
```

Now stop the engine (`Ctrl-C`) and start it again without redeploying:

```bash
pm-engine
```

Expected: the engine **starts anyway**, but logs a warning that
`engine_config.yaml` has changed since the running configuration was
compiled and that the exchange is still serving the previous one. Confirm
with `SYMBOLS` from a gateway that AAPL still reports the old
`tick_decimals` — the warning told the truth, nothing was silently applied.

Restore the file and redeploy to clear the warning:

```bash
mv engine_config.yaml.bak engine_config.yaml
pm-config-deploy engine_config.yaml
```

!!! note "Why the two checks fail differently"
    A hand-edited artifact is refused outright because a process cannot tell
    a malicious edit from a benign one, and either way the file no longer
    means what it claims to. A stale *source* file is only a warning because
    the deployed artifact is still perfectly valid — you just have an edit
    sitting uncommitted next to it. `pm-config-deploy` is the only fix for
    either case.

:material-checkbox-blank-outline: **Checkpoint:** you have seen both the
content-digest error and the source-staleness warning fire for real, and can
state which of the two blocks startup and which only warns.

 

## Summary

You now have:

- A configuration file defining 3 symbols and 3 gateways.
- A repeatable verifier workflow (`pm-cverifier`) to catch config problems before startup.
- A compiled, deployed configuration (`pm-config-deploy`) that `pm-engine` and
  `pm-scheduler` actually read.
- A running engine, scheduler, and at least one trader gateway.
- Confirmation that all symbols accept orders.
- Firsthand experience of the artifact's content-digest error and
  source-staleness warning, and which fix (`pm-config-deploy`) clears both.

## Reflection

Why does the engine, scheduler, and each gateway all run as **separate
processes** connected over ZMQ sockets, instead of one monolithic program?
What would you lose (or gain) operationally if the scheduler crashed while
the engine kept running?

`pm-engine` and `pm-scheduler` never accept a config path, and neither reads
`engine_config.yaml` directly. What problem does forcing every process
through one compiled artifact (`pm-config-deploy`) solve that letting each
process parse its own copy of the YAML would not?

Exercise 12's two checks fail at different severities — one refuses to
start, the other only warns. Why is a hand-edited *artifact* treated as more
serious than a stale *source* file, given that both mean the running
configuration is not what `engine_config.yaml` currently says?

## Further Reading

- [Configuration](../user-guide/010-configuration.md)
- [Configuration — Verifying the Deployed Artifact](../user-guide/010-configuration.md#verifying-the-deployed-artifact)
- [Config Verifier (`pm-cverifier`)](../user-guide/020-config-verifier.md)
- [Running the Engine](../user-guide/040-running-the-exchange.md)
- [Gateway Concepts](../user-guide/051-gateway-intro.md)
- [ALF Console (pm-alf-console)](../user-guide/055-alf-console.md)
- [Message Types (system.symbols)](../user-guide/270-message-reference.md)

**Next:** [02 — Setting Up Market-Maker Liquidity](020-setting-up-MM-bots.md)
