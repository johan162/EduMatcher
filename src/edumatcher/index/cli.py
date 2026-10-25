"""pm-index-cli — read-only query tool for index structural/audit JSONL files.

Reads JSONL history files written by ``pm-index`` directly from disk.
No running process is required, except for ``health``, which pings the
running pm-index to confirm it is alive.

These files hold only structural/corporate-action audit records
(INIT, CORP_ACTION, ADD_CONSTITUENT, DELIST) — index level and
end-of-day history is not stored here. For level/EOD time-series
queries, use ``pm-stats-cli index-daily`` / ``index-snapshots``,
which read from pm-stats' SQLite database instead.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from edumatcher.config import INDEX_HEALTH_ADDR
from edumatcher.healthcheck import (
    PING_TIMEOUT_MS,
    find_process_pids,
    format_bytes,
    ping_health_endpoint,
    read_last_line,
    run_with_timeout,
)
from edumatcher.index.history import STRUCTURAL_RECORD_TYPES

_FORMATS = ("table", "json", "csv")
_DEFAULT_DATA_DIR = "data/indexes"

# ---------------------------------------------------------------------------
# Column definitions for each subcommand
# ---------------------------------------------------------------------------
_EVENTS_COLUMNS = [
    "ts",
    "index_id",
    "type",
    "symbol",
    "detail",
    "old_divisor",
    "new_divisor",
    "level",
]
_INDICES_COLUMNS = [
    "id",
    "description",
    "history_file",
    "state_file",
    "constituents",
]

# Event types shown by the 'events' subcommand.
_STRUCTURAL_TYPES = set(STRUCTURAL_RECORD_TYPES)

# The file check reads the tail of each history file, parses each state file,
# and opens both for append; all normally instant, but on a stalled or
# network-mounted volume any can block -- opt-in via --extended rather than in
# every health call, and bounded so a check that never returns cannot hang
# the CLI indefinitely.
_EXTENDED_HEALTH_TIMEOUT_SEC = 15.0


class _HealthProcessReport(TypedDict):
    healthy: bool
    pids: list[int]
    detail: str


class _HealthIndexFileStats(TypedDict):
    index_id: str
    state_path: str
    history_path: str
    history_size_bytes: int
    last_record_type: str | None
    last_record_ts: str | None
    last_level: float | None
    state_updated: str | None


class _HealthFilesReport(TypedDict):
    healthy: bool
    detail: str
    checked: bool
    stats: list[_HealthIndexFileStats] | None


class _HealthZmqReport(TypedDict):
    healthy: bool
    detail: str


class _HealthReport(TypedDict):
    healthy: bool
    process: _HealthProcessReport
    files: _HealthFilesReport
    zmq: _HealthZmqReport


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _parse_ts(value: str) -> float:
    """Parse ``YYYY-MM-DD`` or an ISO-8601 string to a Unix timestamp (UTC)."""
    value = value.strip()
    # Plain date → start of day UTC.
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        pass
    # ISO-8601; Python 3.11+ fromisoformat handles 'Z' and offset suffixes.
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        pass
    raise ValueError(
        f"Cannot parse timestamp {value!r}. Use YYYY-MM-DD or ISO-8601 "
        "(e.g. 2026-06-14T09:30:00+00:00)."
    )


def _ts_to_str(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# Config / file resolution helpers
# ---------------------------------------------------------------------------


def _try_load_engine_config(config_path: str | None) -> tuple[Any, str]:
    """Return ``(EngineConfig, "")``, or ``(None, error)`` on failure.

    With an explicit *config_path*, parses that YAML file directly. With
    none, falls back to the canonical compiled config used by the running
    exchange, so the common case ("what does the deployed exchange have
    configured?") needs no flag. Never prints or exits, so `health -q` can
    stay silent.
    """
    if config_path is None:
        from edumatcher.config import COMPILED_CONFIG_FILE
        from edumatcher.config_artifact import load_compiled_config

        compiled = load_compiled_config()
        if compiled is None:
            return None, (
                f"No compiled configuration at {COMPILED_CONFIG_FILE} and "
                "no --config given. Run pm-config-deploy, or pass --config PATH."
            )
        return compiled.engine, ""

    from edumatcher.engine.config_loader import load_engine_config

    try:
        return load_engine_config(Path(config_path)), ""
    except Exception as exc:
        return None, f"Could not load config {config_path!r}: {exc}"


def _load_engine_config(config_path: str | None) -> Any:
    """Return the EngineConfig to query, exiting on failure."""
    cfg, error = _try_load_engine_config(config_path)
    if cfg is None:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1)
    return cfg


def _config_index_map(config_path: str | None) -> dict[str, Any]:
    """Return a map of index_id → IndexConfig from engine config."""
    cfg = _load_engine_config(config_path)
    return {idx.id: idx for idx in cfg.indices}


def _resolve_history_files(
    index_ids: list[str],
    config_path: str | None,
    data_dir: str,
) -> dict[str, Path]:
    """Return index_id → history Path, preferring config values."""
    from_config: dict[str, str] = {}
    try:
        idx_map = _config_index_map(config_path)
        for idx_id, idx_cfg in idx_map.items():
            from_config[idx_id] = idx_cfg.history_file
    except SystemExit:
        if config_path is not None:
            # An explicit --config path that failed to load is an operator
            # mistake worth stopping for, not silently ignoring.
            raise
        # No --config given and no compiled configuration deployed: fall
        # back to --data-dir below, matching the pre-existing behaviour.
    except Exception as exc:
        print(
            f"[WARNING] Could not read index paths from config: {exc}",
            file=sys.stderr,
        )

    result: dict[str, Path] = {}
    from edumatcher.config import resolve_data_path

    for idx_id in index_ids:
        if idx_id in from_config:
            result[idx_id] = resolve_data_path(from_config[idx_id])
        else:
            result[idx_id] = resolve_data_path(
                str(Path(data_dir) / f"{idx_id}_history.jsonl")
            )
    return result


def _resolve_index_ids(
    args: argparse.Namespace,
    config_path: str | None,
) -> list[str]:
    """Determine which index IDs to query."""
    raw: list[str] = getattr(args, "index", None) or []
    if raw:
        return [i.upper() for i in raw]
    idx_map = _config_index_map(config_path)
    if not idx_map:
        print("[ERROR] No indices found in engine config.", file=sys.stderr)
        raise SystemExit(1)
    return list(idx_map.keys())


# ---------------------------------------------------------------------------
# JSONL reading
# ---------------------------------------------------------------------------


def _read_jsonl(
    path: Path,
    from_ts_ns: int,
    to_ts_ns: int,
    types: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Return matching records from *path* in chronological order.

    *from_ts_ns*/*to_ts_ns* are epoch nanoseconds (AR-0.3) — the same unit
    the archive itself stores under "ts_ns". Callers that speak in seconds
    (this CLI's own --from/--to/--days flags) convert once, at the call
    site in _cmd_events, before reaching this internal boundary.
    """
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") not in types:
                continue
            try:
                ts_ns = int(rec["ts_ns"])
            except KeyError, TypeError, ValueError:
                continue
            if from_ts_ns <= ts_ns <= to_ts_ns:
                records.append(rec)
                if len(records) >= limit:
                    break
    return records


# ---------------------------------------------------------------------------
# Row projection helpers
# ---------------------------------------------------------------------------


def _project_event(rec: dict[str, Any]) -> dict[str, Any]:
    rec_type = rec.get("type", "")
    if rec_type == "CORP_ACTION":
        detail = f"{rec.get('action', '')} {rec.get('detail', '')}".strip()
    elif rec_type == "ADD_CONSTITUENT":
        detail = f"ref_price={rec.get('reference_price', '')}"
    elif rec_type == "DELIST":
        detail = ""
    elif rec_type == "INIT":
        constituents = rec.get("constituents", [])
        detail = f"base={rec.get('base_value', '')} [{','.join(str(c) for c in constituents)}]"
    else:
        detail = ""
    return {
        "ts": _ts_to_str(int(rec["ts_ns"]) / 1_000_000_000),
        "index_id": rec.get("index_id", ""),
        "type": rec_type,
        "symbol": rec.get("symbol", ""),
        "detail": detail,
        "old_divisor": rec.get("old_divisor"),
        "new_divisor": rec.get("new_divisor"),
        "level": rec.get("level"),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


def _render_table(
    rows: list[dict[str, Any]], columns: list[str], no_header: bool
) -> None:
    if not rows:
        print("No rows found.")
        return
    widths: list[int] = []
    for col in columns:
        content_w = max((len(_stringify(row.get(col))) for row in rows), default=0)
        widths.append(max(len(col), content_w))

    def _line(values: list[str]) -> str:
        return " | ".join(v.ljust(w) for v, w in zip(values, widths, strict=True))

    if not no_header:
        print(_line(columns))
        print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(_line([_stringify(row.get(col)) for col in columns]))


def _render_json(rows: list[dict[str, Any]], columns: list[str]) -> None:
    projected = [{col: row.get(col) for col in columns} for row in rows]
    print(json.dumps(projected, indent=2))


def _render_csv(
    rows: list[dict[str, Any]], columns: list[str], no_header: bool
) -> None:
    writer = csv.DictWriter(
        sys.stdout, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
    )
    if not no_header:
        writer.writeheader()
    for row in rows:
        writer.writerow({col: _stringify(row.get(col)) for col in columns})


def _render(
    rows: list[dict[str, Any]], columns: list[str], fmt: str, no_header: bool
) -> None:
    if fmt == "json":
        _render_json(rows, columns)
    elif fmt == "csv":
        _render_csv(rows, columns, no_header)
    else:
        _render_table(rows, columns, no_header)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-index-cli",
        description=(
            "Query EduMatcher index structural/audit JSONL files directly from disk.\n"
            "No running process is required — reads JSONL files written by pm-index.\n"
            "For index level/EOD time-series history, use pm-stats-cli instead\n"
            "(index-daily / index-snapshots subcommands)."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-index-cli")
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        metavar="PATH",
        help=(
            "Path to an engine_config.yaml to query instead of the\n"
            "deployed exchange's compiled configuration.\n"
            "Used to auto-discover history file paths and index IDs."
        ),
    )
    parser.add_argument(
        "--data-dir",
        default=_DEFAULT_DATA_DIR,
        metavar="DIR",
        help=f"Directory containing history files (default: {_DEFAULT_DATA_DIR}).",
    )
    parser.add_argument(
        "--format",
        default="table",
        choices=_FORMATS,
        help="Output format: table (default), json, or csv.",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Suppress header row (csv output only).",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # ----------------------------------------------------------------- events
    events_p = sub.add_parser(
        "events",
        help="Show structural events: INIT, CORP_ACTION, ADD_CONSTITUENT, DELIST.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    events_p.add_argument(
        "--index",
        "-i",
        action="append",
        metavar="ID",
        help=(
            "Index ID to query (repeatable).\n"
            "Defaults to all indices in --config, or the deployed exchange's\n"
            "compiled configuration if --config is omitted."
        ),
    )
    events_p.add_argument(
        "--type",
        "-t",
        dest="event_types",
        action="append",
        metavar="TYPE",
        help=(
            "Filter to one event type (repeatable).\n"
            "Valid values: INIT, CORP_ACTION, ADD_CONSTITUENT, DELIST.\n"
            "Omit to show all structural event types."
        ),
    )
    _add_time_args(events_p)
    events_p.add_argument(
        "--limit",
        type=int,
        default=1000,
        metavar="N",
        help="Maximum rows per index (default: 1000).",
    )

    # --------------------------------------------------------------- indices
    sub.add_parser(
        "indices",
        help=(
            "List indices from --config, or the deployed exchange's compiled "
            "configuration if --config is omitted."
        ),
    )

    # ---------------------------------------------------------------- health
    health = sub.add_parser(
        "health",
        help="Check the pm-index process and its state/history file health",
    )
    health.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print nothing; exit 0 when healthy or -1 otherwise",
    )
    health.add_argument(
        "--extended",
        action="store_true",
        help=(
            "Also check every configured index's state and history files are "
            "readable, writable and well-formed; allowed up to "
            f"{_EXTENDED_HEALTH_TIMEOUT_SEC:.0f}s"
        ),
    )
    health.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Describe exactly what was checked, plus each index's file paths, "
            "history size, last record and last level when combined with "
            "--extended"
        ),
    )

    return parser


def _add_time_args(p: argparse.ArgumentParser) -> None:
    """Add --from / --to / --days to a subcommand parser."""
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--days",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Return records from the last N days.\n"
            "Mutually exclusive with --from / --to."
        ),
    )
    group.add_argument(
        "--from",
        dest="from_ts",
        metavar="DATE_OR_TS",
        help="Start of time range: YYYY-MM-DD or ISO-8601 (e.g. 2026-06-14T09:00:00+00:00).",
    )
    p.add_argument(
        "--to",
        dest="to_ts",
        metavar="DATE_OR_TS",
        help="End of time range: YYYY-MM-DD or ISO-8601. Defaults to now.",
    )


# ---------------------------------------------------------------------------
# Time range resolution
# ---------------------------------------------------------------------------


def _resolve_time_range(args: argparse.Namespace) -> tuple[float, float]:
    """Return (from_ts, to_ts) as Unix timestamps."""
    to_ts = time.time()
    from_ts = 0.0

    days = getattr(args, "days", None)
    if days is not None:
        if days <= 0:
            print("[ERROR] --days must be > 0", file=sys.stderr)
            raise SystemExit(2)
        from_ts = to_ts - days * 86400.0
        return from_ts, to_ts

    raw_to = getattr(args, "to_ts", None)
    raw_from = getattr(args, "from_ts", None)

    if raw_to is not None:
        try:
            to_ts = _parse_ts(str(raw_to))
        except ValueError as exc:
            print(f"[ERROR] --to: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc

    if raw_from is not None:
        try:
            from_ts = _parse_ts(str(raw_from))
        except ValueError as exc:
            print(f"[ERROR] --from: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc

    if from_ts > to_ts:
        print("[ERROR] --from must be earlier than --to", file=sys.stderr)
        raise SystemExit(2)

    return from_ts, to_ts


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_events(args: argparse.Namespace) -> None:
    index_ids = _resolve_index_ids(args, args.config)
    from_ts, to_ts = _resolve_time_range(args)
    hist_paths = _resolve_history_files(index_ids, args.config, args.data_dir)

    if args.event_types:
        requested = {t.upper() for t in args.event_types}
        invalid = requested - _STRUCTURAL_TYPES
        if invalid:
            print(
                f"[ERROR] Unknown event type(s): {', '.join(sorted(invalid))}. "
                f"Valid: {', '.join(sorted(_STRUCTURAL_TYPES))}",
                file=sys.stderr,
            )
            raise SystemExit(2)
        types = requested
    else:
        types = _STRUCTURAL_TYPES

    from_ts_ns = int(from_ts * 1_000_000_000)
    to_ts_ns = int(to_ts * 1_000_000_000)

    rows: list[dict[str, Any]] = []
    for idx_id in index_ids:
        for rec in _read_jsonl(
            hist_paths[idx_id], from_ts_ns, to_ts_ns, types, args.limit
        ):
            rows.append(_project_event(rec))

    _render(rows, _EVENTS_COLUMNS, args.format, args.no_header)


def _cmd_indices(args: argparse.Namespace) -> None:
    cfg = _load_engine_config(args.config)
    rows: list[dict[str, Any]] = [
        {
            "id": idx.id,
            "description": idx.description,
            "history_file": idx.history_file,
            "state_file": idx.state_file,
            "constituents": ",".join(idx.constituents),
        }
        for idx in cfg.indices
    ]
    _render(rows, _INDICES_COLUMNS, args.format, args.no_header)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def _find_index_pids() -> list[int]:
    """Find pm-index processes without matching this pm-index-cli process."""
    return find_process_pids("pm-index")


def _ns_to_iso(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).isoformat()


def _check_state_file(index_id: str, path: Path) -> tuple[str | None, dict[str, Any]]:
    """Return ``(problem, state)``; `problem` is None when the file is sound."""
    if not path.is_file():
        return f"state file not found: {path}", {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return f"state file is not valid JSON: {path}", {}
    if not isinstance(state, dict):
        return f"state file is not a JSON object: {path}", {}
    state_id = str(state.get("index_id", "")).upper()
    if state_id and state_id != index_id:
        return f"state file belongs to index {state_id!r}: {path}", {}
    # Opening for append and writing nothing proves pm-index could still
    # rewrite the file without touching it.
    with path.open("ab"):
        pass
    return None, state


def _check_history_file(path: Path) -> tuple[str | None, dict[str, Any] | None]:
    """Return ``(problem, last_record)``; `last_record` is None if empty."""
    if not path.is_file():
        return f"history file not found: {path}", None
    last_line = read_last_line(path)
    record: dict[str, Any] | None = None
    if last_line is not None:
        try:
            parsed = json.loads(last_line)
        except json.JSONDecodeError:
            return f"last history record is malformed: {path}", None
        if (
            not isinstance(parsed, dict)
            or parsed.get("type") not in _STRUCTURAL_TYPES
            or not isinstance(parsed.get("ts_ns"), int)
        ):
            return f"last history record is not a structural record: {path}", None
        record = parsed
    with path.open("ab"):
        pass
    return None, record


def _check_index_files_health(
    config_path: str | None, *, collect_stats: bool = False
) -> tuple[bool, str, list[_HealthIndexFileStats] | None]:
    """Check every configured index's state and history files."""
    cfg, error = _try_load_engine_config(config_path)
    if cfg is None:
        return False, error, None
    if not cfg.indices:
        return (
            True,
            "no indices configured; nothing to check",
            [] if collect_stats else None,
        )
    from edumatcher.config import resolve_data_path

    problems: list[str] = []
    stats: list[_HealthIndexFileStats] = []
    try:
        for idx in cfg.indices:
            state_path = resolve_data_path(idx.state_file)
            history_path = resolve_data_path(idx.history_file)
            state_problem, state = _check_state_file(idx.id, state_path)
            history_problem, last = _check_history_file(history_path)
            problems += [
                f"{idx.id}: {p}" for p in (state_problem, history_problem) if p
            ]
            if collect_stats and not state_problem and not history_problem:
                updated = state.get("last_updated")
                level = state.get("last_level")
                stats.append(
                    {
                        "index_id": idx.id,
                        "state_path": str(state_path),
                        "history_path": str(history_path),
                        "history_size_bytes": history_path.stat().st_size,
                        "last_record_type": last["type"] if last else None,
                        "last_record_ts": _ns_to_iso(last["ts_ns"]) if last else None,
                        "last_level": (
                            float(level) if isinstance(level, (int, float)) else None
                        ),
                        "state_updated": (
                            datetime.fromtimestamp(updated, tz=timezone.utc).isoformat()
                            if isinstance(updated, (int, float))
                            else None
                        ),
                    }
                )
    except OSError as exc:
        return False, f"index file read/write check failed: {exc}", None
    if problems:
        return False, "; ".join(problems), None
    count = len(cfg.indices)
    noun = "index" if count == 1 else "indices"
    return (
        True,
        f"state and history checks passed for {count} {noun}",
        stats if collect_stats else None,
    )


def _run_extended_index_files_check(
    config_path: str | None,
    *,
    collect_stats: bool = False,
    timeout_sec: float = _EXTENDED_HEALTH_TIMEOUT_SEC,
) -> tuple[bool, str, list[_HealthIndexFileStats] | None]:
    """Run `_check_index_files_health`, bounded by `timeout_sec`."""
    try:
        return run_with_timeout(
            lambda: _check_index_files_health(config_path, collect_stats=collect_stats),
            timeout_sec,
        )
    except TimeoutError as exc:
        return False, f"index file check {exc}", None


def _check_zmq_health(timeout_ms: int = PING_TIMEOUT_MS) -> tuple[bool, str]:
    """Ping pm-index's health REP socket and confirm it replies."""
    return ping_health_endpoint(INDEX_HEALTH_ADDR, timeout_ms)


def _health_report(
    config_path: str | None, *, extended: bool = False, collect_stats: bool = False
) -> tuple[bool, _HealthReport]:
    pids = _find_index_pids()
    zmq_ok, zmq_detail = _check_zmq_health()
    if extended:
        files_ok, files_detail, files_stats = _run_extended_index_files_check(
            config_path, collect_stats=collect_stats
        )
        files_checked = True
    else:
        files_ok, files_detail, files_stats = (
            True,
            "skipped (pass --extended to check state and history files)",
            None,
        )
        files_checked = False
    report: _HealthReport = {
        "healthy": bool(pids) and files_ok and zmq_ok,
        "process": {
            "healthy": bool(pids),
            "pids": pids,
            "detail": "pm-index is running" if pids else "pm-index process not found",
        },
        "files": {
            "healthy": files_ok,
            "detail": files_detail,
            "checked": files_checked,
            "stats": files_stats,
        },
        "zmq": {"healthy": zmq_ok, "detail": zmq_detail},
    }
    return bool(report["healthy"]), report


def _cmd_health(args: argparse.Namespace) -> None:
    try:
        healthy, report = _health_report(
            args.config,
            extended=args.extended,
            collect_stats=args.extended and args.verbose,
        )
    except (OSError, ValueError) as exc:
        healthy = False
        report = _HealthReport(
            healthy=False,
            process={"healthy": False, "pids": [], "detail": str(exc)},
            files={
                "healthy": False,
                "detail": "health check could not run",
                "checked": False,
                "stats": None,
            },
            zmq={"healthy": False, "detail": "health check could not run"},
        )
    if args.quiet:
        raise SystemExit(0 if healthy else -1)
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        process = report["process"]
        files = report["files"]
        zmq_report = report["zmq"]
        print(
            f"pm-index process: {'OK' if process['healthy'] else 'FAIL'} - {process['detail']}"
        )
        print(
            f"index files:      {'OK' if files['healthy'] else 'FAIL'} - {files['detail']}"
        )
        print(
            f"index ZMQ ping:   {'OK' if zmq_report['healthy'] else 'FAIL'} - {zmq_report['detail']}"
        )
        print(f"health: {'OK' if healthy else 'FAIL'}")
        if args.verbose:
            print()
            print("Checks performed:")
            print("  pm-index process (pgrep):     yes")
            print("  ZMQ health ping:               yes")
            print(
                "  Index state/history files:     "
                + ("yes" if files["checked"] else "no (pass --extended)")
            )
            stats = files["stats"]
            if stats:
                print()
                print("Index files:")
                for entry in stats:
                    print(f"  {entry['index_id']}:")
                    print(f"    state:       {entry['state_path']}")
                    print(
                        f"    history:     {entry['history_path']} "
                        f"({format_bytes(entry['history_size_bytes'])})"
                    )
                    if entry["last_record_type"] is None:
                        print("    last record: (empty history)")
                    else:
                        print(
                            f"    last record: {entry['last_record_type']} "
                            f"at {entry['last_record_ts']}"
                        )
                    print(f"    last level:  {entry['last_level']}")
                    print(f"    state saved: {entry['state_updated'] or '(unknown)'}")
    raise SystemExit(0 if healthy else 1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "limit", 1) <= 0:
        print("[ERROR] --limit must be > 0", file=sys.stderr)
        raise SystemExit(2)

    if args.command == "events":
        _cmd_events(args)
    elif args.command == "indices":
        _cmd_indices(args)
    elif args.command == "health":
        _cmd_health(args)
    else:  # pragma: no cover
        parser.print_help()
        raise SystemExit(2)


if __name__ == "__main__":
    main()
