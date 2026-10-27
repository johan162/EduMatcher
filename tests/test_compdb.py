"""Tests for the company database (src/edumatcher/compdb) and pm-compdb-cli."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher.compdb.cli import main
from edumatcher.compdb.store import (
    COLUMNS,
    FIELDS,
    SIM_INDUSTRY_LABELS,
    CompanyError,
    build,
    check,
    connect,
    delete,
    get,
    load_seed,
    parse_filter,
    query,
)
from edumatcher.market_sim.sectors import SECTOR_OF, industry_of

ROOT = Path(__file__).resolve().parents[1]
S300 = ROOT / "docs/examples/ref_data/s300-sim-setup"


@pytest.fixture(scope="module")
def seed() -> list[dict[str, Any]]:
    return load_seed()


@pytest.fixture
def db(tmp_path: Path, seed: list[dict[str, Any]]) -> Path:
    path = tmp_path / "companies.db"
    build(path, seed)
    return path


def _minimal(**over: Any) -> dict[str, Any]:
    return {
        "symbol": "ACME",
        "name": "Acme Rockets",
        "sector": "INDUSTRIALS",
        "industry": "Machinery",
    } | over


# --- the bundled companies -----------------------------------------------------


def test_seed_covers_the_s300_simulation_with_its_sectors(
    seed: list[dict[str, Any]],
) -> None:
    sim = yaml.safe_load((S300 / "market_sim.yaml").read_text(encoding="utf-8"))
    expected = {s: body["sector"] for s, body in sim["symbols"].items()}
    assert {r["symbol"]: r["sector"] for r in seed} == expected


def test_seed_uses_the_simulations_own_industries(
    seed: list[dict[str, Any]],
) -> None:
    sim_industries = {industry_of(s, sec) for s, sec in SECTOR_OF.items()}
    assert sim_industries - set(SECTOR_OF.values()) == set(SIM_INDUSTRY_LABELS)
    for r in seed:
        sim = industry_of(r["symbol"], r["sector"])
        if sim != r["sector"]:
            assert r["industry"] == SIM_INDUSTRY_LABELS[sim], r["symbol"]
        else:
            assert r["industry"] not in SIM_INDUSTRY_LABELS.values(), r["symbol"]


def test_seed_records_are_complete_and_distinct(seed: list[dict[str, Any]]) -> None:
    for r in seed:
        missing = [k for k, v in r.items() if v is None and k != "competitors"]
        assert not missing, (r["symbol"], missing)
    assert len({r["name"] for r in seed}) == len(seed)
    assert len({r["ceo_name"] for r in seed}) == len(seed)


def test_seed_competitors_are_other_listed_companies(
    seed: list[dict[str, Any]],
) -> None:
    symbols = {r["symbol"] for r in seed}
    for r in seed:
        for other in (r["competitors"] or "").split():
            assert other in symbols and other != r["symbol"], (r["symbol"], other)


def test_committed_database_matches_the_seed(seed: list[dict[str, Any]]) -> None:
    with closing(sqlite3.connect(S300 / "companies.db")) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(r) for r in conn.execute("SELECT * FROM companies ORDER BY symbol")
        ]
    assert rows == seed, "rebuild it: pm-compdb-cli --db <path> init --force"


# --- checking ------------------------------------------------------------------


def test_check_types_values_and_fills_missing_fields() -> None:
    rec = check(_minimal(symbol="acme", sector="industrials", founded_year="1990"))
    assert rec["symbol"] == "ACME" and rec["sector"] == "INDUSTRIALS"
    assert rec["founded_year"] == 1990
    assert set(rec) == {c.name for c in FIELDS}


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"name": ""}, "name is required"),
        ({"symbol": "TOO-LONG"}, "1-6 letters"),
        ({"sector": "SPACE"}, "sector must be one of"),
        ({"symbol": "AAPL", "sector": "ENERGY"}, "puts AAPL in TECH"),
        ({"symbol": "NVDA", "sector": "TECH"}, "industry is Semiconductors"),
        ({"industry": "Airlines"}, "kept for the companies"),
        ({"origin": "MAGIC"}, "origin must be one of"),
        ({"credit_rating": "A++"}, "credit_rating must be one of"),
        ({"founded_year": 2001, "ipo_year": 1999}, "founded_year (2001) is after"),
        ({"ceo_since": 2020, "ceo_industry_years": 1}, "shorter than the CEO"),
        ({"founded_year": 2000, "ceo_since": 1990}, "ceo_since is before"),
        ({"employees": 0}, "employees must be positive"),
        ({"revenue_musd": "lots"}, "is not a number"),
        ({"employees": 1.5}, "is not a number"),
        ({"colour": "red"}, "unknown field"),
    ],
)
def test_check_rejects(over: dict[str, Any], message: str) -> None:
    with pytest.raises(
        CompanyError, match=message.replace("(", r"\(").replace(")", r"\)")
    ):
        check(_minimal(**over))


# --- queries -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("pe_ratio<15", ("pe_ratio", "<", 15.0)),
        ("employees >= 1000", ("employees", ">=", 1000)),
        ("sector=TECH", ("sector", "=", "TECH")),
        ("purpose~cloud computing", ("purpose", "~", "cloud computing")),
        ("ipo_year~19", ("ipo_year", "~", "19")),
    ],
)
def test_parse_filter(text: str, expected: tuple[str, str, Any]) -> None:
    assert tuple(parse_filter(text)) == expected


@pytest.mark.parametrize(
    "text", ["pe_ratio", "nope=1", "name<B", "pe_ratio<", "pe_ratio<cheap"]
)
def test_parse_filter_rejects(text: str) -> None:
    with pytest.raises(CompanyError):
        parse_filter(text)


def test_query_filters_sorts_and_limits(db: Path) -> None:
    with closing(connect(db)) as conn:
        rows = query(
            conn,
            ["symbol", "pe_ratio"],
            [parse_filter("sector=tech"), parse_filter("industry~semi")],
            sort="pe_ratio",
            descending=True,
            limit=3,
        )
    assert len(rows) == 3
    pes = [r["pe_ratio"] for r in rows]
    assert pes == sorted(pes, reverse=True)


def test_query_like_treats_wildcards_literally(db: Path) -> None:
    with closing(connect(db)) as conn:
        assert query(conn, ["symbol"], [parse_filter("name~%")]) == []


def test_query_rejects_unknown_columns(db: Path) -> None:
    with closing(connect(db)) as conn, pytest.raises(CompanyError, match="no column"):
        query(conn, ["symbol", "colour"])


def test_view_derives_ratios(db: Path) -> None:
    with closing(connect(db)) as conn:
        conn.execute(
            "INSERT INTO companies (symbol, name, sector, industry, revenue_musd, "
            "net_income_musd, market_cap_musd) VALUES "
            "('XA', 'X', 'TECH', 'X', 200, 50, 1000), "
            "('XB', 'X', 'TECH', 'X', 200, -50, 1000)"
        )
        xa, xb = get(conn, "XA"), get(conn, "xb")
    assert xa is not None and xb is not None
    assert (xa["pe_ratio"], xa["ps_ratio"], xa["net_margin_pct"]) == (20.0, 5.0, 25.0)
    assert xb["pe_ratio"] is None and xb["net_margin_pct"] == -25.0


def test_readonly_connection_reads_but_cannot_write(db: Path) -> None:
    with closing(connect(db, readonly=True)) as conn:
        assert get(conn, "AAPL") is not None
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            delete(conn, "AAPL")


def test_build_refuses_to_overwrite_without_force(db: Path) -> None:
    with pytest.raises(CompanyError, match="exists"):
        build(db, [])
    build(db, [], force=True)
    with closing(connect(db)) as conn:
        assert query(conn, ["symbol"]) == []


# --- the command line ----------------------------------------------------------


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    main(list(argv))
    return capsys.readouterr().out


def test_cli_init_builds_the_bundled_companies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "sub" / "c.db"
    assert "300 companies" in _run(capsys, "--db", str(path), "init")
    with pytest.raises(SystemExit):
        main(["--db", str(path), "init"])
    assert "--force" in capsys.readouterr().err


def test_cli_init_reports_an_unwritable_location(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["--db", str(blocker / "c.db"), "init"])
    assert exc.value.code == 1
    assert "pm-compdb-cli: cannot write" in capsys.readouterr().err


def test_cli_list_table(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(
        capsys,
        "--db", str(db), "list", "-c", "symbol,name,dividend_yield_pct",
        "-w", "sector=UTILITIES", "-s", "dividend_yield_pct", "--desc", "-n", "2",
    )  # fmt: skip
    lines = out.splitlines()
    assert lines[0].split(" | ")[0].strip() == "symbol"
    assert len(lines) == 4  # header, rule, two rows


def test_cli_list_csv_and_json(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "--db", str(db), "--format", "csv", "list", "-w", "symbol=AAPL")
    assert out.splitlines()[0] == "symbol,name,sector,industry,market_cap_musd,pe_ratio"
    assert out.splitlines()[1].startswith("AAPL,")
    rows = json.loads(
        _run(
            capsys, "--db", str(db), "--format", "json", "list", "-c", "all", "-n", "1"
        )
    )
    assert list(rows[0]) == list(COLUMNS)


def test_cli_list_reports_no_match(
    db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run(capsys, "--db", str(db), "list", "-w", "employees<0")
    assert out.strip() == "No companies found."


def test_cli_show(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "--db", str(db), "show", "aapl", "MSFT")
    assert out.count("symbol ") == 2 and "pe_ratio" in out
    with pytest.raises(SystemExit):
        main(["--db", str(db), "show", "NOPE"])
    assert "NOPE is not in the database" in capsys.readouterr().err


def test_cli_add_update_delete(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = ["--db", str(db)]
    _run(capsys, *base, "add", "ACME", "name=Acme Rockets", "sector=INDUSTRIALS",
         "industry=Machinery", "employees=12")  # fmt: skip
    _run(capsys, *base, "update", "acme", "employees=40", "headquarters=")
    with closing(connect(db)) as conn:
        acme = get(conn, "ACME")
    assert acme is not None
    assert (acme["employees"], acme["headquarters"]) == (40, None)
    with pytest.raises(SystemExit):
        main([*base, "add", "ACME", "name=Again", "sector=TECH", "industry=X"])
    assert "already in the database" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main([*base, "update", "ACME", "symbol=ACM"])
    assert "cannot be changed" in capsys.readouterr().err
    assert "ACME deleted" in _run(capsys, *base, "delete", "ACME")
    with pytest.raises(SystemExit):
        main([*base, "delete", "ACME"])


def test_cli_add_rejects_bad_assignment(
    db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["--db", str(db), "add", "ACME", "name"])
    assert "FIELD=VALUE" in capsys.readouterr().err


def test_cli_import(
    db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "new.yaml"
    src.write_text(
        "ACME: {name: Acme Rockets, sector: INDUSTRIALS, industry: Machinery}\n"
        "ZZZ: {name: Zed, sector: TECH, industry: Gadgets}\n",
        encoding="utf-8",
    )
    assert "2 companies added" in _run(capsys, "--db", str(db), "import", str(src))
    # All or nothing: a clash leaves the database as it was.
    src.write_text("NEW1: {name: N, sector: TECH, industry: X}\n", encoding="utf-8")
    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "ACME: {name: A, sector: INDUSTRIALS, industry: X}\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        main(["--db", str(db), "import", str(src), str(dup)])
    with closing(connect(db)) as conn:
        assert get(conn, "NEW1") is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- AAPL\n", "a mapping of symbol to fields"),
        ("ACME: just a name\n", "fields must be a mapping"),
        ("ACME: {name: [\n", "cannot read"),
        ("ACME: {name: A, sector: TECH}\n", "industry is required"),
    ],
)
def test_cli_import_rejects_bad_files(
    db: Path,
    tmp_path: Path,
    text: str,
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "bad.yaml"
    src.write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--db", str(db), "import", str(src)])
    assert message in capsys.readouterr().err


def test_cli_import_rejects_a_symbol_listed_twice(
    db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(
            "ACME: {name: A, sector: TECH, industry: X}\n", encoding="utf-8"
        )
    with pytest.raises(SystemExit):
        main(
            [
                "--db",
                str(db),
                "import",
                str(tmp_path / "a.yaml"),
                str(tmp_path / "b.yaml"),
            ]
        )
    assert "listed twice" in capsys.readouterr().err


def test_cli_columns_marks_derived(capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "columns")
    assert "pe_ratio" in out and "(derived)" in out
    assert len(out.splitlines()) == len(COLUMNS)


@pytest.mark.parametrize(
    "argv",
    [
        ["list", "-w", "bad filter"],
        ["list", "-n", "0"],
        ["list", "-s", "colour"],
    ],
)
def test_cli_errors_exit_1(
    db: Path, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--db", str(db), *argv])
    assert exc.value.code == 1
    assert capsys.readouterr().err.startswith("pm-compdb-cli: ")


def test_cli_missing_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["--db", str(tmp_path / "none.db"), "list"])
    assert "pm-compdb-cli init" in capsys.readouterr().err
