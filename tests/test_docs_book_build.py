"""Book manifests: sources (book_sources.py) and site navigation (gen_nav.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

BUILD = Path(__file__).resolve().parents[1] / "docs" / "build"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, BUILD / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


book_sources = load("book_sources")
gen_nav = load("gen_nav")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    """Two books; ``sim`` includes one chapter of ``guide``."""
    write(tmp_path / "books/guide/part-1/010-bots.md", "# Bots\n")
    write(
        tmp_path / "books/guide/book.toml",
        'title = "Guide"\n[[parts]]\ntitle = "P1"\ndir = "part-1"\n'
        'files = ["010-bots.md"]\n',
    )
    write(tmp_path / "books/sim/part-1/010-intro.md", "# Intro\n")
    write(
        tmp_path / "books/sim/book.toml",
        'title = "Sim"\n[[parts]]\ntitle = "P1"\ndir = "part-1"\n'
        'files = ["010-intro.md", "../../guide/part-1/010-bots.md"]\n',
    )
    return tmp_path


def test_sources_normalise_a_chapter_from_another_book(docs: Path) -> None:
    paths = book_sources.sources(docs / "books/sim/book.toml")
    assert paths == [
        str(docs / "books/sim/part-1/010-intro.md"),
        str(docs / "books/guide/part-1/010-bots.md"),
    ]


def test_sources_refuse_a_missing_file(docs: Path) -> None:
    manifest = docs / "books/sim/book.toml"
    manifest.write_text(manifest.read_text().replace("010-intro.md", "011-gone.md", 1))
    with pytest.raises(SystemExit, match="no such file"):
        book_sources.sources(manifest)


def test_sources_refuse_a_duplicate_basename(docs: Path) -> None:
    write(docs / "books/sim/part-1/010-bots.md", "# Local bots\n")
    manifest = docs / "books/sim/book.toml"
    manifest.write_text(
        manifest.read_text().replace('"010-intro.md"', '"010-bots.md"', 1)
    )
    with pytest.raises(SystemExit, match="used twice"):
        book_sources.sources(manifest)


def test_nav_links_a_shared_chapter_by_url(docs: Path) -> None:
    # The shared page stays in its own book's nav: MkDocs would otherwise
    # file it under the last book that lists it.
    assert gen_nav.book_nav(docs, docs / "books/sim/book.toml") == [
        '  - "Sim":',
        '    - "P1":',
        '      - "Intro": books/sim/part-1/010-intro.md',
        '      - "Bots": books/guide/part-1/010-bots/',
    ]
    assert gen_nav.book_nav(docs, docs / "books/guide/book.toml")[-1] == (
        '      - "Bots": books/guide/part-1/010-bots.md'
    )
