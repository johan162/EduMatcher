"""The route class every v1 router uses."""

from __future__ import annotations

from typing import Any

from fastapi.routing import APIRoute


class ContractRoute(APIRoute):
    """Serialise responses with ``exclude_unset``.

    A route's ``response_model`` declares and validates the reply; without
    this, every optional field the engine leaves out (``oco_group_id`` on an
    ordinary order, ``next`` when no transition is scheduled) would come back
    as ``null``, breaking the documented "omitted rather than null" contract.
    Set once here so no route can forget it.
    """

    def __init__(self, path: str, endpoint: Any, **kwargs: Any) -> None:
        kwargs["response_model_exclude_unset"] = True
        super().__init__(path, endpoint, **kwargs)
