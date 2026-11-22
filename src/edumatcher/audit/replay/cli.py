"""pm-audit-replay — CLI entry point.

Usage::

    pm-audit-replay [global-options] COMMAND [command-options]

The global options are the ones design section 9.1 specifies, and they
deliberately mirror ``pm-audit-cli``'s time-window and filter flags so muscle
memory carries between the two tools.

Nine subcommands, one required. The reports -- ``stream``, ``episodes``,
``digest``, ``anomalies`` and ``stats`` -- reconstruct their window straight
off the log (:func:`_stream_from_log`) and never touch the index; ``anomalies``,
``episodes``, ``digest`` and ``stats`` keep one row, one finding list or one
ranking per episode rather than the episodes themselves. ``story`` and
``index`` read and build the episode index (section 9.7). ``rerun`` and
``queue`` feed the whole trail of the data directory to a fresh engine.

**The index policy lives in :func:`ensure_index`**, one function rather than a
rule each command reimplements. ``--rebuild`` forces a build; otherwise the
index is built when it is absent or was built under other rules, schema or
detection settings. A trail that has only grown since is read from the index
as it stands by ``story``, with a note naming how far it reaches, and rebuilt
by ``index``. There is no incremental build (AR-3.4 records why): a rebuild
reads the whole trail at about 6 000 lines a second, which is minutes for a
session's log and over an hour for a simulation day.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import shlex
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from edumatcher.cli_pipe import pipe_safe
from edumatcher.audit.archive import session_timezone
from edumatcher.audit.query import (
    AuditEntry,
    discover_day_files,
    discover_log_files,
    is_explicit_file,
    iter_entries,
    parse_ts,
    validate_date,
    validate_iso_ts,
)
from edumatcher.audit.replay import episodes as episodes_mod
from edumatcher.audit.replay import index as episode_index
from edumatcher.audit.replay import reader
from edumatcher.audit.replay import render_json
from edumatcher.audit.replay import render_text
from edumatcher.audit.replay import stats as stats_report
from edumatcher.audit.replay import terminal
from edumatcher.audit.replay import views
from edumatcher.audit.replay.anomalies import SEVERITY_INFO
from edumatcher.audit.replay.detect import (
    DEFAULT_CLOCK_SKEW_WARN,
    Detector,
    detected,
    observed,
)
from edumatcher.audit.replay.episodes import Episode, assemble
from edumatcher.audit.replay.pipeline import reconstruct
from edumatcher.audit.replay.state import StateModel
from edumatcher.config import AUDIT_LOG_FILE, AUDIT_REPLAY_DB_FILE

_FORMATS = ("text", "ndjson", "json", "markdown", "csv")

#: The section 11 shapes, and the commands that can produce them. A format a
#: command does not implement is refused rather than silently ignored: a tool
#: that accepts `--format json` and prints a table has told the caller
#: something untrue, and a script will only find out by parsing the table.
_FORMAT_COMMANDS = {
    "csv": ("episodes",),
    "ndjson": ("stream", "story", "anomalies"),
    "json": ("stream", "story", "anomalies"),
    "markdown": ("stream", "story"),
}
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


def parse_top(value: str) -> int:
    """``digest --top``: a count of episodes, at least one."""
    count = int(value)
    if count < 1:
        raise ValueError(f"--top {value!r} must be at least 1.")
    return count


def parse_skew(value: str) -> float:
    """``--clock-skew-warn``: seconds, finite and not negative.

    A negative tolerance reported every stamped message; ``nan`` compares
    false with everything and so switched the check off without saying so.
    """
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(
            f"--clock-skew-warn {value!r} must be a number of seconds >= 0."
        )
    return seconds


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


def _option_groups(
    parser: argparse.ArgumentParser, *, suppress: bool
) -> argparse.ArgumentParser:
    """Add the section 9.1 options to *parser*.

    Called twice: once for the top-level parser with real defaults, and once
    for a parent the subcommands inherit, where every default is ``SUPPRESS``.
    That is what lets a global be written on either side of the subcommand --
    ``stream --symbol AAPL`` and ``--symbol AAPL stream`` both work -- without
    the subparser's own defaults quietly overwriting what was parsed before
    it, which is the standard argparse trap here.
    """

    def default(value: Any) -> Any:
        return argparse.SUPPRESS if suppress else value

    source = parser.add_argument_group("source")
    source.add_argument(
        "--log-file",
        metavar="PATH",
        default=default(str(AUDIT_LOG_FILE)),
        help=(
            f"Audit log to read (default: {AUDIT_LOG_FILE}).\n"
            "Reads the live trail: unarchived day parts, then this file.\n"
            "An archive or day part named here is read alone."
        ),
    )
    source.add_argument(
        "--db",
        metavar="PATH",
        default=default(str(AUDIT_REPLAY_DB_FILE)),
        help=(
            f"Episode index story and index use (default: {AUDIT_REPLAY_DB_FILE});\n"
            "the reports name it in the story commands they suggest"
        ),
    )
    source.add_argument(
        "--rebuild",
        action="store_true",
        default=default(False),
        help="story, index: rebuild the episode index first",
    )

    window = parser.add_argument_group("window")
    window.add_argument(
        "--from",
        dest="from_ts",
        type=_timestamp,
        metavar="ISO_TS",
        default=default(None),
        help="Start of window (ISO-8601 or YYYY-MM-DD)",
    )
    window.add_argument(
        "--to",
        dest="to_ts",
        type=_timestamp,
        metavar="ISO_TS",
        default=default(None),
        help="End of window",
    )
    window.add_argument(
        "--date",
        type=_date,
        metavar="YYYY-MM-DD",
        default=default(None),
        help=(
            "Read this trading day (session timezone): its archive, or its "
            "parts before it is archived"
        ),
    )
    window.add_argument(
        "--last",
        type=parse_duration,
        metavar="DURATION",
        default=default(None),
        help="Relative window, e.g. 15m, 2h, 1d",
    )

    narrow = parser.add_argument_group("filters")
    narrow.add_argument(
        "--symbol",
        action="append",
        metavar="SYMBOL",
        default=default(None),
        help="Restrict to one or more symbols (repeatable)",
    )
    narrow.add_argument(
        "--gateway",
        action="append",
        metavar="GW_ID",
        default=default(None),
        help="Restrict to one or more gateways (repeatable)",
    )
    narrow.add_argument(
        "--kind",
        action="append",
        metavar="KIND",
        default=default(None),
        help="Restrict to episode kinds (repeatable)",
    )

    out = parser.add_argument_group("output")
    out.add_argument(
        "-q",
        dest="quiet",
        action="store_true",
        default=default(False),
        help="Detail level 0: episode outcomes only",
    )
    out.add_argument(
        "-v",
        dest="verbose",
        action="count",
        default=default(0),
        help="Raise detail level: -v, -vv, -vvv (see design section 8.1)",
    )
    out.add_argument(
        "--format",
        choices=_FORMATS,
        default=default("text"),
        help="Output format (default: text)",
    )
    out.add_argument(
        "--show-source",
        action="store_true",
        default=default(False),
        help="Append audit.log:LINE to every narrated line",
    )
    out.add_argument(
        "--show-units",
        action="store_true",
        default=default(False),
        help="Append unit provenance to every price",
    )
    out.add_argument(
        "--explain",
        action="store_true",
        default=default(False),
        help="Show link evidence and confidence inline",
    )
    out.add_argument(
        "--id-len",
        type=parse_id_len,
        metavar="N|full",
        default=default(6),
        help="Order-id abbreviation (default: 6)",
    )
    out.add_argument(
        "--actor-style",
        choices=_ACTOR_STYLES,
        default=default("id"),
        help="Actor naming: id (default) or descriptive",
    )
    out.add_argument(
        "--tz",
        metavar="TZ",
        type=terminal.parse_tz,
        default=default(terminal.parse_tz("UTC")),
        help="Render timestamps in this zone (default: UTC)",
    )
    out.add_argument(
        "--reorder-window",
        type=parse_reorder_window,
        metavar="SPEC",
        default=default(None),
        help=(
            f"Reorder buffer, e.g. {DEFAULT_REORDER_FACTS} or "
            f"{DEFAULT_REORDER_SECONDS:g}s\n"
            f"(default: {DEFAULT_REORDER_FACTS}/{DEFAULT_REORDER_SECONDS:g}s)"
        ),
    )
    out.add_argument(
        "--no-color",
        action="store_true",
        default=default(False),
        help="Never emit ANSI colour, even to a terminal",
    )
    out.add_argument(
        "--force-color",
        action="store_true",
        default=default(False),
        help=(
            "Emit ANSI colour even when stdout is not a terminal,\n"
            "for a pager that renders it: `... --force-color | less -R`"
        ),
    )

    # Pass-one knobs, like --reorder-window above: they change what is
    # *detected*, not how it is printed, so an index built under one value
    # does not hold the answers the other asks for. Both are part of the
    # index's recorded detection settings and a change to either forces a
    # rebuild.
    detection = parser.add_argument_group("detection")
    detection.add_argument(
        "--strict",
        action="store_true",
        default=default(False),
        help="Report findings that are expected at a window edge (ARRIVAL_SEQ_GAP)",
    )
    detection.add_argument(
        "--clock-skew-warn",
        type=parse_skew,
        metavar="SECONDS",
        default=default(DEFAULT_CLOCK_SKEW_WARN),
        help=(
            "Engine/receipt clock difference worth reporting\n"
            f"(default: {DEFAULT_CLOCK_SKEW_WARN:g}s)"
        ),
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    """The global option surface of design section 9.1."""
    parser = argparse.ArgumentParser(
        prog="pm-audit-replay",
        description=(
            "Reconstruct the causal structure of an EduMatcher audit trail and\n"
            "narrate it. Reads the same JSONL files as pm-audit-cli, read-only."
        ),
    )

    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-audit-replay")
    _option_groups(parser, suppress=False)
    _add_commands(parser, _inherited())
    return parser


def _inherited() -> argparse.ArgumentParser:
    """A parent carrying every global option with no defaults of its own."""
    parent = argparse.ArgumentParser(add_help=False)
    return _option_groups(parent, suppress=True)


def _add_commands(
    parser: argparse.ArgumentParser, inherited: argparse.ArgumentParser
) -> None:
    """Register the subcommands; one is required (exit 2 with usage)."""
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    commands.add_parser(
        "stream",
        parents=[inherited],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Narrate a window chronologically (the default view)",
        description=(
            "Everything the exchange did, in causal order (section 9.2).\n"
            "Detail is one axis: -q for outcomes only, -v and -vv for more."
        ),
    )

    story = commands.add_parser(
        "story",
        parents=[inherited],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Narrate one entity and what it is connected to",
        description=(
            "One episode and everything causally connected to it (section\n"
            "9.3). Exactly one selector; --chain is the complete descent and\n"
            "needs no --depth."
        ),
    )
    selector = story.add_mutually_exclusive_group(required=True)
    for flag, dest, metavar, helptext in _STORY_SELECTORS:
        selector.add_argument(flag, dest=dest, metavar=metavar, help=helptext)
    story.add_argument(
        "--depth",
        type=int,
        default=DEFAULT_STORY_DEPTH,
        metavar="N",
        help=f"Link-following depth (default: {DEFAULT_STORY_DEPTH})",
    )
    story.add_argument(
        "--strict-causality",
        action="store_true",
        help="Follow only RECORDED links, never an inferred one",
    )

    commands.add_parser(
        "index",
        parents=[inherited],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Build or refresh the episode index",
        description=(
            "Materialise the episode model into SQLite (design section 9.7).\n"
            "Rebuilds whenever the reconstruction rules or the source logs\n"
            "have changed; --rebuild forces one regardless. There is no\n"
            "incremental mode -- see AR-3.4 in the design for why."
        ),
    ).add_argument(
        "--stats",
        dest="index_stats",
        action="store_true",
        help="Report what the index holds once it is current",
    )
    digest = commands.add_parser(
        "digest",
        parents=[inherited],
        formatter_class=argparse.RawTextHelpFormatter,
        help="One paragraph per episode, most significant first",
        description=(
            "A whole session or a whole day, collapsed (design section 9.4).\n"
            'Answers "what kind of day was it?" rather than "what happened\n'
            'at 09:31?". Ranked, not chronological -- --significance has a\n'
            "default, so the ordering it implies applies with or without --top."
        ),
    )
    digest.add_argument(
        "--top",
        type=parse_top,
        metavar="N",
        default=None,
        help="Show only the N most significant episodes",
    )
    digest.add_argument(
        "--significance",
        choices=views.SIGNIFICANCE_RULES,
        default=views.SIGNIFICANCE_ANOMALIES,
        help=(
            "What makes an episode significant\n"
            f"(default: {views.SIGNIFICANCE_ANOMALIES}, then notional)"
        ),
    )

    listing = commands.add_parser(
        "episodes",
        parents=[inherited],
        formatter_class=argparse.RawTextHelpFormatter,
        help="The index as a table, one row per episode",
        description=(
            "A structured listing (design section 9.5): kind, anchor, actor,\n"
            "symbol, span, outcome and a finding count. How you locate the\n"
            "episode you then want a story for. --format csv for export."
        ),
    )
    listing.add_argument(
        "--outcome",
        action="append",
        metavar="OUTCOME",
        default=None,
        help="Restrict to episode outcomes, e.g. REJECTED (repeatable)",
    )

    commands.add_parser(
        "anomalies",
        parents=[inherited],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Every finding, worst first, with the story command to run next",
        description=(
            "The bug-hunting view (design section 9.6). Every finding from\n"
            "section 12, ordered by severity then time, each with the episode\n"
            "it belongs to. --severity is a floor, not a filter on one level."
        ),
    ).add_argument(
        "--severity",
        choices=views.SEVERITY_ORDER,
        default=SEVERITY_INFO,
        help="Report findings at this severity or worse (default: info)",
    )

    commands.add_parser(
        "rerun",
        parents=[inherited],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Feed the audit's commands to a fresh engine and compare",
        description=(
            "Re-execute the trail (design: Audit-Completeness-Workplan A4).\n"
            "Builds an engine from the config in system.startup, feeds it every\n"
            "echoed command in order and compares what it publishes with what\n"
            "the live engine did; an engine restart is re-run as a restart.\n"
            "Needs a trail that begins at an engine start with an empty book,\n"
            "carries each run's config, and has no proven hole (eseq gap,\n"
            "recorder restart while the engine ran). Exit 0 clean, 1 on a\n"
            "difference, 3 when the trail cannot be re-run."
        ),
    )
    queue = commands.add_parser(
        "queue",
        parents=[inherited],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Where an order stood in its level, or what a price level did",
        description=(
            "Follow a resting order or a price level through the day by\n"
            "observing the re-run (Audit-Completeness-Workplan A8). Needs a\n"
            "trail `rerun` can re-run. Exit 0 answered, 1 order not in the\n"
            "trail, 2 bad arguments, 3 the trail cannot be re-run."
        ),
    )
    queue.add_argument(
        "--order", metavar="ID", help="Order view: the order id, or a prefix of it"
    )
    queue.add_argument(
        "--price",
        type=float,
        metavar="P",
        help="Level view: the display price (with the global --symbol)",
    )
    queue.add_argument(
        "--side", choices=("BUY", "SELL"), help="Level view: one side of the level"
    )
    queue.add_argument(
        "--anonymise",
        action="store_true",
        help=(
            "Name other gateways A, B, C and leave out iceberg reserve, so the\n"
            "output can be quoted to a participant"
        ),
    )
    commands.add_parser(
        "stats",
        parents=[inherited],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Report link confidence and envelope coverage over the window",
        description=(
            "How the tool arrived at what it knows. On a log recorded since\n"
            "the causal envelope landed, RECORDED should dominate; a large\n"
            "share anywhere else means a publisher is bypassing\n"
            "CausalPublisher, or that the window reaches back before it."
        ),
    )


def window_bounds(args: argparse.Namespace) -> tuple[datetime | None, datetime | None]:
    """The window as two datetimes, whichever flag spelled it.

    ``validate_args`` has already rejected every combination of these, so the
    branches here are exclusive by the time this runs.
    """
    if args.last is not None:
        now = datetime.now(timezone.utc)
        return now - timedelta(seconds=args.last), now
    from_dt = parse_ts(args.from_ts) if args.from_ts else None
    # A bare date is the end of that day, as in pm-audit-cli.
    to_dt = parse_ts(args.to_ts, end_of_day=True) if args.to_ts else None
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


#: ``story``'s selectors (section 9.3): ``(flag, dest, metavar, help)``.
#:
#: The dest is spelled out because one of them has to be. ``--command`` would
#: otherwise land on ``args.command``, which is where the subparsers action
#: records *which subcommand was chosen* -- and argparse copies the
#: subparser's namespace over the parent's afterwards, so choosing ``story``
#: was silently overwritten with None. The failure was total and silent, and
#: it hit the one selector the plan names in its acceptance criteria.
_STORY_SELECTORS: tuple[tuple[str, str, str, str], ...] = (
    ("--order", "order", "ORDER_ID", "Follow an order (an unambiguous prefix will do)"),
    ("--trade", "trade", "TRADE_ID", "Follow a trade and both its legs"),
    ("--quote", "quote", "QUOTE_ID", "Follow a quote and its derived leg orders"),
    ("--oco", "oco", "OCO_ID", "Follow an OCO pair"),
    ("--combo", "combo", "COMBO_ID", "Follow a combo and its legs"),
    (
        "--command",
        "command_id",
        "COMMAND_ID",
        "Follow a risk/admin command and its effects",
    ),
    ("--client-tag", "client_tag", "TAG", "Follow by the client's own tag"),
    ("--chain", "chain", "ULID", "Follow a whole causal chain (the complete descent)"),
    ("--msg", "msg", "ULID", "Follow one message and what it caused"),
)

#: Which episode kind each selector looks in, by its dest.
_SELECTOR_KINDS: dict[str, str] = {
    "order": episodes_mod.KIND_ORDER,
    "trade": episodes_mod.KIND_TRADE,
    "quote": episodes_mod.KIND_QUOTE,
    "oco": episodes_mod.KIND_OCO,
    "combo": episodes_mod.KIND_COMBO,
    "command_id": episodes_mod.KIND_COMMAND,
}

#: Section 9.3's default. Two hops reaches an order's trades and their
#: counterparty orders, which is what "what happened to this order" means.
DEFAULT_STORY_DEPTH = 2


def _log_files(args: argparse.Namespace) -> list[Path]:
    """The live trail, or with ``--date`` that trading day's archive or parts.

    A day is its files (session timezone), so ``--date`` sets no time window.
    """
    log_file = Path(args.log_file)
    if args.date:
        return discover_day_files(log_file, args.date, session_timezone())
    return discover_log_files(log_file)


def detection_key(args: argparse.Namespace) -> str:
    """The detection settings, canonically, for the index to record.

    Compared as a string rather than field by field so that adding an option
    is one edit here and nothing anywhere else.
    """
    return f"strict={int(args.strict)} clock_skew={args.clock_skew_warn:g}"


def _detector(state: StateModel, args: argparse.Namespace) -> Detector:
    return Detector(state, strict=args.strict, clock_skew_warn=args.clock_skew_warn)


def build_index(args: argparse.Namespace, log_files: list[Path]) -> int:
    """Run the whole pipeline into the index, returning the episode count.

    The whole log, never the query's window. The index is a cache of the
    reconstruction and a cache may not depend on the question that happened
    to populate it: narrowing the build by ``--from``/``--to``/``--date``/
    ``--last`` produced an index that answered a later, wider query with a
    truncated window and said nothing about it -- an OCO reported ``OPEN``
    when the trail plainly said ``CANCELLED``, exit 0. Its currency check is
    the source fingerprint, which cannot see a window, and adding the window
    to that check would instead rebuild on almost every ``--last`` call,
    since a relative window moves.

    So the window is a property of the *query* only, and only ``story``
    queries the index; the reports read their window off the log.
    """
    entries = iter_entries(log_files)
    max_facts, max_seconds = reorder_bounds(args)
    run, steps = reconstruct(entries, max_facts=max_facts, max_seconds=max_seconds)
    detector = _detector(run.state, args)
    episodes = detected(
        assemble(
            observed(steps, detector),
            run.state,
            run.links,
            max_facts=max_facts,
            max_seconds=max_seconds,
        ),
        detector,
    )
    return episode_index.build(
        Path(args.db),
        episodes,
        run.state,
        log_files,
        detection=detection_key(args),
    )


def ensure_index(
    args: argparse.Namespace, log_files: list[Path], *, refresh: bool
) -> sqlite3.Connection:
    """A readonly connection to the index, built first when it must be.

    Built when absent, when built under other rules, schema or detection
    settings, and on ``--rebuild``. When only the trail has changed since,
    *refresh* (the ``index`` command) rebuilds; otherwise (``story``) an
    index of a trail that has only grown -- every file it read, bar the live
    ``--log-file``, is still part of the trail -- is read as it stands, with a
    note on stderr naming how far it reaches. A running exchange's trail grows
    every millisecond, and a rebuild of a simulation day is over an hour and
    tens of gigabytes; the episodes the index holds are still the trail's.
    """
    db = Path(args.db)
    if not args.rebuild:
        try:
            conn = episode_index.open_readonly(db)
        except FileNotFoundError, episode_index.StaleIndexError:
            conn = None
        if conn is not None:
            if episode_index.read_meta(
                conn, episode_index.META_DETECTION
            ) == detection_key(args):
                if episode_index.is_current(conn, log_files):
                    return conn
                if not refresh and _only_grown(conn, log_files, Path(args.log_file)):
                    _say_how_far(conn, db)
                    return conn
            # Close the handle before rebuilding, or it outlives the database
            # it was opened on.
            conn.close()
    build_index(args, log_files)
    return episode_index.open_readonly(db)


def _only_grown(conn: sqlite3.Connection, log_files: list[Path], live: Path) -> bool:
    """Whether every file the index read, bar the live log, is still in the
    trail: the trail has grown (or the live log rotated into a part), rather
    than become another trail (another ``--date``, an archived day)."""
    read = json.loads(
        episode_index.read_meta(conn, episode_index.META_SOURCE_FILES) or "[]"
    )
    trail = {str(path) for path in log_files}
    return all(path in trail for path in read if path != str(live))


def _say_how_far(conn: sqlite3.Connection, db: Path) -> None:
    covered_to = episode_index.read_meta(conn, episode_index.META_COVERED_TO)
    print(
        f"pm-audit-replay: the index ({db}) covers the trail to {covered_to}; "
        "the trail has grown since. Add --rebuild to include the rest.",
        file=sys.stderr,
    )


def _run_index(args: argparse.Namespace) -> int:
    log_files = _log_files(args)
    if not log_files:
        print(f"pm-audit-replay: no audit log at {args.log_file}", file=sys.stderr)
        return 1
    conn = ensure_index(args, log_files, refresh=True)
    try:
        if args.index_stats:
            print(render_index_stats(conn), end="")
        else:
            counts = _index_counts(conn)
            print(f"{Path(args.db)}: {counts['episodes']} episodes")
        return 0
    finally:
        conn.close()


_COUNTED = (
    "episodes",
    "episode_events",
    "links",
    "stated_links",
    "anomalies",
    "actors",
)


def _index_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in _COUNTED
    }


def render_index_stats(conn: sqlite3.Connection) -> str:
    """What the index holds, for ``index --stats`` (design section 9.7)."""
    meta = episode_index.describe(conn)
    lines = ["Episode index", ""]
    for key in (
        episode_index.META_SCHEMA_VERSION,
        episode_index.META_RULES_VERSION,
        episode_index.META_BUILT_AT,
        episode_index.META_COVERED_FROM,
        episode_index.META_COVERED_TO,
        episode_index.META_DETECTION,
    ):
        lines.append(f"  {key:<16} {meta.get(key, '-')}")
    lines.append("")
    for table, count in _index_counts(conn).items():
        lines.append(f"  {table:<16} {count}")
    by_kind = conn.execute(
        "SELECT kind, COUNT(*) AS n FROM episodes GROUP BY kind ORDER BY n DESC"
    ).fetchall()
    if by_kind:
        lines.extend(["", "  episodes by kind"])
        lines.extend(f"    {row['kind']:<14} {row['n']}" for row in by_kind)
    return "\n".join(lines) + "\n"


def render_options(args: argparse.Namespace) -> render_text.Options:
    """The section 8 switches, off one namespace."""
    return render_text.Options(
        level=detail_level(args),
        id_len=args.id_len,
        descriptive_actors=args.actor_style == "descriptive",
        show_source=args.show_source,
        show_units=args.show_units,
        explain=args.explain,
        tz=args.tz,
        palette=_palette(args),
    )


def _palette(args: argparse.Namespace) -> terminal.Palette:
    """Colour for a terminal, plain for anything else.

    Read once per invocation rather than per line, and from the real
    ``sys.stdout`` so that a redirect, a pipe or a capturing test all reach
    the same answer without being asked.
    """
    return terminal.palette_for(args.no_color, force=args.force_color)


def _narrate(
    episodes: Sequence[Episode], state: StateModel | None, args: argparse.Namespace
) -> int:
    """The window, in whichever of section 11's shapes was asked for.

    One choke point for both narrating commands, and all four formats read
    the same episodes at the same options -- which is what `--format` is for:
    a choice of rendering, never a choice of content.
    """
    if not episodes:
        print("pm-audit-replay: nothing to narrate in this window", file=sys.stderr)
        return 1
    options = render_options(args)
    if args.format == "ndjson":
        lines: Sequence[str] = render_json.ndjson(episodes, state, options)
    elif args.format == "json":
        from_dt, to_dt = window_bounds(args)
        return _print(
            [
                render_json.document(
                    episodes,
                    state,
                    options,
                    window={
                        "from": from_dt.isoformat() if from_dt else None,
                        "to": to_dt.isoformat() if to_dt else None,
                    },
                    source_files=[str(path) for path in _log_files(args)],
                    rules_version=episode_index.RULES_VERSION,
                )
            ]
        )
    elif args.format == "markdown":
        lines = render_json.markdown(episodes, state, options)
    else:
        lines = render_text.narrate(episodes, state, options)
    return _print(lines)


def _print(lines: Sequence[str]) -> int:
    for line in lines:
        print(line)
    return 0


def _stream_from_log(
    args: argparse.Namespace, log_files: list[Path]
) -> tuple[Iterator[Episode], StateModel]:
    """The window's episodes as they retire, filtered, straight off the log.

    An iterator: a caller that needs one episode at a time holds one.
    """
    from_dt, to_dt = window_bounds(args)
    max_facts, max_seconds = reorder_bounds(args)
    run, steps = reconstruct(
        _window(log_files, from_dt, to_dt, max_seconds),
        max_facts=max_facts,
        max_seconds=max_seconds,
    )
    detector = _detector(run.state, args)
    episodes = detected(
        assemble(
            observed(steps, detector),
            run.state,
            run.links,
            max_facts=max_facts,
            max_seconds=max_seconds,
        ),
        detector,
    )
    return (episode for episode in episodes if _wanted(episode, args)), run.state


def _window(
    log_files: list[Path],
    from_dt: datetime | None,
    to_dt: datetime | None,
    slack: float,
) -> Iterator[AuditEntry]:
    """The lines of the window, and no read outside it.

    A closed part that ends before ``from_dt`` is not opened
    (:func:`_ends_before`). ``iter_entries`` skips the lines before
    ``from_dt`` unparsed, but with a ``to_dt`` it still parses every later
    line to the end of the trail only to drop it -- about 5 s per 256 MB
    part. Lines are in receipt order, so once one is stamped more than
    *slack* (the reorder window) past ``to_dt``, nothing later belongs to the
    window and the read stops.
    """
    if from_dt is not None:
        # The last file is the live log, still being written.
        log_files = [
            path for path in log_files[:-1] if not _ends_before(path, from_dt)
        ] + log_files[-1:]
    if to_dt is None:
        yield from iter_entries(log_files, from_dt=from_dt)
        return
    stop = to_dt + timedelta(seconds=slack)
    for entry in iter_entries(log_files, from_dt=from_dt):
        try:
            when = parse_ts(entry.timestamp)
        except ValueError:
            continue
        if when <= to_dt:
            yield entry
        elif when > stop:
            return


#: How far back from a plain part's end :func:`_ends_before` looks for its last
#: line: far more than any one audit line.
_TAIL_BYTES = 1 << 20


def _ends_before(path: Path, when: datetime) -> bool:
    """Whether a closed plain-text part's last line is stamped before *when*.

    Read from the end of the file, so deciding costs one seek rather than
    the 0.2 s of skipping a 256 MB part line by line. False whenever it
    cannot tell (a compressed archive, no stamped line in the tail), which
    is the safe direction: the part is then read.
    """
    if path.suffix != ".log":
        return False
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - _TAIL_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    for raw in reversed(tail.splitlines()):
        if raw.startswith("[") and "]" in raw:
            try:
                return parse_ts(raw[1 : raw.index("]")]) < when
            except ValueError:
                return False
    return False


def _from_log(
    args: argparse.Namespace, log_files: list[Path]
) -> tuple[list[Episode], StateModel]:
    """The window's episodes, filtered, held in memory (``stream`` needs all of
    them at once: a sentence names the counterparty's order)."""
    episodes, state = _stream_from_log(args, log_files)
    return list(episodes), state


def _run_stream(args: argparse.Namespace) -> int:
    log_files = _log_files(args)
    if not log_files:
        print(f"pm-audit-replay: no audit log at {args.log_file}", file=sys.stderr)
        return 1
    episodes, state = _from_log(args, log_files)
    return _narrate(episodes, state, args)


def _wanted(episode: Episode, args: argparse.Namespace) -> bool:
    """The ``--symbol``/``--gateway``/``--kind`` filters on one episode.

    The same predicates ``reader.episodes_in_window`` applies in SQL.
    """
    return (
        (not args.symbol or episode.symbol in args.symbol)
        and (not args.gateway or episode.actor in args.gateway)
        and (not args.kind or episode.kind in args.kind)
    )


class _Counted:
    """The window's episodes, counted as a report consumes them.

    The reports below keep a row, a finding list or a ranking rather than
    the episodes, so the count of what the window held -- for "nothing to
    narrate" and for the tallies -- is taken on the way through.
    """

    def __init__(self, episodes: Iterator[Episode]) -> None:
        self._episodes = episodes
        self.count = 0

    def __iter__(self) -> Iterator[Episode]:
        for episode in self._episodes:
            self.count += 1
            yield episode


def _run_view(args: argparse.Namespace, render: Callable[[_Counted], str]) -> int:
    """Stream the window through one of section 9.4-9.6's reports."""
    log_files = _log_files(args)
    if not log_files:
        print(f"pm-audit-replay: no audit log at {args.log_file}", file=sys.stderr)
        return 1
    stream, _state = _stream_from_log(args, log_files)
    episodes = _Counted(stream)
    text = render(episodes)
    if not episodes.count:
        print("pm-audit-replay: nothing to narrate in this window", file=sys.stderr)
        return 1
    print(text, end="")
    return 0


def _run_digest(args: argparse.Namespace) -> int:
    """One row per episode, or with ``--top N`` only the N most significant
    (``heapq.nsmallest`` keeps N rows, not the window)."""

    def render(episodes: _Counted) -> str:
        rows = (views.row(episode) for episode in episodes)
        kept = (
            list(rows)
            if args.top is None
            else heapq.nsmallest(
                args.top, rows, key=views.digest_key(args.significance)
            )
        )
        return views.render_digest(
            kept,
            significance=args.significance,
            top=args.top,
            total=episodes.count,
            id_len=args.id_len,
            tz=args.tz,
            palette=_palette(args),
        )

    return _run_view(args, render)


def _run_episodes(args: argparse.Namespace) -> int:
    return _run_view(
        args,
        lambda episodes: views.render_episodes(
            [
                views.row(episode, derived=False)
                for episode in episodes
                if not args.outcome or episode.outcome in args.outcome
            ],
            as_csv=args.format == "csv",
            id_len=args.id_len,
            tz=args.tz,
            palette=_palette(args),
        ),
    )


def _run_anomalies(args: argparse.Namespace) -> int:
    """Only the episodes with a finding at ``--severity`` or worse are kept."""

    def render(episodes: _Counted) -> str:
        found = [
            views.row(episode, derived=False)
            for episode in episodes
            if views.has_finding(episode, args.severity)
        ]
        if args.format in ("ndjson", "json"):
            objects = render_json.anomalies(
                found, severity=args.severity, story_source=story_source(args)
            )
            if args.format == "json":
                return render_json.dumps(list(objects)) + "\n"
            return "".join(f"{render_json.dumps(obj)}\n" for obj in objects)
        return views.render_anomalies(
            found,
            severity=args.severity,
            story_source=story_source(args),
            total=episodes.count,
            id_len=args.id_len,
            tz=args.tz,
            palette=_palette(args),
        )

    return _run_view(args, render)


def story_source(args: argparse.Namespace) -> str:
    """The source options a suggested ``story`` command needs to read the
    same trail and index this run read: ``--log-file`` and ``--db`` when not
    the defaults, and ``--date``. Shell-quoted, ready to paste."""
    parts: list[str] = []
    if args.log_file != str(AUDIT_LOG_FILE):
        parts += ["--log-file", shlex.quote(args.log_file)]
    if args.db != str(AUDIT_REPLAY_DB_FILE):
        parts += ["--db", shlex.quote(args.db)]
    if args.date:
        parts += ["--date", args.date]
    return " ".join(parts)


def _run_story(args: argparse.Namespace) -> int:
    log_files = _log_files(args)
    if not log_files:
        print(f"pm-audit-replay: no audit log at {args.log_file}", file=sys.stderr)
        return 1
    conn = ensure_index(args, log_files, refresh=False)
    try:
        if args.chain:
            episodes = reader.episodes_in_chain(conn, args.chain)
            if not episodes:
                return _not_found(args, "chain", args.chain)
            return _narrate(episodes, reader.actors(conn), args)
        seeds, label, value = _seeds(conn, args)
        if not seeds:
            return _not_found(args, label, value)
        episodes = reader.walk(
            conn, seeds, depth=args.depth, recorded_only=args.strict_causality
        )
        return _narrate(episodes, reader.actors(conn), args)
    finally:
        conn.close()


def _seeds(
    conn: sqlite3.Connection, args: argparse.Namespace
) -> tuple[list[Episode], str, str]:
    for dest, kind in _SELECTOR_KINDS.items():
        value = getattr(args, dest, None)
        if value:
            return reader.episodes_by_anchor(conn, kind, value), kind, value
    if args.client_tag:
        tagged = reader.episode_by_client_tag(conn, args.client_tag)
        return [tagged] if tagged else [], "tag", args.client_tag
    found = reader.episode_containing(conn, args.msg)
    return [found] if found else [], "msg", args.msg


def _not_found(args: argparse.Namespace, label: str, value: str) -> int:
    """Say where to look next, rather than only that nothing was found.

    Section 8.3's rule applied to the command line: most misses are a window
    that starts too late, and saying so saves the same wasted hour.
    """
    window = (
        "this window"
        if (args.from_ts or args.to_ts or args.date or args.last)
        else "the index"
    )
    print(
        f"pm-audit-replay: no {label} matching {value!r} in {window}"
        + (" (try a wider --from/--to)" if window != "the index" else ""),
        file=sys.stderr,
    )
    return 1


def _run_stats(args: argparse.Namespace) -> int:
    log_files = _log_files(args)
    if not log_files:
        print(f"pm-audit-replay: no audit log at {args.log_file}", file=sys.stderr)
        return 1
    episodes, _state = _stream_from_log(args, log_files)
    stats = stats_report.collect_episodes(episodes)
    print(stats_report.render(stats, _palette(args)), end="")
    return 0 if stats.facts else 1


def detail_level(args: argparse.Namespace) -> int:
    """Collapse ``-q`` and repeated ``-v`` onto the one axis of section 8.1."""
    if args.quiet:
        return _MIN_DETAIL
    return min(1 + int(args.verbose), _MAX_DETAIL)


def validate_args(args: argparse.Namespace) -> str | None:
    """Return an error message for a combination argparse cannot reject."""
    if args.date and is_explicit_file(Path(args.log_file)):
        return "--date cannot be combined with an archive --log-file"
    if args.date and (args.from_ts or args.to_ts):
        return "--date cannot be combined with --from/--to"
    if args.last is not None and (args.from_ts or args.to_ts or args.date):
        return "--last cannot be combined with --from/--to/--date"
    if (
        args.from_ts
        and args.to_ts
        and parse_ts(args.from_ts) > parse_ts(args.to_ts, end_of_day=True)
    ):
        return "--from must not be later than --to"
    if args.quiet and args.verbose:
        return "-q cannot be combined with -v"
    if args.no_color and args.force_color:
        return "--no-color cannot be combined with --force-color"
    # --date is not a window but the day's files, which story reads too.
    if args.command == "index" and (
        args.from_ts or args.to_ts or args.last is not None
    ):
        return (
            "the index always covers the whole log, so it takes no window; "
            "narrow the query instead"
        )
    if args.command in _RERUN_COMMANDS:
        error = _rerun_error(args)
        if error:
            return error
    if args.rebuild and args.command not in _INDEX_COMMANDS:
        return (
            f"{args.command} reads the log and never the index, so it takes "
            "no --rebuild (story and index do)"
        )
    allowed = _FORMAT_COMMANDS.get(args.format)
    if allowed is not None and args.command not in allowed:
        return f"--format {args.format} is only available for " + ", ".join(
            f"`{name}`" for name in allowed
        )
    return None


#: The commands that build and read the episode index; the reports read
#: their window off the log (``_stream_from_log``).
_INDEX_COMMANDS = ("story", "index")

#: The commands that re-run the whole trail of the ``--log-file``'s directory.
_RERUN_COMMANDS = ("rerun", "queue")


def _rerun_error(args: argparse.Namespace) -> str | None:
    """What ``rerun`` and ``queue`` would silently ignore, refused.

    Both feed the whole trail of the data directory to a fresh engine: there
    is no window to narrow and no index to read, so a ``--date 1999-01-01``
    that re-ran today's trail at exit 0 told the caller something untrue.
    ``queue`` takes ``--symbol`` (the level view); its times are UTC.
    """
    if is_explicit_file(Path(args.log_file)):
        return (
            f"{args.command} re-runs the whole trail of a data directory; "
            "--log-file must name its audit.log, not an archive or a day part"
        )
    given = {
        "--date": args.date,
        "--from": args.from_ts,
        "--to": args.to_ts,
        "--last": args.last is not None,
        "--gateway": args.gateway,
        "--kind": args.kind,
        "--db": args.db != str(AUDIT_REPLAY_DB_FILE),
        "--strict": args.strict,
        "--clock-skew-warn": args.clock_skew_warn != DEFAULT_CLOCK_SKEW_WARN,
        "--reorder-window": args.reorder_window is not None,
        "--symbol": args.symbol and args.command == "rerun",
        "--tz": str(args.tz) != "UTC" and args.command == "queue",
    }
    ignored = [flag for flag, value in given.items() if value]
    if ignored:
        return f"{args.command} re-runs the whole trail and takes no " + ", ".join(
            ignored
        )
    return None


def _run_rerun(args: argparse.Namespace) -> int:
    from edumatcher.audit.rawlines import Unavailable
    from edumatcher.audit.replay.rerun import rerun

    try:
        result = rerun(Path(args.log_file).expanduser().parent)
    except Unavailable as exc:
        print(f"pm-audit-replay: cannot re-run: {exc}", file=sys.stderr)
        return 3
    total = sum(result.commands.values())
    top = ", ".join(f"{t} {n}" for t, n in result.commands.most_common(6))
    print(f"re-ran {total} commands ({top}, ...)")
    print(f"hidden inputs: {result.counts['E1']}")
    print(f"outputs: {result.counts['E2']} differing episodes; {result.note()}")
    if result.book_checked:
        print(f"final book: {result.counts['E4']} differences")
    else:
        print(f"final book: not checked ({result.book_unchecked})")
    for label, key in (
        ("hidden input", "E1"),
        ("difference", "E2"),
        ("book", "E4"),
    ):
        for sample in result.samples[key][:5]:
            print(f"  {label}: {sample}")
    return 1 if any(result.counts[k] for k in ("E1", "E2", "E4")) else 0


def _run_queue(args: argparse.Namespace) -> int:
    from edumatcher.audit.rawlines import Unavailable
    from edumatcher.audit.replay.queue import LevelQueue, OrderQueue, order_ids
    from edumatcher.audit.replay.rerun import Rerun

    symbols = args.symbol or []
    level = args.price is not None or bool(symbols)
    if (args.order is None) == (not level):
        print(
            "pm-audit-replay: queue needs --order ID, or --symbol SYM and "
            "--price P (not both)",
            file=sys.stderr,
        )
        return 2
    view: OrderQueue | LevelQueue
    data_dir = Path(args.log_file).expanduser().parent
    if args.order is not None:
        try:
            matches = order_ids(data_dir, args.order)
        except Unavailable as exc:
            print(f"pm-audit-replay: cannot re-run: {exc}", file=sys.stderr)
            return 3
        if not matches:
            print(f"order {args.order} is not in the trail")
            return 1
        if len(matches) > 1:
            shown = ", ".join(matches[:5]) + (", ..." if len(matches) > 5 else "")
            print(
                f"pm-audit-replay: --order {args.order!r} matches "
                f"{len(matches)} orders ({shown}); give more of the id",
                file=sys.stderr,
            )
            return 2
        view = OrderQueue(matches[0], anonymise=args.anonymise)
    elif args.price is None or len(symbols) != 1:
        print(
            "pm-audit-replay: a level view needs one --symbol and a --price",
            file=sys.stderr,
        )
        return 2
    else:
        view = LevelQueue(
            symbols[0], args.price, side=args.side, anonymise=args.anonymise
        )
    run = Rerun(data_dir)
    run.observers.append(view)
    try:
        run.run()
    except Unavailable as exc:
        print(f"pm-audit-replay: cannot re-run: {exc}", file=sys.stderr)
        return 3
    print(view.render(), end="")
    return 1 if isinstance(view, OrderQueue) and view.rid is None else 0


@pipe_safe
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
    try:
        return _dispatch(args)
    except episode_index.NotAnIndexError as exc:
        print(f"pm-audit-replay: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "stream":
        return _run_stream(args)
    if args.command == "story":
        return _run_story(args)
    if args.command == "digest":
        return _run_digest(args)
    if args.command == "episodes":
        return _run_episodes(args)
    if args.command == "anomalies":
        return _run_anomalies(args)
    if args.command == "index":
        return _run_index(args)
    if args.command == "stats":
        return _run_stats(args)
    if args.command == "rerun":
        return _run_rerun(args)
    if args.command == "queue":
        return _run_queue(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
