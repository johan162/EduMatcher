# SQLite Database Formats

EduMatcher uses SQLite for durable event records, derived summaries, and
operator-interface state. Database paths normally live under `$DATA_DIR`, but
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

Trading prices and notionals in the statistics and clearing stores use integer
ticks and require the row's `tick_decimals` to convert to display currency.
Index levels and some derived values are `REAL` values. Timestamps may be UTC
ISO-8601 text or integer Unix nanoseconds; the generated reference shows each
column's declared type, and the owning process defines its units.

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