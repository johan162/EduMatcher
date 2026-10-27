"""Verify release branch synchronization in isolated local repositories."""

import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize(
    "scenario", ["synced", "behind", "ahead", "diverged", "fetch-head", "dry-run"]
)
def test_main_sync_requires_remote_tip(tmp_path: Path, scenario: str) -> None:
    env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": os.devnull,
        "GIT_CONFIG_KEY_1": "commit.gpgSign",
        "GIT_CONFIG_VALUE_1": "false",
        "GIT_AUTHOR_NAME": "Release Test",
        "GIT_AUTHOR_EMAIL": "release@example.invalid",
        "GIT_COMMITTER_NAME": "Release Test",
        "GIT_COMMITTER_EMAIL": "release@example.invalid",
    }

    def git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "--initial-branch=main")
    git(remote, "commit", "--allow-empty", "-m", "release")
    repo = tmp_path / "checkout"
    git(tmp_path, "clone", str(remote), str(repo))
    git(repo, "checkout", "-b", "develop")
    git(repo, "commit", "--allow-empty", "-m", "development")
    if scenario in {"behind", "diverged"}:
        git(remote, "commit", "--allow-empty", "-m", "remote release")
    if scenario in {"ahead", "diverged"}:
        git(repo, "checkout", "main")
        git(repo, "commit", "--allow-empty", "-m", "local only")
        git(repo, "checkout", "develop")

    main_before = git(repo, "rev-parse", "main")
    develop_before = git(repo, "rev-parse", "develop")
    source = (Path(__file__).resolve().parents[1] / "scripts/mkrelease.sh").read_text()
    helpers = source.split("run_command() {", 1)[1].split(
        'if [[ "$DRY_RUN" == "true" ]]; then\n    print_warning_colored', 1
    )[0]
    sync = source.split("# 2.2:", 1)[1].split("# Squash merge develop", 1)[0]
    sync = sync[sync.index('run_command "git checkout main"') :]
    harness = tmp_path / "sync.sh"
    harness.write_text(
        "set -e\n"
        f"DRY_RUN={'true' if scenario == 'dry-run' else 'false'}\n"
        'print_sub_step() { echo "$*"; }\n'
        'print_success() { echo "$*"; }\n'
        'print_error_colored() { echo "$*" >&2; }\n'
        "run_command() {"
        + helpers
        + "\n"
        + (
            # Simulate another fetch replacing FETCH_HEAD before the merge.
            """git() {
    command git "$@" || return $?
    if [[ "$1" == "fetch" ]]; then
        command git rev-parse develop > "$(command git rev-parse --git-path FETCH_HEAD)"
    fi
}
"""
            if scenario == "fetch-head"
            else ""
        )
        + sync
        + '\necho "READY_FOR_SQUASH"\n'
    )
    result = subprocess.run(
        ["/bin/bash", str(harness)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = result.stdout + result.stderr
    if scenario in {"ahead", "diverged"}:
        assert result.returncode != 0, output
        assert "READY_FOR_SQUASH" not in output
        assert git(repo, "rev-parse", "main") == main_before
        if scenario == "ahead":
            assert "Local main does not match origin/main" in output
    else:
        assert result.returncode == 0, output
        assert "READY_FOR_SQUASH" in output
        assert git(repo, "rev-parse", "main") == git(remote, "rev-parse", "main")
    assert git(repo, "rev-parse", "develop") == develop_before
    assert git(repo, "status", "--porcelain") == ""
    if scenario == "dry-run":
        assert git(repo, "branch", "--show-current") == "develop"
        assert git(repo, "rev-parse", "main") == main_before
