"""pm-new-symbol / pm-ipo command line: parser, entry point and output."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from edumatcher.config_artifact import ArtifactError
from edumatcher.config_deploy import CompileError
from edumatcher.cverifier.models import CheckResult
from edumatcher.new_symbol.install import add_symbol
from edumatcher.new_symbol.listing import FIELDS


def _price(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"invalid price: {text!r}") from None
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError(f"price must be positive: {text!r}")
    return value


def _prog_name() -> str:
    name = Path(sys.argv[0]).name
    return name if name in ("pm-new-symbol", "pm-ipo") else "pm-new-symbol"


def build_parser() -> argparse.ArgumentParser:
    prog = _prog_name()
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "List a new symbol (an IPO) in an engine configuration and, when "
            "that file is the deployed one, redeploy it."
        ),
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, prog)
    parser.add_argument(
        "--config",
        type=Path,
        help="Authored YAML to edit (default: the deployed configuration's source)",
    )
    parser.add_argument(
        "--symbol", required=True, help="New symbol, 1-8 of A-Z 0-9 . _"
    )
    parser.add_argument(
        "--ipo-price",
        required=True,
        type=_price,
        help="Offer price: the book's reference price for collars and breakers",
    )
    parser.add_argument("--outstanding-shares", required=True, type=int)
    parser.add_argument("--tick-decimals", type=int, default=2)
    parser.add_argument(
        "--mm-gateway-id", help="MARKET_MAKER gateway that posts the seed quote"
    )
    parser.add_argument("--mm-bid-price", type=_price)
    parser.add_argument("--mm-ask-price", type=_price)
    parser.add_argument("--mm-bid-qty", type=int, default=1000)
    parser.add_argument("--mm-ask-qty", type=int, default=1000)
    parser.add_argument(
        "--mm-tif", type=str.upper, choices=("DAY", "GTC"), default="DAY"
    )
    parser.add_argument(
        "--mm-seed-once", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--field",
        action="append",
        default=[],
        metavar="KEY=YAML_VALUE",
        help=(
            f"Optional symbol section, one of {', '.join(FIELDS)}; repeatable "
            "(e.g. --field 'collar={static_band_pct: 0.2}')"
        ),
    )
    return parser


def _report(findings: list[CheckResult]) -> None:
    for finding in findings:
        location = f" [{finding.path}]" if finding.path else ""
        print(f"  {finding.code}{location}: {finding.message}", file=sys.stderr)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = add_symbol(args)
    except CompileError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        _report(exc.findings)
        print("        Nothing was changed.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError, yaml.YAMLError, ArtifactError) as exc:
        parser.exit(1, f"[ERROR] {exc}\n")

    if result.warnings:
        print("[WARN] the verifier has advice about the new symbol:", file=sys.stderr)
        _report(result.warnings)
    payload = result.payload
    decimals = payload["tick_decimals"]
    print(
        f"Listed {result.symbol} in {result.source}: IPO price "
        f"{payload['last_buy_price']:.{decimals}f}, "
        f"{payload['outstanding_shares']} shares outstanding"
    )
    for quote in payload.get("market_maker_quotes", []):
        print(
            f"  seed quote {quote['gateway_id']}: {quote['bid_qty']} @ "
            f"{quote['bid_price']:.{decimals}f} / {quote['ask_qty']} @ "
            f"{quote['ask_price']:.{decimals}f} ({quote['tif']})"
        )
    if "market_maker_quotes" not in payload:
        print("  no seed quote: the book opens empty")
    if result.deployed:
        print(f"Deployed to {result.artifact}. Start the exchange to open trading.")
    else:
        print(
            f"Not deployed: {result.source} is not the deployed configuration's "
            f"source. Run pm-config-deploy {result.source} with the exchange stopped."
        )


if __name__ == "__main__":
    main()
