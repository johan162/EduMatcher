"""A reusable CALF market data client.

CALF is a read-only, credential-free market data feed: connect, subscribe to
``(channel, symbol)`` streams, and receive newline-delimited
``MSGTYPE|KEY=VALUE`` lines. The wire format is simple enough to parse in a
dozen lines, which is why almost every consumer starts by doing exactly
that -- and then rediscovers, one at a time, the handful of things that
make a feed client correct rather than merely working.

This package is those things:

* **Reconnect with backoff**, and re-subscribe afterwards. The gateway keeps
  no subscription state across connections.
* **Sequence-gap detection** per ``(channel, symbol)``, kept across
  reconnects -- which is what makes a gap visible at all.
* **Repair with ``RESUME``**, and de-duplication of what repair sends back.
  A ``RESUME`` reply carries everything past ``LASTSEQ``, duplicates
  included; getting this wrong processes trades twice or discards the
  backfill.
* **Per-symbol display precision** from ``REF=`` on the handshake, so
  prices are rendered at the instrument's own ``tick_decimals`` rather than
  an assumed two.
* **Optional cached state** -- top of book merged from ``MD`` deltas, the
  depth ladder, session phase, halt status.

Two layers, and the caller picks. Raw frames::

    from edumatcher.calf_client import CalfClient, CalfClientOptions

    client = CalfClient(CalfClientOptions(symbols=["AAPL"]))
    client.run(on_frame=lambda f: print(f.msg_type, f.fields))

Or the cached state, with frames as the trigger to read it::

    def on_frame(frame):
        book = client.state.top("AAPL")
        if book:
            print(client.reference.format_price("AAPL", book.bid))

    client.run(on_frame=on_frame, on_gap=lambda g: print("lost", g.count))

See ``docs/user-guide/920-app-calf-protocol.md`` for the normative wire
contract, and ``docs/examples/calf/`` for standalone examples that show the
protocol directly rather than through this package.
"""

from edumatcher.calf_client.client import (
    CalfClient,
    CalfClientOptions,
    CalfConnectionError,
    CalfError,
    CalfProtocolMismatch,
    FrameHandler,
    GapHandler,
)
from edumatcher.calf_client.recovery import (
    RESUMABLE_CHANNELS,
    SNAPSHOT_CHANNELS,
    Gap,
    SequenceTracker,
    has_snapshot,
    is_resumable,
)
from edumatcher.calf_client.refdata import DEFAULT_TICK_DECIMALS, ReferenceData
from edumatcher.calf_client.state import (
    DepthBook,
    DepthLevel,
    HaltStatus,
    MarketState,
    TopOfBook,
)

__all__ = [
    "DEFAULT_TICK_DECIMALS",
    "RESUMABLE_CHANNELS",
    "SNAPSHOT_CHANNELS",
    "CalfClient",
    "CalfClientOptions",
    "CalfConnectionError",
    "CalfError",
    "CalfProtocolMismatch",
    "DepthBook",
    "DepthLevel",
    "FrameHandler",
    "Gap",
    "GapHandler",
    "HaltStatus",
    "MarketState",
    "ReferenceData",
    "SequenceTracker",
    "TopOfBook",
    "has_snapshot",
    "is_resumable",
]
