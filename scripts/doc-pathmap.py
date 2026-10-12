#!/usr/bin/env python3
"""Rewrite documentation paths using the migration map."""

from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path

BOOKS = {
    "quick-start",
    "participant-guide",
    "operator-guide",
    "reference-manual",
    "protocols-and-clients",
    "architecture-and-development",
    "training-guide",
}
ROOT_DOC_DIRS = {"assets", "examples", "training"}


def read_paths(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = csv.DictReader(stream, delimiter="\t")
        if rows.fieldnames is None or {"old_path", "new_path"} - set(rows.fieldnames):
            raise ValueError("path map must contain old_path and new_path columns")
        mappings = {
            row["old_path"].strip(): row["new_path"].strip()
            for row in rows
            if row["old_path"].strip() and row["new_path"].strip()
        }
    for old_path, new_path in list(mappings.items()):
        if old_path.startswith("../") and new_path.startswith("../"):
            old_tail = old_path[3:]
            new_tail = new_path[3:]
            if old_tail.split("/", 1)[0] in ROOT_DOC_DIRS | BOOKS | {
                "user-guide", "concepts", "architecture", "developer"
            }:
                mappings.setdefault(f"docs/{old_tail}", f"docs/books/{new_tail}")
    return mappings


def rewrite(text: str, paths: dict[str, str], source: Path | None = None) -> str:
    for old_path, new_path in sorted(paths.items(), key=lambda item: len(item[0]), reverse=True):
        if source is not None and old_path.startswith("../") and new_path.startswith("../"):
            target = Path("docs/books") / new_path[3:]
            new_path = os.path.relpath(target, source.parent).replace(os.sep, "/")
        if old_path.startswith("../"):
            old_path = old_path.removeprefix("../")
            pattern = rf"(?<![A-Za-z0-9_])(?:\.\./)+{re.escape(old_path)}(?=[#),.;:\"'`\s]|$)"
        else:
            pattern = rf"(?<![A-Za-z0-9_./]){re.escape(old_path)}(?=[#),.;:\"'`\s]|$)"
        text = re.sub(pattern, new_path, text)
    if source is not None:
        book_pattern = rf"(?<![A-Za-z0-9_])(?:[A-Za-z0-9_.-]+/|\.\./)+({'|'.join(sorted(BOOKS))})/([^#)\"'`\s]+)"

        def normalize(match: re.Match[str]) -> str:
            book = match.group(1)
            rest = match.group(2)
            while rest.startswith(f"{book}/"):
                rest = rest[len(book) + 1 :]
            target = Path("docs/books") / book / rest
            return os.path.relpath(target, source.parent).replace(os.sep, "/")

        text = re.sub(book_pattern, normalize, text)
        root_pattern = rf"(?<![A-Za-z0-9_])(?:\.\./)+({'|'.join(sorted(ROOT_DOC_DIRS))})/([^#)\"'`\s]+)"

        def normalize_root(match: re.Match[str]) -> str:
            if match.group(1) == "training":
                target = Path("docs/books/training-guide") / match.group(2)
            else:
                target = Path("docs") / match.group(1) / match.group(2)
            return os.path.relpath(target, source.parent).replace(os.sep, "/")

        text = re.sub(root_pattern, normalize_root, text)
        home_pattern = r"(?<![A-Za-z0-9_])(?:\.\./)+how-exchange-works\.md"
        text = re.sub(
            home_pattern,
            lambda _: os.path.relpath(Path("docs/how-exchange-works.md"), source.parent).replace(os.sep, "/"),
            text,
        )
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--check", action="store_true", help="fail when a file would change")
    args = parser.parse_args()
    paths = read_paths(args.mapping)
    changed = False
    for path in args.files:
        original = path.read_text(encoding="utf-8")
        updated = rewrite(original, paths, path)
        if updated != original:
            changed = True
            if not args.check:
                path.write_text(updated, encoding="utf-8")
            print(path)
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())