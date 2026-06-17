#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import tomllib


def iter_sources(manifest_path: Path) -> list[str]:
    data = tomllib.loads(manifest_path.read_text(encoding='utf-8'))
    sources: list[str] = []
    for rel in data.get('frontmatter', {}).get('files', []):
        sources.append(rel)
    for part in data.get('parts', []):
        part_dir = part['dir']
        for rel in part.get('files', []):
            sources.append(str(Path(part_dir) / rel))
    for rel in data.get('backmatter', {}).get('files', []):
        sources.append(rel)
    return sources


def main() -> None:
    parser = argparse.ArgumentParser(description='Print intro book sources in order')
    parser.add_argument('--manifest', default='book.toml')
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    for rel in iter_sources(manifest_path):
        print(rel)


if __name__ == '__main__':
    main()
