"""The generated SQLite reference must stay tied to executable schemas."""

from __future__ import annotations

import re
from pathlib import Path

from edumatcher import sqlite_schema_docs
from edumatcher.sqlite_schema_docs import check, generate, render_reference

ROOT = Path(__file__).resolve().parents[1]


def test_reference_renders_all_runtime_databases_and_ddl() -> None:
    reference = render_reference()

    for filename in (
        "stats.db",
        "clearing.db",
        "log.db",
        "market_sim_news.db",
        "log-ui-acks.db",
        "audit_index.db",
        "audit_replay.db",
    ):
        assert f"## `{filename}`" in reference

    assert "CREATE VIEW gateway_pnl_totals" in reference
    assert "CREATE INDEX idx_acks_at" in reference
    assert "| `table: news_events` | `event_seq` | `INTEGER` |" in reference


def test_generate_and_check_detect_drift(tmp_path: Path) -> None:
    output = tmp_path / "sqlite-reference.md"

    assert generate(output)
    assert check(output)
    output.write_text("edited by hand\n", encoding="utf-8")
    assert not check(output)


def test_generation_cli_succeeds_when_output_is_current() -> None:
    assert sqlite_schema_docs.main(["generate"]) == 0
    assert sqlite_schema_docs.main(["check"]) == 0


def test_drift_check_is_wired_into_make_ci_and_book() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    aggregate = re.search(r"^_check:([^\n]+)", makefile, re.MULTILINE)
    assert aggregate and "dbdocs-check" in aggregate.group(1)
    assert re.search(r"^dbdocs:", makefile, re.MULTILINE)
    assert re.search(r"^dbdocs-check:", makefile, re.MULTILINE)

    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python -m edumatcher.sqlite_schema_docs check" in ci

    book = (ROOT / "docs/books/architecture-and-development/book.toml").read_text(
        encoding="utf-8"
    )
    assert '"040-sqlite-schemas.md"' in book
