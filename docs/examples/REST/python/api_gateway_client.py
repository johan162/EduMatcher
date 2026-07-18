"""Tiny reusable EduMatcher API Gateway REST client.

The module intentionally uses only the Python standard library so it can be
copied into small teaching examples without extra dependencies.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ApiGatewayClient:
    """Minimal REST client for JSON endpoints."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def get_json(self, path: str) -> dict[str, Any]:
        """Issue a GET request and decode the JSON response body."""
        return self._json_request("GET", path)

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Issue a POST request with a JSON body and decode the response."""
        return self._json_request("POST", path, payload)

    def _json_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
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
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            raise RuntimeError(f"API request failed: HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(
                f"Could not reach API gateway at {self.base_url}: {exc.reason}"
            ) from exc
        return json.loads(body) if body else {}
