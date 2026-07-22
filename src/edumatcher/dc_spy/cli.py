"""CLI entry point for ``pm-dc-spy``.

A drop-copy feed "spy": connects to the matching engine's drop-copy ``PUB``
socket (``edumatcher.engine.drop_copy.DropCopyPublisher``, default
``tcp://127.0.0.1:5557``), subscribes to fill events for one gateway or all
gateways, and prints every message it receives -- either as a colourised,
human-readable log line or as a JSON line for scripting.

The point of the tool is purely observational: it never publishes anything
back onto the bus, and it is safe to run any number of instances (in
separate terminals, with different ``--gateway`` filters each) at once,
since ZeroMQ PUB/SUB fans out independently to every connected subscriber.

Unlike ``pm-calf-spy``/``pm-ralf-spy``, the drop-copy feed has no
HELLO/WELCOME handshake and no heartbeat protocol -- it is a plain ZMQ
PUB/SUB stream filtered by topic prefix, so there is nothing to keep alive
and no session banner to print before the first message arrives.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from rich.console import Console

from edumatcher.dc_spy.client import DcSpyClient, DcSpyConnectionError, DcSpyOptions
from edumatcher.dc_spy.formatters import format_human, format_json

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-dc-spy",
        description=(
            "Spy on the engine's drop-copy feed: connect to the drop-copy "
            "PUB socket and print every fill event it sends, human-readable "
            "or as JSON."
        ),
        epilog=(
            "Examples:\n"
            "  pm-dc-spy\n"
            "  pm-dc-spy --gateway TRADER01\n"
            "  pm-dc-spy --gateway TRADER01 --format json\n"
            "  pm-dc-spy --gateway TRADER01 --replay-of MY_RISK_SYS\n"
            "  pm-dc-spy --format json --count 50 > fills.jsonl\n"
            "\n"
            "Run several instances at once (e.g. one per terminal) to watch "
            "different gateways side by side -- the drop-copy PUB socket "
            "fans out independently to any number of subscribers."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-dc-spy")

    conn = parser.add_argument_group("connection")
    conn.add_argument(
        "--host",
        default="127.0.0.1",
        help="Drop-copy PUB socket host (default: 127.0.0.1)",
    )
    conn.add_argument(
        "--port",
        type=int,
        default=5557,
        help="Drop-copy PUB socket port (default: 5557)",
    )

    sub = parser.add_argument_group("subscription filtering")
    sub.add_argument(
        "--gateway",
        default=None,
        metavar="GW_ID",
        help="Only show fills for this gateway (subscribes to the "
        "drop_copy.event.<GW_ID> topic). Default: all gateways "
        "(drop_copy.event. prefix). Note the drop-copy socket performs no "
        "entitlement checks -- any gateway's fills can be requested.",
    )
    sub.add_argument(
        "--replay-of",
        default=None,
        metavar="RECIPIENT_ID",
        help="Also subscribe to drop_copy.replay.<RECIPIENT_ID>, the topic "
        "DropCopyPublisher.replay() publishes on when a recipient's replay "
        "is requested programmatically. Replay lines are tagged REPLAY "
        "instead of FILL. Useful for observing replay() calls made by "
        "tests or embedded consumers; there is no wire protocol to trigger "
        "a replay from pm-dc-spy itself (see docs/user-guide/200-drop-copy.md).",
    )

    out = parser.add_argument_group("output")
    out.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    out.add_argument(
        "--raw",
        action="store_true",
        help="Also echo the raw topic + JSON payload under each formatted "
        "line (human format only; ignored in json format, where the "
        "record already carries every field verbatim)",
    )
    out.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour even when stdout is a terminal",
    )
    out.add_argument(
        "--count",
        type=int,
        default=0,
        metavar="N",
        help="Exit after N messages (0 = run until Ctrl-C, default).",
    )

    diag = parser.add_argument_group("diagnostics")
    diag.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level override (default: WARNING)",
    )
    diag.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v: INFO, -vv: DEBUG)",
    )
    diag.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce log output to warnings/errors",
    )
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    log_level = getattr(args, "log_level", None)
    verbose = getattr(args, "verbose", 0)
    quiet = getattr(args, "quiet", False)

    if log_level:
        level = getattr(logging, str(log_level).upper(), logging.WARNING)
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    return int(level)


class _SpySession:
    """Wires a DcSpyClient to a Console/stdout renderer for one run."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        color = not args.no_color and sys.stdout.isatty()
        self.console = Console(
            highlight=False, no_color=not color, force_terminal=color
        )
        self.count = 0

    def on_message(self, topic: str, payload: dict[str, Any], recv_time: float) -> None:
        if self.args.format == "json":
            print(format_json(topic, payload, recv_ts=recv_time), flush=True)
        else:
            self.console.print(format_human(topic, payload, raw=self.args.raw))
        self.count += 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _configure_logging(args)

    gateway = args.gateway.strip().upper() if args.gateway else None
    replay_of = args.replay_of.strip() if args.replay_of else None

    options = DcSpyOptions(
        host=args.host,
        port=args.port,
        gateway=gateway,
        replay_of=replay_of,
    )
    client = DcSpyClient(options)
    session = _SpySession(args)

    try:
        client.connect()
    except DcSpyConnectionError as exc:
        session.console.print(f"[bold red]pm-dc-spy: {exc}[/bold red]")
        raise SystemExit(1) from exc

    target = (
        f"drop_copy.event.{gateway}" if gateway else "drop_copy.event.* (all gateways)"
    )
    session.console.print(
        f"[bold cyan]◆ pm-dc-spy[/bold cyan] connected to "
        f"{args.host}:{args.port}, subscribed to [bold]{target}[/bold]"
        f"{f' + drop_copy.replay.{replay_of}' if replay_of else ''} "
        f"(Ctrl-C to stop)"
    )

    try:
        client.run(session.on_message, max_messages=args.count)
    except DcSpyConnectionError as exc:
        session.console.print(f"[bold red]pm-dc-spy: {exc}[/bold red]")
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
        session.console.print("[dim]pm-dc-spy: connection closed.[/dim]")


__all__ = ["main"]


if __name__ == "__main__":
    main()
