"""Verify npm batching in the build script without running a full build."""

import os
from pathlib import Path
import shlex
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mkbld.sh"
NPM_COMMANDS = ["install", "run typecheck", "run lint", "test"]


def _make_apps(tmp_path: Path, count: int) -> list[Path]:
    web_apps = tmp_path / "web-apps"
    web_apps.mkdir()
    (web_apps / "not-a-directory").touch()
    apps = [web_apps / f"app {index};$literal" for index in range(count)]
    for app in apps:
        app.mkdir()
    return apps


def _run_npm_section(
    tmp_path: Path,
    *,
    dry_run: bool = False,
    failed_app: Path | None = None,
    synchronize: int = 0,
) -> subprocess.CompletedProcess[str]:
    source = SCRIPT.read_text(encoding="utf-8")
    helpers = (
        "print_sub_step() {"
        + source.split("print_sub_step() {", 1)[1].split(
            "# Build all documentation", 1
        )[0]
    )
    section = (
        source.split('print_sub_step "Running npm tests for web applications"', 1)[
            1
        ].split("\nfi\n", 1)[0]
        + "\nfi\n"
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(
        r"""#!/bin/bash
set -eu
printf '%s\n' "$*" >> npm-commands.log
if [ "$PWD" = "$MKB_TEST_FAIL_APP" ] && [ "$*" = "run lint" ]; then
    exit 1
fi
if [ "$MKB_TEST_SYNCHRONIZE" -gt 0 ] && [ "$1" = "install" ]; then
    index="${PWD##*/app }"
    index="${index%%;*}"
    group_start=$((index / 3 * 3))
    group_end=$((group_start + 3))
    if [ "$group_end" -gt "$MKB_TEST_SYNCHRONIZE" ]; then
        group_end="$MKB_TEST_SYNCHRONIZE"
    fi
    for ((i = 0; i < group_start; i++)); do
        if [ ! -f "$MKB_TEST_APPS/app $i;\$literal/.npm-finished" ]; then
            echo "npm batches overlapped" >&2
            exit 1
        fi
    done
    touch .npm-started
    for _ in {1..400}; do
        all_started=true
        for ((i = group_start; i < group_end; i++)); do
            if [ ! -f "$MKB_TEST_APPS/app $i;\$literal/.npm-started" ]; then
                all_started=false
            fi
        done
        if [ "$all_started" = true ]; then
            break
        fi
        sleep 0.02
    done
    if [ "$all_started" != true ]; then
        echo "Timed out waiting for concurrent npm installs" >&2
        exit 1
    fi
elif [ "$MKB_TEST_SYNCHRONIZE" -gt 0 ] && [ "$1" = "test" ]; then
    touch .npm-finished
fi
""",
        encoding="utf-8",
    )
    npm.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "MKB_TEST_APPS": str(tmp_path / "web-apps"),
        "MKB_TEST_FAIL_APP": str(failed_app) if failed_app else "",
        "MKB_TEST_SYNCHRONIZE": str(synchronize),
    }
    script = (
        "set -euo pipefail\n"
        "CI_MODE=true\nBLUE=\nYELLOW=\nGREEN=\nRED=\nNC=\n"
        f"DRY_RUN={'true' if dry_run else 'false'}\n" + helpers + section
    )
    return subprocess.run(
        ["/bin/bash", "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize("count", range(8))
@pytest.mark.parametrize("dry_run", [False, True])
def test_npm_batches(tmp_path: Path, count: int, dry_run: bool) -> None:
    apps = _make_apps(tmp_path, count)
    result = _run_npm_section(tmp_path, dry_run=dry_run)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output

    triples, remainder = divmod(count, 3)
    if dry_run:
        lines = [
            line for line in output.splitlines() if "[DRY-RUN] Would execute" in line
        ]
        assert sum("Would execute in parallel:" in line for line in lines) == (
            triples * 3 + (2 if remainder == 2 else 0)
        )
        assert [shlex.split(line[line.index("(cd ") :])[1] for line in lines] == [
            f"web-apps/{app.name}" for app in apps
        ]
        assert all(
            line.endswith(
                "&& npm install && npm run typecheck && npm run lint && npm test)"
            )
            for line in lines
        )
        assert all(not (app / "npm-commands.log").exists() for app in apps)
    else:
        assert output.count("Running three commands in parallel") == triples
        assert output.count("Running two commands in parallel") == (remainder == 2)
        for app in apps:
            assert (app / "npm-commands.log").read_text().splitlines() == NPM_COMMANDS
            assert (
                f"npm verification and tests for web-apps/{app.name} completed"
                in output
            )


@pytest.mark.parametrize("count", [3, 5, 7, 8])
def test_npm_batches_run_concurrently_without_overlap(
    tmp_path: Path, count: int
) -> None:
    apps = _make_apps(tmp_path, count)
    result = _run_npm_section(tmp_path, synchronize=count)
    assert result.returncode == 0, result.stdout + result.stderr
    assert all((app / ".npm-started").exists() for app in apps)
    assert all((app / ".npm-finished").exists() for app in apps)


@pytest.mark.parametrize("failed_index", range(3))
def test_npm_failure_waits_for_batch_and_stops_later_apps(
    tmp_path: Path, failed_index: int
) -> None:
    apps = _make_apps(tmp_path, 4)
    result = _run_npm_section(tmp_path, failed_app=apps[failed_index])
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    for index, app in enumerate(apps[:3]):
        commands = NPM_COMMANDS[:-1] if index == failed_index else NPM_COMMANDS
        status = "failed" if index == failed_index else "completed"
        assert (app / "npm-commands.log").read_text().splitlines() == commands
        assert f"npm verification and tests for web-apps/{app.name} {status}" in output
    assert not (apps[3] / "npm-commands.log").exists()


@pytest.mark.parametrize(("count", "failed_index"), [(4, 3), (5, 3), (5, 4)])
def test_npm_failure_in_remainder(
    tmp_path: Path, count: int, failed_index: int
) -> None:
    apps = _make_apps(tmp_path, count)
    result = _run_npm_section(tmp_path, failed_app=apps[failed_index])
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    for index, app in enumerate(apps):
        commands = NPM_COMMANDS[:-1] if index == failed_index else NPM_COMMANDS
        status = "failed" if index == failed_index else "completed"
        assert (app / "npm-commands.log").read_text().splitlines() == commands
        assert f"npm verification and tests for web-apps/{app.name} {status}" in output


def test_missing_web_apps_directory_warns(tmp_path: Path) -> None:
    result = _run_npm_section(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "web-apps directory not found" in result.stdout
