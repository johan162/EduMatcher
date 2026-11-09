"""The log ledger: coverage of the source, the entries format, the scanner, the CLI.

Design: docs-design/EduMatcher-Log-Ledger.md.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import textwrap
import time
from pathlib import Path

import pytest

from edumatcher.log_cli import main as log_cli_main
from edumatcher.log_ledger import (
    CheckReport,
    LedgerError,
    check_ledger,
    load_ledger,
    parse_entries,
)
from edumatcher.log_ledger.scan import CallSite, scan_package
from edumatcher.log_srv.schema import open_db
from edumatcher.logclient.handler import TcpLogHandler
from edumatcher.logclient.protocol import FrameReader, iso_utc, template_id

#: Packages whose entries are not written yet (content WPs L4-L8). Each
#: content WP removes its packages; L8 deletes this set and the gap check
#: becomes a hard failure for everything.
PENDING_PACKAGES = frozenset(
    {
        # L5
        "alf_gwy", "balf_gwy", "api_gateway", "md_gateway", "dc_gateway",
        "ralf_gateway", "calf_client", "ralf_spy", "dc_spy",
        # L6
        "alf_console", "clearing", "audit", "stats",
        # L7
        "ai_trader", "mm_bot", "market_sim", "index", "viewer",
        # L8
        "monitor", "scheduler", "health", "healthcheck", "config_artifact",
    }
)  # fmt: skip


# ---------------------------------------------------------------------------
# The shipped ledger against the source
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def report() -> CheckReport:
    return check_ledger(load_ledger())


def test_every_call_site_outside_pending_packages_has_an_entry(
    report: CheckReport,
) -> None:
    missing = [s for s in report.missing if s.package not in PENDING_PACKAGES]
    assert not missing, "\n".join(
        f"{s.where} {s.logger}: {s.template!r}" for s in missing
    )


def test_pending_packages_still_have_gaps(report: CheckReport) -> None:
    """A finished package must leave PENDING_PACKAGES, so the gate closes on it."""
    done = PENDING_PACKAGES - {s.package for s in report.missing}
    assert not done, f"complete, remove from PENDING_PACKAGES: {sorted(done)}"


def test_no_stale_entries(report: CheckReport) -> None:
    assert not report.stale, [f"{e.logger}: {e.template!r}" for e in report.stale]


def test_entry_levels_match_the_code(report: CheckReport) -> None:
    assert not report.level_mismatch


def test_every_warning_call_site_is_understood(report: CheckReport) -> None:
    assert not report.problems, [f"{s.where}: {s.problem}" for s in report.problems]


def test_the_log_client_stamps_the_entry_key_on_a_real_record(tmp_path: Path) -> None:
    """The handler's TPL and the ledger's key are the same function of a call."""
    entry = next(iter(load_ledger().values()))
    handler = TcpLogHandler("127.0.0.1", 1, "pm-test", failover_dir=tmp_path)
    try:
        record = logging.LogRecord(
            entry.logger, logging.WARNING, __file__, 1, entry.template, None, None
        )
        reader = FrameReader()
        reader.feed(handler._build_log_frame(record))
        frame = reader.next_frame()
    finally:
        handler.close()
    assert frame is not None
    assert frame.fields["TPL"] == entry.tpl


# ---------------------------------------------------------------------------
# Entries format
# ---------------------------------------------------------------------------

_GOOD = """
- logger: edumatcher.x
  template: "slow %s"
  level: WARNING
  explanation: >
    Something is
    slow.
  actions:
    - "Wait."
"""


def test_entries_parse_and_are_keyed_by_template_id() -> None:
    ledger = parse_entries({"x.yaml": _GOOD})
    tpl = template_id("edumatcher.x", "slow %s")
    assert list(ledger) == [tpl]
    assert ledger[tpl].explanation == "Something is slow."
    assert ledger[tpl].actions == ("Wait.",)


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (("level: WARNING", "level: INFO"), "level must be one of"),
        (('    - "Wait."', "    []"), "actions must be"),
        (
            ('    - "Wait."', '    - "a"\n    - "b"\n    - "c"\n    - "d"\n    - "e"'),
            "1-4",
        ),
        (("  level: WARNING\n", ""), "missing \\['level'\\]"),
        (
            ("  level: WARNING\n", "  level: WARNING\n  owner: me\n"),
            "unknown \\['owner'\\]",
        ),
        (('    - "Wait."', "    - Run: it"), "actions must be"),
    ],
)
def test_malformed_entries_are_rejected(change: tuple[str, str], error: str) -> None:
    with pytest.raises(LedgerError, match=error):
        parse_entries({"x.yaml": _GOOD.replace(*change)})


def test_a_duplicate_entry_is_rejected() -> None:
    with pytest.raises(LedgerError, match="duplicate of an entry in a.yaml"):
        parse_entries({"a.yaml": _GOOD, "b.yaml": _GOOD})


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _scan(tmp_path: Path, source: str, name: str = "mod.py") -> list[CallSite]:
    pkg = tmp_path / "edumatcher"
    pkg.mkdir(exist_ok=True)
    (pkg / name).write_text(textwrap.dedent(source))
    return scan_package(pkg)


def test_scanner_finds_templates_and_levels(tmp_path: Path) -> None:
    sites = _scan(
        tmp_path,
        """
        import logging
        log = logging.getLogger(__name__)
        LEVELS = {"OK": logging.INFO, "BAD": logging.ERROR}

        def f(parser, x, lost):
            log.info("fine %s", x)
            log.warning("slow %s", x)
            log.exception("boom")
            log.log(logging.WARNING if lost else logging.INFO, "lost %d", x)
            log.log(LEVELS[x], "state %s", x)
            log.log(logging.DEBUG, "quiet")
            parser.error("not a log call")
        """,
    )
    found = {(s.template, s.level, s.logger) for s in sites}
    assert found == {
        ("slow %s", "WARNING", "edumatcher.mod"),
        ("boom", "ERROR", "edumatcher.mod"),
        ("lost %d", "WARNING", "edumatcher.mod"),
        ("state %s", "ERROR", "edumatcher.mod"),
    }
    assert not any(s.problem for s in sites)


def test_scanner_reports_what_it_cannot_resolve(tmp_path: Path) -> None:
    sites = _scan(
        tmp_path,
        """
        import logging
        log = logging.getLogger("edumatcher.named")

        def f(msg, level):
            log.warning(msg)
            log.error(f"x {msg}")
            log.log(level, "dynamic level")

        def g(log):
            log.warning("whose logger?")
        """,
    )
    problems = sorted((s.line, s.problem) for s in sites)
    assert problems == [
        (6, "template is not a string literal"),
        (7, "template is not a string literal"),
        (8, "level expression not understood"),
        (11, "logger 'log' is shadowed by a local name"),
    ]


def test_scanner_reads_templates_at_relay_feeders(tmp_path: Path) -> None:
    """board.main's startup warnings: the template is in warnings.append()."""
    pkg = tmp_path / "edumatcher" / "board"
    pkg.mkdir(parents=True)
    sites = _scan(
        tmp_path,
        """
        import logging
        log = logging.getLogger(__name__)

        def collect(warnings, path):
            warnings.append(("engine config not found at %s", (path,)))

        def _log_startup_warnings(warnings):
            for template, args in warnings:
                log.warning(template, *args)
        """,
        name="board/main.py",
    )
    assert [(s.template, s.level, s.logger, s.problem) for s in sites] == [
        ("engine config not found at %s", "WARNING", "edumatcher.board.main", None)
    ]


# ---------------------------------------------------------------------------
# pm-log-cli
# ---------------------------------------------------------------------------


def _run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-log-cli", *argv])
    log_cli_main.main()


@pytest.fixture
def log_db(tmp_path: Path) -> Path:
    """Rows 1-3: WARNING with a ledger entry, WARNING without one, INFO."""
    entry = next(iter(load_ledger().values()))
    db = tmp_path / "log.db"
    conn: sqlite3.Connection = open_db(db)
    now = iso_utc(time.time())
    for level, logger, message, tpl in (
        ("WARNING", entry.logger, "known trouble", entry.tpl),
        ("WARNING", "edumatcher.x", "unknown trouble", "0123456789ab"),
        ("INFO", "edumatcher.x", "all fine", None),
    ):
        conn.execute(
            "INSERT INTO log_events (client_ts, server_ts, process, pid, host, session,"
            " level, logger, message, tpl) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (now, now, "pm-x", 1, "h", "s1", level, logger, message, tpl),
        )
    conn.commit()
    conn.close()
    return db


def test_explain_prints_the_entry(
    log_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = next(iter(load_ledger().values()))
    _run(monkeypatch, "--db", str(log_db), "explain", "1")
    out = capsys.readouterr().out
    assert "known trouble" in out
    assert "Explanation:" in out
    assert entry.explanation.split()[0] in out
    assert "  1. " in out


@pytest.mark.parametrize(
    ("seq", "expected"),
    [
        ("2", "No ledger entry for this message (tpl=0123456789ab)."),
        ("3", "WARNING and above only; this row is INFO."),
    ],
)
def test_explain_without_an_entry(
    log_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    seq: str,
    expected: str,
) -> None:
    _run(monkeypatch, "--db", str(log_db), "explain", seq)
    assert expected in capsys.readouterr().out


def test_explain_json_and_unknown_seq(
    log_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, "--db", str(log_db), "explain", "1", "--format", "json")
    row = json.loads(capsys.readouterr().out)
    assert row["seq"] == 1
    assert row["explain"]["actions"]

    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, "--db", str(log_db), "explain", "99")
    assert excinfo.value.code == 1


def test_query_explain_adds_explanations_under_known_rows(
    log_db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = next(iter(load_ledger().values()))
    _run(monkeypatch, "--db", str(log_db), "query", "--explain")
    out = capsys.readouterr().out
    assert out.count("    1. ") == 1
    assert entry.actions[0].split()[0] in out

    _run(monkeypatch, "--db", str(log_db), "query", "--explain", "--format", "json")
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [("explain" in r) for r in rows] == [True, False, False]


def test_ledger_commands_need_no_log_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = load_ledger()
    entry = next(iter(ledger.values()))
    nowhere = str(tmp_path / "missing.db")

    _run(monkeypatch, "--db", nowhere, "ledger", "export")
    exported = json.loads(capsys.readouterr().out)
    assert set(exported) == set(ledger)
    assert exported[entry.tpl]["actions"] == list(entry.actions)

    _run(monkeypatch, "--db", nowhere, "ledger", "show", entry.tpl)
    shown = capsys.readouterr().out
    assert entry.template in shown
    assert "Explanation:" in shown and "\nActions:\n  1. " in shown

    _run(monkeypatch, "ledger", "list", "--logger", entry.logger, "--format", "json")
    listed = json.loads(capsys.readouterr().out)
    assert listed and all(e["logger"].startswith(entry.logger) for e in listed)

    _run(monkeypatch, "ledger", "check", "--package", "log_srv")
    assert "ledger check: OK" in capsys.readouterr().out

    # An empty ledger: every call site is missing, whatever content exists.
    monkeypatch.setattr(log_cli_main, "load_ledger", lambda: {})
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, "ledger", "check")
    assert excinfo.value.code == 1
    assert "MISSING  engine:" in capsys.readouterr().out


def test_ledger_list_and_check_output_formats(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, "ledger", "list", "--level", "critical")
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("tpl ")
    assert "refusing to start: %s" in out

    _run(monkeypatch, "ledger", "list", "--logger", "edumatcher.nowhere")
    assert capsys.readouterr().out == "No ledger entries match.\n"

    monkeypatch.setattr(log_cli_main, "load_ledger", lambda: {})
    with pytest.raises(SystemExit):
        _run(monkeypatch, "ledger", "check", "--format", "json")
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert {"stale", "level_mismatch", "problems"} <= set(report)
    assert any(m["where"].startswith("edumatcher/engine/") for m in report["missing"])
    assert {g["template"] for g in report["generic"]} >= {"%s"}


def test_ledger_show_unknown_tpl_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, "ledger", "show", "ffffffffffff")
    assert excinfo.value.code == 1
