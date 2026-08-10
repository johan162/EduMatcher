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
from edumatcher.msgen.generators import c as c_gen
from edumatcher.msgen.generators import markdown as md_gen
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


def build_artifacts(
    spec_root: Path,
    out_python: Path,
    out_c: Path | None = None,
    docs_reference: Path | None = None,
    docs_preamble: Path | None = None,
) -> list[Artifact]:
    """Load every spec under ``spec_root`` and render each target.

    A family contributes a C header and source only when it declares at least
    one text projection; generating an empty header for a bus-only family would
    be a file with nothing in it that ``check`` then has to keep in step.

    Returns artifacts sorted by path so the sequence is deterministic.
    """
    _transports, families = spec_mod.load_all(spec_root)
    artifacts: list[Artifact] = []
    if docs_reference is not None and docs_preamble is not None:
        # The reference page is an artifact like any other, which is the whole
        # point: `check` diffs it against the spec on the same code path that
        # diffs the bindings, so the documentation surface can no longer drift
        # away from the other two (design section 30).
        artifacts.append(
            Artifact(
                path=docs_reference,
                content=md_gen.render_reference(
                    families, docs_preamble.read_text(encoding="utf-8")
                ),
                label=f"{docs_reference.parent.name}/{docs_reference.name}",
            )
        )
    for family in families:
        label = _spec_label(spec_root, family.family)
        artifacts.append(
            Artifact(
                path=out_python / f"{family.family}.py",
                content=py_gen.render_family(family, label),
                label=f"{out_python.name}/{family.family}.py",
            )
        )
        has_external = any(
            m.text_encoding or m.binary_encoding for m in family.messages
        )
        if out_c is None or not has_external:
            continue
        stem = f"edumatcher_{family.family}"
        artifacts.append(
            Artifact(
                path=out_c / f"{stem}.h",
                content=c_gen.render_header(family, label),
                label=f"{out_c.name}/{stem}.h",
            )
        )
        artifacts.append(
            Artifact(
                path=out_c / f"{stem}.c",
                content=c_gen.render_source(family, label),
                label=f"{out_c.name}/{stem}.c",
            )
        )
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
