# AI Bot Traders

## Background and Principle — How Bots Gain Intelligence

EduMatcher bot traders are designed to be **autonomous, reproducible, and explainable**.
Instead of using opaque model inference on every decision, the MVP bot layer uses a
policy engine with configurable traits and live market signals.

This gives three practical benefits:

1. Deterministic simulations for debugging and regression tests
2. Clear behavior tuning per trader personality
3. Fast decisions suitable for high-frequency event loops

### Core intelligence loop

Each bot continuously runs this loop:

1. Subscribe to market events from the engine (`book.*`, `trade.executed`)
2. Maintain local state (best bid/ask, last trade, symbol activity)
3. Apply personality policy (aggression, cadence, size style, etc.)
4. Build an order candidate (side, quantity, limit price)
5. Apply risk guardrails (position cap, reject breaker, stale-data pause)
6. Submit order and observe lifecycle feedback (`order.ack.*`, `order.fill.*`)
7. Update state and adapt next decision

### Why this is called intelligence

The intelligence is not a single AI model call. It is the **combination** of:

- Live perception from market data
- A configurable decision policy
- Feedback adaptation through acknowledgements, fills, and rejects
- Safety constraints that prevent unstable behavior

Over time, each trader behaves in a distinct way because the policy parameters,
seed, symbol set, and event stream differ.

### Data sources used by bots

Bots consume the same data foundations that drive market displays:

- Market board and viewer signals via `book.<SYMBOL>` snapshots
- Ticker-compatible trade flow via `trade.executed`
- Private execution feedback via per-gateway order topics

This ensures bot behavior is based on the same observable market reality as
human operators.

---

## How to Control Each Trader

You control each bot through CLI flags and profile selection.

### 1. Select gateway identity

Every bot must use a unique gateway ID that is allowed in `engine_config.yaml`.

```bash
poetry run pm-ai-trader --id AI01
```

### 2. Choose personality profile

Available profile presets:

- `aggressive`
- `cautious`
- `many-small`
- `few-large`

```bash
poetry run pm-ai-trader --id AI01 --profile aggressive
```

### 3. Restrict symbols per trader

Assign one symbol or a comma-separated set.

```bash
poetry run pm-ai-trader --id AI01 --symbols AAPL,MSFT
```

### 4. Make runs reproducible

Control randomness with `--seed` and group runs with `--run-id`.

```bash
poetry run pm-ai-trader --id AI01 --seed 42 --run-id demo-2026-05-07
```

### 5. Control risk behavior

Guardrails are configurable per bot:

- `--max-position`: absolute per-symbol position cap
- `--max-rejects`: reject threshold before breaker triggers
- `--reject-window`: rolling window for reject counting
- `--reject-cooldown`: pause after breaker trip
- `--stale-data`: maximum market-data age before pausing submissions

```bash
poetry run pm-ai-trader \
  --id AI01 \
  --profile cautious \
  --symbols AAPL \
  --max-position 500 \
  --max-rejects 10 \
  --reject-window 10 \
  --reject-cooldown 5 \
  --stale-data 4
```

### 6. Run many traders at once

Use swarm mode to launch multiple bots with profile cycling and symbol allocation.

```bash
poetry run pm-ai-swarm --count 30 --duration 60
```

Useful swarm controls:

- `--count`: number of bots
- `--prefix`: gateway ID prefix (example: `AI`)
- `--start-index`: first trader index
- `--profiles`: profile cycle list
- `--symbols`: symbol universe override
- `--seed-base`: deterministic seed start

## How to Start a Swarm of Bots

Use this sequence for reliable startup.

### Step 1: Ensure gateway IDs exist in config

Your swarm IDs must be listed under `gateways.alf` in `engine_config.yaml`.
For example, if you launch with `--prefix AI --start-index 1 --count 30`,
the engine must allow `AI01` through `AI30`.

### Step 2: Start core exchange processes

At minimum, start engine first and then optional observers:

```bash
# Terminal 1
poetry run pm-engine --verbose

# Terminal 2 (optional, recommended)
poetry run pm-audit --terminal

# Terminal 3 (optional)
poetry run pm-board

# Terminal 4 (optional)
poetry run pm-ticker
```

### Step 3: Launch swarm

Use one command to start all bot traders:

```bash
poetry run pm-ai-swarm \
  --count 30 \
  --prefix AI \
  --start-index 1 \
  --profiles aggressive,cautious,many-small,few-large \
  --duration 300
```

### Step 4: Validate swarm health

Quick checks:

1. No authentication rejects in engine output
2. Bot logs show submitted and acknowledged orders increasing
3. Board/ticker keep updating without stalls
4. No runaway reject breaker trips unless intentionally stress testing

### Step 5: Stop and rerun deterministic scenarios

- `Ctrl-C` in swarm terminal stops spawned bots gracefully.
- Reuse the same `--seed-base` and profile list to replay similar behavior.
- Change one parameter at a time for controlled experiments.

### 7. Example control setups

Conservative liquidity set:

```bash
poetry run pm-ai-swarm \
  --count 12 \
  --profiles cautious,many-small \
  --symbols AAPL,MSFT,TSLA \
  --duration 120
```

High-impact mixed flow:

```bash
poetry run pm-ai-swarm \
  --count 20 \
  --profiles aggressive,few-large,many-small \
  --duration 120
```

---

## Practical Notes

1. Keep engine and subscribers running before bots start.
2. Ensure all bot IDs are listed under `gateways.alf` in `engine_config.yaml`.
3. Start small (2–5 bots), verify flow, then scale to 30.
4. Use fixed seeds for scenario replay and performance comparisons.

## Tick/Ns Migration Notes

- Bots still choose human-readable decimal prices based on profile settings.
- Engine boundary conversion maps those prices to symbol tick units.
- To avoid off-grid prices, keep profile `tick_size` aligned with symbol
  `tick_decimals` configuration.
