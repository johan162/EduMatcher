"""Constructors for the application metrics a process puts in its beacon.

Two functions, not a metrics framework: a process keeps its counters however
it already does (a dict, an attribute) and turns them into samples once per
beacon interval with these. The returned records are the generated
``MetricSample`` of ``spec/messages/health.yaml``; they are validated in the
reporter's sampler thread, where an invalid one is dropped and counted rather
than allowed to stop the beacon.
"""

from __future__ import annotations

from edumatcher.models.generated.health import MetricSample


def counter(name: str, value: float, label: str = "") -> MetricSample:
    """A monotonic count since process start, e.g. ``engine.orders_in``."""
    return MetricSample(name=name, kind="COUNTER", label=label, value=float(value))


def gauge(name: str, value: float, label: str = "") -> MetricSample:
    """A level at the time of sampling, e.g. ``md.clients``."""
    return MetricSample(name=name, kind="GAUGE", label=label, value=float(value))


def gateway_stats_samples(
    stats: dict[str, int], clients_max: int
) -> list[MetricSample]:
    """ALF/BALF: every key of a gateway's ``_global_stats`` as ``gwy.<key>``.

    Exported as they are rather than re-implemented (design finding F5), so a
    key added to the dict reaches the dashboard without an edit here.
    ``connected_clients`` is a level; every other key is a running total.
    """
    out = [
        (gauge if key == "connected_clients" else counter)(f"gwy.{key}", value)
        for key, value in stats.items()
    ]
    out.append(gauge("gwy.clients_max", clients_max))
    return out


def client_gateway_samples(
    prefix: str,
    *,
    clients: int,
    msgs_out: int,
    disconnects: dict[str, int],
    clients_max: int | None = None,
    slow_clients: int | None = None,
    closing_clients: int | None = None,
) -> list[MetricSample]:
    """MD, RALF, DC: one shape for the gateways that stream lines to clients.

    ``disconnects`` is keyed by the reason string the gateway's own
    ``_disconnect`` receives -- a closed set fixed in code, so a bounded label.
    """
    out = [gauge(f"{prefix}.clients", clients), counter(f"{prefix}.msgs_out", msgs_out)]
    if clients_max is not None:
        out.append(gauge(f"{prefix}.clients_max", clients_max))
    if slow_clients is not None:
        out.append(counter(f"{prefix}.slow_clients", slow_clients))
    if closing_clients is not None:
        out.append(gauge(f"{prefix}.closing_clients", closing_clients))
    out.extend(
        counter(f"{prefix}.disconnects", n, reason)
        for reason, n in sorted(disconnects.items())
    )
    return out
