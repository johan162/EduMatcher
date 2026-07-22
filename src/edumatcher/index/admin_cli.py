"""
pm-index-admin-cli — non-interactive CLI for applying corporate actions and
constituent changes to a running ``pm-index`` process.

Each mutating subcommand maps 1-to-1 to a method on
:class:`~edumatcher.commands.client.ExchangeCommandClient`
(``index_corp_action``, ``index_delist``, ``index_add_constituent``), the
same client class ``pm-admin-cli`` uses for engine commands. This tool talks
directly to ``pm-index``'s PUSH/SUB pair (default ports 5559/5558) — it does
not touch the engine's own PUSH/SUB pair (5555/5556) and does not require
``pm-engine`` to be reachable.

Unlike ``pm-admin-cli``, there is no ``connect()``/auth handshake: ``pm-index``
has no authentication of any kind on its PULL socket (see
docs-design/EduMatcher-index-admin-cli.md, section 9). The ``--id`` value is
used purely as an ack-routing key, not as an identity check.

Exit codes
----------
  0  Command accepted / completed successfully (or --dry-run validated OK)
  1  Command rejected by pm-index, or ack timeout
  2  Usage error (bad flags, failed client-side validation)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from edumatcher.commands import CommandError, CommandTimeoutError, ExchangeCommandClient
from edumatcher.config import INDEX_PUB_CONNECT_ADDR, INDEX_PULL_CONNECT_ADDR

_FORMATS = ("table", "json")

# Corporate-action types pm-index's _handle_corp_action supports today.
# See src/edumatcher/index/main.py::IndexProcess._handle_corp_action.
_SPLIT = "SPLIT"
_CASH_DIVIDEND = "CASH_DIVIDEND"
_SHARES_ISSUANCE = "SHARES_ISSUANCE"


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _report(result: dict[str, Any], accepted_message: str, fmt: str) -> bool:
    """Print *accepted_message* on success, else a REJECTED line with reason.

    Mirrors edumatcher.commands.console._report's accepted/rejected
    convention (same wording style) without importing that module, since
    console.py pulls in prompt_toolkit for its interactive REPL — an
    unnecessary dependency for this one-shot tool.
    """
    accepted = bool(result.get("accepted"))
    if fmt == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return accepted
    if accepted:
        print(accepted_message)
    else:
        print(f"REJECTED  {result.get('reason', '')}")
    return accepted


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _print_dry_run(topic: str, payload: dict[str, Any]) -> None:
    print(f"DRY RUN — would send topic={topic!r}")
    print(json.dumps(payload, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Client-side validators
# ---------------------------------------------------------------------------


def _parse_ratio(raw: str) -> tuple[int, int]:
    """Parse an 'N:M' split ratio string into (numerator, denominator)."""
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"--ratio must be in N:M form (e.g. 4:1), got {raw!r}")
    try:
        numerator, denominator = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"--ratio components must be integers, got {raw!r}") from exc
    if numerator <= 0 or denominator <= 0:
        raise ValueError(f"--ratio components must both be positive, got {raw!r}")
    return numerator, denominator


def _require_positive(value: float, flag: str) -> None:
    if value <= 0:
        raise ValueError(f"{flag} must be > 0, got {value!r}")


def _require_positive_int(value: int, flag: str) -> None:
    if value <= 0:
        raise ValueError(f"{flag} must be a positive integer, got {value!r}")


# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------


def _confirm(prompt: str, assume_yes: bool) -> bool:
    """Return True if the operator confirms, or --yes/-y was passed."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(
            f"{prompt}\n"
            "REJECTED  stdin is not a TTY; pass --yes/-y to confirm "
            "non-interactively.",
            file=sys.stderr,
        )
        return False
    reply = input(f"{prompt} [y/N] ").strip().lower()
    return reply in ("y", "yes")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-index-admin-cli",
        description=(
            "EduMatcher Index Admin CLI — apply a corporate action or "
            "constituent change to a running pm-index process, then exit."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  pm-index-admin-cli --id OPS01 split --index TECH10 --sym AAPL --ratio 4:1\n"
            "  pm-index-admin-cli --id OPS01 dividend --index TECH10 --sym MSFT --amount 0.75\n"
            "  pm-index-admin-cli --id OPS01 shares --index TECH10 --sym AAPL --new-shares 15200000000\n"
            "  pm-index-admin-cli --id OPS01 shares --index TECH10 --sym AAPL --delta -800000000\n"
            "  pm-index-admin-cli --id OPS01 add --index TECH10 --sym NVDA --shares 2470000000 --price 118.50\n"
            "  pm-index-admin-cli --id OPS01 delist --index TECH10 --sym XYZ\n"
            "  pm-index-admin-cli --id OPS01 history --index TECH10 --limit 20\n"
        ),
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-index-admin-cli")

    # ---- Global flags ----
    parser.add_argument(
        "--id",
        required=True,
        metavar="GW_ID",
        help=(
            "Gateway ID used as the ack-routing key. Not authenticated by "
            "pm-index (its PULL socket has no auth) — any non-empty value "
            "works, but a real gateway_id makes acks easier to correlate."
        ),
    )
    parser.add_argument(
        "--push",
        dest="index_push",
        default=INDEX_PULL_CONNECT_ADDR,
        metavar="ADDR",
        help=f"pm-index PULL socket address (default: {INDEX_PULL_CONNECT_ADDR})",
    )
    parser.add_argument(
        "--sub",
        dest="index_sub",
        default=INDEX_PUB_CONNECT_ADDR,
        metavar="ADDR",
        help=f"pm-index PUB socket address (default: {INDEX_PUB_CONNECT_ADDR})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3000,
        metavar="MS",
        help="Ack timeout in milliseconds (default: 3000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the outbound payload; do not send it.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt for mutating commands.",
    )
    parser.add_argument(
        "--format",
        default="table",
        choices=_FORMATS,
        help="Output format: table (default, human-readable) or json.",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # ---- split ----
    p = sub.add_parser("split", help="Apply a stock split (or reverse split)")
    p.add_argument("--index", required=True, metavar="INDEX_ID", help="Index ID")
    p.add_argument("--sym", required=True, metavar="SYMBOL", help="Constituent symbol")
    p.add_argument(
        "--ratio",
        required=True,
        metavar="N:M",
        help="Split ratio, e.g. 4:1 for a 4-for-1 split, 1:10 for a 1-for-10 reverse split",
    )

    # ---- dividend ----
    p = sub.add_parser("dividend", help="Apply a cash dividend adjustment")
    p.add_argument("--index", required=True, metavar="INDEX_ID", help="Index ID")
    p.add_argument("--sym", required=True, metavar="SYMBOL", help="Constituent symbol")
    p.add_argument(
        "--amount",
        required=True,
        type=float,
        metavar="AMOUNT",
        help="Dividend per share, in price units. Must be > 0.",
    )

    # ---- shares ----
    p = sub.add_parser(
        "shares", help="Set shares outstanding (covers both issuances and buy-backs)"
    )
    p.add_argument("--index", required=True, metavar="INDEX_ID", help="Index ID")
    p.add_argument("--sym", required=True, metavar="SYMBOL", help="Constituent symbol")
    shares_group = p.add_mutually_exclusive_group(required=True)
    shares_group.add_argument(
        "--new-shares",
        type=int,
        metavar="N",
        help="New absolute total shares outstanding.",
    )
    shares_group.add_argument(
        "--delta",
        type=int,
        metavar="N",
        help=(
            "Signed change applied to the constituent's last known shares "
            "outstanding (negative for a buy-back, positive for an "
            "issuance). Resolved via 'history' before sending; the "
            "computed absolute value is shown in the confirmation prompt."
        ),
    )

    # ---- add ----
    p = sub.add_parser("add", help="Add a new constituent")
    p.add_argument("--index", required=True, metavar="INDEX_ID", help="Index ID")
    p.add_argument("--sym", required=True, metavar="SYMBOL", help="Symbol to add")
    p.add_argument(
        "--shares",
        required=True,
        type=int,
        metavar="N",
        help="Initial shares outstanding. Must be > 0.",
    )
    p.add_argument(
        "--price",
        required=True,
        type=float,
        metavar="PRICE",
        help="Initial reference price. Must be > 0.",
    )

    # ---- delist ----
    p = sub.add_parser("delist", help="Remove a constituent")
    p.add_argument("--index", required=True, metavar="INDEX_ID", help="Index ID")
    p.add_argument("--sym", required=True, metavar="SYMBOL", help="Symbol to delist")

    # ---- history ----
    p = sub.add_parser(
        "history", help="Show recent structural/corp-action history for an index"
    )
    p.add_argument("--index", required=True, metavar="INDEX_ID", help="Index ID")
    p.add_argument(
        "--from",
        dest="from_ts",
        type=float,
        default=None,
        metavar="UNIX_TS",
        help="Start of range as a Unix timestamp (default: 24h ago).",
    )
    p.add_argument(
        "--to",
        dest="to_ts",
        type=float,
        default=None,
        metavar="UNIX_TS",
        help="End of range as a Unix timestamp (default: now).",
    )
    p.add_argument(
        "--types",
        default=None,
        metavar="TYPE,TYPE,...",
        help=(
            "Comma-separated filter: INIT, CORP_ACTION, DELIST, "
            "ADD_CONSTITUENT (default: all)."
        ),
    )
    p.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="Maximum rows shown (default: 50).",
    )

    return parser


# ---------------------------------------------------------------------------
# Subcommand handlers
#
# Each returns True (accepted / success) or False (rejected / validation
# failure). main() maps this to the process exit code.
# ---------------------------------------------------------------------------


def _cmd_split(client: ExchangeCommandClient, args: argparse.Namespace) -> bool:
    numerator, denominator = _parse_ratio(args.ratio)

    if args.dry_run:
        _print_dry_run(
            "index.corp_action",
            {
                "action": _SPLIT,
                "index_id": args.index.upper(),
                "symbol": args.sym.upper(),
                "gateway_id": args.id.upper(),
                "ratio_numerator": numerator,
                "ratio_denominator": denominator,
            },
        )
        return True

    if not _confirm(
        f"This will apply a SPLIT ({numerator}:{denominator}) to "
        f"{args.sym.upper()} in index {args.index.upper()}. Continue?",
        args.yes,
    ):
        return False

    result = client.index_corp_action(
        args.index,
        action=_SPLIT,
        symbol=args.sym,
        ratio_numerator=numerator,
        ratio_denominator=denominator,
    )
    return _report(
        result,
        f"SPLIT OK   {args.index.upper()}  {args.sym.upper()}  "
        f"ratio={numerator}:{denominator}  "
        f"new_level={result.get('level')}  new_divisor={result.get('divisor')}",
        args.format,
    )


def _cmd_dividend(client: ExchangeCommandClient, args: argparse.Namespace) -> bool:
    _require_positive(args.amount, "--amount")

    if args.dry_run:
        _print_dry_run(
            "index.corp_action",
            {
                "action": _CASH_DIVIDEND,
                "index_id": args.index.upper(),
                "symbol": args.sym.upper(),
                "gateway_id": args.id.upper(),
                "dividend_per_share": args.amount,
            },
        )
        return True

    if not _confirm(
        f"This will apply a CASH_DIVIDEND ({args.amount}) to "
        f"{args.sym.upper()} in index {args.index.upper()}. Continue?",
        args.yes,
    ):
        return False

    result = client.index_corp_action(
        args.index,
        action=_CASH_DIVIDEND,
        symbol=args.sym,
        dividend_per_share=args.amount,
    )
    return _report(
        result,
        f"CASH_DIVIDEND OK   {args.index.upper()}  {args.sym.upper()}  "
        f"amount={args.amount}  "
        f"new_level={result.get('level')}  new_divisor={result.get('divisor')}",
        args.format,
    )


def _resolve_delta(
    client: ExchangeCommandClient, index_id: str, symbol: str, delta: int
) -> int | None:
    """Resolve --delta into an absolute new_shares_outstanding value.

    Looks up the most recent ADD_CONSTITUENT / CORP_ACTION SHARES_ISSUANCE
    record for *symbol* via index_history() and applies *delta* to it.
    Returns None (and prints an error) if no prior share count is found.
    """
    import time

    hist = client.index_history(
        index_id,
        from_ts=0.0,
        to_ts=time.time(),
        types=["ADD_CONSTITUENT", "CORP_ACTION"],
    )
    records = hist.get("records", [])
    last_shares: int | None = None
    last_ts: float = -1.0
    sym_upper = symbol.upper()
    for rec in records:
        if rec.get("symbol") != sym_upper:
            continue
        ts = float(rec.get("timestamp", 0.0))
        detail = str(rec.get("detail", ""))
        shares: int | None = None
        if rec.get("type") == "ADD_CONSTITUENT":
            # ADD_CONSTITUENT records don't carry shares_outstanding in the
            # history payload (only reference_price) — skip; SHARES_ISSUANCE
            # corp-action records are the authoritative source once applied.
            continue
        if rec.get("type") == "CORP_ACTION" and detail.startswith("shares="):
            try:
                shares = int(detail.split("=", 1)[1])
            except ValueError:
                shares = None
        if shares is not None and ts >= last_ts:
            last_ts = ts
            last_shares = shares

    if last_shares is None:
        print(
            f"REJECTED  no prior shares_outstanding found for {sym_upper} in "
            f"index {index_id.upper()} — pass --new-shares instead.",
            file=sys.stderr,
        )
        return None

    print(f"Last known shares_outstanding for {sym_upper}: {_fmt_int(last_shares)}")
    return last_shares + delta


def _cmd_shares(client: ExchangeCommandClient, args: argparse.Namespace) -> bool:
    if args.new_shares is not None:
        new_shares = args.new_shares
    else:
        resolved = _resolve_delta(client, args.index, args.sym, args.delta)
        if resolved is None:
            return False
        new_shares = resolved

    _require_positive_int(new_shares, "resulting shares outstanding")

    if args.dry_run:
        _print_dry_run(
            "index.corp_action",
            {
                "action": _SHARES_ISSUANCE,
                "index_id": args.index.upper(),
                "symbol": args.sym.upper(),
                "gateway_id": args.id.upper(),
                "new_shares_outstanding": new_shares,
            },
        )
        return True

    verb = "buy-back" if args.delta is not None and args.delta < 0 else "issuance"
    if args.new_shares is not None:
        prompt = (
            f"This will apply a SHARES_ISSUANCE to {args.sym.upper()} in "
            f"index {args.index.upper()}, setting shares_outstanding to "
            f"{_fmt_int(new_shares)}. Continue?"
        )
    else:
        prompt = (
            f"This will set shares_outstanding to {_fmt_int(new_shares)} "
            f"(delta {args.delta:+,}, a {verb}). Continue?"
        )
    if not _confirm(prompt, args.yes):
        return False

    result = client.index_corp_action(
        args.index,
        action=_SHARES_ISSUANCE,
        symbol=args.sym,
        new_shares_outstanding=new_shares,
    )
    return _report(
        result,
        f"SHARES_ISSUANCE OK   {args.index.upper()}  {args.sym.upper()}  "
        f"new_shares_outstanding={_fmt_int(new_shares)}  "
        f"new_level={result.get('level')}  new_divisor={result.get('divisor')}",
        args.format,
    )


def _cmd_add(client: ExchangeCommandClient, args: argparse.Namespace) -> bool:
    _require_positive_int(args.shares, "--shares")
    _require_positive(args.price, "--price")

    if args.dry_run:
        _print_dry_run(
            "index.constituent_change",
            {
                "change_type": "ADD",
                "index_id": args.index.upper(),
                "symbol": args.sym.upper(),
                "gateway_id": args.id.upper(),
                "shares_outstanding": args.shares,
                "initial_price": args.price,
            },
        )
        return True

    if not _confirm(
        f"Add {args.sym.upper()} to index {args.index.upper()} "
        f"(shares_outstanding={_fmt_int(args.shares)}, initial_price={args.price})?\n"
        f"Note: {args.sym.upper()} must already be a configured tradeable "
        "symbol, or it will never update.",
        args.yes,
    ):
        return False

    result = client.index_add_constituent(
        args.index,
        args.sym,
        shares_outstanding=args.shares,
        initial_price=args.price,
    )
    return _report(
        result,
        f"ADD OK   {args.index.upper()}  {args.sym.upper()}  "
        f"new_level={result.get('level')}  new_divisor={result.get('divisor')}",
        args.format,
    )


def _cmd_delist(client: ExchangeCommandClient, args: argparse.Namespace) -> bool:
    if args.dry_run:
        _print_dry_run(
            "index.constituent_change",
            {
                "change_type": "DELIST",
                "index_id": args.index.upper(),
                "symbol": args.sym.upper(),
                "gateway_id": args.id.upper(),
            },
        )
        return True

    if not _confirm(
        f"Delist {args.sym.upper()} from index {args.index.upper()}? "
        "This cannot be undone from history — re-adding "
        f"{args.sym.upper()} will require supplying shares_outstanding "
        "and initial_price again.",
        args.yes,
    ):
        return False

    result = client.index_delist(args.index, args.sym)
    return _report(
        result,
        f"DELIST OK   {args.index.upper()}  {args.sym.upper()}  "
        f"new_level={result.get('level')}  new_divisor={result.get('divisor')}",
        args.format,
    )


def _cmd_history(client: ExchangeCommandClient, args: argparse.Namespace) -> bool:
    import time

    to_ts = args.to_ts if args.to_ts is not None else time.time()
    from_ts = args.from_ts if args.from_ts is not None else to_ts - 86400.0

    types: list[str] | None = None
    if args.types:
        types = [t.strip().upper() for t in args.types.split(",") if t.strip()]

    result = client.index_history(args.index, from_ts=from_ts, to_ts=to_ts, types=types)
    records = list(result.get("records", []))[: args.limit]

    if args.format == "json":
        print(json.dumps(records, indent=2, sort_keys=True))
        return True

    if not records:
        print("No history records found.")
        return True

    for rec in records:
        ts = rec.get("timestamp", "")
        rtype = rec.get("type", "")
        symbol = rec.get("symbol", "-")
        if rtype == "CORP_ACTION":
            detail = f"{rec.get('action', '')} {rec.get('detail', '')} -> level={rec.get('level')}"
        elif rtype == "ADD_CONSTITUENT":
            detail = (
                f"shares={_fmt_int(rec.get('shares_outstanding', ''))} "
                f"price={rec.get('reference_price', '')}"
            )
        elif rtype == "DELIST":
            detail = f"-> level={rec.get('level')}"
        elif rtype == "INIT":
            detail = f"base_value={rec.get('base_value', '')}"
        else:
            detail = ""
        print(f"  {ts}  {rtype:<15} {symbol:<8} {detail}")
    return True


_HANDLERS = {
    "split": _cmd_split,
    "dividend": _cmd_dividend,
    "shares": _cmd_shares,
    "add": _cmd_add,
    "delist": _cmd_delist,
    "history": _cmd_history,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    client = ExchangeCommandClient(
        args.id,
        index_pull_addr=args.index_push,
        index_pub_addr=args.index_sub,
        timeout_ms=args.timeout,
    )

    handler = _HANDLERS[args.command]
    try:
        try:
            ok = handler(client, args)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            sys.exit(2)
        except CommandError as exc:
            # A generic side-channel error reply (e.g. index.error.<id> for
            # an unrecognized --index) — fails fast instead of waiting out
            # the full --timeout for an ack that will never arrive.
            if args.format == "json":
                print(json.dumps(exc.payload, indent=2, sort_keys=True))
            else:
                print(f"REJECTED  {exc.reason}")
            sys.exit(1)
        except CommandTimeoutError as exc:
            print(
                f"Timed out waiting for pm-index: {exc}\n"
                f"Is pm-index running and reachable at {args.index_push}?",
                file=sys.stderr,
            )
            sys.exit(1)
    finally:
        client.close()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
