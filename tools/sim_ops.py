"""Scripted operator events for a sim run (sim forensics S27).

A long sim run otherwise never halts a symbol, kills a gateway's orders or
forces an uncross, so every check on those paths passes vacuously (H5).
This sends them on a fixed, seeded schedule through pm-admin's command
client, as an ADMIN gateway (OPS01 in the s300-sim profile)::

    PYTHONPATH=tools poetry run python -m sim_ops --dry-run
    PYTHONPATH=tools poetry run python -m sim_ops --start-in 10

The engine restart the forensics also want (E6, X25) is not scripted --
restarting a container is the operator's call: the schedule prints when.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class Client(Protocol):
    def symbol_list(self) -> list[str]: ...
    def gateway_list(self) -> list[dict[str, Any]]: ...
    def symbol_halt(self, symbol: str) -> dict[str, Any]: ...
    def symbol_resume(self, symbol: str) -> dict[str, Any]: ...
    def kill_switch(self, target_gw: str, symbol: str = "") -> dict[str, Any]: ...
    def cancel_symbol(self, symbol: str) -> dict[str, Any]: ...

    def force_uncross(self, symbol: str, price: float | None = None) -> dict[str, Any]: ...  # fmt: skip


@dataclass(frozen=True)
class Step:
    at_min: float
    what: str
    #: None: a reminder for the operator, not a command.
    run: Callable[[Client], dict[str, Any]] | None


def schedule(symbols: list[str], gateways: list[str], seed: int) -> list[Step]:
    """The events, minutes after the start, on symbols and a gateway the
    seed picks (three distinct symbols)."""
    rng = random.Random(seed)
    halt, cancel, uncross = rng.sample(sorted(symbols), 3)
    victim = rng.choice(sorted(gateways))
    return [
        Step(0, f"halt {halt}", lambda c: c.symbol_halt(halt)),
        Step(5, f"resume {halt}", lambda c: c.symbol_resume(halt)),
        Step(8, f"kill switch {victim} (cancel all its orders)", lambda c: c.kill_switch(victim)),  # fmt: skip
        Step(12, f"cancel every order on {cancel}", lambda c: c.cancel_symbol(cancel)),
        Step(15, f"halt {uncross}", lambda c: c.symbol_halt(uncross)),
        Step(20, f"force uncross {uncross} (reopens it)", lambda c: c.force_uncross(uncross)),  # fmt: skip
        Step(30, "RESTART THE ENGINE NOW (by hand: e.g. podman restart the engine container)", None),  # fmt: skip
    ]


def run(
    client: Client,
    steps: list[Step],
    start_in_min: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    out: Callable[[str], None] = print,
) -> int:
    """Send each step at its time; returns how many commands were refused."""
    t0 = clock() + start_in_min * 60
    refused = 0
    for step in steps:
        wait = t0 + step.at_min * 60 - clock()
        if wait > 0:
            sleep(wait)
        if step.run is None:
            out(f"[+{step.at_min:g} min] {step.what}")
            continue
        try:
            ack = step.run(client)
        except Exception as exc:  # a timeout must not end the schedule
            ack = {"accepted": False, "reason": f"{type(exc).__name__}: {exc}"}
        ok = bool(ack.get("accepted", True))
        refused += not ok
        out(f"[+{step.at_min:g} min] {step.what}: {'ok' if ok else 'REFUSED'} {ack.get('reason', '')}".rstrip())  # fmt: skip
    return refused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sim_ops", description=__doc__.split("\n\n")[0])  # fmt: skip
    parser.add_argument("--gw", default="OPS01", help="ADMIN gateway id (OPS01)")
    parser.add_argument("--seed", type=int, default=27)
    parser.add_argument("--start-in", type=float, default=0.0, metavar="MIN")
    parser.add_argument("--dry-run", action="store_true", help="print the schedule only")  # fmt: skip
    args = parser.parse_args(argv)

    from edumatcher.commands.client import ExchangeCommandClient

    with ExchangeCommandClient(args.gw) as client:
        client.connect()
        symbols = client.symbol_list()
        gateways = [str(g["id"]) for g in client.gateway_list() if str(g.get("id", "")).startswith("AI")]  # fmt: skip
        steps = schedule(symbols, gateways, args.seed)
        if args.dry_run:
            for s in steps:
                print(f"[+{args.start_in + s.at_min:g} min] {s.what}")
            return 0
        return 1 if run(client, steps, args.start_in) else 0


if __name__ == "__main__":
    sys.exit(main())
