"""``edumatcher.systest`` must be importable with only production deps.

Requirement 1.3 promises that ``pm-systest`` runs on the fixed-state test VM
without installing anything from the project's ``dev`` or ``docs``
dependency groups. Two failure modes would break that promise silently:

  * a module under ``systest/`` that fails to import at all (a typo, a
    missing ``__init__.py``, a broken relative import), and
  * a module that imports cleanly today but reaches for a package that only
    exists because ``pytest``, ``mkdocs``, or another dev/docs-only tool
    happens to be on the developer's ``sys.path``.

The second case is checked statically (parsing each module's top-level
imports and cross-referencing them against the dev/docs group package names
declared in ``pyproject.toml``) rather than via a runtime ``sys.modules``
diff: the test process itself already has many dev-group packages (pytest
included) loaded before any systest module is touched, so a diff would flag
every module as guilty regardless of what it actually imports.

``invariants.py`` is excluded: it is created by task 2, not task 1, and does
not exist yet.
"""

from __future__ import annotations

import ast
import importlib
import importlib.metadata as metadata
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
SYSTEST_ROOT = SRC_ROOT / "edumatcher" / "systest"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: Created by task 2 (the shared invariant library); does not exist yet.
_NOT_YET_IMPLEMENTED = {"invariants.py"}


def _dev_and_docs_group_package_names() -> set[str]:
    """Distribution names declared in the ``dev``/``docs`` poetry groups."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    groups = data["tool"]["poetry"]["group"]
    names: set[str] = set()
    for group_name in ("dev", "docs"):
        names.update(groups[group_name]["dependencies"].keys())
    return names


def _top_level_import_names(dist_name: str) -> set[str]:
    """Top-level importable names an installed distribution provides.

    Derived from the distribution's installed file manifest rather than a
    hand-maintained mapping, since several dev/docs packages install under a
    name that differs from their PyPI/poetry name (``mkdocs-material`` ->
    ``material``, ``types-PyYAML`` -> ``yaml-stubs``, and so on).
    """
    try:
        dist = metadata.distribution(dist_name)
    except metadata.PackageNotFoundError:
        return set()
    names: set[str] = set()
    for file in dist.files or []:
        parts = file.parts
        if not parts:
            continue
        top = parts[0]
        if top == ".." or top.endswith(".dist-info") or top.endswith(".egg-info"):
            continue
        names.add(top.split("/")[0].removesuffix(".py"))
    return names


def _dev_and_docs_import_names() -> set[str]:
    names: set[str] = set()
    for dist_name in _dev_and_docs_group_package_names():
        names.update(_top_level_import_names(dist_name))
    return names


def _systest_module_paths() -> list[Path]:
    paths = [
        path
        for path in sorted(SYSTEST_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts and path.name not in _NOT_YET_IMPLEMENTED
    ]
    assert paths, "no modules found under systest/ -- has the package moved?"
    return paths


def _module_name_for(path: Path) -> str:
    rel_parts = list(path.relative_to(SRC_ROOT).with_suffix("").parts)
    if rel_parts[-1] == "__init__":
        rel_parts = rel_parts[:-1]
    return ".".join(rel_parts)


def _top_level_imports(path: Path) -> set[str]:
    """Names imported by top-level ``import``/``from`` statements in a module.

    Only top-level (module-body) statements are inspected -- a nested,
    function-local import would not run merely by importing the module,
    which is the property this test cares about.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # A relative import (``from . import x``, level > 0) always
            # targets another module inside the project, never a dev/docs
            # dependency, so only absolute imports are relevant here.
            if node.module is not None and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


_MODULE_PATHS = _systest_module_paths()
_MODULE_IDS = [str(path.relative_to(SYSTEST_ROOT)) for path in _MODULE_PATHS]


class TestSystestModulesAreImportable:
    """Requirement 1.2/1.3: every listed module path is a real, loadable module."""

    @pytest.mark.parametrize("path", _MODULE_PATHS, ids=_MODULE_IDS)
    def test_module_imports_without_error(self, path: Path) -> None:
        importlib.import_module(_module_name_for(path))


class TestSystestModulesAvoidDevAndDocsDependencies:
    """Requirement 1.3: no module reaches for a dev/docs-only package."""

    @pytest.mark.parametrize("path", _MODULE_PATHS, ids=_MODULE_IDS)
    def test_module_does_not_import_a_dev_or_docs_package(self, path: Path) -> None:
        forbidden = _dev_and_docs_import_names()
        imported = _top_level_imports(path)
        offending = imported & forbidden
        assert not offending, (
            f"{path.relative_to(SYSTEST_ROOT)} imports dev/docs-group-only "
            f"package(s) {sorted(offending)}; pm-systest must run using only "
            "the project's production dependency set"
        )
