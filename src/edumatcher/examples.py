"""The bundled example configurations, found without importing anything else.

``pm-setup`` resolves ``--config`` before it creates the data directory;
importing ``edumatcher.config_deploy`` for this would import
``edumatcher.config``, which resolves the not-yet-existing directory and
warns about it. ``config_deploy`` re-exports both functions.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# --example resolution
# ---------------------------------------------------------------------------
# docs/examples/ref_data/<book-count>-book(s)-<profile>-setup/engine_config.yaml
# is shipped both in the source tree and, alongside the installed package, in
# the wheel (see pyproject.toml's [tool.poetry.include]). The two layouts
# differ by one directory level: in a source checkout "docs/" is a sibling of
# "src/" (repo root), but a wheel install has no "src/" layer, so "docs/"
# lands as a sibling of the "edumatcher" package directory itself. This mirrors
# edumatcher.data_dir's own source-tree detection (this file lives in the same
# "src/edumatcher/" directory that module's _IN_SOURCE_TREE check is based on).
_EXAMPLE_PREFIXES = {
    "s1": "s1",
    "s3": "s3",
    "s10": "s10",
    "s30": "s30",
    "s150": "s150",
}
_EXAMPLE_PROFILES = ("basic", "nominal", "complex")
#: Examples outside the count x profile grid, by shorthand -> folder.
_STANDALONE_EXAMPLES = {
    "s300-load": "s300-load-setup",
    "s300-sim": "s300-sim-setup",
}


def examples_root() -> Path:
    pkg_dir = Path(__file__).parent  # .../edumatcher/
    src_dir = pkg_dir.parent  # .../src/  (source) or site-packages (installed)
    base = src_dir.parent if src_dir.name == "src" else src_dir
    return base / "docs" / "examples" / "ref_data"


def resolve_example(name: str) -> Path:
    """Resolve an ``--example`` shorthand (e.g. ``s3-basic``) to its YAML.

    An optional trailing ``-nomm`` selects the no-market-maker-quotes variant
    of the same example (e.g. ``s3-basic-nomm`` ->
    ``docs/examples/ref_data/s3-basic-nomm-setup/engine_config.yaml``)
    — see ../../docs/books/participant-guide/part-3-market-making/010-market-maker-quotes.md.

    Raises ``ValueError`` with the available names when *name* is not one of
    the bundled examples.
    """
    standalone = _STANDALONE_EXAMPLES.get(name)
    if standalone is not None:
        path = examples_root() / standalone / "engine_config.yaml"
        if not path.is_file():
            raise ValueError(f"Example {name!r} not found (expected {path})")
        return path

    base = name
    nomm = False
    if base.endswith("-nomm"):
        nomm = True
        base = base[: -len("-nomm")]

    count, _, profile = base.partition("-")
    prefix = _EXAMPLE_PREFIXES.get(count)
    if prefix is None or profile not in _EXAMPLE_PROFILES:
        available = ", ".join(
            [
                f"{count}-{profile}{suffix}"
                for count in _EXAMPLE_PREFIXES
                for profile in _EXAMPLE_PROFILES
                for suffix in ("", "-nomm")
            ]
            + list(_STANDALONE_EXAMPLES)
        )
        raise ValueError(f"Unknown example {name!r}. Available: {available}")

    nomm_suffix = "-nomm" if nomm else ""
    path = (
        examples_root()
        / f"{prefix}-{profile}{nomm_suffix}-setup"
        / "engine_config.yaml"
    )
    if not path.is_file():
        raise ValueError(f"Example {name!r} not found (expected {path})")
    return path
