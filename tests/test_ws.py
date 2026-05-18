"""Unit tests for app.ws — the HA WebSocket client.

Wire-level coverage: confirms the auth handshake, the request shape, and
error paths against an in-process mock WebSocket. Protocol-level callers
(get_statistics, get_statistics_range) patch `call_ws` directly, so this
file is the only thing that actually exercises the JSON protocol.
"""
import asyncio
import json

import pytest

from app.ws import call_ws, HassWebSocketError


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# tests/conftest.py installs an autouse fixture that patches httpx.AsyncClient
# globally. websockets doesn't use httpx, so it doesn't matter — we just
# need to defeat the autouse get_client patch for the import-from-app.hass
# call inside ws.py (it only calls _build_ssl_context, which we monkeypatch
# anyway).
@pytest.fixture(autouse=True)
def _no_real_ssl(monkeypatch):
    """`_build_ssl_context` only matters for wss://; force None for ws://."""
    monkeypatch.setattr("app.ws._build_ssl_context", lambda: None)


class _FakeWebSocket:
    """In-memory async stand-in for a websockets connection.

    Server scripts a list of messages to send; the test inspects what the
    client sent. Mirrors the auth_required -> auth -> auth_ok -> request ->
    response flow.
    """
    def __init__(self, script: list[str]):
        self._to_send = list(script)
        self.received: list[str] = []
        self._closed = False

    async def recv(self) -> str:
        if not self._to_send:
            raise AssertionError("FakeWebSocket exhausted — client read too far")
        return self._to_send.pop(0)

    async def send(self, payload: str) -> None:
        self.received.append(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._closed = True
        return False


def _patch_connect(monkeypatch, fake: _FakeWebSocket) -> dict:
    """Replace `websockets.connect` so it yields our fake."""
    captured: dict = {}

    def fake_connect(url, ssl=None):
        captured["url"] = url
        captured["ssl"] = ssl
        return fake

    monkeypatch.setattr("app.ws.websockets.connect", fake_connect)
    return captured


async def test_call_ws_happy_path(monkeypatch):
    """auth handshake completes, request goes out with id=1, result returned."""
    fake = _FakeWebSocket(script=[
        json.dumps({"type": "auth_required"}),
        json.dumps({"type": "auth_ok"}),
        json.dumps({"id": 1, "type": "result", "success": True,
                    "result": {"sensor.x": [{"mean": 1.0}]}}),
    ])
    captured = _patch_connect(monkeypatch, fake)

    result = await call_ws(
        "recorder/statistics_during_period",
        statistic_ids=["sensor.x"], period="hour",
    )
    assert result == {"sensor.x": [{"mean": 1.0}]}

    # ws:// because HA_URL is http://localhost:8123 in conftest.
    assert captured["url"] == "ws://localhost:8123/api/websocket"

    # Auth + request both sent, in order.
    assert len(fake.received) == 2
    auth_msg = json.loads(fake.received[0])
    assert auth_msg == {"type": "auth", "access_token": "mock_token_for_tests"}
    req_msg = json.loads(fake.received[1])
    assert req_msg == {
        "id": 1,
        "type": "recorder/statistics_during_period",
        "statistic_ids": ["sensor.x"],
        "period": "hour",
    }


async def test_call_ws_auth_failure_raises(monkeypatch):
    """HA replies auth_invalid -> we surface a HassWebSocketError, not a hang."""
    fake = _FakeWebSocket(script=[
        json.dumps({"type": "auth_required"}),
        json.dumps({"type": "auth_invalid", "message": "Invalid token"}),
    ])
    _patch_connect(monkeypatch, fake)

    with pytest.raises(HassWebSocketError, match="auth"):
        await call_ws("recorder/statistics_during_period")


async def test_call_ws_request_failure_raises(monkeypatch):
    """success=False on the request response surfaces as HassWebSocketError."""
    fake = _FakeWebSocket(script=[
        json.dumps({"type": "auth_required"}),
        json.dumps({"type": "auth_ok"}),
        json.dumps({"id": 1, "type": "result", "success": False,
                    "error": {"code": "not_found", "message": "no such entity"}}),
    ])
    _patch_connect(monkeypatch, fake)

    with pytest.raises(HassWebSocketError, match="not_found|no such entity"):
        await call_ws("recorder/statistics_during_period")


async def test_call_ws_https_uses_wss(monkeypatch):
    """HA_URL=https://... -> we connect over wss://."""
    monkeypatch.setattr("app.ws.HA_URL", "https://ha.example.internal:8123")
    # wss path -> _build_ssl_context will be called; stub a sentinel so we
    # can verify it was used.
    sentinel = object()
    monkeypatch.setattr("app.ws._build_ssl_context", lambda: sentinel)

    fake = _FakeWebSocket(script=[
        json.dumps({"type": "auth_required"}),
        json.dumps({"type": "auth_ok"}),
        json.dumps({"id": 1, "type": "result", "success": True, "result": []}),
    ])
    captured = _patch_connect(monkeypatch, fake)

    await call_ws("recorder/statistics_during_period")
    assert captured["url"] == "wss://ha.example.internal:8123/api/websocket"
    assert captured["ssl"] is sentinel
