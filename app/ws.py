"""Home Assistant WebSocket API client.

A thin async wrapper around the `websockets` library. Each call opens a
fresh connection, authenticates with the long-lived access token, sends
one request, and returns the result. Connections are not pooled — HA's
WebSocket auth flow is cheap enough (one round-trip) that pooling would
trade simplicity for marginal latency wins, and statistics/trace calls
aren't on a hot path.

TLS policy mirrors the REST client (`app.hass._build_ssl_context`): OS
native trust store via truststore, with `SSL_CERT_FILE` as the explicit
override. Use `ws://` for HTTP HA, `wss://` for HTTPS HA.
"""
from typing import Any, Dict
import json
import logging

import websockets

from app.config import HA_URL, HA_TOKEN
from app.hass import _build_ssl_context

logger = logging.getLogger(__name__)


def _ws_url() -> str:
    if HA_URL.startswith("https://"):
        return "wss://" + HA_URL[len("https://"):] + "/api/websocket"
    if HA_URL.startswith("http://"):
        return "ws://" + HA_URL[len("http://"):] + "/api/websocket"
    raise ValueError(f"HA_URL must start with http:// or https://, got: {HA_URL!r}")


class HassWebSocketError(Exception):
    """Raised when the HA WebSocket API returns an error response."""


async def call_ws(message_type: str, **payload: Any) -> Any:
    """Send a single request over the HA WebSocket API and return its result.

    Args:
        message_type: HA WS message type, e.g. ``"recorder/statistics_during_period"``.
        **payload: Additional fields merged into the request body.

    Returns:
        The ``result`` field of HA's success response — shape depends on
        the message type (dict, list, etc.).

    Raises:
        HassWebSocketError: HA replied with ``success=False`` or auth failed.
    """
    url = _ws_url()
    ssl_ctx = _build_ssl_context() if url.startswith("wss://") else None

    async with websockets.connect(url, ssl=ssl_ctx) as ws:
        # 1. Server sends auth_required first.
        auth_required = json.loads(await ws.recv())
        if auth_required.get("type") != "auth_required":
            raise HassWebSocketError(
                f"Unexpected initial WS message: {auth_required}"
            )

        # 2. Authenticate.
        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        auth_result = json.loads(await ws.recv())
        if auth_result.get("type") != "auth_ok":
            raise HassWebSocketError(f"WS authentication failed: {auth_result}")

        # 3. Send the actual request. HA requires monotonically increasing
        #    `id` per connection; since we open a fresh connection per call,
        #    `1` is always valid.
        await ws.send(json.dumps({"id": 1, "type": message_type, **payload}))
        response = json.loads(await ws.recv())

        if not response.get("success", False):
            raise HassWebSocketError(
                f"WS request {message_type!r} failed: {response.get('error', response)}"
            )
        return response.get("result")
