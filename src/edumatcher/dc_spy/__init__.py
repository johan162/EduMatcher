"""pm-dc-spy: a drop-copy feed spy/inspection client.

Connects to the matching engine's drop-copy ``PUB`` socket (default
``tcp://127.0.0.1:5557``), subscribes to fill events for one gateway or all
gateways, and prints every incoming message either as a human-readable log
line or as a JSON line, for exploring/debugging what the drop-copy feed
actually publishes.
"""

from edumatcher.dc_spy.client import DcSpyClient, DcSpyOptions

__all__ = ["DcSpyClient", "DcSpyOptions"]
