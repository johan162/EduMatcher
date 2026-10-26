"""Check setup prerequisites without installing packages or running later checks."""

import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize(
    ("python_version", "missing_tool", "expected", "status"),
    [
        ("3.13", "", "Python 3.14 or newer is required", 1),
        ("", "", "Python 3.14 or newer is required", 1),
        ("3.14", "expect", "expect is required to continue", 1),
        ("3.14", "zstd", "zstd is required to continue", 1),
        ("3.14", "", "✅ zstd is available", 0),
        ("3.15", "", "✅ zstd is available", 0),
    ],
)
def test_release_prerequisites(
    tmp_path: Path,
    python_version: str,
    missing_tool: str,
    expected: str,
    status: int,
) -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts/verify_setup.sh"
    ).read_text()
    script = tmp_path / "verify_setup.sh"
    script.write_text(source.split("# Ensure Poetry is available.", 1)[0])
    tools = tmp_path / "bin"
    tools.mkdir()
    for name, body in {
        "uname": "echo Linux",
        "expect": "exit 0",
        "zstd": "exit 0",
    }.items():
        if name != missing_tool:
            executable = tools / name
            executable.write_text(f"#!/bin/bash\n{body}\n")
            executable.chmod(0o755)
    if python_version:
        # Mock both the version predicate and the human-readable version output.
        executable = tools / "python3"
        executable.write_text(
            "#!/bin/bash\n"
            f'if [[ "$1" == "--version" ]]; then echo "Python {python_version}"; '
            f"else exit {int(python_version == '3.13')}; fi\n"
        )
        executable.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", str(script), "--non-interactive"],
        env={**os.environ, "PATH": str(tools)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == status, result.stdout + result.stderr
    assert expected in result.stdout
