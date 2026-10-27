"""Generate and check the architecture book's SQLite schema reference."""

from __future__ import annotations

import argparse
import difflib
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = (
    ROOT
    / "docs/books/architecture-and-development/part-1-architecture/040-sqlite-schemas.md"
)
ACK_SCHEMA = ROOT / "web-apps/log-gui/apps/bridge/src/schema.sql"


@dataclass(frozen=True)
class DatabaseSpec:
    filename: str
    owner: str
    purpose: str
    source: str
    initialize: Callable[[sqlite3.Connection], None]


def _initialize_stats(conn: sqlite3.Connection) -> None:
    from edumatcher.stats.main import initialize_schema

    initialize_schema(conn)


def _initialize_clearing(conn: sqlite3.Connection) -> None:
    from edumatcher.clearing.store import apply_schema

    apply_schema(conn)


def _initialize_log(conn: sqlite3.Connection) -> None:
    from edumatcher.log_srv.schema import initialize_schema

    initialize_schema(conn)


def _initialize_news(conn: sqlite3.Connection) -> None:
    from edumatcher.market_sim.news_history import initialize_schema

    initialize_schema(conn)


def _initialize_companies(conn: sqlite3.Connection) -> None:
    from edumatcher.compdb.store import initialize_schema

    initialize_schema(conn)


def _initialize_audit_index(conn: sqlite3.Connection) -> None:
    from edumatcher.audit.indexer import initialize_schema

    initialize_schema(conn)


def _initialize_audit_replay(conn: sqlite3.Connection) -> None:
    from edumatcher.audit.replay.index import initialize_schema

    initialize_schema(conn)


def _initialize_metrics(conn: sqlite3.Connection) -> None:
    from edumatcher.monitor.store import initialize_schema

    initialize_schema(conn)


def _initialize_log_ui_acks(conn: sqlite3.Connection) -> None:
    conn.executescript(ACK_SCHEMA.read_text(encoding="utf-8"))


def database_specs() -> tuple[DatabaseSpec, ...]:
    """Describe the stores while delegating every schema to its owner."""
    return (
        DatabaseSpec(
            "stats.db",
            "pm-stats",
            "Market, order, and index statistics; raw event retention is configured by pm-stats.",
            "src/edumatcher/stats/main.py",
            _initialize_stats,
        ),
        DatabaseSpec(
            "clearing.db",
            "pm-clearing",
            "Executions, gateway positions, daily summaries, and clearing metadata.",
            "src/edumatcher/clearing/store.py",
            _initialize_clearing,
        ),
        DatabaseSpec(
            "log.db",
            "pm-log-srv",
            "Process log events, connection sessions, and server counters.",
            "src/edumatcher/log_srv/schema.py",
            _initialize_log,
        ),
        DatabaseSpec(
            "metrics.db",
            "pm-monitor",
            "Operator-dashboard history: raw and 1-minute samples, daily totals, counter state and events.",
            "src/edumatcher/monitor/store.py",
            _initialize_metrics,
        ),
        DatabaseSpec(
            "market_sim_news.db",
            "pm-market-sim",
            "Generated and instructor-published news events, and the value "
            "model's jumps.",
            "src/edumatcher/market_sim/news_history.py",
            _initialize_news,
        ),
        DatabaseSpec(
            "companies.db",
            "pm-compdb-cli",
            "Made-up company profiles of the simulated market's tickers.",
            "src/edumatcher/compdb/store.py",
            _initialize_companies,
        ),
        DatabaseSpec(
            "log-ui-acks.db",
            "Log GUI bridge",
            "Operator issue acknowledgements and acknowledgement history.",
            "web-apps/log-gui/apps/bridge/src/schema.sql",
            _initialize_log_ui_acks,
        ),
        DatabaseSpec(
            "audit_index.db",
            "pm-audit-cli",
            "Rebuildable query index over the rotating audit log.",
            "src/edumatcher/audit/indexer.py",
            _initialize_audit_index,
        ),
        DatabaseSpec(
            "audit_replay.db",
            "pm-audit-replay",
            "Rebuildable episode, event, causal-link, anomaly, and actor index.",
            "src/edumatcher/audit/replay/index.py",
            _initialize_audit_replay,
        ),
    )


def _inline(value: object) -> str:
    if value is None:
        return ""
    escaped = str(value).replace("`", "\\`")
    return f"`{escaped}`"


def _label(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _columns(conn: sqlite3.Connection, name: str) -> list[tuple[object, ...]]:
    return conn.execute(f'PRAGMA table_info("{name}")').fetchall()


def render_reference() -> str:
    lines = [
        "# SQLite Schema Reference",
        "",
        "<!-- GENERATED FILE - DO NOT EDIT. Run `make dbdocs`. -->",
        "",
        "This reference is generated by applying each database owner's schema",
        "initializer to a temporary SQLite database. Column tables and SQL below",
        "come from SQLite's `table_info` and `sqlite_schema`; DDL is not copied into",
        "this document by hand. Run `make dbdocs-check` to detect drift.",
        "",
        "SQLite affinity types are shown as declared. The full DDL contains",
        "constraints, keys, defaults, indexes, and views where defined.",
        "",
    ]

    for spec in database_specs():
        conn = sqlite3.connect(":memory:")
        try:
            spec.initialize(conn)
            objects = conn.execute("""SELECT type, name, sql
                   FROM sqlite_schema
                   WHERE sql IS NOT NULL
                     AND name NOT LIKE 'sqlite_%'
                   ORDER BY CASE type
                       WHEN 'table' THEN 0 WHEN 'view' THEN 1
                       WHEN 'index' THEN 2 WHEN 'trigger' THEN 3 ELSE 4
                   END, name""").fetchall()
            lines.extend(
                [
                    f"## `{spec.filename}`",
                    "",
                    f"**Owner:** {spec.owner}  ",
                    f"**Purpose:** {spec.purpose}  ",
                    f"**Schema source:** `{spec.source}`",
                    "",
                    "### Fields",
                    "",
                    "| Object | Field | Declared type | Not null | Default | Primary key |",
                    "|---|---|---|---|---|---|",
                ]
            )
            for object_type, name, _sql in objects:
                if object_type not in ("table", "view"):
                    continue
                for row in _columns(conn, str(name)):
                    _, field, declared_type, not_null, default, primary_key = row
                    not_null_text = "yes" if not_null else "no"
                    primary_key_text = str(primary_key) if primary_key else ""
                    lines.append(
                        f"| `{object_type}: {name}` | `{field}` | "
                        f"`{declared_type or 'BLOB'}` | {not_null_text} | "
                        f"{_inline(default)} | {primary_key_text} |"
                    )
            lines.extend(["", "### DDL", ""])
            for object_type, name, sql in objects:
                lines.extend(
                    [f"#### `{object_type} {name}`", "", "```sql", str(sql), "```", ""]
                )
        finally:
            conn.close()

    return "\n".join(lines).rstrip() + "\n"


def generate(path: Path = OUTPUT) -> bool:
    expected = render_reference()
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == expected:
        print(f"sqlite schema docs: already up to date ({_label(path)})")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expected, encoding="utf-8")
    print(f"sqlite schema docs: wrote {_label(path)}")
    return True


def check(path: Path = OUTPUT) -> bool:
    expected = render_reference()
    actual = path.read_text(encoding="utf-8") if path.exists() else ""
    if actual == expected:
        print("sqlite schema docs: OK - generated output matches the live schemas")
        return True
    print(
        "sqlite schema docs: generated output is out of date. "
        "Run `make dbdocs` and commit the result.",
        file=sys.stderr,
    )
    diff = difflib.unified_diff(
        actual.splitlines(),
        expected.splitlines(),
        fromfile=str(path),
        tofile="generated",
        lineterm="",
    )
    print("\n".join(diff), file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate/check SQLite schema documentation"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("generate", help="Write the generated architecture reference")
    subparsers.add_parser("check", help="Fail if the committed reference is stale")
    args = parser.parse_args(argv)
    if args.command == "generate":
        generate()
        return 0
    return 0 if check() else 1


if __name__ == "__main__":
    raise SystemExit(main())
