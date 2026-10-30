"""Every web GUI is in every place that ships one (WP-E1).

A GUI is a directory under ``web-apps/`` with a ``Dockerfile``. Adding one
means touching the source-built and released compose files, the docker
Makefile's lists, ``edumatcher.sh``'s container lists, the GHCR workflow's
two matrices, and the release scripts -- and missing any one of them fails
only on someone else's machine. This test reads those files as text and
checks each GUI is in each, under the name that file's pattern gives it.

``config-gui`` talks to no backend: it is opt-in in the source stack
(``compose.config-gui.yaml``) and absent from the AI-trader simulation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
DOCKER = REPO / "deployment" / "docker"
CURL = REPO / "deployment" / "curl"

GUIS = sorted(p.parent.name for p in (REPO / "web-apps").glob("*/Dockerfile"))
#: Talks to no backend: not in the simulation, opt-in in the source stack.
STANDALONE = {"config-gui"}
BACKED = [g for g in GUIS if g not in STANDALONE]


def _services(path: Path) -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    services = data["services"]
    assert isinstance(services, dict)
    return services


def _make_list(name: str) -> list[str]:
    """A ``NAME := a b \\ c`` list from the docker Makefile."""
    text = (DOCKER / "Makefile").read_text(encoding="utf-8")
    match = re.search(rf"^{name} := ((?:.*\\\n)*.*)$", text, re.MULTILINE)
    assert match, name
    return match.group(1).replace("\\\n", " ").split()


def test_there_are_guis() -> None:
    assert "dash-gui" in GUIS and "log-gui" in GUIS


@pytest.mark.parametrize(
    ("path", "guis", "container"),
    [
        (DOCKER / "compose.guis.yaml", BACKED, "${{CONTAINER_NAME:-edumatcher}}-{}"),
        (
            DOCKER / "compose.config-gui.yaml",
            ["config-gui"],
            "${{CONTAINER_NAME:-edumatcher}}-{}",
        ),
        (DOCKER / "compose.ai-sim.yaml", BACKED, "edumatcher-sim-{}"),
        (CURL / "compose.yaml", GUIS, "edumatcher-{}"),
        (CURL / "compose.ai-sim.yaml", BACKED, "edumatcher-sim-{}"),
        (CURL / "compose.guis.yaml", GUIS, "edumatcher-host-{}"),
    ],
    ids=lambda v: v.name if isinstance(v, Path) else None,
)
def test_each_compose_file_runs_its_guis(
    path: Path, guis: list[str], container: str
) -> None:
    services = _services(path)
    for gui in guis:
        assert gui in services, f"{path.name} has no {gui} service"
        assert services[gui]["container_name"] == container.format(gui), gui
    if path.parent == CURL or "ai-sim" in path.name:
        for gui in guis:
            image = str(services[gui]["image"])
            assert image.endswith(f"/edumatcher-{gui}:${{EM_VERSION:-latest}}"), image


def test_the_docker_makefile_lists_every_gui() -> None:
    assert sorted(_make_list("GUI_SERVICES")) == GUIS
    assert sorted(_make_list("GUI_IMAGES")) == [f"edumatcher-{g}" for g in GUIS]


def test_edumatcher_sh_owns_every_container() -> None:
    lists = re.findall(
        r'CONTAINERS="([^"]+)"', (CURL / "edumatcher.sh").read_text(encoding="utf-8")
    )
    normal, host, sim = (set(names.split()) for names in lists)
    assert normal == {"edumatcher", *(f"edumatcher-{g}" for g in GUIS)}
    assert sim == {"edumatcher-sim", *(f"edumatcher-sim-{g}" for g in BACKED)}
    assert host == {f"edumatcher-host-{g}" for g in GUIS}


def test_every_gui_image_is_published_and_announced() -> None:
    workflow = yaml.safe_load(
        (REPO / ".github/workflows/publish-images.yml").read_text(encoding="utf-8")
    )
    build = {
        i["name"]: i["context"]
        for i in workflow["jobs"]["build"]["strategy"]["matrix"]["image"]
    }
    merge = set(workflow["jobs"]["merge"]["strategy"]["matrix"]["image"])
    announced = re.search(
        r"for img in (.*?); do",
        (REPO / "scripts/mkghrelease.sh").read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert announced
    for gui in GUIS:
        assert build[f"edumatcher-{gui}"] == f"web-apps/{gui}"
        assert f"edumatcher-{gui}" in merge
        assert f"edumatcher-{gui}" in announced.group(1).replace("\\", " ").split()


def test_mkbld_writes_every_guis_version() -> None:
    loop = re.search(
        r"for app in ([\w ]+); do",
        (REPO / "scripts/mkbld.sh").read_text(encoding="utf-8"),
    )
    assert loop
    assert sorted(f"{a}-gui" for a in loop.group(1).split()) == GUIS


@pytest.mark.parametrize(
    "path",
    sorted([*DOCKER.glob("compose*.yaml"), *CURL.glob("compose*.yaml")]),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_every_host_mount_is_relabelled_for_selinux(path: Path) -> None:
    """A host directory mounted without ``z`` is unreadable (or unwritable)
    in the container on an SELinux-enforcing host (I119)."""
    for name, service in _services(path).items():
        for volume in service.get("volumes") or []:
            parts = str(volume).split(":")
            if not parts[0].startswith("."):
                continue  # a named volume
            options = parts[2].split(",") if len(parts) > 2 else []
            assert "z" in options or "Z" in options, f"{path.name} {name}: {volume}"
