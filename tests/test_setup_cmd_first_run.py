"""pm-setup's first run is quiet about the directory it is about to create.

Importing ``edumatcher.config`` resolves the data directory and warns when
it does not exist. ``pm-setup`` imported it at the top, before creating the
directory, so the very first command of a pipx installation printed
"WARNING: data directory ... not found" (Quick Start review 2026-11). The
check runs at import, so these tests start a fresh interpreter.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _pm_setup(
    tmp_path: Path, *args: str, data_dir: Path
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "EDUMATCHER_DATA_DIR"}
    env["EDUMATCHER_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from edumatcher.setup_cmd import main; "
            "sys.argv = ['pm-setup', *sys.argv[1:]]; main()",
            *args,
        ],
        cwd=tmp_path,  # no ./data here, so the cwd fallback cannot hide it
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("args", [(), ("--show",), ("--no-config",)])
def test_first_run_prints_no_missing_directory_warning(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    data_dir = tmp_path / "fresh"

    result = _pm_setup(tmp_path, "--config", "s1-basic", *args, data_dir=data_dir)

    assert result.returncode == 0, result.stderr
    assert "WARNING" not in result.stderr
    if args != ("--show",):
        assert data_dir.is_dir()


def test_an_explicit_data_dir_is_the_one_used_and_checked(tmp_path: Path) -> None:
    """--data-dir wins over EDUMATCHER_DATA_DIR, so a missing directory
    named only in the environment is neither warned about nor created."""
    env_dir, chosen = tmp_path / "from-env", tmp_path / "chosen"

    result = _pm_setup(
        tmp_path, "--config", "s1-basic", "--data-dir", str(chosen), data_dir=env_dir
    )

    assert result.returncode == 0, result.stderr
    assert "WARNING" not in result.stderr
    assert (chosen / "ref_data" / "engine_config.json").is_file()
    assert not env_dir.exists()
