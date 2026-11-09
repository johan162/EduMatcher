"""The log ledger key on a real exchange: runtime tpl == the scanner's key.

The ``mini`` exchange runs real processes logging through the real log
client into a real pm-log-srv. Every WARNING+ row they log must carry a
``tpl``, that ``tpl`` must be the key the call-site scanner derives from the
source (so ``pm-log-cli ledger check`` and the rows agree), and
``pm-log-cli explain`` must read it (docs-design/EduMatcher-Log-Ledger.md).

End-to-end: runs only with ``-m e2e`` (``make test-e2e``).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections.abc import Iterator
from typing import Any

import pytest

from edumatcher.log_ledger import load_ledger
from edumatcher.log_ledger.scan import scan_package
from edumatcher.logclient.protocol import template_id
from tests.e2e_exchange import Exchange, running_exchange

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals"),
]


@pytest.fixture(scope="module")
def exchange(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Exchange]:
    with running_exchange(request, tmp_path_factory) as ex:
        yield ex


def _rows(exchange: Exchange, where: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{exchange.data_dir / 'log.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT seq, level, logger, tpl, message FROM log_events WHERE {where}"
            )
        ]
    finally:
        conn.close()


@pytest.fixture(scope="module")
def warnings(exchange: Exchange) -> list[dict[str, Any]]:
    """WARNING+ rows; the scheduler logs some at every start of ``mini``."""
    deadline = time.monotonic() + 30
    while True:
        rows = _rows(exchange, "level IN ('WARNING', 'ERROR', 'CRITICAL')")
        if rows or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    assert rows, "the mini exchange logged no WARNING+ row within 30 s"
    return rows


def test_warning_rows_carry_the_scanned_call_site_key(
    exchange: Exchange, warnings: list[dict[str, Any]]
) -> None:
    scanned = {
        template_id(s.logger, s.template)
        for s in scan_package()
        if s.logger is not None and s.template is not None
    }
    assert all(r["tpl"] in scanned for r in warnings), warnings
    assert not _rows(exchange, "level IN ('DEBUG', 'INFO') AND tpl IS NOT NULL")


def test_explain_reads_a_real_row(
    exchange: Exchange, warnings: list[dict[str, Any]]
) -> None:
    row = warnings[0]
    entry = load_ledger().get(row["tpl"])

    out = exchange.cli("pm-log-cli", "explain", str(row["seq"]))
    assert row["message"].splitlines()[0] in out
    if entry is None:
        assert f"No ledger entry for this message (tpl={row['tpl']})." in out
    else:
        assert "Explanation:" in out

    explained = json.loads(
        exchange.cli("pm-log-cli", "--format", "json", "explain", str(row["seq"]))
    )
    assert explained["tpl"] == row["tpl"]
    assert (explained["explain"] is None) == (entry is None)
