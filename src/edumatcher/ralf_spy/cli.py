"""CLI entry point for ``pm-ralf-spy``.

A RALF post-trade protocol "spy": connects to a running ``pm-ralf-gwy`` over
TCP, subscribes under a chosen role to whatever channels/symbols you ask
for, and prints every line it receives -- either as a colourised,
human-readable log line or as a JSON line for scripting.

The point of the tool is purely observational: it never places orders or
otherwise mutates exchange state, and it is safe to run any number of
instances (in separate terminals, with different roles/filters each) against
the same gateway at once.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from rich.console import Console

from edumatcher.ralf_gateway.protocol import RalfFrame
from edumatcher.ralf_spy.client import (
    RalfSpyClient,
    RalfSpyConnectionError,
    RalfSpyOptions,
)
from edumatcher.ralf_spy.formatters import format_human, format_json

log = logging.getLogger(__name__)

# Mirrors ralf_gateway.gateway._ALLOWED_CHANNELS -- also doubles as the set
# of valid --role values, since RALF's roles and channels share one
# namespace (see docs/user-guide/930-app-ralf-protocol.md).
_ALLOWED_CHANNELS = ("CLEARING", "DROP_COPY", "AUDIT")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-ralf-spy",
        description=(
            "Spy on the RALF post-trade protocol: connect to pm-ralf-gwy and "
            "print every line it sends, human-readable or as JSON."
        ),
        epilog=(
            "Examples:\n"
            "  pm-ralf-spy --role AUDIT --symbols AAPL\n"
            "  pm-ralf-spy --role CLEARING --format json\n"
            "  pm-ralf-spy --role DROP_COPY --symbols AAPL,MSFT --count 5\n"
            "  pm-ralf-spy --role AUDIT --lastseq 1042\n"
            "\n"
            "Run several instances at once (e.g. one per terminal) to watch "
            "different roles/channels side by side -- pm-ralf-gwy accepts "
            "any number of concurrent client connections."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-ralf-spy")

    conn = parser.add_argument_group("connection")
    conn.add_argument(
        "--host", default="127.0.0.1", help="pm-ralf-gwy TCP host (default: 127.0.0.1)"
    )
    conn.add_argument(
        "--port", type=int, default=5580, help="pm-ralf-gwy TCP port (default: 5580)"
    )
    conn.add_argument(
        "--client-name",
        default=None,
        metavar="NAME",
        help="HELLO|CLIENT= identifier reported in gateway logs "
        "(default: ralf-spy-<pid>)",
    )

    sub = parser.add_argument_group("subscription filtering")
    sub.add_argument(
        "--role",
        choices=_ALLOWED_CHANNELS,
        default="AUDIT",
        help="HELLO|ROLE= to authenticate as (default: AUDIT). AUDIT is "
        "entitled to every channel; CLEARING/DROP_COPY are entitled only "
        "to their own same-named channel.",
    )
    sub.add_argument(
        "--channels",
        default="*",
        metavar="CH[,CH...]",
        help="Comma-separated channels to subscribe to, e.g. "
        "CLEARING,DROP_COPY. '*' (default) subscribes to every channel "
        "--role is entitled to (all three for AUDIT; just its own name "
        "for CLEARING/DROP_COPY).",
    )
    sub.add_argument(
        "--symbols",
        default="*",
        metavar="SYM[,SYM...]",
        help="Comma-separated symbols to subscribe to, e.g. AAPL,MSFT. "
        "'*' (default) subscribes to every symbol -- RALF has no "
        "per-channel wildcard restriction the way CALF does.",
    )
    sub.add_argument(
        "--lastseq",
        type=int,
        default=0,
        metavar="N",
        help="Request replay on connect via HELLO|LASTSEQ=N for every "
        "channel --role is entitled to (0 = no replay, default). Unlike "
        "CALF's RESUME=1, RALF replay is requested directly on HELLO and "
        "is not scoped to a single channel/symbol.",
    )
    sub.add_argument(
        "--ping-interval",
        type=float,
        default=60.0,
        metavar="SECONDS",
        help="Send PING to the gateway every SECONDS seconds to avoid its "
        "idle timeout (default: 60). The gateway replies PONG (hidden by "
        "default, see --show-heartbeats). Set to 0 to disable.",
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
        help="Also echo the raw wire line under each formatted line (human "
        "format only; ignored in json format, where the parsed record "
        "already carries every field verbatim)",
    )
    out.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour even when stdout is a terminal",
    )
    out.add_argument(
        "--show-heartbeats",
        action="store_true",
        help="Also print HB heartbeat lines and PONG keep-alive replies "
        "(suppressed by default to reduce noise; they still keep the "
        "connection alive either way)",
    )
    out.add_argument(
        "--count",
        type=int,
        default=0,
        metavar="N",
        help="Exit after N data-carrying lines (0 = run until Ctrl-C, "
        "default). Heartbeats do not count towards N.",
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


def _parse_csv_upper(raw: str) -> list[str]:
    return [token.strip().upper() for token in raw.split(",") if token.strip()]


def _entitled_channels(role: str) -> list[str]:
    """Channels a given role may subscribe to (mirrors the gateway's own
    entitlement rule: AUDIT gets everything, everyone else gets only their
    own same-named channel)."""
    if role == "AUDIT":
        return list(_ALLOWED_CHANNELS)
    return [role]


def _resolve_channels(role: str, requested: str) -> list[str]:
    """Turn --channels ('*' or an explicit CSV list) into a concrete list.

    '*' means "everything --role is entitled to". An explicit list is used
    as-is; the gateway itself will reject (ERR|CODE=ENTITLEMENT_DENIED) any
    channel the role isn't actually allowed to subscribe to, so no
    client-side validation is needed beyond resolving the wildcard.
    """
    if requested.strip() != "*":
        return _parse_csv_upper(requested)
    return _entitled_channels(role)


class _SpySession:
    """Wires a RalfSpyClient to a Console/stdout renderer for one run."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        color = not args.no_color and sys.stdout.isatty()
        self.console = Console(
            highlight=False, no_color=not color, force_terminal=color
        )
        self.count = 0

    def on_frame(self, frame: RalfFrame, raw_line: str, recv_time: float) -> None:
        if frame.msg_type in ("HB", "PONG") and not self.args.show_heartbeats:
            return

        if self.args.format == "json":
            print(format_json(frame, recv_ts=recv_time), flush=True)
        else:
            raw = raw_line if self.args.raw else None
            self.console.print(format_human(frame, raw_line=raw))

        self.count += 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _configure_logging(args)

    if args.ping_interval < 0:
        parser.error("--ping-interval must be >= 0")
        return  # unreachable, parser.error() raises SystemExit

    client_name = args.client_name or f"ralf-spy-{os.getpid()}"
    requested_symbols = _parse_csv_upper(args.symbols) or ["*"]

    options = RalfSpyOptions(
        host=args.host,
        port=args.port,
        client_name=client_name,
        role=args.role,
        symbols=requested_symbols,
        last_seq=args.lastseq,
        ping_interval_sec=args.ping_interval,
    )
    client = RalfSpyClient(options)
    session = _SpySession(args)

    try:
        client.connect()
        welcome = client.handshake()
    except RalfSpyConnectionError as exc:
        session.console.print(f"[bold red]pm-ralf-spy: {exc}[/bold red]")
        raise SystemExit(1) from exc

    session.console.print(
        f"[bold cyan]◆ pm-ralf-spy[/bold cyan] connected to "
        f"{args.host}:{args.port} as [bold]{client_name}[/bold] "
        f"role=[bold]{args.role}[/bold] (Ctrl-C to stop)"
    )
    session.on_frame(welcome, "", time.time())

    channels = _resolve_channels(args.role, args.channels)
    if not channels:
        session.console.print(
            "[bold red]pm-ralf-spy: no channels to subscribe to "
            "(--channels resolved empty)[/bold red]"
        )
        client.close()
        raise SystemExit(1)

    log.info("subscribing channels=%s symbols=%s", channels, requested_symbols)
    client.subscribe(channels, requested_symbols)

    try:
        client.run(session.on_frame, max_frames=args.count)
    except RalfSpyConnectionError as exc:
        session.console.print(f"[bold red]pm-ralf-spy: {exc}[/bold red]")
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
        session.console.print("[dim]pm-ralf-spy: connection closed.[/dim]")


__all__ = ["main"]


if __name__ == "__main__":
    main()
