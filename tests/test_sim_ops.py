"""tools/sim_ops.py (S27): the scripted operator events of a sim run."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from sim_ops import run, schedule  # noqa: E402


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def symbol_list(self) -> list[str]:
        return []

    def gateway_list(self) -> list[dict[str, Any]]:
        return []

    def symbol_halt(self, symbol: str) -> dict[str, Any]:
        self.calls.append(("halt", symbol))
        return {"accepted": True}

    def symbol_resume(self, symbol: str) -> dict[str, Any]:
        self.calls.append(("resume", symbol))
        return {"accepted": True}

    def kill_switch(self, target_gw: str, symbol: str = "") -> dict[str, Any]:
        self.calls.append(("kill", target_gw))
        return {"accepted": True}

    def kill_switch_gateway(self, target_gw: str, note: str = "") -> dict[str, Any]:
        self.calls.append(("kill_gw", target_gw))
        return {"accepted": True}

    def kill_switch_global(self, note: str = "") -> dict[str, Any]:
        self.calls.append(("kill_all",))
        return {"accepted": True}

    def halt_all(self) -> dict[str, Any]:
        self.calls.append(("halt_all",))
        return {"accepted": True}

    def resume_all(self) -> dict[str, Any]:
        self.calls.append(("resume_all",))
        return {"accepted": True}

    def reference_reload(self) -> dict[str, Any]:
        self.calls.append(("reload",))
        return {"accepted": False, "reason": "No reloadable config file"}

    def cancel_symbol(self, symbol: str) -> dict[str, Any]:
        self.calls.append(("cancel", symbol))
        raise TimeoutError("no reply")

    def force_uncross(self, symbol: str, price: float | None = None) -> dict[str, Any]:
        self.calls.append(("uncross", symbol))
        return {"accepted": False, "reason": "NOT_HALTED"}


def test_the_schedule_is_seeded_and_runs_in_order_through_refusals() -> None:
    symbols, gateways = ["AAPL", "MSFT", "TSLA", "IBM"], ["AI001", "AI002"]
    steps = schedule(symbols, gateways, seed=27)
    assert [s.what for s in steps] == [s.what for s in schedule(symbols[::-1], gateways, 27)]  # fmt: skip
    now = [0.0]
    lines: list[str] = []

    def sleep(sec: float) -> None:
        now[0] += sec

    client = _Client()
    refused = run(client, steps, 1.0, sleep=sleep, clock=lambda: now[0], out=lines.append)  # fmt: skip
    calls = client.calls
    assert [c[0] for c in calls] == ["halt", "resume", "kill", "kill_gw", "cancel", "halt", "uncross", "halt_all", "resume_all", "reload", "kill_all"]  # fmt: skip
    halted = calls[0][1]
    assert calls[1] == ("resume", halted)
    assert {calls[2][1], calls[3][1]} <= set(gateways) and calls[2][1] != calls[3][1]
    assert len({halted, calls[4][1], calls[5][1]}) == 3
    assert calls[5][1] == calls[6][1]
    # the timeout and the refused uncross; the reload's refusal is expected
    assert refused == 2
    assert now[0] == 46 * 60  # one minute's delay, the last step at +45
    assert "REFUSED TimeoutError: no reply" in lines[4]
    assert lines[-2].startswith("[+30 min] RESTART THE ENGINE")
