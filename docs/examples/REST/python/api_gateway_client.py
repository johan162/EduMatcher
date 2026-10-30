"""Tiny reusable EduMatcher API Gateway REST client.

The module intentionally uses only the Python standard library so it can be
copied into small teaching examples without extra dependencies.

Two kinds of failure, kept apart because a client must react differently:

* ``ApiError``: the gateway answered with an error. Nothing reached the
  engine (see the REST spec's "Write outcomes and safe retries"), so the
  request may be fixed and sent again. ``code``, ``reject_code`` and
  ``field`` come from the error envelope.
* ``ApiUnreachable``: no answer at all. A write may or may not have been
  sent, so retry it only with the same ``Idempotency-Key``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    """The gateway answered with an error envelope."""

    def __init__(self, status: int, error: dict[str, Any]) -> None:
        self.status = status
        self.code = str(error.get("code", "UNKNOWN"))
        self.reject_code = error.get("reject_code")
        self.field = error.get("field")
        self.message = str(error.get("message", ""))
        super().__init__(
            f"API request failed: HTTP {status} {self.code}: {self.message}"
        )


class ApiUnreachable(RuntimeError):
    """No answer from the gateway; a write's outcome is unknown."""


class ApiGatewayClient:
    """Minimal REST client for JSON endpoints."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def get_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Issue a GET request and decode the JSON response body."""
        query = {k: v for k, v in (params or {}).items() if v is not None}
        if query:
            path = f"{path}?{urlencode(query)}"
        return self._json_request("GET", path)

    def post_json(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Issue a POST request with a JSON body and decode the response.

        Pass the same *idempotency_key* when retrying a write after a dropped
        connection: the gateway then replays the first reply instead of
        submitting the order a second time.
        """
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return self._json_request("POST", path, payload, headers)

    def patch_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Issue a PATCH request with a JSON body (an amend)."""
        return self._json_request("PATCH", path, payload)

    def delete_json(self, path: str) -> dict[str, Any]:
        """Issue a DELETE request (a cancel)."""
        return self._json_request("DELETE", path)

    def pages(
        self, path: str, key: str, params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Every item of a paginated list, following ``next_cursor``.

        *key* names the list in the reply (``trades``, ``events``, ...). The
        loop ends on ``has_more: false``; ``next_cursor`` is then ``null``.
        """
        query = dict(params or {})
        while True:
            page = self.get_json(path, query)
            yield from page.get(key, [])
            if not page.get("has_more"):
                return
            query["after"] = page["next_cursor"]

    def _json_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                **(extra_headers or {}),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                error = json.loads(raw)["error"]
            except ValueError, KeyError, TypeError:
                error = {"code": "HTTP_ERROR", "message": raw}
            raise ApiError(exc.code, error) from exc
        except (URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ApiUnreachable(
                f"Could not reach API gateway at {self.base_url}: {reason}"
            ) from exc
        return json.loads(body) if body else {}
