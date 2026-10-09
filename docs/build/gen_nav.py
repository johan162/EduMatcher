#!/usr/bin/env python3
"""Generate the MkDocs navigation block from book manifests."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

BEGIN = "# BEGIN GENERATED NAV (build/gen_nav.py) - do not edit by hand"
END = "# END GENERATED NAV"


def first_h1(path: Path) -> str:
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and line.startswith("# "):
            # Drop a trailing attribute list such as "{.part}" (LaTeX-only).
            return re.sub(r"\s*\{[^}]*\}\s*$", "", line[2:]).strip()
    return path.stem


def quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def book_nav(docs: Path, manifest: Path) -> list[str]:
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    book = manifest.parent
    relative = lambda file: (book / file).relative_to(docs).as_posix()
    output = [f"  - {quote(data['title'])}:"]
    for file in data.get("frontmatter", {}).get("files", []):
        output.append(f"    - {quote(first_h1(book / file))}: {relative(file)}")
    for part in data.get("parts", []):
        output.append(f"    - {quote(part['title'])}:")
        for file in part["files"]:
            path = Path(part["dir"]) / file
            output.append(
                f"      - {quote(first_h1(book / path))}: "
                f"{(book / path).relative_to(docs).as_posix()}"
            )
    for file in data.get("backmatter", {}).get("files", []):
        output.append(f"    - {quote(first_h1(book / file))}: {relative(file)}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mkdocs", type=Path, required=True)
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    parser.add_argument("--books", nargs="*", help="book slugs in nav order")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    slugs = args.books or sorted(
        path.parent.name for path in (args.docs / "books").glob("*/book.toml")
    )
    block = [BEGIN]
    for slug in slugs:
        block += book_nav(args.docs, args.docs / "books" / slug / "book.toml")
    block.append(END)

    text = args.mkdocs.read_text(encoding="utf-8")
    head, _, rest = text.partition(BEGIN)
    _, _, tail = rest.partition(END)
    if not rest:
        raise SystemExit(f"markers not found in {args.mkdocs}")
    new = head + "\n".join(block) + tail
    if args.check:
        if new != text:
            print("mkdocs.yml nav is stale: run `make nav`", file=sys.stderr)
            return 1
        return 0
    args.mkdocs.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
