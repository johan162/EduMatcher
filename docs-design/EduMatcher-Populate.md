# EduMatcher pm-populate — Design

Status: Draft v0.1 (2026-10-01). Not implemented.

## 1. Purpose

`pm-populate` replays a date range at accelerated pace through the REST API
(`pm-api-gwy`), using all configured traders, to simulate a given average number
of trades per business day. The result is an exchange restored with all data a
real period would have produced (history, audit, clearing, GTC orders,
positions). It doubles as a stress test.

## 2. Decisions (settled with Johan)

| Topic | Decision |
|---|---|
| Time model | Engine gets an injectable virtual clock; data carries backdated timestamps |
| Clock driver | `pm-populate` sends set/advance via an ADMIN REST call |
| Restored state | Everything: history, audit, clearing/P&L, GTC orders, end-of-run positions |
| Daily volume | Random (Poisson-like) around the average |
| Order flow | Broad mix: all order types incl. stop, OCO, combos, MM quotes |
| Stack | Either: `--stack spawn` or `--stack attach` |
| Reproducibility | Seeded RNG, same seed gives same exchange state |
| Pacing | Throttled to a max real-time rate (`--max-rate`) |
| Prices | Seeded random walk per symbol from config reference prices |
| Business days | Mon–Fri minus the engine's country holiday calendar |
| Order errors | Log, skip, continue, summarize at the end |
| Traders | All traders in the s150- configs (12 after the config change) |

## 3. Virtual clock (the large part)

Every place that reads wall-clock time or derives a date must use one `Clock`
abstraction: engine, scheduler (session transitions, EOD), stats (`trading_day`),
clearing/settlement, GTC/DAY expiry, index, gateways, retention pruning.

- Real clock by default. Sim clock only when the stack is started in sim mode
  (e.g. `--sim-clock`).
- New ADMIN endpoint `POST /admin/clock` with `set` and `advance`. Rejected with
  an error when not in sim mode. Time never moves backwards.
- The engine publishes sim time; other processes follow it.
- Retention pruning must use the sim clock, otherwise old simulated days are
  pruned as soon as they are written.
- **Step 0 is a spike:** enumerate every wall-clock call site (`time.time`,
  `datetime.now`, `time_ns`, …) before committing to the design.

## 4. Day loop

For each business day:

1. Advance the clock to PRE_OPEN; the scheduler drives the session states on its
   own as the clock crosses boundaries.
2. Opening auction, CONTINUOUS trading with generated order flow at sim
   timestamps, closing auction, CLOSED.
3. Advance across EOD so clearing, stats rollup and DAY-order expiry run for real.
4. Weekends and holidays are skipped by advancing the clock past them.

## 5. Volume model

- Per day draw `T_d ~ Poisson(avg_trades)`.
- Intraday intensity is U-shaped (heavier at open and close).
- A feedback controller compares trades so far against the day's target and
  shifts the aggressive/passive mix, so the trade count tracks `T_d` without
  being forced exactly.

## 6. Traders and order mix

- All traders are used; each is a REST gateway identity with its own API key.
- A subset are MARKET_MAKER and post two-sided quotes; the rest trade.
- Weighted, configurable mix: LIMIT, MARKET, IOC/FOK, stop, stop-limit,
  trailing, OCO, combos, amend, cancel.
- Prices are display money (per `claude/config_prices_are_display_money`), snapped
  to each symbol's tick grid and kept inside collars.
- Prices follow a per-symbol seeded random walk from `last_buy_price` /
  `last_sell_price` in the config.

## 7. Reproducibility

- One master seed (`--seed`) feeds per-symbol and per-trader substreams.
- A single sequencer sends one request at a time and awaits the ack.
- "Same state" means identical trades, prices, positions and book contents.
  Order IDs are random (`os.urandom`) and will differ between runs.

## 8. Pacing and error handling

- `--max-rate N` caps orders per real second.
- Rejects and errors are logged and skipped; the run continues.
- Final summary: orders sent/accepted/rejected by reason, actual vs target trades
  per day, throughput, latency percentiles.

## 9. Run modes

- `--stack spawn`: start a fresh stack in sim mode, populate, shut down cleanly so
  GTC orders, positions and stats persist.
- `--stack attach`: drive an already-running empty stack in sim mode; leave it
  running.

## 10. CLI sketch

```
pm-populate --from 2026-01-02 --to 2026-03-31 --avg-trades 5000 \
            --seed 42 --max-rate 500 --stack spawn
```

## 11. Open items

- Default value for `--max-rate`.
- Whether gateway rate limits and risk limits (`order_limits`, SMP) need relaxing
  in sim mode.
- Trader roles in the s150- configs (which are MARKET_MAKER-capable), pending
  the config change.
- Behaviour of `pm-index` and index history under the sim clock.
