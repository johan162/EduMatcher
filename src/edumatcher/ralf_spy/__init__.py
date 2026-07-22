"""pm-ralf-spy: a RALF post-trade protocol spy/inspection client.

Connects to a running ``pm-ralf-gwy`` over TCP, subscribes to one or more
channels/symbols under a chosen role, and prints every incoming line either
as a human-readable log line or as a JSON line, for exploring/debugging what
the RALF protocol actually sends on the wire.
"""

from edumatcher.ralf_spy.client import RalfSpyClient, RalfSpyOptions

__all__ = ["RalfSpyClient", "RalfSpyOptions"]
