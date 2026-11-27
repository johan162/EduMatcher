"""Every documentation page that lists the web GUIs lists all of them (E2.5).

A page naming three or more of the GUIs' ports is a list of the GUIs, and
must include the newest ones: the Operator Dashboard's 8095 and the Audit
GUI's 8097 (Audit GUI AG7). A port range ending before 8097 is a list that
stopped before them. Read as text, like tests/test_docs_monitor_config.py.
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
        r"8090\s*[–-]\s*809[0-6]\b", text
    ), "a GUI port range that ends before 8097"
    named = {port for port in GUI_PORTS if re.search(rf"\b{port}\b", text)}
    if len(named) >= 3:
        for newest in ("8095", "8097"):
            assert re.search(
                rf"\b{newest}\b", text
            ), f"lists GUI ports {sorted(named)} but not {newest}"
