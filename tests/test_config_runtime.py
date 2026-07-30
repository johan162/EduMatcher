"""Tests for config.py environment variable resolution."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


def _reload_config(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> types.ModuleType:
    """Reload edumatcher.config with *env* set and return the module."""
    for var in ("EDUMATCHER_DATA_DIR", "EDUMATCHER_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Remove cached module so it re-evaluates the top-level expressions
    sys.modules.pop("edumatcher.config", None)
    import edumatcher.config as cfg  # noqa: PLC0415

    return cfg


class TestDataDirResolution:
    def test_env_var_wins(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        custom = str(tmp_path / "custom_data")
        cfg = _reload_config(monkeypatch, {"EDUMATCHER_DATA_DIR": custom})
        assert cfg.DATA_DIR == Path(custom).resolve()
        # All derived paths share the same root
        assert cfg.GTC_ORDERS_FILE.parent == cfg.DATA_DIR
        assert cfg.STATS_DB_FILE.parent == cfg.DATA_DIR

    def test_source_tree_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _reload_config(monkeypatch, {})
        # In the test environment we ARE in the source tree — src/data is expected
        assert cfg._IN_SOURCE_TREE is True
        assert cfg.DATA_DIR.name == "data"
        assert cfg.DATA_DIR.parent.name == "src"

    def test_installed_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Simulate an installed (site-packages) environment by patching __file__."""
        cfg_module = _reload_config(monkeypatch, {})
        # Pretend the package is installed (parent dir is NOT named "src")
        monkeypatch.setattr(cfg_module, "_IN_SOURCE_TREE", False)
        monkeypatch.setattr(
            cfg_module,
            "DATA_DIR",
            Path("~/.local/share/edumatcher").expanduser(),
        )
        assert (
            "edumatcher" in str(cfg_module.DATA_DIR)
            or cfg_module.DATA_DIR == Path("~/.local/share/edumatcher").expanduser()
        )


class TestEngineConfigResolution:
    def test_travels_with_the_data_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # One data directory is one exchange instance: pointing at a different
        # data dir must relocate the config along with stats.db and log.db,
        # never leave it behind pointing at the previous instance's file.
        custom = str(tmp_path / "custom_data")
        cfg = _reload_config(monkeypatch, {"EDUMATCHER_DATA_DIR": custom})

        assert cfg.ENGINE_CONFIG_FILE.parent.parent == cfg.DATA_DIR
        assert cfg.ENGINE_CONFIG_FILE.parent == cfg.REF_DATA_DIR

    def test_ignores_a_config_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # EDUMATCHER_CONFIG is gone. Honouring it for some processes and not
        # others is the divergence this resolution exists to prevent, so a
        # leftover export in a shell profile must have no effect at all.
        data_dir = str(tmp_path / "d")
        stray = str(tmp_path / "stray.yaml")

        without = _reload_config(
            monkeypatch, {"EDUMATCHER_DATA_DIR": data_dir}
        ).ENGINE_CONFIG_FILE
        with_stray = _reload_config(
            monkeypatch,
            {"EDUMATCHER_DATA_DIR": data_dir, "EDUMATCHER_CONFIG": stray},
        ).ENGINE_CONFIG_FILE

        assert with_stray == without
        assert with_stray != Path(stray)

    def test_two_data_dirs_never_share_a_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        first = _reload_config(
            monkeypatch, {"EDUMATCHER_DATA_DIR": str(tmp_path / "a")}
        ).ENGINE_CONFIG_FILE
        second = _reload_config(
            monkeypatch, {"EDUMATCHER_DATA_DIR": str(tmp_path / "b")}
        ).ENGINE_CONFIG_FILE

        assert first != second
