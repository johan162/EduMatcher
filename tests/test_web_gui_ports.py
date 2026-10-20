"""The web GUIs' port numbering scheme, held to in every place it is written.

Each GUI under ``web-apps/`` (a directory with a ``Dockerfile``) has one
number N, and from it three ports (web-apps/README.md):

* ``809N`` -- the container port: what its image serves and what every
  compose file publishes;
* ``819N`` -- ``make dev``'s Vite server;
* ``519N`` -- ``make dev``'s backend (bridge or server), which Vite proxies to;
  trader-gui has none.

The scheme is a convention written in a dozen files per app; this test reads
them as text and checks they agree, that no two GUIs share a number, and that
no GUI port is one the exchange itself binds (``gateway_ports.py``). The
host side of a published port is a ``<APP>_GUI_PORT`` variable wherever it
appears, and its default must be the same port everywhere.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher import gateway_ports

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web-apps"
GUIS = sorted(p.parent.name for p in WEB.glob("*/Dockerfile"))
DEPLOYMENT_COMPOSE = sorted((REPO / "deployment").glob("*/compose*.yaml"))
#: ``${NAME:-default}`` with an optional nested default, as compose writes it.
VAR = re.compile(r"\$\{(\w+):-([^}]*)\}")


def _resolve(text: str) -> str:
    """A compose value with every ``${VAR:-default}`` replaced by its default."""
    while VAR.search(text):
        text = VAR.sub(lambda m: m.group(2), text)
    return text


def _container_port(gui: str) -> int:
    """``ARG WEB_PORT`` in the GUI's Dockerfile, which every stage must agree on."""
    dockerfile = (WEB / gui / "Dockerfile").read_text(encoding="utf-8")
    ports = set(re.findall(r"^ARG WEB_PORT=(\d+)$", dockerfile, re.MULTILINE))
    assert len(ports) == 1, f"{gui}: ARG WEB_PORT {sorted(ports)}"
    assert "EXPOSE ${WEB_PORT}" in dockerfile, gui
    return int(ports.pop())


PORT = {gui: _container_port(gui) for gui in GUIS}
N = {gui: port - 8090 for gui, port in PORT.items()}


def _variable(gui: str) -> str:
    """``book-gui`` -> ``BOOK_GUI_PORT``."""
    return f"{gui.split('-')[0].upper()}_GUI_PORT"


def _services(path: Path) -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    services = data["services"]
    assert isinstance(services, dict)
    return services


def _published(service: dict[str, Any]) -> list[tuple[int, int]]:
    """``(host, container)`` for each port mapping, defaults resolved."""
    out = []
    for mapping in service.get("ports") or []:
        parts = _resolve(str(mapping)).split(":")
        out.append((int(parts[-2]), int(parts[-1])))
    return out


def test_every_gui_has_its_own_number_in_the_scheme() -> None:
    assert len(GUIS) >= 6
    assert all(0 <= n <= 9 for n in N.values()), PORT
    assert len(set(N.values())) == len(GUIS), f"two GUIs share a number: {PORT}"


@pytest.mark.parametrize("gui", GUIS)
def test_dev_ports_follow_the_container_port(gui: str) -> None:
    vite = (WEB / gui / "apps/web/vite.config.ts").read_text(encoding="utf-8")
    assert re.findall(r"^\s+port: (\d+),", vite, re.MULTILINE) == [str(8190 + N[gui])]
    backends = [
        d
        for d in ("bridge", "server")
        if (WEB / gui / "apps" / d / "src/config.ts").exists()
    ]
    proxied = {int(p) for p in re.findall(r"//127\.0\.0\.1:(\d+)", vite)}
    if not backends:
        assert not proxied, f"{gui} has no dev backend but proxies to {proxied}"
        return
    (backend,) = backends
    config = (WEB / gui / "apps" / backend / "src/config.ts").read_text(
        encoding="utf-8"
    )
    assert re.findall(r'intFromEnv\("PORT", (\d+)\)', config) == [str(5190 + N[gui])]
    assert proxied == {5190 + N[gui]}, f"Vite proxies to {proxied}"


@pytest.mark.parametrize("gui", GUIS)
def test_the_apps_own_compose_file_serves_the_container_port(gui: str) -> None:
    (service,) = _services(WEB / gui / "docker-compose.yml").values()
    assert [c for _host, c in _published(service)] == [PORT[gui]]
    assert [h for h, _c in _published(service)] == [PORT[gui]]
    assert _resolve(str(service["environment"]["PORT"])) == str(PORT[gui])


@pytest.mark.parametrize(
    "path", DEPLOYMENT_COMPOSE, ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_the_deployments_publish_each_gui_on_its_port(path: Path) -> None:
    for name, service in _services(path).items():
        if name not in PORT:
            continue
        assert _published(service) == [(PORT[name], PORT[name])], f"{path.name} {name}"
        assert str(service["environment"]["PORT"]) == str(
            PORT[name]
        ), f"{path.name} {name}"
        mapping = str(service["ports"][0])
        assert (
            f"${{{_variable(name)}:-{PORT[name]}}}" in mapping
        ), f"{path.name} {name}: {mapping}"


def test_every_gui_port_variable_has_one_default_everywhere() -> None:
    """``LOG_GUI_PORT`` is 8091 in every compose file, Makefile, script,
    ``.env.example`` and app compose file that names it."""
    files = [
        *DEPLOYMENT_COMPOSE,
        *(REPO / "deployment").glob("*/.env*.example"),
        *(REPO / "deployment").glob("*/Makefile"),
        *(REPO / "deployment").glob("*/*.sh"),
        WEB / "Makefile",
        *WEB.glob("*/docker-compose*.yml"),
        *WEB.glob("*/Makefile"),
    ]
    expected = {_variable(gui): PORT[gui] for gui in GUIS}
    seen: dict[str, set[str]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        for name, default in VAR.findall(text):
            if name.endswith("_GUI_PORT"):
                seen.setdefault(name, set()).add(
                    f"{default} ({path.relative_to(REPO)})"
                )
                assert default == str(
                    expected.get(name)
                ), f"{path.relative_to(REPO)}: ${{{name}:-{default}}}"
        for name, value in re.findall(r"^(\w+_GUI_PORT)=(\d+)$", text, re.MULTILINE):
            assert value == str(
                expected.get(name)
            ), f"{path.relative_to(REPO)}: {name}={value}"
    assert set(seen) <= set(expected), f"unknown variables: {set(seen) - set(expected)}"


def test_no_gui_port_is_one_the_exchange_binds() -> None:
    exchange = {spec.default_port for spec in gateway_ports.SINGLETON_GATEWAYS}
    exchange |= {spec.default_port for spec in gateway_ports.LOG_SERVER_EXTRA_PORTS}
    exchange |= {spec.default_port for spec in gateway_ports.MONITOR_PORTS}
    exchange |= {listener.port for listener in gateway_ports.FIXED_LISTENERS}
    exchange.add(gateway_ports.DEFAULT_API_GATEWAY_PORT)
    gui_ports = {p + offset for p in PORT.values() for offset in (0, 100)} | {
        5190 + n for n in N.values()
    }
    assert not gui_ports & exchange, sorted(gui_ports & exchange)
