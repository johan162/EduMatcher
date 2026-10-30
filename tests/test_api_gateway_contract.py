"""WP-API06: the committed OpenAPI document is the v1 contract.

``spec/rest/openapi.json`` must be exactly what the gateway publishes, so any
change to the REST surface shows up as a diff in review -- an accidental
breaking change cannot slip through a refactor unseen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edumatcher.api_gateway import contract


def test_the_committed_contract_matches_the_gateway() -> None:
    assert contract.OUTPUT.exists(), "run `make openapi` and commit the result"
    assert contract.check(), "run `make openapi` and commit the result"


def test_the_contract_does_not_depend_on_deployment_config() -> None:
    """One document for every deployment: config must not leak into it."""
    from edumatcher.api_gateway.config import ApiGatewayConfig

    other = ApiGatewayConfig(swagger_enabled=False, order_retention_sec=10)
    assert contract.render(other) == contract.render()


def test_the_contract_is_v1() -> None:
    document = json.loads(contract.render())
    assert document["info"]["version"] == "1.0.0"
    assert all(path.startswith("/api/v1/") for path in document["paths"])


def test_check_reports_drift_and_generate_repairs_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "openapi.json"
    assert not contract.check(path)  # missing
    path.write_text(contract.render().replace("Submit an order", "Submit"))
    assert not contract.check(path)
    err = capsys.readouterr().err
    assert "make openapi" in err
    assert any(
        line.startswith("+") and '"summary": "Submit an order"' in line
        for line in err.splitlines()
    )
    assert contract.generate(path) is True
    assert contract.check(path)
    assert contract.generate(path) is False  # already up to date


def test_main_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contract, "OUTPUT", tmp_path / "openapi.json")
    assert contract.main(["check"]) == 1
    assert contract.main(["generate"]) == 0
    assert contract.main(["check"]) == 0
