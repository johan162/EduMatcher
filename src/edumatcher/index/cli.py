"""pm-index-cli — read-only query tool for index history JSONL files.

Reads JSONL history files written by ``pm-index`` directly from disk.
No running process is required.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FORMATS = ("table", "json", "csv")
_DEFAULT_DATA_DIR = "data/indexes"

# ---------------------------------------------------------------------------
# Column definitions for each subcommand
# ---------------------------------------------------------------------------
_LEVEL_COLUMNS = [
    "ts",
    "index_id",
    "level",
    "session_state",
    "aggregate_cap",
    "divisor",
]
_EOD_COLUMNS = [
    "date",
    "index_id",
    "open",
    "high",
    "low",
    "close",
    "level",
    "aggregate_cap",
    "divisor",
]
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

# Event types shown by the 'events' subcommand (not LEVEL / EOD).
_STRUCTURAL_TYPES = {"INIT", "CORP_ACTION", "ADD_CONSTITUENT", "DELIST"}


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


def _ts_to_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Config / file resolution helpers
# ---------------------------------------------------------------------------


def _load_engine_config(config_path: str) -> Any:
    """Load EngineConfig from *config_path*, exiting on failure."""
    from edumatcher.engine.config_loader import load_engine_config

    try:
        return load_engine_config(Path(config_path))
    except Exception as exc:
        print(f"[ERROR] Could not load config {config_path!r}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _config_index_map(config_path: str) -> dict[str, Any]:
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
    if config_path is not None:
        try:
            idx_map = _config_index_map(config_path)
            for idx_id, idx_cfg in idx_map.items():
                from_config[idx_id] = idx_cfg.history_file
        except SystemExit:
            raise
        except Exception as exc:
            print(
                f"[WARNING] Could not read index paths from config: {exc}",
                file=sys.stderr,
            )

    result: dict[str, Path] = {}
    for idx_id in index_ids:
        if idx_id in from_config:
            result[idx_id] = Path(from_config[idx_id])
        else:
            result[idx_id] = Path(data_dir) / f"{idx_id}_history.jsonl"
    return result


def _resolve_index_ids(
    args: argparse.Namespace,
    config_path: str | None,
) -> list[str]:
    """Determine which index IDs to query."""
    raw: list[str] = getattr(args, "index", None) or []
    if raw:
        return [i.upper() for i in raw]
    if config_path is not None:
        idx_map = _config_index_map(config_path)
        if not idx_map:
            print("[ERROR] No indices found in engine_config.yaml.", file=sys.stderr)
            raise SystemExit(1)
        return list(idx_map.keys())
    print(
        "[ERROR] Specify at least one --index ID, or pass --config to "
        "auto-discover all configured indices.",
        file=sys.stderr,
    )
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# JSONL reading
# ---------------------------------------------------------------------------


def _read_jsonl(
    path: Path,
    from_ts: float,
    to_ts: float,
    types: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Return matching records from *path* in chronological order."""
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
                ts_f = float(rec["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            if from_ts <= ts_f <= to_ts:
                records.append(rec)
                if len(records) >= limit:
                    break
    return records


# ---------------------------------------------------------------------------
# Row projection helpers
# ---------------------------------------------------------------------------


def _project_level(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": _ts_to_str(float(rec["timestamp"])),
        "index_id": rec.get("index_id", ""),
        "level": rec.get("level"),
        "session_state": rec.get("session_state", ""),
        "aggregate_cap": rec.get("aggregate_cap"),
        "divisor": rec.get("divisor"),
    }


def _project_eod(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": _ts_to_date(float(rec["timestamp"])),
        "index_id": rec.get("index_id", ""),
        "open": rec.get("open"),
        "high": rec.get("high"),
        "low": rec.get("low"),
        "close": rec.get("close"),
        "level": rec.get("level"),
        "aggregate_cap": rec.get("aggregate_cap"),
        "divisor": rec.get("divisor"),
    }


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
        "ts": _ts_to_str(float(rec["timestamp"])),
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-index-cli",
        description=(
            "Query EduMatcher index history files directly from disk.\n"
            "No running process is required — reads JSONL files written by pm-index."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        metavar="PATH",
        help=(
            "Path to engine_config.yaml.\n"
            "Used to auto-discover history file paths and index IDs.\n"
            "Required for the 'indices' subcommand."
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

    # ------------------------------------------------------------------ level
    level_p = sub.add_parser(
        "level",
        help="Show throttled LEVEL records (index value snapshots during trading).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    level_p.add_argument(
        "--index",
        "-i",
        action="append",
        metavar="ID",
        help=(
            "Index ID to query (repeatable).\n"
            "Defaults to all configured indices when --config is given."
        ),
    )
    _add_time_args(level_p)
    level_p.add_argument(
        "--limit",
        type=int,
        default=1000,
        metavar="N",
        help="Maximum rows per index (default: 1000).",
    )

    # -------------------------------------------------------------------- eod
    eod_p = sub.add_parser(
        "eod",
        help="Show EOD records (daily open/high/low/close summaries).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    eod_p.add_argument(
        "--index",
        "-i",
        action="append",
        metavar="ID",
        help=(
            "Index ID to query (repeatable).\n"
            "Defaults to all configured indices when --config is given."
        ),
    )
    _add_time_args(eod_p)
    eod_p.add_argument(
        "--limit",
        type=int,
        default=365,
        metavar="N",
        help="Maximum rows per index (default: 365).",
    )

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
            "Defaults to all configured indices when --config is given."
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
        help="List indices configured in engine_config.yaml (requires --config).",
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


def _cmd_level(args: argparse.Namespace) -> None:
    index_ids = _resolve_index_ids(args, args.config)
    from_ts, to_ts = _resolve_time_range(args)
    hist_paths = _resolve_history_files(index_ids, args.config, args.data_dir)

    rows: list[dict[str, Any]] = []
    for idx_id in index_ids:
        for rec in _read_jsonl(
            hist_paths[idx_id], from_ts, to_ts, {"LEVEL"}, args.limit
        ):
            rows.append(_project_level(rec))

    _render(rows, _LEVEL_COLUMNS, args.format, args.no_header)


def _cmd_eod(args: argparse.Namespace) -> None:
    index_ids = _resolve_index_ids(args, args.config)
    from_ts, to_ts = _resolve_time_range(args)
    hist_paths = _resolve_history_files(index_ids, args.config, args.data_dir)

    rows: list[dict[str, Any]] = []
    for idx_id in index_ids:
        for rec in _read_jsonl(hist_paths[idx_id], from_ts, to_ts, {"EOD"}, args.limit):
            rows.append(_project_eod(rec))

    _render(rows, _EOD_COLUMNS, args.format, args.no_header)


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

    rows: list[dict[str, Any]] = []
    for idx_id in index_ids:
        for rec in _read_jsonl(hist_paths[idx_id], from_ts, to_ts, types, args.limit):
            rows.append(_project_event(rec))

    _render(rows, _EVENTS_COLUMNS, args.format, args.no_header)


def _cmd_indices(args: argparse.Namespace) -> None:
    if args.config is None:
        print(
            "[ERROR] --config is required for the 'indices' subcommand.",
            file=sys.stderr,
        )
        raise SystemExit(2)
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
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if getattr(args, "limit", 1) <= 0:
        print("[ERROR] --limit must be > 0", file=sys.stderr)
        raise SystemExit(2)

    if args.command == "level":
        _cmd_level(args)
    elif args.command == "eod":
        _cmd_eod(args)
    elif args.command == "events":
        _cmd_events(args)
    elif args.command == "indices":
        _cmd_indices(args)
    else:  # pragma: no cover
        parser.print_help()
        raise SystemExit(2)


if __name__ == "__main__":
    main()
