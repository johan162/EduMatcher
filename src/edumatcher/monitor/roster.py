"""The expected roster: which processes the active ``emo`` profile runs.

See docs-design/EduMatcher-Operator-Dashboard.md §9.3. ``pm-opctl-cli
start <profile>`` writes ``<DATA>/emo/active-profile`` and ``stop`` removes
it; the profile itself is built in or comes from ``emo-config.yaml``, read
through the same ``load_profiles()`` the CLI uses. A process the profile runs
that has never beaconed is MISSING. Without an active profile (processes
started by hand) there is no roster and nothing is MISSING.

A profile entry maps to a beacon by the program name -- the first word of
``command`` -- plus its ``--instance`` argument, the identity
``matches_command`` uses. Never by the entry's ``name``, which is a display
label (``"market-data-gwy (md-gwy)"``).

Only programs that send a beacon are expected: a profile may run something
that does not (an interactive console), and that must not read MISSING
forever.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

import yaml

from edumatcher.emo import cli as emo_cli

log = logging.getLogger(__name__)

#: Programs that send ``health.beacon`` (Phase A, plus pm-monitor itself).
#: The participant bots join with design task B5.4.
BEACONING_PROCESSES = frozenset(
    {
        "pm-engine",
        "pm-alf-gwy",
        "pm-balf-gwy",
        "pm-md-gwy",
        "pm-ralf-gwy",
        "pm-dc-gwy",
        "pm-api-gwy",
        "pm-log-srv",
        "pm-stats",
        "pm-audit",
        "pm-clearing",
        "pm-scheduler",
        "pm-index",
        "pm-market-sim",
        "pm-monitor",
    }
)

#: ``(process, instance)``: a beacon's identity without its host.
Expected = tuple[str, str | None]


def _instance(args: Sequence[str]) -> str | None:
    for i, token in enumerate(args):
        if token == "--instance" and i + 1 < len(args):
            return args[i + 1]
        if token.startswith("--instance="):
            return token.partition("=")[2]
    return None


def expected_from_profile(entries: Iterable[dict[str, Any]]) -> frozenset[Expected]:
    """The beaconing ``(process, instance)`` pairs a profile runs."""
    expected: set[Expected] = set()
    for entry in entries:
        command = entry.get("command") or []
        if not command:
            continue
        program = os.path.basename(str(command[0]))
        if program in BEACONING_PROCESSES:
            expected.add((program, _instance([str(a) for a in command[1:]])))
    return frozenset(expected)


class ExpectedRoster(Protocol):
    """What the collector needs from a roster (tests pass a fixed one)."""

    @property
    def profile(self) -> str | None: ...

    @property
    def expected(self) -> frozenset[Expected] | None: ...

    def refresh(self) -> bool: ...


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


class Roster:
    """The active profile's expected processes, re-read when its files change."""

    def __init__(self) -> None:
        self.profile: str | None = None
        #: ``None`` without an active profile: nothing is expected.
        self.expected: frozenset[Expected] | None = None
        self._seen: object = object()  # never equal to a real signature

    def refresh(self) -> bool:
        """Re-read if the active-profile file or emo-config.yaml changed.

        Called once a second; two ``stat`` calls when nothing changed.
        Returns True when the roster was re-read.
        """
        signature = (
            _signature(emo_cli.active_profile_path()),
            _signature(emo_cli.config_path()),
        )
        if signature == self._seen:
            return False
        self._seen = signature
        self._load()
        return True

    def _load(self) -> None:
        profile = emo_cli.read_active_profile()
        if profile is None:
            if self.profile is not None:
                log.info("no active emo profile: nothing is expected")
            self.profile, self.expected = None, None
            return
        try:
            profiles = emo_cli.load_profiles()
        except (OSError, ValueError, yaml.YAMLError) as exc:  # bad emo-config.yaml
            log.warning("cannot read emo profiles, roster unchanged: %s", exc)
            return
        entries = profiles.get(profile)
        if entries is None:
            log.warning(
                "active emo profile %r is not defined: nothing is expected", profile
            )
            self.profile, self.expected = profile, None
            return
        self.profile, self.expected = profile, expected_from_profile(entries)
        log.info(
            "emo profile %r expects %d beaconing processes", profile, len(self.expected)
        )
