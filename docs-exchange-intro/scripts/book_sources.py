#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import tomllib


def iter_sources(manifest_path: Path, part: int | None = None) -> list[str]:
    data = tomllib.loads(manifest_path.read_text(encoding='utf-8'))
    sources: list[str] = []
    for rel in data.get('frontmatter', {}).get('files', []):
        sources.append(rel)
    all_parts = data.get('parts', [])
    selected = [all_parts[part - 1]] if part is not None else all_parts
    for p in selected:
        part_dir = p['dir']
        for rel in p.get('files', []):
            sources.append(str(Path(part_dir) / rel))
    for rel in data.get('backmatter', {}).get('files', []):
        sources.append(rel)
    return sources


def main() -> None:
    parser = argparse.ArgumentParser(description='Print intro book sources in order')
    parser.add_argument('--manifest', default='book.toml')
    parser.add_argument(
        '--part', type=int, default=None,
        help='Emit only the Nth part (1-based) wrapped in front/backmatter',
    )
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    for rel in iter_sources(manifest_path, args.part):
        print(rel)


if __name__ == '__main__':
    main()
