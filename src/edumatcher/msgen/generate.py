"""Orchestration: load the spec, render each target, write or diff.

``generate`` writes; ``check`` renders to memory and compares against what is
committed. Both walk the same code path, which is what makes the check
meaningful — see design section 7.2.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from edumatcher.msgen import spec as spec_mod
from edumatcher.msgen.generators import python as py_gen


@dataclass(frozen=True)
class Artifact:
    """One generated file: where it belongs and what it should contain."""

    path: Path
    content: str
    #: Repo-relative label used in messages, so output is machine-independent.
    label: str


def _spec_label(spec_root: Path, family_name: str) -> str:
    """Return the repo-relative spec label baked into the generated banner.

    Constructed rather than derived from the absolute path: the banner is
    diffed by ``pm-msgen check``, so it must be identical on every machine
    (design section B.17).
    """
    return f"{spec_root.name}/messages/{family_name}.yaml"


def build_artifacts(spec_root: Path, out_python: Path) -> list[Artifact]:
    """Load every spec under ``spec_root`` and render the Python target.

    Returns artifacts sorted by path so the sequence is deterministic.
    """
    _transports, families = spec_mod.load_all(spec_root)
    artifacts = [
        Artifact(
            path=out_python / f"{family.family}.py",
            content=py_gen.render_family(family, _spec_label(spec_root, family.family)),
            label=f"{out_python.name}/{family.family}.py",
        )
        for family in families
    ]
    return sorted(artifacts, key=lambda a: a.path.as_posix())


def write(artifacts: list[Artifact]) -> list[Artifact]:
    """Write every artifact whose on-disk content differs. Returns those written."""
    changed: list[Artifact] = []
    for art in artifacts:
        art.path.parent.mkdir(parents=True, exist_ok=True)
        current = art.path.read_text(encoding="utf-8") if art.path.exists() else None
        if current != art.content:
            art.path.write_text(art.content, encoding="utf-8")
            changed.append(art)
    return changed


def diff(artifacts: list[Artifact]) -> list[str]:
    """Return a unified diff per artifact that differs from what is committed.

    An empty list means the committed output matches the spec — which is the
    only thing ``pm-msgen check`` asserts, and the property that keeps the
    surfaces aligned (design section 7.2).
    """
    out: list[str] = []
    for art in artifacts:
        expected = art.content
        if not art.path.exists():
            out.append(f"{art.label}: missing - run `pm-msgen generate`")
            continue
        actual = art.path.read_text(encoding="utf-8")
        if actual == expected:
            continue
        delta = difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=f"{art.label} (committed)",
            tofile=f"{art.label} (from spec)",
        )
        out.append("".join(delta))
    return out
