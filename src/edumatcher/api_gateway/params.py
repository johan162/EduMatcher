"""Path parameters shared by the routers: one description and bound each.

The bounds mirror the message specs' ``max_len`` for the field each becomes,
so an over-long id is a 400 naming the parameter rather than a failed message
build further in.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, Path

from edumatcher.api_gateway.idempotency import MAX_KEY_LENGTH

from edumatcher.api_gateway.schemas import GATEWAY_ID_MAX_LEN, SYMBOL_MAX_LEN

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=MAX_KEY_LENGTH,
        description=(
            "Makes a retry safe: a later request with the same key (per "
            "gateway, for `order_retention_sec`) is not sent again but gets the "
            "first reply, marked `Idempotent-Replayed: true`. Use a fresh key "
            "(a UUID) per logical request; the same key on a different request "
            "is `409 IDEMPOTENCY_KEY_REUSED`. Keys are lost when the gateway "
            "restarts."
        ),
    ),
]

OrderIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        description="Engine order id, as the submit reply returned it.",
    ),
]
SymbolPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=SYMBOL_MAX_LEN,
        description="Instrument, e.g. `AAPL` (case-insensitive).",
    ),
]
GatewayIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=GATEWAY_ID_MAX_LEN,
        description="Engine gateway id, e.g. `TRADER01` (case-insensitive).",
    ),
]
IndexIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=32,
        description="Exchange index id, e.g. `EDU3` (case-insensitive).",
    ),
]
OcoIdPath = Annotated[
    str, Path(min_length=1, description="The `oco_id` you submitted the pair with.")
]
ComboIdPath = Annotated[
    str, Path(min_length=1, description="The `combo_id` you submitted the combo with.")
]
