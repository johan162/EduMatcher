#!/usr/bin/env python3
"""Split a Markdown document at heading boundaries.

The route file is tab-separated with ``heading`` and ``destination`` columns.
An empty heading routes the preamble. A heading route owns that heading and
all descendants until the next heading at the same or shallower level.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path


HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")


@dataclass(frozen=True)
class Route:
    heading: str
    destination: Path


@dataclass(frozen=True)
class Section:
    heading: str
    level: int
    start: int
    end: int


def read_routes(path: Path) -> list[Route]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = csv.DictReader(stream, delimiter="\t")
        if rows.fieldnames is None or {"heading", "destination"} - set(rows.fieldnames):
            raise ValueError("route file must contain heading and destination columns")
        return [
            Route(row["heading"].strip(), Path(row["destination"].strip()))
            for row in rows
            if row["destination"].strip()
        ]


def find_sections(lines: list[str]) -> list[Section]:
    sections: list[Section] = []
    fenced = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = HEADING_RE.match(line.rstrip("\n"))
        if match:
            sections.append(Section(match.group(2), len(match.group(1)), index, len(lines)))
    return [
        Section(section.heading, section.level, section.start, sections[index + 1].start if index + 1 < len(sections) else len(lines))
        for index, section in enumerate(sections)
    ]


def route_for(section: Section, routes: list[Route]) -> Route | None:
    candidates = [route for route in routes if route.heading == section.heading]
    return candidates[0] if candidates else None


def split_document(source: Path, routes_path: Path, output_root: Path) -> list[Path]:
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    routes = read_routes(routes_path)
    if not routes:
        raise ValueError("route file contains no destinations")
    sections = find_sections(lines)
    preamble = next((route for route in routes if not route.heading), None)
    outputs: dict[Path, list[str]] = {}
    if sections and sections[0].start and preamble:
        outputs.setdefault(preamble.destination, []).extend(lines[: sections[0].start])
    elif not sections and preamble:
        outputs.setdefault(preamble.destination, []).extend(lines)

    current: Route | None = preamble
    for section in sections:
        matched = route_for(section, routes)
        if matched:
            current = matched
        if current is None:
            raise ValueError(f"no route for heading: {section.heading}")
        outputs.setdefault(current.destination, []).extend(lines[section.start : section.end])

    written: list[Path] = []
    for relative_path, content in outputs.items():
        destination = output_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("".join(content), encoding="utf-8")
        written.append(destination)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("routes", type=Path)
    parser.add_argument("output_root", type=Path)
    args = parser.parse_args()
    for path in split_document(args.source, args.routes, args.output_root):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())