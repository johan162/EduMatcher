"""Tests for pm-config-deploy — installing an authored config as the live one.

The command exists because the authored configuration and the running one are
now different files: the first is yours to edit and version, the second is the
single copy every process reads. Deploying is the only moment those two meet,
so it is the only moment validation can still be cheap.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.config_deploy import deploy

VALID = """
symbols:
  AAPL: {}
  MSFT: {}
gateways:
  alf:
    - id: GW01
"""


def _source(tmp_path: Path, text: str = VALID) -> Path:
    path = tmp_path / "authored.yaml"
    path.write_text(text)
    return path


class TestDeploy:
    def test_installs_the_configuration(self, tmp_path: Path) -> None:
        dest = tmp_path / "ref_data" / "engine_config.yaml"

        deploy(_source(tmp_path), dest)

        assert dest.read_text() == VALID

    def test_creates_the_reference_directory(self, tmp_path: Path) -> None:
        # A first deploy into a fresh data directory must work without the
        # operator having to guess at the layout.
        dest = tmp_path / "brand" / "new" / "engine_config.yaml"

        deploy(_source(tmp_path), dest)

        assert dest.is_file()

    def test_reports_what_was_installed(self, tmp_path: Path) -> None:
        # The symbol count is the one number that would have made yesterday's
        # empty-universe failure obvious at deploy time.
        count = deploy(_source(tmp_path), tmp_path / "engine_config.yaml")

        assert count == 2

    def test_replaces_a_previous_deployment(self, tmp_path: Path) -> None:
        dest = tmp_path / "engine_config.yaml"
        dest.write_text("symbols:\n  OLD: {}\n")

        deploy(_source(tmp_path), dest)

        assert "AAPL" in dest.read_text()
        assert "OLD" not in dest.read_text()

    def test_leaves_the_old_config_in_place_when_the_new_one_is_bad(
        self, tmp_path: Path
    ) -> None:
        # Half-deploying is worse than not deploying: the exchange would come
        # back up on a file nobody wrote.
        dest = tmp_path / "engine_config.yaml"
        dest.write_text(VALID)
        bad = _source(tmp_path, "symbols: [this is not a mapping]\n")

        with pytest.raises(Exception):
            deploy(bad, dest)

        assert dest.read_text() == VALID

    def test_leaves_no_staging_file_behind(self, tmp_path: Path) -> None:
        dest = tmp_path / "engine_config.yaml"

        deploy(_source(tmp_path), dest)

        assert list(tmp_path.glob("*.tmp")) == []

    def test_rejects_a_config_the_engine_could_not_load(self, tmp_path: Path) -> None:
        # Validation is the same load every process performs at startup, so a
        # deploy that succeeds cannot be followed by a parse failure at boot.
        dest = tmp_path / "engine_config.yaml"
        bad = _source(tmp_path, "symbols: [this is not a mapping]\n")

        with pytest.raises(Exception):
            deploy(bad, dest)

        assert not dest.exists()
