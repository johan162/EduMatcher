#!/usr/bin/env python3
"""Documentation loss ledger.

Answers one question: is every part of the OLD documentation still present,
somewhere, in the NEW documentation? Moves, splits, merges and re-wrapping are
fine; silent deletion is not.

Method: every old markdown file is cut into blocks at its headings. Each block
is turned into overlapping 8-word shingles (case/punctuation-insensitive). A
shingle is "covered" when it occurs anywhere in the new corpus. A block whose
coverage is below --threshold must be listed in the migration map with a
disposition (REWRITTEN, RETIRED or GENERATED) and a reason, else the run fails.

--old/--new accept directories (searched recursively for *.md) and single files.
Keep the new corpus to the documentation books only: if design notes were part
of it, text that merely also exists there would mask a loss.

Migration map (TSV, '#' starts a comment), one row per accepted exception:
    <old block-id prefix> <TAB> <DISPOSITION> <TAB> <new location> <TAB> <reason>
A block id is "<path relative to --old root>#<heading text>"; the prefix
"user-guide/190-audit.md" accepts every block of that file.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

N = 8
WORD = re.compile(r"[a-z0-9_]+")
FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
OK_DISPOSITIONS = {
    "MOVED",
    "SPLIT",
    "DUPLICATED",
    "REWRITTEN",
    "RETIRED",
    "GENERATED",
}


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def shingles(tokens: list[str]) -> list[tuple[str, ...]]:
    if len(tokens) < N:
        return [tuple(tokens)] if tokens else []
    return [tuple(tokens[i : i + N]) for i in range(len(tokens) - N + 1)]


def md_files(root: Path) -> list[tuple[Path, Path]]:
    """Return (file, base) pairs; block ids are relative to base."""
    if root.is_file():
        return [(root, root.parent)]
    return [
        (path, root)
        for path in sorted(root.rglob("*.md"))
        if "/.build/" not in path.as_posix()
    ]


def blocks(path: Path, base: Path):
    """Yield (block_id, text) for each heading-delimited block of one file."""
    relative = path.relative_to(base).as_posix()
    current_id, buffer, in_fence = f"{relative}#(top)", [], False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else HEADING.match(line)
        if match:
            yield current_id, "\n".join(buffer)
            current_id, buffer = f"{relative}#{match.group(2).strip()}", [line]
        else:
            buffer.append(line)
    yield current_id, "\n".join(buffer)


def load_map(path: Path | None) -> list[tuple[str, str]]:
    rows = []
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                columns = line.split("\t")
                if len(columns) >= 2:
                    rows.append((columns[0], columns[1].strip()))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--old", nargs="+", required=True, type=Path)
    parser.add_argument("--new", nargs="+", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--map", type=Path, help="migration map TSV (see above)")
    parser.add_argument("--report", type=Path, help="write the full per-block table here")
    args = parser.parse_args()

    new_shingles: set[tuple[str, ...]] = set()
    new_text = []
    for root in args.new:
        for path, _ in md_files(root):
            tokens = words(path.read_text(encoding="utf-8", errors="replace"))
            new_shingles.update(shingles(tokens))
            new_text.append(" ".join(tokens))
    haystack = " ".join(new_text)

    accepted = load_map(args.map)
    rows, unaccounted = [], []
    total_words = low_words = 0
    for root in args.old:
        for path, base in md_files(root):
            for block_id, text in blocks(path, base):
                tokens = words(text)
                if not tokens:
                    continue
                if len(tokens) < N:
                    coverage = 1.0 if " ".join(tokens) in haystack else 0.0
                else:
                    block_shingles = shingles(tokens)
                    coverage = sum(
                        shingle in new_shingles for shingle in block_shingles
                    ) / len(block_shingles)
                total_words += len(tokens)
                rows.append((coverage, len(tokens), block_id))
                if coverage < args.threshold:
                    low_words += len(tokens)
                    if not any(
                        block_id.startswith(prefix) and disposition in OK_DISPOSITIONS
                        for prefix, disposition in accepted
                    ):
                        unaccounted.append((coverage, len(tokens), block_id))

    if args.report:
        args.report.write_text(
            "".join(
                f"{coverage:.3f}\t{word_count}\t{block_id}\n"
                for coverage, word_count, block_id in sorted(rows)
            ),
            encoding="utf-8",
        )
    print(
        f"blocks={len(rows)} words={total_words} below_threshold_words={low_words} "
        f"unaccounted_blocks={len(unaccounted)}"
    )
    for coverage, word_count, block_id in sorted(unaccounted)[:40]:
        print(
            f"  LOSS? coverage={coverage:.2f} words={word_count}  {block_id}"
        )
    return 1 if unaccounted else 0


if __name__ == "__main__":
    sys.exit(main())
