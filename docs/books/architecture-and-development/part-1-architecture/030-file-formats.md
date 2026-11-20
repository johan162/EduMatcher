# Data File Formats

EduMatcher uses SQLite for durable event records, derived summaries, and
operator-interface state, a line-oriented text format for the audit trail, and
small JSON files for the engine's own state. Database paths normally live under `$DATA_DIR`, but
services and bridges can override their individual paths. Each database has
one owning writer and its own retention and recovery policy.

The complete database inventory, field metadata, and formal DDL are in the
[generated SQLite Schema Reference](040-sqlite-schemas.md). It is built by
running each owner's schema initializer against a temporary database; the
tables, columns, indexes, and views are not duplicated here.

## Storage Behavior

The statistics store retains daily rollups. Raw event and snapshot retention is
configurable through `pm-stats`; the default keeps all rows. Clearing trade
events default to a 90-day window, while current positions and daily summaries
remain available beyond that window. The log server defaults to 30 days of log
events; `log_server.retention_days: null` or zero keeps them indefinitely.

The market-simulation news store is not pruned automatically. If an older
`market_sim_news.jsonl` exists, it is imported when the SQLite database is
first created, and the source file remains untouched. Audit indexes are
derived from retained audit logs and can be rebuilt.

The audit trail is line-oriented text, `[ts] [topic] [meta] {json}`, in three
kinds of file under the data directory: `audit.log`, the active file holding
one trading day (midnight in `locale.session_timezone`, by each line's receive
time); `audit/audit-YYYY-MM-DD.N.log`, closed parts of a day, numbered in write
order and never renamed; and `audit/audit-YYYY-MM-DD.log.zst`, one zstd stream
per archived day, the day's parts concatenated, so decompressing it yields the
day's log byte for byte. The archive's frame header records the uncompressed
size. Readers take the live trail (unarchived parts, then `audit.log`) by
default and a day's archive by `--date` or by path.

Trading prices and notionals in the statistics and clearing stores use integer
ticks and require the row's `tick_decimals` to convert to display currency.
Index levels and some derived values are `REAL` values. Timestamps may be UTC
ISO-8601 text or integer Unix nanoseconds; the generated reference shows each
column's declared type, and the owning process defines its units.

## Engine State Files (JSON)

The engine keeps its own state in small JSON files in the data directory,
outside SQLite. Each is written with `atomic_write_text`: write a temporary file
beside it, fsync, rename over the old one. A crash during a write therefore
leaves the previous version intact, never a truncated file.

| File | Written | Read | Contents |
|---|---|---|---|
| `gtc_orders.json` | every 5 s while running, and at shutdown | at startup | every resting order (`TIF=GTC` and `TIF=DAY`) as `Order.to_dict()`, with its `arrival_seq`; restored in that order so queue priority survives. A DAY order whose business day has passed is dropped at startup |
| `gtc_combos.json` | with `gtc_orders.json` | at startup | live combo parents and the ids of their child legs |
| `book_stats.json` | with `gtc_orders.json` | at startup | per symbol: last buy and sell price, previous close, each circuit breaker's reference window (`cb_window`) and any operator halt still in force |
| `engine_run_seq.json` | once, at every engine start | at every engine start | `{"run_seq": N}` — the engine-run number in every trade id (`{run_seq:06d}-{n:09d}`). A corrupt file stops the engine rather than risk reissuing trade ids |
| `ref_data/engine_config.json` | by `pm-config-deploy` / `pm-setup` | by every process at startup | the compiled configuration, with a digest of its content; a process refuses to start against a copy edited by hand |

If `gtc_orders.json` or `gtc_combos.json` cannot be parsed at startup, the
engine first copies it aside as `<name>.corrupt-<UTC timestamp>` — its first
checkpoint will overwrite the original seconds later — and names the copy in a
CRITICAL log line. Each index's state and structural history are kept in the
files its `indexes:` entry names (`state_file`, a JSON checkpoint, and
`history_file`, append-only JSON lines); `pm-index-cli` can check both.

## SQLite Files on Disk

`stats.db.lock` is a SQLite sidecar used only to hold the `pm-stats` writer
lock; it contains no application tables. While a database is open in WAL mode,
SQLite may also create `-wal` and `-shm` files. Keep these beside the database
while its owner is running and do not remove them independently.

For a consistent backup, stop the database owner or use SQLite's backup API.
Copying only the main database file while WAL writes are active can omit
committed transactions. Confirm the effective path before inspecting or backing
up a file.

## Keeping the Schema Reference Current

The schema initializer used by a runtime owner is authoritative. After changing
one, regenerate the reference and verify it:

```bash
make dbdocs
make dbdocs-check
```

`make check` and CI run the drift check. The generated chapter is not edited
by hand; update the schema owner and regenerate instead.