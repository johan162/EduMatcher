"""Tests for config.py environment variable resolution."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


def _reload_config(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    request: pytest.FixtureRequest,
) -> types.ModuleType:
    """Reload edumatcher.config with *env* set and return the module.

    Popping edumatcher.config from sys.modules and re-importing it mutates
    process-global state that outlives monkeypatch's own undo stack (which
    only restores environment variables, not sys.modules). Left alone, the
    rebound module — with whatever tmp_path-derived DATA_DIR it was last
    reloaded with — stays installed in sys.modules for every other test in
    the same worker process, including ones that deleted their tmp_path
    already. Under pytest-xdist that produced an intermittent failure in
    test_stats_and_orders.py depending on test interleaving. Restore the
    original module object on teardown so this reload is local to the test.
    """
    original = sys.modules.get("edumatcher.config")

    def _restore() -> None:
        if original is not None:
            sys.modules["edumatcher.config"] = original
        else:
            sys.modules.pop("edumatcher.config", None)

    request.addfinalizer(_restore)

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
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        # _resolve_data_dir only honours EDUMATCHER_DATA_DIR when it points
        # at a directory that actually exists — that's the documented
        # host/container fallback (tier 4: ./data under cwd) kicking in when
        # it doesn't, not a bug. tmp_path itself always exists, so create
        # the target dir to test "the env var wins" rather than "the env
        # var is silently overridden because nothing created its target".
        custom_path = tmp_path / "custom_data"
        custom_path.mkdir()
        custom = str(custom_path)
        cfg = _reload_config(monkeypatch, {"EDUMATCHER_DATA_DIR": custom}, request)
        assert cfg.DATA_DIR == Path(custom).resolve()
        # All derived paths share the same root
        assert cfg.GTC_ORDERS_FILE.parent == cfg.DATA_DIR
        assert cfg.STATS_DB_FILE.parent == cfg.DATA_DIR

    def test_source_tree_default(
        self, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
    ) -> None:
        cfg = _reload_config(monkeypatch, {}, request)
        # In the test environment we ARE in the source tree — src/data is expected
        assert cfg._IN_SOURCE_TREE is True
        assert cfg.DATA_DIR.name == "data"
        assert cfg.DATA_DIR.parent.name == "src"

    def test_installed_default(
        self, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
    ) -> None:
        """Simulate an installed (site-packages) environment by patching __file__."""
        cfg_module = _reload_config(monkeypatch, {}, request)
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
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        # One data directory is one exchange instance: pointing at a different
        # data dir must relocate the config along with stats.db and log.db,
        # never leave it behind pointing at the previous instance's file.
        custom = str(tmp_path / "custom_data")
        cfg = _reload_config(monkeypatch, {"EDUMATCHER_DATA_DIR": custom}, request)

        assert cfg.ENGINE_CONFIG_FILE.parent.parent == cfg.DATA_DIR
        assert cfg.ENGINE_CONFIG_FILE.parent == cfg.REF_DATA_DIR

    def test_ignores_a_config_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        # EDUMATCHER_CONFIG is gone. Honouring it for some processes and not
        # others is the divergence this resolution exists to prevent, so a
        # leftover export in a shell profile must have no effect at all.
        data_dir = str(tmp_path / "d")
        stray = str(tmp_path / "stray.yaml")

        without = _reload_config(
            monkeypatch, {"EDUMATCHER_DATA_DIR": data_dir}, request
        ).ENGINE_CONFIG_FILE
        with_stray = _reload_config(
            monkeypatch,
            {"EDUMATCHER_DATA_DIR": data_dir, "EDUMATCHER_CONFIG": stray},
            request,
        ).ENGINE_CONFIG_FILE

        assert with_stray == without
        assert with_stray != Path(stray)

    def test_two_data_dirs_never_share_a_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        # Both candidate dirs must actually exist, or EDUMATCHER_DATA_DIR is
        # correctly ignored in favour of the ./data fallback (tier 4) — see
        # test_env_var_wins — and both reloads would resolve to the same
        # ./data, defeating the point of this test.
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        first = _reload_config(
            monkeypatch, {"EDUMATCHER_DATA_DIR": str(dir_a)}, request
        ).ENGINE_CONFIG_FILE
        second = _reload_config(
            monkeypatch, {"EDUMATCHER_DATA_DIR": str(dir_b)}, request
        ).ENGINE_CONFIG_FILE

        assert first != second
