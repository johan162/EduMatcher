"""
pm-admin-cli — non-interactive CLI tool for ADMIN exchange operations.

Each subcommand maps 1-to-1 to a method on ExchangeCommandClient.
All output formatting and command execution is delegated to
:func:`~edumatcher.commands.console.execute_command` — the same function
used by the interactive ``pm-admin`` REPL — so adding a new command only
requires changes in that one place plus an argparse subcommand here.

Exit codes
----------
  0  Command accepted / completed successfully
  1  Auth failure, command rejected, or timeout
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from edumatcher.commands import CommandTimeoutError, ExchangeCommandClient
from edumatcher.commands.console import execute_command
from edumatcher.config import ENGINE_PUB_ADDR, ENGINE_PULL_ADDR


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-admin-cli",
        description="EduMatcher ADMIN CLI — send a single exchange command and exit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  pm-admin-cli --id GW_ADMIN halt\n"
            "  pm-admin-cli --id GW_ADMIN resume\n"
            "  pm-admin-cli --id GW_ADMIN kill --gw TRADER01\n"
            "  pm-admin-cli --id GW_ADMIN kill --gw TRADER01 --sym AAPL\n"
            "  pm-admin-cli --id GW_ADMIN kick --gw TRADER01 --reason 'Compliance hold'\n"
            "  pm-admin-cli --id GW_ADMIN qcancel --gw MM01 --sym AAPL\n"
            "  pm-admin-cli --id GW_ADMIN book --sym AAPL\n"
            "  pm-admin-cli --id GW_ADMIN orders --gw TRADER01\n"
            "  pm-admin-cli --id GW_ADMIN symbols\n"
            "  pm-admin-cli --id GW_ADMIN session --state CONTINUOUS\n"
            "  pm-admin-cli --id GW_ADMIN session-status\n"
            "  pm-admin-cli --id GW_ADMIN schedule\n"
            "  pm-admin-cli --id GW_ADMIN gateways\n"
            "  pm-admin-cli --id GW_ADMIN volume\n"
        ),
    )

    # Global flags
    parser.add_argument(
        "--id",
        required=True,
        metavar="GW_ID",
        help="ADMIN gateway ID configured in engine_config.yaml (e.g. GW_ADMIN)",
    )
    parser.add_argument(
        "--push",
        default=ENGINE_PULL_ADDR,
        metavar="ADDR",
        help=f"Engine PULL socket address (default: {ENGINE_PULL_ADDR})",
    )
    parser.add_argument(
        "--sub",
        default=ENGINE_PUB_ADDR,
        metavar="ADDR",
        help=f"Engine PUB socket address (default: {ENGINE_PUB_ADDR})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3000,
        metavar="MS",
        help="Ack timeout in milliseconds (default: 3000)",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # ---- ADMIN-only ----
    sub.add_parser(
        "halt",
        help="Exchange-wide circuit-breaker halt (ADMIN role required)",
    )
    sub.add_parser(
        "resume",
        help="Resume all symbols halted by 'halt' (ADMIN role required)",
    )

    # ---- Any connected gateway ----
    p = sub.add_parser(
        "kill",
        help="Cancel all resting orders and quotes for a gateway",
    )
    p.add_argument("--gw", required=True, metavar="GW_ID", help="Target gateway ID")
    p.add_argument(
        "--sym",
        default="",
        metavar="SYMBOL",
        help="Scope cancellation to one symbol (omit for all symbols)",
    )

    p = sub.add_parser(
        "kick",
        help="Forcefully disconnect a gateway",
    )
    p.add_argument("--gw", required=True, metavar="GW_ID", help="Target gateway ID")
    p.add_argument(
        "--reason",
        default="",
        metavar="TEXT",
        help="Reason string recorded in the engine log",
    )

    p = sub.add_parser(
        "qcancel",
        help="Cancel the active two-sided quote for a gateway on one symbol",
    )
    p.add_argument("--gw", required=True, metavar="GW_ID", help="Target gateway ID")
    p.add_argument("--sym", required=True, metavar="SYMBOL", help="Symbol to cancel")

    p = sub.add_parser(
        "book",
        help="Print the L1/L2 order-book snapshot for a symbol",
    )
    p.add_argument("--sym", required=True, metavar="SYMBOL", help="Symbol to query")

    p = sub.add_parser(
        "orders",
        help="List all resting orders for a gateway",
    )
    p.add_argument("--gw", required=True, metavar="GW_ID", help="Target gateway ID")

    sub.add_parser(
        "symbols",
        help="List all instruments configured in the engine",
    )

    p = sub.add_parser(
        "session",
        help="Request a session-phase transition",
    )
    p.add_argument(
        "--state",
        required=True,
        type=str.upper,
        metavar="STATE",
        help=(
            "Target session state.  "
            "One of: PRE_OPEN OPENING_AUCTION CONTINUOUS CLOSING_AUCTION CLOSED"
        ),
    )

    sub.add_parser(
        "session-status",
        help="Show the current session state (read-only, no transition)",
    )

    sub.add_parser(
        "schedule",
        help="Show the automatic session-transition schedule from the engine config",
    )

    sub.add_parser(
        "gateways",
        help="List all configured gateways and their connection status",
    )

    sub.add_parser(
        "volume",
        help="Show daily traded volume per symbol and exchange total",
    )

    return parser


def _args_to_fields(args: Any) -> dict[str, str]:
    """Convert a parsed args namespace to the ``fields`` dict expected by execute_command."""
    fields: dict[str, str] = {}
    if getattr(args, "gw", None):
        fields["GW"] = args.gw
    if getattr(args, "sym", None):
        fields["SYM"] = args.sym
    if getattr(args, "reason", None):
        fields["REASON"] = args.reason
    if getattr(args, "state", None):
        fields["STATE"] = args.state
    return fields


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    client = ExchangeCommandClient(
        args.id,
        push_addr=args.push,
        pub_addr=args.sub,
        timeout_ms=args.timeout,
    )

    # Connect / authenticate
    try:
        auth = client.connect()
    except CommandTimeoutError:
        print(
            f"Connection timed out.  Is the engine running at {args.push}?",
            file=sys.stderr,
        )
        client.close()
        sys.exit(1)

    if not auth.get("accepted"):
        print(
            f"Auth refused: {auth.get('reason', '')}  "
            "(check role: ADMIN in engine_config.yaml)",
            file=sys.stderr,
        )
        client.close()
        sys.exit(1)

    # Execute the single command
    # argparse uses hyphens; normalise to UNDERSCORE for execute_command
    cmd = args.command.upper().replace("-", "_")
    fields = _args_to_fields(args)
    ok = True
    try:
        ok = execute_command(client, cmd, fields)
    except CommandTimeoutError as exc:
        print(f"Timeout: {exc}", file=sys.stderr)
        ok = False
    finally:
        client.disconnect()
        client.close()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
