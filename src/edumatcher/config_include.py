"""Load an authored config YAML, resolving its top-level ``include:`` list.

YAML has no include of its own, so EduMatcher defines a deliberately small one::

    include:
      - symbols.yaml
      - participants.yaml

Rules (see docs-design/EduMatcher-Config-Include-Workplan.md section 3):

  * paths are relative to the main file, never absolute, never contain ``..``;
  * one level only -- an included file may not have an ``include:`` of its own;
  * an included file is a mapping with the same top-level keys as the main file;
  * a key present in several files is merged: lists concatenate (main file
    first, then includes in order), mappings merge one level deep, anything
    else is an error. Nothing is ever silently overridden.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

import yaml

INCLUDE_KEY = "include"


class ConfigIncludeError(ValueError):
    """The config or one of its included files cannot be loaded or merged."""


@dataclass(frozen=True)
class LoadedConfig:
    data: dict[str, Any]
    #: The main file first, then each include in the order listed.
    files: tuple[Path, ...]


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigIncludeError(f"{path}: cannot read: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise ConfigIncludeError(f"{path}: not valid YAML: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigIncludeError(
            f"{path}: must be a YAML mapping, got {type(raw).__name__}"
        )
    return raw


def _include_paths(main: Path, raw: dict[str, Any]) -> list[Path]:
    entries = raw.get(INCLUDE_KEY)
    if entries is None:
        return []
    if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
        raise ConfigIncludeError(f"{main}: 'include' must be a list of file names")
    paths: list[Path] = []
    for entry in entries:
        rel = PurePath(entry)
        if rel.is_absolute() or ".." in rel.parts:
            raise ConfigIncludeError(
                f"{main}: include '{entry}' must be a relative path without '..'"
            )
        target = main.parent / rel
        if not target.is_file():
            raise ConfigIncludeError(f"{main}: included file not found: {target}")
        paths.append(target)
    return paths


def _merge(
    merged: dict[str, Any], origin: dict[str, Path], extra: dict[str, Any], path: Path
) -> None:
    for key, value in extra.items():
        if key not in merged:
            merged[key] = value
            origin[key] = path
            continue
        have = merged[key]
        if isinstance(have, list) and isinstance(value, list):
            merged[key] = have + value
        elif isinstance(have, dict) and isinstance(value, dict):
            clash = sorted(set(have) & set(value), key=str)
            if clash:
                raise ConfigIncludeError(
                    f"{path}: '{key}.{clash[0]}' is already defined in {origin[key]}"
                )
            merged[key] = {**have, **value}
        else:
            raise ConfigIncludeError(
                f"{path}: '{key}' is already defined in {origin[key]} and cannot "
                "be merged (only lists and mappings merge)"
            )


def load_config_mapping(path: Path) -> LoadedConfig:
    """Parse *path*, resolve its ``include:`` list and return the merged mapping."""
    main_raw = _read_mapping(path)
    includes = _include_paths(path, main_raw)
    merged = {k: v for k, v in main_raw.items() if k != INCLUDE_KEY}
    origin = {k: path for k in merged}
    for included in includes:
        extra = _read_mapping(included)
        if INCLUDE_KEY in extra:
            raise ConfigIncludeError(
                f"{included}: includes cannot be nested; list every file in {path}"
            )
        _merge(merged, origin, extra, included)
    return LoadedConfig(data=merged, files=(path, *includes))
