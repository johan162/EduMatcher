Version: 1.0.0

Date: 2026-06-28

Status: Design Specification

# EduMatcher - AI Trading Bot (`pm-ai-trader`, `pm-ai-swarm`)

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [Runtime Architecture](#2-runtime-architecture)
3. [Bot State Model](#3-bot-state-model)
4. [Message Contracts](#4-message-contracts)
5. [Lifecycle and Control Flow](#5-lifecycle-and-control-flow)
6. [Order Decision Policy](#6-order-decision-policy)
7. [Risk Guardrails](#7-risk-guardrails)
8. [CLI and Configuration Surface](#8-cli-and-configuration-surface)
9. [Personality Profiles](#9-personality-profiles)
10. [Swarm Launcher Behavior](#10-swarm-launcher-behavior)
11. [Known Behavioral Limits](#11-known-behavioral-limits)
12. [Step 2 Review Against an Ideal AI Agent](#12-step-2-review-against-an-ideal-ai-agent)
13. [Top 7 Priority Additions for Intelligence](#13-top-7-priority-additions-for-intelligence)
14. [Personality Knobs - Should There Be More?](#14-personality-knobs---should-there-be-more)
15. [Acceptance Checks for Next Iteration](#15-acceptance-checks-for-next-iteration)


## 1. Purpose and Scope

`pm-ai-trader` is an autonomous order-flow generator that connects as a normal
ALF gateway, consumes book and trade events, and emits `LIMIT DAY` orders.

Primary intent:

- Generate realistic background order flow for classroom/demo sessions
- Provide non-human counterparties for student traders
- Produce profile-differentiated behavior (frequency, size, aggression)

Out of scope in current implementation:

- Forecasting alpha or predictive modeling
- Portfolio optimization across symbols
- Adversarial strategic behavior against specific counterparties
- Explicit P&L optimization and risk-adjusted utility maximization


## 2. Runtime Architecture

Each bot instance is a standalone process:

- PUSH socket to engine command input (`ENGINE_PULL_ADDR`)
- SUB socket to engine market/event feed (`ENGINE_PUB_ADDR`)

Subscribed topics include:

- `system.gateway_auth.<GW_ID>`
- `system.symbols.<GW_ID>`
- `order.ack.<GW_ID>`
- `order.fill.<GW_ID>`
- `order.cancelled.<GW_ID>`
- `order.expired.<GW_ID>`
- `book.<SYMBOL>` (prefix subscription via `book.`)
- `trade.executed`

Sent messages include:

- `gateway_connect` (authentication)
- `symbols_request` (symbol discovery/refresh)
- `order.new` (generated orders)


## 3. Bot State Model

Per process instance, the bot maintains:

- `gateway_id`, `run_id`, deterministic RNG (`seed`)
- Profile parameters (decision interval, aggression, size policy)
- Market cache per symbol:
  - best bid
  - best ask
  - last traded price
- Last market update timestamp per symbol
- Known symbol universe and optional user-provided symbol filter
- Internal position estimate per symbol (updated from own fills only)
- Reject timestamps deque for rolling reject-breaker logic
- Counters: submitted, acknowledged, rejected, filled, cancelled


## 4. Message Contracts

### 4.1 Inputs consumed

- `system.gateway_auth.<GW_ID>`: success/failure of connection
- `system.symbols.<GW_ID>`: available symbols
- `book.<SYMBOL>`: top-of-book and last price updates
- `trade.executed`: last-trade updates used as fallback price reference
- `order.ack.<GW_ID>`: accepted/rejected order acknowledgments
- `order.fill.<GW_ID>`: fill events for internal position tracking
- `order.cancelled.<GW_ID>`, `order.expired.<GW_ID>`: lifecycle metrics only

### 4.2 Outputs generated

All generated orders are currently:

- `order_type = LIMIT`
- `tif = DAY`
- Side and price generated from profile + top-of-book snapshot


## 5. Lifecycle and Control Flow

1. Connect and authenticate (`gateway_connect`)
2. Request symbols (`symbols_request`)
3. Enter poll loop
4. Consume events and update local state
5. Periodically attempt submission (`decision_interval_ms` driven)
6. Stop on duration expiry or interrupt
7. Print summary metrics and close sockets

If symbol discovery is delayed, bot retries symbols request every ~2 seconds
until symbols are available.


## 6. Order Decision Policy

For each decision tick:

1. Skip if reject breaker cooldown active
2. Skip if profile interval has not elapsed
3. Pick a symbol uniformly from active universe
4. Skip if market data is stale (older than `stale_data_sec`), when stale check applies
5. Choose side:
   - If at long max position: SELL only
   - If at short max position: BUY only
   - Else random 50/50 BUY or SELL
6. Sample size from profile distribution
7. Cap quantity by remaining position headroom
8. Build price:
   - BUY: reference best bid (else last price)
     - cross with probability `cross_probability` at best ask
     - else quote passive at `ref - passive_offset_ticks * tick_size`
   - SELL: reference best ask (else last price)
     - cross with probability `cross_probability` at best bid
     - else quote passive at `ref + passive_offset_ticks * tick_size`
9. Submit order

Important behavioral implication:

- This is a reactive stochastic policy, not a predictive policy
- There is no explicit signal from spread, depth imbalance, volatility, or trend


## 7. Risk Guardrails

Current safeguards are intentionally simple:

1. Position cap per symbol (`max_position`)
2. Reject breaker:
   - track rejects in rolling window (`reject_window_sec`)
   - if rejects >= threshold (`max_rejects`) then pause for cooldown (`reject_cooldown_sec`)
3. Stale data gate (`stale_data_sec`) to avoid trading on old state

These controls reduce runaway behavior, but do not form a full risk engine.


## 8. CLI and Configuration Surface

`pm-ai-trader` controls:

- identity and profile: `--id`, `--profile`
- universe and determinism: `--symbols`, `--seed`, `--run-id`
- run control: `--duration`
- risk controls: `--max-position`, `--max-rejects`, `--reject-window`, `--reject-cooldown`, `--stale-data`

`pm-ai-swarm` controls:

- scale and identity generation: `--count`, `--prefix`, `--start-index`
- profile cycle: `--profiles`
- symbol source: `--symbols` or `--config`
- deterministic seeds: `--seed-base`
- inherited bot controls for risk and duration


## 9. Personality Profiles

Built-in profiles:

- `aggressive`
- `cautious`
- `many-small`
- `few-large`

Current profile dimensions:

- decision interval
- min/max quantity
- crossing probability
- passive offset in ticks
- fixed tick size (0.01 in current presets)
- size distribution shape (`balanced`, `small-heavy`, `block-heavy`)


## 10. Swarm Launcher Behavior

`pm-ai-swarm` launches N independent subprocesses of `pm-ai-trader`.

Key details:

- Gateway IDs are generated sequentially, zero-padded (`AI01`, `AI02`, ...)
- Profiles are assigned round-robin across chosen cycle
- Symbols are assigned round-robin, one primary symbol per bot
- Seeds are deterministic (`seed_base + i`)
- Small launch stagger (~20ms) limits startup burst

Operational implication:

- With 50 bots and 100 symbols, only 50 primary symbols are actively targeted
  if one-symbol-per-bot assignment is used


## 11. Known Behavioral Limits

Current implementation limitations that materially affect realism:

1. No outstanding-order book for the bot itself (no amend/reprice/cancel strategy)
2. Side is mostly random, only inventory-constrained, not signal-driven
3. No volatility-adaptive or spread-adaptive sizing/aggression
4. No session-state awareness in behavior policy
5. No explicit objective function (P&L, inventory cost, adverse-selection control)
6. No cross-symbol relationship modeling
7. Tick size is profile-level static, not symbol-specific


## 12. Step 2 Review Against an Ideal AI Agent

### 12.1 Can it act as a reasonable intelligent agent?

Short answer: partially.

- Yes for educational background flow: it is robust, deterministic when seeded,
  inventory-aware, and produces varied flow through profiles.
- No for true "intelligent" behavior: it does not infer market regimes,
  optimize execution, adapt policy online, or manage strategic order lifecycle.

Conclusion:

- It is a competent stochastic simulator, not yet an intelligent trading agent.

### 12.2 50 agents across 100 symbols - realistic pattern?

Short answer: limited realism.

Positives:

- Throughput is non-trivial and can produce continuous activity
- Heterogeneous profile mix improves tape diversity

Constraints:

- One-primary-symbol assignment leaves many symbols under-active
- Behavior remains memory-light and mostly random around top-of-book
- Correlation structure across symbols and market regimes is absent

Expected result:

- Reasonable synthetic activity for demos
- Not realistic enough for microstructure research, stress tests, or
  "institutional-like" market ecology


## 13. Top 7 Priority Additions for Intelligence

1. Order lifecycle intelligence (highest priority)
- Track own resting orders by symbol/price/age.
- Add cancel/replace and stale-order cleanup.
- Prevent uncontrolled quote stacking and improve realism.

2. Signal-driven side and aggression policy
- Replace 50/50 side with signal score from short-horizon momentum,
  spread, microprice/imbalance, and recent trade direction.

3. Symbol-specific market microstructure parameters
- Pull tick size and optional per-symbol behavior config from engine metadata
  (or external config) rather than fixed profile tick size.

4. Volatility and spread-adaptive sizing
- Scale size, interval, and cross probability by realized volatility and spread.
- Calm market: tighter/passive behavior. Fast market: smaller/more defensive behavior.

5. Session and regime awareness
- Distinct policies for pre-open/opening auction/continuous/closing auction.
- Add opening/closing behavior templates and auction-specific participation logic.

6. Portfolio-level allocation across symbols
- For multi-symbol bots, allocate risk budget dynamically instead of uniform random pick.
- Include symbol activity weighting and exposure caps by sector/basket.

7. Online adaptation loop
- Add lightweight contextual bandit or score-based adaptation of key knobs
  (`cross_probability`, interval, size multiplier) from recent fill quality,
  reject rates, and drawdown.


## 14. Personality Knobs - Should There Be More?

Yes, but in structured layers rather than many flat parameters.

Recommended additional knobs:

1. Inventory behavior
- inventory target (default 0)
- inventory skew strength
- mean-reversion urgency when inventory is extreme

2. Execution behavior
- max concurrent resting orders per symbol
- cancel-replace cadence
- order age timeout

3. Market-response behavior
- volatility sensitivity
- spread sensitivity
- imbalance sensitivity

4. Session behavior
- opening aggression multiplier
- closing inventory-flatten multiplier

5. Exploration behavior
- randomization/jitter controls for timing and price offsets
- symbol exploration rate for multi-symbol bots

Guardrail recommendation:

- Keep existing presets as "simple mode"
- Introduce advanced knobs under profile files (YAML/JSON) for "expert mode"


## 15. Acceptance Checks for Next Iteration

A next-generation AI bot should meet all of the following:

1. Maintains bounded outstanding orders per symbol with explicit lifecycle metrics.
2. Uses at least one market-state signal beyond random side selection.
3. Supports symbol-specific tick size and behavior overrides.
4. Demonstrates differentiated behavior across session phases.
5. Produces measurable regime adaptation in live metrics.
6. With 50 bots and 100 symbols, achieves configurable symbol coverage targets.
7. Preserves deterministic replay when seeded and run under fixed inputs.
