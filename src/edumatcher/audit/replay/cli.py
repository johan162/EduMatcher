"""pm-audit-replay — CLI entry point.

Usage::

    pm-audit-replay [global-options] COMMAND [command-options]

The global options are the ones design section 9.1 specifies, and they
deliberately mirror ``pm-audit-cli``'s time-window and filter flags so muscle
memory carries between the two tools.

Two subcommands so far. ``stats`` (task AR-2.5) is the confidence distribution
over a window; it is registered ahead of ``stream``, ``story`` and ``digest``
because it reports on the *trail* rather than narrating it, so it is useful the
moment pass 1 works -- and because the distribution is what says whether
narration can be trusted at all. ``index`` (section 9.7) materialises the
episode model into SQLite.

A subcommand is optional: with none, the command validates its options and
exits, as it did through phase 1.

**The index policy lives in :func:`ensure_index`**, one function rather than a
rule each renderer reimplements. ``--no-index`` opts out entirely; ``--rebuild``
forces; otherwise the index is built when it is absent, when it was built under
different rules, or when the logs have changed since -- and read as it stands
when none of those hold. There is no incremental build (AR-3.4 records why), so
"the logs have changed" means a full rebuild; at the measured build rate that
is seconds for a session and minutes for a day.
"""

from __future__ import annotations

import argparse
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from edumatcher.audit.query import (
    date_to_range,
    discover_log_files,
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
            "Rotated .1, .2.gz ... siblings are discovered automatically."
        ),
    )
    source.add_argument(
        "--db",
        metavar="PATH",
        default=default(str(AUDIT_REPLAY_DB_FILE)),
        help=f"Episode index (default: {AUDIT_REPLAY_DB_FILE})",
    )
    source.add_argument(
        "--no-index",
        action="store_true",
        default=default(False),
        help="Stream without building or reading an index",
    )
    source.add_argument(
        "--rebuild",
        action="store_true",
        default=default(False),
        help="Rebuild the episode index before rendering",
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
        help="Shorthand for a whole UTC day",
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
        default=default("UTC"),
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
        help="Disable ANSI colour",
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
        type=float,
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
    """Register the subcommands.

    ``required=False`` on purpose: every option above is global, and
    ``pm-audit-replay --help`` has to keep working as the review surface for
    the option set while the renderers are still being built.
    """
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
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
        type=int,
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
    return discover_log_files(Path(args.log_file))


def detection_key(args: argparse.Namespace) -> str:
    """The detection settings, canonically, for the index to record.

    Compared as a string rather than field by field so that adding an option
    is one edit here and nothing anywhere else.
    """
    return f"strict={int(args.strict)} clock_skew={args.clock_skew_warn:g}"


def _detector(state: StateModel, args: argparse.Namespace) -> Detector:
    return Detector(state, strict=args.strict, clock_skew_warn=args.clock_skew_warn)


def build_index(
    args: argparse.Namespace, log_files: list[Path], *, rebuild: bool
) -> int:
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

    So the window is a property of the *query* only. `reader` applies it in
    SQL, `_from_log` applies it to the read, and both narrow the same
    complete model. `--no-index` remains the way to avoid paying for a full
    build on a one-off log.
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
        rebuild=rebuild,
        detection=detection_key(args),
    )


def ensure_index(
    args: argparse.Namespace, log_files: list[Path]
) -> sqlite3.Connection | None:
    """A readonly connection to a current index, built first if it is not.

    None when ``--no-index``: the caller streams instead. Everything else is
    one decision made in one place, so ``stream`` and ``story`` cannot come to
    differ about when a rebuild is due.
    """
    if args.no_index:
        return None
    db = Path(args.db)
    if not args.rebuild:
        try:
            conn = episode_index.open_readonly(db)
        except (FileNotFoundError, episode_index.StaleIndexError):
            conn = None
        if conn is not None:
            if episode_index.is_current(conn, log_files) and (
                episode_index.read_meta(conn, episode_index.META_DETECTION)
                == detection_key(args)
            ):
                return conn
            # Stale content rather than stale rules: close the handle before
            # rebuilding, or it outlives the database it was opened on.
            conn.close()
    build_index(args, log_files, rebuild=True)
    return episode_index.open_readonly(db)


def _run_index(args: argparse.Namespace) -> int:
    log_files = _log_files(args)
    if not log_files:
        print(f"pm-audit-replay: no audit log at {args.log_file}", file=sys.stderr)
        return 1
    if args.no_index:
        print("pm-audit-replay: --no-index leaves nothing for index to do")
        return 2
    conn = ensure_index(args, log_files)
    assert conn is not None  # --no-index is refused above
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
    )


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


def _from_log(
    args: argparse.Namespace, log_files: list[Path]
) -> tuple[list[Episode], StateModel]:
    """Reconstruct without the index -- what ``--no-index`` asks for."""
    from_dt, to_dt = window_bounds(args)
    max_facts, max_seconds = reorder_bounds(args)
    run, steps = reconstruct(
        iter_entries(log_files, from_dt=from_dt, to_dt=to_dt),
        max_facts=max_facts,
        max_seconds=max_seconds,
    )
    detector = _detector(run.state, args)
    episodes = list(
        detected(
            assemble(
                observed(steps, detector),
                run.state,
                run.links,
                max_facts=max_facts,
                max_seconds=max_seconds,
            ),
            detector,
        )
    )
    return episodes, run.state


def _run_stream(args: argparse.Namespace) -> int:
    log_files = _log_files(args)
    if not log_files:
        print(f"pm-audit-replay: no audit log at {args.log_file}", file=sys.stderr)
        return 1
    conn = ensure_index(args, log_files)
    if conn is None:
        episodes, state = _from_log(args, log_files)
        return _narrate(_filtered(episodes, args), state, args)
    try:
        from_dt, to_dt = window_bounds(args)
        episodes = reader.episodes_in_window(
            conn,
            from_ts=from_dt.isoformat() if from_dt else None,
            to_ts=to_dt.isoformat() if to_dt else None,
            symbols=args.symbol,
            gateways=args.gateway,
            kinds=args.kind,
        )
        return _narrate(episodes, reader.actors(conn), args)
    finally:
        conn.close()


def _filtered(episodes: Sequence[Episode], args: argparse.Namespace) -> list[Episode]:
    """The ``--symbol``/``--gateway``/``--kind`` filters, off the index.

    The same predicates the index applies in SQL, so ``--no-index`` answers
    the same question rather than a broader one.
    """
    return [
        episode
        for episode in episodes
        if (not args.symbol or episode.symbol in args.symbol)
        and (not args.gateway or episode.actor in args.gateway)
        and (not args.kind or episode.kind in args.kind)
    ]


def _selected(
    args: argparse.Namespace,
    conn: sqlite3.Connection | None,
    log_files: list[Path],
) -> list[Episode]:
    """The window's episodes, however the caller is allowed to get them.

    The index applies the filters in SQL and the log path applies the same
    predicates in Python, so ``--no-index`` answers the same question rather
    than a broader one.
    """
    if conn is None:
        episodes, _state = _from_log(args, log_files)
        return _filtered(episodes, args)
    from_dt, to_dt = window_bounds(args)
    return reader.episodes_in_window(
        conn,
        from_ts=from_dt.isoformat() if from_dt else None,
        to_ts=to_dt.isoformat() if to_dt else None,
        symbols=args.symbol,
        gateways=args.gateway,
        kinds=args.kind,
    )


def _run_view(
    args: argparse.Namespace, render: Callable[[Sequence[Episode]], str]
) -> int:
    """Load the window and print one of section 9.4-9.6's reports."""
    log_files = _log_files(args)
    if not log_files:
        print(f"pm-audit-replay: no audit log at {args.log_file}", file=sys.stderr)
        return 1
    conn = ensure_index(args, log_files)
    try:
        print(render(_selected(args, conn, log_files)), end="")
        return 0
    finally:
        if conn is not None:
            conn.close()


def _run_digest(args: argparse.Namespace) -> int:
    return _run_view(
        args,
        lambda episodes: views.render_digest(
            episodes,
            significance=args.significance,
            top=args.top,
            id_len=args.id_len,
        ),
    )


def _run_episodes(args: argparse.Namespace) -> int:
    return _run_view(
        args,
        lambda episodes: views.render_episodes(
            [
                episode
                for episode in episodes
                if not args.outcome or episode.outcome in args.outcome
            ],
            as_csv=args.format == "csv",
            id_len=args.id_len,
        ),
    )


def _run_anomalies(args: argparse.Namespace) -> int:
    def render(episodes: Sequence[Episode]) -> str:
        found = render_json.anomalies(episodes, severity=args.severity)
        if args.format == "ndjson":
            return "".join(f"{render_json.dumps(obj)}\n" for obj in found)
        if args.format == "json":
            return render_json.dumps(list(found)) + "\n"
        return views.render_anomalies(
            episodes, severity=args.severity, id_len=args.id_len
        )

    return _run_view(args, render)


def _run_story(args: argparse.Namespace) -> int:
    log_files = _log_files(args)
    if not log_files:
        print(f"pm-audit-replay: no audit log at {args.log_file}", file=sys.stderr)
        return 1
    if args.no_index:
        print(
            "pm-audit-replay: story needs the index; drop --no-index",
            file=sys.stderr,
        )
        return 2
    conn = ensure_index(args, log_files)
    assert conn is not None  # --no-index is refused above
    try:
        if args.chain:
            episodes = reader.episodes_in_chain(conn, args.chain)
            if not episodes:
                return _not_found(args, "chain", args.chain)
            return _narrate(episodes, reader.actors(conn), args)
        seed, label, value = _seed(conn, args)
        if seed is None:
            return _not_found(args, label, value)
        episodes = reader.walk(
            conn, seed, depth=args.depth, recorded_only=args.strict_causality
        )
        return _narrate(episodes, reader.actors(conn), args)
    finally:
        conn.close()


def _seed(
    conn: sqlite3.Connection, args: argparse.Namespace
) -> tuple[Episode | None, str, str]:
    for dest, kind in _SELECTOR_KINDS.items():
        value = getattr(args, dest, None)
        if value:
            return reader.episode_by_anchor(conn, kind, value), kind, value
    if args.client_tag:
        return (
            reader.episode_by_client_tag(conn, args.client_tag),
            "tag",
            args.client_tag,
        )
    return reader.episode_containing(conn, args.msg), "msg", args.msg


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
    if args.command == "index" and (
        args.from_ts or args.to_ts or args.date or args.last is not None
    ):
        return (
            "the index always covers the whole log, so it takes no window; "
            "narrow the query instead"
        )
    allowed = _FORMAT_COMMANDS.get(args.format)
    if allowed is not None and args.command not in allowed:
        return f"--format {args.format} is only available for " + ", ".join(
            f"`{name}`" for name in allowed
        )
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
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
