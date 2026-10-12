"""pm-ticker's headline line (WP-E5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.console import Console
from rich.text import Text

from edumatcher.ticker.main import (  # pyright: ignore[reportPrivateUsage]
    _build_panel,
    _format_news,
)

ITEM: dict[str, Any] = {
    "id": "N7",
    "ts_ns": 1_700_000_000_000_000_000,
    "status": "RUMOUR",
    "credibility": 0.7,
    "sentiment": -0.4,
    "headline": "Rumour: MSFT probe widens",
}


def _styles(text: Text) -> set[str]:
    return {str(span.style) for span in text.spans}


def test_no_news_yet() -> None:
    assert _format_news(None, 80).plain == "no news yet"


def test_rumour_shows_credibility_and_sentiment_colour() -> None:
    text = _format_news(ITEM, 200)
    assert "[RUMOUR 70%] Rumour: MSFT probe widens" in text.plain
    assert "red" in _styles(text)


def test_retraction_is_struck_through() -> None:
    item = {**ITEM, "status": "RETRACTED", "sentiment": 0.5, "headline": "x"}
    text = _format_news(item, 200)
    assert "[RETRACTED] x" in text.plain
    assert "green strike" in _styles(text)


def test_long_headline_is_cut_to_the_box() -> None:
    text = _format_news({**ITEM, "headline": "y" * 300}, 60)
    assert text.cell_len <= 60


def test_panel_renders_the_news_line() -> None:
    panel = _build_panel(0, 0, datetime.now(), Text("tape"), _format_news(ITEM, 100))
    console = Console(width=120, record=True)
    console.print(panel)
    out = console.export_text()
    assert "tape" in out and "MSFT probe widens" in out
