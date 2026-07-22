"""pm-calf-spy: a CALF market-data protocol spy/inspection client.

Connects to a running ``pm-md-gwy`` over TCP, subscribes to one or more
channels/symbols, and prints every incoming line either as a human-readable
log line or as a JSON line, for exploring/debugging what the CALF protocol
actually sends on the wire.
"""

from edumatcher.calf_spy.client import CalfSpyClient, CalfSpyOptions

__all__ = ["CalfSpyClient", "CalfSpyOptions"]
