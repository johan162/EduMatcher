"""CG3: the EOD settlement and balance read routes over ``eod.db``.

Settlement amounts are integer minor units of the display currency (2
decimals), never clearing ticks: positive means the exchange owes the
gateway. A balance is derived -- the roster's opening balance plus the
settlement amounts up to a date -- and is not stored anywhere. ``EXCHANGE``,
the rounding account, is visible to ADMIN only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.eod.report import fmt_minor
from tests.api_gateway_harness import call
from tests.clearing_api_fixture import (
    ADMIN_KEY,
    DAY1,
    DAY2,
    DAY3,
    MM_KEY,
    OPENINGS,
    READ_ONLY_KEY,
    TRADER_KEY,
    Venue,
    build_venue,
    make_clearing_app,
    rows,
)


@pytest.fixture(scope="module")
def venue(tmp_path_factory: pytest.TempPathFactory) -> Venue:
    return build_venue(tmp_path_factory.mktemp("venue"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _get(
    venue: Venue, path: str, key: str = ADMIN_KEY, **config: Any
) -> tuple[int, dict[str, Any]]:
    status, _, body = await call(
        make_clearing_app(venue, **config),
        "GET",
        f"/api/v1/clearing{path}",
        authorization=f"Bearer {key}",
    )
    return status, body


def _code(body: dict[str, Any]) -> str:
    return str(body["error"]["code"])


def _stored() -> str:
    return "SELECT trade_date, account, amount_minor FROM eod_settlement"


def _amounts(venue: Venue) -> dict[tuple[str, str], int]:
    return {
        (r["trade_date"], r["account"]): r["amount_minor"]
        for r in rows(venue.eod_db, _stored())
    }


# ---------------------------------------------------------------------------
# settlements
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_settlements_are_the_ledger_rows_in_minor_units(
    venue: Venue,
) -> None:
    status, body = await _get(venue, "/settlements")
    assert status == 200
    stored = _amounts(venue)
    got = {(s["trade_date"], s["account"]): s for s in body["settlements"]}
    assert set(got) == set(stored)
    for key, amount in stored.items():
        assert got[key]["amount_minor"] == amount
        assert got[key]["amount"] == fmt_minor(amount)
    # Newest date first, then account.
    assert [(s["trade_date"], s["account"]) for s in body["settlements"]] == [
        (DAY2, "EXCHANGE"),
        (DAY2, "MM01"),
        (DAY2, "TRADER01"),
        (DAY1, "MM01"),
        (DAY1, "TRADER01"),
    ]
    for day in (DAY1, DAY2):
        assert sum(a for (d, _), a in stored.items() if d == day) == 0


@pytest.mark.anyio
async def test_signs_say_who_owes_whom(venue: Venue) -> None:
    _, body = await _get(venue, f"/settlements?date={DAY1}")
    by_account = {s["account"]: s for s in body["settlements"]}
    # TRADER01 closed DAY1 long AAPL marked 25.00 above its average cost.
    assert by_account["TRADER01"]["amount_minor"] == 2500
    assert by_account["TRADER01"]["amount"] == "25.00"
    assert by_account["MM01"]["amount_minor"] == -2500
    assert by_account["MM01"]["amount"] == "-25.00"


@pytest.mark.anyio
async def test_per_symbol_detail_is_the_unrounded_calculation(venue: Venue) -> None:
    _, body = await _get(venue, f"/settlements?date={DAY2}&gateway=TRADER01")
    (row,) = body["settlements"]
    assert set(row["detail"]) == {"AAPL", "EURUSD"}
    exact = sum(float(v) for v in row["detail"].values())
    # The stored amount is the rounded sum, less the cent the fixture moved
    # to EXCHANGE.
    assert row["amount_minor"] == round(exact * 100) - 1
    assert all(isinstance(v, str) for v in row["detail"].values())


@pytest.mark.anyio
async def test_each_row_carries_its_run_status_and_runs_are_listed(
    venue: Venue,
) -> None:
    _, body = await _get(venue, "/settlements")
    status_by_date = {s["trade_date"]: s["run_status"] for s in body["settlements"]}
    assert status_by_date == {DAY1: "ok", DAY2: "report-failed"}
    assert [(r["trade_date"], r["status"]) for r in body["runs"]] == [
        (DAY3, "failed"),
        (DAY2, "report-failed"),
        (DAY1, "ok"),
    ]
    assert body["runs"][0]["steps"][0]["step"] == "gate"


@pytest.mark.anyio
async def test_a_date_without_settlement_is_empty_not_unavailable(
    venue: Venue,
) -> None:
    status, body = await _get(venue, f"/settlements?date={DAY3}")
    assert status == 200
    assert body["settlements"] == []
    assert [(r["trade_date"], r["status"]) for r in body["runs"]] == [(DAY3, "failed")]


@pytest.mark.anyio
async def test_settlement_ranges_and_bounds(venue: Venue) -> None:
    _, body = await _get(venue, f"/settlements?from={DAY2}&to={DAY2}")
    assert {s["trade_date"] for s in body["settlements"]} == {DAY2}
    assert [r["trade_date"] for r in body["runs"]] == [DAY2]
    _, body = await _get(venue, "/settlements?limit=2")
    assert (body["count"], body["has_more"]) == (2, True)
    status, body = await _get(venue, f"/settlements?from={DAY2}&to={DAY1}")
    assert (status, _code(body), body["error"]["field"]) == (400, "VALIDATION", "from")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("key", "gateway"), [(TRADER_KEY, "TRADER01"), (MM_KEY, "MM01")]
)
async def test_a_participant_reads_only_its_own_settlement(
    venue: Venue, key: str, gateway: str
) -> None:
    status, body = await _get(venue, "/settlements", key)
    assert status == 200
    assert {s["account"] for s in body["settlements"]} == {gateway}
    assert body["count"] == 2
    # Run outcomes, but not the operator's step messages.
    assert body["runs"] and all("steps" not in r for r in body["runs"])


@pytest.mark.anyio
@pytest.mark.parametrize("foreign", ["MM01", "EXCHANGE", "exchange"])
async def test_a_participant_cannot_guess_another_account(
    venue: Venue, foreign: str
) -> None:
    for path in (f"/settlements?gateway={foreign}", f"/balances?gateway={foreign}"):
        status, body = await _get(venue, path, TRADER_KEY)
        assert (status, _code(body)) == (403, "SCOPE_DENIED"), path


@pytest.mark.anyio
async def test_admin_may_read_the_rounding_account_alone(venue: Venue) -> None:
    _, body = await _get(venue, "/settlements?gateway=EXCHANGE")
    assert [(s["trade_date"], s["amount_minor"]) for s in body["settlements"]] == [
        (DAY2, 1)
    ]


# ---------------------------------------------------------------------------
# balances
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_balance_is_the_opening_plus_the_settlements(venue: Venue) -> None:
    status, body = await _get(venue, "/balances")
    assert status == 200
    stored = _amounts(venue)
    by_account = {b["account"]: b for b in body["balances"]}
    assert set(by_account) == {"TRADER01", "MM01", "EXCHANGE"}
    for account in ("TRADER01", "MM01", "EXCHANGE"):
        settled = sum(a for (_, acc), a in stored.items() if acc == account)
        opening = OPENINGS.get(account, 0)
        row = by_account[account]
        assert row["opening_balance_minor"] == opening
        assert row["settlement_total_minor"] == settled
        assert row["balance_minor"] == opening + settled
        assert row["balance"] == fmt_minor(opening + settled)
        assert row["opening_balance"] == fmt_minor(opening)
    assert by_account["TRADER01"]["balance"] == "10098.79"
    assert by_account["EXCHANGE"]["balance"] == "0.01"
    assert body["as_of"] is None
    assert body["last_settled_date"] == DAY2
    for unsupported in ("equity", "margin", "collateral", "cash"):
        assert not any(unsupported in field for field in by_account["TRADER01"])


@pytest.mark.anyio
async def test_as_of_stops_the_sum_at_that_date(venue: Venue) -> None:
    _, body = await _get(venue, f"/balances?as_of={DAY1}&gateway=TRADER01")
    (row,) = body["balances"]
    assert row["balance_minor"] == OPENINGS["TRADER01"] + 2500
    assert (body["as_of"], body["last_settled_date"]) == (DAY1, DAY1)
    _, body = await _get(venue, "/balances?as_of=2026-10-01&gateway=TRADER01")
    (row,) = body["balances"]
    assert (row["settlement_total_minor"], row["balance_minor"]) == (
        0,
        OPENINGS["TRADER01"],
    )
    assert body["last_settled_date"] is None
    status, body = await _get(venue, "/balances?as_of=2026-02-30")
    assert (status, body["error"]["field"]) == (400, "as_of")


@pytest.mark.anyio
async def test_a_participant_gets_its_own_balance_only(venue: Venue) -> None:
    status, body = await _get(venue, "/balances", MM_KEY)
    assert status == 200
    assert [b["account"] for b in body["balances"]] == ["MM01"]
    assert body["balances"][0]["balance_minor"] == OPENINGS["MM01"] - 2500 - 7380


@pytest.mark.anyio
async def test_a_gateway_never_settled_has_its_opening_balance(
    venue: Venue,
) -> None:
    _, body = await _get(venue, "/balances?gateway=OPS01", ADMIN_KEY)
    assert body["balances"] == [
        {
            "account": "OPS01",
            "opening_balance_minor": 0,
            "opening_balance": "0.00",
            "settlement_total_minor": 0,
            "settlement_total": "0.00",
            "balance_minor": 0,
            "balance": "0.00",
        }
    ]


# ---------------------------------------------------------------------------
# unavailable store, roster, access
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_missing_ledger_is_503(venue: Venue, tmp_path: Path) -> None:
    for path in ("/settlements", "/balances"):
        status, body = await _get(venue, path, eod_db=tmp_path / "eod.db")
        assert (status, _code(body)) == (503, "EOD_DB"), path
        assert str(tmp_path) not in body["error"]["message"]
    assert not (tmp_path / "eod.db").exists()


@pytest.mark.anyio
async def test_an_unreadable_ledger_is_503(venue: Venue, tmp_path: Path) -> None:
    garbage = tmp_path / "eod.db"
    garbage.write_bytes(b"not a database" * 200)
    status, body = await _get(venue, "/settlements", eod_db=garbage)
    assert (status, _code(body)) == (503, "EOD_DB")


@pytest.mark.anyio
async def test_a_malformed_roster_is_503_and_a_missing_one_is_empty(
    venue: Venue, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    (data / "ref_data").mkdir(parents=True)
    ledger = data / "eod.db"
    ledger.write_bytes(venue.eod_db.read_bytes())
    _, body = await _get(venue, "/balances?gateway=TRADER01", eod_db=ledger)
    assert body["balances"][0]["opening_balance_minor"] == 0
    (data / "ref_data" / "roster.yaml").write_text("traders: 7\n", encoding="utf-8")
    status, body = await _get(venue, "/balances", eod_db=ledger)
    assert (status, _code(body)) == (503, "EOD_DB")
    assert str(tmp_path) not in body["error"]["message"]


@pytest.mark.anyio
async def test_a_read_only_key_reads_no_settlement(venue: Venue) -> None:
    for path in ("/settlements", "/balances"):
        status, body = await _get(venue, path, READ_ONLY_KEY)
        assert (status, _code(body)) == (403, "READ_ONLY"), path
