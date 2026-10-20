"""Every documentation page that lists the web GUIs lists all of them (E2.5).

A page naming three or more of the GUIs' ports is a list of the GUIs, and
must include the Operator Dashboard's 8095; a port range ending at 8094 is a
list that stopped before it. Read as text, like tests/test_docs_monitor_config.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BOOKS = Path(__file__).resolve().parents[1] / "docs" / "books"
PAGES = sorted(BOOKS.rglob("*.md"))
GUI_PORTS = {"8090", "8091", "8092", "8093", "8094"}


def test_there_are_pages() -> None:
    assert len(PAGES) > 50


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(BOOKS)))
def test_a_page_listing_the_guis_lists_the_dashboard(page: Path) -> None:
    text = page.read_text(encoding="utf-8")
    assert not re.search(
        r"8090\s*[–-]\s*8094", text
    ), "a GUI port range that ends before 8095"
    named = {port for port in GUI_PORTS if re.search(rf"\b{port}\b", text)}
    if len(named) >= 3:
        assert re.search(
            r"\b8095\b", text
        ), f"lists GUI ports {sorted(named)} but not 8095"
