"""Which configuration file pm-new-symbol edits, and whether it is deployed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edumatcher.config import COMPILED_CONFIG_FILE, ENGINE_CONFIG_FILE
from edumatcher.config_artifact import load_compiled_config, source_digest
from edumatcher.config_deploy import examples_root


@dataclass(frozen=True)
class Target:
    source: Path
    deploys: bool
    #: The compiled artifact a deploy installs. COMPILED_CONFIG_FILE is read
    #: here and nowhere else in the package.
    artifact: Path


def resolve_target(config: Path | None) -> Target:
    deployed = load_compiled_config(COMPILED_CONFIG_FILE)
    if config is None:
        if deployed is None:
            raise ValueError(
                f"no configuration is deployed at {COMPILED_CONFIG_FILE}; "
                "name the file to edit with --config"
            )
        config = Path(deployed.meta.source_path)
    source = config.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"no such configuration file: {source}")
    if source.is_relative_to(examples_root().resolve()):
        raise ValueError(
            f"{source} is a bundled example and is never edited; copy it, "
            "deploy the copy, and list the symbol there"
        )
    if deployed is None:
        return Target(source, False, COMPILED_CONFIG_FILE)

    deployed_source = Path(deployed.meta.source_path).expanduser().resolve()
    if source != deployed_source:
        deployed_copy = COMPILED_CONFIG_FILE.with_name(ENGINE_CONFIG_FILE.name)
        if source == deployed_copy.resolve():
            raise ValueError(
                f"{source} is only the deployed copy of {deployed_source}; "
                "edit that file, or its next deploy would drop the symbol"
            )
        return Target(source, False, COMPILED_CONFIG_FILE)
    if source_digest(source.read_text(encoding="utf-8")) != (
        deployed.meta.source_sha256
    ):
        raise ValueError(
            f"{source} has edits that were never deployed; deploy or revert "
            "them first so the listing does not ship them unreviewed"
        )
    return Target(source, True, COMPILED_CONFIG_FILE)
