"""CLI entry point for ``pm-calf-spy``.

A CALF market-data protocol "spy": connects to a running ``pm-md-gwy`` over
TCP, subscribes to whatever channels/symbols you ask for, and prints every
line it receives -- either as a colourised, human-readable log line or as a
JSON line for scripting.

The point of the tool is purely observational: it never places orders or
otherwise mutates exchange state, and it is safe to run any number of
instances (in separate terminals, with different ``--channels``/``--symbols``
filters each) against the same gateway at once, since ``pm-md-gwy`` supports
an arbitrary number of concurrent client connections.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from rich.console import Console

from edumatcher.calf_spy.client import (
    CalfSpyClient,
    CalfSpyConnectionError,
    CalfSpyOptions,
    ResumeRequest,
)
from edumatcher.calf_spy.formatters import format_human, format_json
from edumatcher.md_gateway.protocol import CalfFrame

log = logging.getLogger(__name__)

# Channels guaranteed to exist even against a gateway build that predates
# WELCOME|CH_SUPPORTED= (see md_gateway.gateway._ALLOWED_CHANNELS history and
# docs/user-guide/920-app-calf-protocol.md). Used as the --channels default
# fallback only when the gateway's own WELCOME omits CH_SUPPORTED.
_BASELINE_CHANNELS = ("TOP", "TRADE", "STATE")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-calf-spy",
        description=(
            "Spy on the CALF market-data protocol: connect to pm-md-gwy and "
            "print every line it sends, human-readable or as JSON."
        ),
        epilog=(
            "Examples:\n"
            "  pm-calf-spy --channels TOP,TRADE --symbols AAPL\n"
            "  pm-calf-spy --channels CB,STATE --symbols AAPL --format json\n"
            "  pm-calf-spy --channels AUCTION --symbols '*'\n"
            "  pm-calf-spy --channels DEPTH --symbols AAPL --count 5\n"
            "\n"
            "Run several instances at once (e.g. one per terminal) to watch "
            "different channels side by side -- pm-md-gwy accepts any number "
            "of concurrent client connections."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-calf-spy")

    conn = parser.add_argument_group("connection")
    conn.add_argument(
        "--host", default="127.0.0.1", help="pm-md-gwy TCP host (default: 127.0.0.1)"
    )
    conn.add_argument(
        "--port", type=int, default=5570, help="pm-md-gwy TCP port (default: 5570)"
    )
    conn.add_argument(
        "--client-name",
        default=None,
        metavar="NAME",
        help="HELLO|CLIENT= identifier reported in gateway logs "
        "(default: calf-spy-<pid>)",
    )

    sub = parser.add_argument_group("subscription filtering")
    sub.add_argument(
        "--channels",
        default="*",
        metavar="CH[,CH...]",
        help="Comma-separated channels to subscribe to, e.g. TOP,TRADE,CB. "
        "'*' (default) subscribes to every channel the gateway advertises "
        "via WELCOME|CH_SUPPORTED= (falling back to TOP,TRADE,STATE if that "
        "field is absent).",
    )
    sub.add_argument(
        "--symbols",
        default="*",
        metavar="SYM[,SYM...]",
        help="Comma-separated symbols to subscribe to, e.g. AAPL,MSFT. "
        "'*' (default) requests the wildcard for every channel that allows "
        "it (TOP, TRADE, STATE, AUCTION); channels that reject SYM=* "
        "(INDEX, DEPTH, CB) will report an ERR|CODE=INVALID_SYMBOL for that "
        "channel alone rather than aborting the whole session -- pass "
        "explicit symbols to subscribe to those too.",
    )
    sub.add_argument(
        "--resume",
        metavar="CH:SYM:LASTSEQ",
        help="Request single-stream replay on connect, e.g. TOP:AAPL:1042 "
        "(mirrors HELLO|RESUME=1|CH=..|SYM=..|LASTSEQ=..). Only one stream "
        "may be resumed per connection; live subscriptions from --channels/"
        "--symbols are still applied afterwards.",
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


def _parse_resume(raw: str | None) -> ResumeRequest | None:
    if raw is None:
        return None
    parts = raw.split(":")
    if len(parts) != 3:
        raise ValueError(f"--resume must be CH:SYM:LASTSEQ, got {raw!r}")
    ch, sym, last_seq_raw = parts
    try:
        last_seq = int(last_seq_raw)
    except ValueError as exc:
        raise ValueError(
            f"--resume LASTSEQ must be an integer, got {last_seq_raw!r}"
        ) from exc
    return ResumeRequest(
        channel=ch.strip().upper(), symbol=sym.strip().upper(), last_seq=last_seq
    )


def _resolve_channels(welcome: CalfFrame, requested: str) -> list[str]:
    """Turn --channels ('*' or an explicit CSV list) into a concrete list.

    '*' means "everything this gateway build supports" -- read from
    WELCOME|CH_SUPPORTED= when present, else fall back to the channels
    guaranteed on every CALF build (see _BASELINE_CHANNELS).
    """
    if requested.strip() != "*":
        return _parse_csv_upper(requested)
    raw_supported = welcome.fields.get("CH_SUPPORTED")
    if raw_supported:
        return sorted(_parse_csv_upper(raw_supported))
    return list(_BASELINE_CHANNELS)


class _SpySession:
    """Wires a CalfSpyClient to a Console/stdout renderer for one run."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        color = not args.no_color and sys.stdout.isatty()
        self.console = Console(
            highlight=False, no_color=not color, force_terminal=color
        )
        self.count = 0

    def on_frame(self, frame: CalfFrame, raw_line: str, recv_time: float) -> None:
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

    try:
        resume = _parse_resume(args.resume)
    except ValueError as exc:
        parser.error(str(exc))
        return  # unreachable, parser.error() raises SystemExit

    if args.ping_interval < 0:
        parser.error("--ping-interval must be >= 0")
        return  # unreachable, parser.error() raises SystemExit

    client_name = args.client_name or f"calf-spy-{os.getpid()}"
    requested_symbols = _parse_csv_upper(args.symbols) or ["*"]

    options = CalfSpyOptions(
        host=args.host,
        port=args.port,
        client_name=client_name,
        symbols=requested_symbols,
        resume=resume,
        ping_interval_sec=args.ping_interval,
    )
    client = CalfSpyClient(options)
    session = _SpySession(args)

    try:
        client.connect()
        welcome = client.handshake()
    except CalfSpyConnectionError as exc:
        session.console.print(f"[bold red]pm-calf-spy: {exc}[/bold red]")
        raise SystemExit(1) from exc

    session.console.print(
        f"[bold cyan]◆ pm-calf-spy[/bold cyan] connected to "
        f"{args.host}:{args.port} as [bold]{client_name}[/bold] "
        f"(Ctrl-C to stop)"
    )
    session.on_frame(welcome, "", time.time())

    channels = _resolve_channels(welcome, args.channels)
    if not channels:
        session.console.print(
            "[bold red]pm-calf-spy: no channels to subscribe to "
            "(gateway advertised none and --channels resolved empty)[/bold red]"
        )
        client.close()
        raise SystemExit(1)

    log.info("subscribing channels=%s symbols=%s", channels, requested_symbols)
    client.subscribe(channels, requested_symbols)

    try:
        client.run(session.on_frame, max_frames=args.count)
    except CalfSpyConnectionError as exc:
        session.console.print(f"[bold red]pm-calf-spy: {exc}[/bold red]")
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
        session.console.print("[dim]pm-calf-spy: connection closed.[/dim]")


__all__ = ["main"]


if __name__ == "__main__":
    main()
