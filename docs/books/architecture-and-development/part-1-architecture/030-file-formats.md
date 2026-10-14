# SQLite Database Formats

EduMatcher uses SQLite for durable event records, derived summaries, and a few
operator-interface stores. The database files live under `$DATA_DIR` unless a
service or bridge is configured with a path override. They are ordinary SQLite
databases, not interchangeable application formats: each has an owning writer
and a schema described below.

## Database Inventory

| File | Writer | Role | Lifecycle |
|---|---|---|---|
| `stats.db` | `pm-stats` | Market, order, and index statistics | Primary data; retention is configurable |
| `clearing.db` | `pm-clearing` | Executions, positions, and P&L | Primary data; trades default to 90 days |
| `log.db` | `pm-log-srv` | Process logs and server connection state | Primary data; logs default to 30 days |
| `market_sim_news.db` | `pm-market-sim` | Published news and rumour events | Primary news history; no automatic pruning |
| `log-ui-acks.db` | Log GUI bridge | Operator acknowledgements and their history | User state; retained until removed |
| `audit_index.db` | `pm-audit-cli` | Search index over the rotating audit log | Derived; can be rebuilt from audit logs |
| `audit_replay.db` | `pm-audit-replay` | Reconstructed event episodes and causal links | Derived; rebuilt when its schema version changes |

`stats.db.lock` is a separate SQLite file used only to hold an exclusive
writer lock for `pm-stats`; it contains no application records. SQLite may
also create `-wal` and `-shm` companion files while a database is open. Keep
those files with the database during live operation; do not treat them as
independent databases or delete them while the owner is running.

## `stats.db`

`pm-stats` creates the database and owns all writes. The main tables are:

| Table | Contents |
|---|---|
| `stats_meta` | Store metadata, including the session timezone used for trading dates |
| `instruments` | Symbol tick precision and reference metadata |
| `daily_stats` | Per-symbol daily OHLC, bid/ask, volume, trade count, turnover, and VWAP |
| `price_snapshots` | Timestamped midpoint, best bid/ask, and percentage change |
| `trade_log` | Individual engine executions, keyed by durable trade ID |
| `order_events` | Order lifecycle and fill events, including gateway and order identifiers |
| `feed_gaps` | Missing sequence ranges observed on subscribed streams |
| `index_daily_stats` | Daily OHLC and capitalization summaries per index |
| `index_level_snapshots` | Timestamped index levels and associated market state |

Trading prices in `daily_stats`, `trade_log`, and the bid/ask columns of
`price_snapshots` are integer ticks. Use `instruments.tick_decimals` to convert
them to display prices: one tick is $10^{-tick\_decimals}$. Snapshot midpoints
are `REAL` ticks because a midpoint may be half a tick. `trade_log` and
`price_snapshots` are pruned by `--keep-days`; `order_events` can use the
separate `--keep-order-events-days` setting. Daily rollups are retained.
The defaults keep all rows. See the [statistics reference](../../operator-guide/part-4-run-a-market/060-statistics-and-reporting.md)
for queries and tick conversion examples.

## `clearing.db`

`pm-clearing` writes execution and position state. Its main tables are:

| Table or view | Contents |
|---|---|
| `trade_events` | One row per durable engine trade ID, with trade date, tick price, quantity, and both counterparties |
| `gateway_symbol_positions` | Current net position, cost basis, realized and unrealized P&L per gateway and symbol |
| `gateway_daily_summary` | Per-day traded amounts, end-of-day positions, and P&L |
| `session_events` | Session and operational events with their original payload |
| `gateway_sessions` | Gateway connect/disconnect intervals and reasons |
| `clearing_meta` | Store metadata, including the session timezone used to assign trade dates |
| `gateway_pnl_totals`, `daily_exchange_totals` | Views that normalize per-symbol tick units before aggregating monetary totals |

Execution prices and notionals are stored in tick units with `tick_decimals` on
the relevant rows. P&L views convert each row to display currency before
summing across symbols. By default, `trade_events` older than 90 days are
pruned; pass `--retention-days 0` to disable that pruning. Current positions
and daily summaries are not the trade-event archive. See the [persistence
reference](../../operator-guide/part-6-observe-and-recover/010-persistence.md).

## `log.db`

`pm-log-srv` owns this append-oriented process log database:

| Table | Contents |
|---|---|
| `log_events` | One row per received log message, with client/server timestamps, process, severity, logger, and message |
| `processes` | Connection session, last-seen/disconnected times, and per-session log count |
| `server_stats` | Singleton row of lifetime server counters |

Timestamps are UTC ISO-8601 text. `log_events` defaults to 30 days of retention;
`log_server.retention_days: null` (or zero) keeps logs indefinitely. Query it
with `pm-log-cli` or the Log GUI rather than writing directly.

## `market_sim_news.db`

`pm-market-sim` appends each generated or instructor-published event to
`news_events`. Columns keep the public event ID, nanosecond Unix timestamp,
scope, JSON-encoded targets, kind, status, headline, sentiment, rumour
credibility, and related event ID. The timestamp and status have indexes for
history queries. `pm-news past` reads this table, applying `--date` in the
exchange session timezone and `--limit` newest-first. Events are not pruned
automatically. An existing `market_sim_news.jsonl` is imported the first time
the SQLite database is created; the source file is left untouched.

## Log GUI Store

The Log GUI bridge keeps operator acknowledgements separate from `log.db`, so
the log server remains the sole writer of its event store. `log-ui-acks.db`
contains:

| Table | Contents |
|---|---|
| `issue_acks` | Current acknowledgement by issue fingerprint, including who acknowledged it, note, and highest covered sequence |
| `ack_history` | Append-only acknowledge/unacknowledge actions with time, operator, and note |

The default path is `$DATA_DIR/log-ui-acks.db`; `ACK_STORE_PATH` can override
it. In container deployments it may be mounted as a separate named volume.

## Audit Indexes

The audit log itself is the rotating `audit.log` file, not a SQLite database.
Two optional SQLite files accelerate offline analysis:

| File | Main tables | Source and rebuild behavior |
|---|---|---|
| `audit_index.db` | `audit_events`, `index_meta` | Parsed audit-log rows with commonly filtered fields indexed; `pm-audit-cli` can rebuild it from the logs |
| `audit_replay.db` | `replay_meta`, `episodes`, `episode_events`, `links`, `stated_links`, `anomalies`, `actors` | Reconstructed causal episodes; derived from audit logs and discarded/rebuilt when the replay schema version changes |

These are query indexes, not substitutes for the audit log. If removed, their
contents can be regenerated from retained audit log files. The
[audit-trail guide](../../operator-guide/part-6-observe-and-recover/020-audit-trail.md)
covers building and querying them.

## Working with the Files

The owning process creates and evolves its schema. Use the corresponding CLI
for routine queries, and do not modify tables while a service is running.
For a consistent backup, stop the database owner or use SQLite's backup API;
copying only the main file while WAL writes are active can omit committed
transactions. The database path can be redirected by service configuration,
so confirm the effective path before inspecting or backing up a file.

## Column Catalog

Each row lists the complete set of fields in a physical table that share a
declared SQLite type. Field names are grouped only to keep this reference
compact; every field is named explicitly. SQLite types are affinities, and
SQLite's normal storage-class rules still apply.

### `stats.db`

| Table | Field(s) | SQLite type |
|---|---|---|
| `stats_meta` | `key`, `value` | `TEXT` |
| `instruments` | `symbol`, `currency`, `source`, `updated_ts` | `TEXT` |
| `instruments` | `tick_decimals` | `INTEGER` |
| `instruments` | `tick_size` | `REAL` |
| `daily_stats` | `date`, `symbol` | `TEXT` |
| `daily_stats` | `open_price`, `high_price`, `low_price`, `close_price`, `open_bid`, `open_ask`, `close_bid`, `close_ask`, `volume`, `trade_count`, `turnover`, `largest_trade_qty`, `largest_trade_price`, `tick_decimals` | `INTEGER` |
| `daily_stats` | `vwap` | `REAL` |
| `price_snapshots` | `ts`, `symbol` | `TEXT` |
| `price_snapshots` | `mid_price`, `pct_change` | `REAL` |
| `price_snapshots` | `best_bid`, `best_ask`, `tick_decimals` | `INTEGER` |
| `trade_log` | `ts`, `trade_id`, `symbol`, `buy_gateway_id`, `sell_gateway_id`, `aggressor_side` | `TEXT` |
| `trade_log` | `price`, `quantity`, `tick_decimals` | `INTEGER` |
| `feed_gaps` | `ts`, `stream` | `TEXT` |
| `feed_gaps` | `seq`, `expected_id`, `received_id`, `missing_count` | `INTEGER` |
| `order_events` | `ts`, `event_type`, `order_id`, `gateway_id`, `symbol`, `side`, `order_type`, `tif`, `status`, `trade_id`, `reason`, `client_tag`, `combo_parent_id`, `oco_group_id` | `TEXT` |
| `order_events` | `price`, `fill_price` | `REAL` |
| `order_events` | `seq`, `quantity`, `remaining_qty`, `fill_qty`, `priority_reset` | `INTEGER` |
| `index_daily_stats` | `date`, `index_id`, `close_session_state` | `TEXT` |
| `index_daily_stats` | `open_level`, `high_level`, `low_level`, `close_level`, `open_aggregate_cap`, `close_aggregate_cap` | `REAL` |
| `index_daily_stats` | `update_count` | `INTEGER` |
| `index_level_snapshots` | `ts`, `index_id`, `session_state` | `TEXT` |
| `index_level_snapshots` | `level`, `aggregate_cap`, `divisor`, `day_open`, `day_high`, `day_low` | `REAL` |

### `clearing.db`

| Table | Field(s) | SQLite type |
|---|---|---|
| `trade_events` | `id`, `trade_date`, `symbol`, `buy_order_id`, `sell_order_id`, `buy_gateway_id`, `sell_gateway_id`, `aggressor_side` | `TEXT` |
| `trade_events` | `ts_ns`, `quantity`, `price`, `tick_decimals`, `ingest_ts_ns` | `INTEGER` |
| `gateway_symbol_positions` | `gateway_id`, `symbol` | `TEXT` |
| `gateway_symbol_positions` | `net_qty`, `mark_price`, `tick_decimals`, `buy_qty`, `sell_qty`, `buy_notional`, `sell_notional`, `last_trade_ts_ns`, `updated_ts_ns` | `INTEGER` |
| `gateway_symbol_positions` | `avg_cost`, `realized_pnl`, `unrealized_pnl` | `REAL` |
| `gateway_daily_summary` | `trade_date`, `gateway_id`, `symbol` | `TEXT` |
| `gateway_daily_summary` | `traded_qty`, `traded_notional`, `buy_qty`, `sell_qty`, `buy_notional`, `sell_notional`, `net_amount`, `tick_decimals`, `end_net_qty`, `last_trade_ts_ns`, `updated_ts_ns` | `INTEGER` |
| `gateway_daily_summary` | `realized_pnl`, `end_avg_cost`, `end_unrealized_pnl` | `REAL` |
| `session_events` | `event_type`, `trade_date`, `payload_json` | `TEXT` |
| `session_events` | `id`, `ts_ns` | `INTEGER` |
| `gateway_sessions` | `gateway_id`, `disconnect_reason` | `TEXT` |
| `gateway_sessions` | `connected_at_ns`, `disconnected_at_ns` | `INTEGER` |
| `clearing_meta` | `key`, `value` | `TEXT` |

### `log.db`

| Table | Field(s) | SQLite type |
|---|---|---|
| `log_events` | `client_ts`, `server_ts`, `process`, `instance`, `host`, `session`, `level`, `logger`, `module`, `message` | `TEXT` |
| `log_events` | `seq`, `pid`, `line`, `has_exception`, `truncated` | `INTEGER` |
| `processes` | `session`, `process`, `instance`, `host`, `connected_at`, `last_seen_at`, `disconnected_at` | `TEXT` |
| `processes` | `pid`, `log_count` | `INTEGER` |
| `server_stats` | `id`, `total_log_events`, `total_connections`, `total_truncated`, `total_errors_sent` | `INTEGER` |
| `server_stats` | `started_at` | `TEXT` |

### `market_sim_news.db`

| Table | Field(s) | SQLite type |
|---|---|---|
| `news_events` | `id`, `scope`, `targets`, `kind`, `status`, `headline`, `related_id` | `TEXT` |
| `news_events` | `event_seq`, `ts_ns` | `INTEGER` |
| `news_events` | `sentiment`, `credibility` | `REAL` |

### `log-ui-acks.db`

| Table | Field(s) | SQLite type |
|---|---|---|
| `issue_acks` | `fingerprint`, `acked_at`, `acked_by`, `note`, `level`, `process`, `logger`, `sample_message` | `TEXT` |
| `issue_acks` | `acked_through_seq` | `INTEGER` |
| `ack_history` | `fingerprint`, `action`, `at`, `by`, `note` | `TEXT` |
| `ack_history` | `id` | `INTEGER` |

### `audit_index.db`

| Table | Field(s) | SQLite type |
|---|---|---|
| `audit_events` | `timestamp`, `topic`, `payload`, `gateway_id`, `symbol`, `order_id`, `trade_id`, `event_type`, `msg_id`, `causation_id`, `correlation_id` | `TEXT` |
| `audit_events` | `id`, `seq` | `INTEGER` |
| `index_meta` | `key`, `value` | `TEXT` |

### `audit_replay.db`

| Table | Field(s) | SQLite type |
|---|---|---|
| `replay_meta` | `key`, `value` | `TEXT` |
| `episodes` | `kind`, `anchor_key`, `correlation_id`, `root_msg_id`, `symbol`, `actor`, `opened_sort_key`, `closed_sort_key`, `opened_ts`, `closed_ts`, `outcome`, `summary`, `facts_json` | `TEXT` |
| `episodes` | `episode_id`, `run_seq` | `INTEGER` |
| `episode_events` | `ref`, `sort_key`, `receipt_ts`, `topic`, `kind`, `file`, `role`, `msg_id`, `causation_id`, `correlation_id`, `payload` | `TEXT` |
| `episode_events` | `episode_id`, `seq_in_ep`, `line_no`, `late`, `topic_seq` | `INTEGER` |
| `links` | `relation`, `confidence`, `evidence` | `TEXT` |
| `links` | `from_episode`, `to_episode` | `INTEGER` |
| `stated_links` | `from_ref`, `to_ref`, `relation`, `confidence`, `evidence` | `TEXT` |
| `anomalies` | `code`, `severity`, `sort_key`, `receipt_ts`, `detail`, `file` | `TEXT` |
| `anomalies` | `anomaly_id`, `episode_id`, `line_no` | `INTEGER` |
| `actors` | `gateway_id`, `description`, `first_seen`, `last_seen` | `TEXT` |
| `actors` | `orders`, `trades` | `INTEGER` |