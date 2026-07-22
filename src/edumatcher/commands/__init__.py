"""
Exchange command client — high-level operator interface for an ADMIN-role gateway.

Usage
-----
    from edumatcher.commands import ExchangeCommandClient, CommandTimeoutError

    with ExchangeCommandClient("GW_ADMIN") as client:
        client.connect()
        result = client.halt_all()
        print(result["halted_symbols"])
"""

from edumatcher.commands.client import (
    CommandError,
    CommandTimeoutError,
    ExchangeCommandClient,
)

__all__ = ["ExchangeCommandClient", "CommandTimeoutError", "CommandError"]
