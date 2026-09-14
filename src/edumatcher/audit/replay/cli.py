"""pm-audit-replay — CLI entry point.

Usage::

    pm-audit-replay [global-options] COMMAND [command-options]

The global options are the ones design section 9.1 specifies, and they
deliberately mirror ``pm-audit-cli``'s time-window and filter flags so muscle
memory carries between the two tools.

One subcommand so far, ``stats`` (task AR-2.5): the confidence distribution
over a window. It is registered ahead of ``stream``, ``story`` and ``digest``
because it reports on the *trail* rather than narrating it, so it is useful
the moment pass 1 works -- and because the distribution is what says whether
narration can be trusted at all. A subcommand is optional: with none, the
command validates its options and exits, as it did through phase 1.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from edumatcher.audit.query import (
    date_to_range,
    discover_log_files,
    iter_entries,
    parse_ts,
    validate_date,
    validate_iso_ts,
)
from edumatcher.audit.replay import stats as stats_report
from edumatcher.audit.replay.pipeline import reconstruct
from edumatcher.config import AUDIT_LOG_FILE, AUDIT_REPLAY_DB_FILE

_FORMATS = ("text", "ndjson", "json", "markdown")
_ACTOR_STYLES = ("id", "descriptive")

#: Detail levels, design section 8.1. ``-q`` is 0 and the default is 1.
_MIN_DETAIL = 0
_MAX_DETAIL = 4

_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

#: Design section 5.2.3. Facts are buffered this long before being emitted in
#: ``msg_id`` order; one arriving later is emitted in place and tagged ``late``.
DEFAULT_REORDER_FACTS = 2000
DEFAULT_REORDER_SECONDS = 5.0


def parse_duration(value: str) -> float:
    """Return seconds for a ``15m``/``2h``/``1d`` style duration.

    Raises ``ValueError`` on anything else, including a bare number: a
    ``--last 15`` whose unit the reader has to guess is the kind of ambiguity
    this whole tool exists to remove.
    """
    text = value.strip().lower()
    if len(text) < 2 or text[-1] not in _DURATION_UNITS:
        raise ValueError(
            f"Cannot parse duration {value!r}. "
            f"Use a number followed by s, m, h or d (e.g. 15m, 2h, 1d)."
        )
    try:
        magnitude = float(text[:-1])
    except ValueError:
        raise ValueError(
            f"Cannot parse duration {value!r}: {text[:-1]!r} is not a number."
        ) from None
    if magnitude <= 0:
        raise ValueError(f"Duration {value!r} must be positive.")
    return magnitude * _DURATION_UNITS[text[-1]]


def parse_reorder_window(value: str) -> tuple[int | None, float | None]:
    """Return ``(facts, seconds)`` for a ``--reorder-window`` spec.

    The window has two independent bounds and the spec names one of them: a
    bare integer is a fact count, a duration is receipt time. Whichever is not
    named keeps its default, so ``--reorder-window 5s`` does not silently
    remove the count bound.
    """
    text = value.strip().lower()
    if text.isdigit():
        count = int(text)
        if count <= 0:
            raise ValueError(f"Reorder window {value!r} must be positive.")
        return count, None
    return None, parse_duration(text)


def parse_id_len(value: str) -> int | None:
    """Return the id abbreviation length, or None for ``full``."""
    if value.strip().lower() == "full":
        return None
    try:
        length = int(value)
    except ValueError:
        raise ValueError(
            f"Cannot parse --id-len {value!r}. Use a positive integer or 'full'."
        ) from None
    if length <= 0:
        raise ValueError(f"--id-len {value!r} must be positive.")
    return length


def _timestamp(value: str) -> str:
    """Validate an ISO-8601 or ``YYYY-MM-DD`` window bound, returning it raw.

    Kept as the original string rather than a datetime so ``--help`` output and
    error messages quote what the user typed.
    """
    validate_iso_ts(value)
    return value


def _date(value: str) -> str:
    validate_date(value)
    return value


def build_parser() -> argparse.ArgumentParser:
    """The global option surface of design section 9.1."""
    parser = argparse.ArgumentParser(
        prog="pm-audit-replay",
        description=(
            "Reconstruct the causal structure of an EduMatcher audit trail and\n"
            "narrate it. Reads the same JSONL files as pm-audit-cli, read-only."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-audit-replay")

    source = parser.add_argument_group("source")
    source.add_argument(
        "--log-file",
        default=str(AUDIT_LOG_FILE),
        metavar="PATH",
        help=(
            f"Audit log to read (default: {AUDIT_LOG_FILE}).\n"
            "Rotated .1, .2.gz ... siblings are discovered automatically."
        ),
    )
    source.add_argument(
        "--db",
        default=str(AUDIT_REPLAY_DB_FILE),
        metavar="PATH",
        help=f"Episode index (default: {AUDIT_REPLAY_DB_FILE})",
    )
    source.add_argument(
        "--no-index",
        action="store_true",
        help="Stream without building or reading an index",
    )
    source.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild the episode index before rendering",
    )

    window = parser.add_argument_group("window")
    window.add_argument(
        "--from",
        dest="from_ts",
        type=_timestamp,
        metavar="ISO_TS",
        help="Start of window (ISO-8601 or YYYY-MM-DD)",
    )
    window.add_argument(
        "--to",
        dest="to_ts",
        type=_timestamp,
        metavar="ISO_TS",
        help="End of window",
    )
    window.add_argument(
        "--date",
        type=_date,
        metavar="YYYY-MM-DD",
        help="Shorthand for a whole UTC day",
    )
    window.add_argument(
        "--last",
        type=parse_duration,
        metavar="DURATION",
        help="Relative window, e.g. 15m, 2h, 1d",
    )

    _add_commands(parser)

    narrow = parser.add_argument_group("filters")
    narrow.add_argument(
        "--symbol",
        action="append",
        metavar="SYMBOL",
        help="Restrict to one or more symbols (repeatable)",
    )
    narrow.add_argument(
        "--gateway",
        action="append",
        metavar="GW_ID",
        help="Restrict to one or more gateways (repeatable)",
    )
    narrow.add_argument(
        "--kind",
        action="append",
        metavar="KIND",
        help="Restrict to episode kinds (repeatable)",
    )

    out = parser.add_argument_group("output")
    out.add_argument(
        "-q",
        dest="quiet",
        action="store_true",
        help="Detail level 0: episode outcomes only",
    )
    out.add_argument(
        "-v",
        dest="verbose",
        action="count",
        default=0,
        help="Raise detail level: -v, -vv, -vvv (see design section 8.1)",
    )
    out.add_argument(
        "--format",
        default="text",
        choices=_FORMATS,
        help="Output format (default: text)",
    )
    out.add_argument(
        "--show-source",
        action="store_true",
        help="Append audit.log:LINE to every narrated line",
    )
    out.add_argument(
        "--show-units",
        action="store_true",
        help="Append unit provenance to every price",
    )
    out.add_argument(
        "--explain",
        action="store_true",
        help="Show link evidence and confidence inline",
    )
    out.add_argument(
        "--id-len",
        type=parse_id_len,
        default=6,
        metavar="N|full",
        help="Order-id abbreviation (default: 6)",
    )
    out.add_argument(
        "--actor-style",
        default="id",
        choices=_ACTOR_STYLES,
        help="Actor naming: id (default) or descriptive",
    )
    out.add_argument(
        "--tz",
        default="UTC",
        metavar="TZ",
        help="Render timestamps in this zone (default: UTC)",
    )
    out.add_argument(
        "--reorder-window",
        type=parse_reorder_window,
        metavar="SPEC",
        help=(
            f"Reorder buffer, e.g. {DEFAULT_REORDER_FACTS} or "
            f"{DEFAULT_REORDER_SECONDS:g}s\n"
            f"(default: {DEFAULT_REORDER_FACTS}/{DEFAULT_REORDER_SECONDS:g}s)"
        ),
    )
    out.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour",
    )
    return parser


def _add_commands(parser: argparse.ArgumentParser) -> None:
    """Register the subcommands.

    ``required=False`` on purpose: every option above is global, and
    ``pm-audit-replay --help`` has to keep working as the review surface for
    the option set while the renderers are still being built.
    """
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser(
        "stats",
        help="Report link confidence and envelope coverage over the window",
        description=(
            "How the tool arrived at what it knows. On a log recorded since\n"
            "the causal envelope landed, RECORDED should dominate; a large\n"
            "share anywhere else means a publisher is bypassing\n"
            "CausalPublisher, or that the window reaches back before it."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )


def window_bounds(args: argparse.Namespace) -> tuple[datetime | None, datetime | None]:
    """The window as two datetimes, whichever flag spelled it.

    ``validate_args`` has already rejected every combination of these, so the
    branches here are exclusive by the time this runs.
    """
    if args.date:
        return date_to_range(args.date)
    if args.last is not None:
        now = datetime.now(timezone.utc)
        return now - timedelta(seconds=args.last), now
    from_dt = parse_ts(args.from_ts) if args.from_ts else None
    to_dt = parse_ts(args.to_ts) if args.to_ts else None
    return from_dt, to_dt


def reorder_bounds(args: argparse.Namespace) -> tuple[int, float]:
    """The reorder window as its two bounds, with defaults filled in.

    ``--reorder-window`` names one bound and the other keeps its default,
    which is what stops ``--reorder-window 5s`` from silently removing the
    fact-count bound.
    """
    spec = getattr(args, "reorder_window", None)
    if not spec:
        return DEFAULT_REORDER_FACTS, DEFAULT_REORDER_SECONDS
    facts, seconds = spec
    return (
        DEFAULT_REORDER_FACTS if facts is None else facts,
        DEFAULT_REORDER_SECONDS if seconds is None else seconds,
    )


def _run_stats(args: argparse.Namespace) -> int:
    log_files = discover_log_files(Path(args.log_file))
    if not log_files:
        print(f"pm-audit-replay: no audit log at {args.log_file}", file=sys.stderr)
        return 1
    from_dt, to_dt = window_bounds(args)
    entries = iter_entries(log_files, from_dt=from_dt, to_dt=to_dt)
    max_facts, max_seconds = reorder_bounds(args)
    _run, steps = reconstruct(entries, max_facts=max_facts, max_seconds=max_seconds)
    print(stats_report.render(stats_report.collect(steps)), end="")
    return 0


def detail_level(args: argparse.Namespace) -> int:
    """Collapse ``-q`` and repeated ``-v`` onto the one axis of section 8.1."""
    if args.quiet:
        return _MIN_DETAIL
    return min(1 + int(args.verbose), _MAX_DETAIL)


def validate_args(args: argparse.Namespace) -> str | None:
    """Return an error message for a combination argparse cannot reject."""
    if args.date and (args.from_ts or args.to_ts):
        return "--date cannot be combined with --from/--to"
    if args.last is not None and (args.from_ts or args.to_ts or args.date):
        return "--last cannot be combined with --from/--to/--date"
    if args.from_ts and args.to_ts and parse_ts(args.from_ts) > parse_ts(args.to_ts):
        return "--from must not be later than --to"
    if args.quiet and args.verbose:
        return "-q cannot be combined with -v"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except ValueError as exc:  # a type= callable rejecting its input
        parser.error(str(exc))
    error = validate_args(args)
    if error:
        print(f"pm-audit-replay: {error}", file=sys.stderr)
        return 2
    if args.command == "stats":
        return _run_stats(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
