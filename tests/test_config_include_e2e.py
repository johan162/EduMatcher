"""A configuration split with ``include:`` deploys and runs a real exchange.

The bundled ``s10-basic`` config is split into ``symbols.yaml`` and
``participants.yaml`` around a main file that lists them; ``pm-config-deploy``
compiles that, ``pm-opctl-cli`` starts the ``mini`` profile on it, and the API
gateway comes up healthy. Then the installed copy is checked to hold the
include files, so the deployed directory records what the exchange runs on.

End-to-end: runs only with ``-m e2e`` (``make test-e2e``).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from edumatcher.config_deploy import resolve_example
from tests.e2e_exchange import Exchange, running_exchange

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals"),
]

URL = "http://127.0.0.1:8080"


def _split_s10(directory: Path) -> Path:
    raw = yaml.safe_load(resolve_example("s10-basic").read_text(encoding="utf-8"))
    for key in ("symbols", "participants"):
        (directory / f"{key}.yaml").write_text(
            yaml.safe_dump({key: raw.pop(key)}, sort_keys=False), encoding="utf-8"
        )
    main = directory / "engine_config.yaml"
    main.write_text(
        yaml.safe_dump(
            {"include": ["symbols.yaml", "participants.yaml"], **raw}, sort_keys=False
        ),
        encoding="utf-8",
    )
    return main


@pytest.fixture(scope="module")
def exchange(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Exchange]:
    main = _split_s10(tmp_path_factory.mktemp("split"))
    with running_exchange(request, tmp_path_factory, config=main) as ex:
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(f"{URL}/api/v1/healthz", timeout=2) as r:
                    if json.loads(r.read()).get("ok"):
                        break
            except OSError:
                pass
            assert time.monotonic() < deadline, "the API gateway never became healthy"
            time.sleep(0.5)
        yield ex


def test_the_exchange_runs_on_a_split_config(exchange: Exchange) -> None:
    compiled = json.loads(
        (exchange.data_dir / "ref_data" / "engine_config.json").read_text()
    )
    expected = yaml.safe_load(resolve_example("s10-basic").read_text("utf-8"))
    assert set(compiled["engine"]["symbols"]) == {
        s.upper() for s in expected["symbols"]
    }
    assert compiled["meta"]["source_sha256"]


def test_the_include_files_are_installed_beside_the_artifact(
    exchange: Exchange,
) -> None:
    ref_data = exchange.data_dir / "ref_data"
    assert (ref_data / "symbols.yaml").is_file()
    assert (ref_data / "participants.yaml").is_file()
    assert "include" in (ref_data / "engine_config.yaml").read_text()
