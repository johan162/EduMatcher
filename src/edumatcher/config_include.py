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

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any

import yaml

from edumatcher.config import COMPILED_CONFIG_FILE, ENGINE_CONFIG_FILE
from edumatcher.market_sim.config import FILE_NAME as SIM_FILE_NAME

INCLUDE_KEY = "include"


CREDENTIALS_FILE_KEY = "credentials_file"

_LOCATION = re.compile(r"^(\w+)(?:\[(\d+)\])?")

#: Names pm-config-deploy writes beside the artifact. A top-level include or
#: credentials file with one of them would be overwritten by, or overwrite,
#: that file when installed.
_RESERVED_NAMES = frozenset(
    {ENGINE_CONFIG_FILE.name, COMPILED_CONFIG_FILE.name, SIM_FILE_NAME}
)
_CREDENTIALS_LOCATION = re.compile(r"^api_gateways\.([^.\[]+)\.credentials\b")


class ConfigIncludeError(ValueError):
    """The config or one of its included files cannot be loaded or merged."""


@dataclass(frozen=True)
class LoadedConfig:
    data: dict[str, Any]
    #: The main file first, then each include in the order listed.
    files: tuple[Path, ...]
    #: Which file first supplied each top-level key.
    key_files: dict[str, Path] = field(default_factory=dict)
    #: Which file supplied each list element ``(key, index)`` and each mapping
    #: entry ``(key, name)`` of a top-level list or mapping.
    entry_files: dict[tuple[str, str | int], Path] = field(default_factory=dict)
    #: The ``credentials_file`` that supplied each API gateway's credentials.
    credential_files: dict[str, Path] = field(default_factory=dict)

    def origin_of(self, location: str) -> Path | None:
        """The file a finding's ``symbols.AAPL.x`` / ``participants[3]`` is from."""
        creds = _CREDENTIALS_LOCATION.match(location)
        if creds is not None and creds.group(1) in self.credential_files:
            return self.credential_files[creds.group(1)]
        match = _LOCATION.match(location)
        if match is None:
            return None
        key, index = match.groups()
        if index is not None and (key, int(index)) in self.entry_files:
            return self.entry_files[(key, int(index))]
        rest = location[match.end() :]
        if index is None and rest.startswith("."):
            # A name may itself contain dots (symbol BRK.B): longest match wins.
            parts = rest[1:].split(".")
            for n in range(len(parts), 0, -1):
                name = ".".join(parts[:n])
                if (key, name) in self.entry_files:
                    return self.entry_files[(key, name)]
        return self.key_files.get(key)


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
        target = _relative_file(main, entry, "include")
        _refuse_reserved(main, target)
        if any(target.resolve() == p.resolve() for p in paths):
            raise ConfigIncludeError(f"{main}: include '{entry}' is listed twice")
        paths.append(target)
    return paths


def _relative_file(owner: Path, entry: str, what: str) -> Path:
    """The file *entry* names, relative to the file *owner* that lists it."""
    rel = PurePath(entry)
    if rel.is_absolute() or ".." in rel.parts:
        raise ConfigIncludeError(
            f"{owner}: {what} '{entry}' must be a relative path without '..'"
        )
    target = owner.parent / rel
    if not target.is_file():
        raise ConfigIncludeError(f"{owner}: {what} file not found: {target}")
    return target


def _refuse_reserved(main: Path, target: Path) -> None:
    name = target.relative_to(main.parent).as_posix()
    if name in _RESERVED_NAMES:
        raise ConfigIncludeError(
            f"{main}: '{name}' is a reserved name (pm-config-deploy installs "
            "its own file there); rename it or move it into a subdirectory"
        )


def _record_entries(
    entries: dict[tuple[str, str | int], Path],
    key: str,
    value: Any,
    path: Path,
    offset: int = 0,
) -> None:
    if isinstance(value, list):
        for i in range(len(value)):
            entries[(key, offset + i)] = path
    elif isinstance(value, dict):
        for name in value:
            entries[(key, str(name))] = path


def _merge(
    merged: dict[str, Any],
    origin: dict[str, Path],
    entries: dict[tuple[str, str | int], Path],
    extra: dict[str, Any],
    path: Path,
) -> None:
    for key, value in extra.items():
        if key not in merged:
            merged[key] = value
            origin[key] = path
            _record_entries(entries, key, value, path)
            continue
        have = merged[key]
        if isinstance(have, list) and isinstance(value, list):
            _record_entries(entries, key, value, path, offset=len(have))
            merged[key] = have + value
        elif isinstance(have, dict) and isinstance(value, dict):
            clash = sorted(set(have) & set(value), key=str)
            if clash:
                raise ConfigIncludeError(
                    f"{path}: '{key}.{clash[0]}' is already defined in {origin[key]}"
                )
            _record_entries(entries, key, value, path)
            merged[key] = {**have, **value}
        else:
            raise ConfigIncludeError(
                f"{path}: '{key}' is already defined in {origin[key]} and cannot "
                "be merged (only lists and mappings merge)"
            )


def _read_credentials(path: Path) -> list[Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigIncludeError(f"{path}: cannot read: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise ConfigIncludeError(f"{path}: not valid YAML: {exc}") from exc
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigIncludeError(
            f"{path}: must be a YAML list of credentials, got {type(raw).__name__}"
        )
    return raw


def _resolve_credentials_files(
    merged: dict[str, Any], entries: dict[tuple[str, str | int], Path], main: Path
) -> dict[str, Path]:
    """Replace each API gateway's ``credentials_file`` by its ``credentials``."""
    gateways = merged.get("api_gateways")
    if not isinstance(gateways, dict):
        return {}
    resolved: dict[str, Path] = {}
    for name, block in gateways.items():
        if not isinstance(block, dict) or CREDENTIALS_FILE_KEY not in block:
            continue
        owner = entries.get(("api_gateways", str(name)), main)
        where = f"api_gateways.{name}"
        entry = block.pop(CREDENTIALS_FILE_KEY)
        if not isinstance(entry, str):
            raise ConfigIncludeError(
                f"{owner}: {where}.credentials_file must be a name"
            )
        if "credentials" in block:
            raise ConfigIncludeError(
                f"{owner}: {where} has both 'credentials' and 'credentials_file'"
            )
        target = _relative_file(owner, entry, f"{where}.credentials_file")
        _refuse_reserved(main, target)
        block["credentials"] = _read_credentials(target)
        resolved[str(name)] = target
    return resolved


def load_config_mapping(path: Path) -> LoadedConfig:
    """Parse *path*, resolve its ``include:`` list and return the merged mapping."""
    main_raw = _read_mapping(path)
    includes = _include_paths(path, main_raw)
    merged = {k: v for k, v in main_raw.items() if k != INCLUDE_KEY}
    origin = {k: path for k in merged}
    entries: dict[tuple[str, str | int], Path] = {}
    for key, value in merged.items():
        _record_entries(entries, key, value, path)
    for included in includes:
        extra = _read_mapping(included)
        if INCLUDE_KEY in extra:
            raise ConfigIncludeError(
                f"{included}: includes cannot be nested; list every file in {path}"
            )
        _merge(merged, origin, entries, extra, included)
    credential_files = _resolve_credentials_files(merged, entries, path)
    files = (path, *includes, *dict.fromkeys(credential_files.values()))
    return LoadedConfig(
        data=merged,
        files=files,
        key_files=origin,
        entry_files=entries,
        credential_files=credential_files,
    )
