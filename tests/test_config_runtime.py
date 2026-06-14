"""Tests for config.py environment variable resolution."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


def _reload_config(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> object:
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
        fake_pkg_dir = Path("/usr/lib/python3.13/site-packages/edumatcher")
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
    def test_env_var_wins(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        custom_cfg = str(tmp_path / "my_engine.yaml")
        cfg = _reload_config(monkeypatch, {"EDUMATCHER_CONFIG": custom_cfg})
        assert cfg.ENGINE_CONFIG_FILE == Path(custom_cfg).resolve()

    def test_source_tree_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _reload_config(monkeypatch, {})
        assert cfg._IN_SOURCE_TREE is True
        # Should resolve to <repo>/engine_config.yaml
        assert cfg.ENGINE_CONFIG_FILE.name == "engine_config.yaml"
        assert cfg.ENGINE_CONFIG_FILE.parent.name != "src"  # repo root, not src/
