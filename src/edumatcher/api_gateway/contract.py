"""Generate/check the committed REST contract, ``spec/rest/openapi.json``.

The document is exactly what ``/openapi.json`` serves. Committing it makes
every change to the v1 surface -- a field, a status code, a parameter bound --
a reviewed diff, and ``check`` (in ``make _check`` and CI) fails when the code
and the committed contract disagree. Run ``make openapi`` after a deliberate
change and commit the result; whether the change is additive is then a review
question the diff makes answerable (see the spec's compatibility policy).
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from edumatcher.api_gateway.config import ApiGatewayConfig

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "spec" / "rest" / "openapi.json"


def render(config: ApiGatewayConfig | None = None) -> str:
    """The OpenAPI document the gateway publishes, as committed."""
    from edumatcher.api_gateway.main import create_app

    app = create_app(config or ApiGatewayConfig())
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def generate(path: Path | None = None) -> bool:
    """Write the contract; return whether it changed."""
    path = path or OUTPUT
    expected = render()
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == expected:
        print(f"openapi contract: already up to date ({_label(path)})")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expected, encoding="utf-8")
    print(f"openapi contract: wrote {_label(path)}")
    return True


def check(path: Path | None = None) -> bool:
    """True when the committed contract is what the gateway publishes."""
    path = path or OUTPUT
    expected = render()
    actual = path.read_text(encoding="utf-8") if path.exists() else ""
    if actual == expected:
        print("openapi contract: OK - spec/rest/openapi.json matches the gateway")
        return True
    print(
        "openapi contract: the REST surface changed. Review the diff below, "
        "run `make openapi` and commit the result.",
        file=sys.stderr,
    )
    diff = difflib.unified_diff(
        actual.splitlines(),
        expected.splitlines(),
        fromfile=_label(path),
        tofile="gateway",
        lineterm="",
    )
    print("\n".join(diff), file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate/check the committed REST contract (openapi.json)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("generate", help="Write spec/rest/openapi.json")
    subparsers.add_parser("check", help="Fail if the committed contract is stale")
    args = parser.parse_args(argv)
    if args.command == "generate":
        generate(OUTPUT)
        return 0
    return 0 if check(OUTPUT) else 1


if __name__ == "__main__":
    raise SystemExit(main())
