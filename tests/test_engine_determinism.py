"""
Determinism replay test: identical inputs must produce identical outputs.

A matching engine's fundamental contract is that its output is a pure
function of its input sequence.  This test runs the same pre-built message
sequence through two fresh Engine instances and diffs the complete
published streams (normalizing engine-generated trade ids and timestamps,
which use process-global counters/clocks).

Expected to PASS today — it is the safety net for the review's phase-4
work (H1 arrival-sequence priority, M9/M10 clock discipline) and for any
future data-structure migration (review §7): if a change makes matching
order-dependent on anything other than the input sequence, this fails.

The repo already has tools/replay_to_engine.py + verify_matching.sh for
manual end-to-end verification; this is the in-CI, sub-second version.
"""

from __future__ import annotations

import random
from typing import Any

from edumatcher.models.order import OrderType, Side

from tests.engine_harness import (
    SYMBOL,
    all_msgs,
    connect,
    make_engine,
    order_payload,
)

# Fields that legitimately differ between runs (process-global counter /
# wall clock) and carry no matching semantics.
_VOLATILE_KEYS = {"id", "timestamp"}


def _build_scenario(seed: int = 42, n: int = 60) -> list[tuple[str, dict[str, Any]]]:
    """A fixed, seeded mixed workload; built ONCE and replayed verbatim."""
    rng = random.Random(seed)
    script: list[tuple[str, dict[str, Any]]] = []
    live_ids: list[str] = []

    for _ in range(n):
        r = rng.random()
        side = rng.choice([Side.BUY, Side.SELL])
        gw = rng.choice(["GW01", "GW02", "GW03"])
        qty = rng.randint(1, 200)
        price = round(100 + rng.randint(-20, 20) * 0.1, 2)

        if r < 0.55:
            p = order_payload(side, OrderType.LIMIT, qty, gw, price=price)
            script.append(("order.new", p))
            live_ids.append(p["id"])
        elif r < 0.65:
            p = order_payload(
                side, OrderType.ICEBERG, qty, gw, price=price,
                visible_qty=max(1, qty // 4),
            )
            script.append(("order.new", p))
            live_ids.append(p["id"])
        elif r < 0.75:
            p = order_payload(side, OrderType.IOC, qty, gw, price=price)
            script.append(("order.new", p))
        elif r < 0.85 and live_ids:
            oid = rng.choice(live_ids)
            script.append(("order.cancel", {"order_id": oid, "gateway_id": "GW01"}))
        elif live_ids:
            oid = rng.choice(live_ids)
            script.append(
                (
                    "order.amend",
                    {
                        "order_id": oid,
                        "gateway_id": "GW01",
                        "qty": rng.randint(1, 300),
                    },
                )
            )
    return script


def _run_scenario(
    monkeypatch, tmp_path, script: list[tuple[str, dict[str, Any]]], run_id: int
) -> list[tuple[str, dict[str, Any]]]:
    run_dir = tmp_path / f"run{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    engine, pub = make_engine(
        monkeypatch, run_dir, gateways=("GW01", "GW02", "GW03")
    )
    connect(engine)
    for topic, payload in script:
        if topic == "order.new":
            engine._handle_new_order(dict(payload))
        elif topic == "order.cancel":
            engine._handle_cancel(dict(payload))
        elif topic == "order.amend":
            engine._handle_amend(dict(payload))
    return all_msgs(pub)


def _normalize(
    stream: list[tuple[str, dict[str, Any]]]
) -> list[tuple[str, tuple[tuple[str, Any], ...]]]:
    out = []
    for topic, payload in stream:
        cleaned = tuple(
            sorted((k, v) for k, v in payload.items() if k not in _VOLATILE_KEYS)
        )
        out.append((topic, cleaned))
    return out


def test_identical_input_produces_identical_output_stream(
    monkeypatch, tmp_path
) -> None:
    script = _build_scenario()

    stream_a = _normalize(_run_scenario(monkeypatch, tmp_path, script, 1))
    stream_b = _normalize(_run_scenario(monkeypatch, tmp_path, script, 2))

    assert len(stream_a) == len(stream_b), (
        f"DETERMINISM: run A published {len(stream_a)} messages, "
        f"run B {len(stream_b)} — same input must produce the same output"
    )
    for i, (a, b) in enumerate(zip(stream_a, stream_b)):
        assert a == b, (
            f"DETERMINISM: streams diverge at message {i}:\n"
            f"  run A: {a}\n  run B: {b}"
        )
