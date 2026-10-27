"""SQLite storage for the company database.

One row per company in ``companies``; the view ``company_view`` adds the
figures that follow from the stored ones (P/E, years in business, ...), so
they never disagree with them. Every query reads the view.

The bundled companies are made up: each keeps its real-world ticker and line
of business but has an invented name, people and numbers. They are written
by hand in ``companies/*.yaml``; ``build`` turns them into a database.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from edumatcher.config import DATA_DIR
from edumatcher.market_sim.sectors import PROFILES, SECTOR_OF, industry_of

COMPANIES_DB = DATA_DIR / "companies.db"
SEED_DIR = Path(__file__).resolve().parent / "companies"


class CompanyError(Exception):
    pass


class Column(NamedTuple):
    name: str
    kind: str  # TEXT, INTEGER or REAL
    description: str


ORIGINS = (
    "FOUNDER",
    "CO_FOUNDERS",
    "FAMILY",
    "MERGER",
    "SPIN_OFF",
    "PRIVATISATION",
    "COOPERATIVE",
)
RATINGS = tuple("AAA AA+ AA AA- A+ A A- BBB+ BBB BBB- BB+ BB BB- B+ B B- CCC".split())

#: The stored columns; symbol, name, sector and industry are required.
FIELDS: tuple[Column, ...] = (
    Column("symbol", "TEXT", "Ticker"),
    Column("name", "TEXT", "Company name"),
    Column("sector", "TEXT", "Sector, as pm-market-sim uses it"),
    Column("industry", "TEXT", "Industry within the sector"),
    Column("headquarters", "TEXT", "City and country of the head office"),
    Column("purpose", "TEXT", "What the company does: its main purpose"),
    Column("key_market", "TEXT", "Where most of the revenue comes from"),
    Column("market_position", "TEXT", "What sets it apart: its unique position"),
    Column("origin", "TEXT", "How it started: " + ", ".join(ORIGINS)),
    Column("founders", "TEXT", "Who founded it"),
    Column("founder_story", "TEXT", "How and why the company was created"),
    Column("founded_year", "INTEGER", "Year founded"),
    Column("ipo_year", "INTEGER", "Year of the initial public offering"),
    Column("ipo_valuation_musd", "REAL", "Market value at the IPO, USD millions"),
    Column("ceo_name", "TEXT", "Chief executive"),
    Column("ceo_since", "INTEGER", "Year the CEO took office"),
    Column("ceo_industry_years", "INTEGER", "The CEO's years in the industry"),
    Column("employees", "INTEGER", "Head count"),
    Column("fiscal_year", "INTEGER", "Fiscal year of the financial figures"),
    Column("revenue_musd", "REAL", "Revenue (turnover), USD millions"),
    Column("net_income_musd", "REAL", "Net income (profit), USD millions"),
    Column("revenue_growth_pct", "REAL", "Revenue growth on the year before, %"),
    Column("operating_margin_pct", "REAL", "Operating income / revenue, %"),
    Column("free_cash_flow_musd", "REAL", "Free cash flow, USD millions"),
    Column("market_cap_musd", "REAL", "Market capitalisation, USD millions"),
    Column("dividend_yield_pct", "REAL", "Dividend yield, %"),
    Column("debt_to_equity", "REAL", "Total debt / shareholders' equity"),
    Column("credit_rating", "TEXT", "Long-term credit rating"),
    Column("competitors", "TEXT", "Main listed competitors (tickers)"),
    Column("key_risk", "TEXT", "The biggest risk to the business"),
)

REQUIRED = ("symbol", "name", "sector", "industry")

#: The figures the view derives from the stored ones.
_THIS_YEAR = "CAST(strftime('%Y', 'now') AS INTEGER)"
DERIVED: tuple[tuple[Column, str], ...] = (
    (
        Column("years_in_business", "INTEGER", "Years since founding"),
        f"{_THIS_YEAR} - founded_year",
    ),
    (
        Column("ceo_tenure_years", "INTEGER", "Years the CEO has been in office"),
        f"{_THIS_YEAR} - ceo_since",
    ),
    (
        Column("pe_ratio", "REAL", "Price/earnings: market cap / net income"),
        "CASE WHEN net_income_musd > 0 "
        "THEN ROUND(market_cap_musd / net_income_musd, 1) END",
    ),
    (
        Column("ps_ratio", "REAL", "Price/sales: market cap / revenue"),
        "CASE WHEN revenue_musd > 0 "
        "THEN ROUND(market_cap_musd / revenue_musd, 2) END",
    ),
    (
        Column("net_margin_pct", "REAL", "Net income / revenue, %"),
        "CASE WHEN revenue_musd > 0 "
        "THEN ROUND(100.0 * net_income_musd / revenue_musd, 1) END",
    ),
)

COLUMNS: dict[str, Column] = {c.name: c for c in FIELDS} | {
    c.name: c for c, _ in DERIVED
}

#: The labels of the industries pm-market-sim gives news of their own; only
#: their members may use them.
SIM_INDUSTRY_LABELS = {
    "SEMICONDUCTORS": "Semiconductors",
    "SOFTWARE": "Software",
    "PHARMA": "Pharmaceuticals",
    "AUTOS": "Automobiles",
    "AIRLINES": "Airlines",
    "AEROSPACE": "Aerospace & Defense",
}

_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,5}")


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create the company schema on an open SQLite connection."""
    columns = ",\n    ".join(
        f"{c.name} {c.kind}"
        + (" PRIMARY KEY" if c.name == "symbol" else "")
        + (" NOT NULL" if c.name in REQUIRED[1:] else "")
        for c in FIELDS
    )
    conn.execute(f"CREATE TABLE IF NOT EXISTS companies (\n    {columns}\n)")
    conn.execute("CREATE INDEX IF NOT EXISTS companies_sector ON companies(sector)")
    derived = ",\n    ".join(f"{sql} AS {c.name}" for c, sql in DERIVED)
    conn.execute(
        f"CREATE VIEW IF NOT EXISTS company_view AS\nSELECT *,\n    {derived}\n"
        "FROM companies"
    )


# --- checking ------------------------------------------------------------------
def _coerce(column: Column, value: Any) -> Any:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if column.kind == "TEXT":
        return str(value).strip()
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
        if column.kind == "INTEGER":
            if number != int(number):
                raise ValueError
            return int(number)
        return number
    except (TypeError, ValueError) as exc:
        raise CompanyError(f"{column.name}: {value!r} is not a number") from exc


def check(record: dict[str, Any]) -> dict[str, Any]:
    """The record with its values typed, or a ``CompanyError`` saying what is
    wrong with it."""
    unknown = sorted(set(record) - {c.name for c in FIELDS})
    if unknown:
        raise CompanyError(f"unknown field(s): {', '.join(unknown)}")
    rec = {c.name: _coerce(c, record.get(c.name)) for c in FIELDS}
    symbol = rec["symbol"] = (rec["symbol"] or "").upper()
    where = f"{symbol or '?'}: "
    for name in REQUIRED:
        if rec[name] is None:
            raise CompanyError(f"{where}{name} is required")
    if not _SYMBOL.fullmatch(symbol):
        raise CompanyError(f"{where}a symbol is 1-6 letters or digits")
    sector = rec["sector"] = rec["sector"].upper()
    if sector not in PROFILES:
        raise CompanyError(f"{where}sector must be one of {', '.join(PROFILES)}")
    if SECTOR_OF.get(symbol, sector) != sector:
        raise CompanyError(
            f"{where}pm-market-sim puts {symbol} in {SECTOR_OF[symbol]}, not {sector}"
        )
    sim_industry = industry_of(symbol, sector)
    if sim_industry != sector:
        label = SIM_INDUSTRY_LABELS[sim_industry]
        if rec["industry"] != label:
            raise CompanyError(f"{where}pm-market-sim's industry is {label}")
    elif rec["industry"] in SIM_INDUSTRY_LABELS.values():
        raise CompanyError(
            f"{where}{rec['industry']} is kept for the companies pm-market-sim "
            "puts in that industry"
        )
    if rec["origin"] is not None:
        rec["origin"] = rec["origin"].upper()
        if rec["origin"] not in ORIGINS:
            raise CompanyError(f"{where}origin must be one of {', '.join(ORIGINS)}")
    if rec["credit_rating"] is not None and rec["credit_rating"] not in RATINGS:
        raise CompanyError(f"{where}credit_rating must be one of {' '.join(RATINGS)}")
    if rec["competitors"] is not None:
        rec["competitors"] = " ".join(rec["competitors"].upper().split())
    this_year = date.today().year
    order = ("founded_year", "ipo_year", "fiscal_year")
    years = [(n, rec[n]) for n in order if rec[n] is not None]
    for (a, ya), (b, yb) in zip(years, years[1:]):
        if ya > yb:
            raise CompanyError(f"{where}{a} ({ya}) is after {b} ({yb})")
    for name in ("founded_year", "ipo_year", "ceo_since", "fiscal_year"):
        if rec[name] is not None and rec[name] > this_year:
            raise CompanyError(f"{where}{name} is in the future")
    ceo_since = rec["ceo_since"]
    if ceo_since is not None:
        if rec["founded_year"] is not None and ceo_since < rec["founded_year"]:
            raise CompanyError(f"{where}ceo_since is before founded_year")
        industry_years = rec["ceo_industry_years"]
        if industry_years is not None and industry_years < this_year - ceo_since:
            raise CompanyError(
                f"{where}ceo_industry_years is shorter than the CEO's tenure"
            )
    for name in ("ipo_valuation_musd", "employees", "market_cap_musd"):
        if rec[name] is not None and rec[name] <= 0:
            raise CompanyError(f"{where}{name} must be positive")
    for name in ("ceo_industry_years", "revenue_musd", "dividend_yield_pct"):
        if rec[name] is not None and rec[name] < 0:
            raise CompanyError(f"{where}{name} cannot be negative")
    return rec


# --- the bundled companies -----------------------------------------------------
def load_seed(seed_dir: Path = SEED_DIR) -> list[dict[str, Any]]:
    """The checked companies of every ``*.yaml`` in ``seed_dir``."""
    return read_companies(sorted(seed_dir.glob("*.yaml")))


def read_companies(paths: list[Path]) -> list[dict[str, Any]]:
    """The checked companies of YAML files, each a mapping of symbol to
    fields, sorted by symbol."""
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise CompanyError(f"cannot read {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise CompanyError(f"{path}: a mapping of symbol to fields is required")
        for symbol, fields in raw.items():
            if not isinstance(fields, dict):
                raise CompanyError(f"{path}: {symbol}: fields must be a mapping")
            try:
                rec = check({"symbol": str(symbol), **fields})
            except CompanyError as exc:
                raise CompanyError(f"{path}: {exc}") from exc
            if rec["symbol"] in records:
                raise CompanyError(f"{path}: {rec['symbol']} is listed twice")
            records[rec["symbol"]] = rec
    return [records[s] for s in sorted(records)]


def build(path: Path, records: list[dict[str, Any]], force: bool = False) -> None:
    """Write a new database at ``path`` holding ``records``."""
    if path.exists() and not force:
        raise CompanyError(f"{path} exists (use --force to replace it)")
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.unlink(missing_ok=True)
        with closing(sqlite3.connect(tmp)) as conn:
            initialize_schema(conn)
            with conn:
                for rec in records:
                    insert(conn, rec)
            conn.execute("VACUUM")
        os.replace(tmp, path)
    except (OSError, sqlite3.Error) as exc:
        raise CompanyError(f"cannot write {path}: {exc}") from exc


# --- reading and writing -------------------------------------------------------
def connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise CompanyError(f"no company database at {path} (run: pm-compdb-cli init)")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def insert(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    rec = check(record)
    names = [c.name for c in FIELDS]
    try:
        conn.execute(
            f"INSERT INTO companies ({', '.join(names)}) "
            f"VALUES ({', '.join('?' * len(names))})",
            [rec[n] for n in names],
        )
    except sqlite3.IntegrityError as exc:
        raise CompanyError(f"{rec['symbol']} is already in the database") from exc


def get(conn: sqlite3.Connection, symbol: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM company_view WHERE symbol = ?", (symbol.upper(),)
    ).fetchone()
    return dict(row) if row is not None else None


def update(conn: sqlite3.Connection, symbol: str, changes: dict[str, Any]) -> None:
    current = get(conn, symbol)
    if current is None:
        raise CompanyError(f"{symbol.upper()} is not in the database")
    if "symbol" in changes:
        raise CompanyError("the symbol cannot be changed; delete and add instead")
    stored = {c.name: current[c.name] for c in FIELDS}
    rec = check(stored | changes)
    names = [c.name for c in FIELDS if c.name != "symbol"]
    conn.execute(
        f"UPDATE companies SET {', '.join(f'{n} = ?' for n in names)} "
        "WHERE symbol = ?",
        [rec[n] for n in names] + [rec["symbol"]],
    )


def delete(conn: sqlite3.Connection, symbol: str) -> None:
    if (
        conn.execute(
            "DELETE FROM companies WHERE symbol = ?", (symbol.upper(),)
        ).rowcount
        == 0
    ):
        raise CompanyError(f"{symbol.upper()} is not in the database")


class Filter(NamedTuple):
    column: str
    op: str  # = != < <= > >= or ~ (contains, any case)
    value: Any


_FILTER = re.compile(r"\s*([a-z_]+)\s*(>=|<=|!=|=|<|>|~)\s*(.*?)\s*")


def parse_filter(text: str) -> Filter:
    """``COLUMN OP VALUE``, e.g. ``pe_ratio<15``, ``sector=TECH`` or
    ``purpose~cloud``."""
    match = _FILTER.fullmatch(text)
    if match is None:
        raise CompanyError(
            f"bad filter {text!r}: use COLUMN OP VALUE, OP one of = != < <= > >= ~"
        )
    name, op, value = match.groups()
    column = COLUMNS.get(name)
    if column is None:
        raise CompanyError(f"bad filter {text!r}: no column {name!r}")
    if op != "~" and column.kind != "TEXT":
        value = _coerce(column, value)
        if value is None:
            raise CompanyError(f"bad filter {text!r}: a value is required")
    elif op in ("<", "<=", ">", ">="):
        raise CompanyError(f"bad filter {text!r}: {name} is text; use = != or ~")
    return Filter(name, op, value)


def query(
    conn: sqlite3.Connection,
    columns: list[str],
    filters: Sequence[Filter] = (),
    sort: str = "symbol",
    descending: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    for name in [*columns, sort]:
        if name not in COLUMNS:
            raise CompanyError(f"no column {name!r} (see: pm-compdb-cli columns)")
    clauses: list[str] = []
    params: list[Any] = []
    for f in filters:
        if f.op == "~":
            clauses.append(f"{f.column} LIKE ? ESCAPE '\\'")
            escaped = re.sub(r"([\\%_])", r"\\\1", str(f.value))
            params.append(f"%{escaped}%")
        elif COLUMNS[f.column].kind == "TEXT":
            clauses.append(f"{f.column} {f.op} ? COLLATE NOCASE")
            params.append(f.value)
        else:
            clauses.append(f"{f.column} {f.op} ?")
            params.append(f.value)
    sql = f"SELECT {', '.join(columns)} FROM company_view"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += f" ORDER BY {sort} IS NULL, {sort} {'DESC' if descending else 'ASC'}"
    if sort != "symbol":
        sql += ", symbol"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in conn.execute(sql, params)]
