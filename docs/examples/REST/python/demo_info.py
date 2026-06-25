"""Print simple API Gateway status information to the terminal."""

from __future__ import annotations

import json
import os

from api_gateway_client import ApiGatewayClient


def main() -> None:
    base_url = os.environ.get("EDUMATCHER_API_URL", "http://127.0.0.1:8080")
    api_key = os.environ.get("EDUMATCHER_API_KEY", "key-trader-demo")
    client = ApiGatewayClient(base_url, api_key)
    for path in ("/api/v1/status", "/api/v1/symbols", "/api/v1/session"):
        print(f"\n{path}")
        print(json.dumps(client.get_json(path), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()