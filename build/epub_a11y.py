#!/usr/bin/env python3
"""Add schema.org accessibility metadata to an EPUB3 package document."""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

PREFIX = "schema: http://schema.org/"
SUMMARY = (
    "Reflowable text with a linked table of contents and a linear reading "
    "order. Diagrams and figures may not have text alternatives."
)
META = [
    ("accessMode", "textual"),
    ("accessMode", "visual"),
    ("accessModeSufficient", "textual"),
    ("accessibilityFeature", "tableOfContents"),
    ("accessibilityFeature", "readingOrder"),
    ("accessibilityFeature", "displayTransformability"),
    ("accessibilityHazard", "none"),
    ("accessibilitySummary", SUMMARY),
]


def patch_opf(opf: str) -> str:
    if "schema:accessMode" in opf:
        return opf
    if 'prefix="' in opf:
        opf = re.sub(
            r'prefix="([^"]*)"',
            lambda match: f'prefix="{match.group(1)} {PREFIX}"',
            opf,
            count=1,
        )
    else:
        opf = opf.replace("<package ", f'<package prefix="{PREFIX}" ', 1)
    lines = "".join(
        f'    <meta property="schema:{key}">{value}</meta>\n'
        for key, value in META
    )
    return opf.replace("  </metadata>", lines + "  </metadata>", 1)


def main(path: Path) -> None:
    temporary = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.endswith(".opf"):
                data = patch_opf(data.decode("utf-8")).encode("utf-8")
            target.writestr(info, data)
    temporary.replace(path)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
