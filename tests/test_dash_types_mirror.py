"""web-apps/dash-gui's TypeScript mirror of the `health` messages.

The dashboard bridge passes pm-monitor's `health.snapshot` and `health.event`
payloads to the browser unchanged, so `packages/dash-types/src/health.ts`
must describe exactly what `spec/messages/health.yaml` puts on the wire:
every field, with its nullability, enum values and element type. The
TypeScript is read as text, so no Node toolchain is needed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((REPO / "spec/messages/health.yaml").read_text(encoding="utf-8"))
TS = (REPO / "web-apps/dash-gui/packages/dash-types/src/health.ts").read_text(
    encoding="utf-8"
)

#: Spec message -> TypeScript interface; the beacon never reaches a browser.
MESSAGES = {"health_snapshot": "HealthSnapshot", "health_event": "HealthEvent"}
SCALARS = {"string": "string", "int": "number", "float": "number", "bool": "boolean"}


def _interfaces() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for name, body in re.findall(
        r"export interface (\w+) \{\n(.*?)\n\}", TS, re.DOTALL
    ):
        fields = re.findall(r"^\s+(\w+): (.+);$", body, re.MULTILINE)
        out[name] = dict(fields)
    return out


def _aliases() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for name, body in re.findall(r"export type (\w+) =(.*?);", TS, re.DOTALL):
        out[name] = set(re.findall(r'"([A-Z_]+)"', body))
    return out


INTERFACES = _interfaces()
ALIASES = _aliases()


def _spec_records() -> dict[str, list[dict[str, Any]]]:
    records = {name: t["fields"] for name, t in SPEC["types"].items()}
    for message in SPEC["messages"]:
        if message["name"] in MESSAGES:
            records[MESSAGES[message["name"]]] = message["fields"]
    return records


def _expected_type(field: dict[str, Any]) -> str:
    kind = field["type"]
    if kind == "nested":
        ts = str(field["ref"])
    elif kind == "list":
        item = field.get("ref") or SCALARS[field["item"]]
        ts = f"{item}[]"
    elif kind == "enum":
        ts = "<enum>"
    else:
        ts = SCALARS[kind]
    return f"{ts} | null" if field.get("nullable") else ts


@pytest.mark.parametrize("record", sorted(_spec_records()))
def test_every_record_matches_the_spec(record: str) -> None:
    fields = _spec_records()[record]
    assert record in INTERFACES, f"health.ts has no interface {record}"
    ts_fields = INTERFACES[record]
    assert list(ts_fields) == [f["name"] for f in fields], record
    for field in fields:
        ts_type = ts_fields[field["name"]]
        expected = _expected_type(field)
        where = f"{record}.{field['name']}"
        if expected.startswith("<enum>"):
            alias = ts_type.removesuffix(" | null")
            assert alias in ALIASES, f"{where}: {ts_type} is not a string-union alias"
            assert ALIASES[alias] == set(field["values"]), where
        else:
            assert ts_type == expected, f"{where}: {ts_type} != {expected}"


def test_the_scanner_sees_what_it_should() -> None:
    """Guards the guard: a regex that found nothing would pass above."""
    assert len(INTERFACES) >= 12
    assert INTERFACES["ProcessHealth"]["fds"] == "number | null"
    assert ALIASES["EventKind"] >= {"CONNECT", "THRESHOLD"}
