"""roster.yaml: gateway -> person, opening balance, line-numbered errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.eod.roster import RosterError, Trader, load_roster


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "roster.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_is_an_empty_roster(tmp_path: Path) -> None:
    assert load_roster(tmp_path / "nope.yaml") == {}


def test_loads_traders_and_normalises_gateway_case(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "traders:\n"
        "  - gateway: gw_alice\n"
        "    name: Alice Andersson\n"
        "    email: alice@example.org\n"
        "    opening_balance: 1000.50\n"
        "  - gateway: GW_BOB\n",
    )
    assert load_roster(path) == {
        "GW_ALICE": Trader("GW_ALICE", "Alice Andersson", "alice@example.org", 100050),
        "GW_BOB": Trader("GW_BOB", "GW_BOB", None, 0),
    }


def test_empty_file_is_an_empty_roster(tmp_path: Path) -> None:
    assert load_roster(write(tmp_path, "")) == {}


@pytest.mark.parametrize(
    ("text", "line", "message"),
    [
        ("traders:\n  - name: X\n", 2, "gateway"),
        ("traders:\n  - gateway: A\n  - gateway: a\n", 3, "duplicate"),
        ("traders:\n  - gateway: A\n    opening_balance: 1.234\n", 2, "2 decimals"),
        ("traders:\n  - gateway: A\n    opening_balance: lots\n", 2, "opening_balance"),
        ("traders:\n  - gateway: A\n    colour: red\n", 2, "colour"),
        ("traders:\n  - gateway: EXCHANGE\n", 2, "EXCHANGE"),
        ("traders: 5\n", 1, "list"),
        ("people: []\n", 1, "traders"),
    ],
)
def test_errors_name_the_line(
    tmp_path: Path, text: str, line: int, message: str
) -> None:
    with pytest.raises(RosterError, match=message) as err:
        load_roster(write(tmp_path, text))
    assert f"line {line}" in str(err.value)
