#!/usr/bin/env python3
"""Print a book's sources in manifest order, or one manifest key.

Exits non-zero if two files of one book share a basename (00-part.md excepted).
"""
from __future__ import annotations

import argparse
import tomllib
from pathlib import Path


def sources(manifest: Path) -> list[str]:
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    book = manifest.parent
    output = [*data.get("frontmatter", {}).get("files", [])]
    for part in data.get("parts", []):
        output += [str(Path(part["dir"]) / file) for file in part["files"]]
    output += data.get("backmatter", {}).get("files", [])
    seen: dict[str, str] = {}
    for relative in output:
        name = Path(relative).name
        if name == "00-part.md":
            continue
        if name in seen:
            raise SystemExit(
                f"{manifest}: file name {name!r} used twice: "
                f"{seen[name]} and {relative}"
            )
        seen[name] = relative
    return [str(book / relative) for relative in output]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--meta", help="print this top-level manifest key")
    args = parser.parse_args()
    if args.meta:
        print(tomllib.loads(args.manifest.read_text(encoding="utf-8"))[args.meta])
    else:
        print("\n".join(sources(args.manifest)))


if __name__ == "__main__":
    main()
