"""WP-API14: the REST spec's endpoint sections agree with the contract.

Clients read ``060-rest-and-websocket.md``; the gateway serves
``spec/rest/openapi.json`` (held to the code by test_api_gateway_contract and
test_api_gateway_error_codes). Each endpoint section's tables are checked
against it: the endpoint exists, the argument names and which are required,
the success statuses, and the error codes -- exactly, in both directions.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute

from edumatcher.api_gateway import contract
from edumatcher.api_gateway.errors import ERROR_CODES
from edumatcher.api_gateway.routers import admin, bootstrap, history, orders, reference

SPEC = (
    Path(__file__).resolve().parents[1]
    / "docs/books/protocols-and-clients/part-2-specifications/060-rest-and-websocket.md"
)
#: Every operation can answer these; the spec says so once, in "Common error
#: codes", instead of in each endpoint's table.
UNIVERSAL = {"AUTH", "ENGINE_AUTH", "ENGINE_UNAVAILABLE", "INTERNAL_ERROR"}
_HEADING = re.compile(r"^### `(GET|POST|PUT|PATCH|DELETE) (/api/v1/[^`]*)`\s*$", re.M)


@cache
def _text() -> str:
    return SPEC.read_text(encoding="utf-8")


@cache
def _contract() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(contract.OUTPUT.read_text(encoding="utf-8"))
    return document


def _operations() -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method.upper(), path): operation
        for path, item in _contract()["paths"].items()
        for method, operation in item.items()
    }


def _hidden_routes() -> set[tuple[str, str]]:
    """Documented in the spec but kept out of the contract (``/healthz``)."""
    return {
        (method, route.path)
        for module in (orders, reference, history, admin, bootstrap)
        for route in module.router.routes
        if isinstance(route, APIRoute) and not route.include_in_schema
        for method in route.methods or ()
    }


@cache
def _sections() -> dict[tuple[str, str], str]:
    text = _text()
    found: dict[tuple[str, str], str] = {}
    matches = list(_HEADING.finditer(text))
    for match in matches:
        rest = text[match.end() :]
        end = re.search(r"^#{2,3} ", rest, re.M)
        key = (match.group(1), match.group(2))
        assert key not in found, f"two sections for {key}"
        found[key] = rest[: end.start()] if end else rest
    return found


def _table(section: str, title: str) -> list[list[str]]:
    """The rows (header excluded) of the table under ``**title**``."""
    marker = f"**{title}**"
    assert marker in section, f"no {marker} table"
    rows = []
    for line in section.split(marker, 1)[1].splitlines()[1:]:
        if line.startswith("**"):
            break
        if line.startswith("|") and not re.match(r"^\|\s*-", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows[1:]


def _cell_name(cell: str) -> str:
    return re.sub(r"[`\s]", "", cell)


def _resolve(schema: dict[str, Any]) -> dict[str, Any]:
    if "anyOf" in schema:  # an optional body: the non-null branch
        schema = next(s for s in schema["anyOf"] if s.get("type") != "null")
    while "$ref" in schema:
        schema = _contract()["components"]["schemas"][schema["$ref"].split("/")[-1]]
    return schema


def _declared_codes(operation: dict[str, Any]) -> set[str]:
    return {
        example["value"]["error"]["code"]
        for status_code, response in operation["responses"].items()
        if not status_code.startswith("2")
        for example in response["content"]["application/json"]["examples"].values()
    }


_DOCUMENTED = sorted(_operations())


def test_every_operation_has_exactly_one_section() -> None:
    expected = set(_operations()) | _hidden_routes()
    documented = set(_sections())
    assert sorted(expected - documented) == [], "no spec section"
    assert sorted(documented - expected) == [], "spec section for no route"


def test_the_endpoint_index_lists_every_section() -> None:
    index = _text().split("## Endpoint index", 1)[1].split("\n## ", 1)[0]
    listed = set(re.findall(r"\[(GET|POST|PUT|PATCH|DELETE) (/api/v1/[^\]]*)\]", index))
    assert listed == set(_sections())


def test_the_universal_codes_are_universal_and_documented_once() -> None:
    every = set.intersection(*(_declared_codes(o) for o in _operations().values()))
    assert every == UNIVERSAL
    common = _text().split("### Common error codes", 1)[1].split("\n### ", 1)[0]
    for code in UNIVERSAL:
        assert f"`{code}`" in common.split("|", 1)[0], f"{code} not named as universal"


def test_the_common_error_table_is_the_registry() -> None:
    common = _text().split("### Common error codes", 1)[1].split("\n### ", 1)[0]
    rows = re.findall(r"^\| `([A-Z_]+)` \| `(\d{3})` \|", common, re.M)
    assert {code: int(status) for code, status in rows} == {
        code: entry.status for code, entry in ERROR_CODES.items()
    }


@pytest.mark.parametrize(
    ("method", "path"), _DOCUMENTED, ids=[f"{m} {p}" for m, p in _DOCUMENTED]
)
def test_the_arguments_table_matches(method: str, path: str) -> None:
    operation = _operations()[(method, path)]
    wanted: dict[str, bool] = {
        p["name"]: bool(p.get("required")) for p in operation.get("parameters", [])
    }
    rows = [r for r in _table(_sections()[(method, path)], "Arguments") if r]
    documented = {_cell_name(r[0]): r[2] for r in rows if _cell_name(r[0]) != "none"}
    # A `body` row stands for "the same body as" another endpoint (replace
    # takes a whole order); its fields are checked there.
    if "requestBody" in operation and documented.pop("body", None) is None:
        schema = _resolve(
            operation["requestBody"]["content"]["application/json"]["schema"]
        )
        required = set(schema.get("required", []))
        for name in schema.get("properties", {}):
            wanted[name] = name in required
    assert set(documented) == set(wanted), (
        f"spec-only {sorted(set(documented) - set(wanted))}, "
        f"contract-only {sorted(set(wanted) - set(documented))}"
    )
    for name, is_required in wanted.items():
        says_required = documented[name].strip("`").lower().startswith("yes")
        assert says_required == is_required, f"{name}: Req says {documented[name]!r}"


@pytest.mark.parametrize(
    ("method", "path"), _DOCUMENTED, ids=[f"{m} {p}" for m, p in _DOCUMENTED]
)
def test_the_success_statuses_match(method: str, path: str) -> None:
    rows = _table(_sections()[(method, path)], "Reply")
    documented = {m.group(1) for r in rows if r and (m := re.match(r"`?(2\d\d)", r[0]))}
    contracted = {
        s for s in _operations()[(method, path)]["responses"] if s.startswith("2")
    }
    assert documented == contracted


@pytest.mark.parametrize(
    ("method", "path"), _DOCUMENTED, ids=[f"{m} {p}" for m, p in _DOCUMENTED]
)
def test_the_error_codes_match(method: str, path: str) -> None:
    rows = _table(_sections()[(method, path)], "Errors")
    documented = {_cell_name(r[0]) for r in rows if r and _cell_name(r[0]) != "none"}
    expected = _declared_codes(_operations()[(method, path)]) - UNIVERSAL
    assert documented == expected, (
        f"spec-only {sorted(documented - expected)}, "
        f"missing {sorted(expected - documented)}"
    )
